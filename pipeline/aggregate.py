#!/usr/bin/env python3
"""Aggregate harvested works into (institution, area, year) adjusted counts.

Usage:
    python3 pipeline/aggregate.py --venue iedm
    python3 pipeline/aggregate.py --venue iedm --year 2022
    python3 pipeline/aggregate.py --all-cached
    python3 pipeline/aggregate.py --all-cached --sequential

Processes venues in parallel by default (one worker per CPU core).
Use --sequential to disable and run single-threaded.

Reads cache/<venue_key>/<year>/works.jsonl (produced by harvest.py or
harvest_crossref.py), maps each venue to its area via data/areas.json, and
computes CSRankings-style adjusted counts: each paper is worth 1.0, split
evenly across its credited authors. Only authorship-institution pairs with
type == "education" are credited (drops industry/government/nonprofit/
facility affiliations).

Rewrites the full site/data/*.csv output from every cached year each run
(not an incremental merge) -- at current data volumes (hundreds of works
per venue-year) this stays cheap; --year narrows which cached years are
read, for inspecting or spot-checking one year's contribution, but the
output CSVs still cover whatever's in cache, not just that one year.

Institution identity: an author's institution is credited AS OpenAlex
reports it directly (its own id/display_name), with NO lineage rollup to a
parent institution. This is a deliberate, documented limitation, not an
oversight -- see "Known limitation: lineage rollup" below.

Known limitation: lineage rollup
---------------------------------
OpenAlex's per-institution `lineage` field is NOT consistently ordered.
Verified directly against canonical /institutions/{id} records:
  - "National Institutes of Applied Research" (government, Taiwan):
    lineage = [parent_id, self_id]           <- root-first, self-last
  - "TSMC (United States)" (company):
    lineage = [self_id, parent_id]           <- self-first, root-last
Both are real OpenAlex records; there is no reliable positional rule for
"which element is the root." A wrong guess would silently misattribute a
paper to the wrong institution, which is worse than not rolling up at all.

Empirically (checked on the IEDM 2022 pilot, 229 works): 126 of 133 distinct
education-type institutions already have lineage length 1 (they ARE the
root -- e.g. universities are mostly registered at top level in OpenAlex).
Only ~5% (7 institutions in the pilot) have lineage length > 1. Those are
credited under their own (unrolled) id/name and logged below at the end of
each run under "Nested institutions (not rolled up)" for manual review.
A real fix requires resolving each ambiguous id's OWN canonical record
(confirming which candidate has lineage == [itself]) before rollup -- left
for a future pass once this is worth the extra API calls at full scale.

Known limitation: multi-institution authors
---------------------------------------------
When one author lists multiple education institutions on a single paper
(e.g. a joint appointment), this script splits that author's 1/N paper
share evenly across all of them. This is a provisional policy, not a
settled decision -- flag to the user before relying on it for real
rankings. See SPLIT_MULTI_INSTITUTION below to check how often it happens.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import cpu_count

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
SITE_DATA_DIR = os.path.join(REPO_ROOT, "site", "data")

CREDIT_TYPES = {"education"}


def load_registry():
    with open(AREAS_JSON) as f:
        return json.load(f)


def venue_to_area(registry):
    mapping = {}
    for area_key, area in registry["areas"].items():
        for venue in area["venues"]:
            mapping[venue["key"]] = (area_key, area["name"])
    return mapping


def find_cached_venues():
    if not os.path.isdir(CACHE_DIR):
        return []
    found = []
    for venue_key in sorted(os.listdir(CACHE_DIR)):
        venue_dir = os.path.join(CACHE_DIR, venue_key)
        if os.path.isdir(venue_dir) and find_cached_years(venue_key):
            found.append(venue_key)
    return found


MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")


def load_affiliation_map():
    """Load affiliation-map.csv into {raw_affiliation: row}."""
    mapping = {}
    if not os.path.exists(MAP_CSV):
        print(f"  Warning: {MAP_CSV} not found — Crossref-only venues contribute nothing.", file=sys.stderr)
        return mapping
    with open(MAP_CSV, newline="") as f:
        for r in csv.DictReader(f):
            mapping[r["raw_affiliation"]] = r
    return mapping


def resolve_raw_affiliations(raw_affils, affil_map):
    """Resolve Crossref free-text affiliations via the map. Returns list of (id, name, type) tuples."""
    seen = set()
    resolved = []
    for raw in raw_affils:
        row = affil_map.get(raw)
        if not row:
            continue
        inst_id = row.get("institution_id", "")
        if not inst_id or row.get("status") not in ("auto", "manual"):
            continue
        if inst_id in seen:
            continue
        seen.add(inst_id)
        resolved.append({
            "id": inst_id,
            "display_name": row.get("institution_name", ""),
            "type": row.get("institution_type", ""),
        })
    return resolved


def find_cached_years(venue_key):
    venue_dir = os.path.join(CACHE_DIR, venue_key)
    if not os.path.isdir(venue_dir):
        return []
    years = []
    for entry in sorted(os.listdir(venue_dir)):
        if entry.isdigit() and os.path.exists(os.path.join(venue_dir, entry, "works.jsonl")):
            years.append(int(entry))
    return years


def process_venues(venue_keys, v2a, year_filter, affil_map):
    """Process a list of venue keys and return accumulated results.

    Returns: (inst_area_year, author_area_year_inst, inst_names, author_names,
              metrics, nested_institutions)
    """
    inst_area_year = {}
    author_area_year_inst = defaultdict(float)
    inst_names = {}
    author_names = {}

    total_works = 0
    total_authorship_pairs = 0
    dropped_no_edu_inst = 0
    crossref_resolved = 0
    multi_inst_author_events = 0
    nested_institutions = {}

    for venue_key in venue_keys:
        if venue_key not in v2a:
            print(f"  [{venue_key}] not in data/areas.json, skipping.", file=sys.stderr)
            continue
        area_key, _area_name = v2a[venue_key]
        cached_years = find_cached_years(venue_key)
        if year_filter is not None:
            cached_years = [y for y in cached_years if y == year_filter]
        if not cached_years:
            print(f"  [{venue_key}] no cached years match, skipping.", file=sys.stderr)
            continue

        for year_dir in cached_years:
            path = os.path.join(CACHE_DIR, venue_key, str(year_dir), "works.jsonl")
            with open(path) as f:
                for line in f:
                    w = json.loads(line)
                    total_works += 1
                    year = w["publication_year"]
                    authorships = w.get("authorships", [])
                    n_authors = len(authorships)
                    if n_authors == 0:
                        continue
                    paper_weight = 1.0 / n_authors
                    papers_credited_insts_this_work = set()

                    for a in authorships:
                        total_authorship_pairs += 1
                        insts = a.get("institutions") or []
                        edu_insts = [i for i in insts if i.get("type") in CREDIT_TYPES]

                        if not edu_insts and not insts:
                            raw = a.get("raw_affiliations") or []
                            resolved = resolve_raw_affiliations(raw, affil_map)
                            edu_insts = [i for i in resolved if i.get("type") in CREDIT_TYPES]
                            if edu_insts:
                                crossref_resolved += 1

                        if not edu_insts:
                            dropped_no_edu_inst += 1
                            continue
                        if len(edu_insts) > 1:
                            multi_inst_author_events += 1
                        share = paper_weight / len(edu_insts)

                        for inst in edu_insts:
                            inst_id = inst["id"]
                            inst_names[inst_id] = inst["display_name"]
                            lineage = inst.get("lineage") or [inst_id]
                            if len(lineage) > 1 and inst_id not in nested_institutions:
                                nested_institutions[inst_id] = (inst["display_name"], lineage)

                            key = (inst_id, area_key, year)
                            if key not in inst_area_year:
                                inst_area_year[key] = {"pub_count": 0, "adjusted_count": 0.0}
                            inst_area_year[key]["adjusted_count"] += share
                            papers_credited_insts_this_work.add(key)

                            author_id = a["author_id"]
                            author_names[author_id] = a["author_name"]
                            author_area_year_inst[(author_id, area_key, year, inst_id)] += share

                    for key in papers_credited_insts_this_work:
                        inst_area_year[key]["pub_count"] += 1

    metrics = (total_works, total_authorship_pairs, dropped_no_edu_inst,
               crossref_resolved, multi_inst_author_events)
    return inst_area_year, dict(author_area_year_inst), inst_names, author_names, metrics, nested_institutions


def merge_results(results):
    """Merge results from parallel workers into single accumulators."""
    inst_area_year = {}
    author_area_year_inst = defaultdict(float)
    inst_names = {}
    author_names = {}
    total_works = 0
    total_authorship_pairs = 0
    dropped_no_edu_inst = 0
    crossref_resolved = 0
    multi_inst_author_events = 0
    nested_institutions = {}

    for (r_inst_area_year, r_author_ay, r_inst_names, r_author_names,
         metrics, r_nested) in results:
        for key, vals in r_inst_area_year.items():
            if key not in inst_area_year:
                inst_area_year[key] = {"pub_count": 0, "adjusted_count": 0.0}
            inst_area_year[key]["pub_count"] += vals["pub_count"]
            inst_area_year[key]["adjusted_count"] += vals["adjusted_count"]

        for key, val in r_author_ay.items():
            author_area_year_inst[key] += val

        inst_names.update(r_inst_names)
        author_names.update(r_author_names)

        tw, tap, dne, cr, mie = metrics
        total_works += tw
        total_authorship_pairs += tap
        dropped_no_edu_inst += dne
        crossref_resolved += cr
        multi_inst_author_events += mie

        for inst_id, val in r_nested.items():
            if inst_id not in nested_institutions:
                nested_institutions[inst_id] = val

    return (inst_area_year, author_area_year_inst, inst_names, author_names,
            total_works, total_authorship_pairs, dropped_no_edu_inst,
            crossref_resolved, multi_inst_author_events, nested_institutions)


def main():
    parser = argparse.ArgumentParser(description="Aggregate cached works into adjusted counts.")
    parser.add_argument("--venue", action="append", default=[], help="Venue key to include (repeatable)")
    parser.add_argument("--all-cached", action="store_true", help="Include every venue with cached works.jsonl")
    parser.add_argument("--year", type=int, default=None, help="Only read this year's cache per venue (default: all cached years)")
    parser.add_argument("--sequential", action="store_true", help="Disable parallel processing (single-threaded)")
    parser.add_argument("--workers", type=int, default=None, help="Number of parallel workers (default: CPU count)")
    args = parser.parse_args()

    registry = load_registry()
    v2a = venue_to_area(registry)

    venue_keys = args.venue if args.venue else (find_cached_venues() if args.all_cached else [])
    if not venue_keys:
        print("Specify --venue <key> (repeatable) or --all-cached", file=sys.stderr)
        sys.exit(1)

    affil_map = load_affiliation_map()
    n_venues = len(venue_keys)

    if args.sequential or n_venues < 2:
        results = [process_venues(venue_keys, v2a, args.year, affil_map)]
    else:
        n_workers = args.workers or cpu_count()
        n_workers = min(n_workers, n_venues)
        chunks = [[] for _ in range(n_workers)]
        for i, vk in enumerate(venue_keys):
            chunks[i % n_workers].append(vk)

        print(f"Aggregating {n_venues} venues across {n_workers} workers...")
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(process_venues, chunk, v2a, args.year, affil_map)
                       for chunk in chunks]
            results = [f.result() for f in futures]

    (inst_area_year, author_area_year_inst, inst_names, author_names,
     total_works, total_authorship_pairs, dropped_no_edu_inst,
     crossref_resolved, multi_inst_author_events, nested_institutions) = merge_results(results)

    os.makedirs(SITE_DATA_DIR, exist_ok=True)

    inst_out = os.path.join(SITE_DATA_DIR, "inst-area-year.csv")
    with open(inst_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["institution_id", "institution_name", "area", "year", "pub_count", "adjusted_count"])
        for (inst_id, area, year), vals in sorted(inst_area_year.items(), key=lambda x: -x[1]["adjusted_count"]):
            w.writerow([inst_id, inst_names[inst_id], area, year, vals["pub_count"], round(vals["adjusted_count"], 5)])

    author_out = os.path.join(SITE_DATA_DIR, "author-info.csv")
    with open(author_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["author_id", "author_name", "institution_id", "institution_name", "area", "year", "adjusted_count"])
        for (author_id, area, year, inst_id), adj in sorted(author_area_year_inst.items(), key=lambda x: -x[1]):
            w.writerow([author_id, author_names[author_id], inst_id, inst_names[inst_id], area, year, round(adj, 5)])

    # --- Summary ---
    print(f"Works processed:              {total_works}")
    print(f"Authorship-institution pairs: {total_authorship_pairs}")
    print(f"Dropped (no education inst):  {dropped_no_edu_inst}")
    print(f"Crossref-resolved via map:    {crossref_resolved}")
    print(f"Multi-education-inst authors: {multi_inst_author_events}  (share split provisionally)")
    print(f"Distinct credited institutions: {len(inst_names)}")
    print(f"Wrote {inst_out}")
    print(f"Wrote {author_out}")

    if nested_institutions:
        print(f"\nNested institutions (lineage length > 1, NOT rolled up -- {len(nested_institutions)} distinct):")
        for inst_id, (name, lineage) in sorted(nested_institutions.items(), key=lambda x: x[1][0]):
            print(f"  {inst_id}  {name}  lineage={lineage}")

    print("\nTop 15 institutions by adjusted count (this run's scope):")
    top = sorted(inst_area_year.items(), key=lambda x: -x[1]["adjusted_count"])[:15]
    for (inst_id, area, year), vals in top:
        print(f"  {vals['adjusted_count']:.3f}  (pubs={vals['pub_count']:>3})  {inst_names[inst_id]:45s}  [{area}, {year}]")


if __name__ == "__main__":
    main()
