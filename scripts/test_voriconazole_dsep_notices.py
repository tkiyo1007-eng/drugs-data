"""規格ごとの予定・後続案内・メーカー候補を混同しない。"""
import csv
import json
import unittest
from pathlib import Path
from generate_item_pages import manufacturer_notices_html
from validate_manufacturer_notices import validate

ROOT = Path(__file__).resolve().parent.parent

class VoriconazoleDsepNotices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'manufacturer_notices.json').read_text())
        with (ROOT / 'drugs_app_ready.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.rows = list(csv.DictReader(f))
        cls.by_yj = {r['YJコード']: r for r in cls.rows}
        cls.notices = {n['id']: n for n in cls.data['notices']}
        cls.jul = cls.notices['dsep-voriconazole-supply-plan-202607']
        cls.oct = cls.notices['dsep-voriconazole50-release-plan-202610']

    def test_source_scopes_and_candidate_groups(self):
        self.assertEqual(validate(self.data, self.rows), [])
        self.assertEqual([t['yj_code'] for t in self.oct['targets']], ['6179001F1031'])
        self.assertEqual([t['yj_code'] for t in self.jul['targets']], ['6179001F1031','6179001F2038'])
        groups = {g['target_yj_codes'][0]: g['products'][0]['yj_code'] for g in self.jul['alternatives']}
        self.assertEqual(groups, {'6179001F1031':'6179001F1066','6179001F2038':'6179001F2062'})
        for t in self.jul['targets']:
            self.assertEqual(t['packages'][0]['package'], 'PTP50錠（10錠×5）')
            self.assertNotIn('planned_timing', t)

    def test_static_pages_keep_timing_as_plans_and_do_not_cross_strengths(self):
        notices = [self.jul, self.oct]
        one = manufacturer_notices_html(self.by_yj['6179001F1031'], notices, catalog_yj_codes=set(self.by_yj))
        two = manufacturer_notices_html(self.by_yj['6179001F2038'], notices, catalog_yj_codes=set(self.by_yj))
        self.assertIn('2026年10月末', one)
        self.assertIn('2027年1月末', two)
        self.assertIn('実際の停止', one)
        self.assertIn('停止・再開の実施を確認した意味ではありません', one)
        self.assertIn('6179001F1066', one)
        self.assertNotIn('6179001F2062', one)
        self.assertIn('6179001F2062', two)
        self.assertNotIn('6179001F1066', two)
        self.assertIn(self.oct['url'], one)
        self.assertNotIn(self.oct['url'], two)
        self.assertNotIn('メーカーの再開・解除に関する案内：2026年10月末', one)

if __name__ == '__main__':
    unittest.main()
