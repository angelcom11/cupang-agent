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
    c.post("/classic/inventory", data={"vendor_item_id": towel["vendor_item_id"], "stock": "30", "low_stock": "5"})
    towel = _item("극세사 차량용 세차타올 5P")
    assert towel["on_sale"] and not towel["auto_stopped"]  # 입고 즉시 자동 재개
    # 수동 중지한 상품은 재고가 있어도 자동 재개하지 않음
    c.post(f"/items/{towel['vendor_item_id']}/sale")
    A.sync.run_once()
    assert not _item("극세사 차량용 세차타올 5P")["on_sale"]


def test_featured_on_dashboard():
    c = A.app.test_client()
    vid = _item("캠핑용 LED 랜턴")["vendor_item_id"]
    assert "fcard" not in c.get("/classic/").get_data(as_text=True)
    c.post(f"/items/{vid}/featured")
    html = c.get("/classic/").get_data(as_text=True)
    assert "fcard" in html and "캠핑용 LED 랜턴" in html.split("fgrid")[1].split("</section>")[0]


def test_featured_card_links_to_that_item_in_inventory():
    """주력 상품 카드를 누르면 재고 관리의 그 상품 행으로 간다 (대시보드 → #item-<옵션ID>)."""
    c = A.app.test_client()
    vid = _item("캠핑용 LED 랜턴")["vendor_item_id"]
    if "fcard" not in c.get("/classic/").get_data(as_text=True):
        c.post(f"/items/{vid}/featured")

    card = c.get("/classic/").get_data(as_text=True).split("fgrid")[1].split("</section>")[0]
    # 카드가 링크여야 하고, 가리키는 곳이 재고 관리의 그 옵션이어야 한다
    assert f'href="/classic/inventory#item-{vid}"' in card, "카드가 재고 관리의 해당 상품을 가리켜야 한다"
    assert "<a class=\"fcard" in card, "카드 전체가 눌리는 링크여야 한다"

    # 그 자리가 재고 관리에 실제로 있어야 한다 — 없으면 눌러도 아무 데도 안 간다
    inv = c.get("/classic/inventory").get_data(as_text=True)
    assert f'id="item-{vid}"' in inv, "재고 관리 행에 링크가 가리키는 id 가 있어야 한다"


def test_anchor_target_clears_the_sticky_nav_on_mobile():
    """모바일에서는 .side 가 화면 위에 sticky 로 붙으므로(높이 190px) 앵커 정지 위치가 그보다 커야 한다.

    이게 없으면 카드를 눌러 도착한 행이 상단바 뒤에 가려 보이지 않는다 (실측: 121px 가림).
    """
    css = A.app.test_client().get("/static/style.css").get_data(as_text=True)
    # 파일에 @media(max-width:760px) 가 여럿이라 split 으로 고르면 데스크톱 규칙을 집는다.
    # 모바일 블록 안의 그 규칙만 통째로 찾는다.
    m = re.search(r"@media\(max-width:760px\)\{#inv-table tr\[id\]\{scroll-margin-top:(\d+)px\}\}", css)
    assert m, "모바일에서 #inv-table tr[id] 의 scroll-margin-top 을 따로 줘야 한다"
    assert int(m.group(1)) >= 190, f"상단바(190px)보다 커야 행이 가리지 않는다 (지금 {m.group(1)}px)"


def test_settings_keys_saved_and_masked():
    c = A.app.test_client()
    c.post("/classic/settings", data={"action": "save_keys", "vendor_id": "A123", "access_key": "AK-TEST", "secret_key": "SK-SECRET"})
    assert A.client.mode == "live" and A.sync.client is A.client
    if os.name == "posix":  # Windows 는 권한 비트 대신 ACL: 사용자 폴더 기본 권한을 따른다
        assert stat.S_IMODE(os.stat(A.CONFIG_PATH).st_mode) == 0o600
    html = c.get("/classic/settings").get_data(as_text=True)
    assert "SK-SECRET" not in html and "AK-TEST" not in html and "저장됨" in html
    c.post("/classic/settings", data={"action": "save_keys", "vendor_id": "", "access_key": "", "secret_key": ""})
    assert A.cfg["secret_key"] == "SK-SECRET"  # 빈칸 저장은 기존 키 유지
    c.post("/classic/settings", data={"action": "clear_keys"})
    assert A.client.mode == "mock" and "secret_key" not in A.cfg
    c.post("/classic/settings", data={"action": "save_rules", "sync_interval_sec": "15", "soldout_threshold": "3"})
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


