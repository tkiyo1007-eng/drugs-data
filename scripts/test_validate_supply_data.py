import csv
import datetime as dt
import tempfile
import unittest
from pathlib import Path

from validate_supply_data import ALLOWED_STATUSES, REQUIRED_COLUMNS, validate_csv


class ValidateSupplyDataTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "drugs.csv"

    def row(self, **overrides):
        row = {column: "値" for column in REQUIRED_COLUMNS}
        row.update({
            "商品名": "テスト錠", "一般名": "テスト成分", "製造メーカー": "テスト製薬",
            "販売メーカー": "", "供給状況": next(iter(ALLOWED_STATUSES)),
            "理由": "７．－",
            "代替候補": "解除/解消見込み: エ. － / 出荷量状況: A．出荷量通常",
            "更新日": "2026/08/01", "ステータス更新日": "2026/08/01",
            "YJコード": "1234567A1234", "薬価": "",
        })
        row.update(overrides)
        return row

    def write(self, rows, headers=REQUIRED_COLUMNS):
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def errors(self):
        return validate_csv(self.path, today=dt.date(2026, 8, 3),
                            min_rows=1, max_rows=10, max_age_days=7)[0]

    def test_valid_csv(self):
        self.write([self.row()])
        self.assertEqual(self.errors(), [])

    def test_schema_status_and_identifier_failures_are_rejected(self):
        headers = [column for column in REQUIRED_COLUMNS if column != "理由"]
        self.write([
            self.row(供給状況="⑥未知", YJコード="BAD"),
            self.row(商品名="別の薬", 供給状況="⑥未知", YJコード="BAD"),
        ], headers=headers)
        errors = "\n".join(self.errors())
        self.assertIn("必須列", errors)
        self.assertIn("未対応", errors)
        self.assertIn("YJコード形式", errors)
        self.assertIn("YJコードが重複", errors)

    def test_unknown_publication_codes_and_shifted_metadata_are_rejected(self):
        self.write([
            self.row(
                理由="９．未知",
                代替候補="解除/解消見込み: オ. 未知 / 出荷量状況: E．未知",
            ),
            self.row(
                商品名="列ずれテスト錠", YJコード="1234567A1235",
                代替候補="A．出荷量通常",
            ),
        ])
        errors = "\n".join(self.errors())
        self.assertIn("未対応または空の理由区分", errors)
        self.assertIn("未対応の解除・解消見込み区分", errors)
        self.assertIn("未対応の出荷量状況区分", errors)
        self.assertIn("複合形式が不正", errors)

    def test_invalid_and_future_dates_are_rejected(self):
        self.write([self.row(更新日="2026-07-01", ステータス更新日="2026/08/10")])
        errors = "\n".join(self.errors())
        self.assertIn("更新日の日付形式", errors)
        self.assertIn("ステータス更新日が未来日", errors)

    def test_stale_data_is_rejected(self):
        self.write([self.row(更新日="2026/07/01", ステータス更新日="2026/07/01")])
        self.assertTrue(any("データが古すぎます" in error for error in self.errors()))

    def test_missing_sales_maker_rate_can_be_guarded_without_guessing_values(self):
        self.write([
            self.row(),
            self.row(商品名="別の薬", YJコード="1234567A1235", 販売メーカー="テスト販売"),
        ])
        errors, summary = validate_csv(
            self.path, today=dt.date(2026, 8, 3), min_rows=1, max_rows=10, max_age_days=7,
            max_missing_sales_maker_rate=40.0)
        self.assertEqual(50.0, summary["missing_sales_maker_rate"])
        self.assertTrue(any("記載なし率が上限" in error for error in errors))

    def test_maker_document_noise_and_invalid_prices_are_rejected(self):
        self.write([self.row(
            製造メーカー="会社名 本注意事項等情報を使用している製造販売業者一覧表",
            薬価="無料",
        )])
        errors = "\n".join(self.errors())
        self.assertIn("外部文書の説明文", errors)
        self.assertIn("薬価が正の数値ではない", errors)

    def test_remote_compatibility_can_defer_new_maker_noise_rule(self):
        self.write([self.row(
            製造メーカー="会社名 本注意事項等情報を使用している製造販売業者一覧表",
        )])
        errors, _ = validate_csv(
            self.path, today=dt.date(2026, 8, 3), min_rows=1, max_rows=10,
            max_age_days=7, reject_maker_noise=False)
        self.assertFalse(any("外部文書の説明文" in error for error in errors))

    def test_missing_price_rate_can_be_guarded(self):
        self.write([
            self.row(),
            self.row(商品名="別の薬", YJコード="1234567A1235", 薬価="10.5"),
        ])
        errors, summary = validate_csv(
            self.path, today=dt.date(2026, 8, 3), min_rows=1, max_rows=10, max_age_days=7,
            max_missing_price_rate=40.0)
        self.assertEqual(50.0, summary["missing_price_rate"])
        self.assertTrue(any("薬価の記載なし率が上限" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
