import csv
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pipeline import normalize_affiliations_local as local


def write_works(cache_root, venue, year, affiliations):
    path = Path(cache_root) / venue / str(year) / "works.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    works = [{"authorships": [{"raw_affiliations": [raw]}]} for raw in affiliations]
    path.write_text("".join(json.dumps(work) + "\n" for work in works))


def load_semantic_without_optional_dependencies():
    """Load the collector/CLI module without importing ML runtime packages."""
    fake_numpy = types.ModuleType("numpy")
    fake_torch = types.ModuleType("torch")
    false = types.SimpleNamespace(is_available=lambda: False)
    fake_torch.backends = types.SimpleNamespace(mps=false)
    fake_torch.cuda = false
    fake_sentence_transformers = types.ModuleType("sentence_transformers")
    fake_sentence_transformers.SentenceTransformer = object
    stubs = {
        "numpy": fake_numpy,
        "torch": fake_torch,
        "sentence_transformers": fake_sentence_transformers,
    }
    path = Path(__file__).resolve().parents[1] / "pipeline" / "normalize_semantic.py"
    spec = importlib.util.spec_from_file_location("normalize_semantic_test_module", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    module.torch = fake_torch
    return module


class StagedCacheNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.stage = self.root / "stage-cache"
        self.live = self.root / "live-cache"
        self.map_path = self.root / "affiliation-map.csv"
        self.db_path = self.root / "institutions.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_cli_reads_only_selected_staged_venue_year_and_preserves_manual_row(self):
        write_works(self.stage, "iclr", 2025,
                    ["Example University", "Adjudicated Institute"])
        write_works(self.stage, "iclr", 2024, ["Wrong year affiliation"])
        write_works(self.stage, "other", 2025, ["Wrong venue affiliation"])
        write_works(self.live, "iclr", 2025, ["Live cache decoy"])

        manual = {
            "raw_affiliation": "Adjudicated Institute", "status": "manual",
            "institution_id": "https://openalex.org/I2", "institution_name": "Adjudicated Institute",
            "institution_type": "education", "country_code": "US",
            "lineage": "https://openalex.org/I2", "score": "1.000",
            "matched_via": "human adjudication", "candidate": "Adjudicated Institute",
        }
        with self.map_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=local.MAP_FIELDS)
            writer.writeheader()
            writer.writerow(manual)
        index = {
            "by_name": {"example university": "https://openalex.org/I1"},
            "by_id": {"https://openalex.org/I1": {
                "id": "https://openalex.org/I1", "display_name": "Example University",
                "type": "education", "country_code": "US", "lineage": ["https://openalex.org/I1"],
            }},
        }
        self.db_path.write_text(json.dumps(index))

        argv = ["normalize_affiliations_local.py", "--cache-dir", str(self.stage),
                "--venue", "iclr", "--year", "2025"]
        with patch.object(local, "CACHE_DIR", str(self.live)), \
             patch.object(local, "MAP_CSV", str(self.map_path)), \
             patch.object(local, "INST_DB", str(self.db_path)), \
             patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            local.main()

        with self.map_path.open(newline="") as f:
            rows = {row["raw_affiliation"]: row for row in csv.DictReader(f)}
        self.assertEqual(set(rows), {"Example University", "Adjudicated Institute"})
        self.assertEqual(rows["Example University"]["institution_id"], "https://openalex.org/I1")
        self.assertEqual(rows["Example University"]["status"], "auto")
        self.assertEqual(rows["Adjudicated Institute"], manual)
        self.assertEqual(set(rows["Example University"]), set(local.MAP_FIELDS))

    def test_semantic_cli_reads_selected_staged_cache_without_ml_runtime(self):
        semantic = load_semantic_without_optional_dependencies()
        write_works(self.stage, "iclr", 2025, ["Staged affiliation"])
        write_works(self.stage, "iclr", 2024, ["Wrong year affiliation"])
        write_works(self.live, "iclr", 2025, ["Live cache decoy"])
        argv = ["normalize_semantic.py", "--cache-dir", str(self.stage),
                "--venue", "iclr", "--year", "2025", "--report-only"]
        collect = semantic.collect_raw_affiliations
        with patch.object(semantic, "CACHE_DIR", str(self.live)), \
             patch.object(semantic, "SentenceTransformer", return_value=object()), \
             patch.object(semantic, "load_inst_db", return_value={}), \
             patch.object(semantic, "build_inst_index", return_value=(None, [], {}, [])), \
             patch.object(semantic, "load_map", return_value={}), \
             patch.object(semantic, "collect_raw_affiliations", wraps=collect) as collect_mock, \
             patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
            semantic.main()
        collect_mock.assert_called_once_with("iclr", 2025, str(self.stage))


if __name__ == "__main__":
    unittest.main()
