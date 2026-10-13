#!/usr/bin/env python3
"""Read official bulletin metadata; never infer medicine status or post to X.

The reviewed notice registry is the only source of medical content. A bulletin is
confirmed only after its registered URL returns a PDF with the registered hash.
Index failures preserve previous records and success timestamps. The collector
uses one index attempt per maker/day and at most eight known PDFs/day.
"""
import argparse
import copy
import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9))
UA = "DrugSupplyNavi/1.0 (+https://kyokyu-navi.jp/)"
SUPPLY_WORDS = ("供給", "出荷", "販売中止", "販売終了", "製造中止", "経過措置", "回収", "在庫消尽", "流通", "受注")
PARSERS = {"pfizer_json", "sandoz_next", "html", "legacy_cache"}
STATUSES = {"ok", "partial", "failed"}
SHA = re.compile(r"^[a-f0-9]{64}$")
MAX_INDEX_BYTES = 3 * 1024 * 1024
MAX_PDF_BYTES = 8 * 1024 * 1024


class CollectionError(ValueError):
    pass


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(value).hexdigest()


def clean_text(value):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", " ", value))).strip()


def real_date(value):
    """Parse a date printed in the listing, never a URL or discovery timestamp."""
    if not isinstance(value, str):
        return None
    text = clean_text(value)
    m = re.search(r"(?<!\d)(20\d{2})[年/.-]\s*(\d{1,2})[月/.-]\s*(\d{1,2})(?:日|\b)", text)
    if m:
        try:
            return dt.date(*map(int, m.groups())).isoformat()
        except ValueError:
            return None
    try:
        return dt.datetime.strptime(text, "%B %d, %Y").date().isoformat()
    except ValueError:
        pass
    m = re.fullmatch(r"\s*(20\d{2})[年/.-]\s*(\d{1,2})月?\s*", text)
    if m and 1 <= int(m[2]) <= 12:
        return f"{int(m[1]):04d}-{int(m[2]):02d}"
    return None


def normalized_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise CollectionError("URL型・長さが不正")
    p = urllib.parse.urlsplit(html.unescape(value))
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise CollectionError("許可されたHTTPS公開URLではない")
    path = p.path
    for _ in range(10):
        decoded = urllib.parse.unquote(path)
        if decoded == path:
            break
        path = decoded
    if "\\" in path or any(x in (".", "..") for x in path.split("/")) or any(ord(x) < 32 for x in value + path):
        raise CollectionError("URL pathが不正")
    return urllib.parse.urlunsplit(("https", p.hostname.lower(), p.path or "/", p.query, ""))


def in_scope(url, scopes):
    try:
        p = urllib.parse.urlsplit(normalized_url(url))
        path = urllib.parse.unquote(p.path)
        return any(p.hostname == s["host"] and
                   (path == urllib.parse.unquote(s["path"]) if s["exact"] else
                    path.startswith(urllib.parse.unquote(s["path"]))) for s in scopes)
    except (ValueError, KeyError, TypeError):
        return False


def validate_config(data):
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1 or not isinstance(data.get("sources"), list):
        raise CollectionError("収集元JSONの型が不正")
    limit = data.get("max_document_checks_per_day", 8)
    if type(limit) is not int or not 0 <= limit <= 8:
        raise CollectionError("PDF日次上限は0～8")
    ids, makers = set(), set()
    for s in data["sources"]:
        if not isinstance(s, dict) or any(not isinstance(s.get(k), str) or not s[k] for k in ("id", "maker", "index_url", "parser", "link_base")):
            raise CollectionError("収集元の必須文字列が不正")
        if s["id"] in ids or s["maker"] in makers or s["parser"] not in PARSERS:
            raise CollectionError("収集元の重複または未知のparser")
        ids.add(s["id"]); makers.add(s["maker"])
        for kind in ("index_scope", "document_scope"):
            if not isinstance(s.get(kind), list) or not s[kind]:
                raise CollectionError("URL scopeがない")
            for scope in s[kind]:
                if not isinstance(scope, dict) or not isinstance(scope.get("host"), str) or not isinstance(scope.get("path"), str) or type(scope.get("exact")) is not bool:
                    raise CollectionError("URL scope型が不正")
                if not scope["path"].startswith("/") or not re.fullmatch(r"[a-z0-9.-]+", scope["host"]):
                    raise CollectionError("URL scopeが不正")
        if not in_scope(s["index_url"], s["index_scope"]):
            raise CollectionError("収集URLが登録scope外")
        if "robots_4xx_unavailable" in s and type(s["robots_4xx_unavailable"]) is not bool:
            raise CollectionError("robots設定型が不正")
    return data


