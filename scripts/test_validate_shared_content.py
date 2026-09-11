import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("validate_shared_content.py")
SPEC = importlib.util.spec_from_file_location("validate_shared_content", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SharedContentValidationTests(unittest.TestCase):
    def test_optional_sources_reject_non_https_and_notes_reject_non_text(self):
        base = Path(__file__).resolve().parents[1]
        read_json = MODULE.read_json

        def invalid_topic(path):
            document = read_json(path)
            if path.name == "industry_topics.json":
                document["topics"][0]["sources"] = [{"name": "原文", "url": "javascript:alert(1)"}]
                document["topics"][0]["notes"] = [{"html": "invalid"}]
            return document

        with patch.object(MODULE, "read_json", side_effect=invalid_topic):
            errors = MODULE.validate(base)
        self.assertTrue(any(".sources[0]" in error for error in errors))
        self.assertTrue(any(".notes" in error for error in errors))

    def test_repository_shared_content_is_valid(self):
        base = Path(__file__).resolve().parents[1]
        self.assertEqual([], MODULE.validate(base))


if __name__ == "__main__":
    unittest.main()
