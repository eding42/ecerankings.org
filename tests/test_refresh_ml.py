import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import refresh_ml


def oa_work(doi="10.1234/paper", title="Paper on machine learning", ident="W1", authorships=None, **extra):
    return {"id": f"https://openalex.org/{ident}", "doi": f"https://doi.org/{doi}", "title": title,
            "publication_year": 2020, "type": "article", "authorships": authorships or [], **extra}


def authorship(name="Ada Lovelace", raw=None):
    return {"author": {"id": "https://openalex.org/A1", "display_name": name},
            "institutions": [], "raw_affiliation_strings": raw or []}


class RefreshMLTests(unittest.TestCase):
    def test_missing_doi_profile_evidence_stays_out_of_historical_credit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            source = base / "icml" / "2020" / "works.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"id": None, "doi": None, "title": "No DOI", "source": "semanticscholar",
                                         "authorships": [{"author_name": "A", "institutions": [{"id": "I-unverified"}], "raw_affiliations": ["Current University"]}]}) + "\n")
            output = Path(tmp) / "out"
            manifest = Path(tmp) / "manifest.json"
            report = refresh_ml.run(base, output, manifest, None)
            row = json.loads((output / "icml/2020/works.jsonl").read_text())
            author = row["authorships"][0]
            self.assertEqual(author["profile_affiliations"], ["Current University"])
            self.assertEqual(author["raw_affiliations"], [])
            self.assertEqual(author["institutions"], [])
            self.assertEqual(author["profile_affiliation_scope"], "Semantic Scholar author profile; not verified at publication")
            self.assertEqual(report["counts"]["missing_doi_unresolved"], 1)
            self.assertEqual(report["counts"]["profile_affiliations_withheld_from_historical_credit"], 1)

    def test_title_collision_is_rejected_even_when_doi_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            source = base / "icml/2020/works.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"id": None, "doi": "https://doi.org/10.1234/paper", "title": "Quantum cryptography", "source": "semanticscholar",
                                         "authorships": [{"author_name": "A", "institutions": [], "raw_affiliations": ["Current University"]}]}) + "\n")
            output = Path(tmp) / "out"
            manifest = Path(tmp) / "manifest.json"
            with patch.object(refresh_ml.OAClient, "batch", return_value=[oa_work(authorships=[authorship()])]):
                report = refresh_ml.run(base, output, manifest, None)
            row = json.loads((output / "icml/2020/works.jsonl").read_text())
            self.assertNotEqual(row.get("backfilled_from"), "openalex")
            self.assertEqual(row["authorships"][0]["raw_affiliations"], [])
            self.assertEqual(row["authorships"][0]["institutions"], [])
            self.assertEqual(report["api_execution"]["doi_title_identity_rejected"], 1)

    def test_publication_year_mismatch_is_not_backfilled(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            source = base / "icml/2020/works.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"id": None, "doi": "https://doi.org/10.1234/paper", "title": "Paper on machine learning", "publication_year": 2020, "source": "semanticscholar",
                                         "authorships": [{"author_name": "A", "institutions": [], "raw_affiliations": []}]}) + "\n")
            output = Path(tmp) / "out"
            manifest = Path(tmp) / "manifest.json"
            with patch.object(refresh_ml.OAClient, "batch", return_value=[oa_work(publication_year=2019, authorships=[authorship()])]):
                report = refresh_ml.run(base, output, manifest, None)
            row = json.loads((output / "icml/2020/works.jsonl").read_text())
            self.assertNotEqual(row.get("backfilled_from"), "openalex")
            self.assertEqual(row["publication_year"], 2020)
            self.assertEqual(report["api_execution"]["doi_year_identity_rejected_rows"], 1)

    def test_unaligned_profile_evidence_is_retained_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base"
            source = base / "icml/2020/works.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(json.dumps({"id": None, "doi": "https://doi.org/10.1234/paper", "title": "Paper on machine learning", "publication_year": 2020, "source": "semanticscholar",
                                         "authorships": [{"author_id": "s2:1", "author_name": "Different baseline author", "institutions": [], "raw_affiliations": ["Current University"]}]}) + "\n")
            output = Path(tmp) / "out"
            manifest = Path(tmp) / "manifest.json"
            with patch.object(refresh_ml.OAClient, "batch", return_value=[oa_work(authorships=[authorship("OpenAlex author")])]):
                report = refresh_ml.run(base, output, manifest, None)
            row = json.loads((output / "icml/2020/works.jsonl").read_text())
            self.assertEqual(row["authorships"][0]["raw_affiliations"], [])
            self.assertEqual(row["semanticscholar_profile_authorships"][0]["author_id"], "s2:1")
            self.assertEqual(row["semanticscholar_profile_authorships"][0]["profile_affiliations"], ["Current University"])
            self.assertEqual(report["counts"]["profile_affiliations_withheld_from_historical_credit"], 1)

    def test_repeated_cursor_is_a_hard_error(self):
        client = refresh_ml.OAClient(None, 4)
        payload = {"meta": {"count": 2, "next_cursor": "repeat"}, "results": [oa_work()]}
        with patch.object(client, "_get", side_effect=[payload, payload]):
            with self.assertRaisesRegex(refresh_ml.RefreshError, "repeated cursor"):
                client.batch(["10.1234/paper"])

    def test_pagination_can_return_multiple_records_for_one_doi(self):
        client = refresh_ml.OAClient(None, 4)
        first = {"meta": {"count": 2, "next_cursor": "page-2"}, "results": [oa_work(ident="W1")]}
        second = {"meta": {"count": 2, "next_cursor": None}, "results": [oa_work(ident="W2", authorships=[authorship(raw=["Institute"])])]}
        with patch.object(client, "_get", side_effect=[first, second]) as get:
            results = client.batch(["10.1234/paper"])
        candidates = refresh_ml.candidate_sets(results)["10.1234/paper"]
        self.assertEqual(len(candidates), 2)
        self.assertEqual(get.call_count, 2)
        self.assertIn("openalex_duplicate_doi_byline_conflict", refresh_ml.conflict_flags([refresh_ml.trim_openalex(r) for r in candidates]))

    def test_truncated_authorships_hydrate_by_singleton_and_verify_doi_and_id(self):
        client = refresh_ml.OAClient(None, 1)
        truncated = oa_work(authorships=[authorship()], authors_count=101)
        full = oa_work(authorships=[authorship(f"Author {n}") for n in range(101)], authors_count=101)
        with patch.object(client, "singleton", return_value=full) as singleton:
            result = refresh_ml.work_to_openalex(truncated, client)
        singleton.assert_called_once_with("W1")
        self.assertEqual(len(result["authorships"]), 101)
        self.assertTrue(result["authors_hydrated"])

        bad = dict(full, doi="https://doi.org/10.1234/other")
        with patch.object(client, "singleton", return_value=bad):
            with self.assertRaisesRegex(refresh_ml.RefreshError, "DOI mismatch"):
                refresh_ml.hydrate(truncated, client)


if __name__ == "__main__":
    unittest.main()
