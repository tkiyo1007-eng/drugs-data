"""岩城製薬の10月原文と品目・包装・日付の結び付け。"""
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate
ROOT = Path(__file__).resolve().parent.parent
NAME = 'モメタゾンフランカルボン酸エステルローション０．１％「イワキ」'
URL = 'https://www.iwakiseiyaku.co.jp/dcms_media/other/fmlosirase20261005.pdf'
class IwakiMometasoneNotice(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT/'manufacturer_notices.json').read_text())
        with (ROOT/'drugs_app_ready.csv').open(encoding='utf-8-sig',newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.row = next(r for r in cls.rows if r['YJコード']=='2646731Q1063')
        cls.notice = next(n for n in cls.data['notices'] if n['id']=='iwaki-mometasone-lotion-limited-20261005')

    def test_october_announcement_overrides_september_and_preserves_mhlw(self):
        for file in ['manual_announcements.json','maker_announcements.json']:
            record=json.loads((ROOT/file).read_text())[NAME]
            self.assertEqual(record['url'], URL)
            self.assertEqual(record['event_type'],'limited')
        events=json.loads((ROOT/'maker_announcement_events.json').read_text())[NAME]
        self.assertTrue(any(e['url']==URL and e['event_type']=='limited' for e in events))
        self.assertTrue(any(e['url'].endswith('fmlosirase20260915.pdf') and e['event_type']=='stopped' for e in events))
        before=self.row['供給状況']
        manufacturer_notices_html(self.row,[self.notice])
        self.assertEqual(self.row['供給状況'],before)
        self.assertEqual(validate(self.data,self.rows),[])

    def test_source_limits_scope_to_10_by_10_and_does_not_claim_current(self):
        n=self.notice
        self.assertEqual(n['url'],URL)
        self.assertEqual([t['yj_code'] for t in n['targets']],['2646731Q1063'])
        p=n['targets'][0]['packages']
        self.assertEqual([(x['package'],x['unified_product_code']) for x in p],[('10g×10','020-021535')])
        self.assertIn('2026年10月5日',n['summary'])
        self.assertTrue(any('現在も同じ出荷状態' in s for s in n['cautions']))
        html=manufacturer_notices_html(self.row,[n])
        self.assertIn('現在の受注可否や在庫は未確認',html)
        other=dict(self.row,**{'YJコード':'2646731Q1055'})
        self.assertEqual(manufacturer_notices_html(other,[n]),'')

if __name__=='__main__':unittest.main()
