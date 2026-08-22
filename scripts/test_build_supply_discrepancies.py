from __future__ import annotations

import unittest

from build_supply_discrepancies import build, make_entry


def row(name="テスト錠10mg「ABC」", status="①通常出荷", updated="2026/08/01",
        maker="テスト製薬", sales="テスト製薬", yj="1234567F1234"):
    return {
        "商品名": name, "製造メーカー": maker, "販売メーカー": sales,
        "供給状況": status, "更新日": updated, "ステータス更新日": "", "YJコード": yj,
    }


def announcement(title="2026年8月10日 テスト錠10mg「ABC」 限定出荷のお知らせ",
                 event_type="limited", announced="2026-08-10", maker="テスト製薬"):
    return {
        "maker": maker, "title": title, "event_type": event_type,
        "announced_at": announced, "checked": "2026-08-21", "url": "https://example.com/notice.pdf",
    }


class SupplyDiscrepancyBuilderTests(unittest.TestCase):
    def test_newer_exact_manufacturer_notice_is_high_confidence(self):
        entry = make_entry(row(), announcement())
        self.assertEqual(entry["confidence"], "high")
        self.assertEqual(entry["official"]["status"], "ok")
        self.assertEqual(entry["manufacturer"]["status"], "limited")

    def test_older_notice_and_matching_status_are_not_discrepancies(self):
        self.assertIsNone(make_entry(row(updated="2026/08/15"), announcement()))
        self.assertIsNone(make_entry(row(status="②限定出荷（自社の事情）"), announcement()))

    def test_month_precision_must_be_definitely_newer(self):
        self.assertIsNone(make_entry(row(updated="2026/08/01"), announcement(announced="2026-08")))
        self.assertIsNotNone(make_entry(row(updated="2026/07/31"), announcement(announced="2026-08")))

    def test_family_match_without_exact_strength_is_review_only(self):
        entry = make_entry(
            row(name="テスト錠5mg「ABC」"),
            announcement(title="2026年8月10日 テスト錠20mg「ABC」 限定出荷のお知らせ"),
        )
        self.assertEqual(entry["confidence"], "review")
        self.assertEqual(entry["manufacturer"]["scope"], "ambiguous")

    def test_maker_mismatch_is_review_only(self):
        entry = make_entry(row(), announcement(maker="別会社"))
        self.assertEqual(entry["confidence"], "review")

    def test_package_word_after_product_is_recorded(self):
        entry = make_entry(
            row(),
            announcement(title="2026年8月10日 テスト錠10mg「ABC」 PTP100錠 限定出荷のお知らせ"),
        )
        self.assertEqual(entry["manufacturer"]["scope"], "package")

    def test_resumption_conflicts_with_older_official_stop(self):
        entry = make_entry(
            row(status="⑤供給停止"),
            announcement(title="2026年8月10日 テスト錠10mg「ABC」 出荷再開", event_type="resumed"),
        )
        self.assertEqual(entry["manufacturer"]["status"], "resumed")

    def test_limited_resumption_does_not_overstate_normal_supply(self):
        self.assertIsNone(make_entry(
            row(status="②限定出荷（自社の事情）"),
            announcement(
                title="2026年8月10日 テスト錠10mg「ABC」限定出荷による出荷再開",
                event_type="resumed",
            ),
        ))

    def test_limited_release_is_a_confirmed_return_to_normal(self):
        entry = make_entry(
            row(status="②限定出荷（自社の事情）"),
            announcement(
                title="2026年8月10日 テスト錠10mg「ABC」限定出荷解除のご案内",
                event_type="resumed",
            ),
        )
        self.assertEqual(entry["manufacturer"]["status"], "ok")

    def test_document_is_keyed_by_yj_and_counts_confidence(self):
        rows = [row(), row(name="テスト錠5mg「ABC」", yj="1234567F5678")]
        announcements = {
            "テスト錠10mg「ABC」": announcement(),
            "テスト錠5mg「ABC」": announcement(
                title="2026年8月10日 テスト錠20mg「ABC」 限定出荷のお知らせ"
            ),
        }
        document = build(rows, announcements, {"version": 202608212350, "note": "test"})
        self.assertEqual(document["counts"], {"high": 1, "review": 1, "total": 2})
        self.assertEqual(set(document["products"]), {"1234567F1234", "1234567F5678"})

    def test_latest_history_prevents_old_limited_notice_from_returning(self):
        rows = [row()]
        announcements = {"テスト錠10mg「ABC」": announcement()}
        events = {"テスト錠10mg「ABC」": [
            announcement(),
            announcement(
                title="2026年8月20日 テスト錠10mg「ABC」限定出荷解除",
                event_type="resumed",
                announced="2026-08-20",
            ),
        ]}
        document = build(rows, announcements, {"version": 202608212350}, events)
        self.assertEqual(document["products"], {})

    def test_latest_unknown_supply_notice_does_not_reuse_old_limited_state(self):
        rows = [row()]
        announcements = {"テスト錠10mg「ABC」": announcement()}
        events = {"テスト錠10mg「ABC」": [
            announcement(),
            announcement(
                title="2026年8月20日 テスト錠10mg「ABC」供給に関するお知らせ",
                event_type="supply",
                announced="2026-08-20",
            ),
        ]}
        document = build(rows, announcements, {"version": 202608212350}, events)
        self.assertEqual(document["products"], {})


if __name__ == "__main__":
    unittest.main()
