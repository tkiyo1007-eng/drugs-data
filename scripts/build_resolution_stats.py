#!/usr/bin/env python3
"""status_changes.json（毎日の状況変化ログ）から、限定出荷・供給停止になってから
通常出荷に解除されるまでの日数を集計し、resolution_stats.json を生成する。

厚労省データにも他の供給情報サイトにも無い統計で、Web版・アプリ版の詳細画面に
「同じ状況の品目は平均◯日で解除されています」の目安として表示するために使う。
サンプル数がまだ少ないため、参考値であることが伝わるよう件数も一緒に出力する。

出力: resolution_stats.json = {
  "limited": {"count": N, "medianDays": M, "avgDays": A},
  "stopped": {"count": N, "medianDays": M, "avgDays": A},
  "updatedAt": "YYYY/MM/DD"
}
"""
import datetime
import json
import statistics
import sys

from jst_time import jst_today

LOG_FILE = "status_changes.json"
OUT_FILE = "resolution_stats.json"


def map_status(s):
    if "停止" in s:
        return "stopped"
    if "限定" in s:
        return "limited"
    if "中止" in s:
        return "ended"
    return "ok"


def build():
    try:
        data = json.load(open(LOG_FILE, encoding="utf-8"))
    except FileNotFoundError:
        print("status_changes.json が見つかりません", file=sys.stderr)
        return

    by_yj = {}
    for e in data:
        by_yj.setdefault(e["yj"], []).append(e)

    durations = {"limited": [], "stopped": []}
    for evs in by_yj.values():
        evs.sort(key=lambda e: e["date"])
        for i in range(len(evs) - 1):
            a, b = evs[i], evs[i + 1]
            to_a, to_b = map_status(a["to"]), map_status(b["to"])
            if to_a not in ("limited", "stopped") or to_b != "ok":
                continue
            d1 = datetime.date(*map(int, a["date"].split("/")))
            d2 = datetime.date(*map(int, b["date"].split("/")))
            days = (d2 - d1).days
            if 0 < days <= 365:  # 異常値（ログ欠損等での誤ペア化）を除外
                durations[to_a].append(days)

    out = {"updatedAt": jst_today().strftime("%Y/%m/%d")}
    for key, vals in durations.items():
        if len(vals) < 5:  # サンプルが少なすぎる区分は出力しない（誤った印象を避ける）
            continue
        out[key] = {
            "count": len(vals),
            "medianDays": round(statistics.median(vals)),
            "avgDays": round(statistics.mean(vals), 1),
        }

    json.dump(out, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"resolution_stats.json: {out}", file=sys.stderr)


if __name__ == "__main__":
    build()
