"""SQLite 저장소: 상품 스냅샷, 경쟁가 이력, 가격 규칙, 알림, 등록 로그."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  vendor_item_id TEXT PRIMARY KEY, seller_product_id TEXT, name TEXT,
  sale_price INTEGER, stock INTEGER, on_sale INTEGER, status TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS rules (
  vendor_item_id TEXT PRIMARY KEY, low_stock INTEGER DEFAULT 5,
  auto_reprice INTEGER DEFAULT 0, min_price INTEGER DEFAULT 0, undercut INTEGER DEFAULT 10,
  competitor_urls TEXT DEFAULT '', featured INTEGER DEFAULT 0, auto_stopped INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS competitor_prices (
  id INTEGER PRIMARY KEY AUTOINCREMENT, vendor_item_id TEXT, seller TEXT,
  price INTEGER, my_price INTEGER, checked_at TEXT);
CREATE INDEX IF NOT EXISTS ix_cp ON competitor_prices(vendor_item_id, checked_at);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, level TEXT, kind TEXT, message TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS drafts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, data TEXT, note TEXT DEFAULT '', updated_at TEXT);
CREATE TABLE IF NOT EXISTS registrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, result TEXT, ok INTEGER, payload TEXT, created_at TEXT);
"""


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self.alert_listeners: list = []
        self._conn.executescript(SCHEMA)
        cols = {r["name"] for r in self._q("PRAGMA table_info(rules)")}
        for col in ("featured", "auto_stopped"):  # 이전 버전 DB 업그레이드
            if col not in cols:
                self._q(f"ALTER TABLE rules ADD COLUMN {col} INTEGER DEFAULT 0")

    def _q(self, sql: str, args=()):
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return [dict(r) for r in cur.fetchall()]

    # items
    def upsert_items(self, items: list[dict]):
        for it in items:
            self._q(
                "INSERT INTO items VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(vendor_item_id) DO UPDATE SET "
                "seller_product_id=excluded.seller_product_id, name=excluded.name, sale_price=excluded.sale_price, "
                "stock=excluded.stock, on_sale=excluded.on_sale, status=excluded.status, updated_at=excluded.updated_at",
                (it["vendor_item_id"], it["seller_product_id"], it["name"], it["sale_price"],
                 it["stock"], int(it["on_sale"]), it["status"], now()),
            )
            self._q("INSERT OR IGNORE INTO rules(vendor_item_id) VALUES (?)", (it["vendor_item_id"],))

    def replace_items(self, items: list[dict]):
        """받은 목록으로 갱신하고, 목록에 없는 상품(삭제됨·다른 모드의 상품)과 그 규칙은 지운다."""
        self.upsert_items(items)
        keep = [it["vendor_item_id"] for it in items]
        marks = ",".join("?" * len(keep)) or "''"
        for table in ("items", "rules"):
            self._q(f"DELETE FROM {table} WHERE vendor_item_id NOT IN ({marks})", keep)

    def delete_items(self, vendor_item_ids: list[str]):
        for vid in vendor_item_ids:
            for table in ("items", "rules", "competitor_prices"):
                self._q(f"DELETE FROM {table} WHERE vendor_item_id=?", (vid,))

    def items(self) -> list[dict]:
        return self._q(
            "SELECT i.*, r.low_stock, r.auto_reprice, r.min_price, r.undercut, r.competitor_urls, r.featured, r.auto_stopped "
            "FROM items i LEFT JOIN rules r USING(vendor_item_id) ORDER BY r.featured DESC, i.name")

    def item(self, vid: str) -> dict | None:
        rows = [r for r in self.items() if r["vendor_item_id"] == vid]
        return rows[0] if rows else None

    def set_item_field(self, vid: str, field: str, value):
        assert field in ("stock", "sale_price", "on_sale")
        self._q(f"UPDATE items SET {field}=?, updated_at=? WHERE vendor_item_id=?", (value, now(), vid))

    def update_rule(self, vid: str, **fields):
        allowed = {"low_stock", "auto_reprice", "min_price", "undercut", "competitor_urls", "featured", "auto_stopped"}
        for k, v in fields.items():
            if k in allowed:
                self._q(f"UPDATE rules SET {k}=? WHERE vendor_item_id=?", (v, vid))

    # competitor prices
    def add_competitor_prices(self, vid: str, my_price: int, rows: list[dict]):
        ts = now()
        for r in rows:
            self._q("INSERT INTO competitor_prices(vendor_item_id,seller,price,my_price,checked_at) VALUES (?,?,?,?,?)",
                    (vid, r["seller"], r["price"], my_price, ts))

    def latest_competitors(self, vid: str) -> list[dict]:
        return self._q(
            "SELECT seller, price, checked_at FROM competitor_prices WHERE vendor_item_id=? AND checked_at="
            "(SELECT MAX(checked_at) FROM competitor_prices WHERE vendor_item_id=?) ORDER BY price", (vid, vid))

    def lowest_history(self, vid: str, limit: int = 30) -> list[dict]:
        rows = self._q(
            "SELECT checked_at, MIN(price) AS low, MAX(my_price) AS mine FROM competitor_prices "
            "WHERE vendor_item_id=? GROUP BY checked_at ORDER BY checked_at DESC LIMIT ?", (vid, limit))
        return rows[::-1]

    # alerts
    def alert(self, level: str, kind: str, message: str):
        recent = self._q("SELECT message FROM alerts ORDER BY id DESC LIMIT 30")
        if any(r["message"] == message for r in recent):
            return  # 같은 알림 반복 방지
        self._q("INSERT INTO alerts(level,kind,message,created_at) VALUES (?,?,?,?)", (level, kind, message, now()))
        for listener in self.alert_listeners:  # 예: 텔레그램 전송 (중복으로 걸러진 알림은 보내지 않음)
            listener(level, kind, message)

    def delete_alerts(self, ids: list[int] | None = None) -> int:
        """ids 가 None 이면 전체 삭제. 지운 개수를 돌려준다."""
        if ids is None:
            n = self._q("SELECT COUNT(*) AS n FROM alerts")[0]["n"]
            self._q("DELETE FROM alerts")
            return n
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        n = self._q(f"SELECT COUNT(*) AS n FROM alerts WHERE id IN ({marks})", ids)[0]["n"]
        self._q(f"DELETE FROM alerts WHERE id IN ({marks})", ids)
        return n

    def all_alerts(self) -> list[dict]:
        return self._q("SELECT * FROM alerts ORDER BY id")

    def alerts(self, limit: int = 30) -> list[dict]:
        return self._q("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))

    # registrations
    def log_registration(self, name: str, ok: bool, result: str, payload: dict):
        self._q("INSERT INTO registrations(name,result,ok,payload,created_at) VALUES (?,?,?,?,?)",
                (name, result, int(ok), json.dumps(payload, ensure_ascii=False), now()))

    def registrations(self, limit: int = 50) -> list[dict]:
        return self._q("SELECT id,name,result,ok,created_at FROM registrations ORDER BY id DESC LIMIT ?", (limit,))

    def all_registrations(self) -> list[dict]:
        return self._q("SELECT * FROM registrations ORDER BY id")

    def delete_registrations(self, ids: list[int] | None = None) -> int:
        """ids 가 None 이면 전체 삭제. 지운 개수를 돌려준다."""
        if ids is None:
            n = self._q("SELECT COUNT(*) AS n FROM registrations")[0]["n"]
            self._q("DELETE FROM registrations")
            return n
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        marks = ",".join("?" * len(ids))
        n = self._q(f"SELECT COUNT(*) AS n FROM registrations WHERE id IN ({marks})", ids)[0]["n"]
        self._q(f"DELETE FROM registrations WHERE id IN ({marks})", ids)
        return n

    # drafts (상품 등록 임시저장)
    def save_draft(self, data: dict, draft_id: int | None = None, note: str | None = None) -> int:
        name = (data.get("display_name") or data.get("name") or "").strip() or "(이름 없음)"
        blob = json.dumps(data, ensure_ascii=False)
        if draft_id and self.draft(draft_id):
            if note is None:
                self._q("UPDATE drafts SET name=?, data=?, updated_at=? WHERE id=?", (name, blob, now(), draft_id))
            else:
                self._q("UPDATE drafts SET name=?, data=?, note=?, updated_at=? WHERE id=?",
                        (name, blob, note, now(), draft_id))
            return int(draft_id)
        with self._lock:
            cur = self._conn.execute("INSERT INTO drafts(name,data,note,updated_at) VALUES (?,?,?,?)",
                                     (name, blob, note or "", now()))
            self._conn.commit()
            return cur.lastrowid

    def draft(self, draft_id) -> dict | None:
        rows = self._q("SELECT * FROM drafts WHERE id=?", (draft_id,))
        if not rows:
            return None
        return {**rows[0], "data": json.loads(rows[0]["data"])}

    def drafts(self, limit: int = 30) -> list[dict]:
        return self._q("SELECT id,name,note,updated_at FROM drafts ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,))

    def delete_draft(self, draft_id):
        self._q("DELETE FROM drafts WHERE id=?", (draft_id,))
