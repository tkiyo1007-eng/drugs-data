import contextlib
import datetime as dt
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import textwrap
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


class MhlwDownloadWorkflowTests(unittest.TestCase):
    def run_download(self, page):
        # 実際の日次stepを実行し、公式ページとworkbookのネットワーク境界だけを置換。
        workflow = (ROOT / ".github/workflows/update_drugs.yml").read_text()
        step = workflow.split("name: 供給状況Excel ダウンロード（厚労省ページからリンク取得）", 1)[1]
        program = textwrap.dedent(step.split("python3 - <<'EOF'\n", 1)[1].split("\n          EOF", 1)[0])
        from scripts.mhlw_supply_source import MHLW_SUPPLY_PAGE
        payload = b"test-only-workbook-payload"
        requests = types.ModuleType("requests")
        def response(body):
            return types.SimpleNamespace(text=body.decode(), content=body, raise_for_status=lambda: None)
        requests.get = mock.Mock(side_effect=[response(page.encode()), response(payload)])
        with tempfile.TemporaryDirectory() as folder:
            previous = Path.cwd()
            try:
                os.chdir(folder)
                with mock.patch.dict(sys.modules, {"requests": requests}), \
                        mock.patch("scripts.jst_time.jst_today", return_value=dt.date(2026, 10, 14)), \
                        contextlib.redirect_stdout(io.StringIO()):
                    try:
                        exec(compile(program, "<actual-download-workflow>", "exec"), {})
                    except ValueError as error:
                        return None, requests.get.call_args_list, sorted(p.name for p in Path(folder).iterdir()), str(error)
                record = json.loads(Path("mhlw_source.json").read_text())
                self.assertEqual(Path("supply_latest.xlsx").read_bytes(), payload)
                requests.get.assert_any_call(MHLW_SUPPLY_PAGE, timeout=30)
                return record, requests.get.call_args_list, [], None
            finally:
                os.chdir(previous)

    def test_real_step_records_numeric_url_and_explicit_date_before_core_publish(self):
        record, calls, _, error = self.run_download(
            '<a href="/content/10800000/001758803.xlsx">医療用医薬品供給状況（令和８年10月13日現在）</a>')
        self.assertIsNone(error)
        self.assertEqual(record, {"file": "001758803.xlsx", "url": "https://www.mhlw.go.jp/content/10800000/001758803.xlsx", "excel_date": "2026-10-13"})
        self.assertEqual(calls[1], mock.call(record["url"], timeout=60))

    def test_ambiguous_or_undated_source_stops_before_download_or_metadata_write(self):
        valid = '<a href="/content/10800000/001758803.xlsx">医療用医薬品供給状況（令和８年10月13日現在）</a>'
        for page in [valid + valid.replace("001758803", "001758804"), valid.replace("（令和８年10月13日現在）", "")]:
            with self.subTest(page=page):
                record, calls, files, error = self.run_download(page)
                self.assertIsNone(record)
                self.assertTrue(error)
                self.assertEqual(len(calls), 1)
                self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
