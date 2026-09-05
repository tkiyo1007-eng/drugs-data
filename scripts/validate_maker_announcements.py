#!/usr/bin/env python3
"""メーカー案内データの構造・参照整合性・最低件数を検査する。"""
import argparse
import csv
import datetime
import json
import os
import sys

from maker_identity import maker_is_listed_in_row


ALLOWED_EVENT_TYPES = {
    "discontinued", "package_discontinued", "handling_discontinued", "resumed", "stopped",
    "limited", "supply", "other",
}
REQUIRED_FIELDS = ("maker", "title", "url")
ALLOWED_TARGET_SCOPES = {"product", "package", "seller_route"}


def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _validate_date(value, label, errors, *, allow_month=False):
    """Validate an ISO calendar date without adding precision the source lacks.

    Manufacturer notices are sometimes published with only a year and month.
    ``announced_at`` therefore accepts both ``YYYY-MM`` and ``YYYY-MM-DD``;
    operational timestamps such as ``checked`` remain full dates.
    """
    if value in (None, ""):
        return
    text = str(value)
    if allow_month and len(text) == 7:
        try:
            parsed_month = datetime.date.fromisoformat(f"{text}-01")
        except ValueError:
            errors.append(f"{label}がYYYY-MM形式の実在月ではありません: {value}")
            return
        if parsed_month.strftime("%Y-%m") != text:
            errors.append(f"{label}がYYYY-MM形式ではありません: {value}")
        return
    try:
        parsed = datetime.date.fromisoformat(text)
    except ValueError:
        expected = "YYYY-MMまたはYYYY-MM-DD" if allow_month else "YYYY-MM-DD"
        errors.append(f"{label}が{expected}形式の実在日ではありません: {value}")
        return
    if parsed.isoformat() != text:
        expected = "YYYY-MMまたはYYYY-MM-DD" if allow_month else "YYYY-MM-DD"
        errors.append(f"{label}が{expected}形式ではありません: {value}")


def validate(csv_path, announcement_path, min_count=1):
    errors = []
    with open(csv_path, encoding="utf-8-sig") as f:
        product_names = {r.get("商品名", "") for r in csv.DictReader(f)}
    data = _load_json(announcement_path)

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
        _validate_date(
            info.get("announced_at"), f"announced_at: {name}", errors,
            allow_month=True,
        )
        _validate_date(info.get("checked"), f"checked: {name}", errors)
    return errors


def validate_history(history_path):
    if not os.path.exists(history_path):
        return []
    data = _load_json(history_path)
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
            _validate_date(
                event.get("announced_at"), f"案内履歴のannounced_at: {name}", errors,
                allow_month=True,
            )
            for field in ("first_seen", "last_checked"):
                _validate_date(event.get(field), f"案内履歴の{field}: {name}", errors)
    return errors


def validate_current_history(announcement_path, history_path):
    """現在の代表案内が履歴にも同一タイトル・URLで保存されていることを検査する。"""
    current = _load_json(announcement_path)
    history = _load_json(history_path)
    if not isinstance(current, dict) or not isinstance(history, dict):
        return []  # ルート型のエラーは各専用検査で報告する
    errors = []
    for name, info in current.items():
        if not isinstance(info, dict):
            continue
        events = history.get(name) or []
        if not any(isinstance(event, dict)
                   and event.get("title") == info.get("title")
                   and event.get("url") == info.get("url") for event in events):
            errors.append(f"代表案内が履歴に存在しません: {name}")
    return errors


def validate_unmatched(path):
    data = _load_json(path)
    if not isinstance(data, list):
        return ["未マッチ案内のルートが配列ではありません"]
    errors = []
    seen = set()
    for index, info in enumerate(data):
        label = f"未マッチ案内[{index}]"
        if not isinstance(info, dict):
            errors.append(f"{label}がオブジェクトではありません")
            continue
        for field in REQUIRED_FIELDS:
            if not str(info.get(field, "")).strip():
                errors.append(f"{label}.{field}が空です")
        url = str(info.get("url", ""))
        if url and not url.startswith("https://"):
            errors.append(f"{label}.urlがHTTPSではありません: {url}")
        event_type = info.get("event_type")
        if event_type not in ALLOWED_EVENT_TYPES:
            errors.append(f"{label}.event_typeが不正です: {event_type}")
        key = (str(info.get("maker", "")).strip(), url)
        if key in seen:
            errors.append(f"未マッチ案内のURLが重複しています: {url}")
        seen.add(key)
        _validate_date(
            info.get("announced_at"), f"{label}.announced_at", errors,
            allow_month=True,
        )
    return errors


