"""텔레그램: 선택한 종류만 전송, 토큰 비노출, 대화 찾기, 반복 억제."""
import os, tempfile, time

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402
import notifier as N  # noqa: E402


class FakeTelegram:
    def __init__(self):
        self.sent = []

    def __call__(self, url, json=None, timeout=None):
        method = url.rsplit("/", 1)[1]
        token = url.split("/bot", 1)[1].split("/", 1)[0]
        ok = token == "123:GOOD"
        if method == "sendMessage" and ok:
            self.sent.append((json["chat_id"], json["text"]))
            body = {"ok": True, "result": {}}
        elif method == "getMe" and ok:
            body = {"ok": True, "result": {"username": "wing_test_bot"}}
        elif method == "getUpdates" and ok:
            body = {"ok": True, "result": [
                {"message": {"chat": {"id": 111, "type": "private", "first_name": "홍길동"}}},
                {"message": {"chat": {"id": -222, "type": "group", "title": "가게 단톡"}}}]}
        else:
            body = {"ok": False, "error_code": 401, "description": "Unauthorized"}
        return type("R", (), {"json": lambda s: body, "status_code": 200 if ok else 401})()


def _wait(pred, sec=6):
    end = time.time() + sec
    while time.time() < end and not pred():
        time.sleep(0.05)
    return pred()


def test_settings_flow_and_topic_filter(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(N.requests, "post", fake)
    c = A.app.test_client()
    r = c.post("/settings/telegram", data={"action": "test", "token": "bad", "chat_id": "1"}, follow_redirects=True)
    assert "봇 토큰이 올바르지 않습니다 (401)" in r.get_data(as_text=True) and not A.cfg.get("telegram")
    r = c.post("/settings/telegram", data={"action": "find_chat", "token": "123:GOOD"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "가게 단톡" in html and A.cfg["telegram"]["chat_id"] == "-222" and "123:GOOD" not in html
    c.post("/settings/telegram", data={"action": "save", "token": "", "chat_id": "111", "enabled": "1",
                                       "topics": ["stock"]})
    assert A.cfg["telegram"]["token"] == "123:GOOD"           # 빈 칸 저장은 기존 토큰 유지
    A.store.alert("danger", "soldout", "자동 품절 처리(재고 1개 < 5개): 테스트상품")
    A.store.alert("info", "reprice", "자동 가격조정: 테스트상품 10,000 → 9,990원")   # 단가변경 미선택 → 안 보냄
    A.store.alert("warn", "price", "최저가 밀림: 테스트")                              # 대상 아님
    assert _wait(lambda: len(fake.sent) == 1)
    time.sleep(0.2)
    assert len(fake.sent) == 1 and fake.sent[0][0] == "111" and "[재고]" in fake.sent[0][1]
    c.post("/settings/telegram", data={"action": "save", "chat_id": "111", "enabled": "1", "topics": ["stock", "price"]})
    A.store.alert("info", "reprice", "자동 가격조정: 테스트상품 9,990 → 9,980원")
    assert _wait(lambda: len(fake.sent) == 2) and "[단가변경]" in fake.sent[1][1]


def test_repeat_cooldown_and_disabled(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(N.requests, "post", fake)
    n = N.TelegramNotifier({"telegram": {"enabled": True, "token": "123:GOOD", "chat_id": "1", "topics": ["stock"]}},
                           start=False, settle_sec=0)
    n.on_alert("warn", "stock", "재고 부족(3개): A")
    n.on_alert("warn", "stock", "재고 부족(3개): A")     # 같은 문장 반복 → 한 번만
    n.on_alert("warn", "stock", "재고 부족(2개): A")
    n.tick()
    assert len(fake.sent) == 1 and "요약 (2건)" in fake.sent[0][1]
    off = N.TelegramNotifier({"telegram": {"enabled": False, "token": "123:GOOD", "chat_id": "1", "topics": ["stock"]}},
                             start=False, settle_sec=0)
    off.on_alert("warn", "stock", "재고 부족(1개): B")
    off.tick()
    assert len(fake.sent) == 1


def test_reprice_alerts_use_reprice_kind():
    from mock_backend import MockCompetitorProvider, MockCoupangClient
    from services import SyncService
    from store import Store
    st = Store(os.path.join(tempfile.mkdtemp(), "r.db"))
    comp = MockCompetitorProvider()
    sync = SyncService(MockCoupangClient(), st, comp, {"auto_soldout": False})
    sync.run_once()
    vid = st.items()[0]["vendor_item_id"]
    st.update_rule(vid, auto_reprice=1, min_price=1, undercut=10)
    comp._base[vid] = [("X", 1000)]
    sync.run_once()
    assert any(a["kind"] == "reprice" and "자동 가격조정" in a["message"] for a in st.alerts())


def test_failed_action_keeps_typed_fields(monkeypatch):
    monkeypatch.setattr(N.requests, "post", FakeTelegram())
    c = A.app.test_client()
    A.cfg.pop("telegram", None)
    html = c.post("/settings/telegram", data={"action": "test", "token": "bad", "chat_id": "98765", "enabled": "1",
                                              "topics": ["price"]}, follow_redirects=True).get_data(as_text=True)
    assert 'value="98765"' in html and 'value="price" checked' in html and 'value="bad"' not in html
    assert "telegram" not in A.cfg
    assert 'value="98765"' not in c.get("/settings").get_data(as_text=True)   # 한 번만 보여 줌


def test_save_schedule_and_validate_time(monkeypatch):
    monkeypatch.setattr(N.requests, "post", FakeTelegram())
    c = A.app.test_client()
    base = {"action": "save", "token": "123:GOOD", "chat_id": "111", "enabled": "1",
            "topics": ["lowest", "my_price", "competitor"], "frequency": "1h", "outside": "drop"}
    html = c.post("/settings/telegram", data={**base, "send_from": "25:00", "send_to": "07:00"},
                  follow_redirects=True).get_data(as_text=True)
    assert "00:00 ~ 23:59 형식" in html and A.cfg.get("telegram", {}).get("send_from") != "25:00"
    html = c.post("/settings/telegram", data={**base, "send_from": "22:00", "send_to": "07:00"},
                  follow_redirects=True).get_data(as_text=True)
    t = A.cfg["telegram"]
    assert (t["frequency"], t["send_from"], t["send_to"], t["outside"]) == ("1h", "22:00", "07:00", "drop")
    assert "1시간마다 모아서 · 22:00~07:00" in html
    import re
    assert re.search(r'<option value="1h"\s+selected', html) and 'value="22:00"' in html and '<option value="drop" selected' in html
