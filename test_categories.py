"""카테고리 목록(기본/API/엑셀), 최하위 검증, 노출·등록 상품명."""
import io, json, os, tempfile
from pathlib import Path

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402
from categories import CategoryError, CategoryStore, nodes_from_api_tree, nodes_from_file  # noqa: E402
from product_form import build_product_payload, validate_form  # noqa: E402

API_TREE = {"displayItemCategoryCode": 0, "name": "ROOT", "status": "ACTIVE", "child": [
    {"displayItemCategoryCode": 80285, "name": "주방용품", "status": "ACTIVE", "child": [
        {"displayItemCategoryCode": 90001, "name": "텀블러", "status": "ACTIVE", "child": []},
        {"displayItemCategoryCode": 90002, "name": "단종", "status": "DISABLED", "child": []}]}]}


def _store(tmp):
    return CategoryStore(Path(tmp) / "c.json")


def test_default_sample_only_documented_and_permissive():
    s = _store(tempfile.mkdtemp())
    assert s.summary()["source"] == "sample" and not s.is_full
    assert s.path_of("79382") == "패션의류잡화 > 여성패션 > 여성의류 > 티셔츠 > 반소매"
    assert s.check("79382") is None
    assert "하위 분류" in s.check("79268")       # 중간 단계는 등록 불가
    assert s.check("12345") is None               # 일부 목록일 때는 모르는 코드 허용


def test_api_tree_replaces_and_validates_strictly():
    s = _store(tempfile.mkdtemp())
    s.replace(nodes_from_api_tree(API_TREE), "api")
    assert s.is_full and s.summary()["count"] == 2 and s.leaves == {"90001"}
    assert s.check("90002") and "목록에 없습니다" in s.check("90002")   # DISABLED 제외
    assert s.check("90001") is None
    assert _store(s.path.parent).summary()["count"] == 2              # 파일로 저장돼 재시작 후 유지


def test_excel_with_depth_columns():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["전체 카테고리 정보"])
    ws.append(["노출카테고리코드", "1depth", "2depth", "3depth", "수수료율"])
    ws.append([90001, "주방용품", "보온/보냉용품", "텀블러", 10.8])
    ws.append([90003, "주방용품", "보온/보냉용품", "보온병", 10.8])
    ws.append([90010, "생활용품", "세탁용품", None, 7.8])
    buf = io.BytesIO(); wb.save(buf)
    nodes = nodes_from_file("cats.xlsx", buf.getvalue())
    s = _store(tempfile.mkdtemp()); s.replace(nodes, "file")
    assert s.leaves == {"90001", "90003", "90010"}
    assert s.path_of("90003") == "주방용품 > 보온/보냉용품 > 보온병"


def test_csv_with_path_column_and_bad_files():
    data = "카테고리코드,카테고리 경로\n90001,주방용품>텀블러\n".encode("cp949")
    assert [n["n"] for n in nodes_from_file("c.csv", data)] == ["주방용품", "텀블러"]
    for name, blob in (("x.xlsx", b"not a zip"), ("x.txt", b"a"), ("c.csv", "a,b\n1,2\n".encode())):
        try:
            nodes_from_file(name, blob)
            raise AssertionError(name)
        except CategoryError:
            pass


def test_names_in_payload():
    p = build_product_payload({"display_name": "여성 반팔티", "name": "TS-001", "category_code": "79382",
                               "sale_price": "1000"}, "V")
    assert (p["displayProductName"], p["sellerProductName"], p["generalProductName"]) == ("여성 반팔티", "TS-001", "여성 반팔티")
    p2 = build_product_payload({"display_name": "여성 반팔티", "category_code": "79382", "sale_price": "1"}, "V")
    assert p2["sellerProductName"] == "여성 반팔티"   # 등록상품명 비우면 노출상품명
    assert "노출상품명은(는) 필수입니다" in validate_form({"name": "", "category_code": "1", "sale_price": "1"})


