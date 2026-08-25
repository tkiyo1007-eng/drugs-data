import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from generate_item_pages import (
    STATUS_NOTES,
    discrepancy_matches,
    index_html,
    latest_publication_date,
    official_row_date,
    page_html,
    reconcile_existing_pages,
    should_generate,
    supplemental_context,
    validated_product_map,
    version_date,
)


class ItemPageMetadataTests(unittest.TestCase):
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
        self.assertIn("メーカー：販売中止予定／メーカー：限定出荷", output)
        self.assertIn("サイト全体の公開データ基準日", output)
        self.assertIn('fetch("../version.json"', output)
        self.assertIn('response.headers.get("X-DSN-Source") === "cache"', output)
        self.assertIn("公開データ基準日が7日以上更新されていません", output)
        self.assertNotIn("全体データ基準日 2026-08-26", output)
        self.assertNotIn("\x08", output)
        self.assertNotIn("メーカーが通常どおり出荷", output)

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

    def test_pages_missing_from_current_csv_are_removed(self):
        with TemporaryDirectory() as directory:
            out = Path(directory)
            (out / "keep.html").write_text("keep", encoding="utf-8")
            (out / "stale.html").write_text("stale", encoding="utf-8")
            (out / "index.html").write_text("index", encoding="utf-8")
            existing, removed = reconcile_existing_pages(out, {"keep"})
            self.assertEqual(existing, {"keep"})
            self.assertEqual(removed, {"stale"})
            self.assertFalse((out / "stale.html").exists())
            self.assertTrue((out / "index.html").exists())

    def test_item_index_keeps_supplemental_items_in_official_status_section_too(self):
        output = index_html([{
            "key": "1234567F1234", "name": "対象錠", "maker": "対象製薬", "status": "ok",
            "supplements": ["メーカー：限定出荷"],
        }], "2026-08-26")
        self.assertIn("メーカー公式の補足情報がある品目", output)
        self.assertIn("厚労省公表区分が通常出荷の品目", output)
        self.assertEqual(output.count('href="1234567F1234.html"'), 2)

    def test_item_index_keeps_the_context_free_banner(self):
        output = index_html([], "2026-08-16")
        self.assertIn(
            '<meta name="apple-itunes-app" content="app-id=6777696446">',
            output,
        )
        self.assertNotIn("app-argument=", output)


if __name__ == "__main__":
    unittest.main()
