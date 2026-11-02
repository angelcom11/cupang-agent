"""로그인 화면 꾸미기 설정 (config.json 의 "login_page").

로그인 화면은 로그인 전에 누구나 보는 화면이라, 값은 모두 검사한 뒤에만 저장한다.
글자는 템플릿에서 자동 이스케이프되고, 색은 #RRGGBB 만, 배경 이미지는 이 프로그램에 올린 파일 이름만 받는다.
"""
from __future__ import annotations

import re

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
UPLOAD_NAME = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|gif|webp)$")
LAYOUTS = {"center": "가운데 카드", "split": "왼쪽 이미지 · 오른쪽 로그인"}
BACKGROUNDS = {"color": "단색", "image": "이미지"}
LIMITS = {"brand": 30, "title": 40, "message": 200, "footer": 120}

DEFAULTS = {
    "brand": "WING 매니저",
    "title": "로그인",
    "message": "",
    "footer": "",
    "accent": "#e8590c",
    "bg_type": "color",
    "bg_color": "#f4f5f7",
    "bg_image": "",
    "layout": "center",
    "show_help": True,
}


def get(cfg: dict) -> dict:
    """저장된 값 + 기본값. 잘못 저장된 값이 있어도 화면이 깨지지 않게 기본값으로 되돌린다."""
    saved = cfg.get("login_page") or {}
    lp = {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}
    for key in ("accent", "bg_color"):
        if not HEX.match(str(lp[key])):
            lp[key] = DEFAULTS[key]
    if lp["layout"] not in LAYOUTS:
        lp["layout"] = DEFAULTS["layout"]
    if lp["bg_type"] not in BACKGROUNDS or (lp["bg_type"] == "image" and not UPLOAD_NAME.match(lp["bg_image"] or "")):
        lp["bg_type"] = "color"
    return lp


def from_form(form, current: dict) -> tuple[dict, list[str]]:
    """설정 화면 입력 → (저장할 값, 오류 목록). 오류가 있으면 아무것도 저장하지 않는다."""
    errors = []
    lp = {}
    for key, limit in LIMITS.items():
        value = (form.get(key) or "").strip()
        if len(value) > limit:
            errors.append(f"{_LABELS[key]}은(는) {limit}자 이하로 입력하세요")
        lp[key] = value
    lp["brand"] = lp["brand"] or DEFAULTS["brand"]
    lp["title"] = lp["title"] or DEFAULTS["title"]
    for key in ("accent", "bg_color"):
        value = (form.get(key) or "").strip()
        if not HEX.match(value):
            errors.append(f"{_LABELS[key]}은(는) #RRGGBB 형식이어야 합니다")
        lp[key] = value.lower()
    lp["layout"] = form.get("layout") if form.get("layout") in LAYOUTS else DEFAULTS["layout"]
    lp["bg_type"] = form.get("bg_type") if form.get("bg_type") in BACKGROUNDS else "color"
    image = (form.get("bg_image") or "").strip().rsplit("/", 1)[-1]  # 업로드 주소 전체가 와도 파일 이름만
    if image and not UPLOAD_NAME.match(image):
        errors.append("배경 이미지는 이 화면에서 올린 이미지만 쓸 수 있습니다")
        image = current.get("bg_image", "")
    lp["bg_image"] = image
    if lp["bg_type"] == "image" and not image:
        errors.append("배경을 이미지로 하려면 이미지를 올리세요")
    if lp["layout"] == "split" and not image:
        errors.append("'왼쪽 이미지' 배치는 이미지를 먼저 올려야 합니다")
    lp["show_help"] = bool(form.get("show_help"))
    return lp, errors


_LABELS = {"brand": "상단 이름", "title": "제목", "message": "안내 문구", "footer": "아래쪽 문구",
           "accent": "강조색", "bg_color": "배경색"}
