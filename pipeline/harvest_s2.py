#!/usr/bin/env python3
"""Extract ICML, NeurIPS, and ICLR papers + author affiliations from a local Semantic Scholar
Datasets snapshot (s2-datasets/papers/*.gz + s2-datasets/authors/*.gz) and
write cache/<venue_key>/<year>/works.jsonl in the same envelope used by
harvest_crossref.py.

ICML, NeurIPS, and ICLR have no reliable OpenAlex/Crossref harvest paths, 
so this is a one-off bulk alternative: the S2 "papers" dataset has no per-venue filter, 
so we stream all 60 shards and match on exact venue strings. 

Usage:
    python3 pipeline/harvest_s2.py
"""

import gzip
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAPERS_DIR = os.path.join(REPO_ROOT, "s2-datasets", "papers")
AUTHORS_DIR = os.path.join(REPO_ROOT, "s2-datasets", "authors")

TARGET_VENUES = {
    "International Conference on Machine Learning": "icml",
    "Neural Information Processing Systems": "neurips",
    "International Conference on Learning Representations": "iclr"
}

def find_shards(d):
    return sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".gz"))

def pass1_find_ml_papers():
    """Stream all papers shards, keep exact-venue matches."""
    papers = []
    author_ids_needed = set()
    shards = find_shards(PAPERS_DIR)
    for si, shard in enumerate(shards, 1):
        n_shard = 0
        with gzip.open(shard, "rt") as f:
            for line in f:
                rec = json.loads(line)
                v = rec.get("venue")
                if not v:
                    continue
                venue_key = None
                if v == "International Conference on Machine Learning":
                    venue_key = "icml"
                elif v == "International Conference on Learning Representations":
                    venue_key = "iclr"
                elif "Neural Information Processing Systems" in v:
                    venue_key = "neurips"
                
                if not venue_key:
                    continue
                n_shard += 1
                authors = rec.get("authors") or []
                for a in authors:
                    aid = a.get("authorId")
                    if aid:
                        author_ids_needed.add(aid)
                papers.append(
                    {
                        "corpusid": rec.get("corpusid"),
                        "doi": (rec.get("externalids") or {}).get("DOI"),
                        "title": rec.get("title"),
                        "year": rec.get("year"),
                        "venue_key": venue_key,
                        "authors": [
                            {"authorId": a.get("authorId"), "name": a.get("name")}
                            for a in authors
                        ],
                    }
                )
        print(f"  [papers {si}/{len(shards)}] {os.path.basename(shard)}: "
              f"+{n_shard} ML papers (total {len(papers)})")
    return papers, author_ids_needed

def pass2_load_affiliations(author_ids_needed):
    """Stream all authors shards, keep only authors referenced by ML papers."""
    affils = {}
    shards = find_shards(AUTHORS_DIR)
    remaining = set(author_ids_needed)
    for si, shard in enumerate(shards, 1):
        if not remaining:
            break
        found_here = 0
        with gzip.open(shard, "rt") as f:
            for line in f:
                rec = json.loads(line)
                aid = rec.get("authorid")
                if aid in remaining:
                    affils[aid] = rec.get("affiliations") or []
                    remaining.discard(aid)
                    found_here += 1
        print(f"  [authors {si}/{len(shards)}] {os.path.basename(shard)}: "
              f"+{found_here} matched ({len(remaining)} still needed)")
    print(f"  {len(affils)}/{len(author_ids_needed)} authors resolved ")
    return affils

def write_cache(papers, affils):
    # Group by venue_key -> year -> papers
    by_venue_year = {}
    for p in papers:
        y = p.get("year")
        v = p.get("venue_key")
        if not y or not v:
            continue
        if v not in by_venue_year:
            by_venue_year[v] = {}
        by_venue_year[v].setdefault(y, []).append(p)

    for venue_key, by_year in by_venue_year.items():
        print(f"\nWriting {venue_key}...")
        for year, year_papers in sorted(by_year.items()):
            year_dir = os.path.join(REPO_ROOT, "cache", venue_key, str(year))
            os.makedirs(year_dir, exist_ok=True)
            out_path = os.path.join(year_dir, "works.jsonl")
            with open(out_path, "w") as f:
                for p in year_papers:
                    authorships = []
                    for a in p["authors"]:
                        aid = a.get("authorId")
                        raw = affils.get(aid, []) if aid else []
                        authorships.append(
                            {
                                "author_id": f"s2:{aid}" if aid else None,
                                "author_name": a.get("name"),
                                "institutions": [],
                                "raw_affiliations": raw,
                            }
                        )
                    envelope = {
                        "id": None,
                        "doi": f"https://doi.org/{p['doi']}" if p.get("doi") else None,
                        "title": p.get("title"),
                        "publication_year": year,
                        "type": "proceedings-article",
                        "source": "semanticscholar",
                        "s2_corpusid": p.get("corpusid"),
                        "authorships": authorships,
                    }
                    f.write(json.dumps(envelope) + "\n")
            print(f"  wrote {len(year_papers)} {venue_key} papers for {year} -> {out_path}")

def main():
    print("Pass 1: scanning papers shards for ML venues...")
    papers, author_ids_needed = pass1_find_ml_papers()
    print(f"\nFound {len(papers)} ML papers, {len(author_ids_needed)} distinct authors\n")

    print("Pass 2: resolving author affiliations...")
    affils = pass2_load_affiliations(author_ids_needed)

    print("\nWriting cache/<venue_key>/<year>/works.jsonl...")
    write_cache(papers, affils)

if __name__ == "__main__":
    main()
