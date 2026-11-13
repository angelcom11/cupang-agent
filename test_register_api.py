"""새 등록 마법사(/ui/register)가 쓰는 API.

검증·요청본문 만들기는 product_form.py 를 그대로 쓴다. 규칙이 두 벌로 갈라지면
한쪽만 고쳐지는 사고가 나므로, 여기서는 "같은 규칙이 JSON 경로로도 나오는지" 를 본다.
"""
import json
import os
import tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import pytest  # noqa: E402

import app as A  # noqa: E402
import product_form as pf  # noqa: E402

TUMBLER = "63"  # test_register_full 과 같은 모의 카테고리


@pytest.fixture(autouse=True)
def _defaults():
    before = dict(A.cfg)
    A.cfg["register_defaults"] = {"outbound_place_code": "100001",
                                  "return_center_code": "1000005678",
                                  "vendor_user_id": "tester"}
    yield
    A.cfg.clear()
    A.cfg.update(before)


def _client():
    return A.app.test_client()


def _good_form(**over) -> dict:
    """등록이 통과하는 폼. test_register_full._form 과 같은 내용이다."""
    f = {
        "display_name": "스텐 진공 텀블러", "category_code": TUMBLER, "image_url": "https://e.com/a.jpg",
        "option_types": ["색상"], "fixed_attrs": {"수량": "1개"},
        "options": [{"values": {"색상": c}, "original_price": "20000", "sale_price": "15900",
                     "stock": "30", "sku": f"TB-{c}", "barcode": ""} for c in ("블랙", "화이트")],
        "notice_category": "주방용품", "notices": {"재질": "스테인리스"},
        "certification_type": "NOT_REQUIRED",
        "outbound_place_code": "100001", "return_center_code": "1000005678", "vendor_user_id": "tester",
        "return_name": "본사", "return_phone": "02-1", "return_zip": "06236",
        "return_addr": "서울", "return_addr_detail": "B1",
    }
    f.update(over)
    return f


def test_meta_gives_the_wizard_its_steps_and_an_empty_form():
    d = _client().get("/api/register/meta").get_json()
    assert [s["id"] for s in d["steps"]] == pf.STEP_IDS, "단계 목록이 product_form 과 달라졌다"
    assert d["steps"][0]["label"] == "노출상품명"
    assert d["form"], "빈 폼의 기본값이 와야 한다"
    assert "outbound" in d["places"] and "returns" in d["places"]


def test_submit_refusal_carries_the_steps_too_not_just_a_message():
    """마법사는 400 의 errors 로 고칠 단계를 찾는다.

    error 한 줄만 주면 '뭐가 틀렸는지는 아는데 어디서 고치는지 모르는' 상태가 된다.
    """
    r = _client().post("/api/register/submit", json={"action": "request"})
    assert r.status_code == 400
    body = r.get_json()
    assert "errors" in body, "errors 목록이 없으면 마법사가 단계로 데려가지 못한다"
    assert all(e["step"] in pf.STEP_IDS for e in body["errors"])


def test_option_rows_carry_every_field_the_wizard_edits():
    """화면이 고치는 칸과 payload 가 읽는 칸이 어긋나면 입력이 조용히 사라진다."""
    form = _good_form()
    form["options"][0].update(model_no="M-1", barcode="8801234567890", sku="TB-1")
    r = _client().post("/api/register/preview", json=form)
    assert r.status_code == 200, r.get_json()
    sent = json.dumps(r.get_json()["payload"], ensure_ascii=False)
    for value in ("M-1", "8801234567890", "TB-1"):
        assert value in sent, f"{value} 이(가) 쿠팡에 보낼 본문에 없다"


def test_every_validation_error_carries_the_step_that_fixes_it():
    """마법사는 오류를 받아 그 단계로 데려간다. 단계가 없으면 사용자가 헤맨다."""
    errors = _client().post("/api/register/validate", json={}).get_json()["errors"]

    assert errors, "빈 폼은 통과하면 안 된다"
    for e in errors:
        assert e["step"] in pf.STEP_IDS, f"{e['message']} 의 단계가 {e['step']} 다"
        assert isinstance(e["sub"], int)
    # 빈 폼이면 적어도 이름·카테고리는 걸려야 한다
    assert {"s-name", "s-cat"} <= {e["step"] for e in errors}


def test_a_good_form_passes_and_preview_shows_the_real_payload():
    c = _client()
    form = _good_form()

    assert c.post("/api/register/validate", json=form).get_json()["errors"] == []

    body = c.post("/api/register/preview", json=form).get_json()
    assert body["errors"] == []
    payload = body["payload"]
    assert payload["displayProductName"] == "스텐 진공 텀블러"
    assert [i["itemName"] for i in payload["items"]] == ["블랙", "화이트"]
    assert payload["items"][0]["salePrice"] == 15900


def test_preview_refuses_an_invalid_form_with_400():
    res = _client().post("/api/register/preview", json=_good_form(display_name=""))
    assert res.status_code == 400
    assert any(e["step"] == "s-name" for e in res.get_json()["errors"])


def test_submit_save_and_request_set_the_approval_flag_differently(monkeypatch):
    """WING 의 두 버튼: 저장하기는 쿠팡 임시저장, 판매요청은 바로 승인요청."""
    c = _client()
    sent = []

    def fake(payload):
        sent.append(payload)
        return {"data": 777}

    monkeypatch.setattr(A.client, "create_product", fake)
    for action in ("save", "request"):
        res = c.post("/api/register/submit", json={**_good_form(), "action": action})
        assert res.status_code == 200, res.get_json()
    assert sent[0]["requested"] is False, "저장하기가 판매요청으로 갔다"
    assert sent[1]["requested"] is True, "판매요청이 저장하기로 갔다"


def test_submit_refuses_an_unknown_action():
    res = _client().post("/api/register/submit", json={**_good_form(), "action": "지워"})
    assert res.status_code == 400


def test_submit_leaves_a_draft_so_the_work_is_not_lost(monkeypatch):
    """등록한 내용은 임시저장에 남아야 이어서 고칠 수 있다 (기존 화면과 같다)."""
    c = _client()
    monkeypatch.setattr(A.client, "create_product", lambda payload: {"data": 888})
    body = c.post("/api/register/submit", json={**_good_form(), "action": "save"}).get_json()

    assert body["draft_id"], "임시저장이 남지 않았다"
    loaded = c.get(f"/api/register/draft/{body['draft_id']}").get_json()
    assert loaded["form"]["display_name"] == "스텐 진공 텀블러"


def test_draft_saves_even_without_required_fields():
    """임시저장은 언제든 된다 — 쓰다 말고 닫아도 잃지 않아야 한다."""
    body = _client().post("/api/register/draft", json={"display_name": "쓰다 만 상품"}).get_json()
    assert body["draft_id"]
    assert "쓰다 만 상품" in body["message"]


def test_loading_a_missing_draft_is_404():
    assert _client().get("/api/register/draft/999999").status_code == 404
