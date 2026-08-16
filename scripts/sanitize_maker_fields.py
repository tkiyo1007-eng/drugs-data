#!/usr/bin/env python3
"""メーカー欄へ混入した医療用ガス共通文書の説明文を除去する。"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


NOISE_START = "一般社団法人 日本産業・医療ガス協会"
NOISE_MARKER = "本注意事項等情報を使用している製造販売業者一覧表"
NOISE_END = "PDF形式にてご確認ください。"
MULTIPLE_MAKERS_LABEL = "複数の製造販売業者（医薬品ラベルを確認）"


def strip_gas_document_note(value: str) -> tuple[str, bool]:
    """共通文書の説明部分だけを除き、前後にある実在会社名は保持する。"""
    value = (value or "").strip()
    start = value.find(NOISE_START)
    if start < 0 or NOISE_MARKER not in value[start:]:
        return value, False
    end = value.find(NOISE_END, start)
    if end < 0:
        # 不完全な未知形式は推測で削らず、公開前検査に検知させる。
        return value, False
    end += len(NOISE_END)
    before = value[:start].rstrip(" ・")
    after = value[end:].lstrip(" ・")
    return "・".join(part for part in (before, after) if part), True


def sanitize_csv(path: Path) -> tuple[int, int]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return 0, 0
    header = rows[0]
    manufacturer_index = header.index("製造メーカー")
    sales_index = header.index("販売メーカー")
    manufacturer_fixed = sales_fixed = 0
    for row in rows[1:]:
        if len(row) <= max(manufacturer_index, sales_index):
            continue
        manufacturer, changed = strip_gas_document_note(row[manufacturer_index])
        if changed:
            row[manufacturer_index] = manufacturer or MULTIPLE_MAKERS_LABEL
            manufacturer_fixed += 1
        sales, changed = strip_gas_document_note(row[sales_index])
        if changed:
            row[sales_index] = sales
            sales_fixed += 1
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    return manufacturer_fixed, sales_fixed


def main(argv=None):
    args = argv or sys.argv[1:]
    path = Path(args[0] if args else "drugs_app_ready.csv")
    manufacturer_fixed, sales_fixed = sanitize_csv(path)
    print(
        f"✅ メーカー欄整形: 製造メーカー {manufacturer_fixed}件 / "
        f"販売メーカー {sales_fixed}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
