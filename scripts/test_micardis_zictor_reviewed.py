import csv
import json
import unittest
from pathlib import Path
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class NewManufacturerNotices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        doc = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        cls.notices = {n['id']: n for n in doc['notices']}
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))

    def test_zictor_packaging_and_future_stop(self):
        n = self.notices['hisamitsu-zictor-fourth-202610']
        self.assertEqual([], validate({'schema_version': 1, 'notices': [n]}, self.rows))
        target, = n['targets']
        self.assertEqual('1147700S1028', target['yj_code'])
        first, second = target['packages']
        self.assertEqual(('188-488010', '188-488027'), (first['unified_product_code'], second['unified_product_code']))
        self.assertIn('2026年11月下旬', first['supply']['note'])
        self.assertIn('限定出荷継続', second['supply']['status_text'])
        self.assertNotEqual('stopped', first['supply']['status'])

    def test_micardis_scoped_to_three_manufacturer_packages(self):
        n = self.notices['boehringer-micardis-limited-202611']
        self.assertEqual([], validate({'schema_version': 1, 'notices': [n]}, self.rows))
        self.assertEqual({'2149042F1025':'413-660525', '2149042F2021':'413-660624', '2149042F3028':'413-660716'}, {t['yj_code']:t['packages'][0]['unified_product_code'] for t in n['targets']})
        self.assertTrue(all(t['scope'] == 'package' and t['packages'][0]['supply']['status'] == 'limited' for t in n['targets']))
        self.assertNotIn('listed_at', n)

if __name__ == '__main__':
    unittest.main()
