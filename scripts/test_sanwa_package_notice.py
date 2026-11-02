import json
import unittest
from pathlib import Path

from generate_item_pages import load_manufacturer_notices, manufacturer_notices_html


ROOT = Path(__file__).resolve().parent.parent


class SanwaPackageNoticeTest(unittest.TestCase):
    def test_past_notice_does_not_claim_present_shipment_state(self):
        notices = load_manufacturer_notices(ROOT / 'manufacturer_notices.json')
        notice = next(n for n in notices if n['id'] == 'sanwa-calcium-carbonate-package-202610')
        target = notice['targets'][0]
        self.assertEqual(target['yj_code'], '2190024F1040')
        self.assertEqual(notice['collection_mode'], 'manual')
        self.assertEqual(len(target['packages']), 4)
        self.assertTrue(all(p['supply']['status'] == 'unconfirmed' for p in target['packages']))
        self.assertIn('2026年12月中予定', json.dumps(target, ensure_ascii=False))
        row = {'YJコード': target['yj_code'], '商品名': target['product_name'], '販売メーカー': target['maker'], '製造メーカー': target['maker']}
        html = manufacturer_notices_html(row, [notice])
        for text in ('PTP500錠', 'PTP100錠', 'PTP1000錠', 'バラ500錠', '実際の消尽・停止・再開は未確認'):
            self.assertIn(text, html)


if __name__ == '__main__':
    unittest.main()
