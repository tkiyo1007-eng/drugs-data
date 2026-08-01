import csv
import datetime
import os
import tempfile
import unittest
from unittest import mock

import fetch_maker_announcements as mod


FIELDS = ["商品名", "一般名", "製造メーカー", "販売メーカー", "供給状況", "代替候補"]


class AnnouncementMatchingTests(unittest.TestCase):
    def make_csv(self, rows):
        f = tempfile.NamedTemporaryFile("w", encoding="utf-8-sig", newline="", delete=False)
        with f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        self.addCleanup(lambda: os.path.exists(f.name) and os.unlink(f.name))
        return f.name

    def row(self, name, maker="沢井製薬", status="①通常出荷", alt=""):
        return {"商品名": name, "一般名": "テスト成分", "製造メーカー": maker,
                "販売メーカー": maker, "供給状況": status, "代替候補": alt}

    def test_normal_supply_product_is_matched_to_discontinuation(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name)])
        result = mod.match_to_csv(
            [("沢井製薬", "2026/04/01 テスト錠1mg「サワイ」販売中止のご案内", "https://example.test/a.pdf")],
            path)
        self.assertEqual(result[name]["event_type"], "discontinued")

    def test_same_name_from_different_maker_is_not_matched(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name)])
        result = mod.match_to_csv(
            [("ニプロ", "テスト錠1mg「サワイ」販売中止のご案内", "https://example.test/a.pdf")],
            path)
        self.assertNotIn(name, result)

    def test_terminal_notice_survives_when_supply_returns_to_normal(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name)])
        existing = {name: {"maker": "沢井製薬", "title": "販売中止のご案内",
                           "url": "https://example.test/end.pdf"}}
        result = mod.match_to_csv([], path, existing=existing)
        self.assertEqual(result[name]["event_type"], "discontinued")

    def test_transient_notice_is_removed_after_normal_supply(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name)])
        existing = {name: {"maker": "沢井製薬", "title": "限定出荷のご案内",
                           "url": "https://example.test/limited.pdf"}}
        self.assertNotIn(name, mod.match_to_csv([], path, existing=existing))

    def test_grouped_strengths_match_only_the_named_maker(self):
        names = [f"テモカプリル塩酸塩錠{x}ｍｇ「サワイ」" for x in "１２４"]
        rows = [self.row(n) for n in names]
        rows.append(self.row("エースコール錠１ｍｇ", maker="第一三共エスファ"))
        path = self.make_csv(rows)
        anns = [("沢井製薬", "テモカプリル塩酸塩錠1mg・2mg・4mg「サワイ」販売中止のご案内",
                 "https://example.test/temocapril.pdf")]
        result = mod.match_to_csv(anns, path)
        self.assertEqual(set(result), set(names))

    def test_event_classification_avoids_false_discontinuation(self):
        self.assertEqual(mod.classify_event("他社品販売中止に伴う限定出荷のお願い"), "limited")
        self.assertEqual(mod.classify_event("一部包装販売中止のご案内"), "package_discontinued")
        self.assertEqual(mod.classify_event("製品販売中止のご案内"), "discontinued")

    def test_sawai_deep_scan_includes_normal_supply(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name)])
        with mock.patch.object(mod, "build_sawai_prodid_map", return_value={mod.norm(name): "123"}), \
             mock.patch.object(mod, "fetch_sawai_prodid_announcement",
                               return_value=("2026/04/01 販売中止のご案内", "https://example.test/a.pdf")):
            result = mod.deepen_sawai({}, path, limit=10)
        self.assertEqual(result[name]["event_type"], "discontinued")

    def test_event_history_keeps_replaced_notice_without_duplicates(self):
        current = {"テスト錠": {"maker": "テスト製薬", "title": "販売中止のご案内",
                                "url": "https://example.test/end.pdf",
                                "event_type": "discontinued", "announced_at": "2026-04-01"}}
        first = mod.update_event_history({}, current, today="2026-04-02")
        second = mod.update_event_history(first, current, today="2026-04-03")
        self.assertEqual(len(second["テスト錠"]), 1)
        self.assertEqual(second["テスト錠"][0]["first_seen"], "2026-04-02")
        self.assertEqual(second["テスト錠"][0]["last_checked"], "2026-04-03")

        legacy = {"テスト錠": [{"maker": "テスト製薬", "title": "販売中止のご案内",
                               "url": "https://example.test/end.pdf", "first_seen": "2026-04-02"}]}
        migrated = mod.update_event_history(legacy, current, today="2026-04-03")
        self.assertEqual(migrated["テスト錠"][0]["event_type"], "discontinued")

        replacement = {"テスト錠": {"maker": "テスト製薬", "title": "販売中止（第2報）",
                                    "url": "https://example.test/end-2.pdf",
                                    "event_type": "discontinued", "announced_at": "2026-05-01"}}
        third = mod.update_event_history(second, replacement, today="2026-05-02")
        self.assertEqual(len(third["テスト錠"]), 2)
        self.assertEqual(third["テスト錠"][0]["url"], "https://example.test/end-2.pdf")


class ParserTests(unittest.TestCase):
    def test_hisamitsu_parser_extracts_recent_pdf(self):
        yy = datetime.date.today().year % 100
        html = (f'<a href="/product/whatsnew/pdf/{yy:02d}0403.pdf">'
                "インサイドパップ70mg 販売中止のご案内</a>")
        with mock.patch.object(mod, "fetch", return_value=html):
            rows = mod.parse_hisamitsu(pages=2)
        self.assertEqual(len(rows), 1)
        self.assertIn("インサイドパップ70mg", rows[0][1])
        self.assertTrue(rows[0][2].endswith(f"/{yy:02d}0403.pdf"))

    def test_nipro_parser_reads_sales_and_supply_categories(self):
        def page(category, number):
            if number > 1:
                return {"data": [], "lastPage": 1}
            return {"data": [{
                "c_NpNewsTitle__c": f"テスト錠 {category}",
                "c_NpNewsDateTimeToShowFormula__c": "2026年7月1日",
                "newsPDFUrl__c": f"/files/{category}.pdf",
            }], "lastPage": 1}
        with mock.patch.object(mod, "fetch_nipro_page", side_effect=page):
            rows = mod.parse_nipro(pages=2)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r[0] == "ニプロ" and r[2].startswith("https://med.nipro.co.jp/") for r in rows))


if __name__ == "__main__":
    unittest.main()
