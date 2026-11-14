"""Unit tests for --field parameterization in pipeline/aggregate.py and pipeline/split.py."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

from fields import get_field


class TestAggregateFieldCLI(unittest.TestCase):
    def test_aggregate_scoped_run_rejects_default_output_for_field(self):
        # ECE default output protection
        res_ece = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/aggregate.py"), "--field", "ece", "--venue", "jssc"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_ece.returncode, 0)
        self.assertIn("Scoped runs require --out pointing outside site/data", res_ece.stderr)

        # Earth & Space default output protection
        res_earth = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/aggregate.py"), "--field", "earth-space", "--venue", "apj"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_earth.returncode, 0)
        self.assertIn("Scoped runs require --out pointing outside site/earth-space/data", res_earth.stderr)

        # Biology default output protection
        res_bio = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/aggregate.py"), "--field", "biology", "--venue", "cell"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_bio.returncode, 0)
        self.assertIn("Scoped runs require --out pointing outside data/biosciences_aggregates", res_bio.stderr)

    def test_aggregate_field_defaults_resolution(self):
        # Verify that get_field matches expected configs for each discipline
        ece = get_field("ece")
        self.assertEqual(ece.areas_file, "data/areas.json")
        self.assertEqual(ece.cache_dir, "cache")
        self.assertEqual(ece.site_data_dir, "site/data")
        self.assertEqual(set(ece.default_credit_types), {"education"})

        earth = get_field("earth-space")
        self.assertEqual(earth.areas_file, "data/areas_earth_space.json")
        self.assertEqual(earth.cache_dir, "cache")
        self.assertEqual(earth.site_data_dir, "site/earth-space/data")
        self.assertEqual(
            set(earth.default_credit_types),
            {"education", "facility", "government", "nonprofit"},
        )

        bio = get_field("biology")
        self.assertEqual(bio.areas_file, "data/areas_biosciences.json")
        self.assertEqual(bio.cache_dir, "cache_biosciences")
        self.assertEqual(bio.site_data_dir, "site/biology/data")
        self.assertTrue(bio.has_capability("has_all_insts_mode"))

    def test_aggregate_help_mentions_field_options(self):
        res = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/aggregate.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--field", res.stdout)
        import re
        normalized = re.sub(r"\s+", " ", res.stdout)
        self.assertIn("choices: biology, earth- space, ece", normalized)

    def test_split_help_mentions_field_options(self):
        res = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/split.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--field", res.stdout)
        import re
        normalized = re.sub(r"\s+", " ", res.stdout)
        self.assertIn("choices: biology, earth- space, ece", normalized)


if __name__ == "__main__":
    unittest.main()
