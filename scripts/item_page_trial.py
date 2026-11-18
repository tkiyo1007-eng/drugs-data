"""Opt-in comparison of three item pages. The regular generator supplies the verified data."""

from html import escape
from pathlib import Path
import re
from shutil import copyfile

TRIAL_KEYS = ("2646730Q1026", "3179106F1039", "2359110B1037")
SITE = "https://kyokyu-navi.jp/"


def layout(title, content, canonical=""):
    canonical_tag = f'<link rel="canonical" href="{escape(canonical)}">' if canonical else ""
    return f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,follow">
<title>{escape(title)}｜医薬品供給ナビ</title>{canonical_tag}
<link rel="icon" href="../../icon-192.png"><link rel="stylesheet" href="trial.css">
<script defer src="trial.js"></script></head><body>
<a class="skip" href="#main">本文へ</a>
<header><div class="bar"><a class="brand" href="../../"><span aria-hidden="true">✚</span>医薬品供給ナビ</a>
<a href="index.html">試用する品目</a></div></header>
<main id="main">{content}</main></body></html>
'''


def comparison_html(rows):
    if len(rows) < 2:
        return ""
    body = []
    for index, (name, href, spec, status, reason, release) in enumerate(rows):
        label = escape(name)
        if index == 0:
            label += '<small>表示中の品目</small>'
        else:
            label = f'<a href="{escape(href)}">{label}</a>'
        body.append(f'<tr><th scope="row">{label}<small>{escape(spec)}</small></th>'
                    f'<td>{escape(status)}</td><td>{escape(reason)}</td><td>{escape(release)}</td></tr>')
    return ('<section id="compare"><h2>同成分・同剤形の供給状況</h2>'
            '<p>各製品・規格の厚労省公表値です。切替の可否や納入先の在庫は別途確認が必要です。</p>'
            '<div class="table-scroll" tabindex="0" role="region" aria-label="規格別比較表、横にスクロールできます">'
            '<table><thead><tr><th scope="col">品名・規格</th><th scope="col">出荷対応</th>'
            '<th scope="col">公表理由</th><th scope="col">解除・解消見込み</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></section>')


def write_page(folder, item, source_date, imported, version_id, notices_html, topics, comparison):
    key = item["key"]
    raw_name = item["display_name"]
    # Keep concentrations and strength suffixes together on narrow screens.
    name = re.sub(r"[０-９0-9]+(?:[．.][０-９0-9]+)?[％%]|(?:ＬＤ|ＨＤ|LD|HD)$",
                  r'<span class="strength">\g<0></span>', escape(raw_name))
    status = escape(item["supply_raw"] or "記載なし")
    canonical = SITE + "items/" + key + ".html"
    day = escape(source_date or "確認できません")
    historical = ""
    if topics:
        links = "".join(f'<li><a href="../../topics/{escape(t["slug"])}.html">{escape(t["title"])}</a>'
                        f'<small>掲載 {escape(t["date"])}</small></li>' for t in topics)
        historical = f'<section id="history"><h2>過去の案内・対応記録</h2><ul>{links}</ul></section>'
    compare = comparison_html(comparison)
    nav = ['<a href="#manufacturerNoticesTitle">メーカー案内</a>'] if notices_html else []
    if 'id="trialAlternatives"' in notices_html:
        nav.append('<a href="#trialAlternatives">原文の代替候補</a>')
    if historical:
        nav.append('<a href="#history">過去の記録</a>')
    if compare:
        nav.append('<a href="#compare">規格を比較</a>')
    shortcuts = ('<nav class="jumps" aria-label="この品目の情報">' + ''.join(nav) + '</nav>') if nav else ""
    source_links = []
    for match in item["manufacturer_notices"]:
        n = match["notice"]
        label = "更新された原文" if match["source_changed"] else "原文"
        source_links.append(f'<a class="source-link" href="{escape(n["url"])}">{escape(n["maker"])}の{label}'
                            f' <small>文書 {escape(n["announced_at"])}</small></a>')
        if n["url"].startswith("https://www.torii.co.jp/iyakuDB/"):
            source_links.append('<small>鳥居薬品のサイトで職種の確認があります。</small>')
    summary_date = escape(item["updated"] or "記載なし")
    caution = '<span class="caution">薬価削除予定</span>' if item["delist"] else ""
    content = f'''<p class="trail"><a href="index.html">試用品目</a> / 品目詳細</p>
<article><div class="intro"><p class="maker">{escape(item["maker"])}</p><h1>{name}</h1>
<p class="spec">{escape(item["spec"])} <span>YJ {escape(key)}</span></p></div>
<section class="summary" data-version="{escape(str(version_id))}" data-source="{escape(source_date)}" data-imported="{escape(imported)}">
<h2>厚労省の供給状況</h2><div class="statusline"><strong class="status {escape(item["status"])}">{status}</strong>{caution}
<span>厚労省基準日 <time>{day}</time></span></div>
<dl class="facts"><div><dt>公表理由</dt><dd>{escape(item["reason"] or "記載なし")}</dd></div>
<div><dt>解除・解消見込み</dt><dd>{escape(item["release"] or "記載なし")}</dd></div></dl>
<details><summary>出典と日付</summary><p>品目行の更新日 {summary_date}<br>サイト取込日 {escape(imported)}<br>
<a href="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html">厚生労働省の公表ページ</a></p></details>
<p id="freshness" role="status">表示は上記基準日時点です。</p></section>
<div class="actions"><button type="button" id="share" hidden>この品目を共有</button>
<a href="../{key}.html">従来の表示</a></div><p id="feedback" role="status"></p>
<textarea id="manualCopy" aria-label="コピー用の共有文" readonly hidden></textarea>
{shortcuts}
<div class="sources">{''.join(source_links)}</div>
{notices_html}{historical}{compare}
</article><footer><a href="../{key}.html">品目の全情報・監視リスト</a><a href="index.html">試用品目の一覧</a></footer>'''
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{key}.html").write_text(layout(raw_name + "の供給状況（試用版）", content, canonical), encoding="utf-8")


def write_index(folder: Path, entries):
    items = {item["key"]: item for item in entries}
    cards = []
    for key in TRIAL_KEYS:
        if key not in items:
            (folder / f"{key}.html").unlink(missing_ok=True)
            continue
        item = items[key]
        name = escape(item["name"])
        cards.append(f'<li><h2>{name}</h2><p>{escape(item["maker"])} · {escape(item["spec"])}</p>'
                     f'<div class="actions"><a class="primary" href="{key}.html" aria-label="{name}の試用版">試用版</a>'
                     f'<a href="../{key}.html" aria-label="{name}の従来版">従来版</a></div></li>')
    if not cards and not folder.is_dir():
        return
    folder.mkdir(parents=True, exist_ok=True)
    assets = Path(__file__).resolve().parents[1] / "items" / "trial"
    if folder.resolve() != assets:
        for filename in ("trial.css", "trial.js"):
            copyfile(assets / filename, folder / filename)
    content = ('<div class="intro"><h1>品目ページの使い比べ</h1>'
               '<p>同じ規格の供給状況を、2つの画面で確認できます。</p></div>'
               f'<ul class="choices">{"".join(cards)}</ul>')
    (folder / "index.html").write_text(layout("品目ページの使い比べ", content), encoding="utf-8")
