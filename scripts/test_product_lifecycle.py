import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_product_lifecycle import (
    PARTIAL_RE,
    announcement_date,
    announcement_covers_product,
    backfill_announcement_dates,
    is_product_wide_discontinuation,
)
from scripts.fetch_maker_announcements import match_to_csv


class ProductLifecycleTests(unittest.TestCase):
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
