import csv
import tempfile
import unittest
from pathlib import Path

from sanitize_maker_fields import (
    MULTIPLE_MAKERS_LABEL,
    NOISE_END,
    NOISE_MARKER,
    NOISE_START,
    sanitize_csv,
    strip_gas_document_note,
)


NOTE = NOISE_START + NOISE_MARKER + "を以下に掲載しております。" + NOISE_END


class SanitizeMakerFieldsTests(unittest.TestCase):
    def test_keeps_real_company_names_around_document_note(self):
        value = "日本エア・リキード合同会社・" + NOTE + "・小池メディカル"
        self.assertEqual(
            ("日本エア・リキード合同会社・小池メディカル", True),
            strip_gas_document_note(value),
        )

    def test_unknown_incomplete_note_is_not_deleted_by_guess(self):
        value = NOISE_START + NOISE_MARKER + "（文末不明）"
        self.assertEqual((value, False), strip_gas_document_note(value))

    def test_pure_note_uses_honest_manufacturer_label_and_empty_sales(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "drugs.csv"
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["商品名", "製造メーカー", "販売メーカー"])
                writer.writerow(["液体酸素", NOTE, NOTE])
            self.assertEqual((1, 1), sanitize_csv(path))
            with path.open(encoding="utf-8-sig", newline="") as handle:
                row = list(csv.DictReader(handle))[0]
            self.assertEqual(MULTIPLE_MAKERS_LABEL, row["製造メーカー"])
            self.assertEqual("", row["販売メーカー"])


if __name__ == "__main__":
    unittest.main()
