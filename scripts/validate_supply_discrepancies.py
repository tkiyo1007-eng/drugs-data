#!/usr/bin/env python3
"""supply_discrepancies.json の型と供給CSV・メーカー案内との整合を検証する。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


YJ_RE = re.compile(r"(?:[0-9A-Z]{12}|X[0-9]{5})\Z")
DATE_RE = re.compile(r"\d{4}-\d{2}(?:-\d{2})?\Z")
ALLOWED_STATES = {"ok", "limited", "stopped", "resumed"}
ALLOWED_CONFIDENCE = {"high", "review"}
ALLOWED_SCOPE = {"product", "package", "ambiguous"}


def load_csv(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["YJコード"]: row for row in csv.DictReader(handle)}


def validate(document: object, rows: dict[str, dict[str, str]],
             announcements: dict[str, object] | None = None,
             events: dict[str, object] | None = None) -> list[str]:
    if not isinstance(document, dict):
        return ["ルートはオブジェクトである必要があります"]
    errors: list[str] = []
    if document.get("schema_version") != 1:
        errors.append("schema_version は1である必要があります")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(document.get("generated_at") or "")):
        errors.append("generated_at はYYYY-MM-DDである必要があります")
    products = document.get("products")
    if not isinstance(products, dict):
        return errors + ["products はオブジェクトである必要があります"]
    counts = document.get("counts")
    if not isinstance(counts, dict):
        errors.append("counts はオブジェクトである必要があります")
    else:
        high = sum(isinstance(value, dict) and value.get("confidence") == "high" for value in products.values())
        review = sum(isinstance(value, dict) and value.get("confidence") == "review" for value in products.values())
        if counts != {"high": high, "review": review, "total": len(products)}:
            errors.append("counts がproductsの集計と一致しません")

    announcement_urls = {
        str(value.get("url")) for value in (announcements or {}).values()
        if isinstance(value, dict) and value.get("url")
    }
    for history in (events or {}).values():
        if isinstance(history, list):
            announcement_urls.update(
                str(value.get("url")) for value in history
                if isinstance(value, dict) and value.get("url")
            )
    for yj, entry in products.items():
        prefix = f"products.{yj}"
        if not YJ_RE.fullmatch(str(yj)) or yj not in rows:
            errors.append(f"{prefix}: CSVに存在するYJコードではありません")
            continue
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: オブジェクトではありません")
            continue
        row = rows[yj]
        if entry.get("product_name") != row.get("商品名"):
            errors.append(f"{prefix}: 商品名がCSVと一致しません")
        confidence = entry.get("confidence")
        if confidence not in ALLOWED_CONFIDENCE:
            errors.append(f"{prefix}: confidence が不正です")
        official = entry.get("official")
        manufacturer = entry.get("manufacturer")
        evidence = entry.get("evidence")
        if not isinstance(official, dict) or official.get("status") not in ALLOWED_STATES:
            errors.append(f"{prefix}: official が不正です")
        if not isinstance(manufacturer, dict):
            errors.append(f"{prefix}: manufacturer が不正です")
            continue
        if manufacturer.get("status") not in ALLOWED_STATES:
            errors.append(f"{prefix}: manufacturer.status が不正です")
        if manufacturer.get("scope") not in ALLOWED_SCOPE:
            errors.append(f"{prefix}: manufacturer.scope が不正です")
        if not DATE_RE.fullmatch(str(manufacturer.get("announced_at") or "")):
            errors.append(f"{prefix}: announced_at が不正です")
        url = str(manufacturer.get("url") or "")
        if not url.startswith("https://"):
            errors.append(f"{prefix}: メーカーURLはHTTPS必須です")
        if announcement_urls and url not in announcement_urls:
            errors.append(f"{prefix}: URLがメーカー案内データにありません")
        if not isinstance(evidence, dict) or evidence.get("manufacturer_notice_is_newer") is not True:
            errors.append(f"{prefix}: 新しい案内である根拠がありません")
        if confidence == "high" and (
            not isinstance(evidence, dict)
            or evidence.get("maker_match") is not True
            or evidence.get("exact_product_in_title") is not True
        ):
            errors.append(f"{prefix}: high はメーカー・製品規格の完全一致が必要です")
        if isinstance(official, dict) and official.get("status") == manufacturer.get("status"):
            errors.append(f"{prefix}: 同じ状態を差異として登録しています")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", nargs="?", default="supply_discrepancies.json")
    parser.add_argument("--csv", default="drugs_app_ready.csv")
    parser.add_argument("--announcements", default="maker_announcements.json")
    parser.add_argument("--events", default="maker_announcement_events.json")
    args = parser.parse_args()
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    announcements = json.loads(Path(args.announcements).read_text(encoding="utf-8"))
    events_path = Path(args.events)
    events = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else {}
    errors = validate(document, load_csv(Path(args.csv)), announcements, events)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"OK: 供給情報差異 {len(document['products'])}件を検証しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
