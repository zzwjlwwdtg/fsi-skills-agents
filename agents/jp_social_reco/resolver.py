from __future__ import annotations

import re

from .settings import load_universe

_CODE_RE = re.compile(r"(?<!\d)(\d{4})(?:\.T|\.JP|番)?(?!\d)")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DATE_RE = re.compile(r"\b20\d{2}[./-]\d{1,2}(?:[./-]\d{1,2})?\b")
_MONEY_RE = re.compile(r"[$￥¥]\s*\d+(?:[,.]\d+)*|\d+(?:[,.]\d+)*\s*(?:美元|美金|円|日元|%|％)")
_JP_CONTEXT_RE = re.compile(
    r"証券コード|銘柄コード|コード番号|東証\s*\d{4}|TSE\s*\d{4}",
    re.IGNORECASE,
)


def normalize_code(value: str) -> str:
    m = _CODE_RE.search(str(value or ""))
    return m.group(1) if m else ""


def build_alias_index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for row in load_universe():
        code = row["code"]
        names = [row.get("name", ""), code, f"{code}.T", f"JP.{code}"]
        names.extend(row.get("aliases") or [])
        for name in names:
            key = str(name).strip().lower()
            if key:
                idx[key] = row
    return idx


def _clean_for_code_scan(text: str) -> str:
    out = _URL_RE.sub(" ", text or "")
    out = _DATE_RE.sub(" ", out)
    out = _MONEY_RE.sub(" ", out)
    return out


def _has_jp_stock_context(text: str, start: int, end: int, width: int = 80) -> bool:
    ctx = text[max(0, start - width): min(len(text), end + width)]
    return bool(_JP_CONTEXT_RE.search(ctx))


def resolve_mentions(text: str) -> list[dict]:
    """Resolve Japanese stock codes or known aliases from free text."""
    alias_idx = build_alias_index()
    known_by_code = {row["code"]: row for row in load_universe()}
    found: dict[str, dict] = {}
    cleaned = _clean_for_code_scan(text or "")
    for m in _CODE_RE.finditer(cleaned):
        code = m.group(1)
        if code in known_by_code:
            found[code] = known_by_code[code]
        elif _has_jp_stock_context(cleaned, m.start(), m.end()):
            found[code] = {"code": code, "name": code, "aliases": []}

    low = (text or "").lower()
    for alias, row in alias_idx.items():
        if alias and alias in low:
            found[row["code"]] = row
    return list(found.values())
