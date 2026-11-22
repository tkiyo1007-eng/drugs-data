#!/usr/bin/env python3
"""Collect official recall index entries, retaining each class if its index fails."""
import argparse
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

JST = dt.timezone(dt.timedelta(hours=9))
PMDA = "https://www.info.pmda.go.jp"
CLASSES = {1: "I", 2: "II", 3: "III"}
MAX_BYTES = 2_000_000


class RecallTable(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = None
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            self.cell = [[], []]
        elif tag == "a" and self.cell is not None:
            self.cell[1].extend(value for key, value in attrs if key == "href" and value)
        elif tag == "br" and self.cell is not None and "".join(self.cell[0]).strip():
            self.cell[0].append(" / ")

    def handle_data(self, value):
        if self.cell is not None:
            self.cell[0].append(value)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            parts, links = self.cell
            self.row.append((" ".join("".join(parts).split()), links))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def parse_index(body, category):
    table = RecallTable()
    table.feed(body)
    table.close()
    if not any([cell[0] for cell in row[:5]] ==
               ["番号", "掲載年月日", "種類", "一般名", "販売名"] for row in table.rows):
        raise ValueError("PMDA回収一覧の見出しが見つかりません")
    items = []
    for row in table.rows:
        if len(row) < 7 or not re.fullmatch(rf"{category}-\d+", row[0][0]):
            continue
        number, date, kind, _, name, maker, notes = (cell[0] for cell in row[:7])
        if kind != "医薬品" or "体外診断用医薬品" in notes:
            continue
        path = f"/rgo/MainServlet?recallno={number}"
        if not name or not maker or not any(href in (path, PMDA + path) for href in row[4][1]):
            raise ValueError(f"PMDA回収原典の確認に失敗しました ({number})")
        items.append(dict(id=number, date=dt.date.fromisoformat(date.replace("/", "-")).isoformat(),
                          title=name, maker=maker, url=PMDA + path,
                          ended="回収終了" in notes))
    return items


def fetch_index(fiscal_year, category):
    url = f"{PMDA}/kaisyuu/rcidx{fiscal_year % 100:02}-{category}m.html"
    request = Request(url, headers={"User-Agent": "DrugSupplyNavi/1.0 (+https://kyokyu-navi.jp/)"})
    with urlopen(request, timeout=15) as response:
        body = response.read(MAX_BYTES + 1)
        if response.geturl() != url or len(body) > MAX_BYTES:
            raise ValueError("PMDA回収一覧のURLまたはサイズが不正です")
        return parse_index(body.decode(response.headers.get_content_charset() or "euc_jp"), category)


def collect(previous, today, fetch=fetch_index):
    cutoff = today - dt.timedelta(days=29)
    fiscal_years = {day.year - (day.month < 4) for day in (today, cutoff)}

    def collect_class(category):
        key = CLASSES[category]
        try:
            items = [item for year in sorted(fiscal_years) for item in fetch(year, category)]
        except (OSError, ValueError, LookupError) as error:
            print(f"PMDA クラス{key}の取得に失敗しました ({type(error).__name__})")
            return {**previous.get(key, {"last_success_date": None, "items": []}), "status": "failed"}
        return dict(status="ok", last_success_date=today.isoformat(), items=[
            item for item in items if cutoff.isoformat() <= item["date"] <= today.isoformat()
        ])

    with ThreadPoolExecutor(max_workers=len(CLASSES)) as pool:
        return dict(zip(CLASSES.values(), pool.map(collect_class, CLASSES)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, nargs="?", default=Path("pmda_recalls.json"))
    output = parser.parse_args().output
    old = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"classes": {}}
    classes = collect(old["classes"], dt.datetime.now(JST).date())
    pending = output.with_suffix(".next.json")
    pending.write_text(json.dumps({"classes": classes}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(output)
