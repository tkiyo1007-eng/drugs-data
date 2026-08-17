#!/usr/bin/env python3
"""status_changes.json から日別の供給変更ページとサイトマップを生成する。"""

import argparse
import html
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape as xml_escape


SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/"
STATUS_LABELS = {
    "ok": "通常出荷",
    "limited": "限定出荷",
    "stopped": "供給停止",
    "ended": "販売中止",
}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def normalize_date(value: object) -> str:
    raw = str(value or "").strip().replace("/", "-")
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return ""


def status_key(value: object) -> str:
    text = str(value or "")
    if "停止" in text:
        return "stopped"
    if "限定" in text:
        return "limited"
    if "中止" in text:
        return "ended"
    return "ok"


def status_label(value: object) -> str:
    return STATUS_LABELS[status_key(value)]


def item_key(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", str(value or ""))


def load_changes(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("status_changes.json は配列である必要があります")
    grouped: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        date = normalize_date(entry.get("date"))
        name = str(entry.get("name") or "").strip()
        before = str(entry.get("from") or "").strip()
        after = str(entry.get("to") or "").strip()
        yj = item_key(entry.get("yj"))
        identity = (date, yj or name, before, after)
        if not date or not name or not before or not after or identity in seen:
            continue
        seen.add(identity)
        grouped[date].append({"date": date, "name": name, "from": before, "to": after, "yj": yj})
    return dict(grouped)


def page_html(date: str, changes: list[dict], item_keys: set[str]) -> str:
    dt = datetime.strptime(date, "%Y-%m-%d")
    date_jp = f"{dt.year}年{dt.month}月{dt.day}日"
    counts = Counter(status_key(change["to"]) for change in changes)
    title = f"{date_jp}に供給状況が変わった医薬品（{len(changes)}品目）｜医薬品供給ナビ"
    description = (
        f"{date_jp}に厚生労働省公表データ上の供給状況が変わった医療用医薬品{len(changes)}品目の一覧。"
        "通常出荷への復帰、限定出荷、供給停止など、前回データとの差分を掲載しています。"
    )
    url = f"{SITE_ROOT}updates/{date}.html"
    chips = "".join(
        f'<span class="stat {key}"><strong>{counts[key]}</strong>{label}へ</span>'
        for key, label in STATUS_LABELS.items() if counts[key]
    )
    rows = []
    for change in sorted(changes, key=lambda item: (status_key(item["to"]), item["name"])):
        key = status_key(change["to"])
        yj = change["yj"]
        href = (f"../items/{yj}.html" if yj and yj in item_keys
                else "../#item=" + quote(yj, safe="") if yj
                else "../#drug=" + quote(change["name"], safe=""))
        rows.append(
            f'<li class="change {key}"><a href="{href}">{esc(change["name"])}</a>'
            f'<span class="transition">{esc(status_label(change["from"]))} → '
            f'<strong>{esc(status_label(change["to"]))}</strong></span></li>'
        )
    structured = json.dumps({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description,
        "datePublished": date,
        "dateModified": date,
        "inLanguage": "ja",
        "mainEntityOfPage": url,
        "publisher": {"@type": "Organization", "name": "医薬品供給ナビ", "url": SITE_ROOT},
    }, ensure_ascii=False, separators=(",", ":"))
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{url}">
<link rel="alternate" type="application/atom+xml" title="医薬品供給ナビ 供給変更フィード" href="{SITE_ROOT}updates/feed.xml">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE_ROOT}og_updates.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="今日の供給変更をいつでも確認。医薬品供給ナビ">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{SITE_ROOT}og_updates.png">
<meta name="twitter:image:alt" content="今日の供給変更をいつでも確認。医薬品供給ナビ">
<script type="application/ld+json">{structured}</script>
<script src="../analytics.js"></script>
<style>
:root{{--blue:#2F63E8;--ink:#14213D;--sub:#5A6B8C;--line:#E1E9F7;--bg:#F4F8FF}}
*{{box-sizing:border-box}}body{{margin:0;font-family:"Hiragino Sans","Yu Gothic",Meiryo,sans-serif;color:var(--ink);background:var(--bg);line-height:1.75}}
.wrap{{max-width:820px;margin:auto;padding:22px 18px 56px}}header a,footer a{{color:var(--blue);font-weight:700;text-decoration:none}}
.crumb{{font-size:12px;color:var(--sub);margin:20px 0}}h1{{font-size:clamp(24px,5vw,38px);line-height:1.45;margin:0 0 12px}}
.lede{{color:var(--sub);font-size:14px}}.stats{{display:flex;gap:9px;flex-wrap:wrap;margin:24px 0}}
.stat{{background:#fff;border:1px solid var(--line);border-radius:999px;padding:7px 13px;font-size:12px;font-weight:700}}
.stat strong{{font-size:17px;margin-right:4px;color:var(--blue)}}ul{{list-style:none;padding:0;margin:24px 0}}
.change{{display:flex;justify-content:space-between;align-items:center;gap:14px;padding:14px 16px;background:#fff;border:1px solid var(--line);border-left:5px solid #9AA8C6;border-radius:12px;margin:8px 0}}
.change.ok{{border-left-color:#2FAE6E}}.change.limited{{border-left-color:#E8912F}}.change.stopped{{border-left-color:#E14D4D}}.change.ended{{border-left-color:#8A6A52}}
.change a{{color:var(--ink);font-weight:700;text-decoration:none}}.change a:hover{{color:var(--blue);text-decoration:underline}}
.transition{{flex:none;font-size:11.5px;color:var(--sub);text-align:right}}.cta{{margin:34px 0;padding:24px;border-radius:18px;background:linear-gradient(135deg,#1E44B8,#48A7E8);color:#fff}}
.cta h2{{font-size:19px;margin:0 0 6px}}.cta p{{font-size:13px;margin:0 0 14px;opacity:.92}}.cta a{{display:inline-block;background:#fff;color:var(--blue);padding:9px 18px;border-radius:999px;text-decoration:none;font-weight:800}}
.note,footer{{font-size:11.5px;color:var(--sub)}}footer{{text-align:center;margin-top:34px}}
@media(max-width:580px){{.change{{display:block}}.transition{{display:block;text-align:left;margin-top:6px}}}}
</style>
</head>
<body><div class="wrap">
<header><a href="../">＋ 医薬品供給ナビ</a></header>
<nav class="crumb"><a href="../">トップ</a> › <a href="index.html">供給変更履歴</a> › {date_jp}</nav>
<main>
<h1>{date_jp}に供給状況が変わった医薬品</h1>
<p class="lede">厚生労働省「医療用医薬品供給状況」の前回公表分との差分です。新規収載だけではなく、供給区分が実際に変わった品目を掲載しています。</p>
<div class="stats">{chips}</div>
<ul>{''.join(rows)}</ul>
<div class="cta"><h2>採用品目の変化をまとめて確認</h2><p>Web版では、採用品目CSVを端末内だけで読み込み、監視リストへ一括登録できます。</p><a href="../#f=changed">Web版で変更品目を見る</a></div>
<p class="note">本ページは厚生労働省の公表データをもとに自動生成した非公式情報です。実際の流通状況と異なる場合があります。医薬品の使用・変更は、必ず医師・薬剤師にご相談ください。</p>
</main>
<footer>{date_jp}時点｜<a href="../">医薬品供給ナビ</a>｜<a href="feed.xml">更新を購読（RSS）</a></footer>
</div><script data-goatcounter="https://kt1007.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script></body></html>
"""


def index_html(groups: dict[str, list[dict]]) -> str:
    links = []
    for date in sorted(groups, reverse=True):
        dt = datetime.strptime(date, "%Y-%m-%d")
        links.append(
            f'<li><a href="{date}.html">{dt.year}年{dt.month}月{dt.day}日</a>'
            f'<span>{len(groups[date])}品目</span></li>'
        )
    return f"""<!DOCTYPE html><html lang="ja"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>医薬品の供給変更履歴｜医薬品供給ナビ</title>
<meta name="description" content="厚生労働省公表データ上で供給状況が変わった医療用医薬品を日別に確認できます。">
<meta name="robots" content="index,follow,max-image-preview:large"><link rel="canonical" href="{SITE_ROOT}updates/index.html">
<link rel="alternate" type="application/atom+xml" title="医薬品供給ナビ 供給変更フィード" href="{SITE_ROOT}updates/feed.xml">
<script src="../analytics.js"></script>
<style>*{{box-sizing:border-box}}body{{margin:0;background:#F4F8FF;color:#14213D;font-family:"Hiragino Sans","Yu Gothic",Meiryo,sans-serif;line-height:1.7}}main{{max-width:760px;margin:auto;padding:34px 18px}}a{{color:#2F63E8}}h1{{font-size:30px}}p{{color:#5A6B8C}}ul{{list-style:none;padding:0}}li{{display:flex;justify-content:space-between;padding:14px 16px;margin:8px 0;background:#fff;border:1px solid #E1E9F7;border-radius:12px}}li a{{font-weight:700;text-decoration:none}}li span{{color:#5A6B8C;font-size:13px}}</style>
</head><body><main><a href="../">＋ 医薬品供給ナビ</a><h1>医薬品の供給変更履歴</h1><p>前回公表分から供給状況が変わった品目を日別に掲載しています。<a href="feed.xml">更新を購読（RSS）</a></p><ul>{''.join(links)}</ul></main><script data-goatcounter="https://kt1007.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script></body></html>"""


def atom_feed(groups: dict[str, list[dict]]) -> str:
    """供給変更をフィードリーダーで継続購読できるAtom 1.0として出力する。"""
    latest = max(groups)
    feed_url = f"{SITE_ROOT}updates/feed.xml"
    entries = []
    for date in sorted(groups, reverse=True):
        changes = groups[date]
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_jp = f"{dt.year}年{dt.month}月{dt.day}日"
        counts = Counter(status_key(change["to"]) for change in changes)
        summary = "、".join(
            f"{label}へ{counts[key]}品目"
            for key, label in STATUS_LABELS.items() if counts[key]
        )
        url = f"{SITE_ROOT}updates/{date}.html"
        title = f"{date_jp}の供給変更（{len(changes)}品目）"
        entries.append(
            "  <entry>\n"
            f"    <title>{xml_escape(title)}</title>\n"
            f"    <id>{url}</id>\n"
            f"    <link rel=\"alternate\" href=\"{url}\"/>\n"
            f"    <updated>{date}T00:00:00+09:00</updated>\n"
            f"    <summary type=\"text\">{xml_escape(summary)}</summary>\n"
            "  </entry>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="ja">\n'
        '  <title>医薬品供給ナビ 供給変更フィード</title>\n'
        f'  <id>{feed_url}</id>\n'
        f'  <link rel="self" type="application/atom+xml" href="{feed_url}"/>\n'
        f'  <link rel="alternate" href="{SITE_ROOT}updates/index.html"/>\n'
        f'  <updated>{latest}T00:00:00+09:00</updated>\n'
        '  <author><name>医薬品供給ナビ</name></author>\n'
        '  <subtitle>厚生労働省公表データ上で供給状況が変わった医薬品を日別に配信します。</subtitle>\n'
        + "\n".join(entries)
        + "\n</feed>\n"
    )


def sitemap_xml(dates: list[str]) -> str:
    latest = max(dates)
    body = [f"  <url><loc>{SITE_ROOT}updates/index.html</loc><lastmod>{latest}</lastmod></url>"]
    body.extend(f"  <url><loc>{SITE_ROOT}updates/{date}.html</loc><lastmod>{date}</lastmod></url>" for date in sorted(dates, reverse=True))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(body) + "\n</urlset>\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changes", default="status_changes.json")
    parser.add_argument("--site", default=".")
    args = parser.parse_args()
    site = Path(args.site)
    groups = load_changes(Path(args.changes))
    if not groups:
        raise SystemExit("有効な供給変更履歴がありません")
    out = site / "updates"
    out.mkdir(parents=True, exist_ok=True)
    keys_path = site / "items" / "keys.json"
    item_keys = set(json.loads(keys_path.read_text(encoding="utf-8"))) if keys_path.exists() else set()
    for date, changes in groups.items():
        (out / f"{date}.html").write_text(page_html(date, changes, item_keys), encoding="utf-8")
    (out / "index.html").write_text(index_html(groups), encoding="utf-8")
    (out / "feed.xml").write_text(atom_feed(groups), encoding="utf-8")
    (site / "sitemap-updates.xml").write_text(sitemap_xml(list(groups)), encoding="utf-8")
    print(f"供給変更ページ生成: {len(groups)}日分 / {sum(map(len, groups.values()))}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
