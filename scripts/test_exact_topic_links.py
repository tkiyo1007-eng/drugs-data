import json
import tempfile
import unittest
from pathlib import Path
from generate_item_pages import exact_target_topic_index, related_topics_html, item_page_lastmod


class ExactTopicLinkTests(unittest.TestCase):
    def test_generated_item_pages_link_to_exact_target_topics(self):
        root = Path(__file__).resolve().parent.parent
        topic_index = exact_target_topic_index(root)
        generated = set(json.loads((root / 'items' / 'keys.json').read_text(encoding='utf-8')))
        for yj, topics in topic_index.items():
            if yj not in generated:
                continue
            page = (root / 'items' / f'{yj}.html').read_text(encoding='utf-8')
            for topic in topics:
                with self.subTest(yj=yj, topic=topic['slug']):
                    self.assertIn(f'../topics/{topic["slug"]}.html', page)

    def test_exact_yj_with_existing_article_only_and_escaped_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp)
            (site / 'topics').mkdir()
            (site / 'topics' / 'iwaki-article.html').write_text('article', encoding='utf-8')
            topics = {'topics': [
                {'slug': 'iwaki-article', 'title': '<script>文書</script>', 'date': '2026.10.20',
                 'target_queries': ['2655712N1039', '2655712M1033', 'ルリコナゾール', '2655712N1039']},
                {'slug': 'missing', 'title': '未生成', 'target_queries': ['2655712N1039']},
                {'slug': '../bad', 'title': '不正', 'target_queries': ['2655712N1039']},
                {'slug': 'iwaki-article', 'title': '関連候補', 'queries': ['2655712N1039']},
            ]}
            (site / 'industry_topics.json').write_text(json.dumps(topics, ensure_ascii=False), encoding='utf-8')
            idx = exact_target_topic_index(site)
            self.assertEqual(set(idx), {'2655712N1039', '2655712M1033'})
            self.assertEqual(len(idx['2655712N1039']), 1)
            rendered = related_topics_html(idx['2655712N1039'])
            self.assertIn('../topics/iwaki-article.html', rendered)
            self.assertIn('&lt;script&gt;文書&lt;/script&gt;', rendered)
            self.assertIn('2026-10-20', rendered)
            self.assertIn('記事は掲載時点の情報', rendered)
            self.assertNotIn('ルリコン', rendered)
            self.assertEqual(related_topics_html([]), '')
            self.assertEqual(item_page_lastmod({}, related_topics=idx['2655712N1039']), '2026-11-04')
            (site / 'industry_topics.json').write_text('{', encoding='utf-8')
            self.assertEqual(exact_target_topic_index(site), {})


if __name__ == '__main__':
    unittest.main()
