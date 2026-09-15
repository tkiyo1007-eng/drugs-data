"""2026-09-15に原典確認した案内の対象・包装・日付精度を保護する。"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    'ドプスＯＤ錠１００ｍｇ': ('package_discontinued', '2026年11月'),
    'ドプスＯＤ錠２００ｍｇ': ('discontinued', '2027年3月'),
    'タガメット注射液２００ｍｇ': ('discontinued', '2028年2月'),
    'ルーラン錠１６ｍｇ': ('discontinued', '2027年7月'),
    'ミリプラ動注用７０ｍｇ': ('discontinued', '2029年3月'),
    'ミリプラ用懸濁用液４ｍＬ': ('discontinued', '2029年3月'),
    'モメタゾンフランカルボン酸エステルローション０．１％「イワキ」': ('stopped', '未定'),
    'イワコールラブ消毒液０．２％': ('discontinued', '2026年10月'),
}


class VerifiedContentTests(unittest.TestCase):
    def test_verified_manual_notices_keep_date_precision_and_history(self):
        manual = json.loads((ROOT / 'manual_announcements.json').read_text())
        history = json.loads((ROOT / 'maker_announcement_events.json').read_text())
        summaries = json.loads((ROOT / 'announcement_summaries.json').read_text())
        for name, (kind, timing) in TARGETS.items():
            with self.subTest(name=name):
                item = manual[name]
                self.assertEqual(item['event_type'], kind)
                self.assertEqual(item['announced_at'], '2026-09')
                self.assertTrue(item['url'].startswith((
                    'https://sumitomo-pharma.jp/',
                    'https://www.iwakiseiyaku.co.jp/')))
                self.assertTrue(any(e['url'] == item['url'] for e in history[name]))
                self.assertIn(timing, ''.join(summaries[name]['lines']))

    def test_packaging_and_formulation_boundaries_are_explicit(self):
        data = json.loads((ROOT / 'announcement_summaries.json').read_text())
        dops = ''.join(data['ドプスＯＤ錠１００ｍｇ']['lines'])
        self.assertIn('バラ500錠', dops)
        self.assertIn('PTP100錠は販売継続', dops)
        tagamet = ''.join(data['タガメット注射液２００ｍｇ']['lines'])
        self.assertIn('2027年2月', tagamet)
        self.assertIn('2028年2月', tagamet)
        lotion = ''.join(data['モメタゾンフランカルボン酸エステルローション０．１％「イワキ」']['lines'])
        self.assertIn('10g×10', lotion)
        self.assertIn('クリーム・軟膏へ一律に適用するものではありません', lotion)


if __name__ == '__main__':
    unittest.main()
