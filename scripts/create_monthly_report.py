#!/usr/bin/env python3
"""前月の「医薬品供給レポート」の数値を reports/YYYY-MM.json に1回だけ固定する。

引用されても数値が後から変わらないよう、月が明けて最初の日次更新で作成し、
以後は上書きしない（HTMLは generate_curated_pages.py がこのJSONから描画する）。

- 月内の区分変更は status_changes.json（直近90日保持）から集計する。保持期間が
  対象月の初日を覆っていない場合は、欠けた集計を作らず作成しない。
- 公表区分の件数・供給危機指数・解除までの日数は、作成時点（version.jsonの
  データ日付）の値として日付付きで記録する。月末時点の値とは表記しない。
- 対象はデータ日付の前月だけ。過去月へ遡って現在値を当てはめない。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

REPORT_START = "2026-09"  # これより前の月は作成しない（遡及しない）
KEEP_DAYS = 90            # build_status_changes.py の保持日数と同じ


def status_group(value: str) -> str | None:
    if "通常出荷" in value:
        return "ok"
    if "供給停止" in value:
        return "stopped"
    if "限定出荷" in value:
        return "limited"
    return None


def data_date(site: Path) -> dt.date:
    note = json.loads((site / "version.json").read_text(encoding="utf-8")).get("note", "")
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(note))
    if not match:
        raise ValueError("version.jsonからデータ日付を取得できません")
    return dt.date(*(int(part) for part in match.groups()))


def previous_month(day: dt.date) -> str:
    first = day.replace(day=1)
    return (first - dt.timedelta(days=1)).strftime("%Y-%m")


def month_bounds(month: str) -> tuple[dt.date, dt.date]:
    start = dt.date.fromisoformat(month + "-01")
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    return start, end


def transition_counts(entries: list[dict]) -> Counter:
    counts: Counter = Counter()
    for entry in entries:
        before, after = status_group(str(entry.get("from", ""))), status_group(str(entry.get("to", "")))
        if before is None or after is None:
            raise ValueError(f"未対応の供給区分を含みます: {entry.get('yj')}")
        if after == "limited" and before != "limited":
            counts["limited"] += 1
        elif after == "stopped" and before != "stopped":
            counts["stopped"] += 1
        elif after == "ok":
            counts["ok"] += 1
        else:
            counts["other"] += 1
    return counts


def changes_in(changes: list[dict], month: str) -> list[dict]:
    prefix = month.replace("-", "/") + "/"
    return [entry for entry in changes if str(entry.get("date", "")).startswith(prefix)]


def build_report(site: Path, csv_path: Path, month: str, snapshot: dt.date) -> dict | None:
    start, _ = month_bounds(month)
    if snapshot - dt.timedelta(days=KEEP_DAYS) > start:
        return None  # 変更履歴の保持期間が対象月を覆っていない
    changes = json.loads((site / "status_changes.json").read_text(encoding="utf-8"))
    if not isinstance(changes, list):
        raise ValueError("status_changes.json が配列ではありません")
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if (row.get("商品名") or "").strip()]
    category_by_yj = {row.get("YJコード"): (row.get("薬効分類") or "").strip() for row in rows}
    code_by_category = {}
    for row in rows:
        code = (row.get("YJコード") or "")[:3]
        if code.isdigit():
            code_by_category.setdefault((row.get("薬効分類") or "").strip(), code)

    entries = changes_in(changes, month)
    counts = transition_counts(entries)
    new_restrictions = Counter()
    for entry in entries:
        after, before = status_group(entry["to"]), status_group(entry["from"])
        if after in ("limited", "stopped") and before == "ok":
            new_restrictions[category_by_yj.get(entry.get("yj"), "") or "分類不明（現行CSVに該当なし）"] += 1
    prev = previous_month(start)
    prev_start, _ = month_bounds(prev)
    prev_counts = (transition_counts(changes_in(changes, prev))
                   if snapshot - dt.timedelta(days=KEEP_DAYS) <= prev_start else None)

    status_counts = Counter(status_group(row.get("供給状況", "")) or "unknown" for row in rows)
    crisis = json.loads((site / "crisis_index.json").read_text(encoding="utf-8"))
    resolution = json.loads((site / "resolution_stats.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "month": month,
        "snapshot_date": snapshot.isoformat(),
        "changes": {
            "items": len(entries),
            "days_with_changes": len({entry["date"] for entry in entries}),
            "to_limited": counts["limited"], "to_stopped": counts["stopped"],
            "to_ok": counts["ok"], "other": counts["other"],
        },
        "previous_month": ({"month": prev, "items": sum(prev_counts.values()),
                            "to_limited": prev_counts["limited"], "to_stopped": prev_counts["stopped"],
                            "to_ok": prev_counts["ok"], "other": prev_counts["other"]}
                           if prev_counts is not None else None),
        "top_new_restriction_categories": [
            {"name": name, "code": code_by_category.get(name, ""), "count": count}
            for name, count in sorted(new_restrictions.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        "snapshot_status": {"total": len(rows), "ok": status_counts["ok"],
                            "limited": status_counts["limited"], "stopped": status_counts["stopped"]},
        "crisis_index": {"date": str(crisis.get("date", "")).replace("/", "-"),
                         "score": crisis.get("score"), "level": crisis.get("level")},
        "resolution": {"updated_at": str(resolution.get("updatedAt", "")).replace("/", "-"),
                       "limited": resolution.get("limited"), "stopped": resolution.get("stopped")},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, default=Path("."))
    parser.add_argument("--csv", type=Path, default=Path("drugs_app_ready.csv"))
    args = parser.parse_args(argv)
    snapshot = data_date(args.site)
    month = previous_month(snapshot)
    path = args.site / "reports" / f"{month}.json"
    if month < REPORT_START:
        print(f"{month}: レポート対象期間より前のため作成しません")
        return 0
    if path.exists():
        print(f"{month}: 作成済みのため変更しません")
        return 0
    report = build_report(args.site, args.csv, month, snapshot)
    if report is None:
        print(f"{month}: 変更履歴の保持期間が対象月を覆っていないため作成しません")
        return 0
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ {month} のレポート数値を固定しました（{snapshot.isoformat()}時点）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
