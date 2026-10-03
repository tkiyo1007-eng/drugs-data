"""成分（一般名）別ページの検査。"""
import unittest
from pathlib import Path
from html.parser import HTMLParser

import generate_curated_pages as MOD

ROOT = Path(__file__).resolve().parents[1]


def row(name, generic, status="①通常出荷", yj="2171022F1000", cat="血管拡張剤"):
    return {"商品名": name, "一般名": generic, "供給状況": status, "YJコード": yj, "薬効分類": cat,
            "規格": "", "販売メーカー": "", "製造メーカー": "", "更新日": "2026/10/01"}


class IngredientPageTests(unittest.TestCase):
    def test_ingredient_download_links_use_the_official_app_without_search_data(self):
        rows = [row(f"テスト錠{i}", "成分<テスト>") for i in range(3)]
        groups = MOD.ingredient_groups(rows)
        page, _ = MOD.ingredient_page(next(iter(groups.values())), set(), {}, {})
        index = MOD.ingredient_index_page(groups, "2026-10-01")

        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stores = []
                self.banners = []

            def handle_starttag(self, tag, attrs):
                attr = dict(attrs)
                if tag == "a" and "apps.apple.com" in attr.get("href", ""):
                    self.stores.append(attr)
                if tag == "meta" and attr.get("name") == "apple-itunes-app":
                    self.banners.append(attr.get("content"))

        for output in (page, index):
            parsed = Links()
            parsed.feed(output)
            self.assertEqual(parsed.banners, ["app-id=6777696446"])
            self.assertEqual(len(parsed.stores), 1)
            self.assertEqual(parsed.stores[0]["href"], "https://apps.apple.com/jp/app/id6777696446")
            self.assertEqual(parsed.stores[0]["data-dsn-event"], "app-store-open")
        self.assertIn("通知の許可が必要", page)
        self.assertIn("代替薬の推薦ではなく", page)

    def test_only_substantial_ingredients_get_pages(self):
        rows = [row("A錠1", "成分A"), row("A錠2", "成分A"), row("A錠3", "成分A"),          # 3品目 → 掲載
                row("B錠1", "成分B", yj="1111111F1"), row("B錠2", "成分B", status="②限定出荷（自社の事情）", yj="1111111F2"),  # 2品目＋制限 → 掲載
                row("C錠1", "成分C", yj="2222222F1"), row("C錠2", "成分C", yj="2222222F2"),   # 2品目・制限なし → 非掲載
                row("D錠1", "成分D", status="③供給停止", yj="3333333F1")]                     # 1品目 → 非掲載
        names = {g["name"] for g in MOD.ingredient_groups(rows).values()}
        self.assertEqual(names, {"成分A", "成分B"})

    def test_slugs_are_stable_and_unique_for_shared_yj_prefix(self):
        rows = [row(f"X{i}", "成分X") for i in range(3)] + [row(f"Y{i}", "成分Y") for i in range(3)]
        groups = MOD.ingredient_groups(rows)
        self.assertEqual(len(groups), 2)
        self.assertIn("2171022", groups)
        self.assertTrue(all(slug.startswith("2171022") for slug in groups))
        reordered = MOD.ingredient_groups(list(reversed(rows)))
        self.assertEqual({slug: g["name"] for slug, g in groups.items()},
                         {slug: g["name"] for slug, g in reordered.items()})

    def test_brand_names_exclude_company_suffixed_generics(self):
        rows = [row("ノルバスク錠５ｍｇ", "アムロジピンベシル酸塩"), row("アムロジン錠５ｍｇ", "アムロジピンベシル酸塩"),
                row("アムロジピン錠５ｍｇ「サワイ」", "アムロジピンベシル酸塩")]
        self.assertEqual(MOD.ingredient_brand_names("アムロジピンベシル酸塩", rows), ["アムロジン", "ノルバスク"])

    def test_committed_pages_cover_amlodipine_and_link_from_category(self):
        page = (ROOT / "ingredients" / "2171022.html").read_text(encoding="utf-8")
        self.assertIn("<h1>アムロジピンベシル酸塩の供給状況</h1>", page)
        self.assertIn("代替薬の推薦ではなく", page)
        self.assertIn('href="https://kyokyu-navi.jp/ingredients/2171022.html"', page)
        category = (ROOT / "categories" / "217.html").read_text(encoding="utf-8")
        self.assertIn('href="../ingredients/2171022.html"', category)
        self.assertIn("ingredients/2171022.html", (ROOT / "sitemap-curated.xml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
