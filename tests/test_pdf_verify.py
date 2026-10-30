import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline import harvest_ml, pdf_verify

BBOX = '''<doc><page width="612.000000" height="792.000000">
<word xMin="100" yMin="40" xMax="200" yMax="50">Published</word>
<word xMin="250" yMin="300" xMax="260" yMax="312">A</word>
<word xMin="262" yMin="300" xMax="320" yMax="312">BSTRACT</word>
</page></doc>'''


def member(key, authors=("Tiago Silva", "Amauri Souza")):
    digest = key.rsplit(":", 1)[1]
    return {"paper_key": key, "membership_id": digest, "membership_url": "https://proceedings.iclr.cc/x.html",
            "pdf_url": f"https://proceedings.iclr.cc/{digest}.pdf", "track": "Conference", "title": f"Paper {digest}",
            "authors": list(authors), "publisher_doi": None}


class Verify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        harvest_ml.EDITIONS[("iclr", 1999)] = {"adapter": "proceedings_listing", "url": "https://x",
                                               "include_tracks": ["Conference"], "s2_venue": None, "expected": []}
        self.ed = harvest_ml.Edition("iclr", 1999, self.root, harvest_ml.Fetcher(self.root / "raw"), self.root / "no.env")
        self.ed.dir.mkdir(parents=True)
        self.members = [member(f"iclr:1999:p{i}") for i in range(6)]
        harvest_ml.atomic_write_lines(self.ed.membership_path, self.members)
        extracts = [{"paper_key": m["paper_key"], "confidence": "partial" if i == 0 else "high",
                     "affiliations": [["Getulio Vargas Foundation"], [] if i == 0 else ["Aalto University"]]}
                    for i, m in enumerate(self.members)]
        harvest_ml.atomic_write_lines(self.ed.pdf_extract_path, extracts)
        self.works = [{"id": m["paper_key"], "evidence": {"pdf_openalex_conflicts": [{"author": "x"}] if i == 1 else []}}
                      for i, m in enumerate(self.members)]

    def tearDown(self):
        harvest_ml.EDITIONS.pop(("iclr", 1999), None)
        self.tmp.cleanup()

    def test_task_selection_is_deterministic_review_conflict_then_sample(self):
        tasks = pdf_verify.select_tasks(self.ed, self.works, {r["paper_key"]: r for r in harvest_ml.read_jsonl(self.ed.pdf_extract_path)}, 2)
        kinds = [(k, kind) for k, kind, _ in tasks]
        self.assertEqual(kinds[0], ("iclr:1999:p0", "review"))
        self.assertEqual(kinds[1], ("iclr:1999:p1", "conflict"))
        self.assertEqual([kind for _, kind in kinds[2:]], ["sample", "sample"])
        again = pdf_verify.select_tasks(self.ed, self.works, {r["paper_key"]: r for r in harvest_ml.read_jsonl(self.ed.pdf_extract_path)}, 2)
        self.assertEqual(tasks, again)

    def test_crop_stops_below_the_abstract_heading(self):
        with patch.object(pdf_verify.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, BBOX.encode(), b"")):
            width, height, cut = pdf_verify.abstract_cut("x.pdf")
        self.assertEqual((width, height, cut), (612.0, 792.0, 300.0))

    def test_context_render_uses_full_first_page_at_render_resolution(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "context.png"
            with patch.object(pdf_verify.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, b"", b"")) as run:
                result = pdf_verify.render_context("paper.pdf", dest, dpi=300)
        args = run.call_args.args[0]
        self.assertIn("-f", args)
        self.assertIn("1", args)
        self.assertIn("-r", args)
        self.assertIn("300", args)
        self.assertNotIn("-x", args)
        self.assertNotIn("-y", args)
        self.assertEqual(result, {"dpi": 300})

    def write_batches(self):
        def render(_pdf, png):
            png.parent.mkdir(parents=True, exist_ok=True)
            png.write_bytes(b"rendered")
            return {"crop_to_abstract": True, "height_px": 10} if "context" not in png.name else {"dpi": 300}
        for m in self.members:
            self.ed.pdf_dir.mkdir(parents=True, exist_ok=True)
            (self.ed.pdf_dir / f"{m['membership_id']}.pdf").write_bytes(b"%PDF")
        with patch.object(pdf_verify, "render_crop", side_effect=render), \
             patch.object(pdf_verify, "render_context", side_effect=render):
            return pdf_verify.prep(self.ed, self.works, sample_size=1, batch_size=2, workers=1)

    def test_status_lists_pending_batches_with_kinds(self):
        counts = self.write_batches()
        self.assertEqual(counts["tasks"], 3)
        st = pdf_verify.status(self.ed)
        self.assertEqual((st["pending_batches"], st["pending_images"]), (2, 3))
        self.assertEqual(st["by_kind"], {"review": 1, "conflict": 1, "sample": 1})

    def test_new_resolution_avoids_old_crops_and_changes_batch_identity(self):
        def render(_pdf, png, **kwargs):
            png.parent.mkdir(parents=True, exist_ok=True)
            png.write_bytes(b"rendered")
            return {"crop_to_abstract": True, "height_px": 10} if "context" not in png.name else {"dpi": kwargs.get("dpi", 300)}

        for m in self.members:
            self.ed.pdf_dir.mkdir(parents=True, exist_ok=True)
            (self.ed.pdf_dir / f"{m['membership_id']}.pdf").write_bytes(b"%PDF")
        with patch.object(pdf_verify, "render_crop", side_effect=render) as renderer, \
             patch.object(pdf_verify, "render_context", side_effect=render) as context_renderer:
            with patch.object(pdf_verify, "RENDER_DPI", 110):
                pdf_verify.prep(self.ed, self.works, sample_size=1, batch_size=2, workers=1)
            old_batches = {p.name for p in pdf_verify.pending_batches(self.ed)}
            self.assertEqual((renderer.call_count, context_renderer.call_count), (3, 3))
            first_batch = json.loads(next(pdf_verify.paths(self.ed)["batches"].glob("batch-*.json")).read_text())
            first_task = first_batch["tasks"][0]
            self.assertIn("context_image", first_task)
            self.assertIn("pdf_path", first_task)
            self.assertIn("pdf_url", first_task)
            self.assertTrue((self.root / first_task["context_image"]).exists())
            with patch.object(pdf_verify, "RENDER_DPI", 300):
                pdf_verify.prep(self.ed, self.works, sample_size=1, batch_size=2, workers=1)
                new_batches = {p.name for p in pdf_verify.pending_batches(self.ed)}
                self.assertEqual((renderer.call_count, context_renderer.call_count), (6, 6))
                self.assertTrue(old_batches.isdisjoint(new_batches))
                pdf_verify.prep(self.ed, self.works, sample_size=1, batch_size=2, workers=1)
                self.assertEqual((renderer.call_count, context_renderer.call_count), (6, 6))  # both cached views resume

    def test_missing_context_cache_forces_both_views_to_be_rebuilt(self):
        self.write_batches()
        rows = pdf_verify._read_jsonl(pdf_verify.paths(self.ed)["tasks"])
        (self.root / rows[0]["context_image"]).unlink()
        def crop_render(_pdf, png):
            png.write_bytes(b"crop")
            return {"crop_to_abstract": True, "height_px": 10}
        def context_render(_pdf, png):
            png.write_bytes(b"context")
            return {"dpi": 300}
        with patch.object(pdf_verify, "render_crop", side_effect=crop_render) as crop, \
             patch.object(pdf_verify, "render_context", side_effect=context_render) as context:
            # Existing PDF files were prepared by write_batches.
            pdf_verify.prep(self.ed, self.works, sample_size=1, batch_size=2, workers=1)
            self.assertEqual(crop.call_count, 1)
            self.assertEqual(context.call_count, 1)

    def test_pdf_provenance_changes_batch_identity_even_when_images_are_cached(self):
        self.write_batches()
        batch_dir = pdf_verify.paths(self.ed)["batches"]
        before = next(x for x in batch_dir.glob("batch-*.json")
                      if any(t["task_id"].endswith("p0") for t in json.loads(x.read_text())["tasks"]))
        changed = self.members[0]
        changed["pdf_url"] = "https://different.example/source.pdf"
        harvest_ml.atomic_write_lines(self.ed.membership_path, self.members)
        pdf_verify.prep(self.ed, self.works, sample_size=1, batch_size=2, workers=1)
        after = next(x for x in batch_dir.glob("batch-*.json")
                     if any(t["task_id"].endswith("p0") for t in json.loads(x.read_text())["tasks"]))
        self.assertNotEqual(before.name, after.name)

    def write_subagent_results(self):
        results = pdf_verify.paths(self.ed)["results"]
        results.mkdir(parents=True, exist_ok=True)
        for batch in pdf_verify.pending_batches(self.ed):
            out = []
            for t in json.loads(batch.read_text())["tasks"]:
                out.append({"task_id": t["task_id"], "image_ok": True, "notes": "", "authors": [
                    {"index": 0, "name": t["authors"][0], "verdict": "correct", "page_affiliations": ["Getulio Vargas Foundation"]},
                    {"index": 1, "name": t["authors"][1], "verdict": "missing" if t["task_id"].endswith("p0") else "wrong",
                     "page_affiliations": ["Federal Institute of Ceará"]}]})
            (results / batch.name).write_text(json.dumps({"batch": batch.name, "model": "claude-haiku-5-5",
                                                          "via": "subagent:pdf-affiliation-verifier", "results": out}))

    def test_apply_and_build_use_page_values(self):
        self.write_batches()
        self.write_subagent_results()
        self.assertEqual(pdf_verify.pending_batches(self.ed), [])           # resumable: nothing left
        counts, rows = pdf_verify.apply(self.ed)
        self.assertEqual(counts["papers_verified"], 3)
        accuracy, correct, wrong = pdf_verify.sample_accuracy(rows)
        self.assertEqual((correct, wrong), (1, 1))
        harvest_ml.stage_build(self.ed)
        built = {w["id"]: w for w in harvest_ml.read_jsonl(self.ed.works_path)}
        review = built["iclr:1999:p0"]["authorships"]
        self.assertEqual(review[1]["raw_affiliations"], ["Federal Institute of Ceará"])   # read from image
        self.assertEqual(review[1]["affiliation_source"], "publisher-pdf-image")
        self.assertEqual(built["iclr:1999:p2"]["authorships"][0]["affiliation_source"], "publisher-pdf")
        gates = harvest_ml.compute_gates(self.ed, list(built.values()))
        self.assertFalse(gates["pdf_verification"]["pass"])                             # 50% < 98%
        self.assertEqual(gates["pdf_verification"]["judge_model"], ["claude-haiku-5-5"])

    def test_no_model_is_ever_invoked_by_the_pipeline(self):
        self.assertFalse(hasattr(pdf_verify, "run"))
        source = Path(pdf_verify.__file__).read_text() + Path(harvest_ml.__file__).read_text()
        self.assertNotIn('"claude", "-p"', source)

    def test_subagent_results_with_full_bylines_apply_cleanly(self):
        self.write_batches()
        batch = sorted(pdf_verify.paths(self.ed)["batches"].glob("batch-*.json"))[0]
        tasks = json.loads(batch.read_text())["tasks"]
        results = pdf_verify.paths(self.ed)["results"]
        results.mkdir(parents=True)
        (results / batch.name).write_text(json.dumps({"batch": batch.name, "model": "claude-haiku-5-5", "via": "subagent",
            "results": [{"task_id": t["task_id"], "image_ok": True, "notes": "",
                         "authors": [{"index": i, "name": n, "verdict": "correct", "page_affiliations": ["X"]}
                                     for i, n in enumerate(t["authors"])]} for t in tasks]}))
        counts, rows = pdf_verify.apply(self.ed)
        self.assertEqual(counts["problems"], 0)
        self.assertEqual(len(rows), len(tasks))
        self.assertNotIn(batch, pdf_verify.pending_batches(self.ed))

    def test_reminder_until_review_queue_and_sample_are_verified(self):
        harvest_ml.atomic_write_lines(self.ed.dir / "pdf-review.jsonl", [{"paper_key": "iclr:1999:p0"}])
        text = harvest_ml.pdf_verification_reminder(self.ed)
        self.assertIn("NEXT REQUIRED STEP", text)
        self.assertIn("verify-pdf-affiliations skill", text)
        self.assertIn("--stage verify-prep", text)                         # nothing prepared yet
        self.write_batches()
        text = harvest_ml.pdf_verification_reminder(self.ed)
        self.assertIn("prepared and pending: 2 batches / 3 images", text)
        self.assertNotIn("--stage verify-prep", text)
        self.write_subagent_results()
        pdf_verify.apply(self.ed)
        self.assertIsNone(harvest_ml.pdf_verification_reminder(self.ed))    # review + sample verified

    def test_apply_rejects_results_that_do_not_cover_the_byline(self):
        self.write_batches()
        results = pdf_verify.paths(self.ed)["results"]
        results.mkdir(parents=True)
        (results / "batch-0001-deadbeef00.json").write_text(json.dumps({"model": "m", "results": [
            {"task_id": "iclr:1999:p0", "image_ok": True, "notes": "",
             "authors": [{"index": 0, "name": "Tiago Silva", "verdict": "correct", "page_affiliations": ["X"]}]}]}))
        counts, rows = pdf_verify.apply(self.ed)
        self.assertEqual(counts["problems"], 1)
        self.assertEqual(rows, {})

    def test_apply_rejects_partial_duplicate_unknown_stale_and_reordered_batches_atomically(self):
        cases = ("partial", "duplicate", "unknown", "stale-name", "wrong-batch-field",
                 "no-model", "wrong-name", "reordered")
        for case in cases:
            with self.subTest(case=case):
                self.write_batches()
                batch_path = sorted(pdf_verify.paths(self.ed)["batches"].glob("batch-*.json"))[0]
                batch = json.loads(batch_path.read_text())
                assigned = batch["tasks"]
                def result(task):
                    return {"task_id": task["task_id"], "image_ok": True, "notes": "", "authors": [
                        {"index": i, "name": name, "verdict": "correct", "page_affiliations": ["X"]}
                        for i, name in enumerate(task["authors"])]}
                results_list = [result(t) for t in assigned]
                result_name = batch_path.name
                if case == "partial":
                    results_list.pop()
                elif case == "duplicate":
                    results_list.append(result(assigned[0]))
                elif case == "unknown":
                    results_list[0]["task_id"] = "iclr:1999:not-in-batch"
                elif case == "wrong-name":
                    results_list[0]["authors"][0]["name"] = "Someone Else"
                elif case == "reordered":
                    results_list[0]["authors"].reverse()
                elif case == "stale-name":
                    result_name = "batch-0001-deadbeef00.json"
                batch_field = result_name if case != "wrong-batch-field" else "batch-0001-stale.json"
                model = "test-model" if case != "no-model" else ""
                results_dir = pdf_verify.paths(self.ed)["results"]
                results_dir.mkdir(parents=True, exist_ok=True)
                (results_dir / result_name).write_text(json.dumps({"batch": batch_field,
                    "model": model, "results": results_list}))
                counts, rows = pdf_verify.apply(self.ed)
                self.assertGreater(counts["problems"], 0)
                self.assertEqual(rows, {})  # never accept part of an invalid batch


if __name__ == "__main__":
    unittest.main()
