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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from validate_supply_data import ALLOWED_STATUSES, YJ_PATTERN, validate_csv as validate_drug_csv
from validate_product_lifecycle import load_csv, validate as validate_lifecycle
from validate_supply_discrepancies import load_csv as load_discrepancy_csv, validate as validate_discrepancies
from public_data_manifest import JSON_FILES, MANIFEST_NAME, PUBLIC_FILES, fingerprint, validate_manifest


BASE_URL = "https://raw.githubusercontent.com/tkiyo1007-eng/drugs-data/main/"
PAGES_URL = "https://tkiyo1007-eng.github.io/drugs-data/"
MAX_JSON_BYTES = 20 * 1024 * 1024
MAX_CSV_BYTES = 30 * 1024 * 1024
SUPPORTING_FILES = JSON_FILES
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
    if type(version) is not int or version <= 0:
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
    if name in {"product_lifecycle.json", "featured_products.json", "industry_topics.json", "supply_discrepancies.json"}:
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
            label = f"{name}: {index + 1}件目"
            if not isinstance(item, dict) or not all(
                isinstance(item.get(key), str) and item[key].strip()
                for key in ("date", "yj", "name", "from", "to")
            ):
                errors.append(f"{name}: {index + 1}件目に必須項目がありません")
            else:
                try:
                    parsed = dt.datetime.strptime(item["date"], "%Y/%m/%d").date()
                    if parsed.strftime("%Y/%m/%d") != item["date"]:
                        raise ValueError("非正規日付")
                except ValueError:
                    errors.append(f"{label}の日付が実在するYYYY/MM/DDではありません")
                if not YJ_PATTERN.fullmatch(item["yj"]):
                    errors.append(f"{label}の品目IDが不正です")
                if item["from"] not in ALLOWED_STATUSES or item["to"] not in ALLOWED_STATUSES:
                    errors.append(f"{label}の供給区分が不正です")
            if len(errors) >= 20:
                break
    if name == "items/keys.json":
        if (not document or not all(isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9_-]+", key) for key in document)
                or len(set(document)) != len(document)):
            errors.append(f"{name}: 品目キーの型・重複・形式が不正です")
    if name == "maker_collection_health.json":
        sources = document.get("sources")
        try:
            checked = document.get("checked")
            if not isinstance(checked, str) or dt.date.fromisoformat(checked).isoformat() != checked:
                raise ValueError("日付不正")
        except ValueError:
            errors.append(f"{name}: checkedが実在する日付ではありません")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(source, dict) or not isinstance(source.get("source"), str)
            or not source["source"].strip() or type(source.get("ok")) is not bool
            or type(source.get("count")) is not int or source["count"] < 0
            or not isinstance(source.get("error"), str) for source in sources
        ):
            errors.append(f"{name}: sourcesの形式が不正です")
    return errors


def validate_discrepancy_bundle(
    document: object,
    rows: dict[str, dict[str, str]],
    documents: dict[str, object],
) -> list[str]:
    """公開差異JSONを、作成時と同じ案内履歴・確認済み対象表で検証する。"""
    announcements = documents.get("maker_announcements.json")
    announcement_events = documents.get("maker_announcement_events.json")
    manual_groups = documents.get("manual_announcement_groups.json")
    return validate_discrepancies(
        document,
        rows,
        announcements if isinstance(announcements, dict) else None,
        announcement_events if isinstance(announcement_events, dict) else None,
        manual_groups if isinstance(manual_groups, list) else None,
    )


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


