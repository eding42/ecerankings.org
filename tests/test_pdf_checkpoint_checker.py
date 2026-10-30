import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".agents/skills/verify-pdf-affiliations/scripts/check_checkpoints.py"
SPEC = importlib.util.spec_from_file_location("pdf_checkpoint_checker", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class Checkpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        self.task = {"task_id": "pilot:1", "authors": ["First", "Second"], "extracted": [[], ["Example"]]}
        self.batch = self.out / "batch.json"
        raw = json.dumps({"tasks": [self.task]}).encode()
        self.batch.write_bytes(raw)
        self.run = {"batch": str(self.batch), "batch_sha256": hashlib.sha256(raw).hexdigest(), "model": "test-model"}
        (self.out / "run.json").write_text(json.dumps(self.run))
        self.saved = {"batch": self.batch.name, "model": "test-model", "task": self.task,
                      "result": {"task_id": "pilot:1", "image_ok": True, "notes": "",
                                 "authors": [{"index": i, "name": name, "verdict": "unclear", "page_affiliations": []}
                                             for i, name in enumerate(self.task["authors"])]}}

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, obj=None):
        (self.out / "paper-0001.json").write_text(json.dumps(self.saved if obj is None else obj))

    def check(self):
        return checker.check_checkpoints(self.out)

    def test_missing_checkpoint_is_next_work(self):
        result = self.check()
        self.assertEqual((result["state"], result["position"], result["papers_saved"]), ("work", 1, 0))

    def test_complete_unclear_checkpoint_is_not_accuracy_proof(self):
        self.save()
        result = self.check()
        self.assertEqual((result["state"], result["author_slots_saved"]), ("done", 2))
        self.assertFalse(result["affiliation_accuracy_checked"])

    def test_incomplete_or_reordered_bylines_remain_work(self):
        self.saved["result"]["authors"].reverse()
        self.save()
        self.assertEqual(self.check()["state"], "work")
        self.saved["result"]["authors"].pop()
        self.save()
        self.assertEqual(self.check()["state"], "work")

    def test_malformed_json_or_nonobject_checkpoint_remains_work(self):
        (self.out / "paper-0001.json").write_text("{broken")
        self.assertEqual(self.check()["state"], "work")
        self.save([])
        self.assertEqual(self.check()["state"], "work")

    def test_changed_task_list_cannot_reuse_old_checkpoints(self):
        self.save()
        self.batch.write_text(json.dumps({"tasks": []}))
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.check()

    def test_missing_verdict_cannot_hide_nonempty_parser_value(self):
        author = self.saved["result"]["authors"][1]
        author.update(verdict="missing", page_affiliations=["Another institution"])
        self.save()
        self.assertEqual(self.check()["state"], "work")


if __name__ == "__main__":
    unittest.main()
