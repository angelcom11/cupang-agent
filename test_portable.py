"""포터블 실행기: 데이터 폴더 위치, 포트 고르기, '이미 실행 중' 감지."""
import socket
import sys
import threading
from pathlib import Path

import portable


def test_data_dir_is_next_to_executable_when_frozen(monkeypatch, tmp_path):
    exe = tmp_path / "내 폴더" / ("WING-Manager.exe" if sys.platform == "win32" else "WING-Manager")
    exe.parent.mkdir()
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert portable.app_dir() == exe.parent.resolve()


def test_choose_port_skips_busy_port_and_detects_running_wing():
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    try:
        chosen, running = portable.choose_port("127.0.0.1", port)
        assert chosen != port and not running  # 다른 프로그램이 쓰는 포트는 건너뛴다
    finally:
        busy.close()

    import app as wing
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 0, wing.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert portable.is_wing(server.port)
        assert portable.choose_port("127.0.0.1", server.port) == (server.port, True)
    finally:
        server.shutdown()


def test_args():
    a = portable.parse_args(["--lan", "--port", "27000", "--data", "x", "--no-browser"])
    assert (a.lan, a.port, a.data, a.no_browser) == (True, 27000, "x", True)
    assert Path(portable.__file__).parent == portable.app_dir()
