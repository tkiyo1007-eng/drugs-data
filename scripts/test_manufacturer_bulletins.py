import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("bulletins", Path(__file__).with_name("fetch_manufacturer_bulletins.py"))
mod = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(mod)
NOW = dt.datetime(2026, 10, 14, 2, 0, tzinfo=mod.JST)
PDF = b"%PDF-1.7\noriginal public notice"


def configuration(parser="html", limit=8):
    return {"schema_version": 1, "max_document_checks_per_day": limit, "sources": [{
        "id": "test", "maker": "テスト製薬", "parser": parser,
        "index_url": "https://maker.test/news/", "link_base": "https://maker.test/",
        "index_scope": [{"host": "maker.test", "path": "/news/", "exact": True}],
        "document_scope": [{"host": "maker.test", "path": "/pdf/", "exact": False}],
    }]}


def registry(pdf=PDF, url="https://maker.test/pdf/a.pdf"):
    return {"schema_version": 1, "notices": [{"id": "verified-a", "maker": "テスト製薬", "title": "テスト錠 出荷停止",
        "url": url, "sha256": mod.digest(pdf), "listed_at": "2026-10-13"}]}


def listing(extra=""):
    return ('<table><tr><td>2026/10/13</td><td><a href="/pdf/a.pdf">テスト錠 出荷停止</a></td></tr>' + extra + '</table>').encode()


class Transport:
    def __init__(self, index=None, pdf=PDF, robots=b"User-agent: *\nAllow: /\n"):
        self.calls = []
        self.responses = {"https://maker.test/robots.txt": (200, robots, None),
                          "https://maker.test/news/": (200, listing() if index is None else index, None),
                          "https://maker.test/pdf/a.pdf": (200, pdf, None)}

    def __call__(self, url, limit):
        self.calls.append((url, limit))
        return self.responses.get(url, (404, b"", None))


