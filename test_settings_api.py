"""설정 화면이 쓰는 API.

가장 중요한 것: 비밀값(Secret Key, 봇 토큰)은 **절대 내보내지 않는다**.
화면은 "저장되어 있는지" 만 알면 되고, 빈 칸으로 저장하면 서버가 기존 값을 그대로 둔다.
"""
import os
import tempfile

os.environ.setdefault("WING_DATA_DIR", tempfile.mkdtemp())
import pytest  # noqa: E402

import app as A  # noqa: E402

SECRET = "sk-aaaabbbbcccc-donotleak"
TOKEN = "123456:bot-token-donotleak"


@pytest.fixture(autouse=True)
def _restore_config():
    """설정은 파일에 저장된다. 테스트가 바꾼 값을 되돌린다."""
    before = dict(A.cfg)
    yield
    A.cfg.clear()
    A.cfg.update(before)
    A.save_config(A.cfg)
    A._apply_client(A.cfg)


def _client():
    return A.app.test_client()


def test_settings_api_never_sends_the_secret_key():
    A.cfg.update(access_key="ak-public", secret_key=SECRET, vendor_id="A00012345")
    A.save_config(A.cfg)

    res = _client().get("/api/settings")
    body = res.get_json()

    assert SECRET not in res.get_data(as_text=True), "비밀키가 응답에 들어갔다"
    assert body["keys"]["has_secret_key"] is True
    assert body["keys"]["access_key"] == "ak-public"  # 공개키는 화면에서 확인해야 한다
    assert "secret_key" not in body["keys"]


def test_settings_api_never_sends_the_telegram_token():
    A.cfg["telegram"] = {"token": TOKEN, "chat_id": "555", "enabled": True, "topics": ["stock"],
                         "frequency": "realtime", "send_from": "00:00", "send_to": "00:00", "outside": "hold"}
    A.save_config(A.cfg)

    res = _client().get("/api/settings")

    assert TOKEN not in res.get_data(as_text=True), "봇 토큰이 응답에 들어갔다"
    assert res.get_json()["telegram"]["has_token"] is True
    assert res.get_json()["telegram"]["chat_id"] == "555"  # 대화 ID 는 비밀이 아니다


def test_blank_secret_key_keeps_the_saved_one():
    """화면은 비밀키를 다시 채우지 않는다. 다른 칸만 고쳐 저장해도 키가 지워지면 안 된다."""
    A.cfg.update(access_key="ak-old", secret_key=SECRET, vendor_id="A000")
    A.save_config(A.cfg)

    res = _client().post("/api/settings/keys",
                         json={"action": "save", "access_key": "ak-new", "secret_key": "", "vendor_id": "A000"})

    assert res.status_code == 200
    assert A.cfg["secret_key"] == SECRET, "비워 둔 칸이 저장된 비밀키를 지웠다"
    assert A.cfg["access_key"] == "ak-new"


def test_clearing_keys_drops_both_and_falls_back_to_mock():
    A.cfg.update(access_key="ak", secret_key=SECRET, vendor_id="A000")
    A.save_config(A.cfg)

    res = _client().post("/api/settings/keys", json={"action": "clear"})

    assert res.status_code == 200
    assert "secret_key" not in A.cfg
    assert "access_key" not in A.cfg
    assert A.client.mode == "mock"


def test_rules_are_validated_before_anything_is_saved():
    """일부만 반영되면 안 된다 — 주기는 바뀌고 주소는 거부되는 상태가 생기면 혼란스럽다."""
    A.cfg.update(sync_interval_sec=30, public_base_url="")
    A.save_config(A.cfg)

    res = _client().post("/api/settings/rules", json={
        "sync_interval_sec": 99, "soldout_threshold": 1,
        "auto_soldout": True, "public_base_url": "example.com",  # 스킴이 없다
    })

    assert res.status_code == 400
    assert "http" in res.get_json()["error"]
    assert A.cfg["sync_interval_sec"] == 30, "거부된 요청이 주기를 바꿨다"


def test_sync_interval_has_a_floor():
    res = _client().post("/api/settings/rules", json={
        "sync_interval_sec": 1, "soldout_threshold": 0, "auto_soldout": False, "public_base_url": "",
    })
    assert res.status_code == 200
    assert A.cfg["sync_interval_sec"] == 5, "5초보다 짧은 주기를 허용했다"


def test_unknown_theme_is_refused():
    res = _client().post("/api/settings/theme", json={"theme": "네온"})
    assert res.status_code == 400


def test_bad_telegram_input_is_400_not_502():
    """502 는 '상대 서버 탓' 이라는 뜻이다. 내가 잘못 넣은 값은 400 이어야 한다."""
    for body, why in [
        ({"action": "save", "token": "", "send_from": "00:00", "send_to": "00:00"}, "토큰 없음"),
        ({"action": "save", "token": "x", "send_from": "99:99", "send_to": "00:00"}, "시간 형식"),
        ({"action": "save", "token": "x", "enabled": True, "chat_id": "",
          "send_from": "00:00", "send_to": "00:00"}, "켰는데 대화 ID 없음"),
    ]:
        res = _client().post("/api/settings/telegram", json=body)
        assert res.status_code == 400, f"{why}: {res.status_code} 가 나왔다"
