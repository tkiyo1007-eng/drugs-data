import datetime as dt
import json
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import check_public_data_health as health
from jst_time import JST
from mhlw_source_date import source_excel_date
from mhlw_supply_source import workbook_url

ROOT = Path(__file__).resolve().parents[1]
PAGE = '<a href="/content/10800000/{}iyakuhinkyoukyu.xlsx">供給状況</a>'


class MhlwIngestCheckTests(unittest.TestCase):
    def run_check(self, page_stamps, ingested="2026-09-18", now=dt.datetime(2026, 9, 26, 7, 15, tzinfo=JST),
                  page_error=None, source=None, version=None):
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
            return health.check_mhlw_ingest(now, version)

    def test_version_source_date_is_bound_to_the_ingested_source_record(self):
        now = dt.datetime(2026, 10, 14, 7, 15, tzinfo=JST)
        version = {"note": "2026年10月14日厚労省データ反映", "mhlw_excel_date": "2026-10-08"}
        errors, _, _ = self.run_check(["261008"], ingested="2026-10-08", now=now, version=version)
        self.assertEqual(errors, [])
        version["mhlw_excel_date"] = "2026-10-14"
        errors, _, _ = self.run_check(["261008"], ingested="2026-10-08", now=now, version=version)
        self.assertTrue(any("mhlw_source.json" in error for error in errors))

    def test_detects_published_file_not_ingested_after_a_day(self):
        # 複数URLは共通parserで曖昧として拒否する。ここでは一意な最新版の遅延を検査。
        errors, warnings, _ = self.run_check(["260925"])
        self.assertEqual(1, len(errors))
        self.assertIn("2026-09-25版", errors[0])
        self.assertIn("2026-09-18版のまま", errors[0])

    def test_public_metadata_mismatch_is_detected_during_external_outage_or_format_change(self):
        version = {"mhlw_excel_date": "2026-10-14"}
        for failure in (None, urllib.error.URLError("timeout")):
            with self.subTest(failure=failure):
                errors, warnings, results = self.run_check(
                    [], ingested="2026-10-08", page_error=failure, version=version)
                self.assertTrue(any("mhlw_source.json" in error for error in errors))
                self.assertTrue(warnings)
                self.assertEqual(results, [])

    def test_same_day_publication_only_warns(self):
        errors, warnings, _ = self.run_check(["260925"], now=dt.datetime(2026, 9, 25, 18, 0, tzinfo=JST))
        self.assertEqual([], errors)
        self.assertTrue(any("待機" in warning for warning in warnings))

    def test_waits_for_delayed_daily_update_after_midnight(self):
        # 2026-09-29 1:07、日次更新（23:10予約・実行は3時頃）より前の公開後監視が誤検知した
        errors, warnings, _ = self.run_check(
            ["260928"], ingested="2026-09-25", now=dt.datetime(2026, 9, 29, 1, 7, tzinfo=JST))
        self.assertEqual([], errors)
        self.assertTrue(any("日次更新の実行待ち" in warning for warning in warnings))
        errors, _, _ = self.run_check(
            ["260928"], ingested="2026-09-25", now=dt.datetime(2026, 9, 29, 5, 59, tzinfo=JST))
        self.assertEqual([], errors)

    def test_scheduled_morning_monitor_detects_failed_daily_update(self):
        errors, _, _ = self.run_check(
            ["260928"], ingested="2026-09-25", now=dt.datetime(2026, 9, 29, 7, 15, tzinfo=JST))
        self.assertEqual(1, len(errors))
        self.assertIn("2026-09-28版", errors[0])

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
        recorded_date = source_excel_date(record, health.jst_today())
        self.assertIsNotNone(recorded_date)
        self.assertEqual(recorded_date, record["excel_date"])
        self.assertEqual(workbook_url(record["url"]), record["url"])
        self.assertIn("supply_source_from_page(r.text, jst_today())", workflow)

    def test_numeric_filename_uses_anchor_date_and_detects_missing_ingestion(self):
        page = '<a href="/content/10800000/001758803.xlsx">医療用医薬品供給状況（令和８年10月13日現在）</a>'
        def fetch(url, _limit):
            return (page.encode() if url == health.MHLW_SUPPLY_PAGE else json.dumps({"excel_date": "2026-10-08"}).encode())
        with mock.patch.object(health, "fetch", side_effect=fetch):
            errors, warnings, results = health.check_mhlw_ingest(dt.datetime(2026, 10, 14, 7, 15, tzinfo=JST))
        self.assertEqual(warnings, [])
        self.assertTrue(any("2026-10-13版" in value for value in errors))
        self.assertTrue(any("2026-10-13" in value for value in results))


if __name__ == "__main__":
    unittest.main()
