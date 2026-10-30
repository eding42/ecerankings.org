import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

from pipeline import refresh_openalex as r


def work(wid="W1", doi="https://doi.org/10.1/example", *, raw=None, trunc=False, authors_count=1):
    return {"id": "https://openalex.org/" + wid, "doi": doi, "title": wid,
            "publication_year": 2024, "type": "article", "authors_count": authors_count,
            "is_authors_truncated": trunc,
            "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "A One"},
                             "institutions": [], "raw_affiliation_strings": raw or []}]}


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = os.path.join(self.tmp.name, "cache")
        self.manifest = {}
        self.venue = {"key": "j", "kind": "journal", "openalex_ids": ["S1"]}

    def test_command_help_runs_without_repository_on_pythonpath(self):
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        result = subprocess.run([sys.executable, r.__file__, '--help'], cwd=self.tmp.name,
                                env=env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--out-cache', result.stdout)

    def test_concurrent_writers_cannot_share_cache_or_manifest(self):
        manifest = os.path.join(self.tmp.name, 'manifest.json')
        with r.exclusive_run_lock(self.out, manifest):
            with self.assertRaisesRegex(r.RefreshError, 'Another journal refresh'):
                with r.exclusive_run_lock(self.out, manifest + '.other'):
                    self.fail('Same cache must have one writer')
            with self.assertRaisesRegex(r.RefreshError, 'Another journal refresh'):
                with r.exclusive_run_lock(self.out + '-other', manifest):
                    self.fail('Same manifest must have one writer')
        # Closing the owning process's handles releases both locks.
        with r.exclusive_run_lock(self.out, manifest):
            pass

    def test_changed_stage_is_rejected_before_publication(self):
        def get(path, params):
            return {'meta': {'count': 1, 'next_cursor': None}, 'results': [work()]}
        with mock.patch.object(r, 'read_stage', return_value=[]):
            with self.assertRaisesRegex(r.RefreshError, 'Staged row count differs'):
                r.harvest_year('j', self.venue, 2024, self.out, self.manifest, get, {'requests': 0})
        self.assertFalse(os.path.exists(os.path.join(self.out, 'j', '2024', 'works.jsonl')))

    def test_transport_failure_is_distinct_from_a_missing_source(self):
        get, state = r.make_client('test-key', 20, 10)
        with mock.patch.object(r.urllib.request, 'urlopen', side_effect=urllib.error.URLError('DNS unavailable')):
            with mock.patch.object(r.time, 'sleep'):
                with self.assertRaises(r.NetworkUnavailable):
                    get('/works', {'filter': 'primary_location.source.id:S1'})
        self.assertEqual(state['list_calls'], 4)

    def test_complete_pagination_dedup_and_raw_affiliations(self):
        first = work("W1", raw=["One Lab"])
        richer = work("W2", raw=["One Lab", "Dept"])
        other = work("W3", doi="https://doi.org/10.1/other")
        def get(path, params):
            if params["cursor"] == "*":
                return {"meta": {"count": 3, "next_cursor": "next"}, "results": [first, other]}
            return {"meta": {"count": 3, "next_cursor": None}, "results": [richer]}
        rec = r.harvest_year("j", self.venue, 2024, self.out, self.manifest, get, {"requests": 0})
        self.assertEqual((rec["api_results"], rec["unique_works"]), (3, 2))
        with open(os.path.join(self.out, "j", "2024", "works.jsonl")) as f:
            rows = [json.loads(x) for x in f]
        by_doi = {r["doi"]: r for r in rows}
        self.assertEqual(by_doi["https://doi.org/10.1/example"]["id"], "https://openalex.org/W2")
        self.assertEqual(by_doi["https://doi.org/10.1/example"]["authorships"][0]["raw_affiliations"], ["One Lab", "Dept"])
        self.assertEqual(by_doi["https://doi.org/10.1/example"]["source"], "openalex")
        self.assertEqual(rec["query"]["per-page"], 200)

    def test_author_truncation_hydrates_singleton_work(self):
        truncated = work("W1", trunc=True, authors_count=2)
        full = dict(truncated, is_authors_truncated=False,
                    authorships=truncated["authorships"] + [{"author": {"id": "A2", "display_name": "B Two"},
                                                             "institutions": [], "raw_affiliation_strings": ["B Lab"]}])
        calls = []
        state = {"requests": 0, "list_calls": 0, "singleton_calls": 0, "retries": 0}
        def get(path, params):
            calls.append(path)
            state["requests"] += 1
            state["list_calls" if path == "/works" else "singleton_calls"] += 1
            if path == "/works":
                return {"meta": {"count": 1, "next_cursor": None}, "results": [truncated]}
            return full
        rec = r.harvest_year("j", self.venue, 2024, self.out, self.manifest, get, state)
        with open(os.path.join(self.out, "j", "2024", "works.jsonl")) as f:
            row = json.loads(f.readline())
        self.assertEqual(rec["unique_works"], 1)
        self.assertEqual(len(row["authorships"]), 2)
        self.assertEqual(calls, ["/works", "/works/W1"])
        self.assertEqual(rec["singleton_attempts"], 1)
        self.assertEqual(rec["list_call_attempts"], 1)

    def test_singleton_hydration_rejects_missing_or_different_doi(self):
        listed = work("W1", trunc=True)
        wrong = dict(listed, doi=None)
        def get(path, params):
            return ({"meta": {"count": 1, "next_cursor": None}, "results": [listed]}
                    if path == "/works" else wrong)
        with self.assertRaisesRegex(r.RefreshError, "DOI mismatch"):
            r.harvest_year("j", self.venue, 2024, self.out, self.manifest, get, {"requests": 0})

    def test_100_authorships_without_flags_hydrates_and_validates_identity(self):
        auths = [{"author": {"id": f"A{i}", "display_name": f"Author {i}"},
                  "institutions": [], "raw_affiliation_strings": []} for i in range(100)]
        listed = {"id": "https://openalex.org/W100", "doi": "https://doi.org/10.2/full.",
                  "title": "Large collaboration", "publication_year": 2024, "type": "article",
                  "authorships": auths}
        full = dict(listed, authorships=auths + [{"author": {"id": "A100", "display_name": "Author 100"},
                                                  "institutions": [], "raw_affiliation_strings": []}])
        calls = []
        def get(path, params):
            calls.append(path)
            return ({"meta": {"count": 1, "next_cursor": None}, "results": [listed]}
                    if path == "/works" else full)
        rec = r.harvest_year("j", self.venue, 2024, self.out, self.manifest, get, {"requests": 0})
        with open(os.path.join(self.out, "j", "2024", "works.jsonl")) as f:
            row = json.loads(f.readline())
        self.assertEqual(calls, ["/works", "/works/W100"])
        self.assertEqual(len(row["authorships"]), 101)
        self.assertTrue(row["authors_hydrated"])
        self.assertEqual(row["doi"], "https://doi.org/10.2/full.")
        self.assertNotIn("authors_count", row)
        self.assertEqual(rec["unique_works"], 1)

    def test_singleton_identity_mismatch_is_rejected(self):
        listed = work("W1", trunc=True)
        wrong = work("W2", trunc=False)
        def get(path, params):
            if path == "/works":
                return {"meta": {"count": 1, "next_cursor": None}, "results": [listed]}
            return wrong
        with self.assertRaisesRegex(r.RefreshError, "different work"):
            r.harvest_year("j", self.venue, 2024, self.out, self.manifest, get, {"requests": 0})

    def test_rehydrate_published_file_repairs_capped_record_atomically(self):
        path = os.path.join(self.out, "j", "2024", "works.jsonl")
        os.makedirs(os.path.dirname(path))
        capped = work("W1", raw=[])
        capped["authorships"] = capped["authorships"] * 100
        original = {**r.trim_work(capped), "provenance": {"checked_at": "earlier"}}
        with open(path, "w") as f:
            f.write(json.dumps(original) + "\n")
        full = dict(capped, authorships=capped["authorships"] + [capped["authorships"][0]])
        def get(pathname, params):
            self.assertEqual(pathname, "/works/W1")
            return full
        result = r.rehydrate_published_file(path, get, "j", 2024)
        self.assertEqual(result["hydrated_count"], 1)
        with open(path) as f:
            row = json.loads(f.readline())
        self.assertEqual(len(row["authorships"]), 101)
        self.assertTrue(row["authors_hydrated"])
        self.assertEqual(row["provenance"], {"checked_at": "earlier"})

    def test_midpage_failure_does_not_publish_partial_and_resumes(self):
        n = {"calls": 0}
        def fail_once(path, params):
            n["calls"] += 1
            if n["calls"] == 1:
                return {"meta": {"count": 2, "next_cursor": "next"}, "results": [work()]}
            raise r.RefreshError("temporary failure")
        with self.assertRaisesRegex(r.RefreshError, "temporary"):
            r.harvest_year("j", self.venue, 2024, self.out, self.manifest, fail_once, {"requests": 0})
        dest = os.path.join(self.out, "j", "2024", "works.jsonl")
        self.assertFalse(os.path.exists(dest))
        # Simulate interruption after writing the next page but before committing
        # its checkpoint; resume must truncate this uncommitted staged row.
        with open(dest + ".partial", "a") as f:
            f.write(json.dumps(work("W-extra", "https://doi.org/10.1/extra")) + "\n")
        def finish(path, params):
            self.assertEqual(params["cursor"], "next")
            return {"meta": {"count": 2, "next_cursor": None},
                    "results": [work("W2", "https://doi.org/10.1/second")]}
        rec = r.harvest_year("j", self.venue, 2024, self.out, self.manifest, finish, {"requests": 0})
        self.assertEqual(rec["api_results"], 2)
        self.assertTrue(os.path.exists(dest))

    def test_crossref_registered_zero_is_logged_and_not_published(self):
        venue = dict(self.venue, years={"2024": {"source": "crossref"}})
        def empty(path, params):
            return {"meta": {"count": 0, "next_cursor": None}, "results": []}
        rec = r.harvest_year("j", venue, 2024, self.out, self.manifest, empty, {"requests": 0})
        self.assertEqual(rec["status"], "skipped_crossref_preserved_openalex_zero")
        self.assertFalse(os.path.exists(os.path.join(self.out, "j", "2024", "works.jsonl")))

    def test_count_drift_restarts_query_before_publishing(self):
        n = {"calls": 0}
        def get(path, params):
            n["calls"] += 1
            count = 2 if n["calls"] == 1 else 1
            return {"meta": {"count": count, "next_cursor": None}, "results": [work()]}
        rec = r.harvest_year("j", self.venue, 2024, self.out, self.manifest, get, {"requests": 0})
        self.assertEqual(n["calls"], 2)
        self.assertEqual(rec["api_reported_count"], 1)
        self.assertEqual(rec["api_results"], 1)


if __name__ == "__main__":
    unittest.main()
