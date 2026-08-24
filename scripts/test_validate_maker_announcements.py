import csv
import json
import os
import tempfile
import unittest

from validate_maker_announcements import (
    validate,
    validate_current_history,
    validate_health,
    validate_history,
    validate_manual_groups,
    validate_unmatched,
)


class ValidateMakerAnnouncementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv_path = os.path.join(self.tmp.name, "drugs.csv")
        with open(self.csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(
                f, fieldnames=["商品名", "YJコード", "製造メーカー", "販売メーカー"],
            )
            w.writeheader()
            w.writerow({
                "商品名": "テスト錠", "YJコード": "123456789012",
                "製造メーカー": "テスト製薬", "販売メーカー": "テスト製薬",
            })

    def write_json(self, data):
        path = os.path.join(self.tmp.name, "announcements.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def write_named_json(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        return path

    def test_valid_data(self):
        path = self.write_json({"テスト錠": {
            "maker": "テスト製薬", "title": "販売中止のご案内",
            "url": "https://example.test/a.pdf", "event_type": "discontinued",
        }})
        self.assertEqual(validate(self.csv_path, path, min_count=1), [])

    def test_orphan_unknown_type_and_insecure_url_are_rejected(self):
        path = self.write_json({"CSV外錠": {
            "maker": "テスト製薬", "title": "案内",
            "url": "http://example.test/a.pdf", "event_type": "mystery",
        }})
        errors = "\n".join(validate(self.csv_path, path, min_count=1))
        self.assertIn("CSVに存在しない品目", errors)
        self.assertIn("HTTPS", errors)
        self.assertIn("未知のevent_type", errors)

    def test_duplicate_history_is_rejected(self):
        path = self.write_json({"テスト錠": [{
            "maker": "テスト製薬", "title": "販売中止のご案内",
            "url": "https://example.test/a.pdf", "event_type": "discontinued",
        }, {
            "maker": "テスト製薬", "title": "販売中止のご案内",
            "url": "https://example.test/a.pdf", "event_type": "discontinued",
        }]})
        self.assertTrue(any("重複" in e for e in validate_history(path)))

    def test_current_announcement_must_exist_in_history(self):
        current = self.write_named_json("current.json", {"テスト錠": {
            "maker": "テスト製薬", "title": "販売中止のご案内",
            "url": "https://example.test/current.pdf", "event_type": "discontinued",
        }})
        history = self.write_named_json("history.json", {"テスト錠": [{
            "maker": "テスト製薬", "title": "旧案内",
            "url": "https://example.test/old.pdf", "event_type": "limited",
        }]})
        self.assertTrue(any("履歴に存在しません" in e
                            for e in validate_current_history(current, history)))

    def test_duplicate_unmatched_urls_are_rejected(self):
        record = {"maker": "テスト製薬", "title": "供給案内",
                  "url": "https://example.test/a.pdf", "event_type": "supply"}
        path = self.write_named_json("unmatched.json", [record, dict(record)])
        self.assertTrue(any("重複" in e for e in validate_unmatched(path)))

    def test_health_checks_expected_jst_date_and_totals(self):
        path = self.write_named_json("health.json", {
            "checked": "2026-08-02",
            "sources": [{"source": "parser_a", "ok": True, "count": 2, "error": ""}],
            "total": 3,
        })
        errors = "\n".join(validate_health(path, expected_checked="2026-08-03"))
        self.assertIn("期待値2026-08-03", errors)
        self.assertIn("合計を超えています", errors)

    def test_invalid_calendar_date_is_rejected(self):
        path = self.write_json({"テスト錠": {
            "maker": "テスト製薬", "title": "販売中止のご案内",
            "url": "https://example.test/a.pdf", "event_type": "discontinued",
            "checked": "2026-02-30",
        }})
        self.assertTrue(any("実在日" in e for e in validate(self.csv_path, path, min_count=1)))

    def test_announced_at_accepts_exact_month_precision_from_2026_notices(self):
        for announced_at in ("2026-05", "2026-07"):
            with self.subTest(announced_at=announced_at):
                path = self.write_json({"テスト錠": {
                    "maker": "テスト製薬", "title": "販売中止のご案内",
                    "url": "https://example.test/a.pdf", "event_type": "discontinued",
                    "announced_at": announced_at,
                }})
                self.assertEqual(validate(self.csv_path, path, min_count=1), [])

    def test_announced_at_rejects_invalid_or_non_padded_month(self):
        for announced_at in ("2026-13", "2026-5"):
            with self.subTest(announced_at=announced_at):
                path = self.write_json({"テスト錠": {
                    "maker": "テスト製薬", "title": "販売中止のご案内",
                    "url": "https://example.test/a.pdf", "event_type": "discontinued",
                    "announced_at": announced_at,
                }})
                self.assertTrue(validate(self.csv_path, path, min_count=1))

    def test_operational_checked_date_still_requires_day_precision(self):
        path = self.write_json({"テスト錠": {
            "maker": "テスト製薬", "title": "販売中止のご案内",
            "url": "https://example.test/a.pdf", "event_type": "discontinued",
            "announced_at": "2026-05", "checked": "2026-05",
        }})
        errors = "\n".join(validate(self.csv_path, path, min_count=1))
        self.assertIn("checked", errors)
        self.assertIn("YYYY-MM-DD", errors)

    def test_manual_groups_validate_products_and_announcement(self):
        valid = self.write_named_json("manual-groups-valid.json", [{
            "products": ["テスト錠"],
            "announcement": {
                "maker": "テスト製薬", "title": "販売中止のご案内",
                "url": "https://example.test/a.pdf", "event_type": "discontinued",
                "announced_at": "2026-08-03",
            },
        }])
        self.assertEqual(validate_manual_groups(self.csv_path, valid), [])

        invalid = self.write_named_json("manual-groups-invalid.json", [{
            "products": ["CSV外錠", "CSV外錠"],
            "announcement": {"maker": "", "title": "案内", "url": "http://example.test/a.pdf"},
        }])
        errors = "\n".join(validate_manual_groups(self.csv_path, invalid))
        self.assertIn("CSVに存在しない品目", errors)
        self.assertIn("重複", errors)
        self.assertIn("HTTPS", errors)
        self.assertIn("makerが空", errors)

    def test_verified_manual_group_requires_scope_and_complete_target_count(self):
        path = self.write_named_json("manual-groups-verified-invalid.json", [{
            "products": ["テスト錠"],
            "target_products_verified": True,
            "announcement": {
                "maker": "テスト製薬", "title": "販売中止のご案内",
                "url": "https://example.test/a.pdf", "event_type": "discontinued",
            },
        }])
        errors = "\n".join(validate_manual_groups(self.csv_path, path))
        self.assertIn("target_scope", errors)
        self.assertIn("expected_target_count", errors)


if __name__ == "__main__":
    unittest.main()
