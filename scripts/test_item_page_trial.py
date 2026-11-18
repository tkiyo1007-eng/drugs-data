import tempfile
import unittest
from pathlib import Path

from item_page_trial import TRIAL_KEYS, write_index, write_page


class ItemPageTrialTests(unittest.TestCase):
    def test_index_removes_retired_product_and_keeps_only_trial_links(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            retired = folder / (TRIAL_KEYS[1] + ".html")
            retired.touch()
            write_index(folder, [{"key": TRIAL_KEYS[0], "name": "テスト製品", "maker": "製薬", "spec": "１錠"}])
            index = (folder / "index.html").read_text(encoding="utf-8")
            self.assertFalse(retired.exists())
            self.assertNotIn(TRIAL_KEYS[1], index)
            self.assertIn(f'href="../{TRIAL_KEYS[0]}.html"', index)
            self.assertIn('noindex,follow', index)
            self.assertTrue((folder / "trial.css").is_file())
            self.assertTrue((folder / "trial.js").is_file())

    def test_no_source_metadata_never_invents_date_or_alternative_jump(self):
        item = dict(key=TRIAL_KEYS[0], display_name="テスト薬０．０５％", supply_raw="", updated="",
                    reason="", release="", manufacturer_notices=[], spec="１ｇ", maker="Ａ＆Ｂ",
                    status="", delist=False)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_page(folder, item, "", "", "", "", [], [])
            page = (folder / (TRIAL_KEYS[0] + ".html")).read_text(encoding="utf-8")
            self.assertIn('data-source=""', page)
            self.assertIn('<time>確認できません</time>', page)
            self.assertIn('<span class="strength">０．０５％</span>', page)
            self.assertNotIn('href="#trialAlternatives"', page)
            self.assertNotIn('href="#compare"', page)
