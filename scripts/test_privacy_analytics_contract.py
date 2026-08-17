import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PrivacyAnalyticsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analytics = (ROOT / "analytics.js").read_text(encoding="utf-8")
        cls.privacy = (ROOT / "privacy.html").read_text(encoding="utf-8")
        cls.about = (ROOT / "about.html").read_text(encoding="utf-8")

    def test_analytics_collapses_sensitive_page_urls_to_page_kinds(self):
        expected_paths = [
            "/drugs-data/items/_item",
            "/drugs-data/updates/_daily",
            "/drugs-data/topics/_topic",
            "/drugs-data/products/_product",
        ]
        for path in expected_paths:
            with self.subTest(path=path):
                self.assertIn(path, self.analytics)
        self.assertIn("new URL(document.referrer).origin", self.analytics)
        self.assertIn("no_events: true", self.analytics)
        self.assertIn("no_onload: dnt", self.analytics)
        self.assertIn('get("src") === "share"', self.analytics)

    def test_analytics_uses_only_fixed_allowlisted_events(self):
        match = re.search(r"const allowed = new Set\(\[(.*?)\]\);", self.analytics, re.DOTALL)
        self.assertIsNotNone(match)
        events = re.findall(r'"([a-z0-9-]+)"', match.group(1))
        self.assertGreaterEqual(len(events), 10)
        self.assertEqual(len(events), len(set(events)))
        self.assertRegex(self.analytics, r'count\(\{path:"event:"\+name, title:name, event:true\}\)')
        self.assertNotIn("localStorage", self.analytics)
        self.assertNotIn("sessionStorage", self.analytics)
        self.assertNotIn("document.cookie", self.analytics)
        self.assertNotRegex(self.analytics, r'get\(["\'](?:q|query|yj|drug|item|filename)["\']\)')

    def test_privacy_discloses_local_processing_and_measurement_boundaries(self):
        required = [
            "ブラウザのlocalStorage",
            "CSV原本、ファイル名、CSV内容を運営者のサーバーやアクセス解析へ送信しません",
            "Service Worker",
            "GoatCounter",
            "医薬品名、検索語、YJコード、CSV内容、ファイル名、監視リストの内容",
            "Do Not Track",
            "Google Fonts",
            "サイト横断追跡は行いません",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.privacy)
        self.assertIn('<script src="analytics.js"></script>', self.privacy)
        self.assertIn('src="https://gc.zgo.at/count.js"', self.privacy)

    def test_about_page_is_pseudonymous_and_explains_editorial_process(self):
        required = [
            "表示名：KT",
            "個人開発サービス",
            "利用者の職種や所属は限定していません",
            "厚生労働省、製薬企業、医薬品卸その他の団体とは提携していません",
            "販売中止予定",
            "AI要約",
            "話題のニュースの編集方針",
            "訂正方針",
            "必ず原文をご確認ください",
        ]
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, self.about)
        self.assertIn('rel="canonical"', self.about)
        self.assertIn('"@type":"AboutPage"', self.about)
        self.assertIn('<script src="analytics.js"></script>', self.about)


if __name__ == "__main__":
    unittest.main()
