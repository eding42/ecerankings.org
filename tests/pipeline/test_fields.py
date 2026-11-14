"""Unit tests for data/fields.json and pipeline/fields.py."""

import argparse
import os
import unittest

from pipeline.fields import (
    FieldConfig,
    add_field_argument,
    get_field,
    list_field_ids,
    load_fields,
)


class TestFields(unittest.TestCase):
    def test_load_all_fields(self):
        fields = load_fields()
        self.assertIn("ece", fields)
        self.assertIn("biology", fields)
        self.assertIn("earth-space", fields)
        self.assertEqual(list_field_ids(), ["biology", "earth-space", "ece"])

    def test_field_configs_have_required_metadata(self):
        fields = load_fields()
        for fid, cfg in fields.items():
            self.assertEqual(cfg.id, fid)
            self.assertTrue(cfg.name)
            self.assertTrue(cfg.short_name)
            self.assertTrue(cfg.description)
            self.assertTrue(cfg.default_credit_types)
            self.assertLessEqual(cfg.earliest_year, cfg.default_start_year)
            self.assertLessEqual(cfg.default_start_year, cfg.default_end_year)

    def test_file_paths_exist_on_disk(self):
        fields = load_fields()
        for fid, cfg in fields.items():
            self.assertTrue(
                os.path.isfile(cfg.areas_path),
                f"Areas file for {fid} not found at {cfg.areas_path}",
            )
            self.assertTrue(
                os.path.isdir(cfg.site_path),
                f"Site directory for {fid} not found at {cfg.site_path}",
            )
            self.assertTrue(
                os.path.isdir(cfg.site_data_path),
                f"Site data directory for {fid} not found at {cfg.site_data_path}",
            )

    def test_get_field_by_id_and_alias(self):
        # By ID
        ece = get_field("ece")
        self.assertEqual(ece.id, "ece")
        self.assertEqual(ece.short_name, "ECERankings")

        bio = get_field("biology")
        self.assertEqual(bio.id, "biology")
        self.assertEqual(bio.short_name, "BioRankings")

        earth = get_field("earth-space")
        self.assertEqual(earth.id, "earth-space")
        self.assertEqual(earth.short_name, "EarthSpaceRankings")

        # By aliases
        self.assertEqual(get_field("bio").id, "biology")
        self.assertEqual(get_field("biosciences").id, "biology")
        self.assertEqual(get_field("engineering").id, "ece")
        self.assertEqual(get_field("earth_space").id, "earth-space")
        self.assertEqual(get_field("geo").id, "earth-space")
        self.assertEqual(get_field("space").id, "earth-space")

    def test_get_unknown_field_raises(self):
        with self.assertRaises(KeyError) as ctx:
            get_field("physics")
        self.assertIn("Unknown field 'physics'", str(ctx.exception))
        self.assertIn("Valid fields: biology, earth-space, ece", str(ctx.exception))

    def test_field_capabilities(self):
        ece = get_field("ece")
        self.assertTrue(ece.has_capability("strict_manifest_checksums"))
        self.assertFalse(ece.has_capability("has_hospital_rollup"))

        bio = get_field("biology")
        self.assertTrue(bio.has_capability("has_hospital_rollup"))
        self.assertTrue(bio.has_capability("has_all_insts_mode"))
        self.assertFalse(bio.has_capability("strict_manifest_checksums"))

        earth = get_field("earth-space")
        self.assertTrue(earth.has_capability("has_sector_filter"))
        self.assertFalse(earth.has_capability("has_hospital_rollup"))

    def test_add_field_argument(self):
        parser = argparse.ArgumentParser()
        add_field_argument(parser, default="ece")
        args = parser.parse_args([])
        self.assertEqual(args.field, "ece")

        args = parser.parse_args(["--field", "biology"])
        self.assertEqual(args.field, "biology")


if __name__ == "__main__":
    unittest.main()
