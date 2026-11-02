"""상품등록 단건: 옵션 조합, 카테고리 메타(필수 구매옵션·고시정보·구비서류·인증), 판매방식, 배송·출고지, 반품/교환지."""
import io, json, os, re, tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402
import product_form as pf  # noqa: E402
from mock_backend import MOCK_CATEGORY_META  # noqa: E402

TUMBLER = "80534"  # 보온/보냉텀블러: 색상·용량·수량 필수, 고시정보 '주방용품'/'기타 재화'


def _form(**over):
    f = {"display_name": "스텐 진공 텀블러", "category_code": TUMBLER, "image_url": "https://e.com/a.jpg",
         "option_types": ["색상", "용량"], "fixed_attrs": {"수량": "1개"},
         "options": [{"values": {"색상": c, "용량": v}, "original_price": "20000", "sale_price": "15900", "stock": "30",
                      "sku": f"TB-{c}-{v}", "barcode": ""} for c in ("블랙", "화이트") for v in ("350ml", "500ml")],
         "notice_category": "주방용품", "notices": {"재질": "스테인리스"}, "certification_type": "NOT_REQUIRED",
         "outbound_place_code": "100001", "return_center_code": "1000005678", "vendor_user_id": "tester",
         "return_name": "본사", "return_phone": "02-1", "return_zip": "06236", "return_addr": "서울", "return_addr_detail": "B1"}
    f.update(over)
    return pf.normalize_form(f)


def _errors(**over):
    return pf.validate_form(_form(**over), A.categories, MOCK_CATEGORY_META)


def test_options_attrs_notices_and_shipping_in_payload():
    f = _form(delivery_charge_type="CONDITIONAL_FREE", delivery_charge="3000", free_ship_over="30000",
              max_per_person="2", outbound_days="1", union_delivery="N", filter_attrs={"컵 재질": "스테인리스"})
    assert pf.validate_form(f, A.categories, MOCK_CATEGORY_META) == []
    p = pf.build_product_payload(f, "A01", True, MOCK_CATEGORY_META)
    assert [i["itemName"] for i in p["items"]] == ["블랙 350ml", "블랙 500ml", "화이트 350ml", "화이트 500ml"]
    it = p["items"][1]
    assert (it["salePrice"], it["originalPrice"], it["maximumBuyCount"], it["externalVendorSku"]) == (15900, 20000, 30, "TB-블랙-500ml")
    assert it["attributes"] == [{"attributeTypeName": "색상", "attributeValueName": "블랙"},
                                {"attributeTypeName": "용량", "attributeValueName": "500ml"},
                                {"attributeTypeName": "수량", "attributeValueName": "1개"},
                                {"attributeTypeName": "컵 재질", "attributeValueName": "스테인리스", "exposed": "NONE"}]
    notices = {n["noticeCategoryDetailName"]: n["content"] for n in it["notices"]}
    assert len(notices) == 9 and notices["재질"] == "스테인리스" and notices["제조국"] == "상세페이지 참조"
    assert {n["noticeCategoryName"] for n in it["notices"]} == {"주방용품"}
    assert (it["maximumBuyForPerson"], it["outboundShippingTimeDay"], it["emptyBarcode"]) == (2, 1, True)
    assert (p["deliveryChargeType"], p["deliveryCharge"], p["freeShipOverAmount"]) == ("CONDITIONAL_FREE", 3000, 30000)
    assert (p["unionDeliveryType"], p["outboundShippingPlaceCode"], p["returnCenterCode"]) == ("NOT_UNION_DELIVERY", "100001", "1000005678")
    assert (p["vendorUserId"], p["requested"], p["brand"]) == ("tester", True, "GENERIC")


