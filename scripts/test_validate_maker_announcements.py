import csv
import json
import os
import tempfile
import unittest

from validate_maker_announcements import validate, validate_history


class ValidateMakerAnnouncementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.csv_path = os.path.join(self.tmp.name, "drugs.csv")
        with open(self.csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["商品名"])
            w.writeheader()
            w.writerow({"商品名": "テスト錠"})

    def write_json(self, data):
        path = os.path.join(self.tmp.name, "announcements.json")
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


if __name__ == "__main__":
    unittest.main()
