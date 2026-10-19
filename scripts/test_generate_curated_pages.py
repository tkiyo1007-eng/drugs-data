import csv
import json
import re
import subprocess
import sys
import tempfile
import unittest
from generate_curated_pages import product_rows_html
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote


class ChangedManufacturerSourceTests(unittest.TestCase):
    def test_known_changed_source_preserves_official_status_but_hides_future_assertion(self):
        row = {'商品名': 'fixture', 'YJコード': '123456789012', '供給状況': '①通常出荷', '製造メーカー': 'maker'}
        output = product_rows_html([row], set(), {'123456789012': {'state': 'discontinuation_announced', 'source_changed': True}})
        self.assertIn('通常出荷', output)
        self.assertIn('メーカー原典更新・再確認待ち', output)
        self.assertNotIn('>販売中止予定<', output)
    def test_unmodified_verified_lifecycle_keeps_its_badge(self):
        row = {'商品名': 'fixture', 'YJコード': '123456789012', '供給状況': '①通常出荷'}
        output = product_rows_html([row], set(), {'123456789012': {'state': 'discontinuation_announced'}})
        self.assertIn('>販売中止予定<', output)

from generate_curated_pages import (
    DISCONTINUATION_GUIDE_PUBLISHED_AT,
    DISCONTINUATION_GUIDE_SLUG,
    DISCONTINUATION_GUIDE_UPDATED_AT,
    GUIDE_SLUG,
    GUIDE_UPDATED_AT,
    WEB_HIDDEN_FEATURED_SLUGS,
    discontinuation_guide_page,
    guide_page,
    ingredient_page,
    ingredient_index_page,
    list_page,
    product_intent_html,
    product_page,
    product_seo_metadata,
    search_rows,
    topic_related_rows,
)


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "generate_curated_pages.py"


class PageLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = set()
        self.ids = []
        self.element_tags = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.append(attributes["id"])
            self.element_tags[attributes["id"]] = tag
        if tag == "a":
            self.hrefs.add(attributes.get("href"))


class IngredientSourceDateTests(unittest.TestCase):
    group = {"slug": "1234567", "name": "日付検証成分", "rows": [
        {"商品名": "日付検証錠", "一般名": "日付検証成分", "供給状況": "限定出荷",
         "更新日": "2024/03/11", "YJコード": "1234567F1234", "製造メーカー": "検証製薬"}]}

    def block(self, output):
        return re.search(r'<p class="dataset-context">(.*?)</p>', output, re.S).group(1)

    def test_ingredient_dates_are_generated_metadata_not_row_or_lastmod_dates(self):
        metadata = {"note": "2026年10月14日厚労省データ反映", "mhlw_excel_date": "2026-10-08"}
        old, old_lastmod = ingredient_page(self.group, set(), {}, {})
        page, lastmod = ingredient_page(self.group, set(), {}, {}, "2026-10-14", metadata)
        index = ingredient_index_page({"1234567": self.group}, "2024-03-11", "2026-10-14", metadata)
        for output in (page, index):
            block = self.block(output)
            self.assertIn('class="mhlw-excel-date" aria-live="polite">2026-10-08</span>', block)
            self.assertIn('class="dataset-date" aria-live="polite">2026-10-14</span>', block)
            self.assertIn("サイト取込日", block)
            self.assertIn("HTML生成時の確認情報です", block)
            self.assertNotIn("2024-03-11", block)
            self.assertIn("品目行の最新更新日：2024-03-11", output)
        self.assertEqual(old_lastmod, lastmod)
        self.assertEqual(re.findall(r'"dateModified":"([^"]+)"', old),
                         re.findall(r'"dateModified":"([^"]+)"', page))

    def test_ingredient_unknown_source_does_not_infer_from_any_other_date(self):
        for metadata in (None, {"note": "2026年10月14日厚労省データ反映"},
                         {"note": "2026年10月14日厚労省データ反映", "mhlw_excel_date": "2026-02-30"},
                         {"note": "2026年10月14日厚労省データ反映", "mhlw_excel_date": "2026-10-15"},
                         {"note": "2026年10月08日厚労省データ反映", "mhlw_excel_date": "2026-10-08"}):
            with self.subTest(metadata=metadata):
                page, _ = ingredient_page(self.group, set(), {}, {}, "2026-10-14", metadata)
                index = ingredient_index_page({"1234567": self.group}, "2024-03-11", "2026-10-14", metadata)
                for output in (page, index):
                    self.assertIn('class="mhlw-excel-date" aria-live="polite">確認できません</span>', self.block(output))
                    self.assertIn('class="dataset-date" aria-live="polite">2026-10-14</span>', self.block(output))
        old, _ = ingredient_page(self.group, set(), {}, {})
        self.assertEqual(2, self.block(old).count("確認できません"))


