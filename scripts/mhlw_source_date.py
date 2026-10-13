"""原Excelの記録済み基準日。取込日やURLの日付からは補完しない。"""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import unquote, urlsplit


def source_excel_date(source: object, imported_on: dt.date) -> str | None:
    if not isinstance(source, dict) or type(imported_on) is not dt.date:
        return None
    value, filename, url = (source.get(k) for k in ("excel_date", "file", "url"))
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    if not isinstance(filename, str) or not filename or "/" in filename or "\\" in filename:
        return None
    if not isinstance(url, str):
        return None
    try:
        day = dt.date.fromisoformat(value)
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname not in {"www.mhlw.go.jp", "mhlw.go.jp"}
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not parsed.path.startswith("/content/")
                or unquote(parsed.path.rsplit("/", 1)[-1]) != filename
                or not filename.lower().endswith(".xlsx") or day > imported_on):
            return None
    except ValueError:
        return None
    return value
