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
STATUS = {
    "ok": ("通常出荷", "#227D4F", "#E7F6EE", 0),
    "limited": ("限定出荷", "#9F5E11", "#FCF0DF", 1),
    "stopped": ("供給停止", "#B03434", "#FBE7E7", 2),
    "ended": ("販売中止", "#7A5E49", "#F2EBE4", 3),
}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def ld_json(value: object) -> str:
    """HTMLのscript要素を閉じられない形でJSON-LDを埋め込む。"""
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e"))


def norm(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).lower().strip()


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
.cta{margin-top:28px;padding:22px;border-radius:16px;background:linear-gradient(135deg,#2F63E8,#4F80F4);color:#fff}.cta a{display:inline-block;background:#fff;border-radius:999px;padding:9px 18px;text-decoration:none;font-weight:800;margin-top:8px}.list{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px}.list a{display:block;background:#fff;border:1px solid var(--line);border-radius:13px;padding:14px;text-decoration:none;font-weight:750}.list small{display:block;color:var(--sub);font-weight:500;margin-top:4px}
.note,footer{font-size:12px;color:var(--sub)}footer{text-align:center;margin-top:36px}footer a{color:var(--sub)}
@media(max-width:640px){.hero,.card{padding:21px 18px}.product{grid-template-columns:1fr}.tag{margin:5px 5px 0 0}}
"""


def analytics_footer() -> str:
    return '<script data-goatcounter="https://kt1007.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>'


def row_link(row: dict[str, str], generated_keys: set[str]) -> str:
    key = item_key(row)
    if key in generated_keys:
        return f"../items/{key}.html"
    return "../#item=" + quote(key, safe="")


def product_rows_html(rows: list[dict[str, str]], generated_keys: set[str],
                      lifecycle: dict[str, dict]) -> str:
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
        cards.append(f"""<div class="product">
  <div><a href="{row_link(row, generated_keys)}">{esc(row.get('商品名'))}</a><div class="meta">{esc(spec)}</div></div>
  <div class="meta">{esc(maker)}<br>更新 {esc(updated)}</div><div>{badges}</div>
</div>""")
    return "".join(cards)


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
<p class="source">出典：<a href="{esc(source['url'])}" target="_blank" rel="noopener">{esc(source['name'])}</a></p></article>
{related_html}
<div class="cta"><strong>最新の供給状況を検索</strong><p>医薬品名・メーカー名・YJコードから、厚生労働省公表データを確認できます。</p><a href="../">Web版で検索する</a></div>
</main><footer><p>ニュースは一次情報または信頼できる報道をもとに編集しています。必ず出典原文をご確認ください。</p><a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


def product_page(product: dict, rows: list[dict[str, str]], generated_keys: set[str],
                 lifecycle: dict[str, dict]) -> tuple[str, str]:
    slug, label = product["slug"], product["label"]
    canonical = f"{SITE_ROOT}products/{slug}.html"
    suffix = "メーカー別供給状況" if len(rows) > 1 else "供給状況"
    title = f"{label}の{suffix}｜医薬品供給ナビ"
    description = f"{label}に該当する{len(rows)}品目の通常出荷・限定出荷・供給停止・販売中止予定をメーカー別に確認できます。厚生労働省公表データを毎日更新。"
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
                      "url": SITE_ROOT + row_link(row, generated_keys).removeprefix("../")}
                     for index, row in enumerate(rows, 1)]}
    collection = {"@type": "CollectionPage", "name": title, "description": description,
                  "url": canonical, "mainEntity": item_list}
    breadcrumb = {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
        {"@type": "ListItem", "position": 2, "name": "注目製品", "item": SITE_ROOT + "products/index.html"},
        {"@type": "ListItem", "position": 3, "name": label, "item": canonical}]}
    query_link = "../#q=" + quote(product["query"], safe="")
    body = f"""<!DOCTYPE html><html lang="ja"><head>
{common_head(title, description, canonical, 'website', [collection, breadcrumb])}<style>{STYLE}</style></head><body>
<div class="wrap"><header class="site"><a href="../">💊 医薬品供給ナビ</a></header>
<nav class="crumb"><a href="../">トップ</a> › <a href="index.html">注目製品</a> › {esc(label)}</nav><main>
<section class="hero"><p class="eyebrow">CURRENT SUPPLY STATUS</p><h1>{esc(label)}の{suffix}</h1>
<p class="lede">該当する{len(rows)}品目を、現在の供給区分とメーカーごとにまとめています。</p><div class="summary">{summary}</div></section>
<h2>該当品目</h2><div class="products">{product_rows_html(rows, generated_keys, lifecycle)}</div>
<div class="cta"><strong>Web版で絞り込んで確認</strong><p>同成分・同剤形の関連品目やメーカー案内も確認できます。</p><a href="{query_link}">この製品を検索する</a></div>
</main><footer><p>厚生労働省公表データをもとにした非公式情報です。実際の流通状況は卸・メーカーにもご確認ください。</p><a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
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
<main><section class="hero"><p class="eyebrow">CURATED</p><h1>{heading}</h1><p class="lede">{description}</p><p class="note">最終更新：{esc(updated_at)}</p></section>
<h2>一覧</h2><div class="list">{''.join(links)}</div></main><footer><a href="../about.html">運営情報・編集方針</a>｜<a href="../privacy.html">プライバシー</a></footer></div>
{analytics_footer()}</body></html>"""


def sitemap(topic_dates: dict[str, str], product_dates: dict[str, str]) -> str:
    topic_latest = max(topic_dates.values(), default="")
    product_latest = max(product_dates.values(), default="")
    entries = [("topics/index.html", topic_latest), ("products/index.html", product_latest)]
    entries += [(f"topics/{slug}.html", date) for slug, date in topic_dates.items()]
    entries += [(f"products/{slug}.html", date) for slug, date in product_dates.items()]
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
    if len(topics) + len(products) > args.max_pages:
        raise ValueError("生成対象が安全上限を超えています")
    generated_keys: set[str] = set()
    keys_path = site / "items" / "keys.json"
    if keys_path.exists():
        generated_keys = set(json.loads(keys_path.read_text(encoding="utf-8")))
    lifecycle: dict[str, dict] = {}
    lifecycle_path = site / "product_lifecycle.json"
    if lifecycle_path.exists():
        lifecycle = load_json(lifecycle_path).get("products") or {}

    topic_dir, product_dir = site / "topics", site / "products"
    topic_dir.mkdir(exist_ok=True)
    product_dir.mkdir(exist_ok=True)
    topic_dates: dict[str, str] = {}
    for topic in topics:
        related = search_rows(rows, topic.get("query"))
        (topic_dir / f"{topic['slug']}.html").write_text(
            topic_page(topic, related, generated_keys, lifecycle, topics_doc.get("updated_at", "")),
            encoding="utf-8")
        topic_dates[topic["slug"]] = normalize_date(topic.get("date"))
    product_dates: dict[str, str] = {}
    for product in products:
        matched = search_rows(rows, product.get("query"))
        if not matched:
            raise ValueError(f"{product['slug']}: CSVに一致する品目がありません")
        page, lastmod = product_page(product, matched, generated_keys, lifecycle)
        (product_dir / f"{product['slug']}.html").write_text(page, encoding="utf-8")
        curated_date = normalize_date(products_doc.get("updated_at"))
        product_dates[product["slug"]] = max(lastmod, curated_date)
    (topic_dir / "index.html").write_text(
        list_page("topics", topics, topics_doc.get("updated_at", "")), encoding="utf-8")
    (product_dir / "index.html").write_text(
        list_page("products", products, products_doc.get("updated_at", "")), encoding="utf-8")
    (site / "sitemap-curated.xml").write_text(sitemap(topic_dates, product_dates), encoding="utf-8")
    print(f"生成: ニュース{len(topics)}件、注目製品{len(products)}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
