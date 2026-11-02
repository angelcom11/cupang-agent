"""화면 모드(시스템·라이트·다크): 설정에서 저장하면 모든 화면과 로그인 화면에 반영."""
import app as A
import gen_dark_css


def test_theme_saved_and_applied_to_pages_and_login():
    c = A.app.test_client()
    html = c.get("/settings").get_data(as_text=True)
    assert 'data-theme-pref="system"' in html and 'value="system" checked' in html and "dark.css" in html
    r = c.post("/settings", data={"action": "save_theme", "theme": "dark"}, follow_redirects=True)
    assert "화면 모드: 다크 모드" in r.get_data(as_text=True) and A.cfg["theme"] == "dark"
    login = "/login?preview=1" if A.app.extensions["wing_auth"].configured() else "/setup"
    for path in ("/", "/inventory", login):
        assert 'data-theme-pref="dark" data-theme="dark"' in c.get(path).get_data(as_text=True)
    r = c.post("/settings", data={"action": "save_theme", "theme": "purple"}, follow_redirects=True)
    assert "화면 모드를 다시 고르세요" in r.get_data(as_text=True) and A.cfg["theme"] == "dark"
    A.cfg.pop("theme")


def test_dark_css_is_generated_from_current_style():
    assert gen_dark_css.OUT.read_text(encoding="utf-8") == gen_dark_css.build(), "style.css 를 고쳤으면 python gen_dark_css.py 를 다시 실행하세요"
    assert gen_dark_css.to_dark("#ffffff") == "var(--surface)" and gen_dark_css.to_dark("#000000") == "var(--ink)"
