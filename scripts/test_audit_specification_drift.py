import tempfile
import unittest
from pathlib import Path
import openpyxl
from audit_specification_drift import audit, comparable, load_source


class SpecificationDriftAudit(unittest.TestCase):
    def test_normalization_and_changed_value_without_mutation(self):
        self.assertEqual(comparable('１０ ｍＬ'), comparable('10mL'))
        row = {'YJコード': '1', '規格': '１Ｌ'}
        result = audit([row], {'1': ['１０ｍＬ']})
        self.assertEqual(result['pairs'][('１Ｌ', '１０ｍＬ')], 1)
        self.assertEqual(row['規格'], '１Ｌ')

    def test_missing_duplicate_and_blank_are_distinct(self):
        rows = [{'YJコード': '1', '規格': 'A'}, {'YJコード': '2', '規格': 'B'},
                {'YJコード': '3', '規格': ''}]
        result = audit(rows, {'1': ['A', 'B'], '3': ['C']})
        self.assertEqual((result['missing'], result['ambiguous']), (1, 1))
        self.assertEqual(result['pairs'][('', 'C')], 1)

    def test_excel_headers_and_duplicate_codes(self):
        book = openpyxl.Workbook()
        book.active.append(['heading'])
        book.active.append(['⑤YJコード', '④規格単位\n※全角'])
        book.active.append(['X01', '１Ｌ'])
        book.active.append(['X01', '１０ｍＬ'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            book.save(path)
            self.assertEqual(load_source(path), {'X01': ['１Ｌ', '１０ｍＬ']})

    def test_unexpected_headers_fail(self):
        book = openpyxl.Workbook()
        book.active.append(['name', 'value'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.xlsx'
            book.save(path)
            with self.assertRaises(ValueError):
                load_source(path)


if __name__ == '__main__':
    unittest.main()
