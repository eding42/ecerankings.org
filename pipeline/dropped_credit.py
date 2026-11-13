#!/usr/bin/env python3
"""Where does the credit that `aggregate.py` drops go, and why?

`aggregate.py` credits an author only when it finds an institution of a credit
type. Everything else is dropped without a line in the output, so a pipeline
bug that drops credit looks identical to a paper by an industry author. This
module replays the aggregator's own decision for every author and files each
dropped author under one reason:

  no_affiliation:never_backfilled  OpenAlex-native work, no institution and no raw
                                   string; backfill_openalex.py only covers
                                   Crossref and S2 works, so nobody retried it.
  no_affiliation:backfill_tried    the DOI was looked up and came back empty.
  no_affiliation:no_doi            nothing to look up by DOI.
  no_affiliation:other
  openalex_noncredit               OpenAlex resolved it to a company, hospital,
                                   archive, ... Usually correct.
  untyped_institution              OpenAlex institution with no type, which the
                                   index says is a credit type (Tampere
                                   University). A bug, not a judgement.
  retyped_row                      the curated map resolved it, but the row's
                                   stored type is not a credit type while the
                                   index says it is (UC Riverside stored as
                                   "other"). A bug.
  raw_noncredit                    the map resolved it to a non-credit type.
  raw_unmapped                     raw strings the map does not know.

Only default-on areas are counted, because those drive the default ranking.
Read-only. Stdlib only. Used by verify_global.py (Phase 4); also runnable:

    python3 pipeline/dropped_credit.py [--all-areas] [--top 12]
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aggregate  # noqa: E402
from workkey import record_key, work_key  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
INDEX_JSON = os.path.join(REPO_ROOT, "data", "institutions.json")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
EXCLUDED_CSV = os.path.join(REPO_ROOT, "data", "excluded-works.csv")
NEGATIVE_TXT = os.path.join(CACHE_DIR, ".backfill-negative.txt")

BUGS = ("untyped_institution", "retyped_row")


def short_id(value):
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def normalize_doi(value):
    return (value or "").lower().replace("https://doi.org/", "").strip()


def load_negative(path=NEGATIVE_TXT):
    if not os.path.exists(path):
        return set()
    with open(path) as handle:
        return {line.strip().lower() for line in handle if line.strip()}


def load_excluded(path=EXCLUDED_CSV):
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as handle:
        return {(row.get("work_key") or "").strip() for row in csv.DictReader(handle)} - {""}


def index_types(index):
    """institution short id -> index type."""
    return {short_id(iid): inst.get("type") for iid, inst in index.items()}


def classify_author(author, doi, native, affil_map, types, negative, credit_types):
    """Return (reason, institution_name). reason is None when credited."""
    institutions = author.get("institutions") or []
    if [i for i in institutions if i.get("type") in credit_types]:
        return None, ""
    raw = author.get("raw_affiliations") or []
    if institutions:
        for inst in institutions:
            if not inst.get("type") and types.get(short_id(inst.get("id"))) in credit_types:
                return "untyped_institution", inst.get("display_name") or ""
        return "openalex_noncredit", ""
    resolved = aggregate.resolve_raw_affiliations(raw, affil_map)
    if [i for i in resolved if i.get("type") in credit_types]:
        return None, ""
    for inst in resolved:
        if types.get(short_id(inst.get("id"))) in credit_types:
            return "retyped_row", inst.get("display_name") or ""
    if resolved:
        return "raw_noncredit", ""
    if raw:
        return "raw_unmapped", ""
    if not doi:
        return "no_affiliation:no_doi", ""
    if doi in negative:
        return "no_affiliation:backfill_tried", ""
    return ("no_affiliation:never_backfilled" if native else "no_affiliation:other"), ""


def scan(cache_dir, registry, affil_map, types, excluded=frozenset(), negative=frozenset(), all_areas=False,
         credit_types=None):
    """Replay the aggregator's per-author decision across the cache."""
    credit_types = credit_types or aggregate.CREDIT_TYPES
    venues = {}
    for area_key, area in registry["areas"].items():
        if all_areas or area.get("default_on", True):
            for venue in area["venues"]:
                venues[venue["key"]] = area_key
    out = {"total": 0.0, "reasons": Counter(), "authors": Counter(), "by_venue": defaultdict(Counter),
           "institutions": defaultdict(Counter), "stale_works": Counter(),
           "venues": venues}
    for venue in sorted(venues):
        venue_dir = os.path.join(cache_dir, venue)
        if not os.path.isdir(venue_dir):
            continue
        seen = set()
        for entry in sorted(os.listdir(venue_dir)):
            path = os.path.join(venue_dir, entry, "works.jsonl")
            if not entry.isdigit() or not os.path.exists(path):
                continue
            year = int(entry)
            with open(path) as handle:
                for line in handle:
                    work = json.loads(line)
                    identity = record_key(work, venue, year)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if (work.get("type") or "").lower() in aggregate.NONRESEARCH_TYPES:
                        continue
                    if work_key(work, venue, year) in excluded:
                        continue
                    authors = work.get("authorships") or []
                    if not authors:
                        continue
                    weight = 1.0 / len(authors)
                    doi = normalize_doi(work.get("doi"))
                    native = str(work.get("id") or "").startswith("https://openalex.org/W")
                    dropped = Counter()
                    for author in authors:
                        out["total"] += weight
                        out["by_venue"][venue]["total"] += weight
                        reason, name = classify_author(author, doi, native, affil_map, types, negative, credit_types)
                        if reason is None:
                            continue
                        out["reasons"][reason] += weight
                        out["authors"][reason] += 1
                        out["by_venue"][venue][reason] += weight
                        if name:
                            out["institutions"][reason][name] += weight
                        dropped[reason] += 1
                    if dropped["no_affiliation:never_backfilled"] == len(authors):
                        out["stale_works"][(venue, year)] += 1
    return out


