"""시스템 로그인. 로그인 정보는 데이터 폴더의 .env 파일에만 저장한다 (config.json 과 분리, 권한 600).

.env 키
  WING_LOGIN_USER           로그인 아이디
  WING_LOGIN_PASSWORD_HASH  비밀번호 해시 (werkzeug scrypt — 원래 비밀번호는 어디에도 저장하지 않음)
  WING_SESSION_SECRET       로그인 쿠키 서명 키 (재시작해도 로그인 유지)

처음 실행(계정 없음): /setup 에서 관리자 계정을 만든다. 다른 기기에서 만들 때는 서버 창(로그)에 나온 설정 코드가 필요하다
  → 같은 네트워크의 다른 사람이 먼저 계정을 만들어 버리는 것을 막는다.
비밀번호를 잊으면: .env 에서 WING_LOGIN_ 로 시작하는 두 줄을 지우고 프로그램을 다시 실행 → 계정 다시 만들기.
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

log = logging.getLogger("wing")
bp = Blueprint("auth", __name__)

PUBLIC_ENDPOINTS = {"auth.login", "auth.setup", "static", "uploaded", "api_ping"}  # 업로드 이미지는 쿠팡이 가져가야 함
USER_KEY, HASH_KEY, SECRET_KEY = "WING_LOGIN_USER", "WING_LOGIN_PASSWORD_HASH", "WING_SESSION_SECRET"
USER_RE = re.compile(r"^[A-Za-z0-9._@-]{3,32}$")
MIN_PASSWORD = 8
MAX_FAILS, LOCK_SEC = 5, 300  # 5번 틀리면 5분 잠금 (접속 IP 별)
REMEMBER_DAYS = 30
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


# ---------------- .env 읽기/쓰기 ----------------
def read_env(path: Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#") or not (m := _ENV_LINE.match(line)):
            continue
        value = m.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[m.group(1)] = value
    return data


def write_env(path: Path, updates: dict):
    """주어진 키만 바꾸거나 추가하고, 다른 줄(주석·다른 값)은 그대로 둔다. 값이 None 이면 그 줄을 지운다."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else [
        "# WING 매니저 로그인 정보 — 다른 사람에게 보여주거나 GitHub 에 올리지 마세요.",
        "# 비밀번호를 잊으면 WING_LOGIN_ 로 시작하는 줄을 지우고 프로그램을 다시 실행하세요."]
    todo = dict(updates)
    out = []
    for line in lines:
        m = _ENV_LINE.match(line)
        if m and not line.lstrip().startswith("#") and m.group(1) in todo:
            value = todo.pop(m.group(1))
            if value is not None:
                out.append(f"{m.group(1)}='{value}'")
            continue
        out.append(line)
    out += [f"{k}='{v}'" for k, v in todo.items() if v is not None]
    tmp = path.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)  # 소유자만 읽기 (Windows 는 사용자 폴더 권한을 따름)
    tmp.replace(path)


