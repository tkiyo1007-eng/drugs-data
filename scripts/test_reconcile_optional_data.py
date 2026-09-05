import csv
import json
import tempfile
import unittest
from pathlib import Path

from reconcile_optional_data import reconcile, validate_retained_bundle
from validate_maker_announcements import validate_manual_groups


class ReconcileOptionalDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        with (self.base / "drugs_app_ready.csv").open(
            "w", encoding="utf-8-sig", newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=["商品名", "YJコード", "製造メーカー", "販売メーカー"],
            )
            writer.writeheader()
            writer.writerow({
                "商品名": "継続錠", "YJコード": "123456789012",
                "製造メーカー": "沢井製薬", "販売メーカー": "沢井製薬",
            })

        kept_announcement = {
            "maker": "沢井製薬", "title": "2026年5月 販売中止のご案内",
            "url": "https://med.sawai.co.jp/file/keep.pdf",
            "event_type": "discontinued", "announced_at": "2026-05",
        }
        removed_announcement = {
            "maker": "沢井製薬", "title": "2026年7月 販売中止のご案内",
            "url": "https://med.sawai.co.jp/file/removed.pdf",
            "event_type": "discontinued", "announced_at": "2026-07",
        }
        self.write_json("maker_announcements.json", {
            "継続錠": kept_announcement,
            "削除済み錠": removed_announcement,
        })
        self.write_json("maker_announcement_events.json", {
            "継続錠": [{**kept_announcement, "first_seen": "2026-05-01", "last_checked": "2026-08-17"}],
            "削除済み錠": [{**removed_announcement, "first_seen": "2026-07-01", "last_checked": "2026-08-17"}],
        })
        self.write_json("maker_collection_health.json", {
            "checked": "2026-08-17",
            "sources": [{"source": "test", "ok": True, "count": 2, "error": ""}],
            "total": 2,
        })
        self.write_json("unmatched_maker_announcements.json", [])
        self.write_json("manual_announcement_groups.json", [])
        self.write_json("product_lifecycle.json", {
            "schema_version": 1,
            "generated_at": "2026-08-17T23:00:00+09:00",
            "products": {
                "123456789012": {
                    "product_name": "継続錠", "maker": "沢井製薬",
                    "state": "discontinuation_announced", "announced_at": "2026-05",
                    "source_title": "2026年5月 販売中止のご案内",
                    "source_url": "https://med.sawai.co.jp/file/keep.pdf",
                    "verified_at": "2026-08-17",
                },
                "999999999999": {
                    "product_name": "削除済み錠", "maker": "沢井製薬",
                    "state": "discontinuation_announced", "announced_at": "2026-07",
                    "source_title": "2026年7月 販売中止のご案内",
                    "source_url": "https://med.sawai.co.jp/file/removed.pdf",
                    "verified_at": "2026-08-17",
                },
            },
        })

    def write_json(self, name, document):
        (self.base / name).write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8",
        )

    def read_json(self, name):
        return json.loads((self.base / name).read_text(encoding="utf-8"))

    def test_removed_core_product_is_pruned_from_all_reference_checked_outputs(self):
        removed_announcements, removed_lifecycle = reconcile(self.base, min_count=1)
        self.assertEqual(removed_announcements, 2)
        self.assertEqual(removed_lifecycle, 1)
        self.assertEqual(set(self.read_json("maker_announcements.json")), {"継続錠"})

        self.assertEqual(set(self.read_json("maker_announcement_events.json")), {"継続錠"})
        lifecycle_products = self.read_json("product_lifecycle.json")["products"]
        self.assertEqual(set(lifecycle_products), {"123456789012"})
        self.assertEqual(lifecycle_products["123456789012"]["announced_at"], "2026-05")

    def test_core_release_rejects_corrupt_retained_data_instead_of_repairing_it(self):
        reconcile(self.base, min_count=1)
        self.write_json("maker_announcements.json", {})
        before = (self.base / "maker_announcements.json").read_bytes()
        self.assertTrue(validate_retained_bundle(self.base, min_count=1))
        self.assertEqual((self.base / "maker_announcements.json").read_bytes(), before)

    def test_incompatible_name_or_maker_is_pruned_from_lifecycle(self):
        lifecycle = self.read_json("product_lifecycle.json")
        lifecycle["products"]["123456789012"]["maker"] = "別会社"
        self.write_json("product_lifecycle.json", lifecycle)
        _, removed_lifecycle = reconcile(self.base, min_count=1)
        self.assertEqual(removed_lifecycle, 2)
        self.assertEqual(self.read_json("product_lifecycle.json")["products"], {})

    def test_stale_optional_manual_group_does_not_block_core_reconciliation(self):
        self.write_json("manual_announcement_groups.json", [{
            "products": ["削除済み錠"],
            "announcement": {
                "maker": "沢井製薬", "title": "2026年7月 販売中止のご案内",
                "url": "https://med.sawai.co.jp/file/removed.pdf",
                "event_type": "discontinued", "announced_at": "2026-07",
            },
        }])
        removed_announcements, removed_lifecycle = reconcile(self.base, min_count=1)
        self.assertEqual(removed_announcements, 2)
        self.assertEqual(removed_lifecycle, 1)
        self.assertEqual(set(self.read_json("maker_announcements.json")), {"継続錠"})
        # 同じ状態を定刻公開のゲートも読み取りだけで受理する。一方、通常CIや
        # 任意メーカー更新で使う手動登録の厳格検査は引き続きこの古い対象を拒否する。
        before = {path.name: path.read_bytes() for path in self.base.iterdir() if path.is_file()}
        self.assertEqual(validate_retained_bundle(self.base, min_count=1), [])
        self.assertTrue(validate_manual_groups(
            str(self.base / "drugs_app_ready.csv"), str(self.base / "manual_announcement_groups.json")))
        self.assertEqual(validate_manual_groups(
            str(self.base / "drugs_app_ready.csv"), str(self.base / "manual_announcement_groups.json"),
            allow_removed_targets=True), [])
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.base.iterdir() if path.is_file()})

    def test_core_manual_exception_does_not_allow_bad_notice_url(self):
        self.write_json("manual_announcement_groups.json", [{
            "products": ["削除済み錠"],
            "announcement": {"maker": "沢井製薬", "title": "販売中止案内",
                             "url": "http://example.test/removed.pdf", "event_type": "discontinued"},
        }])
        errors = validate_manual_groups(str(self.base / "drugs_app_ready.csv"),
                                        str(self.base / "manual_announcement_groups.json"),
                                        allow_removed_targets=True)
        self.assertTrue(any("HTTPS" in error for error in errors))
        self.assertFalse(any("CSVに存在しない" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
