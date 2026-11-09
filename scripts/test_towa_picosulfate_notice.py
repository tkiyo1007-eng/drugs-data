import csv
import json
import unittest
from pathlib import Path

from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent


class PicosulfateNoticeTest(unittest.TestCase):
    def test_source_package_and_alternative_are_separate(self):
        document = json.loads((ROOT / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([], validate(document, rows))
        notice = next(n for n in document['notices'] if n['id'] == 'towa-picosulfate-discontinuation-20261029')
        target = notice['targets'][0]
        self.assertEqual('2359005S1305', target['yj_code'])
        self.assertEqual(['10mL×10'], [p['package'] for p in target['packages']])
        self.assertEqual('unconfirmed', target['packages'][0]['supply']['status'])
        self.assertEqual('2359005S1348', notice['alternatives'][0]['products'][0]['yj_code'])
        row = next(r for r in rows if r['YJコード'] == target['yj_code'])
        html = manufacturer_notices_html(row, [notice], catalog_yj_codes={r['YJコード'] for r in rows})
        for text in ('10mL×10', '2027年11月（予定）', 'イワキ', '2028年3月末'):
            self.assertIn(text, html)


if __name__ == '__main__':
    unittest.main()
