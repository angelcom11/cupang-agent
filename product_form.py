"""상품 등록 폼 ↔ 쿠팡 상품 생성 API(POST seller-products).

필드명·허용값은 쿠팡 개발자 문서 '상품 생성', '카테고리 메타정보 조회'를 따른다.
폼은 화면·임시저장·CSV가 함께 쓰는 dict 이며, 옵션·고시정보 같은 구조는 list/dict 로 들어 있다.
"""
from __future__ import annotations

import json
import re
from html import escape

import rocket_growth as rg
from datetime import datetime

# ---------------- 선택지 (쿠팡 문서의 값) ----------------
DELIVERY_METHODS = {"SEQUENCIAL": "일반배송(순차배송)", "COLD_FRESH": "신선냉동", "MAKE_ORDER": "주문제작",
                    "AGENT_BUY": "구매대행", "VENDOR_DIRECT": "설치배송 또는 판매자 직접 전달"}
CHARGE_TYPES = {"FREE": "무료배송", "NOT_FREE": "유료배송", "CONDITIONAL_FREE": "조건부 무료배송",
                "CHARGE_RECEIVED": "착불배송"}
# 택배사 코드: 쿠팡 '택배사 코드' 문서 중 국내 주요 택배사
COURIERS = {"CJGLS": "CJ대한통운", "HANJIN": "한진택배", "HYUNDAI": "롯데택배", "KGB": "로젠택배", "EPOST": "우체국",
            "KDEXP": "경동택배", "ILYANG": "일양택배", "CHUNIL": "천일특송", "DAESIN": "대신택배", "HDEXP": "합동택배",
            "KUNYOUNG": "건영택배", "CVS": "CVS택배", "SLX": "SLX택배", "DIRECT": "업체직송"}
OFFER_CONDITIONS = {"NEW": "새 상품", "REFURBISHED": "리퍼", "USED_BEST": "중고(최상)", "USED_GOOD": "중고(상)",
                    "USED_NORMAL": "중고(중)"}
NO_RETURN_CENTER = "NO_RETURN_CENTERCODE"  # 반품지 미등록 시 주소를 직접 넣는 쿠팡 지정 값

FORM_DEFAULTS = {
    "adult_only": "EVERYONE", "tax_type": "TAX", "parallel_imported": "", "overseas_purchased": "",
    "offer_condition": "NEW", "certification_type": "", "certification_code": "",
    "sale_start": "", "sale_end": "2099-01-01T23:59", "max_per_person": "0", "max_per_person_period": "1",
    "outbound_days": "2", "unit_count": "1", "vendor_user_id": "",
    "delivery_method": "SEQUENCIAL", "delivery_company": "CJGLS", "delivery_charge_type": "FREE",
    "delivery_charge": "0", "free_ship_over": "0", "remote_area": "N", "union_delivery": "Y",
    "outbound_place_code": "", "extra_info_message": "", "detail_mode": "editor",
    "return_center_code": "", "return_name": "", "return_phone": "", "return_zip": "", "return_addr": "",
    "return_addr_detail": "", "delivery_charge_on_return": "2500", "return_charge": "2500",
    **rg.FORM_DEFAULTS,
}
# '이 배송·반품 설정을 기본값으로 저장'에서 기억하는 항목
REMEMBER_KEYS = [k for k in FORM_DEFAULTS if k not in ("certification_type", "certification_code", "sale_start",
                                                       "extra_info_message", "offer_condition", "detail_mode")
                 and (not k.startswith(("rg_", "sell_")) or k in rg.REMEMBER_KEYS)]
# 예전 config.json product_defaults(API 이름) → 폼 이름
LEGACY_DEFAULT_KEYS = {"deliveryCompanyCode": "delivery_company", "outboundShippingPlaceCode": "outbound_place_code",
                       "returnCenterCode": "return_center_code", "returnChargeName": "return_name",
                       "companyContactNumber": "return_phone", "returnZipCode": "return_zip",
                       "returnAddress": "return_addr", "returnAddressDetail": "return_addr_detail",
                       "vendorUserId": "vendor_user_id"}
JSON_KEYS = {"options": list, "option_types": list, "fixed_attrs": dict, "filter_attrs": dict, "notices": dict,
             "docs": dict, "detail_images": list, "content_images": list}
