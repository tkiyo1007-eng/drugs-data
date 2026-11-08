import tempfile
import unittest
from pathlib import Path
import openpyxl
from audit_manufacturer_drift import audit, comparable, load_source


class ManufacturerDriftAudit(unittest.TestCase):
    def test_legal_suffix_and_punctuation_are_not_false_transfers(self):
        self.assertEqual(comparable('ヴィアトリス・ヘルスケア合同会社'), comparable('ヴィアトリス・ヘルスケア'))
        self.assertEqual(comparable("T's製薬"), comparable('Ｔ’ｓ製薬'))

    def test_changed_owner_is_a_review_candidate_not_an_automatic_edit(self):
        row = {'YJコード': '1', '製造メーカー': '田辺ファーマ'}
        result = audit([row], {'1': ['塩野義製薬']})
        self.assertEqual(result['review_pairs'][('田辺ファーマ', '塩野義製薬')], 1)
        self.assertEqual(row['製造メーカー'], '田辺ファーマ')

    def test_missing_duplicate_and_blank_are_distinct(self):
        rows = [{'YJコード': '1', '製造メーカー': 'A'}, {'YJコード': '2', '製造メーカー': 'B'},
                {'YJコード': '3', '製造メーカー': ''}]
        result = audit(rows, {'1': ['A', 'B'], '3': ['C']})
        self.assertEqual((result['missing'], result['ambiguous']), (1, 1))
        self.assertEqual(result['review_pairs'][('', 'C')], 1)

    def test_excel_headers_are_identified_and_duplicate_codes_preserved(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(['heading'])
        sheet.append(['⑦製造販売業者名', '⑤YJコード'])
        sheet.append(['企業A', '123'])
        sheet.append(['企業B', '123'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            workbook.save(path)
            self.assertEqual(load_source(path), {'123': ['企業A', '企業B']})

    def test_unexpected_excel_headers_are_not_interpreted_as_source_data(self):
        workbook = openpyxl.Workbook()
        workbook.active.append(['name', 'value'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            workbook.save(path)
            with self.assertRaises(ValueError):
                load_source(path)


if __name__ == '__main__':
    unittest.main()
