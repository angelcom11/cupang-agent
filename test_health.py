"""메뉴바 연결 상태: 쿠팡 연결 판정, 서버 주소 목록, /api/health."""
import os
import tempfile
from datetime import datetime, timedelta

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import app as A  # noqa: E402
import health  # noqa: E402

UP = {"reachable": True, "error": None, "host": "api-gateway.coupang.com", "ip": "1.2.3.4", "ms": 30}
DOWN = {"reachable": False, "error": "쿠팡 서버에 닿지 않습니다 (ConnectTimeout)", "host": "api-gateway.coupang.com",
        "ip": None, "ms": None}
NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def test_coupang_state():
    st = lambda *a: health.coupang_state(*a)["state"]  # noqa: E731
    assert st("live", NOW, None, 30, UP) == "ok"
    assert st("live", NOW, None, 30, DOWN) == "bad"                     # 인터넷이 끊김
    assert st("live", None, "401: Specified key is not registered", 30, UP) == "bad"  # 키 오류: 네트워크는 되어도 실패
    assert st("live", NOW, "401: x", 30, UP) == "warn"                   # 성공한 적은 있는데 방금 실패
    old = (datetime.now() - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    assert health.coupang_state("live", old, None, 30, UP)["text"] == "쿠팡 동기화 멈춤"
    assert st("mock", NOW, None, 30, UP) == "mock"


def test_addresses_and_ip_kinds():
    assert [health.ip_kind(i) for i in ("127.0.0.1", "100.101.5.103", "192.168.0.233", "8.8.8.8")] == \
        ["이 컴퓨터", "Tailscale", "내부망(LAN)", "외부"]
    local = health.addresses("127.0.0.1", 26118, "127.0.0.1:26118")
    assert local == [{"url": "http://127.0.0.1:26118", "ip": "127.0.0.1", "kind": "이 컴퓨터", "current": True}]
    rows = health.addresses("0.0.0.0", 26118, "127.0.0.1:26118")
    assert rows[0]["current"] and all(r["url"].endswith(":26118") for r in rows)
    assert health.uptime_text(health.STARTED + 90061) == "1일 1시간 1분"


def test_health_api(monkeypatch):
    monkeypatch.setattr(health, "probe_coupang", lambda force=False: dict(DOWN))
    monkeypatch.setitem(A.app.config, "WING_HOST", "127.0.0.1")
    monkeypatch.setitem(A.app.config, "WING_PORT", 26118)
    h = A.app.test_client().get("/api/health").get_json()
    assert h["running"] and h["version"] and h["coupang"]["state"] == "bad" and "닿지 않습니다" in h["coupang"]["detail"]
    assert h["addresses"] == [{"url": "http://127.0.0.1:26118", "ip": "127.0.0.1", "kind": "이 컴퓨터", "current": False}]
    page = A.app.test_client().get("/classic/").get_data(as_text=True)
    assert 'id="h-app"' in page and 'id="h-addr"' in page and "/api/health" in page
