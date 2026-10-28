"""One reviewed manufacturer notice per day; no medical inference or backlog."""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path

SITE = 'https://kyokyu-navi.jp/'

def build(base, log, today, finalize):
    skip = lambda reason: {'action': 'skip', 'kind': 'manufacturer', 'reason': reason}
    try:
        policy = json.loads((base / 'manufacturer_posting_policy.json').read_text())
        notices = json.loads((base / 'manufacturer_notices.json').read_text())['notices']
        bulletins = json.loads((base / 'manufacturer_bulletins.json').read_text())
    except (OSError, ValueError, KeyError): return skip('メーカー速報の検証済みデータを取得できません')
    if policy.get('enabled') is not True: return skip('メーカー速報配信は無効です')
    if (type(policy.get('max_posts_per_day')) is not int or policy['max_posts_per_day'] != 1
            or type(policy.get('max_attempts_per_month')) is not int or policy['max_attempts_per_month'] != 31
            or policy.get('estimated_usd_per_post_with_url') != '0.20'
            or policy.get('estimated_monthly_cap_usd') != '6.20'): return skip('承認した配信上限と一致しません')
    history = [p for p in log['posted'] if p.get('kind') == 'manufacturer']
    month = today.strftime('%Y-%m')
    if any(p.get('post_day') == today.isoformat() for p in history): return skip('本日のメーカー速報は投稿済み、または結果確認待ちです')
    if sum(str(p.get('post_day', '')).startswith(month) for p in history) >= 31: return skip('月31件の追加費用上限に到達しています')
    if any(p.get('state') == 'pending' for p in history): return skip('前回の投稿結果が未確定のため自動再投稿しません')
    try:
        checked = dt.datetime.fromisoformat(bulletins['checked_at']).astimezone(dt.timezone(dt.timedelta(hours=9))).date()
    except (KeyError, ValueError, TypeError): return skip('速報の収集試行日が不正です')
    if checked != today: return skip('当日の原典確認を取得できません')
    already = {p.get('document_key') for p in history}
    priority = {'recall': 0, 'stopped': 1, 'limited': 2, 'resumption_planned': 3, 'resumed': 4, 'discontinued': 5}
    for n in sorted(notices, key=lambda n: (priority.get(n.get('event_type'), 9), str(n.get('id')))):
        if 'collection_mode' in n: continue  # manualおよび未知modeは自動投稿対象外。
        if any(t.get('archived_from_csv_at') for t in n['targets']): continue
        try: listed = dt.date.fromisoformat(n['listed_at'])
        except (KeyError, ValueError): continue
        if not 0 <= (today - listed).days <= 3: continue
        key = n['id'] + ':' + n['sha256']
        if key in already: continue
        item = next((i for i in bulletins['items'] if i.get('url') == n['url']
                     and i.get('sha256') == n['sha256'] and i.get('review_status') == 'confirmed'
                     and i.get('document_checked_at', i.get('last_seen', ''))[:10] == today.isoformat()), None)
        if item is None: continue
        text = n.get('x_text')
        if not text: continue
        page_url = SITE + 'items/' + n['targets'][0]['yj_code'] + '.html'
        text += '\nサイトの補足▶ ' + page_url
        return finalize({'kind': 'manufacturer', 'key': 'manufacturer:' + today.isoformat() + ':' + n['id'],
                         'post_day': today.isoformat(), 'document_key': key, 'notice_id': n['id'],
                         'source_url': n['url'], 'source_sha256': n['sha256'],
                         'url': page_url, 'text': text})
    return skip('当日確認済み・未配信・直近掲載のメーカー案内はありません')

def verify_published(item, fetch=None):
    def download(url):
        request = urllib.request.Request(url, headers={'User-Agent': 'DrugSupplyNavi-source-verification/1.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(10 * 1024 * 1024 + 1)
        if len(body) > 10 * 1024 * 1024: raise ValueError('source is too large')
        return body
    fetch = fetch or download
    manifest_url = SITE + 'public-data-manifest.json'
    before = fetch(manifest_url)
    manifest = json.loads(before)
    for name in ['manufacturer_notices.json', 'manufacturer_bulletins.json']:
        body = Path(name).read_bytes()
        entry = manifest['files'][name]
        if hashlib.sha256(body).hexdigest() != entry['sha256'] or len(body) != entry['bytes']:
            raise ValueError('公開artifactと投稿計画のメーカー情報が一致しません')
    page = fetch(item['url'])
    if item['source_sha256'].encode() not in page: raise ValueError('公開品目ページに今回の原典確認情報がありません')
    source = fetch(item['source_url'])
    if hashlib.sha256(source).hexdigest() != item['source_sha256']: raise ValueError('原典が変更されたため再確認が必要です')
    if fetch(manifest_url) != before: raise ValueError('検査中に公開artifactが切り替わりました')

def reserve_remote(log_path):
    """No POST until a durable pending record exists on main."""
    if os.environ.get('GITHUB_ACTIONS') != 'true' or log_path.resolve() != Path('x_post_log.json').resolve():
        raise RuntimeError('実投稿の予約保存は承認済みGitHub Actions内だけで実行します')
    def git(*args):
        return subprocess.run(['git', *args], capture_output=True, check=True, text=True).stdout.strip()
    if git('branch', '--show-current') != 'main': raise RuntimeError('投稿予約はmain以外へ保存しません')
    git('config', 'user.name', 'github-actions[bot]')
    git('config', 'user.email', 'github-actions[bot]@users.noreply.github.com')
    git('add', '--', 'x_post_log.json')
    git('commit', '-m', 'メーカー速報の送信予約（結果未確認時の再送を防止）')
    git('pull', '--rebase', 'origin', 'main')
    git('push', 'origin', 'HEAD:main')
