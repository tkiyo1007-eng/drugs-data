#!/usr/bin/env python3
"""Make last-known manufacturer/lifecycle data compatible with a fresh core CSV.

The MHLW list can legitimately remove a product.  Before the core snapshot is
published, stale optional records for removed or renamed products are pruned and
the remaining set is strictly validated.  This keeps the intermediate core
commit self-consistent even if the later network-based enrichment refresh falls
back to the previous data.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import tempfile
import unicodedata
from pathlib import Path

from update_maker_enrichment import MANAGED_FILES, publish_validated_files
from validate_maker_announcements import (
    validate as validate_announcements,
    validate_current_history,
    validate_health,
    validate_history,
    validate_unmatched,
)
from validate_product_lifecycle import validate as validate_lifecycle
from maker_identity import maker_is_listed_in_row


LIFECYCLE_FILE = "product_lifecycle.json"


def _norm(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _write_json(
    path: Path, document: object, *, indent: int = 1, trailing_newline: bool = False,
) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=indent)
        + ("\n" if trailing_newline else ""),
        encoding="utf-8",
    )


def validate_retained_bundle(
    base: Path, *, csv_path: Path | None = None, min_count: int = 300,
) -> list[str]:
    """既存core境界の保持データ検査。元データやmanual登録は変更しない。

    手動登録元の古い対象は任意メーカー更新側で厳格検査する。ここでは表示に使う
    保持4 JSONとlifecycleが最新CSVへ整合済みであることを要求する。
    """
    csv_path = csv_path or base / "drugs_app_ready.csv"
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        rows_by_yj = {(row.get("YJコード") or "").strip(): row for row in csv.DictReader(handle)}
    lifecycle = json.loads((base / LIFECYCLE_FILE).read_text(encoding="utf-8"))
    errors = validate_announcements(str(csv_path), str(base / "maker_announcements.json"),
                                    min_count=min_count)
    errors.extend(validate_history(str(base / "maker_announcement_events.json")))
    errors.extend(validate_current_history(str(base / "maker_announcements.json"),
                                           str(base / "maker_announcement_events.json")))
    errors.extend(validate_unmatched(str(base / "unmatched_maker_announcements.json")))
    errors.extend(validate_health(str(base / "maker_collection_health.json")))
    errors.extend(validate_lifecycle(lifecycle, rows_by_yj, 0))
    return errors


def reconcile(base: Path, *, min_count: int = 300) -> tuple[int, int]:
    """Prune stale optional records, validate the set, then publish it.

    Returns the number of removed announcement keys and lifecycle products.
    """
    base = base.resolve()
    with (base / "drugs_app_ready.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    product_names = {row.get("商品名") or "" for row in rows}
    rows_by_yj = {(row.get("YJコード") or "").strip(): row for row in rows}

    with tempfile.TemporaryDirectory(prefix="optional-core-reconcile-") as directory:
        stage = Path(directory)
        for name in MANAGED_FILES:
            shutil.copy2(base / name, stage / name)

        announcements = json.loads((stage / "maker_announcements.json").read_text(encoding="utf-8"))
        history = json.loads((stage / "maker_announcement_events.json").read_text(encoding="utf-8"))
        if not isinstance(announcements, dict) or not isinstance(history, dict):
            raise ValueError("メーカー案内と履歴はオブジェクトである必要があります")
        filtered_announcements = {
            name: info for name, info in announcements.items() if name in product_names
        }
        filtered_history = {
            name: events for name, events in history.items() if name in product_names
        }
        removed_announcements = (
            len(announcements) - len(filtered_announcements)
            + len(history) - len(filtered_history)
        )
        _write_json(stage / "maker_announcements.json", filtered_announcements)
        _write_json(stage / "maker_announcement_events.json", filtered_history)

        lifecycle = json.loads((base / LIFECYCLE_FILE).read_text(encoding="utf-8"))
        products = lifecycle.get("products") if isinstance(lifecycle, dict) else None
        if not isinstance(products, dict):
            raise ValueError("product_lifecycle.json.products はオブジェクトである必要があります")

        def compatible(yj_code: str, item: object) -> bool:
            if not isinstance(item, dict):
                return False
            row = rows_by_yj.get(yj_code)
            if row is None or _norm(item.get("product_name")) != _norm(row.get("商品名")):
                return False
            return maker_is_listed_in_row(item.get("maker"), row)

        filtered_products = {
            yj_code: item for yj_code, item in products.items() if compatible(yj_code, item)
        }
        removed_lifecycle = len(products) - len(filtered_products)
        lifecycle["products"] = filtered_products
        _write_json(stage / LIFECYCLE_FILE, lifecycle, indent=2, trailing_newline=True)

        errors = validate_retained_bundle(stage, csv_path=base / "drugs_app_ready.csv", min_count=min_count)
        if errors:
            raise ValueError("前回の補足情報を最新CSVへ整合できません: " + " / ".join(errors[:10]))

        publish_validated_files(
            stage, base, (*MANAGED_FILES, LIFECYCLE_FILE),
        )
    return removed_announcements, removed_lifecycle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("."))
    parser.add_argument("--min-count", type=int, default=300)
    args = parser.parse_args()
    try:
        removed_announcements, removed_lifecycle = reconcile(
            args.base, min_count=args.min_count,
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}")
        return 1
    print(
        "✅ 前回の補足情報を最新CSVへ整合: "
        f"案内/履歴 {removed_announcements}件除外 / ライフサイクル {removed_lifecycle}件除外"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
