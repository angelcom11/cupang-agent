"""경쟁 판매자 샵 주소.

- 경쟁가 공급자가 판매자 업체코드(vendorId, 예: A00012345)나 샵 주소를 주면 그걸 쓰고,
- 아니면 사용자가 경쟁가 화면에서 판매자를 눌러 한 번 등록한 주소를 쓴다 (판매자 이름별로 저장).
링크는 쿠팡 주소(https://shop.coupang.com/…, https://www.coupang.com/…)만 허용한다 — 다른 사이트·javascript: 링크 방지.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

VENDOR_ID = re.compile(r"^[A-Z]\d{8}$")
ALLOWED_HOSTS = {"shop.coupang.com", "www.coupang.com", "coupang.com", "m.coupang.com"}


def shop_url(value: str | None) -> str | None:
    """업체코드나 쿠팡 주소 → 열어도 안전한 샵 주소. 아니면 None."""
    v = (value or "").strip()
    if not v:
        return None
    if VENDOR_ID.match(v.upper()):
        return f"https://shop.coupang.com/{v.upper()}"
    if not v.startswith(("http://", "https://")):
        v = "https://" + v
    u = urlparse(v)
    if (u.hostname or "").lower() not in ALLOWED_HOSTS or u.username or u.password:
        return None
    return u._replace(scheme="https").geturl()


def attach(rows: list[dict], saved: dict[str, str]) -> list[dict]:
    """경쟁가 행마다 shop(열 주소)과 shop_source(provider/saved) 를 붙인다."""
    for r in rows:
        url = shop_url(r.get("url") or r.get("vendor_id"))
        source = "provider" if url else None
        if not url and saved.get(r["seller"]):
            url, source = saved[r["seller"]], "saved"
        r["shop"], r["shop_source"] = url, source
    return rows
