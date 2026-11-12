"""모의 모드 스모크 테스트: 서명, 동기화, 자동조정, 자동품절, 주력상품, 키 설정, 등록, 전 페이지 렌더."""
import hashlib, hmac, io, os, re, stat, tempfile

os.environ["WING_DATA_DIR"] = tempfile.mkdtemp()
import app as A  # noqa: E402
from coupang_client import CoupangClient  # noqa: E402

# 판매자 설정(출고지·반품지·WING 아이디)을 마친 상태 — 모의 클라이언트의 출고지/반품지 코드
A.cfg["register_defaults"] = {"outbound_place_code": "100001", "return_center_code": "1000005678",
                              "vendor_user_id": "tester"}


def test_signature_format():
    c = CoupangClient("ak", "sk", "V1")
    h = c._authorization("GET", "/p", "a=1")
    m = re.match(r"CEA algorithm=HmacSHA256, access-key=ak, signed-date=(\S+), signature=(\w+)", h)
    d, sig = m.groups()
    assert sig == hmac.new(b"sk", f"{d}GET/pa=1".encode(), hashlib.sha256).hexdigest()


def _item(name):
    return next(i for i in A.store.items() if i["name"] == name)


def test_auto_soldout_and_resume(monkeypatch):
    import mock_backend
    monkeypatch.setattr(mock_backend.random, "random", lambda: 0.5)  # 모의 재고 변동(주문/입고) 끄기
    # 앞선 테스트의 fetch_items() 가 모의 '입고'(5% 확률)로 재고를 바꿨을 수 있으니 시드 상태로 되돌린다
    for it in A.client._items.values():
        if it["name"] == "극세사 차량용 세차타올 5P":
            it.update(stock=0, on_sale=True)
    A.sync.run_once()
    towel = _item("극세사 차량용 세차타올 5P")  # 시드 재고 0
    assert not towel["on_sale"] and towel["auto_stopped"]
    assert A.client._items[towel["vendor_item_id"]]["on_sale"] is False  # 쿠팡(모의)에도 판매중지 호출됨
    c = A.app.test_client()
    c.post("/inventory", data={"vendor_item_id": towel["vendor_item_id"], "stock": "30", "low_stock": "5"})
    towel = _item("극세사 차량용 세차타올 5P")
    assert towel["on_sale"] and not towel["auto_stopped"]  # 입고 즉시 자동 재개
    # 수동 중지한 상품은 재고가 있어도 자동 재개하지 않음
    c.post(f"/items/{towel['vendor_item_id']}/sale")
    A.sync.run_once()
    assert not _item("극세사 차량용 세차타올 5P")["on_sale"]


def test_featured_on_dashboard():
    c = A.app.test_client()
    vid = _item("캠핑용 LED 랜턴")["vendor_item_id"]
    assert "fcard" not in c.get("/").get_data(as_text=True)
    c.post(f"/items/{vid}/featured")
    html = c.get("/").get_data(as_text=True)
    assert "fcard" in html and "캠핑용 LED 랜턴" in html.split("fgrid")[1].split("</section>")[0]


def test_featured_card_links_to_that_item_in_inventory():
    """주력 상품 카드를 누르면 재고 관리의 그 상품 행으로 간다 (대시보드 → #item-<옵션ID>)."""
    c = A.app.test_client()
    vid = _item("캠핑용 LED 랜턴")["vendor_item_id"]
    if "fcard" not in c.get("/").get_data(as_text=True):
        c.post(f"/items/{vid}/featured")

    card = c.get("/").get_data(as_text=True).split("fgrid")[1].split("</section>")[0]
    # 카드가 링크여야 하고, 가리키는 곳이 재고 관리의 그 옵션이어야 한다
    assert f'href="/inventory#item-{vid}"' in card, "카드가 재고 관리의 해당 상품을 가리켜야 한다"
    assert "<a class=\"fcard" in card, "카드 전체가 눌리는 링크여야 한다"

    # 그 자리가 재고 관리에 실제로 있어야 한다 — 없으면 눌러도 아무 데도 안 간다
    inv = c.get("/inventory").get_data(as_text=True)
    assert f'id="item-{vid}"' in inv, "재고 관리 행에 링크가 가리키는 id 가 있어야 한다"


def test_settings_keys_saved_and_masked():
    c = A.app.test_client()
    c.post("/settings", data={"action": "save_keys", "vendor_id": "A123", "access_key": "AK-TEST", "secret_key": "SK-SECRET"})
    assert A.client.mode == "live" and A.sync.client is A.client
    if os.name == "posix":  # Windows 는 권한 비트 대신 ACL: 사용자 폴더 기본 권한을 따른다
        assert stat.S_IMODE(os.stat(A.CONFIG_PATH).st_mode) == 0o600
    html = c.get("/settings").get_data(as_text=True)
    assert "SK-SECRET" not in html and "AK-TEST" not in html and "저장됨" in html
    c.post("/settings", data={"action": "save_keys", "vendor_id": "", "access_key": "", "secret_key": ""})
    assert A.cfg["secret_key"] == "SK-SECRET"  # 빈칸 저장은 기존 키 유지
    c.post("/settings", data={"action": "clear_keys"})
    assert A.client.mode == "mock" and "secret_key" not in A.cfg
    c.post("/settings", data={"action": "save_rules", "sync_interval_sec": "15", "soldout_threshold": "3"})
    assert A.cfg["sync_interval_sec"] == 15 and A.cfg["soldout_threshold"] == 3 and A.cfg["auto_soldout"] is False


def test_pages_and_register():
    A.sync.run_once()
    vid = A.store.items()[0]["vendor_item_id"]
    A.store.update_rule(vid, auto_reprice=1, min_price=1, undercut=10)
    A.competitor._base[vid] = [("X", 1000)]
    A.sync.run_once()
    assert A.store.item(vid)["sale_price"] < 1100
    c = A.app.test_client()
    for p in ("/", "/inventory", "/prices", "/register", "/settings", "/api/prices", "/api/inventory"):
        assert c.get(p).status_code == 200, p
    csv = open("sample_products.csv", "rb").read()
    r = c.post("/register", data={"action": "csv", "csv_file": (io.BytesIO(csv), "s.csv")},
               content_type="multipart/form-data", follow_redirects=True)
    assert "성공 2건 / 실패 1건" in r.get_data(as_text=True)
