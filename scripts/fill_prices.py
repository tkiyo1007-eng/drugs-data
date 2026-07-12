#!/usr/bin/env python3
"""drugs_app_ready.csv の薬価・経過措置期限の空欄を薬価マスタから補完する。

夜間の自動更新（update_drugs.yml）は供給状況しか更新せず、新規品目の薬価は
空欄のまま追加されるため、このスクリプトで毎回補完する。

マッチング規則（安全側に倒す）:
1. YJコード完全一致
2. ブランド名一致 — YJコード先頭9桁（成分・剤形・規格まで同一）のグループ内に、
   商品名と同じ品名の銘柄別収載があればその薬価
3. 統一名収載 — 同グループ内のカッコ（「」/（））なしの共通名エントリの薬価。
   薬価基準で統一名収載された後発品は共通名の薬価が適用されるため。
   候補の薬価が一意に決まらない場合は補完しない（誤った値を入れない）

使い方: python3 scripts/fill_prices.py drugs_app_ready.csv yakka_master.csv
"""
import csv
import sys
import unicodedata


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s or "").replace(" ", "").replace("　", "")


def load_master(path):
    exact = {}      # YJ → entry
    group9 = {}     # YJ先頭9桁 → [entry]
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            yj = (r.get("YJコード") or "").strip()
            if not yj:
                continue
            e = {
                "price": (r.get("薬価") or "").strip(),
                "keika": (r.get("経過措置期限") or "").strip(),
                "name": (r.get("品名") or "").strip(),
                "seibun": (r.get("成分名") or "").strip(),
            }
            exact[yj] = e
            group9.setdefault(yj[:9], []).append(e)
    return exact, group9


def pick_entry(row, exact, group9):
    yj = (row.get("YJコード") or "").strip()
    if not yj:
        return None
    # 1. 完全一致
    e = exact.get(yj)
    if e and e["price"]:
        return e
    cands = [e for e in group9.get(yj[:9], []) if e["price"]]
    if not cands:
        return None
    # 2. ブランド名一致（銘柄別収載）
    name = nfkc(row.get("商品名"))
    brand = [e for e in cands if nfkc(e["name"]) == name]
    if brand:
        return brand[0]
    # 3. 統一名収載（カッコなしの共通名。成分名で始まるものに限定）
    unified = [
        e for e in cands
        if "「" not in e["name"] and "（" not in e["name"] and "(" not in e["name"]
        and e["seibun"] and nfkc(e["name"]).startswith(nfkc(e["seibun"])[:6])
    ]
    prices = {e["price"] for e in unified}
    if len(prices) == 1:
        return unified[0]
    return None  # 一意に決まらないときは補完しない


def main():
    csv_path, master_path = sys.argv[1], sys.argv[2]
    exact, group9 = load_master(master_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header = rows[0]
    i_price = header.index("薬価")
    i_keika = header.index("経過措置期限")
    filled = 0
    for c in rows[1:]:
        if len(c) <= max(i_price, i_keika) or c[i_price].strip():
            continue
        row = dict(zip(header, c))
        e = pick_entry(row, exact, group9)
        if not e:
            continue
        c[i_price] = e["price"]
        if not c[i_keika].strip() and e["keika"]:
            c[i_keika] = e["keika"]
        filled += 1
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)
    total = len(rows) - 1
    have = sum(1 for c in rows[1:] if len(c) > i_price and c[i_price].strip())
    print(f"✅ 薬価補完: {filled}件を追加補完 / 薬価あり {have}/{total}件 ({have/total*100:.1f}%)")


if __name__ == "__main__":
    main()
