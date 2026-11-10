"""Make a source-bound, review-only record of specification differences."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path

import openpyxl

from audit_specification_drift import comparable
from jst_time import jst_today
from mhlw_source_date import source_excel_date


def checked_source_metadata(meta: object, workbook_bytes: bytes, today: date) -> tuple[str, str]:
    """Bind the stored source metadata to the exact bytes used for parsing."""
    source_date = source_excel_date(meta, today)
    if not source_date or not isinstance(meta, dict):
        raise ValueError("invalid source metadata")
    match = re.fullmatch(r"(\d{6})iyakuhinkyoukyu\.xlsx", meta["file"], re.IGNORECASE)
    if match and date.fromisoformat(source_date).strftime("%y%m%d") != match.group(1):
        raise ValueError("source date and workbook filename disagree")
    digest = hashlib.sha256(workbook_bytes).hexdigest()
    if meta.get("sha256") != digest:
        raise ValueError("source workbook hash mismatch")
    return source_date, digest


def load_source(workbook_bytes: bytes) -> dict[str, list[dict[str, str]]]:
    """Read identity and specification together from the named official columns."""
    wb = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)
    try:
        rows = wb.active.iter_rows(values_only=True)
        columns = {}
        for i, cells in enumerate(rows):
            for col, value in enumerate(cells):
                text = str(value or '').replace('\n', '').strip()
                for prefix, key in (('③成分名', 'ingredient'), ('④規格単位', 'spec'),
                                    ('⑤YJコード', 'code'), ('⑥品名', 'name')):
                    if text.startswith(prefix):
                        if key in columns:
                            raise ValueError('duplicate source column')
                        columns[key] = col
            if len(columns) == 4:
                break
            if i >= 5:
                raise ValueError('missing source columns')
        if len(columns) != 4:
            raise ValueError('missing source columns')
        out = {}
        for cells in rows:
            if len(cells) <= max(columns.values()):
                continue
            record = {key: str(cells[col] or '').strip() for key, col in columns.items()}
            if record['code']:
                out.setdefault(record['code'], []).append(record)
        return out
    finally:
        wb.close()


def build(csv_bytes: bytes, source: dict[str, list[dict[str, str]]], source_date: str,
          source_sha256: str) -> dict:
    if date.fromisoformat(source_date).isoformat() != source_date:
        raise ValueError("invalid source date")
    if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
        raise ValueError("invalid source hash")
    reader = csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"), newline=""))
    if not {"YJコード", "規格", "商品名", "一般名"}.issubset(reader.fieldnames or []):
        raise ValueError("missing CSV columns")
    rows = list(reader)
    if not rows:
        raise ValueError("empty CSV")
    differences = {}
    seen = set()
    for row in rows:
        code = (row.get("YJコード") or "").strip()
        if not code or code in seen:
            raise ValueError("empty or duplicate CSV identifier")
        seen.add(code)
        matches = source.get(code, [])
        if len(matches) != 1:
            raise ValueError(f"missing or ambiguous source identifier: {code}")
        matched = matches[0]
        for col, key in (("商品名", "name"), ("一般名", "ingredient")):
            if not comparable(row.get(col)) or comparable(row.get(col)) != comparable(matched[key]):
                raise ValueError(f"source identity mismatch: {code} {col}")
        retained = (row.get("規格") or "").strip()
        official = matched['spec']
        if comparable(retained) != comparable(official):
            differences[code] = {"retained": retained, "source": official}
    return {"schema_version": 1, "source_date": source_date,
            "source_sha256": source_sha256,
            "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
            "differences": differences}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--xlsx", type=Path, required=True)
    p.add_argument("--source-metadata", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    meta = json.loads(args.source_metadata.read_text(encoding="utf-8"))
    workbook_bytes = args.xlsx.read_bytes()
    source_date, workbook_sha = checked_source_metadata(meta, workbook_bytes, jst_today())
    payload = build(args.csv.read_bytes(), load_source(workbook_bytes), source_date,
                    workbook_sha)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output.parent,
                                     prefix=".spec-differences-", delete=False) as temp:
        name = temp.name
        try:
            temp.write(body)
            temp.flush()
            os.fsync(temp.fileno())
        except Exception:
            os.unlink(name)
            raise
    try:
        os.replace(name, args.output)
    except Exception:
        os.unlink(name)
        raise


if __name__ == "__main__":
    main()
