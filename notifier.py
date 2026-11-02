"""텔레그램 알림: 고른 종류의 알림을, 정한 시간대 안에서, 정한 빈도(실시간/10분/1시간)로 보낸다."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import requests

log = logging.getLogger("wing.telegram")
API = "https://api.telegram.org"

# 알림 kind → 텔레그램 선택 항목
TOPIC_OF_KIND = {"stock": "stock", "soldout": "stock", "reprice": "price",
                 "my_price": "my_price", "competitor": "competitor", "lowest": "lowest"}
TOPICS = {
    "stock": ("재고", "재고 부족 · 자동 품절(판매중지) · 재입고 판매재개"),
    "price": ("단가변경", "자동 가격조정 · 하한가 때문에 조정 중단"),
    "my_price": ("내 가격", "쿠팡에서 내 판매가가 바뀌었을 때 (WING에서 직접 바꾼 경우 포함)"),
    "competitor": ("경쟁 가격", "경쟁 판매자의 가격이 바뀌었을 때"),
    "lowest": ("최저가 변동", "경쟁 최저가가 바뀌었을 때 · 내 가격과의 차이 포함"),
    "login": ("로그인·로그아웃", "로그인 · 로그아웃 · 로그인 실패로 잠김 · 비밀번호 변경 (시각 · 아이디 · 접속 IP) — 빈도·시간대와 관계없이 바로 보냄"),
}
TOPIC_ICON = {"stock": "📦", "price": "🏷", "my_price": "💰", "competitor": "👥", "lowest": "📉", "login": "🔐"}
INSTANT_TOPICS = {"login"}      # 보안 알림: 모으거나 시간대로 미루지 않고 바로 보낸다
STATUS_TTL = 300                # 메뉴 표시용 봇 연결 확인(getMe) 결과를 다시 쓰는 시간(초)
FREQUENCIES = {"realtime": "실시간", "10m": "10분마다 모아서", "1h": "1시간마다 모아서"}
FREQ_MINUTES = {"10m": 10, "1h": 60}
ICON = {"danger": "🔴", "warn": "🟠", "info": "🔵"}
REPEAT_COOLDOWN_SEC = 6 * 3600  # 같은 문장(재고 부족 등)은 6시간에 한 번만
MAX_LEN = 3900                  # 텔레그램 한 메시지 최대 4096자
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class TelegramError(RuntimeError):
    pass


def call(token: str, method: str, timeout: int = 10, **params) -> dict:
    try:
        resp = requests.post(f"{API}/bot{token}/{method}", json=params, timeout=timeout)
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TelegramError(f"텔레그램에 연결하지 못했습니다 ({type(exc).__name__})") from exc
    if not data.get("ok"):
        code, desc = data.get("error_code", resp.status_code), data.get("description", "알 수 없는 오류")
        friendly = {401: "봇 토큰이 올바르지 않습니다", 404: "봇 토큰이 올바르지 않습니다",
                    409: "이 봇은 다른 곳(웹훅/다른 프로그램)에서 메시지를 받고 있어 대화 찾기를 할 수 없습니다. 대화 ID를 직접 입력하세요"}
        if code == 400 and "chat not found" in desc.lower():
            raise TelegramError("대화 ID가 올바르지 않거나, 아직 봇에게 메시지를 보내지 않았습니다")
        raise TelegramError(f"{friendly[code]} ({code})" if code in friendly else f"{code}: {desc}")
    return data["result"]


def find_chats(token: str) -> list[dict]:
    """봇에게 최근 메시지를 보낸 대화 목록 (최신순, 중복 제거)."""
    seen, out = set(), []
    for upd in reversed(call(token, "getUpdates", limit=50)):
        msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is None or chat["id"] in seen:
            continue
        seen.add(chat["id"])
        name = chat.get("title") or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")])) \
            or chat.get("username") or str(chat["id"])
        out.append({"id": str(chat["id"]), "name": name, "type": chat.get("type", "")})
    return out


def in_window(now: datetime, start: str, end: str) -> bool:
    """보낼 수 있는 시간대인지. 시작=끝이면 하루 종일, 22:00~07:00처럼 자정을 넘는 구간도 지원."""
    t = now.strftime("%H:%M")
    if start == end:
        return True
    return start <= t < end if start < end else (t >= start or t < end)


def next_boundary(now: datetime, minutes: int) -> datetime:
    """다음 정각 단위 (10분이면 :00 :10 :20 …, 60분이면 매시 정각)."""
    base = now.replace(second=0, microsecond=0)
    return base + timedelta(minutes=minutes - (base.hour * 60 + base.minute) % minutes)


@dataclass
class Event:
    level: str
    topic: str
    text: str
    key: str | None = None   # 같은 상품의 가격 변동은 모아 보낼 때 한 줄로 합친다
    name: str = ""
    old: int | None = None
    new: int | None = None
    mine: int | None = None
    changes: dict = field(default_factory=dict)  # 경쟁가: {판매자: (이전, 현재)}
    count: int = 1


def _merge(a: Event, b: Event) -> Event:
    """같은 key의 변동을 '처음 값 → 마지막 값'으로 합친다."""
    changes = dict(a.changes)
    for seller, (old, new) in b.changes.items():
        changes[seller] = (changes[seller][0] if seller in changes else old, new)
    return Event(b.level, b.topic, b.text, b.key, b.name, a.old, b.new, b.mine, changes, a.count + b.count)


def describe(e: Event) -> str:
    times = f" ({e.count}회 변동)" if e.count > 1 else ""
    if e.topic == "my_price":
        return f"{e.name}: 내 가격 {e.old:,} → {e.new:,}원{times}"
    if e.topic == "lowest":
        gap = e.mine - e.new
        pos = "내가 최저가" if gap <= 0 else f"내 가격이 {gap:,}원 비쌈"
        return f"{e.name}: 경쟁 최저가 {e.old:,} → {e.new:,}원 (내 가격 {e.mine:,}원 · {pos}){times}"
    if e.topic == "competitor":
        parts = [f"{s} {o:,}→{n:,}" if o is not None else f"{s} 신규 {n:,}"
                 for s, (o, n) in list(e.changes.items())[:6] if o != n]
        more = f" 외 {len(e.changes) - 6}곳" if len(e.changes) > 6 else ""
        return f"{e.name}: " + ", ".join(parts) + more + times
    return e.text


class TelegramNotifier:
    """알림을 모아 두었다가 설정한 빈도·시간대에 맞춰 백그라운드에서 보낸다 (동기화를 막지 않음)."""

    def __init__(self, cfg: dict, mode_fn=lambda: "live", clock=datetime.now, start=True, settle_sec: float = 3.0):
        self.cfg = cfg
        self.mode_fn = mode_fn
        self.clock = clock
        self.last_result: str | None = None
        self.last_ok: bool | None = None          # 마지막 전송 성공 여부 (메뉴 표시용)
        self._bot: dict = {}                      # 봇 연결 확인 캐시: {"key", "at", "name" | "error"}
        self._checking = threading.Event()
        self.next_flush: datetime | None = None
        self._pending: list[Event] = []
        self._lock = threading.Lock()
        self._sent_at: dict[str, float] = {}
        self.settle_sec = settle_sec  # 실시간: 마지막 알림 후 잠깐 기다려 한 번의 동기화분을 한 메시지로
        self._last_push = 0.0
        if start:
            threading.Thread(target=self._loop, daemon=True, name="telegram").start()

    @property
    def tg(self) -> dict:
        return self.cfg.get("telegram") or {}

    @property
    def freq(self) -> str:
        return self.tg.get("frequency") if self.tg.get("frequency") in FREQUENCIES else "realtime"

    def ready(self) -> bool:
        return bool(self.tg.get("enabled") and self.tg.get("token") and self.tg.get("chat_id"))

    def window_open(self, now: datetime | None = None) -> bool:
        return in_window(now or self.clock(), self.tg.get("send_from", "00:00"), self.tg.get("send_to", "00:00"))

    @property
    def upcoming_flush(self) -> datetime | None:
        """화면 표시용 다음 전송 시각 (모아 보내기일 때)."""
        if self.freq == "realtime":
            return None
        return self.next_flush or next_boundary(self.clock(), FREQ_MINUTES[self.freq])

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ---------- 연결 상태 (메뉴 표시) ----------
    def status(self, force: bool = False) -> dict:
        tg = self.tg
        if not tg.get("token"):
            return {"state": "off", "text": "텔레그램 연결 안 함", "detail": "설정 > 텔레그램 알림에서 봇을 연결하세요"}
        bot = self._check_bot(tg["token"], force)
        if bot.get("checking"):
            return {"state": "wait", "text": "텔레그램 확인 중…", "detail": None}
        name = f"@{bot['name']}" if bot.get("name") else ""
        if bot.get("error"):
            return {"state": "bad", "text": "텔레그램 연결 실패", "detail": bot["error"]}
        if not tg.get("chat_id"):
            return {"state": "warn", "text": "텔레그램 대화 미선택", "detail": f"{name} · 설정에서 대화 찾기를 하세요"}
        if not tg.get("enabled"):
            return {"state": "off", "text": "텔레그램 알림 꺼짐", "detail": f"{name} 연결됨 · 설정에서 알림 켜기를 체크하세요"}
        if self.last_ok is False:
            return {"state": "warn", "text": "텔레그램 전송 실패", "detail": f"{name} · {self.last_result}"}
        return {"state": "ok", "text": "텔레그램 연결됨", "detail": " · ".join(filter(None, [name, self.last_result]))}

    def _check_bot(self, token: str, force: bool) -> dict:
        """봇 연결 확인(getMe)은 백그라운드에서 — 메뉴 상태 응답을 텔레그램 응답 시간만큼 늦추지 않는다."""
        key = token[-8:]
        cached = self._bot if self._bot.get("key") == key else {}
        stale = not cached or force or time.time() - cached["at"] >= STATUS_TTL
        if stale and not self._checking.is_set():
            self._checking.set()

            def run():
                try:
                    me = call(token, "getMe", timeout=5)
                    self._bot = {"key": key, "at": time.time(), "name": me.get("username", "")}
                except TelegramError as exc:
                    self._bot = {"key": key, "at": time.time(), "error": str(exc)}
                finally:
                    self._checking.clear()
            threading.Thread(target=run, daemon=True, name="telegram-check").start()
        return cached or {"checking": True}

    def record(self, ok: bool, text: str):
        self.last_ok, self.last_result = ok, text

    # ---------- 바로 보내는 알림 (로그인 등) ----------
    def notify_now(self, topic: str, text: str):
        """고른 항목이면 빈도·시간대와 관계없이 바로 보낸다 (백그라운드, 요청을 막지 않음)."""
        if not self.ready() or topic not in (self.tg.get("topics") or []):
            return
        prefix = "[모의] " if self.mode_fn() == "mock" else ""
        msg = f"{TOPIC_ICON[topic]} {prefix}[{TOPICS[topic][0]}] {text}\n— WING 매니저"

        def run():
            now = self.clock()
            try:
                self.send_now(msg)
                self.record(True, f"{now:%m-%d %H:%M:%S} 전송 성공 (1건)")
            except (TelegramError, KeyError) as exc:
                self.record(False, f"{now:%m-%d %H:%M:%S} 전송 실패: {exc}")
                log.warning("telegram send failed: %s", exc)
        threading.Thread(target=run, daemon=True, name="telegram-now").start()

    # ---------- 알림 받기 ----------
    def on_alert(self, level: str, kind: str, message: str, **meta):
        topic = TOPIC_OF_KIND.get(kind)
        if not topic or not self.ready() or topic not in (self.tg.get("topics") or []):
            return
        if not self.window_open() and self.tg.get("outside", "hold") == "drop":
            return
        if not meta.get("key"):  # 반복되는 문장형 알림만 6시간 억제 (가격 변동은 값이 매번 달라 대상 아님)
            mono = time.monotonic()
            if mono - self._sent_at.get(message, -REPEAT_COOLDOWN_SEC) < REPEAT_COOLDOWN_SEC:
                return
            self._sent_at[message] = mono
        with self._lock:
            if len(self._pending) < 2000:
                self._pending.append(Event(level, topic, message, **meta))
                self._last_push = time.monotonic()

    # ---------- 보내기 ----------
    def tick(self, now: datetime | None = None):
        """주기적으로 호출: 시간대·빈도 조건이 맞으면 모아 둔 알림을 보낸다."""
        now = now or self.clock()
        if self.freq == "realtime":
            self.next_flush = None
        elif self.next_flush is None or self.next_flush - now > timedelta(minutes=FREQ_MINUTES[self.freq]):
            self.next_flush = next_boundary(now, FREQ_MINUTES[self.freq])  # 빈도를 바꾼 경우 다시 계산
        if not self._pending or not self.ready():
            return
        if not self.window_open(now):
            if self.tg.get("outside", "hold") == "drop":  # '보내지 않기'로 바꾸기 전에 쌓인 알림도 버린다
                with self._lock:
                    self._pending = []
            return
        if self.next_flush and now < self.next_flush:
            return
        if not self.next_flush and time.monotonic() - self._last_push < self.settle_sec:
            return
        with self._lock:
            events, self._pending = self._pending, []
        if self.next_flush:
            self.next_flush = next_boundary(now, FREQ_MINUTES[self.freq])
        try:
            for text in self.render(events, now):
                self.send_now(text)
            self.record(True, f"{now:%m-%d %H:%M:%S} 전송 성공 ({len(events)}건)")
        except (TelegramError, KeyError) as exc:
            self.record(False, f"{now:%m-%d %H:%M:%S} 전송 실패: {exc}")
            log.warning("telegram send failed: %s", exc)

    def render(self, events: list[Event], now: datetime) -> list[str]:
        prefix = "[모의] " if self.mode_fn() == "mock" else ""
        footer = f"— WING 매니저 {now:%m-%d %H:%M}"
        if len(events) == 1:
            e = events[0]
            return [f"{ICON.get(e.level, '🔔')} {prefix}[{TOPICS[e.topic][0]}] {describe(e)}\n{footer}"]
        merged: dict = {}
        for i, e in enumerate(events):  # 같은 상품·같은 종류의 가격 변동은 한 줄로
            k = (e.topic, e.key) if e.key else (e.topic, i)
            merged[k] = _merge(merged[k], e) if k in merged else e
        lines = [f"🔔 {prefix}WING 알림 요약 ({len(events)}건)"]
        for topic, (label, _) in TOPICS.items():
            group = [e for (t, _), e in merged.items() if t == topic]
            if group:
                lines.append(f"\n{TOPIC_ICON[topic]} {label} ({len(group)})")
                lines.extend(f"• {describe(e)}" for e in group)
        lines.append(footer)
        chunks, cur = [], ""
        for line in lines:
            if len(cur) + len(line) + 1 > MAX_LEN:
                chunks.append(cur)
                cur = ""
            cur += line + "\n"
        return chunks + [cur.rstrip()]

    def send_now(self, text: str, token: str | None = None, chat_id: str | None = None):
        call(token or self.tg["token"], "sendMessage", chat_id=chat_id or self.tg["chat_id"], text=text,
             disable_web_page_preview=True)

    def _loop(self):
        while True:
            try:
                self.tick()
            except Exception:  # 알림 오류가 스레드를 멈추지 않게
                log.exception("telegram tick failed")
            time.sleep(2)
