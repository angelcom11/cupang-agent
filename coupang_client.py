"""쿠팡 Open API(WING) 클라이언트.

인증: HMAC-SHA256 서명 (CEA algorithm). 공식 문서
https://developers.coupangcorp.com 의 '인증' 항목 방식을 그대로 따른다.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import requests

BASE_URL = "https://api-gateway.coupang.com"
SELLER_API = "/v2/providers/seller_api/apis/api/v1/marketplace"


def _place_address(addrs) -> str:
    a = (addrs or [{}])[0]
    return " ".join(x for x in (a.get("returnZipCode", ""), a.get("returnAddress", ""),
                                a.get("returnAddressDetail", "")) if x)


class CoupangAPIError(RuntimeError):
    pass


class CoupangClient:
    """실제 쿠팡 WING Open API 호출."""

    mode = "live"

    def __init__(self, access_key: str, secret_key: str, vendor_id: str, timeout: int = 15):
        self.access_key = access_key
        self.secret_key = secret_key
        self.vendor_id = vendor_id
        self.timeout = timeout
        self.session = requests.Session()

    # ---------- 인증 ----------
    def _authorization(self, method: str, path: str, query: str) -> str:
        signed_date = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
        message = f"{signed_date}{method}{path}{query}"
        signature = hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).hexdigest()
        return (
            f"CEA algorithm=HmacSHA256, access-key={self.access_key}, "
            f"signed-date={signed_date}, signature={signature}"
        )

    def _request(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        query = urlencode(params or {})
        url = f"{BASE_URL}{path}" + (f"?{query}" if query else "")
        headers = {
            "Authorization": self._authorization(method, path, query),
            "Content-Type": "application/json;charset=UTF-8",
            "X-EXTENDED-TIMEOUT": "90000",
        }
        resp = self.session.request(
            method, url, headers=headers, timeout=self.timeout,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        )
        try:
            data = resp.json()
        except ValueError:
            raise CoupangAPIError(f"{resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400 or str(data.get("code", "SUCCESS")).upper() not in ("SUCCESS", "200"):
            raise CoupangAPIError(f"{resp.status_code}: {data.get('message') or data}")
        return data

    # ---------- 상품 ----------
    def list_seller_products(self, max_per_page: int = 50) -> list[dict]:
        out, token = [], ""
        while True:
            params = {"vendorId": self.vendor_id, "maxPerPage": max_per_page}
            if token:
                params["nextToken"] = token
            data = self._request("GET", f"{SELLER_API}/seller-products", params)
            out.extend(data.get("data") or [])
            token = data.get("nextToken") or ""
            if not token:
                return out

    def get_seller_product(self, seller_product_id) -> dict:
        return self._request("GET", f"{SELLER_API}/seller-products/{seller_product_id}")["data"]

    def get_status_history(self, seller_product_id, max_items: int = 50) -> list[dict]:
        """상품 상태변경이력 조회 (승인·반려 상태와 사유 comment)."""
        out, token = [], "1"
        while token and len(out) < max_items:
            data = self._request("GET", f"{SELLER_API}/seller-products/{int(seller_product_id)}/histories",
                                 {"nextToken": token, "maxPerPage": 10})
            out += data.get("data") or []
            token = str(data.get("nextToken") or "")
        return out[:max_items]

    def create_product(self, payload: dict) -> dict:
        return self._request("POST", f"{SELLER_API}/seller-products", body=payload)

    # ---------- 재고 / 가격 ----------
    def get_inventory(self, vendor_item_id) -> dict:
        return self._request("GET", f"{SELLER_API}/vendor-items/{vendor_item_id}/inventories")["data"]

    def update_quantity(self, vendor_item_id, quantity: int) -> dict:
        return self._request("PUT", f"{SELLER_API}/vendor-items/{vendor_item_id}/quantities/{int(quantity)}")

    def update_price(self, vendor_item_id, price: int) -> dict:
        return self._request(
            "PUT", f"{SELLER_API}/vendor-items/{vendor_item_id}/prices/{int(price)}",
            params={"forceSalePriceUpdate": "true"},
        )

    def stop_sale(self, vendor_item_id) -> dict:
        return self._request("PUT", f"{SELLER_API}/vendor-items/{vendor_item_id}/sales/stop")

    def resume_sale(self, vendor_item_id) -> dict:
        return self._request("PUT", f"{SELLER_API}/vendor-items/{vendor_item_id}/sales/resume")

    def delete_product(self, seller_product_id) -> dict:
        """등록상품 삭제(옵션 전체). 쿠팡 조건: 승인대기 상태가 아니고 모든 옵션이 판매중지여야 함."""
        return self._request("DELETE", f"{SELLER_API}/seller-products/{seller_product_id}")

    def get_categories(self) -> dict:
        """노출 카테고리 전체 트리 (ROOT)."""
        return self._request("GET", f"{SELLER_API}/meta/display-categories")["data"]

    def get_category_meta(self, category_code) -> dict:
        """구매옵션·검색필터(attributes), 상품정보 제공고시, 구비서류, 인증정보, 허용 상품상태."""
        return self._request("GET", f"{SELLER_API}/meta/category-related-metas/display-category-codes/{int(category_code)}")["data"]

    def list_outbound_places(self) -> list[dict]:
        """WING에 등록한 출고지 → [{code, name, address, usable}]"""
        data = self._request("GET", "/v2/providers/marketplace_openapi/apis/api/v2/vendor/shipping-place/outbound",
                             {"pageNum": 1, "pageSize": 50})
        return [{"code": str(p["outboundShippingPlaceCode"]), "name": p.get("shippingPlaceName", ""),
                 "address": _place_address(p.get("placeAddresses")), "usable": p.get("usable", True)}
                for p in (data.get("content") or [])]

    def list_return_centers(self) -> list[dict]:
        """WING에 등록한 반품지 → [{code, name, address, zip, addr, addr_detail, phone, usable}]"""
        data = self._request("GET", f"/v2/providers/openapi/apis/api/v5/vendors/{self.vendor_id}/returnShippingCenters",
                             {"pageNum": 1, "pageSize": 50})
        out = []
        for c in ((data.get("data") or {}).get("content") or []):
            a = (c.get("placeAddresses") or [{}])[0]
            out.append({"code": str(c["returnCenterCode"]), "name": c.get("shippingPlaceName", ""),
                        "address": _place_address(c.get("placeAddresses")), "zip": a.get("returnZipCode", ""),
                        "addr": a.get("returnAddress", ""), "addr_detail": a.get("returnAddressDetail", ""),
                        "phone": a.get("companyContactNumber", ""), "usable": c.get("usable", True),
                        "courier": c.get("deliverCode", "")})
        return out

    def ping(self) -> int:
        """키·업체코드 확인용: 상품 1건만 조회해 본다."""
        data = self._request("GET", f"{SELLER_API}/seller-products", {"vendorId": self.vendor_id, "maxPerPage": 1})
        return len(data.get("data") or [])

    # ---------- 정규화: 화면에서 쓰는 옵션(vendorItem) 단위 목록 ----------
    def fetch_items(self) -> list[dict]:
        items = []
        for prod in self.list_seller_products():
            detail = self.get_seller_product(prod["sellerProductId"])
            for it in detail.get("items") or []:
                vid = it.get("vendorItemId")
                if not vid:
                    continue  # 승인 전 상품은 vendorItemId가 없음
                inv = self.get_inventory(vid)
                items.append({
                    "vendor_item_id": str(vid),
                    "seller_product_id": str(prod["sellerProductId"]),
                    "name": f"{detail.get('sellerProductName', '')} {it.get('itemName', '')}".strip(),
                    "sale_price": int(inv.get("salePrice") or it.get("salePrice") or 0),
                    "stock": int(inv.get("amountInStock") or 0),
                    "on_sale": bool(inv.get("onSale", True)),
                    "status": prod.get("statusName", ""),
                })
        return items