MAX_OPTIONS = 200
# 단건등록 작성 단계 — 쿠팡 WING 상품등록 화면 순서 (판매자 가이드 Step 1~14)
STEPS = [("s-name", "노출상품명"), ("s-cat", "카테고리"), ("s-option", "옵션"), ("s-image", "상품이미지"),
         ("s-detail", "상세설명"), ("s-main", "주요정보"), ("s-keyword", "검색어"), ("s-filter", "검색필터"),
         ("s-notice", "제공고시"), ("s-ship", "배송"), ("s-return", "반품/교환"), ("s-rg", "로켓그로스"), ("s-docs", "구비서류"),
         ("s-confirm", "판매요청")]
STEP_IDS = [k for k, _ in STEPS]
# 상품 주요정보 안의 작은 단계 (WING 항목 순서)
MAIN_SUBS = ["브랜드·제조사", "인증정보", "판매 조건", "구매수량·판매기간"]
# 오류 문구 → 고칠 단계/작은 단계 (위에서부터 처음 맞는 규칙, 없으면 옵션)
_ERROR_STEPS = [("로켓그로스", "s-rg", 0), ("판매방식", "s-name", 0), ("카테고리 정보", "s-cat", 0), ("반품", "s-return", 0), ("제공고시", "s-notice", 0),
                ("구비서류", "s-docs", 0), ("인증", "s-main", 1), ("상품 상태", "s-main", 2),
                ("' 상품을 등록할 수 없습니다", "s-main", 2), ("판매 종료", "s-main", 3), ("판매 기간", "s-main", 3),
                ("구매수량", "s-main", 3), ("이미지", "s-image", 0), ("출고", "s-ship", 0), ("배송", "s-ship", 0),
                ("택배사", "s-ship", 0), ("WING 로그인", "s-confirm", 0), ("노출상품명", "s-name", 0),
                ("카테고리", "s-cat", 0), ("category_code", "s-cat", 0), ("마지막 단계", "s-cat", 0)]


def sub_of_error(msg: str) -> int:
    return next((sub for key, _, sub in _ERROR_STEPS if key in msg), 0)


def step_of_error(msg: str) -> str:
    return next((step for key, step, _ in _ERROR_STEPS if key in msg), "s-option")
MAX_DETAIL_IMAGES = 9


def _int(v, default: int = 0) -> int:
    s = str(v if v is not None else "").replace(",", "").strip()
    return int(s) if s.lstrip("-").isdigit() else default


def _digits(v) -> bool:
    return str(v if v is not None else "").replace(",", "").strip().isdigit()


def product_names(form: dict) -> tuple[str, str]:
    """(노출상품명, 등록상품명). 등록상품명(판매자 관리용)을 비우면 노출상품명을 그대로 쓴다."""
    display = (form.get("display_name") or form.get("name") or "").strip()
    return display, (form.get("name") or "").strip() or display


def defaults_from_config(cfg: dict) -> dict:
    """FORM_DEFAULTS ← 예전 product_defaults ← 저장한 등록 기본값 순으로 덮어쓴다."""
    out = dict(FORM_DEFAULTS)
    for api_key, key in LEGACY_DEFAULT_KEYS.items():
        if (cfg.get("product_defaults") or {}).get(api_key):
            out[key] = cfg["product_defaults"][api_key]
    out.update({k: v for k, v in (cfg.get("register_defaults") or {}).items() if k in FORM_DEFAULTS})
    return out


