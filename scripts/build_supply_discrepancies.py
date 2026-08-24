#!/usr/bin/env python3
"""厚労省の供給区分と、より新しいメーカー公式案内の差異を構造化する。

厚労省データは上書きしない。検索一覧へ出せる ``high`` と、品目詳細でのみ
原文確認を促す ``review`` を分け、規格違いの誤警告を防ぐ。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

from fetch_maker_announcements import base_name_and_specs, maker_matches_row
from verified_targets import verified_target_registry


TRANSIENT_STATES = {
    "limited": ("limited", "限定出荷"),
    "stopped": ("stopped", "供給停止"),
}
OFFICIAL_STATES = {
    "①通常出荷": ("ok", "通常出荷"),
    "②限定出荷（自社の事情）": ("limited", "限定出荷（自社の事情）"),
    "③限定出荷（他社品の影響）": ("limited", "限定出荷（他社品の影響）"),
    "④限定出荷（その他）": ("limited", "限定出荷（その他）"),
    "⑤供給停止": ("stopped", "供給停止"),
}
DATE_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")
PACKAGE_RE = re.compile(
    r"(?:PTP|SP|バラ|瓶|袋|箱|包|本|管|V|アンプル|シリンジ)\s*[0-9０-９]",
    re.IGNORECASE,
)


def norm(value: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def parse_csv_date(value: object) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(value or "").strip(), "%Y/%m/%d").date()
    except ValueError:
        return None


def official_date(row: dict[str, str]) -> dt.date | None:
    values = [parse_csv_date(row.get(key)) for key in ("更新日", "ステータス更新日")]
    return max((value for value in values if value is not None), default=None)


def announcement_is_definitely_newer(value: object, reference: dt.date | None) -> bool:
    """年月精度の案内は、その月の初日でも更新日より後の場合だけ新しいと断定する。"""
    match = DATE_RE.fullmatch(str(value or "").strip())
    if not match or reference is None:
        return False
    try:
        lower_bound = dt.date(int(match[1]), int(match[2]), int(match[3] or 1))
    except ValueError:
        return False
    return lower_bound > reference


def exact_product_in_title(product_name: str, title: str) -> bool:
    return bool(product_name) and norm(product_name) in norm(title)


def related_product_family_in_title(product_name: str, title: str) -> bool:
    product_n = norm(product_name)
    title_n = norm(title)
    core, _, maker_suffix = base_name_and_specs(product_n)
    return bool(core and core in title_n and (not maker_suffix or maker_suffix in title_n))


def announcement_scope(product_name: str, title: str) -> str:
    title_n = unicodedata.normalize("NFKC", title or "")
    product_n = unicodedata.normalize("NFKC", product_name or "")
    index = title_n.find(product_n)
    if index < 0:
        return "ambiguous"
    # 製品名の直後に包装記号がある案内は、製品全体ではなく包装単位の可能性がある。
    tail = title_n[index + len(product_n): index + len(product_n) + 48]
    return "package" if PACKAGE_RE.search(tail) else "product"


def manufacturer_state(event_type: str, title: str, official_state: str) -> tuple[str, str] | None:
    if event_type in TRANSIENT_STATES:
        return TRANSIENT_STATES[event_type]
    if event_type != "resumed":
        return None
    title_n = norm(title)
    # 「限定出荷による出荷再開」は、出荷は再開しても限定出荷のまま。
    # 「一部包装出荷再開」だけで製品全体を通常出荷へ扱うこともしない。
    if re.search(r"限定出荷(?:の)?解除|出荷調整解除|通常出荷", title_n):
        return ("ok", "限定出荷解除・通常出荷")
    if "限定出荷" in title_n and "出荷再開" in title_n:
        return ("limited", "限定出荷で出荷再開")
    # 厚労省が供給停止のままなら、単なる「出荷再開」でも状態が異なる事実は確実。
    # 再開後の数量制限は断定できないため、通常出荷とは表示しない。
    if official_state == "stopped" and "出荷再開" in title_n:
        return ("resumed", "出荷再開（供給区分は原文確認）")
    return None


def make_entry(
    row: dict[str, str], announcement: dict[str, object],
    verified_target: dict[str, str] | None = None,
) -> dict[str, object] | None:
    event_type = str(announcement.get("event_type") or "")
    official = OFFICIAL_STATES.get((row.get("供給状況") or "").strip())
    transient = manufacturer_state(event_type, str(announcement.get("title") or ""), official[0]) if official else None
    if transient is None or official is None or transient[0] == official[0]:
        return None
    reference_date = official_date(row)
    if not announcement_is_definitely_newer(announcement.get("announced_at"), reference_date):
        return None

    product_name = (row.get("商品名") or "").strip()
    title = str(announcement.get("title") or "").strip()
    maker_match = maker_matches_row(str(announcement.get("maker") or ""), row)
    exact_title = exact_product_in_title(product_name, title)
    family_title = exact_title or related_product_family_in_title(product_name, title)
    if not maker_match or (not family_title and verified_target is None):
        return None

    scope = (
        verified_target.get("scope") if verified_target is not None
        else announcement_scope(product_name, title) if exact_title
        else "ambiguous"
    )
    verified_product = verified_target is not None and scope == "product"
    confidence = "high" if scope == "product" and (exact_title or verified_product) else "review"
    if confidence == "high":
        reason = (
            "メーカー公式資料の対象表で製品全体・公表日の一致を確認"
            if verified_product else "メーカー・製品規格・公表日の一致を確認"
        )
        badge = "情報差異あり"
    elif scope == "package":
        reason = "包装単位のメーカー案内です。製品全体の供給区分は原文で確認してください"
        badge = "メーカー案内あり・原文確認"
    elif scope == "seller_route":
        reason = "販売会社・取扱い経路に関する案内です。製品全体の供給区分は原文で確認してください"
        badge = "メーカー案内あり・原文確認"
    else:
        reason = "関連製品の案内ですが、本品の対象規格を機械判定できません"
        badge = "メーカー案内あり・原文確認"

    reference_text = reference_date.isoformat() if reference_date else ""
    return {
        "product_name": product_name,
        "maker": (row.get("販売メーカー") or row.get("製造メーカー") or "").strip(),
        "official": {
            "status": official[0],
            "label": official[1],
            "updated_at": reference_text,
        },
        "manufacturer": {
            "status": transient[0],
            "label": transient[1],
            "announced_at": str(announcement.get("announced_at") or ""),
            "maker": str(announcement.get("maker") or ""),
            "title": title,
            "url": str(announcement.get("url") or ""),
            "scope": scope,
        },
        "confidence": confidence,
        "reason": reason,
        "badge": badge,
        "evidence": {
            "maker_match": maker_match,
            "exact_product_in_title": exact_title,
            "manufacturer_notice_is_newer": True,
            "verified_target_source": (
                verified_target.get("source") if verified_target is not None else ""
            ),
            "verified_target_scope": scope if verified_target is not None else "",
        },
    }


def latest_transient_announcement(
    representative: dict[str, object] | None,
    history: list[dict[str, object]] | None,
    product_name: str = "",
) -> dict[str, object] | None:
    """履歴の最新供給案内を選ぶ。古い限定出荷を再開後に復活させない。"""
    candidates: list[dict[str, object]] = []
    for value in [*(history or []), representative]:
        if not isinstance(value, dict):
            continue
        if value.get("event_type") not in {"limited", "stopped", "resumed", "supply", "other"}:
            continue
        if not DATE_RE.fullmatch(str(value.get("announced_at") or "")):
            continue
        candidates.append(value)
    if not candidates:
        return None
    latest_date = max(str(value.get("announced_at")) for value in candidates)
    latest = [value for value in candidates if str(value.get("announced_at")) == latest_date]
    known = [value for value in latest if value.get("event_type") in {"limited", "stopped", "resumed"}]
    # 同日中に状態の異なる複数案内がある、または最新案内の状態を分類できない場合は
    # 強い差異判定を作らず、次回の公式データ更新を待つ。
    if not known or len({value.get("event_type") for value in known}) != 1:
        return None
    # 同じ状態なら、品目名をタイトルに完全記載した案内を優先する。
    return max(
        known,
        key=lambda value: (
            exact_product_in_title(product_name, str(value.get("title") or "")),
            str(value.get("last_checked") or value.get("checked") or ""),
        ),
    )


def build(rows: list[dict[str, str]], announcements: dict[str, dict[str, object]],
          version: dict[str, object] | None = None,
          events: dict[str, list[dict[str, object]]] | None = None,
          manual_groups: object | None = None) -> dict[str, object]:
    products: dict[str, dict[str, object]] = {}
    verified_targets = verified_target_registry(rows, manual_groups or [])
    announcements_by_name = {norm(name): value for name, value in announcements.items()}
    events_by_name = {norm(name): value for name, value in (events or {}).items()}
    for row in rows:
        yj = (row.get("YJコード") or "").strip()
        product_key = norm(row.get("商品名"))
        announcement = latest_transient_announcement(
            announcements_by_name.get(product_key),
            events_by_name.get(product_key),
            str(row.get("商品名") or ""),
        )
        if not yj or announcement is None:
            continue
        entry = make_entry(
            row, announcement,
            verified_targets.get((yj, str(announcement.get("url") or "").strip())),
        )
        if entry is not None:
            products[yj] = entry

    checked_dates = sorted({
        str(value.get("checked")) for value in announcements.values()
        if isinstance(value, dict) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value.get("checked") or ""))
    })
    version = version or {}
    version_value = version.get("version")
    version_date = str(version_value)[:8] if isinstance(version_value, int) else ""
    generated_at = checked_dates[-1] if checked_dates else (
        f"{version_date[:4]}-{version_date[4:6]}-{version_date[6:8]}" if len(version_date) == 8 else ""
    )
    high = sum(value["confidence"] == "high" for value in products.values())
    review = len(products) - high
    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": {
            "mhlw_version": version_value,
            "mhlw_note": str(version.get("note") or ""),
            "manufacturer_checked_through": checked_dates[-1] if checked_dates else "",
        },
        "counts": {"high": high, "review": review, "total": len(products)},
        "products": dict(sorted(products.items())),
    }


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="drugs_app_ready.csv")
    parser.add_argument("--announcements", default="maker_announcements.json")
    parser.add_argument("--events", default="maker_announcement_events.json")
    parser.add_argument("--version", default="version.json")
    parser.add_argument("--manual-groups", default="manual_announcement_groups.json")
    parser.add_argument("--output", default="supply_discrepancies.json")
    args = parser.parse_args()
    rows = load_rows(Path(args.csv))
    announcements = json.loads(Path(args.announcements).read_text(encoding="utf-8"))
    events_path = Path(args.events)
    events = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else {}
    version_path = Path(args.version)
    version = json.loads(version_path.read_text(encoding="utf-8")) if version_path.exists() else {}
    manual_groups_path = Path(args.manual_groups)
    manual_groups = (
        json.loads(manual_groups_path.read_text(encoding="utf-8"))
        if manual_groups_path.exists() else []
    )
    document = build(rows, announcements, version, events, manual_groups)
    Path(args.output).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "供給情報差異: "
        f"高確度{document['counts']['high']}件 / 要原文確認{document['counts']['review']}件"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
