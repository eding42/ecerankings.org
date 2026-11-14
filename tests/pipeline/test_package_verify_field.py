"""Unit tests for --field parameterization in pipeline/package_site.py and pipeline/verify.py."""

import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

from fields import get_field


class TestPackageAndVerifyFieldCLI(unittest.TestCase):
    def test_package_site_help_mentions_field_options(self):
        res = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/package_site.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--field", res.stdout)
        import re
        normalized = re.sub(r"-\s+", "-", re.sub(r"\s+", " ", res.stdout))
        self.assertIn("choices: biology, earth-space, ece", normalized)

    def test_verify_help_mentions_field_options(self):
        res = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/verify.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("--field", res.stdout)
        import re
        normalized = re.sub(r"-\s+", "-", re.sub(r"\s+", " ", res.stdout))
        self.assertIn("choices: biology, earth-space, ece", normalized)

    def test_verify_field_unknown_area_validation(self):
        # ECE does not have 'astronomy'
        res_ece = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/verify.py"), "--field", "ece", "--phase", "3", "--area", "astronomy"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_ece.returncode, 0)
        self.assertIn("Unknown area: astronomy", res_ece.stderr)

        # Earth & Space HAS 'astronomy', but does not have 'circuits'
        res_earth = subprocess.run(
            [sys.executable, str(ROOT / "pipeline/verify.py"), "--field", "earth-space", "--phase", "3", "--area", "circuits"],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(res_earth.returncode, 0)
        self.assertIn("Unknown area: circuits", res_earth.stderr)


if __name__ == "__main__":
    unittest.main()
