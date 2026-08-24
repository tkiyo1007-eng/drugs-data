#!/usr/bin/env python3
"""本文・表で確認済みの手動対象をYJコード単位へ安全に展開する。"""

from __future__ import annotations

from maker_identity import maker_is_listed_in_row


ALLOWED_SCOPES = {"product", "package", "seller_route"}


def verified_target_registry(
    rows: list[dict[str, str]], groups: object,
) -> dict[tuple[str, str], dict[str, str]]:
    """``(YJコード, 公式URL)`` をキーに、確認済み対象範囲を返す。

    件数宣言・メーカー・商品名のいずれかが曖昧なグループは信頼境界へ
    入れない。同名で複数YJがある場合は ``lifecycle_targets`` の明示を必須にする。
    """
    if not isinstance(groups, list):
        return {}
    by_name: dict[str, list[dict[str, str]]] = {}
    by_yj: dict[str, dict[str, str]] = {}
    for row in rows:
        by_name.setdefault(row.get("商品名") or "", []).append(row)
        yj_code = (row.get("YJコード") or "").strip()
        if yj_code:
            by_yj[yj_code] = row

    result: dict[tuple[str, str], dict[str, str]] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, dict) or group.get("target_products_verified") is not True:
            continue
        scope = group.get("target_scope")
        products = group.get("products") or []
        lifecycle_targets = group.get("lifecycle_targets") or []
        announcement = group.get("announcement")
        if (scope not in ALLOWED_SCOPES or not isinstance(products, list)
                or not isinstance(lifecycle_targets, list) or not isinstance(announcement, dict)):
            continue
        target_count = len(products) + len(lifecycle_targets)
        if group.get("expected_target_count") != target_count or target_count <= 0:
            continue
        url = str(announcement.get("url") or "").strip()
        maker = str(announcement.get("maker") or "").strip()
        if not url or not maker:
            continue

        for product_name in products:
            candidates = [
                row for row in by_name.get(product_name, [])
                if maker_is_listed_in_row(maker, row)
            ]
            if len(candidates) != 1:
                continue
            yj_code = (candidates[0].get("YJコード") or "").strip()
            if yj_code:
                result[(yj_code, url)] = {
                    "scope": scope,
                    "source": "manual_group",
                    "group_index": str(index),
                }

        for target in lifecycle_targets:
            if not isinstance(target, dict):
                continue
            yj_code = str(target.get("yj_code") or "").strip()
            row = by_yj.get(yj_code)
            if (row is None or row.get("商品名") != target.get("product_name")
                    or not maker_is_listed_in_row(maker, row)):
                continue
            result[(yj_code, url)] = {
                "scope": scope,
                "source": "manual_group",
                "group_index": str(index),
            }
    return result
