import unittest

from check_supply_source_identity import require_unique_codes


class SupplySourceIdentityTest(unittest.TestCase):
    def test_unique_official_and_synthetic_codes(self):
        require_unique_codes([(None, None, None, None, "799070BX1026"),
                              (None, None, None, None, "X00064")])

    def test_duplicate_is_rejected_including_whitespace(self):
        rows = [(None, None, None, None, "X00064"),
                (None, None, None, None, " X00064 ")]
        with self.assertRaisesRegex(ValueError, "X00064"):
            require_unique_codes(rows)


if __name__ == "__main__":
    unittest.main()
