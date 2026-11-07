import unittest
from check_reviewed_gas_sources import validate


class ReviewedGasSourceTests(unittest.TestCase):
    def setUp(self):
        self.reviewed = {'X00001': {'name': '液化酸素', 'manufacturer': '会社A'}}

    def test_same_identity_and_removed_row(self):
        self.assertEqual([], validate([('X00001', '液化酸素', '会社Ａ')], self.reviewed))
        self.assertEqual([], validate([], self.reviewed))

    def test_changed_name_maker_and_duplicate_stop(self):
        self.assertTrue(validate([('X00001', '液体窒素', '会社A')], self.reviewed))
        self.assertTrue(validate([('X00001', '液化酸素', '会社B')], self.reviewed))
        self.assertTrue(validate([('X00001', '液化酸素', '会社A'), ('X00001', '液化酸素', '会社A')], self.reviewed))
