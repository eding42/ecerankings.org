import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import harvest_ml

LISTING = """<ul class="paper-list">
<li class="conference" data-track="conference"><div class="paper-content">
<a title="paper title" href="/paper_files/paper/2025/hash/aaa111-Abstract-Conference.html">Generalization of GFlowNets</a>
<span class="paper-authors">Tiago Silva, Pierluca D&amp;#x27;Oro, John Smith, Jr.</span></div></li>
<li class="position" data-track="position"><div class="paper-content">
<a title="paper title" href="/paper_files/paper/2025/hash/bbb222-Abstract-Position_Paper_Track.html">A Position</a>
<span class="paper-authors">Ada Lovelace</span></div></li>
<li class="nav-item"><a href="/other">nav</a></li>
</ul>"""

BIB = r"""
@Proceedings{ICML2025,
  booktitle = {Proceedings of the 42nd International Conference on Machine Learning},
  volume = 267
}
@InProceedings{pmlr-v267-aamand25a,
  title = {Lightweight {P}rotocols for {\"O}rder},
  author = {Aamand, Anders and M{\"u}ller, J{\o}rn},
  pages = {27--58},
  pdf = {https://example.org/a.pdf},
  url = {https://proceedings.mlr.press/v267/aamand25a.html},
  abstract = {Uses {nested {braces}} and an email a@b.c.}
}
"""


def member(title="Generalization of GFlowNets", authors=("Tiago Silva", "Amauri Souza"), key="iclr:2025:aaa111",
           track="Conference", doi=None):
    return {"paper_key": key, "membership_id": key.rsplit(":", 1)[1], "membership_url": "https://proceedings.iclr.cc/x.html",
            "pdf_url": "https://proceedings.iclr.cc/x.pdf", "track": track, "title": title, "authors": list(authors),
            "publisher_doi": doi}


def oa_candidate(doi, title="Generalization of GFlowNets", year=2024, names=("Tiago Silva", "Amauri Souza"), inst=True):
    return {"id": "https://openalex.org/W1", "doi": f"https://doi.org/{doi}", "title": title, "publication_year": year,
            "authorships": [{"author_id": f"https://openalex.org/A{i}", "author_name": n,
                             "institutions": [{"id": "https://openalex.org/I1", "display_name": "Aalto", "type": "education"}] if inst else [],
                             "raw_affiliations": ["Aalto University"] if inst else []} for i, n in enumerate(names)]}


class Parsers(unittest.TestCase):
    def test_listing_parses_tracks_authors_and_double_escaped_names(self):
        rows = harvest_ml.parse_listing(LISTING, "https://proceedings.iclr.cc/paper_files/paper/2025", "iclr", 2025)
        self.assertEqual([r["track"] for r in rows], ["Conference", "Position_Paper_Track"])
        self.assertEqual(rows[0]["authors"], ["Tiago Silva", "Pierluca D'Oro", "John Smith, Jr."])
        self.assertEqual(rows[0]["pdf_url"], "https://proceedings.iclr.cc/paper_files/paper/2025/file/aaa111-Paper-Conference.pdf")
        self.assertEqual(rows[0]["paper_key"], "iclr:2025:aaa111")

    def test_pmlr_bib_handles_nested_braces_and_latex(self):
        rows = harvest_ml.parse_pmlr(BIB, "icml", 2025, 267)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Lightweight Protocols for Örder")
        self.assertEqual(rows[0]["authors"], ["Anders Aamand", "Jørn Müller"])
        self.assertEqual(rows[0]["paper_key"], "icml:2025:aamand25a")

    def test_pmlr_rejects_non_icml_volume(self):
        with self.assertRaises(harvest_ml.HarvestError):
            harvest_ml.parse_pmlr(BIB.replace("International Conference on Machine Learning", "Workshop"), "icml", 2025, 267)


