#!/usr/bin/env python3
"""Image verification of PDF-extracted affiliations: the mechanical stages.

The `verify-pdf-affiliations` skill is the only way verification runs. The
agent the user is talking to is the entry point: it asks the user which
subagent model to use and how much to run, fans batches out to the
`pdf-affiliation-verifier` subagent (.claude/agents/), and writes the result
files. It runs on the user's Claude Code subscription, with no API key and no
headless processes. This module does only what must be deterministic:

  prep     choose papers (review / conflict / sample), render each author
           block to PNG (page top to the Abstract heading, located with
           pdftotext -bbox-layout) plus a full-page context image, write
           batches named by content hash
  status   pending batches with their task kinds, for the skill to show the
           user before asking
  apply    validate every result (one per task, byline-aligned, known
           verdicts) and write pdf-verify.jsonl for build and gates
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ".agents/skills/verify-pdf-affiliations/SKILL.md"
DEFAULT_BATCH = 15
DEFAULT_SAMPLE = 200
RENDER_DPI = 300
VERDICTS = ("correct", "wrong", "missing", "absent", "not_found", "unclear")

class VerifyError(RuntimeError):
    pass


def _read_jsonl(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf8")
    os.replace(tmp, path)


def paths(ed):
    base = ed.dir / "pdf-verify"
    return {"base": base, "img": base / "img", "batches": base / "batches", "results": base / "results",
            "tasks": base / "tasks.jsonl", "out": ed.dir / "pdf-verify.jsonl"}


# --------------------------------------------------------------------------
# verify-prep

def abstract_cut(pdf_path):
    """(page_width_pt, page_height_pt, y_pt of the Abstract heading or None)."""
    out = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "-bbox-layout", str(pdf_path), "-"],
                         capture_output=True, timeout=60).stdout.decode("utf8", "replace")
    page = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', out)
    if not page:
        return None, None, None
    width, height = float(page.group(1)), float(page.group(2))
    # Small caps render "Abstract" as "A" + "BSTRACT"; take the first word that
    # completes it, below the top tenth of the page (skips running headers).
    for m in re.finditer(r'<word xMin="[\d.]+" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]+)</word>', out):
        y, word = float(m.group(1)), m.group(2).strip().upper()
        if word in ("ABSTRACT", "BSTRACT", "ABSTRACT:") and y > height * 0.1:
            return width, height, y
    return width, height, None


def render_crop(pdf_path, png_path, dpi=RENDER_DPI):
    """Render page 1 from the top to just below the Abstract heading."""
    width, height, cut = abstract_cut(pdf_path)
    if width is None:
        raise VerifyError(f"cannot read page geometry: {pdf_path}")
    bottom = (cut + 14) if cut else height * 0.55
    scale = dpi / 72.0
    png_path.parent.mkdir(parents=True, exist_ok=True)
    stem = png_path.with_suffix("")
    subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(dpi), "-png", "-singlefile",
                    "-x", "0", "-y", "0", "-W", str(int(width * scale)), "-H", str(int(bottom * scale)),
                    str(pdf_path), str(stem)], check=True, capture_output=True, timeout=120)
    return {"crop_to_abstract": cut is not None, "height_px": int(bottom * scale)}


def render_context(pdf_path, png_path, dpi=RENDER_DPI):
    """Render the complete first PDF page at the verification render resolution."""
    png_path.parent.mkdir(parents=True, exist_ok=True)
    stem = png_path.with_suffix("")
    subprocess.run(["pdftoppm", "-f", "1", "-l", "1", "-r", str(dpi), "-png", "-singlefile",
                    str(pdf_path), str(stem)], check=True, capture_output=True, timeout=120)
    return {"dpi": dpi}


def _path_label(path):
    path = Path(path)
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def select_tasks(ed, works, extracts, sample_size):
    """Deterministic task list: review, conflict, then hash-ordered sample."""
    by_key = {m["paper_key"]: m for m in ed.included()}
    chosen = {}
    for key, ext in extracts.items():
        if key in by_key and ext.get("confidence") != "high":
            chosen.setdefault(key, "review")
    for w in works:
        if w["evidence"].get("pdf_openalex_conflicts"):
            chosen.setdefault(w["id"], "conflict")
    high = sorted((k for k, e in extracts.items() if k in by_key and e.get("confidence") == "high" and k not in chosen),
                  key=lambda k: hashlib.sha256(k.encode()).hexdigest())
    for key in high[:sample_size]:
        chosen[key] = "sample"
    order = {"review": 0, "conflict": 1, "sample": 2}
    return [(key, kind, by_key[key]) for key, kind in sorted(chosen.items(), key=lambda kv: (order[kv[1]], kv[0]))]


def prep(ed, works, sample_size=DEFAULT_SAMPLE, batch_size=DEFAULT_BATCH, workers=4, download=None, keep_pdfs=False,
         limit=None):
    p = paths(ed)
    extracts = {r["paper_key"]: r for r in _read_jsonl(ed.pdf_extract_path)}
    tasks = select_tasks(ed, works, extracts, sample_size)
    if limit:
        tasks = tasks[:limit]
    counts = Counter(kind for _, kind, _ in tasks)

    def one(item):
        key, kind, member = item
        # Reuse requires both rendered views. A crop alone can omit affiliation
        # footnotes at the bottom of page one.
        png = p["img"] / f"{member['membership_id']}-{RENDER_DPI}dpi.png"
        context_png = p["img"] / f"{member['membership_id']}-{RENDER_DPI}dpi-context.png"
        if png.exists() and context_png.exists():
            return key, kind, member, png, context_png, None
        pdf = ed.pdf_dir / f"{member['membership_id']}.pdf"
        fetched = False
        if not pdf.exists():
            if download is None:
                raise VerifyError(f"PDF not on disk for {key}")
            body = download(member["pdf_url"])
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(body)
            fetched = True
        info = render_crop(pdf, png)
        render_context(pdf, context_png)
        # PDFs fetched only to render a sample/conflict crop are not kept.
        if fetched and not keep_pdfs and kind != "review":
            pdf.unlink()
        return key, kind, member, png, context_png, info

    rendered, errors = [], []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for item, fut in [(t, pool.submit(one, t)) for t in tasks]:
            try:
                rendered.append(fut.result())
            except Exception as exc:  # one bad PDF must not stop the batch
                errors.append({"paper_key": item[0], "error": str(exc)[:200]})
    task_rows = []
    for key, kind, member, png, context_png, info in rendered:
        ext = extracts.get(key) or {}
        pdf = ed.pdf_dir / f"{member['membership_id']}.pdf"
        task_rows.append({"task_id": key, "kind": kind, "title": member["title"], "image": _path_label(png),
                          "context_image": _path_label(context_png), "pdf_path": _path_label(pdf),
                          "pdf_url": member.get("pdf_url"),
                          "authors": member["authors"],
                          "extracted": ext.get("affiliations") or [[] for _ in member["authors"]],
                          "crop_to_abstract": (info or {}).get("crop_to_abstract")})
    p["base"].mkdir(parents=True, exist_ok=True)
    with p["tasks"].open("w", encoding="utf8") as handle:
        for row in task_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    if p["batches"].exists():
        shutil.rmtree(p["batches"])
    for n in range(0, len(task_rows), batch_size):
        chunk = task_rows[n:n + batch_size]
        body = [{k: t[k] for k in ("task_id", "title", "image", "context_image", "pdf_path", "pdf_url",
                                   "authors", "extracted")} for t in chunk]
        # Named by content, so a re-prep never mistakes an old result for a new batch.
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:10]
        _write_json(p["batches"] / f"batch-{n // batch_size + 1:04d}-{digest}.json",
                    {"batch": n // batch_size + 1, "tasks": body})
    counts["tasks"] = len(task_rows)
    counts["batches"] = -(-len(task_rows) // batch_size) if task_rows else 0
    counts["render_errors"] = len(errors)
    counts["crops_without_abstract_anchor"] = sum(1 for t in task_rows if t["crop_to_abstract"] is False)
    if errors:
        _write_json(p["base"] / "prep-errors.json", errors)
    return counts


# --------------------------------------------------------------------------
# status

def pending_batches(ed):
    p = paths(ed)
    done = {f.name for f in p["results"].glob("batch-*.json")} if p["results"].exists() else set()
    return sorted(b for b in p["batches"].glob("batch-*.json") if b.name not in done) if p["batches"].exists() else []


def status(ed):
    """Pending batches with task counts by kind; what the skill shows the user."""
    kinds = {t["task_id"]: t["kind"] for t in _read_jsonl(paths(ed)["tasks"])}
    batches = []
    for path in pending_batches(ed):
        tasks = json.loads(path.read_text(encoding="utf8"))["tasks"]
        batches.append({"batch": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                        "images": len(tasks), "kinds": dict(Counter(kinds.get(t["task_id"], "?") for t in tasks))})
    total = Counter()
    for b in batches:
        total.update(b["kinds"])
    return {"pending_batches": len(batches), "pending_images": sum(b["images"] for b in batches),
            "by_kind": dict(total), "batches": batches}


# --------------------------------------------------------------------------
# verify-apply

def apply(ed):
    p = paths(ed)
    tasks = {t["task_id"]: t for t in _read_jsonl(p["tasks"])}
    current_batches = {b.name: json.loads(b.read_text(encoding="utf8"))
                      for b in p["batches"].glob("batch-*.json")} if p["batches"].exists() else {}
    rows, problems = {}, []
    counts = Counter()
    for result_file in sorted(p["results"].glob("batch-*.json")) if p["results"].exists() else []:
        if result_file.name.endswith(".raw.json"):
            continue
        batch = current_batches.get(result_file.name)
        if batch is None:
            problems.append({"file": result_file.name, "error": "stale or unknown batch identity"})
            continue
        try:
            data = json.loads(result_file.read_text(encoding="utf8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append({"file": result_file.name, "error": f"invalid result JSON: {exc}"})
            continue
        batch_problems = []
        if not isinstance(data, dict) or data.get("batch") != result_file.name:
            batch_problems.append({"file": result_file.name, "error": "result batch name does not match current batch"})
        if not isinstance(data, dict) or not isinstance(data.get("model"), str) or not data["model"].strip():
            batch_problems.append({"file": result_file.name, "error": "missing or invalid result model"})
        assigned = batch.get("tasks") or []
        assigned_by_id = {t.get("task_id"): t for t in assigned}
        expected_ids = set(assigned_by_id)
        if (len(expected_ids) != len(assigned) or
                any(task_id not in tasks for task_id in expected_ids)):
            problems.append({"file": result_file.name, "error": "current batch has duplicate or unknown assigned task IDs"})
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            batch_problems.append({"file": result_file.name, "error": "results must be a list"})
            results = []
        seen = set()
        accepted = []
        for res in results:
            if not isinstance(res, dict):
                batch_problems.append({"file": result_file.name, "error": "result entry must be an object"})
                continue
            task_id = res.get("task_id")
            if task_id not in expected_ids:
                batch_problems.append({"file": result_file.name, "task_id": task_id,
                                       "error": "unknown task for current batch"})
                continue
            if task_id in seen:
                batch_problems.append({"file": result_file.name, "task_id": task_id,
                                       "error": "duplicate task result"})
                continue
            seen.add(task_id)
            task = assigned_by_id[task_id]
            expected_task = tasks.get(task_id)
            authors = res.get("authors")
            if not isinstance(authors, list) or len(authors) != len(task.get("authors", [])):
                batch_problems.append({"file": result_file.name, "task_id": task_id,
                                       "error": f"author count does not match byline of {len(task.get('authors', []))}"})
                continue
            author_error = None
            for i, (author, expected_name) in enumerate(zip(authors, task["authors"])):
                if not isinstance(author, dict) or type(author.get("index")) is not int or author.get("index") != i:
                    author_error = "author indexes or order do not match the assigned byline"
                    break
                if author.get("name") != expected_name:
                    author_error = "author names or order do not match the assigned byline"
                    break
                if author.get("verdict") not in VERDICTS:
                    author_error = "unknown verdict"
                    break
                affiliations = author.get("page_affiliations")
                if not isinstance(affiliations, list) or any(not isinstance(s, str) or not s.strip() for s in affiliations):
                    author_error = "page_affiliations must be a list of nonempty strings"
                    break
                if "raw_marks" in author and not isinstance(author["raw_marks"], str):
                    author_error = "raw_marks must be a string when provided"
                    break
            if author_error:
                batch_problems.append({"file": result_file.name, "task_id": task_id, "error": author_error})
                continue
            if type(res.get("image_ok")) is not bool:
                batch_problems.append({"file": result_file.name, "task_id": task_id,
                                       "error": "image_ok must be a boolean"})
                continue
            if not isinstance(res.get("notes", ""), str):
                batch_problems.append({"file": result_file.name, "task_id": task_id,
                                       "error": "notes must be a string"})
                continue
            accepted.append((task, res, authors, expected_task))
        missing_ids = expected_ids - seen
        for task_id in sorted(missing_ids):
            batch_problems.append({"file": result_file.name, "task_id": task_id,
                                   "error": "missing task result"})
        if batch_problems:
            problems.extend(batch_problems)
            continue  # batch-level atomicity: never accept a partial batch
        for task, res, authors, expected_task in accepted:
            rows[task["task_id"]] = {
                "paper_key": task["task_id"], "kind": expected_task["kind"], "model": data.get("model"),
                "image_ok": res["image_ok"], "notes": res.get("notes") or "",
                "authors": [{"verdict": a["verdict"],
                             "page_affiliations": [s.strip() for s in a.get("page_affiliations") or [] if isinstance(s, str) and s.strip()]}
                            for a in authors]}
    for row in rows.values():
        counts[f"papers:{row['kind']}"] += 1
        for a in row["authors"]:
            counts[f"{row['kind']}:{a['verdict']}"] += 1
    counts["papers_verified"] = len(rows)
    counts["tasks"] = len(tasks)
    counts["problems"] = len(problems)
    with p["out"].open("w", encoding="utf8") as handle:
        for key in sorted(rows):
            handle.write(json.dumps(rows[key], ensure_ascii=False) + "\n")
    if problems:
        _write_json(p["base"] / "apply-problems.json", problems)
    return counts, rows


def sample_accuracy(rows):
    """Extractor accuracy on the high-confidence sample, by author slot.

    Denominator: slots where the extractor produced a value and the image was
    readable (correct + wrong); `missing` cannot occur for credited papers,
    `unclear`/`not_found` say nothing about the extractor.
    """
    correct = wrong = 0
    for row in rows.values():
        if row["kind"] != "sample" or not row["image_ok"]:
            continue
        for a in row["authors"]:
            correct += a["verdict"] == "correct"
            wrong += a["verdict"] in ("wrong", "missing")
    total = correct + wrong
    return (correct / total if total else None), correct, wrong
