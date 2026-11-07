"""住友ファーマ原文の包装・予定・参考候補の対象を検証。"""
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
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
        self.assertEqual([(p['package'],p['supply']['note']) for p in packs],
                         [('2mL×10アンプル','メーカーが案内した出荷終了時期：2028年2月頃。'),('2mL×50アンプル','メーカーが案内した出荷終了時期：2027年2月頃。')])
        html = manufacturer_notices_html(self.by_yj['2325400A1077'], [n])
        self.assertIn('有効成分が異なります', html)
        self.assertIn('ファモチジン静注１０ｍｇ', html)
        self.assertEqual(validate(self.data, self.rows), [])

if __name__ == '__main__':
    unittest.main()