class Identity(unittest.TestCase):
    def test_arxiv_year_window(self):
        self.assertTrue(harvest_ml.year_plausible("10.48550/arxiv.2401.1", 2023, 2025))
        self.assertFalse(harvest_ml.year_plausible("10.48550/arxiv.2401.1", 2022, 2025))
        self.assertFalse(harvest_ml.year_plausible("10.52202/085713-0001", 2023, 2025))

    def test_byline_mismatch_rejects_candidate(self):
        ok, _, reasons = harvest_ml.evaluate_candidate(
            member(), "10.48550/arxiv.1", oa_candidate("10.48550/arxiv.1", names=("Someone Else", "Another Person")), 2025)
        self.assertFalse(ok)
        self.assertIn("byline_mismatch", reasons)

    def test_publisher_byline_defines_authors_and_affiliations_attach_by_alignment(self):
        ed = type("E", (), {"venue": "iclr", "year": 2025})()
        doi = "10.48550/arxiv.2401.00001"
        row = harvest_ml.build_row(ed, member(), {"status": "ok", "arxiv_doi": doi, "source": "s2-match"},
                                   {doi: {"candidates": [oa_candidate(doi, names=("T. Silva", "Amauri Souza"))]}})
        self.assertEqual([a["author_name"] for a in row["authorships"]], ["Tiago Silva", "Amauri Souza"])
        self.assertEqual(row["authorships"][0]["affiliation_source"], "openalex-arxiv-doi")
        self.assertIsNone(row["doi"])  # arXiv twins never become the corpus identity
        self.assertEqual(row["publication_year"], 2025)


