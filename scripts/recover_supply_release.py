#!/usr/bin/env python3
"""厚労省原表・main・公開サイトを照合し、未反映の工程だけを再起動する。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass

from check_public_data_health import MHLW_SOURCE_NAME, PAGES_URL, fetch
from jst_time import jst_today
from mhlw_supply_source import MHLW_SUPPLY_PAGE, decode_supply_page, supply_source_from_page
from public_data_manifest import MANIFEST_NAME, fingerprint

INGEST = "update_drugs.yml"
PAGES = "deploy_pages.yml"
MAX_DISPATCHES = 2
QUALITY_CHECKS = {
    "公開前の供給CSV品質検査",
    "公開中のWebがCSVを読み込めるか検査（形式変更での検索停止を防ぐ）",
}


@dataclass(frozen=True)
class Source:
    date: dt.date
    sha256: str

    @classmethod
    def read(cls, metadata):
        date = dt.date.fromisoformat(metadata["excel_date"])
        digest = metadata["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("原表のSHA-256が不正です")
        return cls(date, digest)

    def __str__(self):
        return f"{self.date.isoformat()}:{self.sha256}"


def recovery_target(upstream, main, public):
    if upstream.date < main.date or public.date > main.date:
        raise ValueError("原表・main・公開サイトの日付が逆転しています。公開状況を確認してください。")
    if upstream != main:
        return INGEST
    if main != public:
        return PAGES
    return None


def gh_api(path, *arguments):
    command = ["gh", "api", f"repos/{{owner}}/{{repo}}/{path}", *arguments]
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, text=True, timeout=90).stdout


def list_runs(workflow, since):
    output = gh_api(f"actions/workflows/{workflow}/runs", "--paginate", "-X", "GET",
                    "-f", "branch=main", "-f", f"created=>={since.isoformat()}",
                    "-F", "per_page=100", "--jq", ".workflow_runs[]")
    return [json.loads(line) for line in output.splitlines()]


def failed_checks(run_id):
    output = gh_api(f"actions/runs/{run_id}/jobs", "--paginate",
                    "--jq", '.jobs[].steps[] | select(.conclusion == "failure") | .name')
    return [name for name in output.splitlines() if name in QUALITY_CHECKS]


def run_title(source):
    return f"供給更新の自動復旧 {source}"


def dispatch(workflow, source):
    gh_api(f"actions/workflows/{workflow}/dispatches", "-X", "POST",
           "-f", "ref=main", "-f", f"inputs[recovery_source]={source}")


def report(message):
    print(message, flush=True)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as stream:
            print(message, file=stream)


def recover(workflow, latest, committed):
    since = min(latest.date, jst_today()) - dt.timedelta(days=1)
    runs = list_runs(workflow, since)
    related_runs = runs + list_runs(INGEST, since) if workflow == PAGES else runs
    if active := next((run for run in related_runs if run["status"] != "completed"), None):
        report(f"取込または公開が実行中のため待機します（実行 {active['id']}）。")
        return
    version = latest if workflow == INGEST else committed
    attempts = [run for run in runs if run["display_title"] == run_title(version)]
    if workflow == INGEST:
        for attempt in attempts:
            if attempt["conclusion"] == "failure" and (checks := failed_checks(attempt["id"])):
                raise RuntimeError(f"実行 {attempt['id']} の品質検査で停止しました（{'、'.join(checks)}）。")
    if len(attempts) >= MAX_DISPATCHES:
        run_ids = "、".join(str(run["id"]) for run in attempts)
        raise RuntimeError(f"{workflow} の同一原表に対する自動再試行上限に達しました（実行 {run_ids}）。")
    dispatch(workflow, version)
    report(f"{workflow} の再試行を受付（{len(attempts) + 1}/{MAX_DISPATCHES}回目）。")


def check(dry_run):
    committed = Source.read(json.loads(gh_api(f"contents/{MHLW_SOURCE_NAME}?ref=main",
                                              "-H", "Accept: application/vnd.github.raw+json")))
    # 配信切替中に取得した新旧ファイルを混ぜて再公開しない。
    manifest = json.loads(fetch(PAGES_URL + MANIFEST_NAME, 1024 * 1024))
    public_body = fetch(PAGES_URL + MHLW_SOURCE_NAME, 1024 * 1024)
    if fingerprint(public_body) != manifest["files"][MHLW_SOURCE_NAME]:
        raise ValueError("公開サイトの配信整合性表と原表メタデータが一致しません。")
    public = Source.read(json.loads(public_body))
    page = decode_supply_page(fetch(MHLW_SUPPLY_PAGE, 5 * 1024 * 1024))
    metadata = supply_source_from_page(page, jst_today())
    metadata["sha256"] = hashlib.sha256(fetch(metadata["url"], 30 * 1024 * 1024)).hexdigest()
    latest = Source.read(metadata)
    for label, version in (("厚労省原表", latest), ("取込済み main", committed), ("公開サイト", public)):
        report(f"- {label} `{version}`")
    workflow = recovery_target(latest, committed, public)
    if workflow is None:
        report("厚労省原表と公開サイトが一致しています。")
    elif dry_run:
        report(f"再試行対象 `{workflow}`")
    else:
        recover(workflow, latest, committed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        check(args.dry_run)
    except (OSError, ValueError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        report(f"供給データ確認停止。{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