# ---------- 새 화면(React + Astryx) 서빙 ----------
def test_spa_owns_the_root_and_still_needs_login():
    """새 화면이 루트를 쓴다. 기존 화면과 같은 로그인 가드를 받아야 한다."""
    c = A.app.test_client()
    assert c.get("/").status_code == 200

    # 새 화면이 가진 경로는 모두 같은 문서를 준다 — 화면은 브라우저 라우터가 고른다
    for path in ("/inventory", "/prices", "/keywords", "/settings"):
        assert c.get(path).status_code == 200, f"{path} 가 404 다"

    # 로그인을 켜면 막혀야 한다 — 새 화면이 인증 구멍이 되면 안 된다
    A.app.config["WING_LOGIN_REQUIRED"] = True
    try:
        assert c.get("/").status_code in (302, 401)
        assert c.get("/inventory").status_code in (302, 401)
    finally:
        A.app.config["WING_LOGIN_REQUIRED"] = False


def test_links_to_the_new_ui_point_at_the_root():
    """한 함수에 라우트를 여러 개 달면 url_for 가 /settings 를 골랐다.

    그 주소로 '새 화면' 링크와 로그인 후 목적지가 만들어지므로, 설정 화면으로 떨어졌다.
    """
    with A.app.test_request_context():
        assert A.url_for("spa") == "/"


def test_classic_pages_stay_reachable_as_a_way_back():
    """기존 화면을 지우지 않고 /classic/ 에 남겼다. 새 화면이 고장나면 돌아갈 곳이다."""
    c = A.app.test_client()
    for path in ("/classic/", "/classic/inventory", "/classic/prices",
                 "/classic/keywords", "/classic/settings"):
        assert c.get(path).status_code == 200, f"{path} 가 404 다"


def test_old_ui_addresses_still_land_on_the_same_screen():
    """전환 전 새 화면은 /ui 에 있었다. 북마크해 둔 주소가 깨지면 안 된다."""
    c = A.app.test_client()
    for path, expected in (("/ui", "/"), ("/ui/", "/"),
                           ("/ui/inventory", "/inventory"), ("/ui/없는화면", "/")):
        r = c.get(path)
        assert r.status_code == 301, f"{path} 가 {r.status_code} 다"
        assert r.headers["Location"].endswith(expected), f"{path} → {r.headers['Location']}"


def test_jinja_register_stays_reachable_for_the_new_ui_menu():
    """새 UI 의 '상품 등록' 은 아직 기존 화면으로 나가는 바깥 링크다.

    이 경로가 사라지면 새 UI 에서 등록으로 갈 길이 끊긴다.
    """
    assert A.app.test_client().get("/register").status_code == 200


def test_unknown_addresses_still_give_404_not_a_blank_screen():
    """catch-all 로 SPA 를 주면 오타 주소와 /api·/uploads 까지 삼켜 빈 화면이 된다."""
    c = A.app.test_client()
    for path in ("/없는화면", "/inventoryy", "/api/없는것"):
        assert c.get(path).status_code == 404, f"{path} 가 404 가 아니다"


def test_spa_html_carries_the_saved_theme_so_it_does_not_flash():
    """모드를 API 로 받아서 고치면 밝게 떴다가 어두워진다. HTML 에 심어 보낸다."""
    c = A.app.test_client()
    A.cfg["theme"] = "dark"
    assert '<meta name="wing-theme" content="dark">' in c.get("/").get_data(as_text=True)
    A.cfg["theme"] = "네온"  # 알 수 없는 값은 system 으로 떨어진다
    assert 'content="system"' in c.get("/").get_data(as_text=True)
    A.cfg.pop("theme", None)


def test_existing_pages_untouched_while_spa_coexists():
    """전환 중에는 기존 Jinja 화면이 그대로 떠야 한다."""
    c = A.app.test_client()
    for path in ("/", "/inventory", "/prices", "/keywords", "/register", "/settings"):
        assert c.get(path).status_code == 200, f"{path} 가 깨졌다"
