"""업무 로직: 주기 동기화(재고·경쟁가), 자동 가격조정, 상품 등록 페이로드 생성."""
from __future__ import annotations

import csv
import io
import logging
import re
import threading
from datetime import datetime

from product_form import product_names

log = logging.getLogger("wing")


class SyncService:
    """설정(cfg)은 app 과 같은 dict 를 공유해서, 설정 화면에서 바꾼 값이 다음 주기에 바로 적용된다."""

    def __init__(self, client, store, competitor_provider, cfg: dict):
        self.client = client
        self.store = store
        self.provider = competitor_provider
        self.cfg = cfg
        self.last_sync: str | None = None
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()
        self.event_listeners: list = []  # 가격 변동 이벤트(대시보드 알림에는 저장하지 않음) — 예: 텔레그램

    def emit(self, level: str, kind: str, message: str, **meta):
        for listener in self.event_listeners:
            listener(level, kind, message, **meta)

    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="wing-sync").start()

    def _loop(self):
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(max(5, int(self.cfg.get("sync_interval_sec") or 30)))

    def run_once(self):
        with self._run_lock:  # 백그라운드 주기와 '지금 동기화' 버튼이 겹치지 않게
            try:
                fetched = self.client.fetch_items()
                before = {i["vendor_item_id"]: i["sale_price"] for i in self.store.items()}
                # 쿠팡(또는 모의)에서 받은 목록과 DB를 일치시킨다: 모드 전환 시 다른 쪽 상품이 섞이지 않게
                self.store.replace_items(fetched)
                for it in fetched:  # 내 판매가 변동 (WING에서 직접 바꾼 경우 포함, 처음 보는 상품은 제외)
                    old = before.get(it["vendor_item_id"])
                    if old is not None and old != it["sale_price"]:
                        self.emit("info", "my_price", f"내 가격 변동: {it['name']} {old:,} → {it['sale_price']:,}원",
                                  key=it["vendor_item_id"], name=it["name"], old=old, new=it["sale_price"])
            except Exception as exc:  # 동기화 실패는 화면에 보여주고 다음 주기에 재시도
                self.last_error = str(exc)
                log.exception("sync failed")
                return
            errors = []
            for item in self.store.items():
                for step in (self.apply_soldout_rule, self._check_stock, self._check_price):
                    try:  # 한 상품의 실패가 나머지 상품 처리를 막지 않게
                        step(item)
                    except Exception as exc:
                        errors.append(f"{item['name']}: {exc}")
                        log.exception("sync step failed")
            for e in errors:
                self.store.alert("danger", "error", f"처리 실패 – {e}")
            self.last_sync = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.last_error = f"{len(errors)}건 처리 실패 (알림 참고)" if errors else None

    def delete_products(self, seller_product_ids: list[str], stop_first: bool) -> list[tuple[str, bool, str]]:
        """등록상품 단위 삭제. 판매중인 옵션은 stop_first 일 때만 먼저 판매중지한다.
        반환: [(상품명, 성공여부, 메시지)] — 동기화 도중 삭제한 상품이 다시 들어오지 않게 동기화 잠금 안에서 실행."""
        results = []
        with self._run_lock:
            items = self.store.items()
            for spid in dict.fromkeys(seller_product_ids):
                opts = [i for i in items if i["seller_product_id"] == spid]
                if not opts:
                    results.append((spid, False, "목록에 없는 상품입니다 (이미 삭제됐을 수 있음)"))
                    continue
                results.append(self._delete_one(spid, opts, stop_first))
        return results

    def _delete_one(self, spid: str, opts: list[dict], stop_first: bool) -> tuple[str, bool, str]:
        name = opts[0]["name"] if len(opts) == 1 else f"{opts[0]['name']} 외 {len(opts) - 1}개 옵션"
        if any("승인대기" in (o["status"] or "") for o in opts):
            return name, False, "승인대기 중인 상품은 쿠팡에서 삭제할 수 없습니다"
        selling = [o for o in opts if o["on_sale"]]
        if selling and not stop_first:
            return name, False, f"판매중인 옵션 {len(selling)}개가 있어 삭제할 수 없습니다 (먼저 판매중지 필요)"
        stopped = []
        try:
            for o in selling:
                self.client.stop_sale(o["vendor_item_id"])
                self.store.set_item_field(o["vendor_item_id"], "on_sale", 0)
                self.store.update_rule(o["vendor_item_id"], auto_stopped=0)
                stopped.append(o)
            self.client.delete_product(spid)
        except Exception as exc:
            note = f" (옵션 {len(stopped)}개는 판매중지된 상태로 남음)" if stopped else ""
            self.store.alert("danger", "delete", f"상품 삭제 실패: {name} – {exc}{note}")
            return name, False, f"{exc}{note}"
        self.store.delete_items([o["vendor_item_id"] for o in opts])
        self.store.alert("info", "delete", f"상품 삭제: {name} (등록상품ID {spid})")
        return name, True, "삭제 완료"

    @property
    def competitor_is_mock_on_live(self) -> bool:
        """경쟁가가 모의 데이터인데 실제 상점에 연결된 상태 — 이때 가격을 자동으로 바꾸면 안 된다."""
        return getattr(self.provider, "name", "") == "mock" and self.client.mode == "live"

    def apply_soldout_rule(self, item: dict):
        """재고가 기준 미만이면 판매중지, 자동으로 멈춘 상품이 기준 이상으로 입고되면 판매재개."""
        if not self.cfg.get("auto_soldout", True):
            return
        threshold = int(self.cfg.get("soldout_threshold", 5))
        vid = item["vendor_item_id"]
        if item["on_sale"] and item["stock"] < threshold:
            self.client.stop_sale(vid)
            self.store.set_item_field(vid, "on_sale", 0)
            self.store.update_rule(vid, auto_stopped=1)
            item.update(on_sale=0, auto_stopped=1)
            self.store.alert("danger", "soldout",
                             f"자동 품절 처리(재고 {item['stock']}개 < {threshold}개): {item['name']}")
        elif item["auto_stopped"] and not item["on_sale"] and item["stock"] >= threshold:
            self.client.resume_sale(vid)
            self.store.set_item_field(vid, "on_sale", 1)
            self.store.update_rule(vid, auto_stopped=0)
            item.update(on_sale=1, auto_stopped=0)
            self.store.alert("info", "soldout", f"재입고 자동 판매재개(재고 {item['stock']}개): {item['name']}")

    def _check_stock(self, item: dict):
        if not item["on_sale"]:
            return  # 판매중지 상품은 위 자동품절 알림으로 충분
        if item["stock"] <= (item["low_stock"] or 0):
            self.store.alert("warn", "stock", f"재고 부족({item['stock']}개): {item['name']}")

    def _check_price(self, item: dict):
        rows = self.provider.fetch(item)
        if not rows:
            return
        prev = {r["seller"]: r["price"] for r in self.store.latest_competitors(item["vendor_item_id"])}
        self.store.add_competitor_prices(item["vendor_item_id"], item["sale_price"], rows)
        if self.competitor_is_mock_on_live:
            return  # 화면 표시용으로만 기록. 가짜 경쟁가로 실제 가격을 바꾸거나 알림을 내지 않는다
        lowest = min(r["price"] for r in rows)
        self._emit_competitor_changes(item, prev, rows, lowest)
        if lowest >= item["sale_price"]:
            return
        if item["auto_reprice"]:
            self._reprice(item, lowest)
        else:
            self.store.alert("warn", "price",
                             f"최저가 밀림: {item['name']} 내 가격 {item['sale_price']:,}원 > 경쟁 최저 {lowest:,}원")

    def _emit_competitor_changes(self, item: dict, prev: dict, rows: list[dict], lowest: int):
        if not prev:
            return  # 첫 수집은 비교 대상이 없음
        vid, name = item["vendor_item_id"], item["name"]
        changes = {r["seller"]: (prev.get(r["seller"]), r["price"]) for r in rows if prev.get(r["seller"]) != r["price"]}
        if changes:
            self.emit("info", "competitor", f"경쟁가 변동: {name}", key=vid, name=name, changes=changes)
        prev_low = min(prev.values())
        if prev_low != lowest:
            level = "warn" if lowest < item["sale_price"] else "info"
            self.emit(level, "lowest", f"최저가 변동: {name} {prev_low:,} → {lowest:,}원", key=vid, name=name,
                      old=prev_low, new=lowest, mine=item["sale_price"])

    def _reprice(self, item: dict, lowest: int):
        target = lowest - (item["undercut"] or 0)
        floor = item["min_price"] or 0
        if target < floor:
            self.store.alert("danger", "reprice",
                             f"자동조정 중단(하한가 {floor:,}원 미만): {item['name']} 경쟁 최저 {lowest:,}원")
            return
        self.client.update_price(item["vendor_item_id"], target)
        self.store.set_item_field(item["vendor_item_id"], "sale_price", target)
        self.store.alert("info", "reprice", f"자동 가격조정: {item['name']} {item['sale_price']:,} → {target:,}원")