def render(result, top=12):
    total = result["total"] or 1.0
    lines = [f"credit weight (default-on areas): {result['total']:,.0f}"]
    for reason, credit in result["reasons"].most_common():
        lines.append(f"  {reason:36s}{result['authors'][reason]:9,d} authors {credit:9,.0f} credit {100 * credit / total:5.2f}%")
    lines.append(f"  {'dropped, all reasons':36s}{sum(result['authors'].values()):9,d} authors "
                 f"{sum(result['reasons'].values()):9,.0f} credit {100 * sum(result['reasons'].values()) / total:5.2f}%")
    for reason in BUGS:
        top_inst = result["institutions"][reason].most_common(top)
        if top_inst:
            lines.append(f"\n{reason} (bugs, by institution):")
            lines += [f"  {credit:8.1f}  {name}" for name, credit in top_inst]
    stale = sum(result["stale_works"].values())
    if stale:
        lines.append(f"\nworks where every author lacks an affiliation and nothing retried them: {stale:,}")
        for (venue, year), n in result["stale_works"].most_common(top):
            lines.append(f"  {venue} {year}: {n}")
    return "\n".join(lines)


def load_context(map_csv=MAP_CSV, index_json=INDEX_JSON):
    with open(map_csv, newline="") as handle:
        affil_map = aggregate.prepare_affiliation_map({r["raw_affiliation"]: r for r in csv.DictReader(handle)})
    with open(index_json) as handle:
        types = index_types(json.load(handle)["by_id"])
    return affil_map, types


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    parser.add_argument("--areas-json", default=AREAS_JSON, help="Path to areas registry (default: data/areas.json)")
    parser.add_argument("--credit-types", default=None, help="Comma-separated institution types to credit")
    parser.add_argument("--all-areas", action="store_true", help="include areas that are off by default")
    parser.add_argument("--top", type=int, default=12)
    args = parser.parse_args()
    with open(args.areas_json) as handle:
        registry = json.load(handle)
    credit_types = set(t.strip() for t in args.credit_types.split(",") if t.strip()) if args.credit_types else None
    affil_map, types = load_context()
    result = scan(os.path.realpath(args.cache_dir), registry, affil_map, types, load_excluded(), load_negative(),
                  all_areas=args.all_areas, credit_types=credit_types)
    print(render(result, args.top))


if __name__ == "__main__":
    main()