class MetadataTests(unittest.TestCase):
    def test_fuso_registry_is_limited_to_the_verified_product_and_pdf(self):
        root = Path(__file__).resolve().parents[1]
        config = json.loads((root / 'manufacturer_feed_sources.json').read_text())
        notices = json.loads((root / 'manufacturer_notices.json').read_text())
        self.assertIs(mod.validate_registry(notices, config['sources']), notices)
        source = next(s for s in config['sources'] if s['id'] == 'fuso-codeine')
        notice = next(n for n in notices['notices'] if n['id'] == 'fuso-codeine-discontinuation-202509')
        self.assertTrue(mod.in_scope(notice['url'], source['document_scope']))
        self.assertEqual(1, len(source['document_scope']))
        self.assertTrue(source['document_scope'][0]['exact'])
        self.assertTrue(source['index_scope'][0]['exact'])
        for url in [notice['url'].replace('www.fuso-pharm.co.jp', 'www.fuso-pharm.co.jp.evil.test'),
                    'https://www.fuso-pharm.co.jp/med/other.pdf',
                    source['index_url'] + 'other/']:
            self.assertFalse(mod.in_scope(url, source['document_scope']))
        previous = json.loads((root / 'manufacturer_bulletins.json').read_text())
        self.assertEqual([], mod.validate_document(previous, config))

    def test_date_only_printed_listing_dates(self):
        self.assertEqual(mod.real_date("2026年10月13日更新"), "2026-10-13")
        self.assertEqual(mod.real_date("2026.10.13"), "2026-10-13")
        self.assertEqual(mod.real_date("October 1, 2026"), "2026-10-01")
        self.assertEqual(mod.real_date("2026年 10月"), "2026-10")
        self.assertIsNone(mod.real_date("2026/02/30"))
        self.assertIsNone(mod.real_date("日付なし"))

    def test_url_filename_does_not_become_date(self):
        rows = mod.parse_index('<p><a href="/pdf/20261013.pdf">テスト錠 出荷停止</a></p>'.encode(), configuration()["sources"][0])
        self.assertIsNone(rows[0]["posted_at"])

    def test_date_association_is_per_row_not_page(self):
        raw = '<p>2026/10/14</p><p><a href="/pdf/a.pdf">テスト錠 出荷停止</a></p>'.encode()
        rows = mod.parse_index(raw, configuration()["sources"][0])
        self.assertIsNone(rows[0]["posted_at"])

    def test_article_updated_date_does_not_date_an_undated_pdf_row(self):
        raw = '<article><p>ページ更新2026/10/14</p><p><a href="/pdf/a.pdf">テスト錠 出荷停止</a></p></article>'.encode()
        rows = mod.parse_index(raw, configuration()["sources"][0])
        self.assertIsNone(rows[0]["posted_at"])

    def test_sandoz_next_tables_have_dates_and_skip_external_links(self):
        source = configuration("sandoz_next")["sources"][0]
        table = '<tr><td>2026/10/13</td><td>テスト錠 出荷停止（<a href="/pdf/a.pdf">医療関係者様向け</a>）</td></tr>'
        value = {"props": {"pageProps": {"table": "<table>" + table + "</table>"}}}
        raw = ('<script id="__NEXT_DATA__" type="application/json">' + json.dumps(value) + '</script>').encode()
        rows = mod.parse_index(raw, source)
        self.assertEqual(rows[0]["posted_at"], "2026-10-13")
        self.assertIn("テスト錠 出荷停止", rows[0]["title"])
        self.assertNotIn("医療関係者様向け", rows[0]["title"])

    def test_official_api_shape_is_checked(self):
        source = configuration("pfizer_json")["sources"][0]
        with self.assertRaises(mod.CollectionError): mod.parse_index(b'{"success":true,"data":[]}', source)
        value = {"success": True, "data": {"2026": [{"title": "テスト錠 供給再開", "path": "/pdf/a.pdf", "field_announcement_date": "October 13, 2026"}]}}
        self.assertEqual(mod.parse_index(json.dumps(value).encode(), source)[0]["posted_at"], "2026-10-13")

    def test_strict_scope_no_external_credentials_or_traversal(self):
        scopes = configuration()["sources"][0]["document_scope"]
        for url in ["http://maker.test/pdf/a.pdf", "https://maker.test.evil/pdf/a.pdf", "https://maker.test@evil.test/pdf/a.pdf", "https://maker.test:8080/pdf/a.pdf", "https://maker.test/pdf/%2e%2e/secret", "https://maker.test/pdf/%252e%252e/secret", "https://maker.test/pdf/%0a", "https://maker.test/other/a.pdf"]:
            self.assertFalse(mod.in_scope(url, scopes), url)

    def test_robots_wildcard_pdf_allow_overrides_root_disallow(self):
        rules = "User-agent: *\nDisallow: /\nAllow: /sites/*.pdf\n"
        self.assertTrue(mod.robots_allowed(rules, "https://cms.test/sites/default/files/notice.pdf"))
        self.assertFalse(mod.robots_allowed(rules, "https://cms.test/sites/default/files/notice.html"))


