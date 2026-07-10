#!/usr/bin/env python3
"""供給状況の「実際の変化」ログ status_changes.json を管理する。

厚労省Excelの更新日(⑳)は新発売収載でも動き、状況更新日(⑬)も
新発売時の初回登録で動くため、「最近ステータスが変わった品目」の
抽出には使えない。代わりに、このリポジトリに毎日コミットされる
CSVスナップショット同士の差分から本物の変化だけを記録する。

- backfill: git履歴のdrugs_app_ready.csvを時系列に辿り、ログを再構築
    python3 scripts/build_status_changes.py backfill
- diff: 2つのCSVを比較して変化をログに追記（日次ワークフロー用）
    python3 scripts/build_status_changes.py diff prev.csv new.csv [日付YYYY/MM/DD]

出力: status_changes.json = [{date, yj, name, from, to}, ...] 新しい順、直近90日分。
新規収載（前回スナップショットに存在しない品目）は変化として記録しない。
"""
import csv
import datetime
import io
import json
import subprocess
import sys

LOG_FILE = "status_changes.json"
KEEP_DAYS = 90


def read_status_map(text):
    """CSVテキスト → {(yj, name): 供給状況}"""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    m = {}
    for r in reader:
        yj = (r.get("YJコード") or "").strip()
        name = (r.get("商品名") or "").strip()
        if name:
            m[(yj, name)] = (r.get("供給状況") or "").strip()
    return m


def diff_maps(prev, new, date_str):
    changes = []
    for key, new_st in new.items():
        old_st = prev.get(key)
        if old_st is None:
            continue  # 新規収載は「変化」ではない
        if old_st and new_st and old_st != new_st:
            yj, name = key
            changes.append({"date": date_str, "yj": yj, "name": name, "from": old_st, "to": new_st})
    return changes


def load_log():
    try:
        return json.load(open(LOG_FILE, encoding="utf-8"))
    except FileNotFoundError:
        return []


def save_log(entries):
    # 同一(日付,YJ,商品名)は1件に。新しい順に整列し、直近KEEP_DAYS日だけ保持
    seen = set()
    uniq = []
    for e in sorted(entries, key=lambda e: e["date"], reverse=True):
        k = (e["date"], e["yj"], e["name"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(e)
    cutoff = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).strftime("%Y/%m/%d")
    uniq = [e for e in uniq if e["date"] >= cutoff]
    json.dump(uniq, open(LOG_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"status_changes.json: {len(uniq)}件", file=sys.stderr)


def git_show(commit, path="drugs_app_ready.csv"):
    out = subprocess.run(["git", "show", f"{commit}:{path}"], capture_output=True)
    return out.stdout.decode("utf-8", errors="replace") if out.returncode == 0 else None


def backfill():
    # CSVを変更したコミットを古い順に取得（コミット日時はJSTに変換）
    log = subprocess.run(
        ["git", "log", "--reverse", "--format=%H %ad", "--date=format-local:%Y/%m/%d",
         "--", "drugs_app_ready.csv"],
        capture_output=True, text=True, env={"TZ": "Asia/Tokyo", "PATH": "/usr/bin:/bin"})
    commits = [line.split() for line in log.stdout.strip().split("\n") if line]
    print(f"CSV変更コミット: {len(commits)}件", file=sys.stderr)

    entries = []
    prev_map = None
    for commit, date_str in commits:
        text = git_show(commit)
        if not text:
            continue
        cur = read_status_map(text)
        if len(cur) < 10000:  # 壊れたスナップショットはスキップ
            continue
        if prev_map is not None:
            entries.extend(diff_maps(prev_map, cur, date_str))
        prev_map = cur
    save_log(entries)


def daily_diff(prev_path, new_path, date_str=None):
    date_str = date_str or datetime.date.today().strftime("%Y/%m/%d")
    prev = read_status_map(open(prev_path, encoding="utf-8").read())
    new = read_status_map(open(new_path, encoding="utf-8").read())
    changes = diff_maps(prev, new, date_str)
    print(f"本日の状況変化: {len(changes)}件", file=sys.stderr)
    save_log(load_log() + changes)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "backfill"
    if mode == "backfill":
        backfill()
    elif mode == "diff":
        daily_diff(sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
    else:
        sys.exit(f"unknown mode: {mode}")
