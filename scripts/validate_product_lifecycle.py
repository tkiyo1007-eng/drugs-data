#!/usr/bin/env python3
"""YJコード別の販売ライフサイクルデータを公開前に検証する。"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse


YJ_RE = re.compile(r"^[0-9A-Z]{12}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")
STATES = {"active", "discontinuation_announced", "discontinued"}
OFFICIAL_HOSTS = {
    "久光製薬": {"hisamitsu-pharm.jp"},
    "キョーリンリメディオ": {"kyorin-rmd.com"},
    "第一三共エスファ": {"daiichisankyo-ep.co.jp"},
    "日医工": {"nichiiko.co.jp"},
    "日本ジェネリック": {"nihon-generic.co.jp"},
    "日本ケミファ": {"nc-medical.com"},
    "東和薬品": {"towayakuhin.co.jp"},
    "沢井製薬": {"sawai.co.jp"},
    "高田製薬": {"takata-seiyaku.co.jp"},
    "ニプロ": {"nipro.co.jp"},
    "サンド": {"sandoz.com", "sandoz.jp"},
}


def norm(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def load_csv(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {(row.get("YJコード") or "").strip(): row for row in rows}


def validate(document: object, csv_rows: dict[str, dict[str, str]]) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["ルートはオブジェクトである必要があります"]
    if document.get("schema_version") != 1:
        errors.append("schema_version は 1 にしてください")
    generated_at = document.get("generated_at")
    try:
        dt.datetime.fromisoformat(generated_at)
    except (TypeError, ValueError):
        errors.append("generated_at はISO 8601形式で指定してください")

    products = document.get("products")
    if not isinstance(products, dict):
        return errors + ["products はYJコードをキーにしたオブジェクトである必要があります"]

    for yj_code, item in products.items():
        prefix = f"products.{yj_code}"
        if not isinstance(yj_code, str) or not YJ_RE.fullmatch(yj_code):
            errors.append(f"{prefix}: YJコードは半角英数字12桁で指定してください")
            continue
        if not isinstance(item, dict):
            errors.append(f"{prefix}: 値はオブジェクトである必要があります")
            continue
        state = item.get("state")
        if state not in STATES:
            errors.append(f"{prefix}.state: {sorted(STATES)} のいずれかを指定してください")
        row = csv_rows.get(yj_code)
        if row is None:
            errors.append(f"{prefix}: 供給状況CSVに存在しないYJコードです")
            continue

        product_name = item.get("product_name") or ""
        if norm(product_name) != norm(row.get("商品名") or ""):
            errors.append(
                f"{prefix}.product_name: CSVの商品名と一致しません"
                f"（CSV: {row.get('商品名') or ''}）"
            )
        maker = norm(item.get("maker") or "")
        makers = {norm(row.get("製造メーカー") or ""), norm(row.get("販売メーカー") or "")}
        if maker not in makers:
            errors.append(f"{prefix}.maker: CSVの製造・販売メーカーと一致しません")

        for field in ("announced_at", "supply_end_expected", "verified_at"):
            value = item.get(field)
            if value is not None and not DATE_RE.fullmatch(str(value)):
                errors.append(f"{prefix}.{field}: YYYY-MM または YYYY-MM-DD で指定してください")

        if state != "active":
            for field in ("product_name", "maker", "source_title", "source_url", "verified_at"):
                if not item.get(field):
                    errors.append(f"{prefix}.{field}: 販売中止情報では必須です")
            source = urlparse(str(item.get("source_url") or ""))
            if source.scheme != "https" or not source.netloc:
                errors.append(f"{prefix}.source_url: メーカー一次資料のHTTPS URLを指定してください")
            allowed_hosts = OFFICIAL_HOSTS.get(item.get("maker") or "")
            hostname = (source.hostname or "").lower()
            if not allowed_hosts:
                errors.append(f"{prefix}.maker: 公式ドメインの許可リストにないメーカーです")
            elif not any(hostname == host or hostname.endswith("." + host) for host in allowed_hosts):
                errors.append(f"{prefix}.source_url: {item.get('maker')}の公式ドメインではありません")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json", type=Path)
    parser.add_argument("--csv", type=Path, default=Path("DrugSupplyAssist/drugs_app_ready.csv"))
    args = parser.parse_args()

    with args.json.open(encoding="utf-8") as handle:
        document = json.load(handle)
    errors = validate(document, load_csv(args.csv))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(document['products'])}件の販売ライフサイクル情報を検証しました")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
