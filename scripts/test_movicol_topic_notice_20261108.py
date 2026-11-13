import json
import unittest
from datetime import date
from pathlib import Path


class MovicolTopicNoticeTests(unittest.TestCase):
    def test_second_edition_scope_and_future_plan_are_visible(self):
        root = Path(__file__).resolve().parent.parent
        topics = json.loads((root / 'industry_topics.json').read_text(encoding='utf-8'))['topics']
        by_slug = {topic['slug']: topic for topic in topics}
        source = 'https://www.eapharma.co.jp/hubfs/medical/news/2026/MVC-H-2-PM-05818.pdf'
        for slug in ('movicol-alternatives-20260930', 'movicol-ld-hd-supply-restriction-20260929'):
            topic = by_slug[slug]
            self.assertEqual(source, topic['source']['url'])
            self.assertGreaterEqual(date.fromisoformat(topic['updated_at']), date(2026, 11, 8))
            html = (root / 'topics' / (slug + '.html')).read_text(encoding='utf-8')
            self.assertIn(source, html)
            self.assertIn('2026年12月', html)
            self.assertIn('2027年6月', html)
            self.assertIn('厚労省', html)
            self.assertIn('同製造所での製造・出荷を一時停止', html)
        plan = by_slug['movicol-alternatives-20260930']['points'][1]
        self.assertIn('100包', plan)
        self.assertIn('予定', plan)
        self.assertIn('小児', plan)
        self.assertIn('変更される可能性', plan)
        supply = by_slug['movicol-ld-hd-supply-restriction-20260929']
        self.assertIn('LD 100包（統一商品コード699059402）', supply['points'][1])
        self.assertIn('HD 100包（統一商品コード699059426）', supply['points'][2])
        self.assertIn('一時出荷停止の予定', supply['points'][2])


if __name__ == '__main__':
    unittest.main()
