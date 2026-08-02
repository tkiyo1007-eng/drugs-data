import datetime as dt
import unittest

from jst_time import jst_now, jst_today


class JstTimeTests(unittest.TestCase):
    def test_utc_afternoon_is_next_calendar_day_in_japan(self):
        instant = dt.datetime(2026, 8, 2, 15, 16, tzinfo=dt.timezone.utc)
        self.assertEqual(jst_today(instant), dt.date(2026, 8, 3))
        self.assertEqual(jst_now(instant).isoformat(), "2026-08-03T00:16:00+09:00")

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            jst_now(dt.datetime(2026, 8, 3))


if __name__ == "__main__":
    unittest.main()
