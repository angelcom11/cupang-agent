"""상품 등록: 임시저장, 이미지 업로드, CSV 템플릿, 상세설명 정리."""
import io, os, struct, tempfile, zlib

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402
from services import clean_html, parse_csv  # noqa: E402

# 판매자 설정(출고지·반품지·WING 아이디)을 마친 상태 — 모의 클라이언트의 출고지/반품지 코드
A.cfg["register_defaults"] = {"outbound_place_code": "100001", "return_center_code": "1000005678",
                              "vendor_user_id": "tester"}


def _png() -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def test_draft_without_required_fields_then_reload():
    c = A.app.test_client()
    r = c.post("/register", data={"action": "draft", "display_name": "작성중 상품", "description_html": "<p>설명</p>"})
    assert r.status_code == 302 and "draft_id=" in r.location
    html = c.get(r.location).get_data(as_text=True)
    assert 'value="작성중 상품"' in html and "&lt;p&gt;설명&lt;/p&gt;" in html and "편집 중" in html


def test_submit_keeps_form_and_draft_after_success_and_failure():
    c = A.app.test_client()
    data = {"action": "submit", "display_name": "등록상품", "category_code": "79382", "sale_price": "1000",
            "image_url": "https://example.com/a.jpg",
            "description_html": '<p onclick="x()">ok</p><script>alert(1)</script>'}
    r = c.post("/register", data=data)
    assert r.status_code == 302 and "draft_id=" in r.location
    d = A.store.draft(int(r.location.split("draft_id=")[1].split("&")[0]))
    assert d["note"].startswith("[모의] 등록 완료") and d["data"]["description_html"] == "<p>ok</p>"
    # 등록 후에도 같은 임시저장에 다시 저장 가능
    r2 = c.post("/register", data={**data, "action": "draft", "draft_id": d["id"], "display_name": "등록상품 v2"})
    assert A.store.draft(d["id"])["data"]["display_name"] == "등록상품 v2"
    # 필수값 누락 시 입력값을 잃지 않음
    html = c.post("/register", data={"action": "submit", "display_name": "누락상품"}).get_data(as_text=True)
    assert 'value="누락상품"' in html and "필수입니다" in html


def test_upload_image_and_reject_non_image():
    c = A.app.test_client()
    r = c.post("/api/upload", data={"file": (io.BytesIO(_png()), "a.png")}, content_type="multipart/form-data")
    url = r.get_json()["url"]
    assert r.status_code == 200 and url.endswith(".png")
    assert c.get(url.split("localhost", 1)[1]).data == _png()
    bad = c.post("/api/upload", data={"file": (io.BytesIO(b"<html>"), "x.png")}, content_type="multipart/form-data")
    assert bad.status_code == 400 and "이미지만" in bad.get_json()["error"]
    big = c.post("/api/upload", data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * (11 * 1024 * 1024)), "b.png")},
                 content_type="multipart/form-data")
    assert big.status_code == 413


def test_csv_template_download_roundtrip():
    c = A.app.test_client()
    r = c.get("/register/template.csv")
    assert "attachment" in r.headers["Content-Disposition"]
    text = r.data.decode("utf-8")
    assert text.startswith("\ufeff노출상품명*,등록상품명(판매자관리용),카테고리코드*")
    assert parse_csv(text) == []  # [예시] 행은 건너뜀
    filled = text + '내 상품,관리용-01,79381,,,,9900,10,https://example.com/a.jpg,0,,,수량=1개\n'
    rows = parse_csv(filled)
    assert rows == [{**{k: "" for k in rows[0]}, "display_name": "내 상품", "name": "관리용-01",
                     "category_code": "79381", "sale_price": "9900", "stock": "10", "delivery_charge": "0",
                     "image_url": "https://example.com/a.jpg", "attrs_text": "수량=1개"}]
    up = c.post("/register", data={"action": "csv", "csv_file": (io.BytesIO(filled.encode("utf-8")), "t.csv")},
                content_type="multipart/form-data", follow_redirects=True)
    assert "성공 1건 / 실패 0건" in up.get_data(as_text=True)


def test_clean_html():
    assert clean_html('<a href="javascript:alert(1)" onmouseover=\'x\'>a</a><iframe src=x></iframe>') == '<a href="#">a</a>'
    assert clean_html('<p style="color:red"><b>굵게</b></p><img src="https://x/y.png">') == \
        '<p style="color:red"><b>굵게</b></p><img src="https://x/y.png">'


def test_invalid_settings_change_nothing():
    c = A.app.test_client()
    before = dict(A.cfg)
    c.post("/classic/settings", data={"action": "save_rules", "sync_interval_sec": "99", "soldout_threshold": "7",
                              "public_base_url": "nohttp.com"})
    assert {k: A.cfg.get(k) for k in before} == before
