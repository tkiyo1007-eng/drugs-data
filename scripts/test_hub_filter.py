"""状態別一覧の検索範囲・非JS表示・日付と実際の入力操作を検証する。"""
import json
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from generate_item_pages import (
    FILTERABLE_HUB_SLUGS, HUB_TEMPLATE_LASTMOD, ITEM_HUB_SLUGS,
    MHLW_PRICE_LIST_URL, OFFICIAL_SUPPLY_URL, hub_html, sitemap_xml,
)


class HubParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.links = []
        self.anchors = []
        self.controls = {}
        self.groups = {}
        self.current_group = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section" and "supplemental-group" in attrs.get("class", "").split():
            self.current_group = attrs["id"]
            self.groups[self.current_group] = []
        if tag == "li":
            self.rows.append(attrs)
            if self.current_group:
                self.groups[self.current_group].append(attrs)
        if tag == "a":
            self.links.append(attrs.get("href", ""))
            self.anchors.append(attrs)
        if attrs.get("id", "").startswith("hubFilter"):
            self.controls[attrs["id"]] = attrs

    def handle_endtag(self, tag):
        if tag == "section":
            self.current_group = None


class HubFilterTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {
                "key": "1111111F1111", "name": "ユベラ錠",
                "display_name": "ユベラ錠", "maker": "エーザイ",
                "manufacturer": "製造会社", "ingredient": "トコフェロール",
                "spec": "１錠", "status": "limited", "updated": "2026-09-14",
                "hubs": ["limited"],
            },
            {
                "key": "2222222F2222", "name": "テストＯＤ錠１０ｍｇ",
                "display_name": "テストＯＤ錠１０ｍｇ", "maker": "対象製薬",
                "manufacturer": "対象工場", "ingredient": "アセトアミノフェン",
                "spec": "１０ｍｇ", "status": "limited", "updated": "2026-10-08",
                "hubs": ["limited"],
            },
            {
                "key": "3333333F3333", "name": "別の錠剤",
                "maker": "対象製薬", "ingredient": "別の成分", "spec": "５ｍｇ",
                "status": "stopped", "updated": "2026-10-07",
                "hubs": ["stopped"],
            },
        ]

    def supplemental_entries(self):
        return [
            dict(self.entries[0], status="ended", delist=True, hubs=["supplemental"]),
            dict(self.entries[1], status="ok", delist=True, hubs=["supplemental"]),
            dict(self.entries[2], name="薬価削除予定という名前のテスト", delist=False,
                 hubs=["supplemental"]),
        ]

    def test_price_filter_uses_collected_flag_across_groups_without_duplicate_items(self):
        entries = self.supplemental_entries()
        output = hub_html("supplemental", entries, "2026-10-10")
        parsed = HubParser()
        parsed.feed(output)
        self.assertEqual(["1", "1", "0"], [
            row["data-price-info"] for group in (
                "sales-notices", "delisting", "maker-notices")
            for row in parsed.groups[group]])
        self.assertEqual(3, len(parsed.rows))
        for entry in entries:
            self.assertEqual(1, parsed.links.count(entry["key"] + ".html"))
        self.assertTrue(all("hidden" not in row for row in parsed.rows))
        self.assertIn("全体で2品目に収録", output)
        self.assertIn("そのうち1品目は「販売中止", output)
        self.assertIn("薬価削除済み、製造・販売の終了や終了日を示すものではありません", output)
        checkbox = parsed.controls["hubFilterPriceOnly"]
        self.assertEqual("checkbox", checkbox["type"])
        self.assertEqual("hubFilterPriceHint", checkbox["aria-describedby"])
        self.assertEqual("hubItems", checkbox["aria-controls"])
        self.assertNotIn("checked", checkbox)
        self.assertRegex(output, r'<label class="price-filter">\s*<input id="hubFilterPriceOnly"[^>]*>\s*<span>厚労省の薬価削除予定・経過措置期限が収録された品目だけ表示</span>\s*</label>')
        self.assertIn("厚労省データの薬価削除予定・経過措置期限は、全体で2品目", output)
        self.assertIn("メーカー案内だけの経過措置情報は、原文も別に確認してください", output)
        self.assertNotIn('for="hubFilterPriceOnly"', output)
        self.assertLess(output.index('class="price-note"'), output.index('id="hubFilter"'))
        for slug in ITEM_HUB_SLUGS - {"supplemental"}:
            other = hub_html(slug, [dict(entry, hubs=[slug]) for entry in entries], "2026-10-10")
            other_parsed = HubParser()
            other_parsed.feed(other)
            self.assertNotIn("hubFilterPriceOnly", other_parsed.controls)
            self.assertTrue(all("data-price-info" not in row for row in other_parsed.rows))
            self.assertNotIn('class="price-note"', other)

    def test_search_is_limited_to_three_hubs_and_keeps_static_items(self):
        for slug in ITEM_HUB_SLUGS:
            with self.subTest(slug=slug):
                output = hub_html(slug, self.entries, "2026-10-10")
                parsed = HubParser()
                parsed.feed(output)
                expected = [entry for entry in self.entries if slug in entry["hubs"]]
                self.assertEqual(len(parsed.rows), len(expected))
                for row in parsed.rows:
                    self.assertNotIn("hidden", row)
                for entry in expected:
                    self.assertEqual(parsed.links.count(entry["key"] + ".html"), 1)
                    self.assertIn(entry["name"], output)
                    self.assertIn("品目行更新 " + entry["updated"], output)
                self.assertIn('href="https://kyokyu-navi.jp/items/' + slug + '.html"', output)
                self.assertIn("https://iyakuhin-kyokyu.mhlw.go.jp/public/supply-status-list", output)
                if slug in {"limited", "stopped", "supplemental"}:
                    self.assertIn("hidden", parsed.controls["hubFilter"])
                    self.assertIn("この一覧内に該当する品目なし", output)
                    self.assertIn("すべての医薬品の検索結果ではありません", output)
                else:
                    self.assertEqual({}, parsed.controls)
                    self.assertNotIn("data-search=", output)

    def test_restricted_hubs_keep_raw_public_fields_without_inferring_dates(self):
        self.entries[0].update({
            "supply_raw": "③限定出荷（他社品の影響）", "reason": "１．需要増 <原文>",
            "release": "ア．あり", "hubs": ["limited", "recent-restrictions"],
        })
        self.entries[2].update({
            "supply_raw": "⑤供給停止", "reason": "７．その他", "release": "ウ．未定",
        })
        for slug, values in (
            ("limited", ("③限定出荷（他社品の影響）", "１．需要増 &lt;原文&gt;", "ア．あり")),
            ("stopped", ("⑤供給停止", "７．その他", "ウ．未定")),
        ):
            output = hub_html(slug, self.entries, "2026-10-10")
            for value in values:
                self.assertIn("<dd>" + value + "</dd>", output)
            self.assertIn("「あり」だけでは具体的な解除日を示しません", output)
            self.assertIn('href="../guides/how-to-check-drug-supply.html#resumption"', output)
            self.assertNotIn("１．需要増 <原文>", output)
            # Raw fields are evidence; the existing medicine-name search contract stays intact.
            parsed = HubParser()
            parsed.feed(output)
            self.assertTrue(all("需要増" not in row.get("data-search", "") for row in parsed.rows))
        limited = hub_html("limited", self.entries, "2026-10-10")
        self.assertEqual(3, limited.count("公表欄の記載なし（詳細・原典で確認）"))
        self.assertNotIn('class="hub-evidence"', hub_html("recent-restrictions", self.entries, "2026-10-10"))
        self.assertNotIn('class="hub-evidence"', hub_html("supplemental", self.entries, "2026-10-10"))

    def test_search_index_includes_ingredient_and_both_makers_and_escapes_text(self):
        self.entries[0]["ingredient"] = '成分" & <script>alert(1)</script>'
        output = hub_html("limited", self.entries, "2026-10-10")
        parsed = HubParser()
        parsed.feed(output)
        text = next(row["data-search"] for row in parsed.rows
                    if row["data-search"].startswith("1111111F1111 "))
        for value in (
            "1111111F1111", "ユベラ錠", "エーザイ", "製造会社",
            '成分" & <script>alert(1)</script>', "１錠",
        ):
            self.assertIn(value, text)
        self.assertNotIn("<script>alert(1)</script>", output)

    def test_template_revision_covers_all_hubs_without_expanding_filters_or_item_dates(self):
        sitemap = sitemap_xml(
            {"1111111F1111": "2026-09-14"}, "2026-10-10", ITEM_HUB_SLUGS)
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        dates = {
            node.find("s:loc", ns).text.rsplit("/", 1)[-1]:
                node.find("s:lastmod", ns).text
            for node in ET.fromstring(sitemap).findall("s:url", ns)
        }
        for slug in ITEM_HUB_SLUGS:
            self.assertEqual(
                HUB_TEMPLATE_LASTMOD,
                dates[slug + ".html"],
            )
            output = hub_html(slug, self.entries, "2026-10-10")
            self.assertIn('"dateModified":"' + HUB_TEMPLATE_LASTMOD + '"', output)
            self.assertIn("サイト全体の公開データ基準日（サイト取込日）：", output)
            self.assertIn('class="dataset-date" aria-live="polite">2026-10-10</span>', output)
            self.assertIn('class="mhlw-excel-date" aria-live="polite">確認できません</span>', output)
            self.assertIn("HTML生成時の確認情報です", output)
            self.assertEqual(slug in FILTERABLE_HUB_SLUGS, 'id="hubFilter"' in output)
        self.assertEqual("2026-09-14", dates["1111111F1111.html"])
        self.assertEqual("2026-10-10", dates["index.html"])
        later = sitemap_xml({}, "2026-10-15", ["limited"])
        self.assertIn("<lastmod>2026-10-15</lastmod>", later)

    def test_official_sources_are_reachable_before_items_and_keep_distinct_roles(self):
        for slug in ITEM_HUB_SLUGS:
            with self.subTest(slug=slug):
                entry = dict(self.entries[0], hubs=[slug], status={
                    "resumed": "ok", "supplemental": "ended", "stopped": "stopped",
                }.get(slug, "limited"))
                output = hub_html(slug, [entry], "2026-10-10")
                navigation = re.search(
                    r'<nav class="entry-nav" aria-label="医薬品の探し方と確認方法">(.*?)</nav>',
                    output, re.S,
                ).group(1)
                parsed = HubParser()
                parsed.feed(navigation)
                supply = [a for a in parsed.anchors if a.get("href") == OFFICIAL_SUPPLY_URL]
                price = [a for a in parsed.anchors if a.get("href") == MHLW_PRICE_LIST_URL]
                self.assertEqual(1, len(supply))
                self.assertEqual(1 if slug == "supplemental" else 0, len(price))
                for source in supply + price:
                    self.assertEqual("_blank", source.get("target"))
                    self.assertIn("noopener", source.get("rel", "").split())
                    self.assertEqual("official-source-open", source.get("data-dsn-event"))
                    self.assertNotIn("onclick", source)
                self.assertIn("厚労省の公式システムで供給区分を確認", navigation)
                self.assertLess(output.index(navigation), re.search(r'<li(?:\s|>)', output).start())
                if slug == "supplemental":
                    self.assertIn("厚労省の薬価基準・経過措置資料", navigation)
                else:
                    self.assertNotIn(MHLW_PRICE_LIST_URL, output)

    def test_hub_identity_preserves_spec_and_formal_yj_and_omits_unknown_parts(self):
        fixtures = (
            ("1111111F1111", "１１ｍｇ１錠", "1111111F1111",
             "規格：１１ｍｇ１錠｜YJコード：1111111F1111"),
            ("X00001", "１０Ｌ", "X00001", "規格：１０Ｌ"),
            ("x123456abcdef", "", "", ""),
            ("1111111F1111", "", "", ""),
            ("x123456abcdef", "", "2222222F2222", "YJコード：2222222F2222"),
            ("1111111F1111", '<img src=x onerror="alert(1)"> & 規格', "1111111F1111",
             '規格：&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; 規格｜YJコード：1111111F1111'),
        )
        for slug in ITEM_HUB_SLUGS:
            for key, spec, yj_raw, expected in fixtures:
                with self.subTest(slug=slug, key=key, spec=spec):
                    entry = dict(self.entries[0], key=key, spec=spec, yj_raw=yj_raw, hubs=[slug],
                                 status={"resumed": "ok", "supplemental": "ended",
                                         "stopped": "stopped"}.get(slug, "limited"))
                    output = hub_html(slug, [entry], "2026-10-10")
                    identity = re.findall(r'<span class="hub-identity">(.*?)</span>', output)
                    self.assertEqual([expected] if expected else [], identity)
                    self.assertNotIn('<img src=x', output)
                    self.assertNotIn("YJコード：X00001", output)
                    self.assertNotIn("YJコード：x123456abcdef", output)
                    self.assertNotIn("規格：なし", output)
                    self.assertIn(f'href="{key}.html"', output)
                    self.assertIn("品目行更新 " + entry["updated"], output)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise input events")
    def test_real_script_normalizes_and_filters_and_recovers_from_failure(self):
        output = hub_html("limited", self.entries, "2026-10-10")
        parsed = HubParser()
        parsed.feed(output)
        script = next(
            script for script in re.findall(r"<script>(.*?)</script>", output, re.S)
            if 'getElementById("hubFilter")' in script
        )
        payload = {"script": script, "rows": parsed.rows}
        runner = r'''
const assert = require("node:assert/strict");
const vm = require("node:vm");
const payload = JSON.parse(process.argv[1]);
function setup(before = "") {
  const rows = payload.rows.map(attrs => ({
    hidden: false, textContent: attrs["data-search"],
    getAttribute: name => attrs[name] ?? null
  }));
  const node = (extra = {}) => Object.assign({
    hidden: true, handlers: {}, addEventListener(event, fn) { this.handlers[event] = fn; }
  }, extra);
  const nodes = {
    hubFilter: node(), hubItems: node({querySelectorAll: selector => selector === "li" ? rows : []}),
    hubFilterInput: node({value: "", focus() { this.focused = true; }}),
    hubFilterClear: node({disabled: true}),
    hubFilterCount: node({textContent: ""}), hubFilterEmpty: node()
  };
  const context = vm.createContext({document: {getElementById: id => nodes[id]}});
  if (before) vm.runInContext(before, context);
  vm.runInContext(payload.script, context);
  return {rows, nodes, context};
}
const live = setup();
const input = live.nodes.hubFilterInput;
const clear = live.nodes.hubFilterClear;
const visible = () => live.rows.filter(row => !row.hidden)
  .map(row => row.textContent.split(" ")[0]).sort();
const search = text => { input.value = text; input.handlers.input(); };
assert.equal(live.nodes.hubFilter.hidden, false);
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222"]);
assert.equal(live.nodes.hubFilterCount.textContent, "2 / 2品目を表示");
search("ゆべら　えーざい");
assert.deepEqual(visible(), ["1111111F1111"]);
assert.equal(live.nodes.hubFilterCount.textContent, "1 / 2品目を表示");
search("ｱｾﾄｱﾐﾉﾌｪﾝ １０ｍｇ");
assert.deepEqual(visible(), ["2222222F2222"]);
search("１１１１１１１ｆ１１１１");
assert.deepEqual(visible(), ["1111111F1111"]);
search("製造会社");
assert.deepEqual(visible(), ["1111111F1111"]);
search("ユベラ 対象製薬");
assert.deepEqual(visible(), []);
assert.equal(live.nodes.hubFilterEmpty.hidden, false);
assert.equal(live.nodes.hubFilterCount.textContent, "0 / 2品目を表示");
clear.handlers.click();
assert.equal(input.value, "");
assert.equal(input.focused, true);
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222"]);
assert.equal(live.nodes.hubFilterEmpty.hidden, true);
assert.equal(clear.disabled, true);
search("　 ");
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222"]);
search("ユベラ");
vm.runInContext("String.prototype.normalize = undefined", live.context);
input.handlers.input();
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222"]);
assert.equal(live.nodes.hubFilter.hidden, true);
const unsupported = setup("String.prototype.normalize = undefined");
assert.equal(unsupported.nodes.hubFilter.hidden, true);
assert.ok(unsupported.rows.every(row => !row.hidden));
'''
        result = subprocess.run(
            [shutil.which("node"), "-e", runner, json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise input events")
    def test_real_script_price_condition_and_text_clear_empty_and_fail_open(self):
        output = hub_html("supplemental", self.supplemental_entries(), "2026-10-10")
        parsed = HubParser()
        parsed.feed(output)
        script = next(
            script for script in re.findall(r"<script>(.*?)</script>", output, re.S)
            if 'getElementById("hubFilter")' in script
        )
        payload = {"script": script, "rows": parsed.rows, "groups": parsed.groups}
        runner = r'''
const assert = require("node:assert/strict");
const vm = require("node:vm");
const payload = JSON.parse(process.argv[1]);
function setup(before = "", omitFlag = false) {
  const rows = payload.rows.map(attrs => ({
    hidden: false, textContent: attrs["data-search"],
    key: attrs["data-search"].split(" ")[0],
    getAttribute: name => omitFlag && name === "data-price-info" ? null : attrs[name] ?? null
  }));
  const node = (extra = {}) => Object.assign({
    hidden: true, handlers: {}, addEventListener(event, fn) { this.handlers[event] = fn; }
  }, extra);
  const groups = Object.entries(payload.groups).map(([id, attrs]) => node({
    id, hidden: false, querySelectorAll: () => rows.filter(row =>
      attrs.some(attr => attr["data-search"].split(" ")[0] === row.key))
  }));
  const nodes = {
    hubFilter: node(), hubItems: node({querySelectorAll: selector => selector === "li" ? rows : groups}),
    hubFilterInput: node({value: "", focus() { this.focused = true; }}),
    hubFilterPriceOnly: node({checked: false}), hubFilterClear: node({disabled: true}),
    hubFilterCount: node({textContent: ""}), hubFilterEmpty: node()
  };
  const context = vm.createContext({document: {getElementById: id => nodes[id] ?? null}});
  if (before) vm.runInContext(before, context);
  vm.runInContext(payload.script, context);
  return {rows, groups, nodes, context};
}
const live = setup();
const input = live.nodes.hubFilterInput;
const price = live.nodes.hubFilterPriceOnly;
const clear = live.nodes.hubFilterClear;
const visible = () => live.rows.filter(row => !row.hidden).map(row => row.key).sort();
const search = text => { input.value = text; input.handlers.input(); };
const toggle = value => { price.checked = value; price.handlers.change(); };
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222", "3333333F3333"]);
toggle(true);
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222"]);
assert.equal(live.nodes.hubFilterCount.textContent, "2 / 3品目を表示");
assert.deepEqual(live.groups.map(group => [group.id, group.hidden]), [
  ["sales-notices", false], ["delisting", false], ["maker-notices", true]
]);
assert.equal(clear.disabled, false);
search("テスト 対象製薬");
assert.deepEqual(visible(), ["2222222F2222"]);
search("薬価削除予定という名前");
assert.deepEqual(visible(), []); // The words alone never make delist=false qualify.
assert.equal(live.nodes.hubFilterEmpty.hidden, false);
assert.equal(live.nodes.hubFilterCount.textContent, "0 / 3品目を表示");
assert.ok(live.groups.every(group => group.hidden));
toggle(false);
assert.deepEqual(visible(), ["3333333F3333"]);
toggle(true);
clear.handlers.click();
assert.equal(input.value, "");
assert.equal(price.checked, false);
assert.equal(input.focused, true);
assert.equal(clear.disabled, true);
assert.equal(live.nodes.hubFilterEmpty.hidden, true);
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222", "3333333F3333"]);
assert.ok(live.groups.every(group => !group.hidden));
toggle(true);
vm.runInContext("String.prototype.normalize = undefined", live.context);
price.handlers.change();
assert.deepEqual(visible(), ["1111111F1111", "2222222F2222", "3333333F3333"]);
assert.ok(live.groups.every(group => !group.hidden));
assert.equal(live.nodes.hubFilter.hidden, true);
assert.equal(live.nodes.hubFilterEmpty.hidden, true);
assert.equal(price.checked, false);
const unsupported = setup("String.prototype.normalize = undefined");
assert.equal(unsupported.nodes.hubFilter.hidden, true);
assert.ok(unsupported.rows.every(row => !row.hidden));
assert.ok(unsupported.groups.every(group => !group.hidden));
const missingFlag = setup("", true);
missingFlag.nodes.hubFilterPriceOnly.checked = true;
missingFlag.nodes.hubFilterPriceOnly.handlers.change();
assert.ok(missingFlag.rows.every(row => row.hidden));
assert.equal(missingFlag.nodes.hubFilterCount.textContent, "0 / 3品目を表示");
'''
        result = subprocess.run(
            [shutil.which("node"), "-e", runner, json.dumps(payload, ensure_ascii=False)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
