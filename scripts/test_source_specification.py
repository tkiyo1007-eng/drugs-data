import hashlib
import unittest

from generate_item_pages import page_html
from source_specification import valid_comparison


class SourceSpecificationTest(unittest.TestCase):
    def setUp(self):
        self.csv = 'YJコード,規格\nA,１Ｌ\n'.encode()
        self.meta = {'file': '261109iyakuhinkyoukyu.xlsx',
                     'url': 'https://www.mhlw.go.jp/content/10800000/261109iyakuhinkyoukyu.xlsx',
                     'excel_date': '2026-11-09', 'sha256': 'a' * 64}
        self.version = {'version': 202611110202, 'mhlw_excel_date': '2026-11-09'}
        self.doc = {'schema_version': 1, 'source_date': '2026-11-09', 'source_sha256': 'a' * 64,
                    'csv_sha256': hashlib.sha256(self.csv).hexdigest(),
                    'differences': {'A': {'retained': '１Ｌ', 'source': '１０ｍＬ'}}}

    def test_data_bound_to_source_and_csv(self):
        self.assertTrue(valid_comparison(self.doc, self.meta, self.csv, self.version))
        self.assertFalse(valid_comparison(self.doc, self.meta, self.csv + b'\n', self.version))
        self.assertFalse(valid_comparison(self.doc, {**self.meta, 'sha256': 'b' * 64}, self.csv, self.version))
        self.assertFalse(valid_comparison(self.doc, self.meta, self.csv, {**self.version, 'mhlw_excel_date': '2026-11-10'}))
        self.assertFalse(valid_comparison(self.doc, {**self.meta, 'url': 'https://example.com/file.xlsx'}, self.csv, self.version))
        self.assertFalse(valid_comparison(self.doc, self.meta, self.csv, {**self.version, 'version': 202611080000}))
        self.assertFalse(valid_comparison({**self.doc, 'differences': {'A': {'retained': '別値', 'source': '１０ｍＬ'}}}, self.meta, self.csv, self.version))

    def test_static_page_escapes_source_value(self):
        row = {'商品名': '対象', '一般名': '酸素', '規格': '１Ｌ', '供給状況': '①通常出荷', 'YJコード': 'A'}
        doc = {**self.doc, 'differences': {'A': {'retained': '１Ｌ', 'source': '<test>'}}}
        output = page_html(row, 'A', 'ok', '2026-11-11', [], set(), specification_comparison=doc)
        self.assertIn('厚労省原表の規格単位（2026-11-09）：&lt;test&gt;', output)
        self.assertNotIn('：<test>', output)
        self.assertNotIn('厚労省原表の規格単位', page_html(row, 'A', 'ok', '2026-11-11', [], set()))


if __name__ == '__main__':
    unittest.main()
