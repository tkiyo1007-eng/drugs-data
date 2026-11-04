import copy
import csv
import json
import unittest
from pathlib import Path
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class KyorinPackagingTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        cls.notice = next(n for n in data['notices'] if n['id'] == 'kyorin-kipres-ketas-package-202610')
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))

    def test_source_and_packaging_are_scoped(self):
        self.assertEqual([], validate({'schema_version': 1, 'notices': [self.notice]}, self.rows))
        expected = {'4490026C1021': [('060-006837', '2027年3月')], '4490026F1044': [('060-007087', '2027年4月'), ('060-007599', '2027年4月')], '4490010N1021': [('060-004338', '2027年5月')]}
        self.assertEqual(set(expected), {t['yj_code'] for t in self.notice['targets']})
        for target in self.notice['targets']:
            self.assertEqual('package', target['scope'])
            plans = [(p['unified_product_code'], plan['timing']) for p in target['packages'] for plan in p['supply']['plans']]
            self.assertEqual(expected[target['yj_code']], plans)
            self.assertTrue(any(not p['supply']['plans'] for p in target['packages']))
            self.assertTrue(all(p['supply']['status'] == 'unconfirmed' for p in target['packages']))

    def test_unofficial_source_is_rejected(self):
        notice = copy.deepcopy(self.notice)
        notice['url'] = 'https://www.kyorin-pharm.co.jp.example.org/notice.pdf'
        self.assertTrue(any('unofficial URL' in e for e in validate({'schema_version': 1, 'notices': [notice]}, self.rows)))

if __name__ == '__main__':
    unittest.main()
