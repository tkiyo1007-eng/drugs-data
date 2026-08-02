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

    def test_invalid_and_future_dates_are_rejected(self):
        self.write([self.row(更新日="2026-07-01", ステータス更新日="2026/08/10")])
        errors = "\n".join(self.errors())
        self.assertIn("更新日の日付形式", errors)
        self.assertIn("ステータス更新日が未来日", errors)

    def test_stale_data_is_rejected(self):
        self.write([self.row(更新日="2026/07/01", ステータス更新日="2026/07/01")])
        self.assertTrue(any("データが古すぎます" in error for error in self.errors()))


if __name__ == "__main__":
    unittest.main()
