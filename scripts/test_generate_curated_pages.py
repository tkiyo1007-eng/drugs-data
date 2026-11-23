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
    STRENGTH_HUBS,
    CADUET_STRENGTH_SLUGS,
    discontinuation_guide_page,
    guide_page,
    ingredient_page,
    ingredient_index_page,
    list_page,
    product_intent_html,
    product_package_snapshot,
    product_page,
    product_seo_metadata,
    search_rows,
    strength_hub_page,
    topic_page,
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
    def test_topic_renders_verified_publisher_pdfs_only_on_the_matching_article(self):
        doc = json.loads((ROOT / "industry_topics.json").read_text(encoding="utf-8"))
        topic = next(item for item in doc["topics"] if item["slug"] == "rakool-packaged-supply-20261118")
        sources = {source["url"] for source in topic["publisher_http_sources"]}
        unexpected = "http://www.rakool.co.jp/other.pdf"
        topic["publisher_http_sources"].append({"name": "別のPDF", "url": unexpected})

        links = PageLinks()
        links.feed(topic_page(topic, [], set(), {}, doc["updated_at"]))
        self.assertTrue(sources <= links.hrefs)
        self.assertNotIn(unexpected, links.hrefs)

        other_links = PageLinks()
        other_links.feed(topic_page({**topic, "slug": "other-topic"}, [], set(), {}, doc["updated_at"]))
        self.assertTrue(sources.isdisjoint(other_links.hrefs))

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
        self.assertLess(page.index('id="guidePathsTitle"'), page.index('id="supply-status"'))
        self.assertIn("原Excelの基準日・品目行の更新日・メーカー案内の日付を分けて確認", page)
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
        self.assertIn('id="package-check"', page)
        self.assertIn("情報のない包装は未確認", page)
        self.assertIn("予定を実施済みと決めつけません", page)
        self.assertIn("現在の在庫を保証しません", page)
        self.assertIn("../items/2649805M1026.html", links.hrefs)
        self.assertIn("../items/2190102F1106.html", links.hrefs)
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

    def test_web_list_preserves_the_four_featured_links_and_exposes_other_products(self):
        document = json.loads((ROOT / "featured_products.json").read_text())
        records = document["products"]
        before = json.dumps(records)
        page = list_page("products", records, "2026-09-12", {"2649805M1026", "3179106F1039"})
        first, other = page.split('<details class="other-products">')
        featured = re.findall(r'<a href="([^"]+)">[^<]+<small>', first)
        self.assertEqual(["movicol.html", "juvela-ointment.html", "teramuro.html", "zictor-tape-75mg.html"], featured)
        for record in records:
            link = f'href="{record["slug"]}.html"'
            if f'{record["slug"]}.html' in featured:
                self.assertNotIn(link, other)
            elif record["slug"] in CADUET_STRENGTH_SLUGS:
                self.assertNotIn(link, page)
            else:
                self.assertIn(link, other)
        self.assertEqual(before, json.dumps(records))
        self.assertEqual(1, page.count('テラムロ配合錠'))
        self.assertIn('href="../items/3179106F1039.html"', other)
        self.assertIn("1〜4番の規格別比較", other)
        self.assertNotIn("最終更新", page)
        self.assertNotIn('テラムロ配合錠', list_page('topics', [], '2026-09-12'))

    def test_strength_hub_groups_only_matching_brands_and_resolves_each_item(self):
        rows = [
            {"商品名": "テラムロ配合錠ＡＰ「例」", "YJコード": "APKEY", "供給状況": "①通常出荷", "販売メーカー": "販売元A"},
            {"商品名": "テラムロ配合錠BP「例」", "YJコード": "BPKEY", "供給状況": "⑤供給停止"},
            {"商品名": "ミカムロ配合錠AP", "YJコード": "OTHER", "供給状況": "①通常出荷"},
            {"商品名": "テラムロ配合錠AP徐放錠「例」", "YJコード": "LOOKALIKE"},
            {"商品名": "テラムロ配合錠CP「例」", "YJコード": "NEWGRADE"},
        ]
        page = strength_hub_page("teramuro", rows, {"APKEY"}, "2026-11-20")
        self.assertIn("<title>テラムロ配合錠AP・BPの出荷調整・供給状況｜販売元別｜医薬品供給ナビ</title>", page)
        self.assertIn("厚労省の供給区分をAP・BPと販売元ごとに比較できます", page)
        self.assertIn('href="#bp"', page)
        ap_section, bp_section = page.split('<section aria-labelledby="bp">')
        self.assertIn('href="../items/APKEY.html"', ap_section)
        self.assertIn('href="../#item=BPKEY"', bp_section)
        self.assertNotIn("ミカムロ", page)
        self.assertNotIn("LOOKALIKE", page)
        self.assertNotIn("NEWGRADE", page)
        self.assertIn("⑤供給停止", bp_section)
        self.assertIn("販売元A", ap_section)
        self.assertIn("2026-11-20", page)
        self.assertNotIn('href="#packageSnapshotTitle"', page)
        snapshot = '<section><h2 id="packageSnapshotTitle">包装別案内</h2></section>'
        with_snapshot = strength_hub_page("teramuro", rows, {"APKEY"}, "2026-11-20",
                                          package_snapshot=snapshot, package_keys={"APKEY"})
        self.assertIn('href="#packageSnapshotTitle"', with_snapshot)
        self.assertIn('href="#packages-APKEY"', with_snapshot)
        self.assertIn('id="comparison-APKEY"', with_snapshot)
        self.assertNotIn('href="#packages-BPKEY"', with_snapshot)
        self.assertIn('id="comparison-BPKEY"', with_snapshot)
        self.assertIn("出荷調整や販売中止の案内", with_snapshot)
        self.assertGreater(with_snapshot.index(snapshot), with_snapshot.index('<h2 id="bp">'))
        towa_supply = with_snapshot.split('<h3 id="towaSupplyTitle">', 1)[1].split('<h3 id="sawaiSupplyTitle">', 1)[0]
        self.assertIn("2026年11月19日版では、AP・BPともに", towa_supply)
        self.assertIn("限定出荷（自社の事情）", towa_supply)
        self.assertIn('href="https://med.towayakuhin.co.jp/medical/product/fileloader.php?id=80558&amp;t=6#page=7"', towa_supply)
        sawai_supply = with_snapshot.split('<h3 id="sawaiSupplyTitle">', 1)[1].split("</section>", 1)[0]
        self.assertIn("2026年11月13日版では、AP・BPともに", sawai_supply)
        self.assertIn("限定出荷（他社品の影響）", sawai_supply)
        self.assertIn('href="https://med.sawai.co.jp/file/pr115_4577_1.pdf#page=8"', sawai_supply)
        self.assertIn('href="#dsepPackagingTitle"', with_snapshot)
        packaging = with_snapshot.split('<h2 id="dsepPackagingTitle">', 1)[1].split("</section>", 1)[0]
        self.assertIn("AG呼称の使用終了</strong>　2027年1月1日から", packaging)
        self.assertIn("新包装の市場出荷</strong>　案内時点で時期は未公表", packaging)
        self.assertIn("PTP100錠（081-186754）、PTP500錠（081-186761）", packaging)
        self.assertIn("BP</strong>　PTP100錠（081-186853）", packaging)
        self.assertIn('href="#nigTransferTitle"', with_snapshot)
        transfer = with_snapshot.split('<h2 id="nigTransferTitle">', 1)[1].split("</section>", 1)[0]
        self.assertIn("2026年2月1日", transfer)
        self.assertIn("2026年2月9日", transfer)
        self.assertIn("123-87483-0 → 376-78452-8", transfer)
        self.assertIn("123-87484-7 → 376-78462-7", transfer)
        missing = strength_hub_page("movicol", [
            {"商品名": "モビコール配合内用剤に似た名称", "YJコード": "LOOKALIKE"},
            {"商品名": "モビコール配合内用剤LD別製品", "YJコード": "LOOKALIKE2"},
        ], set(), "")
        self.assertIn("<title>モビコール配合内用剤LD・HDの出荷調整・供給状況｜医薬品供給ナビ</title>", missing)
        self.assertNotIn("LOOKALIKE", missing)
        self.assertNotIn("dsepPackagingTitle", missing)
        self.assertNotIn("sawaiSupplyTitle", missing)
        self.assertNotIn("towaSupplyTitle", missing)
        self.assertIn("基準日 未確認", missing)
        self.assertIn("今回の公表データでは該当する品目を確認できません", missing)

    def test_movicol_distinguishes_official_outlooks_from_packaging_and_falls_back(self):
        ld, hd = "2359110B1037", "2359110B2025"
        rows = [
            {"商品名": "モビコール配合内用剤" + strength, "YJコード": key,
             "供給状況": "②限定出荷（自社の事情）",
             "代替候補": "解除/解消見込み: ア. あり / 出荷量状況: B．出荷量減少"}
            for strength, key in (("ＬＤ", ld), ("ＨＤ", hd))
        ]
        url = "https://www.mhlw.go.jp/content/10800000/261120iyakuhinkyoukyu.xlsx"
        meta = {"url": url, "excel_date": "2026-11-20", "release_outlooks": {hd: "2027年6月頃"}}
        snapshot = '<section><h2 id="packageSnapshotTitle">包装別案内</h2></section>'
        page = strength_hub_page("movicol", rows, {ld, hd}, "2026-11-20", mhlw_source=meta,
                                 package_snapshot=snapshot, package_keys={ld})
        ld_section, hd_section = page.split('<section aria-labelledby="hd">')
        self.assertIn('href="#ld">LD</a>', ld_section)
        self.assertIn('href="#hd">HD</a>', ld_section)
        self.assertNotIn("解除見込み（品目全体）", ld_section)
        self.assertIn("解除見込み（品目全体）　2027年6月頃", hd_section)
        self.assertIn(f'href="{url}"', page)
        self.assertIn(f'href="#packages-{ld}"', ld_section)
        self.assertNotIn(f'href="#packages-{hd}"', page)
        fallback = strength_hub_page("movicol", rows, {ld, hd}, "2026-11-23", mhlw_source=meta)
        self.assertNotIn("2027年6月頃", fallback)
        self.assertNotIn('href="#packageSnapshotTitle"', fallback)

    def test_generated_movicol_has_both_dated_packaging_notices(self):
        page = (ROOT / "products" / "movicol.html").read_text(encoding="utf-8")
        self.assertIn('id="packages-2359110B1037"', page)
        self.assertIn('id="packages-2359110B2025"', page)
        self.assertIn("2026年10月のEAファーマの案内", page)
        self.assertIn("LD 100包（EAファーマ販売）", page)
        self.assertIn("HD 100包（EAファーマ販売）", page)
        self.assertIn("2026年12月から一時出荷停止予定", page)
        self.assertIn("MVC-H-2-PM-05818.pdf", page)

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
            self.assertIn("products/teramuro.html", sitemap)
            self.assertIn("products/movicol.html", sitemap)
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
        product_slugs = {record["slug"] for record in products} | set(STRENGTH_HUBS) | {"hilnamin"}
        topic_files = {path.stem for path in (ROOT / "topics").glob("*.html") if path.name != "index.html"}
        product_files = {path.stem for path in (ROOT / "products").glob("*.html") if path.name != "index.html"}

        # Preserve the old article URL while removing it from current news listings.
        archived_topics = {
            "luliconazole-iwaki-normal-shipment-plan-20261020",
            "chuikyo-drug-price-hearing-20260826",
            "astra-zeneca-bms-merger-report-20260803",
            "locoid-transfer-20260723",
            "efluelda-launch-delay-20260721",
        }
        self.assertEqual(topic_slugs | archived_topics, topic_files)
        self.assertTrue(archived_topics.isdisjoint(topic_slugs))
        index = (ROOT / "topics" / "index.html").read_text(encoding="utf-8")
        for slug in archived_topics:
            self.assertNotIn(f"{slug}.html", index)
        self.assertEqual(product_slugs, product_files)
        hilnamin = (ROOT / "products" / "hilnamin.html").read_text(encoding="utf-8")
        for key in ("1172014B2056", "1172014C1055", "1172014F1027", "1172014F2139", "1172014F3038"):
            self.assertIn(f'href="../items/{key}.html"', hilnamin)
        sitemap = (ROOT / "sitemap-curated.xml").read_text(encoding="utf-8")
        for kind, slugs in (("topics", topic_slugs), ("products", product_slugs)):
            index = (ROOT / kind / "index.html").read_text(encoding="utf-8")
            for slug in slugs:
                with self.subTest(kind=kind, slug=slug):
                    page = (ROOT / kind / f"{slug}.html").read_text(encoding="utf-8")
                    if kind == "products" and slug in CADUET_STRENGTH_SLUGS:
                        self.assertNotIn(f'{slug}.html', index)
                        base_product = (ROOT / "products" / "caduet.html").read_text(encoding="utf-8")
                        self.assertIn('href="caduet.html"', index)
                        self.assertIn(f'href="{slug}.html"', base_product)
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

    def test_zictor_product_shows_verified_packaging_before_share_and_keeps_fallback(self):
        product = {"slug": "zictor-tape-75mg", "label": "ジクトルテープ75mg", "query": "ジクトル"}
        row = {"商品名": "ジクトルテープ７５ｍｇ", "YJコード": "1147700S1028",
               "供給状況": "②限定出荷（自社の事情）", "更新日": "2026/10/01"}
        section = '<section id="verified-packages">案内時点の包装別の予定</section>'
        inputs = (product, [row], {row["YJコード"]}, {})
        page, lastmod = product_page(*inputs, package_brief=("包装別の出荷案内", "原文の要約", section),
                                     source_date="2026-11-20")
        self.assertLess(page.index(section), page.index("data-dsn-share-page"))
        self.assertIn("厚労省公表　②限定出荷（自社の事情）", page)
        self.assertIn("2026-11-20基準", page)
        self.assertIn('<title>ジクトルテープ75mgの出荷調整・供給状況｜包装別の出荷案内', page)
        self.assertIn('久光製薬の資料で示された1枚包装・7枚包装の出荷予定', page)
        self.assertNotIn('<h2>該当品目</h2>', page)
        self.assertIn(f'href="../items/{row["YJコード"]}.html"', page)
        with_delisting, _ = product_page(
            product, [dict(row, 代替候補="薬価削除予定")], {row["YJコード"]}, {},
            package_brief=("包装別の出荷案内", "原文の要約", section), source_date="2026-11-20")
        self.assertIn("薬価削除予定</span>", with_delisting)
        fallback, fallback_lastmod = product_page(*inputs, source_date="2026-11-23")
        self.assertNotIn(section, fallback)
        self.assertNotIn("原文の要約", fallback)
        self.assertIn("厚労省の原典で確認", fallback)
        self.assertIn('<h2>該当品目</h2>', fallback)
        self.assertGreaterEqual(fallback_lastmod, lastmod)

    def test_juvela_product_highlights_only_outlook_from_matching_workbook(self):
        product = {"slug": "juvela-ointment", "label": "ユベラ軟膏", "query": "ユベラ軟膏"}
        key = "2649805M1026"
        row = {"商品名": "ユベラ軟膏", "YJコード": key, "供給状況": "②限定出荷（自社の事情）",
               "代替候補": "解除/解消見込み: ア. あり / 出荷量状況: B．出荷量減少"}
        url = "https://www.mhlw.go.jp/content/10800000/261120iyakuhinkyoukyu.xlsx"
        source = {"url": url, "excel_date": "2026-11-20", "release_outlooks": {key: "2027年3月"}}
        def render(meta, shipment="②限定出荷（自社の事情）"):
            return product_page(product, [dict(row, 供給状況=shipment)], {key}, {},
                                source_date="2026-11-20", mhlw_source=meta)[0]
        page = render(source)
        hero = page.split('<section class="hero">', 1)[1].split("</section>", 1)[0]
        self.assertIn("解除見込み（品目全体）", hero)
        self.assertIn("2027年3月", hero)
        self.assertIn("2026-11-20", hero)
        self.assertIn(f'href="{url}"', hero)
        self.assertIn("包装ごとの再開時期はメーカー案内で確認", hero)
        self.assertIn('href="../items/2649805M1026.html"', hero)
        self.assertNotIn('href="#packageSnapshotTitle"', hero)
        snapshot = '<section><h2 id="packageSnapshotTitle">包装別の案内</h2></section>'
        with_packaging, _ = product_page(product, [row], {key}, {}, source_date="2026-11-20",
                                         mhlw_source=source, package_snapshot=snapshot)
        self.assertIn('href="#packageSnapshotTitle">包装別の案内を見る</a>', with_packaging)
        self.assertLess(with_packaging.index("解除見込み（品目全体）"), with_packaging.index(snapshot))
        self.assertLess(with_packaging.index(snapshot), with_packaging.index('<h2>該当品目</h2>'))
        for omitted in (render(None), render(source, "①通常出荷"),
                        render(dict(source, excel_date="2026-11-19")),
                        render(dict(source, url="https://example.test/outlook.xlsx"))):
            self.assertNotIn("2027年3月", omitted)
            self.assertNotIn("解除見込み（品目全体）", omitted)

    def test_priority_product_hero_links_to_available_strengths(self):
        for slug, label in (("kenacort-a-injection", "ケナコルト－Ａ注"), ("hilnamin", "ヒルナミン")):
            with self.subTest(slug=slug):
                product = {"slug": slug, "label": label, "query": label}
                key = "1172014F2139"
                row = {"商品名": label + "の試験規格", "YJコード": key, "供給状況": "①通常出荷"}
                page, _ = product_page(product, [row], {key}, {}, source_date="2026-11-20")
                self.assertIn(f"<h1>{label}の規格別供給状況</h1>", page)
                self.assertIn('href="#productItems">規格別の供給状況を見る</a>', page)
                self.assertIn('<h2 id="productItems">規格別の品目</h2>', page)
                self.assertIn(f'href="../items/{key}.html"', page)

    def test_hilnamin_links_each_strength_to_its_matching_package_notice(self):
        product = {"slug": "hilnamin", "label": "ヒルナミン", "query": "ヒルナミン"}
        powder, granules = "1172014B2056", "1172014C1055"
        rows = [
            {"YJコード": key, "商品名": "ヒルナミン" + name, "販売メーカー": "テスト製薬",
             "供給状況": "②限定出荷（自社の事情）"}
            for key, name in ((powder, "散５０％"), (granules, "細粒１０％"))
        ]
        keys = {powder, granules}
        notice = {
            "url": "https://example.test/a.pdf", "announced_at": "2026-10",
            "maker": "テスト製薬", "sha256": "a" * 64, "event_type": "limited",
            "targets": [{"yj_code": granules, "product_name": rows[1]["商品名"],
                         "scope": "package", "packages": [
                             {"package": "100g", "supply": {"status": "limited",
                                                            "status_text": "限定出荷", "plans": []}}]}],
        }
        snapshot, package_keys = product_package_snapshot(
            rows, {granules: [notice]}, {"items": []}, keys, link_comparison=True)
        page, _ = product_page(product, rows, keys, {}, package_snapshot=snapshot, package_keys=package_keys)
        for key in keys:
            self.assertEqual(page.count(f'id="comparison-{key}"'), 1)
            self.assertIn(f'href="#comparison-{key}"', page)
        self.assertIn(f'href="#comparison-{powder}">散50%</a>', page)
        self.assertIn(f'href="#packages-{granules}"', page)
        self.assertEqual(page.count(f'id="packages-{granules}"'), 1)
        self.assertNotIn(f'#packages-{powder}', page)
        fallback, _ = product_page(product, rows, keys, {})
        self.assertNotIn('#packages-', fallback)

    def test_kenacort_article_links_to_product_comparison_for_both_exact_targets(self):
        topic = json.loads((ROOT / "industry_topics.json").read_text(encoding="utf-8"))
        topic = next(item for item in topic["topics"] if item["slug"] == "kenacort-supply-plan-20261020")
        keys = set(topic["target_queries"])
        targets = [{"YJコード": key, "商品名": f"対象品目 {key}"} for key in sorted(keys)]
        html = topic_page(topic, [], keys, {}, "2026-11-24", targets)
        link = 'href="../products/kenacort-a-injection.html#productItems"'
        self.assertLess(html.index(link), html.index('<ul class="points">'))
        self.assertNotIn(link, topic_page(topic, [], keys, {}, "2026-11-24", targets[:1]))

    def test_kenacort_comparison_prioritizes_the_dated_packaging_notice(self):
        key = "2454402A3033"
        product = {"slug":"kenacort-a-injection", "label":"ケナコルト－Ａ注", "query":"ケナコルト"}
        row = {"YJコード":key, "商品名":"ケナコルトＡ", "供給状況":"②限定出荷（自社の事情）",
               "販売メーカー":"テスト製薬"}
        target = {"yj_code":key, "product_name":row["商品名"], "scope":"package", "packages":[
            {"package":"10バイアル", "unified_product_code":"279-11523-8", "supply":{
                "status":"limited", "status_text":"限定出荷", "plans":[]}}]}
        notice = {"url":"https://example.test/a.pdf", "announced_at":"2026-10", "listed_at":"2026-10-19",
                  "verified_at":"2026-11-24", "maker":"テスト製薬", "sha256":"a"*64, "targets":[target],
                  "summary":"12月から通常時の約30％まで出荷量を引き上げる予定です。", "event_type":"limited",
                  "reason":"新製造ラインの適格性評価が長期化したため。"}
        args = (product,[row],{key},{})
        snapshot, _ = product_package_snapshot([row], {key:[notice]}, {"items":[]}, {key}, show_notice_details=True)
        page, _ = product_page(*args, package_snapshot=snapshot)
        self.assertIn('href="#packageSnapshotTitle">メーカーの供給予定・対象包装</a>', page)
        self.assertIn("メーカー公式掲載日 2026年10月19日", page)
        self.assertIn("統一商品コード 279-11523-8", page)
        self.assertIn(notice["reason"], page)
        self.assertIn('href="../topics/kenacort-supply-plan-20261020.html"', page)
        fallback, _ = product_page(*args)
        self.assertNotIn('href="#packageSnapshotTitle"', fallback)

    def test_product_packaging_snapshot_keeps_the_scope_and_hides_changed_sources(self):
        code = "1172014F2139"
        row = {"商品名": "ヒルナミン錠（25mg）", "YJコード": code, "製造メーカー": "共和薬品工業"}
        target = {"yj_code": code, "product_name": row["商品名"], "scope": "package",
                  "packages": [{"package": "PTP100錠", "supply": {
                      "status": "stopped", "status_text": "出荷停止", "plans": [],
                  }}]}
        notice = {"url": "https://example.test/notice.pdf", "announced_at": "2026-11-16",
                  "maker": "共和薬品工業", "sha256": "a" * 64, "targets": [target],
                  "reason": "メーカー案内の理由"}
        html, keys = product_package_snapshot([row], {code: [notice]}, {"items": []}, {code})
        self.assertEqual(set(), keys)
        self.assertIn("2026年11月16日の共和薬品工業の案内", html)
        self.assertIn("PTP100錠：出荷停止", html)
        self.assertIn(f'href="../items/{code}.html"', html)
        self.assertNotIn(notice["reason"], html)
        target["packages"][0]["supply"]["plans"] = [{"event": "stock_depletion", "timing": "2026年12月予定"}]
        with_details, keys = product_package_snapshot([row], {code: [notice]}, None, {code}, include_details=True)
        self.assertEqual({code}, keys)
        self.assertIn(f'id="packages-{code}"', with_details)
        self.assertIn(f'href="#comparison-{code}"', with_details)
        self.assertIn(notice["reason"], with_details)
        self.assertIn("PTP100錠：出荷停止<br>在庫消尽予定 2026年12月", with_details)
        changed = {"items": [{"url": notice["url"], "sha256": "b" * 64}]}
        self.assertEqual(("", set()), product_package_snapshot(
            [row], {code: [notice]}, changed, {code}, include_details=True))
        other_strength = dict(row, 商品名="ヒルナミン錠（50mg）")
        self.assertEqual(("", set()), product_package_snapshot([other_strength], {code: [notice]}, None, {code}))

        route = dict(target, scope="seller_route_and_package", seller="販売元A")
        route_notice = dict(notice, targets=[route], source_index_url="https://example.test/source-list.pdf")
        index = {code: [route_notice]}
        matching_seller = dict(row, 販売メーカー="販売元A")
        html, _ = product_package_snapshot([matching_seller], index, None, {code})
        self.assertIn("対象の販売元　販売元A", html)
        self.assertIn('href="https://example.test/source-list.pdf"', html)
        joint_sellers = dict(row, 販売メーカー="販売元B・販売元A")
        html, _ = product_package_snapshot([joint_sellers], index, None, {code})
        self.assertIn("対象の販売元　販売元A", html)
        other_seller = dict(row, 販売メーカー="販売元B")
        self.assertEqual(("", set()), product_package_snapshot([other_seller], index, None, {code}))

        old_target = dict(target, packages=[
            {"package": "PTP140錠", "supply": {"status": "stopped", "status_text": "販売終了", "plans": []}},
        ])
        old_notice = dict(notice, event_type="discontinued", announced_at="2025-07",
                          url="https://example.test/old.pdf", targets=[old_target])
        html, keys = product_package_snapshot([row], {code: [notice, old_notice]}, None, {code}, include_details=True)
        self.assertIn("PTP100錠：出荷停止", html)
        self.assertIn("PTP140錠：販売終了", html)
        self.assertEqual({code}, keys)
        self.assertEqual(1, html.count(f'id="packages-{code}"'))
        self.assertEqual(2, html.count(f'href="#comparison-{code}"'))
        old_target["packages"][0]["package"] = "PTP100錠"
        html, _ = product_package_snapshot([row], {code: [notice, old_notice]}, None, {code}, include_details=True)
        self.assertNotIn("PTP100錠：販売終了", html)

    def test_teramuro_item_comparison_links_match_the_hub_cards(self):
        hub = (ROOT / "products" / "teramuro.html").read_text(encoding="utf-8")
        keys = re.findall(r'id="comparison-(2149117F\d{4})"', hub)
        self.assertTrue(keys)
        self.assertEqual(len(keys), len(set(keys)))
        for key in keys:
            with self.subTest(key=key):
                item = (ROOT / "items" / f"{key}.html").read_text(encoding="utf-8")
                href = f'href="../products/teramuro.html#comparison-{key}"'
                self.assertEqual(item.count(href), 1)
                self.assertLess(item.index(href), item.index('id="itemFreshnessTitle"'))

    def test_sawai_teramuro_discontinuation_headline_only_names_ptp140(self):
        for code in ("2149117F1050", "2149117F2056"):
            with self.subTest(code=code):
                page = (ROOT / "items" / f"{code}.html").read_text(encoding="utf-8")
                self.assertIn("メーカー：販売中止の案内（PTP140錠）", page)
                self.assertRegex(page, r'<meta name="description" content="[^"]*対象はPTP140錠。')
                self.assertIn("PTP100錠", page)

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


