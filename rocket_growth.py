"""로켓그로스 상품 등록 (쿠팡 '상품 생성 - 로켓그로스 및 마켓플레이스/로켓그로스 동시 운영 상품').

같은 POST seller-products 이지만 요청 모양이 다르다 (공식 문서의 요청 예시 기준):
- items[] 의 가격·재고·바코드·판매자코드·모델번호 → rocketGrowthItemData / marketplaceItemData 안으로
- 판매자배송 배송·반품 정보 → marketplaceShippingAndReturnInfo 안으로 (로켓그로스만이면 null)
- rocketGrowthAdditionalInformation: 물류 입고용 상품명(rfmInboundName) + 검수 기준 동의(legalAgreement=AGREE)
사전 준비: WING > 판매자정보 > 추가판매정보 > '로켓그로스 상품 생성 API 이용 및 검수 기준 동의'.
"""
from __future__ import annotations

import re

FORM_DEFAULTS = {
    "sell_seller": "1", "sell_rocket": "", "rg_agree": "",
    "rg_inbound": "later", "rg_barcode_mode": "auto", "rg_inbound_name": "",
    "rg_width": "", "rg_length": "", "rg_height": "", "rg_weight": "", "rg_net_weight": "",
    "rg_expiry_days": "0", "rg_fragile": "N",
}
CHECKBOX_KEYS = ("sell_seller", "sell_rocket", "rg_agree")
REMEMBER_KEYS = ("sell_seller", "sell_rocket", "rg_barcode_mode", "rg_inbound")  # 상품마다 다른 크기·무게는 기억하지 않음
AUTO_BARCODE = "AUTO_GENERATED"  # 쿠팡 바코드 자동 생성을 요청하는 쿠팡 지정 값
SHIPPING_KEYS = ("deliveryMethod", "deliveryCompanyCode", "deliveryChargeType", "deliveryCharge", "freeShipOverAmount",
                 "remoteAreaDeliverable", "unionDeliveryType", "outboundShippingPlaceCode", "extraInfoMessage",
                 "returnCenterCode", "returnChargeName", "companyContactNumber", "returnZipCode", "returnAddress",
                 "returnAddressDetail", "returnCharge", "deliveryChargeOnReturn")
SKU_FIELDS = (("rg_width", "가로(mm)"), ("rg_length", "세로(mm)"), ("rg_height", "높이(mm)"),
              ("rg_weight", "무게(g)"), ("rg_net_weight", "순중량(g)"))
_BARCODE_LENGTHS = {8, 12, 13, 14, 18}


def seller_on(f: dict) -> bool:
    return bool(f.get("sell_seller"))


def rocket_on(f: dict) -> bool:
    return bool(f.get("sell_rocket"))


def _int(v) -> int:
    s = str(v if v is not None else "").replace(",", "").strip()
    return int(s) if s.isdigit() else 0


def barcode_problem(code: str) -> str | None:
    """문서 기준: 소문자·공백·하이픈 외 특수문자 없음, 8·12·13·14·18자리."""
    if not re.fullmatch(r"[A-Z0-9-]+", code):
        return "영문 대문자·숫자만 쓸 수 있습니다"
    if len(code.replace("-", "")) not in _BARCODE_LENGTHS:
        return "8·12·13·14·18자리여야 합니다"
    return None


def validate(f: dict, meta: dict | None, option_label, errors: list):
    if not seller_on(f) and not rocket_on(f):
        errors.append("판매방식(판매자배송·로켓그로스)을 하나 이상 선택하세요")
    if not rocket_on(f):
        return
    if not f.get("rg_agree"):
        errors.append("로켓그로스 상품 검수 기준 동의가 필요합니다")
    if f.get("rg_barcode_mode") == "own":
        for i, o in enumerate(f["options"], 1):
            label = option_label(f, o) or f"{i}번째 옵션"
            code = str(o.get("barcode") or "").strip()
            if not code:
                errors.append(f"로켓그로스 바코드: '{label}' 바코드를 입력하거나 '쿠팡 바코드 사용'을 고르세요")
            elif problem := barcode_problem(code):
                errors.append(f"로켓그로스 바코드: '{label}' 바코드는 {problem}")
    if f.get("rg_inbound") == "now":
        if not str(f.get("rg_inbound_name") or "").strip():
            errors.append("로켓그로스 물류 입고용 상품명을 입력하세요")
        for key, label in SKU_FIELDS:
            if _int(f.get(key)) <= 0:
                errors.append(f"로켓그로스 입고 정보 {label} 값을 1 이상의 숫자로 입력하세요")
        if _int(f.get("rg_net_weight")) > _int(f.get("rg_weight")) > 0:
            errors.append("로켓그로스 입고 정보 순중량은 무게보다 클 수 없습니다")
        if not str(f.get("rg_expiry_days") or "0").strip().isdigit():
            errors.append("로켓그로스 소비기한(일)은 숫자로 입력하세요")
        elif (meta or {}).get("isExpirationDateRequiredForRocketGrowth") and _int(f.get("rg_expiry_days")) <= 0:
            errors.append("이 카테고리는 로켓그로스 소비기한(일)이 필수입니다")


def _sku_info(f: dict) -> dict:
    days = _int(f.get("rg_expiry_days"))
    return {"fragile": f.get("rg_fragile") == "Y", "weight": _int(f.get("rg_weight")),
            "netWeight": _int(f.get("rg_net_weight")), "width": _int(f.get("rg_width")),
            "length": _int(f.get("rg_length")), "height": _int(f.get("rg_height")),
            "quantityPerBox": 1,  # 로켓그로스는 입수량 1 고정 (문서)
            "distributionPeriod": days, "expiredAtManaged": days > 0}


def to_hybrid(payload: dict, f: dict) -> dict:
    """판매자배송용으로 만든 요청 본문 → 로켓그로스(또는 동시 운영) 요청 본문."""
    seller = seller_on(f)
    shipping = {k: payload.pop(k) for k in SHIPPING_KEYS if k in payload}
    payload["marketplaceShippingAndReturnInfo"] = shipping if seller else None
    own = f.get("rg_barcode_mode") == "own"
    sku_info = _sku_info(f) if f.get("rg_inbound") == "now" else None
    for item in payload["items"]:
        price = {"originalPrice": item.pop("originalPrice"), "salePrice": item.pop("salePrice")}
        stock = item.pop("maximumBuyCount")
        sku, model = item.pop("externalVendorSku"), item.pop("modelNo")
        barcode, empty, reason = item.pop("barcode"), item.pop("emptyBarcode"), item.pop("emptyBarcodeReason")
        item["marketplaceItemData"] = {"externalVendorSku": sku, "modelNo": model, "maximumBuyCount": stock,
                                       "barcode": barcode, "emptyBarcode": empty, "emptyBarcodeReason": reason,
                                       "priceData": dict(price)} if seller else None
        rg = {"barcode": barcode if own else "", "emptyBarcode": False,
              "emptyBarcodeReason": "" if own else AUTO_BARCODE,
              "externalVendorSku": sku, "modelNo": model, "priceData": dict(price)}
        if sku_info:
            rg["skuInfo"] = dict(sku_info)
        item["rocketGrowthItemData"] = rg
    payload["rocketGrowthAdditionalInformation"] = {
        "rfmInboundName": str(f.get("rg_inbound_name") or "").strip() if sku_info else "",
        "legalAgreement": "AGREE" if f.get("rg_agree") else ""}
    return payload