def test_category_rules_are_enforced():
    assert any("필수 구매옵션 '수량'" in e for e in _errors(fixed_attrs={}))
    assert any("단위가 올바르지 않습니다" in e for e in _errors(fixed_attrs={"수량": "1박스"}))
    bad = _form().get("options")
    bad[0]["values"]["용량"] = "큰거"
    assert any("숫자로 시작" in e for e in pf.validate_form(_form(options=bad), A.categories, MOCK_CATEGORY_META))
    opts = _form()["options"]
    opts[0]["sale_price"], opts[1]["original_price"] = "15905", "100"
    opts[3]["values"] = dict(opts[2]["values"])
    errs = pf.validate_form(_form(options=opts), A.categories, MOCK_CATEGORY_META)
    assert any("10원 단위" in e for e in errs) and any("판매가보다 작을 수 없습니다" in e for e in errs)
    assert any("중복" in e for e in errs)
    assert "상품정보 제공고시 종류를 선택하세요" in _errors(notice_category="")      # 종류가 2개라 골라야 함
    assert "구비서류 '수입신고필증(병행수입 선택시)'을(를) 올려 주세요" in _errors(parallel_imported="1")
    assert _errors(parallel_imported="1", docs={"수입신고필증(병행수입 선택시)": "https://e.com/d.pdf"}) == []
    assert "'[생활용품] 안전확인' 인증번호를 입력하세요" in _errors(certification_type="KC_SAFETY_CONFIRM")


def test_shipping_and_return_rules():
    assert "조건부 무료배송 기준 금액은 100원 단위로 입력하세요" in _errors(delivery_charge_type="CONDITIONAL_FREE",
                                                                    delivery_charge="3000", free_ship_over="150")
    assert "유료·조건부 무료·착불 배송은 기본 배송비를 입력하세요" in _errors(delivery_charge_type="NOT_FREE", delivery_charge="0")
    assert any("출고지를 선택하세요" in e for e in _errors(outbound_place_code=""))
    errs = _errors(return_center_code=pf.NO_RETURN_CENTER, return_zip="", return_addr_detail="")
    assert errs == ["반품/교환지 우편번호을(를) 입력하세요", "반품/교환지 상세주소을(를) 입력하세요"]
    p = pf.build_product_payload(_form(return_center_code=pf.NO_RETURN_CENTER), "A01", False, MOCK_CATEGORY_META)
    assert (p["returnCenterCode"], p["returnZipCode"], p["returnAddressDetail"]) == ("NO_RETURN_CENTERCODE", "06236", "B1")
    assert "판매 종료일은 시작일보다 뒤여야 합니다" in _errors(sale_start="2030-01-02T00:00", sale_end="2030-01-01T00:00")


def test_page_submit_with_json_fields_and_remember_defaults():
    c = A.app.test_client()
    f = _form()
    data = {k: (json.dumps(v, ensure_ascii=False) if k in pf.JSON_KEYS else v) for k, v in f.items()}
    r = c.post("/register", data={**data, "action": "preview", "remember_defaults": "on", "delivery_company": "HANJIN"})
    html = r.get_data(as_text=True)
    assert "요청 본문" in html and "&#34;화이트 500ml&#34;" in html and "maximumBuyCount" in html, re.findall(r'flash[^>]*>([^<]*)', html)
    assert A.cfg["register_defaults"]["delivery_company"] == "HANJIN"
    assert json.loads(open(A.CONFIG_PATH, encoding="utf-8").read())["register_defaults"]["outbound_place_code"] == "100001"
    page = c.get("/register").get_data(as_text=True)          # 새 상품에도 기억한 값
    assert re.search(r'<option value="HANJIN"\s+selected', page) and 'data-value="100001"' in page
    # 사용자가 지운 칸은 기본값으로 되돌리지 않는다
    r = c.post("/register", data={**data, "action": "submit", "vendor_user_id": ""})
    assert "WING 로그인 아이디(실사용자 아이디)를 입력하세요" in r.get_data(as_text=True)
    r = c.post("/register", data={**data, "action": "submit"})
    assert r.status_code == 302
    d = A.store.draft(int(r.location.split("draft_id=")[1].split("&")[0]))
    assert len(d["data"]["options"]) == 4 and d["data"]["fixed_attrs"] == {"수량": "1개"}
    assert any(i["name"].endswith("화이트 500ml") for i in A.client.fetch_items())


