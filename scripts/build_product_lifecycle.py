#!/usr/bin/env python3
"""メーカー案内JSONから、完全一致した販売中止予定だけをYJコードへ変換する。"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

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


def verified_group_announcements(document: object) -> dict[str, dict[str, object]]:
    """公式資料の本文・表で対象品目を再確認済みのグループだけを展開する。"""
    if not isinstance(document, list):
        return {}
    result: dict[str, dict[str, object]] = {}
    for group in document:
        if not isinstance(group, dict) or group.get("target_products_verified") is not True:
            continue
        products = group.get("products")
        announcement = group.get("announcement")
        if not isinstance(products, list) or not isinstance(announcement, dict):
            continue
        for product_name in products:
            if not isinstance(product_name, str) or not product_name.strip():
                continue
            info = dict(announcement)
            info["target_products_verified"] = True
            result[product_name] = info
    return result


def announcement_date(title: str, source_url: str = "") -> str | None:
    match = DATE_RE.search(norm(title))
    if match:
        year, month, day = int(match.group("y")), int(match.group("m")), match.group("d")
        try:
            if day:
                return dt.date(year, month, int(day)).isoformat()
            dt.date(year, month, 1)
            return f"{year:04d}-{month:02d}"
        except ValueError:
            pass
    decoded_url = unquote(source_url or "")
    match = re.search(
        r"(?:^|[/?&=_.-])(?P<y>20\d{2})[._-]?(?P<m>\d{2})[._-]?"
        r"(?P<d>\d{2})(?=$|[&_.-])",
        decoded_url,
    )
    if match:
        try:
            return dt.date(*(int(match.group(key)) for key in ("y", "m", "d"))).isoformat()
        except ValueError:
            pass
    return None


def backfill_announcement_dates(products: dict[str, dict[str, str]]) -> int:
    """既存データにも安全に抽出できる案内日を補完する。"""
    count = 0
    for item in products.values():
        if item.get("announced_at"):
            continue
        value = announcement_date(item.get("source_title", ""), item.get("source_url", ""))
        if value:
            item["announced_at"] = value
            count += 1
    return count


def announcement_covers_product(product_name: str, title: str) -> bool:
    """案内タイトルが対象規格そのものを含むか。2.5mg中の5mgを誤一致させない。"""
    name_n, title_n = norm(product_name), norm(title)
    if name_n in title_n:
        return True
    maker_match = re.search(r"「[^」]+」\s*$", name_n)
    maker_suffix = maker_match.group(0) if maker_match else ""
    body = name_n[: maker_match.start()] if maker_match else name_n
    strengths = {(m.group("number"), m.group("unit").lower()) for m in STRENGTH_RE.finditer(body)}
    if not maker_suffix or maker_suffix not in title_n:
        return False
    # 「1番/2番/3番/4番」のように規格番号を一つの公式案内に並べる
    # 配合剤に対応する。メーカー括弧と製品本体の完全な「N番」の
    # 両方を必須にし、1番を10番などに誤照合しないようにする。
    if not strengths:
        numbered = re.fullmatch(r"(?P<core>.+?)(?P<number>\d+)番", body)
        if numbered:
            number = re.escape(numbered.group("number"))
            return (
                numbered.group("core") in title_n
                and re.search(rf"(?<!\d){number}\s*番(?!\d)", title_n) is not None
            )
        return False
    core = STRENGTH_RE.sub("", body).strip()
    title_strengths = {(m.group("number"), m.group("unit").lower()) for m in STRENGTH_RE.finditer(title_n)}
    return bool(core) and core in title_n and strengths.issubset(title_strengths)


def announcement_targets_product(product_name: str, announcement: object) -> bool:
    """販売中止案内が当該品目を対象とすることを確認する。

    手動グループは公式資料の本文・表で対象品目を確認済み。
    自動収集データは従来どおりタイトルで厳格照合する。
    """
    if not isinstance(announcement, dict):
        return False
    if announcement.get("target_products_verified") is True:
        return True
    return announcement_covers_product(product_name, announcement.get("title") or "")


def is_product_wide_discontinuation(announcement: object) -> bool:
    """製品全体の販売中止案内だけをライフサイクルへ反映する。"""
    if not isinstance(announcement, dict):
        return False
    title = announcement.get("title") or ""
    if announcement.get("event_type") == "package_discontinued":
        return False
    return bool(END_RE.search(title) and not PARTIAL_RE.search(title))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--announcements", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--manual-groups", type=Path, default=Path("manual_announcement_groups.json"),
        help="本文・表で対象を確認済みの手動グループ",
    )
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
        backfilled = backfill_announcement_dates(products)
        if backfilled:
            print(f"既存データの案内日を補完: {backfilled}件", file=sys.stderr)

    skipped: list[str] = []
    today = jst_today().isoformat()
    announcement_sets: list[dict[str, dict[str, object]]] = []
    for path in args.announcements:
        with path.open(encoding="utf-8") as handle:
            announcement_sets.append(exact_announcements(json.load(handle)))
    if args.manual_groups and args.manual_groups.exists():
        with args.manual_groups.open(encoding="utf-8") as handle:
            announcement_sets.append(verified_group_announcements(json.load(handle)))
    for announcements in announcement_sets:
        for product_name, announcement in announcements.items():
            title = announcement.get("title") if isinstance(announcement, dict) else ""
            if not isinstance(announcement, dict) or not END_RE.search(title or ""):
                continue
            if not is_product_wide_discontinuation(announcement):
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
            if not announcement_targets_product(product_name, announcement):
                skipped.append(f"{product_name}: 案内タイトルで対象規格を確認できません")
                continue
            row = candidates[0]
            yj_code = (row.get("YJコード") or "").strip()
            current = products.get(yj_code) or {}
            if current.get("state") == "active":
                continue  # 明示的に解除された品目は自動処理で再登録しない
            source_url = announcement.get("url") or ""
            announced_at = (
                announcement.get("announced_at")
                or announcement_date(title or "", source_url)
                or current.get("announced_at")
            )
            verified_candidates = [
                value for value in (announcement.get("checked"), current.get("verified_at"))
                if value
            ]
            verified_at = max(verified_candidates) if verified_candidates else today
            products[yj_code] = {
                "product_name": row.get("商品名") or product_name,
                "maker": announcement.get("maker") or "",
                "state": "discontinuation_announced",
                **({"announced_at": announced_at} if announced_at else {}),
                **({"supply_end_expected": current["supply_end_expected"]} if current.get("supply_end_expected") else {}),
                "source_title": title or "",
                "source_url": source_url,
                "verified_at": verified_at,
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
