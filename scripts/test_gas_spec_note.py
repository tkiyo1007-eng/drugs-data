import unittest
from generate_item_pages import page_html


class GasSpecNoteTest(unittest.TestCase):
    def test_note_is_limited_to_the_gas_ingredients(self):
        phrase = "表示の規格は容器の容量や充填量を示すとは限りません。"
        for ingredient in ("酸素", "液体酸素", "窒素", "液体窒素", "二酸化炭素", "アセトアミノフェン"):
            row = {"商品名": "対象品目", "一般名": ingredient, "規格": "１Ｌ",
                   "供給状況": "①通常出荷", "YJコード": "799070EX1020"}
            html = page_html(row, row["YJコード"], "ok", "2026-11-10", [], set())
            self.assertEqual(phrase in html, ingredient != "アセトアミノフェン")
            self.assertIn("１Ｌ", html)
            self.assertFalse(any(line.rstrip() != line for line in html.splitlines()))
