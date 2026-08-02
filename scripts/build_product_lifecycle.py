#!/usr/bin/env python3
"""メーカー案内JSONから、完全一致した販売中止予定だけをYJコードへ変換する。"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

from jst_time import jst_now, jst_today


END_RE = re.compile(r"販売中止|販売終了|製造中止|製造販売中止")
PARTIAL_RE = re.compile(r"一部包装")
DATE_RE = re.compile(r"(?P<y>20\d{2})[./年](?P<m>\d{1,2})(?:[./月](?P<d>\d{1,2}))?")
STRENGTH_RE = re.compile(r"(?<![\d.])(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>mg|g|μg|mcg|%|mL|L)", re.I)


def norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def exact_announcements(document: object) -> dict[str, dict[str, str]]:
    if not isinstance(document, dict):
        return {}
    exact = document.get("exact") if "exact" in document or "patterns" in document else document
    return exact if isinstance(exact, dict) else {}


def announcement_date(title: str) -> str | None:
    match = DATE_RE.search(norm(title))
    if not match:
        return None
    year, month, day = match.group("y"), int(match.group("m")), match.group("d")
    return f"{year}-{month:02d}" + (f"-{int(day):02d}" if day else "")


def announcement_covers_product(product_name: str, title: str) -> bool:
    """案内タイトルが対象規格そのものを含むか。2.5mg中の5mgを誤一致させない。"""
    name_n, title_n = norm(product_name), norm(title)
    if name_n in title_n:
        return True
    maker_match = re.search(r"「[^」]+」\s*$", name_n)
    maker_suffix = maker_match.group(0) if maker_match else ""
    body = name_n[: maker_match.start()] if maker_match else name_n
    strengths = {(m.group("number"), m.group("unit").lower()) for m in STRENGTH_RE.finditer(body)}
    if not maker_suffix or not strengths or maker_suffix not in title_n:
        return False
    core = STRENGTH_RE.sub("", body).strip()
    title_strengths = {(m.group("number"), m.group("unit").lower()) for m in STRENGTH_RE.finditer(title_n)}
    return bool(core) and core in title_n and strengths.issubset(title_strengths)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--announcements", type=Path, nargs="+", required=True)
    parser.add_argument("--existing", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_name: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_name.setdefault(norm(row.get("商品名") or ""), []).append(row)

    products: dict[str, dict[str, str]] = {}
    if args.existing and args.existing.exists():
        with args.existing.open(encoding="utf-8") as handle:
            previous = json.load(handle)
        products.update(previous.get("products") or {})

    skipped: list[str] = []
    today = jst_today().isoformat()
    for path in args.announcements:
        with path.open(encoding="utf-8") as handle:
            announcements = exact_announcements(json.load(handle))
        for product_name, announcement in announcements.items():
            title = announcement.get("title") if isinstance(announcement, dict) else ""
            if not isinstance(announcement, dict) or not END_RE.search(title or ""):
                continue
            if PARTIAL_RE.search(title or ""):
                skipped.append(f"{product_name}: 一部包装のみの案内は製品全体の販売中止にしません")
                continue
            maker = norm(announcement.get("maker") or "")
            candidates = [
                row for row in by_name.get(norm(product_name), [])
                if maker in {norm(row.get("製造メーカー") or ""), norm(row.get("販売メーカー") or "")}
            ]
            if len(candidates) != 1:
                skipped.append(f"{product_name}: 商品名＋メーカーでYJコードを一意に決定できません（{len(candidates)}件）")
                continue
            if not announcement_covers_product(product_name, title or ""):
                skipped.append(f"{product_name}: 案内タイトルで対象規格を確認できません")
                continue
            row = candidates[0]
            yj_code = (row.get("YJコード") or "").strip()
            current = products.get(yj_code) or {}
            if current.get("state") == "active":
                continue  # 明示的に解除された品目は自動処理で再登録しない
            products[yj_code] = {
                "product_name": row.get("商品名") or product_name,
                "maker": announcement.get("maker") or "",
                "state": "discontinuation_announced",
                **({"announced_at": announcement_date(title or "")} if announcement_date(title or "") else {}),
                **({"supply_end_expected": current["supply_end_expected"]} if current.get("supply_end_expected") else {}),
                "source_title": title or "",
                "source_url": announcement.get("url") or "",
                "verified_at": today,
            }

    output = {
        "schema_version": 1,
        "generated_at": jst_now().isoformat(timespec="seconds"),
        "products": dict(sorted(products.items())),
    }
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for message in skipped:
        print(f"REVIEW: {message}", file=sys.stderr)
    print(f"generated: {len(products)}件 / review: {len(skipped)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
