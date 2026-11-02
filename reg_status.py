"""등록 이력의 쿠팡 심사 상태: '상품 상태변경이력 조회' API로 승인·반려 상태와 반려 사유를 읽어 온다.

API: GET /v2/providers/seller_api/apis/api/v1/marketplace/seller-products/{sellerProductId}/histories
응답 data[]: status(심사중·임시저장·승인대기중·승인완료·부분승인완료·승인반려·상품삭제) · comment(상태변경내용) · createdBy · createdAt
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time

log = logging.getLogger("wing")

FINAL = {"승인완료", "상품삭제"}               # 더 바뀌지 않는 상태 → 자동 새로고침 대상에서 뺀다
REJECTED = re.compile(r"반려|거절|거부")
REFRESH_SEC = 600                              # 자동 새로고침 주기 (10분)
MAX_PER_ROUND = 30                             # 한 번에 확인하는 이력 수 (API 호출 제한 고려)
SPID_IN_RESULT = re.compile(r"sellerProductId=(\d+)")


def seller_product_id(row: dict) -> str | None:
    if row.get("seller_product_id"):
        return str(row["seller_product_id"])
    m = SPID_IN_RESULT.search(row.get("result") or "")   # 이전 버전 이력: 결과 문구에서 읽는다
    return m.group(1) if m and row.get("ok") else None


def row_mode(row: dict) -> str:
    return row.get("mode") or ("mock" if (row.get("result") or "").startswith("[모의]") else "live")


def normalize(history: list[dict]) -> list[dict]:
    """실제 API는 문서(status)와 달리 statusName 으로 준다 (2026-11 확인) → 둘 다 받아 status 로 맞춘다."""
    return [{**h, "status": h.get("status") or h.get("statusName") or ""} for h in history]


def summarize(history: list[dict]) -> dict:
    """최신 상태와, 반려된 적이 있으면 가장 최근 반려 사유."""
    rows = sorted(normalize(history), key=lambda h: h.get("createdAt") or "", reverse=True)
    if not rows:
        return {"status": "", "comment": "", "at": "", "reason": ""}
    latest = rows[0]
    reason = ""
    if REJECTED.search(latest.get("status") or ""):
        # 반려 사유는 반려 줄의 comment. 비어 있으면 같은 시각 근처의 다른 줄(시스템 메모)에서 찾는다
        reason = latest.get("comment") or next((h.get("comment") for h in rows[1:3] if h.get("comment")), "")
    return {"status": latest.get("status") or "", "comment": latest.get("comment") or "",
            "at": (latest.get("createdAt") or "").replace("T", " "), "reason": reason}


class StatusChecker:
    def __init__(self, store, client_fn, on_rejected=None):
        self.store = store
        self.client_fn = client_fn          # 설정에서 키를 바꾸면 클라이언트가 바뀌므로 매번 꺼내 쓴다
        self.on_rejected = on_rejected      # fn(name, spid, reason) — 대시보드 알림 등
        self.last_run: str | None = None
        self._lock = threading.Lock()

    def targets(self, ids: list[int] | None = None, include_final: bool = False) -> list[dict]:
        mode = self.client_fn().mode
        out = []
        for row in self.store.registrations_for_status():
            if ids is not None and row["id"] not in ids:
                continue
            if not seller_product_id(row) or row_mode(row) != mode:
                continue                    # 모의 이력을 실제 쿠팡에 묻지 않는다 (반대도 마찬가지)
            if not include_final and row.get("cp_status") in FINAL:
                continue
            out.append(row)
        return out[:MAX_PER_ROUND]

    def refresh(self, ids: list[int] | None = None, include_final: bool = False) -> dict:
        """결과: {"checked": n, "rejected": n, "errors": n}"""
        if not self._lock.acquire(blocking=False):
            return {"checked": 0, "rejected": 0, "errors": 0, "busy": True}
        try:
            client = self.client_fn()
            done = {"checked": 0, "rejected": 0, "errors": 0}
            for row in self.targets(ids, include_final):
                spid = seller_product_id(row)
                try:
                    history = client.get_status_history(spid)
                except Exception as exc:  # 한 건 실패가 나머지를 막지 않게 (네트워크·삭제된 상품 등)
                    self.store.set_registration_status(row["id"], spid=spid, error=str(exc)[:300])
                    done["errors"] += 1
                    continue
                s = summarize(history)
                was = row.get("cp_status")
                self.store.set_registration_status(row["id"], spid=spid, status=s["status"], comment=s["comment"],
                                                   at=s["at"], reason=s["reason"],
                                                   history=json.dumps(normalize(history), ensure_ascii=False))
                done["checked"] += 1
                if s["reason"] and was != s["status"]:
                    done["rejected"] += 1
                    if self.on_rejected:
                        self.on_rejected(row["name"], spid, s["reason"])
            self.last_run = time.strftime("%Y-%m-%d %H:%M:%S")
            return done
        finally:
            self._lock.release()

    def start(self):
        def loop():
            time.sleep(30)                  # 켠 직후 한 번, 그 뒤 10분마다
            while True:
                try:
                    self.refresh()
                except Exception:
                    log.exception("등록 상태 확인 실패")
                time.sleep(REFRESH_SEC)
        threading.Thread(target=loop, daemon=True, name="reg-status").start()
