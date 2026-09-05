#!/usr/bin/env python3
"""手動キュレーションしたニュース・注目製品から検索向け静的ページを生成する。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote

SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/"
MHLW_SUPPLY_URL = "https://iyakuhin-kyokyu.mhlw.go.jp/public/supply-status-list"
PMDA_SEARCH_URL = "https://www.pmda.go.jp/PmdaSearch/iyakuSearch/"
PMDA_RECALL_URL = "https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/recall-info/0002.html"
GUIDE_SLUG = "how-to-check-drug-supply"
TEMPLATE_UPDATED_AT = "2026-08-28"
PRODUCT_TEMPLATE_UPDATED_AT = "2026-09-06"
STATUS = {
    "ok": ("通常出荷", "#227D4F", "#E7F6EE", 0),
    "limited": ("限定出荷", "#9F5E11", "#FCF0DF", 1),
    "stopped": ("供給停止", "#B03434", "#FBE7E7", 2),
    "ended": ("販売中止", "#7A5E49", "#F2EBE4", 3),
}
SUPPLY_METADATA_RE = re.compile(
    r"^解除/解消見込み:\s*(.*?)\s*/\s*出荷量状況:\s*(.*)$")

# Search Consoleで実際に表示された検索意図だけを、既存の注目製品ページで補う。
# 文面は原因や代替適否を推測せず、CSVの公表値と公式確認手順へ誘導する。
PRODUCT_SEARCH_INTENTS = {
    "lulicon-cream": {
        "heading": "ルリコンクリームの出荷調整情報を確認する方へ",
        "intro": ("『なぜ』と検索する方に向け、厚生労働省公表データの供給区分・理由欄・"
                  "品目行の更新日を下にそのまま示します。表示されていない原因を推測で補いません。"),
        "alternative": True,
    },
    "zictor-tape-75mg": {
        "heading": "ジクトルテープの代替を検討する前に",
        "intro": ("現在の供給区分・理由・解除見込みを確認してください。品目詳細に"
                  "『同成分・同剤形』が表示される場合も、代替適否や実在庫を示すものではありません。"),
        "alternative": True,
    },
    "caduet": {
        "heading": "カデュエット配合錠1〜4番を規格別に確認",
        "intro": ("カデュエット配合錠は1〜4番で成分量が異なります。"
                  "各番号の現在区分と品目行の更新日を同じページで比較できます。"),
        "alternative": False,
    },
}
for _caduet_number in range(1, 5):
    PRODUCT_SEARCH_INTENTS[f"caduet-{_caduet_number}"] = {
        "heading": "カデュエット配合錠の出荷調整情報を確認する方へ",
        "intro": ("カデュエット配合錠は番号ごとに成分量が異なります。"
                  "検索語だけで一括判断せず、対象番号の現在区分と更新日を確認してください。"),
        "alternative": False,
    }


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def ld_json(value: object) -> str:
    """HTMLのscript要素を閉じられない形でJSON-LDを埋め込む。"""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def norm(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).lower().strip()


def supply_metadata_values(row: dict[str, str]) -> dict[str, str]:
    """供給CSVの直接列と、旧互換の複合列から公表値を取り出す。"""
    values = {}
    for field in ("解除・解消見込み", "出荷量状況"):
        value = str(row.get(field) or "").strip()
        if value:
            values[field] = value
    legacy = str(row.get("代替候補") or "").strip()
    match = SUPPLY_METADATA_RE.match(legacy)
    if match:
        values.setdefault("解除・解消見込み", match.group(1).strip())
        values.setdefault("出荷量状況", match.group(2).strip())
    return values


def map_status(value: object) -> str:
    text = str(value or "")
    if "停止" in text:
        return "stopped"
    if "限定" in text:
        return "limited"
    if "中止" in text:
        return "ended"
    return "ok"


def item_key(row: dict[str, str]) -> str:
    yj = re.sub(r"[^0-9A-Za-z]", "", row.get("YJコード", "") or "")
    if yj:
        return yj
    seed = ((row.get("商品名") or "") + "|" + (row.get("規格") or "")).encode()
    return "x" + hashlib.sha1(seed).hexdigest()[:12]


def is_delist(row: dict[str, str]) -> bool:
    return ("薬価削除予定" in (row.get("代替候補") or "")
            or bool((row.get("経過措置期限") or "").strip()))


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} はオブジェクトである必要があります")
    return value


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [row for row in csv.DictReader(handle) if (row.get("商品名") or "").strip()]


def search_rows(rows: list[dict[str, str]], query: object) -> list[dict[str, str]]:
    terms = norm(query).split()
    if not terms:
        return []
    found = []
    for row in rows:
        haystack = norm(" ".join((row.get("商品名", ""), row.get("一般名", ""),
                                  row.get("製造メーカー", ""), row.get("販売メーカー", ""),
                                  row.get("YJコード", ""))))
        if all(term in haystack for term in terms):
            found.append(row)
    return sorted(found, key=lambda row: (-STATUS[map_status(row.get("供給状況"))][3],
                                          row.get("商品名") or ""))


def topic_related_rows(rows: list[dict[str, str]], topic: dict) -> list[dict[str, str]]:
    """単一または複数の検索語から、ニュースに関係する品目を重複なく返す。"""
    raw_queries = topic.get("queries")
    queries = raw_queries if isinstance(raw_queries, list) else [topic.get("query")]
    related: dict[str, dict[str, str]] = {}
    for query in queries:
        for row in search_rows(rows, query):
            related[item_key(row)] = row
    return sorted(related.values(), key=lambda row: (
        -STATUS[map_status(row.get("供給状況"))][3], row.get("商品名") or ""))


def normalize_date(value: object) -> str:
    text = str(value or "").strip().replace("/", "-").replace(".", "-")
    return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else ""


def common_head(title: str, description: str, canonical: str, kind: str,
                structured: list[dict]) -> str:
    graph = {"@context": "https://schema.org", "@graph": structured}
    return f"""<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="{kind}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE_ROOT}og_image.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(description)}">
