import hashlib
import tempfile
import unittest
from datetime import date
from pathlib import Path

import openpyxl

from build_specification_differences import build, checked_source_metadata, load_source


class SpecificationDifferencesTest(unittest.TestCase):
    def setUp(self):
        self.csv = ('YJコード,規格,商品名,一般名\nA,１Ｌ,酸素製品,酸素\nB,10mg,製品B,成分B\n').encode()
        self.source = {'A': [{'spec': '１０ｍＬ', 'name': '酸素製品', 'ingredient': '酸素'}],
                       'B': [{'spec': '１０ｍｇ', 'name': '製品B', 'ingredient': '成分B'}]}

    def make(self, data=None, source=None, source_date='2026-11-09'):
        return build(data if data is not None else self.csv,
                     source if source is not None else self.source,
                     source_date, 'a' * 64)

    def test_records_only_distinct_values_and_binds_to_csv(self):
        result = self.make()
        self.assertEqual(result['differences'], {'A': {'retained': '１Ｌ', 'source': '１０ｍＬ'}})
        self.assertEqual(result['csv_sha256'], hashlib.sha256(self.csv).hexdigest())
        self.assertEqual(result['source_date'], '2026-11-09')

    def test_missing_or_duplicate_identifiers_fail_closed(self):
        for source in ({'A': self.source['A']}, {'A': self.source['A'] * 2, 'B': self.source['B']}):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.make(source=source)
        with self.assertRaises(ValueError):
            self.make(data='YJコード,規格,商品名,一般名\nA,１Ｌ,酸素製品,酸素\nA,１Ｌ,酸素製品,酸素\n'.encode())

    def test_name_and_ingredient_must_match(self):
        for column in ('name', 'ingredient'):
            source = {k: [dict(v[0])] for k, v in self.source.items()}
            source['A'][0][column] = '別製品'
            with self.subTest(column=column), self.assertRaises(ValueError):
                self.make(source=source)

    def test_bad_date_and_empty_input_fail(self):
        with self.assertRaises(ValueError):
            self.make(source_date='2026-02-30')
        with self.assertRaises(ValueError):
            self.make(data='YJコード,規格,商品名,一般名\n'.encode())

    def test_source_columns_are_found_by_name_and_duplicates_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.xlsx'
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.append(['⑤YJコード', '⑥品名', '④規格単位', '③成分名'])
            ws.append(['A', '酸素製品', '１０ｍＬ', '酸素'])
            ws.append(['A', '酸素製品', '１Ｌ', '酸素'])
            wb.save(path)
            source = load_source(path.read_bytes())
            self.assertEqual(len(source['A']), 2)
            self.assertEqual(source['A'][0]['spec'], '１０ｍＬ')
            with self.assertRaises(ValueError):
                self.make(source=source)

    def test_source_date_and_hash_must_match_workbook_bytes(self):
        body = b'workbook bytes'
        meta = {'file': '261109iyakuhinkyoukyu.xlsx',
                'url': 'https://www.mhlw.go.jp/content/10800000/261109iyakuhinkyoukyu.xlsx',
                'excel_date': '2026-11-09', 'sha256': hashlib.sha256(body).hexdigest()}
        self.assertEqual(checked_source_metadata(meta, body, date(2026, 11, 11)),
                         ('2026-11-09', hashlib.sha256(body).hexdigest()))
        with self.assertRaises(ValueError):
            checked_source_metadata(meta, b'other workbook', date(2026, 11, 11))
        meta['excel_date'] = '2026-11-08'
        with self.assertRaises(ValueError):
            checked_source_metadata(meta, body, date(2026, 11, 11))
        meta['excel_date'] = '2026-11-12'
        with self.assertRaises(ValueError):
            checked_source_metadata(meta, body, date(2026, 11, 11))

if __name__ == '__main__':
    unittest.main()
