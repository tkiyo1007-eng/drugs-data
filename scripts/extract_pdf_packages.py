#!/usr/bin/env python3
"""maker_announcements.json の各案内文PDFから包装単位の記載を自動抽出する。

厚労省データには包装単位が存在しないため、「どの包装が対象か」は
メーカー案内文PDFの表（対象製品/包装単位/在庫消尽時期など）が唯一の情報源。
PDF全文から包装単位トークン（PTP100錠 等）と同一行の時期（20XX年X月）を抽出し、
announcement_packages.json {商品名: [{"pkg":..., "until":...}]} を生成する。

時期の意味（在庫消尽/中止時期/解除見込み）はPDFにより異なるため、
表示側では意味を断定せず「案内文記載の包装単位（自動抽出）」として扱うこと。

ダウンロード結果はURL単位で packages_cache.json にキャッシュし、
日次実行では新規・変更URLのみ取得する（1回の新規取得数は上限で制御）。

usage: extract_pdf_packages.py [announcements.json] [出力.json] [新規取得上限]
"""
import io
import json
import re
import sys
import unicodedata
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
CACHE_FILE = "packages_cache.json"

# 包装単位: PTP/バラ/分包等の形態語 + 数量単位（×N の連包表記も含む）
PKG_RE = re.compile(
    r'(?:PTP|ＰＴＰ|バラ|分包|包装小|SP|ＳＰ|瓶|袋)\s*[\d,.]+\s*'
    r'(?:錠|カプセル|Cap|包|枚|管|瓶|袋|本|個|g|mL|ｇ|ｍＬ|キット)(?:[×x]\s*\d+)?'
)
DATE_RE = re.compile(r'20\d{2}年\d{1,2}月')


def extract_from_pdf(url):
    import pypdf
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read()
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


def main():
    ann_path = sys.argv[1] if len(sys.argv) > 1 else "maker_announcements.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "announcement_packages.json"
    fetch_limit = int(sys.argv[3]) if len(sys.argv) > 3 else 60

    announcements = json.load(open(ann_path, encoding="utf-8"))
    try:
        cache = json.load(open(CACHE_FILE, encoding="utf-8"))
    except FileNotFoundError:
        cache = {}

    fetched = 0
    for name, info in announcements.items():
        url = info["url"]
        if url in cache:
            continue
        if fetched >= fetch_limit:
            continue
        fetched += 1
        try:
            cache[url] = extract_from_pdf(url)
        except Exception as e:
            print(f"[WARN] {name}: {e}", file=sys.stderr)
            # 失敗はキャッシュしない（次回リトライ）

    result = {}
    for name, info in announcements.items():
        pkgs = cache.get(info["url"])
        if pkgs:
            result[name] = pkgs

    json.dump(cache, open(CACHE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"新規取得: {fetched}件 / キャッシュ計: {len(cache)}URL / 包装情報あり: {len(result)}品目", file=sys.stderr)


if __name__ == "__main__":
    main()