# ---------------- 상태 ----------------
class Auth:
    def __init__(self, env_path: Path):
        self.env_path = Path(env_path)
        self.setup_code = secrets.token_hex(3).upper()  # 다른 기기에서 첫 계정을 만들 때 필요한 6자리 코드
        self._fails: dict[str, list] = {}
        self._lock = threading.Lock()
        self.listeners: list = []  # 로그인 기록 알림 (예: 텔레그램) — fn(text)

    def emit(self, what: str, user: str, extra: str = ""):
        """'로그인: owner · 2026-11-02 16:40:12 · IP 1.2.3.4 · Chrome/Windows' 형태로 알린다."""
        ip = request.remote_addr or "?"
        parts = [f"{what}: {user or '-'}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), f"IP {ip}", _device(), extra]
        text = " · ".join(p for p in parts if p)
        for fn in self.listeners:
            try:
                fn(text)
            except Exception:  # 알림 실패가 로그인을 막지 않게
                log.exception("login listener failed")

    @property
    def env(self) -> dict:
        return read_env(self.env_path)

    def configured(self) -> bool:
        e = self.env
        return bool(e.get(USER_KEY) and e.get(HASH_KEY))

    def session_secret(self) -> str:
        secret = self.env.get(SECRET_KEY)
        if not secret:
            secret = secrets.token_hex(32)
            write_env(self.env_path, {SECRET_KEY: secret})
        return secret

    def user(self) -> str:
        return self.env.get(USER_KEY, "")

    def password_version(self) -> str:
        """비밀번호를 바꾸면 달라지는 값 → 다른 기기에 남은 예전 로그인은 자동으로 풀린다."""
        return self.env.get(HASH_KEY, "")[-12:]

    def set_credentials(self, user: str, password: str):
        write_env(self.env_path, {USER_KEY: user, HASH_KEY: generate_password_hash(password)})

    def verify(self, user: str, password: str) -> bool:
        e = self.env
        ok_user = hmac.compare_digest(user.encode(), e.get(USER_KEY, "").encode())
        ok_pw = bool(e.get(HASH_KEY)) and check_password_hash(e[HASH_KEY], password)
        return ok_user and ok_pw

    # 로그인 시도 제한
    def locked_for(self, ip: str) -> int:
        with self._lock:
            fails = [t for t in self._fails.get(ip, []) if time.time() - t < LOCK_SEC]
            self._fails[ip] = fails
            return int(LOCK_SEC - (time.time() - fails[0])) + 1 if len(fails) >= MAX_FAILS else 0

    def failed(self, ip: str):
        with self._lock:
            self._fails.setdefault(ip, []).append(time.time())

    def succeeded(self, ip: str):
        with self._lock:
            self._fails.pop(ip, None)


def password_problem(user: str, password: str, confirm: str) -> str | None:
    if not USER_RE.match(user):
        return "아이디는 영문·숫자·._@- 로 3~32자여야 합니다"
    if len(password) < MIN_PASSWORD:
        return f"비밀번호는 {MIN_PASSWORD}자 이상이어야 합니다"
    if password != confirm:
        return "비밀번호 확인이 일치하지 않습니다"
    if password.lower() == user.lower():
        return "아이디와 같은 비밀번호는 쓸 수 없습니다"
    return None


def _device() -> str:
    """접속 기기를 짧게 (브라우저/OS). 모르면 빈 문자열."""
    ua = request.headers.get("User-Agent", "")
    browser = next((n for k, n in (("Edg/", "Edge"), ("Whale/", "Whale"), ("SamsungBrowser", "삼성 인터넷"), ("Chrome/", "Chrome"),
                                   ("Firefox/", "Firefox"), ("Safari/", "Safari")) if k in ua), "")
    system = next((n for k, n in (("Android", "Android"), ("iPhone", "iPhone"), ("iPad", "iPad"), ("Windows", "Windows"),
                                  ("Mac OS X", "Mac"), ("Linux", "Linux")) if k in ua), "")
    return "/".join(filter(None, [browser, system]))


def _is_local(ip: str) -> bool:
    return ip in ("127.0.0.1", "::1")


def _safe_next(target: str | None) -> str:
    """로그인 후 돌아갈 주소: 이 사이트 안의 경로만 (다른 사이트로 보내는 피싱 링크 방지)."""
    if target and target.startswith("/") and not target.startswith("//") and not urlparse(target).netloc:
        return target
    # 'dashboard' 는 /classic/ 로 옮긴 기존 화면이다. 로그인하면 새 화면으로 들어간다.
    return url_for("spa")


# ---------------- 연결 ----------------
def init_app(app, auth: Auth):
    app.secret_key = auth.session_secret()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      PERMANENT_SESSION_LIFETIME=timedelta(days=REMEMBER_DAYS))
    app.extensions["wing_auth"] = auth
    app.register_blueprint(bp)
    if not auth.configured():
        log.warning("로그인 계정이 없습니다. 브라우저에서 계정을 만드세요. 다른 기기에서 만들 때 설정 코드: %s", auth.setup_code)
        print(f"\n[로그인] 계정을 아직 만들지 않았습니다. 다른 기기에서 처음 계정을 만들 때 필요한 설정 코드: {auth.setup_code}\n",
              flush=True)

    @app.before_request
    def require_login():
        if not app.config.get("WING_LOGIN_REQUIRED", True) or request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if not auth.configured():
            return _deny(url_for("auth.setup"), "로그인 계정을 먼저 만드세요")
        if session.get("user") == auth.user() and session.get("pwv") == auth.password_version():
            return None
        session.clear()
        return _deny(url_for("auth.login", next=request.full_path.rstrip("?")), "로그인이 필요합니다")

    @app.context_processor
    def inject_user():
        return {"login_user": session.get("user"), "login_on": app.config.get("WING_LOGIN_REQUIRED", True)}