def validate_manual_groups(csv_path, path, *, allow_removed_targets=False):
    """複数品目向け手動登録の構造とCSV参照を検査する。"""
    if not os.path.exists(path):
        return []
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    product_names = {r.get("商品名", "") for r in rows}
    rows_by_name = {}
    rows_by_yj = {}
    for row in rows:
        rows_by_name.setdefault(row.get("商品名", ""), []).append(row)
        if row.get("YJコード"):
            rows_by_yj[row["YJコード"]] = row
    data = _load_json(path)
    if not isinstance(data, list):
        return ["手動グループ案内のルートが配列ではありません"]
    errors = []
    seen_product_urls = set()
    for index, group in enumerate(data):
        label = f"手動グループ案内[{index}]"
        if not isinstance(group, dict):
            errors.append(f"{label}がオブジェクトではありません")
            continue
        products = group.get("products") or []
        lifecycle_targets = group.get("lifecycle_targets") or []
        if not isinstance(products, list):
            errors.append(f"{label}.productsが配列ではありません")
            products = []
        if not isinstance(lifecycle_targets, list):
            errors.append(f"{label}.lifecycle_targetsが配列ではありません")
            lifecycle_targets = []
        if not products and not lifecycle_targets:
            errors.append(f"{label}: productsまたはlifecycle_targetsを1件以上指定してください")
        if products:
            if len(products) != len(set(products)):
                errors.append(f"{label}.productsに重複があります")
            for name in products:
                if not isinstance(name, str) or not name.strip():
                    errors.append(f"{label}.productsに空または文字列以外の品目があります")
                    continue
                if name not in product_names and not allow_removed_targets:
                    errors.append(f"{label}: CSVに存在しない品目: {name}")
        lifecycle_yj_codes = set()
        for target_index, target in enumerate(lifecycle_targets):
            target_label = f"{label}.lifecycle_targets[{target_index}]"
            if not isinstance(target, dict):
                errors.append(f"{target_label}がオブジェクトではありません")
                continue
            yj_code = str(target.get("yj_code") or "").strip()
            product_name = str(target.get("product_name") or "").strip()
            if not yj_code or not product_name:
                errors.append(f"{target_label}: yj_codeとproduct_nameは必須です")
                continue
            if yj_code in lifecycle_yj_codes:
                errors.append(f"{label}.lifecycle_targetsのYJコードが重複しています: {yj_code}")
            lifecycle_yj_codes.add(yj_code)
            row = rows_by_yj.get(yj_code)
            if row is None:
                if not allow_removed_targets:
                    errors.append(f"{target_label}: CSVに存在しないYJコードです: {yj_code}")
            elif row.get("商品名") != product_name:
                errors.append(f"{target_label}: YJコードと商品名がCSVで一致しません")
        verified = group.get("target_products_verified")
        if verified is not None and verified is not True:
            errors.append(f"{label}.target_products_verifiedはtrueのみ指定できます")
        target_scope = group.get("target_scope")
        if target_scope is not None and target_scope not in ALLOWED_TARGET_SCOPES:
            errors.append(f"{label}.target_scopeが不正です: {target_scope}")
        expected_count = group.get("expected_target_count")
        target_count = len(products) + len(lifecycle_targets)
        if expected_count is not None and (
            not isinstance(expected_count, int) or isinstance(expected_count, bool)
            or expected_count <= 0 or expected_count != target_count
        ):
            errors.append(
                f"{label}.expected_target_countは対象件数{target_count}と一致する正の整数にしてください"
            )
        if verified is True:
            if target_scope not in ALLOWED_TARGET_SCOPES:
                errors.append(f"{label}: 確認済みグループにはtarget_scopeが必須です")
            if expected_count != target_count:
                errors.append(f"{label}: 確認済みグループには正しいexpected_target_countが必須です")
        if lifecycle_targets and (verified is not True or target_scope != "product"):
            errors.append(f"{label}: lifecycle_targetsは製品全体を確認済みのグループだけ指定できます")
        info = group.get("announcement")
        if not isinstance(info, dict):
            errors.append(f"{label}.announcementがオブジェクトではありません")
            continue
        for field in REQUIRED_FIELDS:
            if not str(info.get(field, "")).strip():
                errors.append(f"{label}.announcement.{field}が空です")
        url = str(info.get("url", ""))
        if url and not url.startswith("https://"):
            errors.append(f"{label}.announcement.urlがHTTPSではありません: {url}")
        event_type = info.get("event_type")
        if event_type is not None and event_type not in ALLOWED_EVENT_TYPES:
            errors.append(f"{label}.announcement.event_typeが不正です: {event_type}")
        _validate_date(
            info.get("announced_at"), f"{label}.announcement.announced_at", errors,
            allow_month=True,
        )
        maker = info.get("maker")
        for name in products:
            if (isinstance(name, str) and name in rows_by_name
                    and not any(maker_is_listed_in_row(maker, row) for row in rows_by_name[name])):
                errors.append(f"{label}: メーカーと対象品目が一致しません: {name}")
            key = (name, url)
            if key in seen_product_urls:
                errors.append(f"手動グループ案内の品目とURLが重複しています: {name} ({url})")
            seen_product_urls.add(key)
        for target in lifecycle_targets:
            if not isinstance(target, dict):
                continue
            yj_code = str(target.get("yj_code") or "").strip()
            row = rows_by_yj.get(yj_code)
            if row is not None and not maker_is_listed_in_row(maker, row):
                errors.append(f"{label}: メーカーとlifecycle_targetsが一致しません: {yj_code}")
            key = (yj_code, url)
            if key in seen_product_urls:
                errors.append(f"手動グループ案内のYJコードとURLが重複しています: {yj_code} ({url})")
            seen_product_urls.add(key)
    return errors


