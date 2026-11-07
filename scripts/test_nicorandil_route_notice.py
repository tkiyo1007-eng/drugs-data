"""別製品の販売中止をニコランジルに割り当てず、販売経路を区別する。"""
import csv
import json
import unittest
from pathlib import Path
from fetch_maker_announcements import update_event_history
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent
NAME = 'ニコランジル錠５ｍｇ「サワイ」'
URL = 'https://med.daiichisankyo-ep.co.jp/information/files/2220/gentei_20260612_E1_G.pdf'


class NicorandilNotice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.notices = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.row = next(r for r in cls.rows if r['YJコード'] == '2171017F2156')
        cls.notice = next(n for n in cls.notices['notices'] if n['id'] == 'dsep-nicorandil-5mg-limited-20260612')

    def test_current_link_and_history_do_not_label_launch_as_discontinued(self):
        for filename in ['manual_announcements.json', 'maker_announcements.json']:
            item = json.loads((ROOT / filename).read_text())[NAME]
            self.assertEqual((item['url'], item['event_type']), (URL, 'limited'))
        history = json.loads((ROOT / 'maker_announcement_events.json').read_text())
        events = history[NAME]
        historic = next(e for e in events if '20130809111658' in e['url'])
        self.assertEqual(historic['event_type'], 'other')
        self.assertEqual(sum(e['url'] == URL for e in events), 1)
        manual = json.loads((ROOT / 'manual_announcements.json').read_text())[NAME]
        next_history = update_event_history(history, {NAME: manual}, today='2026-11-09')
        self.assertEqual(sum(e['url'] == URL for e in next_history[NAME]), 1)
        self.assertEqual(next(e for e in next_history[NAME] if e['url'] == URL)['last_checked'], '2026-11-08')

    def test_notice_is_specific_to_seller_and_two_packaging_units(self):
        target = self.notice['targets'][0]
        self.assertEqual((target['yj_code'], target['scope'], target['seller']),
                         ('2171017F2156', 'seller_route_and_package', '第一三共エスファ'))
        self.assertEqual([p['package'] for p in target['packages']], ['PTP100錠', 'PTP1000錠'])
        self.assertEqual(self.notice['alternatives'], [])
        self.assertTrue(any('別の対象製品' in c for c in self.notice['cautions']))
        html = manufacturer_notices_html(self.row, [self.notice])
        self.assertIn('第一三共エスファ', html)
        self.assertIn('他の販売経路', html)
        self.assertNotIn('ファモチジン', html)
        self.assertEqual(validate(self.notices, self.rows), [])

if __name__ == '__main__':
    unittest.main()
