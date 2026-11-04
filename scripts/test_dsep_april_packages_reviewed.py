import csv
import json
import unittest
from pathlib import Path
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class DsepAprilPackagesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        cls.notice = next(n for n in data['notices'] if n['id'] == 'dsep-azosemide-ezetimibe-package-202604')
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))

    def test_exact_product_and_manufacturer_identity(self):
        self.assertEqual([], validate({'schema_version': 1, 'notices': [self.notice]}, self.rows))
        self.assertEqual({'2139008F2052','2139008F1072','2189018F1035'}, {t['yj_code'] for t in self.notice['targets']})

    def test_current_status_is_not_inferred_from_plans(self):
        expected = {'2139008F2052': ('081-185320','2027年2月'), '2139008F1072': ('081-185382','2027年1月'), '2189018F1035': ('081-189472','2027年2月')}
        for target in self.notice['targets']:
            self.assertEqual('package',target['scope'])
            plans = [(p['unified_product_code'],plan['timing']) for p in target['packages'] for plan in p['supply']['plans'] if plan['event']=='stock_depletion']
            self.assertEqual([expected[target['yj_code']]],plans)
            self.assertTrue(any(not p['supply']['plans'] for p in target['packages']))
            self.assertTrue(all(p['supply']['status']=='unconfirmed' for p in target['packages']))

if __name__ == '__main__': unittest.main()
