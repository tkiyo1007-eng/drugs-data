"""Product-level notices must not invent packaging coverage."""
import csv
import unittest
from pathlib import Path

from generate_item_pages import manufacturer_notice_scope_text
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent


class ProductScopeNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.row = next(r for r in cls.rows if r['YJコード'] == '2399006F1579')

    def notice(self, scope):
        return {'schema_version': 1, 'notices': [{
            'id': 'sample-product-notice', 'maker': '沢井製薬', 'title': '確認用資料',
            'url': 'https://med.sawai.co.jp/pdf/announce/announce20.pdf',
            'sha256': '0' * 64, 'event_type': 'limited', 'reason': '品目単位の資料',
            'announced_at': '2026-11-09', 'verified_at': '2026-11-09',
            'targets': [{'yj_code': self.row['YJコード'], 'product_name': self.row['商品名'],
                         'scope': scope, 'packages': []}],
            'alternatives': [], 'cautions': [],
        }]}

    def test_product_scope_accepts_unknown_packaging_and_labels_it(self):
        document = self.notice('product')
        self.assertEqual(validate(document, self.rows), [])
        self.assertIn('包装別の内訳は未確認', manufacturer_notice_scope_text(document['notices'][0]['targets'][0]))

    def test_package_scope_without_package_is_rejected(self):
        self.assertTrue(any('missing package scope' in e for e in validate(self.notice('package'), self.rows)))

    def test_manufacturer_status_rejects_non_text_values(self):
        document = self.notice('product')
        document['notices'][0]['maker_supply_status'] = {'volume': ['出荷量減少']}
        self.assertTrue(any('invalid maker supply status' in e for e in validate(document, self.rows)))


if __name__ == '__main__':
    unittest.main()
