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


def validate_health_document(data, expected_checked=None):
    """採用済み情報と今回の試行を別々に厳密検査する（旧形式も許容）。"""
    if not isinstance(data, dict):
        return ["収集状態のルートがオブジェクトではありません"]
    errors = []
    checked = data.get("checked")
    if not isinstance(checked, str) or not checked:
        errors.append("収集状態.checkedは全収集元の最終成功日が必要です")
    _validate_date(checked, "収集状態.checked", errors)
    attempt = data.get("last_attempt")
    actual_checked = attempt.get("checked") if isinstance(attempt, dict) else checked
    if expected_checked and actual_checked != expected_checked:
        errors.append(f"収集試行日が日本時間の実行日と一致しません: {actual_checked}（期待値{expected_checked}）")
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
        name = source.get("source")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}.sourceが空です")
        elif name in seen:
            errors.append(f"収集元が重複しています: {name}")
        if isinstance(name, str):
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
        elif source.get("ok") is True and source["error"]:
            errors.append(f"{label}: 成功なのにエラーがあります")
        if "last_success" in source:
            value = source["last_success"]
            if not isinstance(value, str) or not value:
                errors.append(f"{label}.last_successに最終成功日が必要です")
            _validate_date(value, f"{label}.last_success", errors)
    total = data.get("total")
    if not isinstance(total, int) or isinstance(total, bool) or total < 0:
        errors.append("収集状態.totalが0以上の整数ではありません")
    elif total > count_sum:
        errors.append(f"収集状態.totalが収集元件数の合計を超えています: {total}>{count_sum}")
    if "last_attempt" not in data:
        return errors
    if not isinstance(attempt, dict):
        return errors + ["収集状態.last_attemptがオブジェクトではありません"]
    attempt_checked = attempt.get("checked")
    if not isinstance(attempt_checked, str) or not attempt_checked:
        errors.append("収集状態.last_attempt.checkedに試行日が必要です")
    _validate_date(attempt_checked, "収集状態.last_attempt.checked", errors)
    if isinstance(checked, str) and isinstance(attempt_checked, str) and checked > attempt_checked:
        errors.append("全収集元の最終成功日が試行日より未来です")
    status = attempt.get("status")
    status = status if isinstance(status, str) else ""
    if status not in {"success", "partial", "failed"}:
        errors.append("収集状態.last_attempt.statusが不正です")
    attempt_errors = attempt.get("errors")
    if (not isinstance(attempt_errors, list)
            or any(not isinstance(value, str) or not value.strip() for value in attempt_errors)):
        errors.append("収集状態.last_attempt.errorsはエラー文字列の配列が必要です")
    elif status == "success" and attempt_errors:
        errors.append("成功した試行にエラーがあります")
    elif status in {"partial", "failed"} and not attempt_errors:
        errors.append("不完全な試行にはエラー理由が必要です")
    attempt_sources = attempt.get("sources")
    if not isinstance(attempt_sources, list) or not attempt_sources:
        return errors + ["収集状態.last_attempt.sourcesが空または配列ではありません"]
    attempt_seen = set()
    attempt_count_sum = 0
    successes = failures = 0
    for index, source in enumerate(attempt_sources):
        label = f"収集状態.last_attempt.sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label}がオブジェクトではありません")
            continue
        name = source.get("source")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{label}.sourceが空または文字列ではありません")
        elif name in attempt_seen:
            errors.append(f"試行の収集元が重複しています: {name}")
        else:
            attempt_seen.add(name)
        ok, count, error = source.get("ok"), source.get("count"), source.get("error")
        if type(ok) is not bool:
            errors.append(f"{label}.okが真偽値ではありません")
        if type(count) is not int or count < 0:
            errors.append(f"{label}.countが0以上の整数ではありません")
        else:
            attempt_count_sum += count
        if not isinstance(error, str):
            errors.append(f"{label}.errorが文字列ではありません")
        if ok is True:
            successes += 1
            if count == 0 or error:
                errors.append(f"{label}: 0件またはエラーのある取得を成功にできません")
        elif ok is False:
            failures += 1
            if not isinstance(error, str) or not error.strip():
                errors.append(f"{label}: 取得失敗の理由が必要です")
        if "retained" in source and type(source["retained"]) is not bool:
            errors.append(f"{label}.retainedが真偽値ではありません")
        if source.get("retained") is True:
            if ok is not False or type(source.get("retained_count")) is not int or source["retained_count"] <= 0:
                errors.append(f"{label}: 前回値保持には失敗状態と正のretained_countが必要です")
            if not source.get("last_success"):
                errors.append(f"{label}: 前回値保持にはlast_successが必要です")
        if "last_success" in source:
            last_success = source["last_success"]
            if not isinstance(last_success, str) or not last_success:
                errors.append(f"{label}.last_successに最終成功日が必要です")
            _validate_date(last_success, f"{label}.last_success", errors)
            if isinstance(last_success, str) and isinstance(attempt_checked, str) and last_success > attempt_checked:
                errors.append(f"{label}.last_successが試行日より未来です")
    if attempt_seen != seen:
        errors.append("採用済み情報と試行結果の収集元が一致しません")
    attempt_total = attempt.get("total")
    if type(attempt_total) is not int or attempt_total < 0:
        errors.append("収集状態.last_attempt.totalが0以上の整数ではありません")
    elif attempt_total > attempt_count_sum:
        errors.append("試行の総取得件数が収集元件数の合計を超えています")
    if status == "success" and (failures or successes != len(attempt_sources) or checked != attempt_checked):
        errors.append("全収集元の成功・確認日が揃わない試行をsuccessにできません")
    if status == "partial" and not (successes and failures):
        errors.append("partialには取得成功と失敗の両方が必要です")
    if status in {"success", "partial"}:
        adopted_by_name = {source["source"]: source for source in sources
                           if isinstance(source, dict) and isinstance(source.get("source"), str)}
        for source in attempt_sources:
            if not isinstance(source, dict) or not isinstance(source.get("source"), str):
                continue
            adopted = adopted_by_name.get(source["source"], {})
            if adopted.get("ok") is not True:
                errors.append("更新時の採用済み収集元には検証済みの成功情報が必要です")
            if source.get("ok") is True and adopted.get("count") != source.get("count"):
                errors.append("取得成功した収集元の採用件数と試行件数が一致しません")
            if source.get("ok") is True and (
                source.get("last_success") != attempt_checked
                or adopted.get("last_success") != attempt_checked
            ):
                errors.append("取得成功した収集元の最終成功日と試行日が一致しません")
            if status == "partial" and source.get("ok") is False and source.get("retained") is not True:
                errors.append("部分更新で失敗した収集元には前回値保持の記録が必要です")
            if source.get("retained") is True and (
                adopted.get("count") != source.get("retained_count")
                or adopted.get("last_success", checked) != source.get("last_success")
            ):
                errors.append("失敗収集元の採用情報と保持件数・成功日が一致しません")
    return errors


def validate_health(path, expected_checked=None):
    return validate_health_document(_load_json(path), expected_checked)


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
