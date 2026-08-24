import unittest

from scripts.maker_identity import maker_is_listed_in_row


class MakerIdentityTests(unittest.TestCase):
    def test_exact_and_delimited_maker_names_match(self):
        self.assertTrue(maker_is_listed_in_row("沢井製薬", {
            "製造メーカー": "沢井製薬", "販売メーカー": "沢井製薬・メディサ新薬",
        }))
        self.assertTrue(maker_is_listed_in_row("日本ケミファ", {
            "製造メーカー": "東亜薬品", "販売メーカー": "日本ケミファ・沢井製薬",
        }))
        self.assertTrue(maker_is_listed_in_row("日本ジェネリック", {
            "製造メーカー": "長生堂製薬", "販売メーカー": "長生堂製薬",
        }))

    def test_substring_and_empty_maker_do_not_match(self):
        row = {"製造メーカー": "ニプロESファーマ", "販売メーカー": ""}
        self.assertFalse(maker_is_listed_in_row("ニプロ", row))
        self.assertFalse(maker_is_listed_in_row("", row))


if __name__ == "__main__":
    unittest.main()
