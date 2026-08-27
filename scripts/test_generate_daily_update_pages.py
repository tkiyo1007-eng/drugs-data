import unittest

from generate_daily_update_pages import atom_feed, index_html, page_html, sitemap_xml, status_key


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
        self.assertIn('<script src="../analytics.js"></script>', output)
        self.assertIn('src="https://gc.zgo.at/count.js"', output)
        self.assertIn('data-dsn-share-page', output)
        self.assertIn('data-dsn-event="related-item-open"', output)
        self.assertIn('data-dsn-event="search-cta-open"', output)
        self.assertIn('../guides/how-to-check-drug-supply.html', output)
        self.assertIn("テスト錠&lt;10mg&gt;", output)
        self.assertNotIn("テスト錠<10mg>", output)

    def test_page_falls_back_to_unique_item_hash_and_index_uses_private_analytics(self):
        output = page_html(
            "2026-08-16",
            [{
                "date": "2026-08-16",
                "name": "同名の可能性がある製品",
                "from": "①通常出荷",
                "to": "②限定出荷（その他）",
                "yj": "1234567F5678",
            }],
            set(),
        )
        self.assertIn('../#item=1234567F5678', output)
        listing = index_html({"2026-08-16": [{"to": "①通常出荷"}]})
        self.assertIn('<script src="../analytics.js"></script>', listing)
        self.assertIn('src="https://gc.zgo.at/count.js"', listing)
        self.assertIn('data-dsn-share-page', listing)
        self.assertIn('../guides/how-to-check-drug-supply.html', listing)

    def test_sitemap_contains_index_and_dated_pages(self):
        output = sitemap_xml(["2026-08-15", "2026-08-16"])
        self.assertIn("updates/index.html", output)
        self.assertIn("updates/2026-08-15.html", output)
        self.assertIn("updates/2026-08-16.html", output)
        self.assertIn("<lastmod>2026-08-16</lastmod>", output)

    def test_atom_feed_exposes_dated_updates_and_discovery_links(self):
        output = atom_feed({
            "2026-08-16": [{"to": "①通常出荷"}, {"to": "⑤供給停止"}],
            "2026-08-15": [{"to": "②限定出荷（自社の事情）"}],
        })
        self.assertIn('xmlns="http://www.w3.org/2005/Atom"', output)
        self.assertIn('rel="self" type="application/atom+xml"', output)
        self.assertIn("<author><name>医薬品供給ナビ</name></author>", output)
        self.assertIn("updates/2026-08-16.html", output)
        self.assertIn("2026年8月16日の供給変更（2品目）", output)
        self.assertIn("通常出荷へ1品目、供給停止へ1品目", output)
        self.assertEqual(output.count("<entry>"), 2)


if __name__ == "__main__":
    unittest.main()
