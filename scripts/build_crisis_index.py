#!/usr/bin/env python3
"""医薬品供給状況の「供給危機指数」を算出し、crisis_index.json を生成する。

厚労省データの「限定出荷」「供給停止」の全品目に占める割合を重み付け集計した
独自の日次指数（0〜100）。花粉指数のように毎日チェックする定点観測の指標として、
Web版のヒーローカードに表示するために使う。

算出式: min(100, round((限定出荷件数×0.5 + 供給停止件数×1.0) / 総品目数 × 1000))
  - 供給停止は限定出荷より深刻なため重みを2倍にしている
  - ×1000のスケーリングは現状のデータ規模（全体の1割強が調整対象）で
    0〜100の指数として読みやすい値になるよう調整したもの

出力: crisis_index.json = {
  date, score, level, delta,
  limited, stopped, total,
  history: [{date, score}, ...]  最大30日分
}
"""
import csv
import datetime
import json
import sys

CSV_FILE = "drugs_app_ready.csv"
OUT_FILE = "crisis_index.json"
HISTORY_KEEP = 30

LEVELS = [
    (25, "平常"),
    (45, "やや注意"),
    (65, "注意"),
    (85, "警戒"),
    (101, "厳重警戒"),
]


def level_for(score):
    for threshold, label in LEVELS:
        if score < threshold:
            return label
    return "厳重警戒"


def build():
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    total = len(rows)
    if total < 10000:
        print(f"❌ 品目数が少なすぎます({total}件)。異常データの可能性があるため中断", file=sys.stderr)
        return
    limited = sum(1 for r in rows if "限定" in (r.get("供給状況") or ""))
    stopped = sum(1 for r in rows if "停止" in (r.get("供給状況") or ""))
    score = min(100, round((limited * 0.5 + stopped * 1.0) / total * 1000))

    today = datetime.date.today().strftime("%Y/%m/%d")
    try:
        prev = json.load(open(OUT_FILE, encoding="utf-8"))
        history = prev.get("history", [])
        prev_score = prev.get("score") if prev.get("date") != today else None
    except FileNotFoundError:
        history = []
        prev_score = None

    history = [h for h in history if h.get("date") != today]
    history.append({"date": today, "score": score})
    history = history[-HISTORY_KEEP:]

    delta = (score - prev_score) if prev_score is not None else None

    out = {
        "date": today,
        "score": score,
        "level": level_for(score),
        "delta": delta,
        "limited": limited,
        "stopped": stopped,
        "total": total,
        "history": history,
    }
    json.dump(out, open(OUT_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"crisis_index.json: score={score} level={out['level']} delta={delta}", file=sys.stderr)


if __name__ == "__main__":
    build()
