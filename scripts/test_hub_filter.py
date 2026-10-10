"""状態別一覧の検索範囲・非JS表示・日付と実際の入力操作を検証する。"""
import json
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from generate_item_pages import (
    HUB_FILTER_TEMPLATE_LASTMOD, ITEM_HUB_SLUGS, hub_html, sitemap_xml,
)


class HubParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.links = []
        self.controls = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "li":
            self.rows.append(attrs)
        if tag == "a":
            self.links.append(attrs.get("href", ""))
        if attrs.get("id", "").startswith("hubFilter"):
            self.controls[attrs["id"]] = attrs


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

    def test_search_is_limited_to_two_hubs_and_keeps_static_items(self):
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
                if slug in {"limited", "stopped"}:
                    self.assertIn("hidden", parsed.controls["hubFilter"])
                    self.assertIn("この一覧内に該当する品目なし", output)
                    self.assertIn("すべての医薬品の検索結果ではありません", output)
                else:
                    self.assertEqual({}, parsed.controls)
                    self.assertNotIn("data-search=", output)

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

    def test_template_revision_advances_only_changed_hubs_not_item_dates(self):
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
                HUB_FILTER_TEMPLATE_LASTMOD.get(slug, "2026-10-10"),
                dates[slug + ".html"],
            )
            output = hub_html(slug, self.entries, "2026-10-10")
            if slug in {"limited", "stopped"}:
                self.assertIn('"dateModified":"2026-10-11"', output)
                self.assertIn("全体データ基準日 2026-10-10", output)
        self.assertEqual("2026-09-14", dates["1111111F1111.html"])
        self.assertEqual("2026-10-10", dates["index.html"])
        later = sitemap_xml({}, "2026-10-15", ["limited"])
        self.assertIn("<lastmod>2026-10-15</lastmod>", later)

    @unittest.skipUnless(shutil.which("node"), "Node.js is needed to exercise input events")
    def test_real_script_normalizes_and_filters_and_recovers_from_failure(self):
        output = hub_html("limited", self.entries, "2026-10-10")
        parsed = HubParser()
        parsed.feed(output)
        script = next(
            script for script in re.findall(r"<script>(.*?)</script>", output, re.S)
            if 'getElementById("hubFilter")' in script
        )
        payload = {"script": script, "rows": [row["data-search"] for row in parsed.rows]}
        runner = r'''
const assert = require("node:assert/strict");
const vm = require("node:vm");
const payload = JSON.parse(process.argv[1]);
function setup(before = "") {
  const rows = payload.rows.map(text => ({
    hidden: false, textContent: text, getAttribute: () => text
  }));
  const node = (extra = {}) => Object.assign({
    hidden: true, handlers: {}, addEventListener(event, fn) { this.handlers[event] = fn; }
  }, extra);
  const nodes = {
    hubFilter: node(), hubItems: node({querySelectorAll: () => rows}),
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


if __name__ == "__main__":
    unittest.main()
