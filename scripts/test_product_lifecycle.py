import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_product_lifecycle import (
    PARTIAL_RE,
    announcement_date,
    announcement_covers_product,
    announcement_targets_product,
    backfill_announcement_dates,
    is_product_wide_discontinuation,
    verified_group_announcements,
)
from scripts.fetch_maker_announcements import match_to_csv


class ProductLifecycleTests(unittest.TestCase):
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

    def test_verified_manual_group_target_accepts_generic_title(self):
        self.assertTrue(announcement_targets_product(
            "薬Ａ錠５ｍｇ「Ａ」",
            {"title": "販売中止品目のご案内", "target_products_verified": True},
        ))

    def test_only_explicitly_verified_group_is_expanded(self):
        document = [
            {
                "products": ["薬Ａ錠", "薬Ｂ錠"],
                "target_products_verified": True,
                "announcement": {"maker": "Ａ製薬", "title": "販売中止", "url": "https://example.test/a"},
            },
            {
                "products": ["薬Ｃ錠"],
                "announcement": {"maker": "Ａ製薬", "title": "販売中止", "url": "https://example.test/c"},
            },
        ]
        expanded = verified_group_announcements(document)
        self.assertEqual(set(expanded), {"薬Ａ錠", "薬Ｂ錠"})
        self.assertTrue(expanded["薬Ａ錠"]["target_products_verified"])

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


if __name__ == "__main__":
    unittest.main()
