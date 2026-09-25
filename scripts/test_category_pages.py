import tempfile
import unittest
from pathlib import Path

from generate_curated_pages import (
    CATEGORY_MIN_ROWS,
    category_groups,
    category_index_page,
    category_page,
    dataset_month,
    load_rows,
    seasonal_codes,
)

ROOT = Path(__file__).resolve().parents[1]


def row(name, yj, status="①通常出荷", category="去たん剤", updated="2026/09/18"):
    return {"商品名": name, "YJコード": yj, "薬効分類": category, "供給状況": status,
            "規格": "1錠", "販売メーカー": "テスト製薬", "製造メーカー": "テスト製薬",
            "更新日": updated, "代替候補": "", "経過措置期限": ""}


class CategoryPageTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("通常錠A", "2233001F1011"),
            row("限定錠B", "2233001F1020", "②限定出荷（自社の事情）", updated="2026/09/10"),
            row("停止錠C", "2233001F1030", "⑤供給停止", updated="2026/09/01"),
            row("内部ID品D", "X12345", "③限定出荷（他社品の影響）"),
            row("少数分類E", "1149001F1010", category="解熱鎮痛消炎剤"),
        ]

    def test_groups_by_yj_prefix_and_maps_internal_ids_by_name(self):
        groups = category_groups(self.rows)
        self.assertEqual({"223"}, set(groups))
        self.assertEqual(4, len(groups["223"]["rows"]))
        self.assertNotIn("114", groups)  # CATEGORY_MIN_ROWS 未満は掲載しない
        self.assertEqual(3, CATEGORY_MIN_ROWS)

    def test_conflicting_category_codes_fail(self):
        with self.assertRaises(ValueError):
            category_groups(self.rows + [row("矛盾F", "2249001F1010")])

    def test_restricted_items_first_with_safety_note_and_no_recommendation(self):
        page, lastmod = category_page(category_groups(self.rows)["223"], set(), {})
        self.assertLess(page.index("停止錠C"), page.index("限定錠B"))
        self.assertLess(page.index("限定錠B"), page.index("通常出荷などの品目"))
        self.assertIn("代替薬の推薦ではなく", page)
        for forbidden in ("おすすめ", "代わりに", "在庫あり", "問題なし"):
            self.assertNotIn(forbidden, page)
        self.assertIn('href="https://tkiyo1007-eng.github.io/drugs-data/categories/223.html"', page)
        self.assertEqual("2026-09-25", lastmod)  # サイトマップ用はテンプレート改訂日を含む
        self.assertIn("品目行の最新更新日：2026-09-18", page)  # 表示はデータの日付だけ
        self.assertNotIn("品目行の最新更新日：2026-09-25", page)

    def test_empty_restriction_is_not_described_as_safe_supply(self):
        rows = [row(f"通常{i}", f"2233001F10{i}0") for i in range(3)]
        page, _ = category_page(category_groups(rows)["223"], set(), {})
        self.assertIn("限定出荷・供給停止と公表されている品目はありません（厚生労働省公表データの現在区分）", page)

    def test_index_orders_seasonal_first_and_is_deterministic(self):
        groups = category_groups(load_rows(ROOT / "drugs_app_ready.csv"))
        october = category_index_page(groups, "2026-10-01", 10)
        self.assertEqual(october, category_index_page(groups, "2026-10-01", 10))
        label, codes = seasonal_codes(10)
        self.assertIn(label, october)
        self.assertLess(october.index('href="223.html"'), october.index("すべての薬効分類"))
        self.assertEqual("花粉・夏季に確認が増える分類", seasonal_codes(5)[0])

    def test_season_comes_from_dataset_date_not_clock(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "version.json").write_text('{"note":"2026年10月01日厚労省データ反映"}', encoding="utf-8")
            self.assertEqual(10, dataset_month(Path(directory)))

    def test_item_pages_link_only_to_generated_category_pages(self):
        from generate_item_pages import category_pages
        rows = load_rows(ROOT / "drugs_app_ready.csv")
        self.assertEqual(set(category_groups(rows)), set(category_pages(rows).values()))
        self.assertEqual(category_groups(self.rows).keys(), set(category_pages(self.rows).values()))

    def test_committed_pages_match_committed_data(self):
        groups = category_groups(load_rows(ROOT / "drugs_app_ready.csv"))
        committed = {path.stem for path in (ROOT / "categories").glob("*.html")} - {"index"}
        self.assertEqual(set(groups), committed)


if __name__ == "__main__":
    unittest.main()