def normalize_form(form: dict, defaults: dict | None = None) -> dict:
    """빈 값은 기본값으로, JSON 문자열은 list/dict 로, 예전(옵션 1개짜리) 폼은 옵션 목록으로 바꾼다."""
    f = {**(defaults or FORM_DEFAULTS)}
    f.update({k: v for k, v in form.items() if v is not None})  # 보낸 값(빈칸 포함)이 기본값보다 우선
    for key, typ in JSON_KEYS.items():
        v = f.get(key)
        if isinstance(v, str):
            try:
                v = json.loads(v) if v.strip() else typ()
            except ValueError:
                v = typ()
        f[key] = v if isinstance(v, typ) else typ()
    if not f["options"] and any(f.get(k) for k in ("sale_price", "original_price", "stock", "item_name")):
        f["options"] = [{"values": {}, "name": f.get("item_name", ""), "original_price": f.get("original_price", ""),
                         "sale_price": f.get("sale_price", ""), "stock": f.get("stock", ""), "sku": "", "barcode": ""}]
    if "delivery_charge_type" not in form and _int(form.get("delivery_charge")) > 0:
        f["delivery_charge_type"] = "NOT_FREE"  # 예전 폼: 배송비만 있던 경우
    if f.get("attrs_text"):  # CSV '구매옵션' 칸: 색상=블랙;수량=1개 → 모든 옵션 공통 값
        for part in re.split(r"[;\n]", f.pop("attrs_text")):
            name, _, value = part.partition("=")
            if name.strip() and value.strip():
                f["fixed_attrs"][name.strip()] = value.strip()
    # WING 상세설명 '이미지 업로드': 올린 이미지를 순서대로 상세설명으로 쓴다
    if f.get("detail_mode") == "images" and f["content_images"]:
        f["description_html"] = "".join(f'<div style="text-align:center"><img src="{escape(u)}" alt=""></div>'
                                        for u in f["content_images"] if u)
    if rg.rocket_on(f) and f.get("rg_inbound") == "now" and not str(f.get("rg_inbound_name") or "").strip():
        f["rg_inbound_name"] = product_names(f)[0]  # 물류 입고용 상품명을 비우면 노출상품명
    # WING: 해외구매대행은 배송방법 '구매대행'으로 정한다 (별도 체크 없음)
    f["overseas_purchased"] = "1" if rg.seller_on(f) and f.get("delivery_method") == "AGENT_BUY" else ""
    f["option_types"] = [t.strip() for t in f["option_types"] if str(t).strip()][:3]
    for o in f["options"]:
        o.setdefault("values", {})
    return f


def option_label(form: dict, opt: dict) -> str:
    vals = [str(opt["values"].get(t, "")).strip() for t in form["option_types"]]
    return " ".join(v for v in vals if v) or str(opt.get("name") or "").strip()


def autofill_notices(f: dict, meta: dict | None) -> dict:
    """CSV처럼 고시정보를 따로 받지 않는 경로: '기타 재화'(없으면 첫 종류)를 고르고 빈칸은 '상세페이지 참조'."""
    cats = (meta or {}).get("noticeCategories") or []
    if not cats:
        return f
    names = [c["noticeCategoryName"] for c in cats]
    if f.get("notice_category") not in names:
        f["notice_category"] = "기타 재화" if "기타 재화" in names else names[0]
    cat = cats[names.index(f["notice_category"])]
    for d in cat["noticeCategoryDetailNames"]:
        f["notices"].setdefault(d["noticeCategoryDetailName"], "상세페이지 참조")
    return f


# ---------------- 검증 ----------------
def _check_value(attr: dict, value: str) -> str | None:
    """NUMBER 형식 구매옵션은 '숫자+사용 가능 단위'여야 쿠팡이 받는다 (예: 500ml)."""
    if attr.get("dataType") != "NUMBER":
        return None
    units = [u for u in (attr.get("usableUnits") or []) if u] or (
        [attr["basicUnit"]] if attr.get("basicUnit") not in (None, "", "없음") else [])
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(\S*)\s*", value)
    if not m:
        return f"'{attr['attributeTypeName']}' 값 '{value}'는 숫자로 시작해야 합니다 (예: 1{units[0] if units else ''})"
    if units and m.group(2) not in units:
        return f"'{attr['attributeTypeName']}' 값 '{value}'의 단위가 올바르지 않습니다 (사용 가능: {', '.join(units[:12])})"
    return None


