#!/usr/bin/env python3
"""公開中のWeb（index.html）のCSV読込検証で、候補の供給CSVを読めるか検査する。

2026年9月16〜19日、データ側で許可した値（出荷量の原典記載なし「－」）をWebの
ブラウザ検証が拒否し、利用者の検索が約3日半停止した。Python側の品質検査だけでは
クライアントとの契約ずれを検出できないため、公開済みWebの判定そのものをNodeで実行する。

index.html から次を抜き出して実行する（Web側の実装を複製しない）:
- mapPublishedStatus（供給区分の対応表）
- parseCSV 〜 validateSupplyCSVRows（公開CSV契約）
抜き出せない・Nodeがない場合は通過させず失敗にする。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STATUS_START = "function mapPublishedStatus("
STATUS_END = "function mapStatus("
CONTRACT_START = "function parseCSV("
CONTRACT_END = "// ===== End public CSV contract ====="

# Webの loadRealData と同じ順序・条件で判定する。
HARNESS = r"""
const fs = require("fs");
const text = fs.readFileSync(process.env.DSN_CSV_PATH, "utf8");
const result = {error: null, rows: 0};
try {
  const rows = parseCSV(text.replace(/^﻿/, ""), true).filter(row => !(row.length === 1 && row[0] === ""));
  const head = rows.shift();
  if (!Array.isArray(head)) throw new Error("列構成を確認できません");
  const error = validateSupplyCSVRows(head, rows);
  if (error) throw new Error(error);
  const iName = head.indexOf("商品名"), iSt = head.indexOf("供給状況");
  if (iName < 0 || iSt < 0) throw new Error("必須列を確認できません");
  rows.forEach((row, index) => {
    if (!(row[iName] || "").trim()) throw new Error(`${index + 2}行目: 商品名が空のためWebの品目数検査に失敗します`);
    if (!mapPublishedStatus(row[iSt])) throw new Error(`${index + 2}行目: Webが未対応の供給区分「${row[iSt]}」`);
  });
  result.rows = rows.length;
} catch (e) {
  result.error = String(e && e.message || e);
}
console.log(JSON.stringify(result));
"""


def extract(html: str, start: str, end: str) -> str:
    begin = html.find(start)
    stop = html.find(end, begin + 1) if begin >= 0 else -1
    if begin < 0 or stop < 0:
        raise ValueError(f"index.htmlから `{start.strip()}` 〜 `{end.strip()}` を抜き出せません。"
                         "Web側の構成変更に合わせてこの検査を更新してください")
    return html[begin:stop]


def build_script(html: str) -> str:
    return "\n".join((
        extract(html, STATUS_START, STATUS_END),
        extract(html, CONTRACT_START, CONTRACT_END),
        HARNESS,
    ))


def check(html_path: Path, csv_path: Path, node: str | None = None) -> tuple[str | None, int]:
    node = node or shutil.which("node")
    if not node:
        return "Node.jsが見つからないため、Webの読込検査を実行できません", 0
    script = build_script(html_path.read_text(encoding="utf-8"))
    completed = subprocess.run(
        [node, "-e", script],
        capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "DSN_CSV_PATH": str(csv_path)},
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or not lines:
        return f"Webの読込検査を実行できません: {completed.stderr.strip()[:500]}", 0
    result = json.loads(lines[-1])
    return result.get("error"), int(result.get("rows") or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--html", type=Path, default=Path("index.html"))
    parser.add_argument("--csv", type=Path, default=Path("drugs_app_ready.csv"))
    args = parser.parse_args(argv)
    try:
        error, rows = check(args.html, args.csv)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        error, rows = str(exc), 0
    if error:
        print(f"❌ 公開中のWebはこのCSVを読み込めません: {error}", file=sys.stderr)
        print("   データ側の形式変更は、Web側の対応を公開してから反映してください。", file=sys.stderr)
        return 1
    print(f"✅ 公開中のWebの読込検証に合格: {rows:,}品目")
    return 0


if __name__ == "__main__":
    sys.exit(main())
