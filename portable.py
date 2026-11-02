"""포터블 실행기: 실행 파일 하나로 WING 매니저를 띄운다 (Windows · Linux · macOS).

- 내 데이터(config.json · wing.db · uploads/)는 실행 파일 옆 'WING-data' 폴더에 둔다 → 폴더째 USB로 옮겨도 그대로.
- 기본은 이 컴퓨터에서만 접속(127.0.0.1). 같은 와이파이의 휴대폰에서도 쓰려면 --lan.
- 이미 실행 중이면 새로 띄우지 않고 브라우저만 연다.

실행:  WING-Manager [--lan] [--port 26118] [--data 폴더] [--no-browser]
개발:  python portable.py
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from version import VERSION

DEFAULT_PORT = 26118
APP_ID = "wing-manager"  # /api/ping 응답: 이 포트에 떠 있는 게 WING 매니저인지 확인


def app_dir() -> Path:
    """실행 파일(포터블) 또는 이 소스 파일이 있는 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="WING-Manager", description=f"쿠팡 WING 매니저 {VERSION} (포터블)")
    p.add_argument("--data", help="데이터 폴더 (기본: 실행 파일 옆 WING-data)")
    p.add_argument("--port", type=int, help=f"포트 (기본: 설정값 또는 {DEFAULT_PORT})")
    p.add_argument("--lan", action="store_true", help="같은 네트워크의 다른 기기(휴대폰 등)에서도 접속 허용")
    p.add_argument("--host", help="직접 지정할 바인딩 주소 (고급)")
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않음")
    p.add_argument("--version", action="version", version=VERSION)
    return p.parse_args(argv)


def read_config(data_dir: Path) -> dict:
    try:
        return json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def is_wing(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as r:
            return json.loads(r.read().decode()).get("app") == APP_ID
    except (OSError, ValueError):
        return False


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def lan_ip() -> str | None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))  # 실제로 보내지 않음: 기본 경로의 내 주소만 알아낸다
            return s.getsockname()[0]
        except OSError:
            return None


def choose_port(host: str, wanted: int) -> tuple[int, bool]:
    """(포트, 이미_실행중). 원하는 포트를 다른 프로그램이 쓰면 다음 빈 포트."""
    for port in range(wanted, wanted + 20):
        if is_wing(port):
            return port, True
        if port_free(host, port):
            return port, False
    raise SystemExit(f"{wanted}~{wanted + 19} 포트가 모두 사용 중입니다. --port 로 다른 포트를 지정하세요.")


def open_browser_when_ready(url: str, port: int):
    def run():
        for _ in range(60):
            if is_wing(port):
                webbrowser.open(url)
                return
            time.sleep(0.5)
    threading.Thread(target=run, daemon=True).start()


def utf8_output():
    """Windows 는 출력이 콘솔이 아닐 때(파일로 저장 등) 옛 코드페이지(cp1252 등)를 써서 한글에서 멈춘다."""
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    utf8_output()  # 로그 설정(app 불러오기)보다 먼저
    args = parse_args(argv)
    data_dir = Path(args.data).expanduser().resolve() if args.data else app_dir() / "WING-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["WING_DATA_DIR"] = str(data_dir)  # app 을 불러오기 전에 정해야 한다

    cfg = read_config(data_dir)
    host = args.host or ("0.0.0.0" if args.lan else "127.0.0.1")
    port, running = choose_port(host, args.port or int(cfg.get("port") or DEFAULT_PORT))
    url = f"http://127.0.0.1:{port}"
    if running:
        print(f"WING 매니저가 이미 실행 중입니다 → {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return

    import app as wing  # noqa: E402  (WING_DATA_DIR 을 정한 뒤에 불러온다)
    from werkzeug.serving import make_server

    wing.app.config.update(WING_HOST=host, WING_PORT=port)  # 메뉴바 '서버 주소' 표시용
    server = make_server(host, port, wing.app, threaded=True)
    print("=" * 60)
    print(f" 쿠팡 WING 매니저 {VERSION}  ({'실연동' if wing.client.mode == 'live' else '모의 모드'})")
    print(f" 접속 주소 : {url}")
    if host == "0.0.0.0" and (ip := lan_ip()):
        print(f" 휴대폰 등 : http://{ip}:{port}   (같은 와이파이에서)")
    print(f" 데이터    : {data_dir}")
    print(" 끝내려면 이 창을 닫거나 Ctrl+C 를 누르세요.")
    print("=" * 60, flush=True)
    wing.sync.start()
    wing.reg_checker.start()
    if not args.no_browser:
        open_browser_when_ready(url, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
