"""Report source/retained specification differences for review; never rewrite data."""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

import openpyxl


def comparable(value: object) -> str:
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')).lower())


def audit(rows: list[dict], source: dict[str, list[str]]) -> dict:
    pairs = Counter()
    examples: dict[tuple[str, str], list[str]] = {}
    missing = ambiguous = 0
    for row in rows:
        code = str(row.get('YJコード') or '').strip()
        matches = source.get(code, [])
        if not matches:
            missing += 1
            continue
        if len(matches) != 1:
            ambiguous += 1
            continue
        retained = str(row.get('規格') or '').strip()
        official = matches[0]
        if comparable(retained) != comparable(official):
            pair = (retained, official)
            pairs[pair] += 1
            examples.setdefault(pair, []).append(code)
    return {'pairs': pairs, 'examples': examples, 'missing': missing, 'ambiguous': ambiguous, 'rows': len(rows)}


def load_source(path: Path) -> dict[str, list[str]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        data = workbook.active.iter_rows(values_only=True)
        spec_col = yj_col = None
        for index, cells in enumerate(data):
            for col, value in enumerate(cells):
                text = str(value or '').replace('\n', '').strip()
                if text.startswith('④規格単位'):
                    spec_col = col
                if text.startswith('⑤YJコード'):
                    yj_col = col
            if spec_col is not None and yj_col is not None:
                break
            if index >= 5:
                raise ValueError('厚労省Excelの規格・YJ列を特定できません')
        if spec_col is None or yj_col is None:
            raise ValueError('厚労省Excelの規格・YJ列を特定できません')
        result: dict[str, list[str]] = {}
        for cells in data:
            if len(cells) <= max(spec_col, yj_col):
                continue
            code = str(cells[yj_col] or '').strip()
            if code:
                result.setdefault(code, []).append(str(cells[spec_col] or '').strip())
        return result
    finally:
        workbook.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--xlsx', type=Path, required=True)
    args = parser.parse_args()
    with args.csv.open(encoding='utf-8-sig', newline='') as source_file:
        reader = csv.DictReader(source_file)
        if not {'YJコード', '規格'}.issubset(reader.fieldnames or []):
            raise ValueError('CSVの規格・YJ列を特定できません')
        rows = list(reader)
    if not rows:
        raise ValueError('照合するCSVの品目がありません')
    result = audit(rows, load_source(args.xlsx))
    count = sum(result['pairs'].values())
    print(f"規格照合: {result['rows']}行中、表記正規化後の要確認 {count}件、原表未一致 {result['missing']}件、原表重複 {result['ambiguous']}件")
    for (old, new), number in result['pairs'].most_common():
        print(f'  {number}件 CSV={old or "(空欄)"} / 原表={new or "(空欄)"} / YJ={", ".join(result["examples"][(old, new)])}')
    if count or result['missing'] or result['ambiguous']:
        print('::warning::規格表記に要確認の差があります。測定単位や表記の差を含む候補であり、誤りや包装の違いと自動判定しません。')


if __name__ == '__main__':
    main()
