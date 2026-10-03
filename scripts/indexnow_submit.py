#!/usr/bin/env python3
"""公開直後の新しい・更新されたページを IndexNow（Bing など）へ通知する。

2026-10 のアクセス解析では検索流入の約4割が Bing だった。sitemap の lastmod が
直近の日付（日本時間）のURLだけを送り、全件の再送は行わない。

IndexNow の鍵はプロトコル上公開するもの（サイト直下の <key>.txt に同じ値を置く）で、
秘密情報ではない。実送信は --submit を付けたときだけで、既定は送信内容の表示のみ。

usage:
  python3 scripts/indexnow_submit.py               # 試運転（送信しない）
  python3 scripts/indexnow_submit.py --submit      # 送信
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from jst_time import jst_today

SITE_HOST = "kyokyu-navi.jp"
SITE_ROOT = f"https://{SITE_HOST}/"
ENDPOINT = "https://api.indexnow.org/indexnow"
SITEMAPS = ("sitemap.xml", "sitemap-items.xml", "sitemap-updates.xml", "sitemap-curated.xml")
MAX_URLS = 10000  # IndexNow の1リクエスト上限
KEY_RE = re.compile(r"^[0-9a-f]{32}$")
URL_RE = re.compile(r"<url>\s*<loc>([^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", re.S)


def find_key(site: Path) -> str:
    """サイト直下の鍵ファイル（<32桁hex>.txt、中身も同じ値）を1つだけ見つける。"""
    keys = [p.stem for p in site.glob("*.txt") if KEY_RE.match(p.stem)
            and p.read_text(encoding="utf-8").strip() == p.stem]
    if len(keys) != 1:
        sys.exit(f"IndexNow の鍵ファイルが1つに定まりません: {keys}")
    return keys[0]


def recent_urls(site: Path, since: dt.date) -> list[str]:
    """sitemap の lastmod が since 以降のURLを、重複なく元の順で返す。"""
    urls: list[str] = []
    seen: set[str] = set()
    for name in SITEMAPS:
        path = site / name
        if not path.exists():
            continue
        for loc, lastmod in URL_RE.findall(path.read_text(encoding="utf-8")):
            loc = loc.strip()
            if not loc.startswith(SITE_ROOT) or loc in seen:
                continue
            try:
                modified = dt.date.fromisoformat((lastmod or "").strip()[:10])
            except ValueError:
                continue
            if modified >= since:
                seen.add(loc)
                urls.append(loc)
    return urls[:MAX_URLS]


def build_payload(key: str, urls: list[str]) -> dict:
    return {"host": SITE_HOST, "key": key, "keyLocation": f"{SITE_ROOT}{key}.txt", "urlList": urls}


def submit(payload: dict) -> int:
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, default=Path("."))
    parser.add_argument("--days", type=int, default=1, help="今日（日本時間）から何日前までの lastmod を送るか")
    parser.add_argument("--submit", action="store_true", help="実際に送信する（既定は試運転）")
    args = parser.parse_args()

    key = find_key(args.site)
    since = jst_today() - dt.timedelta(days=max(0, args.days))
    urls = recent_urls(args.site, since)
    print(f"対象: lastmod {since.isoformat()} 以降 {len(urls)}件")
    for url in urls[:20]:
        print(f"  {url}")
    if len(urls) > 20:
        print(f"  ...ほか{len(urls) - 20}件")
    if not urls:
        print("送信対象なし")
        return 0
    if not args.submit:
        print("試運転のため送信しません")
        return 0
    status = submit(build_payload(key, urls))
    # 200: 受理 / 202: 受理（鍵の確認待ち）。それ以外は失敗として扱う
    print(f"IndexNow 応答: HTTP {status}")
    return 0 if status in (200, 202) else 1


if __name__ == "__main__":
    raise SystemExit(main())
