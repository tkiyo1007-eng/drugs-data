#!/usr/bin/env python3
"""Refresh optional manufacturer data without making the MHLW update fragile.

The manufacturer collectors depend on external sites whose HTML and availability
can change independently of the Ministry of Health, Labour and Welfare (MHLW)
spreadsheet.  This wrapper builds and validates all collector-owned JSON files in
a temporary directory.  They replace the last known-good files only as one
validated set.  When an optional refresh fails, callers may explicitly keep the
previous set and continue publishing the already-validated MHLW core CSV.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Optional, Sequence

from jst_time import jst_today


MANAGED_FILES = (
    "maker_announcements.json",
    "maker_announcement_events.json",
    "maker_collection_health.json",
    "unmatched_maker_announcements.json",
)

Runner = Callable[..., subprocess.CompletedProcess]


def _run(command: Sequence[str], base: Path, runner: Runner) -> int:
    result = runner(list(command), cwd=str(base))
    return int(result.returncode)


def _last_known_good_available(base: Path) -> bool:
    return all((base / name).is_file() for name in MANAGED_FILES)


def publish_validated_files(
    stage: Path, base: Path, names: Sequence[str] = MANAGED_FILES,
) -> None:
    """Prepare every replacement before atomically replacing individual files."""
    prepared: list[tuple[Path, Path]] = []
    backups: dict[Path, Optional[bytes]] = {}
    replaced: list[Path] = []
    try:
        for name in names:
            source = stage / name
            # Validation already parsed these files.  Parse once more here so a
            # missing/truncated output can never replace the last known-good set.
            with source.open(encoding="utf-8") as handle:
                json.load(handle)
            pending = base / f".{name}.next"
            shutil.copy2(source, pending)
            destination = base / name
            prepared.append((pending, destination))
            backups[destination] = destination.read_bytes() if destination.exists() else None
        try:
            for pending, destination in prepared:
                os.replace(pending, destination)
                replaced.append(destination)
        except OSError as publish_error:
            rollback_errors = []
            for destination in reversed(replaced):
                try:
                    previous = backups[destination]
                    if previous is None:
                        destination.unlink(missing_ok=True)
                    else:
                        rollback = base / f".{destination.name}.rollback"
                        rollback.write_bytes(previous)
                        os.replace(rollback, destination)
                except OSError as rollback_error:
                    rollback_errors.append(f"{destination.name}: {rollback_error}")
            if rollback_errors:
                raise RuntimeError(
                    "補足情報の置換とロールバックの一部に失敗しました: "
                    + " / ".join(rollback_errors)
                ) from publish_error
            raise
    finally:
        for pending, _ in prepared:
            pending.unlink(missing_ok=True)
        for _, destination in prepared:
            (base / f".{destination.name}.rollback").unlink(missing_ok=True)


def _write_github_output(updated: bool) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(f"updated={'true' if updated else 'false'}\n")


def refresh(
    base: Path,
    *,
    expected_checked: str,
    min_count: int = 300,
    pages: int = 2,
    deepen_limit: int = 60,
    python_executable: str = sys.executable,
    runner: Runner = subprocess.run,
) -> bool:
    """Return True on refresh; False when the previous complete set is retained.

    A failed refresh is only recoverable when every managed file existed before
    the attempt.  An initial setup or an incomplete previous set fails closed.
    """
    base = base.resolve()
    fallback_available = _last_known_good_available(base)

    with tempfile.TemporaryDirectory(prefix="maker-enrichment-") as directory:
        stage = Path(directory)
        for name in MANAGED_FILES:
            source = base / name
            if source.is_file():
                shutil.copy2(source, stage / name)

        fetch_command = (
            python_executable,
            str(base / "scripts" / "fetch_maker_announcements.py"),
            str(base / "drugs_app_ready.csv"),
            str(stage / "maker_announcements.json"),
            str(pages),
            str(deepen_limit),
        )
        if _run(fetch_command, base, runner) != 0:
            if fallback_available:
                return False
            raise RuntimeError("メーカー案内の取得に失敗し、前回の完全なデータ一式もありません")

        validate_command = (
            python_executable,
            str(base / "scripts" / "validate_maker_announcements.py"),
            "--csv", str(base / "drugs_app_ready.csv"),
            "--announcements", str(stage / "maker_announcements.json"),
            "--events", str(stage / "maker_announcement_events.json"),
            "--unmatched", str(stage / "unmatched_maker_announcements.json"),
            "--health", str(stage / "maker_collection_health.json"),
            "--manual-groups", str(base / "manual_announcement_groups.json"),
            "--min-count", str(min_count),
            "--expected-checked", expected_checked,
        )
        if _run(validate_command, base, runner) != 0:
            if fallback_available:
                return False
            raise RuntimeError("メーカー案内の検証に失敗し、前回の完全なデータ一式もありません")

        publish_validated_files(stage, base)
        return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=Path("."))
    parser.add_argument("--expected-checked", default=jst_today().isoformat())
    parser.add_argument("--min-count", type=int, default=300)
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--deepen-limit", type=int, default=60)
    parser.add_argument(
        "--fallback-to-previous",
        action="store_true",
        help="取得・検証失敗時に前回の完全なメーカー情報を維持して成功終了する",
    )
    args = parser.parse_args()

    try:
        updated = refresh(
            args.base,
            expected_checked=args.expected_checked,
            min_count=args.min_count,
            pages=args.pages,
            deepen_limit=args.deepen_limit,
        )
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if updated:
        _write_github_output(True)
        print("✅ メーカー案内を検証済みデータ一式へ更新しました")
        return 0
    message = (
        "メーカー案内の取得または検証に失敗したため、前回の検証済みデータを維持します。"
        "厚労省の供給CSV更新は継続します"
    )
    if args.fallback_to_previous:
        _write_github_output(False)
        print(f"::warning title=メーカー補足情報は前回値を維持::{message}", file=sys.stderr)
        return 0
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
