"""실시간 검색어: 쿠팡 인기 검색어 순위 + 내 상품의 연관검색어.

쿠팡 Open API에는 검색어 순위·연관검색어 조회 API가 없다. 그래서 경쟁가처럼 공급자를 교체 가능하게 분리했고,
지금은 모의 공급자(MockKeywordProvider)만 있다. 실제 공급자는 같은 두 메서드를 가지면 된다:

    trending() -> [{"rank": 1, "keyword": "…", "change": "up|down|same|new", "delta": 2}, …]   (1위부터 10위까지)
    related(name) -> ["연관검색어", …]                                                        (상품 이름 하나에 대해)
"""
from __future__ import annotations

import random
import re
import time
from urllib.parse import quote

TOP_N = 10
RELATED_N = 8
SEARCH_URL = "https://www.coupang.com/np/search?q="

# 모의 인기 검색어 후보 (순위는 시간에 따라 조금씩 바뀐다)
_POOL = [
    "무선 이어폰", "텀블러", "전기장판", "핫팩", "가습기", "고속충전 케이블", "캠핑 랜턴", "노트북 거치대",
    "세차타올", "주방 조리도구", "미니 선풍기", "보조배터리", "수면양말", "크리스마스 트리", "귤 5kg",
    "생수 2L", "물티슈", "무릎담요", "에어프라이어", "스마트폰 케이스",
]

# 모의 연관검색어: 상품 이름에 이 낱말이 들어 있으면 그 목록을 쓴다
_RELATED = {
    "이어폰": ["블루투스 이어폰", "무선 이어폰 가성비", "노이즈캔슬링 이어폰", "이어폰 케이스", "오픈형 이어폰", "운동용 이어폰", "게이밍 이어폰", "이어폰 이어팁"],
    "텀블러": ["스텐 텀블러", "보온보냉 텀블러", "텀블러 500ml", "빨대 텀블러", "대용량 텀블러", "손잡이 텀블러", "텀블러 세척솔", "차량용 텀블러"],
    "케이블": ["C타입 케이블", "고속충전 케이블 2m", "PD 케이블", "아이폰 충전 케이블", "멀티 충전 케이블", "케이블 정리", "100W 케이블", "충전기 세트"],
    "랜턴": ["캠핑 랜턴", "충전식 랜턴", "LED 랜턴", "감성 랜턴", "랜턴 걸이", "헤드랜턴", "무드등 랜턴", "랜턴 스탠드"],
    "거치대": ["노트북 거치대", "접이식 거치대", "알루미늄 거치대", "태블릿 거치대", "모니터 받침대", "휴대용 거치대", "높이조절 거치대", "맥북 거치대"],
    "세차": ["세차타올", "극세사 타올", "드라잉 타올", "세차용품 세트", "유리 세정제", "세차 스펀지", "휠 브러쉬", "차량용 왁스"],
    "조리도구": ["실리콘 조리도구", "조리도구 세트", "뒤집개", "국자", "조리도구 거치대", "스텐 조리도구", "실리콘 주걱", "요리 집게"],
    "선풍기": ["휴대용 선풍기", "미니 선풍기", "손풍기", "탁상용 선풍기", "넥밴드 선풍기", "무선 선풍기", "유모차 선풍기", "선풍기 거치대"],
}
_SUFFIXES = ["추천", "가성비", "세트", "대용량", "선물", "인기", "1+1", "특가"]
_STOP = re.compile(r"^(\d+(ml|l|m|cm|mm|g|kg|p|개|종|매|입|인용)?|화이트|블랙|그레이|핑크|블루|용)$", re.I)


def search_url(keyword: str) -> str:
    """검색어 → 쿠팡 검색 결과 주소 (새 탭으로 여는 링크용)."""
    return SEARCH_URL + quote(keyword)


def base_keyword(name: str) -> str:
    """상품 이름에서 연관검색어의 바탕이 될 낱말 (색·용량·수량은 뺀 마지막 두 낱말)."""
    words = [w for w in re.split(r"[\s/,()\[\]]+", name or "") if w and not _STOP.match(w)]
    return " ".join(words[-2:]) if words else (name or "").strip()


class MockKeywordProvider:
    """인기 검색어 순위를 1분마다 조금씩 흔들고, 상품 이름으로 연관검색어를 만들어 낸다 (가짜 데이터)."""

    name = "mock"
    step_sec = 60

    def _order(self, tick: int) -> list[str]:
        rnd = random.Random(tick)
        return sorted(_POOL, key=lambda k: _POOL.index(k) + rnd.uniform(-3.5, 3.5))

    def trending(self, now: float | None = None) -> list[dict]:
        tick = int((time.time() if now is None else now) // self.step_sec)
        prev = {k: i + 1 for i, k in enumerate(self._order(tick - 1)[:TOP_N])}
        out = []
        for i, kw in enumerate(self._order(tick)[:TOP_N]):
            rank, before = i + 1, prev.get(kw)
            change = "new" if before is None else "up" if before > rank else "down" if before < rank else "same"
            out.append({"rank": rank, "keyword": kw, "change": change, "delta": abs(before - rank) if before else 0})
        return out

    def related(self, name: str) -> list[str]:
        for key, words in _RELATED.items():
            if key in (name or ""):
                return words[:RELATED_N]
        base = base_keyword(name)
        return [f"{base} {s}" for s in _SUFFIXES][:RELATED_N] if base else []


def product_rows(provider, items: list[dict], limit: int = 50) -> list[dict]:
    """내 상품(이름이 같은 옵션은 한 번만)마다 연관검색어를 붙인다. 공급자가 실패한 상품은 빈 목록."""
    rows, seen = [], set()
    for it in items:
        name = (it.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        try:
            words = [str(w).strip() for w in provider.related(name) if str(w).strip()][:RELATED_N]
        except Exception:  # 공급자 하나가 실패해도 화면은 떠야 한다
            words = []
        rows.append({"name": name, "on_sale": bool(it.get("on_sale")), "featured": bool(it.get("featured")),
                     "keywords": [{"keyword": w, "url": search_url(w)} for w in words]})
        if len(rows) >= limit:
            break
    return rows


def trending_rows(provider) -> list[dict]:
    """1위부터 10위까지, 순위가 빠지거나 뒤섞여 와도 화면에는 1…10 순서로."""
    rows = sorted(provider.trending(), key=lambda r: int(r.get("rank") or 0))[:TOP_N]
    return [{"rank": i + 1, "keyword": str(r["keyword"]), "change": r.get("change") or "same",
             "delta": int(r.get("delta") or 0), "url": search_url(str(r["keyword"]))} for i, r in enumerate(rows)]
