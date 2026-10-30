import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pipeline import adjudication as adj

FIELDS = ["raw_affiliation", "status", "institution_id", "institution_name", "institution_type",
          "country_code", "lineage", "score", "matched_via", "candidate"]
INDEX = {"by_id": {
    "https://openalex.org/I1": {"id": "https://openalex.org/I1", "display_name": "Purdue University West Lafayette",
                                "type": "education", "country_code": "US", "lineage": ["https://openalex.org/I1"],
                                "acronyms": [], "alternatives": ["Purdue University"]},
    "https://openalex.org/I2": {"id": "https://openalex.org/I2", "display_name": "Purdue University Northwest",
                                "type": "education", "country_code": "US", "lineage": ["https://openalex.org/I2"],
                                "acronyms": [], "alternatives": []},
    "https://openalex.org/I3": {"id": "https://openalex.org/I3", "display_name": "Qualcomm (United States)",
                                "type": "company", "country_code": "US", "lineage": ["https://openalex.org/I3"],
                                "acronyms": [], "alternatives": []},
}}


def row(raw, status="review", iid="", name="", itype="", via=""):
    return {"raw_affiliation": raw, "status": status, "institution_id": iid, "institution_name": name,
            "institution_type": itype, "country_code": "", "lineage": "", "score": "0.8", "matched_via": via,
            "candidate": ""}


