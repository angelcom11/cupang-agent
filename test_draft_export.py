"""임시저장 목록: 일괄등록 템플릿 내려받기, 선택한 임시저장만 등록."""
import html

import app as A
import draft_export
from services import parse_csv


def _draft(name, **extra):
    data = {"display_name": name, "category_code": "79382", "sale_price": "10000", "original_price": "12000",
            "stock": "5", "image_url": "https://example.com/a.jpg", "search_tags": "a,b"} | extra
    return A.store.save_draft(data)


def test_export_roundtrips_through_csv_upload_and_expands_options():
    one = _draft("단일 상품")
    multi = _draft("옵션 상품", option_types=["색상"], fixed_attrs={"수량": "1개"},
                   options=[{"values": {"색상": "블랙"}, "sale_price": "9000", "stock": "3"},
                            {"values": {"색상": "화이트"}, "sale_price": "9500", "stock": "4"}])
    c = A.app.test_client()
    r = c.post("/register/drafts/export.csv", data={"draft_ids": [str(one), str(multi)]})
    assert "attachment; filename=coupang_drafts_" in r.headers["Content-Disposition"]
    text = r.data.decode("utf-8")
    assert text.startswith("\ufeff노출상품명*")
    rows = parse_csv(text)                                         # 'CSV 일괄 등록'이 그대로 읽는 형식
    assert [r["display_name"] for r in rows] == ["단일 상품", "옵션 상품", "옵션 상품"]
    assert rows[1]["item_name"] == "블랙" and rows[1]["sale_price"] == "9000"
    assert rows[1]["attrs_text"] == "수량=1개;색상=블랙" and rows[0]["search_tags"] == "a,b"
    assert c.get("/register/drafts/export.csv").status_code == 200     # 전체
    for d in (one, multi):
        A.store.delete_draft(d)


def test_submit_only_selected_and_mark_registered(monkeypatch):
    sent = []
    monkeypatch.setattr(A, "category_meta", lambda code, refresh=False: {})
    monkeypatch.setattr(A, "validate_form", lambda form, cats, meta: [] if form["display_name"] != "불량" else ["노출상품명 오류"])
    monkeypatch.setattr(A, "build_product_payload", lambda form, vid, approve, meta: {"name": form["display_name"], "requested": approve})
    monkeypatch.setattr(A.client, "create_product", lambda p: sent.append(p) or {"code": "SUCCESS", "data": "777"})
    a, b, skip = _draft("선택A"), _draft("불량"), _draft("안 고름")
    c = A.app.test_client()
    r = c.post("/register/drafts/submit", data={"draft_ids": [str(a), str(b)], "request_approval": "1"},
               follow_redirects=True).get_data(as_text=True)
    r = html.unescape(r)
    assert sent == [{"name": "선택A", "requested": True}]              # 고른 것 중 검사 통과한 것만, 안 고른 건 그대로
    assert "선택 등록: 성공 1건 / 실패 1건" in r and "'불량' 등록 안 함: 노출상품명 오류" in r
    assert "sellerProductId=777" in A.store.draft(a)["note"] and not A.store.draft(skip)["note"]
    r = c.post("/register/drafts/submit", follow_redirects=True).get_data(as_text=True)
    assert "등록할 임시저장을 선택하세요" in r
    for d in (a, b, skip):
        A.store.delete_draft(d)