def check_pages(
    today: dt.date, max_age_days: int, *, attempts: int = 6, retry_delay: float = 10,
) -> tuple[list[str], list[str]]:
    """Webが読むPagesを直接検査。移動するraw/mainではなく公開artifactと照合する。

    通常は各本文を1回だけ取得する。切替中は整合性表を再取得し、不一致・失敗した
    ファイルだけを再取得する。整合性表が変わった場合も既取得本文は再利用する。
    """
    bodies: dict[str, bytes] = {}
    last_errors: list[str] = []
    manifest: dict = {}
    for attempt in range(max(1, attempts)):
        last_errors = []
        try:
            candidate = json.loads(fetch(PAGES_URL + MANIFEST_NAME, 64 * 1024))
            last_errors.extend(validate_manifest(candidate))
            if last_errors:
                raise ValueError("; ".join(last_errors))
            manifest = candidate
            pending = [name for name in PUBLIC_FILES
                       if name not in bodies or fingerprint(bodies[name]) != manifest["files"][name]]

            def download(name: str) -> tuple[str, bytes | None, str | None]:
                try:
                    limit = MAX_CSV_BYTES if name.endswith(".csv") else MAX_JSON_BYTES
                    return name, fetch(PAGES_URL + name, limit), None
                except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
                    return name, None, f"Pages {name}を取得できません: {error}"

            with ThreadPoolExecutor(max_workers=4) as executor:
                for name, body, error in executor.map(download, pending):
                    if error:
                        last_errors.append(error)
                    elif body is not None:
                        bodies[name] = body
            for name in PUBLIC_FILES:
                if name in bodies and fingerprint(bodies[name]) != manifest["files"][name]:
                    last_errors.append(f"Pages {name}: 公開artifactとのサイズ・SHA256不一致")
            # この読み直しは小さい整合性表のみ。取得中に公開が切り替わった場合を検出する。
            after = json.loads(fetch(PAGES_URL + MANIFEST_NAME, 64 * 1024))
            if after != manifest:
                last_errors.append("Pages: 検査中に公開artifactが切り替わりました")
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as error:
            last_errors = [f"Pages {MANIFEST_NAME}を取得・解析できません: {error}"]
        if not last_errors:
            break
        if attempt + 1 < max(1, attempts):
            time.sleep(retry_delay)
    if last_errors:
        return last_errors, []

    errors: list[str] = []
    documents: dict[str, object] = {}
    results = [f"Pages/{MANIFEST_NAME} (commit {manifest['source_commit'][:12]})"]
    for name in ("version.json", *SUPPORTING_FILES):
        try:
            document = json.loads(bodies[name])
            documents[name] = document
            validation = (validate_version(document, today, max_age_days) if name == "version.json"
                          else validate_supporting_document(name, document))
            errors.extend(f"Pages {error}" for error in validation)
            results.append(f"Pages/{name}")
        except (ValueError, TypeError) as error:
            errors.append(f"Pages {name}を解析できません: {error}")
    with tempfile.TemporaryDirectory(prefix="drug-supply-pages-health-") as directory:
        csv_path = Path(directory) / "drugs_app_ready.csv"
        # version.csv_urlがrawを指していても、ここでは必ずPages自身のCSVを検査する。
        csv_path.write_bytes(bodies["drugs_app_ready.csv"])
        csv_errors, _ = validate_drug_csv(csv_path, today=today, max_age_days=max_age_days,
                                        reject_maker_noise=False)
        errors.extend(f"Pages CSV: {error}" for error in csv_errors)
        results.append("Pages/drugs_app_ready.csv")
        if not csv_errors:
            lifecycle = documents.get("product_lifecycle.json")
            if isinstance(lifecycle, dict):
                errors.extend(f"Pages product_lifecycle.json: {error}"
                              for error in validate_lifecycle(lifecycle, load_csv(csv_path)))
            discrepancies = documents.get("supply_discrepancies.json")
            if isinstance(discrepancies, dict):
                errors.extend(f"Pages supply_discrepancies.json: {error}"
                              for error in validate_discrepancy_bundle(
                                  discrepancies, load_discrepancy_csv(csv_path), documents))
    return errors, results


def run(
    today: dt.date,
    max_age_days: int,
    allow_missing_supply_discrepancies: bool = False,
    allow_stale_supply_discrepancies: bool = False,
    include_pages: bool = True,
) -> tuple[list[str], list[str]]:
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

        if not isinstance(version, dict):
            return errors, results
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
                # PRの検査コードは、まだデプロイ前のmainデータを取得する。
                # 新しい厳格ルールとの一時的不一致はローカルCSV検査で担保し、
                # ここでは公開中データの取得・鮮度・既存整合性だけを確認する。
                reject_maker_noise=False,
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
                # 初回導入PRでは、検査コードが先に動き、main上の新ファイルは
                # まだ404になる。PR時だけこの1ファイルの404を許容し、形式不正や
                # 導入後のpush・定期監視では従来どおり失敗させる。
                if (
                    allow_missing_supply_discrepancies
                    and name == "supply_discrepancies.json"
                    and isinstance(error, urllib.error.HTTPError)
                    and error.code == 404
                ):
                    continue
                errors.append(f"{name}を取得・解析できません: {error}")

        lifecycle = documents.get("product_lifecycle.json")
        if lifecycle is not None and csv_path.exists():
            errors.extend(
                f"product_lifecycle.json: {error}"
                for error in validate_lifecycle(lifecycle, load_csv(csv_path))
            )
        discrepancies = documents.get("supply_discrepancies.json")
        if discrepancies is not None and csv_path.exists():
            discrepancy_errors = validate_discrepancy_bundle(
                discrepancies,
                load_discrepancy_csv(csv_path),
                documents,
            )
            # PRでは検査コードが先に厳格化され、公開mainの生成JSONはまだ旧版。
            # ローカルvalidate.ymlでPR内データを厳格検証し、公開監視はマージ後の
            # push・scheduleで新データに対して必ず厳格化する。
            if not allow_stale_supply_discrepancies:
                errors.extend(
                    f"supply_discrepancies.json: {error}"
                    for error in discrepancy_errors
                )
    if include_pages:
        pages_errors, pages_results = check_pages(today, max_age_days)
        errors.extend(pages_errors)
        results.extend(pages_results)
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
    parser.add_argument("--allow-missing-supply-discrepancies", action="store_true")
    parser.add_argument("--allow-stale-supply-discrepancies", action="store_true")
    parser.add_argument("--skip-pages", action="store_true",
                        help="未公開PRコードのraw検査用。通常運用では指定しない")
    args = parser.parse_args()
    errors, results = run(
        args.today,
        args.max_age_days,
        allow_missing_supply_discrepancies=args.allow_missing_supply_discrepancies,
        allow_stale_supply_discrepancies=args.allow_stale_supply_discrepancies,
        include_pages=not args.skip_pages,
    )
    write_summary(errors, results)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: 公開データ{len(results)}ファイルの取得・鮮度・整合性を検証しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
