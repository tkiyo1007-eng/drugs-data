import unittest
from pathlib import Path
from generate_item_pages import load_manufacturer_notices, manufacturer_notices_html

ROOT = Path(__file__).resolve().parent.parent


class SanwaDistributionNoticeTest(unittest.TestCase):
    def test_package_distributions_are_attributed_to_source_date(self):
        notices = load_manufacturer_notices(ROOT / 'manufacturer_notices.json')
        n = next(n for n in notices if n['id'] == 'sanwa-packages-distribution-list-20261001')
        self.assertEqual(n['collection_mode'], 'manual')
        self.assertEqual(n['announced_at'], '2026-10-01')
        for target in n['targets']:
            self.assertEqual({p['supply']['status'] for p in target['packages']}, {'normal', 'stopped'})
            row = {'YJコード': target['yj_code'], '商品名': target['product_name'], '販売メーカー': target['maker'], '製造メーカー': target['maker']}
            html = manufacturer_notices_html(row, [n])
            self.assertIn('2026年10月1日', html)
            self.assertIn('現在の状況は未確認', html)
            for p in target['packages']:
                self.assertIn(p['package'], html)
                if p['supply']['status'] == 'normal':
                    self.assertEqual(p['supply']['plans'], [{'event': 'discontinuation', 'timing': '在庫消尽次第'}])


if __name__ == '__main__':
    unittest.main()
