import re
import unittest
from pathlib import Path

from generate_curated_pages import watch_guide_page

ROOT = Path(__file__).resolve().parents[1]
LABELS = ("CSVからまとめて追加", "CSVから追加・復元", "未確認の変更を見る", "確認済みにする",
          "変更を共有", "文章をコピー", "監視リストを保存", "ホーム画面に追加")


class WatchGuideTests(unittest.TestCase):
    def setUp(self):
        self.page = watch_guide_page()
        self.web = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_every_button_label_in_the_guide_exists_in_published_web(self):
        for label in LABELS:
            with self.subTest(label=label):
                self.assertIn(f"「{label}」", self.page)
                self.assertIn(f">{label}</button>", self.web)

    def test_import_limits_and_columns_match_web_implementation(self):
        self.assertIn("5MB", self.page)
        self.assertIn("10,000行", self.page)
        self.assertIn('"yjコード","yjcode","薬価基準収載医薬品コード"', self.web)
        self.assertIn('"商品名","品名","医薬品名","製品名"', self.web)
        self.assertRegex(self.web, r"rows\.length > 10001")
        self.assertIn('["YJコード","商品名","メーカー","供給状況","更新日"]', self.web)

    def test_privacy_and_medical_safety_statements(self):
        self.assertIn("外部へ送信しません", self.page)
        self.assertIn("実在庫や入手可否を示すものではありません", self.page)
        self.assertIn('href="../#watchDashboard"', self.page)
        self.assertIn('id="watchDashboard"', self.web)


if __name__ == "__main__":
    unittest.main()
