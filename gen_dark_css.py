"""static/style.css → static/dark.css (다크 모드 색).

style.css 를 고친 뒤에는 이 스크립트를 다시 실행하세요:  python gen_dark_css.py
  - 색 변수(--bg, --ink …)는 DARK_VARS 로 직접 정한다.
  - 그 밖의 색 선언은 원래 순서대로 다시 적고, #RRGGBB 로 직접 적힌 색만
    다크 색으로 바꾼다(흰 면 → 어두운 면, 진한 글자 → 밝은 글자).
  - 상세설명 편집기처럼 쿠팡 상품 페이지(흰 배경) 모습을 그대로 보여야 하는 곳은 건드리지 않는다.
"""
from __future__ import annotations

import colorsys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC, OUT = ROOT / "static" / "style.css", ROOT / "static" / "dark.css"

DARK_VARS = {
    "--bg": "#0e1013", "--surface": "#16191e", "--surface-2": "#1c2026", "--line": "#2b3038", "--line-soft": "#22262d",
    "--field": "#3b414c", "--ink": "#f1f3f6", "--text": "#d8dce2", "--text-2": "#b3bac5", "--text-3": "#8d96a3",
    "--accent": "#e8590c", "--accent-ink": "#ff9a55", "--accent-soft": "#2b1a0e", "--accent-ring": "#7a3410",
    "--ok": "#4ade80", "--ok-soft": "#0f2419", "--ok-line": "#1e4d31",
    "--warn": "#fbbf24", "--warn-soft": "#2a210d", "--warn-line": "#5a4410",
    "--bad": "#f87171", "--bad-soft": "#2b1313", "--bad-line": "#5a2222",
    "--info": "#7cb4ff", "--info-soft": "#111d30", "--info-line": "#22406a",
}
# (밝기 하한, 다크 모드 값) — 흰 면은 어두운 면으로, 진한 글자는 밝은 글자로
NEUTRALS = [(0.975, "var(--surface)"), (0.94, "var(--surface-2)"), (0.88, "var(--line)"), (0.78, "var(--field)"),
            (0.6, "var(--text-3)"), (0.42, "var(--text-2)"), (0.25, "var(--text)"), (0.0, "var(--ink)")]
SKIP_SELECTOR = re.compile(r"\.editor|textarea\.src|pre\.json|loginart|\.lppreview|\.lpframe")
COLOR_PROPS = re.compile(r"^(background|background-color|color|border(-\w+)*|box-shadow|outline|fill|stroke)$")
HEX = re.compile(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")


def to_dark(hexstr: str) -> str:
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, light, sat = colorsys.rgb_to_hls(r, g, b)
    if sat < 0.3:                                   # 무채색 → 다크 팔레트 변수 (화면 전체 톤을 맞춘다)
        for limit, var in NEUTRALS:
            if light >= limit:
                return var
    if light > 0.85 or light < 0.3:                 # 옅은 색 바탕·진한 색 글자: 밝기를 뒤집는다
        light = 0.07 + (1 - light) * 0.86
        sat = min(sat, 0.45) * (0.6 if light < 0.5 else 1)
    else:                                           # 버튼·상태 색처럼 진한 색은 조금 밝게만
        light = min(light + 0.08, 0.7)
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return "#%02x%02x%02x" % tuple(round(x * 255) for x in (r, g, b))


def _blocks(css: str, ctx: tuple = ()):
    """(문맥(@media 등), 선택자, 선언문) 을 순서대로 낸다. @keyframes 는 건너뛴다."""
    i = 0
    while i < len(css):
        j = css.find("{", i)
        if j < 0:
            return
        head = css[i:j].strip()
        depth, k = 1, j + 1
        while depth and k < len(css):
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        body = css[j + 1:k - 1]
        if head.startswith("@"):
            if not head.startswith("@keyframes"):
                yield from _blocks(body, ctx + (head,))
        elif head:
            yield ctx, head, body
        i = k


def build() -> str:
    """style.css 의 색 선언만 원래 순서대로 다시 적는다 (#색 → 다크 색, var() 는 그대로).
    순서와 선택자 세기(:where 로 0 추가)를 그대로 지켜야 '어느 규칙이 이기는지'가 라이트 모드와 같아진다."""
    css = re.sub(r"/\*.*?\*/", "", SRC.read_text(encoding="utf-8"), flags=re.S)
    out = ["/* 자동 생성 파일 — 직접 고치지 말고 gen_dark_css.py 를 고친 뒤 다시 실행하세요. */",
           ":root[data-theme=dark]{color-scheme:dark;" + ";".join(f"{k}:{v}" for k, v in DARK_VARS.items()) + "}"]
    has_hex = False
    for ctx, selector, body in _blocks(css):
        if selector.startswith(":root"):
            continue
        sels = [x.strip() for x in selector.split(",") if not SKIP_SELECTOR.search(x)]
        decls = []
        for decl in body.split(";"):
            if ":" not in decl:
                continue
            prop, value = (x.strip() for x in decl.split(":", 1))
            if COLOR_PROPS.match(prop) and (HEX.search(value) or "var(--" in value):
                has_hex |= bool(HEX.search(value))
                decls.append(f"{prop}:{HEX.sub(lambda m: to_dark(m.group(0)), value)}")
        if sels and decls:
            rule = ",".join(f":where(:root[data-theme=dark]) {x}" for x in sels) + "{" + ";".join(decls) + "}"
            out.append("".join(f"{c}{{" for c in ctx) + rule + "}" * len(ctx))
    assert has_hex
    out.append(MANUAL)
    return "\n".join(out) + "\n"


# 자동 변환으로 맞지 않는 곳
MANUAL = """/* 수동 보정 */
:root[data-theme=dark] .wysiwyg{background:var(--surface)}
:root[data-theme=dark] .editor,:root[data-theme=dark] textarea.src{background:#fff;color:#111827;color-scheme:light}
:root[data-theme=dark] button.ghost,:root[data-theme=dark] .star,:root[data-theme=dark] .wtabs button,:root[data-theme=dark] .stepper button,
:root[data-theme=dark] .cat-hit,:root[data-theme=dark] .navout button,:root[data-theme=dark] .status .hsum,:root[data-theme=dark] .tb button,
:root[data-theme=dark] button.optchip,:root[data-theme=dark] .substeps button{color:var(--text)}
:root[data-theme=dark] button.danger-btn,:root[data-theme=dark] .loginbox button,:root[data-theme=dark] .stepper button.on b{color:#fff}
:root[data-theme=dark] :where(button):hover{background:#d8dce2}
:root[data-theme=dark] button.ghost:hover,:root[data-theme=dark] .navout button:hover{background:var(--surface-2)}
:root[data-theme=dark] button.danger-btn:hover{background:#dc2626}
:root[data-theme=dark] a.ghostlink,:root[data-theme=dark] label.ghostlink{color:var(--ink)!important}
:root[data-theme=dark] .star.on{color:#f59e0b}
:root[data-theme=dark] .modal{background:var(--surface);color:var(--text)}
:root[data-theme=dark] img{opacity:.92}
"""

if __name__ == "__main__":
    OUT.write_text(build(), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)} 를 만들었습니다 ({OUT.stat().st_size:,} bytes)")
