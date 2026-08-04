import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("validate_shared_content.py")
SPEC = importlib.util.spec_from_file_location("validate_shared_content", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SharedContentValidationTests(unittest.TestCase):
    def test_repository_shared_content_is_valid(self):
        base = Path(__file__).resolve().parents[1]
        self.assertEqual([], MODULE.validate(base))


if __name__ == "__main__":
    unittest.main()
