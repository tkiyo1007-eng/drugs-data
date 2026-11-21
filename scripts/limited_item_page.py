"""Presentation for limited-shipment item pages and previously shared pilot URLs."""
from html import escape
from pathlib import Path
import re
from shutil import copyfile

PILOT_KEYS = ("2646730Q1026", "3179106F1039", "2359110B1037")
SITE = "https://kyokyu-navi.jp/"


def comparison_html(rows, note):
    if len(rows) < 2:
        return ""
    body = []
    for index, (name, href, spec, maker, status, reason, release) in enumerate(rows):
        label = escape(name)
        if index == 0:
            label += '<small>表示中の品目</small>'
        else:
            label = f'<a href="{escape(href)}" data-dsn-event="related-item-open">{label}</a>'
        identity = "｜".join(escape(x) for x in (spec, maker) if x)
        body.append(f'<tr><th scope="row">{label}<small>{identity}</small></th>'
                    f'<td>{escape(status)}</td><td>{escape(reason)}</td><td>{escape(release)}</td></tr>')
    return ('<section id="compare"><h2>同成分・同剤形の供給状況</h2>'
            f'<p>{escape(note)}適応・規格・剤形の互換性は必ず添付文書と医師・薬剤師の判断でご確認ください。</p>'
            '<div class="table-scroll" tabindex="0" role="region" aria-label="規格別比較表、横にスクロールできます">'
            '<table><thead><tr><th scope="col">品名・規格</th><th scope="col">出荷対応</th>'
            '<th scope="col">公表理由</th><th scope="col">解除・解消見込み</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div></section>')


def overview_html(row, name, maker, release, source_date, imported, version, updated,
                  delist, notices, shortcuts, spec_note, discontinuation_labels=(), *,
                  historical_package_labels=None):
    # Keep strength units together even on narrow screens.
    name = re.sub(r"[０-９0-9]+(?:[．.][０-９0-9]+)?(?:[％%]|[ｍm][ｇg]|[μµ]g)|(?:ＬＤ|ＨＤ|LD|HD)$",
                  r'<span class="strength">\g<0></span>', escape(name))
    source_links = []
    for match in notices:
        notice = match["notice"]
        packaging = (historical_package_labels or {}).get(notice["url"])
        label = "更新された原文" if match["source_changed"] else "原文"
        if packaging and not match["source_changed"]:
            label = f"当時の包装別案内（{packaging}）"
        source_links.append(f'<a class="source-link" data-dsn-event="official-source-open" href="{escape(notice["url"])}">'
                            f'{escape(notice["maker"])}の{escape(label)} <small>文書 {escape(notice["announced_at"])}</small></a>')
    if any(m["notice"]["url"].startswith("https://www.torii.co.jp/iyakuDB/") for m in notices):
        source_links.append('<small>鳥居薬品のサイトで職種の確認があります。</small>')
    links = ''.join(f'<a href="#{anchor}">{label}</a>' for anchor, label in shortcuts)
    yj = escape(row.get("YJコード") or "")
    code = f'<span>YJ {yj}</span>' if yj else ''
    caution = '<span class="caution">薬価削除予定</span>' if delist else ''
    manufacturer_status = "".join(
        f'<p><strong class="caution">{escape(label)}</strong></p>' for label in discontinuation_labels)
    return f'''<div class="intro"><p class="maker">{escape(maker)}</p><h1>{name}</h1>
<p class="spec"><b>{escape(row.get("規格") or "規格の記載なし")}</b> {code}</p>{manufacturer_status}{spec_note}</div>
<section class="summary" data-version="{escape(version)}" data-spec-note="{int(bool(spec_note))}" data-source="{escape(source_date)}" data-imported="{escape(imported)}">
<h2>厚労省の供給状況</h2><div class="statusline"><strong class="status limited">{escape(row["供給状況"])}</strong>{caution}
<span>厚労省基準日 <time>{escape(source_date or "確認できません")}</time></span></div>
<dl class="facts"><div><dt>公表理由</dt><dd>{escape(row.get("理由") or "記載なし")}</dd></div>
<div><dt>解除・解消見込み</dt><dd>{escape(release or "記載なし")}</dd></div></dl>
<details><summary>出典と日付</summary><p>品目行の更新日 {escape(updated or "記載なし")}<br>サイト取込日 {escape(imported or "確認できません")}<br>
<a href="https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html" data-dsn-event="official-source-open">厚生労働省の公表ページ</a></p></details>
<p id="freshness" role="status">表示は上記基準日時点です。</p></section>
<div class="actions"><button type="button" id="share" hidden>この品目を共有</button><a href="#watchButton">監視リスト</a></div>
<p id="feedback" role="status"></p><textarea id="manualCopy" aria-label="コピー用の共有文" readonly hidden></textarea>
<nav class="jumps" aria-label="この品目の情報">{links}<a href="#itemDetails">品目の詳細</a></nav>
<div class="sources">{''.join(source_links)}</div>'''


def prepare_assets(site):
    source = Path(__file__).resolve().parents[1] / "items"
    dest = site / "items"
    if dest.resolve() != source:
        (dest / "trial").mkdir(parents=True, exist_ok=True)
        for asset in ("trial/trial.css", "trial/trial.js", "limited-detail.css"):
            copyfile(source / asset, dest / asset)


def write_pilot_links(folder, entries):
    """Previously shared URLs resolve to the current canonical item, including after recovery."""
    folder.mkdir(parents=True, exist_ok=True)
    available = {e["key"]: e for e in entries}
    items = []
    for key in PILOT_KEYS:
        path = folder / f"{key}.html"
        if key not in available:
            path.unlink(missing_ok=True)
            continue
        name = escape(available[key]["display_name"])
        href = "../" + key + ".html"
        path.write_text(f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,follow">
<link rel="canonical" href="{SITE}items/{key}.html"><meta http-equiv="refresh" content="0;url={href}">
<title>{name}｜医薬品供給ナビ</title></head><body><main><a href="{href}">{name}の品目ページを開く</a></main></body></html>
''', encoding="utf-8")
        items.append(f'<li><a href="{href}">{name}</a></li>')
    (folder / "index.html").write_text(f'''<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,follow">
<link rel="stylesheet" href="trial.css"><title>品目ページのご案内｜医薬品供給ナビ</title></head><body>
<header><div class="bar"><a class="brand" href="../../"><span aria-hidden="true">✚</span>医薬品供給ナビ</a></div></header>
<main class="intro"><h1>品目ページのご案内</h1><p>試用版のデザインを限定出荷の品目ページに採用しました。</p>
<ul>{''.join(items)}</ul><a href="../limited.html">限定出荷の品目一覧を開く</a></main></body></html>
''', encoding="utf-8")