class Adjudication(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.paths = {"MAP_CSV": d / "map.csv", "INDEX_JSON": d / "index.json", "LEDGER": d / "ledger.jsonl",
                      "TRAPS_CSV": d / "traps.csv", "ROOT": d}
        self.paths["INDEX_JSON"].write_text(json.dumps(INDEX))
        adj.write_map(FIELDS, [row("PURDUE UNIVERSITY", "auto", "https://openalex.org/I2", "Purdue University Northwest", "education", "PURDUE UNIVERSITY"),
                               row("Purdue University", "manual", "https://openalex.org/I1", "Purdue University West Lafayette", "education"),
                               row("Qualcomm Inc, San Diego, CA")], self.paths["MAP_CSV"])
        self.patches = [patch.object(adj, k, v) for k, v in self.paths.items()]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_cmd(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out):
            code = adj.main(list(argv))
        return code, out.getvalue()

    def decisions(self, items):
        path = Path(self.tmp.name) / "decisions.json"
        path.write_text(json.dumps(items))
        return str(path)

    def map_rows(self):
        return {r["raw_affiliation"]: r for r in adj.read_map(self.paths["MAP_CSV"])[1]}

    def test_apply_takes_fields_from_index_and_writes_ledger(self):
        f = self.decisions([{"key": adj.row_key("PURDUE UNIVERSITY"), "raw_affiliation": "PURDUE UNIVERSITY",
                             "decision": "corrected", "institution_id": "I1", "institution_name": "made up",
                             "evidence": "Case variant of Purdue University; flagship campus", "decided_by": "test"}])
        code, _ = self.run_cmd("apply", f)
        self.assertEqual(code, 0)
        r = self.map_rows()["PURDUE UNIVERSITY"]
        self.assertEqual((r["status"], r["institution_name"], r["institution_type"], r["country_code"]),
                         ("manual", "Purdue University West Lafayette", "education", "US"))
        self.assertEqual(r["lineage"], "https://openalex.org/I1")
        self.assertEqual(adj.read_ledger(self.paths["LEDGER"])[0]["evidence"], "Case variant of Purdue University; flagship campus")

    def test_invalid_decisions_are_rejected_without_touching_map(self):
        f = self.decisions([
            {"raw_affiliation": "Qualcomm Inc, San Diego, CA", "decision": "supported", "institution_id": "I3", "evidence": "x"},
            {"raw_affiliation": "Qualcomm Inc, San Diego, CA", "decision": "supported", "institution_id": "I999", "evidence": "x"},
            {"raw_affiliation": "Qualcomm Inc, San Diego, CA", "decision": "noneducation", "evidence": ""},
            {"key": "deadbeef", "raw_affiliation": "Qualcomm Inc, San Diego, CA", "decision": "unresolved", "evidence": "x"},
        ])
        code, out = self.run_cmd("apply", f)
        self.assertEqual(code, 1)
        self.assertIn("type company; use noneducation", out)
        self.assertIn("not in data/institutions.json", out)
        self.assertIn("evidence is required", out)
        self.assertIn("key does not match", out)
        self.assertEqual(self.map_rows()["Qualcomm Inc, San Diego, CA"]["status"], "review")

    def test_manual_rows_need_override_and_replay_restores_clobbered_rows(self):
        f = self.decisions([{"raw_affiliation": "Purdue University", "decision": "corrected", "institution_id": "I2", "evidence": "x"}])
        code, out = self.run_cmd("apply", f)
        self.assertIn("already manual", out)
        f = self.decisions([{"raw_affiliation": "Qualcomm Inc, San Diego, CA", "decision": "noneducation",
                             "institution_id": "I3", "evidence": "Qualcomm is a company; San Diego is its location"}])
        self.assertEqual(self.run_cmd("apply", f)[0], 0)
        fields, rows, _ = adj.read_map(self.paths["MAP_CSV"])
        for r in rows:  # a normalizer rerun clobbers the adjudicated row
            if r["raw_affiliation"].startswith("Qualcomm"):
                r.update(status="auto", institution_id="https://openalex.org/I1", institution_type="education")
        adj.write_map(fields, rows, self.paths["MAP_CSV"])
        code, out = self.run_cmd("replay")
        self.assertIn("rows restored: 1", out)
        r = self.map_rows()["Qualcomm Inc, San Diego, CA"]
        self.assertEqual((r["status"], r["institution_type"]), ("manual", "company"))

    def test_write_refuses_when_another_writer_changed_the_map(self):
        fields, rows, stamp = adj.read_map(self.paths["MAP_CSV"])
        import os, time
        time.sleep(0.01)
        with open(self.paths["MAP_CSV"], "a") as f:   # another process appends a row
            f.write("Other Writer Row,auto,,,,,,,,\n")
        with self.assertRaises(adj.ConcurrentWrite):
            adj.write_map(fields, rows, self.paths["MAP_CSV"], expect_stamp=stamp)
        self.assertIn("Other Writer Row", self.map_rows())

    def test_rejected_only_apply_never_rewrites_the_map(self):
        before = self.paths["MAP_CSV"].stat().st_mtime_ns
        f = self.decisions([{"raw_affiliation": "Qualcomm Inc, San Diego, CA", "decision": "supported",
                             "institution_id": "I999", "evidence": "x"}])
        self.run_cmd("apply", f)
        self.assertEqual(self.paths["MAP_CSV"].stat().st_mtime_ns, before)
        self.assertFalse(self.paths["LEDGER"].exists())

    def test_check_reports_trap_failures_and_variant_splits(self):
        with open(self.paths["TRAPS_CSV"], "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["raw_affiliation", "expect", "why", "absent_ok"])
            w.writerow(["PURDUE UNIVERSITY", "id:I1", "case variant", "yes"])
            w.writerow(["Never seen", "noneducation", "absent is fine", "yes"])
        code, out = self.run_cmd("check", "--show", "5")
        self.assertEqual(code, 1)
        self.assertIn("expected I1, map has I2", out)
        self.assertIn("1 variant groups disagree", out)

    def test_queue_adds_unmapped_cache_strings_sorted_by_credited_share(self):
        cache = Path(self.tmp.name) / "cache" / "iclr" / "2025"
        cache.mkdir(parents=True)
        works = [{"authorships": [{"institutions": [], "raw_affiliations": ["Brand New Lab"]}]},
                 {"authorships": [{"institutions": [], "raw_affiliations": ["Qualcomm Inc, San Diego, CA"]},
                                  {"institutions": [{"id": "I1"}], "raw_affiliations": ["ignored: has institutions"]}]}]
        (cache / "works.jsonl").write_text("\n".join(json.dumps(w) for w in works) + "\n")
        out = Path(self.tmp.name) / "queue"
        self.run_cmd("queue", "--cache-dir", str(cache.parents[1]), "--out", str(out), "--batch", "10")
        rows = json.loads((out / "batch-0001.json").read_text())["rows"]
        self.assertEqual([r["raw_affiliation"] for r in rows], ["Brand New Lab", "Qualcomm Inc, San Diego, CA"])
        self.assertEqual(rows[0]["status"], "unmapped")
        self.assertEqual(rows[0]["key"], adj.row_key("Brand New Lab"))
        self.assertNotIn("ignored: has institutions", json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
