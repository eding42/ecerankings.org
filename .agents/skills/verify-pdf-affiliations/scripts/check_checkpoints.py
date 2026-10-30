"""Read-only checkpoint validation; no model calls or affiliation judging."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
VERDICTS = {"correct", "wrong", "missing", "absent", "not_found", "unclear"}


def validate(saved, task, batch_name, model):
    if not isinstance(saved, dict):
        raise ValueError("checkpoint must be an object")
    if saved.get("batch") != batch_name or saved.get("model") != model:
        raise ValueError("checkpoint assignment does not match")
    if saved.get("task") != task:
        raise ValueError("saved task differs from immutable task list")
    result = saved.get("result")
    if not isinstance(result, dict) or result.get("task_id") != task["task_id"]:
        raise ValueError("invalid result identity")
    if type(result.get("image_ok")) is not bool:
        raise ValueError("image_ok must be a boolean")
    authors = result.get("authors")
    if not isinstance(authors, list) or not all(isinstance(a, dict) for a in authors):
        raise ValueError("authors must be a list of objects")
    if any(type(a.get("index")) is not int for a in authors):
        raise ValueError("author indexes must be integers")
    if [a["index"] for a in authors] != list(range(len(task["authors"]))):
        raise ValueError("author indexes do not cover the original byline")
    if [a.get("name") for a in authors] != task["authors"]:
        raise ValueError("author names or order differ from original byline")
    for i, author in enumerate(authors):
        verdict, affiliations = author.get("verdict"), author.get("page_affiliations")
        if verdict not in VERDICTS or not isinstance(affiliations, list):
            raise ValueError("invalid verdict or affiliation list")
        if not all(isinstance(s, str) and s.strip() for s in affiliations):
            raise ValueError("affiliations must be nonempty strings")
        if verdict in {"absent", "not_found", "unclear"} and affiliations:
            raise ValueError("unresolved/absent verdict must have empty affiliations")
        if verdict in {"correct", "wrong", "missing"} and not affiliations:
            raise ValueError("resolved verdict must include page affiliations")
        if verdict == "missing" and task["extracted"][i]:
            raise ValueError("missing requires an empty parser extraction")
        if not result["image_ok"] and verdict != "unclear":
            raise ValueError("unusable image requires unclear verdicts")
        if "raw_marks" in author and not isinstance(author["raw_marks"], str):
            raise ValueError("raw_marks must be a string")
    if not isinstance(result.get("notes"), str):
        raise ValueError("notes must be a string")


def check_checkpoints(directory):
    output = Path(directory)
    run = json.loads((output / "run.json").read_text(encoding="utf8"))
    batch_path = Path(run["batch"])
    if not batch_path.is_absolute():
        batch_path = ROOT / batch_path
    raw = batch_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != run["batch_sha256"]:
        raise ValueError("immutable task list hash changed")
    tasks = json.loads(raw)["tasks"]
    completed = slots = 0
    next_task = None
    for position, task in enumerate(tasks, 1):
        target = output / f"paper-{position:04d}.json"
        try:
            saved = json.loads(target.read_text(encoding="utf8"))
            validate(saved, task, batch_path.name, run["model"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            if next_task is None:
                next_task = {"position": position, "output_file": str(target),
                             "task": task, "validation_error": str(error)}
        else:
            completed += 1
            slots += len(task["authors"])
    summary = {"state": "done" if next_task is None else "work",
               "papers_saved": completed, "papers_expected": len(tasks),
               "author_slots_saved": slots,
               "author_slots_expected": sum(len(t["authors"]) for t in tasks),
               "affiliation_accuracy_checked": False}
    if next_task:
        summary.update(next_task)
    return summary


if __name__ == "__main__":
    print(json.dumps(check_checkpoints(sys.argv[1]), ensure_ascii=False, indent=2))
