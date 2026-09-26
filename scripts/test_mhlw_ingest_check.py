import datetime as dt
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import check_public_data_health as health

ROOT = Path(__file__).resolve().parents[1]
PAGE = '<a href="/content/10800000/{}iyakuhinkyoukyu.xlsx">供給状況</a>'


class MhlwIngestCheckTests(unittest.TestCase):
    def run_check(self, page_stamps, ingested="2026-09-18", today=dt.date(2026, 9, 26), page_error=None, source=None):
        def fake_fetch(url, _limit):
            if url == health.MHLW_SUPPLY_PAGE:
                if page_error:
                    raise page_error
                return "".join(PAGE.format(stamp) for stamp in page_stamps).encode()
            if url.endswith(health.MHLW_SOURCE_NAME):
                if source is not None:
                    return source
                return json.dumps({"excel_date": ingested}).encode()
            raise AssertionError(url)
        with mock.patch.object(health, "fetch", side_effect=fake_fetch):
            return health.check_mhlw_ingest(today)

    def test_detects_published_file_not_ingested_after_a_day(self):
        errors, warnings, _ = self.run_check(["260918", "260925"])
        self.assertEqual(1, len(errors))
        self.assertIn("2026-09-25版", errors[0])
        self.assertIn("2026-09-18版のまま", errors[0])

    def test_same_day_publication_only_warns(self):
        errors, warnings, _ = self.run_check(["260925"], today=dt.date(2026, 9, 25))
        self.assertEqual([], errors)
        self.assertTrue(any("待機" in warning for warning in warnings))

    def test_ingested_latest_is_healthy(self):
        errors, warnings, results = self.run_check(["260925"], ingested="2026-09-25")
        self.assertEqual(([], []), (errors, warnings))
        self.assertIn("取り込み済み 2026-09-25", results[0])

    def test_mhlw_outage_or_renamed_file_warns_instead_of_false_alarm(self):
        errors, warnings, _ = self.run_check([], page_error=urllib.error.URLError("timeout"))
        self.assertEqual([], errors)
        self.assertTrue(warnings)
        errors, warnings, _ = self.run_check([])
        self.assertEqual([], errors)
        self.assertTrue(any("形式変更" in warning for warning in warnings))

    def test_missing_or_broken_source_record_is_an_error(self):
        errors, _, _ = self.run_check(["260925"], source=b"{}")
        self.assertTrue(errors)

    def test_daily_update_records_and_commits_ingested_file(self):
        workflow = (ROOT / ".github/workflows/update_drugs.yml").read_text(encoding="utf-8")
        self.assertIn('with open("mhlw_source.json", "w"', workflow)
        self.assertIn("sitemap-curated.xml mhlw_source.json maker_announcements.json", workflow)
        record = json.loads((ROOT / "mhlw_source.json").read_text(encoding="utf-8"))
        self.assertRegex(record["file"], r"^\d{6}iyakuhinkyoukyu\.xlsx$")
        self.assertEqual(health.mhlw_file_date(record["file"][:6]).isoformat(), record["excel_date"])


if __name__ == "__main__":
    unittest.main()
