import csv
import json
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

    def test_announcement_date_falls_back_to_official_pdf_url(self):
        self.assertEqual(
            mod.extract_announcement_date(
                "テスト錠 販売中止のお知らせ",
                "https://example.test/fileloader.php?f=20260730_test.pdf",
            ),
            "2026-07-30",
        )

    def test_announcement_date_rejects_invalid_url_date(self):
        self.assertEqual(
            mod.extract_announcement_date(
                "テスト錠 販売中止のお知らせ",
                "https://example.test/20260231_test.pdf",
            ),
            "",
        )

    def test_announcement_date_does_not_parse_embedded_identifier(self):
        self.assertEqual(
            mod.extract_announcement_date(
                "テスト錠 販売中止のお知らせ",
                "https://example.test/documentX20260730Y.pdf",
            ),
            "",
        )

    @mock.patch.object(mod, "fetch")
    def test_kemifa_listing_date_is_kept(self, fetch_mock):
        fetch_mock.return_value = (
            '<tr><th class="date">2026年7月31日<span>発売中止</span></th>'
            '<td><a href="/product_topics/test.pdf">販売中止のご案内</a></td></tr>'
        )
        result = mod.parse_kemifa()
        self.assertEqual(result[0][1], "2026年7月31日 販売中止のご案内")
        self.assertEqual(mod.extract_announcement_date(result[0][1]), "2026-07-31")

    @mock.patch("urllib.request.urlopen")
    def test_takata_listing_date_is_kept(self, urlopen_mock):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b'<li><span class="date">2026/05/01</span>'
            b'<a href="/medical/topics/test.pdf">discontinued</a></li>'
        )
        urlopen_mock.return_value = response
        result = mod.parse_takata(1)
        self.assertEqual(result[0][1], "2026/05/01 discontinued")
        self.assertEqual(mod.extract_announcement_date(result[0][1]), "2026-05-01")

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

    def test_existing_event_type_is_reclassified_after_rule_improvement(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name)])
        existing = {name: {
            "maker": "沢井製薬", "title": "一部包装における販売中止のご案内",
            "url": "https://example.test/package.pdf", "event_type": "discontinued",
        }}
        result = mod.match_to_csv([], path, existing=existing)
        self.assertEqual(result[name]["event_type"], "package_discontinued")

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
        self.assertEqual(mod.classify_event("包装容量販売終了のご案内"), "package_discontinued")
        self.assertEqual(mod.classify_event("患者さん用パッケージ入り販売終了"), "package_discontinued")
        self.assertEqual(mod.classify_event("製品販売中止のご案内"), "discontinued")

    def test_full_discontinuation_wins_and_secondary_notice_is_resolved(self):
        name = "ナボールＳＲカプセル３７．５"
        path = self.make_csv([self.row(name, maker="久光製薬")])
        unmatched = []
        result = mod.match_to_csv([
            ("久光製薬", "2026.07.03 ナボールSRカプセル37.5 限定出荷のお知らせ",
             "https://example.test/limited.pdf"),
            ("久光製薬", "2026.07.03 ナボールSRカプセル37.5 販売中止のご案内",
             "https://example.test/end.pdf"),
        ], path, unmatched_out=unmatched)
        self.assertEqual(result[name]["event_type"], "discontinued")
        self.assertEqual(result[name]["url"], "https://example.test/end.pdf")
        self.assertEqual(unmatched, [])

    def test_older_terminal_notice_wins_over_newer_transient_notice(self):
        name = "テスト錠１ｍｇ「サワイ」"
        path = self.make_csv([self.row(name, status="②限定出荷")])
        result = mod.match_to_csv([
            ("沢井製薬", "2026/07/01 テスト錠1mg「サワイ」販売中止のご案内",
             "https://example.test/end.pdf"),
            ("沢井製薬", "2026/08/01 テスト錠1mg「サワイ」限定出荷のご案内",
             "https://example.test/limited.pdf"),
        ], path)
        self.assertEqual(result[name]["event_type"], "discontinued")

    def test_suffixless_grouped_nipro_title_matches_only_nipro_rows(self):
        names = [f"ナフトピジルＯＤ錠{x}ｍｇ「ニプロ」" for x in ("２５", "５０", "７５")]
        rows = [self.row(name, maker="ニプロ") for name in names]
        other = "ナフトピジルＯＤ錠２５ｍｇ「サワイ」"
        rows.append(self.row(other))
        path = self.make_csv(rows)
        result = mod.match_to_csv([
            ("ニプロ", "2026年7月1日 ナフトピジルOD錠25mg／50mg／75mg 販売中止品のご案内",
             "https://example.test/nipro.pdf")
        ], path)
        self.assertEqual(set(result), set(names))
        self.assertNotIn(other, result)

    def test_numbered_products_are_matched_from_grouped_title(self):
        names = [f"アマルエット配合錠{x}番「ニプロ」" for x in "１２３４"]
        path = self.make_csv([self.row(name, maker="ニプロ") for name in names])
        result = mod.match_to_csv([
            ("ニプロ", "2025年10月1日 アマルエット配合錠1番／2番／3番／4番「ニプロ」販売中止品のご案内",
             "https://example.test/amalett.pdf")
        ], path)
        self.assertEqual(set(result), set(names))

    def test_all_strength_title_without_strength_matches_explicit_maker_product(self):
        names = [f"ロスバスタチンＯＤ錠{x}ｍｇ「ＤＳＥＰ」" for x in ("２．５", "５")]
        path = self.make_csv([self.row(name, maker="第一三共エスファ") for name in names])
        result = mod.match_to_csv([
            ("第一三共エスファ", "2026.07.16 ロスバスタチンOD錠「DSEP」販売終了製品のご案内",
             "https://example.test/rosuvastatin.pdf")
        ], path)
        self.assertEqual(set(result), set(names))

    def test_terminal_family_title_matches_all_strengths_for_source_maker(self):
        names = [f"アリピプラゾールＯＤ錠{x}ｍｇ「タカタ」" for x in ("３", "６")]
        other = "アリピプラゾールＯＤ錠３ｍｇ「サワイ」"
        rows = [self.row(name, maker="高田製薬") for name in names]
        rows.append(self.row(other))
        path = self.make_csv(rows)
        result = mod.match_to_csv([
            ("高田製薬", "アリピプラゾールOD錠_製造販売中止のご案内",
             "https://example.test/aripiprazole.pdf")
        ], path)
        self.assertEqual(set(result), set(names))

    def test_terminal_family_match_ignores_names_only_listed_in_group_title(self):
        name = "カンデサルタン錠８ｍｇ「ＤＳＥＰ」"
        path = self.make_csv([self.row(name, maker="第一三共エスファ")])
        result = mod.match_to_csv([
            ("第一三共エスファ", "販売終了製品のご案内（オランザピン錠・カンデサルタン錠）",
             "https://example.test/group.pdf")
        ], path)
        self.assertNotIn(name, result)

    def test_grouped_letter_variants_are_matched(self):
        names = [f"バルヒディオ配合錠{x}「サワイ」" for x in ("ＭＤ", "ＥＸ")]
        path = self.make_csv([self.row(name) for name in names])
        result = mod.match_to_csv([
            ("沢井製薬", "2026/07/01 バルヒディオ配合錠MD/EX「サワイ」販売中止のご案内",
             "https://example.test/balhydio.pdf")
        ], path)
        self.assertEqual(set(result), set(names))

    def test_japanese_generic_source_matches_choseido_products(self):
        names = [f"エポセリン坐剤{x}" for x in ("１２５", "２５０")]
        path = self.make_csv([self.row(name, maker="長生堂製薬") for name in names])
        result = mod.match_to_csv([
            ("日本ジェネリック", "2026.05.01 エポセリン坐剤125/250 販売中止のご案内",
             "https://example.test/epoce.pdf")
        ], path)
        self.assertEqual(set(result), set(names))

    def test_resolved_existing_or_manual_url_is_removed_from_unmatched(self):
        url = "https://example.test/manual.pdf"
        unmatched = [{"maker": "テスト製薬", "title": "販売中止", "url": url}]
        matched = {"テスト錠": {"maker": "テスト製薬", "title": "販売中止", "url": url}}
        self.assertEqual(mod.filter_resolved_unmatched(unmatched, matched), [])

    def test_manual_groups_expand_and_single_entry_can_override(self):
        group_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        single_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: os.path.exists(group_file.name) and os.unlink(group_file.name))
        self.addCleanup(lambda: os.path.exists(single_file.name) and os.unlink(single_file.name))
        with group_file:
            json.dump([{
                "products": ["テスト錠１ｍｇ", "テスト錠２ｍｇ"],
                "target_products_verified": True,
                "announcement": {"maker": "テスト製薬", "title": "販売中止", "url": "group"},
            }], group_file, ensure_ascii=False)
        with single_file:
            json.dump({
                "テスト錠２ｍｇ": {"maker": "テスト製薬", "title": "訂正版", "url": "single"},
            }, single_file, ensure_ascii=False)

        result, resolved_urls, group_events = mod.load_manual_announcements(
            single_file.name, group_file.name)
        self.assertEqual(result["テスト錠１ｍｇ"]["url"], "group")
        self.assertIs(result["テスト錠１ｍｇ"]["target_products_verified"], True)
        self.assertEqual(result["テスト錠２ｍｇ"]["url"], "single")
        self.assertEqual(resolved_urls, {"group", "single"})
        self.assertEqual(group_events[0]["テスト錠２ｍｇ"]["url"], "group")

    def test_manual_group_is_not_verified_without_explicit_opt_in(self):
        group_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: os.path.exists(group_file.name) and os.unlink(group_file.name))
        with group_file:
            json.dump([{
                "products": ["テスト錠"],
                "announcement": {"maker": "テスト製薬", "title": "販売中止", "url": "group"},
            }], group_file, ensure_ascii=False)
        result, _, _ = mod.load_manual_announcements(
            os.path.join(os.path.dirname(group_file.name), "missing.json"), group_file.name)
        self.assertNotIn("target_products_verified", result["テスト錠"])

    def test_manual_groups_keep_history_and_choose_newest_terminal_notice(self):
        group_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False)
        self.addCleanup(lambda: os.path.exists(group_file.name) and os.unlink(group_file.name))
        with group_file:
            json.dump([{
                "products": ["テスト錠"],
                "announcement": {"maker": "テスト製薬", "title": "2024.01.01 販売中止",
                                 "url": "old", "event_type": "discontinued"},
            }, {
                "products": ["テスト錠"],
                "announcement": {"maker": "テスト製薬", "title": "2026.01.01 経過措置の販売終了",
                                 "url": "new", "event_type": "discontinued"},
            }], group_file, ensure_ascii=False)

        result, resolved_urls, group_events = mod.load_manual_announcements(
            os.path.join(os.path.dirname(group_file.name), "missing.json"), group_file.name)
        self.assertEqual(result["テスト錠"]["url"], "new")
        self.assertEqual(resolved_urls, {"old", "new"})
        self.assertEqual([events["テスト錠"]["url"] for events in group_events], ["old", "new"])

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

    def test_collection_deduplicates_repeated_source_links(self):
        def parser_a():
            return [
                ("テスト製薬", "供給案内", "https://example.test/a.pdf"),
                ("テスト製薬", "供給案内", "https://example.test/a.pdf"),
            ]

        def parser_b():
            return [("テスト製薬", "供給案内（別一覧）", "https://example.test/a.pdf")]

        with mock.patch.object(mod, "PARSERS", [parser_a, parser_b]), \
             mock.patch.object(mod, "PAGINATED_PARSERS", set()):
            items, health = mod.collect_announcements()
        self.assertEqual(items, [("テスト製薬", "供給案内", "https://example.test/a.pdf")])
        self.assertEqual([source["count"] for source in health], [1, 1])

    def test_collection_detects_large_volume_regressions(self):
        health = [
            {"source": "parser_a", "ok": True, "count": 150, "error": ""},
            {"source": "parser_b", "ok": True, "count": 3, "error": ""},
        ]
        previous = {
            "total": 1000,
            "sources": [
                {"source": "parser_a", "ok": True, "count": 200, "error": ""},
                {"source": "parser_b", "ok": True, "count": 100, "error": ""},
            ],
        }
        errors = "\n".join(mod.collection_anomalies(health, 153, previous))
        self.assertIn("50%未満", errors)
        self.assertIn("parser_b", errors)


class ParserTests(unittest.TestCase):
    def test_hisamitsu_parser_extracts_recent_pdf(self):
        yy = mod.jst_today().year % 100
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
