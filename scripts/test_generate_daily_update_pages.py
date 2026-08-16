import unittest

from generate_daily_update_pages import page_html, sitemap_xml, status_key


class DailyUpdatePageTests(unittest.TestCase):
    def test_status_mapping_matches_web_categories(self):
        self.assertEqual(status_key("①通常出荷"), "ok")
        self.assertEqual(status_key("②限定出荷（自社の事情）"), "limited")
        self.assertEqual(status_key("⑤供給停止"), "stopped")
        self.assertEqual(status_key("販売中止"), "ended")

    def test_page_has_canonical_article_metadata_and_safe_item_link(self):
        output = page_html(
            "2026-08-16",
            [{
                "date": "2026-08-16",
                "name": "テスト錠<10mg>",
                "from": "②限定出荷（その他）",
                "to": "①通常出荷",
                "yj": "1234567F1234",
            }],
            {"1234567F1234"},
        )
        self.assertEqual(output.count('rel="canonical"'), 1)
        self.assertIn('content="index,follow,max-image-preview:large"', output)
        self.assertIn('type="application/ld+json"', output)
        self.assertIn('../items/1234567F1234.html', output)
        self.assertIn("テスト錠&lt;10mg&gt;", output)
        self.assertNotIn("テスト錠<10mg>", output)

    def test_sitemap_contains_index_and_dated_pages(self):
        output = sitemap_xml(["2026-08-15", "2026-08-16"])
        self.assertIn("updates/index.html", output)
        self.assertIn("updates/2026-08-15.html", output)
        self.assertIn("updates/2026-08-16.html", output)
        self.assertIn("<lastmod>2026-08-16</lastmod>", output)


if __name__ == "__main__":
    unittest.main()
