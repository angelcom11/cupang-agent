"""경쟁가 비교 화면이 쓰는 API, 그리고 자동 가격조정의 방향.

자동조정은 **가격을 내릴 뿐 올리지 않는다** (services.py 의 _check_price 에서
`lowest >= sale_price` 면 그냥 반환한다). 이게 깨지면 돈이 걸린 문제라서 고정한다.
"""
import os
import tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import pytest  # noqa: E402

import app as A  # noqa: E402


@pytest.fixture(autouse=True)
def _restore_store():
    """테스트가 DB 를 공유한다. 여기서 바꾼 규칙을 되돌린다."""
    before = {i["vendor_item_id"]: dict(i) for i in A.store.items()}
    yield
    for vid, row in before.items():
        if A.store.item(vid) is None:
            continue
        A.store.update_rule(vid, auto_reprice=row["auto_reprice"], undercut=row["undercut"],
                            min_price=row["min_price"], featured=row["featured"])
        A.store.set_item_field(vid, "sale_price", row["sale_price"])


def _client():
    A.sync.run_once()
    return A.app.test_client()


def _stored(vid: str) -> dict:
    item = A.store.item(vid)
    assert item is not None, f"{vid} 가 없다"
    return item


def test_prices_api_carries_what_the_screen_needs():
    body = _client().get("/api/prices").get_json()
    assert body["rows"], "모의 동기화가 상품을 만들어야 한다"
    row = body["rows"][0]
    for key in ("competitors", "history", "auto_reprice", "undercut", "min_price", "rank", "total"):
        assert key in row, f"{key} 가 빠졌다"
    assert isinstance(row["auto_reprice"], bool), "SQLite 의 0/1 을 그대로 내보내면 안 된다"


def test_price_history_is_kept_for_the_trend_panel():
    """예전 /api/prices 는 history 를 떼어 보냈다. 추이 화면이 그걸 쓴다."""
    row = _client().get("/api/prices").get_json()["rows"][0]
    assert row["history"], "추이 기록이 있어야 한다"
    assert set(row["history"][0]) == {"at", "low", "mine"}


def test_saving_a_rule_reaches_the_store():
    c = _client()
    vid = A.store.items()[0]["vendor_item_id"]
    res = c.post("/api/prices/rule", json={
        "vendor_item_id": vid, "auto_reprice": True, "undercut": 70, "min_price": 5000,
    })
    assert res.status_code == 200
    saved = _stored(vid)
    assert saved["auto_reprice"] == 1
    assert saved["undercut"] == 70
    assert saved["min_price"] == 5000


def test_rule_on_an_unknown_item_answers_404():
    res = _client().post("/api/prices/rule", json={"vendor_item_id": "nope", "auto_reprice": True})
    assert res.status_code == 404


def _watch_price_calls(monkeypatch) -> list:
    """update_price 호출을 기록한다. 쿠팡에 실제로 가격을 쓰는 유일한 길이다."""
    calls = []
    monkeypatch.setattr(A.client, "update_price", lambda v, p: calls.append((v, p)))
    return calls


def _check_with_competitor(monkeypatch, item: dict, competitor_price: int) -> list:
    """경쟁 호가를 하나로 고정해 _check_price 를 돌린다.

    run_once() 를 쓰면 안 된다: 먼저 fetch_items() 가 돌아 쿠팡(모의)의 가격으로
    sale_price 를 덮어쓰기 때문에, 테스트가 심은 가격이 사라진다.
    """
    monkeypatch.setattr(
        A.sync.provider, "fetch",
        lambda _it: [{"seller": "경쟁사", "price": competitor_price, "url": ""}])
    calls = _watch_price_calls(monkeypatch)
    A.sync._check_price(item)
    return calls


def test_auto_reprice_never_raises_the_price(monkeypatch):
    """경쟁 최저가 내 가격보다 높을 때 가격을 올리면 안 된다.

    화면이 "가격을 올리지도 않습니다" 라고 약속한다. 그 약속을 코드로 묶는다.
    """
    vid = A.store.items()[0]["vendor_item_id"]
    A.store.update_rule(vid, auto_reprice=1, undercut=50, min_price=0)
    item = {**_stored(vid), "sale_price": 1000}

    calls = _check_with_competitor(monkeypatch, item, competitor_price=9000)

    assert calls == [], f"가격을 올리려 했다: {calls}"


def test_auto_reprice_lowers_when_a_competitor_is_cheaper(monkeypatch):
    """반대 방향도 확인한다 — 안 올린다는 게 아무것도 안 한다는 뜻이면 안 된다."""
    vid = A.store.items()[0]["vendor_item_id"]
    A.store.update_rule(vid, auto_reprice=1, undercut=50, min_price=0)
    item = {**_stored(vid), "sale_price": 9000}

    calls = _check_with_competitor(monkeypatch, item, competitor_price=8000)

    assert calls == [(vid, 7950)], f"8000 - 50 = 7950 으로 내려야 한다: {calls}"


def test_auto_reprice_stops_at_the_floor(monkeypatch):
    """하한가 아래로는 내리지 않고 알림만 남긴다."""
    vid = A.store.items()[0]["vendor_item_id"]
    A.store.update_rule(vid, auto_reprice=1, undercut=0, min_price=8500)
    item = {**_stored(vid), "sale_price": 9000}

    calls = _check_with_competitor(monkeypatch, item, competitor_price=8000)

    assert calls == [], f"하한가 8500 아래로 내렸다: {calls}"
    assert any("하한가" in a["message"] for a in A.store.alerts(30)), "하한가 알림이 없다"
