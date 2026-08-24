#!/usr/bin/env python3
"""メーカー欄を部分文字列に頼らず照合する。"""

from __future__ import annotations

import re
import unicodedata


TOKEN_SPLIT_RE = re.compile(r"[・／/,、;；\s]+")
DIRECTED_ALIASES = {
    # 日本ジェネリックの公式案内には、製造販売元の長生堂製薬品も掲載される。
    "日本ジェネリック": {"長生堂製薬"},
}


def norm(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def maker_tokens(value: object) -> set[str]:
    return {token for token in TOKEN_SPLIT_RE.split(norm(value)) if token}


def maker_is_listed_in_row(maker: object, row: dict[str, object]) -> bool:
    """製造・販売メーカー欄に社名が完全な単位で記載されているか。"""
    maker_n = norm(maker)
    if not maker_n:
        return False
    row_tokens = set().union(*(
        maker_tokens(row.get(field)) for field in ("製造メーカー", "販売メーカー")
    ))
    allowed = {maker_n, *DIRECTED_ALIASES.get(maker_n, set())}
    return bool(allowed & row_tokens)
