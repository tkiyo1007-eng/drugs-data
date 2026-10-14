"""厚労省の供給一覧リンクと公表基準日を、日次取得・監視で共通に判定する。"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit


MHLW_SUPPLY_PAGE = "https://www.mhlw.go.jp/stf/seisakunitsuite/bunya/kenkou_iryou/iryou/kouhatu-iyaku/04_00003.html"
WORKBOOK_PATH = re.compile(r"/content/\d+/(?P<file>(?:\d{6}iyakuhinkyoukyu|\d{9})\.xlsx)")
CURRENT_LABEL = re.compile(
    r"医療用医薬品供給状況(?:報告)?\((?:令和(?P<era>元|[0-9]{1,2})年|(?P<year>[0-9]{4})年)"
    r"(?P<month>[0-9]{1,2})月(?P<day>[0-9]{1,2})日現在\)"
)


def workbook_url(href: str) -> str:
    """公式content配下の既知のExcel名だけ許可し、URL補正で不正経路を隠さない。"""
    if not isinstance(href, str) or not href or re.search(r"\s|[\\\x00-\x1f\x7f]", href):
        raise ValueError("Excelリンクに空白・制御文字または不正な区切りがあります")
    raw = urlsplit(href)
    if "%" in raw.path or any(part in {".", ".."} for part in unquote(raw.path).split("/")):
        raise ValueError("Excelリンクにエンコードまたは相対移動があります")
    parsed = urlsplit(urljoin(MHLW_SUPPLY_PAGE, href))
    try:
        valid = (parsed.scheme == "https" and parsed.hostname in {"www.mhlw.go.jp", "mhlw.go.jp"}
                 and not parsed.username and not parsed.password and parsed.port in {None, 443}
                 and not parsed.query and not parsed.fragment and WORKBOOK_PATH.fullmatch(parsed.path))
    except ValueError as error:
        raise ValueError("Excelリンクのポートが不正です") from error
    if not valid:
        raise ValueError("Excelリンクが公式の既知のcontent URLではありません")
    return parsed.geturl()


class SupplyLinks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            if self.href is not None:
                raise ValueError("Excelリンクを含むa要素が入れ子です")
            hrefs = [value for key, value in attrs if key == "href"]
            if len(hrefs) > 1:
                raise ValueError("a要素のリンク先が複数あります")
            self.href = hrefs[0] if hrefs else None
            self.label = []

    def handle_data(self, data):
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self.href is not None:
            self.links.append((self.href, "".join(self.label)))
            self.href = None
            self.label = []


def supply_source_from_page(page: str, today: dt.date) -> dict[str, str]:
    """数値名はリンク本文の日付を必須にする。旧日付名との不一致・複数URLは拒否。"""
    if not isinstance(page, str) or type(today) is not dt.date:
        raise ValueError("厚労省ページまたは確認日が不正です")
    parser = SupplyLinks()
    parser.feed(page)
    if parser.href is not None and ".xlsx" in parser.href.lower():
        raise ValueError("Excelリンクが閉じられていません")
    records: dict[str, dict[str, str]] = {}
    for href, label in parser.links:
        if ".xlsx" not in href.lower():
            continue
        url = workbook_url(href)
        filename = urlsplit(url).path.rsplit("/", 1)[-1]
        compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", label))
        match = CURRENT_LABEL.fullmatch(compact)
        label_date = None
        if match:
            era = match["era"]
            year = 2018 + (1 if era == "元" else int(era)) if era else int(match["year"])
            try:
                label_date = dt.date(year, int(match["month"]), int(match["day"]))
            except ValueError as error:
                raise ValueError("供給一覧のリンク本文の日付が実在しません") from error
            if era and label_date < dt.date(2019, 5, 1):
                raise ValueError("供給一覧の令和日付が不正です")
        elif any(token in compact for token in ("年", "月", "日現在")):
            raise ValueError("供給一覧のリンク本文の日付形式を確認できません")
        stamp = re.fullmatch(r"(\d{2})(\d{2})(\d{2})iyakuhinkyoukyu\.xlsx", filename)
        file_date = None
        if stamp:
            try:
                file_date = dt.date(2000 + int(stamp[1]), int(stamp[2]), int(stamp[3]))
            except ValueError as error:
                raise ValueError("供給一覧の旧ファイル名の日付が実在しません") from error
        if label_date and file_date and label_date != file_date:
            raise ValueError("供給一覧のリンク本文と旧ファイル名の日付が一致しません")
        date = label_date or file_date
        if date is None or date > today:
            raise ValueError("供給一覧の公表基準日が不明または未来です")
        record = {"file": filename, "url": url, "excel_date": date.isoformat()}
        if url in records and records[url] != record:
            raise ValueError("同じ供給一覧URLの日付が複数あります")
        records[url] = record
    if len(records) != 1:
        raise ValueError("供給一覧Excelが一意に見つかりません")
    return next(iter(records.values()))
