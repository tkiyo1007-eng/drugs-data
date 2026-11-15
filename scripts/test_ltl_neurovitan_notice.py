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
        for word in ('2026-10-26', '2026-11-15', '500錠（PTP）', '1000錠（瓶）', '熊本地震', '実際の再開やその後の生産量は確認できていません', '未定'):
            self.assertIn(word, html)
        self.assertIn('後続案内を自動追跡していません', html)
        altered = copy.deepcopy(data)
        next(n for n in altered['notices'] if n['id'] == notice['id'])['url'] = 'https://example.com/other.pdf'
        self.assertTrue(any('unofficial URL' in error for error in validate(altered, rows)))

    def test_september_wholesale_notice_keeps_its_dates_packages_and_volume_together(self):
        data = json.loads((ROOT / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            row = next(r for r in csv.DictReader(f) if r['YJコード'] == '3179106F1039')
        current_id = 'ltl-neurovitan-limited-20261026'
        historical_id = 'ltl-neurovitan-specialist-wholesalers-202609'
        notices = [notice for notice in data['notices'] if notice['id'] in {current_id, historical_id}]
        current, historical = notices
        self.assertEqual((current['id'], historical['id']), (current_id, historical_id))
        self.assertEqual(historical['announced_at'], '2026-09')
        self.assertEqual(historical['listed_at'], '2026-09-16')
        self.assertEqual(historical['effective_at'], '2026-09-28')
        target, = historical['targets']
        self.assertEqual([(p['package'], p['unified_product_code'], p['gs1_sales']) for p in target['packages']], [
            ('500錠（PTP）', '919100228', '(01)14987919100225'),
            ('1000錠（バラ）', '919100211', '(01)14987919100218'),
        ])
        summary = manufacturer_notices_html(row, notices)
        self.assertLess(summary.index(current_id), summary.index(historical_id))
        latest_card, earlier_card = summary.split(historical_id, 1)
        self.assertNotIn('約30％', latest_card)
        self.assertIn('9月16日〜27日に一時停止', earlier_card)
        self.assertIn('9月28日から限定出荷', earlier_card)
        self.assertIn('現在の出荷量・受注・卸在庫は未確認', earlier_card)
        self.assertNotIn(historical_id, manufacturer_notices_html(dict(row, YJコード='3179106F9999'), notices))

if __name__ == '__main__':
    unittest.main()
