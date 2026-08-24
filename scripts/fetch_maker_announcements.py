#!/usr/bin/env python3
"""メーカー公式サイトの「お知らせ一覧」から、出荷調整・供給停止・販売中止等の
個別案内文(PDF)を取得し、drugs_app_ready.csv の商品名とマッチングして
maker_announcements.json を生成する。

日次実行時は各社とも直近数ページのみ見れば新規更新分(1日あたり数件)を
拾えるため、MAX_PAGES を小さく保てる。初回だけ広めに遡る。

対応メーカー: 沢井製薬・日医工・日本ジェネリック・キョーリンリメディオ・
             第一三共エスファ・日本ケミファ・東和薬品・高田製薬・久光製薬・ニプロ
"""
import csv
import datetime
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

from jst_time import jst_today
from maker_identity import maker_is_listed_in_row

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


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def parse_nichiiko_excel(pages=1):
    """日医工「製品供給状況一覧」Excel（excel_index.php が xlsx を直接返す）。
    I列に品目ごとの案内文書PDFへのハイパーリンクが埋め込まれており、
    whatsnew（直近数件のみ・品目が通常出荷へ戻ると対象外）と違い調整中の全品目をカバーできる。
    実PDFの題名は取れないため、タイトルは「販売名＋供給状況に関するお知らせ」の汎用形式。
    """
    import io
    import openpyxl
    raw = fetch_bytes("https://www.nichiiko.co.jp/medicine/significant/excel_index.php")
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    ws = wb["HP掲載用"]
    items = []
    for row in ws.iter_rows(min_row=6):
        name = row[2].value          # C列: 販売名
        cell = row[8]                # I列: 案内文書リンク
        if not name or cell.hyperlink is None or not cell.hyperlink.target:
            continue
        items.append((f"{str(name).strip()} 供給状況に関するお知らせ", cell.hyperlink.target))
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
    for block in re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, re.S | re.I):
        link = re.search(
            r'<a[^>]*href="(/product_topics/[^"]+\.pdf)"[^>]*>(.*?)</a>',
            block,
            re.S | re.I,
        )
        if not link:
            continue
        date = re.search(r'<th[^>]*class="[^"]*date[^"]*"[^>]*>(.*?)</th>', block, re.S | re.I)
        href, text = link.group(1), re.sub(r"<[^>]+>", " ", link.group(2))
        title = re.sub(r"\s+", " ", text).strip()
        if date:
            date_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", date.group(1))).strip()
            date_match = re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", date_text)
            if date_match:
                title = f"{date_match.group(0)} {title}"
        items.append((title, "https://www.nc-medical.com" + href))
    return [("日本ケミファ", t, u) for t, u in items]


def parse_towa(pages=3):
    """東和薬品: 職種選択セッションが必要。CookieJar付きで job_selector?job=2(薬剤師) を
    先に踏むと以降のページが本文を返す。tab=5=「供給・販売・中止」カテゴリ、20件/ページ。
    案内文PDFは fileloader.php 経由の直リンク（セッション無しでも開ける）。"""
    import http.cookiejar
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", UA)]

    def get(url):
        with opener.open(url, timeout=30) as r:
            return r.read().decode("utf-8", errors="ignore")

    get("https://med.towayakuhin.co.jp/medical/job_selector?job=2")
    items = []
    for p in range(1, pages + 1):
        url = ("https://med.towayakuhin.co.jp/medical/product/info.php?tab=5" if p == 1
               else f"https://med.towayakuhin.co.jp/medical/product/info.php?tab=5&_section=medical&page={p}")
        html = get(url)
        found = 0
        for m in re.finditer(r'<a[^>]*href="([^"]*fileloader\.php[^"]*)"[^>]*>(.*?)</a>', html, re.S):
            href = m.group(1).replace("&amp;", "&")
            if href.startswith("/"):
                href = "https://med.towayakuhin.co.jp" + href
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(2))).strip()
            items.append((text, href))
            found += 1
        if found == 0:
            break  # 最終ページ到達
    return [("東和薬品", t, u) for t, u in items]


