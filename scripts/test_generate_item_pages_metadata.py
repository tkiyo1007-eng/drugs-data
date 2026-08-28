import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from generate_item_pages import (
    ITEM_HUB_SLUGS,
    STATUS_NOTES,
    build_item_identities,
    discrepancy_matches,
    hub_html,
    index_html,
    item_hub_slugs,
    item_page_lastmod,
    latest_publication_date,
    latest_changes_by_key,
    load_status_changes,
    official_row_date,
    page_html,
    page_title,
    pick_siblings,
    recent_recovery_keys,
    reconcile_existing_pages,
    should_generate,
    sitemap_xml,
    supply_metadata_values,
    supplemental_context,
    validated_product_map,
    version_date,
)


class ItemPageMetadataTests(unittest.TestCase):
    def test_item_page_answers_reason_release_and_shipment_without_inference(self):
        row = {
            "商品名": "テスト錠10mg",
            "一般名": "テスト成分",
            "製造メーカー": "テスト製薬",
            "供給状況": "③限定出荷（他社品の影響）",
            "理由": "１．需要増",
            "代替候補": "解除/解消見込み: ウ. 未定 / 出荷量状況: B．出荷量減少",
            "更新日": "2026/08/20",
            "YJコード": "1234567F1234",
        }
        self.assertEqual({
            "解除・解消見込み": "ウ. 未定",
            "出荷量状況": "B．出荷量減少",
        }, supply_metadata_values(row))

        output = page_html(
            row, "1234567F1234", "limited", "2026-08-28", [],
            {"1234567F1234"},
        )

        self.assertIn("テスト錠10mgはなぜ限定出荷（出荷調整）？", output)
        self.assertIn("理由欄は「<strong>１．需要増</strong>」", output)
        self.assertIn("公表欄の記載は「<strong>ウ. 未定</strong>」", output)
        self.assertIn("出荷量状況の記載は「<strong>B．出荷量減少</strong>」", output)
        self.assertIn("公表されていない個別事情は推測していません", output)
        self.assertLess(output.index('class="quick-answers"'), output.index("<table>"))
        self.assertIn('id="watchButton"', output)
        self.assertLess(output.index('id="watchButton"'), output.index("<table>"))
        self.assertLess(output.index('id="watchButton"'), output.index('class="quick-answers"'))
        self.assertIn('localStorage.setItem("favDrugKeysV2"', output)
        self.assertIn('watchKeys = readWatchKeys();', output)
        self.assertIn('addEventListener("storage"', output)
        self.assertIn('window.dsnTrack("item-watchlist-add")', output)
        self.assertIn('"@type":"WebPage"', output)
        self.assertIn("解除・解消見込みの公表区分は？", output)
        self.assertIn("厚生労働省の公式システムとメーカー案内の原文", output)
        description = output.split('<meta name="description" content="', 1)[1].split('">', 1)[0]
        self.assertIn("公表理由は「１．需要増」", description)
        self.assertIn("解除・解消見込みは「ウ. 未定」", description)

    def test_related_items_prioritize_same_spec_before_status(self):
        row = {
            "商品名": "対象錠20mg", "一般名": "対象成分", "規格": "20mg1錠",
            "供給状況": "②限定出荷（自社の事情）", "YJコード": "1234567F1000",
        }
        candidates = [row,
            {"商品名": "別社錠10mg", "規格": "10mg1錠", "供給状況": "①通常出荷", "YJコード": "1234567F1001"},
            {"商品名": "別社B錠20mg", "規格": "20mg1錠", "供給状況": "②限定出荷（自社の事情）", "YJコード": "1234567F1002"},
            {"商品名": "別社A錠20mg", "規格": "20mg1錠", "供給状況": "①通常出荷", "YJコード": "1234567F1003"},
        ]

        ordered = pick_siblings(row, candidates)

        self.assertEqual(
            ["別社A錠20mg", "別社B錠20mg", "別社錠10mg"],
            [item["商品名"] for item in ordered],
        )
        output = page_html(
            row, "1234567F1000", "limited", "2026-08-28", ordered,
            {"1234567F1000", "1234567F1001", "1234567F1002", "1234567F1003"},
        )
        self.assertIn('<span class="mk">20mg1錠</span>', output)
        self.assertIn("同じ規格を優先し、その中で現在の厚生労働省公表区分と薬価削除予定", output)
        self.assertIn("ほかの品目の供給状況", output)

    def test_item_page_explicitly_explains_when_no_related_candidates_exist(self):
        row = {
            "商品名": "単独品目", "一般名": "単独成分", "規格": "10mg1錠",
            "供給状況": "供給停止", "YJコード": "1234567F1000",
        }
        output = page_html(
            row, "1234567F1000", "stopped", "2026-08-28", [],
            {"1234567F1000"},
        )
        self.assertIn("確認候補は見つかりませんでした", output)
        self.assertIn("候補がないことは、代替品が存在しないこと", output)
        self.assertIn('>Web版でこの品目を開く</a>', output)
        self.assertNotIn("同成分・同剤形の一覧つき", output)

    def test_json_ld_escapes_script_closing_sequences(self):
        row = {
            "商品名": "安全性テスト錠", "一般名": "安全性成分",
            "製造メーカー": "テスト製薬", "供給状況": "限定出荷",
            "理由": "</script><script>alert(1)</script>",
            "YJコード": "1234567F1234",
        }
        output = page_html(
            row, "1234567F1234", "limited", "2026-08-28", [],
            {"1234567F1234"},
        )
        self.assertNotIn("</script><script>alert(1)", output.lower())
        self.assertIn("\\u003c/script\\u003e", output)
        documents = [json.loads(value) for value in re.findall(
            r'<script type="application/ld\+json">(.*?)</script>', output, re.S)]
        self.assertTrue(any(document.get("@type") == "WebPage" for document in documents))

    def test_sales_ended_note_requires_professional_current_information_check(self):
        note = STATUS_NOTES["ended"]
        self.assertIn("メーカー・卸の最新情報", note)
        self.assertIn("医師・薬剤師等の専門職", note)
        self.assertNotIn("代替薬への切り替え検討が必要", note)
        output = page_html({
            "商品名": "販売中止テスト錠",
            "製造メーカー": "テスト製薬",
            "供給状況": "販売中止",
            "更新日": "2026/08/20",
            "YJコード": "1234567F1234",
        }, "1234567F1234", "ended", "2026-08-20", [], {"1234567F1234"})
        self.assertIn(note, output)
        self.assertNotIn("代替薬への切り替え検討が必要", output)

    def test_item_page_has_one_canonical_and_large_preview_permission(self):
        row = {
            "商品名": "テスト錠10mg",
            "一般名": "テスト成分",
            "製造メーカー": "テスト製薬",
            "販売メーカー": "",
            "供給状況": "限定出荷",
            "規格": "10mg1錠",
            "更新日": "2026/08/16",
            "YJコード": "1234567F1234",
        }
        output = page_html(row, "1234567F1234", "limited", "2026-08-16", [], {"1234567F1234"})
        self.assertEqual(output.count('rel="canonical"'), 1)
        self.assertIn('content="index,follow,max-image-preview:large"', output)
        self.assertIn('href="https://tkiyo1007-eng.github.io/drugs-data/#item=1234567F1234"', output)
        self.assertIn(
            '<meta name="apple-itunes-app" content="app-id=6777696446, '
            'app-argument=drugsupplynavi://search?q=1234567F1234">',
            output,
        )
        self.assertIn('<script src="../analytics.js"></script>', output)
        self.assertIn('src="https://gc.zgo.at/count.js"', output)
        self.assertIn('data-dsn-event="item-web-open"', output)
        self.assertIn('data-dsn-event="item-app-store-open"', output)
        self.assertIn('厚生労働省の公式システムで品目名・YJコードを再確認', output)
        self.assertIn('data-dsn-event="official-source-open">PMDAで添付文書を探す', output)
        self.assertIn('../about.html">運営情報・編集方針', output)
        self.assertIn('../privacy.html">プライバシー', output)
        self.assertIn('window.dsnTrack("item-share-success")', output)
        self.assertIn('url.searchParams.set("src", "share")', output)

    def test_item_page_does_not_deep_link_non_formal_identifiers(self):
        for identifier in ("X00001", "", "1234567f1234", "1234567F123<"):
            with self.subTest(identifier=identifier):
                row = {
                    "商品名": "テスト医療用ガス",
                    "製造メーカー": "テスト製薬",
                    "供給状況": "供給停止",
                    "YJコード": identifier,
                }
                output = page_html(
                    row, "safe-page-key", "stopped", "2026-08-16", [],
                    {"safe-page-key"},
                )
                self.assertIn(
                    '<meta name="apple-itunes-app" content="app-id=6777696446">',
                    output,
                )
                self.assertNotIn("app-argument=", output)

    def test_normal_status_keeps_official_label_and_adds_verified_maker_context(self):
        row = {
            "商品名": "テスト錠10mg「サワイ」",
            "一般名": "テスト成分",
            "製造メーカー": "沢井製薬",
            "販売メーカー": "沢井製薬",
            "供給状況": "通常出荷",
            "更新日": "2024/03/11",
            "YJコード": "1234567F1234",
        }
        lifecycle = {
            "product_name": row["商品名"],
            "maker": "沢井製薬",
            "announced_at": "2026-08-07",
            "verified_at": "2026-08-26",
            "source_title": "テスト錠10mg「サワイ」販売中止のご案内",
            "source_url": "https://example.test/lifecycle.pdf",
        }
        discrepancy = {
            "product_name": row["商品名"],
            "confidence": "high",
            "official": {"status": "ok", "label": "通常出荷", "updated_at": "2024-03-11"},
            "manufacturer": {
                "label": "限定出荷", "announced_at": "2026-08-17",
                "maker": "沢井製薬", "scope": "product",
                "url": "https://example.test/limited.pdf",
            },
        }
        output = page_html(
            row, "1234567F1234", "ok", "2026-08-26", [], {"1234567F1234"},
            lifecycle=lifecycle, discrepancy=discrepancy, dataset_date="2026-08-26",
            supplemental_checked_date="2026-08-26",
        )
        self.assertIn("厚生労働省公表データ上の供給区分は「<strong>通常出荷</strong>」", output)
        self.assertIn("メーカー公式：販売中止予定", output)
        self.assertIn("情報差異あり", output)
        self.assertIn("メーカー公式：限定出荷（2026-08-17）", output)
        self.assertEqual(4, output.count('data-dsn-event="official-source-open"'))
        self.assertIn("メーカー：販売中止予定／メーカー：限定出荷", output)
        self.assertIn("サイト全体の公開データ基準日", output)
        self.assertIn('fetch("../version.json"', output)
        self.assertIn('response.headers.get("X-DSN-Source") === "cache"', output)
        self.assertIn("公開データ基準日が7日以上更新されていません", output)
        self.assertNotIn("全体データ基準日 2026-08-26", output)
        self.assertNotIn("\x08", output)
        self.assertNotIn("メーカーが通常どおり出荷", output)

    def test_related_same_ingredient_link_uses_only_the_fixed_event_name(self):
        row = {
            "商品名": "テスト錠10mg",
            "一般名": "テスト成分",
            "製造メーカー": "テスト製薬",
            "供給状況": "限定出荷",
            "YJコード": "1234567F1234",
        }
        sibling = {
            "商品名": "同成分錠10mg「他社」",
            "一般名": "テスト成分",
            "製造メーカー": "他社製薬",
            "供給状況": "通常出荷",
            "YJコード": "1234567F5678",
        }

        output = page_html(
            row,
            "1234567F1234",
            "limited",
            "2026-08-28",
            [sibling],
            {"1234567F1234", "1234567F5678"},
        )

        self.assertIn(
            'href="1234567F5678.html" data-dsn-event="related-item-open"',
            output,
        )
        self.assertNotIn("1234567F5678-related-item-open", output)

    def test_verified_supplemental_item_is_generated_even_when_official_status_is_normal(self):
        row = {
            "商品名": "対象錠", "供給状況": "通常出荷", "YJコード": "1234567F1234",
            "製造メーカー": "対象製薬",
        }
        lifecycle = {"1234567F1234": {"product_name": "対象錠", "maker": "対象製薬"}}
        self.assertTrue(should_generate(row, "1234567F1234", set(), lifecycle, {}))
        wrong_name = {"1234567F1234": {"product_name": "別の品目", "maker": "対象製薬"}}
        self.assertFalse(should_generate(row, "1234567F1234", set(), wrong_name, {}))
        wrong_maker = {"1234567F1234": {"product_name": "対象錠", "maker": "別会社"}}
        self.assertFalse(should_generate(row, "1234567F1234", set(), wrong_maker, {}))

    def test_missing_or_invalid_supplemental_schema_fails_closed(self):
        with self.assertRaises(ValueError):
            validated_product_map({}, "販売中止補足データ")
        with self.assertRaises(ValueError):
            validated_product_map({"schema_version": 1, "products": []}, "販売中止補足データ")

    def test_version_date_distinguishes_dataset_date_from_item_update_date(self):
        self.assertEqual(version_date({"note": "2026年08月26日厚労省データ反映"}), "2026-08-26")
        self.assertEqual(version_date({"version": 202608260000}), "2026-08-26")

    def test_sitemap_lastmod_uses_newest_verified_manufacturer_publication(self):
        row = {
            "商品名": "対象錠", "製造メーカー": "対象製薬", "供給状況": "通常出荷",
            "更新日": "2024/03/11", "ステータス更新日": "2024/03/12",
        }
        lifecycle = {
            "product_name": "対象錠", "maker": "対象製薬", "announced_at": "2026-08-07",
        }
        discrepancy = {
            "product_name": "対象錠", "confidence": "high",
            "official": {"status": "ok", "label": "通常出荷", "updated_at": "2024-03-12"},
            "manufacturer": {"maker": "対象製薬", "label": "限定出荷",
                             "scope": "product", "announced_at": "2026-08-17"},
        }
        self.assertEqual(latest_publication_date(row, lifecycle, discrepancy), "2026-08-17")

    def test_sitemap_lastmod_uses_fixed_template_revision_without_advancing_daily(self):
        old_row = {"商品名": "対象錠", "更新日": "2024/03/11"}
        self.assertEqual(item_page_lastmod(old_row), "2026-08-28")
        future_notice = {"product_name": "対象錠", "maker": "対象製薬",
                         "announced_at": "2026-09-01"}
        old_row["製造メーカー"] = "対象製薬"
        self.assertEqual(item_page_lastmod(old_row, future_notice), "2026-09-01")

    def test_discrepancy_must_match_current_official_row_and_manufacturer(self):
        row = {
            "商品名": "対象錠", "製造メーカー": "対象製薬", "供給状況": "限定出荷",
            "更新日": "2026/08/20", "ステータス更新日": "2026/08/22",
        }
        item = {
            "product_name": "対象錠", "confidence": "high",
            "official": {"status": "limited", "label": "限定出荷（A）",
                         "updated_at": "2026-08-22"},
            "manufacturer": {"maker": "対象製薬", "label": "供給停止",
                             "scope": "product"},
        }
        self.assertEqual(official_row_date(row), "2026-08-22")
        self.assertTrue(discrepancy_matches(row, item))
        item["official"]["updated_at"] = "2026-08-20"
        self.assertFalse(discrepancy_matches(row, item))
        item["official"]["updated_at"] = "2026-08-22"
        item["manufacturer"]["maker"] = "無関係製薬"
        self.assertFalse(discrepancy_matches(row, item))

    def test_unhealthy_supplement_downgrades_instead_of_stopping_official_pages(self):
        discrepancy_doc = {"source": {
            "mhlw_note": "2026年08月26日厚労省データ反映",
            "manufacturer_checked_through": "2026-08-18",
        }}
        state = supplemental_context({
            "checked": "2026-08-18",
            "sources": [{"name": "maker", "ok": False}],
        }, discrepancy_doc, "2026-08-26")
        self.assertFalse(state["trusted"])
        self.assertIn("健全性確認が完了していません", state["warning"])
        self.assertIn("7日以上前", state["warning"])

        row = {
            "商品名": "対象錠", "製造メーカー": "対象製薬", "供給状況": "通常出荷",
            "更新日": "2026/08/26", "YJコード": "1234567F1234",
        }
        discrepancy = {
            "product_name": "対象錠", "confidence": "high",
            "official": {"status": "ok", "label": "通常出荷", "updated_at": "2026-08-26"},
            "manufacturer": {"maker": "対象製薬", "label": "限定出荷",
                             "scope": "product", "announced_at": "2026-08-17"},
        }
        output = page_html(
            row, "1234567F1234", "ok", "2026-08-26", [], {"1234567F1234"},
            discrepancy=discrepancy, dataset_date="2026-08-26",
            supplemental_checked_date=state["checked"], supplemental_trusted=False,
            supplemental_warning=state["warning"],
        )
        self.assertIn("メーカー案内あり（要原文確認）", output)
        self.assertIn("収録済みメーカー案内（要原文確認）：限定出荷", output)
        self.assertIn("補足情報の確認注意", output)
        title = output.split("<title>", 1)[1].split("</title>", 1)[0]
        self.assertNotIn("メーカー：限定出荷", title)

    def test_healthy_supplement_context_keeps_verified_labels(self):
        state = supplemental_context({
            "checked": "2026-08-26",
            "sources": [{"name": "maker", "ok": True}],
        }, {"source": {
            "mhlw_note": "2026年08月26日厚労省データ反映",
            "manufacturer_checked_through": "2026-08-26",
        }}, "2026-08-26")
        self.assertEqual(state, {"checked": "2026-08-26", "trusted": True, "warning": ""})

    def test_seo_title_keeps_meaning_without_exceeding_seventy_characters(self):
        name = "フルボキサミンマレイン酸塩錠２５ｍｇ「タカタ」"
        title = page_title(
            name, "供給停止", ["メーカー：販売中止予定", "メーカー：限定出荷解除・通常出荷"],
        )
        self.assertLessEqual(len(title), 70)
        self.assertIn(name, title)
        self.assertIn("供給停止", title)
        self.assertIn("医薬品供給ナビ", title)

        very_long = page_title("長" * 100, "限定出荷", ["メーカー：補足あり"])
        self.assertLessEqual(len(very_long), 70)
        self.assertTrue(very_long.endswith("｜供給状況｜医薬品供給ナビ"))

        qualified = page_title("長" * 100, "限定出荷", [], "10mg1錠")
        self.assertLessEqual(len(qualified), 70)
        self.assertIn("10mg1錠", qualified)

        long_a = page_title("長" * 100, "限定出荷", [], "規格" * 40 + "A")
        long_b = page_title("長" * 100, "限定出荷", [], "規格" * 40 + "B")
        self.assertLessEqual(len(long_a), 70)
        self.assertLessEqual(len(long_b), 70)
        self.assertNotEqual(long_a, long_b)

    def test_duplicate_names_get_unique_spec_or_maker_identity(self):
        targets = {
            "1111111A1111": ({"商品名": "同名注", "規格": "1mL", "製造メーカー": "A社"}, "limited"),
            "1111111A1112": ({"商品名": "同名注", "規格": "2mL", "製造メーカー": "A社"}, "limited"),
            "1111111A1113": ({"商品名": "単独錠", "規格": "10mg", "製造メーカー": "B社"}, "stopped"),
            "1111111A1114": ({"商品名": "完全同名注", "規格": "1mL", "製造メーカー": "A社"}, "limited"),
            "1111111A1115": ({"商品名": "完全同名注", "規格": "1mL", "製造メーカー": "A社"}, "limited"),
        }
        identities = build_item_identities(targets)
        self.assertEqual("同名注（1mL）", identities["1111111A1111"]["display_name"])
        self.assertEqual("同名注（2mL）", identities["1111111A1112"]["display_name"])
        self.assertEqual("単独錠", identities["1111111A1113"]["display_name"])
        self.assertNotEqual(identities["1111111A1114"]["display_name"],
                            identities["1111111A1115"]["display_name"])
        self.assertIn("YJ 1111111A1114", identities["1111111A1114"]["display_name"])

        output = page_html(
            {"商品名": "同名注", "規格": "1mL", "製造メーカー": "A社",
             "供給状況": "限定出荷", "YJコード": "1111111A1111"},
            "1111111A1111", "limited", "2026-08-26", [], {"1111111A1111"},
            title_qualifier="1mL", hub_slugs=["limited"],
        )
        self.assertIn("<h1>同名注（1mL）", output)
        self.assertIn('<a href="limited.html">限定出荷の一覧</a>', output)

    def test_generated_item_is_qualified_when_same_name_exists_outside_targets(self):
        targets = {
            "1111111A1111": (
                {"商品名": "同名錠", "規格": "10mg", "製造メーカー": "A社"},
                "stopped",
            ),
        }
        catalog = {
            "1111111A1111": targets["1111111A1111"][0],
            "1111111A1112": {
                "商品名": "同名錠", "規格": "10mg", "製造メーカー": "A社",
            },
        }
        identities = build_item_identities(targets, catalog)
        self.assertEqual(
            "同名錠（10mg／A社／YJ 1111111A1111）",
            identities["1111111A1111"]["display_name"],
        )
        self.assertEqual(
            "同名錠（10mg／A社／YJ 1111111A1112）",
            identities["1111111A1112"]["display_name"],
        )

    def test_pages_missing_from_current_csv_are_removed(self):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "keep.html").write_text("keep", encoding="utf-8")
            (out / "stale.html").write_text("stale", encoding="utf-8")
            (out / "index.html").write_text("index", encoding="utf-8")
            for slug in ITEM_HUB_SLUGS:
                (out / f"{slug}.html").write_text("hub", encoding="utf-8")
            existing, removed = reconcile_existing_pages(out, {"keep"})
            self.assertEqual(existing, {"keep"})
            self.assertEqual(removed, {"stale"})
            self.assertFalse((out / "stale.html").exists())
            self.assertTrue((out / "index.html").exists())
            for slug in ITEM_HUB_SLUGS:
                self.assertTrue((out / f"{slug}.html").exists())

    def test_item_index_links_each_item_once_and_routes_supplements_to_hub(self):
        output = index_html([{
            "key": "1234567F1234", "name": "対象錠", "maker": "対象製薬", "status": "ok",
            "supplements": ["メーカー：限定出荷"], "hubs": ["supplemental"],
        }], "2026-08-26")
        self.assertIn('href="supplemental.html"', output)
        self.assertIn("販売中止・メーカー補足", output)
        self.assertIn("厚労省公表区分が通常出荷の品目", output)
        self.assertEqual(output.count('href="1234567F1234.html"'), 1)

    def test_recent_recovery_requires_exact_identity_current_normal_and_latest_change(self):
        by_key = {
            "1234567F1234": {"商品名": "回復錠", "YJコード": "1234567F1234",
                              "供給状況": "①通常出荷"},
            "1234567F5678": {"商品名": "再停止錠", "YJコード": "1234567F5678",
                              "供給状況": "⑤供給停止"},
        }
        events = [
            {"date": "2026/08/25", "yj": "1234567F1234", "name": "回復錠",
             "from": "③限定出荷（他社品の影響）", "to": "①通常出荷"},
            {"date": "2026/08/24", "yj": "1234567F5678", "name": "再停止錠",
             "from": "③限定出荷（他社品の影響）", "to": "①通常出荷"},
            {"date": "2026/08/26", "yj": "1234567F5678", "name": "再停止錠",
             "from": "①通常出荷", "to": "⑤供給停止"},
            {"date": "2026/08/25", "yj": "1234567F1234", "name": "別名錠",
             "from": "③限定出荷（他社品の影響）", "to": "①通常出荷"},
        ]
        latest = latest_changes_by_key(events, by_key)
        recovered = recent_recovery_keys(latest, by_key, "2026-08-26")
        self.assertEqual({"1234567F1234"}, recovered)
        self.assertTrue(should_generate(
            by_key["1234567F1234"], "1234567F1234", set(), {}, {}, recovered))

    def test_status_change_loader_rejects_unknown_status(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "status_changes.json"
            path.write_text(
                '[{"date":"2026/08/26","yj":"1234567F1234","name":"対象錠",'
                '"from":"不明","to":"①通常出荷"}]', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_status_changes(path)
            path.write_text(
                '[{"date":"2026/99/99","yj":"1234567F1234","name":"対象錠",'
                '"from":"③限定出荷（他社品の影響）","to":"①通常出荷"}]',
                encoding="utf-8")
            with self.assertRaises(ValueError):
                load_status_changes(path)

    def test_internal_id_change_is_valid_history_but_never_a_recovery_hub_item(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "status_changes.json"
            path.write_text(
                '[{"date":"2026/08/26","yj":"X00001","name":"医療用ガス",'
                '"from":"⑤供給停止","to":"①通常出荷"}]', encoding="utf-8")
            events = load_status_changes(path)
        by_key = {
            "X00001": {"商品名": "医療用ガス", "YJコード": "X00001",
                        "供給状況": "①通常出荷"},
        }
        self.assertEqual({}, latest_changes_by_key(events, by_key))
        self.assertEqual(set(), recent_recovery_keys({}, by_key, "2026-08-26"))

    def test_hub_page_and_sitemap_have_canonical_context_and_unique_urls(self):
        entry = {
            "key": "1234567F1234", "name": "対象錠", "display_name": "対象錠",
            "maker": "対象製薬", "status": "limited", "updated": "2026-08-25",
            "supplements": [], "hubs": ["limited"],
        }
        output = hub_html("limited", [entry], "2026-08-26")
        self.assertEqual(output.count('rel="canonical"'), 1)
        self.assertIn('href="https://tkiyo1007-eng.github.io/drugs-data/items/limited.html"', output)
        self.assertIn('href="1234567F1234.html"', output)
        self.assertIn("実際の受注可否や在庫を示す一覧ではありません", output)
        self.assertIn("厚生労働省の公式システム", output)

        sitemap = sitemap_xml({"1234567F1234": "2026-08-25"}, "2026-08-26", ITEM_HUB_SLUGS)
        for slug in ITEM_HUB_SLUGS:
            self.assertEqual(sitemap.count(f"items/{slug}.html"), 1)

    def test_hub_membership_uses_current_status_supplements_and_verified_recovery(self):
        entry = {"status": "ok", "delist": False, "supplements": [],
                 "recent_recovery": True}
        self.assertEqual(["resumed"], item_hub_slugs(entry, "2026-08-26"))
        entry.update({"status": "limited", "supplements": ["メーカー案内あり"]})
        self.assertEqual(["limited", "supplemental"],
                         item_hub_slugs(entry, "2026-08-26"))

    def test_item_index_keeps_the_context_free_banner(self):
        output = index_html([], "2026-08-16")
        self.assertIn(
            '<meta name="apple-itunes-app" content="app-id=6777696446">',
            output,
        )
        self.assertNotIn("app-argument=", output)
        self.assertIn('../guides/how-to-check-drug-supply.html', output)


if __name__ == "__main__":
    unittest.main()