def _validate_options(f: dict, meta: dict | None, errors: list):
    opts = f["options"]
    if not opts:
        errors.append("옵션(판매가)을 하나 이상 입력하세요")
        return
    if len(opts) > MAX_OPTIONS:
        errors.append(f"옵션은 최대 {MAX_OPTIONS}개까지 등록할 수 있습니다")
    if len(opts) > 1 and not f["option_types"]:
        errors.append("옵션이 2개 이상이면 옵션 종류(예: 색상, 사이즈)를 정해야 합니다")
    attrs = {a["attributeTypeName"]: a for a in (meta or {}).get("attributes", [])}
    seen = set()
    for i, o in enumerate(opts, 1):
        label = option_label(f, o) or f"{i}번째 옵션"
        for t in f["option_types"]:
            v = str(o["values"].get(t, "")).strip()
            if not v:
                errors.append(f"{label}: '{t}' 값을 입력하세요")
            elif t in attrs and (problem := _check_value(attrs[t], v)):
                errors.append(f"{label}: {problem}")
        if not _digits(o.get("sale_price")) or _int(o.get("sale_price")) <= 0:
            errors.append(f"{label}: 판매가를 숫자로 입력하세요")
        elif _int(o["sale_price"]) % 10:
            errors.append(f"{label}: 판매가는 10원 단위로 입력하세요")
        if str(o.get("original_price") or "").strip():
            if not _digits(o["original_price"]):
                errors.append(f"{label}: 정상가는 숫자여야 합니다")
            elif _digits(o.get("sale_price")) and _int(o["original_price"]) < _int(o["sale_price"]):
                errors.append(f"{label}: 정상가(할인율 기준가)는 판매가보다 작을 수 없습니다")
        if str(o.get("stock") or "").strip() and (not _digits(o["stock"]) or _int(o["stock"]) > 99999):
            errors.append(f"{label}: 재고는 0~99999 사이 숫자여야 합니다")
        key = tuple(str(o["values"].get(t, "")).strip() for t in f["option_types"]) or (label,)
        if key in seen:
            errors.append(f"옵션 '{label}'이(가) 중복됩니다")
        seen.add(key)


def _validate_meta(f: dict, meta: dict, errors: list):
    attrs = meta.get("attributes") or []
    provided = set(f["option_types"]) | {k for k, v in {**f["fixed_attrs"], **f["filter_attrs"]}.items()
                                         if str(v).strip()}
    by_group: dict[str, list] = {}
    for a in attrs:
        if a.get("required") != "MANDATORY":
            continue
        g = a.get("groupNumber") or "NONE"
        if g == "NONE":
            if a["attributeTypeName"] not in provided:
                errors.append(f"필수 구매옵션 '{a['attributeTypeName']}'을(를) 옵션 종류로 쓰거나 고정값을 입력하세요")
        else:
            by_group.setdefault(g, []).append(a["attributeTypeName"])
    for names in by_group.values():
        if not provided & set(names):
            errors.append(f"필수 구매옵션 {' / '.join(names)} 중 하나를 입력하세요")
    by_name = {a["attributeTypeName"]: a for a in attrs}
    for name, v in f["fixed_attrs"].items():
        if str(v).strip() and name in by_name and (problem := _check_value(by_name[name], str(v))):
            errors.append(problem)

    # 고시정보 빈칸은 요청 본문에서 '상세페이지 참조'로 채운다 (WING도 허용하는 값)
    if len(meta.get("noticeCategories") or []) > 1 and not _notice_category(f, meta):
        errors.append("상품정보 제공고시 종류를 선택하세요")

    for doc in meta.get("requiredDocumentNames") or []:
        need = {"MANDATORY": True, "MANDATORY_PARALLEL_IMPORTED": bool(f.get("parallel_imported")),
                "MANDATORY_OVERSEAS_PURCHASED": bool(f.get("overseas_purchased"))}.get(doc.get("required"), False)
        if need and not str(f["docs"].get(doc["templateName"], "")).strip():
            errors.append(f"구비서류 '{doc['templateName']}'을(를) 올려 주세요")

    certs = {c["certificationType"]: c for c in meta.get("certifications") or []}
    chosen = certs.get(f.get("certification_type"))
    if any(c.get("required") == "MANDATORY" for c in certs.values()) and not chosen:
        errors.append("인증정보를 선택하세요")
    if chosen and chosen.get("dataType") == "CODE" and not str(f.get("certification_code") or "").strip():
        errors.append(f"'{chosen['name']}' 인증번호를 입력하세요")
    allowed = meta.get("allowedOfferConditions") or ["NEW"]
    if f.get("offer_condition", "NEW") not in allowed:
        errors.append(f"이 카테고리는 '{OFFER_CONDITIONS.get(f['offer_condition'], f['offer_condition'])}' 상품을 등록할 수 없습니다")


