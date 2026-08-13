#!/usr/bin/env python3
"""drugs_app_ready.csv から品目別の静的ページを生成するSEO用スクリプト。

「(薬品名) 出荷調整」「(薬品名) 供給」のような検索に1品目=1ページで応えるための
ランディングページ群を作る。GitHub Actions(generate-item-pages.yml)が毎晩、
データ更新後に drugs-data リポジトリ内で実行し、items/ 配下へ出力する。

生成対象:
  - 供給に問題がある品目(限定出荷・供給停止・販売中止)と薬価削除予定の品目
  - 過去に生成済みでCSVにまだ存在する品目(通常出荷に戻ってもURLを404にしないため
    最新状態で再生成し続ける。CSVから消えた品目のページは最終状態のまま残す)

出力:
  items/<キー>.html   品目ページ(キーはYJコード。無い品目は商品名+規格のハッシュ)
  items/index.html    品目一覧(クローラーの巡回起点)
  sitemap-items.xml   品目ページのサイトマップ(robots.txt から参照される)

使い方:
  python3 scripts/generate_item_pages.py --csv drugs_app_ready.csv --site .
"""

import argparse
import csv
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/"
APP_STORE = "https://apps.apple.com/jp/app/%E5%8C%BB%E8%96%AC%E5%93%81%E4%BE%9B%E7%B5%A6%E3%83%8A%E3%83%93/id6777696446"

# LP(index.html)の mapStatus / STATUS と同じ判定・配色
# color は淡い bg の上に載る文字色。淡色地の上では元のステータス色のままだと
# コントラストが 2.5〜4.5:1 にしかならず WCAG AA(4.5:1) を満たさなかったため、
# 色相は保ったまま暗くしてある（供給状況はこのページの中心情報なので読めることを優先）。
# 括弧内は bg に対する実測コントラスト比。
STATUSES = {
    "ok":      {"label": "通常出荷", "color": "#227D4F", "bg": "#E7F6EE"},  # 4.56:1 (旧#2FAE6E は2.54:1)
    "limited": {"label": "限定出荷", "color": "#9F5E11", "bg": "#FCF0DF"},  # 4.58:1 (旧#B96D14 は3.55:1)
    "stopped": {"label": "供給停止", "color": "#B03434", "bg": "#FBE7E7"},  # 4.99:1 (旧#C23A3A は4.47:1)
    "ended":   {"label": "販売中止", "color": "#7A5E49", "bg": "#F2EBE4"},  # 4.87:1 (旧#8A6A52 は4.17:1)
}
STATUS_NOTES = {
    "ok":      "メーカーが通常どおり出荷している状態です。",
    "limited": "需要の急増や増産対応などにより、メーカーが出荷数量・販売先を制限している状態です。入手しづらくなる場合があります。",
    "stopped": "メーカーが出荷を一時的に停止している状態です。出荷再開の見込みはメーカーの案内をご確認ください。",
    "ended":   "メーカーが製造・販売を終了した状態です。今後の出荷再開はないため、代替薬への切り替え検討が必要です。",
}
# 詳細表で優先的に上へ並べる列(LPの DETAIL_ORDER と同じ考え方)
DETAIL_ORDER = ["規格", "供給状況", "理由", "代替候補", "一般名", "製造メーカー",
                "販売メーカー", "薬効分類", "薬価", "経過措置期限",
                "ステータス更新日", "更新日", "YJコード"]
SKIP_COLS = {"商品名", "今回更新"}


def is_delist(row: dict) -> bool:
    """薬価削除予定(近く販売終了となる見込み)か。

    LP(index.html)およびiOSアプリ版と同じ判定にすること。片方だけ変えると、
    LPが「薬価削除予定」として品目ページへリンクしているのにページが生成されず
    404になる、といった食い違いが起きる。
      - 出荷量状況の区分に「薬価削除予定」が含まれる
      - 経過措置期限が設定済み(＝薬価基準からの削除が決定済み)
    """
    return ("薬価削除予定" in (row.get("代替候補") or "")
            or bool((row.get("経過措置期限") or "").strip()))


