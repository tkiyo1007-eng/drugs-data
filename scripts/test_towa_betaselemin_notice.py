import csv
import json
import unittest
from pathlib import Path

from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent


class BetaseleminNoticeTest(unittest.TestCase):
    def test_source_packages_are_not_mixed_with_alternative(self):
        document = json.loads((ROOT / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([], validate(document, rows))
        notice = next(n for n in document['notices'] if n['id'] == 'towa-betaselemin-discontinuation-20261029')
        target = notice['targets'][0]
        self.assertEqual('2459100F1197', target['yj_code'])
        self.assertEqual(['PTP100錠', 'PTP1000錠', 'バラ1000錠'], [p['package'] for p in target['packages']])
        self.assertTrue(all(p['supply']['status'] == 'unconfirmed' for p in target['packages']))
        row = next(r for r in rows if r['YJコード'] == target['yj_code'])
        html = manufacturer_notices_html(row, [notice], catalog_yj_codes={r['YJコード'] for r in rows})
        for text in ('2027年9月（予定）', '2027年7月（予定）', '在庫なし', 'セレスタミン配合錠', '2028年3月末'):
            self.assertIn(text, html)
        self.assertNotIn('PTP500錠', html)


if __name__ == '__main__':
    unittest.main()
