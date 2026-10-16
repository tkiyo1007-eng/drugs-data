import contextlib
from datetime import date, datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock
import urllib.error

try:
    from scripts import extract_pdf_packages as packages
except ImportError:
    import extract_pdf_packages as packages


class PdfResponse(io.BytesIO):
    def __init__(self, body, content_type="application/pdf", status=200):
        super().__init__(body)
        self.headers = {} if content_type is None else {"Content-Type": content_type}
        self.status = status
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class ExtractPdfPackagesTests(unittest.TestCase):
    def extract(self, body=b"%PDF-fixture", *, content_type="application/pdf", url="https://maker.example/notice.pdf",
                texts=("PTP100錠 2027年3月",), error=None, status=200):
        response = PdfResponse(body, content_type, status)
        transport = mock.Mock(side_effect=error, return_value=response)
        opener = types.SimpleNamespace(open=transport)
        reader = mock.Mock(return_value=types.SimpleNamespace(
            pages=[types.SimpleNamespace(extract_text=mock.Mock(return_value=text)) for text in texts]))
        pypdf = types.SimpleNamespace(PdfReader=reader)
        with mock.patch.object(packages.urllib.request, "urlopen", transport), \
                mock.patch.object(packages.urllib.request, "build_opener", return_value=opener) as build, \
                mock.patch.dict(sys.modules, {"pypdf": pypdf}):
            try:
                result = packages.extract_from_pdf(url)
            except Exception as caught:
                result = caught
        return result, response, transport, reader, build

    def test_unicode_request_is_ascii_without_changing_existing_escapes_or_query_structure(self):
        url = "https://maker.example/資料%20file/案内 1.pdf?name=包装%2F規格&download=1+2#page=3"
        result, _, transport, _, _ = self.extract(url=url)
        self.assertEqual(result, [{"pkg": "PTP100錠", "until": "2027年3月"}])
        sent = transport.call_args.args[0].full_url
        self.assertTrue(sent.isascii())
        self.assertEqual(sent, "https://maker.example/%E8%B3%87%E6%96%99%20file/%E6%A1%88%E5%86%85%201.pdf?name=%E5%8C%85%E8%A3%85%2F%E8%A6%8F%E6%A0%BC&download=1+2")
        self.assertNotIn("%2520", sent)
        self.assertEqual(transport.call_args.kwargs, {"timeout": 40})

    def test_invalid_uri_is_rejected_before_transport(self):
        for url in [None, 3, "", "/notice.pdf", "file:///tmp/notice.pdf", "http://maker.example/a.pdf",
                    "https://user:password@maker.example/a.pdf", "https://maker.example:444/a.pdf",
                    "https://maker.example/a\npdf", "https://maker.example/a\\b.pdf",
                    "https://maker.example/bad%2.pdf", "https://maker.example:bad/a.pdf",
                    "https://maker .example/a.pdf", "https://maker%20.example/a.pdf"]:
            with self.subTest(url=url):
                result, _, transport, reader, _ = self.extract(url=url)
                self.assertIsInstance(result, ValueError)
                transport.assert_not_called()
                reader.assert_not_called()

    def test_empty_or_non_pdf_body_never_reaches_pdf_parser(self):
        for body in [b"", b" \n", b"<!DOCTYPE html><p>Medical professional login</p>", b"not a pdf"]:
            with self.subTest(body=body):
                result, _, _, reader, _ = self.extract(body=body)
                self.assertIsInstance(result, ValueError)
                reader.assert_not_called()

    def test_html_or_unexpected_content_type_is_rejected_even_with_pdf_prefix(self):
        for mime in ["text/html; charset=utf-8", "application/xhtml+xml", "application/json"]:
            with self.subTest(mime=mime):
                result, _, _, reader, _ = self.extract(content_type=mime)
                self.assertIsInstance(result, ValueError)
                reader.assert_not_called()

    def test_pdf_magic_is_required_with_missing_or_generic_type(self):
        for mime in [None, "application/octet-stream", "application/x-pdf", "APPLICATION/PDF; charset=binary"]:
            with self.subTest(mime=mime):
                result, _, _, reader, _ = self.extract(body=b" \r\n%PDF-fixture", content_type=mime)
                self.assertEqual(result, [{"pkg": "PTP100錠", "until": "2027年3月"}])
                self.assertEqual(reader.call_args.args[0].getvalue(), b" \r\n%PDF-fixture")

    def test_read_is_bounded_and_oversize_data_is_not_parsed(self):
        limit = 8 * 1024 * 1024
        for body in [b"%PDF-" + b"x" * limit, b"<!DOC" + b"x" * limit]:
            with self.subTest(prefix=body[:5]):
                result, response, _, reader, _ = self.extract(body=body)
                self.assertIsInstance(result, ValueError)
                self.assertEqual(response.read_sizes, [limit + 1])
                reader.assert_not_called()
        result, response, _, _, _ = self.extract(body=b"%PDF-" + b"x" * (limit - 5))
        self.assertIsInstance(result, list)
        self.assertEqual(response.read_sizes, [limit + 1])

    def test_http_authentication_failure_is_not_retried_or_parsed(self):
        error = urllib.error.HTTPError("https://maker.example/a.pdf", 401, "Unauthorized", {}, None)
        result, _, transport, reader, _ = self.extract(error=error)
        self.assertIs(result, error)
        self.assertEqual(transport.call_count, 1)
        reader.assert_not_called()

    def test_redirect_is_not_automatically_followed_to_a_gate(self):
        result, _, _, _, build = self.extract()
        self.assertIsInstance(result, list)
        self.assertEqual(build.call_count, 1)
        handlers = build.call_args.args
        request = packages.urllib.request.Request("https://maker.example/a.pdf")
        redirect_handlers = [h for h in handlers if isinstance(h, packages.urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirect_handlers), 1)
        self.assertIsNone(redirect_handlers[0].redirect_request(
            request, None, 302, "Found", {}, "https://maker.example/login"))

    def test_non_success_status_and_pdf_parser_error_remain_failures(self):
        for status in [204, 302, 403, 500]:
            with self.subTest(status=status):
                result, _, _, reader, _ = self.extract(status=status)
                self.assertIsInstance(result, ValueError)
                reader.assert_not_called()
        with mock.patch.dict(sys.modules, {"pypdf": types.SimpleNamespace(
                PdfReader=mock.Mock(side_effect=RuntimeError("AES dependency unavailable")))}), \
                mock.patch.object(packages.urllib.request, "urlopen", return_value=PdfResponse(b"%PDF-fixture")), \
                mock.patch.object(packages.urllib.request, "build_opener", return_value=types.SimpleNamespace(
                    open=mock.Mock(return_value=PdfResponse(b"%PDF-fixture")))):
            with self.assertRaisesRegex(RuntimeError, "AES dependency unavailable"):
                packages.extract_from_pdf("https://maker.example/a.pdf")

    def test_existing_four_page_ten_entry_extraction_rules_and_empty_success_are_preserved(self):
        texts = ["ＰＴＰ１００錠 2027年3月\nPTP100錠 2027年3月\nバラ500錠",
                 "PTP200錠\nPTP300錠\nPTP400錠\nPTP500錠",
                 "分包1包\n分包2包\n分包3包\n分包4包",
                 "瓶5mL", "PTP999錠 2099年1月"]
        result, _, _, reader, _ = self.extract(texts=texts)
        self.assertEqual(len(result), 10)
        self.assertEqual(result[:2], [{"pkg": "PTP100錠", "until": "2027年3月"}, {"pkg": "バラ500錠", "until": ""}])
        self.assertNotIn({"pkg": "PTP999錠", "until": "2099年1月"}, result)
        pages = reader.return_value.pages
        self.assertTrue(all(page.extract_text.call_count == 1 for page in pages[:4]))
        pages[4].extract_text.assert_not_called()
        result, _, _, _, _ = self.extract(texts=("包装単位の記載なし", None))
        self.assertEqual(result, [])

    def run_main(self, announcements, existing=None, *, limit=60, extraction=None, day=date(2026, 10, 17)):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            ann, out, cache = path / "ann.json", path / "out.json", path / "cache.json"
            ann.write_text(json.dumps(announcements, ensure_ascii=False))
            if existing is not None:
                cache.write_text(json.dumps(existing, ensure_ascii=False))
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["extract_pdf_packages", str(ann), str(out), str(limit)]), \
                    mock.patch.object(packages, "CACHE_FILE", str(cache)), \
                    mock.patch.object(packages, "extract_from_pdf", side_effect=extraction) as extract, \
                    contextlib.redirect_stderr(output):
                packages.main(day=day)
            return json.loads(cache.read_text()), json.loads(out.read_text()), extract.call_args_list, output.getvalue()

    def test_failed_duplicate_uses_one_url_slot_and_available_following_pdf_is_attempted(self):
        failure, success = "https://maker.example/failure.pdf", "https://maker.example/success.pdf"
        value = [{"pkg": "PTP100錠", "until": ""}]
        def extract(url):
            if url == failure:
                raise ValueError("HTML職種確認画面")
            return value
        cache, result, calls, output = self.run_main({
            "失敗A": {"url": failure}, "失敗B": {"url": failure}, "成功C": {"url": success}}, limit=2, extraction=extract)
        self.assertEqual(calls, [mock.call(failure), mock.call(success)])
        self.assertEqual(cache, {success: value})
        self.assertEqual(result, {"成功C": value})
        self.assertEqual(output.count("[WARN]"), 1)
        self.assertIn("取得試行: 2URL / 成功: 1URL / 失敗: 1URL / 上限待ち: 0URL", output)

    def test_preserved_cache_success_empty_pdf_and_deferred_unique_urls_are_distinct(self):
        old, success, empty, later = [f"https://maker.example/{name}.pdf" for name in ("old", "success", "empty", "later")]
        value = [{"pkg": "PTP100錠", "until": "2027年3月"}]
        cache, result, calls, output = self.run_main({
            "既存": {"url": old}, "成功A": {"url": success}, "成功B": {"url": success},
            "包装なしA": {"url": empty}, "包装なしB": {"url": empty}, "上限A": {"url": later}, "上限B": {"url": later}},
            {old: value}, limit=2, extraction=lambda url: [] if url == empty else value)
        self.assertEqual(calls, [mock.call(success), mock.call(empty)])
        self.assertEqual(cache, {old: value, success: value, empty: []})
        self.assertEqual(result, {"既存": value, "成功A": value, "成功B": value})
        self.assertIn("取得試行: 2URL / 成功: 2URL / 失敗: 0URL / 上限待ち: 1URL", output)
        self.assertIn("キャッシュ計: 3URL / 包装情報あり: 3品目", output)

    def test_all_failures_preserve_previous_success_and_retry_on_the_next_run(self):
        failed, old = "https://maker.example/failure.pdf", "https://maker.example/old.pdf"
        value = [{"pkg": "バラ500錠", "until": ""}]
        previous = {old: value}
        for _ in range(2):
            cache, result, calls, output = self.run_main({"未確認": {"url": failed}, "既存": {"url": old}},
                previous, extraction=RuntimeError("取得不能"))
            self.assertEqual(cache, previous)
            self.assertEqual(result, {"既存": value})
            self.assertEqual(calls, [mock.call(failed)])
            self.assertIn("取得試行: 1URL / 成功: 0URL / 失敗: 1URL / 上限待ち: 0URL", output)
            previous = cache

    def test_zero_limit_keeps_cache_and_counts_only_unique_waiting_urls(self):
        cache, result, calls, output = self.run_main({"A": {"url": "https://maker.example/a.pdf"},
            "B": {"url": "https://maker.example/a.pdf"}}, limit=0)
        self.assertEqual((cache, result, calls), ({}, {}, []))
        self.assertIn("取得試行: 0URL / 成功: 0URL / 失敗: 0URL / 上限待ち: 1URL", output)

    def test_cli_cannot_raise_the_daily_sixty_url_ceiling(self):
        for limit in [-1, 61]:
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.run_main({}, limit=limit)

    def test_default_ceiling_limits_unique_failed_urls_even_with_repeated_names(self):
        announcements = {}
        for number in range(70):
            for alias in ("A", "B"):
                announcements[f"品目{number}{alias}"] = {"url": f"https://maker.example/{number}.pdf"}
        cache, result, calls, output = self.run_main(announcements, extraction=RuntimeError("取得不能"))
        self.assertEqual(cache, {})
        self.assertEqual(result, {})
        self.assertEqual(len(calls), 60)
        self.assertEqual(len({call.args[0] for call in calls}), 60)
        self.assertIn("取得試行: 60URL / 成功: 0URL / 失敗: 60URL / 上限待ち: 10URL", output)

    def test_daily_rotation_covers_every_raw_url_with_a_fixed_order_and_budget(self):
        # Actual main must reach later URLs even when every earlier attempt fails.
        for total, limit in [(7, 3), (120, 60), (121, 60), (1053, 60), (5, 1)]:
            announcements = {f"品目{i}": {"url": f"https://maker.example/{i}.pdf"} for i in range(total)}
            urls = [info["url"] for info in announcements.values()]
            reached = set()
            for offset in range((total + limit - 1) // limit):
                day = date(2026, 10, 17) + timedelta(days=offset)
                with self.subTest(total=total, limit=limit, day=day):
                    cache, result, calls, output = self.run_main(announcements, limit=limit,
                        extraction=RuntimeError("取得不能"), day=day)
                    start = (day.toordinal() * limit) % total
                    expected = (urls[start:] + urls[:start])[:limit]
                    self.assertEqual([call.args[0] for call in calls], expected)
                    self.assertEqual((cache, result), ({}, {}))
                    self.assertEqual(len(calls), min(total, limit))
                    reached.update(expected)
            self.assertEqual(reached, set(urls), (total, limit))

    def test_rotation_uses_raw_unique_order_before_skipping_cache_and_aliases(self):
        urls = [f"https://maker.example/{i}.pdf" for i in range(7)]
        announcements = {}
        for i, url in enumerate(urls):
            announcements[f"品目{i}"] = {"url": url}
            announcements[f"別名{i}"] = {"url": url}
        value = [{"pkg": "PTP100錠", "until": ""}]
        previous = {urls[1]: value, urls[3]: []}
        reached = set()
        for offset in range(4):
            day = date(2026, 10, 17) + timedelta(days=offset)
            start = day.toordinal() * 2 % len(urls)
            raw_order = urls[start:] + urls[:start]
            expected = [url for url in raw_order if url not in previous][:2]
            cache, result, calls, output = self.run_main(announcements, previous, limit=2,
                extraction=RuntimeError("取得不能"), day=day)
            self.assertEqual([call.args[0] for call in calls], expected)
            self.assertEqual(cache, previous)
            self.assertEqual(list(result), ["品目1", "別名1"])
            self.assertEqual(len(calls), 2)
            self.assertIn("上限待ち: 3URL", output)
            reached.update(expected)
        self.assertEqual(reached, set(urls) - set(previous))

    def test_same_jst_day_repeats_deterministically_without_normalizing_raw_keys(self):
        urls = ["https://maker.example/案内.pdf", "https://maker.example/%E6%A1%88%E5%86%85.pdf",
                "https://maker.example/a.pdf#page=1", "https://maker.example/a.pdf#page=2",
                "https://maker.example/a.pdf?x=1+2", "https://maker.example/a.pdf?x=1%202"]
        announcements = {f"品目{i}": {"url": url} for i, url in enumerate(urls)}
        runs = [self.run_main(announcements, limit=3, extraction=RuntimeError("取得不能")) for _ in range(2)]
        self.assertEqual(runs[0], runs[1])
        reached = set()
        for offset in range(2):
            cache, result, calls, output = self.run_main(announcements, limit=3,
                extraction=lambda url: [{"pkg": url, "until": ""}],
                day=date(2026, 10, 17) + timedelta(days=offset))
            self.assertEqual(set(cache), {call.args[0] for call in calls})
            self.assertEqual(list(result), [name for name, info in announcements.items() if info["url"] in cache])
            for name, entries in result.items():
                self.assertEqual(entries, [{"pkg": announcements[name]["url"], "until": ""}])
            reached.update(cache)
        self.assertEqual(reached, set(urls))

    def test_jst_date_changes_at_utc_fifteen_and_is_read_once_per_run(self):
        announcements = {f"品目{i}": {"url": f"https://maker.example/{i}.pdf"} for i in range(7)}
        instants = [datetime(2026, 10, 16, 14, 59, 59, tzinfo=timezone.utc),
                    datetime(2026, 10, 16, 15, 0, 0, tzinfo=timezone.utc)]
        orders = []
        for instant, jst_day in zip(instants, [date(2026, 10, 16), date(2026, 10, 17)]):
            with mock.patch.object(packages, "datetime") as clock:
                clock.now.side_effect = lambda tz: instant.astimezone(tz)
                _, _, calls, _ = self.run_main(announcements, limit=3,
                    extraction=RuntimeError("取得不能"), day=None)
            clock.now.assert_called_once_with(timezone(timedelta(hours=9)))
            explicit = self.run_main(announcements, limit=3,
                extraction=RuntimeError("取得不能"), day=jst_day)
            self.assertEqual(calls, explicit[2])
            orders.append(calls)
        self.assertNotEqual(orders[0], orders[1])

    def test_empty_announcements_and_zero_limit_never_fetch_or_divide_by_zero(self):
        for announcements in [{}, {"A": {"url": "https://maker.example/a.pdf"},
                                  "別名A": {"url": "https://maker.example/a.pdf"}}]:
            for limit in ([0, 60] if not announcements else [0]):
                with self.subTest(announcements=announcements, limit=limit):
                    cache, result, calls, output = self.run_main(announcements, limit=limit, day=None)
                    self.assertEqual((cache, result, calls), ({}, {}, []))
                    self.assertIn("取得試行: 0URL / 成功: 0URL / 失敗: 0URL", output)

    def test_actual_response_boundaries_write_only_successful_package_values(self):
        origin = "https://maker.example/"
        old_value = [{"pkg": "バラ500錠", "until": ""}]
        new_value = [{"pkg": "PTP100錠", "until": "2027年3月"}]
        invalid = "file:///tmp/not-a-manufacturer.pdf"
        urls = {name: origin + name + ".pdf" for name in ("old", "good", "no-packages", "html", "empty", "large", "unauthorized")}
        responses = {
            urls["good"]: (b"%PDF-good", "application/pdf"),
            urls["no-packages"]: (b"%PDF-no-packages", None),
            urls["html"]: (b"<!DOCTYPE html>login", "text/html"),
            urls["empty"]: (b"", "application/pdf"),
            urls["large"]: (b"%PDF-" + b"x" * (8 * 1024 * 1024), "application/pdf"),
        }
        def transport(request, timeout):
            url = request.full_url
            if url == urls["unauthorized"]:
                raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
            return PdfResponse(*responses[url])
        def parse(stream):
            text = "包装記載なし" if stream.getvalue() == b"%PDF-no-packages" else "PTP100錠 2027年3月"
            return types.SimpleNamespace(pages=[types.SimpleNamespace(extract_text=lambda: text)])
        network = mock.Mock(side_effect=transport)
        announcements = {name: {"url": url} for name, url in urls.items()}
        announcements["invalid"] = {"url": invalid}
        announcements["html-alias"] = {"url": urls["html"]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            ann, out, cache = path / "ann.json", path / "out.json", path / "cache.json"
            ann.write_text(json.dumps(announcements))
            cache.write_text(json.dumps({urls["old"]: old_value}))
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["extract_pdf_packages", str(ann), str(out)]), \
                    mock.patch.object(packages, "CACHE_FILE", str(cache)), \
                    mock.patch.object(packages.urllib.request, "build_opener", return_value=types.SimpleNamespace(open=network)), \
                    mock.patch.dict(sys.modules, {"pypdf": types.SimpleNamespace(PdfReader=parse)}), \
                    contextlib.redirect_stderr(output):
                packages.main(day=date(2026, 10, 17))
            self.assertEqual(json.loads(cache.read_text()), {urls["old"]: old_value,
                urls["good"]: new_value, urls["no-packages"]: []})
            self.assertEqual(json.loads(out.read_text()), {"old": old_value, "good": new_value})
            self.assertEqual(len(network.call_args_list), 6)
            self.assertNotIn(invalid, [call.args[0].full_url for call in network.call_args_list])
            self.assertIn("取得試行: 7URL / 成功: 2URL / 失敗: 5URL / 上限待ち: 0URL", output.getvalue())


if __name__ == "__main__":
    unittest.main()
