import json
import re
import shutil
import subprocess
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
    ingredient_pages,
    item_hub_slugs,
    item_page_lastmod,
    latest_publication_date,
    latest_changes_by_key,
    load_manufacturer_notices,
    load_manufacturer_bulletins,
    manufacturer_notice_changed,
    lifecycle_for_display,
    lifecycle_end_details,
    lifecycle_verification_is_recent,
    supplemental_labels,
    supplemental_bucket,
    manufacturer_notice_index,
    matching_manufacturer_notices,
    manufacturer_notices_html,
    load_status_changes,
    official_row_date,
    page_html,
    page_title,
    pick_siblings,
    recent_recovery_keys,
    recent_restriction_keys,
    reconcile_existing_pages,
    should_generate,
    sitemap_xml,
    supply_metadata_values,
    supplemental_context,
    validated_product_map,
    version_date,
    mhlw_excel_date,
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

    def test_item_page_search_form_routes_encoded_query_to_web_search(self):
        row = {
            "商品名": "テスト錠10mg",
            "一般名": "テスト成分",
            "製造メーカー": "テスト製薬",
            "供給状況": "限定出荷",
            "YJコード": "1234567F1234",
        }
        output = page_html(
            row, "1234567F1234", "limited", "2026-08-28", [],
            {"1234567F1234"},
        )

        self.assertIn('<form class="item-search" id="itemSearchForm" role="search">', output)
        self.assertIn('label for="itemSearchInput">薬品名・成分名・メーカー名・YJコード', output)
        self.assertIn('id="itemSearchInput" type="search" required maxlength="100"', output)
        self.assertIn("検索語はURLの#以降に保持し、アクセス解析には送りません", output)
        self.assertIn('const query = itemSearchInput ? itemSearchInput.value.trim() : "";', output)
        self.assertIn('window.dsnTrack("search-cta-open")', output)
        self.assertIn(
            'location.href = "https://kyokyu-navi.jp/" + '
            '"#q=" + encodeURIComponent(query);',
            output,
        )

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
        self.assertIn('href="https://kyokyu-navi.jp/#item=1234567F1234"', output)
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
        self.assertEqual(item_page_lastmod(old_row), "2026-10-06")
        future_notice = {"product_name": "対象錠", "maker": "対象製薬",
                         "announced_at": "2026-10-13"}
        old_row["製造メーカー"] = "対象製薬"
        self.assertEqual(item_page_lastmod(old_row, future_notice), "2026-10-13")

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

        limited = page_title("テスト錠10mg", "限定出荷", [])
        self.assertIn("限定出荷（出荷調整）", limited)
        self.assertLessEqual(len(limited), 70)

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
        self.assertIn(
            '<a href="limited.html">限定出荷（出荷調整）の一覧</a>',
            output,
        )

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

    def test_recent_restrictions_include_boundary_and_require_current_status_match(self):
        by_key = {
            "boundary": {"供給状況": "②限定出荷（自社の事情）"},
            "today": {"供給状況": "⑤供給停止"},
            "too-old": {"供給状況": "②限定出荷（自社の事情）"},
            "future": {"供給状況": "⑤供給停止"},
            "changed-again": {"供給状況": "⑤供給停止"},
            "same-category": {"供給状況": "③限定出荷（他社品の影響）"},
        }
        latest = {
            "boundary": {"iso_date": "2026-07-27", "from": "①通常出荷",
                         "to": "②限定出荷（自社の事情）"},
            "today": {"iso_date": "2026-08-26", "from": "①通常出荷",
                      "to": "⑤供給停止"},
            "too-old": {"iso_date": "2026-07-26", "from": "①通常出荷",
                        "to": "②限定出荷（自社の事情）"},
            "future": {"iso_date": "2026-08-27", "from": "①通常出荷",
                       "to": "⑤供給停止"},
            "changed-again": {"iso_date": "2026-08-25", "from": "①通常出荷",
                              "to": "②限定出荷（自社の事情）"},
            "same-category": {"iso_date": "2026-08-25",
                              "from": "②限定出荷（自社の事情）",
                              "to": "③限定出荷（他社品の影響）"},
        }

        restricted = recent_restriction_keys(
            latest, by_key, "2026-08-26", days=30)

        self.assertEqual({"boundary", "today"}, restricted)

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
        self.assertIn('href="https://kyokyu-navi.jp/items/limited.html"', output)
        self.assertIn('href="1234567F1234.html"', output)
        self.assertIn("実際の受注可否や在庫を示す一覧ではありません", output)
        self.assertIn("厚生労働省の公式システム", output)

        sitemap = sitemap_xml({"1234567F1234": "2026-08-25"}, "2026-08-26", ITEM_HUB_SLUGS)
        for slug in ITEM_HUB_SLUGS:
            self.assertEqual(sitemap.count(f"items/{slug}.html"), 1)

    def test_recent_restrictions_hub_explains_scope_and_lists_change_date(self):
        entries = [{
            "key": "1234567F1234", "name": "対象錠", "display_name": "対象錠",
            "maker": "対象製薬", "status": "limited", "updated": "2026-08-25",
            "supplements": [], "hubs": ["limited", "recent-restrictions"],
            "latest_change": {"iso_date": "2026-08-24"},
        }]

        output = hub_html("recent-restrictions", entries, "2026-08-26")

        self.assertIn("<title>最近、限定出荷・供給停止になった医薬品一覧", output)
        self.assertIn("<h1>最近、限定出荷・供給停止になった医薬品一覧</h1>", output)
        self.assertIn("recent-restrictions.html", output)
        self.assertIn("実際の制限開始日、受注可否、流通在庫を示す一覧ではありません", output)
        self.assertIn("限定出荷へ変更 2026-08-24", output)
        self.assertIn('href="1234567F1234.html"', output)

        limited = hub_html("limited", entries, "2026-08-26")
        self.assertIn("<title>限定出荷（出荷調整）の医薬品一覧", limited)
        self.assertIn("<h1>限定出荷（出荷調整）の医薬品一覧</h1>", limited)

    def test_hub_membership_uses_current_status_supplements_and_verified_recovery(self):
        entry = {"status": "ok", "delist": False, "supplements": [],
                 "recent_recovery": True}
        self.assertEqual(["resumed"], item_hub_slugs(entry, "2026-08-26"))
        entry.update({"status": "limited", "supplements": ["メーカー案内あり"],
                      "recent_restriction": True})
        self.assertEqual(["limited", "supplemental", "recent-restrictions"],
                         item_hub_slugs(entry, "2026-08-26"))

    def test_item_index_keeps_the_context_free_banner(self):
        output = index_html([], "2026-08-16")
        self.assertIn(
            '<meta name="apple-itunes-app" content="app-id=6777696446">',
            output,
        )
        self.assertNotIn("app-argument=", output)
        self.assertIn('../guides/how-to-check-drug-supply.html', output)


    def test_item_page_links_to_ingredient_page_only_when_generated(self):
        row = {"商品名": "テスト錠10mg", "一般名": "テスト成分", "製造メーカー": "テスト製薬",
               "供給状況": "③限定出荷（他社品の影響）", "更新日": "2026/08/20", "YJコード": "1234567F1234"}
        linked = page_html(row, "1234567F1234", "limited", "2026-08-28", [], {"1234567F1234"},
                           ingredient_slugs={"テスト成分": "1234567"})
        self.assertIn('<a href="../ingredients/1234567.html" data-dsn-event="related-item-open">'
                      'テスト成分の全品目の供給状況を見る</a>', linked)
        self.assertIn("代替の候補を示すものではありません", linked)
        unlinked = page_html(row, "1234567F1234", "limited", "2026-08-28", [], {"1234567F1234"},
                             ingredient_slugs={"別成分": "7654321"})
        self.assertNotIn("../ingredients/", unlinked)

    def test_ingredient_slugs_match_curated_ingredient_pages(self):
        try:
            from generate_curated_pages import ingredient_groups
        except ImportError:  # Web版リポジトリには成分ページ生成器がない
            self.skipTest("generate_curated_pages.py がありません")
        rows = [
            {"一般名": "A成分", "YJコード": "1111111F1011", "供給状況": "③限定出荷"},
            {"一般名": "A成分", "YJコード": "1111111F2011", "供給状況": "④通常出荷"},
            {"一般名": "B成分", "YJコード": "1111111F3011", "供給状況": "④通常出荷"},
            {"一般名": "B成分", "YJコード": "1111111F4011", "供給状況": "④通常出荷"},
            {"一般名": "B成分", "YJコード": "1111111F5011", "供給状況": "④通常出荷"},
            {"一般名": "C成分", "YJコード": "2222222F1011", "供給状況": "④通常出荷"},
            {"一般名": "C成分", "YJコード": "2222222F2011", "供給状況": "④通常出荷"},
            {"一般名": "D成分", "YJコード": "", "供給状況": "①供給停止"},
            {"一般名": "D成分", "YJコード": "", "供給状況": "①供給停止"},
        ]
        csv_path = Path(__file__).resolve().parents[1] / "drugs_app_ready.csv"
        if csv_path.exists():
            import csv
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                rows += list(csv.DictReader(f))
        expected = {group["name"]: slug for slug, group in ingredient_groups(rows).items()}
        self.assertEqual(expected, ingredient_pages(rows))
        self.assertNotIn("C成分", ingredient_pages(rows))


