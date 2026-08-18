import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from update_maker_enrichment import (
    MANAGED_FILES,
    _write_github_output,
    publish_validated_files,
    refresh,
)


class UpdateMakerEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        (self.base / "scripts").mkdir()
        (self.base / "drugs_app_ready.csv").write_text("商品名\nテスト錠\n", encoding="utf-8")
        (self.base / "manual_announcement_groups.json").write_text("[]\n", encoding="utf-8")

    def write_managed_set(self, generation):
        documents = {
            "maker_announcements.json": {"generation": generation},
            "maker_announcement_events.json": {"generation": generation},
            "maker_collection_health.json": {"generation": generation},
            "unmatched_maker_announcements.json": [{"generation": generation}],
        }
        for name, document in documents.items():
            (self.base / name).write_text(json.dumps(document), encoding="utf-8")

    def read_generation(self, name):
        document = json.loads((self.base / name).read_text(encoding="utf-8"))
        if isinstance(document, list):
            return document[0]["generation"]
        return document["generation"]

    @staticmethod
    def failed_runner(command, cwd):
        return subprocess.CompletedProcess(command, 1)

    @staticmethod
    def fetches_new_set_then_validates(command, cwd):
        script_name = Path(command[1]).name
        if script_name == "fetch_maker_announcements.py":
            stage = Path(command[3]).parent
            documents = {
                "maker_announcements.json": {"generation": "new"},
                "maker_announcement_events.json": {"generation": "new"},
                "maker_collection_health.json": {"generation": "new"},
                "unmatched_maker_announcements.json": [{"generation": "new"}],
            }
            for name, document in documents.items():
                (stage / name).write_text(json.dumps(document), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    @staticmethod
    def fetches_new_set_then_fails_validation(command, cwd):
        result = UpdateMakerEnrichmentTests.fetches_new_set_then_validates(command, cwd)
        if Path(command[1]).name == "validate_maker_announcements.py":
            return subprocess.CompletedProcess(command, 1)
        return result

    def test_fetch_failure_retains_every_previous_file(self):
        self.write_managed_set("old")
        updated = refresh(
            self.base, expected_checked="2026-08-18", runner=self.failed_runner,
        )
        self.assertFalse(updated)
        self.assertEqual(
            {name: self.read_generation(name) for name in MANAGED_FILES},
            {name: "old" for name in MANAGED_FILES},
        )

    def test_validation_failure_retains_every_previous_file(self):
        self.write_managed_set("old")
        updated = refresh(
            self.base,
            expected_checked="2026-08-18",
            runner=self.fetches_new_set_then_fails_validation,
        )
        self.assertFalse(updated)
        self.assertTrue(all(self.read_generation(name) == "old" for name in MANAGED_FILES))

    def test_valid_refresh_publishes_complete_new_set(self):
        self.write_managed_set("old")
        updated = refresh(
            self.base,
            expected_checked="2026-08-18",
            runner=self.fetches_new_set_then_validates,
        )
        self.assertTrue(updated)
        self.assertTrue(all(self.read_generation(name) == "new" for name in MANAGED_FILES))

    def test_failure_without_complete_previous_set_fails_closed(self):
        (self.base / MANAGED_FILES[0]).write_text("{}", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            refresh(self.base, expected_checked="2026-08-18", runner=self.failed_runner)

    def test_partial_replace_failure_rolls_back_every_replaced_file(self):
        self.write_managed_set("old")
        stage = self.base / "stage"
        stage.mkdir()
        for name in MANAGED_FILES:
            document = [{"generation": "new"}] if name.startswith("unmatched") else {"generation": "new"}
            (stage / name).write_text(json.dumps(document), encoding="utf-8")

        real_replace = os.replace
        replacement_calls = 0

        def fail_second_replacement(source, destination):
            nonlocal replacement_calls
            if str(source).endswith(".next"):
                replacement_calls += 1
                if replacement_calls == 2:
                    raise OSError("simulated replace failure")
            return real_replace(source, destination)

        with mock.patch("update_maker_enrichment.os.replace", side_effect=fail_second_replacement):
            with self.assertRaises(OSError):
                publish_validated_files(stage, self.base)
        self.assertTrue(all(self.read_generation(name) == "old" for name in MANAGED_FILES))

    def test_github_output_reports_refresh_and_fallback_states(self):
        output = self.base / "github-output.txt"
        with mock.patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}):
            _write_github_output(True)
            _write_github_output(False)
        self.assertEqual(output.read_text(encoding="utf-8"), "updated=true\nupdated=false\n")


if __name__ == "__main__":
    unittest.main()
