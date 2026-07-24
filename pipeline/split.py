#!/usr/bin/env python3
"""Split CSVs into per-area and per-venue JSON files for efficient client loading.

Usage:
    python3 pipeline/split.py [--area-input site/data/inst-area-year.csv]
      [--venue-input site/data/inst-venue-year.csv] [--areas data/areas.json] [--out site/data/]
"""

import argparse
import csv
import json
import os
import sys


def load_all_area_keys(areas_path):
    """Load all area keys from areas.json, or return None if file missing."""
    if os.path.exists(areas_path):
        with open(areas_path) as f:
            return list(json.load(f)["areas"].keys())
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Split CSVs into per-area and per-venue JSON files.")
    parser.add_argument("--area-input", default="site/data/inst-area-year.csv")
    parser.add_argument("--venue-input", default="site/data/inst-venue-year.csv")
    parser.add_argument("--areas", default="data/areas.json")
    parser.add_argument("--out", default="site/data")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    all_area_keys = load_all_area_keys(args.areas)

    # Also copy areas.json so the site can find it
    import shutil
    shutil.copy2(args.areas, os.path.join(args.out, "areas.json"))

    # ── Per-area JSONs (existing) ────────────────
    if not os.path.exists(args.area_input):
        print(f"Area input not found: {args.area_input}", file=sys.stderr)
    else:
        areas = {}
        with open(args.area_input, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                area = row["area"]
                if area not in areas:
                    areas[area] = []
                areas[area].append({
                    "i": row["institution_id"],
                    "n": row["institution_name"],
                    "y": int(row["year"]),
                    "p": int(row["pub_count"]),
                    "a": float(row["adjusted_count"]),
                })

        total_rows = sum(len(v) for v in areas.values())
        total_size = 0

        if all_area_keys:
            for area_key in all_area_keys:
                if area_key not in areas:
                    areas[area_key] = []

        for area_key, rows in sorted(areas.items()):
            path = os.path.join(args.out, f"{area_key}.json")
            payload = json.dumps(rows, separators=(",", ":"))
            with open(path, "w") as f:
                f.write(payload)
            size_kb = len(payload) / 1024
            total_size += len(payload)
            label = f"{len(rows):>6} rows" if rows else "(empty)"
            print(f"  {area_key:20s}  {label:>12s}  {size_kb:>8.1f} KB  → {path}")

        print(f"\nAreas: {total_rows} rows across {len(areas)} areas, {total_size/1024/1024:.1f} MB")

    # ── Per-venue JSONs ──────────────────────────
    if not os.path.exists(args.venue_input):
        print(f"\nVenue input not found: {args.venue_input} (skipping venue split)", file=sys.stderr)
    else:
        venues = {}
        with open(args.venue_input, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                area = row["area"]
                venue = row["venue"]
                key = (area, venue)
                if key not in venues:
                    venues[key] = []
                venues[key].append({
                    "i": row["institution_id"],
                    "n": row["institution_name"],
                    "y": int(row["year"]),
                    "p": int(row["pub_count"]),
                    "a": float(row["adjusted_count"]),
                })

        total_rows = 0
        total_size = 0
        for (area, venue), rows in sorted(venues.items()):
            area_dir = os.path.join(args.out, area)
            os.makedirs(area_dir, exist_ok=True)
            path = os.path.join(area_dir, f"{venue}.json")
            payload = json.dumps(rows, separators=(",", ":"))
            with open(path, "w") as f:
                f.write(payload)
            total_rows += len(rows)
            total_size += len(payload)

        print(f"\nVenues: {total_rows} rows across {len(venues)} venue-area pairs, {total_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
