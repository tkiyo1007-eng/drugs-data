from __future__ import annotations

import datetime as dt
import ast
import contextlib
import io
import json
import textwrap
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


class PublishedDiscoveryHealthTests(unittest.TestCase):
    """実際のWorkflowの定義を再利用し、HTTPと再試行だけを隔離する。"""

    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / '.github/workflows/public-data-health.yml').read_text(encoding='utf-8')
        source = textwrap.dedent(workflow.split("python3 - <<'PY'\n", 1)[1].rsplit('\n          PY', 1)[0])
        tree = ast.parse(source)
        # import・定義・定数だけをロード。ネットワーク取得する末尾forは別途模擬試験。
        definitions = [node for node in tree.body if not isinstance(node, ast.For)]
        self.retry_loop = ast.Module(body=[node for node in tree.body if isinstance(node, ast.For)], type_ignores=[])
        self.scope = {}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), '<published-health-definitions>', 'exec'), self.scope)
        self.real_fetch = self.scope['fetch']
        self.site = self.scope['SITE_ROOT']
        self.files = {self.site + name: (root / name).read_bytes()
                      for name in ('sitemap-index.xml', *self.scope['SITEMAPS'])}
        self.files.update({url: (root / url.removeprefix(self.site)).read_bytes()
                           for url in self.scope['HUB_URLS']})
        self.fetch = mock.Mock(side_effect=lambda url: self.files[url])
        self.scope['fetch'] = self.fetch

    def check(self):
        # 予期せずネットワーク取得を行う変更を検知する。
        with mock.patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden')):
            return self.scope['validate_live_pages']()

    def test_all_five_sitemaps_and_five_hubs_are_checked(self):
        self.assertEqual([], self.check())
        self.assertEqual(10, self.fetch.call_count)
        self.assertEqual(set(self.files), {call.args[0] for call in self.fetch.call_args_list})

    def test_fetch_accepts_cache_buster_but_rejects_wrong_final_destination(self):
        url = self.site + 'sitemap-items.xml'
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b'valid body'
        with mock.patch('urllib.request.urlopen', return_value=response):
            response.geturl.return_value = url + '?health_check=123'
            self.assertEqual(b'valid body', self.real_fetch(url))
            for destination in ('https://outside.invalid/a', self.site + 'wrong.xml',
                                url.replace('https:', 'http:')):
                with self.subTest(destination=destination):
                    response.geturl.return_value = destination
                    with self.assertRaisesRegex(RuntimeError, '想定外'):
                        self.real_fetch(url)

    def test_parent_rejects_http_failures_and_does_not_follow_untrusted_urls(self):
        original = self.files[self.site + 'sitemap-index.xml']
        for status in (404, 500):
            with self.subTest(status=status):
                self.fetch.side_effect = lambda url: (_ for _ in ()).throw(
                    urllib.error.HTTPError(url, status, 'test', {}, None)) if url.endswith('sitemap-index.xml') else self.files[url]
                self.assertTrue(any('sitemap-index.xml' in error for error in self.check()))
        self.fetch.side_effect = lambda url: self.files[url]
        self.files[self.site + 'sitemap-index.xml'] = original.replace(
            (self.site + 'sitemap.xml').encode(), b'https://example.test/foreign.xml')
        self.assertTrue(self.check())
        self.assertFalse(any('example.test' in call.args[0] for call in self.fetch.call_args_list))

    def test_invalid_xml_shapes_and_locations_are_rejected(self):
        parse = self.scope['sitemap_locations']
        prefix = '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        valid = self.site + 'items/index.html'
        invalid = [b'<', b'<html>not xml</html>', b'<urlset/>',
                   (prefix + '</urlset>').encode(),
                   (prefix + '<url/></urlset>').encode(),
                   (prefix + '<url><loc/></url></urlset>').encode(),
                   (prefix + f'<url><loc>{valid}</loc><loc>{valid}</loc></url></urlset>').encode()]
        for url in ('https://example.test/a', self.site + '../a', self.site + '%2e%2e/a',
                    self.site + 'items/a.html?q=1', self.site + 'items/a.html#fragment'):
            invalid.append((prefix + f'<url><loc>{url}</loc></url></urlset>').encode())
        for body in invalid:
            with self.subTest(body=body):
                with self.assertRaises((ValueError, self.scope['ET'].ParseError)):
                    parse(body)

    def test_missing_or_duplicate_parent_children_are_rejected(self):
        original = self.files[self.site + 'sitemap-index.xml']
        tree = self.scope['ET'].fromstring(original)
        entry = tree[0]
        tree.remove(entry)
        self.files[self.site + 'sitemap-index.xml'] = self.scope['ET'].tostring(tree)
        self.assertTrue(self.check())
        tree.append(entry)
        tree.append(entry)
        self.files[self.site + 'sitemap-index.xml'] = self.scope['ET'].tostring(tree)
        self.assertTrue(self.check())

    def test_child_failures_and_cross_sitemap_duplicates_are_rejected(self):
        for name in self.scope['SITEMAPS']:
            original = self.files[self.site + name]
            with self.subTest(name=name):
                self.files[self.site + name] = b'<html>temporary failure</html>'
                self.assertTrue(any(name in error for error in self.check()))
                self.files[self.site + name] = original
        tree = self.scope['ET'].fromstring(self.files[self.site + 'sitemap-updates.xml'])
        root_entry = self.scope['ET'].fromstring(self.files[self.site + 'sitemap.xml'])[0]
        tree.append(root_entry)
        self.files[self.site + 'sitemap-updates.xml'] = self.scope['ET'].tostring(tree)
        self.assertTrue(any('重複' in error for error in self.check()))

    def test_fifth_hub_requires_listing_canonical_and_indexable_robots(self):
        url = self.site + 'items/recent-restrictions.html'
        original = self.files[url]
        for replacement in (b'<html>missing canonical</html>', original.replace(b'index,follow', b'noindex,follow'),
                            original.replace(url.encode(), (self.site + 'wrong.html').encode())):
            with self.subTest(replacement=replacement[:60]):
                self.files[url] = replacement
                self.assertTrue(any(url in error for error in self.check()))
        self.files[url] = original
        tree = self.scope['ET'].fromstring(self.files[self.site + 'sitemap-items.xml'])
        for entry in list(tree):
            if entry.findtext(self.scope['NAMESPACE'] + 'loc') == url:
                tree.remove(entry)
        self.files[self.site + 'sitemap-items.xml'] = self.scope['ET'].tostring(tree)
        self.assertTrue(any('ハブがありません' in error for error in self.check()))

    def test_retry_recovers_without_waiting_or_network(self):
        validator = mock.Mock(side_effect=[['temporary'], []])
        self.scope['validate_live_pages'] = validator
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(self.scope['time'], 'sleep') as sleep:
            exec(compile(self.retry_loop, '<published-health-retries>', 'exec'), self.scope)
        self.assertEqual(2, validator.call_count)
        sleep.assert_called_once_with(10)

    def test_persistent_failure_stops_after_six_attempts(self):
        validator = mock.Mock(return_value=['persistent'])
        self.scope['validate_live_pages'] = validator
        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(self.scope['time'], 'sleep') as sleep:
            with self.assertRaises(SystemExit) as error:
                exec(compile(self.retry_loop, '<published-health-retries>', 'exec'), self.scope)
        self.assertEqual(1, error.exception.code)
        self.assertEqual(6, validator.call_count)
        self.assertEqual(5, sleep.call_count)


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
