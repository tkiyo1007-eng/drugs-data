"""Validate source-verified, package-scoped notices without changing MHLW data."""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse
from maker_identity import maker_is_listed_in_row

MAKER_HOSTS = {
    '扶桑薬品工業': 'www.fuso-pharm.co.jp',
    'ファイザー': 'www.pfizermedicalinformation.jp', 'サンド': 'sandoz-jp.cms.sandoz.com',
    '三和化学研究所': 'med.skk-net.com', '日本薬品工業': 'www.npi-inc.co.jp',
    '第一三共': 'www.medicalcommunity.jp', '東和薬品': 'med.towayakuhin.co.jp',
}
SCOPES = {'product', 'package', 'seller_route_and_package'}
KINDS = {'discontinued', 'limited', 'stopped', 'resumed', 'resumption_planned', 'recall'}
FORMAL_YJ = re.compile(r'[0-9][0-9A-Z]{11}\Z')
ARCHIVE_FIELD = 'archived_from_csv_at'

def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')).lower())

def valid_date(value, month=False):
    if not isinstance(value, str): return False
    try:
        if month and re.fullmatch(r'\d{4}-\d{2}', value):
            return dt.date.fromisoformat(value + '-01').strftime('%Y-%m') == value
        return dt.date.fromisoformat(value).isoformat() == value
    except ValueError: return False

def archived_identity(record, yj, label, errors):
    """欠落品目の履歴は正式YJ・名称・明示された削除確認日が必要。"""
    archived = record.get(ARCHIVE_FIELD)
    if ARCHIVE_FIELD not in record:
        return False
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    if (not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj)
            or not valid_date(archived) or archived > today):
        errors.append(label + ': invalid archived CSV date/identity')
        return False
    return True

def validate(document, rows):
    errors = []
    if not isinstance(document, dict) or type(document.get('schema_version')) is not int or document['schema_version'] != 1 or not isinstance(document.get('notices'), list):
        return ['manufacturer_notices: invalid schema']
    by_yj = {r['YJコード']: r for r in rows}
    ids = set()
    for n in document['notices']:
        if not isinstance(n, dict):
            errors.append('notice must be an object'); continue
        label = str(n.get('id', '?'))
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', label) or label in ids: errors.append(label + ': invalid/duplicate id')
        ids.add(label)
        for field in ['maker', 'title', 'reason']:
            if not isinstance(n.get(field), str) or not n[field].strip(): errors.append(label + ': missing ' + field)
        u = urlparse(str(n.get('url') or ''))
        if u.scheme != 'https' or u.hostname != MAKER_HOSTS.get(n.get('maker')) or u.username or u.password: errors.append(label + ': unofficial URL or wrong publisher')
        if not re.fullmatch(r'[a-f0-9]{64}', str(n.get('sha256') or '')): errors.append(label + ': invalid source hash')
        if not isinstance(n.get('event_type'), str) or n['event_type'] not in KINDS: errors.append(label + ': invalid event type')
        for field in ['announced_at', 'listed_at', 'verified_at']:
            if not valid_date(n.get(field), month=field == 'announced_at'): errors.append(label + ': invalid ' + field)
        if valid_date(n.get('verified_at')) and n['verified_at'] > dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat(): errors.append(label + ': future verification')
        targets = n.get('targets')
        if not isinstance(targets, list) or not targets:
            errors.append(label + ': missing targets'); continue
        seen = set()
        for t in targets:
            if not isinstance(t, dict): errors.append(label + ': invalid target'); continue
            yj = t.get('yj_code')
            if not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj):
                errors.append(label + ': invalid target YJ'); continue
            if not isinstance(t.get('product_name'), str) or not t['product_name'].strip():
                errors.append(label + ': invalid target name')
            if t.get('maker') is not None and (not isinstance(t['maker'], str) or not t['maker'].strip()):
                errors.append(label + ': invalid target maker')
            row = by_yj.get(yj)
            if yj in seen: errors.append(label + ': repeated target')
            seen.add(yj)
            archived = archived_identity(t, yj, label, errors)
            if row is None:
                if not archived: errors.append(label + ': target identity mismatch ' + yj)
            elif norm(t.get('product_name')) != norm(row['商品名']):
                errors.append(label + ': target identity mismatch ' + yj)
            if row and not maker_is_listed_in_row(t.get('maker') or n.get('maker'), row):
                errors.append(label + ': target maker mismatch ' + yj)
            if not isinstance(t.get('scope'), str) or t['scope'] not in SCOPES: errors.append(label + ': invalid target scope')
            packages = t.get('packages')
            if not isinstance(packages, list) or not packages or any(not isinstance(p, dict) or not isinstance(p.get('package'), str) or not p['package'].strip() for p in packages): errors.append(label + ': missing package scope')
            if t.get('scope') == 'seller_route_and_package' and not t.get('seller'): errors.append(label + ': missing sales route')
        alternatives = n.get('alternatives')
        if not isinstance(alternatives, list): errors.append(label + ': invalid alternatives'); continue
        for g in alternatives:
            if not isinstance(g, dict) or not isinstance(g.get('products'), list): errors.append(label + ': invalid candidate group'); continue
            selected = g.get('target_yj_codes') or []
            if not isinstance(selected, list) or any(not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj) for yj in selected):
                errors.append(label + ': invalid candidate group targets')
            elif not set(selected).issubset(seen):
                errors.append(label + ': candidate group outside targets')
            for p in g['products']:
                if not isinstance(p, dict) or not isinstance(p.get('name'), str) or not p['name'].strip(): errors.append(label + ': missing candidate name'); continue
                for field in ['maker', 'product_kind', 'source_class', 'manufacturer_candidate_scope', 'scope']:
                    if p.get(field) is not None and not isinstance(p[field], str):
                        errors.append(label + ': invalid candidate ' + field)
                yj = p.get('yj_code')
                if yj is not None and (not isinstance(yj, str) or not FORMAL_YJ.fullmatch(yj)):
                    errors.append(label + ': invalid candidate YJ'); continue
                archived = archived_identity(p, yj, label, errors)
                if yj:
                    row = by_yj.get(yj)
                    if row is None:
                        if not archived: errors.append(label + ': candidate identity mismatch ' + yj)
                    elif norm(p['name']) != norm(row['商品名']):
                        errors.append(label + ': candidate identity mismatch ' + yj)
                    if p.get('maker') is not None and (not isinstance(p['maker'], str) or not p['maker'].strip()
                            or (row and not maker_is_listed_in_row(p['maker'], row))):
                        errors.append(label + ': candidate maker mismatch ' + yj)
                if p.get('product_kind') == 'medical_device' and yj: errors.append(label + ': device cannot have medicine YJ')
            if not isinstance(g.get('cautions', []), list) or any(not isinstance(s, str) for s in g.get('cautions', [])): errors.append(label + ': invalid group cautions')
        if not isinstance(n.get('cautions'), list) or any(not isinstance(s, str) for s in n['cautions']): errors.append(label + ': invalid cautions')
    return errors

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', type=Path, default=Path('.'))
    args = p.parse_args()
    rows = list(csv.DictReader((args.base / 'drugs_app_ready.csv').open(encoding='utf-8-sig')))
    errors = validate(json.loads((args.base / 'manufacturer_notices.json').read_text(encoding='utf-8')), rows)
    if errors: raise SystemExit('\n'.join(errors))
    print('OK: verified manufacturer notices')

if __name__ == '__main__': main()