def parse_takata(pages=2):
    """高田製薬: Cookie medical=yes で医療関係者ゲートを通過。
    お知らせは年別アーカイブ /medical/topics/{年}.html に集約されている。
    pages=遡る年数（日次実行では当年分だけで十分だが、年始の取りこぼし防止に2年分）"""
    import datetime
    this_year = jst_today().year
    items = []
    for year in range(this_year, this_year - max(1, min(pages, 4)), -1):
        req = urllib.request.Request(
            f"https://www.takata-seiyaku.co.jp/medical/topics/{year}.html",
            headers={"User-Agent": UA, "Cookie": "medical=yes"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                html = r.read().decode("utf-8", errors="ignore")
        except Exception:
            continue  # 存在しない年は無視
        for block in re.findall(r"<li\b[^>]*>(.*?)</li>", html, re.S | re.I):
            link = re.search(r'<a[^>]*href="([^"]+\.pdf)"[^>]*>(.*?)</a>', block, re.S | re.I)
            if not link:
                continue
            href = link.group(1)
            if href.startswith("/"):
                href = "https://www.takata-seiyaku.co.jp" + href
            text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", link.group(2))).strip()
            date = re.search(r'<span[^>]*class="[^"]*date[^"]*"[^>]*>(.*?)</span>', block, re.S | re.I)
            if date:
                date_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", date.group(1))).strip()
                date_match = re.search(r"20\d{2}/\d{1,2}/\d{1,2}", date_text)
                if date_match:
                    text = f"{date_match.group(0)} {text}"
            items.append((text, href))
    return [("高田製薬", t, u) for t, u in items]


def parse_hisamitsu(pages=2):
    """久光製薬のお知らせ一覧から、直近 ``pages`` 年分のPDFを取得する。

    一覧は過去分まで1ページにまとまっているため、URL先頭の yymmdd を使って
    年を絞る。タイトルに複数品目が列挙される販売中止案内もそのまま保持する。
    """
    html = fetch("https://www.hisamitsu-pharm.jp/product/whatsnew/index.html?category=c3")
    this_year = jst_today().year
    min_year = this_year - max(1, min(pages, 5)) + 1
    items = []
    seen = set()
    for m in re.finditer(r'<a[^>]*href="([^"]+\.pdf(?:/[^"]+)?)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href, text = m.group(1), re.sub(r"<[^>]+>", " ", m.group(2))
        title = re.sub(r"\s+", " ", text).strip()
        dm = re.search(r"/(\d{2})(\d{2})(\d{2})(?:[_-]|\.|[a-z])", href, re.I)
        if not (title and dm):
            continue
        year = 2000 + int(dm.group(1))
        if year < min_year:
            continue
        url = href if href.startswith("http") else "https://www.hisamitsu-pharm.jp" + href
        if url in seen:
            continue
        seen.add(url)
        date = f"{year:04d}.{int(dm.group(2)):02d}.{int(dm.group(3)):02d}"
        items.append((f"{date} {title}", url))
    return [("久光製薬", t, u) for t, u in items]


NIPRO_API = "https://med.nipro.co.jp/webruntime/api/apex/execute?language=ja&asGuest=true&htmlEncode=false"
NIPRO_APEX_CLASS = "@udd/01p5g00000jrWnK"


def fetch_nipro_page(category, page):
    """ニプロのお知らせ公開APIから1ページ取得する。"""
    payload = {
        "namespace": "", "classname": NIPRO_APEX_CLASS, "method": "all",
        "isContinuation": False,
        "params": {"keyword": "", "year": "", "category": category,
                   "perPage": 20, "currentPage": page},
        "cacheable": False,
    }
    req = urllib.request.Request(
        NIPRO_API, data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": UA, "Content-Type": "application/json",
                 "Origin": "https://med.nipro.co.jp",
                 "Referer": "https://med.nipro.co.jp/pharmaceuticals/news"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("returnValue", {})


def parse_nipro(pages=2):
    """ニプロの「販売中止」「供給関連情報」を公開APIから取得する。"""
    items = []
    seen = set()
    for category in ("販売中止", "供給関連情報"):
        for page in range(1, pages + 1):
            data = fetch_nipro_page(category, page)
            records = data.get("data") or []
            for row in records:
                title = (row.get("c_NpNewsTitle__c") or "").strip()
                href = row.get("newsPDFUrl__c") or ""
                date = (row.get("c_NpNewsDateTimeToShowFormula__c") or "").strip()
                if not (title and href):
                    continue
                url = href if href.startswith("http") else "https://med.nipro.co.jp" + href
                if url in seen:
                    continue
                seen.add(url)
                items.append((f"{date} {title}".strip(), url))
            if not records or page >= int(data.get("lastPage") or page):
                break
    return [("ニプロ", t, u) for t, u in items]


PARSERS = [parse_sawai, parse_nichiiko, parse_nichiiko_excel, parse_nihon_generic,
           parse_kyorin, parse_dsep, parse_kemifa, parse_towa, parse_takata,
           parse_hisamitsu, parse_nipro]
PAGINATED_PARSERS = {"parse_nihon_generic", "parse_towa", "parse_takata",
                     "parse_hisamitsu", "parse_nipro"}  # pagesパラメータを渡すパーサー


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
    """沢井製薬の対象品目について、prodid経由で最新の案内文を取得する。
    未取得の品目を優先しつつ、既に案内文がある品目も「最終確認が古い順」で
    再チェックしてローテーションする。これにより、メーカーが状況変化で新しい
    案内文を出したとき（例: 供給停止→限定出荷）に古い案内文へ差し替えられる。
    limit件/回で回すため、対象全体は数日かけて一巡する。"""
    today = jst_today().isoformat()
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    # 現在「通常出荷」でも将来の販売中止案内が出ていることがあるため、
    # 沢井製薬の全品目をローテーション対象にする。
    sawai_targets = [r for r in rows
                      if "沢井製薬" in (r["販売メーカー"] or r["製造メーカー"])]
    # 並び順: 未取得(0)を最優先、既存(1)は最終確認日が古い順（未記録は最古扱い）
    def sort_key(r):
        cur = result.get(r["商品名"])
        return ("0", "") if cur is None else ("1", cur.get("checked", ""))
    sawai_targets.sort(key=sort_key)
    if not sawai_targets:
        return result

    try:
        prodid_map = build_sawai_prodid_map()
    except Exception as e:
        print(f"[WARN] 沢井prodidマップ取得失敗: {e}", file=sys.stderr)
        return result
    print(f"沢井prodidマップ: {len(prodid_map)}件", file=sys.stderr)

    checked = updated = 0
    for r in sawai_targets[:limit]:
        name = r["商品名"]
        prodid = prodid_map.get(norm(name))
        if not prodid:
            continue
        checked += 1
        found = fetch_sawai_prodid_announcement(prodid)
        if found:
            title, url = found
            prev = result.get(name, {})
            if prev.get("url") != url:
                updated += 1
            result[name] = make_announcement_record("沢井製薬", title, url, checked=today)
        elif result.get(name, {}).get("maker") == "沢井製薬":
            # 既存はあるが今回見つからなかった場合は最終確認日だけ更新（案内文は残す）
            result[name]["checked"] = today
    print(f"沢井個別ページ確認: {checked}件（うちURL差し替え {updated}件）", file=sys.stderr)
    return result


def collect_announcements(nihon_generic_pages=3):
    all_items = []
    health = []
    seen = set()
    for parser in PARSERS:
        try:
            kwargs = {"pages": nihon_generic_pages} if parser.__name__ in PAGINATED_PARSERS else {}
            items = []
            local_seen = set()
            for maker, title, url in parser(**kwargs):
                # 同じリンクがPC用・モバイル用など複数箇所に現れるメーカーがある。
                # URL単位で一意化し、収集件数と未マッチ確認待ちを水増ししない。
                key = (norm(maker), str(url).strip())
                if not key[1] or key in local_seen:
                    continue
                local_seen.add(key)
                items.append((maker, title, url))
                if key not in seen:
                    seen.add(key)
                    all_items.append((maker, title, url))
            health.append({"source": parser.__name__, "ok": bool(items), "count": len(items),
                           "error": "" if items else "取得件数が0件"})
        except Exception as e:
            print(f"[WARN] {parser.__name__} failed: {e}", file=sys.stderr)
            health.append({"source": parser.__name__, "ok": False, "count": 0, "error": str(e)})
    return all_items, health


def collection_anomalies(health, total, previous=None):
    """複数障害・総量急減・収集元ごとの大幅減を検出する。"""
    anomalies = []
    failed = [source for source in health if not source.get("ok")]
    if len(failed) > max(2, len(PARSERS) // 3):
        anomalies.append(f"{len(failed)}ソースが失敗")
    if total < 20:
        anomalies.append(f"総取得件数が少なすぎます: {total}件")
    if isinstance(previous, dict):
        previous_total = previous.get("total")
        if isinstance(previous_total, int) and previous_total >= 100 and total * 2 < previous_total:
            anomalies.append(f"総取得件数が前回の50%未満です: {previous_total}→{total}件")
        previous_sources = {
            source.get("source"): source.get("count")
            for source in previous.get("sources") or [] if isinstance(source, dict)
        }
        for source in health:
            name, count = source.get("source"), source.get("count")
            old_count = previous_sources.get(name)
            if (isinstance(old_count, int) and old_count >= 20
                    and isinstance(count, int) and count * 5 < old_count):
                anomalies.append(f"{name}の取得件数が前回の20%未満です: {old_count}→{count}件")
    return anomalies


# 供給状況と無関係なお知らせ(電子添文改訂・学会情報など)を除外するキーワード
SUPPLY_KEYWORDS = ["供給", "出荷", "限定", "停止", "中止", "終了", "お詫び", "欠品", "再開", "解除", "納品調整"]
# 品目固有ではない汎用アナウンス(「一覧を更新しました」等)は情報として無価値なため除外
GENERIC_TITLE_PATTERNS = ["供給状況一覧を更新", "情報を更新しました", "を更新いたしました"]


def is_supply_related(title):
    if any(p in title for p in GENERIC_TITLE_PATTERNS):
        return False
    return any(k in title for k in SUPPLY_KEYWORDS)


def classify_event(title):
    """案内タイトルを表示用の安定した種別に分類する。

    「他社品販売中止に伴う限定出荷」を自社品の販売中止と誤判定しないこと、
    一部包装の中止を製品全体の中止と分けることを優先する。
    """
    t = norm(title)
    # 「販売終了製品」と書かれていても、案内そのものが特定包装の
    # 限定出荷解除を知らせる文書なら、販売中止の根拠にはしない。
    if re.search(r"販売終了製品.*(?:限定出荷|出荷調整)(?:の)?解除", t):
        return "resumed"
    if re.search(
            r"(?:一部)?包装(?:容量)?(?:における|の)?(?:販売|発売)?(?:中止|終了)"
            r"|患者(?:さん)?用パッケージ(?:入り)?.*(?:販売|発売)(?:中止|終了)", t):
        return "package_discontinued"
    # 取扱い終了は販売会社・流通経路だけが変わり、製品自体は別会社から
    # 継続する場合があるため、製品全体の販売中止とは分離する。
    if re.search(r"取[り]?扱い(?:販売)?(?:中止|終了)|取扱(?:販売)?(?:中止|終了)", t):
        return "handling_discontinued"
    if (re.search(r"販売中止|販売終了|製造中止|製造販売中止", t)
            and not re.search(r"他社(?:品|製品).*販売中止.*(?:影響|伴)", t)):
        return "discontinued"
    if re.search(r"出荷再開|供給再開|限定出荷解除|出荷調整解除|供給停止解除", t):
        return "resumed"
    if re.search(r"出荷停止|供給停止|欠品", t):
        return "stopped"
    if re.search(r"限定出荷|出荷調整|納品調整|注文辞退", t):
        return "limited"
    if re.search(r"供給|出荷", t):
        return "supply"
    return "other"


def extract_announcement_date(title, url=""):
    """案内日をタイトル、次に公式URL内のファイル名から抽出する。

    URLは東和薬品の ``f=20260730_...pdf`` のようにタイトルへ日付が
    表示されない一次資料を補完するために使う。実在する年月日だけを採用する。
    """
    t = norm(title)
    decoded_url = urllib.parse.unquote(url or "")
    candidates = (
        (t, r"(20\d{2})[./年](\d{1,2})[./月](\d{1,2})日?"),
        (t, r"^(20\d{2})(\d{2})(\d{2})"),
        (decoded_url, r"(?:^|[/?&=_.-])(20\d{2})[._-]?(\d{2})[._-]?(\d{2})(?=$|[&_.-])"),
    )
    for source, pattern in candidates:
        m = re.search(pattern, source)
        if m:
            try:
                value = datetime.date(*(int(m.group(i)) for i in range(1, 4)))
            except ValueError:
                continue
            return value.isoformat()
    return ""


def make_announcement_record(maker, title, url, checked=None):
    record = {"maker": maker, "title": title, "url": url,
              "event_type": classify_event(title)}
    announced_at = extract_announcement_date(title, url)
    if announced_at:
        record["announced_at"] = announced_at
    if checked:
        record["checked"] = checked
    return record


def maker_matches_row(maker, row):
    return maker_is_listed_in_row(maker, row)


def is_normal_row(row):
    return "通常出荷" in (row.get("供給状況") or "")


def has_delist_notice(row):
    return "薬価削除予定" in (row.get("代替候補") or "")


def update_event_history(history, current, today=None):
    """現在の代表案内を品目別履歴へ追記する。同じURLは重複させない。"""
    today = today or jst_today().isoformat()
    result = {name: [dict(e) for e in events]
              for name, events in (history or {}).items() if isinstance(events, list)}
    for name, info in current.items():
        events = result.setdefault(name, [])
        found = next((e for e in events
                      if e.get("url") == info.get("url") and e.get("title") == info.get("title")), None)
        if found is None:
            found = {k: info[k] for k in ("maker", "title", "url", "event_type", "announced_at")
                     if info.get(k)}
            found["first_seen"] = today
            events.append(found)
        else:
            # event_type追加前に作られた履歴など、同一URLの既存レコードを移行する。
            for key in ("maker", "event_type", "announced_at"):
                if info.get(key):
                    found[key] = info[key]
        found["last_checked"] = info.get("checked") or today
        events.sort(key=lambda e: (e.get("announced_at", ""), e.get("first_seen", "")), reverse=True)
    return result


def base_name_and_specs(name_n):
    """規格違いをまとめて案内する表記（例: シロドシンOD錠2mg/4mg「サワイ」）に対応するため、
    正規化済み商品名から (メーカー括弧を除いたコア名, 含まれる規格数値の集合, メーカー括弧) を抽出する。
    """
    m = re.search(r"「[^」]+」\s*$", name_n)
    maker_paren = m.group(0) if m else ""
    body = name_n[: m.start()] if m else name_n
    specs = set(re.findall(r"\d+(?:\.\d+)?", body))
    core = re.sub(r"\d+(?:\.\d+)?\s*(mg|g|ml|%|μg|mcg|番)?", "", body).strip()
    return core, specs, maker_paren


def base_name_and_variant(name_n):
    """MD/EX、LD/HDなど、数字を含まない規格記号を分離する。"""
    m = re.search(r"「[^」]+」\s*$", name_n)
    maker_paren = m.group(0) if m else ""
    body = name_n[: m.start()] if m else name_n
    variant = re.search(r"([A-Z]{1,3})$", body)
    if not variant:
        return "", "", maker_paren
    return body[:variant.start()].strip(), variant.group(1), maker_paren


def maker_suffix_matches(maker_paren, title_n):
    """商品名のメーカー括弧を確認する。

    メーカー公式の案内タイトルでは「ニプロ」等が省略されることがあるため、
    タイトル側に括弧がない場合のみ省略を許す。別メーカーの括弧がある場合は
    ソースのメーカーが一致していても照合しない。
    """
    if not maker_paren:
        return False
    suffixes = re.findall(r"「[^」]+」", title_n)
    return not suffixes or maker_paren in suffixes


def terminal_family_title_matches(core, title_n):
    """規格・メーカー括弧を省略した全規格の販売中止タイトルを判定する。

    製品名の直後に販売中止等が続く場合だけを対象にし、複数製品文書の括弧内で
    一般名が列挙されただけのケースを拾わない。
    """
    if classify_event(title_n) != "discontinued" or re.findall(r"「[^」]+」", title_n):
        return False
    return re.search(
        rf"{re.escape(core)}[_\s]*(?:の)?(?:製造販売|販売|製造)(?:中止|終了)",
        title_n,
    ) is not None


EVENT_PRIORITY = {
    "discontinued": 3,
    "package_discontinued": 2,
    "handling_discontinued": 2,
    "stopped": 1,
    "limited": 1,
    "resumed": 1,
    "supply": 1,
    "other": 1,
}
TRANSIENT_PRIORITY = {
    "stopped": 4,
    "limited": 3,
    "resumed": 2,
    "supply": 1,
    "other": 0,
}


def announcement_rank(info):
    """Web/iOSに表示する代表案内の優先順位を返す。

    製品全体の販売中止を包装中止や一時的な供給案内より常に優先し、
    同じ種別では新しい案内を採用する。
    """
    event_type = info.get("event_type") or classify_event(info.get("title", ""))
    return (EVENT_PRIORITY.get(event_type, 1), info.get("announced_at", ""),
            TRANSIENT_PRIORITY.get(event_type, 0))


def filter_resolved_unmatched(unmatched, matched, extra_resolved_urls=None):
    """深掘り・手動登録・既存引継ぎで解決済みのURLを未照合から除く。"""
    resolved_urls = {info.get("url") for info in matched.values() if info.get("url")}
    resolved_urls.update(extra_resolved_urls or ())
    return [info for info in unmatched if info.get("url") not in resolved_urls]


def load_manual_announcements(single_path="manual_announcements.json",
                              groups_path="manual_announcement_groups.json"):
    """個別登録と、1文書に複数品目を列挙するグループ登録を統合する。

    グループを先に展開し、個別登録を後から重ねることで、例外的な1品目だけを
    個別ファイルで上書きできるようにする。
    """
    manual = {}
    resolved_urls = set()
    group_events = []
    try:
        with open(groups_path, encoding="utf-8") as f:
            groups = json.load(f)
        for group in groups:
            info = dict(group["announcement"])
            # 公式資料の本文・表で対象品目を再確認したグループ
            # だけを強い信頼境界とする。既存グループを一括で確認済みに
            # 格上げすると、未再監査の品目までライフサイクルに反映される。
            if group.get("target_products_verified") is True:
                info["target_products_verified"] = True
                info["target_scope"] = group.get("target_scope")
            info.setdefault("event_type", classify_event(info.get("title", "")))
            announced_at = extract_announcement_date(info.get("title", ""), info.get("url", ""))
            if announced_at:
                info.setdefault("announced_at", announced_at)
            expected = group.get("expected_target_count")
            target_count = len(group.get("products") or []) + len(group.get("lifecycle_targets") or [])
            if info.get("url") and isinstance(expected, int) and expected == target_count:
                resolved_urls.add(info["url"])
            event_group = {}
            for name in group.get("products") or []:
                event_group[name] = dict(info)
                current = manual.get(name)
                if current is None or announcement_rank(info) > announcement_rank(current):
                    manual[name] = dict(info)
            group_events.append(event_group)
    except FileNotFoundError:
        pass

    try:
        with open(single_path, encoding="utf-8") as f:
            single = json.load(f)
        # 品目固有の明示登録はグループの優先順位より常に優先する。
        manual.update(single)
        resolved_urls.update(info.get("url") for info in single.values() if info.get("url"))
    except FileNotFoundError:
        pass
    return manual, resolved_urls, group_events


def match_to_csv(announcements, csv_path, existing=None, unmatched_out=None):
    """既存の対応表(existing)があれば引き継ぎつつ、今回の取得分で追加・上書きする。
    CSVから消えた品目は既存分から取り除く。通常出荷へ戻った品目の一時的な
    供給案内は除くが、販売中止・包装中止は将来情報なので保持する。
    日次実行はメーカー側お知らせの直近数件しか見ないため、これがないと
    過去に一度だけ広く取得した分が毎回の実行で失われてしまう。
    """
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    rows_by_name = {r["商品名"]: r for r in rows}
    targets = rows  # 「通常出荷」でも販売中止予定を拾うため全品目を対象にする

    supply_anns = [(m, t, u, norm(t)) for m, t, u in announcements if is_supply_related(t)]

    result = {}
    for name, value in (existing or {}).items():
        row = rows_by_name.get(name)
        if not row:
            continue
        # 分類規則の改善を既存生成データにも反映し、過去の誤分類を固定化しない。
        # 手動登録の明示event_typeはこの後のオーバーレイで再適用される。
        event_type = classify_event(value.get("title", ""))
        if (not is_normal_row(row) or has_delist_notice(row)
                or event_type in {"discontinued", "package_discontinued", "handling_discontinued"}):
            value = dict(value)
            value["event_type"] = event_type
            announced_at = extract_announcement_date(value.get("title", ""), value.get("url", ""))
            if announced_at:
                value.setdefault("announced_at", announced_at)
            result[name] = value

    used_urls = set()
    today = jst_today().isoformat()
    for r in targets:
        name = r["商品名"]
        name_n = norm(name)
        if not name_n:
            continue
        candidates = []
        if name in result:
            candidates.append(result[name])

        def add_candidate(maker, title, url):
            candidates.append(make_announcement_record(maker, title, url, checked=today))
            # 代表案内に選ばれなかった旧報・続報も、製品への照合自体は完了している。
            used_urls.add(url)

        for maker, title, url, title_n in supply_anns:
            if maker_matches_row(maker, r) and name_n in title_n:
                add_candidate(maker, title, url)

        # 完全一致しない場合、規格違いをまとめた表記（例: 2mg/4mg）にも対応するフォールバック。
        # 公式ソースのメーカー一致に加え規格数値も1つ以上一致させることで誤マッチを防ぐ。
        core, specs, maker_paren = base_name_and_specs(name_n)
        if core and specs:
            for maker, title, url, title_n in supply_anns:
                # spec は日付(2026/07/08)等の数字と衝突しやすいため、前後が数字でない場合のみ一致とみなす
                spec_hit = any(re.search(rf"(?<!\d){re.escape(spec)}(?!\d)", title_n)
                               for spec in specs)
                if (maker_matches_row(maker, r) and core in title_n
                        and (not maker_paren or maker_suffix_matches(maker_paren, title_n))
                        and spec_hit):
                    add_candidate(maker, title, url)

                # 全規格が対象の案内では、タイトルから強度が省略されることがある。
                # 正規化した剤形とメーカー括弧が連続して明記される場合だけ許可する。
                if (maker_paren and maker_matches_row(maker, r)
                        and f"{core}{maker_paren}" in title_n):
                    add_candidate(maker, title, url)

                # メーカー公式タイトルが規格と「タカタ」等を省略し、製品ファミリー名の
                # 直後に製造販売中止を明記する場合は、そのメーカーの全規格へ紐づける。
                if (maker_paren and maker_matches_row(maker, r)
                        and terminal_family_title_matches(core, title_n)):
                    add_candidate(maker, title, url)

        # 数字のない規格記号をまとめた表記（例: MD/EX、LD/HD）にも対応する。
        variant_core, variant, variant_maker = base_name_and_variant(name_n)
        if variant_core and variant:
            for maker, title, url, title_n in supply_anns:
                variant_hit = re.search(
                    rf"(?<![A-Z]){re.escape(variant)}(?![A-Z])", title_n) is not None
                if (maker_matches_row(maker, r) and variant_core in title_n
                        and (not variant_maker or maker_suffix_matches(variant_maker, title_n))
                        and variant_hit):
                    add_candidate(maker, title, url)

        if candidates:
            # 同一URLが完全一致とフォールバックの両方で見つかっても1件にする。
            unique = {(info.get("url"), info.get("title")): info for info in candidates}
            result[name] = max(unique.values(), key=announcement_rank)
    if unmatched_out is not None:
        unmatched_out.extend(make_announcement_record(m, t, u)
                             for m, t, u, _ in supply_anns if u not in used_urls)
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
    announcements, health = collect_announcements(nihon_generic_pages=pages)
    print(f"取得件数: {len(announcements)}", file=sys.stderr)

    health_path = os.path.join(os.path.dirname(out_path) or ".", "maker_collection_health.json")
    try:
        with open(health_path, encoding="utf-8") as f:
            previous_health = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        previous_health = None
    health_doc = {"checked": jst_today().isoformat(), "sources": health,
                  "total": len(announcements)}
    with open(health_path, "w", encoding="utf-8") as f:
        json.dump(health_doc, f, ensure_ascii=False, indent=1)
    failed = [h for h in health if not h["ok"]]
    for h in failed:
        # GitHub Actionsの画面に警告注釈を出し、単一ソース障害もログに埋もれさせない。
        print(f"::warning title=メーカー案内収集失敗::{h['source']}: {h['error']}", file=sys.stderr)
    # 1社の一時障害では厚労省データ更新を止めないが、複数障害や前回比の大幅減は
    # HTML/API変更の可能性が高いため失敗させ、少量だけ取得できた状態も見逃さない。
    anomalies = collection_anomalies(health, len(announcements), previous_health)
    if anomalies:
        print(f"❌ メーカー案内の取得異常: {' / '.join(anomalies)}", file=sys.stderr)
        raise SystemExit(1)

    unmatched = []
    matched = match_to_csv(announcements, csv_path, existing=existing, unmatched_out=unmatched)
    print(f"マッチ件数: {len(matched)}（新規/更新分含む）", file=sys.stderr)

    deepen_limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    if deepen_limit > 0:
        matched = deepen_sawai(matched, csv_path, limit=deepen_limit)
        print(f"沢井深掘り後マッチ件数: {len(matched)}", file=sys.stderr)

    # 手動登録分（manual_announcements.json）を最後に重ねる（手動が優先）
    # 自動収集が対応していないメーカーの案内文をピンポイントで連携するための仕組み
    manual, manual_urls, manual_group_events = load_manual_announcements()
    for name, info in manual.items():
        info = dict(info)
        info.setdefault("event_type", classify_event(info.get("title", "")))
        announced_at = extract_announcement_date(info.get("title", ""), info.get("url", ""))
        if announced_at:
            info.setdefault("announced_at", announced_at)
        matched[name] = info
    if manual:
        print(f"手動登録を反映: {len(manual)}件", file=sys.stderr)

    # 自動照合の代表に選ばれなかった旧報・続報や、沢井深掘り・手動登録・
    # 既存引継ぎで解決済みのURLはレビュー待ち一覧から除外する。
    unmatched = filter_resolved_unmatched(unmatched, matched, manual_urls)
    unmatched_path = os.path.join(os.path.dirname(out_path) or ".", "unmatched_maker_announcements.json")
    with open(unmatched_path, "w", encoding="utf-8") as f:
        json.dump(unmatched, f, ensure_ascii=False, indent=1)
    print(f"未照合案内: {len(unmatched)}件（{unmatched_path}）", file=sys.stderr)

    # 代表案内はWeb/iOS向けに1件だけ保持しつつ、差し替え前の案内も履歴へ残す。
    events_path = os.path.join(os.path.dirname(out_path) or ".", "maker_announcement_events.json")
    try:
        with open(events_path, encoding="utf-8") as f:
            history = json.load(f)
    except FileNotFoundError:
        history = {}
    history = update_event_history(history, matched)
    # 同一品目に複数のグループ通知がある場合、代表に選ばれない旧通知も履歴へ残す。
    for group_events in manual_group_events:
        history = update_event_history(history, group_events)
    with open(events_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=1)
    print(f"案内履歴: {sum(map(len, history.values()))}件（{events_path}）", file=sys.stderr)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=1)
    print(f"saved: {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
