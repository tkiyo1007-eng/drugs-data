#!/usr/bin/env python3
"""Web・iOSが利用する公開データ一式を取得し、鮮度と整合性を検証する。"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from validate_supply_data import validate_csv as validate_drug_csv
from validate_product_lifecycle import load_csv, validate as validate_lifecycle


BASE_URL = "https://raw.githubusercontent.com/tkiyo1007-eng/drugs-data/main/"
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_CSV_BYTES = 30 * 1024 * 1024
SUPPORTING_FILES: dict[str, type] = {
    "maker_announcements.json": dict,
    "announcement_packages.json": dict,
    "announcement_summaries.json": dict,
    "news.json": list,
    "status_changes.json": list,
    "resolution_stats.json": dict,
    "maker_links.json": list,
    "manual_announcements.json": dict,
    "product_lifecycle.json": dict,
    "featured_products.json": dict,
    "industry_topics.json": dict,
    "crisis_index.json": dict,
}
NOTE_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def parse_note_date(note: object) -> dt.date | None:
    if not isinstance(note, str):
        return None
    match = NOTE_DATE_RE.search(note)
    if not match:
        return None
    try:
        return dt.date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def validate_version(document: object, today: dt.date, max_age_days: int) -> list[str]:
    if not isinstance(document, dict):
        return ["version.json: ルートがオブジェクトではありません"]
    errors: list[str] = []
    version = document.get("version")
    if not isinstance(version, int) or version <= 0:
        errors.append("version.json: version は正の整数である必要があります")
    csv_url = document.get("csv_url")
    parsed_url = urllib.parse.urlparse(csv_url if isinstance(csv_url, str) else "")
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        errors.append("version.json: csv_url はHTTPS URLである必要があります")
    snapshot_date = parse_note_date(document.get("note"))
    if snapshot_date is None:
        errors.append("version.json: noteからデータ日付を取得できません")
    else:
        age = max(0, (today - snapshot_date).days)
        if age > max(0, max_age_days):
            errors.append(
                f"version.json: データが{age}日前で、許容{max_age_days}日を超えています"
            )
        if isinstance(version, int) and not str(version).startswith(snapshot_date.strftime("%Y%m%d")):
            errors.append("version.json: versionの日付とnoteの日付が一致しません")
    return errors


def validate_supporting_document(name: str, document: object) -> list[str]:
    expected_type = SUPPORTING_FILES[name]
    if not isinstance(document, expected_type):
        return [f"{name}: ルートは{expected_type.__name__}である必要があります"]
    errors: list[str] = []
    if name in {"product_lifecycle.json", "featured_products.json", "industry_topics.json"}:
        if document.get("schema_version") != 1:  # type: ignore[union-attr]
            errors.append(f"{name}: schema_version は1である必要があります")
    required_keys = {
        "featured_products.json": ("updated_at", "products"),
        "industry_topics.json": ("updated_at", "topics"),
        "crisis_index.json": ("date", "score", "level", "limited", "stopped", "total"),
        "resolution_stats.json": ("updatedAt", "limited", "stopped"),
    }.get(name, ())
    if isinstance(document, dict):
        for key in required_keys:
            if key not in document:
                errors.append(f"{name}: {key} がありません")
    if name == "status_changes.json" and isinstance(document, list):
        for index, item in enumerate(document):
            if not isinstance(item, dict) or not all(item.get(key) for key in ("date", "yj", "name", "from", "to")):
                errors.append(f"{name}: {index + 1}件目に必須項目がありません")
                if len(errors) >= 20:
                    break
    return errors


def fetch(url: str, maximum_bytes: int) -> bytes:
    separator = "&" if "?" in url else "?"
    request = urllib.request.Request(
        f"{url}{separator}health_check={time.time_ns()}",
        headers={"User-Agent": "DrugSupplyNavi-public-data-health/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        data = response.read(maximum_bytes + 1)
    if not data:
        raise RuntimeError("応答が空です")
    if len(data) > maximum_bytes:
        raise RuntimeError(f"応答が上限{maximum_bytes}バイトを超えています")
    return data


def run(today: dt.date, max_age_days: int) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    results: list[str] = []
    with tempfile.TemporaryDirectory(prefix="drug-supply-remote-health-") as directory:
        work = Path(directory)
        try:
            version = json.loads(fetch(BASE_URL + "version.json", 64 * 1024))
            errors.extend(validate_version(version, today, max_age_days))
            results.append("version.json")
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
            return [f"version.jsonを取得・解析できません: {error}"], results

        csv_url = version.get("csv_url")
        if not isinstance(csv_url, str):
            return errors + ["version.json: csv_urlを利用できません"], results
        csv_path = work / "drugs_app_ready.csv"
        try:
            csv_path.write_bytes(fetch(csv_url, MAX_CSV_BYTES))
            csv_errors, _ = validate_drug_csv(
                csv_path,
                today=today,
                max_age_days=max_age_days,
            )
            errors.extend(f"remote CSV: {error}" for error in csv_errors)
            results.append("drugs_app_ready.csv")
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            errors.append(f"remote CSVを取得・解析できません: {error}")

        documents: dict[str, object] = {}
        for name in SUPPORTING_FILES:
            try:
                document = json.loads(fetch(BASE_URL + name, MAX_JSON_BYTES))
                documents[name] = document
                errors.extend(validate_supporting_document(name, document))
                results.append(name)
            except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                errors.append(f"{name}を取得・解析できません: {error}")

        lifecycle = documents.get("product_lifecycle.json")
        if lifecycle is not None and csv_path.exists():
            errors.extend(
                f"product_lifecycle.json: {error}"
                for error in validate_lifecycle(lifecycle, load_csv(csv_path))
            )
    return errors, results


def write_summary(errors: list[str], results: list[str]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    status = "❌ 異常を検出" if errors else "✅ 正常"
    with Path(summary_path).open("a", encoding="utf-8") as handle:
        handle.write(f"## 医薬品供給ナビ データ健全性: {status}\n\n")
        handle.write(f"取得・検証完了: {len(results)}ファイル\n\n")
        if errors:
            handle.write("\n".join(f"- {error}" for error in errors) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-age-days", type=int, default=4)
    parser.add_argument("--today", type=dt.date.fromisoformat, default=dt.date.today())
    args = parser.parse_args()
    errors, results = run(args.today, args.max_age_days)
    write_summary(errors, results)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: 公開データ{len(results)}ファイルの取得・鮮度・整合性を検証しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
