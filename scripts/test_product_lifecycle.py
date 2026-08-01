import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_product_lifecycle import PARTIAL_RE, announcement_covers_product
from scripts.fetch_maker_announcements import match_to_csv


class ProductLifecycleTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
