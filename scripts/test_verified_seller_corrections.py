"""一次資料で確認した販売元の修正を、一括の再変換などで元に戻さないための検査。

販売メーカー欄は厚労省Excelではなく過去のローカル変換で補完した値を引き継ぐため、
販売提携の終了などで古くなることがある。修正した品目と根拠をここに記録する。
"""
import csv
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 商品名: (販売メーカー, 根拠)
VERIFIED_SELLERS = {
    # EAファーマ「持田製薬株式会社との販売提携終了のご案内」（2026年4月、MVC-H-1-PM-05483）
    # 持田製薬の販売終了予定: HD 2026年5月、LD 2026年7月。販売はEAファーマが継続。
    "モビコール配合内用剤ＬＤ": ("EAファーマ", "https://www.eapharma.co.jp/hubfs/medical/news/2026/MVC-H-1-PM-05483.pdf"),
    "モビコール配合内用剤ＨＤ": ("EAファーマ", "https://www.eapharma.co.jp/hubfs/medical/news/2026/MVC-H-1-PM-05483.pdf"),
}


class VerifiedSellerCorrectionTests(unittest.TestCase):
    def test_corrected_sellers_are_kept(self):
        with (ROOT / "drugs_app_ready.csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = {row["商品名"]: row for row in csv.DictReader(handle)}
        for name, (seller, source) in VERIFIED_SELLERS.items():
            with self.subTest(name=name):
                self.assertTrue(source.startswith("https://"))
                if name in rows:  # 厚労省一覧から外れた品目は対象外
                    self.assertEqual(seller, rows[name]["販売メーカー"])


if __name__ == "__main__":
    unittest.main()