# --- 関連品目（同成分の他社品）の絞り込み。LP(index.html)と同じ判定にすること ---
# 一般名の一致だけで並べると、注射剤に対して軟膏・貼付剤など投与経路の違う品目まで
# 「他社品」として並んでしまう（例: ケナコルト-A注に対するレダコート軟膏）。
# 代替薬を探している人が直接たどり着くページなので、LPと同じ精度で絞り込む。
SEV = {"ok": 0, "limited": 1, "stopped": 2, "ended": 3}

# 温感タイプはYJコードでは非温感と区別できず（先頭9桁まで同一）、商品名にも
# 「温感」の表記がない品目があるため、既知のYJコードと商品名の両方で判定する
WARM_PATCH_YJ = {
    "2649735S2237", "2649735S3233",  # ロキソプロフェンナトリウムテープ50/100mg「タイホウ」（温感）
    "2649735S2261", "2649735S3268",  # ロキソプロフェンNaテープ50/100mg「三友」（温感）
}


def is_warm_patch(row: dict) -> bool:
    name = (row.get("商品名") or "") + (row.get("規格") or "")
    yj = re.sub(r"[^0-9A-Za-z]", "", row.get("YJコード", "") or "")
    return (yj in WARM_PATCH_YJ
            or bool(re.search(r"温感|温シップ|温湿布", name))
            or bool(re.search(r"ロキソプロフェン.*テープ.*(三友|タイホウ)", row.get("商品名") or "")))


def patch_kind(row: dict) -> str:
    """貼付剤はYJの剤形コードが全て「S」でテープ/パップを区別できないため商品名で判定。
    判定できない商品名は "" を返し、除外の対象にしない。"""
    name = row.get("商品名") or ""
    if re.search(r"テープ|プラスター", name):
        return "tape"
    if re.search(r"パップ|シップ", name):
        return "pap"
    return ""


def eff_sev(row: dict) -> int:
    """並び順用の実効深刻度。薬価削除予定は「入手しやすい」側に置かない。"""
    base = SEV[map_status(row.get("供給状況") or "")]
    return max(SEV["ended"], base) if is_delist(row) else base


def pick_siblings(row: dict, candidates: list) -> list:
    """同成分・同剤形の他社品を、入手しやすい順に返す。"""
    yj8 = re.sub(r"[^0-9A-Za-z]", "", row.get("YJコード", "") or "")[:8]
    warm = is_warm_patch(row)
    kind = patch_kind(row)
    out = []
    for x in candidates:
        if x is row or (x.get("商品名") or "") == (row.get("商品名") or ""):
            continue
        x_yj8 = re.sub(r"[^0-9A-Za-z]", "", x.get("YJコード", "") or "")[:8]
        if yj8 and x_yj8 != yj8:
            continue                       # 薬効細分類・成分・剤形まで一致するものだけ
        if is_warm_patch(x) != warm:
            continue                       # 温感品には温感のみ（逆も同様）
        x_kind = patch_kind(x)
        if kind and x_kind and x_kind != kind:
            continue                       # テープとパップを混ぜない
        out.append(x)
    out.sort(key=lambda x: (eff_sev(x), x.get("商品名") or ""))
    return out


def map_status(s: str) -> str:
    if "停止" in s:
        return "stopped"
    if "限定" in s:
        return "limited"
    if "中止" in s:
        return "ended"
    return "ok"


def esc(s: str) -> str:
    return html.escape(str(s or ""), quote=True)


def item_key(row: dict) -> str:
    """URLに使う安定キー。YJコード優先、無ければ商品名+規格のハッシュ。"""
    yj = re.sub(r"[^0-9A-Za-z]", "", row.get("YJコード", "") or "")
    if yj:
        return yj
    seed = (row.get("商品名", "") + "|" + row.get("規格", "")).encode("utf-8")
    return "x" + hashlib.sha1(seed).hexdigest()[:12]


