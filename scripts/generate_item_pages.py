#!/usr/bin/env python3
"""drugs_app_ready.csv から品目別の静的ページを生成するSEO用スクリプト。

「(薬品名) 出荷調整」「(薬品名) 供給」のような検索に1品目=1ページで応えるための
ランディングページ群を作る。GitHub Actions(generate-item-pages.yml)が毎晩、
データ更新後に drugs-data リポジトリ内で実行し、items/ 配下へ出力する。

生成対象:
  - 供給に問題がある品目(限定出荷・供給停止・販売中止)と薬価削除予定の品目
  - 過去に生成済みでCSVにまだ存在する品目(通常出荷に戻ってもURLを404にしないため
    最新状態で再生成し続ける。CSVから消えた品目の旧ページは誤表示防止のため削除)

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
import unicodedata
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

SITE_ROOT = "https://tkiyo1007-eng.github.io/drugs-data/"
APP_STORE = "https://apps.apple.com/jp/app/%E5%8C%BB%E8%96%AC%E5%93%81%E4%BE%9B%E7%B5%A6%E3%83%8A%E3%83%93/id6777696446"
APP_ID = "6777696446"
FORMAL_YJ_RE = re.compile(r"^[0-9][0-9A-Z]{11}$")

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
    "ok":      "厚生労働省公表データ上、通常出荷として収録されています。メーカー案内や実際の流通状況と異なる場合があります。",
    "limited": "厚生労働省公表データ上、限定出荷として収録されています。実際の受注可否は卸・メーカーにご確認ください。",
    "stopped": "厚生労働省公表データ上、供給停止として収録されています。出荷再開の見込みはメーカーの案内もご確認ください。",
    "ended":   "厚生労働省公表データ上、販売中止として収録されています。今後の対応はメーカー・卸の最新情報も確認し、医師・薬剤師等の専門職でご判断ください。",
}
# 詳細表で優先的に上へ並べる列(LPの DETAIL_ORDER と同じ考え方)
DETAIL_ORDER = ["規格", "供給状況", "理由", "解除・解消見込み", "出荷量状況", "代替候補", "一般名", "製造メーカー",
                "販売メーカー", "薬効分類", "薬価", "経過措置期限",
                "ステータス更新日", "更新日", "YJコード"]
SKIP_COLS = {"商品名", "今回更新"}
SUPPLY_METADATA_RE = re.compile(
    r"^解除/解消見込み:\s*(.*?)\s*/\s*出荷量状況:\s*(.*)$")


def split_supply_metadata(label: str, value: str) -> list[tuple[str, str]]:
    """CSVの誤解を招く列名を、収録内容に即した表示項目へ分ける。"""
    if label != "代替候補":
        return [(label, value)]
    match = SUPPLY_METADATA_RE.match(value)
    if not match:
        return [(label, value)]
    return [("解除・解消見込み", match.group(1).strip()),
            ("出荷量状況", match.group(2).strip())]


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
# 同成分・同剤形の関連品目を確認する人が直接たどり着くページなので、LPと同じ精度で絞り込む。
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
    """厚労省公表区分の並び順用。薬価削除予定は通常出荷より後ろに置く。"""
    base = SEV[map_status(row.get("供給状況") or "")]
    return max(SEV["ended"], base) if is_delist(row) else base


def pick_siblings(row: dict, candidates: list) -> list:
    """同成分・同剤形の他社品を、厚労省公表区分の順に返す。"""
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


def smart_app_banner_content(row: dict) -> str:
    """品目ページから、正式YJコードに限って同じ品目のアプリ検索へ渡す。"""
    content = f"app-id={APP_ID}"
    yj = (row.get("YJコード") or "").strip()
    # X+5桁の内部IDはiOSのYJコード検索対象ではない。結果0件へ遷移させず、
    # 従来どおりアプリの通常入口を開く。
    if not FORMAL_YJ_RE.fullmatch(yj):
        return content
    app_url = "drugsupplynavi://search?q=" + quote(yj, safe="")
    return f"{content}, app-argument={app_url}"


def load_csv(path: Path):
    text = path.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    return [r for r in rows if (r.get("商品名") or "").strip()]


def load_required_json(path: Path, label: str) -> dict:
    """安全表示に必要なJSONを読み、欠落・破損時は公開生成を止める。"""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label}を読み込めません: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label}のルートがオブジェクトではありません: {path}")
    return value


def validated_product_map(document: dict, label: str) -> dict:
    products = document.get("products")
    if document.get("schema_version") != 1 or not isinstance(products, dict):
        raise ValueError(f"{label}のschema_versionまたはproductsが不正です")
    return products


def version_date(version: dict) -> str:
    """version.jsonからデータセット全体の基準日をYYYY-MM-DDで返す。"""
    text = f'{version.get("note", "")} {version.get("version", "")}'
    match = (re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", text)
             or re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
             or re.search(r"\b(\d{4})(\d{2})(\d{2})\d*\b", text))
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or ""))).casefold()


SUPPLEMENTAL_MAKER_ALIASES = {
    # 日本ジェネリックの公式案内には、製造販売元の長生堂製薬品も掲載される。
    "日本ジェネリック": {"長生堂製薬"},
}


def maker_tokens(value: str) -> set:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return {token for token in re.split(r"[・／/,、;；\s]+", normalized) if token}


def supplemental_maker(item: dict) -> str:
    manufacturer = item.get("manufacturer")
    return str(item.get("maker") or (manufacturer.get("maker") if isinstance(manufacturer, dict) else "") or "")


def row_maker_matches(row: dict, maker: str) -> bool:
    source_makers = maker_tokens(maker)
    for source_maker in list(source_makers):
        source_makers.update(SUPPLEMENTAL_MAKER_ALIASES.get(source_maker, set()))
    row_makers = maker_tokens(row.get("販売メーカー")) | maker_tokens(row.get("製造メーカー"))
    return bool(source_makers and row_makers and source_makers.intersection(row_makers))


def supplemental_matches(row: dict, item: dict = None) -> bool:
    """YJキーに加え商品名・メーカーも一致した補足情報だけを表示する。"""
    if not item or normalized_text(item.get("product_name")) != normalized_text(row.get("商品名")):
        return False
    return row_maker_matches(row, supplemental_maker(item))


def discrepancy_matches(row: dict, item: dict = None) -> bool:
    if (not item
            or normalized_text(item.get("product_name")) != normalized_text(row.get("商品名"))):
        return False
    official = item.get("official")
    manufacturer = item.get("manufacturer")
    if (not isinstance(official, dict) or not isinstance(manufacturer, dict)
            or not row_maker_matches(row, manufacturer.get("maker"))):
        return False
    expected_status = map_status(row.get("供給状況") or "")
    expected_label = STATUSES[expected_status]["label"]
    expected_date = official_row_date(row)
    official_date = iso_publication_date(official.get("updated_at"))
    label = str(official.get("label") or "")
    label_matches = label == expected_label or (
        expected_status == "limited" and label.startswith("限定出荷"))
    return (official.get("status") == expected_status
            and label_matches
            and bool(expected_date and official_date == expected_date))


def should_generate(row: dict, key: str, existing: set[str],
                    lifecycle_products: dict, discrepancy_products: dict) -> bool:
    return (map_status(row.get("供給状況") or "") != "ok"
            or is_delist(row)
            or supplemental_matches(row, lifecycle_products.get(key))
            or discrepancy_matches(row, discrepancy_products.get(key))
            or key in existing)


def lifecycle_verification_is_recent(lifecycle: dict, reference_date: str) -> bool:
    verified = iso_publication_date((lifecycle or {}).get("verified_at"))
    reference = iso_publication_date(reference_date)
    if not verified or not reference:
        return False
    age = (date.fromisoformat(reference) - date.fromisoformat(verified)).days
    return 0 <= age < 7


def supplemental_labels(row: dict, lifecycle=None, discrepancy=None,
                        reference_date="", trusted=True) -> list:
    """検索・共有・一覧にも出す、検証済みメーカー補足ラベルを返す。"""
    labels = []
    if supplemental_matches(row, lifecycle):
        lifecycle_current = trusted and lifecycle_verification_is_recent(
            lifecycle, reference_date)
        labels.append("メーカー：販売中止予定" if lifecycle_current
                      else "メーカー：販売中止案内あり（要原文確認）")
    if discrepancy_matches(row, discrepancy):
        manufacturer = discrepancy.get("manufacturer") or {}
        high = (trusted and discrepancy.get("confidence") == "high"
                and manufacturer.get("scope") == "product")
        label = (manufacturer.get("label") or "").strip()
        labels.append(f"メーカー：{label}" if high and label
                      else "メーカー案内あり（要原文確認）")
    return list(dict.fromkeys(labels))


def iso_publication_date(value: str) -> str:
    match = re.search(r"(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?", str(value or ""))
    if not match:
        return ""
    return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def official_row_date(row: dict) -> str:
    """厚労省の品目行で確認できる最新日を返す。

    供給差異builderと同じく、一般更新日とステータス更新日の新しい方を使う。
    """
    dates = [iso_publication_date(row.get(field))
             for field in ("更新日", "ステータス更新日")]
    valid = [value for value in dates if value]
    return max(valid) if valid else ""


def latest_publication_date(row: dict, lifecycle=None, discrepancy=None) -> str:
    """品目行または検証済みメーカー案内のうち、最も新しい公表日を返す。"""
    dates = [official_row_date(row)]
    if supplemental_matches(row, lifecycle):
        dates.append(iso_publication_date(lifecycle.get("announced_at")))
    if discrepancy_matches(row, discrepancy):
        dates.append(iso_publication_date((discrepancy.get("manufacturer") or {}).get("announced_at")))
    valid = [date for date in dates if date]
    return max(valid) if valid else ""


def supplemental_context(health: dict, discrepancy_document: dict,
                         dataset_date: str) -> dict:
    """メーカー補足の確認状態を返す。

    補足元の一時障害や確認日の古さで厚労省CSVの更新まで止めない。補足の
    断定表示だけを止め、静的ページは公式区分を最新に保ったまま生成する。
    JSON自体の欠落・破損はload_required_json側で引き続き生成失敗にする。
    """
    sources = health.get("sources")
    checked = iso_publication_date(health.get("checked"))
    source = discrepancy_document.get("source")
    warnings = []
    if (not isinstance(sources, list) or not sources
            or any(not isinstance(item, dict) or item.get("ok") is not True
                   for item in sources)):
        warnings.append("メーカー収集元の健全性確認が完了していません")
    if not checked:
        warnings.append("メーカー補足情報の確認日を取得できません")
    if not isinstance(source, dict):
        warnings.append("供給差異データの参照情報を取得できません")
        source = {}
    mhlw_date = version_date({
        "note": source.get("mhlw_note", ""),
        "version": source.get("mhlw_version", ""),
    })
    manufacturer_date = iso_publication_date(source.get("manufacturer_checked_through"))
    if mhlw_date != dataset_date:
        warnings.append("供給差異データの厚労省参照日が公開データ基準日と一致しません")
    if not checked or manufacturer_date != checked:
        warnings.append("供給差異データとメーカー収集健全性の確認日が一致しません")
    if checked:
        age = (date.fromisoformat(dataset_date) - date.fromisoformat(checked)).days
        if age < 0 or age >= 7:
            warnings.append("メーカー補足情報の確認日が7日以上前です")
    return {
        "checked": checked,
        "trusted": not warnings,
        "warning": "。".join(dict.fromkeys(warnings)),
    }


def reconcile_existing_pages(out: Path, current_keys: set) -> tuple:
    """CSVから消えた旧ページを削除し、古い供給区分を現行情報に見せない。"""
    existing = {path.stem for path in out.glob("*.html") if path.stem != "index"}
    stale = existing - current_keys
    for key in sorted(stale):
        (out / f"{key}.html").unlink()
    return existing - stale, stale


def page_title(name: str, status_label: str, supplements: list) -> str:
    """検索結果で意味を保ちつつ、HTMLの推奨70文字以内へ収める。"""
    suffix = "｜医薬品供給ナビ"
    candidates = [
        (f"{name}の供給状況｜厚労省：{status_label}"
         + ("｜メーカー補足あり" if supplements else "") + suffix),
        f"{name}の供給状況｜{status_label}{suffix}",
        f"{name}｜供給状況{suffix}",
    ]
    for candidate in candidates:
        if len(candidate) <= 70:
            return candidate
    tail = f"…｜供給状況{suffix}"
    return name[:max(1, 70 - len(tail))] + tail


def page_html(row, key, status, jst_today, siblings, generated_keys,
              lifecycle=None, discrepancy=None, dataset_date="", supplemental_checked_date="",
              supplemental_trusted=True, supplemental_warning=""):
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
    lifecycle_match = lifecycle if supplemental_matches(row, lifecycle) else None
    discrepancy_match = discrepancy if discrepancy_matches(row, discrepancy) else None
    supplements = supplemental_labels(
        row, lifecycle_match, discrepancy_match, supplemental_checked_date,
        supplemental_trusted)
    lifecycle_current = bool(supplemental_trusted and lifecycle_match
                             and lifecycle_verification_is_recent(
                                 lifecycle_match, supplemental_checked_date))
    supplemental_tags = "".join(
        f'<span class="tag supplemental">{esc(label)}</span>' for label in supplements)
    supplemental_checked = ""
    if supplements:
        supplemental_checked = (f'<p class="supp-checked">メーカー補足情報の確認日：'
                                f'{esc(supplemental_checked_date or "確認できません")}</p>')
        if supplemental_warning:
            supplemental_checked += (f'<p class="supp-warning" role="status">'
                                     f'補足情報の確認注意：{esc(supplemental_warning)}。'
                                     'メーカー原文を再確認してください。</p>')
    # ページ内に「生成日」を書かない。書くと供給状況が何も変わっていない日でも
    # 全ページのHTMLが差し替わり、drugs-data に毎日2,000件規模の無意味なコミットが
    # 積まれてしまう（履歴から「実際に何が変わったか」が読めなくなる）
    # 全体基準日はversion.jsonからブラウザで取得する。HTMLへ日付を埋め込むと、
    # 品目自体が変わらない日も全ページが差分になり、履歴と配信量が膨らむため。
    dataset_context = ('<p class="dataset-context">サイト全体の公開データ基準日：'
                       '<span class="dataset-date" aria-live="polite">確認中</span>。'
                       'これはこの静的ページの生成日ではありません。'
                       'この品目行の最終変更日は下表の「更新日／ステータス更新日」をご確認ください。</p>')
    title = page_title(name, st["label"], supplements)
    desc = (f"{name}（{maker}）の厚生労働省公表データ上の供給区分は「{st['label']}」"
            + ("（薬価削除予定）" if delist else "")
            + (f"。メーカー公式補足は「{'／'.join(supplements)}」" if supplements else "")
            + "。サイト全体の最新基準日はページ上で別途表示します。"
            + "理由・解除見込み・出荷量状況・同成分の他社品は、公表されている場合に確認できます。")
    url = f"{SITE_ROOT}items/{key}.html"
    # 商品名は同名品目があるため、LPの詳細リンクも一意な品目キーを使う。
    lp_link = SITE_ROOT + "#item=" + quote(key, safe="")
    pmda = "https://www.pmda.go.jp/PmdaSearch/iyakuSearch/?nameWord=" + quote(name, safe="")
    smart_app_banner = esc(smart_app_banner_content(row))

    lifecycle_box = ""
    if lifecycle_match:
        lifecycle_url = lifecycle_match.get("source_url") or ""
        lifecycle_link = (f'<a href="{esc(lifecycle_url)}" target="_blank" rel="noopener">'
                          'メーカー公式案内の原文を確認</a>'
                          if lifecycle_url.startswith("https://") else "")
        lifecycle_box = f'''<div class="supp supp-life">
      <strong>メーカー公式：{"販売中止予定" if lifecycle_current else "販売中止案内あり（要原文確認）"}</strong>
      <p>{esc(lifecycle_match.get("source_title") or "販売中止の案内")}'''
        if lifecycle_match.get("announced_at"):
            lifecycle_box += f'（公表 {esc(lifecycle_match.get("announced_at"))}）'
        verified_at = esc(lifecycle_match.get("verified_at") or "確認日不明")
        lifecycle_box += (f'''</p><p>案内の最終確認日：{verified_at}。{"確認日が7日以上前のため、現在の扱いは必ず原文で再確認してください。" if not lifecycle_current else "厚労省の現在の供給区分と、メーカーの今後の販売予定は別の情報として併記しています。"}</p>{lifecycle_link}</div>''')

    discrepancy_box = ""
    if discrepancy_match:
        official = discrepancy_match.get("official") or {}
        manufacturer = discrepancy_match.get("manufacturer") or {}
        high = (supplemental_trusted and discrepancy_match.get("confidence") == "high"
                and manufacturer.get("scope") == "product")
        source_url = manufacturer.get("url") or ""
        source_link = (f'<a href="{esc(source_url)}" target="_blank" rel="noopener">'
                       'メーカー公式案内の原文を確認</a>'
                       if source_url.startswith("https://") else "")
        discrepancy_box = f'''<div class="supp supp-diff">
      <strong>{"情報差異あり" if high else "メーカー案内あり・対象規格を原文確認"}</strong>
      <p>厚労省公表：{esc(official.get("label") or "—")}（{esc(official.get("updated_at") or "更新日不明")}）<br>
      {"メーカー公式" if supplemental_trusted else "収録済みメーカー案内（要原文確認）"}：{esc(manufacturer.get("label") or "—")}（{esc(manufacturer.get("announced_at") or "公表日不明")}）</p>
      <p>厚労省区分は上書きせず、より新しいメーカー案内を併記しています。実際の受注可否は卸・メーカーにもご確認ください。</p>{source_link}</div>'''

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
        for shown_col, shown_value in split_supply_metadata(col, v):
            if shown_value:
                detail_rows.append(
                    f'<tr><th scope="row">{esc(shown_col)}</th><td>{esc(shown_value)}</td></tr>')

    # 同成分(一般名が同じ)の他社品。生成済みページがあれば内部リンク、なければLPの詳細へ
    sib_html = ""
    if siblings:
        lis = []
        for s in siblings[:12]:
            s_key = item_key(s)
            s_status = map_status(s.get("供給状況") or "")
            s_st = STATUSES[s_status]
            href = (f"{s_key}.html" if s_key in generated_keys
                    else SITE_ROOT + "#item=" + quote(s_key, safe=""))
            lis.append(
                f'<li><a href="{href}">{esc(s["商品名"])}</a>'
                f'<span class="tag status-{s_status}">{s_st["label"]}</span>'
                f'<span class="mk">{esc((s.get("販売メーカー") or s.get("製造メーカー") or "").strip())}</span></li>')
        warm_note = ("この品目は温感タイプのため、温感タイプの品目のみを表示しています。"
                     if is_warm_patch(row) else "")
        sib_html = f"""
