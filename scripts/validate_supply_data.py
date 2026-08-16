#!/usr/bin/env python3
"""医薬品供給CSVを公開前に検査する。"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from jst_time import jst_today


REQUIRED_COLUMNS = (
    "商品名", "一般名", "製造メーカー", "販売メーカー", "供給状況", "理由",
    "代替候補", "更新日", "今回更新", "YJコード", "薬効分類", "規格", "薬価",
    "経過措置期限", "ステータス更新日",
)
NON_EMPTY_COLUMNS = ("商品名", "一般名", "製造メーカー", "供給状況", "更新日", "YJコード", "薬効分類")
ALLOWED_STATUSES = {
    "①通常出荷",
    "②限定出荷（自社の事情）",
    "③限定出荷（他社品の影響）",
    "④限定出荷（その他）",
    "⑤供給停止",
}
YJ_PATTERN = re.compile(r"(?:[0-9A-Z]{12}|X[0-9]{5})\Z")
MAKER_NOISE_MARKER = "本注意事項等情報を使用している製造販売業者一覧表"


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y/%m/%d").date()
    except ValueError:
        return None


def validate_csv(path, *, today=None, min_rows=10000, max_rows=30000, max_age_days=10,
                 max_missing_sales_maker_rate=None, max_missing_price_rate=None,
                 reject_maker_noise=True):
    errors = []
    today = today or jst_today()
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            if len(headers) != len(set(headers)):
                duplicates = sorted(name for name, count in Counter(headers).items() if count > 1)
                errors.append("CSVヘッダーが重複しています: " + ", ".join(duplicates))
            missing = [name for name in REQUIRED_COLUMNS if name not in headers]
            if missing:
                errors.append("必須列がありません: " + ", ".join(missing))
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error) as exc:
        return [f"CSVを読み込めません: {exc}"], {"rows": 0}

    if not min_rows <= len(rows) <= max_rows:
        errors.append(f"品目数が許容範囲外です: {len(rows):,}件（{min_rows:,}〜{max_rows:,}件を想定）")

    for column in NON_EMPTY_COLUMNS:
        if column not in headers:
            continue
        empty = [index + 2 for index, row in enumerate(rows) if not (row.get(column) or "").strip()]
        if empty:
            errors.append(f"{column}が空の行が{len(empty):,}件あります: "
                          + ", ".join(map(str, empty[:5])) + ("…" if len(empty) > 5 else ""))

    statuses = Counter((row.get("供給状況") or "").strip() for row in rows)
    unknown = sorted(status for status in statuses if status and status not in ALLOWED_STATUSES)
    if unknown:
        errors.append("未対応の供給状況があります: "
                      + ", ".join(f"{status} ({statuses[status]:,}件)" for status in unknown))

    yj_values = []
    bad_yj = []
    for index, row in enumerate(rows, start=2):
        value = (row.get("YJコード") or "").strip()
        if value:
            yj_values.append(value)
            if not YJ_PATTERN.fullmatch(value):
                bad_yj.append((index, value))
    if bad_yj:
        errors.append(f"YJコード形式が不正な行が{len(bad_yj):,}件あります: "
                      + ", ".join(f"{line}行目={value}" for line, value in bad_yj[:5]))
    duplicate_yj = [(value, count) for value, count in Counter(yj_values).items() if count > 1]
    if duplicate_yj:
        errors.append("YJコードが重複しています: "
                      + ", ".join(f"{value} ({count}件)" for value, count in duplicate_yj[:5]))

    if reject_maker_noise:
        maker_noise = []
        for index, row in enumerate(rows, start=2):
            for column in ("製造メーカー", "販売メーカー"):
                value = (row.get(column) or "").strip()
                if MAKER_NOISE_MARKER in value:
                    maker_noise.append((index, column))
        if maker_noise:
            errors.append(
                f"メーカー欄に外部文書の説明文が混入した行が{len(maker_noise):,}件あります: "
                + ", ".join(f"{line}行目 {column}" for line, column in maker_noise[:5]))

    invalid_prices = []
    for index, row in enumerate(rows, start=2):
        value = (row.get("薬価") or "").strip()
        if not value:
            continue
        try:
            if Decimal(value) <= 0:
                invalid_prices.append((index, value))
        except InvalidOperation:
            invalid_prices.append((index, value))
    if invalid_prices:
        errors.append(
            f"薬価が正の数値ではない行が{len(invalid_prices):,}件あります: "
            + ", ".join(f"{line}行目={value!r}" for line, value in invalid_prices[:5]))

    newest_dates = []
    future_limit = today + timedelta(days=1)
    for column in ("更新日", "ステータス更新日"):
        invalid, future = [], []
        for index, row in enumerate(rows, start=2):
            value = (row.get(column) or "").strip()
            if not value:
                continue
            parsed = parse_date(value)
            if parsed is None:
                invalid.append((index, value))
            else:
                if column == "更新日":
                    newest_dates.append(parsed)
                if parsed > future_limit:
                    future.append((index, value))
        if invalid:
            errors.append(f"{column}の日付形式が不正な行が{len(invalid):,}件あります: "
                          + ", ".join(f"{line}行目={value!r}" for line, value in invalid[:5]))
        if future:
            errors.append(f"{column}が未来日の行が{len(future):,}件あります: "
                          + ", ".join(f"{line}行目={value}" for line, value in future[:5]))

    newest = max(newest_dates) if newest_dates else None
    if newest is None:
        errors.append("有効な更新日が1件もありません")
    elif newest < today - timedelta(days=max_age_days):
        errors.append(f"データが古すぎます: 最新更新日 {newest.isoformat()} "
                      f"（基準日 {today.isoformat()}、許容 {max_age_days}日以内）")

    missing_sales_maker = sum(not (row.get("販売メーカー") or "").strip() for row in rows)
    missing_sales_maker_rate = (missing_sales_maker / len(rows) * 100) if rows else 0.0
    if (max_missing_sales_maker_rate is not None
            and missing_sales_maker_rate > max_missing_sales_maker_rate):
        errors.append(
            f"販売メーカーの記載なし率が上限を超えています: "
            f"{missing_sales_maker:,}/{len(rows):,}件（{missing_sales_maker_rate:.2f}%、"
            f"上限 {max_missing_sales_maker_rate:.2f}%）")
    missing_price = sum(not (row.get("薬価") or "").strip() for row in rows)
    missing_price_rate = (missing_price / len(rows) * 100) if rows else 0.0
    if max_missing_price_rate is not None and missing_price_rate > max_missing_price_rate:
        errors.append(
            f"薬価の記載なし率が上限を超えています: "
            f"{missing_price:,}/{len(rows):,}件（{missing_price_rate:.2f}%、"
            f"上限 {max_missing_price_rate:.2f}%）")

    summary = {
        "rows": len(rows),
        "newest": newest.isoformat() if newest else None,
        "statuses": dict(sorted(statuses.items())),
        "missing_sales_maker": missing_sales_maker,
        "missing_sales_maker_rate": missing_sales_maker_rate,
        "missing_price": missing_price,
        "missing_price_rate": missing_price_rate,
    }
    return errors, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=Path("drugs_app_ready.csv"))
    parser.add_argument("--min-rows", type=int, default=10000)
    parser.add_argument("--max-rows", type=int, default=30000)
    parser.add_argument("--max-age-days", type=int, default=10)
    parser.add_argument("--max-missing-sales-maker-rate", type=float, default=3.4,
                        help="販売メーカー欄の記載なし率の上限（既定3.4%%）")
    parser.add_argument("--max-missing-price-rate", type=float, default=6.0,
                        help="薬価欄の記載なし率の上限（既定6.0%%）")
    args = parser.parse_args(argv)
    errors, summary = validate_csv(
        args.csv, min_rows=args.min_rows, max_rows=args.max_rows, max_age_days=args.max_age_days,
        max_missing_sales_maker_rate=args.max_missing_sales_maker_rate,
        max_missing_price_rate=args.max_missing_price_rate)
    print(f"品目数: {summary.get('rows', 0):,}件")
    if summary.get("newest"):
        print(f"最新更新日: {summary['newest']}")
    if summary.get("statuses"):
        print("供給状況: " + ", ".join(
            f"{name}={count:,}" for name, count in summary["statuses"].items()))
    if "missing_sales_maker" in summary:
        print(f"参考: 販売メーカー記載なし={summary['missing_sales_maker']:,}件"
              f"（{summary['missing_sales_maker_rate']:.2f}%）、"
              f"薬価記載なし={summary['missing_price']:,}件"
              f"（{summary['missing_price_rate']:.2f}%）")
    if errors:
        for error in errors:
            print(f"::error::{error}")
        print(f"供給CSV品質検査: {len(errors)}件のエラー", file=sys.stderr)
        return 1
    print("供給CSV品質検査: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
