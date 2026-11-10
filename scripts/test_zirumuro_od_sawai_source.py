"""The source assigns different forecast dates to each strength and package."""
import json
import unittest
from pathlib import Path


class ZirumuroSourceTest(unittest.TestCase):
    def test_package_forecasts_stay_with_the_source_strength(self):
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        notice = next(n for n in data['notices'] if n['id'] == 'sawai-zirumuro-od-package-supply-202605')
        self.assertEqual(notice['collection_mode'], 'manual')
        self.assertEqual(notice['announced_at'], '2026-05')
        targets = {t['yj_code']: t for t in notice['targets']}
        self.assertEqual(set(targets), {'2149121F3024', '2149121F4020'})
        expected = {'2149121F3024': [('PTP100錠', '080339113', '2026年11月')],
                    '2149121F4020': [('PTP100錠', '080306115', '2026年7月'),
                                     ('バラ200錠', '080306146', '2026年12月')]}
        for yj, products in expected.items():
            packages = targets[yj]['packages']
            self.assertEqual(len(packages), len(products))
            for item, (name, code, date) in zip(packages, products):
                self.assertEqual((item['package'], item['unified_product_code']), (name, code))
                self.assertIn(date, item['supply']['plans'][0]['timing'])
                self.assertIn('予測', item['supply']['plans'][0]['timing'])
        self.assertIn('実際の在庫消尽', ' '.join(notice['cautions']))


if __name__ == '__main__':
    unittest.main()
