"""Check the exact seller, manufacturer and package on the source notice."""
import csv
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class HoneySourceTest(unittest.TestCase):
    def test_source_applies_to_only_the_confirmed_yj_and_route(self):
        document = json.loads((ROOT / 'manufacturer_notices.json').read_text(encoding='utf-8'))
        matches = [n for n in document['notices'] if n['id'] == 'maruishi-honey-akita-discontinued-extension-202603']
        self.assertEqual(len(matches), 1)
        notice = matches[0]
        self.assertEqual(notice['collection_mode'], 'manual')
        self.assertEqual(notice['announced_at'], '2026-03')
        self.assertIn('2027年3月31日', notice['reason'])
        self.assertIn('告示がなされない', ' '.join(notice['cautions']))
        self.assertIn('日本養蜂', ' '.join(notice['cautions']))
        self.assertEqual(len(notice['targets']), 1)
        target = notice['targets'][0]
        self.assertEqual((target['yj_code'], target['maker'], target['seller'], target['scope']),
                         ('7149003X1333', '秋田屋本店', '丸石製薬', 'seller_route_and_package'))
        self.assertEqual([p['package'] for p in target['packages']], ['500g'])
        self.assertEqual(target['packages'][0]['supply']['status'], 'unconfirmed')
        self.assertEqual(target['packages'][0]['supply']['plans'], [])
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = {r['YJコード']: r for r in csv.DictReader(f)}
        if '7149003X1333' in rows:
            self.assertEqual(rows['7149003X1333']['製造メーカー'], '秋田屋本店')
            self.assertEqual(rows['7149003X1333']['販売メーカー'], '丸石製薬')


if __name__ == '__main__':
    unittest.main()