def _deny(target: str, message: str):
    if request.path.startswith("/api/") or request.headers.get("Accept", "").startswith("application/json"):
        return jsonify({"error": message, "login": True}), 401
    return redirect(target)


def _auth() -> Auth:
    from flask import current_app
    return current_app.extensions["wing_auth"]


def _login(user: str, remember: bool):
    session.clear()
    session.update(user=user, pwv=_auth().password_version())
    session.permanent = remember


@bp.route("/setup", methods=["GET", "POST"])
def setup():
    auth = _auth()
    if auth.configured():
        return redirect(url_for("auth.login"))
    need_code = not _is_local(request.remote_addr or "")
    error = None
    if request.method == "POST":
        user = request.form.get("user", "").strip()
        password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        code = request.form.get("code", "").strip().upper()
        if need_code and not hmac.compare_digest(code, auth.setup_code):
            error = "설정 코드가 맞지 않습니다. 서버 창(로그)에 나온 6자리 코드를 입력하세요"
        else:
            error = password_problem(user, password, confirm)
        if not error:
            auth.set_credentials(user, password)
            log.info("로그인 계정을 만들었습니다: %s (%s)", user, request.remote_addr)
            _login(user, remember=False)
            auth.emit("관리자 계정 만듦 · 로그인", user)
            flash("로그인 계정을 만들었습니다. 다음부터는 이 아이디와 비밀번호로 로그인하세요.", "info")
            return redirect(url_for("spa"))
    return render_template("login.html", mode="setup", error=error, need_code=need_code,
                           env_path=str(auth.env_path), user=request.form.get("user", ""))


@bp.route("/login", methods=["GET", "POST"])
def login():
    auth = _auth()
    if not auth.configured():
        return redirect(url_for("auth.setup"))
    ip = request.remote_addr or "?"
    error = None
    logged_in = session.get("user") == auth.user() and session.get("pwv") == auth.password_version()
    if request.method == "GET" and logged_in and not request.args.get("preview"):
        return redirect(_safe_next(request.args.get("next")))  # 이미 로그인했으면 바로 들어간다 (미리보기 제외)
    if request.method == "POST":
        if wait := auth.locked_for(ip):
            error = f"로그인을 여러 번 틀려 잠시 잠겼습니다. {wait // 60}분 {wait % 60}초 뒤에 다시 시도하세요"
        elif auth.verify(request.form.get("user", "").strip(), request.form.get("password", "")):
            auth.succeeded(ip)
            remember = bool(request.form.get("remember"))
            _login(auth.user(), remember=remember)
            log.info("로그인: %s (%s)", auth.user(), ip)
            auth.emit("로그인", auth.user(), "로그인 유지 30일" if remember else "")
            return redirect(_safe_next(request.args.get("next")))
        else:
            auth.failed(ip)
            log.warning("로그인 실패 (%s)", ip)
            left = MAX_FAILS - len(auth._fails.get(ip, []))
            error = "아이디 또는 비밀번호가 맞지 않습니다" + (f" (남은 시도 {left}번)" if 0 < left < MAX_FAILS else "")
            if left <= 0:
                error = f"로그인을 {MAX_FAILS}번 틀려 {LOCK_SEC // 60}분 동안 잠깁니다"
                auth.emit(f"⚠ 로그인 {MAX_FAILS}번 실패 → {LOCK_SEC // 60}분 잠금", request.form.get("user", "").strip()[:32])
    return render_template("login.html", mode="login", error=error, user=request.form.get("user", ""))


@bp.route("/logout", methods=["POST"])
def logout():
    if session.get("user"):
        _auth().emit("로그아웃", session["user"])
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/settings/login", methods=["POST"])
def change_login():
    auth = _auth()
    current = request.form.get("current", "")
    user = request.form.get("user", "").strip() or auth.user()
    password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
    if not auth.verify(auth.user(), current):
        flash("현재 비밀번호가 맞지 않습니다", "danger")
    elif problem := password_problem(user, password, confirm):
        flash(problem, "danger")
    else:
        auth.set_credentials(user, password)
        _login(user, remember=session.permanent)
        log.info("로그인 정보를 바꿨습니다: %s (%s)", user, request.remote_addr)
        auth.emit("로그인 정보 변경", user, "다른 기기 로그인은 풀림")
        flash("로그인 정보를 바꿨습니다. 다른 기기에 남아 있던 로그인은 풀립니다.", "info")
    return redirect(url_for("settings") + "#login")
