import unittest

from generate_item_pages import STATUS_NOTES, page_html


class ItemPageMetadataTests(unittest.TestCase):
    def test_sales_ended_note_requires_professional_current_information_check(self):
        note = STATUS_NOTES["ended"]
        self.assertIn("メーカー・卸の最新情報", note)
        self.assertIn("医師・薬剤師等の専門職", note)
        self.assertNotIn("代替薬への切り替え検討が必要", note)
        output = page_html({
            "商品名": "販売中止テスト錠",
            "製造メーカー": "テスト製薬",
            "供給状況": "販売中止",
            "更新日": "2026/08/20",
            "YJコード": "1234567F1234",
        }, "1234567F1234", "ended", "2026-08-20", [], {"1234567F1234"})
        self.assertIn(note, output)
        self.assertNotIn("代替薬への切り替え検討が必要", output)

    def test_item_page_has_one_canonical_and_large_preview_permission(self):
        row = {
            "商品名": "テスト錠10mg",
            "一般名": "テスト成分",
            "製造メーカー": "テスト製薬",
            "販売メーカー": "",
            "供給状況": "限定出荷",
            "規格": "10mg1錠",
            "更新日": "2026/08/16",
            "YJコード": "1234567F1234",
        }
        output = page_html(row, "1234567F1234", "limited", "2026-08-16", [], {"1234567F1234"})
        self.assertEqual(output.count('rel="canonical"'), 1)
        self.assertIn('content="index,follow,max-image-preview:large"', output)
        self.assertIn('href="https://tkiyo1007-eng.github.io/drugs-data/#item=1234567F1234"', output)
        self.assertIn('<script src="../analytics.js"></script>', output)
        self.assertIn('src="https://gc.zgo.at/count.js"', output)


if __name__ == "__main__":
    unittest.main()
