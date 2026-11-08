"""ホルマリンのメーカー案内と同名他社を取り違えない。"""
import csv
import json
import unittest
from pathlib import Path

from build_product_lifecycle import existing_record_needs_reverification

ROOT = Path(__file__).resolve().parent.parent


class FormalinSourceTests(unittest.TestCase):
    def test_confirmed_notice_matches_yj_and_retained_manufacturer(self):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {row['YJコード']: row for row in csv.DictReader(f)}
        if '2619708X1193' not in rows:
            self.skipTest('原表から対象YJコードが除かれた')
        row = rows['2619708X1193']
        self.assertEqual(row['製造メーカー'], '山善製薬')
        self.assertEqual(row['販売メーカー'], '')
        item = json.loads((ROOT / 'product_lifecycle.json').read_text())['products']['2619708X1193']
        self.assertEqual(item['product_name'], row['商品名'])
        self.assertEqual(item['maker'], row['製造メーカー'])
        self.assertEqual(item['state'], 'discontinuation_announced')
        self.assertEqual(item['announced_at'], '2025-05-19')
        self.assertIn('yamazen-pharm.co.jp/', item['source_url'])
        self.assertFalse(existing_record_needs_reverification(item))


if __name__ == '__main__':
    unittest.main()