def load_csv(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    return [r for r in rows if (r.get("商品名") or "").strip()]


def page_html(row, key, status, jst_today, siblings, generated_keys):
    name = row["商品名"].strip()
    maker = (row.get("販売メーカー") or row.get("製造メーカー") or "").strip()
    gen = (row.get("一般名") or "").strip()
    spec = (row.get("規格") or "").strip()
    updated = (row.get("更新日") or "").replace("/", "-").strip()
    st = STATUSES[status]
    # 薬価削除予定は供給状況欄が「通常出荷」でも表示する。
    # LP側は同じ品目にバッジと注意書きを出しているので、ここで出さないと表示が食い違う
    delist = is_delist(row)
    delist_tag = ('<span class="tag delist">薬価削除予定</span>' if delist else "")
    delist_box = ('<div class="stbox delist-box">この品目は厚生労働省の公表データ上、'
                  '<strong>薬価削除予定</strong>（経過措置期限の設定を含む）となっています。'
                  '供給状況欄の表示に関わらず、近く販売終了となる見込みがあります。'
                  '採用の見直しをご検討ください。</div>' if delist else "")
    # ページ内に「生成日」を書かない。書くと供給状況が何も変わっていない日でも
    # 全ページのHTMLが差し替わり、drugs-data に毎日2,000件規模の無意味なコミットが
    # 積まれてしまう（履歴から「実際に何が変わったか」が読めなくなる）
    as_of = f"（厚生労働省データ {updated} 時点）" if updated else ""
    updated_note = (f"厚生労働省データ {updated} 時点" if updated
                    else "出典: 厚生労働省「医療用医薬品供給状況」")
    title = f"{name}の供給状況：{st['label']}｜医薬品供給ナビ"
    desc = (f"{name}（{maker}）の現在の供給状況は「{st['label']}」"
            + ("（薬価削除予定）" if delist else "")
            + (f"（厚生労働省データ {updated} 時点、毎日自動更新）。" if updated
               else "（厚生労働省データ、毎日自動更新）。")
            + "理由・代替候補・同成分の他社品の供給状況もこのページで確認できます。")
    url = f"{SITE_ROOT}items/{key}.html"
    lp_link = SITE_ROOT + "#drug=" + quote(name, safe="")
    pmda = "https://www.pmda.go.jp/PmdaSearch/iyakuSearch/?nameWord=" + quote(name, safe="")

    # 詳細表: 既知の列を定義順に、その他の列は後ろに(空欄と重複情報はスキップ)
    detail_rows = []
    seen = set(SKIP_COLS)
    for col in DETAIL_ORDER + [c for c in row.keys() if c not in DETAIL_ORDER]:
        if col in seen or col not in row:
            continue
        seen.add(col)
        v = (row.get(col) or "").strip()
        if not v:
            continue
        detail_rows.append(f'<tr><th scope="row">{esc(col)}</th><td>{esc(v)}</td></tr>')

    # 同成分(一般名が同じ)の他社品。生成済みページがあれば内部リンク、なければLPの詳細へ
    sib_html = ""
    if siblings:
        lis = []
        for s in siblings[:12]:
            s_key = item_key(s)
            s_status = map_status(s.get("供給状況") or "")
            s_st = STATUSES[s_status]
            href = (f"{s_key}.html" if s_key in generated_keys
                    else SITE_ROOT + "#drug=" + quote(s["商品名"], safe=""))
            lis.append(
                f'<li><a href="{href}">{esc(s["商品名"])}</a>'
                f'<span class="tag status-{s_status}">{s_st["label"]}</span>'
                f'<span class="mk">{esc((s.get("販売メーカー") or s.get("製造メーカー") or "").strip())}</span></li>')
        warm_note = ("この品目は温感タイプのため、温感タイプの品目のみを表示しています。"
                     if is_warm_patch(row) else "")
        sib_html = f"""
<section>
  <h2>同成分・同剤形（{esc(gen)}）の他社品の供給状況</h2>
  <p class="sib-note">入手しやすい順に表示しています。{esc(warm_note)}適応・規格・剤形の互換性は必ず添付文書と医師・薬剤師の判断でご確認ください。</p>
  <ul class="sib">{''.join(lis)}</ul>
</section>"""

    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
            {"@type": "ListItem", "position": 2, "name": "品目別の供給状況", "item": SITE_ROOT + "items/index.html"},
            {"@type": "ListItem", "position": 3, "name": name, "item": url},
        ]}, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE_ROOT}og_image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="医薬品供給ナビの供給状況サマリー">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(title)}">