class VerifiedManufacturerNoticeTests(unittest.TestCase):
    def row(self):
        return {"商品名": "テスト錠10mg「ケミファ」", "一般名": "テスト成分",
                "製造メーカー": "日本ケミファ", "販売メーカー": "日本薬品工業・日本ケミファ",
                "供給状況": "①通常出荷", "理由": "７．－", "更新日": "2026/07/07",
                "YJコード": "2329028F1210"}

    def notice(self):
        return {"id": "test-notice", "maker": "日本薬品工業", "title": "10mg 500T 限定出荷案内",
                "url": "https://www.npi-inc.co.jp/medical/info/file/1269", "announced_at": "2026-10",
                "listed_at": "2026-10-13", "verified_at": "2026-10-14", "sha256": "a" * 64,
                "event_type": "limited", "reason": "製造工程上の確認事項により入庫が遅延",
                "targets": [{"product_name": "テスト錠10mg「ケミファ」", "yj_code": "2329028F1210",
                             "scope": "seller_route_and_package", "seller": "日本薬品工業",
                             "packages": [{"package": "500T", "unified_product_code": "440576059"}]}],
                "alternatives": [], "cautions": ["今回案内は日本薬品工業販売品500Tだけが対象"]}

    def test_optional_registry_missing_preserves_existing_behavior_but_invalid_present_fails(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manufacturer_notices.json"
            self.assertEqual([], load_manufacturer_notices(path))
            document = {"schema_version": 1, "notices": [self.notice()]}
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(document["notices"], load_manufacturer_notices(path))
            for mutation in (lambda n: n.update(sha256="bad"),
                             lambda n: n.update(url="javascript:alert(1)"),
                             lambda n: n.update(verified_at="2026-13-01"),
                             lambda n: n["targets"][0].update(packages=[{}]),
                             lambda n: n["targets"][0].update(seller="")):
                invalid = self.notice()
                mutation(invalid)
                path.write_text(json.dumps({"schema_version": 1, "notices": [invalid]}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_manufacturer_notices(path)
            path.write_text('{broken', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manufacturer_notices(path)

    def test_notice_requires_yj_name_and_maker_identity(self):
        notice = self.notice()
        index = manufacturer_notice_index([notice])
        self.assertEqual([notice], index["2329028F1210"])
        self.assertEqual(1, len(matching_manufacturer_notices(self.row(), [notice])))
        for field, value in (("YJコード", "2329028F2216"), ("商品名", "別の錠10mg「ケミファ」")):
            row = dict(self.row(), **{field: value})
            self.assertEqual([], matching_manufacturer_notices(row, [notice]))
        row = dict(self.row(), 製造メーカー="別メーカー", 販売メーカー="別販売元")
        self.assertEqual([], matching_manufacturer_notices(row, [notice]))
        self.assertEqual("", manufacturer_notices_html(row, [notice]))

    def test_normal_supply_page_preserves_mhlw_and_displays_only_target_seller_package(self):
        row, notice = self.row(), self.notice()
        self.assertFalse(should_generate(row, row["YJコード"], set(), {}, {}))
        self.assertTrue(should_generate(row, row["YJコード"], set(), {}, {}, manufacturer_notices=[notice]))
        output = page_html(row, row["YJコード"], "ok", "2026-10-14", [], {row["YJコード"]},
                           manufacturer_notices=[notice])
        self.assertIn("厚労省：通常出荷", output)
        self.assertIn("確認済みメーカー案内", output)
        self.assertIn("対象範囲：販売経路・一部包装｜販売元：日本薬品工業｜対象包装：500T", output)
        self.assertIn("原典の案内年月日：2026-10｜", output)
        self.assertIn("原文確認日：2026-10-14", output)
        self.assertNotIn("原典の案内年月日：2026-10-13", output)
        self.assertIn('data-source-sha256="' + "a" * 64 + '"', output)
        self.assertIn("メーカー説明の理由：製造工程上の確認事項により入庫が遅延", output)

    def test_future_recovery_is_explicitly_a_plan_without_changing_current_supply(self):
        row = dict(self.row(), 供給状況="②限定出荷（自社の事情）")
        notice = self.notice()
        notice.update(event_type="resumption_planned", resumption={"text": "2026年10月中旬より通常出荷再開予定"})
        output = page_html(row, row["YJコード"], "limited", "2026-10-14", [], {row["YJコード"]},
                           manufacturer_notices=[notice])
        self.assertIn("厚労省：限定出荷", output)
        self.assertIn("2026年10月中旬より通常出荷再開予定", output)
        self.assertIn("再開の実施日は確認できていません", output)
        self.assertNotIn("厚労省：通常出荷", output)

    def test_indication_groups_candidate_conditions_and_target_filter_are_preserved_and_escaped(self):
        notice = self.notice()
        notice["alternatives"] = [
            {"indication": "慢性便秘症（器質的疾患による便秘を除く）", "type": "別成分の参考候補",
             "products": [{"name": "候補<錠>", "yj_code": "2344009F1035"}],
             "cautions": ["候補の在庫は未確認"]},
            {"indication": "高アンモニア血症に伴う症候の改善", "type": "同一般名・含有量の異なる候補",
             "products": [{"name": "ラクツロース・シロップ60%「コーワ」"}],
             "cautions": ["慢性便秘症の場合は変更調剤できません", "成分含有量が異なるため処方元への確認が必要"]},
            {"indication": "別規格のみ", "products": [{"name": "非対象の候補"}],
             "target_yj_codes": ["2329028F2216"]}]
        notice["reason"] = '</p><script>alert(1)</script>'
        output = manufacturer_notices_html(self.row(), [notice], catalog_yj_codes={"2344009F1035"})
        self.assertIn("慢性便秘症（器質的疾患による便秘を除く）", output)
        self.assertIn("高アンモニア血症に伴う症候の改善", output)
        self.assertIn("慢性便秘症の場合は変更調剤できません", output)
        self.assertIn("候補&lt;錠&gt;", output)
        self.assertIn("&lt;/p&gt;&lt;script&gt;", output)
        self.assertNotIn("<script>", output)
        self.assertNotIn("非対象の候補", output)
        self.assertIn('https://kyokyu-navi.jp/#item=2344009F1035', output)

    def test_manual_notice_lastmod_is_not_advanced_by_generation_or_daily_attempt(self):
        row, notice = self.row(), self.notice()
        self.assertEqual("2026-10-14", item_page_lastmod(row, manufacturer_notices=[notice]))
        notice["listed_at"] = "2026-10-20"
        self.assertEqual("2026-10-14", item_page_lastmod(row, manufacturer_notices=[notice]))
        notice["content_updated_at"] = "2026-10-16"
        self.assertEqual("2026-10-16", item_page_lastmod(row, manufacturer_notices=[notice]))
        notice["targets"][0]["product_name"] = "別の品目"
        self.assertEqual("2026-10-06", item_page_lastmod(row, manufacturer_notices=[notice]))


    def test_discontinuation_timing_device_candidate_and_no_candidate_statement_are_not_reinterpreted(self):
        notice = self.notice()
        notice["event_type"] = "discontinued"
        notice["targets"][0]["planned_timing"] = "2027年12月"
        notice["alternatives"] = [{"type": "医療機器の参考候補", "products": [
            {"name": "候補医療機器", "product_kind": "medical_device", "source_class": "IV 高度管理医療機器",
             "scope": "一部包装のみ"}]},
            {"type": "メーカー回答", "products": [], "no_alternative_statement": "了承を得られている代替候補製品はありません"}]
        output = manufacturer_notices_html(self.row(), [notice])
        self.assertIn("販売中止予定時期：2027年12月", output)
        self.assertNotIn("再開・解除に関する案内：2027年12月", output)
        self.assertIn("医療機器（IV 高度管理医療機器）", output)
        self.assertIn("対象規格・包装：一部包装のみ", output)
        self.assertIn("了承を得られている代替候補製品はありません", output)
        self.assertNotIn("候補医療機器</a>", output)
        notice["targets"][0]["planned_timing"] = "出荷停止中"
        self.assertIn("メーカーが案内した状況：出荷停止中", manufacturer_notices_html(self.row(), [notice]))

    def test_recall_lots_are_limited_to_the_current_strength_and_resumption_keeps_approximate_precision(self):
        row = dict(self.row(), 商品名='ゾニサミドOD錠25mgTRE「サンド」', 製造メーカー="サンド", 販売メーカー="サンド")
        notice = self.notice()
        notice["maker"] = "サンド"
        notice["targets"][0].update(product_name=row["商品名"], maker="サンド")
        notice.update(event_type="recall", recall_class="II", recall_started_at="2026-10-13",
                      recall_scope="一部包装・対象ロット", lots=[
                          {"strength": "25mg", "package": "PTP100錠", "lot": "L0002"},
                          {"strength": "50mg", "package": "PTP100錠", "lot": "L0003"}])
        output = manufacturer_notices_html(row, [notice])
        self.assertIn("自主回収区分：クラスII｜回収開始日：2026-10-13", output)
        self.assertIn("対象ロット：L0002", output)
        self.assertNotIn("L0003", output)
        notice.update(event_type="stopped", expected_resumption={"display": "2027年春頃予定"})
        output = manufacturer_notices_html(row, [notice])
        self.assertIn("出荷再開見込み（メーカー予定）：2027年春頃予定", output)
        self.assertNotIn("2027-03-01", output)

    def test_full_verification_timestamp_is_accepted_but_no_timezone_is_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manufacturer_notices.json"
            notice = self.notice()
            notice["verified_at"] = "2026-10-14T01:09:07+09:00"
            path.write_text(json.dumps({"schema_version": 1, "notices": [notice]}), encoding="utf-8")
            self.assertEqual([notice], load_manufacturer_notices(path))
            self.assertIn("原文確認日：2026-10-14", manufacturer_notices_html(self.row(), [notice]))
            notice["verified_at"] = "2026-10-14T01:09:07"
            path.write_text(json.dumps({"schema_version": 1, "notices": [notice]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manufacturer_notices(path)


    def test_removed_candidate_keeps_historical_name_without_current_item_link(self):
        notice = self.notice()
        notice["alternatives"] = [{"type": "原典の参考候補", "products": [
            {"name": "収録済み候補錠", "yj_code": "2344009F1035"},
            {"name": "削除された候補錠", "yj_code": "2344009F1086", "archived_from_csv_at": "2026-10-14"}]}]
        output = manufacturer_notices_html(self.row(), [notice], catalog_yj_codes={"2344009F1035"})
        self.assertIn('href="https://kyokyu-navi.jp/#item=2344009F1035"', output)
        self.assertIn("削除された候補錠", output)
        self.assertIn("現在のCSVに収録なし・原典記載の過去候補", output)
        self.assertNotIn('#item=2344009F1086', output)
        restored = manufacturer_notices_html(self.row(), [notice], catalog_yj_codes={"2344009F1035", "2344009F1086"})
        self.assertIn('#item=2344009F1086', restored)

    def test_changed_source_replaces_reason_and_candidates_with_recheck_warning(self):
        notice = self.notice()
        notice["alternatives"] = [{"products": [{"name": "以前の参考候補", "yj_code": "2344009F1035"}]}]
        bulletins = {"schema_version": 1, "items": [{"url": notice["url"], "sha256": "b" * 64}]}
        self.assertTrue(manufacturer_notice_changed(notice, bulletins))
        output = manufacturer_notices_html(self.row(), [notice], catalog_yj_codes={"2344009F1035"}, bulletins=bulletins)
        self.assertIn("原典更新を検出・再確認待ち", output)
        self.assertNotIn(notice["reason"], output)
        self.assertNotIn("以前の参考候補", output)
        self.assertNotIn('#item=2344009F1035', output)
        self.assertIn(notice["url"], output)
        bulletins["items"][0].pop("sha256")
        self.assertFalse(manufacturer_notice_changed(notice, bulletins))
        self.assertIn(notice["reason"], manufacturer_notices_html(self.row(), [notice], bulletins=bulletins))

    def test_optional_bulletins_missing_is_not_a_claim_of_matching_hash(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manufacturer_bulletins.json"
            self.assertIsNone(load_manufacturer_bulletins(path))
            path.write_text(json.dumps({"schema_version": 1, "items": [{"url": self.notice()["url"], "sha256": "a" * 64}]}), encoding="utf-8")
            self.assertFalse(manufacturer_notice_changed(self.notice(), load_manufacturer_bulletins(path)))
            path.write_text(json.dumps({"schema_version": 1, "items": [{"url": "javascript:alert(1)", "sha256": "a" * 64}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_manufacturer_bulletins(path)


    def lifecycle(self):
        row, notice = self.row(), self.notice()
        return {"product_name": row["商品名"], "maker": notice["maker"],
                "state": "discontinuation_announced", "announced_at": "2026-10",
                "verified_at": "2026-10-14", "source_url": notice["url"],
                "source_title": "前回の販売中止案内", "supply_end_source_url": notice["url"],
                "supply_end_expected": "2027-12", "supply_end_note": "在庫により前後する以前の条件",
                "supply_end_packages": ["以前の100錠包装"], "supply_end_verified_at": "2026-10-14"}

    def test_lifecycle_hash_guard_is_ephemeral_and_requires_known_url_hash_mismatch(self):
        notice, lifecycle = self.notice(), self.lifecycle()
        before = json.dumps(lifecycle, ensure_ascii=False, sort_keys=True)
        changed = {"items": [{"url": notice["url"], "sha256": "b" * 64}]}
        display = lifecycle_for_display(lifecycle, [notice], changed)
        self.assertTrue(display["source_changed"])
        self.assertEqual(before, json.dumps(lifecycle, ensure_ascii=False, sort_keys=True))
        self.assertFalse(lifecycle_verification_is_recent(display, "2026-10-14"))
        self.assertEqual("", lifecycle_end_details(display))
        alternate_source = dict(lifecycle, source_url="https://example.test/other.pdf")
        self.assertTrue(lifecycle_for_display(alternate_source, [notice], changed)["source_changed"])
        for observations in (None, {"items": []}, {"items": [{"url": notice["url"]}]},
                             {"items": [{"url": notice["url"], "sha256": "a" * 64}]},
                             {"items": [{"url": "https://example.test/unrelated.pdf", "sha256": "b" * 64}]}):
            with self.subTest(observations=observations):
                self.assertIs(lifecycle, lifecycle_for_display(lifecycle, [notice], observations))
        self.assertIs(lifecycle, lifecycle_for_display(lifecycle, [], changed))

    def test_changed_lifecycle_page_hides_current_assertion_end_conditions_and_packages(self):
        row, notice, lifecycle = self.row(), self.notice(), self.lifecycle()
        bulletins = {"items": [{"url": notice["url"], "sha256": "b" * 64}], "checked": "2026-10-20"}
        output = page_html(row, row["YJコード"], "ok", "2026-10-20", [], {row["YJコード"]},
                           lifecycle=lifecycle, supplemental_checked_date="2026-10-14",
                           manufacturer_notices=[notice], manufacturer_bulletins=bulletins)
        self.assertIn("厚労省：通常出荷", output)
        self.assertIn("メーカー公式：原典更新・再確認待ち", output)
        self.assertIn("前回の公表年月日：2026-10", output)
        self.assertNotIn("メーカー公式：販売中止予定", output)
        self.assertNotIn("メーカー：販売中止予定", output)
        for value in ("終了予定時期：", "2027-12", lifecycle["supply_end_note"], lifecycle["supply_end_packages"][0], "終了予定の原文確認日"):
            self.assertNotIn(value, output)
        self.assertEqual("2026-10-14", item_page_lastmod(row, lifecycle, manufacturer_notices=[notice], manufacturer_bulletins=bulletins))
        self.assertIn('"dateModified":"2026-10-14"', output)

    def test_changed_lifecycle_hub_is_pending_and_does_not_search_stale_end_details(self):
        row, notice = self.row(), self.notice()
        lifecycle = lifecycle_for_display(self.lifecycle(), [notice], {"items": [{"url": notice["url"], "sha256": "b" * 64}]})
        labels = supplemental_labels(row, lifecycle, reference_date="2026-10-14")
        self.assertEqual(["メーカー原典更新・再確認待ち"], labels)
        entry = {"key": row["YJコード"], "name": row["商品名"], "maker": notice["maker"],
                 "status": "ok", "updated": "2026-07-07", "lifecycle": lifecycle,
                 "lifecycle_current": False, "supplements": labels, "hubs": ["supplemental"]}
        self.assertEqual("maker-notices", supplemental_bucket(entry))
        output = hub_html("supplemental", [entry], "2026-10-14")
        self.assertIn("メーカー原典更新・再確認待ち", output)
        self.assertIn("現在の厚労省区分：通常出荷", output)
        for value in ("終了予定時期：", "2027-12", lifecycle["supply_end_note"], lifecycle["supply_end_packages"][0]):
            self.assertNotIn(value, output)
        entry["status"] = "ended"
        self.assertEqual("sales-notices", supplemental_bucket(entry))

    def test_fresh_lifecycle_verification_with_partial_health_does_not_claim_seven_day_age(self):
        row, lifecycle = self.row(), self.lifecycle()
        health = {"checked": "2026-10-14", "sources": [{"source": "parse_towa", "ok": True}],
                  "last_attempt": {"checked": "2026-10-14", "status": "partial", "sources": [
                      {"source": "parse_kemifa", "ok": False, "retained": True, "error": "timeout"}]}}
        discrepancy = {"source": {"mhlw_note": "2026年10月14日", "manufacturer_checked_through": "2026-10-14"}}
        context = supplemental_context(health, discrepancy, "2026-10-14")
        self.assertTrue(lifecycle_verification_is_recent(lifecycle, context["checked"]))
        self.assertFalse(context["trusted"])
        output = page_html(row, row["YJコード"], "ok", "2026-10-14", [], {row["YJコード"]},
                           lifecycle=lifecycle, supplemental_checked_date=context["checked"],
                           supplemental_trusted=context["trusted"], supplemental_warning=context["warning"])
        self.assertIn("案内の最終確認日：2026-10-14", output)
        self.assertIn("案内の確認状態が完全でない、確認日が古い、または確認日を取得できません", output)
        self.assertNotIn("確認日が7日以上前のため", output)
        self.assertNotIn("メーカー公式：販売中止予定", output)
        self.assertIn("厚労省：通常出荷", output)
        self.assertIn('"dateModified":"2026-10-14"', output)
        entry = {"key": row["YJコード"], "name": row["商品名"], "maker": lifecycle["maker"],
                 "status": "ok", "updated": "2026-07-07", "lifecycle": lifecycle,
                 "lifecycle_current": False, "supplements": supplemental_labels(
                     row, lifecycle, reference_date=context["checked"], trusted=context["trusted"]),
                 "hubs": ["supplemental"]}
        hub = hub_html("supplemental", [entry], "2026-10-14")
        self.assertIn("案内の確認状態が完全でない、確認日が古い、または確認日を取得できません", hub)
        self.assertNotIn("案内の確認が古い、または確認状態が不明", hub)
        self.assertIn("案内の最終確認：2026-10-14", hub)

    def test_partial_latest_collection_retains_last_complete_date_and_warns_with_attempt_date(self):
        health = {"checked": "2026-10-08", "sources": [{"source": "parse_towa", "ok": True}],
                  "last_attempt": {"checked": "2026-10-14", "status": "partial", "sources": [
                      {"source": "parse_towa", "ok": False, "retained": True, "error": "timeout"}]}}
        discrepancy = {"source": {"mhlw_note": "2026年10月14日", "manufacturer_checked_through": "2026-10-08"}}
        context = supplemental_context(health, discrepancy, "2026-10-14")
        self.assertEqual("2026-10-08", context["checked"])
        self.assertFalse(context["trusted"])
        self.assertIn("2026-10-14", context["warning"])
        self.assertIn("東和薬品", context["warning"])
        health["last_attempt"]["status"] = "success"
        health["last_attempt"]["sources"][0]["ok"] = True
        self.assertTrue(supplemental_context(health, discrepancy, "2026-10-14")["trusted"])


class DatasetSourceDateTests(unittest.TestCase):
    import_date = "2026-10-14"
    row = {"商品名": "日付検証錠", "供給状況": "限定出荷",
           "更新日": "2024/03/11", "ステータス更新日": "2024/03/12",
           "YJコード": "1234567F1234", "製造メーカー": "検証製薬"}

    def version(self, source="2026-10-08", imported="2026-10-14"):
        return {"note": imported + "厚労省データ反映", "mhlw_excel_date": source}

    def page(self, metadata=None, imported="2026-10-14"):
        return page_html(self.row, "1234567F1234", "limited", "2099-01-01", [],
                         {"1234567F1234"}, dataset_date=imported,
                         version_metadata=metadata)

    def visible_date_block(self, output):
        return re.search(r'<p class="dataset-context">(.*?)</p>', output, re.S).group(1)

    def test_explicit_source_date_is_distinct_from_import_and_item_dates(self):
        metadata = self.version()
        self.assertEqual("2026-10-08", mhlw_excel_date(metadata, self.import_date))
        output = self.page(metadata)
        block = self.visible_date_block(output)
        self.assertIn('class="mhlw-excel-date" aria-live="polite">2026-10-08</span>', block)
        self.assertIn('class="dataset-date" aria-live="polite">2026-10-14</span>', block)
        self.assertIn("サイト取込日", block)
        self.assertIn("HTML生成時の確認情報です", block)
        self.assertNotIn("2024-03-11", block)
        self.assertNotIn("2099-01-01", block)
        self.assertIn("<th scope=\"row\">更新日</th><td>2024/03/11</td>", output)
        self.assertIn("2024-03-12", output)

    def test_legacy_missing_source_does_not_guess_from_import_or_row(self):
        for metadata in (None, {}, {"version": 202610080000},
                         {"note": "2026年10月14日厚労省データ反映"}):
            with self.subTest(metadata=metadata):
                self.assertEqual("", mhlw_excel_date(metadata, self.import_date))
                block = self.visible_date_block(self.page(metadata))
                self.assertIn('class="mhlw-excel-date" aria-live="polite">確認できません</span>', block)
                self.assertIn('class="dataset-date" aria-live="polite">2026-10-14</span>', block)

    def test_source_validation_rejects_invalid_after_import_and_mixed_metadata(self):
        for value in (None, False, 20261008, "", "2026/10/08", "2026-10-8",
                      "2026-02-30", "0000-10-08", "2026-10-08T00:00:00Z", " 2026-10-08",
                      "２０２６-１０-０８", "2026-10-15", "2099-10-08"):
            with self.subTest(source=value):
                self.assertEqual("", mhlw_excel_date(self.version(value), self.import_date))
        for metadata in ([self.version()], self.version(imported="2026-10-08"),
                         {"mhlw_excel_date": "2026-10-08"}):
            with self.subTest(metadata=metadata):
                self.assertEqual("", mhlw_excel_date(metadata, self.import_date))
        self.assertEqual("2026-10-14", mhlw_excel_date(self.version("2026-10-14"), self.import_date))
        self.assertEqual("2024-02-29", mhlw_excel_date(self.version("2024-02-29", "2024-03-01"), "2024-03-01"))

    def test_import_date_accepts_only_typed_metadata_and_real_calendar_dates(self):
        for metadata, expected in (
            ({"note": "2026年10月14日厚労省データ反映"}, "2026-10-14"),
            ({"version": 202610140514}, "2026-10-14"),
            ({"version": "202610140514"}, "2026-10-14"),
            ({"note": ["2026年10月14日"], "version": 202610140514}, "2026-10-14"),
            ({"note": "2024年2月29日"}, "2024-02-29"),
            ({"note": "2026年2月30日"}, ""),
            ({"note": "2026年2月30日", "version": 202610140514}, ""),
            ({"note": "2026年13月14日"}, ""),
            ({"note": "0000年10月14日"}, ""),
            ({"version": 202602300000}, ""),
            ({"note": ["2026年10月14日厚労省データ反映"]}, ""),
            ({"note": {"value": "2026年10月14日"}}, ""),
            ({"note": 20261014}, ""),
            ({"version": [202610140514]}, ""),
            ({"version": {"value": "2026年10月14日"}}, ""),
            ({"version": True}, ""),
            (None, ""), ([{"note": "2026年10月14日"}], ""),
        ):
            with self.subTest(metadata=metadata):
                self.assertEqual(expected, version_date(metadata))

    def test_nojs_invalid_import_metadata_shows_both_dates_unknown(self):
        for metadata in (
            {"note": "2026年2月30日厚労省データ反映", "mhlw_excel_date": "2026-02-28"},
            {"note": ["2026年10月14日厚労省データ反映"], "mhlw_excel_date": "2026-10-08"},
            {"version": [202610140514], "mhlw_excel_date": "2026-10-08"},
            [{"note": "2026年10月14日厚労省データ反映"}],
        ):
            with self.subTest(metadata=metadata):
                imported = version_date(metadata)
                output = self.page(metadata, imported=imported)
                block = self.visible_date_block(output)
                self.assertEqual(2, block.count("確認できません"))
                self.assertNotIn("2026-02-30", block)
                self.assertNotIn("2026-10-14", block)

    def test_source_validation_does_not_depend_on_generation_or_device_clock(self):
        metadata = self.version("2099-10-08", "2099-10-14")
        self.assertEqual("2099-10-08", mhlw_excel_date(metadata, "2099-10-14"))

    def test_index_and_all_five_hubs_show_both_dates_without_advancing_metadata(self):
        entry = {"key": "1234567F1234", "name": "日付検証錠", "maker": "検証製薬",
                 "status": "limited", "updated": "2024-03-11", "supplements": [],
                 "hubs": list(ITEM_HUB_SLUGS)}
        for slug in ITEM_HUB_SLUGS:
            with self.subTest(slug=slug):
                old = hub_html(slug, [entry], self.import_date)
                output = hub_html(slug, [entry], self.import_date, self.version())
                block = self.visible_date_block(output)
                self.assertIn(">2026-10-08</span>", block)
                self.assertIn(">2026-10-14</span>", block)
                self.assertIn("HTML生成時の確認情報です", block)
                self.assertEqual(re.findall(r'"dateModified":"([^"]+)"', old),
                                 re.findall(r'"dateModified":"([^"]+)"', output))
        output = index_html([entry], self.import_date, self.version())
        self.assertIn(">2026-10-08</span>", self.visible_date_block(output))
        self.assertIn(">2026-10-14</span>", self.visible_date_block(output))
        for metadata in (None, self.version("2026-10-15"), self.version(imported="2026-10-08")):
            self.assertIn('class="mhlw-excel-date" aria-live="polite">確認できません</span>',
                          self.visible_date_block(index_html([entry], self.import_date, metadata)))

    def test_date_display_does_not_change_item_publication_or_sitemap_dates(self):
        old = self.page()
        output = self.page(self.version())
        self.assertEqual(re.findall(r'"dateModified":"([^"]+)"', old),
                         re.findall(r'"dateModified":"([^"]+)"', output))
        self.assertEqual([item_page_lastmod(self.row)],
                         re.findall(r'"dateModified":"([^"]+)"', output))
        sitemap = sitemap_xml({"1234567F1234": item_page_lastmod(self.row)}, "2099-01-01")
        self.assertIn("items/1234567F1234.html</loc><lastmod>" + item_page_lastmod(self.row) + "</lastmod>", sitemap)
        self.assertNotIn("items/1234567F1234.html</loc><lastmod>2099-01-01", sitemap)

    @unittest.skipUnless(shutil.which("node"), "Node.jsがありません")
    def test_generated_script_handles_old_invalid_mixed_cached_and_clock_cases(self):
        script = re.search(r'<script>\s*(\(function\(\).*?)</script>', self.page(self.version()), re.S).group(1)
        runner = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {'.dataset-date': [{textContent:'generated'}], '.mhlw-excel-date': [{textContent:'generated'}], '.dataset-date-context': [{textContent:'generated'}]};
const warning = {textContent:'', hidden:true};
global.document = {getElementById: id => id === 'datasetWarning' ? warning : null, querySelectorAll: selector => nodes[selector] || []};
global.localStorage = {getItem: () => '[]'};
global.addEventListener = () => {};
Date.now = () => 0;
global.fetch = async () => {
  if(input.failed) throw new Error('unavailable');
  return {ok:true, headers:{get: () => input.cached ? 'cache' : null}, json:async () => input.version};
};
vm.runInThisContext(input.script);
setImmediate(() => process.stdout.write(JSON.stringify({source:nodes['.mhlw-excel-date'][0].textContent, imported:nodes['.dataset-date'][0].textContent, context:nodes['.dataset-date-context'][0].textContent, warning})));
"""
        cases = [
            ({"note": "2026年10月14日厚労省データ反映"}, False, False, "確認できません", "2026-10-14"),
            (self.version(), False, False, "2026-10-08", "2026-10-14"),
            (self.version("2026-02-30"), False, False, "確認できません", "2026-10-14"),
            ({"note": "2026年2月30日厚労省データ反映", "mhlw_excel_date": "2026-02-28"}, False, False, "確認できません", "確認できません"),
            ({"note": "2026年2月30日厚労省データ反映", "mhlw_excel_date": "2026-02-28"}, True, False, "確認できません", "確認できません"),
            (self.version("0000-10-08"), False, False, "確認できません", "2026-10-14"),
            (self.version("2026-10-15"), False, False, "確認できません", "2026-10-14"),
            ({"mhlw_excel_date": "2026-10-08"}, False, False, "確認できません", "確認できません"),
            ({"note": ["2026年10月14日厚労省データ反映"], "mhlw_excel_date": "2026-10-08"}, False, False, "確認できません", "確認できません"),
            ({"version": [202610140514], "mhlw_excel_date": "2026-10-08"}, False, False, "確認できません", "確認できません"),
            ({"version": True, "mhlw_excel_date": "2026-10-08"}, False, False, "確認できません", "確認できません"),
            ([{"note": "2026年10月14日"}], False, False, "確認できません", "確認できません"),
            ({"version": 202610140514, "mhlw_excel_date": "2026-10-08"}, False, False, "2026-10-08", "2026-10-14"),
            (self.version(), True, False, "確認できません", "2026-10-14（前回取得）"),
            (self.version(), False, True, "確認できません", "確認できません"),
            (self.version("2099-10-08", "2099-10-14"), False, False, "2099-10-08", "2099-10-14"),
        ]
        for metadata, cached, failed, source, imported in cases:
            with self.subTest(metadata=metadata, cached=cached, failed=failed):
                result = subprocess.run([shutil.which("node"), "-e", runner], input=json.dumps(
                    {"script":script, "version":metadata, "cached":cached, "failed":failed}),
                    capture_output=True, text=True, check=True)
                rendered = json.loads(result.stdout)
                self.assertEqual(source, rendered["source"])
                self.assertEqual(imported, rendered["imported"])
                self.assertNotEqual("generated", rendered["context"])


if __name__ == "__main__":
    unittest.main()
