#!/usr/bin/env python3
"""Propose non-research works for exclusion, by semantic similarity of titles.

Usage:
    .venv/bin/python pipeline/detect_editorials.py                    # all venues
    .venv/bin/python pipeline/detect_editorials.py --venue scirobotics
    .venv/bin/python pipeline/detect_editorials.py --threshold 0.05 --limit 500

Writes data/editorial-candidates.csv, sorted most-editorial-first. It PROPOSES
only -- nothing is excluded until a human copies rows into
data/excluded-works.csv, which is what aggregate.py actually reads.

Why this is needed at all
-------------------------
Adjusted count is 1/N per author, so a single-author non-research item is worth
a full 1.0 to its institution -- 4x what an author earns on a 4-author research
paper. In Science Robotics, 66 single-author science-fiction columns ("Astromech
robots in Star Wars", "Pacific Rim and exoskeletons") put one institution at #1
in the venue at double the runner-up.

Why a type filter is not enough
-------------------------------
OpenAlex types all 66 of those columns as `article`, not `editorial`. Filtering
on `type` would have caught none of them.

Why author count is not enough
------------------------------
Single authorship is a PRIOR, not a definition. Information Theory (tit, 8.2%
single-author) and Automatica (6.2%) are theory venues where solo-authored
research is normal and legitimate. Excluding on author count would delete real
papers. So the primary signal is what the title MEANS; author count and the
venue's overall commentary rate only adjust the prior.

Method
------
Embed each candidate title with the same sentence-transformer normalize_semantic
uses, and score it as

    similarity(title, editorial exemplars) - similarity(title, research exemplars)

A positive margin means the title reads more like commentary than like a
research contribution. The two exemplar sets are deliberately concrete rather
than abstract -- "In this issue" separates from "Design of a soft robotic
gripper" far more cleanly than "editorial" separates from "research".
"""

import argparse
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workkey import work_key  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
OUT_CSV = os.path.join(REPO_ROOT, "data", "editorial-candidates.csv")
EXCLUDED_CSV = os.path.join(REPO_ROOT, "data", "excluded-works.csv")
MODEL_NAME = "all-MiniLM-L6-v2"      # same model as normalize_semantic.py

EDITORIAL_EXEMPLARS = [
    "Editorial: the year ahead in robotics",
    "In this issue",
    "Introducing a new section of the journal",
    "News and Views: a promising step forward",
    "Comment on the state of the field",
    "A tribute to a pioneering researcher",
    "Obituary",
    "Book review",
    "Erratum",
    "Correction to a previously published article",
    "Reply to the authors",
    "Letter to the editor",
    "Meet the new editorial board",
    "Robots in science fiction",
    "What Star Wars teaches us about robotics",
    "The uncanny valley on television",
    "Reflections on a decade of progress",
    "Conference report and highlights",
    "Interview with a leading roboticist",
    "The road ahead for the field",
]

RESEARCH_EXEMPLARS = [
    "Design and control of a soft robotic gripper for delicate manipulation",
    "A 65 nm CMOS low-noise amplifier for 5G receivers",
    "Deep reinforcement learning for quadrupedal locomotion over rough terrain",
    "On the capacity of the Gaussian multiple-access channel",
    "A novel silicon photonic modulator with 100 GHz bandwidth",
    "Robust model predictive control of nonlinear systems with constraints",
    "Sparse recovery guarantees for compressed sensing measurements",
    "An efficient FPGA accelerator for convolutional neural networks",
    "Thermal characterization of GaN high-electron-mobility transistors",
    "Distributed optimization for multi-agent consensus under delays",
    "A wideband dual-polarized antenna array for millimeter-wave systems",
    "Experimental demonstration of quantum error correction on a superconducting processor",
]

# Cheap prefilter. Embedding 554K titles is wasteful when the overwhelming
# majority are unambiguous research papers; these are the shapes worth scoring.
NONRESEARCH_TYPES = {"editorial", "erratum", "letter", "book-review", "peer-review"}
TITLE_HINTS = re.compile(
    r"\b(editorial|erratum|corrigendum|correction|obituary|in memoriam|book review|"
    r"news and views|in this issue|reply|comment on|tribute|interview|retraction)\b",
    re.I,
)


def strip_markup(title):
    return re.sub(r"<[^>]+>", "", title or "").strip()