class CollectionTests(unittest.TestCase):
    def test_confirmed_requires_registered_url_and_current_pdf_hash(self):
        transport = Transport()
        result = mod.collect(configuration(), registry(), transport=transport, now=NOW)
        item = result["items"][0]
        self.assertEqual(item["review_status"], "confirmed")
        self.assertEqual(item["notice_ids"], ["verified-a"])
        self.assertEqual(item["document_checked_at"], NOW.isoformat())
        self.assertEqual(len(result["drafts"]), 1)
        self.assertEqual(mod.validate_document(result, configuration()), [])

    def test_new_pdf_metadata_is_not_medical_content_or_confirmed(self):
        extra = '<tr><td>2026/10/14</td><td><a href="/pdf/new.pdf">新製品 供給停止</a></td></tr>'
        transport = Transport(listing(extra))
        result = mod.collect(configuration(), registry(), transport=transport, now=NOW)
        item = next(i for i in result["items"] if i["url"].endswith("new.pdf"))
        self.assertEqual(item["review_status"], "needs_review")
        self.assertEqual(item["notice_ids"], [])
        self.assertIsNone(item.get("sha256"))
        self.assertFalse(any(k in item for k in ("reason", "alternatives", "supply_status")))
        self.assertFalse(any("new.pdf" in url for url, _ in transport.calls))
        self.assertNotIn(item["id"], result["drafts"][0]["item_ids"])

    def test_same_url_updated_pdf_requires_review_and_no_draft(self):
        result = mod.collect(configuration(), registry(), transport=Transport(pdf=PDF + b" changed"), now=NOW)
        self.assertEqual(result["items"][0]["review_status"], "needs_review")
        self.assertEqual(result["drafts"], [])

    def test_index_failure_preserves_items_success_date_and_reported_date(self):
        first = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        transport = Transport(); transport.responses["https://maker.test/news/"] = (503, b"", None)
        result = mod.collect(configuration(), registry(), first, transport=transport, now=NOW + dt.timedelta(days=1))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["sources"][0]["last_success_at"], first["sources"][0]["last_success_at"])
        self.assertEqual(result["items"][0]["title"], first["items"][0]["title"])
        self.assertEqual(result["items"][0]["posted_at"], "2026-10-13")
        self.assertEqual(result["items"][0]["first_seen"], first["items"][0]["first_seen"])
        self.assertEqual(result["drafts"], [])

    def test_document_failure_preserves_previous_hash_but_cannot_confirm_current(self):
        first = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        transport = Transport(); transport.responses["https://maker.test/pdf/a.pdf"] = (503, b"", None)
        result = mod.collect(configuration(), registry(), first, transport=transport, now=NOW + dt.timedelta(days=1))
        item = result["items"][0]
        self.assertEqual(item["sha256"], first["items"][0]["sha256"])
        self.assertEqual(item["last_hash_success_at"], first["items"][0]["last_hash_success_at"])
        self.assertEqual(item["review_status"], "needs_review")
        self.assertEqual(result["drafts"], [])

    def test_login_or_captcha_response_never_confirmed_as_pdf(self):
        result = mod.collect(configuration(), registry(), transport=Transport(pdf=b"<html>Login</html>"), now=NOW)
        self.assertEqual(result["items"][0]["hash_status"], "failed")
        self.assertEqual(result["items"][0]["review_status"], "needs_review")

    def test_index_gate_redirect_is_failure_no_cookie_or_redirect_fetch(self):
        transport = Transport(); transport.responses["https://maker.test/news/"] = (302, b"", "https://maker.test/login")
        result = mod.collect(configuration(), registry(), transport=transport, now=NOW)
        self.assertEqual(result["sources"][0]["status"], "failed")
        self.assertFalse(any("/login" in url for url, _ in transport.calls))

    def test_zero_supply_records_is_failure_not_no_change(self):
        result = mod.collect(configuration(), registry(), transport=Transport(index=b"<html>no rows</html>"), now=NOW)
        self.assertEqual(result["sources"][0]["status"], "failed")
        self.assertIn("1件も", result["sources"][0]["error"])

    def test_daily_budget_prevents_index_and_pdf_refetch(self):
        first = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        transport = Transport()
        second = mod.collect(configuration(), registry(), first, transport=transport, now=NOW + dt.timedelta(hours=1))
        self.assertEqual(transport.calls, [])
        self.assertEqual(second["items"][0]["review_status"], "confirmed")
        self.assertEqual(second["drafts"], [])
        self.assertEqual(second["sources"][0]["skipped"], "daily_index_limit")

    def test_pdf_limit_is_bounded_and_failure_consumes_daily_slot(self):
        reg = registry(); reg["notices"].append(dict(reg["notices"][0], id="verified-b", url="https://maker.test/pdf/b.pdf"))
        transport = Transport(); transport.responses["https://maker.test/pdf/a.pdf"] = (503, b"", None)
        result = mod.collect(configuration(limit=1), reg, transport=transport, now=NOW)
        self.assertEqual(len(result["document_checks"]), 1)
        self.assertFalse(any("b.pdf" in url for url, _ in transport.calls))

    def test_ninth_document_is_prioritized_then_old_checks_rotate(self):
        reg = registry()
        for number in range(1, 9):
            reg["notices"].append(dict(reg["notices"][0], id=f"verified-{number}", url=f"https://maker.test/pdf/{number:02d}.pdf"))
        transport = Transport()
        for notice in reg["notices"]:
            transport.responses[notice["url"]] = (200, PDF, None)
        first = mod.collect(configuration(), reg, transport=transport, now=NOW)
        omitted = next(i for i in first["items"] if i["hash_status"] == "daily_limit")
        self.assertEqual(len(first["document_checks"]), 8)
        second = mod.collect(configuration(), reg, first, transport=transport, now=NOW + dt.timedelta(days=1))
        item = next(i for i in second["items"] if i["id"] == omitted["id"])
        self.assertEqual(item["review_status"], "confirmed")
        self.assertEqual(second["document_checks"][0]["url"], omitted["url"])
        third = mod.collect(configuration(), reg, second, transport=transport, now=NOW + dt.timedelta(days=2))
        self.assertTrue(all(i.get("last_hash_success_at") for i in third["items"]))

    def test_failed_pending_documents_rotate_by_last_attempt(self):
        reg = registry()
        for number in range(1, 9):
            reg["notices"].append(dict(reg["notices"][0], id=f"failed-{number}", url=f"https://maker.test/pdf/{number:02d}.pdf"))
        transport = Transport()
        for notice in reg["notices"]:
            transport.responses[notice["url"]] = (503, b"", None)
        first = mod.collect(configuration(), reg, transport=transport, now=NOW)
        omitted = next(i for i in first["items"] if i["hash_status"] == "daily_limit")
        second = mod.collect(configuration(), reg, first, transport=transport, now=NOW + dt.timedelta(days=1))
        self.assertEqual(second["document_checks"][0]["url"], omitted["url"])

    def test_robots_denial_stops_resource_get(self):
        transport = Transport(robots=b"User-agent: *\nDisallow: /\n")
        result = mod.collect(configuration(), registry(), transport=transport, now=NOW)
        self.assertEqual(result["status"], "failed")
        self.assertEqual([url for url, _ in transport.calls], ["https://maker.test/robots.txt"])

    def test_pfizer_robots_unavailable_is_explicit_partial(self):
        cfg = configuration(); cfg["sources"][0]["robots_4xx_unavailable"] = True
        transport = Transport(); transport.responses["https://maker.test/robots.txt"] = (403, b"", None)
        result = mod.collect(cfg, registry(), transport=transport, now=NOW)
        self.assertEqual(result["sources"][0]["status"], "partial")
        self.assertEqual(result["sources"][0]["robots_status"], "unavailable")

    def test_repeated_source_links_deduplicate(self):
        result = mod.collect(configuration(), registry(), transport=Transport(index=listing() * 2), now=NOW)
        self.assertEqual(len(result["items"]), 1)

    def test_bad_json_types_fail_closed(self):
        cfg = configuration(); cfg["max_document_checks_per_day"] = True
        with self.assertRaises(mod.CollectionError): mod.collect(cfg, registry(), transport=Transport(), now=NOW)
        bad = registry(); bad["notices"][0]["sha256"] = 123
        with self.assertRaises(mod.CollectionError): mod.collect(configuration(), bad, transport=Transport(), now=NOW)

    def test_validation_rejects_fabricated_confirmation_or_medical_content(self):
        result = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        result["items"][0]["document_checked_at"] = None
        self.assertTrue(mod.validate_document(result, configuration()))
        result = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        result["items"][0]["reason"] = "推測"
        self.assertTrue(mod.validate_document(result, configuration()))

    def test_previous_malformed_check_and_naive_timestamp_fail_before_network(self):
        result = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        result["document_checks"][0]["url"] = ["not", "a", "url"]
        transport = Transport()
        with self.assertRaises(mod.CollectionError):
            mod.collect(configuration(), registry(), result, transport=transport, now=NOW)
        self.assertEqual(transport.calls, [])
        result = mod.collect(configuration(), registry(), transport=Transport(), now=NOW)
        result["items"][0]["first_seen"] = "2026-10-14"
        self.assertTrue(mod.validate_document(result, configuration()))

    def test_towa_reuses_cache_and_reports_staleness_without_index_request(self):
        cfg = configuration("legacy_cache"); cfg["sources"][0]["reuse_source_id"] = "parse_towa"
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "maker_announcements.json").write_text(json.dumps({"product": {"maker": "テスト製薬", "title": "テスト錠 出荷停止", "url": "https://maker.test/pdf/a.pdf", "checked": "2026-10-08"}}))
            (base / "unmatched_maker_announcements.json").write_text("[]")
            (base / "maker_collection_health.json").write_text(json.dumps({"checked": "2026-10-08", "sources": [{"source": "parse_towa", "ok": True, "last_success": "2026-10-14"}]}))
            transport = Transport()
            result = mod.collect(cfg, registry(), cache_dir=base, transport=transport, now=NOW)
        self.assertEqual(result["sources"][0]["coverage"], "legacy_cache_only")
        self.assertEqual(result["sources"][0]["legacy_checked_date"], "2026-10-14")
        self.assertEqual(result["sources"][0]["legacy_collection_checked_date"], "2026-10-08")
        self.assertFalse(any("/news/" in url for url, _ in transport.calls))
        self.assertIsNone(result["items"][0]["posted_at"])


if __name__ == "__main__":
    unittest.main()
