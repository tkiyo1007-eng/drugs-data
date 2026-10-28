import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from generate_item_pages import (load_manufacturer_notices, manufacturer_notices_html,
                                 package_supply_html, valid_package_supply)


class PackageSupplyPageTests(unittest.TestCase):
    def row(self):
        return {"商品名": "テスト錠5mg", "YJコード": "1172014F1027", "製造メーカー": "共和薬品工業"}

    def supply(self):
        return {"status": "limited", "status_text": "限定出荷（その他）",
                "plans": [{"event": "stock_depletion", "timing": "2026年10月"},
                          {"event": "shipment_resumption", "timing": "2027年3月頃"}]}

    def notice(self):
        return {"id": "fixture-package", "maker": "共和薬品工業", "title": "包装別の案内",
                "url": "https://www.amel-di.com/medical/di/download/news?nid=69975",
                "announced_at": "2026-09", "verified_at": "2026-10-18", "sha256": "a" * 64,
                "reason": "資料に記載の理由", "alternatives": [], "cautions": [],
                "targets": [{"product_name": "テスト錠5mg", "yj_code": "1172014F1027",
                             "scope": "package", "packages": [
                                 {"package": "PTP100錠", "supply": self.supply()},
                                 {"package": "PTP1000錠"}]}]}

    def test_missing_optional_supply_keeps_legacy_output(self):
        self.assertEqual("", package_supply_html({"packages": [{"package": "100錠"}]}))

    def test_per_package_unknown_is_not_inherited_from_known_neighbor(self):
        output = package_supply_html(self.notice()["targets"][0])
        self.assertEqual(1, output.count("限定出荷（その他）"))
        self.assertEqual(1, output.count("包装別情報未確認"))
        self.assertIn("掲載のない包装", output)

    def test_elapsed_plan_remains_plan_not_completed_status(self):
        target = self.notice()["targets"][0]
        target["packages"][0]["supply"]["plans"][0]["timing"] = "2000年1月"
        output = package_supply_html(target)
        self.assertIn("在庫消尽予定：2000年1月", output)
        self.assertIn("出荷再開予定：2027年3月頃", output)
        self.assertIn("案内時点の出荷対応", output)
        self.assertIn("限定出荷（その他）", output)
        self.assertNotIn("供給停止", output)

    def test_fields_are_escaped(self):
        target = self.notice()["targets"][0]
        p = target["packages"][0]
        p["package"] = "<img src=x>"
        p["supply"]["status_text"] = "<script>alert(1)</script>"
        p["supply"]["plans"][0]["timing"] = "<iframe>"
        p["supply"]["note"] = "<svg onload=x>"
        output = package_supply_html(target)
        for tag in ["<img", "<script", "<iframe", "<svg"]:
            self.assertNotIn(tag, output)
        self.assertIn("&lt;img", output)

    def test_invalid_optional_field_stops_generation(self):
        invalids = [None, [], {}, {"status": [], "plans": []},
                    {"status": "unconfirmed", "status_text": "通常出荷", "plans": []},
                    {"status": "normal", "status_text": "", "plans": []},
                    {"status": "limited", "status_text": "限定出荷", "plans": [{"event": ["stock_depletion"], "timing": "明日"}]},
                    {"status": "limited", "status_text": "限定出荷", "plans": [{"event": "other", "timing": "明日"}]},
                    {"status": "limited", "status_text": "限定出荷", "plans": [], "note": " "}]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "manufacturer_notices.json"
            for bad in invalids:
                with self.subTest(bad=bad):
                    self.assertFalse(valid_package_supply(bad))
                    notice = self.notice()
                    notice["targets"][0]["packages"][0]["supply"] = bad
                    path.write_text(json.dumps({"schema_version": 1, "notices": [notice]}))
                    with self.assertRaises(ValueError):
                        load_manufacturer_notices(path)

    def test_explicit_unknown_and_unknown_future_fields_remain_compatible(self):
        self.assertTrue(valid_package_supply({"status": "unconfirmed", "plans": [], "future_field": 1}))
        self.assertTrue(valid_package_supply(self.supply()))

    def test_changed_source_and_wrong_identity_do_not_show_package_states(self):
        notice = self.notice()
        changed = {"items": [{"url": notice["url"], "sha256": "b" * 64}]}
        output = manufacturer_notices_html(self.row(), [notice], bulletins=changed)
        self.assertNotIn('class="package-supply"', output)
        self.assertIn("再確認待ち", output)
        for key, value in [("商品名", "他の錠"), ("製造メーカー", "他社"), ("YJコード", "1172014F2023")]:
            row = self.row(); row[key] = value
            self.assertEqual("", manufacturer_notices_html(row, [notice]))

    def test_document_date_and_verification_date_remain_separate(self):
        output = manufacturer_notices_html(self.row(), [self.notice()])
        self.assertIn("2026-09", output)
        self.assertIn("2026-10-18", output)
        self.assertIn("メーカー公式案内の原文を確認", output)
        self.assertIn("厚生労働省の現在の供給区分と分けて", output)


if __name__ == "__main__":
    unittest.main()
