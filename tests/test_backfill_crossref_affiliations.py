import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

import backfill_crossref_affiliations as bcf  # noqa: E402


def slot(name, institutions=None, raw=None):
    return {"author_id": "https://openalex.org/A1", "author_name": name,
            "institutions": institutions or [], "raw_affiliations": raw or []}


def cr_author(given, family, *affs):
    return {"given": given, "family": family, "affiliation": [{"name": a} for a in affs]}


class FamilyAlignmentTest(unittest.TestCase):
    def test_matches_family_token_ignoring_accents_and_hyphens(self):
        self.assertTrue(bcf.family_in_name("Kabuli", "Leyla Kabuli"))
        self.assertTrue(bcf.family_in_name("Müller", "Anna Muller"))
        self.assertTrue(bcf.family_in_name("Lopez-Ruiz", "Ana Lopez Ruiz"))

    def test_rejects_substring_that_is_not_a_token(self):
        # "Li" is a substring of "Lili" but not a token of it.
        self.assertFalse(bcf.family_in_name("Li", "Lili Wang"))

    def test_missing_family_never_aligns(self):
        self.assertFalse(bcf.family_in_name(None, "Leyla Kabuli"))
        self.assertFalse(bcf.family_in_name("", "Leyla Kabuli"))


class PlanWorkTest(unittest.TestCase):
    def test_fills_only_empty_slots_and_keeps_openalex_institutions(self):
        work = {"authorships": [
            slot("Leyla Kabuli", institutions=[{"id": "https://openalex.org/I1"}]),
            slot("Henry Pinkard"),
        ]}
        msg = {"author": [cr_author("Leyla", "Kabuli", "MIT"),
                          cr_author("Henry", "Pinkard", "UC Berkeley", "UC Berkeley", "Chan Zuckerberg")]}
        fills, status = bcf.plan_work(work, msg)
        self.assertEqual(status, "filled")
        self.assertEqual(fills, {1: ["UC Berkeley", "Chan Zuckerberg"]})

    def test_author_count_mismatch_skips_whole_work(self):
        work = {"authorships": [slot("A B"), slot("C D")]}
        msg = {"author": [cr_author("A", "B", "X")]}
        self.assertEqual(bcf.plan_work(work, msg), ({}, "author-count-mismatch"))

    def test_misaligned_name_skips_whole_work(self):
        work = {"authorships": [slot("Ada Lovelace"), slot("Alan Turing")]}
        msg = {"author": [cr_author("Alan", "Turing", "X"), cr_author("Ada", "Lovelace", "Y")]}
        self.assertEqual(bcf.plan_work(work, msg), ({}, "name-misaligned"))

    def test_no_empty_slots_is_untouched(self):
        work = {"authorships": [slot("A B", raw=["Somewhere"])]}
        self.assertEqual(bcf.plan_work(work, {"author": [cr_author("A", "B", "X")]}),
                         ({}, "no-empty-slots"))

    def test_crossref_without_affiliations_reports_status(self):
        work = {"authorships": [slot("A B")]}
        self.assertEqual(bcf.plan_work(work, {"author": [cr_author("A", "B")]}),
                         ({}, "crossref-no-affiliations"))


class NormalizationTest(unittest.TestCase):
    def test_norm_doi_strips_resolver_and_case(self):
        self.assertEqual(bcf.norm_doi("https://doi.org/10.1364/OPTICA.570334"), "10.1364/optica.570334")
        self.assertIsNone(bcf.norm_doi(None))

    def test_crossref_affiliations_dedupes_in_order(self):
        author = cr_author("A", "B", "MIT", "", "MIT", "Stanford")
        self.assertEqual(bcf.crossref_affiliations(author), ["MIT", "Stanford"])


if __name__ == "__main__":
    unittest.main()
