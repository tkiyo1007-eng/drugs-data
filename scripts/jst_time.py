"""日次データ生成で使う日本時間の時計。

GitHub Actions の runner は UTC で動くため、深夜帯に実行が遅延すると
``date.today()`` が日本の暦日より1日前になる。公開データの日付は利用者と
厚労省データの基準に合わせ、すべて Asia/Tokyo で生成する。
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


JST = ZoneInfo("Asia/Tokyo")


def jst_now(value: dt.datetime | None = None) -> dt.datetime:
    """現在時刻、または指定時刻を日本時間の aware datetime で返す。"""
    if value is None:
        return dt.datetime.now(JST)
    if value.tzinfo is None:
        raise ValueError("タイムゾーンなしの日時は指定できません")
    return value.astimezone(JST)


def jst_today(value: dt.datetime | None = None) -> dt.date:
    """日本時間の暦日を返す。テストではUTC日時を注入できる。"""
    return jst_now(value).date()
