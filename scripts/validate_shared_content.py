#!/usr/bin/env python3
"""Web・iOSで共有する手動設定JSONを検証する。"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


def norm(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).lower().strip()


def read_json(path: Path) -> object:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def valid_https(value: object) -> bool:
    parsed = urlparse(str(value or ""))
    return parsed.scheme == "https" and bool(parsed.netloc)


def valid_date(value: object, dotted: bool = False) -> bool:
    try:
        dt.datetime.strptime(str(value), "%Y.%m.%d" if dotted else "%Y-%m-%d")
        return True
    except (TypeError, ValueError):
        return False


def validate(base: Path) -> list[str]:
    errors: list[str] = []
    with (base / "drugs_app_ready.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    search_haystacks = [
        norm(" ".join((row.get("商品名", ""), row.get("一般名", ""),
                       row.get("製造メーカー", ""), row.get("販売メーカー", ""),
                       row.get("YJコード", ""))))
        for row in rows
    ]

    links = read_json(base / "maker_links.json")
    if not isinstance(links, list) or not links:
        errors.append("maker_links.json: 1件以上の配列にしてください")
    else:
        seen_names: set[str] = set()
        for index, item in enumerate(links):
            prefix = f"maker_links.json[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix}: オブジェクトにしてください")
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                errors.append(f"{prefix}.name: 必須です")
            elif name in seen_names:
                errors.append(f"{prefix}.name: 重複しています")
            seen_names.add(name)
            if not valid_https(item.get("url")):
                errors.append(f"{prefix}.url: HTTPS URLを指定してください")

    featured = read_json(base / "featured_products.json")
    if not isinstance(featured, dict) or featured.get("schema_version") != 1:
        errors.append("featured_products.json: schema_version は1にしてください")
    else:
        if not valid_date(featured.get("updated_at")):
            errors.append("featured_products.json.updated_at: YYYY-MM-DDで指定してください")
        products = featured.get("products")
        if not isinstance(products, list) or not products:
            errors.append("featured_products.json.products: 1件以上の配列にしてください")
        else:
            seen_labels: set[str] = set()
            for index, item in enumerate(products):
                prefix = f"featured_products.json.products[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix}: オブジェクトにしてください")
                    continue
                label = str(item.get("label") or "").strip()
                query = norm(item.get("query"))
                if not label or not query:
                    errors.append(f"{prefix}: labelとqueryは必須です")
                    continue
                if label in seen_labels:
                    errors.append(f"{prefix}.label: 重複しています")
                seen_labels.add(label)
                terms = query.split()
                if not any(all(term in haystack for term in terms) for haystack in search_haystacks):
                    errors.append(f"{prefix}.query: CSVの品目に一致しません（{item.get('query')}）")

    topics = read_json(base / "industry_topics.json")
    if not isinstance(topics, dict) or topics.get("schema_version") != 1:
        errors.append("industry_topics.json: schema_version は1にしてください")
    else:
        if not valid_date(topics.get("updated_at")):
            errors.append("industry_topics.json.updated_at: YYYY-MM-DDで指定してください")
        items = topics.get("topics")
        if not isinstance(items, list) or not items:
            errors.append("industry_topics.json.topics: 1件以上の配列にしてください")
        else:
            seen_titles: set[str] = set()
            for index, item in enumerate(items):
                prefix = f"industry_topics.json.topics[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{prefix}: オブジェクトにしてください")
                    continue
                for field in ("date", "tag", "title", "lede"):
                    if not str(item.get(field) or "").strip():
                        errors.append(f"{prefix}.{field}: 必須です")
                if not valid_date(item.get("date"), dotted=True):
                    errors.append(f"{prefix}.date: YYYY.MM.DDで指定してください")
                if item.get("tone", "info") not in {"info", "warn", "alert"}:
                    errors.append(f"{prefix}.tone: info/warn/alertのいずれかにしてください")
                title = str(item.get("title") or "").strip()
                if title in seen_titles:
                    errors.append(f"{prefix}.title: 重複しています")
                seen_titles.add(title)
                source = item.get("source")
                if not isinstance(source, dict) or not str(source.get("name") or "").strip():
                    errors.append(f"{prefix}.source.name: 必須です")
                elif not valid_https(source.get("url")):
                    errors.append(f"{prefix}.source.url: HTTPS URLを指定してください")
                query = norm(item.get("query"))
                if query:
                    terms = query.split()
                    if not any(all(term in haystack for term in terms) for haystack in search_haystacks):
                        errors.append(f"{prefix}.query: CSVの品目に一致しません（{item.get('query')}）")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("."))
    args = parser.parse_args()
    errors = validate(args.base)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("OK: Web・iOS共通設定を検証しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
