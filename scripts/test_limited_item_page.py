import tempfile
import unittest
from pathlib import Path
from generate_item_pages import item_key, map_status, page_html, should_generate, strict_status
from limited_item_page import PILOT_KEYS, prepare_assets, write_pilot_links


class LimitedItemPageTests(unittest.TestCase):
    def test_new_limitation_and_recovery_keep_the_item_url_and_switch_layout(self):
        row = {"YJコード": "1234567F9876", "商品名": "テスト薬０．０５％", "規格": "１ｇ"}
        key = item_key(row)
        existing = set()
        for raw in ("①通常出荷", "②限定出荷（自社の事情）", "③限定出荷（他社品の影響）",
                    "④限定出荷（その他）", "①通常出荷", "⑤供給停止", "③限定出荷（他社品の影響）"):
            row["供給状況"] = raw
            if not should_generate(row, key, existing, {}, {}):
                self.assertFalse(existing)
                continue
            existing.add(key)
            page = page_html(row, key, map_status(raw), "", [], existing)
            active = strict_status(raw) == "limited"
            self.assertEqual('class="summary"' in page, active)
            self.assertIn(f'rel="canonical" href="https://kyokyu-navi.jp/items/{key}.html"', page)
            self.assertIn('id="watchButton"', page)
            if active:
                self.assertIn(f'<strong class="status limited">{raw}</strong>', page)
                self.assertIn('<time>確認できません</time>', page)
                self.assertNotIn('href="#trialAlternatives"', page)
                self.assertNotIn('href="#compare"', page)

    def test_pilot_urls_follow_canonical_items_and_retired_products_are_removed(self):
        with tempfile.TemporaryDirectory() as name:
            site = Path(name)
            folder = site / "items" / "trial"
            prepare_assets(site)
            retired = folder / (PILOT_KEYS[1] + ".html")
            retired.touch()
            write_pilot_links(folder, [{"key": PILOT_KEYS[0], "display_name": "テスト錠"}])
            index = (folder / "index.html").read_text()
            self.assertFalse(retired.exists())
            self.assertNotIn(PILOT_KEYS[1], index)
            self.assertIn('noindex,follow', index)
            redirect = (folder / (PILOT_KEYS[0] + ".html")).read_text()
            self.assertIn(f'content="0;url=../{PILOT_KEYS[0]}.html"', redirect)
            self.assertTrue((folder / "trial.js").is_file())
            self.assertTrue((site / "items" / "limited-detail.css").is_file())
