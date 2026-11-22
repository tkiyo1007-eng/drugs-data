#!/usr/bin/env python3
"""Build the Web news feed from sources already verified or attributed separately."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from fetch_pmda_recalls import CLASSES, JST, PMDA
from validate_manufacturer_notices import is_official_maker_source, valid_date

SUPPLY_URL = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html"
MAKER_LABELS = {
    "discontinued": "販売・製造中止の案内",
    "package_discontinued": "包装の販売中止の案内",
    "handling_discontinued": "取扱中止の案内",
    "limited": "限定出荷の案内",
    "stopped": "供給停止の案内",
    "resumed": "出荷再開・解除の案内",
    "resumption_planned": "出荷再開予定の案内",
    "supply": "供給に関する案内",
    "recall": "自主回収の案内",
}


def read(site, file):
    return json.loads((site / file).read_text(encoding="utf-8"))


def supply_news(site):
    by_day = defaultdict(Counter)
    for row in read(site, "status_changes.json"):
        day = row["date"].replace("/", "-")
        old, new = row["from"][:1], row["to"][:1]
        if not valid_date(day) or old == new or old not in set("①②③④⑤") or new not in set("①②③④⑤"):
            continue
        by_day[day][new] += 1

    for day, counts in by_day.items():
        page = f"updates/{day}.html"
        if not (site / page).is_file():
            continue
        limited = sum(counts[key] for key in "②③④")
        parts = [f"{label}へ{count}品目" for label, count in (
            ("供給停止", counts["⑤"]), ("限定出荷", limited), ("通常出荷", counts["①"])
        ) if count]
        yield dict(date=day, kind="supply", tag="供給状況の変更", source="厚生労働省",
                   title=f"供給区分が変わった{sum(counts.values())}品目",
                   summary="、".join(parts) + "。", url=SUPPLY_URL, detail="/" + page,
                   date_label="変更検知")


def maker_news(site, explanations):
    entries = {}
    reviewed = read(site, "manufacturer_notices.json")["notices"]
    events = read(site, "maker_announcement_events.json")
    for row in [*(item for group in events.values() for item in group), *reviewed]:
        maker, url, label = row.get("maker"), row.get("url"), MAKER_LABELS.get(row.get("event_type"))
        if not maker or not url or not label or not row.get("title"):
            continue
        if not is_official_maker_source(maker, urlsplit(url)):
            continue
        note = explanations.get(url, {})
        posted = note.get("posted_at") or row.get("listed_at")
        # An automatic event's date can come from a filename. Prefer it to
        # the first-seen day only when the publisher's title says the same.
        announced = row.get("announced_at")
        prefix = re.match(r"^(\d{4})[./年-](\d{1,2})[./月-](\d{1,2})日?\s", row["title"].lstrip())
        titled_day = "-".join(part.zfill(2) for part in prefix.groups()) if prefix else None
        title_confirms_day = bool(announced and titled_day == announced)
        detected = row.get("first_seen") or entries.get(url, {}).get("date")
        day = posted or (announced if title_confirms_day else detected or announced)
        if not valid_date(day):
            continue
        # Shared announcements can cover several products. Prefer a specific
        # matching title over a broad registry heading for the same source.
        if url in entries and not (row.get("listed_at") and entries[url]["date_label"] != "掲載"):
            continue
        entries[url] = dict(date=day, kind="maker", tag=label, source=maker, title=row["title"],
                            url=url, date_label="掲載" if posted else "案内" if title_confirms_day or not detected else "確認",
                            summary=note.get("summary"))

    # An editorial URL pair can represent a single notice after a publisher moves a file.
    # Keep both if their displayed notice metadata diverges or the reviewed original is absent.
    for url, note in explanations.items():
        original = entries.get(note.get("duplicate_of"))
        duplicate = entries.get(url)
        if (original and original["summary"] and duplicate and not duplicate["summary"]
                and all(original[key] == duplicate[key] for key in ("source", "title", "date", "tag"))):
            del entries[url]
    return entries.values()


def recall_news(snapshot, explanations):
    for category, state in snapshot.items():
        if category not in CLASSES.values():
            continue
        for row in state["items"]:
            number = row["id"]
            expected_url = f"{PMDA}/rgo/MainServlet?recallno={number}"
            if not re.fullmatch(r"[123]-\d+", number) or row["url"] != expected_url:
                continue
            ended = row["ended"]
            yield dict(date=row["date"], kind="recall", tag=f"回収 クラス{category}" + ("・終了" if ended else ""),
                       source="PMDA", title=f'{row["title"]}（{row["maker"]}）',
                       summary=None if ended else explanations.get(expected_url, {}).get("summary"),
                       url=expected_url, date_label="掲載")


def build(site, today):
    explanations = read(site, "official_news_explanations.json")
    recall = read(site, "pmda_recalls.json")["classes"]
    items = [*supply_news(site), *maker_news(site, explanations), *recall_news(recall, explanations)]
    first = (today - timedelta(days=29)).isoformat()
    recent = [item for item in items if first <= item["date"] <= today.isoformat()]
    priority = {"recall": 2, "maker": 1, "supply": 0}
    recent.sort(key=lambda item: (item["date"], priority[item["kind"]], bool(item.get("summary")), item["title"]),
                reverse=True)
    recall_ok = all(recall.get(key, {}).get("status") == "ok" and
                    valid_date(recall[key].get("last_success_date")) and
                    first <= recall[key]["last_success_date"] <= today.isoformat() and
                    (today - date.fromisoformat(recall[key]["last_success_date"])).days <= 2
                    for key in CLASSES.values())
    return dict(schema_version=1, pmda_status="ok" if recall_ok else "stale", items=recent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", type=Path, default=Path("."))
    args = parser.parse_args()
    report = build(args.site, datetime.now(JST).date())
    (args.site / "official_news.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
