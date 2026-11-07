"""カモスタットJGの包装別案内を時点・対象・候補で区別する。"""
import copy
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class JgCamostatNotices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.by_yj = {r['YJコード']: r for r in cls.rows}
        cls.notices = {n['id']: n for n in cls.data['notices']}
        cls.old = cls.notices['jg-camostat-500-package-discontinued-202507']
        cls.new = cls.notices['jg-camostat-100-discontinued-202609']

    def test_distinct_source_packages_and_current_candidate(self):
        self.assertEqual(validate(self.data, self.rows), [])
        self.assertEqual(self.old['targets'][0]['packages'][0]['package'], 'PTP500錠')
        self.assertEqual(self.new['targets'][0]['packages'][0]['package'], 'PTP100錠')
        self.assertEqual(self.new['alternatives'][0]['products'][0]['yj_code'], '3999003F1386')
        self.assertTrue(all(n['collection_mode']=='manual' for n in (self.old,self.new)))
        html = manufacturer_notices_html(self.by_yj['3999003F1300'], [self.old,self.new], catalog_yj_codes=set(self.by_yj))
        for expected in ('2025年10月頃','2026年9月','2028年3月31日','3999003F1386','3999003F1017','3999003F1300'):
            self.assertIn(expected, html)
        self.assertIn(self.old['url'], html)
        self.assertIn(self.new['url'], html)
        self.assertIn('別途案内', html)
        self.assertIn('自動追跡対象外', html)

    def test_wrong_publisher_is_rejected(self):
        data=copy.deepcopy(self.data)
        next(n for n in data['notices'] if n['id']==self.new['id'])['url']='https://example.com/CAMOJ.pdf'
        self.assertTrue(any('unofficial URL' in error for error in validate(data,self.rows)))

if __name__ == '__main__':
    unittest.main()