def collect_candidates(venue_filter):
    """Prefilter to works plausibly non-research. Returns list of dicts."""
    out = []
    pattern = os.path.join(CACHE_DIR, venue_filter or "*", "*", "works.jsonl")
    for path in sorted(glob.glob(pattern)):
        parts = path.split(os.sep)
        venue, year = parts[-3], parts[-2]
        with open(path) as fh:
            for line in fh:
                try:
                    w = json.loads(line)
                except json.JSONDecodeError:
                    continue
                title = strip_markup(w.get("title"))
                if not title:
                    continue
                authorships = w.get("authorships") or []
                n_authors = len(authorships)
                wtype = (w.get("type") or "").lower()
                if not (n_authors <= 2
                        or wtype in NONRESEARCH_TYPES
                        or TITLE_HINTS.search(title)):
                    continue
                # only worth proposing if it would actually earn credit
                credited = any(i.get("type") == "education"
                               for a in authorships
                               for i in (a.get("institutions") or []))
                if not credited:
                    continue
                out.append({
                    "work_key": work_key(w, venue, year),
                    "venue": venue,
                    "year": year,
                    "title": title,
                    "n_authors": n_authors,
                    "type": w.get("type") or "",
                })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", help="restrict to one venue key")
    ap.add_argument("--threshold", type=float, default=0.0,
                    help="minimum editorial-minus-research margin to report (default 0.0)")
    ap.add_argument("--limit", type=int, default=1000,
                    help="max rows to write (default 1000)")
    args = ap.parse_args()

    try:
        from sentence_transformers import SentenceTransformer
        import torch
    except ImportError:
        sys.exit("sentence-transformers not available. Run with .venv/bin/python "
                 "(see CLAUDE.md: .venv is reserved for the semantic scripts).")

    print("Scanning cache for candidate non-research works...")
    cands = collect_candidates(args.venue)
    print(f"  {len(cands):,} candidates passed the prefilter")
    if not cands:
        return

    already = set()
    if os.path.exists(EXCLUDED_CSV):
        with open(EXCLUDED_CSV) as fh:
            already = {r["work_key"] for r in csv.DictReader(fh)}
    if already:
        before = len(cands)
        cands = [c for c in cands if c["work_key"] not in already]
        print(f"  {before - len(cands):,} already in excluded-works.csv, skipping")

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Loading model '{MODEL_NAME}' on {device} ...")
    model = SentenceTransformer(MODEL_NAME, device=device)

    ed = model.encode(EDITORIAL_EXEMPLARS, normalize_embeddings=True)
    rs = model.encode(RESEARCH_EXEMPLARS, normalize_embeddings=True)
    titles = model.encode([c["title"] for c in cands],
                          normalize_embeddings=True, batch_size=256,
                          show_progress_bar=True)

    # Max similarity to any exemplar, rather than to a centroid: commentary is a
    # grab-bag of unrelated shapes (an obituary and a Star Wars column share no
    # vocabulary), so averaging them into one vector blurs both away.
    ed_sim = (titles @ ed.T).max(axis=1)
    rs_sim = (titles @ rs.T).max(axis=1)

    for c, e, r in zip(cands, ed_sim, rs_sim):
        c["editorial_sim"] = round(float(e), 4)
        c["research_sim"] = round(float(r), 4)
        c["margin"] = round(float(e - r), 4)

    keep = sorted((c for c in cands if c["margin"] >= args.threshold),
                  key=lambda c: -c["margin"])[:args.limit]

    hdr = ["work_key", "venue", "year", "title", "n_authors", "type",
           "editorial_sim", "research_sim", "margin"]
    with open(OUT_CSV, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=hdr)
        w.writeheader()
        for c in keep:
            w.writerow({k: c[k] for k in hdr})

    print(f"\nWrote {len(keep):,} proposals -> {os.path.relpath(OUT_CSV, REPO_ROOT)}")
    print("\nTop 15 by margin:")
    for c in keep[:15]:
        print(f"  {c['margin']:+.3f}  [{c['venue']}/{c['year']}, {c['n_authors']}a] "
              f"{c['title'][:64]}")
    print("\nNOTHING IS EXCLUDED YET. Review the file, then copy accepted rows")
    print("into data/excluded-works.csv (adding reason/decided_by/decided_on)")
    print("— that is the file aggregate.py reads.")


if __name__ == "__main__":
    main()