<meta name="twitter:image" content="{SITE_ROOT}og_image.png">
<script type="application/ld+json">{ld_json(graph)}</script>
<script src="../analytics.js"></script>"""


STYLE = """
:root{--blue:#2F63E8;--ink:#14213D;--sub:#5A6B8C;--line:#E3EAF6}
*{box-sizing:border-box}body{margin:0;font-family:"Hiragino Sans","Yu Gothic",Meiryo,sans-serif;color:var(--ink);background:#F6F9FE;line-height:1.75}
.wrap{max-width:900px;margin:auto;padding:22px 18px 60px}.site a,.crumb a,a{color:var(--blue)}.site{font-weight:800;margin-bottom:14px}.crumb{font-size:12px;color:var(--sub);margin-bottom:18px}
.hero,.card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:26px 24px;box-shadow:0 10px 32px rgba(47,99,232,.06)}
.eyebrow{font-size:11px;font-weight:900;letter-spacing:.08em;color:var(--blue)}h1{font-size:clamp(23px,4vw,34px);line-height:1.45;margin:7px 0 12px}h2{font-size:19px;margin:34px 0 12px}.lede{font-size:15px;color:var(--sub)}
.points{margin:18px 0 0;padding:16px 20px 16px 38px;background:#F2F6FE;border-radius:14px}.points li+li{margin-top:6px}.source{margin-top:18px;font-size:13px}.source a{font-weight:700}
.summary{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}.chip,.tag{display:inline-block;padding:5px 11px;border-radius:999px;font-size:12px;font-weight:800}.tag{margin-left:7px}
.products{display:grid;gap:9px}.product{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(120px,.8fr) auto;gap:12px;align-items:center;padding:13px 15px;background:#fff;border:1px solid var(--line);border-radius:13px}.product a{font-weight:750;text-decoration:none}.meta{font-size:12px;color:var(--sub)}
.intent{margin-top:28px;padding:22px;border-radius:16px;background:#FFF;border:1px solid var(--line)}.intent h2{margin:0 0 9px}.intent h3{font-size:15px;margin:20px 0 8px}.evidence{display:grid;gap:9px;margin-top:14px}.evidence-item{padding:13px 15px;border-radius:12px;background:#F6F9FE;border:1px solid var(--line)}.evidence-item strong{display:block}.evidence-item span{display:block;font-size:12.5px;color:var(--sub);margin-top:3px}.safety{padding:12px 14px;border-radius:12px;background:#FFF4E8;border:1px solid #F1C69E;color:#69360E;font-size:12.5px}.official-links{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}.official-links a{font-weight:700}
.page-share{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:20px 0}.page-share button{min-height:44px;padding:9px 18px;border:1px solid #B9C9EA;border-radius:999px;background:#fff;color:var(--blue);font:inherit;font-weight:800;cursor:pointer}.page-share button:focus-visible{outline:3px solid rgba(47,99,232,.35);outline-offset:2px}.page-share-status{margin:0;min-height:1.7em;font-size:12px;color:var(--sub)}
.cta{margin-top:28px;padding:22px;border-radius:16px;background:linear-gradient(135deg,#2F63E8,#4F80F4);color:#fff}.cta a{display:inline-block;background:#fff;border-radius:999px;padding:9px 18px;text-decoration:none;font-weight:800;margin-top:8px}.list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.list a{display:block;background:#fff;border:1px solid var(--line);border-radius:13px;padding:14px;text-decoration:none;font-weight:750}.list small{display:block;color:var(--sub);font-weight:500;margin-top:4px}
.note,footer{font-size:12px;color:var(--sub)}footer{text-align:center;margin-top:36px}footer a{color:var(--sub)}
@media(max-width:640px){.hero,.card{padding:21px 18px}.product{grid-template-columns:1fr}.tag{margin:5px 5px 0 0}}
"""

PRODUCT_ENTRY_STYLE = """
.product-entry{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:18px}.product-entry a{display:inline-flex;align-items:center;min-height:44px;font-size:14px;font-weight:700;text-underline-offset:3px}.product-entry a:first-child{padding:8px 16px;border-radius:12px;background:#1B3FA0;color:#fff;text-decoration:none}.product-entry a:focus-visible{outline:3px solid #2F63E8;outline-offset:3px}
"""


def analytics_footer() -> str:
    return '<script data-goatcounter="https://kt1007.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>'


def share_control(label: str = "このページを共有") -> str:
    """analytics.jsの固定イベントだけを使う静的ページ共通の共有UI。"""
    return (f'<div class="page-share"><button type="button" data-dsn-share-page>'
            f'{esc(label)}</button><p class="page-share-status" role="status" '
            'aria-live="polite"></p></div>')


def row_link(row: dict[str, str], generated_keys: set[str]) -> str:
    key = item_key(row)
    if key in generated_keys:
        return f"../items/{key}.html"
    return "../#item=" + quote(key, safe="")


def product_row_link(product: dict, row: dict[str, str],
                     generated_keys: set[str]) -> str:
    """集約ページで依存先の番号別ページがある場合は、そちらを巡回対象にする。"""
    if product.get("slug") == "caduet":
        match = re.search(r"([1-4])番", norm(row.get("商品名")))
        if match:
            return f"caduet-{match.group(1)}.html"
    return row_link(row, generated_keys)


def absolute_product_row_url(href: str) -> str:
    """products/配下の相対リンクをJSON-LD用の公開URLにする。"""
    if href.startswith("../"):
        return SITE_ROOT + href.removeprefix("../")
    return SITE_ROOT + "products/" + href


def product_rows_html(rows: list[dict[str, str]], generated_keys: set[str],
                      lifecycle: dict[str, dict], product: dict | None = None) -> str:
    cards = []
    for row in rows:
        status = map_status(row.get("供給状況"))
        label, color, bg, _ = STATUS[status]
        key = item_key(row)
        future = lifecycle.get(key, {}).get("state") == "discontinuation_announced"
        badges = f'<span class="tag" style="color:{color};background:{bg}">{label}</span>'
        if is_delist(row):
            badges += '<span class="tag" style="color:#7A5E49;background:#F2EBE4">薬価削除予定</span>'
        if future:
            badges += '<span class="tag" style="color:#A03030;background:#FBE7E7">販売中止予定</span>'
        maker = (row.get("販売メーカー") or row.get("製造メーカー") or "").strip()
        spec = (row.get("規格") or "").strip()
        updated = (row.get("更新日") or "").replace("/", "-")
        href = (product_row_link(product, row, generated_keys)
                if product else row_link(row, generated_keys))
        cards.append(f"""<div class="product">
  <div><a href="{href}" data-dsn-event="related-item-open">{esc(row.get('商品名'))}</a><div class="meta">{esc(spec)}</div></div>
  <div class="meta">{esc(maker)}<br>更新 {esc(updated)}</div><div>{badges}</div>
</div>""")
    return "".join(cards)


def product_seo_metadata(product: dict, rows: list[dict[str, str]], suffix: str) -> tuple[str, str]:
    """実際の検索意図に応えるが、現在区分や原因をタイトルで推測しない。"""
    slug, label = product["slug"], product["label"]
    if slug == "lulicon-cream":
        current = STATUS[map_status(rows[0].get("供給状況"))][0]
        release = supply_metadata_values(rows[0]).get("解除・解消見込み", "記載なし")
        if current in {"限定出荷", "供給停止", "販売中止"}:
            title = f"{label}はなぜ{current}？公表理由と供給状況｜医薬品供給ナビ"
        else:
            title = f"{label}の現在の供給状況と公表理由｜医薬品供給ナビ"
        description = (f"{label}の現在の供給区分、公表上の理由、解除・解消見込み「{release}」、品目行の更新日を確認できます。"
                       "同成分・同剤形は確認候補として掲載し、代替適否や実在庫は示しません。")
        return title, description
    if slug == "zictor-tape-75mg":
        release = supply_metadata_values(rows[0]).get("解除・解消見込み", "記載なし")
        return (
            f"{label}の出荷調整・供給状況｜代替検討前の確認事項｜医薬品供給ナビ",
            (f"{label}の現在の供給区分、公表上の理由、解除・解消見込み「{release}」を確認。"
             "候補表示がある場合も、適応・規格・実在庫を専門職と確認してください。"),
        )
    if slug == "caduet":
        return (
            "カデュエット配合錠1〜4番の供給状況｜規格別に出荷調整情報を確認｜医薬品供給ナビ",
            ("カデュエット配合錠1〜4番の現在の供給区分と品目行の更新日を規格別に比較。"
             "番号ごとに成分量が異なるため、出荷調整の有無は対象品目ごとに確認します。"),
        )
    if slug.startswith("caduet-"):
        return (
            f"{label}の現在の供給状況｜出荷調整情報を確認｜医薬品供給ナビ",
            (f"{label}の現在の供給区分と品目行の更新日を確認できます。"
             "番号ごとに成分量が異なるため、対象規格を分けて掲載しています。"),
        )
    return (
        f"{label}の{suffix}｜医薬品供給ナビ",
        (f"{label}に該当する{len(rows)}品目の通常出荷・限定出荷・供給停止・販売中止予定を"
         "メーカー別に確認できます。厚生労働省公表データを毎日更新。"),
    )


def product_intent_html(product: dict, rows: list[dict[str, str]],
                        generated_keys: set[str]) -> str:
    """需要が確認できた製品だけに、推測を含まない検索意図別の説明を付ける。"""
    intent = PRODUCT_SEARCH_INTENTS.get(product["slug"])
    if not intent:
        return ""
    evidence = []
    for row in rows:
        reason = str(row.get("理由") or "").strip()
        if norm(reason) in {"", "-", "－", "7.-", "7.－"}:
            reason = "記載なし"
        updated = normalize_date(row.get("更新日")) or "確認できません"
        release = supply_metadata_values(row).get("解除・解消見込み", "記載なし")
        href = product_row_link(product, row, generated_keys)
        evidence.append(
            f'<div class="evidence-item"><strong><a href="{href}" '
            f'data-dsn-event="related-item-open">'
            f'{esc(row.get("商品名"))}</a></strong>'
            f'<span>厚労省公表の供給区分：{esc(row.get("供給状況") or "確認できません")}</span>'
            f'<span>公表上の理由：{esc(reason)}</span>'
            f'<span>解除・解消見込み：{esc(release)}</span>'
            f'<span>この品目行の更新日：{esc(updated)}</span></div>'
        )
    alternative = ""
    if intent["alternative"]:
        alternative = (
            '<p class="safety"><strong>代替薬の推薦ではありません。</strong> '
            '「同成分・同剤形」は公開データから機械的に範囲を絞った確認候補です。'
            '適応症、規格・用量、投与経路、製剤特性、患者の状態、実在庫を確認し、'
            '医師・薬剤師等の専門職が判断してください。</p>'
        )
    comparison = ""
    if product["slug"].startswith("caduet-"):
        comparison = ('<p><a href="caduet.html" data-dsn-event="related-item-open">'
                      'カデュエット配合錠1〜4番の規格別比較を見る</a></p>')
    return f'''<section class="intent">
<h2>{esc(intent["heading"])}</h2><p>{esc(intent["intro"])}</p>
<h3>現在の公表内容</h3><div class="evidence">{"".join(evidence)}</div>
<p class="note">「理由」は厚生労働省公表データの記載をそのまま表示しています。
品目行の更新日が古い場合や、実際の受注可否を確認するときは公式システム・メーカー・卸の最新情報もご確認ください。</p>
{alternative}
{comparison}
<div class="official-links"><a href="{MHLW_SUPPLY_URL}" target="_blank" rel="noopener" data-dsn-event="official-source-open">厚生労働省の公式システムで確認</a>
<a href="../guides/{GUIDE_SLUG}.html">出荷調整情報の確認手順</a></div>
</section>'''


def guide_page(updated_at: str) -> str:
    """供給情報の出典と代替検討の境界を説明する、1本だけの恒久ガイド。"""
    canonical = f"{SITE_ROOT}guides/{GUIDE_SLUG}.html"
    title = "医薬品の出荷調整・限定出荷を公式情報で確認する方法｜医薬品供給ナビ"
    description = ("医薬品の出荷調整・限定出荷について、厚生労働省の供給状況、メーカー公式案内、"
                   "PMDA情報の役割と、代替検討前に確認する項目を整理します。")
    article = {
        "@type": "Article", "headline": title, "description": description,
        "datePublished": TEMPLATE_UPDATED_AT, "dateModified": updated_at,
        "inLanguage": "ja", "mainEntityOfPage": canonical,
        "author": {"@type": "Organization", "name": "医薬品供給ナビ運営者"},
        "publisher": {"@type": "Organization", "name": "医薬品供給ナビ"},
    }
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "供給情報の確認ガイド", "item": canonical},
    ]}
    return f'''<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, "article", [article, breadcrumb])}<style>{STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header>
<nav class="crumb"><a href="../">トップ</a> › 供給情報の確認ガイド</nav><main>
<article class="hero"><p class="eyebrow">EVERGREEN GUIDE</p><h1>医薬品の出荷調整・限定出荷を公式情報で確認する方法</h1>
<p class="lede">「なぜ出荷調整なのか」「代替をどう探すか」「PMDAで確認できるか」を、出典の役割を分けて整理します。</p>
{share_control("この確認ガイドを共有")}</article>
<section class="intent"><h2>1. 現在の供給区分は厚生労働省データで確認</h2>
<p>厚生労働省「医療用医薬品供給状況」では、通常出荷・限定出荷・供給停止などの現在区分、理由、更新日を品目単位で確認します。医薬品供給ナビもこの公表値を意味を変えずに表示します。</p>
<div class="official-links"><a href="{MHLW_SUPPLY_URL}" target="_blank" rel="noopener" data-dsn-event="official-source-open">厚生労働省の公式システムを開く</a></div></section>
<section class="intent"><h2>2. 「なぜ」は理由欄とメーカー原文を分けて確認</h2>
<p>公表データの理由欄は「需要増」「製造上の問題」などの区分であり、個別事情のすべてを説明するとは限りません。対象包装、開始時期、解除見込みはメーカー公式案内の原文も確認し、記載のない原因を推測しないことが重要です。</p>
<p><a href="../products/lulicon-cream.html" data-dsn-event="related-item-open">ルリコンクリーム1%の公表理由と供給状況を見る</a></p></section>
<section class="intent"><h2>3. 「代替」は同成分・同剤形だけで決めない</h2>
<p class="safety"><strong>同成分・同剤形の一覧は代替薬の推薦ではありません。</strong> 適応症、規格・用量、投与経路、製剤特性、患者の状態、実在庫を確認し、医師・薬剤師等の専門職が判断してください。</p>
<p><a href="../products/zictor-tape-75mg.html" data-dsn-event="related-item-open">ジクトルテープ75mgの供給状況と代替検討前の確認事項を見る</a></p></section>
<section class="intent"><h2>4. PMDAと供給情報の役割は異なる</h2>
<p>PMDAの医療用医薬品情報検索は、添付文書・インタビューフォーム・安全性情報を確認する場所です。現在の供給区分は厚生労働省の供給状況システム、個別の出荷案内はメーカー公式資料を確認します。自主回収などの安全性情報はPMDA情報もあわせて確認してください。</p>
<div class="official-links"><a href="{PMDA_SEARCH_URL}" target="_blank" rel="noopener" data-dsn-event="official-source-open">PMDAの医療用医薬品情報検索を開く</a>
<a href="{PMDA_RECALL_URL}" target="_blank" rel="noopener" data-dsn-event="official-source-open">PMDAの医薬品回収情報を確認</a>
<a href="../topics/alelock-5mg-class2-recall-20260817.html">アレロック錠5の自主回収情報を見る</a></div></section>
<section class="intent"><h2>5. 商品名・規格を特定してから確認</h2>
<p>配合剤や複数規格は、同じブランド名でも成分量が異なります。商品名だけで一括判断せず、YJコードや規格まで確認してください。</p>
<p><a href="../#q={quote("カデュエット配合錠", safe="")}" data-dsn-event="search-cta-open">カデュエット配合錠の全規格をWeb版で確認</a></p></section>
<p class="note">本ガイドは情報源の使い分けを説明するもので、処方・調剤・代替選定その他の医療上の判断を行うものではありません。実際の入手可否は卸・メーカーにもご確認ください。</p>
</main><footer>最終更新：{esc(updated_at)}｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>'''


def topic_page(topic: dict, related: list[dict[str, str]], generated_keys: set[str],
               lifecycle: dict[str, dict], updated_at: str) -> str:
    slug = topic["slug"]
    canonical = f"{SITE_ROOT}topics/{slug}.html"
    title = f"{topic['title']}｜医薬品供給ナビ"
    description = str(topic["lede"])
    published = normalize_date(topic["date"])
    article = {"@type": "Article", "headline": topic["title"], "description": description,
               "datePublished": published, "dateModified": normalize_date(updated_at) or published,
               "mainEntityOfPage": canonical,
               "author": {"@type": "Organization", "name": "医薬品供給ナビ運営者"},
               "publisher": {"@type": "Organization", "name": "医薬品供給ナビ"}}
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "話題のニュース", "item": SITE_ROOT + "topics/index.html"},
        {"@type": "ListItem", "position": 3, "name": topic["title"], "item": canonical}]}
    points = "".join(f"<li>{esc(point)}</li>" for point in topic.get("points") or [])
    source = topic["source"]
    related_html = ""
    if related:
        related_html = (f'<h2>関連品目の現在の供給状況（{len(related)}品目）</h2>'
                        '<p class="note">厚生労働省公表データの現在区分です。ニュース本文の将来予定とは別にご確認ください。</p>'
                        f'<div class="products">{product_rows_html(related, generated_keys, lifecycle)}</div>')
    return f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'article', [article, breadcrumb])}<style>{STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header>
<nav class="crumb"><a href="../">トップ</a> › <a href="index.html">話題のニュース</a> › {esc(topic['tag'])}</nav><main>
<article class="hero"><p class="eyebrow">{esc(topic['tag'])}｜{esc(topic['date'])}</p><h1>{esc(topic['title'])}</h1>
<p class="lede">{esc(topic['lede'])}</p>{f'<ul class="points">{points}</ul>' if points else ''}
<p class="source">出典：<a href="{esc(source['url'])}" target="_blank" rel="noopener" data-dsn-event="official-source-open">{esc(source['name'])}</a></p>
{share_control("この記事を共有")}</article>
{related_html}
<div class="cta"><strong>最新の供給状況を検索</strong><p>医薬品名・メーカー名・YJコードから、厚生労働省公表データを確認できます。</p><a href="../" data-dsn-event="topic-to-search">Web版で検索する</a></div>
</main><footer><p>ニュースは一次情報または信頼できる報道をもとに編集しています。必ず出典原文をご確認ください。</p><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


def product_page(product: dict, rows: list[dict[str, str]], generated_keys: set[str],
                 lifecycle: dict[str, dict]) -> tuple[str, str]:
    slug, label = product["slug"], product["label"]
    canonical = f"{SITE_ROOT}products/{slug}.html"
    suffix = ("規格別供給状況" if slug == "caduet" else
              "メーカー別供給状況" if len(rows) > 1 else "供給状況")
    title, description = product_seo_metadata(product, rows, suffix)
    lastmod = max((normalize_date(row.get("更新日")) for row in rows), default="")
    counts: dict[str, int] = {key: 0 for key in STATUS}
    for row in rows:
        counts[map_status(row.get("供給状況"))] += 1
    summary = "".join(f'<span class="chip" style="color:{STATUS[key][1]};background:{STATUS[key][2]}">{STATUS[key][0]} {count}</span>'
                      for key, count in counts.items() if count)
    item_list = {"@type": "ItemList", "name": label,
                 "numberOfItems": len(rows), "itemListElement": [
                     {"@type": "ListItem", "position": index,
                      "name": row.get("商品名"),
                      "url": absolute_product_row_url(
                          product_row_link(product, row, generated_keys))}
                     for index, row in enumerate(rows, 1)]}
    collection = {"@type": "CollectionPage", "name": title, "description": description,
                  "url": canonical, "mainEntity": item_list}
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "注目製品", "item": SITE_ROOT + "products/index.html"},
        {"@type": "ListItem", "position": 3, "name": label, "item": canonical}]}
    query_link = "../#q=" + quote(product["query"], safe="")
    lede = (f"1〜4番の{len(rows)}品目を、規格ごとの現在の供給区分と更新日でまとめています。"
            if slug == "caduet" else
            f"該当する{len(rows)}品目を、現在の供給区分とメーカーごとにまとめています。")
    body = f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [collection, breadcrumb])}<style>{STYLE}{PRODUCT_ENTRY_STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header>
<nav class="crumb" aria-label="パンくず"><a href="../">トップ</a> › <a href="index.html">注目製品</a> › {esc(label)}</nav><main>
<section class="hero"><p class="eyebrow">CURRENT SUPPLY STATUS</p><h1>{esc(label)}の{suffix}</h1>
<p class="lede">{lede}</p><div class="summary">{summary}</div>
<nav class="product-entry" aria-label="この製品の供給情報を確認">
<a href="{esc(query_link)}" data-dsn-event="search-cta-open">この製品をWeb版で検索</a>
<a href="{MHLW_SUPPLY_URL}" target="_blank" rel="noopener" data-dsn-event="official-source-open">厚労省の原典で確認</a>
<a href="../items/limited.html">限定出荷の品目一覧</a>
</nav>
{share_control("この供給状況を共有")}</section>
<h2>該当品目</h2><div class="products">{product_rows_html(rows, generated_keys, lifecycle, product)}</div>
{product_intent_html(product, rows, generated_keys)}
<div class="cta"><strong>Web版で絞り込んで確認</strong><p>公表理由やメーカー案内を確認できます。同成分・同剤形の確認候補がある場合はあわせて表示します。</p><a href="{query_link}" data-dsn-event="search-cta-open">この製品を検索する</a></div>
</main><footer><p>厚生労働省公表データをもとにした非公式情報です。実際の流通状況は卸・メーカーにもご確認ください。</p><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""
    return body, lastmod


def list_page(kind: str, records: list[dict], updated_at: str) -> str:
    topic = kind == "topics"
    heading = "話題のニュース" if topic else "最近お問い合わせの多い製品"
    description = ("医薬品の販売中止・販売移管・薬価・供給に関する話題を、出典付きでまとめています。"
                   if topic else "最近お問い合わせの多い医薬品について、メーカー別の供給状況をまとめています。")
    canonical = f"{SITE_ROOT}{kind}/index.html"
    links = []
    for record in records:
        label = record["title"] if topic else record["label"]
        meta = (f"{record['date']}｜{record['tag']}" if topic else "メーカー別の供給状況を確認")
        links.append(f'<a href="{esc(record["slug"])}.html">{esc(label)}<small>{esc(meta)}</small></a>')
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": heading, "item": canonical}]}
    title = f"{heading}｜医薬品供給ナビ"
    return f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [breadcrumb])}<style>{STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header><nav class="crumb"><a href="../">トップ</a> › {heading}</nav>
<main><section class="hero"><p class="eyebrow">CURATED</p><h1>{heading}</h1><p class="lede">{description}</p><p class="note">最終更新：{esc(updated_at)}</p>
{share_control("この一覧を共有")}</section>
<h2>一覧</h2><div class="list">{''.join(links)}</div></main><footer><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


def sitemap(topic_dates: dict[str, str], product_dates: dict[str, str],
            guide_dates: dict[str, str] | None = None) -> str:
    topic_latest = max(topic_dates.values(), default="")
    product_latest = max(product_dates.values(), default="")
    entries = [("topics/index.html", topic_latest), ("products/index.html", product_latest)]
    entries += [(f"topics/{slug}.html", date) for slug, date in topic_dates.items()]
    entries += [(f"products/{slug}.html", date) for slug, date in product_dates.items()]
    entries += [(f"guides/{slug}.html", date) for slug, date in (guide_dates or {}).items()]
    body = "".join(f"  <url><loc>{SITE_ROOT}{esc(path)}</loc>{f'<lastmod>{esc(date)}</lastmod>' if date else ''}</url>\n"
                   for path, date in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'{body}</urlset>\n')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="drugs_app_ready.csv")
    parser.add_argument("--site", default=".")
    parser.add_argument("--max-pages", type=int, default=200)
    args = parser.parse_args()
    site = Path(args.site)
    rows = load_rows(Path(args.csv))
    topics_doc = load_json(site / "industry_topics.json")
    products_doc = load_json(site / "featured_products.json")
    topics = topics_doc.get("topics") or []
    products = products_doc.get("products") or []
    if len(topics) + len(products) + 1 > args.max_pages:
        raise ValueError("生成対象が安全上限を超えています")
    generated_keys: set[str] = set()
    keys_path = site / "items" / "keys.json"
    if keys_path.exists():
        generated_keys = set(json.loads(keys_path.read_text(encoding="utf-8")))
    lifecycle: dict[str, dict] = {}
    lifecycle_path = site / "product_lifecycle.json"
    if lifecycle_path.exists():
        lifecycle = load_json(lifecycle_path).get("products") or {}

    topic_dir, product_dir, guide_dir = site / "topics", site / "products", site / "guides"
    topic_dir.mkdir(exist_ok=True)
    product_dir.mkdir(exist_ok=True)
    guide_dir.mkdir(exist_ok=True)
    topic_dates: dict[str, str] = {}
    for topic in topics:
        related = topic_related_rows(rows, topic)
        (topic_dir / f"{topic['slug']}.html").write_text(
            topic_page(topic, related, generated_keys, lifecycle, topics_doc.get("updated_at", "")),
            encoding="utf-8")
        topic_dates[topic["slug"]] = max(
            normalize_date(topic.get("date")), TEMPLATE_UPDATED_AT)
    product_dates: dict[str, str] = {}
    for product in products:
        matched = search_rows(rows, product.get("query"))
        if not matched:
            raise ValueError(f"{product['slug']}: CSVに一致する品目がありません")
        page, lastmod = product_page(product, matched, generated_keys, lifecycle)
        (product_dir / f"{product['slug']}.html").write_text(page, encoding="utf-8")
        curated_date = normalize_date(products_doc.get("updated_at"))
        product_dates[product["slug"]] = max(lastmod, curated_date, TEMPLATE_UPDATED_AT, PRODUCT_TEMPLATE_UPDATED_AT)
    guide_updated = max(
        normalize_date(topics_doc.get("updated_at")),
        normalize_date(products_doc.get("updated_at")),
        TEMPLATE_UPDATED_AT,
    )
    (guide_dir / f"{GUIDE_SLUG}.html").write_text(
        guide_page(guide_updated), encoding="utf-8")
    (topic_dir / "index.html").write_text(
        list_page("topics", topics, max(
            normalize_date(topics_doc.get("updated_at")), TEMPLATE_UPDATED_AT)), encoding="utf-8")
    (product_dir / "index.html").write_text(
        list_page("products", products, max(
            normalize_date(products_doc.get("updated_at")), TEMPLATE_UPDATED_AT, PRODUCT_TEMPLATE_UPDATED_AT)), encoding="utf-8")
    (site / "sitemap-curated.xml").write_text(
        sitemap(topic_dates, product_dates, {GUIDE_SLUG: guide_updated}), encoding="utf-8")
    print(f"生成: ニュース{len(topics)}件、注目製品{len(products)}件、恒久ガイド1件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