def test_legacy_single_option_draft_and_meta_places_api():
    did = A.store.save_draft({"display_name": "옛 상품", "category_code": "79382", "item_name": "화이트 / FREE",
                              "sale_price": "12900", "stock": "5", "delivery_charge": "3000"})
    html = A.app.test_client().get(f"/register?draft_id={did}").get_data(as_text=True)
    state = json.loads(re.search(r'id="reg-state">(.*?)</script>', html, re.S).group(1))
    assert state["options"][0] | {"values": {}} == {"values": {}, "name": "화이트 / FREE", "original_price": "",
                                                    "sale_price": "12900", "stock": "5", "sku": "", "barcode": ""}
    assert re.search(r'value="NOT_FREE"\s+checked', html)  # 배송비만 있던 예전 폼 → 유료배송
    c = A.app.test_client()
    m = c.get(f"/api/category-meta/{TUMBLER}").get_json()
    assert [a["attributeTypeName"] for a in m["attributes"] if a["required"] == "MANDATORY"] == ["색상", "용량", "수량"]
    assert c.get("/api/category-meta/79268").status_code == 400            # 중간 단계 카테고리
    places = c.get("/api/shipping-places").get_json()
    assert places["outbound"][0]["code"] == "100001" and places["returns"][0]["zip"] == "06236" and not places["errors"]


def test_document_upload_types():
    c = A.app.test_client()
    up = lambda blob, name: c.post("/api/upload", data={"kind": "doc", "file": (io.BytesIO(blob), name)},
                                   content_type="multipart/form-data")
    r = up(b"%PDF-1.4\n...", "수입신고필증.pdf")
    assert r.status_code == 200 and r.get_json()["url"].endswith(".pdf")
    assert up(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 8, "서류.hwp").get_json()["url"].endswith(".hwp")
    assert up(b"MZ\x90\x00", "virus.pdf").status_code == 400
    assert "5MB" in up(b"%PDF" + b"0" * (5 * 1024 * 1024 + 1), "big.pdf").get_json()["error"]
    # 이미지 칸은 여전히 이미지만
    assert c.post("/api/upload", data={"file": (io.BytesIO(b"%PDF-1.4"), "a.pdf")},
                  content_type="multipart/form-data").status_code == 400


def test_csv_row_gets_attrs_and_notice_autofill():
    row = pf.normalize_form({"display_name": "티", "category_code": "79382", "sale_price": "9900", "image_url": "https://e/a.jpg",
                             "attrs_text": "색상=블랙; 수량=1개", "outbound_place_code": "1", "return_center_code": "2",
                             "vendor_user_id": "u"})
    meta = A.client.get_category_meta("79382")
    pf.autofill_notices(row, meta)
    assert row["fixed_attrs"] == {"색상": "블랙", "수량": "1개"} and row["notice_category"] == "기타 재화"
    assert pf.validate_form(row, A.categories, meta) == []


