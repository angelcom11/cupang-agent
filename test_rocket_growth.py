"""로켓그로스 판매방식: 요청 본문 모양(공식 문서 예시), 검증, 판매방식에 따른 단계, 화면 체크박스."""
import json, os, re, tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402
import product_form as pf  # noqa: E402
from mock_backend import MOCK_CATEGORY_META  # noqa: E402
from test_register_full import _form  # noqa: E402

INBOUND = {"rg_inbound": "now", "rg_inbound_name": "텀블러 입고", "rg_width": "80", "rg_length": "80",
           "rg_height": "220", "rg_weight": "420", "rg_net_weight": "380", "rg_agree": "1"}


def _post_data(f, **extra):
    data = {k: (json.dumps(v, ensure_ascii=False) if k in pf.JSON_KEYS else v) for k, v in f.items()}
    return {**{k: v for k, v in data.items() if v not in ("", None)}, "has_sell_mode": "1", **extra}


def test_rocket_only_moves_price_into_rocket_growth_item_data():
    f = _form(sell_seller="", sell_rocket="1", outbound_place_code="", return_center_code="", **INBOUND)
    assert pf.validate_form(f, A.categories, MOCK_CATEGORY_META) == []  # 출고지·반품지가 없어도 된다
    p = pf.build_product_payload(f, "A01", True, MOCK_CATEGORY_META)
    assert p["marketplaceShippingAndReturnInfo"] is None and "deliveryMethod" not in p and "returnCenterCode" not in p
    assert p["rocketGrowthAdditionalInformation"] == {"rfmInboundName": "텀블러 입고", "legalAgreement": "AGREE"}
    it = p["items"][1]
    assert it["marketplaceItemData"] is None and "salePrice" not in it and "maximumBuyCount" not in it
    rg = it["rocketGrowthItemData"]
    assert rg["priceData"] == {"originalPrice": 20000, "salePrice": 15900} and rg["externalVendorSku"] == "TB-블랙-500ml"
    assert (rg["barcode"], rg["emptyBarcode"], rg["emptyBarcodeReason"]) == ("", False, "AUTO_GENERATED")
    assert rg["skuInfo"] == {"fragile": False, "weight": 420, "netWeight": 380, "width": 80, "length": 80, "height": 220,
                             "quantityPerBox": 1, "distributionPeriod": 0, "expiredAtManaged": False}
    assert it["itemName"] == "블랙 500ml" and it["attributes"][0]["attributeValueName"] == "블랙"  # 공통 정보는 그대로


def test_hybrid_keeps_seller_shipping_and_stock():
    f = _form(sell_seller="1", sell_rocket="1", rg_agree="1", delivery_charge_type="NOT_FREE", delivery_charge="3000")
    p = pf.build_product_payload(f, "A01", False, MOCK_CATEGORY_META)
    ship = p["marketplaceShippingAndReturnInfo"]
    assert (ship["deliveryChargeType"], ship["deliveryCharge"], ship["returnCenterCode"]) == ("NOT_FREE", 3000, "1000005678")
    mp = p["items"][0]["marketplaceItemData"]
    assert mp["maximumBuyCount"] == 30 and mp["priceData"]["salePrice"] == 15900
    assert "skuInfo" not in p["items"][0]["rocketGrowthItemData"]  # 입고 정보는 나중에(WING)
    assert p["rocketGrowthAdditionalInformation"]["rfmInboundName"] == ""
    seller_only = pf.build_product_payload(_form(), "A01", False, MOCK_CATEGORY_META)  # 기존 판매자배송 본문은 그대로
    assert "rocketGrowthItemData" not in seller_only["items"][0] and seller_only["items"][0]["salePrice"] == 15900


def test_rocket_growth_rules():
    def errs(**over):
        return pf.validate_form(_form(sell_rocket="1", **over), A.categories, MOCK_CATEGORY_META)
    assert any("검수 기준 동의" in e for e in errs())
    assert any("판매방식" in e for e in pf.validate_form(_form(sell_seller="", sell_rocket=""), A.categories, MOCK_CATEGORY_META))
    e = errs(rg_agree="1", rg_inbound="now", rg_weight="100", rg_net_weight="200")
    assert any("가로(mm)" in x for x in e) and any("순중량은 무게보다" in x for x in e)
    opts = _form()["options"]
    opts[0]["barcode"], opts[1]["barcode"] = "8801234567890", "abc"
    e = errs(rg_agree="1", rg_barcode_mode="own", options=opts)
    assert not any("블랙 350ml" in x for x in e) and any("'블랙 500ml' 바코드는 영문 대문자" in x for x in e)
    assert any("'화이트 350ml' 바코드를 입력" in x for x in e)
    meta = {**MOCK_CATEGORY_META.get("80534", {}), "isExpirationDateRequiredForRocketGrowth": True}
    f = _form(sell_rocket="1", sell_seller="", outbound_place_code="", **INBOUND)
    assert any("소비기한" in x for x in pf.validate_form(f, A.categories, meta))
    assert pf.step_of_error("로켓그로스 상품 검수 기준 동의가 필요합니다") == "s-rg"
    # 물류 입고용 상품명을 비우면 노출상품명
    assert _form(sell_rocket="1", rg_inbound="now", rg_inbound_name="")["rg_inbound_name"] == "스텐 진공 텀블러"


def test_page_post_unchecks_seller_and_sends_rocket_request():
    c = A.app.test_client()
    seen, orig = [], A.client.create_product
    A.client.create_product = lambda payload: (seen.append(payload), orig(payload))[1]
    try:
        f = _form(sell_rocket="1", outbound_place_code="", **INBOUND)
        data = _post_data(f, action="request")
        data.pop("sell_seller", None)  # 판매자배송 체크 해제 = 폼에 없음
        r = c.post("/register", data=data)
        assert r.status_code == 302, re.findall(r'class="flash[^"]*">([^<]*)', r.get_data(as_text=True))
    finally:
        A.client.create_product = orig
    assert seen[0]["marketplaceShippingAndReturnInfo"] is None and seen[0]["requested"] is True
    d = A.store.draft(int(r.location.split("draft_id=")[1].split("&")[0]))
    assert (d["data"]["sell_seller"], d["data"]["sell_rocket"]) == ("", "1")
    page = c.get(r.location).get_data(as_text=True)
    assert re.search(r'name="sell_rocket" value="1" form="reg-form" checked', page)
    assert not re.search(r'name="sell_seller" value="1" form="reg-form" checked', page)
    assert 'id="s-rg"' in page and 'data-go="s-rg"' in page
