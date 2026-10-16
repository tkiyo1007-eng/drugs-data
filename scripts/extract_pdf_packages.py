#!/usr/bin/env python3
"""maker_announcements.json の各案内文PDFから包装単位の記載を自動抽出する。

厚労省データには包装単位が存在しないため、「どの包装が対象か」は
メーカー案内文PDFの表（対象製品/包装単位/在庫消尽時期など）が唯一の情報源。
PDF全文から包装単位トークン（PTP100錠 等）と同一行の時期（20XX年X月）を抽出し、
announcement_packages.json {商品名: [{"pkg":..., "until":...}]} を生成する。

時期の意味（在庫消尽/中止時期/解除見込み）はPDFにより異なるため、
表示側では意味を断定せず「案内文記載の包装単位（自動抽出）」として扱うこと。

ダウンロード結果はURL単位で packages_cache.json にキャッシュし、
日次実行では未キャッシュURLを1実行1回だけ試行する（最大60固有URL）。
候補の原URL固有順を、日本時間の日付と取得上限に応じて循環させ、
同じ先頭URLの失敗だけで後方の候補が待ち続ける偏りを減らす。
受信は8MiBまでとし、職種確認・ログインや別URLへの自動転送は通過しない。

usage: extract_pdf_packages.py [announcements.json] [出力.json] [新規取得上限]
"""
import io
from datetime import datetime, timedelta, timezone
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CACHE_FILE = "packages_cache.json"
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_FETCH_URLS = 60
JST = timezone(timedelta(hours=9))

# 包装単位: PTP/バラ/分包等の形態語 + 数量単位（×N の連包表記も含む）
PKG_RE = re.compile(
    r'(?:PTP|ＰＴＰ|バラ|分包|包装小|SP|ＳＰ|瓶|袋)\s*[\d,.]+\s*'
    r'(?:錠|カプセル|Cap|包|枚|管|瓶|袋|本|個|g|mL|ｇ|ｍＬ|キット)(?:[×x]\s*\d+)?'
)
DATE_RE = re.compile(r'20\d{2}年\d{1,2}月')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 職種確認・ログインへ自動移動しない。正当なPDF転送も取得不能として保持する。
        return None


def request_url(url):
    """送信時だけUnicodeをencodeし、既存cacheの原URLキーは変更しない。"""
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise ValueError("取得URLの型・長さが不正")
    if any(ord(c) < 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise ValueError("取得URLに制御文字または不正な区切り")
    if re.search(r"%(?![0-9a-fA-F]{2})", url):
        raise ValueError("取得URLのpercent表記が不正")
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.port not in (None, 443)
            or any(c.isspace() for c in parts.netloc) or "%" in parts.netloc):
        raise ValueError("資格情報のないHTTPS URLだけ取得可能")
    # URIの既存percent表記やpath/queryの区切りを再解釈・二重encodeしない。
    host = parts.hostname.encode("idna").decode("ascii")
    if ":" in host:
        host = f"[{host}]"
    netloc = host + (":443" if parts.port == 443 else "")
    path = urllib.parse.quote(parts.path or "/", safe="/%:@!$&'()*+,;=-._~")
    query = urllib.parse.quote(parts.query, safe="/%?:@!$&'()*+,;=-._~")
    return urllib.parse.urlunsplit(("https", netloc, path, query, ""))


def extract_from_pdf(url):
    req = urllib.request.Request(request_url(url), headers={"User-Agent": UA})
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(req, timeout=40) as r:
        if r.status != 200:
            raise ValueError(f"PDF取得失敗 HTTP {r.status}")
        data = r.read(MAX_PDF_BYTES + 1)
        content_type = r.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("PDF取得サイズ上限超過（8MiB）")
    if not data:
        raise ValueError("空の応答。包装記載なしとして保存しない")
    if content_type not in ("", "application/pdf", "application/x-pdf", "application/octet-stream", "binary/octet-stream"):
        raise ValueError("PDF以外の応答種別。職種確認・ログイン等を自動通過しない")
    if not data.lstrip().startswith(b"%PDF-"):
        raise ValueError("PDFではない応答。包装記載なしとして保存しない")
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    text = "\n".join((p.extract_text() or "") for p in reader.pages[:4])
    text = unicodedata.normalize("NFKC", text)
    found = []
    for line in text.split("\n"):
        for m in PKG_RE.finditer(line):
            until = DATE_RE.search(line)
            entry = {"pkg": m.group(0).replace(" ", ""), "until": until.group(0) if until else ""}
            if entry not in found:
                found.append(entry)
    return found[:10]


def daily_fetch_order(announcements, fetch_limit, day=None):
    """cache除外前の原URL固有順を日毎に循環。元の案内・cacheキーは変えない。"""
    unique = {}
    for name, info in announcements.items():
        unique.setdefault(info["url"], (name, info))
    candidates = list(unique.values())
    if not candidates or fetch_limit == 0:
        return candidates
    if day is None:
        day = datetime.now(JST).date()
    # 順・集合・上限が固定で毎日実行する場合、ceil(URL数/上限)日で全候補を含む。
    start = (day.toordinal() * fetch_limit) % len(candidates)
    return candidates[start:] + candidates[:start]


def main(*, day=None):
    ann_path = sys.argv[1] if len(sys.argv) > 1 else "maker_announcements.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "announcement_packages.json"
    fetch_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60
    if not 0 <= fetch_limit <= MAX_FETCH_URLS:
        raise ValueError("新規取得上限は0～60URL")

    with open(ann_path, encoding="utf-8") as f:
        announcements = json.load(f)
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}

    attempted = succeeded = failed = deferred = 0
    seen = set()
    for name, info in daily_fetch_order(announcements, fetch_limit, day):
        url = info["url"]
        if url in cache or url in seen:
            continue
        seen.add(url)
        if attempted >= fetch_limit:
            deferred += 1
            continue
        attempted += 1
        try:
            cache[url] = extract_from_pdf(url)
            succeeded += 1
        except Exception as e:
            failed += 1
            print(f"[WARN] {name}: {e}", file=sys.stderr)
            # 失敗はキャッシュしない（次回リトライ）

    result = {}
    for name, info in announcements.items():
        pkgs = cache.get(info["url"])
        if pkgs:
            result[name] = pkgs

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(f"取得試行: {attempted}URL / 成功: {succeeded}URL / 失敗: {failed}URL / "
          f"上限待ち: {deferred}URL / キャッシュ計: {len(cache)}URL / 包装情報あり: {len(result)}品目", file=sys.stderr)


if __name__ == "__main__":
    main()
