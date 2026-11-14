#!/usr/bin/env python3
"""Build and package the static Biosciences ranking website data.

Takes aggregated institutional counts from pipeline/aggregate_biosciences.py
and produces the JSON payloads consumed by the static web frontend in site/biology/.
"""

import csv
import json
import os
import shutil
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_BIOSCIENCES = os.path.join(REPO_ROOT, "data", "areas_biosciences.json")
AGGREGATES_DIR = os.path.join(REPO_ROOT, "data", "biosciences_aggregates")
SITE_OUTPUT_DIRS = [
    os.path.join(REPO_ROOT, "site", "biology", "data"),
]

def load_areas():
    with open(AREAS_BIOSCIENCES) as f:
        return json.load(f)

def package_site():
    reg = load_areas()
    areas_list = list(reg["areas"].keys())

    for target_dir in SITE_OUTPUT_DIRS:
        os.makedirs(target_dir, exist_ok=True)

        # 1. Copy areas registry
        shutil.copy2(AREAS_BIOSCIENCES, os.path.join(target_dir, "areas.json"))

        # 2. Package institutions.json from both edu_only and all_insts aggregates
        institutions = {}
        for suffix in ["_edu_only", "_all_insts"]:
            csv_path = os.path.join(AGGREGATES_DIR, f"inst-area-year{suffix}.csv")
            if not os.path.exists(csv_path):
                continue
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    iid = row["institution_id"]
                    if iid not in institutions:
                        institutions[iid] = {
                            "name": row["institution_name"],
                            "country": row.get("country", ""),
                            "type": row.get("type", "education")
                        }

        inst_path = os.path.join(target_dir, "institutions.json")
        with open(inst_path, "w", encoding="utf-8") as f:
            json.dump(institutions, f, separators=(",", ":"))
        print(f"Wrote {len(institutions)} institutions to {inst_path}")

        # 3. Package per-area JSONs ({area}.json and {area}_all.json)
        for mode in ["edu_only", "all_insts"]:
            csv_path = os.path.join(AGGREGATES_DIR, f"inst-area-year_{mode}.csv")
            if not os.path.exists(csv_path):
                continue

            area_records = defaultdict(list)
            with open(csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    area = row["area"]
                    area_records[area].append({
                        "i": row["institution_id"],
                        "n": row["institution_name"],
                        "y": int(row["year"]),
                        "p": int(row["pub_count"]),
                        "a": float(row["adjusted_count"]),
                    })

            for area in areas_list:
                records = area_records.get(area, [])
                target_name = f"{area}.json" if mode == "edu_only" else f"{area}_all.json"
                out_area = os.path.join(target_dir, target_name)
                with open(out_area, "w", encoding="utf-8") as f:
                    json.dump(records, f, separators=(",", ":"))
                print(f"Wrote {len(records)} records to {out_area}")

        # 4. Package per-venue JSONs for drilldown/filtering ({area}/{venue}.json)
        venue_csv_path = os.path.join(AGGREGATES_DIR, "inst-venue-year_edu_only.csv")
        if os.path.exists(venue_csv_path):
            venues_data = defaultdict(list)
            with open(venue_csv_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    area = row["area"]
                    venue = row["venue"]
                    venues_data[(area, venue)].append({
                        "i": row["institution_id"],
                        "n": row["institution_name"],
                        "y": int(row["year"]),
                        "p": int(row["pub_count"]),
                        "a": float(row["adjusted_count"]),
                    })
            for (area, venue), rows in venues_data.items():
                area_dir = os.path.join(target_dir, area)
                os.makedirs(area_dir, exist_ok=True)
                v_path = os.path.join(area_dir, f"{venue}.json")
                with open(v_path, "w", encoding="utf-8") as f:
                    json.dump(rows, f, separators=(",", ":"))
                print(f"Wrote {len(rows)} records to {v_path}")

        # 5. Manifest for site data stamp and latest year
        manifest = {
            "schema_version": 1,
            "latest_complete_year": 2025,
            "generated_at": "2026-11-13",
            "description": "BioRankings: Life Sciences, Biomedical & Bioengineering Rankings",
            "areas_count": len(areas_list)
        }
        with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    print("\nBiosciences site data successfully packaged.")

if __name__ == "__main__":
    package_site()
