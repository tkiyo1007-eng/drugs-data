"""住友ファーマ原文の包装・予定・参考候補の対象を検証。"""
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html, page_html
from validate_manufacturer_notices import validate
ROOT = Path(__file__).resolve().parent.parent

class SumitomoPackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.by_yj = {r['YJコード']: r for r in cls.rows}
        cls.notices = {n['id']: n for n in cls.data['notices']}

    def test_dops_is_package_scoped_and_future_is_not_fact(self):
        n = self.notices['sumitomo-dops100-package-202609']
        self.assertEqual([x['yj_code'] for x in n['targets']], ['1169006F1027'])
        packs = n['targets'][0]['packages']
        self.assertEqual([p['package'] for p in packs], ['バラ500錠', 'PTP100錠'])
        self.assertTrue(all(p['supply']['status'] == 'unconfirmed' for p in packs))
        self.assertIn('出荷終了時期：2026年11月', packs[0]['supply']['note'])
        html = manufacturer_notices_html(self.by_yj['1169006F1027'], [n])
        self.assertIn('現在の在庫・受注可否は未確認', html)
        self.assertEqual(manufacturer_notices_html(self.by_yj['1169006F2023'], [n]), '')

    def test_tagamet_has_separate_pack_dates_and_precautions(self):
        n = self.notices['sumitomo-tagamet-injection-202609']
        packs = n['targets'][0]['packages']
        self.assertEqual([(p['package'], p['supply']['plans']) for p in packs],
                         [('2mL×10アンプル', [{'event': 'stock_depletion', 'timing': '2028年2月頃'}]),
                          ('2mL×50アンプル', [{'event': 'stock_depletion', 'timing': '2027年2月頃'}])])
        html = manufacturer_notices_html(self.by_yj['2325400A1077'], [n])
        self.assertIn('有効成分が異なります', html)
        self.assertIn('ファモチジン静注１０ｍｇ', html)
        self.assertEqual(validate(self.data, self.rows), [])

    def test_tagamet_shows_injection_pack_dates_and_keeps_tablet_end_notice_after_resumption(self):
        tablet, injection = '2325001F1211', '2325400A1077'
        resume = self.notices['sumitomo-tagamet200-ptp100-resumed-202611']
        end = self.notices['sumitomo-tagamet200-ptp100-end-202605']
        injection_notice = self.notices['sumitomo-tagamet-injection-202609']
        def render(key, notices):
            return page_html(self.by_yj[key], key, 'ok', '2026-11-23', [], {tablet, injection},
                             manufacturer_notices=notices, manufacturer_bulletins={'items': []})
        page = render(injection, [injection_notice])
        brief = page.split('id="packageBriefTitle"', 1)[1].split('</section>', 1)[0]
        self.assertIn('2mL×10アンプルの出荷終了見込みは2028年2月頃', brief)
        self.assertIn('2mL×50アンプルの出荷終了見込みは2027年2月頃', brief)
        self.assertIn('href="2325001F1211.html"', page)
        self.assertNotIn('id="tagametPricingTitle"', page)
        page = render(tablet, [resume, end])
        brief = page.split('id="packageBriefTitle"', 1)[1].split('</section>', 1)[0]
        self.assertIn('PTP100錠の出荷終了見込みは2027年1月頃', brief)
        self.assertIn('tagamet_gentei_20261117.pdf', page)
        self.assertIn('href="2325400A1077.html"', page)
        self.assertIn('経過措置期限は<strong>2027年3月31日</strong>', page)
        self.assertIn('2028年3月31日までの延長を申請する予定', page)

if __name__ == '__main__':
    unittest.main()
