"""임시저장 → 일괄등록(CSV) 템플릿. 템플릿과 같은 머리글이라 그대로 'CSV 일괄 등록'에 올릴 수 있다.

CSV 는 한 줄 = 옵션 1개 상품이라, 옵션이 여러 개인 임시저장은 옵션마다 한 줄로 펼친다.
(다시 올리면 옵션마다 별도 상품으로 등록되므로, 옵션 상품은 '선택 등록'으로 등록하는 편이 맞다)
"""
from __future__ import annotations

import csv
import io

import product_form as pf
from services import CSV_COLUMNS, CSV_HEADERS


def _attrs(form: dict, opt: dict) -> str:
    values = {**form.get("fixed_attrs", {}), **{t: v for t, v in opt.get("values", {}).items() if str(v).strip()}}
    return ";".join(f"{k}={v}" for k, v in values.items() if str(v).strip())


def draft_rows(form: dict) -> list[dict]:
    f = pf.normalize_form(form)
    display, name = pf.product_names(f)
    base = {"display_name": display, "name": (f.get("name") or "").strip(), "category_code": f.get("category_code", ""),
            "brand": f.get("brand", ""), "image_url": f.get("image_url", ""),
            "delivery_charge": f.get("delivery_charge", ""), "search_tags": f.get("search_tags", ""),
            "description_html": f.get("description_html", "")}
    opts = f["options"] or [{"values": {}}]
    return [{**base, "item_name": pf.option_label(f, o) if f["options"] else "",
             "original_price": o.get("original_price", ""), "sale_price": o.get("sale_price", ""),
             "stock": o.get("stock", ""), "attrs_text": _attrs(f, o)} for o in opts]


def drafts_csv(drafts: list[dict]) -> tuple[str, int, int]:
    """(CSV 문자열, 상품 수, 줄 수) — 엑셀에서 바로 열리도록 UTF-8 BOM."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([CSV_HEADERS[k] for k in CSV_COLUMNS])
    lines = 0
    for d in drafts:
        for row in draft_rows(d["data"]):
            w.writerow([str(row.get(k, "") or "") for k in CSV_COLUMNS])
            lines += 1
    return "\ufeff" + buf.getvalue(), len(drafts), lines
