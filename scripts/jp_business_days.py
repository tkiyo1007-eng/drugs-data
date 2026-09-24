#!/usr/bin/env python3
"""厚労省の行更新日の鮮度判定に使う、日本の行政機関の営業日計算（標準ライブラリのみ）。

厚労省の供給状況は行政機関の開庁日にしか更新されない。暦日で判定すると、
土日・祝日の連休（例: 2026年9月19〜23日）だけで「古すぎる」と誤判定する。

対応範囲: 現行の「国民の祝日に関する法律」の規則（振替休日・国民の休日を含む）と
年末年始の閉庁日（12月29日〜1月3日）。春分・秋分は1980〜2099年の近似式で求める。
臨時の祝日や将来の法改正は含まないため、該当時は SUPPORTED_YEARS と併せて見直す。
"""

from __future__ import annotations

import datetime as dt
from functools import lru_cache

SUPPORTED_YEARS = range(2022, 2100)


def _nth_monday(year: int, month: int, nth: int) -> dt.date:
    first = dt.date(year, month, 1)
    return first + dt.timedelta(days=(7 - first.weekday()) % 7 + 7 * (nth - 1))


def _equinox_day(year: int, base: float) -> int:
    offset = year - 1980
    return int(base + 0.242194 * offset - offset // 4)


@lru_cache(maxsize=None)
def japanese_holidays(year: int) -> frozenset[dt.date]:
    """その年の国民の祝日・振替休日・国民の休日。対応範囲外の年はValueError。"""
    if year not in SUPPORTED_YEARS:
        raise ValueError(f"{year}年の祝日は未対応です（対応: {SUPPORTED_YEARS.start}〜{SUPPORTED_YEARS.stop - 1}年）")
    base = {
        dt.date(year, 1, 1),                       # 元日
        _nth_monday(year, 1, 2),                   # 成人の日
        dt.date(year, 2, 11),                      # 建国記念の日
        dt.date(year, 2, 23),                      # 天皇誕生日
        dt.date(year, 3, _equinox_day(year, 20.8431)),  # 春分の日
        dt.date(year, 4, 29),                      # 昭和の日
        dt.date(year, 5, 3),                       # 憲法記念日
        dt.date(year, 5, 4),                       # みどりの日
        dt.date(year, 5, 5),                       # こどもの日
        _nth_monday(year, 7, 3),                   # 海の日
        dt.date(year, 8, 11),                      # 山の日
        _nth_monday(year, 9, 3),                   # 敬老の日
        dt.date(year, 9, _equinox_day(year, 23.2488)),  # 秋分の日
        _nth_monday(year, 10, 2),                  # スポーツの日
        dt.date(year, 11, 3),                      # 文化の日
        dt.date(year, 11, 23),                     # 勤労感謝の日
    }
    holidays = set(base)
    # 振替休日: 祝日が日曜なら、その後の最初の祝日でない日。
    for day in sorted(base):
        if day.weekday() == 6:
            substitute = day + dt.timedelta(days=1)
            while substitute in holidays:
                substitute += dt.timedelta(days=1)
            holidays.add(substitute)
    # 国民の休日: 前日と翌日が祝日である祝日でない日（2026年9月22日など）。
    for day in sorted(base):
        between = day + dt.timedelta(days=1)
        if between not in holidays and between + dt.timedelta(days=1) in base:
            holidays.add(between)
    return frozenset(holidays)


def is_government_business_day(day: dt.date) -> bool:
    if day.weekday() >= 5:
        return False
    if (day.month, day.day) >= (12, 29) or (day.month, day.day) <= (1, 3):
        return False
    return day not in japanese_holidays(day.year)


def business_days_between(start: dt.date, end: dt.date) -> int:
    """start の翌日から end まで（両端のうち end を含む）の営業日数。end <= start なら0。"""
    count = 0
    day = start + dt.timedelta(days=1)
    while day <= end:
        if is_government_business_day(day):
            count += 1
        day += dt.timedelta(days=1)
    return count
