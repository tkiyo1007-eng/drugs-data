"""Render the three selected X cards when their public data or artwork changes."""
from datetime import date
from hashlib import sha256
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
from string import Template
import sys
import tempfile
import unicodedata

KEYS = ("2359110B1037", "2646730Q1026", "3179106F1039")
ASSETS = Path(__file__).resolve().parent / "share_card_assets"
PNG_HEADER = b"\x89PNG\r\n\x1a\n"
DEFAULT = ("og_image.png", "医薬品供給ナビの供給状況サマリー")


def is_card(path):
    if not path.is_file():
        return False
    with path.open("rb") as source:
        header = source.read(24)
    return (header.startswith(PNG_HEADER) and header[12:16] == b"IHDR"
            and header[16:24] == struct.pack(">II", 1200, 630))


def render_card(markup, destination):
    chrome = shutil.which("google-chrome") or shutil.which("chromium") or (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        folder = Path(tmp).resolve()
        page = folder / "card.html"
        page.write_text(markup, encoding="utf-8")
        image = folder / "card.png"
        subprocess.run([chrome, "--headless", "--disable-gpu", "--disable-dev-shm-usage",
                        "--no-sandbox", "--hide-scrollbars", "--no-first-run",
                        "--force-device-scale-factor=1", "--window-size=1200,630",
                        "--run-all-compositor-stages-before-draw", "--virtual-time-budget=2500",
                        f"--user-data-dir={folder / 'profile'}", f"--screenshot={image}", page.as_uri()],
                       check=True, capture_output=True, timeout=45)
        if not is_card(image):
            raise ValueError("共有カードのPNG寸法を確認できません")
        os.replace(image, destination)


def prepare(site, targets, source_date):
    """Return metadata only for images that match this release's records."""
    if not source_date or not any(key in targets for key in KEYS):
        return {}
    icon = site / "icon-192.png"
    if not icon.is_file():
        return {}
    folder = site / "items" / "share-cards"
    folder.mkdir(parents=True, exist_ok=True)
    state_file = folder / "versions.json"
    try:
        old = json.loads(state_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        old = {}
    if not isinstance(old, dict):
        old = {}
    versions = {}
    metadata = {}
    font = ASSETS / "card-jp.woff2"
    template = Template((ASSETS / "card.html").read_text(encoding="utf-8"))
    design = sha256(template.template.encode() + font.read_bytes() + icon.read_bytes()).hexdigest()
    day = date.fromisoformat(source_date)
    label = f"{day.year}年{day.month}月{day.day}日時点"
    for key in KEYS:
        if key not in targets:
            continue
        row, kind = targets[key]
        name = unicodedata.normalize("NFKC", row["商品名"]).strip()
        maker = (row.get("販売メーカー") or row.get("製造メーカー") or "").strip()
        status = (row.get("供給状況") or "").strip()
        if not all((name, maker, status)):
            continue
        signature = json.dumps([design, name, maker, status, kind, source_date], ensure_ascii=False)
        rev = sha256(signature.encode()).hexdigest()[:16]
        destination = folder / f"{key}.png"
        if old.get(key) != rev or not is_card(destination):
            title = re.sub(r"(LD|0\.05%)$", r'<span class="suffix">\1</span>', escape(name))
            badge = re.sub(r"^([①-⑳])(.+)$", r'<span class="code">\1</span><span>\2</span>', escape(status))
            markup = template.substitute(title=title, maker=escape(maker), status=badge, kind=escape(kind),
                                         date_label=label, icon=icon.resolve().as_uri(), font=font.as_uri())
            try:
                render_card(markup, destination)
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                print(f"::warning::{key} の共有カード生成失敗、共通画像を使用: {exc}", file=sys.stderr)
                continue
        versions[key] = rev
        metadata[key] = (f"items/share-cards/{key}.png?v={rev}", f"{maker} {name}｜{status}｜厚生労働省公表 {label}")
    if versions != old:
        with tempfile.NamedTemporaryFile(mode="w", dir=folder, delete=False, encoding="utf-8") as output:
            output.write(json.dumps(versions, indent=2) + "\n")
        os.replace(output.name, state_file)
    return metadata
