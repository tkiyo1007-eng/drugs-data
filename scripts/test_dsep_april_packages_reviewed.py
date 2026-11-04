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
        self.assertEqual({'2139008F2052','2139008F1072','2189018F1035','2149044F5038','2149044F6034','2149044F7030','2149032F4128','2149032F1170','2189017F1030','2189017F2037','2189017F3033','2189017F4030'}, {t['yj_code'] for t in self.notice['targets']})

    def test_current_status_is_not_inferred_from_plans(self):
        expected = {'2139008F2052': [('081-185320','2027年2月')], '2139008F1072': [('081-185382','2027年1月')], '2189018F1035': [('081-189472','2027年2月')], '2149044F5038': [('081-187126','2027年6月'),('081-187133','2027年6月')], '2149044F6034': [('081-187195','2027年3月'),('081-187201','2027年4月')], '2149044F7030': [('081-187263','2027年7月')], '2149032F4128': [('081-185436','2028年6月')], '2149032F1170': [('081-185528','2027年12月')], '2189017F1030': [('081-186938','2027年7月'),('081-186921','2027年4月'),('081-186945','2027年4月')], '2189017F2037': [('081-187027','2027年6月'),('081-187034','2027年3月')], '2189017F3033': [('081-187522','2027年4月')], '2189017F4030': [('081-187577','2027年3月')]}
        for target in self.notice['targets']:
            self.assertEqual('package',target['scope'])
            plans = [(p['unified_product_code'],plan['timing']) for p in target['packages'] for plan in p['supply']['plans'] if plan['event']=='stock_depletion']
            self.assertEqual(expected[target['yj_code']],plans)
            self.assertTrue(any(not p['supply']['plans'] for p in target['packages']))
            self.assertTrue(all(p['supply']['status']=='unconfirmed' for p in target['packages']))

if __name__ == '__main__': unittest.main()