def _validate_shipping(f: dict, errors: list):
    ct = f.get("delivery_charge_type")
    if ct not in CHARGE_TYPES:
        errors.append("배송비 종류를 선택하세요")
    if ct in ("NOT_FREE", "CONDITIONAL_FREE", "CHARGE_RECEIVED") and _int(f.get("delivery_charge")) <= 0:
        errors.append("유료·조건부 무료·착불 배송은 기본 배송비를 입력하세요")
    if ct == "CONDITIONAL_FREE" and (_int(f.get("free_ship_over")) < 100 or _int(f.get("free_ship_over")) % 100):
        errors.append("조건부 무료배송 기준 금액은 100원 단위로 입력하세요")
    if f.get("delivery_method") not in DELIVERY_METHODS:
        errors.append("배송 방법을 선택하세요")
    if not str(f.get("delivery_company") or "").strip():
        errors.append("택배사를 선택하세요")
    if not str(f.get("outbound_place_code") or "").strip():
        errors.append("출고지를 선택하세요 (WING에 출고지가 없으면 먼저 등록해야 합니다)")
    if not str(f.get("return_center_code") or "").strip():
        errors.append("반품/교환지를 선택하세요")
    elif f["return_center_code"] == NO_RETURN_CENTER:
        for key, label in (("return_name", "반품지 이름"), ("return_phone", "반품지 연락처"), ("return_zip", "우편번호"),
                           ("return_addr", "주소"), ("return_addr_detail", "상세주소")):
            if not str(f.get(key) or "").strip():
                errors.append(f"반품/교환지 {label}을(를) 입력하세요")
    for key, label in (("delivery_charge_on_return", "초도반품배송비"), ("return_charge", "반품배송비")):
        if not _digits(f.get(key)):
            errors.append(f"{label}는 숫자로 입력하세요")
    if not str(f.get("vendor_user_id") or "").strip():
        errors.append("WING 로그인 아이디(실사용자 아이디)를 입력하세요")


def _validate_sale(f: dict, errors: list):
    try:
        start = datetime.fromisoformat(f["sale_start"]) if f.get("sale_start") else datetime.now()
        end = datetime.fromisoformat(f.get("sale_end") or "2099-01-01T23:59")
        if end <= start:
            errors.append("판매 종료일은 시작일보다 뒤여야 합니다")
    except ValueError:
        errors.append("판매 기간 형식이 올바르지 않습니다")
    for key, label, lo in (("max_per_person", "인당 최대 구매수량", 0), ("max_per_person_period", "최대 구매수량 기간(일)", 1),
                           ("outbound_days", "출고 소요일", 1), ("unit_count", "단위 수량", 1)):
        if not _digits(f.get(key)) or _int(f[key]) < lo:
            errors.append(f"{label}은(는) {lo} 이상의 숫자여야 합니다")


def validate_form(form: dict, categories=None, meta: dict | None = None, full: bool = True) -> list[str]:
    """full=False 는 예전 동작(이름·카테고리·가격만) — 테스트·간이 확인용."""
    f = normalize_form(form) if "options" not in form or isinstance(form.get("options"), str) else form
    errors = []
    if not product_names(f)[0]:
        errors.append("노출상품명은(는) 필수입니다")
    code = str(f.get("category_code") or "").strip()
    if not code:
        errors.append("카테고리은(는) 필수입니다")
    elif not code.isdigit():
        errors.append("category_code 는 숫자여야 합니다")
    elif categories is not None and (problem := categories.check(code)):
        errors.append(problem)
    _validate_options(f, meta, errors)
    if full:
        if meta:
            _validate_meta(f, meta, errors)
        _validate_sale(f, errors)
        if rg.seller_on(f):  # 로켓그로스만이면 배송·반품은 쿠팡이 맡는다
            _validate_shipping(f, errors)
        elif not str(f.get("vendor_user_id") or "").strip():
            errors.append("WING 로그인 아이디(실사용자 아이디)를 입력하세요")
        rg.validate(f, meta, option_label, errors)
        if len(f["detail_images"]) > MAX_DETAIL_IMAGES:
            errors.append(f"추가 이미지는 최대 {MAX_DETAIL_IMAGES}개입니다")
        if not str(f.get("image_url") or "").strip():
            errors.append("대표 이미지를 올리거나 주소를 입력하세요")
    return list(dict.fromkeys(errors))