class Stages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        harvest_ml.EDITIONS[("iclr", 1999)] = {"adapter": "proceedings_listing", "url": "https://proceedings.iclr.cc/paper_files/paper/1999",
                                               "include_tracks": ["Conference"], "s2_venue": None, "expected": [{"count": 1, "scope": "included", "source": "t"}]}
        self.ed = harvest_ml.Edition("iclr", 1999, self.root, harvest_ml.Fetcher(self.root / "raw"), self.root / "no.env")
        self.ed.dir.mkdir(parents=True)
        harvest_ml.atomic_write_lines(self.ed.membership_path, [member(key="iclr:1999:aaa111")])

    def tearDown(self):
        harvest_ml.EDITIONS.pop(("iclr", 1999), None)
        self.tmp.cleanup()

    def test_s2_match_supplies_identifier_only_and_errors_are_retried(self):
        paper = {"paperId": "p1", "title": "Generalization of GFlowNets", "externalIds": {"ArXiv": "2401.00001v2"},
                 "authors": [{"name": "Tiago Silva", "affiliations": ["Profile U"]}, {"name": "Amauri Souza"}]}
        quiet = dict(legacy_index=lambda *a: {}, openalex_title_search=lambda *a: {}, arxiv_title_search=lambda *a: {})
        with patch.multiple(harvest_ml, **quiet), \
             patch.object(harvest_ml.Fetcher, "get_json", side_effect=harvest_ml.HarvestError("boom")):
            harvest_ml.stage_discover(self.ed, s2_match=True)
        self.assertEqual([r for r in harvest_ml.read_jsonl(self.ed.discovery_path)], [])
        self.assertFalse(self.ed.is_done("discover"))
        with patch.multiple(harvest_ml, **quiet), \
             patch.object(harvest_ml.Fetcher, "get_json", return_value=(200, {"data": [paper]})):
            harvest_ml.stage_discover(self.ed, s2_match=True)
        rows = harvest_ml.read_jsonl(self.ed.discovery_path)
        self.assertEqual(rows[0]["arxiv_doi"], "10.48550/arxiv.2401.00001")
        self.assertNotIn("Profile U", json.dumps(rows))
        self.assertTrue(self.ed.is_done("discover"))

    def test_title_search_error_leaves_paper_pending(self):
        with patch.object(harvest_ml, "legacy_index", return_value={}), \
             patch.object(harvest_ml, "openalex_title_search", side_effect=harvest_ml.HarvestError("429")), \
             patch.object(harvest_ml, "arxiv_title_search", return_value={}):
            harvest_ml.stage_discover(self.ed)
        self.assertEqual(harvest_ml.read_jsonl(self.ed.discovery_path), [])
        self.assertFalse(self.ed.is_done("discover"))

    def test_openalex_title_hit_feeds_build_and_foreign_doi_is_rejected(self):
        good = harvest_ml.trim_openalex({"id": "https://openalex.org/W9", "doi": "https://doi.org/10.48550/arxiv.2401.9",
                                         "title": "Generalization of GFlowNets", "publication_year": 1998, "authorships": [
                {"author": {"id": "A1", "display_name": "Tiago Silva"}, "institutions": [{"id": "I1", "display_name": "U", "type": "education"}], "raw_affiliation_strings": ["U"]},
                {"author": {"id": "A2", "display_name": "Amauri Souza"}, "institutions": [], "raw_affiliation_strings": ["V"]}]})
        journal = dict(good, id="https://openalex.org/W8", doi="https://doi.org/10.1000/tmlr.1")
        with patch.object(harvest_ml, "legacy_index", return_value={}), \
             patch.object(harvest_ml, "openalex_title_search", return_value={"iclr:1999:aaa111": [journal, good]}):
            harvest_ml.stage_discover(self.ed)
        self.assertTrue(self.ed.is_done("discover"))
        harvest_ml.stage_build(self.ed)
        row = harvest_ml.read_jsonl(self.ed.works_path)[0]
        self.assertEqual(row["evidence"]["openalex_id"], "https://openalex.org/W9")
        self.assertIn("foreign_doi", row["evidence"]["rejected"][0]["reasons"])
        self.assertEqual(row["authorships"][1]["raw_affiliations"], ["V"])
        gates = harvest_ml.compute_gates(self.ed, [row])
        self.assertTrue(gates["paper_specific_affiliations"]["pass"])
        self.assertFalse(gates["institution_resolution"]["pass"])

    def test_enrich_resume_skips_queried_dois_and_failed_batch_is_not_negative(self):
        harvest_ml.append_jsonl(self.ed.discovery_path, {"paper_key": "iclr:1999:aaa111", "status": "ok", "arxiv_doi": "10.48550/arxiv.1"})
        with patch.object(harvest_ml.OAClient, "batch", side_effect=harvest_ml.RefreshError("429")):
            harvest_ml.stage_enrich(self.ed, None, 5)
        self.assertEqual(harvest_ml.read_jsonl(self.ed.openalex_path), [])
        self.assertFalse(self.ed.is_done("enrich"))
        cand = oa_candidate("10.48550/arxiv.1", year=1999)
        with patch.object(harvest_ml.OAClient, "batch", return_value=[{**cand, "authorships": [
                {"author": {"id": "A1", "display_name": "Tiago Silva"}, "institutions": [], "raw_affiliation_strings": ["X"]}]}]) as batch:
            harvest_ml.stage_enrich(self.ed, None, 5)
            harvest_ml.stage_enrich(self.ed, None, 5)
        self.assertEqual(batch.call_count, 1)
        self.assertEqual(harvest_ml.read_jsonl(self.ed.openalex_path)[0]["key"], "10.48550/arxiv.1")

    def test_gates_fail_below_threshold_and_status_stays_staged(self):
        harvest_ml.stage_build(self.ed)
        gates, passed = harvest_ml.stage_gates(self.ed)
        self.assertTrue(gates["membership"]["pass"])
        self.assertFalse(gates["paper_specific_affiliations"]["pass"])
        self.assertFalse(passed)
        row = harvest_ml.write_manifest(self.root / "m.json", self.ed, {})
        self.assertEqual(row["status"], "staged")

    def test_challenge_403_is_fatal(self):
        err = harvest_ml.urllib.error.HTTPError("https://api2.openreview.net/notes", 403, "Forbidden", {},
                                                 __import__("io").BytesIO(b'{"name":"ChallengeRequiredError"}'))
        with patch.object(harvest_ml.urllib.request, "urlopen", side_effect=err), self.assertRaises(harvest_ml.ChallengeError):
            harvest_ml.Fetcher(self.root / "raw").get("https://api2.openreview.net/notes")


