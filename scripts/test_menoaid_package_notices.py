"""メノエイドの包装と別々のメーカー文書を混同しない。"""
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent


class MenoaidNotices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.row = next(r for r in cls.rows if r['YJコード'] == '2482800S1026')
        cls.notices = {n['id']: n for n in cls.data['notices']}

    def test_each_document_keeps_its_own_packages(self):
        may = self.notices['hisamitsu-menoaid-48-discontinued-20260525']
        jul = self.notices['hisamitsu-menoaid-limited-extension-20260716']
        self.assertEqual([p['package'] for p in may['targets'][0]['packages']], ['48枚（1枚／1袋×48袋）'])
        self.assertEqual([p['package'] for p in jul['targets'][0]['packages']],
                         ['24枚（1枚／1袋×24袋）', '96枚（1枚／1袋×96袋）'])
        self.assertIn('2026年7月時点', jul['resumption'])
        self.assertTrue(any('現在も限定出荷中であること' in c for c in jul['cautions']))
        html = manufacturer_notices_html(self.row, [may, jul])
        self.assertIn('48枚包装の販売中止', html)
        self.assertIn('限定出荷延長', html)
        self.assertIn(may['url'], html)
        self.assertIn(jul['url'], html)
        self.assertEqual(validate(self.data, self.rows), [])

    def test_another_product_cannot_inherit_these_notices(self):
        notices = [self.notices['hisamitsu-menoaid-48-discontinued-20260525'],
                   self.notices['hisamitsu-menoaid-limited-extension-20260716']]
        other = dict(self.row, **{'YJコード': '2482800S1027'})
        self.assertEqual(manufacturer_notices_html(other, notices), '')

if __name__ == '__main__':
    unittest.main()
