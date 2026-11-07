import copy
import csv
import json
import unittest
from pathlib import Path
from validate_manufacturer_notices import validate
from generate_item_pages import manufacturer_notices_html

ROOT = Path(__file__).resolve().parent.parent


class NichiikoAzelnidipineNoticeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = json.loads((ROOT / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        cls.notice = next(n for n in data['notices'] if n['id'] == 'nichiiko-azelnidipine-16-resumed-202609')
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))

    def test_verified_scope_and_official_host(self):
        notice = self.notice
        self.assertEqual([], validate({'schema_version': 1, 'notices': [notice]}, self.rows))
        self.assertEqual('2026-09-30', notice['effective_at'])
        self.assertEqual('2026-09', notice['announced_at'])
        self.assertNotIn('listed_at', notice)
        self.assertEqual(['2149043F2131'], [t['yj_code'] for t in notice['targets']])
        self.assertEqual(['PTP100錠', 'PTP140錠', 'PTP500錠'],
                         [p['package'] for p in notice['targets'][0]['packages']])
        self.assertTrue(all('supply' not in p for p in notice['targets'][0]['packages']))
        spoofed = copy.deepcopy(notice)
        spoofed['url'] = 'https://www.nichiiko.co.jp.example.org/fake.pdf'
        self.assertTrue(any('unofficial URL' in x for x in validate({'schema_version': 1, 'notices': [spoofed]}, self.rows)))

    def test_static_notice_is_scoped_to_the_confirmed_product(self):
        row = next(r for r in self.rows if r['YJコード'] == '2149043F2131')
        content = manufacturer_notices_html(row, [self.notice])
        for text in ('限定出荷解除', 'PTP100錠', 'PTP140錠', 'PTP500錠', '2026-09-30'):
            self.assertIn(text, content)
        other = dict(row, **{'YJコード': '2149043F2069', '商品名': 'アゼルニジピン錠８ｍｇ「日医工」'})
        self.assertEqual('', manufacturer_notices_html(other, [self.notice]))


if __name__ == '__main__':
    unittest.main()
