import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from generate_curated_pages import (
    GUIDE_SLUG,
    product_intent_html,
    product_page,
    product_seo_metadata,
    search_rows,
    topic_related_rows,
)


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

    def test_topic_can_group_multiple_product_queries_without_duplicates(self):
        rows = [
            {"商品名": "製品A錠10mg", "供給状況": "①通常出荷", "YJコード": "1111111F1111"},
            {"商品名": "製品B錠20mg", "供給状況": "②限定出荷", "YJコード": "2222222F2222"},
        ]

        found = topic_related_rows(rows, {"queries": ["製品A", "製品B", "製品A錠"]})

        self.assertEqual(["製品B錠20mg", "製品A錠10mg"], [row["商品名"] for row in found])

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

            self.assertIn("ニュース1件、注目製品1件、恒久ガイド1件", completed.stdout)
            topic = (site / "topics" / "test-release-20260817.html").read_text(encoding="utf-8")
            product = (site / "products" / "test-combination-1.html").read_text(encoding="utf-8")
            topic_index = (site / "topics" / "index.html").read_text(encoding="utf-8")
            product_index = (site / "products" / "index.html").read_text(encoding="utf-8")
            guide = (site / "guides" / f"{GUIDE_SLUG}.html").read_text(encoding="utf-8")
            sitemap = (site / "sitemap-curated.xml").read_text(encoding="utf-8")

            self.assertIn('rel="canonical" href="https://tkiyo1007-eng.github.io/drugs-data/topics/test-release-20260817.html"', topic)
            self.assertIn('"@type":"Article"', topic)
            self.assertIn("テスト&lt;script&gt;alert(1)&lt;/script&gt;", topic)
            self.assertNotIn("<script>alert(1)</script>", topic)
            self.assertIn("../items/1234567F1234.html", topic)
            self.assertIn('src="../analytics.js"', topic)
            self.assertIn("https://gc.zgo.at/count.js", topic)
            self.assertIn('data-dsn-share-page', topic)
            self.assertIn('data-dsn-event="official-source-open"', topic)
            self.assertIn('data-dsn-event="topic-to-search"', topic)

            self.assertIn('"@type":"CollectionPage"', product)
            self.assertIn('"@type":"ItemList"', product)
            self.assertIn("テスト配合錠１番「例」&lt;特&gt;", product)
            self.assertIn("販売中止予定", product)
            self.assertIn("供給停止", product)
            self.assertIn('data-dsn-share-page', product)
            self.assertIn('data-dsn-event="related-item-open"', product)
            self.assertIn('data-dsn-event="search-cta-open"', product)
            self.assertIn("test-release-20260817.html", topic_index)
            self.assertIn("test-combination-1.html", product_index)
            self.assertIn('data-dsn-share-page', topic_index)
            self.assertIn('data-dsn-share-page', product_index)
            self.assertIn("代替薬の推薦ではありません", guide)
            self.assertIn("現在の供給区分は厚生労働省", guide)
            self.assertIn("PMDAと供給情報の役割は異なる", guide)
            self.assertIn("PMDAの医薬品回収情報を確認", guide)
            self.assertIn("https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/recall-info/0002.html", guide)
            self.assertIn('data-dsn-share-page', guide)
            self.assertGreaterEqual(guide.count('data-dsn-event="official-source-open"'), 3)
            self.assertIn("topics/test-release-20260817.html", sitemap)
            self.assertIn("products/test-combination-1.html", sitemap)
            self.assertIn(f"guides/{GUIDE_SLUG}.html", sitemap)
            self.assertIn("<lastmod>2026-08-28</lastmod>", sitemap)

    def test_search_intent_copy_uses_published_fields_without_inferring_a_cause_or_substitute(self):
        product = {
            "slug": "lulicon-cream",
            "label": "ルリコンクリーム1%",
            "query": "ルリコン クリーム",
        }
        rows = [{
            "商品名": "ルリコンクリーム1%",
            "供給状況": "③限定出荷（他社品の影響）",
            "理由": "１．需要増",
            "代替候補": "解除/解消見込み: ウ. 未定 / 出荷量状況: B．出荷量減少",
            "更新日": "2026/02/10",
            "YJコード": "2655712N1020",
        }]

        output = product_intent_html(product, rows, {"2655712N1020"})
        title, description = product_seo_metadata(product, rows, "供給状況")

        self.assertIn("厚労省公表の供給区分：③限定出荷（他社品の影響）", output)
        self.assertIn("公表上の理由：１．需要増", output)
        self.assertIn("解除・解消見込み：ウ. 未定", output)
        self.assertIn("この品目行の更新日：2026-02-10", output)
        self.assertIn("表示されていない原因を推測で補いません", output)
        self.assertIn("代替薬の推薦ではありません", output)
        self.assertIn("同成分・同剤形", output)
        self.assertIn('data-dsn-event="official-source-open"', output)
        self.assertIn("限定出荷", title)
        self.assertLessEqual(len(title), 70)
        self.assertIn("代替適否や実在庫は示しません", description)
        self.assertIn("解除・解消見込み「ウ. 未定」", description)

    def test_lulicon_recovery_does_not_leave_a_limited_shipment_claim(self):
        product = {
            "slug": "lulicon-cream",
            "label": "ルリコンクリーム1%",
            "query": "ルリコンクリーム",
        }
        rows = [{
            "商品名": "ルリコンクリーム1%",
            "供給状況": "①通常出荷",
            "理由": "７．－",
            "更新日": "2026/09/01",
            "YJコード": "2655712N1020",
        }]

        output = product_intent_html(product, rows, {"2655712N1020"})
        title, _ = product_seo_metadata(product, rows, "供給状況")

        self.assertIn("厚労省公表の供給区分：①通常出荷", output)
        self.assertIn("公表上の理由：記載なし", output)
        self.assertNotIn("はなぜ出荷調整（限定出荷）", output)
        self.assertIn("現在の供給状況と公表理由", title)
        self.assertNotIn("限定出荷", title)

    def test_caduet_aggregate_metadata_and_intent_compare_all_four_numbers(self):
        product = {
            "slug": "caduet",
            "label": "カデュエット配合錠",
            "query": "カデュエット配合錠",
        }
        rows = [{
            "商品名": f"カデュエット配合錠{number}番",
            "供給状況": "①通常出荷",
            "理由": "７．－",
            "更新日": "2023/04/28",
            "YJコード": f"2190101F100{number}",
        } for number in range(1, 5)]

        output = product_intent_html(product, rows, {row["YJコード"] for row in rows})
        title, description = product_seo_metadata(product, rows, "メーカー別供給状況")
        page, _ = product_page(product, rows, {row["YJコード"] for row in rows}, {})

        self.assertEqual(4, output.count("厚労省公表の供給区分："))
        self.assertIn("1〜4番を規格別に確認", output)
        self.assertIn("1〜4番の供給状況", title)
        self.assertIn("対象品目ごとに確認", description)
        self.assertLessEqual(len(title), 70)
        self.assertIn("<h1>カデュエット配合錠の規格別供給状況</h1>", page)
        self.assertNotIn("カデュエット配合錠のメーカー別供給状況", page)
        self.assertIn("1〜4番の4品目を、規格ごとの現在の供給区分と更新日", page)
        self.assertNotIn("メーカーごとにまとめています", page)
        for number in range(1, 5):
            self.assertIn(
                f'href="caduet-{number}.html" data-dsn-event="related-item-open"',
                page,
            )
            self.assertIn(
                f'"url":"https://tkiyo1007-eng.github.io/drugs-data/products/caduet-{number}.html"',
                page,
            )

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

        guide = ROOT / "guides" / f"{GUIDE_SLUG}.html"
        self.assertTrue(guide.is_file())
        guide_html = guide.read_text(encoding="utf-8")
        self.assertIn(f"guides/{GUIDE_SLUG}.html", sitemap)
        self.assertIn('rel="canonical"', guide_html)
        self.assertIn('data-dsn-share-page', guide_html)

    def test_checked_in_high_demand_products_have_safe_intent_specific_copy(self):
        expected = {
            "lulicon-cream": [
                "出荷調整情報を確認する方へ",
                "公表上の理由",
                "代替薬の推薦ではありません",
            ],
            "zictor-tape-75mg": [
                "代替を検討する前に",
                "公表上の理由",
                "同成分・同剤形",
            ],
            "caduet": [
                "1〜4番を規格別に確認",
                "1〜4番で成分量が異なります",
            ],
            "caduet-1": [
                "出荷調整情報を確認",
                "1〜4番の規格別比較を見る",
            ],
        }
        for slug, phrases in expected.items():
            page = (ROOT / "products" / f"{slug}.html").read_text(encoding="utf-8")
            with self.subTest(slug=slug):
                for phrase in phrases:
                    self.assertIn(phrase, page)
                self.assertIn('data-dsn-share-page', page)
                self.assertIn('data-dsn-event="official-source-open"', page)


if __name__ == "__main__":
    unittest.main()
