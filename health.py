"""메뉴바 '연결 상태': 프로그램 실행 여부, 쿠팡 서버 연결, 이 프로그램이 돌고 있는 서버의 접속 주소.

- 실행 중 여부는 브라우저가 /api/health 를 주기적으로 불러서 판단한다 (응답이 없으면 화면이 '응답 없음'으로 바뀜).
- 쿠팡 연결은 두 가지를 본다: 네트워크로 쿠팡 API 서버에 닿는지(가벼운 HTTPS 요청, 60초 캐시)
  + 실연동이면 마지막 동기화가 성공했는지 (키가 틀리면 네트워크는 되어도 '연결 실패').
"""
from __future__ import annotations

import ipaddress
import socket
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

from coupang_client import BASE_URL

STARTED = time.time()
PROBE_TTL = 60  # 쿠팡 서버 네트워크 확인 결과를 다시 쓰는 시간(초)
_probe_lock = threading.Lock()
_probe: dict = {}


def _route_ip(target: str) -> str | None:
    """target 으로 나가는 길의 내 IP (UDP connect 는 실제로 패킷을 보내지 않는다)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect((target, 80))
            return s.getsockname()[0]
        except OSError:
            return None


def ip_kind(ip: str) -> str:
    a = ipaddress.ip_address(ip)
    if a.is_loopback:
        return "이 컴퓨터"
    if a in ipaddress.ip_network("100.64.0.0/10"):
        return "Tailscale"
    if a.is_private:
        return "내부망(LAN)"
    return "외부"


def server_ips() -> list[str]:
    """이 서버의 IPv4 주소들 (LAN, Tailscale). 추가 패키지 없이 Windows·macOS·Linux 공통으로 동작."""
    found = []
    for target in ("10.255.255.255", "100.100.100.100"):  # 기본 경로 / Tailscale 경로
        ip = _route_ip(target)
        if ip and ip not in found:
            found.append(ip)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in found:
                found.append(ip)
    except OSError:
        pass
    return [ip for ip in found if not ipaddress.ip_address(ip).is_loopback and not ip.startswith("169.254.")]


def addresses(bind_host: str, port: int, request_host: str) -> list[dict]:
    """접속 가능한 주소 목록. 지금 브라우저가 쓰는 주소를 맨 앞에 표시."""
    local_only = bind_host in ("127.0.0.1", "localhost")
    rows = [{"url": f"http://127.0.0.1:{port}", "ip": "127.0.0.1", "kind": "이 컴퓨터"}]
    if not local_only:
        rows = [{"url": f"http://{ip}:{port}", "ip": ip, "kind": ip_kind(ip)} for ip in server_ips()] + rows
    current = request_host.split(":")[0]
    for r in rows:
        r["current"] = r["ip"] == current
    rows.sort(key=lambda r: not r["current"])
    return rows


def probe_coupang(force: bool = False) -> dict:
    """쿠팡 API 서버에 네트워크로 닿는지. 인증 없는 요청이라 4xx 응답도 '닿음'으로 본다."""
    with _probe_lock:
        if not force and _probe and time.time() - _probe["at"] < PROBE_TTL:
            return dict(_probe)
        host = urlparse(BASE_URL).hostname
        result = {"at": time.time(), "host": host, "ip": None, "ms": None, "reachable": False, "error": None}
        try:
            result["ip"] = socket.getaddrinfo(host, 443, socket.AF_INET)[0][4][0]
            t = time.perf_counter()
            requests.head(BASE_URL, timeout=4, allow_redirects=False)
            result.update(reachable=True, ms=round((time.perf_counter() - t) * 1000))
        except socket.gaierror:
            result["error"] = "쿠팡 서버 주소를 찾을 수 없습니다 (인터넷 연결 확인)"
        except requests.RequestException as exc:
            result["error"] = f"쿠팡 서버에 닿지 않습니다 ({type(exc).__name__})"
        _probe.clear()
        _probe.update(result)
        return dict(result)


def coupang_state(mode: str, last_sync: str | None, last_error: str | None, interval: int, probe: dict) -> dict:
    """화면에 보일 쿠팡 연결 상태: ok / warn / bad / mock."""
    if not probe["reachable"]:
        return {"state": "bad", "text": "쿠팡 서버 연결 안 됨", "detail": probe["error"]}
    if mode != "live":
        return {"state": "mock", "text": "쿠팡 연결 안 함 (키 없음)", "detail": "설정에서 API 키를 넣으면 연결합니다 · 인터넷 정상"}
    if last_error and not last_sync:
        return {"state": "bad", "text": "쿠팡 연결 실패", "detail": last_error}
    if last_error:
        return {"state": "warn", "text": "쿠팡 연결 불안정", "detail": last_error}
    if not last_sync:
        return {"state": "warn", "text": "쿠팡 첫 동기화 대기", "detail": None}
    age = (datetime.now() - datetime.strptime(last_sync, "%Y-%m-%d %H:%M:%S")).total_seconds()
    if age > max(interval * 3, 180):  # 주기 동기화가 멈춤
        return {"state": "warn", "text": "쿠팡 동기화 멈춤", "detail": f"마지막 성공 {int(age // 60)}분 전"}
    return {"state": "ok", "text": "쿠팡 서버 연결됨", "detail": None}


def uptime_text(now: float | None = None) -> str:
    sec = int((now or time.time()) - STARTED)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return (f"{d}일 " if d else "") + (f"{h}시간 " if d or h else "") + f"{m}분"
