#!/usr/bin/env python3
"""Batch harvester for Earth, Planetary, and Space Sciences venues.

Iterates over astronomy, planetary, geosciences, and cryosphere_climate areas,
determines active years respecting source-first-years.json and venue foundation
dates, and calls harvest_year.

Usage:
    python3 pipeline/harvest_earth_space.py --year 2024
    python3 pipeline/harvest_earth_space.py --year-range 2016 2025
    python3 pipeline/harvest_earth_space.py --year-range 2005 2025
    python3 pipeline/harvest_earth_space.py --area astronomy --year 2024
    python3 pipeline/harvest_earth_space.py --venue psj --year-range 2020 2025
"""

import argparse
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
    resolve_year_sources,
)

SOURCE_FIRST_YEARS_FILE = os.path.join(REPO_ROOT, "data", "source-first-years.json")
EARTH_SPACE_JSON = os.path.join(REPO_ROOT, "data", "areas_earth_space.json")


def load_first_years():
    if os.path.exists(SOURCE_FIRST_YEARS_FILE):
        with open(SOURCE_FIRST_YEARS_FILE) as f:
            return json.load(f)
    return {}


def load_earth_space_registry():
    with open(EARTH_SPACE_JSON) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Harvest Earth, Planetary, and Space Sciences works.")
    parser.add_argument("--year", type=int, default=None, help="Single year to harvest")
    parser.add_argument("--year-range", nargs=2, type=int, metavar=("START", "END"),
                        help="Year range to harvest inclusive (e.g. 2016 2025)")
    parser.add_argument("--area", default=None,
                        choices=["astronomy", "planetary", "geosciences", "cryosphere_climate"],
                        help="Filter to a single area")
    parser.add_argument("--venue", default=None, help="Filter to a single venue key")
    parser.add_argument("--cache-dir", default=CACHE_DIR,
                        help="Cache output directory (defaults to cache/, or pass cache_staged/)")
    args = parser.parse_args()

    if not args.year and not args.year_range:
        print("Specify --year <YYYY> or --year-range <START> <END>", file=sys.stderr)
        sys.exit(1)

    if args.year_range:
        start_year, end_year = args.year_range
        years = list(range(start_year, end_year + 1))
    else:
        years = [args.year]

    env = load_env()
    api_key = env.get("OPENALEX_API_KEY")
    if not api_key:
        print("Warning: OPENALEX_API_KEY not found in .env; requests may be rate-limited.", file=sys.stderr)

    reg = load_earth_space_registry()
    first_years = load_first_years()

    areas_to_process = [args.area] if args.area else list(reg["areas"].keys())

    venues_to_process = []
    for a_key in areas_to_process:
        area = reg["areas"][a_key]
        for v in area["venues"]:
            if args.venue and v["key"] != args.venue:
                continue
            venues_to_process.append((a_key, v))

    print(f"Earth & Space Harvester: {len(venues_to_process)} venues queued across {len(years)} year(s) {years[0]}..{years[-1]}")
    print(f"Target Cache: {args.cache_dir}")
    print("-" * 75)

    total_harvested = 0
    for area_key, venue in venues_to_process:
        vkey = venue["key"]
        vname = venue["display"]
        vfirst = first_years.get(vkey, 2005)
        extra_filter = venue.get("openalex_filter")

        print(f"\n>>> [{area_key}/{vkey}] {vname} (Foundation/Start: {vfirst})")
        for y in years:
            if y < vfirst:
                print(f"  [{vkey}/{y}] Skipped (prior to foundation year {vfirst})")
                continue

            source_ids, year_filter, mode = resolve_year_sources(venue, y)
            if not source_ids:
                print(f"  [{vkey}/{y}] No source IDs found, skipping.")
                continue

            harvest_year(vkey, y, source_ids, year_filter, api_key,
                         cache_dir=args.cache_dir, extra_filter=extra_filter)
            total_harvested += 1
            time.sleep(0.1)

    print(f"\nHarvesting batch completed! Processed {total_harvested} venue-year tasks.")


if __name__ == "__main__":
    main()
