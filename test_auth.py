"""로그인: 첫 화면은 로그인, 30일 유지, 로그아웃, 로그인 화면 꾸미기 설정."""
import io

import app as A
import auth
import login_page

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _client_with_account():
    A.app.config["WING_LOGIN_REQUIRED"] = True
    a = A.app.extensions["wing_auth"]
    a.set_credentials("owner", "correct-horse")
    a.succeeded("127.0.0.1")
    return A.app.test_client()


def _login(c, remember=True):
    data = {"user": "owner", "password": "correct-horse"}
    if remember:
        data["remember"] = "1"
    return c.post("/login", data=data)


def test_start_page_is_login_and_logout_returns_there():
    c = _client_with_account()
    r = c.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    html = c.get("/login").get_data(as_text=True)
    assert 'name="remember" value="1" checked' in html and "로그인 유지 (30일)" in html
    r = _login(c)
    assert r.status_code == 302
    cookie = r.headers["Set-Cookie"]
    assert "Expires=" in cookie and "HttpOnly" in cookie        # 로그인 유지 → 브라우저를 닫아도 남는 쿠키
    assert auth.REMEMBER_DAYS == 30 and A.app.permanent_session_lifetime.days == 30
    # 로그아웃 버튼은 기존 화면의 메뉴에 있다 (루트는 새 화면이 쓴다)
    page = c.get("/classic/").get_data(as_text=True)
    assert "로그아웃" in page and 'action="/logout"' in page
    assert c.get("/login").status_code == 302                 # 이미 로그인했으면 로그인 화면을 건너뜀
    assert c.get("/login?preview=1").status_code == 200       # 설정 미리보기는 보임
    r = c.post("/logout")
    assert r.status_code == 302 and r.headers["Location"].endswith("/login")
    assert c.get("/").status_code == 302


def test_login_page_settings_saved_and_shown_escaped():
    c = _client_with_account()
    _login(c)
    up = c.post("/api/upload", data={"file": (io.BytesIO(PNG), "bg.png")}, content_type="multipart/form-data").get_json()
    form = {"action": "save_login_page", "brand": "우리가게", "title": "직원 로그인", "message": "<script>x</script>안녕하세요",
            "footer": "문의 010-1234-5678", "accent": "#2563EB", "bg_color": "#ffffff", "layout": "split",
            "bg_image": up["url"], "show_help": ""}
    r = c.post("/classic/settings", data=form, follow_redirects=True)
    assert "로그인 화면 설정을 저장했습니다" in r.get_data(as_text=True)
    lp = login_page.get(A.cfg)
    assert lp["brand"] == "우리가게" and lp["accent"] == "#2563eb" and lp["bg_image"] == up["name"] and not lp["show_help"]
    c.post("/logout")
    html = c.get("/login").get_data(as_text=True)
    assert "우리가게" in html and "직원 로그인" in html and "문의 010-1234-5678" in html
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "layout-split" in html and up["name"] in html and "#2563eb" in html
    assert "비밀번호를 잊었으면" not in html
    _login(c)
    r = c.post("/classic/settings", data={"action": "reset_login_page"}, follow_redirects=True)
    assert "기본 모양으로" in r.get_data(as_text=True) and login_page.get(A.cfg) == login_page.DEFAULTS


def test_login_page_rejects_bad_values_without_saving():
    c = _client_with_account()
    _login(c)
    before = login_page.get(A.cfg)
    bad = {"action": "save_login_page", "brand": "x", "title": "y", "accent": "red;}body{display:none",
           "bg_color": "#fff", "layout": "center", "bg_image": "../config.json", "bg_type": "image"}
    r = c.post("/classic/settings", data=bad, follow_redirects=True).get_data(as_text=True)
    assert "#RRGGBB" in r and "올린 이미지만" in r
    assert login_page.get(A.cfg) == before
    A.cfg["login_page"] = {"accent": "nope", "layout": "weird", "bg_type": "image", "bg_image": "../x"}
    lp = login_page.get(A.cfg)                                 # 잘못 저장된 값도 화면을 깨지 않음
    assert lp["accent"] == "#e8590c" and lp["layout"] == "center" and lp["bg_type"] == "color"
    A.cfg.pop("login_page")