<meta name="twitter:description" content="{esc(desc)}">
<meta name="twitter:image" content="{SITE_ROOT}og_image.png">
<meta name="twitter:image:alt" content="医薬品供給ナビの供給状況サマリー">
<meta name="apple-itunes-app" content="app-id=6777696446">
<script type="application/ld+json">{breadcrumb_ld}</script>
<style>
:root{{--blue:#2F63E8;--ink:#1C2A44;--sub:#5A6B8C;--line:#E3EAF6}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;color:var(--ink);background:#F6F9FE;line-height:1.75}}
.wrap{{max-width:760px;margin:0 auto;padding:20px 18px 56px}}
.site{{display:flex;align-items:center;gap:8px;padding:14px 0;font-weight:700}}
.site a{{color:var(--blue);text-decoration:none;font-size:15px}}
.crumb{{font-size:12px;color:var(--sub);margin-bottom:14px}}
.crumb a{{color:var(--sub)}}
.card{{background:#fff;border:1px solid var(--line);border-radius:16px;padding:26px 22px;box-shadow:0 8px 28px rgba(47,99,232,.06)}}
.tag{{display:inline-block;font-size:12.5px;font-weight:700;border-radius:999px;padding:3px 12px;margin-left:8px;vertical-align:2px;white-space:nowrap}}
h1{{font-size:22px;line-height:1.45;margin-bottom:6px}}
.maker{{color:var(--sub);font-size:14px;margin-bottom:18px}}
.stbox{{border-radius:12px;padding:14px 16px;font-size:14px;margin-bottom:20px}}
.status-ok{{color:#227D4F;background:#E7F6EE}}
.status-limited{{color:#9F5E11;background:#FCF0DF}}
.status-stopped{{color:#B03434;background:#FBE7E7}}
.status-ended{{color:#7A5E49;background:#F2EBE4}}
.tag.delist{{color:#7A5E49;background:#F2EBE4}}      /* 5.04:1 */
.delist-box{{color:#7A5E49;background:#F7F1EA;border:1px solid #E3D5C6}} /* 5.31:1 */
table{{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:8px}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{white-space:nowrap;color:var(--sub);font-weight:600;width:8.5em}}
section{{margin-top:30px}}
h2{{font-size:16.5px;margin-bottom:12px}}
.sib{{list-style:none}}
.sib li{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px;font-size:14px}}
.sib a{{color:var(--blue);text-decoration:none;font-weight:600}}
.sib .mk{{display:block;font-size:12px;color:var(--sub);margin-top:2px}}
.sib-note{{font-size:12px;color:var(--sub);margin-bottom:10px;line-height:1.7}}
.links a{{display:inline-block;margin:4px 12px 4px 0;color:var(--blue);font-size:14px}}
.cta{{margin-top:30px;background:linear-gradient(135deg,#2F63E8,#4F80F4);border-radius:16px;padding:24px 22px;color:#fff}}
.cta h2{{color:#fff}}
.cta p{{font-size:14px;opacity:.92;margin-bottom:14px}}
.cta a{{display:inline-block;background:#fff;color:var(--blue);font-weight:700;text-decoration:none;border-radius:999px;padding:10px 22px;font-size:14px;margin-right:10px;margin-bottom:6px}}
.cta a.ghost{{background:transparent;color:#fff;border:1px solid rgba(255,255,255,.6)}}
.note{{font-size:12px;color:var(--sub);margin-top:26px}}
footer{{font-size:12px;color:var(--sub);margin-top:34px;text-align:center}}
footer a{{color:var(--sub)}}
</style>
</head>
<body>
<div class="wrap">
  <header class="site"><a href="{SITE_ROOT}">💊 医薬品供給ナビ</a></header>
  <nav class="crumb"><a href="{SITE_ROOT}">トップ</a> › <a href="index.html">品目別の供給状況</a> › {esc(name)}</nav>
  <main>
  <div class="card">
    <h1>{esc(name)}<span class="tag status-{status}">{st['label']}</span>{delist_tag}</h1>
    <p class="maker">{esc(maker)}{('｜' + esc(spec)) if spec else ''}</p>
    <div class="stbox status-{status}">
      現在の供給状況は「<strong>{st['label']}</strong>」です{esc(as_of)}。{STATUS_NOTES[status]}
    </div>
{delist_box}
    <table><tbody>{''.join(detail_rows)}</tbody></table>
    <p class="links">
      <a href="{lp_link}">Web版で詳細を見る（同成分・同分類の一覧つき）</a>
      <a href="{pmda}" target="_blank" rel="noopener">PMDAで添付文書を探す</a>
    </p>
  </div>
{sib_html}
  <div class="cta">
    <h2>供給状況の変化を、毎日自動でチェック。</h2>
    <p>医薬品供給ナビは厚労省の医薬品供給状況データ約16,000品目を毎日自動更新。お気に入り登録した品目が「限定出荷」や「出荷再開」に変わるとすぐ分かります。無料です。</p>
    <a href="{APP_STORE}">App Storeで入手</a>
    <a class="ghost" href="{SITE_ROOT}">Web版を使ってみる</a>
  </div>
  </main>
  <footer>
    <p class="note">本ページは厚生労働省「医療用医薬品供給状況」の公表データをもとに毎日自動生成される非公式の情報であり、厚生労働省および各製薬企業とは関係ありません。公表と実際の流通状況にタイムラグが生じる場合があります。医薬品の使用・変更は必ず医師・薬剤師にご相談ください。</p>
    <p>{esc(updated_note)}｜<a href="{SITE_ROOT}">医薬品供給ナビ</a></p>
  </footer>
</div>
</body>
</html>
"""


def index_html(entries, jst_today):
    """items/index.html — ステータス別の全ページ一覧(クローラーの巡回起点)。"""
    sections = []
    order = ["limited", "stopped", "ended", "ok"]
    heads = {"limited": "限定出荷の品目", "stopped": "供給停止の品目",
             "ended": "販売中止の品目", "ok": "通常出荷に戻った品目"}
    for stk in order:
        group = sorted([e for e in entries if e["status"] == stk], key=lambda e: e["name"])
        if not group:
            continue
        lis = "".join(
            f'<li><a href="{e["key"]}.html">{esc(e["name"])}</a>'
            f'<span class="mk">{esc(e["maker"])}</span></li>' for e in group)
        sections.append(
            f'<section><h2>{heads[stk]}（{len(group):,}品目）</h2><ul>{lis}</ul></section>')
    title = "品目別の供給状況一覧｜医薬品供給ナビ"
    desc = ("限定出荷・供給停止・販売中止となっている医療用医薬品の一覧。"
            "厚生労働省の医薬品供給状況データをもとに毎日自動更新しています。")
    # 個別ページ側と同じ階層を示す。item のURLは canonical と揃えること
    breadcrumb_ld = json.dumps({
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "医薬品供給ナビ", "item": SITE_ROOT},
            {"@type": "ListItem", "position": 2, "name": "品目別の供給状況",
             "item": SITE_ROOT + "items/index.html"},
        ]}, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{SITE_ROOT}items/index.html">
<meta name="apple-itunes-app" content="app-id=6777696446">
<script type="application/ld+json">{breadcrumb_ld}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:"Hiragino Sans","Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;color:#1C2A44;background:#F6F9FE;line-height:1.7}}
.wrap{{max-width:860px;margin:0 auto;padding:24px 18px 56px}}
h1{{font-size:22px;margin:14px 0 6px}}
.lede{{font-size:14px;color:#5A6B8C;margin-bottom:26px}}
.site a{{color:#2F63E8;text-decoration:none;font-weight:700;font-size:15px}}
section{{margin-bottom:30px}}
h2{{font-size:16px;margin-bottom:10px}}
ul{{list-style:none;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:8px}}
li{{background:#fff;border:1px solid #E3EAF6;border-radius:10px;padding:9px 12px;font-size:13.5px}}
li a{{color:#2F63E8;text-decoration:none;font-weight:600}}
.mk{{display:block;font-size:11.5px;color:#5A6B8C}}
footer{{font-size:12px;color:#5A6B8C;text-align:center;margin-top:30px}}
</style>
</head>
<body>
<div class="wrap">
  <header class="site"><a href="{SITE_ROOT}">💊 医薬品供給ナビ</a></header>
  <main>
    <h1>品目別の供給状況一覧</h1>
    <p class="lede">{esc(desc)}（{jst_today} 時点）</p>
    {''.join(sections)}
  </main>
  <footer>出典: 厚生労働省「医療用医薬品供給状況」｜<a href="{SITE_ROOT}">医薬品供給ナビ</a></footer>
</div>
</body>
</html>
"""


def sitemap_xml(key_dates, jst_today):
    """lastmod には各品目の実際の更新日を入れる。

    全URLに生成日を入れると「毎日2,000ページ全部が更新された」と申告することになり、
    lastmod が信頼できない値として扱われる。一覧ページだけは毎日作り直すので生成日でよい。
    """
    body = (f"  <url><loc>{SITE_ROOT}items/index.html</loc><lastmod>{jst_today}</lastmod>"
            f"<changefreq>daily</changefreq></url>\n")
    for k in sorted(key_dates):
        body += (f"  <url><loc>{SITE_ROOT}items/{k}.html</loc>"
                 f"<lastmod>{key_dates[k] or jst_today}</lastmod>"
                 f"<changefreq>daily</changefreq></url>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{body}</urlset>\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="drugs_app_ready.csv のパス")
    ap.add_argument("--site", required=True, help="出力先サイトルート(drugs-dataのクローン)")
    ap.add_argument("--max-pages", type=int, default=20000, help="生成ページ数の上限(安全弁)")
    args = ap.parse_args()

    site = Path(args.site)
    out = site / "items"
    out.mkdir(parents=True, exist_ok=True)  # ローカル検証で出力先が空でも動くように
    jst_today = datetime.now(timezone(timedelta(hours=9))).date().isoformat()

    rows = load_csv(Path(args.csv))
    print(f"CSV: {len(rows):,}行")

    by_key = {}
    for r in rows:
        by_key.setdefault(item_key(r), r)  # キー重複は先勝ち(YJコード重複はまれ)

    # 同成分リンク用: 一般名→行のインデックス
    by_gen = {}
    for r in rows:
        g = (r.get("一般名") or "").strip()
        if g:
            by_gen.setdefault(g, []).append(r)

    # 生成対象 = 供給に問題がある品目 + 薬価削除予定 + 既存ページでCSVに残っている品目
    existing = {p.stem for p in out.glob("*.html") if p.stem != "index"}
    targets = {}
    for k, r in by_key.items():
        s = map_status(r.get("供給状況") or "")
        if s != "ok" or is_delist(r) or k in existing:
            targets[k] = (r, s)
    if len(targets) > args.max_pages:
        print(f"::warning::対象{len(targets):,}件が上限{args.max_pages:,}を超えたため、"
              "問題ステータスの品目を優先して切り詰めます")
        problem = {k: v for k, v in targets.items() if v[1] != "ok"}
        targets = dict(list(problem.items())[:args.max_pages])

    generated_keys = set(targets)
    entries = []
    for k, (r, s) in targets.items():
        g = (r.get("一般名") or "").strip()
        sibs = pick_siblings(r, by_gen.get(g, []))
        (out / f"{k}.html").write_text(
            page_html(r, k, s, jst_today, sibs, generated_keys), encoding="utf-8")
        entries.append({"key": k, "name": r["商品名"].strip(), "status": s,
                        "maker": (r.get("販売メーカー") or r.get("製造メーカー") or "").strip()})

    (out / "index.html").write_text(index_html(entries, jst_today), encoding="utf-8")
    key_dates = {k: (r.get("更新日") or "").replace("/", "-").strip()
                 for k, (r, _) in targets.items()}
    (site / "sitemap-items.xml").write_text(sitemap_xml(key_dates, jst_today), encoding="utf-8")

    # 生成済みページのキー一覧。LPの詳細モーダルはこれを読み、実在するページにだけ
    # リンクする。判定ロジックの推測でリンクすると、定義のずれや生成タイミングの
    # ずれ(データ更新23:50 / 生成1:30)で404になるため、実在するキーを事実として渡す
    (out / "keys.json").write_text(
        json.dumps(sorted(generated_keys), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8")

    counts = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    print(f"生成: {len(entries):,}ページ + index.html + sitemap-items.xml")
    print("内訳:", ", ".join(f"{STATUSES[k]['label']} {v:,}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
