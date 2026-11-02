"""텔레그램 시간대 · 빈도(실시간/10분/1시간) · 가격 변동 알림(내 가격/경쟁가/최저가)."""
import os, tempfile
from datetime import datetime

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import notifier as N  # noqa: E402


class Sent(list):
    def __call__(self, url, json=None, timeout=None):
        self.append(json["text"])
        return type("R", (), {"json": lambda s: {"ok": True, "result": {}}, "status_code": 200})()


def _n(monkeypatch, **tg):
    sent = Sent()
    monkeypatch.setattr(N.requests, "post", sent)
    base = {"enabled": True, "token": "t", "chat_id": "1",
            "topics": ["stock", "price", "my_price", "competitor", "lowest"]}
    clock = {"now": datetime(2026, 11, 2, 9, 3)}
    n = N.TelegramNotifier({"telegram": {**base, **tg}}, clock=lambda: clock["now"], start=False, settle_sec=0)
    return n, sent, clock


def test_window_helpers():
    t = lambda h, m: datetime(2026, 1, 1, h, m)
    assert N.in_window(t(3, 0), "00:00", "00:00")                       # 같으면 하루 종일
    assert N.in_window(t(9, 0), "09:00", "18:00") and not N.in_window(t(18, 0), "09:00", "18:00")
    assert N.in_window(t(23, 30), "22:00", "07:00") and N.in_window(t(6, 59), "22:00", "07:00")
    assert not N.in_window(t(12, 0), "22:00", "07:00")
    assert N.next_boundary(t(9, 3), 10) == t(9, 10) and N.next_boundary(t(9, 10), 10) == t(9, 20)
    assert N.next_boundary(t(9, 3), 60) == t(10, 0)


def test_ten_minute_batch_merges_same_item(monkeypatch):
    n, sent, clock = _n(monkeypatch, frequency="10m")
    n.on_alert("info", "lowest", "x", key="v1", name="텀블러", old=15000, new=14800, mine=15900)
    n.on_alert("warn", "stock", "재고 부족(3개): 텀블러")
    clock["now"] = datetime(2026, 11, 2, 9, 7)
    n.on_alert("info", "lowest", "x", key="v1", name="텀블러", old=14800, new=14500, mine=15900)
    n.tick()
    assert sent == [] and n.next_flush == datetime(2026, 11, 2, 9, 10)  # 정각 단위 전까지 대기
    clock["now"] = datetime(2026, 11, 2, 9, 10, 1)
    n.tick()
    assert len(sent) == 1
    msg = sent[0]
    assert "요약 (3건)" in msg and "📦 재고 (1)" in msg and "📉 최저가 변동 (1)" in msg
    assert "15,000 → 14,500원" in msg and "(2회 변동)" in msg and "1,400원 비쌈" in msg
    assert n.next_flush == datetime(2026, 11, 2, 9, 20)


def test_outside_window_hold_then_send_at_start(monkeypatch):
    n, sent, clock = _n(monkeypatch, send_from="09:00", send_to="18:00")
    clock["now"] = datetime(2026, 11, 2, 22, 0)
    n.on_alert("info", "my_price", "x", key="v1", name="이어폰", old=29900, new=28900)
    n.tick()
    assert sent == [] and n.pending_count == 1
    clock["now"] = datetime(2026, 11, 3, 9, 0)
    n.tick()
    assert len(sent) == 1 and "내 가격 29,900 → 28,900원" in sent[0]


def test_outside_window_drop(monkeypatch):
    n, sent, clock = _n(monkeypatch, send_from="09:00", send_to="18:00", outside="drop")
    clock["now"] = datetime(2026, 11, 2, 22, 0)
    n.on_alert("warn", "stock", "재고 부족(1개): A")
    assert n.pending_count == 0


def test_competitor_merge_and_unselected_topic(monkeypatch):
    n, sent, _ = _n(monkeypatch, topics=["competitor"])
    n.on_alert("info", "lowest", "x", key="v", name="A", old=1, new=2, mine=3)   # 선택 안 함
    n.on_alert("info", "competitor", "x", key="v", name="케이블", changes={"판매자A": (8900, 8800)})
    n.on_alert("info", "competitor", "x", key="v", name="케이블", changes={"판매자A": (8800, 8700), "판매자C": (None, 8500)})
    n.tick()
    assert len(sent) == 1 and "판매자A 8,900→8,700" in sent[0] and "판매자C 신규 8,500" in sent[0] and "최저가" not in sent[0]


def test_sync_emits_price_events_but_not_on_live_with_mock_competitors():
    from mock_backend import MockCompetitorProvider, MockCoupangClient
    from services import SyncService
    from store import Store

    def run(client):
        st = Store(os.path.join(tempfile.mkdtemp(), "e.db"))
        comp = MockCompetitorProvider()
        sync = SyncService(client, st, comp, {"auto_soldout": False})
        got = []
        sync.event_listeners.append(lambda lv, kind, msg, **m: got.append((kind, m)))
        sync.run_once()
        assert got == []                                      # 첫 수집은 비교 대상 없음
        vid = st.items()[0]["vendor_item_id"]
        comp._base[vid] = [("판매자A", 100)]
        client.update_price(vid, 12345)                       # WING에서 직접 바꾼 상황
        sync.run_once()
        return vid, got

    vid, got = run(MockCoupangClient())
    kinds = {(k, m["key"]) for k, m in got}
    assert ("my_price", vid) in kinds and ("lowest", vid) in kinds and ("competitor", vid) in kinds
    mp = next(m for k, m in got if k == "my_price" and m["key"] == vid)
    assert mp["new"] == 12345

    class Live(MockCoupangClient):
        mode = "live"
    _, got = run(Live())
    assert {k for k, _ in got} == {"my_price"}               # 가짜 경쟁가로는 알림 안 보냄


def test_realtime_waits_for_cycle_to_settle(monkeypatch):
    import time as _t
    sent = Sent()
    monkeypatch.setattr(N.requests, "post", sent)
    n = N.TelegramNotifier({"telegram": {"enabled": True, "token": "t", "chat_id": "1", "topics": ["stock"]}},
                           start=False, settle_sec=0.3)
    n.on_alert("warn", "stock", "재고 부족(3개): A")
    n.tick()
    assert sent == []                      # 같은 동기화의 다른 알림이 더 올 수 있어 잠깐 대기
    n.on_alert("warn", "stock", "재고 부족(2개): B")
    _t.sleep(0.35); n.tick()
    assert len(sent) == 1 and "요약 (2건)" in sent[0]


def test_switching_to_drop_discards_already_held(monkeypatch):
    n, sent, clock = _n(monkeypatch, send_from="09:00", send_to="18:00")
    clock["now"] = datetime(2026, 11, 2, 22, 0)
    n.on_alert("warn", "stock", "재고 부족(1개): A")
    n.tick(); assert n.pending_count == 1                 # 모아두기
    n.cfg["telegram"]["outside"] = "drop"
    n.tick(); assert n.pending_count == 0
    clock["now"] = datetime(2026, 11, 3, 9, 0)
    n.tick(); assert sent == []