def test_register_page_rejects_middle_category_and_legacy_draft():
    c = A.app.test_client()
    html = c.post("/register", data={"action": "submit", "display_name": "x", "category_code": "79268",
                                     "sale_price": "1000"}).get_data(as_text=True)
    assert "마지막 단계" in html
    did = A.store.save_draft({"name": "옛날 상품명", "category_code": "79382"})
    html = c.get(f"/register?draft_id={did}").get_data(as_text=True)
    assert 'name="display_name" value="옛날 상품명"' in html and 'name="name" value=""' in html
    assert "반소매 (79382)" in html
    data = c.get("/api/categories").get_json()
    assert data["source"] == "sample" and any(n["c"] == "79382" for n in data["nodes"])


def test_live_with_mock_competitors_never_reprices_and_prunes_other_mode_items():
    from mock_backend import MockCompetitorProvider
    from services import SyncService
    from store import Store

    calls = []

    class LiveStub:
        mode = "live"

        def fetch_items(self):
            return [{"vendor_item_id": "1", "seller_product_id": "9", "name": "실상품", "sale_price": 10000,
                     "stock": 50, "on_sale": True, "status": "승인완료"}]

        def update_price(self, *a):
            calls.append(a)

    st = Store(os.path.join(tempfile.mkdtemp(), "t.db"))
    st.upsert_items([{"vendor_item_id": "700", "seller_product_id": "1", "name": "모의상품", "sale_price": 1,
                      "stock": 1, "on_sale": True, "status": ""}])
    comp = MockCompetitorProvider()
    comp._base["1"] = [("X", 5000)]
    st.upsert_items(LiveStub().fetch_items())
    st.update_rule("1", auto_reprice=1)
    sync = SyncService(LiveStub(), st, comp, {"auto_soldout": False})
    sync.run_once()
    assert [i["vendor_item_id"] for i in st.items()] == ["1"]          # 모의 상품 제거
    assert calls == [] and st.item("1")["sale_price"] == 10000          # 가짜 경쟁가로 실제 가격 변경 없음
    assert not any(a["kind"] == "price" for a in st.alerts())
    assert sync.last_error is None


def test_delete_product_rules():
    """쿠팡 조건대로: 판매중이면 거부(판매중지 동의 시 중지 후 삭제), 확인 문구 필수, 승인대기 거부."""
    from mock_backend import MockCoupangClient
    from services import SyncService
    from store import Store

    st = Store(os.path.join(tempfile.mkdtemp(), "d.db"))
    cl = MockCoupangClient()
    sync = SyncService(cl, st, type("P", (), {"name": "x", "fetch": lambda s, i: []})(), {"auto_soldout": False})
    sync.run_once()
    a, b = st.items()[0], st.items()[1]
    assert a["on_sale"]
    name, ok, msg = sync.delete_products([a["seller_product_id"]], stop_first=False)[0]
    assert not ok and "판매중" in msg and st.item(a["vendor_item_id"])     # 동의 없으면 아무것도 안 바뀜
    assert cl._items[a["vendor_item_id"]]["on_sale"] is True
    name, ok, msg = sync.delete_products([a["seller_product_id"]], stop_first=True)[0]
    assert ok and st.item(a["vendor_item_id"]) is None and a["vendor_item_id"] not in cl._items
    sync.run_once()
    assert st.item(a["vendor_item_id"]) is None                          # 다음 동기화에도 다시 안 생김
    st._q("UPDATE items SET status='승인대기중' WHERE vendor_item_id=?", (b["vendor_item_id"],))
    assert not sync.delete_products([b["seller_product_id"]], True)[0][1]
    assert cl._items[b["vendor_item_id"]]["on_sale"] is True               # 승인대기는 판매중지도 하지 않음


def test_delete_route_requires_confirm_text():
    c = A.app.test_client()
    A.sync.run_once()
    assert A.client.mode == "mock"
    item = A.store.items()[0]
    r = c.post("/items/delete", data={"seller_product_id": item["seller_product_id"], "confirm": "네",
                                      "stop_first": "1"}, follow_redirects=True)
    assert "정확히 입력" in r.get_data(as_text=True) and A.store.item(item["vendor_item_id"])
    r = c.post("/items/delete", data={"seller_product_id": item["seller_product_id"], "confirm": "삭제",
                                      "stop_first": "1"}, follow_redirects=True)
    assert "삭제 완료" in r.get_data(as_text=True) and A.store.item(item["vendor_item_id"]) is None
