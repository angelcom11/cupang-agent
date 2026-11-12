"""내 상품의 연관검색어. 출처는 구글 · 네이버 · 다음 · 쿠팡.

공급자는 한 가지를 낸다:

    related(name, source) -> ["연관검색어", …]     (상품 이름 하나에 대해, 출처 id 는 SOURCES 의 키)

실패는 SourceError(화면에 그대로 보일 한국어 문장)로 알린다.

출처별 연관검색어 (2026-11-10, 서버에서 직접 호출해 확인):
  구글   구글 자동완성
  네이버  네이버 자동완성
  다음   다음 자동완성(모바일)
  쿠팡   자동완성 주소를 시도하지만 서버에서는 접속 거부(403)였다.
         응답 모양은 확인하지 못해서 관대하게 해석한다 — 집·사무실 PC 에서 처음 열렸을 때 모양이 다르면 고쳐야 한다.
네이버·다음·구글 자동완성은 공식 API 가 아니라 각 사이트가 검색창에 쓰는 공개 주소라 예고 없이 바뀔 수 있다.
인기 검색어 순위는 보여 주지 않는다 (네이버·다음은 실시간 검색어 서비스를 종료했고, 쿠팡은 공개 API 가 없다).
"""
from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

RELATED_N = 8
MAX_TAGS = 20          # 쿠팡 상품등록 검색어(searchTags) 상한
DEFAULT_SOURCE = "google"
# 출처 id -> (이름, 검색 결과 주소). 탭 순서 = 이 순서 (실제로 연관검색어가 나오는 곳을 앞에, 막히는 쿠팡을 뒤에)
SOURCES = {
    "google": ("구글", "https://www.google.com/search?q="),
    "naver": ("네이버", "https://search.naver.com/search.naver?query="),
    "daum": ("다음", "https://search.daum.net/search?q="),
    "coupang": ("쿠팡", "https://www.coupang.com/np/search?q="),
}
USER_AGENT = "WING-Manager (+https://github.com/angelcom11/cupang-agent)"  # 브라우저인 척하지 않는다
_STOP = re.compile(r"^(\d+(ml|l|m|cm|mm|g|kg|p|개|종|매|입|인용)?|화이트|블랙|그레이|핑크|블루|용)$", re.I)


class SourceError(RuntimeError):
    """출처에서 가져오지 못했다. 메시지는 화면에 그대로 보이는 문장."""


class SourceBlocked(SourceError):
    """출처가 이 서버의 접속을 거부했다 (401·403·429). 출처 전체를 잠시 쉰다 — 일시적인 시간 초과와 달리 상품마다 두드려도 소용없다."""


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
    """실제 출처에 물어본다. 결과는 캐시한다(연관검색어 30분 · 실패 2분) — 화면을 열어 둬도 자주 묻지 않는다."""

    name = "live"

    def __init__(self, get=None, ttl_related: int = 1800, ttl_error: int = 120):
        self._get = get or requests.get
        self.ttl_related, self.ttl_error = ttl_related, ttl_error
        self._lock = threading.Lock()
        self._cache: dict = {}
        self._down: dict[str, tuple[float, SourceError]] = {}   # 출처 전체가 막혔을 때 (상품마다 다시 두드리지 않는다)

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


# 모의 데이터 (설정 keyword_provider="mock" 또는 환경변수 WING_KEYWORDS=mock): 인터넷 없이 화면을 보거나 테스트할 때
_SUFFIXES = ["추천", "가성비", "세트", "대용량", "선물", "인기", "1+1", "특가"]


class MockKeywordProvider:
    """모의 연관검색어. 출처와 상관없이 같은 가짜 데이터."""

    name = "mock"

    def query(self, name: str) -> str:
        return base_keyword(name)

    def related(self, name: str, source: str) -> list[str]:
        base = base_keyword(name)
        return [f"{base} {s}" for s in _SUFFIXES][:RELATED_N] if base else []


def _norm(word: str) -> str:
    """같은 검색어인지 비교할 때 쓰는 모양 (띄어쓰기·대소문자 무시)."""
    return re.sub(r"\s+", "", (word or "")).lower()


def suggest_tags(provider, name: str, sources=None, limit: int = MAX_TAGS,
                 exclude=()) -> tuple[list[dict], dict[str, str]]:
    """상품 하나의 등록용 검색어 추천. 여러 출처에 동시에 묻고 합쳐서 최대 ``limit`` 개.

    순위는 **몇 개 출처에 함께 나왔는지**가 먼저다 (여러 곳에서 쓰이는 말일수록 실제 검색량이 많다).
    같으면 출처 안에서의 등장 순서(자동완성 상위)가 앞선다.

    exclude 에는 사용자가 이미 넣어 둔 검색어를 준다 — 띄어쓰기·대소문자만 다른 중복도 걸러진다.
    상품 이름에서 뽑은 기준 낱말(base_keyword) 자체는 상품명으로 이미 검색되므로 넣지 않는다.

    반환: (추천 목록, 출처별 오류). 한 출처가 실패해도 나머지 출처의 결과는 그대로 쓴다.
    """
    wanted = [s for s in (sources or list(SOURCES)) if s in SOURCES]
    q = base_keyword(name)
    if not q or limit <= 0:
        return [], {}

    skip = {_norm(q)} | {_norm(w) for w in exclude if str(w).strip()}
    errors: dict[str, str] = {}

    def one(source: str):
        try:
            return source, [str(w).strip() for w in provider.related(name, source) if str(w).strip()], None
        except SourceError as exc:
            return source, [], str(exc)
        except Exception as exc:  # noqa: BLE001 — 바깥 출처 하나가 어떻게 실패해도 추천은 떠야 한다
            return source, [], f"가져오지 못했습니다 ({type(exc).__name__})"

    with ThreadPoolExecutor(max_workers=max(1, len(wanted))) as pool:
        fetched = list(pool.map(one, wanted))

    # 검색어 -> {"keyword": 처음 본 표기, "sources": [출처 이름], "rank": 출처 안에서의 가장 앞선 순서}
    merged: dict[str, dict] = {}
    for source, words, err in fetched:
        if err:
            errors[SOURCES[source][0]] = err
            continue
        for order, word in enumerate(words):
            key = _norm(word)
            if not key or key in skip:
                continue
            hit = merged.setdefault(key, {"keyword": word, "sources": [], "rank": order})
            label = SOURCES[source][0]
            if label not in hit["sources"]:
                hit["sources"].append(label)
            hit["rank"] = min(hit["rank"], order)

    ranked = sorted(merged.values(), key=lambda h: (-len(h["sources"]), h["rank"], h["keyword"]))
    return [{"keyword": h["keyword"], "sources": h["sources"]} for h in ranked[:limit]], errors


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
