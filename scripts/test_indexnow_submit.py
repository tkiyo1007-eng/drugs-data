import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import indexnow_submit as mod

ROOT = Path(__file__).resolve().parents[1]


class IndexNowTests(unittest.TestCase):
    def make_site(self, files):
        tmp = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (tmp / name).write_text(text, encoding="utf-8")
        return tmp

    def test_selects_only_recent_own_urls_without_duplicates(self):
        site = self.make_site({
            "sitemap.xml": "<urlset><url><loc>https://kyokyu-navi.jp/</loc><lastmod>2026-10-03</lastmod></url>"
                           "<url><loc>https://kyokyu-navi.jp/about.html</loc><lastmod>2026-09-01</lastmod></url></urlset>",
            "sitemap-updates.xml": "<urlset><url><loc>https://kyokyu-navi.jp/updates/2026-10-02.html</loc><lastmod>2026-10-02</lastmod></url>"
                                   "<url><loc>https://kyokyu-navi.jp/</loc><lastmod>2026-10-03</lastmod></url>"
                                   "<url><loc>https://example.com/x</loc><lastmod>2026-10-03</lastmod></url></urlset>",
        })
        urls = mod.recent_urls(site, dt.date(2026, 10, 2))
        self.assertEqual(urls, ["https://kyokyu-navi.jp/", "https://kyokyu-navi.jp/updates/2026-10-02.html"])

    def test_payload_points_to_published_key_file(self):
        payload = mod.build_payload("0" * 32, ["https://kyokyu-navi.jp/"])
        self.assertEqual(payload["host"], "kyokyu-navi.jp")
        self.assertEqual(payload["keyLocation"], "https://kyokyu-navi.jp/" + "0" * 32 + ".txt")

    def test_repository_has_exactly_one_valid_key_file(self):
        key = mod.find_key(ROOT)
        self.assertRegex(key, r"^[0-9a-f]{32}$")
        self.assertEqual((ROOT / f"{key}.txt").read_text(encoding="utf-8").strip(), key)

    def test_dry_run_never_posts(self):
        with mock.patch.object(mod, "submit") as submit, \
             mock.patch("sys.argv", ["indexnow_submit.py", "--site", str(ROOT), "--days", "3650"]):
            self.assertEqual(mod.main(), 0)
        submit.assert_not_called()

    def test_workflow_is_gated_by_repository_variable(self):
        workflow = (ROOT / ".github/workflows/indexnow.yml").read_text(encoding="utf-8")
        self.assertIn("vars.INDEXNOW_ENABLED", workflow)
        self.assertIn("workflows: ['Deploy GitHub Pages']", workflow)
        self.assertIn("python3 scripts/indexnow_submit.py --submit", workflow)


if __name__ == "__main__":
    unittest.main()
