"""실시간 검색어: 인기 검색어 순위(1~10위) + 내 상품의 연관검색어. 출처는 구글 · 네이버 · 다음 · 쿠팡.

공급자 하나가 두 가지를 낸다 (출처 id 는 SOURCES 의 키):

    trending(source) -> [{"rank", "keyword", "change": up|down|new|same, "delta", "note"}, …]  (최대 10개)
    related(name, source) -> ["연관검색어", …]                                                (상품 이름 하나에 대해)

실패는 SourceError(화면에 그대로 보일 한국어 문장)로 알린다. 그 출처에 기능 자체가 없으면 SourceUnavailable.

출처별로 실제로 되는 것 (2026-11-10, 서버에서 직접 호출해 확인):
  구글   순위: 구글 트렌드(한국) 일간 인기 검색어 10개 · 연관검색어: 구글 자동완성
  네이버  순위: 없음(네이버는 실시간 검색어 서비스를 종료) · 연관검색어: 네이버 자동완성
  다음   순위: 없음(다음도 종료)                        · 연관검색어: 다음 자동완성(모바일)
  쿠팡   순위: 공개 API 없음                            · 연관검색어: 자동완성 주소를 시도하지만 서버에서는 접속 거부(403)였다.
         응답 모양은 확인하지 못해서 관대하게 해석한다 — 집·사무실 PC 에서 처음 열렸을 때 모양이 다르면 고쳐야 한다.
네이버·다음·구글 자동완성은 공식 API 가 아니라 각 사이트가 검색창에 쓰는 공개 주소라 예고 없이 바뀔 수 있다.
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

TOP_N = 10
RELATED_N = 8
DEFAULT_SOURCE = "google"
# 출처 id -> (이름, 검색 결과 주소). 탭 순서 = 이 순서 (순위가 실제로 나오는 구글이 맨 앞)
SOURCES = {
    "google": ("구글", "https://www.google.com/search?q="),
    "naver": ("네이버", "https://search.naver.com/search.naver?query="),
    "daum": ("다음", "https://search.daum.net/search?q="),
    "coupang": ("쿠팡", "https://www.coupang.com/np/search?q="),
}
NO_TRENDING = {
    "naver": "네이버는 실시간 검색어 서비스를 종료했습니다. 연관검색어(자동완성)는 오른쪽에서 확인할 수 있습니다.",
    "daum": "다음은 실시간 검색어 서비스를 종료했습니다. 연관검색어(자동완성)는 오른쪽에서 확인할 수 있습니다.",
    "coupang": "쿠팡에는 인기 검색어를 가져올 수 있는 공개 API가 없습니다. 연관검색어(자동완성)만 시도합니다.",
}
TREND_NOTE = {
    "google": "구글 트렌드(한국)의 일간 인기 검색어이며 쇼핑에 한정되지 않습니다. 변동은 이 프로그램이 앞서 가져온 순위와 비교한 값입니다.",
}
USER_AGENT = "WING-Manager (+https://github.com/angelcom11/cupang-agent)"  # 브라우저인 척하지 않는다
_STOP = re.compile(r"^(\d+(ml|l|m|cm|mm|g|kg|p|개|종|매|입|인용)?|화이트|블랙|그레이|핑크|블루|용)$", re.I)


class SourceError(RuntimeError):
    """출처에서 가져오지 못했다. 메시지는 화면에 그대로 보이는 문장."""


class SourceBlocked(SourceError):
    """출처가 이 서버의 접속을 거부했다 (401·403·429). 출처 전체를 잠시 쉰다 — 일시적인 시간 초과와 달리 상품마다 두드려도 소용없다."""


class SourceUnavailable(SourceError):
    """그 출처에는 이 기능이 아예 없다 (재시도해도 소용없음)."""


def search_url(keyword: str, source: str = DEFAULT_SOURCE) -> str:
    """검색어 → 그 출처의 검색 결과 주소 (새 탭으로 여는 링크용)."""
    return SOURCES.get(source, SOURCES[DEFAULT_SOURCE])[1] + quote(keyword)


def base_keyword(name: str) -> str:
    """상품 이름에서 검색창에 칠 낱말 (색·용량·수량은 빼고 마지막 두 낱말). 외부로 나가는 건 이것뿐이다."""
    words = [w for w in re.split(r"[\s/,()\[\]]+", name or "") if w and not _STOP.match(w)]
    return " ".join(words[-2:]) if words else (name or "").strip()


def _same(a: str, b: str) -> bool:
    return a.replace(" ", "").lower() == b.replace(" ", "").lower()


def _strings_under(obj, keys=("keyword", "text", "name", "title", "word", "suggest")) -> list[str]:
    """응답 모양을 모를 때(쿠팡): 키가 keyword·text 등인 문자열과, list·items 같은 목록 안의 문자열을 모은다."""
    out: list[str] = []

    def walk(o, in_list=False):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, str) and k in keys:
                    out.append(v)
                else:
                    walk(v, k in ("list", "items", "keywords", "suggestions", "suggest", "result", "results"))
        elif isinstance(o, list):
            for x in o:
                if isinstance(x, str) and in_list:
                    out.append(x)
                else:
                    walk(x)
    walk(obj)
    return out


class LiveKeywordProvider:
    """실제 출처에 물어본다. 결과는 캐시한다(순위 5분 · 연관검색어 30분 · 실패 2분) — 화면을 열어 둬도 자주 묻지 않는다."""

    name = "live"

    def __init__(self, get=None, ttl_trending: int = 300, ttl_related: int = 1800, ttl_error: int = 120):
        self._get = get or requests.get
        self.ttl_trending, self.ttl_related, self.ttl_error = ttl_trending, ttl_related, ttl_error
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._down: dict[str, tuple[float, SourceError]] = {}   # 출처 전체가 막혔을 때 (상품마다 다시 두드리지 않는다)
        self._prev: dict[str, dict[str, int]] = {}              # 출처별 직전 순위 (변동 계산용)

    def query(self, name: str) -> str:
        return base_keyword(name)

    # ---- 공통 ----
    def _http(self, url: str, **params) -> bytes:
        try:
            r = self._get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9"},
                          timeout=(3, 5))
        except requests.RequestException as exc:
            raise SourceError(f"연결하지 못했습니다 ({type(exc).__name__})") from exc
        if r.status_code in (401, 403, 429):
            raise SourceBlocked(f"접속이 거부되었습니다 (HTTP {r.status_code}). 이 서버의 자동 접속을 막았을 수 있습니다.")
        if r.status_code != 200:
            raise SourceError(f"응답 오류 (HTTP {r.status_code})")
        return r.content

    def _cached(self, key, ttl: int, fetch):
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
        if hit and now - hit[0] < (self.ttl_error if hit[2] else ttl):
            if hit[2]:
                raise hit[1]
            return hit[1]
        try:
            value = fetch()
        except SourceError as exc:
            with self._lock:
                self._cache[key] = (now, exc, True)
            raise
        with self._lock:
            self._cache[key] = (now, value, False)
        return value

    # ---- 연관검색어 (자동완성) ----
    def related(self, name: str, source: str) -> list[str]:
        q = base_keyword(name)
        if not q:
            return []
        if source not in SOURCES:
            raise SourceError("알 수 없는 출처입니다")
        down = self._down.get(source)
        if down and time.time() - down[0] < self.ttl_error:
            raise down[1]
        words = self._cached(("rel", source, q), self.ttl_related, lambda: self._fetch_related(source, q))
        return [w for w in words if not _same(w, q)][:RELATED_N]

    def _fetch_related(self, source: str, q: str) -> list[str]:
        try:
            if source == "naver":
                data = json.loads(self._http(
                    "https://ac.search.naver.com/nx/ac", q=q, con=1, frm="nv", ans=2, r_format="json", r_enc="UTF-8",
                    r_unicode=0, t_koreng=1, run=2, rev=4, q_enc="UTF-8", st=100).decode("utf-8"))
                words = [str(row[0]) for row in (data.get("items") or [[]])[0]]
            elif source == "daum":
                data = json.loads(self._http("https://suggest.search.daum.net/sushi/mobile/get", q=q).decode("utf-8"))
                words = [str(w) for w in data["subkeys"]]
            elif source == "google":
                data = json.loads(self._http("https://suggestqueries.google.com/complete/search",
                                             client="firefox", hl="ko", q=q).decode("utf-8"))
                words = [str(w) for w in data[1]]
            else:  # coupang
                data = json.loads(self._http("https://www.coupang.com/np/search/autoComplete", keyword=q).decode("utf-8"))
                words = _strings_under(data)
                if not words:
                    raise SourceError("쿠팡 응답에서 검색어를 찾지 못했습니다 (응답 모양이 다를 수 있습니다)")
            return [w.strip() for w in words if w.strip()]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            raise SourceError(f"응답을 해석하지 못했습니다 ({type(exc).__name__})") from exc
        except SourceBlocked as exc:
            self._down[source] = (time.time(), exc)
            raise

    # ---- 인기 검색어 순위 ----
    def trending(self, source: str) -> list[dict]:
        if source in NO_TRENDING:
            raise SourceUnavailable(NO_TRENDING[source])
        if source != "google":
            raise SourceError("알 수 없는 출처입니다")
        return self._cached(("trend", source), self.ttl_trending, lambda: self._fetch_google_trending(source))

    def _fetch_google_trending(self, source: str) -> list[dict]:
        content = self._http("https://trends.google.com/trending/rss", geo="KR")
        if b"<!DOCTYPE" in content or b"<!ENTITY" in content:   # 외부에서 온 XML: 엔티티 확장 공격 차단
            raise SourceError("응답 형식이 올바르지 않습니다")
        try:
            root = ET.fromstring(content)
            ns = {"ht": "https://trends.google.com/trending/rss"}
            found = [((it.findtext("title") or "").strip(), (it.findtext("ht:approx_traffic", namespaces=ns) or "").strip())
                     for it in root.iter("item")]
        except ET.ParseError as exc:
            raise SourceError("응답을 해석하지 못했습니다 (XML)") from exc
        found = [f for f in found if f[0]][:TOP_N]
        if not found:
            raise SourceError("인기 검색어가 비어 있습니다")
        prev = self._prev.get(source)
        rows = []
        for i, (kw, traffic) in enumerate(found):
            rank, before = i + 1, (prev or {}).get(kw)
            change = "same" if prev is None else "new" if before is None else "up" if before > rank else "down" if before < rank else "same"
            rows.append({"rank": rank, "keyword": kw, "change": change, "delta": abs(before - rank) if before else 0,
                         "note": f"검색 {traffic}" if traffic else ""})
        self._prev[source] = {r["keyword"]: r["rank"] for r in rows}
        return rows


# 모의 데이터 (설정 keyword_provider="mock" 또는 환경변수 WING_KEYWORDS=mock): 인터넷 없이 화면을 보거나 테스트할 때
_POOL = ["무선 이어폰", "텀블러", "전기장판", "핫팩", "가습기", "고속충전 케이블", "캠핑 랜턴", "노트북 거치대", "세차타올",
         "주방 조리도구", "미니 선풍기", "보조배터리", "수면양말", "크리스마스 트리", "귤 5kg", "생수 2L", "물티슈"]
_SUFFIXES = ["추천", "가성비", "세트", "대용량", "선물", "인기", "1+1", "특가"]


class MockKeywordProvider:
    """모의 순위(1분마다 조금씩 변함)와 연관검색어. 출처와 상관없이 같은 가짜 데이터."""

    name = "mock"
    step_sec = 60

    def query(self, name: str) -> str:
        return base_keyword(name)

    def _order(self, tick: int) -> list[str]:
        rnd = random.Random(tick)
        return sorted(_POOL, key=lambda k: _POOL.index(k) + rnd.uniform(-3.5, 3.5))

    def trending(self, source: str, now: float | None = None) -> list[dict]:
        tick = int((time.time() if now is None else now) // self.step_sec)
        prev = {k: i + 1 for i, k in enumerate(self._order(tick - 1)[:TOP_N])}
        out = []
        for i, kw in enumerate(self._order(tick)[:TOP_N]):
            rank, before = i + 1, prev.get(kw)
            change = "new" if before is None else "up" if before > rank else "down" if before < rank else "same"
            out.append({"rank": rank, "keyword": kw, "change": change, "delta": abs(before - rank) if before else 0, "note": ""})
        return out

    def related(self, name: str, source: str) -> list[str]:
        base = base_keyword(name)
        return [f"{base} {s}" for s in _SUFFIXES][:RELATED_N] if base else []


def trending_rows(provider, source: str) -> list[dict]:
    """1위부터 10위까지(순위가 빠지거나 뒤섞여 와도 1…10 순서로) + 그 출처의 검색 주소."""
    rows = sorted(provider.trending(source), key=lambda r: int(r.get("rank") or 0))[:TOP_N]
    return [{"rank": i + 1, "keyword": str(r["keyword"]), "change": r.get("change") or "same", "delta": int(r.get("delta") or 0),
             "note": str(r.get("note") or ""), "url": search_url(str(r["keyword"]), source)} for i, r in enumerate(rows)]


def product_rows(provider, items: list[dict], source: str, limit: int = 50) -> tuple[list[dict], str | None]:
    """내 상품(이름이 같은 옵션은 한 번만)마다 그 출처의 연관검색어를 붙인다. 출처에 따라 병렬로 묻는다.
    반환: (줄 목록, 모든 상품이 같은 이유로 실패했을 때의 오류 문장). 한 상품이 실패해도 나머지는 그대로."""
    uniq, seen = [], set()
    for it in items:
        name = (it.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            uniq.append(it)
        if len(uniq) >= limit:
            break

    def one(it):
        name = it["name"].strip()
        try:
            words, err = [str(w).strip() for w in provider.related(name, source) if str(w).strip()][:RELATED_N], None
        except SourceError as exc:
            words, err = [], str(exc)
        except Exception as exc:  # noqa: BLE001 — 바깥 출처 하나가 어떻게 실패해도 화면은 떠야 한다
            words, err = [], f"가져오지 못했습니다 ({type(exc).__name__})"
        return {"name": name, "query": provider.query(name), "on_sale": bool(it.get("on_sale")),
                "featured": bool(it.get("featured")), "error": err,
                "keywords": [{"keyword": w, "url": search_url(w, source)} for w in words]}

    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(one, uniq))
    errors = {r["error"] for r in rows if r["error"]}
    return rows, (errors.pop() if rows and len(errors) == 1 and all(r["error"] for r in rows) else None)
