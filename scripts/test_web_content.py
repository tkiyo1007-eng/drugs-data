import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublishedWebContentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_current_copy_does_not_promise_same_class_alternatives(self):
        unsafe_claims = [
            "同じ薬効分類の同系統医薬品",
            "同成分・同分類の関連品目一覧",
            "同じ薬効分類の医薬品の一覧",
            "規格・薬価・代替候補など",
        ]
        for claim in unsafe_claims:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, self.html)

    def test_metadata_and_hero_match_the_safe_related_item_scope(self):
        self.assertIn("出荷調整・欠品・販売中止を毎日チェック", self.html)
        self.assertIn("同成分・同剤形の関連品目", self.html)
        self.assertIn("解除／解消見込み・出荷量状況", self.html)

    def test_mobile_search_compaction_is_published(self):
        self.assertIn("#demo{padding-top:28px}", self.html)
        self.assertIn(".pulse-sub,.supply-bar,.legend,.float-chip{display:none}", self.html)

    def test_missing_sales_maker_is_explained_without_guessing(self):
        self.assertIn("公開データに記載なし（製造メーカーを参照）", self.html)
        self.assertIn("if(salesMakerIndex >= 0 && !salesMaker && manufacturer)", self.html)


if __name__ == "__main__":
    unittest.main()
