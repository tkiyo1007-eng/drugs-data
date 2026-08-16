import unittest

from generate_item_pages import page_html


class ItemPageMetadataTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
