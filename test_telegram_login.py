"""텔레그램: 로그인·로그아웃 알림(고른 경우만, 바로 전송)과 메뉴의 텔레그램 연결 표시."""
import app as A
import notifier as N
from test_telegram import FakeTelegram, _wait


def _setup(monkeypatch, topics):
    fake = FakeTelegram()
    monkeypatch.setattr(N.requests, "post", fake)
    A.cfg["telegram"] = {"token": "123:GOOD", "chat_id": "111", "enabled": True, "topics": topics,
                         "frequency": "1h", "send_from": "03:00", "send_to": "03:01", "outside": "drop"}
    A.app.config["WING_LOGIN_REQUIRED"] = True
    a = A.app.extensions["wing_auth"]
    a.set_credentials("owner", "correct-horse")
    a.succeeded("127.0.0.1")
    return fake, A.app.test_client()


def test_login_logout_sent_immediately_when_selected(monkeypatch):
    fake, c = _setup(monkeypatch, ["login"])
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0 Safari/537.36"}
    c.post("/login", data={"user": "owner", "password": "correct-horse", "remember": "1"}, headers=ua)
    # 1시간마다 + 시간대 밖(보내지 않기)이어도 로그인 알림은 바로 간다
    assert _wait(lambda: len(fake.sent) == 1)
    text = fake.sent[0][1]
    assert "[로그인·로그아웃] 로그인: owner" in text and "IP 127.0.0.1" in text and "Chrome/Windows" in text
    assert "로그인 유지 30일" in text
    c.post("/logout")
    assert _wait(lambda: len(fake.sent) == 2) and "로그아웃: owner" in fake.sent[1][1]
    for _ in range(5):
        c.post("/login", data={"user": "owner", "password": "wrong"})
    assert _wait(lambda: len(fake.sent) == 3) and "5번 실패" in fake.sent[2][1]
    A.app.extensions["wing_auth"].succeeded("127.0.0.1")
    A.cfg.pop("telegram")


def test_login_not_sent_when_not_selected(monkeypatch):
    fake, c = _setup(monkeypatch, ["stock"])
    c.post("/login", data={"user": "owner", "password": "correct-horse"})
    c.post("/logout")
    assert not _wait(lambda: fake.sent, sec=1)
    A.cfg.pop("telegram")


def test_menu_shows_telegram_status(monkeypatch):
    fake = FakeTelegram()
    monkeypatch.setattr(N.requests, "post", fake)
    n = N.TelegramNotifier({}, start=False)
    assert n.status()["text"] == "텔레그램 연결 안 함"
    n.cfg["telegram"] = {"token": "bad", "chat_id": "1", "enabled": True}
    assert n.status()["state"] == "wait"                       # 봇 확인은 백그라운드 → 처음엔 '확인 중'
    assert _wait(lambda: n.status()["text"] == "텔레그램 연결 실패")
    n.cfg["telegram"] = {"token": "123:GOOD", "chat_id": "1", "enabled": False}
    n.status()
    assert _wait(lambda: n.status()["text"] == "텔레그램 알림 꺼짐")
    n.cfg["telegram"]["enabled"] = True
    assert n.status()["state"] == "ok"
    n.record(False, "전송 실패: 테스트")
    assert n.status()["text"] == "텔레그램 전송 실패"
    c = A.app.test_client()
    assert "telegram" in c.get("/api/health").get_json() and 'id="h-tg"' in c.get("/classic/").get_data(as_text=True)
