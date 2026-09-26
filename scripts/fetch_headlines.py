#!/usr/bin/env python3
"""薬事日報の公式RSSから見出し・日付・原URLのみ取得（本文・画像は保存しない）。"""
import argparse
import datetime as dt
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED = 'https://www.yakuji.co.jp/feed'
SOURCE = 'https://www.yakuji.co.jp/'
JST = dt.timezone(dt.timedelta(hours=9))
MAX_BYTES = 2_000_000


def parse_feed(body):
    if len(body) > MAX_BYTES or b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():
        raise ValueError('unsupported feed')
    root = ET.fromstring(body)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('invalid RSS')
    items, seen = [], set()
    for entry in root.findall('./channel/item'):
        if 'HEADLINE NEWS' not in [c.text for c in entry.findall('category')]:
            continue
        title = (entry.findtext('title') or '').strip()
        url = (entry.findtext('link') or '').strip()
        if not title or len(title) > 500 or not re.fullmatch(r'https://www\.yakuji\.co\.jp/entry\d+\.html', url):
            raise ValueError('invalid headline')
        published = parsedate_to_datetime(entry.findtext('pubDate') or '')
        if published.tzinfo is None:
            raise ValueError('missing timezone')
        if url in seen:
            continue
        seen.add(url)
        items.append(dict(title=title, url=url, date=published.astimezone(JST).strftime('%Y-%m-%d'), tag='業界ニュース'))
    return sorted(items, key=lambda x: (x['date'], x['url']), reverse=True)[:20]


def collect(path, fetch, now):
    checked = now.astimezone(JST).isoformat(timespec='seconds')
    try:
        previous = json.loads(path.read_text(encoding='utf-8')) if path.exists() else None
    except (OSError, json.JSONDecodeError):
        previous = None
    try:
        items = parse_feed(fetch())
        result = dict(schema_version=1, source_name='薬事日報', source_url=SOURCE,
                      status='ok', checked_at=checked, last_success_at=checked, items=items)
    except Exception:
        result = dict(schema_version=1, source_name='薬事日報', source_url=SOURCE,
                      status='failed', checked_at=checked,
                      last_success_at=previous.get('last_success_at') if previous else None,
                      items=previous.get('items', []) if previous else [])
    temporary = path.with_suffix('.next.json')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return result


def fetch():
    req = urllib.request.Request(FEED, headers={'User-Agent': 'DrugSupplyNavi/1.0 (+https://kyokyu-navi.jp/)'})
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.geturl() != FEED:
            raise ValueError('unexpected redirect')
        return response.read(MAX_BYTES + 1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', nargs='?', default='industry_headlines.json')
    args = parser.parse_args()
    result = collect(Path(args.output), fetch, dt.datetime.now(JST))
    print(f"見出し取得: {result['status']} / {len(result['items'])}件（記事本文は取得対象外）")