def validate_registry(registry, sources):
    if not isinstance(registry, dict) or type(registry.get("schema_version")) is not int or registry.get("schema_version") != 1 or not isinstance(registry.get("notices"), list):
        raise CollectionError("検証済み案内JSONの型が不正")
    by_maker = {s["maker"]: s for s in sources}
    seen = set()
    for n in registry["notices"]:
        if not isinstance(n, dict) or any(not isinstance(n.get(k), str) or not n[k] for k in ("id", "maker", "title", "url", "sha256")):
            raise CollectionError("案内の必須文字列が不正")
        if n["id"] in seen or not SHA.fullmatch(n["sha256"]):
            raise CollectionError("案内ID・hashが不正")
        seen.add(n["id"])
        if n["maker"] not in by_maker or not in_scope(n["url"], by_maker[n["maker"]]["document_scope"]):
            raise CollectionError("案内URLが登録メーカーscope外")
        if n.get("listed_at") is not None and real_date(n["listed_at"]) != n["listed_at"]:
            raise CollectionError("掲載日が不正")
    return registry


def validate_previous(previous):
    if not previous:
        return {"schema_version": 1, "sources": [], "items": [], "document_checks": []}
    if not isinstance(previous, dict) or type(previous.get("schema_version")) is not int or previous.get("schema_version") != 1 or not isinstance(previous.get("sources"), list) or not isinstance(previous.get("items"), list):
        raise CollectionError("前回速報JSONの型が不正。上書きしない")
    for s in previous["sources"]:
        if not isinstance(s, dict) or not isinstance(s.get("id"), str) or s.get("status") not in STATUSES:
            raise CollectionError("前回収集元の型が不正")
    for i in previous["items"]:
        if not isinstance(i, dict) or any(not isinstance(i.get(k), str) for k in ("id", "maker", "title", "url", "first_seen", "last_seen")):
            raise CollectionError("前回候補の型が不正")
        if i.get("review_status") not in {"confirmed", "needs_review"} or not isinstance(i.get("notice_ids"), list):
            raise CollectionError("前回候補の検証状態が不正")
        if i.get("posted_at") is not None and real_date(i["posted_at"]) != i["posted_at"]:
            raise CollectionError("前回候補の掲載日が不正")
        if not i["id"] or not i["title"] or iso_day(i["first_seen"]) is None or iso_day(i["last_seen"]) is None:
            raise CollectionError("前回候補ID/見出し/観測日時が不正")
    if not isinstance(previous.get("document_checks", []), list):
        raise CollectionError("前回PDF検査記録が不正")
    for c in previous.get("document_checks", []):
        if not isinstance(c, dict) or any(not isinstance(c.get(k), str) or not c[k] for k in ("url", "maker", "checked_at")) or c.get("status") not in {"ok", "failed"} or iso_day(c["checked_at"]) is None:
            raise CollectionError("前回PDF検査行の型が不正")
        if c["status"] == "ok" and (not isinstance(c.get("sha256"), str) or not SHA.fullmatch(c["sha256"])):
            raise CollectionError("前回PDF検査hashが不正")
    return previous


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_http(url, limit):
    """No cookies, credentials, redirects, retries, or challenge workarounds."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/html,application/pdf,text/plain"})
    opener = urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(req, timeout=15)
    except urllib.error.HTTPError as e:
        return e.code, b"", e.headers.get("Location")
    with response:
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise CollectionError("取得サイズ上限超過")
        return response.status, raw, None


def robots_allowed(text, url):
    """RFC-style longest match, including the wildcard PDF allow rule."""
    groups, agents, rules = [], [], []
    for line in text.splitlines() + ["User-agent: __end__"]:
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (x.strip() for x in line.split(":", 1)); key = key.lower()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules)); agents, rules = [], []
            agents.append(value.lower())
        elif key in ("allow", "disallow") and agents and value:
            rules.append((key, value))
    specific = [(a, r) for a, r in groups if any(x != "*" and x in UA.lower() for x in a)]
    chosen = specific or [(a, r) for a, r in groups if "*" in a]
    p = urllib.parse.urlsplit(url); path = p.path + ("?" + p.query if p.query else "")
    matches = []
    for _, rules in chosen:
        for kind, pattern in rules:
            terminal = pattern.endswith("$"); raw_pattern = pattern[:-1] if terminal else pattern
            expression = "^" + re.escape(raw_pattern).replace(r"\*", ".*") + ("$" if terminal else "")
            if re.search(expression, path):
                matches.append((len(raw_pattern.replace("*", "")), kind == "allow"))
    return not matches or max(matches)[1]


class Reader:
    def __init__(self, transport=fetch_http):
        self.transport = transport
        self.robots = {}

    def get(self, url, source, document=False):
        url = normalized_url(url)
        scopes = source["document_scope" if document else "index_scope"]
        if not in_scope(url, scopes):
            raise CollectionError("登録scope外のURL。取得しない")
        p = urllib.parse.urlsplit(url); origin = f"https://{p.hostname}"
        if origin not in self.robots:
            status, raw, location = self.transport(origin + "/robots.txt", 65536)
            if status in (404, 410) or (400 <= status < 500 and status != 429 and source.get("robots_4xx_unavailable")):
                self.robots[origin] = ("unavailable", "")
            elif status == 200 and not raw.lstrip().startswith(b"<"):
                self.robots[origin] = ("ok", raw.decode("utf-8", errors="replace"))
            else:
                raise CollectionError(f"robots取得失敗 HTTP {status}。許可未確認")
        robots_status, text = self.robots[origin]
        if text and not robots_allowed(text, url):
            raise CollectionError("robots.txtが対象URLを拒否。取得しない")
        status, raw, location = self.transport(url, MAX_PDF_BYTES if document else MAX_INDEX_BYTES)
        if 300 <= status < 400:
            raise CollectionError("別URL・職種確認・ログインへの移動。自動通過しない")
        if status != 200:
            raise CollectionError(f"取得失敗 HTTP {status}")
        if not raw:
            raise CollectionError("空の応答。該当なしとして扱わない")
        if document and not raw.lstrip().startswith(b"%PDF-"):
            raise CollectionError("原典がPDFではない。hashを確認済みにしない")
        return raw, robots_status


class Blocks(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.finished = [], []
        self.link = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"tr", "li", "p"}:
            self.stack.append({"tag": tag, "text": [], "links": []})
        if tag == "a" and attrs.get("href"):
            self.link = {"href": attrs["href"], "text": []}
            for b in self.stack:
                b["links"].append(self.link)

    def handle_data(self, value):
        for b in self.stack:
            b["text"].append(value)
        if self.link is not None:
            self.link["text"].append(value)

    def handle_endtag(self, tag):
        if tag == "a":
            self.link = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                self.finished.extend(self.stack[index:]); del self.stack[index:]
                break


def parse_html(text, source):
    parser = Blocks(); parser.feed(text)
    found = {}
    for block in parser.finished:
        whole = clean_text(" ".join(block["text"]))
        date = real_date(whole)
        for link in block["links"]:
            title = clean_text(" ".join(link["text"]))
            if title in {"医療関係者様向け", "特約店様向け"}:
                title = re.split(r"（?医療関係者様向け", whole)[0].strip()
                title = re.sub(r"^20\d{2}/\d{1,2}/\d{1,2}\s*", "", title)
            if not title or not any(w in title for w in SUPPLY_WORDS):
                continue
            url = urllib.parse.urljoin(source["link_base"], link["href"])
            if not in_scope(url, source["document_scope"]):
                continue
            url = normalized_url(url)
            row = {"title": title, "url": url, "posted_at": date}
            # Prefer the smallest dated semantic block over an enclosing article.
            score = (date is not None, -len(whole))
            if url not in found or score > found[url][0]:
                found[url] = (score, row)
    return [row for _, row in found.values()]


def parse_index(raw, source):
    text = raw.decode("utf-8", errors="replace")
    if source["parser"] == "html":
        return parse_html(text, source)
    if source["parser"] == "pfizer_json":
        data = json.loads(text)
        if not isinstance(data, dict) or data.get("success") is not True or not isinstance(data.get("data"), dict):
            raise CollectionError("公式通知APIのJSON構造が不正")
        rows = []
        for group in data["data"].values():
            if not isinstance(group, list):
                raise CollectionError("公式通知APIの年別配列が不正")
            for row in group:
                if not isinstance(row, dict) or not isinstance(row.get("title"), str) or not isinstance(row.get("path"), str):
                    raise CollectionError("公式通知行の型が不正")
                if any(w in row["title"] for w in SUPPLY_WORDS):
                    url = urllib.parse.urljoin(source["link_base"], row["path"])
                    if in_scope(url, source["document_scope"]):
                        rows.append({"title": clean_text(row["title"]), "url": normalized_url(url),
                                     "posted_at": real_date(row.get("field_announcement_date")) or real_date(row.get("date_year_month"))})
        return rows
    m = re.search(r'<script\b[^>]*\bid=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', text, re.S)
    if not m:
        raise CollectionError("公式埋込Nextデータが見つからない")
    data = json.loads(m[1])
    if not isinstance(data, dict) or not isinstance(data.get("props"), dict) or not isinstance(data["props"].get("pageProps"), dict):
        raise CollectionError("公式埋込JSON構造が不正")
    tables = []
    def walk(value):
        if isinstance(value, dict):
            for v in value.values(): walk(v)
        elif isinstance(value, list):
            for v in value: walk(v)
        elif isinstance(value, str) and "<table" in value and any(w in value for w in SUPPLY_WORDS):
            tables.append(value)
    walk(data["props"]["pageProps"])
    return parse_html("\n".join(tables), source)


def legacy_rows(source, cache_dir):
    records = []
    for filename in ("maker_announcements.json", "unmatched_maker_announcements.json"):
        path = Path(cache_dir) / filename
        if not path.exists():
            raise CollectionError("既存メーカー収集結果がない")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, (list, dict)):
            raise CollectionError("既存メーカー結果の型が不正")
        records.extend(value.values() if isinstance(value, dict) else value)
    rows = []
    for row in records:
        if isinstance(row, dict) and row.get("maker") == source["maker"] and isinstance(row.get("title"), str) and isinstance(row.get("url"), str) and in_scope(row["url"], source["document_scope"]):
            rows.append({"title": row["title"], "url": normalized_url(row["url"]), "posted_at": real_date(row.get("announced_at"))})
    health = json.loads((Path(cache_dir) / "maker_collection_health.json").read_text(encoding="utf-8"))
    if not isinstance(health, dict) or not isinstance(health.get("sources"), list):
        raise CollectionError("既存メーカー収集healthの型が不正")
    state = next((s for s in health["sources"] if isinstance(s, dict) and s.get("source") == source.get("reuse_source_id")), {})
    last_success = real_date(state.get("last_success"))
    return rows, {"legacy_checked_date": last_success or real_date(health.get("checked")),
                  "legacy_last_success": last_success,
                  "legacy_collection_checked_date": real_date(health.get("checked")),
                  "legacy_source_ok": state.get("ok") is True}


def iso_day(value):
    try:
        parsed = dt.datetime.fromisoformat(value)
        if "T" not in value or parsed.tzinfo is None:
            return None
        return parsed.astimezone(JST).date().isoformat()
    except (TypeError, ValueError):
        return None


def collect(config, registry, previous=None, *, cache_dir=".", transport=fetch_http, now=None):
    config = validate_config(config); validate_registry(registry, config["sources"])
    previous = validate_previous(previous)
    fixed_now = now is not None
    now = now or dt.datetime.now(JST); stamp = now.astimezone(JST).isoformat(); day = now.astimezone(JST).date().isoformat()
    checked_stamp = lambda: stamp if fixed_now else dt.datetime.now(JST).isoformat()
    reader = Reader(transport)
    old_sources = {s["id"]: s for s in previous["sources"]}
    maker_sources = {s["maker"]: s for s in config["sources"]}
    # Do not silently retain an item whose URL no longer belongs to its maker.
    items = {}
    for old in previous["items"]:
        source = maker_sources.get(old["maker"])
        if source is None or not in_scope(old["url"], source["document_scope"]):
            raise CollectionError("前回候補URLが登録scope外。上書きしない")
        items[(old["maker"], normalized_url(old["url"]))] = copy.deepcopy(old)
    prior_items = copy.deepcopy(items)
    sources = []
    def merge_row(source, row, origin):
        key = (source["maker"], row["url"]); old = items.get(key, {})
        fingerprint = digest({"maker": key[0], **row})
        changed = old.get("listing_fingerprint") != fingerprint
        # A failed index is not allowed to erase previously observed dates/titles.
        item = dict(old, id=old.get("id") or digest(list(key))[:24], maker=key[0], title=row["title"], url=key[1],
                    posted_at=row["posted_at"], first_seen=old.get("first_seen", stamp), last_seen=stamp,
                    source_id=source["id"], metadata_origin=origin, listing_fingerprint=fingerprint,
                    last_changed_at=stamp if changed else old.get("last_changed_at", stamp),
                    review_status="needs_review", notice_ids=[])
        items[key] = item
    for source in config["sources"]:
        old = old_sources.get(source["id"], {})
        state = dict(old, id=source["id"], maker=source["maker"], index_url=source["index_url"],
                     last_success_at=old.get("last_success_at"), status="failed")
        if iso_day(old.get("last_attempt_at")) == day and source["parser"] != "legacy_cache":
            state = dict(old, skipped="daily_index_limit")
            sources.append(state); continue
        state["checked_at"] = stamp; state["last_attempt_at"] = stamp
        try:
            if source["parser"] == "legacy_cache":
                rows, info = legacy_rows(source, cache_dir)
                state.update(info); state["status"] = "partial"; state["coverage"] = "legacy_cache_only"
                state["warning"] = "既存収集結果を再利用。各源の成功日と全体収集日を区別し、この収集器で一覧を二重取得しない"
                state["index_sha256"] = digest(rows)
            else:
                raw, robots_status = reader.get(source["index_url"], source)
                rows = parse_index(raw, source); state["index_sha256"] = digest(raw)
                state["robots_status"] = robots_status
                state["status"] = "ok" if robots_status == "ok" else "partial"
                state["coverage"] = "official_index"
                if robots_status != "ok":
                    state["warning"] = "robots.txtは4xxで取得不能。禁止規則の有無は未確認"
                else:
                    state.pop("warning", None)
                state["last_success_at"] = stamp
            rows = list({row["url"]: row for row in rows}.values())
            if not rows:
                raise CollectionError("供給案内を1件も確認できない。該当なしではなく要確認")
            state["count"] = len(rows); state["error"] = None
            for row in rows: merge_row(source, row, "legacy_cache" if source["parser"] == "legacy_cache" else "official_index")
        except (CollectionError, OSError, ValueError, KeyError) as e:
            state.update(status="failed", coverage="index_unavailable", error=str(e)[:300])
            state["last_success_at"] = old.get("last_success_at")
        sources.append(state)
    registered = {}
    for notice in registry["notices"]:
        key = (notice["maker"], normalized_url(notice["url"]))
        registered.setdefault(key, []).append(notice)
        if key not in items:
            merge_row(maker_sources[key[0]], {"title": notice["title"], "url": key[1], "posted_at": notice.get("listed_at")}, "verified_registry")
    # Reuse same-day checks across reruns; failed attempts also consume the cap.
    checks = [copy.deepcopy(c) for c in previous.get("document_checks", []) if isinstance(c, dict) and iso_day(c.get("checked_at")) == day]
    checked_urls = {c.get("url"): c for c in checks}
    limit = config.get("max_document_checks_per_day", 8)
    def check_priority(entry):
        key, notices = entry
        prior = prior_items.get(key, {})
        pending = not prior or prior.get("review_status") != "confirmed" or prior.get("sha256") not in {n["sha256"] for n in notices}
        # Pending records rotate by last attempt too, so inaccessible PDFs cannot
        # permanently consume all slots when the registry grows beyond eight.
        age = (prior.get("last_document_attempt_at") or prior.get("document_checked_at") or "") if pending else (prior.get("last_hash_success_at") or "")
        return (0 if pending else 1, age, key[1])
    for key, notices in sorted(registered.items(), key=check_priority):
        item = items[key]; check = checked_urls.get(key[1])
        if check is None and len(checks) < limit:
            check = {"url": key[1], "maker": key[0], "checked_at": stamp, "status": "failed"}
            try:
                raw, robots_status = reader.get(key[1], maker_sources[key[0]], document=True)
                check.update(status="ok", sha256=digest(raw), robots_status=robots_status)
            except (CollectionError, OSError, ValueError) as e:
                check["error"] = str(e)[:300]
            check["checked_at"] = checked_stamp()
            checks.append(check); checked_urls[key[1]] = check
        item["document_checked_at"] = check.get("checked_at") if check else None
        if check:
            item["last_document_attempt_at"] = check["checked_at"]
        item["hash_status"] = check.get("status") if check else "daily_limit"
        if check and check["status"] == "ok":
            old_hash = item.get("sha256"); item["sha256"] = check["sha256"]
            item["last_hash_success_at"] = check["checked_at"]
            if old_hash != check["sha256"]: item["last_changed_at"] = stamp
            matched = [n["id"] for n in notices if n["sha256"] == check["sha256"]]
            item["notice_ids"] = matched; item["review_status"] = "confirmed" if matched else "needs_review"
            item["review_reason"] = None if matched else "登録済み原典の現在hashが異なるため再確認が必要"
        else:
            item["review_status"] = "needs_review"; item["notice_ids"] = []
            item["review_reason"] = "原典hashの今回確認が未完了。前回内容は保持"
    for key, item in items.items():
        if key not in registered:
            item.update(review_status="needs_review", notice_ids=[], review_reason="検証済み原典registryへの登録がない")
    states = [s["status"] for s in sources]
    status = "ok" if states and all(s == "ok" for s in states) else "failed" if states and all(s == "failed" for s in states) else "partial"
    if status == "ok" and any(items[key]["review_status"] != "confirmed" for key in registered):
        status = "partial"
    output = {"schema_version": 1, "status": status, "checked_at": stamp,
              "last_success_at": stamp if status == "ok" else previous.get("last_success_at"),
              "sources": sources, "items": sorted(items.values(), key=lambda i: (i.get("posted_at") or "", i["maker"], i["url"]), reverse=True),
              "document_checks": checks, "drafts": []}
    output["drafts"] = make_drafts(output, previous, now=now)
    errors = validate_document(output, config)
    if errors:
        raise CollectionError("生成JSON検査: " + "; ".join(errors))
    return output


def make_drafts(current, previous, *, now):
    old = {i["id"]: i for i in previous.get("items", [])}
    fresh = [i for i in current["items"] if i["review_status"] == "confirmed" and i.get("hash_status") == "ok" and
             (i["id"] not in old or old[i["id"]].get("sha256") != i.get("sha256") or old[i["id"]].get("notice_ids") != i["notice_ids"])]
    if not fresh:
        return []
    day = now.astimezone(JST).date().isoformat()
    makers = sorted({i["maker"] for i in fresh})
    text = (f"{day} メーカー原典確認情報\n" + "・".join(makers[:2]) + ("など" if len(makers) > 2 else "") +
            f"の{len(fresh)}件を確認しました。\n販売中止予定・出荷停止・再開・回収は対象包装と出典をご確認ください。\nhttps://kyokyu-navi.jp/")
    return [{"id": "manufacturer-" + day, "date": day, "status": "draft", "text": text,
             "item_ids": [i["id"] for i in fresh], "notice_ids": sorted({n for i in fresh for n in i["notice_ids"]}),
             "items": [{k: i.get(k) for k in ("id", "maker", "title", "url", "posted_at", "sha256", "notice_ids")} for i in fresh],
             "collection_status": current["status"], "contains_unreviewed": False}]


def atomic_json(path, value):
    path = Path(path); temporary = path.with_name(path.name + ".next")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_document(document, config=None):
    """Return validation errors for CI/shared-content checks; no network access."""
    errors = []
    try:
        if config is None:
            config = json.loads((Path(__file__).resolve().parent.parent / "manufacturer_feed_sources.json").read_text(encoding="utf-8"))
        validate_config(config)
        validate_previous(document)
        if not isinstance(document, dict) or document.get("status") not in STATUSES or iso_day(document.get("checked_at")) is None:
            raise CollectionError("速報status/checked_atが不正")
        if document.get("last_success_at") is not None and iso_day(document["last_success_at"]) is None:
            raise CollectionError("速報last_success_atが不正")
        by_id = {s["id"]: s for s in config["sources"]}
        by_maker = {s["maker"]: s for s in config["sources"]}
        if {s["id"] for s in document["sources"]} != set(by_id) or len(document["sources"]) != len(by_id):
            raise CollectionError("収集元集合が登録6社と一致しない")
        for source in document["sources"]:
            definition = by_id[source["id"]]
            if source.get("maker") != definition["maker"] or source.get("index_url") != definition["index_url"]:
                raise CollectionError("収集元のメーカー/URLが登録と異なる")
            if "count" in source and (type(source["count"]) is not int or source["count"] < 0):
                raise CollectionError("収集件数が不正")
            if source.get("status") == "ok" and (not source.get("count") or iso_day(source.get("last_success_at")) is None):
                raise CollectionError("成功源の件数・成功日時が不正")
            for field in ("checked_at", "last_attempt_at", "last_success_at"):
                if source.get(field) is not None and iso_day(source[field]) is None:
                    raise CollectionError("収集元観測日時の型が不正")
        ids, urls = set(), set()
        for item in document["items"]:
            definition = by_maker.get(item["maker"])
            key = (item["maker"], item["url"])
            if definition is None or item.get("source_id") != definition["id"] or not in_scope(item["url"], definition["document_scope"]):
                raise CollectionError("候補URL/収集元が登録scope外")
            if item["id"] in ids or key in urls:
                raise CollectionError("候補ID/メーカーURLの重複")
            ids.add(item["id"]); urls.add(key)
            if any(k in item for k in ("reason", "alternatives", "supply_status", "targets")):
                raise CollectionError("速報候補に自動推定の医薬品情報を保存しない")
            if item.get("sha256") is not None and (not isinstance(item["sha256"], str) or not SHA.fullmatch(item["sha256"])):
                raise CollectionError("候補hashが不正")
            if not all(isinstance(n, str) and n for n in item["notice_ids"]):
                raise CollectionError("候補notice_idsが不正")
            if item["review_status"] == "confirmed" and (not item["notice_ids"] or not item.get("sha256") or item.get("hash_status") != "ok" or iso_day(item.get("document_checked_at")) is None):
                raise CollectionError("確認済み候補の原典hash検査がない")
        checks = document.get("document_checks", [])
        if len(checks) > config.get("max_document_checks_per_day", 8):
            raise CollectionError("PDF検査の日次上限超過")
        for check in checks:
            definition = by_maker.get(check.get("maker"))
            if definition is None or not in_scope(check.get("url"), definition["document_scope"]) or check.get("status") not in {"ok", "failed"} or iso_day(check.get("checked_at")) is None:
                raise CollectionError("PDF検査記録の型/scopeが不正")
            if check["status"] == "ok" and (not isinstance(check.get("sha256"), str) or not SHA.fullmatch(check["sha256"])):
                raise CollectionError("成功PDF検査のhashが不正")
        if not isinstance(document.get("drafts"), list):
            raise CollectionError("下書き配列が不正")
        for draft in document["drafts"]:
            if not isinstance(draft, dict) or draft.get("status") != "draft" or not isinstance(draft.get("text"), str) or draft.get("contains_unreviewed") is not False or not isinstance(draft.get("item_ids"), list):
                raise CollectionError("下書きの型が不正")
            eligible = {i["id"] for i in document["items"] if i["review_status"] == "confirmed"}
            if not draft["item_ids"] or not set(draft["item_ids"]).issubset(eligible):
                raise CollectionError("下書きに未確認候補が混入")
    except (CollectionError, ValueError, OSError, KeyError, TypeError) as e:
        errors.append(str(e))
    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", default="manufacturer_feed_sources.json")
    parser.add_argument("--registry", default="manufacturer_notices.json")
    parser.add_argument("--output", default="manufacturer_bulletins.json")
    parser.add_argument("--drafts-output", default="manufacturer_x_drafts.json")
    parser.add_argument("--draft-text", default="manufacturer_x_drafts.txt")
    parser.add_argument("--cache-dir", default=".")
    parser.add_argument("--base", default=".", help="既定入力・出力を置くデータdirectory")
    parser.add_argument("--reuse-towa-cache", action="store_true", help="東和は既存結果を再利用（既定動作、追加index取得なし）")
    parser.add_argument("--validate-only", action="store_true", help="保存JSON型・URLscopeのローカル検査のみ")
    args = parser.parse_args(argv)
    try:
        base = Path(args.base)
        resolve = lambda value: Path(value) if Path(value).is_absolute() else base / value
        config = json.loads(resolve(args.sources).read_text(encoding="utf-8"))
        registry = json.loads(resolve(args.registry).read_text(encoding="utf-8"))
        path = resolve(args.output)
        previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if args.validate_only:
            validate_config(config); validate_registry(registry, config["sources"])
            errors = validate_document(previous, config)
            if errors:
                raise CollectionError("; ".join(errors))
            print("メーカー速報JSON: 型・scope検査成功")
            return 0
        result = collect(config, registry, previous, cache_dir=resolve(args.cache_dir))
        atomic_json(path, result)
        atomic_json(resolve(args.drafts_output), {"schema_version": 1, "checked_at": result["checked_at"], "drafts": result["drafts"]})
        resolve(args.draft_text).write_text("\n\n".join(d["text"] for d in result["drafts"]) + ("\n" if result["drafts"] else ""), encoding="utf-8")
        print(f"メーカー速報: {result['status']} / {len(result['items'])}候補 / PDF検査{len(result['document_checks'])}件 / 下書き{len(result['drafts'])}件")
        return 1 if result["status"] == "failed" else 0
    except (CollectionError, OSError, ValueError) as e:
        print(f"[ERROR] メーカー速報の生成失敗（既存ファイルを保持）: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
