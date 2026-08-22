from __future__ import annotations

import datetime as dt
import unittest

from check_public_data_health import parse_note_date, validate_supporting_document, validate_version


class RemoteDataHealthTests(unittest.TestCase):
    def test_version_accepts_recent_matching_snapshot(self) -> None:
        document = {
            "version": 202608082347,
            "csv_url": "https://example.com/drugs.csv",
            "note": "2026年08月08日厚労省データ反映",
        }
        self.assertEqual(validate_version(document, dt.date(2026, 8, 9), 4), [])

    def test_version_rejects_stale_or_mismatched_snapshot(self) -> None:
        document = {
            "version": 202608082347,
            "csv_url": "http://example.com/drugs.csv",
            "note": "2026年08月01日厚労省データ反映",
        }
        errors = validate_version(document, dt.date(2026, 8, 9), 4)
        self.assertTrue(any("HTTPS" in error for error in errors))
        self.assertTrue(any("許容4日" in error for error in errors))
        self.assertTrue(any("一致しません" in error for error in errors))

    def test_note_date_rejects_invalid_calendar_date(self) -> None:
        self.assertIsNone(parse_note_date("2026年02月31日厚労省データ反映"))

    def test_schema_documents_require_supported_version_and_keys(self) -> None:
        errors = validate_supporting_document(
            "featured_products.json",
            {"schema_version": 2, "products": []},
        )
        self.assertTrue(any("schema_version" in error for error in errors))
        self.assertTrue(any("updated_at" in error for error in errors))

    def test_status_changes_require_identity_and_transition(self) -> None:
        errors = validate_supporting_document(
            "status_changes.json",
            [{"date": "2026/08/08", "name": "薬A", "from": "通常", "to": "停止"}],
        )
        self.assertTrue(any("必須項目" in error for error in errors))

    def test_supply_discrepancies_requires_schema_version(self) -> None:
        errors = validate_supporting_document(
            "supply_discrepancies.json",
            {"schema_version": 2, "products": {}, "counts": {}},
        )
        self.assertTrue(any("schema_version" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
