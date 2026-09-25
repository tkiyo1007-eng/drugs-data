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

from jst_time import jst_today

SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/"
MHLW_SUPPLY_URL = "https://iyakuhin-kyokyu.mhlw.go.jp/public/supply-status-list"
PMDA_SEARCH_URL = "https://www.pmda.go.jp/PmdaSearch/iyakuSearch/"
PMDA_RECALL_URL = "https://www.pmda.go.jp/safety/info-services/drugs/calling-attention/recall-info/0002.html"
GUIDE_SLUG = "how-to-check-drug-supply"
TEMPLATE_UPDATED_AT = "2026-08-28"
PRODUCT_TEMPLATE_UPDATED_AT = "2026-09-06"
CATEGORY_TEMPLATE_UPDATED_AT = "2026-09-25"
REPORT_TEMPLATE_UPDATED_AT = "2026-09-25"
CATEGORY_MIN_ROWS = 3
# 季節ごとに検索が増えやすい薬効分類（YJコード先頭3桁）。供給状況の予測ではなく入口の並び順だけに使う。
SEASONAL_CATEGORIES = {
    "autumn_winter": {"months": {10, 11, 12, 1, 2, 3},
                      "label": "感染症シーズンに確認が増える分類",
                      "codes": ("222", "223", "224", "114", "625", "613", "225", "441")},
    "spring_summer": {"months": {4, 5, 6, 7, 8, 9},
                      "label": "花粉・夏季に確認が増える分類",
                      "codes": ("449", "441", "131", "132", "114", "264")},
}
# Web一覧のみの編集指定。共通JSONと詳細ページの生成対象は変更しない。
WEB_HIDDEN_FEATURED_SLUGS = {
    "caduet", "caduet-1", "caduet-2", "caduet-3", "caduet-4",
    "gentacin-ointment", "mounjaro-injection", "loxoprofen-sodium-tape", "celecox-tablets",
}
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
    if product["slug"] == "lulicon-cream":
        comparison = ('<p><a href="../topics/lulicon-alternatives-20260911.html">'
                      'ルリコンクリーム・軟膏の代替候補と変更時の注意を見る</a></p>')
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
    notes = "".join(f'<p>{esc(note)}</p>' for note in topic.get("notes") or [])
    extra_sources = "".join(
        f'<p class="source">出典：<a href="{esc(item["url"])}" target="_blank" '
        f'rel="noopener" data-dsn-event="official-source-open">{esc(item["name"])}</a></p>'
        for item in topic.get("sources") or []
    )
    source_details = (f'<details><summary>出典を確認</summary>{extra_sources}</details>'
                      if extra_sources else "")
    supplement = (f'<section class="intent"><h2>変更前の確認事項</h2>'
                  f'{notes}{source_details}</section>') if notes or extra_sources else ""
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
{supplement}
{related_html}
<div class="cta"><strong>最新の供給状況を検索</strong><p>医薬品名・メーカー名・YJコードから、厚生労働省公表データを確認できます。</p><a href="../" data-dsn-event="topic-to-search">Web版で検索する</a></div>
</main><footer><p>ニュースは一次情報または信頼できる報道をもとに編集しています。必ず出典原文をご確認ください。</p><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../categories/index.html">薬効分類別の供給状況</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
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
</main><footer><p>厚生労働省公表データをもとにした非公式情報です。実際の流通状況は卸・メーカーにもご確認ください。</p><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../categories/index.html">薬効分類別の供給状況</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
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
        if not topic and record["slug"] in WEB_HIDDEN_FEATURED_SLUGS:
            continue
        label = record["title"] if topic else record["label"]
        meta = (f"{record['date']}｜{record['tag']}" if topic else "メーカー別の供給状況を確認")
        links.append(f'<a href="{esc(record["slug"])}.html">{esc(label)}<small>{esc(meta)}</small></a>')
    if not topic:
        # Webのみの検索導線。共有キュレーション・iOSの一覧は変更しない。
        links.append(f'<a href="../#q={quote("テラムロ", safe="")}">テラムロ配合錠<small>メーカー別の供給状況を確認</small></a>')
        updated_at = max(updated_at, "2026-09-12")
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": heading, "item": canonical}]}
    title = f"{heading}｜医薬品供給ナビ"
    return f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [breadcrumb])}<style>{STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header><nav class="crumb"><a href="../">トップ</a> › {heading}</nav>
<main><section class="hero"><p class="eyebrow">CURATED</p><h1>{heading}</h1><p class="lede">{description}</p><p class="note">最終更新：{esc(updated_at)}</p>
{share_control("この一覧を共有")}</section>
<h2>一覧</h2><div class="list">{''.join(links)}</div></main><footer><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../categories/index.html">薬効分類別の供給状況</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


CATEGORY_STYLE = """
.normal-list{margin:10px 0 0;padding:0;list-style:none;display:grid;gap:4px}.normal-list li{font-size:13px;padding:6px 2px;border-bottom:1px solid var(--line)}.normal-list li span{color:var(--sub);font-size:12px}
details.normal{margin-top:18px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:12px 16px}details.normal summary{cursor:pointer;font-weight:800;min-height:32px}
.cat-table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;font-size:13.5px}.cat-table th,.cat-table td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left}.cat-table td.num,.cat-table th.num{text-align:right;white-space:nowrap}.cat-table a{font-weight:750}
"""


def dataset_month(site: Path) -> int:
    try:
        note = load_json(site / "version.json").get("note", "")
        match = re.search(r"(\d{4})年(\d{1,2})月", str(note))
        if match:
            return int(match.group(2))
    except (OSError, ValueError):
        pass
    return jst_today().month


def category_code(row: dict[str, str]) -> str:
    code = (row.get("YJコード") or "")[:3]
    return code if code.isdigit() else ""


def category_groups(rows: list[dict[str, str]]) -> dict[str, dict]:
    """薬効分類名とYJ先頭3桁の対応でまとめる。X始まりの内部IDは分類名から番号を引く。"""
    name_to_code: dict[str, str] = {}
    for row in rows:
        code, name = category_code(row), (row.get("薬効分類") or "").strip()
        if code and name:
            if name_to_code.setdefault(name, code) != code:
                raise ValueError(f"薬効分類「{name}」に複数の分類番号があります")
    groups: dict[str, dict] = {}
    for row in rows:
        name = (row.get("薬効分類") or "").strip()
        code = name_to_code.get(name)
        if code:
            groups.setdefault(code, {"code": code, "name": name, "rows": []})["rows"].append(row)
    return {code: group for code, group in groups.items() if len(group["rows"]) >= CATEGORY_MIN_ROWS}


def category_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = {key: 0 for key in STATUS}
    for row in rows:
        counts[map_status(row.get("供給状況"))] += 1
    return counts


def seasonal_codes(month: int) -> tuple[str, tuple[str, ...]]:
    for season in SEASONAL_CATEGORIES.values():
        if month in season["months"]:
            return season["label"], season["codes"]
    return "", ()


def category_page(group: dict, generated_keys: set[str], lifecycle: dict[str, dict]) -> tuple[str, str]:
    code, name, rows = group["code"], group["name"], group["rows"]
    canonical = f"{SITE_ROOT}categories/{code}.html"
    counts = category_counts(rows)
    restricted = sorted((row for row in rows if map_status(row.get("供給状況")) in ("limited", "stopped")),
                        key=lambda row: (-STATUS[map_status(row.get("供給状況"))][3],
                                         -int(normalize_date(row.get("更新日")).replace("-", "") or 0),
                                         row.get("商品名") or ""))
    normal = sorted((row for row in rows if map_status(row.get("供給状況")) not in ("limited", "stopped")),
                    key=lambda row: row.get("商品名") or "")
    # 表示はデータの日付だけ。テンプレート改訂日はサイトマップのlastmodにだけ使う。
    newest_row = max((normalize_date(row.get("更新日")) for row in rows), default="")
    lastmod = max(newest_row, CATEGORY_TEMPLATE_UPDATED_AT)
    title = f"{name}の供給状況（限定出荷・供給停止）｜医薬品供給ナビ"
    description = (f"厚生労働省公表データで「{name}」に分類される医療用医薬品{len(rows)}品目の現在の供給区分。"
                   f"限定出荷{counts['limited']}品目・供給停止{counts['stopped']}品目を、規格・メーカー・更新日とともに確認できます。")
    summary = "".join(f'<span class="chip" style="color:{STATUS[key][1]};background:{STATUS[key][2]}">{STATUS[key][0]} {count}</span>'
                      for key, count in counts.items() if count)
    item_list = {"@type": "ItemList", "name": f"{name}（限定出荷・供給停止）", "numberOfItems": len(restricted),
                 "itemListElement": [{"@type": "ListItem", "position": index, "name": row.get("商品名"),
                                      "url": absolute_product_row_url(row_link(row, generated_keys))}
                                     for index, row in enumerate(restricted[:100], 1)]}
    collection = {"@type": "CollectionPage", "name": title, "description": description,
                  "url": canonical, "dateModified": lastmod, "mainEntity": item_list}
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "薬効分類別の供給状況", "item": SITE_ROOT + "categories/index.html"},
        {"@type": "ListItem", "position": 3, "name": name, "item": canonical}]}
    restricted_html = (f'<div class="products">{product_rows_html(restricted, generated_keys, lifecycle)}</div>'
                       if restricted else '<p class="note">現在、この分類で限定出荷・供給停止と公表されている品目はありません（厚生労働省公表データの現在区分）。</p>')
    normal_items = "".join(
        f'<li><a href="{row_link(row, generated_keys)}" data-dsn-event="related-item-open">{esc(row.get("商品名"))}</a> '
        f'<span>{esc((row.get("規格") or "").strip())}｜{esc((row.get("販売メーカー") or row.get("製造メーカー") or "").strip())}</span></li>'
        for row in normal)
    normal_html = (f'<details class="normal"><summary>通常出荷などの品目（{len(normal)}品目）を表示</summary>'
                   f'<ul class="normal-list">{normal_items}</ul></details>') if normal else ""
    body = f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [collection, breadcrumb])}<style>{STYLE}{CATEGORY_STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header>
<nav class="crumb" aria-label="パンくず"><a href="../">トップ</a> › <a href="index.html">薬効分類別の供給状況</a> › {esc(name)}</nav><main>
<section class="hero"><p class="eyebrow">薬効分類 {esc(code)}</p><h1>{esc(name)}の供給状況</h1>
<p class="lede">厚生労働省公表データで「{esc(name)}」に分類される{len(rows)}品目の現在の供給区分です。限定出荷・供給停止の品目を先に、公表されている品目行の更新日が新しい順に並べています。</p>
<div class="summary">{summary}</div>
<p class="safety">同じ薬効分類でも、適応・用量・投与経路・製剤特性は品目ごとに異なります。この一覧は代替薬の推薦ではなく、実在庫や入手可否も示しません。</p>
{share_control("この分類の供給状況を共有")}</section>
<h2>限定出荷・供給停止の品目（{len(restricted)}品目）</h2>
{restricted_html}
{normal_html}
<div class="cta"><strong>品目名で詳しく確認</strong><p>公表理由・解除見込み・メーカー案内はWeb版の品目詳細で確認できます。</p><a href="../" data-dsn-event="search-cta-open">Web版で検索する</a></div>
<p class="note">分類は厚生労働省公表データの「薬効分類」欄とYJコード先頭3桁によるものです。品目行の最新更新日：{esc(newest_row or "不明")}。原典は<a href="{MHLW_SUPPLY_URL}" target="_blank" rel="noopener" data-dsn-event="official-source-open">厚生労働省の公式システム</a>でご確認ください。</p>
</main><footer><p>厚生労働省公表データをもとにした非公式情報です。実際の流通状況は卸・メーカーにもご確認ください。</p><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="index.html">薬効分類別の供給状況</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""
    return body, lastmod


def category_index_page(groups: dict[str, dict], newest_row: str, month: int) -> str:
    canonical = f"{SITE_ROOT}categories/index.html"
    title = "薬効分類別の医薬品供給状況（限定出荷・供給停止の件数）｜医薬品供給ナビ"
    description = ("厚生労働省公表データの薬効分類ごとに、限定出荷・供給停止の品目数と一覧を確認できます。"
                   "鎮咳剤・去たん剤・解熱鎮痛消炎剤・抗ウイルス剤など分類単位で供給状況を把握できます。")
    ordered = sorted(groups.values(), key=lambda g: (
        -(category_counts(g["rows"])["limited"] + category_counts(g["rows"])["stopped"]), g["code"]))

    def table(items: list[dict]) -> str:
        body_rows = []
        for group in items:
            counts = category_counts(group["rows"])
            body_rows.append(f'<tr><td><a href="{esc(group["code"])}.html">{esc(group["name"])}</a></td>'
                             f'<td class="num">{counts["limited"]}</td><td class="num">{counts["stopped"]}</td>'
                             f'<td class="num">{len(group["rows"])}</td></tr>')
        return ('<table class="cat-table"><thead><tr><th scope="col">薬効分類</th><th scope="col" class="num">限定出荷</th>'
                '<th scope="col" class="num">供給停止</th><th scope="col" class="num">全品目</th></tr></thead>'
                f'<tbody>{"".join(body_rows)}</tbody></table>')

    label, codes = seasonal_codes(month)
    seasonal = [groups[code] for code in codes if code in groups]
    seasonal_html = (f'<h2>{esc(label)}</h2><p class="note">時期により検索が増えやすい分類を先に並べています。供給状況の予測ではありません。</p>{table(seasonal)}'
                     if seasonal else "")
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "薬効分類別の供給状況", "item": canonical}]}
    return f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [breadcrumb])}<style>{STYLE}{CATEGORY_STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header><nav class="crumb"><a href="../">トップ</a> › 薬効分類別の供給状況</nav>
<main><section class="hero"><p class="eyebrow">BY THERAPEUTIC CATEGORY</p><h1>薬効分類別の医薬品供給状況</h1><p class="lede">{description}</p><p class="note">品目行の最新更新日：{esc(newest_row or "不明")}（{len(groups)}分類。{CATEGORY_MIN_ROWS}品目以上の分類を掲載）</p>
{share_control("この一覧を共有")}</section>
{seasonal_html}
<h2>すべての薬効分類（限定出荷・供給停止の多い順）</h2>{table(ordered)}
<p class="note">分類は厚生労働省公表データの「薬効分類」欄によるものです。件数は現在の公表区分の集計で、実在庫や入手可否を示すものではありません。</p>
</main><footer><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


REPORT_STYLE = """
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}.kpi{background:#F2F6FE;border-radius:14px;padding:14px 16px}.kpi strong{display:block;font-size:26px;line-height:1.2}.kpi span{font-size:12px;color:var(--sub)}
.bars{display:grid;gap:8px;margin-top:12px}.bar{display:grid;grid-template-columns:8.5em minmax(0,1fr) 4.5em;gap:10px;align-items:center;font-size:13px}.bar i{display:block;height:12px;border-radius:6px;background:#9BB9FA}.bar b{text-align:right}
.cite{background:#fff;border:1px dashed #B9C9EA;border-radius:12px;padding:12px 14px;font-size:12.5px;word-break:break-all}
"""


def month_label(month: str) -> str:
    year, number = month.split("-")
    return f"{year}年{int(number)}月"


def load_reports(site: Path) -> list[dict]:
    reports = []
    for path in sorted((site / "reports").glob("*.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("schema_version") != 1 or report.get("month") != path.stem:
            raise ValueError(f"{path.name}: レポートの形式が不正です")
        reports.append(report)
    return sorted(reports, key=lambda report: report["month"], reverse=True)


def report_page(report: dict) -> str:
    month, label = report["month"], month_label(report["month"])
    canonical = f"{SITE_ROOT}reports/{month}.html"
    changes, snap = report["changes"], report["snapshot_status"]
    snapshot_date = report["snapshot_date"]
    title = f"医薬品供給レポート {label}｜限定出荷・供給停止の動向｜医薬品供給ナビ"
    description = (f"{label}に厚生労働省公表データ上で供給区分が変わった医療用医薬品は{changes['items']}品目"
                   f"（限定出荷へ{changes['to_limited']}・供給停止へ{changes['to_stopped']}・通常出荷へ{changes['to_ok']}）。"
                   "薬効分類別の動向と公表区分の件数を集計しています。")
    prev = report.get("previous_month")
    rows = [("限定出荷へ", "to_limited"), ("供給停止へ", "to_stopped"), ("通常出荷へ", "to_ok"), ("その他の区分変更", "other")]
    peak = max([changes[key] for _, key in rows] + [1])
    bars = "".join(f'<div class="bar"><span>{name}</span><i style="width:{changes[key] / peak * 100:.1f}%"></i><b>{changes[key]}品目</b></div>'
                   for name, key in rows)
    compare = ""
    if prev:
        compare = ('<table class="cat-table"><thead><tr><th scope="col">区分変更</th>'
                   f'<th scope="col" class="num">{esc(month_label(prev["month"]))}</th><th scope="col" class="num">{esc(label)}</th></tr></thead><tbody>'
                   + "".join(f'<tr><td>{name}</td><td class="num">{prev[key]}</td><td class="num">{changes[key]}</td></tr>' for name, key in rows)
                   + f'<tr><td>合計</td><td class="num">{prev["items"]}</td><td class="num">{changes["items"]}</td></tr></tbody></table>')
    categories = report.get("top_new_restriction_categories") or []
    def category_cell(item: dict) -> str:
        if item.get("code"):
            return f'<a href="../categories/{esc(item["code"])}.html">{esc(item["name"])}</a>'
        return esc(item["name"])

    category_rows = "".join(f'<tr><td>{category_cell(item)}</td><td class="num">{item["count"]}</td></tr>'
                            for item in categories)
    category_html = (f'<table class="cat-table"><thead><tr><th scope="col">薬効分類</th><th scope="col" class="num">通常出荷から制限へ</th></tr></thead><tbody>{category_rows}</tbody></table>'
                     if categories else '<p class="note">この月に通常出荷から限定出荷・供給停止へ変わった記録はありません（変更履歴の集計）。</p>')
    share = lambda value: f"{value / snap['total'] * 100:.1f}%" if snap["total"] else "—"
    crisis, resolution = report.get("crisis_index") or {}, report.get("resolution") or {}
    res_rows = "".join(
        f'<tr><td>{name}</td><td class="num">{esc((resolution.get(key) or {}).get("count", "—"))}</td>'
        f'<td class="num">{esc((resolution.get(key) or {}).get("medianDays", "—"))}日</td><td class="num">{esc((resolution.get(key) or {}).get("avgDays", "—"))}日</td></tr>'
        for name, key in (("限定出荷", "limited"), ("供給停止", "stopped")))
    citation = f"出典：医薬品供給ナビ「医薬品供給レポート（{label}）」（厚生労働省「医療用医薬品供給状況」公表データを集計） {canonical}"
    article = {"@type": "Article", "headline": f"医薬品供給レポート（{label}）", "description": description,
               "datePublished": snapshot_date, "dateModified": snapshot_date, "inLanguage": "ja",
               "mainEntityOfPage": canonical,
               "author": {"@type": "Organization", "name": "医薬品供給ナビ運営者"},
               "publisher": {"@type": "Organization", "name": "医薬品供給ナビ"}}
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "医薬品供給レポート", "item": SITE_ROOT + "reports/index.html"},
        {"@type": "ListItem", "position": 3, "name": label, "item": canonical}]}
    top3 = "、".join(f"{item['name']}（{item['count']}）" for item in categories[:3]) or "記録なし"
    return f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'article', [article, breadcrumb])}<style>{STYLE}{CATEGORY_STYLE}{REPORT_STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header>
<nav class="crumb" aria-label="パンくず"><a href="../">トップ</a> › <a href="index.html">医薬品供給レポート</a> › {esc(label)}</nav><main>
<article class="hero"><p class="eyebrow">MONTHLY SUPPLY REPORT</p><h1>医薬品供給レポート（{esc(label)}）</h1>
<p class="lede">{esc(description)}</p>
<ul class="points"><li>{esc(label)}に供給区分が変わった品目：{changes['items']}品目（{changes['days_with_changes']}日分の更新）{f"、前月は{prev['items']}品目" if prev else ""}</li>
<li>通常出荷から制限へ変わった品目が多い薬効分類：{esc(top3)}</li>
<li>{esc(snapshot_date)}時点の公表区分：限定出荷{snap['limited']}品目（{share(snap['limited'])}）・供給停止{snap['stopped']}品目（{share(snap['stopped'])}）／全{snap['total']}品目</li></ul>
{share_control("このレポートを共有")}</article>
<h2>{esc(label)}の区分変更の内訳</h2><div class="card"><div class="bars">{bars}</div></div>
{f'<h2>前月との比較</h2>{compare}' if compare else ''}
<h2>通常出荷から限定出荷・供給停止へ変わった品目が多い薬効分類</h2>{category_html}
<h2>{esc(snapshot_date)}時点の公表区分</h2>
<div class="kpis"><div class="kpi"><strong>{snap['total']:,}</strong><span>全品目</span></div><div class="kpi"><strong>{snap['limited']:,}</strong><span>限定出荷（{share(snap['limited'])}）</span></div><div class="kpi"><strong>{snap['stopped']:,}</strong><span>供給停止（{share(snap['stopped'])}）</span></div><div class="kpi"><strong>{esc(crisis.get('score', '—'))}</strong><span>供給危機指数（{esc(crisis.get('level', '—'))}・{esc(crisis.get('date', ''))}）</span></div></div>
<p class="note">供給危機指数は（限定出荷×0.5＋供給停止×1.0）÷全品目×1000（上限100）で算出した医薬品供給ナビ独自の目安で、公的な指標ではありません。</p>
<h2>制限から通常出荷に戻るまでの日数（参考値）</h2>
<table class="cat-table"><thead><tr><th scope="col">制限の区分</th><th scope="col" class="num">件数</th><th scope="col" class="num">中央値</th><th scope="col" class="num">平均</th></tr></thead><tbody>{res_rows}</tbody></table>
<p class="note">{esc(resolution.get('updated_at', ''))}時点の集計。変更履歴の保持期間（直近90日）内に制限の開始と解除の両方が記録された品目だけが対象で、長期間続く制限は含まれないため短めに出ます。</p>
<h2>データの定義と引用</h2>
<p class="note">区分変更は日次更新で前回データとの差分として検出したもので、同じ品目が月内に複数回変わった場合はそれぞれ数えます。日付は変更を検出した日（日本時間）で、厚生労働省の公表日・メーカーの発表日とは異なる場合があります。数値は{esc(snapshot_date)}に固定し、以後更新しません。実在庫や入手可否を示すものではありません。</p>
<p class="cite">{esc(citation)}</p>
<p><a href="../updates/index.html">日別の供給変更ページ</a>｜<a href="../categories/index.html">薬効分類別の供給状況</a></p>
</main><footer><p>厚生労働省公表データをもとにした非公式の集計です。</p><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


def report_index_page(reports: list[dict]) -> str:
    canonical = f"{SITE_ROOT}reports/index.html"
    title = "医薬品供給レポート（月次）｜限定出荷・供給停止の動向｜医薬品供給ナビ"
    description = "厚生労働省公表データをもとに、医療用医薬品の供給区分の変化・薬効分類別の動向を毎月集計したレポートの一覧です。"
    links = "".join(f'<a href="{esc(report["month"])}.html">{esc(month_label(report["month"]))}のレポート'
                    f'<small>区分変更 {report["changes"]["items"]}品目｜{esc(report["snapshot_date"])}時点で固定</small></a>'
                    for report in reports)
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "医薬品供給レポート", "item": canonical}]}
    return f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [breadcrumb])}<style>{STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header><nav class="crumb"><a href="../">トップ</a> › 医薬品供給レポート</nav>
<main><section class="hero"><p class="eyebrow">MONTHLY SUPPLY REPORT</p><h1>医薬品供給レポート（月次）</h1><p class="lede">{description}</p>
{share_control("レポート一覧を共有")}</section><h2>レポート一覧</h2><div class="list">{links}</div></main>
<footer><a href="../guides/{GUIDE_SLUG}.html">供給情報の確認ガイド</a>｜<a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


def sitemap(topic_dates: dict[str, str], product_dates: dict[str, str],
            guide_dates: dict[str, str] | None = None,
            category_dates: dict[str, str] | None = None,
            report_dates: dict[str, str] | None = None) -> str:
    topic_latest = max(topic_dates.values(), default="")
    product_latest = max(product_dates.values(), default="")
    entries = [("topics/index.html", topic_latest), ("products/index.html", product_latest)]
    entries += [(f"topics/{slug}.html", date) for slug, date in topic_dates.items()]
    entries += [(f"products/{slug}.html", date) for slug, date in product_dates.items()]
    entries += [(f"guides/{slug}.html", date) for slug, date in (guide_dates or {}).items()]
    if category_dates:
        entries.append(("categories/index.html", max(category_dates.values())))
        entries += [(f"categories/{code}.html", date) for code, date in sorted(category_dates.items())]
    if report_dates:
        entries.append(("reports/index.html", max(report_dates.values())))
        entries += [(f"reports/{month}.html", date) for month, date in sorted(report_dates.items())]
    body = "".join(f"  <url><loc>{SITE_ROOT}{esc(path)}</loc>{f'<lastmod>{esc(date)}</lastmod>' if date else ''}</url>\n"
                   for path, date in entries)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f'{body}</urlset>\n')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="drugs_app_ready.csv")
    parser.add_argument("--site", default=".")
    parser.add_argument("--max-pages", type=int, default=400)
    parser.add_argument("--month", type=int, default=None, help="季節の並び順の確認用（既定はversion.jsonのデータ月）")
    args = parser.parse_args()
    site = Path(args.site)
    rows = load_rows(Path(args.csv))
    topics_doc = load_json(site / "industry_topics.json")
    products_doc = load_json(site / "featured_products.json")
    topics = topics_doc.get("topics") or []
    products = products_doc.get("products") or []
    groups = category_groups(rows)
    if len(topics) + len(products) + len(groups) + 2 > args.max_pages:
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
        if product["slug"] == "lulicon-cream":
            product_dates[product["slug"]] = max(product_dates[product["slug"]], "2026-09-11")
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
    category_dir = site / "categories"
    category_dir.mkdir(exist_ok=True)
    category_dates: dict[str, str] = {}
    for code, group in groups.items():
        page, lastmod = category_page(group, generated_keys, lifecycle)
        (category_dir / f"{code}.html").write_text(page, encoding="utf-8")
        category_dates[code] = lastmod
    for stale in category_dir.glob("*.html"):
        if stale.stem != "index" and stale.stem not in groups:
            stale.unlink()  # 3品目未満になった分類はサイトマップと同時に外す
    # 実行日ではなくデータ（version.json）の日付で季節を決め、同じデータから同じHTMLを再生成できるようにする。
    month = args.month or dataset_month(site)
    (category_dir / "index.html").write_text(
        category_index_page(groups, max((normalize_date(row.get("更新日")) for group in groups.values()
                                         for row in group["rows"]), default=""), month),
        encoding="utf-8")
    reports = load_reports(site) if (site / "reports").is_dir() else []
    report_dates: dict[str, str] = {}
    for report in reports:
        (site / "reports" / f"{report['month']}.html").write_text(report_page(report), encoding="utf-8")
        report_dates[report["month"]] = max(report["snapshot_date"], REPORT_TEMPLATE_UPDATED_AT)
    if reports:
        (site / "reports" / "index.html").write_text(report_index_page(reports), encoding="utf-8")
    (site / "sitemap-curated.xml").write_text(
        sitemap(topic_dates, product_dates, {GUIDE_SLUG: guide_updated}, category_dates, report_dates),
        encoding="utf-8")
    print(f"生成: ニュース{len(topics)}件、注目製品{len(products)}件、恒久ガイド1件、薬効分類{len(groups)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