class TopicDatasetDateTests(unittest.TestCase):
    def test_topic_separates_dataset_and_source_dates_from_item_update(self):
        from generate_curated_pages import topic_page
        topic = {"slug": "test-date", "tag": "供給情報", "title": "試験", "lede": "案内", "date": "2026.09.30",
                 "source": {"name": "原典", "url": "https://example.org/"}}
        row = {"商品名": "試験薬", "YJコード": "123456789012", "供給状況": "②限定出荷", "更新日": "2026-09-29"}
        version = {"note": "2026年11月04日厚労省データ反映", "mhlw_excel_date": "2026-11-02"}
        output = topic_page(topic, [], set(), {}, "2026-10-15", [row], "2026-11-04", version)
        self.assertIn("厚労省原Excelの基準日：", output)
        self.assertIn(">2026-11-02</span>", output)
        self.assertIn(">2026-11-04</span>", output)
        self.assertIn("更新 2026-09-29", output)
        self.assertIn("HTML生成時の公表区分", output)
        self.assertLess(output.index("厚労省原Excelの基準日"), output.index("対象品目の現在の供給状況"))
        unknown = topic_page(topic, [row], set(), {}, "", dataset_date="", version_metadata={})
        self.assertIn("確認できません", unknown)
        self.assertNotIn(">2026-09-29</span>", unknown)
        no_rows = topic_page(topic, [], set(), {}, "")
        self.assertNotIn("供給情報の基準日", no_rows)


class TopicModificationDateTests(unittest.TestCase):
    def test_collection_addition_preserves_existing_article_date(self):
        from generate_curated_pages import topic_page
        topic = {"slug": "old-topic", "tag": "供給予定", "title": "既存記事", "lede": "内容を維持", "date": "2026.10.01",
                 "updated_at": "2026-10-15", "source": {"name": "原典", "url": "https://example.org/"}}
        output = topic_page(topic, [], set(), {}, "2026-10-20")
        self.assertEqual(json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', output, re.S)[1])["@graph"][0]["dateModified"], "2026-10-15")
        topic.pop("updated_at")
        output = topic_page(topic, [], set(), {}, "2026-10-20")
        self.assertEqual(json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', output, re.S)[1])["@graph"][0]["dateModified"], "2026-10-20")