class CuratedPageGenerationTests(unittest.TestCase):
    def test_guide_has_static_purpose_links_and_published_status_boundaries(self):
        page = guide_page()
        links = PageLinks()
        links.feed(page)
        for href in (
            "../items/limited.html", "../items/stopped.html",
            "../items/recent-restrictions.html", "../ingredients/index.html", "../#demo",
            "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html",
            "https://iyakuhin-kyokyu.mhlw.go.jp/public/supply-status-list",
        ):
            with self.subTest(href=href):
                self.assertIn(href, links.hrefs)
        self.assertLess(page.index('id="guidePathsTitle"'), page.index("1. 現在の供給区分"))
        self.assertIn('<nav class="crumb" aria-label="パンくず">', page)
        self.assertIn("出荷調整とは", page)
        self.assertIn("薬ごとの「出荷対応」の区分で確認できます", page)
        self.assertIn("限定出荷と供給停止の違い", page)
        self.assertIn('id="shipment-volume"', page)
        self.assertIn("「C．出荷停止」は「出荷量」の区分", page)
        self.assertIn("「⑤供給停止」は「出荷対応」の区分", page)
        self.assertIn("出荷量の表示だけで現在の出荷対応を置き換えません", page)
        self.assertIn("全ての受注には対応できない", page)
        self.assertIn("供給を停止している状態", page)
        self.assertIn("記載のない再開時期を推測で補いません", page)
        self.assertIn("実際の流通在庫や施設ごとの入手可否を示すものではありません", page)
        self.assertIn("代替薬の推薦ではありません", page)
        self.assertIn("PMDAと供給情報の役割は異なる", page)
        self.assertIn('rel="canonical" href="https://kyokyu-navi.jp/guides/how-to-check-drug-supply.html"', page)
        self.assertIn(f"{DISCONTINUATION_GUIDE_SLUG}.html", links.hrefs)

    def test_discontinuation_guide_separates_statuses_and_links_to_their_sources(self):
        page = discontinuation_guide_page()
        self.assertIn('href="../items/supplemental.html#price-info"', page)
        links = PageLinks()
        links.feed(page)
        for href in (
            "../items/supplemental.html", "../items/limited.html", "../#demo", "../",
            "../about.html", f"{GUIDE_SLUG}.html",
            "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html",
            "https://www.mhlw.go.jp/topics/2026/04/tp20260401-01.html",
            "https://iyakuhin-kyokyu.mhlw.go.jp/public/supply-status-list",
        ):
            with self.subTest(href=href):
                self.assertIn(href, links.hrefs)
        terms = re.findall(r'<th scope="row">(.*?)</th>', page)
        self.assertEqual([
            "製造中止", "製造販売中止", "販売中止", "一部包装中止",
            "供給停止", "薬価削除予定", "経過措置期限",
        ], terms)
        self.assertIn("供給停止を製造中止に、薬価削除予定を薬価削除済みに置き換えません", page)
        self.assertIn("終了日や製造終了実績を推測で補いません", page)
        self.assertIn("この表現だけで承認整理や薬価削除済みまで判断しません", page)
        self.assertIn("製品の使用期限、メーカーの最終出荷時期、流通在庫の消尽時期とは別", page)
        self.assertIn("現在の供給データに品目がないことだけでも", page)
        self.assertIn("過去の案内例は、現在の供給状況の根拠として用いません", page)
        self.assertIn("代替薬の推薦ではありません", page)
        self.assertNotIn("令和8年10月1日適用", page)
        self.assertIn(">薬価基準収載品目リストの凡例</a>", page)
        self.assertIn("リンク先の薬価資料は更新されます", page)
        self.assertIn("ページに記載された適用日と、対象品目の経過措置による使用期限をそれぞれ確認", page)
        self.assertEqual(1, page.count("<h1>"))
        canonical = f"https://kyokyu-navi.jp/guides/{DISCONTINUATION_GUIDE_SLUG}.html"
        self.assertIn(f'rel="canonical" href="{canonical}"', page)
        self.assertIn('<nav class="crumb" aria-label="パンくず">', page)
        structured = json.loads(re.search(
            r'<script type="application/ld\+json">(.*?)</script>', page, re.S,
        ).group(1))
        article = next(entry for entry in structured["@graph"] if entry["@type"] == "Article")
        breadcrumb = next(entry for entry in structured["@graph"] if entry["@type"] == "BreadcrumbList")
        self.assertEqual(canonical, article["mainEntityOfPage"])
        self.assertEqual(DISCONTINUATION_GUIDE_PUBLISHED_AT, article["datePublished"])
        self.assertEqual(DISCONTINUATION_GUIDE_UPDATED_AT, article["dateModified"])
        self.assertEqual(canonical, breadcrumb["itemListElement"][-1]["item"])
        self.assertIn(f"編集確認日：{DISCONTINUATION_GUIDE_UPDATED_AT}", page)

    def test_guide_fragments_reach_distinct_static_information(self):
        supply_page = guide_page()
        supply_links = PageLinks()
        supply_links.feed(supply_page)
        for fragment, tag, heading in (
            ("supply-status", "section", "出荷調整とは"),
            ("reasons", "section", "「なぜ」は理由欄とメーカー原文を分けて確認"),
            ("resumption", "h3", "いつまで続くかを確認するには"),
        ):
            with self.subTest(fragment=fragment):
                self.assertEqual(1, supply_links.ids.count(fragment))
                self.assertEqual(tag, supply_links.element_tags[fragment])
                anchored = re.search(
                    rf'<{tag}[^>]*id="{fragment}"[^>]*>(.*?)</{tag}>',
                    supply_page, re.S,
                ).group(1)
                self.assertIn(heading, anchored)

        ending_page = discontinuation_guide_page()
        ending_links = PageLinks()
        ending_links.feed(ending_page)
        expected_terms = {
            "manufacturing": "製造中止",
            "manufacturing-sales": "製造販売中止",
            "sales": "販売中止",
            "packaging": "一部包装中止",
            "stopped": "供給停止",
            "delisting": "薬価削除予定",
            "transition": "経過措置期限",
        }
        for fragment, term in expected_terms.items():
            with self.subTest(fragment=fragment):
                self.assertEqual(1, ending_links.ids.count(fragment))
                self.assertEqual("tr", ending_links.element_tags[fragment])
                anchored = re.search(
                    rf'<tr id="{fragment}">(.*?)</tr>', ending_page, re.S,
                ).group(1)
                self.assertIn(f'<th scope="row">{term}</th>', anchored)
        self.assertIn("#manufacturing", ending_links.hrefs)
        self.assertLess(ending_page.index('href="#manufacturing"'),
                        ending_page.index('id="manufacturing"'))
        for href in ending_links.hrefs:
            if href and href.startswith("#"):
                self.assertIn(href[1:], ending_links.ids)

    def test_guide_revision_date_is_independent_of_news_and_product_dates(self):
        namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        pages = []
        discontinuation_pages = []
        with tempfile.TemporaryDirectory() as directory:
            site = Path(directory)
            csv_path = site / "drugs.csv"
            csv_path.write_text("商品名,供給状況\n試験薬,①通常出荷\n", encoding="utf-8")
            for source_date in ("2026-09-30", "2026-10-12"):
                for filename, field in (("industry_topics.json", "topics"), ("featured_products.json", "products")):
                    (site / filename).write_text(json.dumps({
                        "updated_at": source_date, field: [],
                    }), encoding="utf-8")
                subprocess.run(
                    [sys.executable, "-B", str(GENERATOR), "--csv", str(csv_path), "--site", str(site), "--month", "10"],
                    check=True, capture_output=True, text=True,
                )
                page = (site / "guides" / f"{GUIDE_SLUG}.html").read_text(encoding="utf-8")
                pages.append(page)
                structured = json.loads(re.search(
                    r'<script type="application/ld\+json">(.*?)</script>', page, re.S,
                ).group(1))
                article = next(entry for entry in structured["@graph"] if entry["@type"] == "Article")
                self.assertEqual("2026-08-28", article["datePublished"])
                self.assertEqual(GUIDE_UPDATED_AT, article["dateModified"])
                self.assertIn(f"最終更新：{GUIDE_UPDATED_AT}", page)
                sitemap = ET.fromstring((site / "sitemap-curated.xml").read_text(encoding="utf-8"))
                dates = {entry.findtext("s:loc", namespaces=namespace):
                         entry.findtext("s:lastmod", namespaces=namespace)
                         for entry in sitemap.findall("s:url", namespace)}
                self.assertEqual(GUIDE_UPDATED_AT, dates[f"https://kyokyu-navi.jp/guides/{GUIDE_SLUG}.html"])
                self.assertEqual("2026-09-26", dates["https://kyokyu-navi.jp/guides/monitor-adopted-drugs.html"])
                discontinuation = (site / "guides" / f"{DISCONTINUATION_GUIDE_SLUG}.html").read_text(encoding="utf-8")
                discontinuation_pages.append(discontinuation)
                self.assertEqual(DISCONTINUATION_GUIDE_UPDATED_AT,
                                 dates[f"https://kyokyu-navi.jp/guides/{DISCONTINUATION_GUIDE_SLUG}.html"])
        self.assertEqual(pages[0], pages[1], "ニュース・製品情報の日付だけではガイドを改訂扱いにしない")
        self.assertEqual(discontinuation_pages[0], discontinuation_pages[1],
                         "販売中止ガイドの確認日もニュース・製品の更新日に置き換えない")

    def test_web_list_hides_requested_products_without_removing_detail_pages(self):
        document = json.loads((ROOT / "featured_products.json").read_text())
        records = document["products"]
        before = json.dumps(records)
        page = list_page("products", records, "2026-09-12")
        for record in records:
            link = f'href="{record["slug"]}.html"'
            if record["slug"] in WEB_HIDDEN_FEATURED_SLUGS:
                self.assertNotIn(link, page)
                detail, _ = product_page(record, [], set(), {})
                self.assertIn(f'products/{record["slug"]}.html', detail)
            else:
                self.assertIn(link, page)
        self.assertEqual(before, json.dumps(records))
        self.assertEqual(9, len(WEB_HIDDEN_FEATURED_SLUGS))
        self.assertEqual(1, page.count('テラムロ配合錠'))
        self.assertIn('href="../#q=' + quote('テラムロ', safe='') + '"', page)
        self.assertNotIn('テラムロ配合錠', list_page('topics', [], '2026-09-12'))

    def test_product_entry_reuses_encoded_search_and_official_links_before_details(self):
        product = {"slug": "entry-test", "label": "確認製品", "query": '製品A & "テスト"'}
        page, _ = product_page(product, [], set(), {})
        entry = page.split('<nav class="product-entry"', 1)[1].split('</nav>', 1)[0]
        self.assertIn('href="../#q=' + quote(product['query'], safe='') + '"', entry)
        self.assertIn('data-dsn-event="search-cta-open"', entry)
        self.assertIn('href="https://iyakuhin-kyokyu.mhlw.go.jp/public/supply-status-list" target="_blank" rel="noopener"', entry)
        self.assertIn('href="../items/limited.html">限定出荷の品目一覧</a>', entry)
        self.assertNotIn('関連品目', entry)
        self.assertLess(page.index('<nav class="product-entry"'), page.index('<h2>該当品目</h2>'))
        self.assertIn('rel="canonical" href="https://kyokyu-navi.jp/products/entry-test.html"', page)
        self.assertIn('<nav class="crumb" aria-label="パンくず">', page)

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
                    "notes": ["変更前に <確認>"],
                    "sources": [{"name": "電子添文 <原文>", "url": "https://example.test/label?a=1&b=2"}],
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

            self.assertIn("ニュース1件、注目製品1件、恒久ガイド3件", completed.stdout)
            topic = (site / "topics" / "test-release-20260817.html").read_text(encoding="utf-8")
            product = (site / "products" / "test-combination-1.html").read_text(encoding="utf-8")
            topic_index = (site / "topics" / "index.html").read_text(encoding="utf-8")
            product_index = (site / "products" / "index.html").read_text(encoding="utf-8")
            guide = (site / "guides" / f"{GUIDE_SLUG}.html").read_text(encoding="utf-8")
            sitemap = (site / "sitemap-curated.xml").read_text(encoding="utf-8")

            self.assertIn('rel="canonical" href="https://kyokyu-navi.jp/topics/test-release-20260817.html"', topic)
            self.assertIn('"@type":"Article"', topic)
            self.assertIn("テスト&lt;script&gt;alert(1)&lt;/script&gt;", topic)
            self.assertNotIn("<script>alert(1)</script>", topic)
            self.assertIn("変更前に &lt;確認&gt;", topic)
            self.assertIn("電子添文 &lt;原文&gt;", topic)
            self.assertIn('href="https://example.test/label?a=1&amp;b=2" target="_blank" rel="noopener"', topic)
            self.assertIn('<summary>出典を確認</summary>', topic)
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
            self.assertIn(f"guides/{DISCONTINUATION_GUIDE_SLUG}.html", sitemap)
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
        self.assertIn('href="../topics/lulicon-alternatives-20260911.html"', output)
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
                f'"url":"https://kyokyu-navi.jp/products/caduet-{number}.html"',
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
                    if kind == "products" and slug in WEB_HIDDEN_FEATURED_SLUGS:
                        self.assertNotIn(f'{slug}.html', index)
                    else:
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
