import datetime as dt
import unittest

from jp_business_days import business_days_between, is_government_business_day, japanese_holidays


def dates(*values):
    return {dt.date.fromisoformat(value) for value in values}


class JapaneseHolidayTests(unittest.TestCase):
    def test_2026_holidays_match_cabinet_office_calendar(self):
        # 内閣府「国民の祝日について」2026年分（振替休日・国民の休日を含む）
        expected = dates(
            "2026-01-01", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20",
            "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06",
            "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22", "2026-09-23",
            "2026-10-12", "2026-11-03", "2026-11-23",
        )
        self.assertEqual(expected, set(japanese_holidays(2026)))

    def test_2025_substitute_holidays(self):
        expected = dates(
            "2025-01-01", "2025-01-13", "2025-02-11", "2025-02-23", "2025-02-24",
            "2025-03-20", "2025-04-29", "2025-05-03", "2025-05-04", "2025-05-05",
            "2025-05-06", "2025-07-21", "2025-08-11", "2025-09-15", "2025-09-23",
            "2025-10-13", "2025-11-03", "2025-11-23", "2025-11-24",
        )
        self.assertEqual(expected, set(japanese_holidays(2025)))

    def test_unsupported_year_is_not_silently_treated_as_business_days(self):
        with self.assertRaises(ValueError):
            japanese_holidays(2100)


class BusinessDayTests(unittest.TestCase):
    def test_2026_silver_week_counts_only_first_business_day(self):
        self.assertEqual(1, business_days_between(dt.date(2026, 9, 18), dt.date(2026, 9, 24)))

    def test_ordinary_week(self):
        self.assertEqual(3, business_days_between(dt.date(2026, 9, 7), dt.date(2026, 9, 10)))
        self.assertEqual(0, business_days_between(dt.date(2026, 9, 10), dt.date(2026, 9, 10)))
        self.assertEqual(0, business_days_between(dt.date(2026, 9, 10), dt.date(2026, 9, 9)))

    def test_year_end_closure(self):
        for day in ("2026-12-29", "2026-12-31", "2027-01-02", "2027-01-03"):
            self.assertFalse(is_government_business_day(dt.date.fromisoformat(day)))
        self.assertTrue(is_government_business_day(dt.date(2026, 12, 28)))
        self.assertEqual(1, business_days_between(dt.date(2026, 12, 28), dt.date(2027, 1, 4)))


if __name__ == "__main__":
    unittest.main()
