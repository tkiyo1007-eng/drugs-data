#!/usr/bin/env python3
"""定刻・手動公開のcore境界を、元データを変えずに再検査する。"""
from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path

from reconcile_optional_data import validate_retained_bundle
from validate_maker_announcements import validate_manual_groups

# 新CSVから消えた手動対象を含む登録元はcore公開を止めないという既存境界。
# 通常CIと任意メーカー更新では、このデータレベルの厳格検査も従来どおり実施する。
OPTIONAL_REGISTRY_TEST = (
    "test_verified_targets.VerifiedTargetRegistryTests."
    "test_every_declared_manual_target_resolves_to_a_unique_yj_and_url"
)


def core_regression_suite(suite: unittest.TestSuite) -> unittest.TestSuite:
    selected = unittest.TestSuite()
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            selected.addTests(core_regression_suite(test))
        elif test.id() != OPTIONAL_REGISTRY_TEST:
            selected.addTest(test)
    return selected


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("."))
    parser.add_argument("--min-count", type=int, default=300)
    parser.add_argument("--run-regressions", action="store_true")
    args = parser.parse_args()
    if args.run_regressions:
        # python -m unittestと同じく、既存のscripts.*形式のimportも解決する。
        sys.path.insert(0, str(args.base.resolve()))
        suite = unittest.defaultTestLoader.discover(str(args.base / "scripts"), pattern="test_*.py")
        selected = core_regression_suite(suite)
        if suite.countTestCases() - selected.countTestCases() != 1:
            raise SystemExit("core境界へ委ねる検査の対象が変わりました。検査範囲を再確認してください")
        print("core境界では削除済み手動登録の完全一致検査1件のみを任意更新へ委ねます", flush=True)
        return 0 if unittest.TextTestRunner().run(selected).wasSuccessful() else 1
    try:
        errors = validate_retained_bundle(args.base, min_count=args.min_count)
        # 登録元は削除済み対象だけを許容する。URL、構造、重複、現在も存在する
        # 品目とのメーカー・名称一致など、他の不正を免除しない。
        errors.extend(validate_manual_groups(str(args.base / "drugs_app_ready.csv"),
                                             str(args.base / "manual_announcement_groups.json"),
                                             allow_removed_targets=True))
    except (OSError, ValueError, TypeError, AttributeError) as error:
        errors = [str(error)]
    if errors:
        raise SystemExit("\n".join(errors))
    print("OK: 新CSVへ整合済みの保持メーカー4 JSON・lifecycleを読取検証しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
