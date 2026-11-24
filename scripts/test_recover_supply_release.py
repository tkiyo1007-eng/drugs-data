import datetime as dt
import unittest
from unittest.mock import patch

import recover_supply_release as recovery


def source(day, digest="a"):
    return recovery.Source(dt.date(2026, 11, day), digest * 64)


class ReleaseRecoveryTests(unittest.TestCase):
    def test_all_three_match(self):
        self.assertIsNone(recovery.recovery_target(source(24), source(24), source(24)))

    def test_missed_import(self):
        self.assertEqual(recovery.recovery_target(source(24), source(20), source(20)), recovery.INGEST)

    def test_unchanged_date_with_replaced_workbook(self):
        self.assertEqual(recovery.recovery_target(source(24, "b"), source(24), source(24)), recovery.INGEST)

    def test_failed_deployment_retries_only_pages(self):
        self.assertEqual(recovery.recovery_target(source(24), source(24), source(20)), recovery.PAGES)

    def test_older_upstream_cannot_trigger_rollback(self):
        with self.assertRaises(ValueError):
            recovery.recovery_target(source(20), source(24), source(20))

    def test_public_snapshot_ahead_of_main_blocks_recovery(self):
        with self.assertRaises(ValueError):
            recovery.recovery_target(source(25), source(20), source(24))

    @patch.object(recovery, "dispatch")
    @patch.object(recovery, "list_runs")
    def test_existing_update_delays_pages_recovery(self, list_runs, dispatch):
        list_runs.side_effect = [[], [{"status": "queued", "id": 1}]]
        recovery.recover(recovery.PAGES, source(24), source(24))
        dispatch.assert_not_called()

    @patch.object(recovery, "dispatch")
    @patch.object(recovery, "failed_checks", return_value=["公開前の供給CSV品質検査"])
    @patch.object(recovery, "list_runs")
    def test_failed_quality_check_blocks_repeated_import(self, list_runs, jobs, dispatch):
        latest = source(24)
        list_runs.return_value = [
            {"status": "completed", "display_title": recovery.run_title(latest), "id": 42, "conclusion": "failure"},
        ]
        with self.assertRaisesRegex(RuntimeError, "供給CSV品質検査"):
            recovery.recover(recovery.INGEST, latest, source(20))
        dispatch.assert_not_called()

    @patch.object(recovery, "dispatch")
    @patch.object(recovery, "list_runs")
    def test_transient_failure_retries_only_for_same_version_and_within_limit(self, list_runs, dispatch):
        latest = source(24)
        run = {"status": "completed", "display_title": recovery.run_title(latest), "id": 42, "conclusion": "failure"}
        older = dict(run, display_title=recovery.run_title(source(23)))
        list_runs.side_effect = [[run, older], []]
        recovery.recover(recovery.PAGES, latest, source(24))
        dispatch.assert_called_once_with(recovery.PAGES, latest)
        dispatch.reset_mock()
        list_runs.side_effect = [[run, dict(run, id=43)], []]
        with self.assertRaisesRegex(RuntimeError, "上限"):
            recovery.recover(recovery.PAGES, latest, source(24))
        dispatch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