# ---------------- 상품 등록 (CSV) ----------------
# 요청 본문·검증은 product_form.py
CSV_COLUMNS = ["display_name", "name", "category_code", "brand", "item_name", "original_price", "sale_price",
               "stock", "image_url", "delivery_charge", "search_tags", "description_html", "attrs_text"]


def parse_csv(text: str) -> list[dict]:
    """영문 키 또는 템플릿의 한글 머리글 모두 읽는다. '[예시]'로 시작하는 행은 건너뛴다."""
    rows = []
    for raw in csv.DictReader(io.StringIO(text.lstrip("\ufeff"))):
        row = {HEADER_TO_KEY.get((k or "").strip(), (k or "").strip()): (v or "").strip() for k, v in raw.items()}
        if not any(row.values()) or product_names(row)[0].startswith(EXAMPLE_PREFIX):
            continue
        rows.append(row)
    return rows


# CSV 템플릿: 엑셀에서 바로 열리도록 UTF-8 BOM + 한글 머리글
CSV_HEADERS = {
    "display_name": "노출상품명*", "name": "등록상품명(판매자관리용)", "category_code": "카테고리코드*", "brand": "브랜드", "item_name": "옵션명",
    "original_price": "정상가", "sale_price": "판매가*", "stock": "재고", "image_url": "대표이미지URL",
    "delivery_charge": "배송비", "search_tags": "검색태그(쉼표구분)", "description_html": "상세설명HTML",
    "attrs_text": "구매옵션(예: 색상=블랙;수량=1개)",
}
HEADER_TO_KEY = {v: k for k, v in CSV_HEADERS.items()} | {"상품명*": "display_name", "상품명": "display_name"}
EXAMPLE_PREFIX = "[예시]"
_EXAMPLES = [  # 카테고리 코드는 쿠팡 개발자 문서 예시의 실제 코드 (여성의류 > 티셔츠 > 반소매 / 맨투맨)
    {"display_name": f"{EXAMPLE_PREFIX} 여성 오버핏 반팔 티셔츠", "name": "TS-001 반팔티 화이트",
     "category_code": "79382", "brand": "데일리핏", "item_name": "화이트 / FREE", "original_price": "19900",
     "sale_price": "12900", "stock": "50", "image_url": "https://example.com/tshirt.jpg", "delivery_charge": "0",
     "search_tags": "반팔티,오버핏", "description_html": "<p>부드러운 면 100% 반팔 티셔츠</p>",
     "attrs_text": "색상=화이트;사이즈=FREE"},
    {"display_name": f"{EXAMPLE_PREFIX} 여성 기모 맨투맨", "name": "MT-002 기모맨투맨 그레이",
     "category_code": "69186", "brand": "데일리핏", "item_name": "그레이 / M", "original_price": "35000",
     "sale_price": "24900", "stock": "30", "image_url": "https://example.com/mtm.jpg", "delivery_charge": "3000",
     "search_tags": "맨투맨,기모", "description_html": "<p>따뜻한 기모 맨투맨</p>",
     "attrs_text": "색상=그레이;사이즈=M"},
]


