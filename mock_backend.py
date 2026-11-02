"""API 키 없이 화면을 확인하기 위한 가짜 쿠팡 클라이언트 + 가짜 경쟁사 가격."""
from __future__ import annotations

import json
import random
import threading

_SEED_PRODUCTS = [
    ("무선 블루투스 이어폰 화이트", 29900, 42),
    ("스테인리스 텀블러 500ml", 15900, 7),
    ("USB-C 고속충전 케이블 2m", 8900, 130),
    ("캠핑용 LED 랜턴", 24500, 3),
    ("접이식 노트북 거치대", 19800, 25),
    ("극세사 차량용 세차타올 5P", 11900, 0),
    ("실리콘 주방 조리도구 10종", 32000, 18),
    ("휴대용 미니 선풍기", 13900, 55),
]


# 쿠팡 '카테고리 메타정보 조회' 응답 모양 (보온/보냉텀블러 80534 실제 응답을 줄인 것)
MOCK_CATEGORY_META = {
    "isAllowSingleItem": True,
    "attributes": [
        {"attributeTypeName": "색상", "dataType": "STRING", "inputType": "INPUT", "inputValues": [], "basicUnit": "없음",
         "usableUnits": [], "required": "MANDATORY", "groupNumber": "NONE", "exposed": "EXPOSED"},
        {"attributeTypeName": "용량", "dataType": "NUMBER", "inputType": "INPUT", "inputValues": [], "basicUnit": "ml",
         "usableUnits": ["L", "ml"], "required": "MANDATORY", "groupNumber": "NONE", "exposed": "EXPOSED"},
        {"attributeTypeName": "수량", "dataType": "NUMBER", "inputType": "INPUT", "inputValues": [], "basicUnit": "개",
         "usableUnits": ["개"], "required": "MANDATORY", "groupNumber": "NONE", "exposed": "EXPOSED"},
        {"attributeTypeName": "컵 재질", "dataType": "STRING", "inputType": "SELECT",
         "inputValues": ["스테인리스", "플라스틱", "유리", "세라믹"], "basicUnit": "없음", "usableUnits": [],
         "required": "OPTIONAL", "groupNumber": "NONE", "exposed": "NONE"},
        {"attributeTypeName": "보온/보냉여부", "dataType": "STRING", "inputType": "SELECT",
         "inputValues": ["보온", "보냉", "보온보냉"], "basicUnit": "없음", "usableUnits": [],
         "required": "OPTIONAL", "groupNumber": "NONE", "exposed": "NONE"},
    ],
    "noticeCategories": [
        {"noticeCategoryName": "주방용품", "noticeCategoryDetailNames": [
            {"noticeCategoryDetailName": n, "required": "MANDATORY"} for n in (
                "품명 및 모델명", "재질", "구성품", "크기", "제조자(수입자)", "제조국",
                "식품용 기구 수입신고 여부", "품질보증기준", "A/S 책임자와 전화번호")]},
        {"noticeCategoryName": "기타 재화", "noticeCategoryDetailNames": [
            {"noticeCategoryDetailName": n, "required": "MANDATORY"} for n in (
                "품명 및 모델명", "인증사항", "제조국(원산지)", "제조자(수입자)", "소비자상담 관련 전화번호")]},
    ],
    "requiredDocumentNames": [
        {"templateName": "기타인증서류", "required": "OPTIONAL"},
        {"templateName": "수입신고필증(병행수입 선택시)", "required": "MANDATORY_PARALLEL_IMPORTED"},
    ],
    "certifications": [
        {"certificationType": "NOT_REQUIRED", "name": "인증대상아님", "dataType": "NONE", "required": "OPTIONAL"},
        {"certificationType": "PRESENTED_IN_DETAIL_PAGE", "name": "상세페이지 별도표기", "dataType": "NONE", "required": "OPTIONAL"},
        {"certificationType": "KC_SAFETY_CONFIRM", "name": "[생활용품] 안전확인", "dataType": "CODE", "required": "OPTIONAL"},
    ],
    "allowedOfferConditions": ["NEW"],
}

# 그 밖의 카테고리: 대부분의 쿠팡 카테고리처럼 '수량'만 필수, 고시정보는 '기타 재화'
MOCK_GENERIC_META = {
    "isAllowSingleItem": True,
    "attributes": [
        {"attributeTypeName": "수량", "dataType": "NUMBER", "inputType": "INPUT", "inputValues": [], "basicUnit": "개",
         "usableUnits": ["개"], "required": "OPTIONAL", "groupNumber": "NONE", "exposed": "EXPOSED"},
        {"attributeTypeName": "색상", "dataType": "STRING", "inputType": "INPUT", "inputValues": [], "basicUnit": "없음",
         "usableUnits": [], "required": "OPTIONAL", "groupNumber": "NONE", "exposed": "EXPOSED"},
        {"attributeTypeName": "사이즈", "dataType": "STRING", "inputType": "INPUT", "inputValues": [], "basicUnit": "없음",
         "usableUnits": [], "required": "OPTIONAL", "groupNumber": "NONE", "exposed": "EXPOSED"},
    ],
    "noticeCategories": [MOCK_CATEGORY_META["noticeCategories"][1]],
    "requiredDocumentNames": [{"templateName": "기타인증서류", "required": "OPTIONAL"}],
    "certifications": MOCK_CATEGORY_META["certifications"][:2],
    "allowedOfferConditions": ["NEW", "REFURBISHED", "USED_BEST", "USED_GOOD", "USED_NORMAL"],
}