class PdfStage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        harvest_ml.EDITIONS[("iclr", 1999)] = {"adapter": "proceedings_listing", "url": "https://proceedings.iclr.cc/x",
                                               "include_tracks": ["Conference"], "s2_venue": None, "expected": []}
        self.ed = harvest_ml.Edition("iclr", 1999, self.root, harvest_ml.Fetcher(self.root / "raw"), self.root / "no.env")
        self.ed.dir.mkdir(parents=True)
        harvest_ml.atomic_write_lines(self.ed.membership_path, [member(key="iclr:1999:aaa111")])
        self.ed.pdf_dir.mkdir(parents=True)
        (self.ed.pdf_dir / "aaa111.pdf").write_bytes(b"%PDF-1.5 fake")
        self.text = ("Generalization of GFlowNets\n\n Tiago Silva           Amauri Souza\n"
                     " Aalto University      Federal Institute of Ceara\n t@aalto.fi            a@ifce.edu.br\n\n\n"
                     "        A BSTRACT\n")

    def tearDown(self):
        harvest_ml.EDITIONS.pop(("iclr", 1999), None)
        self.tmp.cleanup()

    def run_pdf(self, **kw):
        with patch.object(harvest_ml.pdf_affiliations, "first_page_text", return_value=self.text):
            return harvest_ml.stage_pdf(self.ed, workers=1, **kw)

    def test_local_pdf_is_extracted_text_kept_and_high_confidence_pdf_deleted(self):
        counts = self.run_pdf()
        self.assertEqual(counts["confidence:high"], 1)
        self.assertTrue((self.ed.pdf_text_dir / "aaa111.txt").exists())
        self.assertFalse((self.ed.pdf_dir / "aaa111.pdf").exists())
        self.assertTrue(self.ed.is_done("pdf"))
        # Re-running needs neither the PDF nor the network.
        self.assertEqual(self.run_pdf(offline=True)["already_fetched"], 1)

    def test_build_fills_empty_slots_from_pdf_and_flags_conflicts(self):
        self.run_pdf()
        harvest_ml.append_jsonl(self.ed.discovery_path, {"paper_key": "iclr:1999:aaa111", "status": "ok",
                                                         "arxiv_doi": "10.48550/arxiv.1"})
        cand = oa_candidate("10.48550/arxiv.1", year=1999)
        cand["authorships"][1]["institutions"], cand["authorships"][1]["raw_affiliations"] = [], []
        harvest_ml.append_jsonl(self.ed.openalex_path, {"key": "10.48550/arxiv.1", "status": "ok", "candidates": [cand]})
        harvest_ml.stage_build(self.ed)
        row = harvest_ml.read_jsonl(self.ed.works_path)[0]
        first, second = row["authorships"]
        self.assertEqual(first["affiliation_source"], "publisher-pdf")        # PDF first by default
        self.assertEqual(second["affiliation_source"], "publisher-pdf")
        self.assertEqual(second["raw_affiliations"], ["Federal Institute of Ceara"])
        self.assertEqual(second["institutions"], [])
        self.assertFalse(row["evidence"].get("pdf_openalex_conflicts"))       # Aalto == Aalto
        self.ed.prefer_pdf = False                                            # --prefer-openalex
        self.assertFalse(self.ed.is_done("build"))                            # flag change invalidates build
        harvest_ml.stage_build(self.ed)
        first, second = harvest_ml.read_jsonl(self.ed.works_path)[0]["authorships"]
        self.assertEqual(first["affiliation_source"], "openalex-arxiv-doi")
        self.assertEqual(second["affiliation_source"], "publisher-pdf")       # PDF still fills the gap

    def test_partial_extraction_is_queued_not_credited(self):
        self.text = self.text.replace("Amauri Souza", "Someone Else")
        counts = self.run_pdf()
        self.assertEqual(counts["review_queue"], 1)
        self.assertTrue((self.ed.pdf_dir / "aaa111.pdf").exists())          # kept for review
        harvest_ml.stage_build(self.ed)
        row = harvest_ml.read_jsonl(self.ed.works_path)[0]
        self.assertFalse(any(a.get("affiliation_source") == "publisher-pdf" for a in row["authorships"]))
        self.assertFalse(row["evidence"]["pdf"]["credited"])

    def test_download_failure_is_retried_not_negative(self):
        (self.ed.pdf_dir / "aaa111.pdf").unlink()
        with patch.object(harvest_ml, "download_pdf", side_effect=harvest_ml.HarvestError("HTTP 503")):
            counts = harvest_ml.stage_pdf(self.ed, workers=1)
        self.assertEqual(counts["fetch_errors"], 1)
        self.assertFalse(self.ed.is_done("pdf"))
        self.assertEqual(harvest_ml.read_jsonl(self.ed.pdf_extract_path), [])


if __name__ == "__main__":
    unittest.main()