<section>
  <h2>同成分・同剤形（{esc(gen)}）の他社品の供給状況</h2>
  <p class="sib-note">厚生労働省公表区分上の通常出荷を先に表示しています。代替適否や実在庫を示す順位ではありません。{esc(warm_note)}適応・規格・剤形の互換性は必ず添付文書と医師・薬剤師の判断でご確認ください。</p>
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
<meta name="robots" content="index,follow,max-image-preview:large">
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
<meta name="apple-itunes-app" content="{smart_app_banner}">
<script type="application/ld+json">{breadcrumb_ld}</script>
<script src="../analytics.js"></script>
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
.tag.supplemental{{color:#6B4310;background:#FFF3D8;border:1px solid #E4B662}}
.delist-box{{color:#7A5E49;background:#F7F1EA;border:1px solid #E3D5C6}} /* 5.31:1 */
.supp{{border-radius:12px;padding:14px 16px;font-size:13px;margin:0 0 14px;line-height:1.7}}
.supp strong{{display:block;margin-bottom:4px}}
.supp p{{margin:3px 0}}
.supp a{{display:inline-block;margin-top:5px;color:inherit;font-weight:700}}
.supp-life{{color:#6B4310;background:#FFF3D8;border:1px solid #E4B662}}
.supp-diff{{color:#5B4100;background:#FFF0B8;border:1px solid #D69B00}}
.supp-checked{{color:#704700;font-size:12px;font-weight:700;margin:0 0 10px}}
.supp-warning{{color:#8A3B12;background:#FFF4E8;border:1px solid #F1C69E;border-radius:8px;padding:8px 10px;font-size:12px;font-weight:700;margin:0 0 12px}}
.dataset-context{{color:var(--sub);font-size:12px;line-height:1.7;margin:-8px 0 14px}}
.dataset-warning{{color:#704700;background:#FFF3CF;border:1px solid #E4B662;border-radius:10px;padding:9px 12px;font-size:12px;margin:0 0 14px}}
.dataset-warning[hidden]{{display:none}}
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
.share{{min-height:44px;border:1px solid #B9C9EA;border-radius:999px;background:#fff;color:var(--blue);font:inherit;font-weight:700;padding:8px 16px;cursor:pointer}}
.share-status{{font-size:12px;color:var(--sub);min-height:1.6em;margin-top:5px}}
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
    <h1>{esc(name)}<span class="tag status-{status}">厚労省：{st['label']}</span>{supplemental_tags}{delist_tag}</h1>
    <p class="maker">{esc(maker)}{('｜' + esc(spec)) if spec else ''}</p>
    <div class="stbox status-{status}">
      厚生労働省公表データ上の供給区分は「<strong>{st['label']}</strong>」です。{STATUS_NOTES[status]}
    </div>
    {dataset_context}
    <p class="dataset-warning" id="datasetWarning" role="status" hidden></p>
{delist_box}
{supplemental_checked}
{lifecycle_box}
{discrepancy_box}
    <table><tbody>{''.join(detail_rows)}</tbody></table>
    <p class="links">
      <a href="{lp_link}" data-dsn-event="item-web-open">Web版でこの品目を開く（同成分・同剤形の一覧つき）</a>
      <a href="{pmda}" target="_blank" rel="noopener">PMDAで添付文書を探す</a>
    </p>
    <button class="share" id="shareButton" type="button">この品目ページを共有</button>
    <p class="share-status" id="shareStatus" role="status" aria-live="polite"></p>
  </div>
{sib_html}
  <div class="cta">
    <h2>供給状況の変化を、毎日自動でチェック。</h2>
    <p>医薬品供給ナビは厚労省の医薬品供給状況データ約16,000品目を毎日自動更新。お気に入り登録した品目が「限定出荷」や「出荷再開」に変わるとすぐ分かります。無料です。</p>
    <a href="{APP_STORE}" data-dsn-event="item-app-store-open">App Storeで入手</a>
    <a class="ghost" href="{lp_link}" data-dsn-event="item-web-open">Web版でこの品目を開く</a>
    <p>開いた品目は、★を押すとこのブラウザの監視リストへ保存できます。</p>
  </div>
  </main>
  <footer>
    <p class="note">本ページは厚生労働省「医療用医薬品供給状況」の公表データをもとに毎日自動生成される非公式の情報であり、厚生労働省および各製薬企業とは関係ありません。公表と実際の流通状況にタイムラグが生じる場合があります。医薬品の使用・変更は必ず医師・薬剤師にご相談ください。</p>
    <p>サイト全体の公開データ基準日 <span class="dataset-date" aria-live="polite">確認中</span>｜<a href="{SITE_ROOT}">医薬品供給ナビ</a></p>
  </footer>
</div>
<script>
(function(){{
  const button = document.getElementById("shareButton");
  const status = document.getElementById("shareStatus");
  if(button) button.addEventListener("click", async function(){{
    const url = new URL(location.href);
    url.searchParams.set("src", "share");
    try{{
      if(navigator.share) await navigator.share({{title:document.title, url:url.href}});
      else await navigator.clipboard.writeText(url.href);
      status.textContent = navigator.share ? "共有しました。" : "共有用リンクをコピーしました。";
      if(window.dsnTrack) window.dsnTrack("item-share-success");
    }}catch(error){{
      if(error && error.name !== "AbortError") status.textContent = "共有できませんでした。URL欄からリンクをコピーしてください。";
    }}
  }});
  const datasetWarning = document.getElementById("datasetWarning");
  fetch("../version.json", {{cache:"no-cache"}})
    .then(function(response){{
      if(!response.ok) throw new Error("version");
      const cached = response.headers.get("X-DSN-Source") === "cache";
      return response.json().then(function(version){{ return {{version:version,cached:cached}}; }});
    }})
    .then(function(result){{
      const version = result.version;
      const text = String(version.note || "") + " " + String(version.version || "");
      const match = text.match(/(\d{{4}})年(\d{{1,2}})月(\d{{1,2}})日/) || text.match(/\\b(\d{{4}})(\d{{2}})(\d{{2}})\d*\\b/);
      const date = match ? match[1] + "-" + String(match[2]).padStart(2,"0") + "-" + String(match[3]).padStart(2,"0") : "確認できません";
      const label = date + (result.cached ? "（前回取得）" : "");
      document.querySelectorAll(".dataset-date").forEach(function(node){{ node.textContent = label; }});
      if(result.cached){{
        datasetWarning.textContent = "オフライン等のため、前回取得したデータ基準日を表示しています。接続後に再読み込みしてください。";
        datasetWarning.hidden = false;
      }}else if(date !== "確認できません"){{
        const ageDays = Math.floor((Date.now() - Date.parse(date + "T00:00:00+09:00")) / 86400000);
        if(ageDays < 0 || ageDays >= 7){{
          datasetWarning.textContent = "公開データ基準日が7日以上更新されていません。重要な判断では厚生労働省公式とメーカー案内もご確認ください。";
          datasetWarning.hidden = false;
        }}
      }}
    }})
    .catch(function(){{
      document.querySelectorAll(".dataset-date").forEach(function(node){{ node.textContent = "確認できません"; }});
      datasetWarning.textContent = "全体データ基準日を確認できません。重要な判断では厚生労働省公式とメーカー案内もご確認ください。";
      datasetWarning.hidden = false;
    }});
}})();
</script>
<script data-goatcounter="https://kt1007.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
</body>
</html>
"""


def index_html(entries, dataset_date):
    """items/index.html — ステータス別の全ページ一覧(クローラーの巡回起点)。"""
    sections = []
    order = ["supplemental", "limited", "stopped", "ended", "ok"]
    heads = {
        "supplemental": "メーカー公式の補足情報がある品目",
        "limited": "厚労省公表区分が限定出荷の品目",
        "stopped": "厚労省公表区分が供給停止の品目",
        "ended": "厚労省公表区分が販売中止の品目",
        "ok": "厚労省公表区分が通常出荷の品目",
    }
    for stk in order:
        group = sorted([
            e for e in entries
            if (stk == "supplemental" and e.get("supplements"))
            or (stk != "supplemental" and e["status"] == stk)
        ], key=lambda e: e["name"])
        if not group:
            continue
        lis = "".join(
            f'<li><a href="{e["key"]}.html">{esc(e["name"])}</a>'
            f'<span class="mk">{esc(e["maker"])}｜厚労省：{esc(STATUSES[e["status"]]["label"])}'
            f'{("／" + esc("／".join(e.get("supplements", [])))) if e.get("supplements") else ""}</span></li>'
            for e in group)
        sections.append(
            f'<section><h2>{heads[stk]}（{len(group):,}品目）</h2><ul>{lis}</ul></section>')
    title = "品目別の供給状況一覧｜医薬品供給ナビ"
    desc = ("厚生労働省公表の供給区分と、検証済みメーカー公式案内を分けて確認できる医療用医薬品一覧。"
            "供給停止・限定出荷・販売中止予定などを毎日自動更新しています。")
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
<meta name="robots" content="index,follow,max-image-preview:large">
<link rel="canonical" href="{SITE_ROOT}items/index.html">
<meta name="apple-itunes-app" content="app-id=6777696446">
<script type="application/ld+json">{breadcrumb_ld}</script>
<script src="../analytics.js"></script>
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
    <p class="lede">{esc(desc)}（全体データ基準日 {esc(dataset_date or "確認できません")}）</p>
    {''.join(sections)}
  </main>
  <footer>出典: 厚生労働省「医療用医薬品供給状況」｜<a href="{SITE_ROOT}">医薬品供給ナビ</a></footer>
</div>
<script data-goatcounter="https://kt1007.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>
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

    try:
        lifecycle_doc = load_required_json(site / "product_lifecycle.json", "販売中止補足データ")
        discrepancy_doc = load_required_json(site / "supply_discrepancies.json", "供給差異データ")
        version_doc = load_required_json(site / "version.json", "データ基準日")
        health_doc = load_required_json(site / "maker_collection_health.json", "メーカー収集健全性")
        lifecycle_products = validated_product_map(lifecycle_doc, "販売中止補足データ")
        discrepancy_products = validated_product_map(discrepancy_doc, "供給差異データ")
        dataset_date = version_date(version_doc)
        if not dataset_date:
            raise ValueError("version.jsonからデータ基準日を確認できません")
        supplemental_state = supplemental_context(
            health_doc, discrepancy_doc, dataset_date)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    if not supplemental_state["trusted"]:
        print(f'::warning::メーカー補足を要原文確認表示へ降格します: '
              f'{supplemental_state["warning"]}', file=sys.stderr)

    by_key = {}
    for r in rows:
        by_key.setdefault(item_key(r), r)  # キー重複は先勝ち(YJコード重複はまれ)

    # 同成分リンク用: 一般名→行のインデックス
    by_gen = {}
    for r in rows:
        g = (r.get("一般名") or "").strip()
        if g:
            by_gen.setdefault(g, []).append(r)

    # 生成対象 = 供給に問題がある品目 + 薬価削除予定 + メーカー補足情報 +
    # 既存ページでCSVに残っている品目。厚労省区分が通常出荷でも、
    # 販売中止予定やより新しいメーカー限定出荷がある品目は静的ページを作る。
    existing, removed_stale = reconcile_existing_pages(out, set(by_key))
    targets = {}
    for k, r in by_key.items():
        s = map_status(r.get("供給状況") or "")
        if should_generate(r, k, existing, lifecycle_products, discrepancy_products):
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
            page_html(
                r, k, s, jst_today, sibs, generated_keys,
                lifecycle=lifecycle_products.get(k),
                discrepancy=discrepancy_products.get(k),
                dataset_date=dataset_date,
                supplemental_checked_date=supplemental_state["checked"],
                supplemental_trusted=supplemental_state["trusted"],
                supplemental_warning=supplemental_state["warning"],
            ), encoding="utf-8")
        lifecycle = lifecycle_products.get(k)
        discrepancy = discrepancy_products.get(k)
        entries.append({"key": k, "name": r["商品名"].strip(), "status": s,
                        "maker": (r.get("販売メーカー") or r.get("製造メーカー") or "").strip(),
                        "supplements": supplemental_labels(
                            r, lifecycle, discrepancy, supplemental_state["checked"],
                            supplemental_state["trusted"])})

    (out / "index.html").write_text(index_html(entries, dataset_date), encoding="utf-8")
    key_dates = {
        k: latest_publication_date(r, lifecycle_products.get(k), discrepancy_products.get(k))
        for k, (r, _) in targets.items()
    }
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
    if removed_stale:
        print(f"削除: 現行CSVに存在しない旧ページ {len(removed_stale):,}件")
    print("内訳:", ", ".join(f"{STATUSES[k]['label']} {v:,}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