# ---------------- 요청 본문 ----------------
def _dt(value: str, fallback: datetime) -> str:
    try:
        d = datetime.fromisoformat(value) if value else fallback
    except ValueError:
        d = fallback
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def _attributes(f: dict, opt: dict, meta: dict | None) -> list[dict]:
    exposed = {a["attributeTypeName"]: a.get("exposed") for a in (meta or {}).get("attributes", [])}
    out = [{"attributeTypeName": t, "attributeValueName": str(opt["values"].get(t, "")).strip()}
           for t in f["option_types"]]
    for name, v in f["fixed_attrs"].items():  # 모든 옵션에 같은 값인 구매옵션 (예: 수량 1개)
        if str(v).strip() and name not in f["option_types"]:
            out.append({"attributeTypeName": name, "attributeValueName": str(v).strip()})
    for name, v in f["filter_attrs"].items():  # 검색필터
        if str(v).strip() and name not in f["option_types"]:
            a = {"attributeTypeName": name, "attributeValueName": str(v).strip()}
            if exposed.get(name, "NONE") == "NONE":
                a["exposed"] = "NONE"
            out.append(a)
    return out


def _notice_category(f: dict, meta: dict | None) -> dict | None:
    """고른 고시 종류. 이 카테고리에 종류가 하나뿐이면 그것."""
    cats = (meta or {}).get("noticeCategories") or []
    chosen = next((c for c in cats if c["noticeCategoryName"] == f.get("notice_category")), None)
    return chosen or (cats[0] if len(cats) == 1 else None)


def _notices(f: dict, meta: dict | None) -> list[dict]:
    cat = _notice_category(f, meta)
    if cat:
        return [{"noticeCategoryName": cat["noticeCategoryName"], "noticeCategoryDetailName": d["noticeCategoryDetailName"],
                 "content": str(f["notices"].get(d["noticeCategoryDetailName"], "")).strip() or "상세페이지 참조"}
                for d in cat["noticeCategoryDetailNames"]]
    if f.get("notice_category") and f["notices"]:
        return [{"noticeCategoryName": f["notice_category"], "noticeCategoryDetailName": k, "content": v or "상세페이지 참조"}
                for k, v in f["notices"].items()]
    return [{"noticeCategoryName": "기타 재화", "noticeCategoryDetailName": n, "content": "상세페이지 참조"}
            for n in ("품명 및 모델명", "인증사항", "제조국(원산지)", "제조자(수입자)", "소비자상담 관련 전화번호")]