class MockCoupangClient:
    mode = "mock"

    def __init__(self):
        self._lock = threading.Lock()
        self._items = {}
        for i, (name, price, stock) in enumerate(_SEED_PRODUCTS):
            vid = str(70000000000 + i)
            self._items[vid] = {
                "vendor_item_id": vid,
                "seller_product_id": str(1300000000 + i),
                "name": name, "sale_price": price, "stock": stock,
                "on_sale": True, "status": "승인완료",
            }
        self._next_id = 1300000100

    def fetch_items(self) -> list[dict]:
        with self._lock:
            for it in self._items.values():  # 주문으로 재고가 줄고, 가끔 입고되는 상황 흉내
                if it["on_sale"] and it["stock"] > 0 and random.random() < 0.3:
                    it["stock"] -= 1
                elif it["stock"] < 5 and random.random() < 0.05:
                    it["stock"] += 20
            return [dict(v) for v in self._items.values()]

    def stop_sale(self, vendor_item_id) -> dict:
        with self._lock:
            self._items[str(vendor_item_id)]["on_sale"] = False
        return {"code": "SUCCESS"}

    def resume_sale(self, vendor_item_id) -> dict:
        with self._lock:
            self._items[str(vendor_item_id)]["on_sale"] = True
        return {"code": "SUCCESS"}

    def ping(self) -> int:
        return len(self._items)

    # ---- 상품등록 화면용 (모의) ----
    def get_category_meta(self, category_code) -> dict:
        if str(category_code) == "80534":  # 보온/보냉텀블러
            return json.loads(json.dumps(MOCK_CATEGORY_META))
        return json.loads(json.dumps(MOCK_GENERIC_META))

    def list_outbound_places(self) -> list[dict]:
        return [{"code": "100001", "name": "[모의] 본사 창고", "address": "06236 서울 강남구 테헤란로 123 B1",
                 "usable": True}]

    def list_return_centers(self) -> list[dict]:
        return [{"code": "1000005678", "name": "[모의] 본사 반품센터", "address": "06236 서울 강남구 테헤란로 123 B1",
                 "zip": "06236", "addr": "서울 강남구 테헤란로 123", "addr_detail": "B1", "phone": "02-1234-5678",
                 "usable": True, "courier": "CJGLS"}]

    def delete_product(self, seller_product_id) -> dict:
        from coupang_client import CoupangAPIError
        with self._lock:
            opts = [v for v in self._items.values() if v["seller_product_id"] == str(seller_product_id)]
            if not opts or any(v["on_sale"] for v in opts):  # 실제 쿠팡과 같은 조건으로 거부
                raise CoupangAPIError(f"400: 업체상품[{seller_product_id}]이 없거나 삭제가 불가능한 상태입니다. "
                                      "옵션을 먼저 판매중지 하세요.")
            for v in opts:
                del self._items[v["vendor_item_id"]]
        return {"code": "SUCCESS", "data": str(seller_product_id)}

    def update_quantity(self, vendor_item_id, quantity: int) -> dict:
        with self._lock:
            self._items[str(vendor_item_id)]["stock"] = int(quantity)
        return {"code": "SUCCESS"}

    def update_price(self, vendor_item_id, price: int) -> dict:
        with self._lock:
            self._items[str(vendor_item_id)]["sale_price"] = int(price)
        return {"code": "SUCCESS"}

    def create_product(self, payload: dict) -> dict:
        def _price(item):  # 로켓그로스 요청은 가격이 rocketGrowthItemData/marketplaceItemData 안에 있다
            nested = item.get("marketplaceItemData") or item.get("rocketGrowthItemData") or {}
            return item.get("salePrice", nested.get("priceData", {}).get("salePrice", 0))

        def _stock(item):
            return item.get("maximumBuyCount", (item.get("marketplaceItemData") or {}).get("maximumBuyCount", 0)) or 0

        with self._lock:
            self._next_id += 1
            spid = str(self._next_id)
            for n, item in enumerate(payload.get("items", [])):
                vid = str(int(spid) * 10 + n)
                self._items[vid] = {
                    "vendor_item_id": vid, "seller_product_id": spid,
                    "name": f"{payload['sellerProductName']} {item.get('itemName', '')}".strip(),
                    "sale_price": int(_price(item)), "stock": int(_stock(item)),
                    "on_sale": True,
                    "status": "임시저장(모의)" + (" · 로켓그로스" if item.get("rocketGrowthItemData") else ""),
                }
        return {"code": "SUCCESS", "data": spid}


class MockCompetitorProvider:
    """경쟁 판매자 3~5곳의 가격을 무작위로 흔들어 실시간 변동을 흉내낸다."""

    name = "mock"

    def __init__(self):
        self._base: dict[str, list[tuple[str, int]]] = {}

    def fetch(self, item: dict) -> list[dict]:
        vid = item["vendor_item_id"]
        if vid not in self._base:
            p = item["sale_price"]
            self._base[vid] = [
                (f"판매자{chr(65 + k)}", int(p * random.uniform(0.9, 1.12) / 10) * 10)
                for k in range(random.randint(3, 5))
            ]
        out = []
        for seller, base in self._base[vid]:
            price = int(base * random.uniform(0.97, 1.03) / 10) * 10
            out.append({"seller": seller, "price": price, "url": ""})
        return out
