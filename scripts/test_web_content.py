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
        # LP文言はprivate側の正本から同期されるため、公開側の日次処理を特定の
        # キャッチコピーへ固定しない。供給区分と安全な関連品目範囲を契約にする。
        self.assertIn("限定出荷", self.html)
        self.assertIn("供給停止", self.html)
        self.assertIn("販売中止", self.html)
        self.assertIn("同成分・同剤形の関連品目", self.html)
        self.assertIn("解除／解消見込み・出荷量状況", self.html)

    def test_official_system_copy_is_safe_after_private_lp_sync(self):
        if "公式情報との使い分け" not in self.html:
            self.skipTest("private側の新しいLPはまだ同期前")
        self.assertIn("限定出荷・供給停止・販売中止を毎日確認", self.html)
        self.assertIn("医薬品供給ナビ（非公式）", self.html)
        self.assertNotIn("供給危機指数", self.html)
        self.assertNotIn("元データとの違い", self.html)
        self.assertNotIn("Excelファイルのため実用的ではない", self.html)

    def test_mobile_search_compaction_is_published(self):
        self.assertIn("#demo{padding-top:28px}", self.html)
        self.assertIn(".pulse-sub,.supply-bar,.legend,.float-chip{display:none}", self.html)

    def test_dosage_search_uses_the_same_numeric_boundary_as_ios(self):
        self.assertIn("const DOSAGE_SEARCH_UNITS = [", self.html)
        self.assertIn("function isDosageSearchTerm(term){", self.html)
        self.assertIn("Number.isNaN(Number(numeric[0]))", self.html)
        self.assertIn(
            "function searchIndexMatchesTerm(searchIndex, term, dosage = isDosageSearchTerm(term)){",
            self.html,
        )
        self.assertIn('Array.from(searchIndex.slice(0, index)).pop() || ""', self.html)
        self.assertIn('if(!previous || !/[\\p{Number}.,]/u.test(previous)) return true;', self.html)
        self.assertIn("dosage:isDosageSearchTerm(t)", self.html)
        self.assertIn("searchIndexMatchesTerm(d.q, x.t, x.dosage)", self.html)
        self.assertNotIn("terms.every(x => d.q.includes(x.t)", self.html)

    def test_search_index_keeps_both_manufacturer_fields_like_ios(self):
        self.assertIn('const manufacturer = iMk1>=0 ? (r[iMk1]||"").trim() : "";', self.html)
        self.assertIn('const salesMaker = iMk2>=0 ? (r[iMk2]||"").trim() : "";', self.html)
        self.assertIn('q:norm([name,salesMaker,manufacturer,genericName].join(" "))', self.html)
        self.assertNotIn('q:norm(r[iName]+(r[iGen]||"")+maker)', self.html)

    def test_change_history_must_match_the_current_status_like_ios(self):
        self.assertIn("function statusChangeMatchesCurrentItem(item, change){", self.html)
        self.assertIn('mapStatus(String(change.to ?? "")) === item.s', self.html)
        self.assertIn("statusChangeMatchesCurrentItem(item, change) ? change : null", self.html)

    def test_lifecycle_maker_matching_rejects_empty_and_uses_verified_alias(self):
        self.assertIn("function lifecycleMakerMatches(maker, makerText){", self.html)
        self.assertIn("if(!makerName) return false;", self.html)
        self.assertIn("if(!lifecycleMakerMatches(item.maker, makerText)) return null;", self.html)
        self.assertNotIn("if(item.maker && !lifecycleMakerMatches", self.html)
        self.assertIn('"日本ジェネリック": ["長生堂製薬"]', self.html)
        self.assertNotIn("norm(makerText).includes(norm(item.maker))", self.html)

    def test_missing_sales_maker_is_explained_without_guessing(self):
        self.assertIn("公開データに記載なし（製造メーカーを参照）", self.html)
        self.assertIn("if(salesMakerIndex >= 0 && !salesMaker && manufacturer)", self.html)

    def test_detail_share_prefers_only_confirmed_formal_item_pages(self):
        self.assertIn(
            'const PUBLIC_SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/";',
            self.html,
        )
        self.assertIn("const FORMAL_ITEM_YJ = /^[0-9][0-9A-Z]{11}$/;", self.html)
        self.assertIn("FORMAL_ITEM_YJ.test(yj) && ITEM_PAGES.has(yj)", self.html)
        self.assertIn(
            'new URL(`items/${encodeURIComponent(yj)}.html`, PUBLIC_SITE_ROOT)',
            self.html,
        )
        self.assertIn('url.hash = "item=" + encodeURIComponent(itemKey(item));', self.html)
        self.assertIn("const url = detailShareURL(currentItem).href;", self.html)
        share_handler = self.html.split(
            'document.getElementById("mShare").addEventListener', 1
        )[1].split("});", 1)[0]
        before_native_share = share_handler.split("await navigator.share", 1)[0]
        self.assertNotIn("await ", before_native_share)
        self.assertNotIn("loadItemPages", share_handler)
        self.assertNotIn("fetch(", share_handler)


if __name__ == "__main__":
    unittest.main()
