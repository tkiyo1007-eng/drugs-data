import unittest

from generate_item_pages import hub_html, item_page_lastmod, lifecycle_end_details, page_html


class SupplementalDirectoryTests(unittest.TestCase):
    def entry(self, key, **values):
        return {"key": key, "name": key, "maker": "対象製薬", "status": "ok",
                "hubs": ["supplemental"], **values}

    def test_overlapping_reasons_keep_one_item_and_both_sources_of_information(self):
        lifecycle = {"source_url": "https://example.test/notice.pdf", "source_title": "中止案内",
                     "announced_at": "2026-08", "verified_at": "2026-10-10",
                     "supply_end_expected": "2027-03", "supply_end_note": "在庫消尽次第"}
        output = hub_html("supplemental", [
            self.entry("1111111F1111", lifecycle=lifecycle, delist=True,
                       delist_volume=True, transition_deadline="2027/03/31"),
            self.entry("2222222F2222", delist=True, transition_deadline="2027/03/31"),
            self.entry("3333333F3333", discrepancy={"manufacturer": {"label": "限定出荷"}}),
        ], "2026-10-11")
        self.assertEqual(output.count('href="1111111F1111.html"'), 1)
        self.assertIn('id="sales-notices"', output)
        self.assertIn('id="delisting"', output)
        self.assertIn('id="maker-notices"', output)
        self.assertIn("2027-03", output)
        self.assertIn("在庫消尽次第", output)
        self.assertIn("経過措置期限（厚労省）：2027/03/31", output)
        self.assertIn('href="https://example.test/notice.pdf"', output)
        self.assertIn('id="hubFilterInput"', output)
        self.assertNotIn("近く販売終了となる見込み", output)

    def test_old_notice_timing_is_not_shown_as_the_new_notice_timing(self):
        output = lifecycle_end_details({
            "source_url": "https://example.test/new.pdf",
            "supply_end_source_url": "https://example.test/old.pdf",
            "supply_end_expected": "2027-03-31", "supply_end_note": "古い案内の条件",
            "supply_end_packages": ["古い包装"], "supply_end_verified_at": "2026-10-10",
        })
        self.assertNotIn("2027-03-31", output)
        self.assertNotIn("古い案内の条件", output)
        self.assertNotIn("古い包装", output)
        self.assertIn("日付の収録なし", output)
        directory = hub_html("supplemental", [self.entry("1111111F1111", lifecycle={
            "source_url": "https://example.test/new.pdf",
            "supply_end_source_url": "https://example.test/old.pdf",
            "supply_end_expected": "2099-03-31", "supply_end_note": "旧案内だけの条件",
        })], "2026-10-11")
        self.assertNotIn("2099-03-31", directory)
        self.assertNotIn("旧案内だけの条件", directory)

    def test_official_ended_status_does_not_invent_a_manufacturer_notice(self):
        output = hub_html("supplemental", [self.entry("1111111F1111", status="ended")], "2026-10-11")
        self.assertIn("厚労省の公表区分：販売中止", output)
        self.assertNotIn('<span class="reason-tag">メーカーの販売中止案内</span>', output)

    def test_unknown_end_dates_and_untrusted_text_are_not_invented_or_executed(self):
        output = lifecycle_end_details({"source_url": "https://example.test/notice.pdf",
                                        "supply_end_note": '<script>alert("x")</script>'})
        self.assertIn("日付の収録なし", output)
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)

    def test_transition_deadline_does_not_predict_sales_or_manufacturing_end(self):
        row = {"商品名": "対象錠", "製造メーカー": "対象製薬", "供給状況": "通常出荷",
               "経過措置期限": "2027/03/31", "YJコード": "1111111F1111"}
        output = page_html(row, "1111111F1111", "ok", "2026-10-11", [], {"1111111F1111"})
        self.assertIn("販売・製造の終了や終了日とは別の情報", output)
        self.assertNotIn("近く販売終了となる見込み", output)
        self.assertNotIn("採用の見直しをご検討", output)

    def test_later_manual_timing_revision_uses_its_confirmed_source_date(self):
        row = {"商品名": "対象錠", "製造メーカー": "対象製薬"}
        notice = {"product_name": "対象錠", "maker": "対象製薬",
                  "source_url": "https://example.test/current.pdf",
                  "supply_end_source_url": "https://example.test/current.pdf",
                  "supply_end_verified_at": "2026-11-01"}
        self.assertEqual("2026-11-01", item_page_lastmod(row, notice))
        notice["supply_end_source_url"] = "https://example.test/old.pdf"
        self.assertEqual("2026-10-29", item_page_lastmod(row, notice))


if __name__ == "__main__":
    unittest.main()
