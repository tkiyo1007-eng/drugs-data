from __future__ import annotations

import copy
import unittest
from pathlib import Path

from public_data_manifest import PUBLIC_FILES, build_manifest, validate_manifest


class PublicDataManifestTests(unittest.TestCase):
    def setUp(self):
        self.document = build_manifest(Path(__file__).resolve().parents[1], "a" * 40)

    def test_manifest_covers_existing_data_without_rewriting_it(self):
        self.assertEqual(validate_manifest(self.document), [])
        self.assertEqual(set(self.document["files"]), set(PUBLIC_FILES))
        self.assertIn("maker_collection_health.json", self.document["files"])
        self.assertIn("items/keys.json", self.document["files"])
        self.assertNotIn("generated_at", self.document)

    def test_invalid_commit_hash_size_and_file_set_are_rejected(self):
        for field, value in (("schema_version", True), ("source_commit", "main"),
                             ("files", {}), ("files", {"../secret": {}})):
            broken = copy.deepcopy(self.document)
            broken[field] = value
            self.assertTrue(validate_manifest(broken))
        for field, value in (("sha256", "bogus"), ("bytes", True), ("bytes", 0)):
            broken = copy.deepcopy(self.document)
            broken["files"]["version.json"][field] = value
            self.assertTrue(validate_manifest(broken))

    def test_generator_requires_immutable_commit(self):
        with self.assertRaises(ValueError):
            build_manifest(Path("."), "main")


if __name__ == "__main__":
    unittest.main()
