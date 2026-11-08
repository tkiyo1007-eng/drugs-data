"""Report possible manufacturer drift without rewriting retained metadata.

Excel and the CSV may use different legal suffixes or spelling. A mismatch is a
review candidate, not proof of an error or a change in current supply status.
"""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from collections import Counter
from pathlib import Path

import openpyxl


def comparable(value: object) -> str:
    value = unicodedata.normalize('NFKC', str(value or '')).lower()
    value = value.replace('’', "'").replace('‘', "'")
    value = re.sub(r'株式会社|有限会社|合同会社|一般社団法人|一般財団法人', '', value)
    value = re.sub(r'製造販売業者[（(]輸入元[）)]|製造販売元[（(]輸入[）)]|製造販売業者', '', value)
    return re.sub(r'[\s\u3000]+', '', value)


def audit(rows: list[dict], source: dict[str, list[str]]) -> dict:
    different = Counter()
    examples: dict[tuple[str, str], list[str]] = {}
    missing = ambiguous = 0
    for row in rows:
        yj = str(row.get('YJコード') or '').strip()
        matches = source.get(yj, [])
        if not matches:
            missing += 1
            continue
        if len(matches) != 1:
            ambiguous += 1
            continue
        existing = str(row.get('製造メーカー') or '').strip()
        current = matches[0]
        # 空欄を同一視しない。報告のみで自動補完・変更はしない。
        if not existing or not current or comparable(existing) != comparable(current):
            different[(existing, current)] += 1
            examples.setdefault((existing, current), [])
            examples[(existing, current)].append(yj)
    return {'review_pairs': different, 'examples': examples, 'missing': missing, 'ambiguous': ambiguous, 'rows': len(rows)}


def load_source(path: Path) -> dict[str, list[str]]:
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        source: dict[str, list[str]] = {}
        data = sheet.iter_rows(values_only=True)
        yj_column = maker_column = None
        for index, cells in enumerate(data):
            for col, value in enumerate(cells):
                text = str(value or '').replace('\n', '').strip()
                if text.startswith('⑤YJコード'):
                    yj_column = col
                if text.startswith('⑦製造販売業者名'):
                    maker_column = col
            if yj_column is not None and maker_column is not None:
                break
            if index >= 5:
                raise ValueError('厚労省Excelのメーカー・YJ列を特定できません')
        if yj_column is None or maker_column is None:
            raise ValueError('厚労省Excelのメーカー・YJ列を特定できません')
        for cells in data:
            if len(cells) <= max(yj_column, maker_column):
                continue
            yj = str(cells[yj_column] or '').strip()
            if yj:
                source.setdefault(yj, []).append(str(cells[maker_column] or '').strip())
        return source
    finally:
        workbook.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', type=Path, required=True)
    parser.add_argument('--xlsx', type=Path, required=True)
    args = parser.parse_args()
    with args.csv.open(encoding='utf-8-sig', newline='') as source_file:
        rows = list(csv.DictReader(source_file))
    result = audit(rows, load_source(args.xlsx))
    count = sum(result['review_pairs'].values())
    print(f"メーカー照合: {result['rows']}行中、表記正規化後の要確認 {count}件、原表未一致 {result['missing']}件、原表重複 {result['ambiguous']}件")
    for (old, new), number in result['review_pairs'].most_common():
        examples = ', '.join(result['examples'][(old, new)])
        print(f'  {number}件 CSV={old or "(空欄)"} / 原表={new or "(空欄)"} / YJ={examples}')
    if count or result['missing'] or result['ambiguous']:
        print('::warning::メーカー表記に要確認の差があります。表記差・承継等を含む候補であり、自動的に誤りや供給変化とは判定しません。')


if __name__ == '__main__':
    main()
