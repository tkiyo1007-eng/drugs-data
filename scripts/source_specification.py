"""Use original specification differences only when bound to the data version."""
import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit


def unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('duplicate JSON key')
        out[key] = value
    return out


def valid_comparison(doc, meta, csv_bytes, version):
    try:
        if not isinstance(doc, dict) or type(doc.get('schema_version')) is not int or doc['schema_version'] != 1:
            return False
        if not isinstance(meta, dict) or not isinstance(version, dict):
            return False
        source_date = meta.get('excel_date')
        if not isinstance(source_date, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', source_date):
            return False
        if date.fromisoformat(source_date).isoformat() != source_date or source_date != version.get('mhlw_excel_date'):
            return False
        version_id = str(version.get('version') or '')
        if not re.fullmatch(r'\d{8,14}', version_id):
            return False
        version_day = date(int(version_id[:4]), int(version_id[4:6]), int(version_id[6:8]))
        if date.fromisoformat(source_date) > version_day:
            return False
        url = urlsplit(meta.get('url', ''))
        filename = meta.get('file')
        if (url.scheme != 'https' or url.hostname not in {'mhlw.go.jp', 'www.mhlw.go.jp'}
                or url.username or url.password or url.port not in (None, 443)
                or not url.path.startswith('/content/') or unquote(url.path.rsplit('/', 1)[-1]) != filename
                or not isinstance(filename, str) or not filename.lower().endswith('.xlsx')):
            return False
        dated = re.fullmatch(r'(\d{6})iyakuhinkyoukyu\.xlsx', filename, re.IGNORECASE)
        if dated and date.fromisoformat(source_date).strftime('%y%m%d') != dated.group(1):
            return False
        if (not re.fullmatch(r'[0-9a-f]{64}', str(meta.get('sha256') or ''))
                or doc.get('source_date') != source_date or doc.get('source_sha256') != meta['sha256']
                or doc.get('csv_sha256') != hashlib.sha256(csv_bytes).hexdigest()):
            return False
        reader = csv.DictReader(io.StringIO(csv_bytes.decode('utf-8-sig'), newline=''))
        if not {'YJコード', '規格'}.issubset(reader.fieldnames or []):
            return False
        current = {}
        for row in reader:
            key = (row.get('YJコード') or '').strip()
            if not key or key in current:
                return False
            current[key] = (row.get('規格') or '').strip()
        differences = doc.get('differences')
        if not current or not isinstance(differences, dict):
            return False
        def normalized(value):
            return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value).lower())
        for key, item in differences.items():
            if (not isinstance(key, str) or key not in current or not isinstance(item, dict)
                    or set(item) != {'source', 'retained'}
                    or not all(isinstance(item.get(k), str) for k in ('source', 'retained'))
                    or item['retained'] != current[key]
                    or normalized(item['source']) == normalized(item['retained'])):
                return False
        return True
    except (ValueError, TypeError, KeyError, UnicodeError, csv.Error):
        return False


def load_comparison(site, csv_path, version):
    try:
        def read_json(path):
            return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        doc = read_json(Path(site) / 'specification_differences.json')
        meta = read_json(Path(site) / 'mhlw_source.json')
        if valid_comparison(doc, meta, Path(csv_path).read_bytes(), version):
            return doc
    except (OSError, ValueError, TypeError):
        pass
    return None
