import copy
import csv
import json
import unittest
from pathlib import Path
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class DsepSilodosinReviewedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        cls.notice = next(n for n in data['notices'] if n['id'] == 'dsep-silodosin-package-discontinuation-202607')
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))

    def test_exact_manufacturer_host_and_identity_required(self):
        notice = copy.deepcopy(self.notice)
        self.assertEqual([], validate({'schema_version': 1, 'notices': [notice]}, self.rows))
        notice['url'] = 'https://med.daiichisankyo-ep.co.jp.example.org/fake.pdf'
        self.assertTrue(any('unofficial URL' in x for x in validate({'schema_version': 1, 'notices': [notice]}, self.rows)))
        notice = copy.deepcopy(self.notice)
        notice['targets'][0]['yj_code'] = notice['targets'][1]['yj_code']
        self.assertTrue(any('identity mismatch' in x for x in validate({'schema_version': 1, 'notices': [notice]}, self.rows)))

    def test_packaging_plans_are_not_current_shipment_status(self):
        self.assertEqual(4, len(self.notice['targets']))
        for target in self.notice['targets']:
            self.assertEqual('package', target['scope'])
            self.assertTrue(any(not p['supply']['plans'] for p in target['packages']))
            for package in target['packages']:
                self.assertEqual('unconfirmed', package['supply']['status'])
                self.assertTrue(all(plan['event'] == 'stock_depletion' for plan in package['supply']['plans']))

if __name__ == '__main__':
    unittest.main()
