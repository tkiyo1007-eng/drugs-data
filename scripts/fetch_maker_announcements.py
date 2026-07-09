#!/usr/bin/env python3
"""メーカー公式サイトの「お知らせ一覧」から、出荷調整・供給停止・販売中止等の
個別案内文(PDF)を取得し、drugs_app_ready.csv の商品名とマッチングして
maker_announcements.json を生成する。

日次実行時は各社とも直近数ページのみ見れば新規更新分(1日あたり数件)を
拾えるため、MAX_PAGES を小さく保てる。初回だけ広めに遡る。

対応メーカー: 沢井製薬・日医工・日本ジェネリック・キョーリンリメディオ・
             第一三共エスファ・日本ケミファ（他社は個別案内文の構造上、現状スコープ外）
"""
import csv
import json
import re
import sys
import unicodedata
import urllib.request

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def norm(s):
    return unicodedata.normalize("NFKC", s or "")


# ===== メーカーごとのパーサー =====
# 各パーサーは [(title, pdf_url), ...] を返す

def parse_sawai(pages=1):
    items = []
    html = fetch("https://med.sawai.co.jp/con_list.php?cate=5")
    for m in re.finditer(r'<a[^>]*href="(/file/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        items.append((re.sub(r"\s+", " ", text).strip(), "https://med.sawai.co.jp" + href))
    return [("沢井製薬", t, u) for t, u in items]


def parse_nichiiko(pages=1):
    items = []
    html = fetch("https://www.nichiiko.co.jp/medicine/whatsnew/index.php")
    for m in re.finditer(r'<a[^>]*href="(https://www\.nichiiko\.co\.jp/medicine/files/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        items.append((re.sub(r"\s+", " ", text).strip(), href))
    return [("日医工", t, u) for t, u in items]


def parse_nihon_generic(pages=3):
    items = []
    for p in range(1, pages + 1):
        url = "https://medical.nihon-generic.co.jp/news/" if p == 1 else f"https://medical.nihon-generic.co.jp/news/page/{p}/"
        html = fetch(url)
        for m in re.finditer(r'<a[^>]*href="(https://medical\.nihon-generic\.co\.jp/uploadfiles/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
            href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
            items.append((re.sub(r"\s+", " ", text).strip(), href))
    return [("日本ジェネリック", t, u) for t, u in items]


def parse_kyorin(pages=1):
    items = []
    html = fetch("https://www.med.kyorin-rmd.com/news/")
    for m in re.finditer(r'<a[^>]*href="(https://www\.med\.kyorin-rmd\.com/news/pdf/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        items.append((re.sub(r"\s+", " ", text).strip(), href))
    return [("キョーリンリメディオ", t, u) for t, u in items]


def parse_dsep(pages=1):
    items = []
    html = fetch("https://med.daiichisankyo-ep.co.jp/information/?certification=1")
    for m in re.finditer(r'<a[^>]*href="(https://med\.daiichisankyo-ep\.co\.jp/information/files/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        items.append((re.sub(r"\s+", " ", text).strip(), href))
    return [("第一三共エスファ", t, u) for t, u in items]


def parse_kemifa(pages=1):
    items = []
    html = fetch("https://www.nc-medical.com/product/information/")
    for m in re.finditer(r'<a[^>]*href="(/product_topics/[^"]+\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        items.append((re.sub(r"\s+", " ", text).strip(), "https://www.nc-medical.com" + href))
    return [("日本ケミファ", t, u) for t, u in items]


PARSERS = [parse_sawai, parse_nichiiko, parse_nihon_generic, parse_kyorin, parse_dsep, parse_kemifa]


# ===== 沢井製薬: 全製品供給状況一覧PDF経由の深掘り =====
# con_list.php(cate=5)は直近20件しか見えないため、対象163件のうち大半を取りこぼす。
# 沢井は品目ごとに prodid を持ち、各 preview.php?prodid=N ページに
# その品目の告知履歴が「YYYY/MM/DD カテゴリ タイトル」形式で列挙されている。
# 全品目一覧PDF(announce20.pdf)は各行(品目)にprodidへのリンクが張られているため、
# テキスト行の順序とPDF内リンクの順序が一致することを利用してマッピングを作る。

def build_sawai_prodid_map():
    import pypdf
    import io
    req = urllib.request.Request("https://med.sawai.co.jp/pdf/announce/announce20.pdf",
                                  headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        pdf_bytes = r.read()
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    mapping = {}
    for page in reader.pages:
        text = page.extract_text() or ""
        lines = [l for l in text.split("\n") if re.search(r"[A-Z0-9]{10,}", l)]
        annots = page.get("/Annots")
        annots = annots.get_object() if annots else []
        uris = []
        for a in annots:
            obj = a.get_object()
            if obj.get("/Subtype") == "/Link":
                act = obj.get("/A")
                if act:
                    uri = act.get_object().get("/URI")
                    if uri and "prodid=" in uri:
                        uris.append(uri)
        if len(lines) != len(uris):
            continue  # 行数とリンク数がずれるページは誤対応付けを避けてスキップ
        for line, uri in zip(lines, uris):
            m = re.match(r"^(.*?)\s+[A-Z0-9]{10,}", line)
            pm = re.search(r"prodid=(\d+)", uri)
            if m and pm:
                mapping[norm(m.group(1).strip())] = pm.group(1)
    return mapping


def fetch_sawai_prodid_announcement(prodid):
    """1品目のpreview.phpから、供給関連で最も新しい告知PDFを1件取得する"""
    try:
        html = fetch(f"https://med.sawai.co.jp/preview.php?prodid={prodid}")
    except Exception:
        return None
    candidates = []
    for m in re.finditer(r'<a[^>]*href="(/file/pr\d+_\d+(?:_\d+)?\.pdf)"[^>]*>(.*?)</a>', html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        dm = re.match(r"(\d{4}/\d{2}/\d{2})", text)
        if dm and is_supply_related(text):
            candidates.append((dm.group(1), text, "https://med.sawai.co.jp" + href))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    _, title, url = candidates[0]
    return title, url


def deepen_sawai(result, csv_path, limit=200):
    """まだ案内文が見つかっていない沢井製薬の対象品目について、prodid経由で追加取得する"""
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    targets = [r for r in rows if "通常出荷" not in r["供給状況"] or "薬価削除予定" in (r.get("代替候補") or "")]
    sawai_targets = [r for r in targets
                      if "沢井製薬" in (r["販売メーカー"] or r["製造メーカー"]) and r["商品名"] not in result]
    if not sawai_targets:
        return result

    try:
        prodid_map = build_sawai_prodid_map()
    except Exception as e:
        print(f"[WARN] 沢井prodidマップ取得失敗: {e}", file=sys.stderr)
        return result
    print(f"沢井prodidマップ: {len(prodid_map)}件", file=sys.stderr)

    checked = 0
    for r in sawai_targets[:limit]:
        name = r["商品名"]
        prodid = prodid_map.get(norm(name))
        if not prodid:
            continue
        checked += 1
        found = fetch_sawai_prodid_announcement(prodid)
        if found:
            title, url = found
            result[name] = {"maker": "沢井製薬", "title": title, "url": url}
    print(f"沢井個別ページ確認: {checked}件", file=sys.stderr)
    return result


def collect_announcements(nihon_generic_pages=3):
    all_items = []
    for parser in PARSERS:
        try:
            kwargs = {"pages": nihon_generic_pages} if parser is parse_nihon_generic else {}
            all_items.extend(parser(**kwargs))
        except Exception as e:
            print(f"[WARN] {parser.__name__} failed: {e}", file=sys.stderr)
    return all_items


# 供給状況と無関係なお知らせ(電子添文改訂・学会情報など)を除外するキーワード
SUPPLY_KEYWORDS = ["供給", "出荷", "限定", "停止", "中止", "お詫び", "欠品", "再開", "解除", "納品調整"]
# 品目固有ではない汎用アナウンス(「一覧を更新しました」等)は情報として無価値なため除外
GENERIC_TITLE_PATTERNS = ["供給状況一覧を更新", "情報を更新しました", "を更新いたしました"]


def is_supply_related(title):
    if any(p in title for p in GENERIC_TITLE_PATTERNS):
        return False
    return any(k in title for k in SUPPLY_KEYWORDS)


def base_name_and_specs(name_n):
    """規格違いをまとめて案内する表記（例: シロドシンOD錠2mg/4mg「サワイ」）に対応するため、
    正規化済み商品名から (メーカー括弧を除いたコア名, 含まれる規格数値の集合, メーカー括弧) を抽出する。
    """
    m = re.search(r"「[^」]+」\s*$", name_n)
    maker_paren = m.group(0) if m else ""
    body = name_n[: m.start()] if m else name_n
    specs = set(re.findall(r"\d+(?:\.\d+)?", body))
    core = re.sub(r"\d+(?:\.\d+)?\s*(mg|g|ml|%|μg|mcg)?", "", body).strip()
    return core, specs, maker_paren


def match_to_csv(announcements, csv_path, existing=None):
    """既存の対応表(existing)があれば引き継ぎつつ、今回の取得分で追加・上書きする。
    対象(出荷調整等)でなくなった品目は既存分から取り除く。
    日次実行はメーカー側お知らせの直近数件しか見ないため、これがないと
    過去に一度だけ広く取得した分が毎回の実行で失われてしまう。
    """
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    targets = [r for r in rows if "通常出荷" not in r["供給状況"] or "薬価削除予定" in (r.get("代替候補") or "")]
    target_names = {r["商品名"] for r in targets}

    supply_anns = [(m, t, u, norm(t)) for m, t, u in announcements if is_supply_related(t)]

    result = {name: v for name, v in (existing or {}).items() if name in target_names}
    for r in targets:
        name = r["商品名"]
        name_n = norm(name)
        if not name_n:
            continue
        matched = False
        for maker, title, url, title_n in supply_anns:
            if name_n in title_n:
                result[name] = {"maker": maker, "title": title, "url": url}
                matched = True
                break
        if matched:
            continue
        # 完全一致しない場合、規格違いをまとめた表記（例: 2mg/4mg）にも対応するフォールバック。
        # メーカー括弧の一致に加え規格数値も1つ以上一致させることで誤マッチを防ぐ
        core, specs, maker_paren = base_name_and_specs(name_n)
        if not (core and maker_paren and specs):
            continue
        # spec は日付(2026/07/08)等の数字と衝突しやすいため、前後が数字でない場合のみ一致とみなす
        def spec_hit(spec):
            return re.search(rf"(?<!\d){re.escape(spec)}(?!\d)", title_n) is not None
        for maker, title, url, title_n in supply_anns:
            if core in title_n and maker_paren in title_n and any(spec_hit(s) for s in specs):
                result[name] = {"maker": maker, "title": title, "url": url}
                break
    return result


def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "drugs_app_ready.csv"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "maker_announcements.json"
    pages = int(sys.argv[3]) if len(sys.argv) > 3 else 3

    existing = {}
    try:
        with open(out_path, encoding="utf-8") as f:
            existing = json.load(f)
        print(f"既存データ引き継ぎ: {len(existing)}件", file=sys.stderr)
    except FileNotFoundError:
        pass

    print("メーカーお知らせ取得中...", file=sys.stderr)
    announcements = collect_announcements(nihon_generic_pages=pages)
    print(f"取得件数: {len(announcements)}", file=sys.stderr)

    matched = match_to_csv(announcements, csv_path, existing=existing)
    print(f"マッチ件数: {len(matched)}（新規/更新分含む）", file=sys.stderr)

    deepen_limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    if deepen_limit > 0:
        matched = deepen_sawai(matched, csv_path, limit=deepen_limit)
        print(f"沢井深掘り後マッチ件数: {len(matched)}", file=sys.stderr)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=1)
    print(f"saved: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
