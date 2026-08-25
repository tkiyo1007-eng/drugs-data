from __future__ import annotations

import copy
import unittest

from build_supply_discrepancies import make_entry
from validate_supply_discrepancies import validate


YJ_CODE = "1234567F1234"


def supply_row() -> dict[str, str]:
    return {
        "商品名": "テスト錠10mg「ABC」",
        "製造メーカー": "テスト製薬",
        "販売メーカー": "テスト製薬",
        "供給状況": "②限定出荷（自社の事情）",
        "更新日": "2026/08/01",
        "ステータス更新日": "2026/08/05",
        "YJコード": YJ_CODE,
    }


def manufacturer_notice() -> dict[str, object]:
    return {
        "maker": "テスト製薬",
        "title": "2026年8月10日 テスト錠10mg「ABC」 限定出荷解除のお知らせ",
        "event_type": "resumed",
        "announced_at": "2026-08-10",
        "checked": "2026-08-21",
        "url": "https://example.test/notice.pdf",
    }


def valid_document() -> tuple[dict[str, object], dict[str, str], dict[str, object]]:
    row = supply_row()
    notice = manufacturer_notice()
    entry = make_entry(row, notice)
    assert entry is not None
    return ({
        "schema_version": 1,
        "generated_at": "2026-08-21",
        "counts": {"high": 1, "review": 0, "total": 1},
        "products": {YJ_CODE: entry},
    }, row, notice)


class SupplyDiscrepancyValidatorTests(unittest.TestCase):
    def validate_document(self, document, row, notice):
        return validate(
            document,
            {YJ_CODE: row},
            {row["商品名"]: notice},
            {},
            [],
        )

    def test_current_csv_status_label_and_latest_row_date_are_required(self):
        document, row, notice = valid_document()
        official = document["products"][YJ_CODE]["official"]
        self.assertEqual(official, {
            "status": "limited",
            "label": "限定出荷（自社の事情）",
            "updated_at": "2026-08-05",
        })
        self.assertEqual(self.validate_document(document, row, notice), [])

        mutations = (
            ("status", "stopped", "official.status"),
            ("label", "限定出荷", "official.label"),
            ("updated_at", "2026-08-01", "official.updated_at"),
        )
        for field, value, expected_error in mutations:
            with self.subTest(field=field):
                changed = copy.deepcopy(document)
                changed["products"][YJ_CODE]["official"][field] = value
                errors = self.validate_document(changed, row, notice)
                self.assertTrue(any(expected_error in error for error in errors), errors)

    def test_manufacturer_maker_is_recomputed_instead_of_trusting_evidence_flag(self):
        document, row, notice = valid_document()
        changed = copy.deepcopy(document)
        changed["products"][YJ_CODE]["manufacturer"]["maker"] = "無関係製薬"
        self.assertTrue(changed["products"][YJ_CODE]["evidence"]["maker_match"])

        errors = self.validate_document(changed, row, notice)
        self.assertTrue(any("manufacturer.maker" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
