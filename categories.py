"""쿠팡 노출 카테고리 목록: 불러오기(쿠팡 API / WING 엑셀) · 저장 · 조회.

전체 목록은 WING 로그인 또는 Open API 키가 있어야 받을 수 있다. 키가 없을 때 쓰는 기본 목록은
쿠팡 개발자 문서(카테고리 조회/목록조회 응답 예시)에 공개된 항목만 담았다.
"""
from __future__ import annotations

import csv
import io
import json
import threading
from datetime import datetime
from pathlib import Path

# (코드, 부모코드, 이름) — 출처: developers.coupang.com '카테고리 조회', '카테고리 목록조회' 응답 예시
_DOC_SAMPLE = [
    (77834, 0, "가구/홈데코"), (62588, 0, "가전/디지털"), (66679, 0, "도서"), (79648, 0, "문구/오피스"),
    (65799, 0, "반려/애완용품"), (56112, 0, "뷰티"), (63897, 0, "생활용품"), (103371, 0, "스포츠/레져"),
    (59258, 0, "식품"), (102984, 0, "완구/취미"), (79138, 0, "음반/DVD"), (78647, 0, "자동차용품"),
    (80285, 0, "주방용품"), (76844, 0, "출산/유아동"), (69182, 0, "패션의류잡화"),
    (69183, 69182, "여성패션"), (69184, 69183, "여성의류"), (79268, 69184, "티셔츠"),
    (79383, 79268, "민소매/나시"), (79382, 79268, "반소매"), (79381, 79268, "긴소매"),
    (69186, 69184, "맨투맨"), (79269, 69184, "후드티"), (69187, 69184, "블라우스"), (69188, 69184, "셔츠(남방)"),
]

_CODE_HEADER_HINTS = ("코드", "code")
_PATH_HEADER_HINTS = ("분류", "depth", "카테고리명", "카테고리 명", "단계", "레벨", "level", "경로", "path", "카테고리")


class CategoryError(ValueError):
    pass


class CategoryStore:
    """노드: {"c": 코드(str), "p": 부모코드(str, 최상위는 "0"), "n": 이름}. 하위가 없는 노드만 상품 등록 가능."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            data = {"source": "sample", "updated_at": "", "nodes": [
                {"c": str(c), "p": str(p), "n": n} for c, p, n in _DOC_SAMPLE]}
        self._set(data)

    def _set(self, data: dict):
        self.data = data
        parents = {n["p"] for n in data["nodes"]}
        self.by_code = {n["c"]: n for n in data["nodes"]}
        self.leaves = {c for c in self.by_code if c not in parents}

    def replace(self, nodes: list[dict], source: str):
        if not nodes:
            raise CategoryError("카테고리를 하나도 찾지 못했습니다")
        data = {"source": source, "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "nodes": nodes}
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
            self._set(data)

    # ---------- 조회 ----------
    @property
    def is_full(self) -> bool:
        return self.data["source"] != "sample"

    def summary(self) -> dict:
        return {"source": self.data["source"], "updated_at": self.data["updated_at"],
                "count": len(self.by_code), "leaves": len(self.leaves), "full": self.is_full}

    def path_of(self, code) -> str:
        names, node, seen = [], self.by_code.get(str(code)), set()
        while node and node["c"] not in seen:
            seen.add(node["c"])
            names.append(node["n"])
            node = self.by_code.get(node["p"])
        return " > ".join(reversed(names))

    def check(self, code) -> str | None:
        """등록 불가 사유. 기본(샘플) 목록일 때는 목록에 없는 코드도 허용한다."""
        code = str(code or "").strip()
        if code in self.by_code and code not in self.leaves:
            return f"'{self.path_of(code)}'는 하위 분류가 있습니다. 가장 마지막 단계의 카테고리를 선택하세요"
        if self.is_full and code not in self.by_code:
            return f"카테고리 코드 {code} 는 쿠팡 카테고리 목록에 없습니다"
        return None


# ---------- 불러오기: 쿠팡 Open API ----------
def nodes_from_api_tree(root: dict) -> list[dict]:
    """GET /meta/display-categories 응답의 data(ROOT 트리) → 노드 목록 (사용 안 함 카테고리는 제외)."""
    out, stack = [], [(root, "0")]
    while stack:
        node, parent = stack.pop()
        for ch in node.get("child") or []:
            code = ch.get("displayItemCategoryCode", ch.get("displayCategoryCode"))
            if code is None or ch.get("status", "ACTIVE") == "DISABLED":
                continue
            out.append({"c": str(code), "p": parent, "n": str(ch.get("name", "")).strip()})
            stack.append((ch, str(code)))
    return out


# ---------- 불러오기: WING '전체 카테고리 정보' 엑셀 / CSV ----------
def _rows_from_file(filename: str, data: bytes) -> list[list]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            return [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        except Exception as exc:  # 손상·암호화 파일 등 openpyxl 오류 종류가 많아 한 메시지로 안내
            raise CategoryError(f"엑셀 파일을 읽을 수 없습니다 ({type(exc).__name__})") from exc
    if filename.lower().endswith(".csv"):
        for enc in ("utf-8-sig", "cp949"):
            try:
                return list(csv.reader(io.StringIO(data.decode(enc))))
            except UnicodeDecodeError:
                continue
    raise CategoryError("엑셀(.xlsx) 또는 CSV 파일만 올릴 수 있습니다")


def _as_code(v) -> str | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s if s.isdigit() and 4 <= len(s) <= 7 else None


def _find_header(rows: list[list]):
    for i, row in enumerate(rows[:15]):
        cells = [str(c or "").strip() for c in row]
        code_cols = [j for j, c in enumerate(cells) if any(h in c.lower() for h in _CODE_HEADER_HINTS)]
        if not code_cols:
            continue
        code_col = next((j for j in code_cols if "카테고리" in cells[j] or "노출" in cells[j]), code_cols[0])
        path_cols = [j for j, c in enumerate(cells)
                     if j != code_col and c and any(h in c.lower() for h in _PATH_HEADER_HINTS)
                     and not any(h in c.lower() for h in _CODE_HEADER_HINTS)]
        if path_cols:
            return i, code_col, path_cols
    return None


def nodes_from_file(filename: str, data: bytes) -> list[dict]:
    """머리글에서 '코드' 열과 분류/경로 열을 찾아 트리로 만든다. 'A>B>C' 한 칸 경로도 지원."""
    rows = _rows_from_file(filename, data)
    header = _find_header(rows)
    if not header:
        raise CategoryError("머리글에서 카테고리 코드 열과 분류(경로) 열을 찾지 못했습니다")
    start, code_col, path_cols = header
    path_code: dict[tuple, str] = {}
    for row in rows[start + 1:]:
        row = list(row) + [None] * (max(path_cols + [code_col]) + 1 - len(row))
        code = _as_code(row[code_col])
        parts: list[str] = []
        for j in path_cols:
            v = str(row[j] or "").strip()
            parts.extend(p.strip() for p in v.split(">") if p.strip())
        if code and parts:
            path_code[tuple(parts)] = code
    if not path_code:
        raise CategoryError("카테고리 행을 찾지 못했습니다")
    nodes, made = [], {}
    for path in sorted(path_code, key=len):
        for depth in range(1, len(path) + 1):
            sub = path[:depth]
            if sub in made:
                continue
            code = path_code.get(sub) or "g:" + ">".join(sub)  # 코드가 없는 중간 분류는 선택용 임시 키
            parent = made.get(sub[:-1], "0")
            made[sub] = code
            nodes.append({"c": code, "p": parent, "n": sub[-1]})
    return nodes
