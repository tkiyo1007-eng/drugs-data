#!/usr/bin/env python3
"""確認済みガス行の原表の識別が変わったら日次更新を止める。"""
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl


def normalize(value):
    value = unicodedata.normalize('NFKC', str(value or ''))
    return re.sub(r'\s+', '', value).lower()


def validate(rows, reviewed):
    seen = set()
    errors = []
    for code, name, maker in rows:
        code = str(code or '').strip()
        if code not in reviewed:
            continue
        if code in seen:
            errors.append(f'{code}: 原表識別子が重複')
            continue
        seen.add(code)
        expected = reviewed[code]
        if normalize(name) != normalize(expected['name']) or normalize(maker) != normalize(expected['manufacturer']):
            errors.append(f'{code}: 原表の品名または製造販売元が確認済み情報と一致しません')
    return errors


def main():
    reviewed = json.loads(Path('verified_missing_gas_sellers.json').read_text(encoding='utf-8'))['products']
    workbook = openpyxl.load_workbook('supply_latest.xlsx', read_only=True, data_only=True)
    try:
        rows = ((r[4], r[5], r[6]) for r in workbook.active.iter_rows(min_row=2, values_only=True) if len(r) > 6)
        errors = validate(rows, reviewed)
    finally:
        workbook.close()
    if errors:
        print('\n'.join(errors), file=sys.stderr)
        return 1
    print('確認済みガス原表の識別整合: OK（原表から消えた行は取り込み対象外）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
