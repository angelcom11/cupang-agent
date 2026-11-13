"""경쟁가 비교: 경쟁 판매자를 누르면 그 판매자의 쿠팡 샵으로."""
import app as A
import competitor_shop as CS


def test_shop_url_only_coupang():
    assert CS.shop_url("a00012345") == "https://shop.coupang.com/A00012345"
    assert CS.shop_url("shop.coupang.com/A00012345") == "https://shop.coupang.com/A00012345"
    assert CS.shop_url("http://www.coupang.com/vp/products/1?vendorItemId=2") == "https://www.coupang.com/vp/products/1?vendorItemId=2"
    for bad in ("javascript:alert(1)", "https://evil.com/shop.coupang.com", "https://shop.coupang.com.evil.com/x",
                "https://user@shop.coupang.com/", "판매자A", ""):
        assert CS.shop_url(bad) is None, bad


def test_provider_link_and_saved_link_on_prices_page():
    A.store.upsert_items([{"vendor_item_id": "v-shop", "seller_product_id": "s1", "name": "샵 테스트", "sale_price": 10000,
                           "stock": 10, "on_sale": True, "status": "승인완료"}])
    A.store.add_competitor_prices("v-shop", 10000, [
        {"seller": "공급자제공", "price": 9900, "vendor_id": "A00011111"},
        {"seller": "미등록판매자", "price": 9800, "url": ""}])
    c = A.app.test_client()
    row = next(r for r in c.get("/api/prices").get_json()["rows"] if r["vendor_item_id"] == "v-shop")
    shops = {x["seller"]: (x["shop"], x["shop_source"]) for x in row["competitors"]}
    assert shops == {"공급자제공": ("https://shop.coupang.com/A00011111", "provider"), "미등록판매자": (None, None)}
    r = c.post("/api/competitor-shop", json={"seller": "미등록판매자", "url": "https://evil.com"})
    assert r.status_code == 400
    r = c.post("/api/competitor-shop", json={"seller": "미등록판매자", "url": "A00022222"})
    assert r.get_json()["shop"] == "https://shop.coupang.com/A00022222"
    row = next(r for r in c.get("/api/prices").get_json()["rows"] if r["vendor_item_id"] == "v-shop")
    assert {x["seller"]: x["shop_source"] for x in row["competitors"]}["미등록판매자"] == "saved"
    assert "data-comps=" in c.get("/classic/prices").get_data(as_text=True)
    c.post("/api/competitor-shop", json={"seller": "미등록판매자", "url": ""})          # 지우기
    assert "미등록판매자" not in A.store.competitor_shops()
