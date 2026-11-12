"""쿠팡 WING 상점 관리 – 시안 (Flask).

실행:  python app.py   →  http://<서버IP>:26118
API 키가 없으면 모의(mock) 모드로 동작한다. 키는 설정 화면에서 입력하면 config.json 에 저장된다.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests
from flask import Flask, Response, flash, jsonify, redirect, render_template, request, send_from_directory, url_for

from coupang_client import CoupangAPIError, CoupangClient
from mock_backend import MockCompetitorProvider, MockCoupangClient
from notifier import FREQUENCIES, TIME_RE, TOPICS, TelegramError, TelegramNotifier, find_chats
from categories import CategoryError, CategoryStore, nodes_from_api_tree, nodes_from_file
import auth as wing_auth
import login_page
import reg_status
import competitor_shop
import draft_export
import health
import keywords
import product_form as pf
import rocket_growth
from product_form import build_product_payload, product_names, validate_form
from services import (CSV_COLUMNS, CSV_HEADERS, DOC_MAX_MB, SyncService, clean_html, csv_template, detect_document,
                      detect_image, parse_csv)
from store import Store

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("WING_DATA_DIR", BASE))  # 테스트는 임시 폴더를 써서 실제 설정/DB를 건드리지 않는다
CONFIG_PATH = DATA_DIR / "config.json"
UPLOAD_DIR = DATA_DIR / "uploads"
MAX_UPLOAD_MB = 10
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("wing")


def load_config() -> dict:
    cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    cfg.setdefault("sync_interval_sec", 30)
    cfg.setdefault("auto_soldout", True)
    cfg.setdefault("soldout_threshold", 5)
    cfg.setdefault("product_defaults", {})
    return cfg


def save_config(cfg: dict):
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(tmp, 0o600)  # 키가 들어 있으므로 소유자만 읽기
    tmp.replace(CONFIG_PATH)


def make_client(c: dict):
    if c.get("access_key") and c.get("secret_key") and c.get("vendor_id"):
        return CoupangClient(c["access_key"], c["secret_key"], c["vendor_id"])
    return MockCoupangClient()


cfg = load_config()
client = make_client(cfg)
# 경쟁사 가격: 쿠팡 Open API에는 타 판매자 가격 조회 API가 없어서 공급자를 교체 가능하게 분리했다.
competitor = MockCompetitorProvider()
# 연관검색어도 Open API에 없어서 같은 방식으로 분리했다 (keywords.py). 기본은 구글·네이버·다음·쿠팡에 실제로 묻는다.
keyword_provider = (keywords.MockKeywordProvider()
                    if os.environ.get("WING_KEYWORDS") == "mock" or cfg.get("keyword_provider") == "mock"
                    else keywords.LiveKeywordProvider())
store = Store(str(DATA_DIR / "wing.db"))
categories = CategoryStore(DATA_DIR / "categories.json")
sync = SyncService(client, store, competitor, cfg)
notifier = TelegramNotifier(cfg, lambda: client.mode)
store.alert_listeners.append(notifier.on_alert)
sync.event_listeners.append(notifier.on_alert)
reg_checker = reg_status.StatusChecker(
    store, lambda: client,
    on_rejected=lambda name, spid, reason: store.alert("danger", "register", f"쿠팡 승인반려: {name} ({spid}) — {reason}"))

app = Flask(__name__)
login_auth = wing_auth.Auth(DATA_DIR / ".env")
login_auth.listeners.append(lambda text: notifier.notify_now("login", text))
wing_auth.init_app(app, login_auth)  # 로그인 정보는 .env (config.json 과 분리)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024


@app.context_processor
def inject_globals():
    return {"mode": client.mode, "sync": sync, "cfg": cfg, "login_page": login_page.get(cfg),
            "theme": cfg.get("theme") if cfg.get("theme") in THEMES else "system"}


THEMES = {"system": "시스템 설정 따르기", "light": "라이트 모드", "dark": "다크 모드"}


def _price_rows():
    rows = []
    shops = store.competitor_shops()
    for it in store.items():
        comps = competitor_shop.attach(store.latest_competitors(it["vendor_item_id"]), shops)
        low = min((c["price"] for c in comps), default=None)
        prices = sorted([c["price"] for c in comps] + [it["sale_price"]])
        rows.append({
            **it, "competitors": comps, "lowest": low,
            "diff": (it["sale_price"] - low) if low is not None else None,
            "rank": prices.index(it["sale_price"]) + 1, "total": len(prices),
            "history": store.lowest_history(it["vendor_item_id"]),
        })
    return rows


def _dashboard_data(items: list[dict], rows: list[dict]) -> dict:
    """대시보드의 KPI 와 주력 상품. 기존 Jinja 화면과 새 화면(/ui)이 같은 값을 쓰도록 한 곳에 둔다."""
    return {
        "kpi": {
            "total": len(items),
            "stock_value": sum(i["stock"] * i["sale_price"] for i in items),
            "low": sum(1 for i in items if i["on_sale"] and i["stock"] <= i["low_stock"]),
            "soldout": sum(1 for i in items if not i["on_sale"]),
            "undercut": sum(1 for r in rows if r["diff"] and r["diff"] > 0),
            "auto": sum(1 for i in items if i["auto_reprice"]),
        },
        "featured": [r for r in rows if r["featured"]],
    }


# ---------------- 페이지 ----------------
@app.route("/")
def dashboard():
    items = store.items()
    rows = _price_rows()
    data = _dashboard_data(items, rows)
    return render_template("dashboard.html", kpi=data["kpi"], alerts=store.alerts(15),
                           rows=rows, featured=data["featured"])


ALERT_LEVEL = {"danger": "ERROR", "warn": "WARN", "info": "INFO"}


@app.route("/alerts/delete", methods=["POST"])
def delete_alerts():
    if request.form.get("scope") == "all":
        n = store.delete_alerts(None)
    else:
        ids = [i for i in request.form.getlist("alert_id") if i.isdigit()]
        if not ids:
            flash("지울 알림을 선택하세요", "danger")
            return redirect(url_for("dashboard"))
        n = store.delete_alerts(ids)
    flash(f"알림 {n}건을 지웠습니다", "info")
    return redirect(url_for("dashboard"))


@app.route("/alerts/export.log")
def export_alerts():
    lines = [f"# WING 매니저 알림 로그 · {datetime.now():%Y-%m-%d %H:%M:%S} 저장 · "
             f"{'모의' if client.mode == 'mock' else '실연동'} 모드"]
    lines += [f"{a['created_at']} [{ALERT_LEVEL.get(a['level'], a['level'].upper())}] [{a['kind']}] {a['message']}"
              for a in store.all_alerts()]
    return Response("\n".join(lines) + "\n", mimetype="text/plain; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=wing-alerts-{datetime.now():%Y%m%d-%H%M%S}.log"})


@app.route("/inventory", methods=["GET", "POST"])
def inventory():
    if request.method == "POST":
        vid = request.form["vendor_item_id"]
        try:
            if request.form.get("stock", "").strip():
                qty = int(request.form["stock"])
                client.update_quantity(vid, qty)
                store.set_item_field(vid, "stock", qty)
            store.update_rule(vid, low_stock=int(request.form.get("low_stock") or 0))
            sync.apply_soldout_rule(store.item(vid))  # 입고로 기준 이상이 되면 바로 판매재개
            flash("재고 정보를 반영했습니다", "info")
        except (CoupangAPIError, ValueError) as exc:
            flash(f"실패: {exc}", "danger")
        return redirect(url_for("inventory"))
    return render_template("inventory.html", items=store.items())


@app.route("/items/<vid>/featured", methods=["POST"])
def toggle_featured(vid):
    item = store.item(vid)
    if item:
        store.update_rule(vid, featured=0 if item["featured"] else 1)
    return redirect(request.referrer or url_for("inventory"))


@app.route("/items/<vid>/sale", methods=["POST"])
def toggle_sale(vid):
    item = store.item(vid)
    try:
        if item["on_sale"]:
            client.stop_sale(vid)
        else:
            client.resume_sale(vid)
        store.set_item_field(vid, "on_sale", 0 if item["on_sale"] else 1)
        store.update_rule(vid, auto_stopped=0)  # 수동 조작한 상품은 자동 재개 대상에서 뺀다
        flash(f"{'판매중지' if item['on_sale'] else '판매재개'}: {item['name']}", "info")
    except CoupangAPIError as exc:
        flash(f"실패: {exc}", "danger")
    return redirect(url_for("inventory"))


@app.route("/items/delete", methods=["POST"])
def delete_items():
    spids = [s for s in request.form.getlist("seller_product_id") if s.strip()]
    if not spids:
        flash("삭제할 상품을 선택하세요", "danger")
    elif request.form.get("confirm", "").strip() != "삭제":
        flash("확인 칸에 '삭제'를 정확히 입력해야 삭제됩니다", "danger")
    else:
        for name, ok, msg in sync.delete_products(spids, stop_first=bool(request.form.get("stop_first"))):
            flash(f"{'🗑' if ok else '⚠'} {name}: {msg}", "info" if ok else "danger")
    return redirect(url_for("inventory"))


@app.route("/prices")
def prices():
    return render_template("prices.html", rows=_price_rows())


def _keyword_data(source: str) -> dict:
    """실시간 검색어 화면 내용 (출처 하나): 내 상품별 연관검색어. 출처가 실패해도 오류 문구와 함께 화면은 그대로 뜬다."""
    if source not in keywords.SOURCES:
        source = keywords.DEFAULT_SOURCE
    mock = getattr(keyword_provider, "name", "") == "mock"
    out = {"source": source, "label": keywords.SOURCES[source][0], "mock": mock, "mock_on_live": mock and client.mode == "live",
           "products": [], "related_error": None, "checked": datetime.now().strftime("%H:%M:%S")}
    out["products"], out["related_error"] = keywords.product_rows(keyword_provider, store.items(), source)
    return out


@app.route("/keywords")
def keyword_page():
    return render_template("keywords.html", sources=[{"id": k, "label": v[0]} for k, v in keywords.SOURCES.items()],
                           default_source=keywords.DEFAULT_SOURCE,
                           mock=getattr(keyword_provider, "name", "") == "mock", mock_on_live=getattr(keyword_provider, "name", "") == "mock" and client.mode == "live")


@app.route("/prices/rule", methods=["POST"])
def price_rule():
    f = request.form
    store.update_rule(
        f["vendor_item_id"], auto_reprice=1 if f.get("auto_reprice") else 0,
        min_price=int(f.get("min_price") or 0), undercut=int(f.get("undercut") or 0),
    )
    flash("가격 규칙을 저장했습니다", "info")
    return redirect(url_for("prices"))


# ---- 카테고리 메타·출고지·반품지 (조회 전용, 짧게 캐시) ----
_cache: dict = {}
CACHE_SEC = {"meta": 6 * 3600, "places": 300}


def _cached(kind: str, key, fetch, refresh: bool = False):
    hit = _cache.get((kind, key))
    if hit and not refresh and time.time() - hit[0] < CACHE_SEC[kind]:
        return hit[1]
    value = fetch()
    _cache[(kind, key)] = (time.time(), value)
    return value


def category_meta(code, refresh: bool = False) -> dict | None:
    """카테고리 메타정보. 코드가 없거나 조회에 실패하면 None (검증은 메타 없이 기본 항목만)."""
    if not str(code or "").isdigit():
        return None
    try:
        return _cached("meta", (client.mode, str(code)), lambda: client.get_category_meta(code), refresh)
    except (CoupangAPIError, requests.RequestException) as exc:
        log.warning("카테고리 메타 조회 실패 %s: %s", code, exc)
        return None


def shipping_places(refresh: bool = False) -> dict:
    out = {"outbound": [], "returns": [], "errors": []}
    for key, fetch, label in (("outbound", client.list_outbound_places, "출고지"),
                              ("returns", client.list_return_centers, "반품지")):
        try:
            out[key] = _cached("places", (client.mode, key), fetch, refresh)
        except (CoupangAPIError, requests.RequestException) as exc:
            out["errors"].append(f"{label} 목록을 불러오지 못했습니다: {exc}")
    return out


def _form_data() -> dict:
    keys = set(CSV_COLUMNS) | set(pf.FORM_DEFAULTS) | {"model_no", "manufacture", "notice_category", "offer_description"}
    keys.discard("overseas_purchased")  # 배송방법(구매대행)에서 정해짐
    data = {k: request.form[k].strip() for k in keys if k in request.form}  # 없는 칸만 기본값으로
    for key in pf.JSON_KEYS:
        data[key] = request.form.get(key, "")
    data["parallel_imported"] = "1" if request.form.get("parallel_imported") else ""
    if request.form.get("has_sell_mode"):  # 판매방식 칸이 있는 화면에서 온 요청: 체크 해제 = 폼에 없음 = '꺼짐'
        for key in rocket_growth.CHECKBOX_KEYS:
            data[key] = "1" if request.form.get(key) else ""
    data["description_html"] = clean_html(request.form.get("description_html", ""))
    data["request_approval"] = "1" if request.form.get("request_approval") else ""
    return pf.normalize_form(data, pf.defaults_from_config(cfg))


def _remember_defaults(form: dict):
    cfg["register_defaults"] = {k: form[k] for k in pf.REMEMBER_KEYS if k in form}
    save_config(cfg)


@app.route("/register", methods=["GET", "POST"])
def register():
    preview = None
    draft_id = request.values.get("draft_id", type=int)
    form: dict = {}
    errors: list[str] = []
    step = request.values.get("step") if request.values.get("step") in pf.STEP_IDS else pf.STEP_IDS[0]
    if request.method == "GET" and draft_id:
        d = store.draft(draft_id)
        form, draft_id = (d["data"], draft_id) if d else ({}, None)
        if "display_name" not in form:  # 상품명이 하나였던 이전 임시저장 → 노출상품명으로 옮김
            form = {**form, "display_name": form.get("name", ""), "name": ""}
    if request.method == "POST":
        action = request.form.get("action")
        if action == "csv":
            _register_csv(request.files.get("csv_file"), bool(request.form.get("request_approval")))
            return redirect(url_for("register"))
        form = _form_data()
        if request.form.get("remember_defaults"):
            _remember_defaults(form)
        if action == "draft":  # 필수값 없이도 언제든 저장
            draft_id = store.save_draft(form, draft_id)
            flash(f"임시저장했습니다: {product_names(form)[0] or '(이름 없음)'}", "info")
            return redirect(url_for("register", draft_id=draft_id, step=step))
        meta = category_meta(form.get("category_code"))
        errors = validate_form(form, categories, meta)
        if meta is None and form.get("category_code"):
            errors.append("카테고리 정보(필수 옵션·고시정보)를 쿠팡에서 불러오지 못했습니다. 잠시 후 다시 시도하세요")
        for e in errors:
            flash(e, "danger")
        if not errors:
            # WING 버튼: 저장하기 = 쿠팡에 임시저장 상태로, 판매요청 = 바로 승인요청
            approve = {"save": False, "request": True}.get(action, bool(form["request_approval"]))
            payload = build_product_payload(form, cfg.get("vendor_id", "A00000000"), approve, meta)
            if action == "preview":
                preview = json.dumps(payload, ensure_ascii=False, indent=2)
                step = "s-confirm"
            else:
                ok, msg = _submit(product_names(form)[0], payload)
                if ok:  # 등록한 내용도 임시저장 목록에 남겨, 이어서 수정·재저장할 수 있게 한다
                    draft_id = store.save_draft(form, draft_id, note=msg)
                    return redirect(url_for("register", draft_id=draft_id, step="s-confirm"))
    form = pf.normalize_form(form, pf.defaults_from_config(cfg))
    error_steps = {pf.step_of_error(e) for e in errors}
    if error_steps:  # 오류가 있는 첫 단계부터 다시 보여 준다
        step = min(error_steps, key=pf.STEP_IDS.index)
    return render_template("register.html", start_step=step, error_steps=error_steps,
                           start_sub=min((pf.sub_of_error(e) for e in errors if pf.step_of_error(e) == "s-main"), default=0),
                           resume=bool(draft_id or request.method == "POST"), preview=preview, logs=store.registrations(), form=form,
                           form_json={k: form[k] for k in pf.JSON_KEYS}, draft_id=draft_id, drafts=store.drafts(),
                           columns=CSV_HEADERS, public_base=cfg.get("public_base_url", ""), cat=categories.summary(),
                           cat_path=categories.path_of(form.get("category_code", "")), pf=pf,
                           has_saved_defaults=bool(cfg.get("register_defaults")))


@app.route("/api/category-meta/<code>")
def api_category_meta(code):
    problem = categories.check(code) if code.isdigit() else "카테고리 코드가 올바르지 않습니다"
    if problem:
        return jsonify({"error": problem}), 400
    meta = category_meta(code, refresh=bool(request.args.get("refresh")))
    if meta is None:
        return jsonify({"error": "쿠팡에서 카테고리 정보를 불러오지 못했습니다"}), 502
    return jsonify(meta)


@app.route("/api/shipping-places")
def api_shipping_places():
    return jsonify(shipping_places(refresh=bool(request.args.get("refresh"))))


@app.route("/drafts/<int:draft_id>/delete", methods=["POST"])
def delete_draft(draft_id):
    store.delete_draft(draft_id)
    flash("임시저장을 삭제했습니다", "info")
    return redirect(url_for("register"))


@app.route("/register/history/delete", methods=["POST"])
def delete_registrations():
    if request.form.get("scope") == "all":
        n = store.delete_registrations(None)
    else:
        ids = [i for i in request.form.getlist("reg_id") if i.isdigit()]
        if not ids:
            flash("지울 등록 이력을 선택하세요", "danger")
            return redirect(url_for("register") + "#reg-history")
        n = store.delete_registrations(ids)
    flash(f"등록 이력 {n}건을 지웠습니다", "info")
    return redirect(url_for("register") + "#reg-history")


@app.route("/register/history/status", methods=["POST"])
def refresh_registration_status():
    """쿠팡 '상품 상태변경이력'을 읽어 승인·반려 상태와 반려 사유를 갱신한다 (조회만, 상품은 바꾸지 않음)."""
    ids = [int(i) for i in request.form.getlist("reg_id") if i.isdigit()] or None
    res = reg_checker.refresh(ids, include_final=bool(ids))
    if res.get("busy"):
        flash("이미 쿠팡 상태를 확인하는 중입니다. 잠시 뒤 다시 보세요", "info")
    elif not (res["checked"] or res["errors"]):
        flash("확인할 이력이 없습니다 (쿠팡에 등록된 이력만, 승인완료·삭제된 상품은 선택했을 때만 다시 확인)", "info")
    else:
        msg = f"쿠팡 상태 {res['checked']}건 확인" + (f" · 새 반려 {res['rejected']}건" if res["rejected"] else "") + \
              (f" · 실패 {res['errors']}건" if res["errors"] else "")
        flash(msg, "danger" if res["rejected"] or res["errors"] else "info")
    return redirect(url_for("register") + "#reg-history")


@app.route("/register/history/export.log")
def export_registrations():
    """등록 이력 전체를 오래된 것부터. 실패 건은 원인 확인용으로 보낸 내용(JSON)도 함께 적는다."""
    rows = store.all_registrations()
    lines = [f"# WING 매니저 상품 등록 이력 · {datetime.now():%Y-%m-%d %H:%M:%S} 저장 · "
             f"{'모의' if client.mode == 'mock' else '실연동'} 모드 · {len(rows)}건"]
    for r in rows:
        lines.append(f"{r['created_at']} [{'OK' if r['ok'] else 'FAIL'}] {r['name']} | {r['result']}")
        if r.get("cp_status"):
            lines.append(f"    쿠팡 상태: {r['cp_status']} ({r['cp_at']}) {r['cp_comment'] or ''}".rstrip()
                         + (f" | 반려 사유: {r['cp_reason']}" if r.get("cp_reason") else ""))
        if not r["ok"] and r["payload"]:
            lines.append(f"    payload: {r['payload']}")
    return Response("\n".join(lines) + "\n", mimetype="text/plain; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=wing-register-{datetime.now():%Y%m%d-%H%M%S}.log"})


def _selected_drafts() -> list[dict]:
    ids = [int(i) for i in request.form.getlist("draft_ids") if i.isdigit()]
    return [d for d in (store.draft(i) for i in ids) if d]


@app.route("/register/drafts/export.csv", methods=["GET", "POST"])
def export_drafts():
    """임시저장 → 일괄등록 템플릿 CSV. 고른 것이 없으면(또는 GET) 전체."""
    drafts = _selected_drafts() if request.method == "POST" else []
    if not drafts:
        drafts = [x for x in (store.draft(d["id"]) for d in store.drafts(limit=1000)) if x]
    if not drafts:
        flash("내려받을 임시저장이 없습니다", "danger")
        return redirect(url_for("register"))
    text, _, _ = draft_export.drafts_csv(drafts)
    return Response(text, mimetype="text/csv; charset=utf-8", headers={
        "Content-Disposition": f"attachment; filename=coupang_drafts_{datetime.now():%Y%m%d-%H%M%S}.csv"})


@app.route("/register/drafts/submit", methods=["POST"])
def submit_drafts():
    """고른 임시저장만 쿠팡에 등록. 각각 단건 등록과 같은 검사를 거치고, 성공하면 임시저장에 '등록됨'으로 남긴다."""
    drafts = _selected_drafts()
    if not drafts:
        flash("등록할 임시저장을 선택하세요", "danger")
        return redirect(url_for("register"))
    approve = bool(request.form.get("request_approval"))
    defaults = pf.defaults_from_config(cfg)
    ok = fail = 0
    for d in drafts:
        form = pf.normalize_form(d["data"], defaults)
        name = product_names(form)[0] or f"임시저장 #{d['id']}"
        meta = category_meta(form.get("category_code"))
        errors = validate_form(form, categories, meta)
        if meta is None and form.get("category_code"):
            errors.append("카테고리 정보(필수 옵션·고시정보)를 쿠팡에서 불러오지 못했습니다")
        if errors:
            fail += 1
            store.log_registration(name, False, "; ".join(errors), form, mode=client.mode)
            flash(f"'{name}' 등록 안 함: " + "; ".join(errors[:3]) + (f" 외 {len(errors) - 3}건" if len(errors) > 3 else ""),
                  "danger")
            continue
        payload = build_product_payload(form, cfg.get("vendor_id", "A00000000"), approve, meta)
        success, msg = _submit(name, payload)
        if success:
            ok += 1
            store.save_draft(d["data"], d["id"], note=msg)
        else:
            fail += 1
    flash(f"선택 등록: 성공 {ok}건 / 실패 {fail}건" + (" (바로 승인요청)" if approve else " (쿠팡에 임시저장)"),
          "info" if not fail else "danger")
    return redirect(url_for("register"))


@app.route("/register/template.csv")
def csv_template_download():
    return Response(csv_template(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": "attachment; filename=coupang_products_template.csv"})


def _submit(name: str, payload: dict) -> tuple[bool, str]:
    try:
        res = client.create_product(payload)
        msg = ("[모의] " if client.mode == "mock" else "") + f"등록 완료 sellerProductId={res.get('data')}"
        store.log_registration(name, True, msg, payload, mode=client.mode, seller_product_id=res.get("data"))
        flash(f"'{name}' {msg}", "info")
        return True, msg
    except CoupangAPIError as exc:
        store.log_registration(name, False, str(exc), payload, mode=client.mode)
        flash(f"'{name}' 등록 실패: {exc}", "danger")
        return False, str(exc)


def _register_csv(file, request_approval: bool):
    if not file or not file.filename:
        flash("CSV 파일을 선택하세요", "danger")
        return
    try:
        rows = parse_csv(file.read().decode("utf-8-sig"))
    except UnicodeDecodeError:
        flash("CSV를 읽을 수 없습니다. 템플릿을 내려받아 'CSV UTF-8' 형식으로 저장해 주세요", "danger")
        return
    ok = fail = 0
    defaults = pf.defaults_from_config(cfg)
    for row in rows:
        row = pf.normalize_form(row, defaults)
        meta = category_meta(row.get("category_code"))
        pf.autofill_notices(row, meta)
        errors = validate_form(row, categories, meta)
        if errors:
            store.log_registration(product_names(row)[0] or "?", False, "; ".join(errors), row)
            fail += 1
            continue
        row["description_html"] = clean_html(row.get("description_html", ""))
        payload = build_product_payload(row, cfg.get("vendor_id", "A00000000"), request_approval, meta)
        ok, fail = (ok + 1, fail) if _submit(product_names(row)[0], payload)[0] else (ok, fail + 1)
    flash(f"CSV 일괄등록: 성공 {ok}건 / 실패 {fail}건", "info")


# ---------------- 이미지 업로드 ----------------
@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "파일이 없습니다"}), 400
    data = f.read()
    if request.form.get("kind") == "doc":  # 구비서류: 쿠팡 기준 5MB 이하 PDF·HWP·DOC·DOCX·TXT·PNG·JPG
        ext = detect_document(data[:16], f.filename)
        if not ext:
            return jsonify({"error": "PDF, HWP, DOC, DOCX, TXT, PNG, JPG 파일만 올릴 수 있습니다"}), 400
        if len(data) > DOC_MAX_MB * 1024 * 1024:
            return jsonify({"error": f"구비서류는 {DOC_MAX_MB}MB 이하만 올릴 수 있습니다"}), 400
    else:
        ext = detect_image(data[:16])
    if not ext:
        return jsonify({"error": "JPG, PNG, GIF, WEBP 이미지만 올릴 수 있습니다"}), 400
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.{ext}"
    (UPLOAD_DIR / name).write_bytes(data)
    base = (cfg.get("public_base_url") or request.host_url).rstrip("/")
    return jsonify({"url": f"{base}{url_for('uploaded', name=name)}", "name": name})


@app.route("/uploads/<name>")
def uploaded(name):
    return send_from_directory(UPLOAD_DIR, name)


@app.errorhandler(413)
def too_large(_):
    msg = f"파일이 너무 큽니다 (최대 {MAX_UPLOAD_MB}MB)"
    if request.path.startswith("/api/"):
        return jsonify({"error": msg}), 413
    flash(msg, "danger")
    return redirect(request.referrer or url_for("register"))


# ---------------- 설정 ----------------
def _key_form() -> dict:
    """입력값 + 비워 둔 칸은 기존 값 유지 (Secret Key 는 화면에 다시 보여주지 않으므로)."""
    f = request.form
    return {
        "access_key": f.get("access_key", "").strip() or cfg.get("access_key", ""),
        "secret_key": f.get("secret_key", "").strip() or cfg.get("secret_key", ""),
        "vendor_id": f.get("vendor_id", "").strip() or cfg.get("vendor_id", ""),
    }


def _apply_client(new_cfg: dict):
    global client
    client = make_client(new_cfg)
    sync.client = client
    _cache.clear()  # 다른 계정·모드의 카테고리 메타/출고지를 섞지 않는다


@app.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "test":
            keys = _key_form()
            if not all(keys.values()):
                flash("Access Key, Secret Key, 업체코드를 모두 입력하세요", "danger")
            else:
                try:
                    CoupangClient(**keys).ping()
                    flash("연결 성공: 쿠팡 API 인증이 확인되었습니다", "info")
                except (CoupangAPIError, OSError) as exc:
                    flash(f"연결 실패: {exc}", "danger")
        elif action == "save_keys":
            cfg.update(_key_form())
            save_config(cfg)
            _apply_client(cfg)
            flash(f"API 키를 저장했습니다 → {'실연동' if client.mode == 'live' else '모의'} 모드", "info")
        elif action == "clear_keys":
            for k in ("access_key", "secret_key"):
                cfg.pop(k, None)
            save_config(cfg)
            _apply_client(cfg)
            flash("API 키를 삭제했습니다 → 모의 모드", "info")
        elif action == "save_rules":
            base = request.form.get("public_base_url", "").strip().rstrip("/")
            try:  # 모두 검증한 뒤에 한꺼번에 반영 (일부만 바뀌는 일 방지)
                interval = max(5, int(request.form.get("sync_interval_sec") or 30))
                threshold = max(0, int(request.form.get("soldout_threshold") or 0))
            except ValueError:
                flash("숫자를 입력하세요", "danger")
                return redirect(url_for("settings"))
            if base and not base.startswith(("http://", "https://")):
                flash("이미지 공개 주소는 http:// 또는 https:// 로 시작해야 합니다", "danger")
                return redirect(url_for("settings"))
            cfg.update(sync_interval_sec=interval, soldout_threshold=threshold,
                       auto_soldout=bool(request.form.get("auto_soldout")), public_base_url=base)
            save_config(cfg)
            flash("자동화 설정을 저장했습니다", "info")
        elif action == "save_theme":
            theme = request.form.get("theme")
            if theme not in THEMES:
                flash("화면 모드를 다시 고르세요", "danger")
            else:
                cfg["theme"] = theme
                save_config(cfg)
                flash(f"화면 모드: {THEMES[theme]}", "info")
            return redirect(url_for("settings"))
        elif action == "save_login_page":
            lp, errors = login_page.from_form(request.form, login_page.get(cfg))
            if errors:  # 오류 안내는 화면 맨 위에 나오므로 섹션으로 내려가지 않는다
                for e in errors:
                    flash(e, "danger")
                return redirect(url_for("settings"))
            else:
                cfg["login_page"] = lp
                save_config(cfg)
                flash("로그인 화면 설정을 저장했습니다", "info")
            return redirect(url_for("settings") + "#login-page")
        elif action == "reset_login_page":
            cfg.pop("login_page", None)
            save_config(cfg)
            flash("로그인 화면을 기본 모양으로 되돌렸습니다", "info")
            return redirect(url_for("settings") + "#login-page")
        return redirect(url_for("settings"))
    status = {k: bool(cfg.get(k)) for k in ("access_key", "secret_key")}
    saved = cfg.get("telegram") or {}
    tg = {**saved, **session_chats.pop("form", {})}
    return render_template("settings.html", status=status, cat=categories.summary(), topics=TOPICS,
                           tg=tg, tg_has_token=bool(saved.get("token")), tg_chats=session_chats.pop("chats", None),
                           tg_last=notifier.last_result, freqs=FREQUENCIES, tg_pending=notifier.pending_count,
                           tg_next=notifier.upcoming_flush, tg_window_open=notifier.window_open(),
                           mock_competitor_live=sync.competitor_is_mock_on_live,
                           layouts=login_page.LAYOUTS, themes=THEMES)


session_chats: dict = {}  # '대화 찾기' 결과를 다음 화면 한 번에만 보여 주기 위한 임시 보관


def _tg_form() -> dict:
    """빈 토큰 칸은 기존 값 유지 (토큰은 화면에 다시 보여주지 않음)."""
    old = cfg.get("telegram") or {}
    f = request.form
    return {
        "token": f.get("token", "").strip() or old.get("token", ""),
        "chat_id": f.get("chat_id", "").strip(),
        "enabled": bool(f.get("enabled")),
        "topics": [t for t in f.getlist("topics") if t in TOPICS],
        "frequency": f.get("frequency") if f.get("frequency") in FREQUENCIES else "realtime",
        "send_from": f.get("send_from", "00:00").strip() or "00:00",
        "send_to": f.get("send_to", "00:00").strip() or "00:00",
        "outside": "drop" if f.get("outside") == "drop" else "hold",
    }


@app.route("/settings/telegram", methods=["POST"])
def telegram_settings():
    action, tg = request.form.get("action"), _tg_form()
    try:
        if action != "clear" and not (TIME_RE.match(tg["send_from"]) and TIME_RE.match(tg["send_to"])):
            raise TelegramError("보낼 시간대는 00:00 ~ 23:59 형식으로 입력하세요")
        if action == "clear":
            cfg.pop("telegram", None)
            save_config(cfg)
            flash("텔레그램 연결을 해제했습니다", "info")
        elif not tg["token"]:
            raise TelegramError("봇 토큰을 입력하세요")
        elif action == "find_chat":
            chats = find_chats(tg["token"])
            if not chats:
                raise TelegramError("봇에게 온 메시지가 없습니다. 텔레그램에서 봇에게 아무 메시지나 보낸 뒤 다시 눌러 주세요")
            cfg["telegram"] = {**tg, "chat_id": tg["chat_id"] or chats[0]["id"]}
            save_config(cfg)
            session_chats["chats"] = chats
            flash(f"대화 {len(chats)}개를 찾았습니다. 알림 받을 대화를 확인하세요", "info")
        elif action == "test":
            if not tg["chat_id"]:
                raise TelegramError("대화 ID(chat id)를 입력하거나 '대화 찾기'를 눌러 주세요")
            notifier.send_now("✅ WING 매니저 텔레그램 연결 테스트입니다.", tg["token"], tg["chat_id"])
            notifier.record(True, f"{datetime.now():%m-%d %H:%M:%S} 테스트 메시지 전송 성공")
            cfg["telegram"] = tg
            save_config(cfg)
            flash("테스트 메시지를 보냈습니다. 텔레그램을 확인하세요", "info")
        else:  # save
            if tg["enabled"] and not tg["chat_id"]:
                raise TelegramError("알림을 켜려면 대화 ID가 필요합니다")
            cfg["telegram"] = tg
            save_config(cfg)
            on = ", ".join(TOPICS[t][0] for t in tg["topics"]) or "선택 없음"
            when = "하루 종일" if tg["send_from"] == tg["send_to"] else f"{tg['send_from']}~{tg['send_to']}"
            flash(f"텔레그램 설정을 저장했습니다 ({'켜짐' if tg['enabled'] else '꺼짐'} · {on} · "
                  f"{FREQUENCIES[tg['frequency']]} · {when})", "info")
    except TelegramError as exc:
        flash(f"텔레그램: {exc}", "danger")
        # 실패해도 입력한 대화 ID·선택 항목은 다시 보여 준다 (토큰은 보안상 다시 채우지 않음)
        session_chats["form"] = {k: v for k, v in tg.items() if k != "token"}
    return redirect(url_for("settings") + "#telegram")


@app.route("/settings/categories", methods=["POST"])
def load_categories():
    try:
        if request.form.get("action") == "api":
            if client.mode != "live":
                raise CategoryError("API 키를 먼저 저장하세요")
            categories.replace(nodes_from_api_tree(client.get_categories()), "api")
        else:
            f = request.files.get("cat_file")
            if not f or not f.filename:
                raise CategoryError("파일을 선택하세요")
            categories.replace(nodes_from_file(f.filename, f.read()), "file")
        s = categories.summary()
        flash(f"카테고리 {s['count']:,}개를 불러왔습니다 (등록 가능한 최하위 {s['leaves']:,}개)", "info")
    except (CategoryError, CoupangAPIError, OSError) as exc:
        flash(f"카테고리 불러오기 실패: {exc}", "danger")
    return redirect(url_for("settings"))


@app.route("/api/categories")
def api_categories():
    return jsonify({**categories.summary(), "nodes": categories.data["nodes"]})


# ---------------- JSON API (실시간 갱신용) ----------------
@app.route("/api/prices")
def api_prices():
    rows = _price_rows()
    for r in rows:
        r.pop("history", None)
    return jsonify({"last_sync": sync.last_sync, "rows": rows})


@app.route("/api/keywords")
def api_keywords():
    return jsonify(_keyword_data(request.args.get("source", keywords.DEFAULT_SOURCE)))


@app.route("/api/keyword-suggest")
def api_keyword_suggest():
    """상품 등록 화면의 검색어 추천: 상품 이름 하나를 여러 출처에 물어 합친 최대 20개.

    name     추천의 바탕이 되는 상품 이름 (필수)
    exclude  이미 넣어 둔 검색어 (콤마로 구분) — 중복으로 추천하지 않는다
    sources  출처 id 콤마 구분 (기본: 전체)
    """
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"error": "상품 이름을 먼저 입력하세요."}), 400
    exclude = [t.strip() for t in (request.args.get("exclude") or "").split(",") if t.strip()]
    asked = [s.strip() for s in (request.args.get("sources") or "").split(",") if s.strip()]
    sources = [s for s in asked if s in keywords.SOURCES] or None
    room = max(0, keywords.MAX_TAGS - len(exclude))
    suggestions, errors = keywords.suggest_tags(
        keyword_provider, name, sources=sources, limit=room, exclude=exclude)
    return jsonify({"query": keywords.base_keyword(name), "limit": keywords.MAX_TAGS, "room": room,
                    "suggestions": suggestions, "errors": errors,
                    "mock": getattr(keyword_provider, "name", "") == "mock"})


@app.route("/api/competitor-shop", methods=["POST"])
def api_competitor_shop():
    """경쟁 판매자 샵 주소 등록/삭제 (업체코드 A00012345 또는 쿠팡 주소만)."""
    data = request.get_json(silent=True) or {}
    seller = str(data.get("seller") or "").strip()[:80]
    raw = str(data.get("url") or "").strip()
    if not seller:
        return jsonify({"error": "판매자 이름이 없습니다"}), 400
    if not raw:
        store.set_competitor_shop(seller, None)
        return jsonify({"seller": seller, "shop": None})
    url = competitor_shop.shop_url(raw)
    if not url:
        return jsonify({"error": "쿠팡 업체코드(예: A00012345) 또는 쿠팡 주소(shop.coupang.com/…, www.coupang.com/…)만 넣을 수 있습니다"}), 400
    store.set_competitor_shop(seller, url)
    return jsonify({"seller": seller, "shop": url})


@app.route("/api/dashboard")
def api_dashboard():
    """새 화면(/ui) 대시보드가 쓰는 데이터. 기존 dashboard() 뷰와 같은 값을 JSON 으로 준다.

    두 화면이 서로 다른 숫자를 보이면 안 되므로 계산을 한 곳에 둔다.
    """
    items = store.items()
    rows = _price_rows()
    data = _dashboard_data(items, rows)
    return jsonify({
        "kpi": data["kpi"],
        "featured": [
            {
                "vendor_item_id": r["vendor_item_id"], "name": r["name"],
                "on_sale": bool(r["on_sale"]), "auto_stopped": bool(r["auto_stopped"]),
                "sale_price": r["sale_price"], "stock": r["stock"],
                "lowest": r["lowest"], "rank": r["rank"], "total": r["total"],
            }
            for r in data["featured"]
        ],
        "alerts": [
            {"level": a["level"], "kind": a["kind"], "message": a["message"], "at": a["created_at"]}
            for a in store.alerts(15)
        ],
        "prices": [
            {
                "vendor_item_id": r["vendor_item_id"], "name": r["name"], "featured": bool(r["featured"]),
                "sale_price": r["sale_price"], "lowest": r["lowest"], "diff": r["diff"],
                "rank": r["rank"], "total": r["total"],
            }
            for r in rows
        ],
        "soldout_threshold": cfg.get("soldout_threshold"),
        "last_sync": sync.last_sync,
        "sync_error": sync.last_error,
    })


@app.route("/api/inventory")
def api_inventory():
    return jsonify({"last_sync": sync.last_sync, "error": sync.last_error, "items": store.items()})


# ---------------- 새 화면 (React + Astryx) ----------------
# 전환 중에는 /ui 에서만 띄운다. 기존 Jinja 화면은 그대로 두고, 7개 화면을 다 옮긴 뒤
# 루트를 이쪽으로 넘긴다. 번들은 web/ 에서 `npm run build` 로 static/dist 에 만든다.
# 번들은 코드와 함께 배포되므로 BASE(소스 폴더) 기준이다 — DATA_DIR(사용자 데이터)이 아니다.
SPA_DIR = BASE / "static" / "dist"


@app.route("/ui")
@app.route("/ui/<path:_rest>")
def spa(_rest: str = ""):
    """SPA 진입점. 경로는 브라우저 라우터가 처리하므로 어떤 하위 경로든 index.html 을 준다."""
    index = SPA_DIR / "index.html"
    if not index.exists():
        return (
            "<h1>새 화면이 아직 빌드되지 않았습니다</h1>"
            "<p><code>cd web &amp;&amp; npm install &amp;&amp; npm run build</code> 를 실행하세요.</p>"
            '<p><a href="/">기존 화면으로</a></p>',
            503,
        )
    return send_from_directory(SPA_DIR, "index.html")


@app.route("/api/ping")
def api_ping():  # 포터블 실행기가 '이미 실행 중'인지 확인하는 용도
    from version import VERSION
    return jsonify({"app": "wing-manager", "version": VERSION})


@app.route("/api/health")
def api_health():
    """메뉴바 연결 상태. 응답이 온다는 것 자체가 '프로그램 실행 중'이다."""
    from version import VERSION
    probe = health.probe_coupang(force=request.args.get("refresh") == "1")
    port = app.config.get("WING_PORT") or (int(request.host.rsplit(":", 1)[1]) if ":" in request.host else 80)
    return jsonify({
        "running": True, "version": VERSION, "uptime": health.uptime_text(),
        "started": datetime.fromtimestamp(health.STARTED).strftime("%Y-%m-%d %H:%M"),
        "mode": client.mode, "last_sync": sync.last_sync, "sync_error": sync.last_error,
        "coupang": {**health.coupang_state(client.mode, sync.last_sync, sync.last_error,
                                           int(cfg.get("sync_interval_sec", 30)), probe),
                    "host": probe["host"], "ip": probe["ip"], "ms": probe["ms"]},
        "addresses": health.addresses(app.config.get("WING_HOST", "0.0.0.0"), port, request.host),
        "hostname": socket.gethostname(),
        "telegram": notifier.status(force=request.args.get("refresh") == "1"),
    })


@app.route("/api/sync", methods=["POST"])
def api_sync():
    sync.run_once()
    return jsonify({"last_sync": sync.last_sync, "error": sync.last_error})


if __name__ == "__main__":
    sync.start()
    reg_checker.start()
    app.config.update(WING_HOST=cfg.get("host", "0.0.0.0"), WING_PORT=int(cfg.get("port", 26118)))
    app.run(host=app.config["WING_HOST"], port=app.config["WING_PORT"], debug=False)
