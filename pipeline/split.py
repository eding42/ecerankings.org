#!/usr/bin/env python3
"""Split inst-area-year.csv into per-area JSON files for efficient client loading.

Usage:
    python3 pipeline/split.py [--input site/data/inst-area-year.csv] [--areas data/areas.json] [--out site/data/]
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
    parser = argparse.ArgumentParser(description="Split inst-area-year.csv into per-area JSON files.")
    parser.add_argument("--input", default="site/data/inst-area-year.csv")
    parser.add_argument("--areas", default="data/areas.json")
    parser.add_argument("--out", default="site/data")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)

    all_area_keys = load_all_area_keys(args.areas)

    areas = {}
    with open(args.input, newline="") as f:
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

    # Also copy areas.json so the site can find it
    import shutil
    shutil.copy2(args.areas, os.path.join(args.out, "areas.json"))

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

    print(f"\nTotal: {total_rows} rows across {len(areas)} areas, {total_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
