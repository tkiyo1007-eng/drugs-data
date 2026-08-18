import unittest
from pathlib import Path


class UpdateWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[1] / ".github" / "workflows" / "update_drugs.yml"
        ).read_text(encoding="utf-8")

    def test_validated_core_and_pages_are_published_before_optional_enrichment(self):
        supply_validation = self.workflow.index("公開前の供給CSV品質検査")
        item_pages = self.workflow.index("品目別SEOページを最新の厚労省データで生成")
        daily_pages = self.workflow.index("日別の供給変更ページを生成")
        core_publish = self.workflow.index("検証済み厚労省コアデータと対応ページを先に公開")
        reconcile = self.workflow.index("前回の補足情報を最新CSVへ整合")
        optional_refresh = self.workflow.index("メーカー補足情報を一時領域で取得・検証")
        self.assertLess(supply_validation, item_pages)
        self.assertLess(reconcile, core_publish)
        self.assertLess(item_pages, core_publish)
        self.assertLess(daily_pages, core_publish)
        self.assertLess(core_publish, optional_refresh)

    def test_optional_refresh_explicitly_uses_last_known_good_fallback(self):
        self.assertIn("scripts/update_maker_enrichment.py", self.workflow)
        self.assertIn("--fallback-to-previous", self.workflow)
        self.assertNotIn(
            "python3 scripts/fetch_maker_announcements.py drugs_app_ready.csv",
            self.workflow,
        )

    def test_fallback_skips_all_downstream_manufacturer_derived_steps(self):
        self.assertIn("id: maker_refresh", self.workflow)
        condition = "if: steps.maker_refresh.outputs.updated == 'true'"
        self.assertGreaterEqual(self.workflow.count(condition), 3)
        for step in (
            "販売中止案内をYJコード別ライフサイクルへ変換",
            "メーカー補足情報を含めて話題のページを再生成",
            "案内文PDFから包装単位を抽出",
        ):
            position = self.workflow.index(step)
            condition_position = self.workflow.index(condition, position)
            self.assertLess(condition_position - position, 180)

    def test_both_pushes_retry_after_rebase(self):
        self.assertEqual(self.workflow.count("for push_attempt in 1 2 3 4 5"), 2)
        self.assertEqual(self.workflow.count("git pull --rebase origin main"), 2)

    def test_core_commit_contains_csv_version_and_core_generated_pages(self):
        start = self.workflow.index("検証済み厚労省コアデータと対応ページを先に公開")
        end = self.workflow.index("メーカー補足情報を一時領域で取得・検証")
        core_step = self.workflow[start:end]
        for artifact in (
            "drugs_app_ready.csv",
            "version.json",
            "status_changes.json",
            "items sitemap-items.xml",
            "updates sitemap-updates.xml",
        ):
            with self.subTest(artifact=artifact):
                self.assertIn(artifact, core_step)


if __name__ == "__main__":
    unittest.main()
