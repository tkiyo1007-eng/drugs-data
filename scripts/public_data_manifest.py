#!/usr/bin/env python3
"""検証済みPages artifactだけに添付する配信整合性表。元情報の鮮度証明ではない。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

MANIFEST_NAME = "public-data-manifest.json"
JSON_FILES: dict[str, type] = {
    "maker_announcements.json": dict,
    "maker_announcement_events.json": dict,
    "announcement_packages.json": dict,
    "announcement_summaries.json": dict,
    "news.json": list,
    "status_changes.json": list,
    "resolution_stats.json": dict,
    "maker_links.json": list,
    "manual_announcements.json": dict,
    "manual_announcement_groups.json": list,
    "product_lifecycle.json": dict,
    "featured_products.json": dict,
    "industry_topics.json": dict,
    "crisis_index.json": dict,
    "supply_discrepancies.json": dict,
    "maker_collection_health.json": dict,
    "items/keys.json": list,
}
PUBLIC_FILES = ("version.json", "drugs_app_ready.csv", *JSON_FILES)
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")


def fingerprint(body: bytes) -> dict[str, str | int]:
    return {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def build_manifest(root: Path, commit: str) -> dict:
    if not COMMIT_RE.fullmatch(commit):
        raise ValueError("公開対象commitは完全なSHAで指定してください")
    return {
        "schema_version": 1,
        "source_commit": commit,
        "files": {name: fingerprint((root / name).read_bytes()) for name in PUBLIC_FILES},
    }


def validate_manifest(document: object) -> list[str]:
    if not isinstance(document, dict):
        return ["配信整合性表のルートがオブジェクトではありません"]
    errors = []
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        errors.append("配信整合性表のschema_versionが不正です")
    if not isinstance(document.get("source_commit"), str) or not COMMIT_RE.fullmatch(document["source_commit"]):
        errors.append("配信整合性表のsource_commitが不正です")
    files = document.get("files")
    if not isinstance(files, dict) or set(files) != set(PUBLIC_FILES):
        return errors + ["配信整合性表の対象ファイルが一致しません"]
    for name, entry in files.items():
        if (not isinstance(entry, dict)
                or not isinstance(entry.get("sha256"), str)
                or not HASH_RE.fullmatch(entry["sha256"])
                or type(entry.get("bytes")) is not int or entry["bytes"] <= 0):
            errors.append(f"配信整合性表の値が不正です: {name}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, default=Path("."))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = build_manifest(args.site, args.commit)
    errors = validate_manifest(document)
    if errors:
        raise ValueError("; ".join(errors))
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
