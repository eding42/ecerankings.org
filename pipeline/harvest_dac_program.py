#!/usr/bin/env python3
"""Harvest DAC 2026 research papers from the official conference program PDF.

Fallback harvester for DAC 2026 when publisher (ACM DL / Crossref) deposits
are partial or lagged. Parses verified 'Research Manuscript' presentations,
extracts title, authors, and exact publication-time affiliations, and merges
them with existing staged works.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
PROGRAM_URL = "https://confcats-siteplex.s3.amazonaws.com/dac/images/dac-2026_program_july-22.pdf"
DEFAULT_PDF = ROOT / "cache/dac/2026/program.pdf"
DEFAULT_WORKS = ROOT / "cache/dac/2026/works.jsonl"


def normalize_title(title: str) -> str:
    """Normalize paper title for robust deduplication."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def parse_authors(authors_str: str) -> List[Dict[str, Any]]:
    """Parse author string in format: 'Author 1, Affil 1; Author 2, Affil 2; ...'

    Handles multiple affiliations per author separated by semicolons.
    """
    chunks = [c.strip() for c in (authors_str or "").split(";") if c.strip()]
    authors: List[Dict[str, Any]] = []
    for chunk in chunks:
        if "," in chunk:
            name, affil = chunk.split(",", 1)
            name = name.strip()
            affil = affil.strip()
            authors.append({
                "author_id": None,
                "author_name": name,
                "institutions": [],
                "raw_affiliations": [affil] if affil else [],
            })
        else:
            if authors:
                authors[-1]["raw_affiliations"].append(chunk)
            else:
                authors.append({
                    "author_id": None,
                    "author_name": chunk,
                    "institutions": [],
                    "raw_affiliations": [],
                })
    return authors


def parse_program_text(text: str) -> List[Dict[str, Any]]:
    """Extract Research Manuscript papers from pdftotext -layout output."""
    parts = re.split(r"Session Type:\s*([^\n]+)", text)
    papers: List[Dict[str, Any]] = []

    for i in range(1, len(parts), 2):
        stype = parts[i].strip()
        if stype != "Research Manuscript":
            continue

        content = parts[i + 1]
        pattern = re.compile(
            r"^\s*•\s+(.*?)(?=\n\s*•|\n\s*Session Type:|\Z)",
            re.DOTALL | re.MULTILINE,
        )

        for m in pattern.findall(content):
            lines = [l.strip() for l in m.strip().split("\n") if l.strip()]
            o_idx = -1
            for idx, l in enumerate(lines):
                if l.startswith("o ") or l.startswith("o\t"):
                    o_idx = idx
                    break

            if o_idx > 0:
                title = " ".join(lines[:o_idx])
                authors_str = " ".join(lines[o_idx:]).lstrip("o ").strip()
                norm_t = normalize_title(title)
                if len(norm_t) < 5 or norm_t.startswith("full program"):
                    continue

                papers.append({
                    "title": title,
                    "norm_title": norm_t,
                    "authors": parse_authors(authors_str),
                })

    return papers


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Run pdftotext -layout on the program PDF."""
    cmd = ["pdftotext", "-layout", str(pdf_path), "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return proc.stdout.decode("utf-8", errors="ignore")


def merge_program_papers(
    existing_works: List[Dict[str, Any]],
    program_papers: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Merge program papers into existing works, skipping duplicates.

    Returns: (merged_works, existing_matched_count, newly_added_count)
    """
    staged_by_norm = {}
    for w in existing_works:
        nt = normalize_title(w.get("title", ""))
        if nt:
            staged_by_norm[nt] = w

    merged = list(existing_works)
    matched_count = 0
    added_count = 0

    for p in program_papers:
        nt = p["norm_title"]
        # Match if exact or 35-char prefix matches
        found = False
        if nt in staged_by_norm:
            found = True
        else:
            for s_nt in staged_by_norm:
                if len(s_nt) >= 20 and (nt[:35] in s_nt or s_nt[:35] in nt):
                    found = True
                    break

        if found:
            matched_count += 1
        else:
            added_count += 1
            new_work = {
                "id": None,
                "doi": None,
                "title": p["title"],
                "publication_year": 2026,
                "crossref_issued_year": 2026,
                "type": "proceedings-article",
                "source": "dac-program",
                "authorships": p["authors"],
            }
            merged.append(new_work)
            staged_by_norm[nt] = new_work

    return merged, matched_count, added_count


def harvest_dac(
    pdf_path: Path = DEFAULT_PDF,
    works_path: Path = DEFAULT_WORKS,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute DAC 2026 harvesting from program PDF."""
    if not pdf_path.exists():
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading DAC 2026 program PDF from {PROGRAM_URL}...")
        req = urllib.request.Request(PROGRAM_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(pdf_path, "wb") as f:
            shutil.copyfileobj(resp, f)

    print(f"Extracting text from {pdf_path}...")
    text = extract_text_from_pdf(pdf_path)
    program_papers = parse_program_text(text)
    print(f"Found {len(program_papers)} Research Manuscript papers in program.")

    existing_works = []
    if works_path.exists():
        with open(works_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    existing_works.append(json.loads(line))

    print(f"Existing works in {works_path}: {len(existing_works)}")

    merged, matched, added = merge_program_papers(existing_works, program_papers)
    print(f"Matched {matched} papers to existing staged records.")
    print(f"Adding {added} missing Research Manuscripts from program.")
    print(f"Total merged DAC 2026 works: {len(merged)}")

    if not dry_run:
        bak_path = works_path.with_suffix(".jsonl.bak")
        if works_path.exists():
            shutil.copyfile(works_path, bak_path)
            print(f"Created backup at {bak_path}")

        with open(works_path, "w", encoding="utf-8") as f:
            for w in merged:
                f.write(json.dumps(w, ensure_ascii=False) + "\n")
        print(f"Successfully wrote {len(merged)} works to {works_path}")

    return {
        "existing_count": len(existing_works),
        "program_count": len(program_papers),
        "matched_count": matched,
        "added_count": added,
        "total_merged": len(merged),
    }


def main():
    parser = argparse.ArgumentParser(description="Harvest DAC 2026 program papers")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF, help="Path to DAC 2026 program PDF")
    parser.add_argument("--works", type=Path, default=DEFAULT_WORKS, help="Path to works.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without modifying works.jsonl")
    args = parser.parse_args()

    harvest_dac(args.pdf, args.works, args.dry_run)


if __name__ == "__main__":
    main()
