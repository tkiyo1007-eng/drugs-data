import copy
import datetime as dt
import unittest

from mhlw_source_date import source_excel_date


class MhlwSourceDateTests(unittest.TestCase):
    def setUp(self):
        self.imported = dt.date(2026, 10, 14)
        self.source = {
            "file": "261008iyakuhinkyoukyu.xlsx",
            "url": "https://www.mhlw.go.jp/content/10800000/261008iyakuhinkyoukyu.xlsx",
            "excel_date": "2026-10-08",
        }

    def test_source_date_remains_october_eighth_after_fourteenth_import(self):
        self.assertEqual(source_excel_date(self.source, self.imported), "2026-10-08")

    def test_missing_date_is_not_inferred_from_filename_or_import(self):
        self.source.pop("excel_date")
        self.assertIsNone(source_excel_date(self.source, self.imported))

    def test_noncanonical_invalid_and_future_dates_are_unavailable(self):
        for value in [None, True, 20261008, "2026-10-8", "2026-02-30", "2026-10-15"]:
            with self.subTest(value=value):
                source = dict(self.source, excel_date=value)
                self.assertIsNone(source_excel_date(source, self.imported))

    def test_source_must_be_an_official_matching_workbook(self):
        for changes in [
            {"url": "http://www.mhlw.go.jp/content/10800000/261008iyakuhinkyoukyu.xlsx"},
            {"url": "https://example.com/content/10800000/261008iyakuhinkyoukyu.xlsx"},
            {"file": "other.xlsx"},
            {"url": "https://user:password@www.mhlw.go.jp/content/10800000/261008iyakuhinkyoukyu.xlsx"},
            {"url": "https://www.mhlw.go.jp:bad/content/10800000/261008iyakuhinkyoukyu.xlsx"},
        ]:
            with self.subTest(changes=changes):
                self.assertIsNone(source_excel_date(dict(self.source, **changes), self.imported))

    def test_same_day_and_prior_day_are_not_replaced_by_import(self):
        source = dict(self.source, excel_date="2026-10-14")
        self.assertEqual(source_excel_date(source, self.imported), "2026-10-14")
        self.assertIsNone(source_excel_date(self.source, dt.date(2026, 10, 7)))

    def test_input_is_not_mutated(self):
        original = copy.deepcopy(self.source)
        source_excel_date(self.source, self.imported)
        self.assertEqual(self.source, original)


if __name__ == "__main__":
    unittest.main()
