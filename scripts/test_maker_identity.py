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

    def test_only_the_verified_directed_alias_matches(self):
        self.assertTrue(maker_is_listed_in_row("日本ジェネリック", {
            "製造メーカー": "長生堂製薬", "販売メーカー": "長生堂製薬",
        }))
        self.assertFalse(maker_is_listed_in_row("長生堂製薬", {
            "製造メーカー": "日本ジェネリック", "販売メーカー": "日本ジェネリック",
        }))

    def test_full_width_and_ascii_delimiters_are_tokenized(self):
        row = {
            "製造メーカー": "東和薬品／沢井製薬、ニプロ",
            "販売メーカー": "サンド；日医工 / 日本ケミファ",
        }
        for maker in ("東和薬品", "沢井製薬", "ニプロ", "サンド", "日医工", "日本ケミファ"):
            with self.subTest(maker=maker):
                self.assertTrue(maker_is_listed_in_row(maker, row))

    def test_substring_and_empty_maker_do_not_match(self):
        row = {"製造メーカー": "ニプロESファーマ", "販売メーカー": ""}
        self.assertFalse(maker_is_listed_in_row("ニプロ", row))
        self.assertFalse(maker_is_listed_in_row("", row))


if __name__ == "__main__":
    unittest.main()
