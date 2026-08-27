import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_product_lifecycle import (
    PARTIAL_RE,
    announcement_date,
    announcement_covers_product,
    announcement_identifies_product_as_new_release,
    announcement_targets_product,
    backfill_announcement_dates,
    event_last_checked_by_url,
    existing_record_needs_reverification,
    is_product_wide_discontinuation,
    lifecycle_verified_at,
    verified_group_announcements,
    verified_group_scopes,
)
from scripts.fetch_maker_announcements import match_to_csv
from scripts.validate_product_lifecycle import validate


class ProductLifecycleTests(unittest.TestCase):
    def test_verified_tatsumi_and_maruishi_hosts_are_accepted(self):
        cases = (
            ("2190101F1063", "辰巳化学", "https://www.tatsumi-kagaku.com/notice.pdf"),
            ("2614700X1441", "丸石製薬", "https://www.maruishi-pharm.co.jp/notice.pdf"),
        )
        for yj_code, maker, source_url in cases:
            with self.subTest(maker=maker):
                document, rows = self._lifecycle_fixture(yj_code, maker, source_url)
                self.assertEqual(validate(document, rows), [])

    def test_alias_and_delimited_seller_match_through_validator(self):
        cases = (
            (
                "1141007C1148",
                "日本ジェネリック",
                "https://www.nihon-generic.co.jp/notice.pdf",
                "長生堂製薬",
                "長生堂製薬",
            ),
            (
                "2260700F1145",
                "日本ケミファ",
                "https://www.nc-medical.com/notice.pdf",
                "東亜薬品",
                "日本ケミファ・沢井製薬",
            ),
        )
        for yj_code, maker, source_url, manufacturer, seller in cases:
            with self.subTest(maker=maker):
                document, rows = self._lifecycle_fixture(
                    yj_code,
                    maker,
                    source_url,
                    manufacturer,
                    seller,
                )
                self.assertEqual(validate(document, rows), [])

    def test_similar_but_unofficial_host_is_rejected(self):
        document, rows = self._lifecycle_fixture(
            "2190101F1063",
            "辰巳化学",
            "https://evil-tatsumi-kagaku.com/notice.pdf",
        )
        self.assertTrue(any("公式ドメインではありません" in error for error in validate(document, rows)))

    @staticmethod
    def _lifecycle_fixture(yj_code, maker, source_url, manufacturer="", seller=""):
        product_name = "テスト錠１ｍｇ"
        document = {
            "schema_version": 1,
            "generated_at": "2026-08-28T09:00:00+09:00",
            "products": {
                yj_code: {
                    "product_name": product_name,
                    "maker": maker,
                    "state": "discontinuation_announced",
                    "source_title": "販売中止のお知らせ",
                    "source_url": source_url,
                    "verified_at": "2026-08-28",
                }
            },
        }
        rows = {
            yj_code: {
                "商品名": product_name,
                "製造メーカー": manufacturer or maker,
                "販売メーカー": seller or maker,
            }
        }
        return document, rows

    def test_known_package_and_seller_route_false_positives_are_absent(self):
        root = Path(__file__).resolve().parents[1]
        lifecycle = json.loads(
            (root / "product_lifecycle.json").read_text(encoding="utf-8")
        )["products"]
        false_positives = {
            "2344002X1349", "2679701Q1055", "6149004F1036",
            "3969007F3035", "3969007F4031", "2190406A1128", "2190406A2124",
            "1124020F2056", "1124020F4059", "1319710Q2108",
            "2649731S1275", "3231001X1108", "2171017F2156",
        }
        self.assertTrue(false_positives.isdisjoint(lifecycle))

    def test_verified_product_wide_handling_titles_are_readded_safely(self):
        root = Path(__file__).resolve().parents[1]
        lifecycle = json.loads(
            (root / "product_lifecycle.json").read_text(encoding="utf-8")
        )["products"]
        for yj_code in {"2614700X1441", "2649731S1348", "2649731S2077"}:
            with self.subTest(yj_code=yj_code):
                self.assertEqual(
                    lifecycle[yj_code]["state"], "discontinuation_announced"
                )

    def test_amaluet_tracks_manufacturer_discontinuation_while_in_supply_csv(self):
        """対象品がCSVにある間だけ、メーカーの販売中止情報を追跡する。"""
        root = Path(__file__).resolve().parents[1]
        with (root / "drugs_app_ready.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = {row["YJコード"]: row for row in csv.DictReader(handle)}
        lifecycle = json.loads(
            (root / "product_lifecycle.json").read_text(encoding="utf-8")
        )["products"]
        expected = {
            "2190101F1098": "サンド", "2190102F1092": "サンド",
            "2190103F1097": "サンド", "2190104F1091": "サンド",
            "2190101F1063": "辰巳化学", "2190102F1068": "辰巳化学",
            "2190103F1062": "辰巳化学", "2190104F1067": "辰巳化学",
        }
        for yj_code, maker in expected.items():
            with self.subTest(yj_code=yj_code):
                # 厚労省一覧から販売終了品が削除された後は、reconcile処理に
                # 合わせてライフサイクル側にも残さない。正常な将来更新を
                # 固定YJの存在チェックで止めないための条件分岐。
                if yj_code not in rows:
                    self.assertNotIn(yj_code, lifecycle)
                    continue
                self.assertEqual(lifecycle[yj_code]["state"], "discontinuation_announced")
                self.assertEqual(lifecycle[yj_code]["maker"], maker)
                self.assertTrue(lifecycle[yj_code]["source_url"].startswith("https://"))

    def test_announcement_date_uses_pdf_url_when_title_has_no_date(self):
        self.assertEqual(
            announcement_date(
                "販売中止のお知らせ",
                "https://example.test/fileloader.php?f=20260730_notice.pdf",
            ),
            "2026-07-30",
        )

    def test_announcement_date_rejects_impossible_date(self):
        self.assertIsNone(
            announcement_date("販売中止のお知らせ", "https://example.test/20261340.pdf")
        )

    def test_announcement_date_does_not_parse_embedded_identifier(self):
        self.assertIsNone(
            announcement_date(
                "販売中止のお知らせ",
                "https://example.test/documentX20260730Y.pdf",
            )
        )

    def test_existing_lifecycle_date_is_backfilled_from_source_url(self):
        products = {
            "123456789012": {
                "source_title": "販売中止のお知らせ",
                "source_url": "https://example.test/f=20260730_notice.pdf",
            }
        }
        self.assertEqual(backfill_announcement_dates(products), 1)
        self.assertEqual(products["123456789012"]["announced_at"], "2026-07-30")

    def test_existing_lifecycle_date_is_not_overwritten(self):
        products = {
            "123456789012": {
                "announced_at": "2025-01-01",
                "source_url": "https://example.test/f=20260730_notice.pdf",
            }
        }
        self.assertEqual(backfill_announcement_dates(products), 0)
        self.assertEqual(products["123456789012"]["announced_at"], "2025-01-01")

    def test_event_history_last_checked_refreshes_the_same_notice_verification(self):
        source_url = "https://example.test/notice.pdf"
        checks = event_last_checked_by_url({
            "テスト錠": [
                {"url": source_url, "last_checked": "2026-08-20"},
                {"url": source_url, "last_checked": "2026-08-25"},
                {"url": source_url, "last_checked": "2026-99-99"},
                {"url": "https://example.test/other.pdf", "last_checked": "2026-08-26"},
            ],
        })
        self.assertEqual(checks[source_url], "2026-08-25")
        self.assertEqual(
            lifecycle_verified_at(
                {"checked": "2026-08-21"},
                {"verified_at": "2026-08-22"},
                checks,
                source_url,
                "2026-08-26",
            ),
            "2026-08-25",
        )

    def test_event_history_for_another_url_does_not_refresh_lifecycle(self):
        self.assertEqual(
            lifecycle_verified_at(
                {},
                {"verified_at": "2026-08-22"},
                {"https://example.test/other.pdf": "2026-08-26"},
                "https://example.test/notice.pdf",
                "2026-08-26",
            ),
            "2026-08-22",
        )

    def test_normal_supply_discontinuation_is_collected(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "drugs.csv"
            with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=["商品名", "製造メーカー", "販売メーカー", "供給状況", "代替候補"],
                )
                writer.writeheader()
                writer.writerow({
                    "商品名": "薬Ａ錠５ｍｇ「サワイ」",
                    "製造メーカー": "沢井製薬",
                    "販売メーカー": "沢井製薬",
                    "供給状況": "①通常出荷",
                    "代替候補": "出荷量状況: A．出荷量通常",
                })
            result = match_to_csv(
                [("沢井製薬", "薬A錠5mg「サワイ」 販売中止のお知らせ", "https://example.test/a.pdf")],
                csv_path,
            )
            self.assertIn("薬Ａ錠５ｍｇ「サワイ」", result)

    def test_strength_does_not_match_decimal_substring(self):
        self.assertFalse(
            announcement_covers_product(
                "薬Ａ錠５ｍｇ「Ａ」",
                "薬A錠2.5mg/10mg「A」 販売中止のお知らせ",
            )
        )

    def test_grouped_strength_is_accepted(self):
        self.assertTrue(
            announcement_covers_product(
                "薬Ａ錠５ｍｇ「Ａ」",
                "薬A錠2.5mg/5mg/10mg「A」 販売中止のお知らせ",
            )
        )

    def test_grouped_numbered_formulation_is_accepted(self):
        self.assertTrue(
            announcement_covers_product(
                "アマルエット配合錠２番「ＴＣＫ」",
                "アマルエット配合錠1番/2番/3番/4番「TCK」 販売中止のお知らせ",
            )
        )

    def test_grouped_numbered_formulation_rejects_missing_number(self):
        self.assertFalse(
            announcement_covers_product(
                "アマルエット配合錠４番「ＴＣＫ」",
                "アマルエット配合錠1番/2番/3番「TCK」 販売中止のお知らせ",
            )
        )

    def test_product_named_as_new_release_is_not_the_discontinued_target(self):
        title = (
            "シルビノール錠5mg販売中止及び"
            "ニコランジル錠5mg「サワイ」新発売に関するお知らせ"
        )
        product = "ニコランジル錠５ｍｇ「サワイ」"
        self.assertTrue(announcement_identifies_product_as_new_release(product, title))
        self.assertFalse(announcement_covers_product(product, title))
        self.assertTrue(existing_record_needs_reverification({
            "product_name": product,
            "source_title": title,
        }))

    def test_verified_manual_group_target_accepts_generic_title(self):
        self.assertTrue(announcement_targets_product(
            "薬Ａ錠５ｍｇ「Ａ」",
            {"title": "販売中止品目のご案内", "target_products_verified": True,
             "target_scope": "product"},
        ))

    def test_only_explicitly_verified_group_is_expanded(self):
        document = [
            {
                "products": ["薬Ａ錠", "薬Ｂ錠"],
                "target_products_verified": True,
                "target_scope": "product",
                "expected_target_count": 2,
                "announcement": {
                    "maker": "Ａ製薬", "title": "販売中止",
                    "url": "https://example.test/a", "event_type": "discontinued",
                },
            },
            {
                "products": ["薬Ｃ錠"],
                "announcement": {"maker": "Ａ製薬", "title": "販売中止", "url": "https://example.test/c"},
            },
        ]
        expanded = verified_group_announcements(document)
        self.assertEqual(set(expanded), {"薬Ａ錠", "薬Ｂ錠"})
        self.assertTrue(expanded["薬Ａ錠"]["target_products_verified"])

    def test_verified_supply_group_does_not_replace_lifecycle_group(self):
        document = [
            {
                "products": ["薬Ａ錠"],
                "target_products_verified": True,
                "target_scope": "product",
                "expected_target_count": 1,
                "announcement": {
                    "maker": "Ａ製薬", "title": "薬A錠 販売中止",
                    "url": "https://example.test/end", "event_type": "discontinued",
                },
            },
            {
                "products": ["薬Ａ錠"],
                "target_products_verified": True,
                "target_scope": "product",
                "expected_target_count": 1,
                "announcement": {
                    "maker": "Ａ製薬", "title": "薬A錠 限定出荷",
                    "url": "https://example.test/supply", "event_type": "limited",
                },
            },
        ]
        expanded = verified_group_announcements(document)
        self.assertEqual(expanded["薬Ａ錠"]["event_type"], "discontinued")

    def test_verified_seller_route_scope_blocks_raw_product_wide_inference(self):
        groups = [{
            "products": ["薬Ａ錠"],
            "target_products_verified": True,
            "target_scope": "seller_route",
            "expected_target_count": 1,
            "announcement": {
                "maker": "Ａ製薬", "title": "販売中止", "url": "https://example.test/a",
            },
        }]
        self.assertEqual(
            verified_group_scopes(groups)[("薬A錠", "https://example.test/a")],
            "seller_route",
        )
        self.assertEqual(verified_group_announcements(groups), {})

    def test_unverified_generic_title_is_rejected(self):
        self.assertFalse(announcement_targets_product(
            "薬Ａ錠５ｍｇ「Ａ」",
            {"title": "販売中止品目のご案内"},
        ))

    def test_partial_package_notice_is_not_product_discontinuation(self):
        self.assertIsNotNone(PARTIAL_RE.search("薬A錠 一部包装販売中止のお知らせ"))

    def test_explicit_package_event_is_not_product_discontinuation(self):
        self.assertFalse(is_product_wide_discontinuation({
            "title": "薬A注 販売中止のご案内",
            "event_type": "package_discontinued",
        }))

    def test_explicit_product_event_is_product_discontinuation(self):
        self.assertTrue(is_product_wide_discontinuation({
            "title": "薬A注 販売中止のご案内",
            "event_type": "discontinued",
        }))

    def test_legacy_handling_only_record_is_not_carried_forward(self):
        self.assertTrue(existing_record_needs_reverification({
            "source_title": "薬A錠 取り扱い中止のご案内",
        }))

    def test_legacy_product_discontinuation_can_be_carried_forward(self):
        self.assertFalse(existing_record_needs_reverification({
            "source_title": "薬A錠 製造販売中止のご案内",
        }))


if __name__ == "__main__":
    unittest.main()
