import re
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/"
SITEMAPS = {
    "sitemap.xml",
    "sitemap-items.xml",
    "sitemap-updates.xml",
    "sitemap-curated.xml",
}
SITEMAP_INDEX = "sitemap-index.xml"
XML_NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def sitemap_entries(path: Path) -> list[tuple[str, str]]:
    root = ET.parse(path).getroot()
    entries = []
    for node in root.findall("sm:url", XML_NAMESPACE):
        location = (node.findtext("sm:loc", default="", namespaces=XML_NAMESPACE)).strip()
        lastmod = (node.findtext("sm:lastmod", default="", namespaces=XML_NAMESPACE)).strip()
        entries.append((location, lastmod))
    return entries


def sitemap_index_locations(path: Path) -> list[str]:
    root = ET.parse(path).getroot()
    return [
        (node.findtext("sm:loc", default="", namespaces=XML_NAMESPACE)).strip()
        for node in root.findall("sm:sitemap", XML_NAMESPACE)
    ]


def local_path(location: str) -> Path:
    relative = location.removeprefix(SITE_ROOT)
    return ROOT / (relative or "index.html")


class SitemapIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries_by_sitemap = {
            name: sitemap_entries(ROOT / name) for name in SITEMAPS
        }
        cls.all_entries = [
            (name, location, lastmod)
            for name, entries in cls.entries_by_sitemap.items()
            for location, lastmod in entries
        ]
        cls.index_locations = sitemap_index_locations(ROOT / SITEMAP_INDEX)

    def test_robots_declares_only_the_parent_sitemap_index(self):
        robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
        declared = re.findall(r"^Sitemap:\s*(\S+)\s*$", robots, re.MULTILINE)
        self.assertEqual([SITE_ROOT + SITEMAP_INDEX], declared)

    def test_parent_index_lists_each_sitemap_group_exactly_once(self):
        expected = {SITE_ROOT + name for name in SITEMAPS}
        self.assertEqual(expected, set(self.index_locations))
        self.assertEqual(len(self.index_locations), len(set(self.index_locations)))
        for location in self.index_locations:
            with self.subTest(location=location):
                name = location.removeprefix(SITE_ROOT)
                self.assertTrue((ROOT / name).is_file())

    def test_sitemap_locations_are_unique_existing_canonical_pages(self):
        locations = [location for _, location, _ in self.all_entries]
        self.assertEqual(len(locations), len(set(locations)), "URLが複数のsitemapに重複しています")
        for sitemap_name, location, _ in self.all_entries:
            with self.subTest(sitemap=sitemap_name, location=location):
                parsed = urlsplit(location)
                self.assertTrue(location.startswith(SITE_ROOT))
                self.assertFalse(parsed.query)
                self.assertFalse(parsed.fragment)
                page = local_path(location)
                self.assertTrue(page.is_file(), f"公開先に対応するHTMLがありません: {page}")
                content = page.read_text(encoding="utf-8")
                canonicals = re.findall(
                    r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
                    content,
                    re.IGNORECASE,
                )
                self.assertEqual([location], canonicals)

    def test_lastmod_values_are_iso_dates_when_present(self):
        for sitemap_name, location, lastmod in self.all_entries:
            if not lastmod:
                continue
            with self.subTest(sitemap=sitemap_name, location=location):
                self.assertEqual(date.fromisoformat(lastmod).isoformat(), lastmod)

    def test_every_generated_html_is_listed_in_its_sitemap_group(self):
        expected_by_sitemap = {
            "sitemap-items.xml": set((ROOT / "items").glob("*.html")),
            "sitemap-updates.xml": set((ROOT / "updates").glob("*.html")),
            "sitemap-curated.xml": set().union(*(
                set((ROOT / directory).glob("*.html"))
                for directory in ("topics", "products", "guides")
            )),
        }
        for sitemap_name, expected_paths in expected_by_sitemap.items():
            listed_paths = {
                local_path(location) for location, _ in self.entries_by_sitemap[sitemap_name]
            }
            with self.subTest(sitemap=sitemap_name):
                self.assertTrue(expected_paths)
                self.assertEqual(expected_paths, listed_paths)

    def test_primary_sitemap_has_only_top_level_public_pages(self):
        expected = {ROOT / "index.html", ROOT / "privacy.html", ROOT / "about.html"}
        listed = {local_path(location) for location, _ in self.entries_by_sitemap["sitemap.xml"]}
        self.assertEqual(expected, listed)


if __name__ == "__main__":
    unittest.main()
