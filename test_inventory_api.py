"""새 화면(React)이 쓰는 재고 동작 API.

여기서 꼭 지켜야 할 것: 참/거짓은 JSON 에서도 참/거짓이어야 한다.
SQLite 가 0/1 정수를 주는데 그대로 넘기면 받는 쪽이 boolean 인 줄 알고 1 을
거짓으로 다룬다 — 실제로 화면의 판매 스위치가 전부 꺼진 채로 나왔다.
"""
import os
import tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import pytest  # noqa: E402

import app as A  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_store():
    """테스트가 DB 를 공유한다. 여기서 켜고 끄고 지운 것을 되돌려 다른 파일을 망치지 않는다.

    (되돌리지 않았을 때 test_smoke 의 주력상품 테스트 2개가 실제로 깨졌다.)
    """
    before = {i["vendor_item_id"]: dict(i) for i in A.store.items()}
    yield
    A.sync.run_once()  # 지운 상품을 모의 백엔드에서 다시 받아온다
    for vid, row in before.items():
        if A.store.item(vid) is None:
            continue
        A.store.update_rule(vid, featured=row["featured"], low_stock=row["low_stock"],
                            auto_stopped=row["auto_stopped"])
        A.store.set_item_field(vid, "stock", row["stock"])
        A.store.set_item_field(vid, "on_sale", row["on_sale"])


def _client():
    A.sync.run_once()
    return A.app.test_client()


def _any_item() -> dict:
    return A.store.items()[0]


def _stored(vid: str) -> dict:
    """store.item 은 None 일 수 있다. 테스트에서는 없으면 그 자리에서 실패해야 한다."""
    item = A.store.item(vid)
    assert item is not None, f"{vid} 가 없다"
    return item


def test_inventory_api_sends_real_booleans_not_sqlite_ints():
    """1/0 을 그대로 내보내면 화면이 1 을 꺼진 상태로 그린다. 그 회귀를 막는다."""
    body = _client().get("/api/inventory").get_json()
    assert body["items"], "모의 동기화가 상품을 만들어야 한다"
    for item in body["items"]:
        for flag in ("on_sale", "featured", "auto_stopped"):
            assert isinstance(item[flag], bool), f"{flag} 가 {type(item[flag])} 로 나왔다"


def test_toggle_featured_flips_and_answers_with_the_new_state():
    c = _client()
    vid = _any_item()["vendor_item_id"]
    before = bool(_stored(vid)["featured"])
    item = c.post(f"/api/items/{vid}/featured").get_json()["item"]
    assert item["featured"] is (not before)
    assert bool(_stored(vid)["featured"]) is (not before)


def test_stock_update_reaches_the_store():
    c = _client()
    vid = _any_item()["vendor_item_id"]
    res = c.post(f"/api/items/{vid}/stock", json={"stock": "77", "low_stock": "9"})
    assert res.status_code == 200
    assert _stored(vid)["stock"] == 77
    assert _stored(vid)["low_stock"] == 9


def test_stock_update_without_a_number_only_changes_the_threshold():
    """기준만 고친 줄은 재고를 건드리지 않아야 한다 — 쿠팡에 쓸데없는 수량 변경을 보내지 않는다."""
    c = _client()
    vid = _any_item()["vendor_item_id"]
    c.post(f"/api/items/{vid}/stock", json={"stock": "50", "low_stock": "3"})
    c.post(f"/api/items/{vid}/stock", json={"stock": "", "low_stock": "8"})
    assert _stored(vid)["stock"] == 50
    assert _stored(vid)["low_stock"] == 8


def test_delete_needs_the_confirm_word():
    c = _client()
    spid = _any_item()["seller_product_id"]
    res = c.post("/api/items/delete", json={"seller_product_id": [spid], "confirm": "네"})
    assert res.status_code == 400
    assert "삭제" in res.get_json()["error"]
    # 거부당한 요청이 상품을 지우지 않았음을 확인한다
    assert any(i["seller_product_id"] == spid for i in A.store.items())


def test_actions_on_an_unknown_item_answer_404_instead_of_crashing():
    c = _client()
    for path in ("featured", "sale", "stock"):
        res = c.post(f"/api/items/does-not-exist/{path}", json={})
        assert res.status_code == 404, f"{path} 가 {res.status_code} 를 냈다"
