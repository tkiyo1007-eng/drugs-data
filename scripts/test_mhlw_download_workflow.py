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

import scripts.jst_time


ROOT = Path(__file__).resolve().parents[1]


class MhlwDownloadWorkflowTests(unittest.TestCase):
    def run_download(self, page, *, page_encoding="utf-8", content_type="text/html; charset=UTF-8",
                     received_day=None):
        # 実際の日次stepを実行し、公式ページとworkbookのネットワーク境界だけを置換。
        workflow = (ROOT / ".github/workflows/update_drugs.yml").read_text()
        step = workflow.split("name: 供給状況Excel ダウンロード（厚労省ページからリンク取得）", 1)[1]
        program = textwrap.dedent(step.split("python3 - <<'EOF'\n", 1)[1].split("\n          EOF", 1)[0])
        from scripts.mhlw_supply_source import MHLW_SUPPLY_PAGE
        payload = b"test-only-workbook-payload"
        requests = types.ModuleType("requests")
        def response(body, encoding="utf-8", mime="application/octet-stream"):
            return types.SimpleNamespace(text=body.decode(encoding, errors="replace"), content=body,
                encoding=encoding, headers={"Content-Type": mime}, status_code=200,
                raise_for_status=lambda: None)
        body = page if isinstance(page, bytes) else page.encode()
        clock = [dt.date(2026, 10, 14)]
        responses = [response(body, page_encoding, content_type), response(payload)]
        def get(url, timeout):
            if url == MHLW_SUPPLY_PAGE and received_day:
                clock[0] = received_day
            return responses.pop(0)
        requests.get = mock.Mock(side_effect=get)
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as folder:
            previous = Path.cwd()
            try:
                os.chdir(folder)
                with mock.patch.dict(sys.modules, {"requests": requests}), \
                        mock.patch("scripts.jst_time.jst_today", side_effect=lambda: clock[0]), \
                        contextlib.redirect_stdout(output):
                    try:
                        exec(compile(program, "<actual-download-workflow>", "exec"), {})
                    except ValueError as error:
                        self.last_output = output.getvalue()
                        return None, requests.get.call_args_list, sorted(p.name for p in Path(folder).iterdir()), str(error)
                self.last_output = output.getvalue()
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

    def test_charset_absent_response_uses_original_bytes_and_reports_the_decoding_boundary(self):
        import hashlib
        page = '<a href="/content/10800000/001758803.xlsx">医療用医薬品供給状況（令和８年10月13日現在）</a>'
        record, calls, _, error = self.run_download(page, page_encoding="ISO-8859-1", content_type="text/html")
        self.assertIsNone(error)
        self.assertEqual(record["excel_date"], "2026-10-13")
        self.assertEqual(len(calls), 2)
        diagnostic = json.loads(self.last_output.splitlines()[0])
        self.assertEqual(diagnostic["requests_encoding"], "ISO-8859-1")
        self.assertEqual(diagnostic["checked_jst"], "2026-10-14")
        self.assertEqual(diagnostic["sha256"], hashlib.sha256(page.encode()).hexdigest())
        self.assertEqual(diagnostic["bytes"], len(page.encode()))
        self.assertEqual(diagnostic["http_status"], 200)
        self.assertEqual(diagnostic["url"], "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html")
        self.assertNotIn(page, self.last_output)

    def test_invalid_bytes_stop_before_any_file_or_workbook_request_and_leave_diagnostics(self):
        page = b'<a href="/content/10800000/001758803.xlsx">\xff</a>'
        record, calls, files, error = self.run_download(page)
        self.assertIsNone(record)
        self.assertIn("UTF-8", error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(files, [])
        diagnostic = json.loads(self.last_output.splitlines()[0])
        self.assertEqual(diagnostic["phase"], "mhlw_supply_page")
        self.assertEqual(diagnostic["bytes"], len(page))

    def test_midnight_response_uses_receipt_day_and_still_rejects_tomorrows_source(self):
        page = '<a href="/content/10800000/001758803.xlsx">医療用医薬品供給状況（令和８年10月15日現在）</a>'
        record, calls, _, error = self.run_download(page, received_day=dt.date(2026, 10, 15))
        self.assertIsNone(error)
        self.assertEqual(record["excel_date"], "2026-10-15")
        self.assertEqual(len(calls), 2)
        self.assertEqual(json.loads(self.last_output.splitlines()[0])["checked_jst"], "2026-10-15")
        record, calls, files, error = self.run_download(page.replace("10月15日", "10月16日"),
                                                       received_day=dt.date(2026, 10, 15))
        self.assertIsNone(record)
        self.assertIn("未来", error)
        self.assertEqual(len(calls), 1)
        self.assertEqual(files, [])


if __name__ == "__main__":
    unittest.main()
