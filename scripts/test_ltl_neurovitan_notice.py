import copy
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class LtlNeurovitanNoticeTests(unittest.TestCase):
    def test_package_scope_and_historical_plan(self):
        data = json.loads((ROOT / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        notice = next(n for n in data['notices'] if n['id'] == 'ltl-neurovitan-limited-20261026')
        row = next(r for r in rows if r['YJコード'] == '3179106F1039')
        self.assertEqual(validate(data, rows), [])
        self.assertEqual(notice['collection_mode'], 'manual')
        self.assertEqual([p['package'] for p in notice['targets'][0]['packages']], ['500錠（PTP）', '1000錠（瓶）'])
        self.assertTrue(all(p['supply']['status'] == 'limited' for p in notice['targets'][0]['packages']))
        html = manufacturer_notices_html(row, [notice], catalog_yj_codes={r['YJコード'] for r in rows})
        for word in ('2026-10-26', '2026-11-08', '500錠（PTP）', '1000錠（瓶）', '熊本地震', '実際の再開やその後の生産量は確認できていません', '未定'):
            self.assertIn(word, html)
        self.assertIn('後続案内を自動追跡していません', html)
        altered = copy.deepcopy(data)
        next(n for n in altered['notices'] if n['id'] == notice['id'])['url'] = 'https://example.com/other.pdf'
        self.assertTrue(any('unofficial URL' in error for error in validate(altered, rows)))

if __name__ == '__main__':
    unittest.main()
