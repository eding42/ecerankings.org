#!/usr/bin/env python3
"""Batch harvester for 2005-2015 works across all default-on ECE venues.

Iterates over all 18 default-on ECE areas, determines missing years
in [start_year, 2015] respecting source-first-years.json and venue foundation
dates, and calls harvest.harvest_year.
"""

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from pipeline.harvest import (
    AREAS_JSON,
    CACHE_DIR,
    find_venue,
    harvest_year,
    load_env,
    load_registry,
    resolve_year_sources,
)

SOURCE_FIRST_YEARS_FILE = os.path.join(REPO_ROOT, "data", "source-first-years.json")


def load_first_years():
    if os.path.exists(SOURCE_FIRST_YEARS_FILE):
        with open(SOURCE_FIRST_YEARS_FILE) as f:
            return json.load(f)
    return {}


def get_venue_missing_years(venue, first_years):
    key = venue["key"]
    start_year = max(2005, first_years.get(key, 2005))
    if key == "ecce":
        start_year = 2009

    all_years = list(range(start_year, 2016))
    if key == "iccv":
        # Biennial in odd years
        all_years = [y for y in all_years if y % 2 == 1]

    missing = []
    for y in all_years:
        cp_file = os.path.join(CACHE_DIR, key, str(y), ".checkpoint")
        works_file = os.path.join(CACHE_DIR, key, str(y), "works.jsonl")
        if os.path.exists(cp_file):
            try:
                with open(cp_file) as f:
                    state = json.load(f)
                if state.get("done") and os.path.exists(works_file):
                    continue
            except Exception:
                pass
        missing.append(y)
    return missing


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Harvest 2005-2015 works for default-on venues.")
    parser.add_argument("--venue", help="Harvest only this venue")
    parser.add_argument("--area", help="Harvest only venues in this area")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without fetching")
    args = parser.parse_args()

    registry = load_registry()
    first_years = load_first_years()
    env = load_env()
    api_key = env.get("OPENALEX_API_KEY")

    plan = []
    for aid, area in registry["areas"].items():
        if not area.get("default_on", False):
            continue
        if args.area and aid != args.area:
            continue
        for v in area.get("venues", []):
            if args.venue and v["key"] != args.venue:
                continue
            missing = get_venue_missing_years(v, first_years)
            if missing:
                plan.append((aid, v, missing))

    total_tasks = sum(len(m) for _, _, m in plan)
    print(f"=== 2005-2015 Harvest Plan ===")
    print(f"Venues to harvest: {len(plan)}")
    print(f"Total venue-years: {total_tasks}")

    for aid, v, missing in plan:
        print(f"  [{aid}/{v['key']}] {len(missing)} years: {min(missing)}-{max(missing)}")

    if args.dry_run:
        print("Dry run requested. Exiting.")
        return

    print("\nStarting harvest...")
    start_time = time.time()
    completed = 0
    errors = []

    for aid, v, missing in plan:
        v_key = v["key"]
        print(f"\n>>> Harvesting {aid}/{v_key} ({len(missing)} years)...")
        for yr in missing:
            source_ids, year_filter, mode = resolve_year_sources(v, yr)
            if not source_ids:
                print(f"  [{v_key}/{yr}] ERROR: no source IDs found. Skipping.")
                errors.append(f"{v_key}/{yr}: no source IDs")
                continue
            try:
                harvest_year(v_key, yr, source_ids, year_filter, api_key)
                completed += 1
            except Exception as e:
                print(f"  [{v_key}/{yr}] ERROR: {e}")
                errors.append(f"{v_key}/{yr}: {e}")
                time.sleep(1)

    elapsed = time.time() - start_time
    print(f"\n=== Harvest Complete ===")
    print(f"Completed {completed}/{total_tasks} venue-years in {elapsed/60:.1f} minutes.")
    if errors:
        print(f"Errors encountered ({len(errors)}):")
        for err in errors:
            print(f"  - {err}")


if __name__ == "__main__":
    main()
