from __future__ import annotations

import datetime as dt
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from check_public_data_health import (
    BASE_URL,
    PAGES_URL,
    SUPPORTING_FILES,
    check_pages,
    run,
    parse_note_date,
    validate_discrepancy_bundle,
    validate_supporting_document,
    validate_version,
)
from public_data_manifest import MANIFEST_NAME, PUBLIC_FILES, fingerprint


class RemoteDataHealthTests(unittest.TestCase):
    def test_post_merge_health_check_waits_for_pages_deployment(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "public-data-health.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("workflow_run:", workflow)
        self.assertIn("workflows: ['Deploy GitHub Pages']", workflow)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", workflow)
        self.assertNotIn("\n  push:\n", workflow)

    def test_manual_target_registry_is_downloaded_for_discrepancy_validation(self) -> None:
        self.assertIs(SUPPORTING_FILES["manual_announcement_groups.json"], list)

    def test_discrepancy_validation_receives_manual_target_registry(self) -> None:
        manual_groups = [{"target_scope": "product"}]
        documents = {
            "maker_announcements.json": {},
            "maker_announcement_events.json": {},
            "manual_announcement_groups.json": manual_groups,
        }
        with mock.patch(
            "check_public_data_health.validate_discrepancies", return_value=[]
        ) as validator:
            self.assertEqual(validate_discrepancy_bundle({}, {}, documents), [])
        self.assertIs(validator.call_args.args[4], manual_groups)

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

    def test_first_pr_may_skip_only_missing_discrepancy_file(self) -> None:
        version = {
            "version": 202608212350,
            "csv_url": BASE_URL + "drugs_app_ready.csv",
            "note": "2026年08月21日厚労省データ反映",
        }

        def fake_fetch(url: str, _maximum_bytes: int) -> bytes:
            clean_url = url.split("?", 1)[0]
            if clean_url.endswith("version.json"):
                return json.dumps(version).encode()
            if clean_url.endswith("supply_discrepancies.json"):
                raise urllib.error.HTTPError(clean_url, 404, "Not Found", {}, None)
            if clean_url.endswith("drugs_app_ready.csv"):
                raise RuntimeError("stop after optional-file behavior is exercised")
            return b"{}"

        with mock.patch("check_public_data_health.fetch", side_effect=fake_fetch):
            errors, _ = run(
                dt.date(2026, 8, 22),
                4,
                allow_missing_supply_discrepancies=True,
                include_pages=False,
            )
        self.assertFalse(any("supply_discrepancies.jsonを取得" in error for error in errors))

    def test_status_history_rejects_wrong_types_dates_ids_and_statuses(self) -> None:
        valid = {"date": "2026/09/05", "yj": "2189101F1020", "name": "薬A",
                 "from": "①通常出荷", "to": "⑤供給停止"}
        self.assertEqual(validate_supporting_document("status_changes.json", [valid]), [])
        self.assertEqual(validate_supporting_document("status_changes.json", []), [])
        self.assertEqual(validate_supporting_document("status_changes.json", [{**valid, "yj": "X12345"}]), [])
        for invalid in ({}, None, [None], [valid, None], [{**valid, "date": 123}],
                        [{**valid, "date": "2026/02/31"}], [{**valid, "date": "2026/9/05"}],
                        [{**valid, "yj": {"unexpected": True}}], [{**valid, "yj": "123"}],
                        [{**valid, "name": ["drug"]}], [{**valid, "from": True}],
                        [{**valid, "to": "通常らしい"}]):
            with self.subTest(invalid=invalid):
                self.assertTrue(validate_supporting_document("status_changes.json", invalid))


class PagesDataHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        cls.source_bodies = {name: (root / name).read_bytes() for name in PUBLIC_FILES}
        cls.today = parse_note_date(json.loads(cls.source_bodies["version.json"])["note"])

    def setUp(self):
        self.bodies = dict(self.source_bodies)
        self.manifest = {"schema_version": 1, "source_commit": "a" * 40,
                         "files": {name: fingerprint(body) for name, body in self.bodies.items()}}
        self.calls = []

    def fetch(self, url, _limit):
        self.assertTrue(url.startswith(PAGES_URL), "Pages検査がrawへ逃げてはいけない")
        name = url.removeprefix(PAGES_URL)
        self.calls.append(name)
        if name == MANIFEST_NAME:
            return json.dumps(self.manifest).encode()
        return self.bodies[name]

    def check(self, **kwargs):
        with mock.patch("check_public_data_health.fetch", side_effect=self.fetch):
            return check_pages(self.today, 4, retry_delay=0, **kwargs)

    def test_valid_bundle_checks_pages_csv_even_when_version_url_is_raw(self):
        errors, results = self.check()
        self.assertEqual(errors, [])
        self.assertIn("Pages/drugs_app_ready.csv", results)
        for name in PUBLIC_FILES:
            self.assertEqual(self.calls.count(name), 1)

    def test_temporary_content_mismatch_retries_only_changed_file(self):
        original = self.fetch
        def transient(url, limit):
            body = original(url, limit)
            if url.endswith("status_changes.json") and self.calls.count("status_changes.json") == 1:
                return b"[]"
            return body
        with mock.patch("check_public_data_health.fetch", side_effect=transient):
            errors, _ = check_pages(self.today, 4, retry_delay=0)
        self.assertEqual(errors, [])
        self.assertEqual(self.calls.count("status_changes.json"), 2)
        self.assertEqual(self.calls.count("drugs_app_ready.csv"), 1)

    def test_stable_mismatch_fails_after_bounded_retries(self):
        self.bodies["status_changes.json"] = b"[]"
        errors, _ = self.check(attempts=2)
        self.assertTrue(any("SHA256不一致" in error for error in errors))
        self.assertEqual(self.calls.count("status_changes.json"), 2)
        self.assertEqual(self.calls.count("drugs_app_ready.csv"), 1)

    def test_matching_hash_does_not_replace_schema_validation(self):
        self.bodies["status_changes.json"] = b"null"
        self.manifest["files"]["status_changes.json"] = fingerprint(b"null")
        errors, _ = self.check()
        self.assertTrue(any("status_changes.json" in error and "ルート" in error for error in errors))

    def test_matching_hash_with_broken_json_is_not_healthy(self):
        self.bodies["status_changes.json"] = b"{"
        self.manifest["files"]["status_changes.json"] = fingerprint(b"{")
        errors, _ = self.check()
        self.assertTrue(any("status_changes.jsonを解析" in error for error in errors))

    def test_matching_hash_does_not_bypass_csv_contract(self):
        self.bodies["drugs_app_ready.csv"] = "商品名,供給状況\n薬A,①通常出荷\n".encode()
        self.manifest["files"]["drugs_app_ready.csv"] = fingerprint(self.bodies["drugs_app_ready.csv"])
        errors, _ = self.check()
        self.assertTrue(any(error.startswith("Pages CSV:") for error in errors))

    def test_stale_version_and_csv_are_still_checked_after_hash_match(self):
        with mock.patch("check_public_data_health.fetch", side_effect=self.fetch):
            errors, _ = check_pages(self.today + dt.timedelta(days=30), 4, retry_delay=0)
        self.assertTrue(any("version.json" in error and "許容4日" in error for error in errors))

    def test_manifest_absence_does_not_silently_fall_back_to_raw(self):
        with mock.patch("check_public_data_health.fetch", side_effect=urllib.error.HTTPError(
                PAGES_URL + MANIFEST_NAME, 404, "Not Found", {}, None)) as request:
            errors, results = check_pages(self.today, 4, attempts=2, retry_delay=0)
        self.assertTrue(errors)
        self.assertEqual(results, [])
        self.assertEqual(request.call_count, 2)

    def test_pages_http_failure_is_reported_without_redownloading_csv(self):
        original = self.fetch
        def unavailable(url, limit):
            if url.endswith("maker_collection_health.json"):
                raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)
            return original(url, limit)
        with mock.patch("check_public_data_health.fetch", side_effect=unavailable):
            errors, _ = check_pages(self.today, 4, attempts=2, retry_delay=0)
        self.assertTrue(any("maker_collection_health.json" in error for error in errors))
        self.assertEqual(self.calls.count("drugs_app_ready.csv"), 1)

    def test_manifest_switch_during_download_reuses_unchanged_bodies(self):
        original = self.fetch
        def changing(url, limit):
            body = original(url, limit)
            if url.endswith(MANIFEST_NAME) and self.calls.count(MANIFEST_NAME) == 2:
                self.manifest["source_commit"] = "b" * 40
                return json.dumps(self.manifest).encode()
            return body
        with mock.patch("check_public_data_health.fetch", side_effect=changing):
            errors, results = check_pages(self.today, 4, retry_delay=0)
        self.assertEqual(errors, [])
        self.assertTrue(any("bbbbbbbbbbbb" in result for result in results))
        self.assertEqual(self.calls.count("drugs_app_ready.csv"), 1)


if __name__ == "__main__":
    unittest.main()