def build_product_payload(form: dict, vendor_id: str, request_approval: bool = False, meta: dict | None = None) -> dict:
    f = normalize_form(form) if "options" not in form or isinstance(form.get("options"), str) else form
    display, seller_name = product_names(f)
    tags = [t.strip() for t in (f.get("search_tags") or "").split(",") if t.strip()][:20]
    images = [{"imageOrder": 0, "imageType": "REPRESENTATION", "vendorPath": f.get("image_url") or ""}]
    images += [{"imageOrder": i, "imageType": "DETAIL", "vendorPath": u}
               for i, u in enumerate([u for u in f["detail_images"] if u][:MAX_DETAIL_IMAGES], 1)]
    notices = _notices(f, meta)
    cert = {"certificationType": f.get("certification_type") or "NOT_REQUIRED",
            "certificationCode": str(f.get("certification_code") or "").strip()}
    overseas = bool(f.get("overseas_purchased"))
    ct = f.get("delivery_charge_type", "FREE")
    manual_return = f.get("return_center_code") == NO_RETURN_CENTER
    items = []
    for i, o in enumerate(f["options"]):
        sale = _int(o.get("sale_price"))
        barcode = str(o.get("barcode") or "").strip()
        item = {
            "itemName": (option_label(f, o) or ("단일상품" if len(f["options"]) == 1 else f"옵션{i + 1}"))[:150],
            "originalPrice": _int(o.get("original_price"), sale) or sale,
            "salePrice": sale,
            "maximumBuyCount": _int(o.get("stock")),
            "maximumBuyForPerson": _int(f.get("max_per_person")),
            "maximumBuyForPersonPeriod": max(1, _int(f.get("max_per_person_period"), 1)),
            "outboundShippingTimeDay": max(1, _int(f.get("outbound_days"), 2)),
            "unitCount": max(1, _int(f.get("unit_count"), 1)),
            "adultOnly": "ADULT_ONLY" if f.get("adult_only") == "ADULT_ONLY" else "EVERYONE",
            "taxType": "FREE" if f.get("tax_type") == "FREE" else "TAX",
            "parallelImported": "PARALLEL_IMPORTED" if f.get("parallel_imported") else "NOT_PARALLEL_IMPORTED",
            "overseasPurchased": "OVERSEAS_PURCHASED" if overseas else "NOT_OVERSEAS_PURCHASED",
            "pccNeeded": overseas,  # 해외구매대행은 개인통관부호 필수
            "externalVendorSku": str(o.get("sku") or "").strip(),
            "barcode": barcode,
            "emptyBarcode": not barcode,
            "emptyBarcodeReason": "" if barcode else "상품확인불가_바코드없음사유",
            "modelNo": str(o.get("model_no") or f.get("model_no") or "").strip(),
            "certifications": [cert],
            "searchTags": tags,
            "images": images,
            "notices": notices,
            "attributes": _attributes(f, o, meta),
            "contents": [{"contentsType": "TEXT", "contentDetails": [
                {"content": f.get("description_html") or f"<p>{display}</p>", "detailType": "TEXT"}]}],
            "offerCondition": f.get("offer_condition") or "NEW",
        }
        if item["offerCondition"].startswith("USED"):
            item["offerDescription"] = str(f.get("offer_description") or "")[:700]
        items.append(item)
    payload = {
        "displayCategoryCode": _int(f.get("category_code")),
        "sellerProductName": seller_name[:100],
        "vendorId": vendor_id,
        "saleStartedAt": _dt(f.get("sale_start", ""), datetime.now()),
        "saleEndedAt": _dt(f.get("sale_end", ""), datetime(2099, 1, 1, 23, 59, 59)),
        "displayProductName": display[:100],
        "brand": (f.get("brand") or "").strip() or "GENERIC",  # 문서: 브랜드가 없는 상품은 GENERIC
        "generalProductName": display[:100],
        "manufacture": (f.get("manufacture") or f.get("brand") or "").strip(),
        "deliveryMethod": f.get("delivery_method") or "SEQUENCIAL",
        "deliveryCompanyCode": f.get("delivery_company") or "CJGLS",
        "deliveryChargeType": ct,
        "deliveryCharge": 0 if ct == "FREE" else _int(f.get("delivery_charge")),
        "freeShipOverAmount": _int(f.get("free_ship_over")) if ct == "CONDITIONAL_FREE" else 0,
        "deliveryChargeOnReturn": _int(f.get("delivery_charge_on_return")),
        "remoteAreaDeliverable": "Y" if f.get("remote_area") == "Y" else "N",
        "unionDeliveryType": "UNION_DELIVERY" if f.get("union_delivery", "Y") == "Y" else "NOT_UNION_DELIVERY",
        "returnCenterCode": f.get("return_center_code") or "",
        "returnChargeName": f.get("return_name") or "",
        "companyContactNumber": f.get("return_phone") or "",
        "returnZipCode": f.get("return_zip") or "",
        "returnAddress": f.get("return_addr") or "",
        "returnAddressDetail": f.get("return_addr_detail") or "",
        "returnCharge": _int(f.get("return_charge")),
        "outboundShippingPlaceCode": f.get("outbound_place_code") or "",
        "vendorUserId": f.get("vendor_user_id") or "",
        "requested": request_approval,  # False = 임시저장, True = 바로 승인요청
        "items": items,
        "requiredDocuments": [{"templateName": k, "vendorDocumentPath": v} for k, v in f["docs"].items() if v],
    }
    if payload["deliveryMethod"] == "MAKE_ORDER" and f.get("extra_info_message"):
        payload["extraInfoMessage"] = f["extra_info_message"]
    if manual_return:
        payload["returnCenterCode"] = NO_RETURN_CENTER
    return rg.to_hybrid(payload, f) if rg.rocket_on(f) else payload