def test_wizard_steps_error_step_and_saved_step():
    msgs = ["대표 이미지를 올리거나 주소를 입력하세요", "반품/교환지 우편번호을(를) 입력하세요", "출고지를 선택하세요 (WING에…)",
            "출고 소요일은(는) 1 이상의 숫자여야 합니다", "'[생활용품] 안전확인' 인증번호를 입력하세요",
            "블랙 350ml: 판매가는 10원 단위로 입력하세요", "초도반품배송비는 숫자로 입력하세요", "노출상품명은(는) 필수입니다",
            "카테고리은(는) 필수입니다", "판매 종료일은 시작일보다 뒤여야 합니다", "WING 로그인 아이디(실사용자 아이디)를 입력하세요"]
    assert [pf.step_of_error(m) for m in msgs] == ["s-image", "s-return", "s-ship", "s-ship", "s-main", "s-option", "s-return",
                                                   "s-name", "s-cat", "s-main", "s-confirm"]
    assert [pf.sub_of_error(m) for m in (msgs[4], msgs[9])] == [1, 3]   # 주요정보: 인증정보 / 구매수량·판매기간
    assert [k for k, _ in pf.STEPS][:6] == ["s-name", "s-cat", "s-option", "s-image", "s-detail", "s-main"]  # WING 순서
    c = A.app.test_client()
    data = {k: (json.dumps(v, ensure_ascii=False) if k in pf.JSON_KEYS else v) for k, v in _form().items()}
    # 이미지·반품지가 빠지면 앞쪽(이미지) 단계부터 다시 열고, 두 단계 모두 오류 표시
    html = c.post("/register", data={**data, "action": "submit", "image_url": "", "return_center_code": ""}).get_data(as_text=True)
    assert 'id="cur-step" value="s-image"' in html
    assert re.search(r'data-go="s-image"[^>]*class="err"', html) and re.search(r'data-go="s-return"[^>]*class="err"', html)
    assert not re.search(r'data-go="s-ship"[^>]*class="err"', html)
    assert 'data-resume="1"' in html
    html = c.post("/register", data={**data, "action": "submit", "certification_type": "KC_SAFETY_CONFIRM"}).get_data(as_text=True)
    assert 'value="s-main"' in html and 'data-sub="1"' in html               # 주요정보의 2번째(인증정보) 작은 단계
    # 임시저장은 보고 있던 단계를 기억, 미리보기는 확인 단계에서 보여 줌
    r = c.post("/register", data={**data, "action": "draft", "step": "s-ship"})
    assert "step=s-ship" in r.location
    assert 'id="cur-step" value="s-ship"' in c.get(r.location).get_data(as_text=True)
    html = c.post("/register", data={**data, "action": "preview"}).get_data(as_text=True)
    assert 'value="s-confirm"' in html and html.index('id="s-confirm"') < html.index("요청 본문") < html.index('class="actions sticky wiz"')
    new = c.get("/register").get_data(as_text=True)
    assert 'id="cur-step" value="s-name"' in new and 'data-resume="0"' in new


def test_wing_buttons_save_vs_request_and_derived_fields():
    """저장하기 = 쿠팡에 임시저장(requested false), 판매요청 = 승인요청(true). 구매대행은 배송방법에서, 상세 이미지 모드."""
    c = A.app.test_client()
    seen = []
    orig = A.client.create_product
    A.client.create_product = lambda payload: (seen.append(payload), orig(payload))[1]
    try:
        base = _form(delivery_method="AGENT_BUY", detail_mode="images",
                     content_images=["https://e.com/d1.jpg", "https://e.com/d2.jpg"])
        base["options"][0]["model_no"] = "TB-B350"
        data = {k: (json.dumps(v, ensure_ascii=False) if k in pf.JSON_KEYS else v) for k, v in base.items()}
        assert c.post("/register", data={**data, "action": "save"}).status_code == 302
        assert c.post("/register", data={**data, "action": "request"}).status_code == 302
    finally:
        A.client.create_product = orig
    assert [p["requested"] for p in seen] == [False, True]
    it = seen[0]["items"][0]
    assert (it["overseasPurchased"], it["pccNeeded"], it["modelNo"]) == ("OVERSEAS_PURCHASED", True, "TB-B350")
    assert seen[0]["items"][1]["modelNo"] == ""
    html = it["contents"][0]["contentDetails"][0]["content"]
    assert html.index("d1.jpg") < html.index("d2.jpg") and html.count("<img") == 2
    # 일반배송이면 해외구매대행 아님 (예전 체크박스 값이 남아 있어도)
    p = pf.build_product_payload(_form(overseas_purchased="1"), "A01", False, MOCK_CATEGORY_META)
    assert p["items"][0]["overseasPurchased"] == "NOT_OVERSEAS_PURCHASED"
