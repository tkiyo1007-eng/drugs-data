import datetime as dt
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import create_monthly_report as cmr
from generate_curated_pages import load_reports, report_index_page, report_page

ROOT = Path(__file__).resolve().parents[1]


class MonthlyReportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.site = Path(self.tempdir.name)
        for name in ("drugs_app_ready.csv", "crisis_index.json", "resolution_stats.json"):
            shutil.copy(ROOT / name, self.site / name)
        self.changes = [
            {"date": "2026/09/20", "yj": "2233002F1336", "name": "A", "from": "①通常出荷", "to": "②限定出荷（自社の事情）"},
            {"date": "2026/09/20", "yj": "2233002F1344", "name": "B", "from": "①通常出荷", "to": "⑤供給停止"},
            {"date": "2026/09/15", "yj": "X99999", "name": "C", "from": "③限定出荷（他社品の影響）", "to": "①通常出荷"},
            {"date": "2026/08/31", "yj": "1149001F1010", "name": "D", "from": "①通常出荷", "to": "⑤供給停止"},
            {"date": "2026/10/01", "yj": "1149001F1020", "name": "E", "from": "①通常出荷", "to": "⑤供給停止"},
        ]
        (self.site / "status_changes.json").write_text(json.dumps(self.changes, ensure_ascii=False), encoding="utf-8")

    def set_version(self, note):
        (self.site / "version.json").write_text(json.dumps({"note": note}, ensure_ascii=False), encoding="utf-8")

    def run_main(self):
        return cmr.main(["--site", str(self.site), "--csv", str(self.site / "drugs_app_ready.csv")])

    def test_creates_previous_month_once_and_never_overwrites(self):
        self.set_version("2026年10月01日厚労省データ反映")
        self.assertEqual(0, self.run_main())
        path = self.site / "reports" / "2026-09.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({"items": 3, "days_with_changes": 2, "to_limited": 1, "to_stopped": 1, "to_ok": 1, "other": 0},
                         report["changes"])
        self.assertEqual("2026-10-01", report["snapshot_date"])
        self.assertEqual({"month": "2026-08", "items": 1, "to_limited": 0, "to_stopped": 1, "to_ok": 0, "other": 0},
                         report["previous_month"])
        self.assertEqual([{"name": "去たん剤", "code": "223", "count": 2}], report["top_new_restriction_categories"])
        path.write_text(path.read_text(encoding="utf-8").replace('"items": 3', '"items": 999'), encoding="utf-8")
        self.set_version("2026年10月02日厚労省データ反映")
        self.run_main()
        self.assertIn('"items": 999', path.read_text(encoding="utf-8"))

    def test_does_not_backfill_before_start_or_without_full_coverage(self):
        self.set_version("2026年09月25日厚労省データ反映")  # 前月=8月は対象外
        self.run_main()
        self.assertFalse((self.site / "reports").exists())
        self.assertIsNone(cmr.build_report(self.site, self.site / "drugs_app_ready.csv", "2026-09", dt.date(2026, 12, 31)))

    def test_unknown_status_fails_instead_of_miscounting(self):
        self.changes.append({"date": "2026/09/21", "yj": "Y", "name": "F", "from": "①通常出荷", "to": "⑨未知"})
        (self.site / "status_changes.json").write_text(json.dumps(self.changes, ensure_ascii=False), encoding="utf-8")
        self.set_version("2026年10月01日厚労省データ反映")
        with self.assertRaises(ValueError):
            self.run_main()

    def test_page_labels_snapshot_date_caveats_and_citation(self):
        self.set_version("2026年10月01日厚労省データ反映")
        self.run_main()
        [report] = load_reports(self.site)
        page = report_page(report)
        self.assertIn("2026-10-01時点の公表区分", page)
        self.assertNotIn("月末時点", page)
        self.assertIn("長期間続く制限は含まれないため短めに出ます", page)
        self.assertIn("公的な指標ではありません", page)
        self.assertIn("出典：医薬品供給ナビ「医薬品供給レポート（2026年9月）」", page)
        self.assertIn('href="../categories/223.html"', page)
        for forbidden in ("おすすめ", "代わりに", "在庫あり"):
            self.assertNotIn(forbidden, page)
        self.assertEqual(page, report_page(report))
        self.assertIn('href="2026-09.html"', report_index_page([report]))

    def test_workflow_freezes_report_before_rendering_and_commits_it(self):
        workflow = (ROOT / ".github/workflows/update_drugs.yml").read_text(encoding="utf-8")
        self.assertLess(workflow.index("scripts/create_monthly_report.py"),
                        workflow.index("scripts/generate_curated_pages.py"))
        self.assertIn("categories reports sitemap-curated.xml", workflow)
        self.assertTrue((ROOT / "reports" / ".gitkeep").exists())


if __name__ == "__main__":
    unittest.main()