def validate_health(path, expected_checked=None):
    data = _load_json(path)
    if not isinstance(data, dict):
        return ["収集状態のルートがオブジェクトではありません"]
    errors = []
    checked = data.get("checked")
    _validate_date(checked, "収集状態.checked", errors)
    if expected_checked and checked != expected_checked:
        errors.append(f"収集確認日が日本時間の実行日と一致しません: {checked}（期待値{expected_checked}）")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        return errors + ["収集状態.sourcesが空または配列ではありません"]
    seen = set()
    count_sum = 0
    for index, source in enumerate(sources):
        label = f"収集状態.sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label}がオブジェクトではありません")
            continue
        name = str(source.get("source", "")).strip()
        if not name:
            errors.append(f"{label}.sourceが空です")
        elif name in seen:
            errors.append(f"収集元が重複しています: {name}")
        seen.add(name)
        if not isinstance(source.get("ok"), bool):
            errors.append(f"{label}.okが真偽値ではありません")
        count = source.get("count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append(f"{label}.countが0以上の整数ではありません")
        else:
            count_sum += count
            if source.get("ok") is True and count == 0:
                errors.append(f"{label}: 成功なのに取得件数が0件です")
        if not isinstance(source.get("error"), str):
            errors.append(f"{label}.errorが文字列ではありません")
    total = data.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        errors.append("収集状態.totalが0以上の整数ではありません")
    elif total > count_sum:
        errors.append(f"収集状態.totalが収集元件数の合計を超えています: {total}>{count_sum}")
    return errors


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="drugs_app_ready.csv")
    p.add_argument("--announcements", default="maker_announcements.json")
    p.add_argument("--events", default="maker_announcement_events.json")
    p.add_argument("--unmatched", default="unmatched_maker_announcements.json")
    p.add_argument("--health", default="maker_collection_health.json")
    p.add_argument("--manual-groups", default="manual_announcement_groups.json")
    p.add_argument("--expected-checked")
    p.add_argument("--min-count", type=int, default=300)
    args = p.parse_args()
    errors = validate(args.csv, args.announcements, args.min_count)
    errors.extend(validate_history(args.events))
    errors.extend(validate_current_history(args.announcements, args.events))
    errors.extend(validate_unmatched(args.unmatched))
    errors.extend(validate_manual_groups(args.csv, args.manual_groups))
    errors.extend(validate_health(args.health, args.expected_checked))
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
