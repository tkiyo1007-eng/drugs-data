import datetime as dt
import unittest

from mhlw_supply_source import supply_source_from_page


class MhlwSupplySourceTests(unittest.TestCase):
    TODAY = dt.date(2026, 10, 14)
    URL = "https://www.mhlw.go.jp/content/10800000/001758803.xlsx"

    def page(self, label="医療用医薬品供給状況（令和８年10月13日現在）", href=None):
        return f'<a href="{href or self.URL}">{label}</a>'

    def test_numeric_name_uses_explicit_official_anchor_date(self):
        record = supply_source_from_page(self.page(), self.TODAY)
        self.assertEqual(record, {"file": "001758803.xlsx", "url": self.URL, "excel_date": "2026-10-13"})

    def test_relative_url_full_width_digits_nested_label_and_whitespace(self):
        page = self.page("医療用医薬品供給状況（<span>令和８年１０月１３日</span>現在）\n", "/content/10800000/001758803.xlsx")
        self.assertEqual(supply_source_from_page(page, self.TODAY)["url"], self.URL)
        self.assertEqual(supply_source_from_page(page, self.TODAY)["excel_date"], "2026-10-13")

    def test_gregorian_and_first_reiwa_year_are_explicit_supported_dates(self):
        for label, expected in [("医療用医薬品供給状況（2026年10月13日現在）", "2026-10-13"),
                                ("医療用医薬品供給状況（令和元年5月1日現在）", "2019-05-01")]:
            with self.subTest(label=label):
                self.assertEqual(supply_source_from_page(self.page(label), self.TODAY)["excel_date"], expected)

    def test_legacy_filename_remains_supported_without_date_in_label(self):
        page = self.page("供給状況", "/content/10800000/261008iyakuhinkyoukyu.xlsx")
        self.assertEqual(supply_source_from_page(page, self.TODAY)["excel_date"], "2026-10-08")

    def test_legacy_filename_and_explicit_label_must_agree(self):
        href = "/content/10800000/261013iyakuhinkyoukyu.xlsx"
        self.assertEqual(supply_source_from_page(self.page(href=href), self.TODAY)["excel_date"], "2026-10-13")
        with self.assertRaisesRegex(ValueError, "一致しません"):
            supply_source_from_page(self.page(href=href.replace("261013", "261008")), self.TODAY)

    def test_missing_date_is_not_inferred_from_numeric_name_or_today(self):
        with self.assertRaisesRegex(ValueError, "不明"):
            supply_source_from_page(self.page("医療用医薬品供給状況"), self.TODAY)

    def test_invalid_future_and_wrong_era_dates_are_rejected(self):
        for date in ["令和8年2月30日", "令和8年10月15日", "令和0年10月13日", "令和元年4月30日",
                     "2026年13月1日", "令和八年10月13日", "令和8年10月13日・14日"]:
            with self.subTest(date=date), self.assertRaises(ValueError):
                supply_source_from_page(self.page(f"医療用医薬品供給状況（{date}現在）"), self.TODAY)

    def test_legacy_invalid_or_future_filename_is_rejected(self):
        for name in ["260230iyakuhinkyoukyu.xlsx", "261015iyakuhinkyoukyu.xlsx"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                supply_source_from_page(self.page("供給状況", f"/content/10800000/{name}"), self.TODAY)

    def test_date_from_another_paragraph_or_unrelated_anchor_is_not_adopted(self):
        for page in ["<p>令和8年10月13日現在</p>" + self.page("医療用医薬品供給状況"),
                     self.page("別資料（令和8年10月13日現在）")]:
            with self.subTest(page=page), self.assertRaises(ValueError):
                supply_source_from_page(page, self.TODAY)

    def test_two_distinct_workbooks_are_ambiguous_even_if_both_have_dates(self):
        page = self.page() + self.page(href=self.URL.replace("001758803", "001758804"))
        with self.assertRaisesRegex(ValueError, "一意"):
            supply_source_from_page(page, self.TODAY)

    def test_identical_duplicate_link_is_allowed_but_conflicting_date_is_not(self):
        self.assertEqual(supply_source_from_page(self.page() * 2, self.TODAY)["excel_date"], "2026-10-13")
        with self.assertRaisesRegex(ValueError, "複数"):
            supply_source_from_page(self.page() + self.page("医療用医薬品供給状況（令和8年10月12日現在）"), self.TODAY)

    def test_non_official_hosts_schemes_credentials_queries_and_traversal_are_rejected(self):
        for href in [self.URL.replace("https:", "http:"), self.URL.replace("www.mhlw.go.jp", "example.com"),
                     self.URL.replace("www.mhlw.go.jp", "www.mhlw.go.jp.example.com"),
                     self.URL.replace("www.mhlw.go.jp", "user:secret@www.mhlw.go.jp"),
                     self.URL.replace("www.mhlw.go.jp", "www.mhlw.go.jp:invalid"),
                     self.URL.replace("/10800000/", "/10800000/../10800000/"),
                     self.URL.replace("/10800000/", "/10800000/%2e%2e/10800000/"),
                     self.URL.replace("/10800000/", "/10800000/%252e%252e/10800000/"),
                     self.URL + "?file=other", self.URL + "#other", "//example.com/content/10800000/001758803.xlsx",
                     self.URL.replace("/content/", "/other/"), self.URL.replace(".xlsx", ".xlsx/extra"),
                     self.URL.replace("001758803", "unidentified"), self.URL.replace("https://", "https:\\\\")]:
            with self.subTest(href=href), self.assertRaises(ValueError):
                supply_source_from_page(self.page(href=href), self.TODAY)

    def test_missing_incomplete_or_duplicate_href_is_rejected(self):
        for page in ["<p>一覧は未掲載</p>", self.page()[:-4],
                     f'<a href="{self.URL}" href="{self.URL}">医療用医薬品供給状況（令和8年10月13日現在）</a>']:
            with self.subTest(page=page), self.assertRaises(ValueError):
                supply_source_from_page(page, self.TODAY)


if __name__ == "__main__":
    unittest.main()
