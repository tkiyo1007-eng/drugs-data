import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from generate_curated_pages import search_rows


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_curated_pages.py"


class CuratedPageGenerationTests(unittest.TestCase):
    def test_search_normalizes_width_and_orders_more_severe_status_first(self):
        rows = [
            {"商品名": "テスト配合錠１番", "供給状況": "①通常出荷"},
            {"商品名": "テスト配合錠1番", "供給状況": "⑤供給停止"},
        ]

        found = search_rows(rows, "テスト 配合錠1番")

        self.assertEqual(2, len(found))
        self.assertEqual("⑤供給停止", found[0]["供給状況"])

    def test_generator_creates_safe_crawlable_topic_and_product_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            csv_path = site / "drugs.csv"
            fields = [
                "商品名", "一般名", "製造メーカー", "販売メーカー", "供給状況",
                "理由", "代替候補", "更新日", "今回更新", "YJコード",
                "薬効分類", "規格", "薬価", "経過措置期限", "ステータス更新日",
            ]
            row = {
                "商品名": "テスト配合錠１番「例」<特>",
                "一般名": "テスト成分",
                "製造メーカー": "例製薬",
                "販売メーカー": "例販売",
                "供給状況": "⑤供給停止",
                "更新日": "2026/08/16",
                "YJコード": "1234567F1234",
                "規格": "10mg1錠",
            }
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow(row)

            (site / "industry_topics.json").write_text(json.dumps({
                "schema_version": 1,
                "updated_at": "2026-08-17",
                "topics": [{
                    "slug": "test-release-20260817",
                    "date": "2026.08.17",
                    "tag": "供給情報",
                    "tone": "alert",
                    "title": "テスト<script>alert(1)</script>",
                    "lede": "供給情報を安全に表示します。",
                    "points": ["要点 <確認>"],
                    "query": "テスト配合錠1番",
                    "source": {
                        "name": "公式情報",
                        "url": "https://example.test/release?a=1&b=2",
                    },
                }],
            }, ensure_ascii=False), encoding="utf-8")
            (site / "featured_products.json").write_text(json.dumps({
                "schema_version": 1,
                "updated_at": "2026-08-17",
                "products": [{
                    "slug": "test-combination-1",
                    "label": "テスト配合錠１番",
                    "query": "テスト配合錠1番",
                }],
            }, ensure_ascii=False), encoding="utf-8")
            (site / "items").mkdir()
            (site / "items" / "keys.json").write_text(
                json.dumps(["1234567F1234"]), encoding="utf-8")
            (site / "product_lifecycle.json").write_text(json.dumps({
                "products": {
                    "1234567F1234": {"state": "discontinuation_announced"},
                },
            }), encoding="utf-8")

            completed = subprocess.run(
                [sys.executable, str(GENERATOR), "--csv", str(csv_path), "--site", str(site)],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("ニュース1件、注目製品1件", completed.stdout)
            topic = (site / "topics" / "test-release-20260817.html").read_text(encoding="utf-8")
            product = (site / "products" / "test-combination-1.html").read_text(encoding="utf-8")
            topic_index = (site / "topics" / "index.html").read_text(encoding="utf-8")
            product_index = (site / "products" / "index.html").read_text(encoding="utf-8")
            sitemap = (site / "sitemap-curated.xml").read_text(encoding="utf-8")

            self.assertIn('rel="canonical" href="https://tkiyo1007-eng.github.io/drugs-data/topics/test-release-20260817.html"', topic)
            self.assertIn('"@type":"Article"', topic)
            self.assertIn("テスト&lt;script&gt;alert(1)&lt;/script&gt;", topic)
            self.assertNotIn("<script>alert(1)</script>", topic)
            self.assertIn("../items/1234567F1234.html", topic)
            self.assertIn('src="../analytics.js"', topic)
            self.assertIn("https://gc.zgo.at/count.js", topic)

            self.assertIn('"@type":"CollectionPage"', product)
            self.assertIn('"@type":"ItemList"', product)
            self.assertIn("テスト配合錠１番「例」&lt;特&gt;", product)
            self.assertIn("販売中止予定", product)
            self.assertIn("供給停止", product)
            self.assertIn("test-release-20260817.html", topic_index)
            self.assertIn("test-combination-1.html", product_index)
            self.assertIn("topics/test-release-20260817.html", sitemap)
            self.assertIn("products/test-combination-1.html", sitemap)
            self.assertIn("<lastmod>2026-08-17</lastmod>", sitemap)

    def test_checked_in_pages_cover_every_curated_record(self):
        topics = json.loads((ROOT / "industry_topics.json").read_text(encoding="utf-8"))["topics"]
        products = json.loads((ROOT / "featured_products.json").read_text(encoding="utf-8"))["products"]
        topic_slugs = {record["slug"] for record in topics}
        product_slugs = {record["slug"] for record in products}
        topic_files = {path.stem for path in (ROOT / "topics").glob("*.html") if path.name != "index.html"}
        product_files = {path.stem for path in (ROOT / "products").glob("*.html") if path.name != "index.html"}

        self.assertEqual(topic_slugs, topic_files)
        self.assertEqual(product_slugs, product_files)
        sitemap = (ROOT / "sitemap-curated.xml").read_text(encoding="utf-8")
        for kind, slugs in (("topics", topic_slugs), ("products", product_slugs)):
            index = (ROOT / kind / "index.html").read_text(encoding="utf-8")
            for slug in slugs:
                with self.subTest(kind=kind, slug=slug):
                    page = (ROOT / kind / f"{slug}.html").read_text(encoding="utf-8")
                    self.assertIn(f'{slug}.html', index)
                    self.assertIn(f"{kind}/{slug}.html", sitemap)
                    self.assertIn('rel="canonical"', page)
                    self.assertIn('type="application/ld+json"', page)
                    self.assertIn('src="../analytics.js"', page)
                    self.assertIn('../about.html', page)
                    self.assertIn('../privacy.html', page)


if __name__ == "__main__":
    unittest.main()