def csv_template() -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([CSV_HEADERS[k] for k in CSV_COLUMNS])
    for ex in _EXAMPLES:
        w.writerow([ex[k] for k in CSV_COLUMNS])
    return "\ufeff" + buf.getvalue()


# ---------------- 상세설명 HTML / 이미지 ----------------
_DANGEROUS = [
    (re.compile(r"<\s*(script|style|iframe|object|embed|form)\b.*?<\s*/\s*\1\s*>", re.I | re.S), ""),
    (re.compile(r"<\s*/?\s*(script|style|iframe|object|embed|form|meta|link)\b[^>]*>", re.I), ""),
    (re.compile(r"\s+on\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", re.I), ""),
    (re.compile(r"(href|src)\s*=\s*([\"']?)\s*javascript:[^\"'>\s]*\2", re.I), r'\1="#"'),
]


def clean_html(html: str) -> str:
    """에디터 HTML에서 스크립트·이벤트 속성 등 실행 가능한 부분을 제거 (쿠팡 상세페이지에도 허용되지 않음)."""
    for pat, rep in _DANGEROUS:
        html = pat.sub(rep, html or "")
    return html.strip()


_IMAGE_MAGIC = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png", b"GIF87a": "gif", b"GIF89a": "gif"}


def detect_image(head: bytes) -> str | None:
    """확장자 대신 파일 앞부분으로 실제 이미지 형식을 판별한다."""
    for magic, ext in _IMAGE_MAGIC.items():
        if head.startswith(magic):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


DOC_MAX_MB = 5
_DOC_MAGIC = {b"%PDF": ("pdf",), b"PK\x03\x04": ("docx",), b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": ("doc", "hwp")}


def detect_document(head: bytes, filename: str) -> str | None:
    """구비서류 파일 형식. DOC/HWP 는 같은 OLE 형식이라 확장자로 구분한다."""
    suffix = (filename or "").rsplit(".", 1)[-1].lower()
    for magic, exts in _DOC_MAGIC.items():
        if head.startswith(magic):
            return suffix if suffix in exts else exts[0]
    img = detect_image(head)
    if img in ("jpg", "png"):
        return img
    if suffix == "txt" and b"\x00" not in head:
        return "txt"
    return None
