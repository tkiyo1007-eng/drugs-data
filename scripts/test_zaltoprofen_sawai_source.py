"""Source-specific package dates and the manufacturer's distinct-ingredient candidate."""
import json
import unittest
from pathlib import Path


class ZaltoprofenSourceTest(unittest.TestCase):
    def test_august_notice_scope_and_merged_forecast_cell(self):
        root = Path(__file__).resolve().parent.parent
        data = json.loads((root / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        notice = next(n for n in data['notices'] if n['id'] == 'sawai-zaltoprofen-discontinuation-202608')
        self.assertEqual((notice['event_type'], notice['announced_at']), ('discontinued', '2026-08'))
        self.assertEqual(notice['collection_mode'], 'manual')
        self.assertEqual(len(notice['targets']), 1)
        target = notice['targets'][0]
        self.assertEqual(target['yj_code'], '1149029F1165')
        self.assertEqual([(p['package'], p['unified_product_code']) for p in target['packages']],
                         [('PTP100錠', '080302513'), ('PTP500錠', '080302520')])
        for package in target['packages']:
            self.assertEqual(package['supply']['status'], 'unconfirmed')
            self.assertEqual(package['supply']['plans'][0]['timing'], '2026年11月（2026年8月時点の予測）')
        group = notice['alternatives'][0]
        self.assertEqual(group['products'][0]['yj_code'], '1149019F1587')
        self.assertIn('成分が異なり', ' '.join(group['cautions']))
        self.assertIn('予定', ' '.join(notice['cautions']))


if __name__ == '__main__':
    unittest.main()
