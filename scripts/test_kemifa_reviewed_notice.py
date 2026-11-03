"""公式RSS経由で原文を確認したケミファ案内の対象範囲。"""
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT=Path(__file__).resolve().parents[1]

class KemifaReviewedNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document=json.loads((ROOT/'manufacturer_notices.json').read_text())
        cls.notice=next(n for n in cls.document['notices'] if n['id']=='kemifa-clopidogrel-75-package-202610')
        with (ROOT/'drugs_app_ready.csv').open(encoding='utf-8-sig',newline='') as file:
            cls.rows=list(csv.DictReader(file))
        cls.row=next(r for r in cls.rows if r['YJコード']=='3399008F2196')

    def test_source_and_package_scope(self):
        self.assertEqual([],validate(self.document,self.rows))
        notice=self.notice
        self.assertEqual('2026-10',notice['announced_at'])
        self.assertNotIn('listed_at',notice)
        self.assertEqual('manual',notice['collection_mode'])
        self.assertEqual(['140錠'],[p['package'] for p in notice['targets'][0]['packages']])
        output=manufacturer_notices_html(self.row,[notice])
        for text in ('140錠','2026年10月27日','公式RSS掲載日','現在の在庫・受注可否は未確認','自動追跡対象外'):
            self.assertIn(text,output)
        self.assertNotIn('メーカーが案内した通常出荷再開日',output)

    def test_never_apply_to_other_maker_or_strength(self):
        for field,value in [('YJコード','3399008F2226'),('製造メーカー','他社'),('商品名','他の製品')]:
            row=dict(self.row);row[field]=value
            if field=='製造メーカー': row['販売メーカー']='他社'
            self.assertEqual('',manufacturer_notices_html(row,[self.notice]))

if __name__=='__main__': unittest.main()
