#!/usr/bin/env python3
"""供給状況の変更をXへ1日1回投稿する（日別ページへの案内のみ）。

- 投稿するのは status_changes.json に変更記録がある日だけ。記録がない日・取得に
  失敗した日は投稿しない（「変更なし」「供給問題なし」と誤認させないため）。
- 件数は厚労省公表データ上の区分変更の集計で、代替薬の推奨や在庫の断定は書かない。
- 同じ日付は二度投稿しない（x_post_log.json）。初回有効化時に過去分をまとめて
  流さないよう、実行日から MAX_AGE_DAYS を超える変更日は投稿しない。
- 認証情報は環境変数（GitHub Secrets）からだけ読み、ログや出力に書かない。

使い方:
  python3 scripts/x_daily_post.py build --out /tmp/x_post.json   # 文面を作るだけ
  python3 scripts/x_daily_post.py post --plan /tmp/x_post.json    # 投稿して記録
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from jst_time import jst_today

SITE_URL = "https://tkiyo1007-eng.github.io/drugs-data/"
LOG_PATH = Path("x_post_log.json")
MAX_AGE_DAYS = 3
MAX_WEIGHTED_LENGTH = 280
X_URL_LENGTH = 23  # t.co短縮後の長さ
POST_ENDPOINT = "https://api.x.com/2/tweets"
CREDENTIAL_ENV = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
HASHTAGS = "#医薬品供給 #限定出荷"
URL_PATTERN = re.compile(r"https?://\S+")


def category(status: str) -> str | None:
    if "通常出荷" in status:
        return "ok"
    if "供給停止" in status:
        return "stopped"
    if "限定出荷" in status:
        return "limited"
    return None


def _weigh(text: str) -> int:
    total = 0
    for char in text:
        code = ord(char)
        light = code <= 4351 or 8192 <= code <= 8205 or 8208 <= code <= 8223 or 8242 <= code <= 8247
        total += 1 if light else 2
    return total


def weighted_length(text: str) -> int:
    """Xの文字数計算（twitter-text v3）。URLは23文字、CJK等は2文字として数える。"""
    total, position = 0, 0
    for match in URL_PATTERN.finditer(text):
        total += _weigh(text[position:match.start()]) + X_URL_LENGTH
        position = match.end()
    return total + _weigh(text[position:])


def load_log(path: Path | None = None) -> dict:
    path = path or LOG_PATH
    if not path.exists():
        return {"posted": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("posted"), list):
        raise ValueError(f"{path}: 形式が不正です")
    return data


def build_plan(changes: list, log: dict, today: dt.date) -> dict:
    if not isinstance(changes, list) or not changes:
        return {"action": "skip", "reason": "変更履歴が空、または取得できません"}
    dates = sorted({entry.get("date") for entry in changes if isinstance(entry, dict)
                    and isinstance(entry.get("date"), str)}, reverse=True)
    if not dates:
        return {"action": "skip", "reason": "変更履歴に日付がありません"}
    latest = dates[0]
    try:
        latest_date = dt.datetime.strptime(latest, "%Y/%m/%d").date()
    except ValueError:
        return {"action": "skip", "reason": f"変更日の形式が不正です: {latest}"}
    if latest_date > today:
        return {"action": "skip", "reason": f"変更日 {latest} が実行日より未来です"}
    if (today - latest_date).days > MAX_AGE_DAYS:
        return {"action": "skip", "reason": f"最新の変更日 {latest} が{MAX_AGE_DAYS}日より前です"}
    if latest in {item.get("date") for item in log["posted"] if isinstance(item, dict)}:
        return {"action": "skip", "reason": f"{latest} は投稿済みです"}

    entries = [entry for entry in changes if entry.get("date") == latest]
    counts = Counter()
    for entry in entries:
        before, after = category(str(entry.get("from", ""))), category(str(entry.get("to", "")))
        if before is None or after is None:
            return {"action": "skip", "reason": f"未対応の供給区分を含むため投稿しません: {entry.get('yj')}"}
        if after == "limited" and before != "limited":
            counts["limited"] += 1
        elif after == "stopped" and before != "stopped":
            counts["stopped"] += 1
        elif after == "ok":
            counts["ok"] += 1
        else:
            counts["other"] += 1

    iso = latest_date.isoformat()
    url = f"{SITE_URL}updates/{iso}.html"
    lines = [f"【医薬品の供給状況の変更】{latest_date.month}月{latest_date.day}日の更新分（厚労省公表データ）",
             f"変更があった医薬品：{len(entries)}品目"]
    for key, label in (("limited", "限定出荷へ"), ("stopped", "供給停止へ"),
                       ("ok", "通常出荷へ"), ("other", "その他の区分変更")):
        if counts[key]:
            lines.append(f"・{label}：{counts[key]}品目")
    lines += ["品目の一覧▶ " + url, HASHTAGS]
    text = "\n".join(lines)
    length = weighted_length(text)
    if length > MAX_WEIGHTED_LENGTH:
        return {"action": "skip", "reason": f"文字数が上限を超えます（{length}）"}
    return {"action": "post", "date": latest, "url": url, "text": text, "weighted_length": length}


def oauth1_header(method: str, url: str, credentials: dict) -> str:
    params = {
        "oauth_consumer_key": credentials["X_API_KEY"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": credentials["X_ACCESS_TOKEN"],
        "oauth_version": "1.0",
    }
    quote = lambda value: urllib.parse.quote(str(value), safe="~")
    base = "&".join((method.upper(), quote(url),
                     quote("&".join(f"{quote(k)}={quote(v)}" for k, v in sorted(params.items())))))
    key = f"{quote(credentials['X_API_SECRET'])}&{quote(credentials['X_ACCESS_TOKEN_SECRET'])}"
    params["oauth_signature"] = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{quote(k)}="{quote(v)}"' for k, v in sorted(params.items()))


def post_to_x(text: str, credentials: dict) -> str:
    body = json.dumps({"text": text}, ensure_ascii=False).encode()
    request = urllib.request.Request(POST_ENDPOINT, data=body, method="POST", headers={
        "Authorization": oauth1_header("POST", POST_ENDPOINT, credentials),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as error:
        detail = error.read()[:300].decode("utf-8", "replace")
        raise RuntimeError(f"Xへの投稿に失敗しました（HTTP {error.code}）: {detail}") from None
    post_id = (data.get("data") or {}).get("id")
    if not post_id:
        raise RuntimeError("Xの応答に投稿IDがありません")
    return str(post_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--changes", type=Path, default=Path("status_changes.json"))
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--today", type=dt.date.fromisoformat, default=None)
    post = sub.add_parser("post")
    post.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "build":
        changes = json.loads(args.changes.read_text(encoding="utf-8"))
        plan = build_plan(changes, load_log(), args.today or jst_today())
        args.out.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if plan.get("action") != "post":
        print(f"投稿しません: {plan.get('reason')}")
        return 0
    missing = [name for name in CREDENTIAL_ENV if not os.environ.get(name)]
    if missing:
        print(f"❌ 認証情報が未設定です: {', '.join(missing)}", file=sys.stderr)
        return 1
    log = load_log()
    if plan["date"] in {item.get("date") for item in log["posted"]}:
        print(f"{plan['date']} は投稿済みのため中止します")
        return 0
    post_id = post_to_x(plan["text"], {name: os.environ[name] for name in CREDENTIAL_ENV})
    log["posted"].insert(0, {"date": plan["date"], "post_id": post_id,
                             "posted_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
    log["posted"] = log["posted"][:120]
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✅ 投稿しました: {plan['date']}（ID {post_id}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
