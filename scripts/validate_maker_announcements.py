#!/usr/bin/env python3
"""メーカー案内データの構造・参照整合性・最低件数を検査する。"""
import argparse
import csv
import json
import os
import sys


ALLOWED_EVENT_TYPES = {
    "discontinued", "package_discontinued", "resumed", "stopped",
    "limited", "supply", "other",
}
REQUIRED_FIELDS = ("maker", "title", "url")


def validate(csv_path, announcement_path, min_count=1):
    errors = []
    with open(csv_path, encoding="utf-8-sig") as f:
        product_names = {r.get("商品名", "") for r in csv.DictReader(f)}
    with open(announcement_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return ["案内データのルートがオブジェクトではありません"]
    if len(data) < min_count:
        errors.append(f"案内件数が少なすぎます: {len(data)}件（最低{min_count}件）")

    for name, info in data.items():
        if name not in product_names:
            errors.append(f"CSVに存在しない品目: {name}")
        if not isinstance(info, dict):
            errors.append(f"案内情報がオブジェクトではありません: {name}")
            continue
        for field in REQUIRED_FIELDS:
            if not str(info.get(field, "")).strip():
                errors.append(f"{field}が空です: {name}")
        url = str(info.get("url", ""))
        if url and not url.startswith("https://"):
            errors.append(f"公式URLがHTTPSではありません: {name} ({url})")
        event_type = info.get("event_type")
        if event_type is not None and event_type not in ALLOWED_EVENT_TYPES:
            errors.append(f"未知のevent_type: {name} ({event_type})")
    return errors


def validate_history(history_path):
    if not os.path.exists(history_path):
        return []
    with open(history_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        return ["案内履歴のルートがオブジェクトではありません"]
    errors = []
    for name, events in data.items():
        if not isinstance(events, list) or not events:
            errors.append(f"案内履歴が空または配列ではありません: {name}")
            continue
        seen = set()
        for event in events:
            key = (event.get("title"), event.get("url")) if isinstance(event, dict) else None
            if not isinstance(event, dict) or not all(event.get(k) for k in REQUIRED_FIELDS):
                errors.append(f"案内履歴の必須項目が不足: {name}")
                continue
            if key in seen:
                errors.append(f"案内履歴が重複: {name} ({event.get('url')})")
            seen.add(key)
            if not str(event.get("url", "")).startswith("https://"):
                errors.append(f"案内履歴URLがHTTPSではありません: {name}")
            if event.get("event_type") not in ALLOWED_EVENT_TYPES:
                errors.append(f"案内履歴のevent_typeが不正: {name} ({event.get('event_type')})")
    return errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="drugs_app_ready.csv")
    p.add_argument("--announcements", default="maker_announcements.json")
    p.add_argument("--events", default="maker_announcement_events.json")
    p.add_argument("--min-count", type=int, default=300)
    args = p.parse_args()
    errors = validate(args.csv, args.announcements, args.min_count)
    errors.extend(validate_history(args.events))
    if errors:
        for e in errors[:50]:
            print(f"ERROR: {e}", file=sys.stderr)
        if len(errors) > 50:
            print(f"...ほか{len(errors)-50}件", file=sys.stderr)
        raise SystemExit(1)
    with open(args.announcements, encoding="utf-8") as f:
        count = len(json.load(f))
    print(f"メーカー案内データ検証OK: {count}件")


if __name__ == "__main__":
    main()
