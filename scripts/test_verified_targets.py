import csv
import json
import unittest
from pathlib import Path

from verified_targets import verified_target_registry


class VerifiedTargetRegistryTests(unittest.TestCase):
    def test_every_declared_manual_target_resolves_to_a_unique_yj_and_url(self):
        root = Path(__file__).resolve().parents[1]
        with (root / "drugs_app_ready.csv").open(
            encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
        groups = json.loads(
            (root / "manual_announcement_groups.json").read_text(encoding="utf-8")
        )
        expected = sum(
            len(group.get("products") or [])
            + len(group.get("lifecycle_targets") or [])
            for group in groups
            if group.get("target_products_verified") is True
        )
        registry = verified_target_registry(rows, groups)
        self.assertEqual(len(registry), expected)


if __name__ == "__main__":
    unittest.main()
