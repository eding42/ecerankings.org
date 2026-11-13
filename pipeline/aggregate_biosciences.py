#!/usr/bin/env python3
"""Aggregate harvested Biosciences works into institutional adjusted counts.

Supports:
1. Academic-only mode (type == "education", plus accredited degree grantors like UT Southwestern)
2. Institutional rollups for university hospital health systems (MGH/BWH -> Harvard, Stanford Med -> Stanford)
3. Comprehensive mode (all research institutions, crediting HHMI, Broad, NIH, Inserm, CAS)
4. Front-matter / news / preview filtering (Nature d41586, Science news, Cell 1-page intros)
5. Outputs inst-area-year.csv, inst-venue-year.csv, and summary rankings.

Usage:
    python3 pipeline/aggregate_biosciences.py
    python3 pipeline/aggregate_biosciences.py --cache-dir cache_biosciences --out-dir data/biosciences_aggregates
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache_biosciences")
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas_biosciences.json")
OUT_DIR = os.path.join(REPO_ROOT, "data", "biosciences_aggregates")

# Health system and teaching hospital rollups to parent universities
INSTITUTION_ROLLUP = {
    # Harvard teaching hospitals
    "https://openalex.org/I4210087915": "https://openalex.org/I136199984",  # Massachusetts General Hospital -> Harvard
    "https://openalex.org/I1283280774": "https://openalex.org/I136199984",  # Brigham and Women's Hospital -> Harvard
    "https://openalex.org/I4210117453": "https://openalex.org/I136199984",  # Dana-Farber Cancer Institute -> Harvard
    "https://openalex.org/I1288882113": "https://openalex.org/I136199984",  # Boston Children's Hospital -> Harvard
    "https://openalex.org/I1282245388": "https://openalex.org/I136199984",  # Beth Israel Deaconess Medical Center -> Harvard
    "https://openalex.org/I48633490":   "https://openalex.org/I136199984",  # Mass General Brigham -> Harvard
    # Stanford Medicine
    "https://openalex.org/I4210137306": "https://openalex.org/I97018004",   # Stanford Medicine -> Stanford University
    # Johns Hopkins Medicine
    "https://openalex.org/I2799853436": "https://openalex.org/I145311948",  # Johns Hopkins Medicine -> Johns Hopkins University
    # Cornell
    "https://openalex.org/I4210164223": "https://openalex.org/I205783295",  # Weill Cornell Medicine -> Cornell University
    # Penn
    "https://openalex.org/I4210129206": "https://openalex.org/I79510175",   # Hospital of Univ of Pennsylvania -> Penn
    # Yale
    "https://openalex.org/I4210145889": "https://openalex.org/I32971472",   # Yale New Haven Health -> Yale University
    # Pittsburgh
    "https://openalex.org/I4210143521": "https://openalex.org/I170897317",  # UPMC -> University of Pittsburgh
    # UCLA
    "https://openalex.org/I4210137532": "https://openalex.org/I161048801",  # UCLA Health -> UCLA
    # UC San Diego
    "https://openalex.org/I4210137449": "https://openalex.org/I36234482",   # UCSD Health -> UCSD
    # UCSF
    "https://openalex.org/I4210137482": "https://openalex.org/I180670191",  # UCSF Health -> UCSF
    # NYU
    "https://openalex.org/I4210141675": "https://openalex.org/I57206974",   # NYU Langone -> NYU
    # Michigan
    "https://openalex.org/I4210137349": "https://openalex.org/I27837315",   # Michigan Medicine -> University of Michigan
    # Duke
    "https://openalex.org/I4210140227": "https://openalex.org/I170201317",  # Duke Health -> Duke University
    # Washington University in St. Louis
    "https://openalex.org/I4210162590": "https://openalex.org/I204465549",  # Barnes-Jewish Hospital -> WashU
    # Vanderbilt
    "https://openalex.org/I4210156064": "https://openalex.org/I9093155",    # Vanderbilt Univ Medical Center -> Vanderbilt
    # Colorado
    "https://openalex.org/I4210133038": "https://openalex.org/I96673550",   # UCHealth -> CU Anschutz
}

# Accredited degree-granting medical institutions / graduate schools misclassified by OpenAlex
ACADEMIC_ALLOWLIST = {
    "https://openalex.org/I867280407": "The University of Texas Southwestern Medical Center",
    "https://openalex.org/I1343551460": "The University of Texas MD Anderson Cancer Center",
    "https://openalex.org/I1334819555": "Memorial Sloan Kettering Cancer Center",
    "https://openalex.org/I123431417": "Scripps Research Institute",
    "https://openalex.org/I1311060955": "Mayo Clinic College of Medicine and Science",
}

CANONICAL_NAMES = {
    "https://openalex.org/I136199984": "Harvard University",
    "https://openalex.org/I97018004": "Stanford University",
    "https://openalex.org/I145311948": "Johns Hopkins University",
    "https://openalex.org/I205783295": "Cornell University",
    "https://openalex.org/I79510175": "University of Pennsylvania",
    "https://openalex.org/I32971472": "Yale University",
    "https://openalex.org/I161048801": "University of California, Los Angeles",
    "https://openalex.org/I36234482": "University of California, San Diego",
    "https://openalex.org/I180670191": "University of California, San Francisco",
    "https://openalex.org/I57206974": "New York University",
    "https://openalex.org/I27837315": "University of Michigan",
    "https://openalex.org/I170201317": "Duke University",
    "https://openalex.org/I170897317": "University of Pittsburgh",
    "https://openalex.org/I204465549": "Washington University in St. Louis",
    "https://openalex.org/I9093155": "Vanderbilt University",
    "https://openalex.org/I96673550": "University of Colorado Anschutz Medical Campus",
    "https://openalex.org/I867280407": "The University of Texas Southwestern Medical Center",
    "https://openalex.org/I1343551460": "The University of Texas MD Anderson Cancer Center",
    "https://openalex.org/I1334819555": "Memorial Sloan Kettering Cancer Center",
    "https://openalex.org/I123431417": "Scripps Research Institute",
    "https://openalex.org/I1311060955": "Mayo Clinic College of Medicine and Science",
}

def load_registry(path):
    with open(path) as f:
        return json.load(f)

def is_research_article(w, vkey):
    wtype = w.get("type")
    # Disqualify errata, editorials, book reviews, letters
    if wtype in ("editorial", "erratum", "letter", "book-review", "note"):
        return False

    doi = (w.get("doi") or "").lower()

    # Nature portfolio front-matter / magazine items (d41586, d41587, etc.)
    if re.search(r"10\.1038/d\d+", doi):
        return False

    # Science: Exclude news, policy, perspectives without research content
    if vkey == "science" or "10.1126/science" in doi:
        refs = w.get("referenced_works_count")
        if refs is not None and refs == 0:
            return False
        b = w.get("biblio") or {}
        fp = str(b.get("first_page") or "").strip()
        lp = str(b.get("last_page") or "").strip()
        if fp.startswith("e") or lp.startswith("e"):
            return True
        if fp and lp and fp.isdigit() and lp.isdigit():
            if (int(lp) - int(fp) <= 2) and (refs is None or refs < 10):
                return False

    # Cell: Exclude Previews / Voices / Introductions
    if vkey == "cell" or "10.1016/j.cell" in doi:
        refs = w.get("referenced_works_count")
        if refs is not None and refs == 0:
            return False
        b = w.get("biblio") or {}
        fp = str(b.get("first_page") or "").strip()
        lp = str(b.get("last_page") or "").strip()
        if fp and lp and fp == lp and not fp.endswith(".e1") and (refs is None or refs < 5):
            return False

    return True

def run_aggregation(cache_dir, areas_path, out_dir, include_non_education=False):
    os.makedirs(out_dir, exist_ok=True)
    registry = load_registry(areas_path)

    venue_to_areas = defaultdict(list)
    for akey, ainfo in registry["areas"].items():
        for v in ainfo["venues"]:
            venue_to_areas[v["key"]].append(akey)

    # Trackers
    # (inst_id, area, year) -> {pub_count, adj_count}
    inst_area_year = defaultdict(lambda: {"pub_count": 0, "adjusted_count": 0.0})
    # (inst_id, venue, year) -> {pub_count, adj_count}
    inst_venue_year = defaultdict(lambda: {"pub_count": 0, "adjusted_count": 0.0})
    inst_meta = {}

    # Seed canonical names and types
    for cid, cname in CANONICAL_NAMES.items():
        inst_meta[cid] = {"name": cname, "country": "US", "type": "education"}

    total_works = 0
    research_works = 0
    total_authorships = 0
    credited_authorships = 0

    venues = sorted(os.listdir(cache_dir))
    for v in venues:
        vdir = os.path.join(cache_dir, v)
        if not os.path.isdir(vdir):
            continue
        assigned_areas = venue_to_areas.get(v, ["elite_bio"])

        for ystr in sorted(os.listdir(vdir)):
            ydir = os.path.join(vdir, ystr)
            wfile = os.path.join(ydir, "works.jsonl")
            if not os.path.isfile(wfile):
                continue
            year = int(ystr)

            with open(wfile, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    w = json.loads(line)
                    total_works += 1

                    if not is_research_article(w, v):
                        continue
                    research_works += 1

                    authorships = w.get("authorships", [])
                    num_authors = len(authorships)
                    if num_authors == 0:
                        continue

                    share_per_author = 1.0 / num_authors

                    for a in authorships:
                        total_authorships += 1
                        insts = a.get("institutions", [])
                        valid_targets = {}

                        for i in insts:
                            iid = i.get("id")
                            if not iid:
                                continue
                            itype = i.get("type")
                            target_id = INSTITUTION_ROLLUP.get(iid, iid)
                            target_name = CANONICAL_NAMES.get(target_id, i.get("display_name"))
                            target_country = i.get("country_code")

                            is_academic = (
                                itype == "education"
                                or target_id in ACADEMIC_ALLOWLIST
                                or target_id in INSTITUTION_ROLLUP.values()
                            )

                            if include_non_education or is_academic:
                                valid_targets[target_id] = {
                                    "name": target_name,
                                    "country": target_country,
                                    "type": "education" if is_academic else itype,
                                }

                        if not valid_targets:
                            continue

                        # Split author's share evenly across distinct target institutions
                        split_share = share_per_author / len(valid_targets)

                        for target_id, target_info in valid_targets.items():
                            if target_id not in inst_meta or (inst_meta[target_id]["name"].startswith("http") and not target_info["name"].startswith("http")):
                                inst_meta[target_id] = target_info

                            # Credit each area the venue belongs to
                            for area in assigned_areas:
                                inst_area_year[(target_id, area, year)]["pub_count"] += 1
                                inst_area_year[(target_id, area, year)]["adjusted_count"] += split_share

                            inst_venue_year[(target_id, v, year)]["pub_count"] += 1
                            inst_venue_year[(target_id, v, year)]["adjusted_count"] += split_share
                            credited_authorships += 1

    suffix = "_all_insts" if include_non_education else "_edu_only"
    out_csv = os.path.join(out_dir, f"inst-area-year{suffix}.csv")
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["institution_id", "institution_name", "country", "type", "area", "year", "pub_count", "adjusted_count"])
        for (iid, area, year), vals in sorted(inst_area_year.items(), key=lambda x: (x[0][1], x[0][2], -x[1]["adjusted_count"])):
            meta = inst_meta.get(iid, {"name": iid, "country": "", "type": "education"})
            writer.writerow([
                iid,
                meta["name"],
                meta.get("country", ""),
                meta.get("type", "education"),
                area,
                year,
                vals["pub_count"],
                round(vals["adjusted_count"], 4)
            ])

    venue_csv = os.path.join(out_dir, f"inst-venue-year{suffix}.csv")
    with open(venue_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["institution_id", "institution_name", "country", "type", "area", "venue", "year", "pub_count", "adjusted_count"])
        for (iid, v, year), vals in sorted(inst_venue_year.items(), key=lambda x: (x[0][1], x[0][2], -x[1]["adjusted_count"])):
            meta = inst_meta.get(iid, {"name": iid, "country": "", "type": "education"})
            writer.writerow([
                iid,
                meta["name"],
                meta.get("country", ""),
                meta.get("type", "education"),
                venue_to_areas.get(v, ["biosciences"])[0],
                v,
                year,
                vals["pub_count"],
                round(vals["adjusted_count"], 4)
            ])

    # Summary table across all years (using elite_bio or total adjusted count)
    summary = defaultdict(lambda: {"pub_count": 0, "adjusted_count": 0.0})
    for (iid, area, year), vals in inst_area_year.items():
        summary[iid]["pub_count"] += vals["pub_count"]
        summary[iid]["adjusted_count"] += vals["adjusted_count"]

    summary_csv = os.path.join(out_dir, f"rankings_summary{suffix}.csv")
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "institution_id", "institution_name", "country", "type", "pub_count", "adjusted_count"])
        ranked = sorted(summary.items(), key=lambda x: -x[1]["adjusted_count"])
        for rank, (iid, vals) in enumerate(ranked, 1):
            meta = inst_meta.get(iid, {"name": iid, "country": "", "type": "education"})
            writer.writerow([
                rank,
                iid,
                meta["name"],
                meta.get("country", ""),
                meta.get("type", "education"),
                vals["pub_count"],
                round(vals["adjusted_count"], 4)
            ])

    print(f"\n[{'All Institutions' if include_non_education else 'Universities Only'}]")
    print(f"  Processed {total_works} total works ({research_works} research articles after front-matter filter).")
    print(f"  Credited {credited_authorships}/{total_authorships} author slots.")
    print(f"  Wrote {out_csv} and {summary_csv}")
    print("  Top 10 Institutions:")
    ranked = sorted(summary.items(), key=lambda x: -x[1]["adjusted_count"])
    for rank, (iid, vals) in enumerate(ranked[:10], 1):
        meta = inst_meta.get(iid, {"name": iid, "country": "", "type": "education"})
        print(f"    {rank:2d}. {meta['name']} ({meta.get('country', '')}, {meta.get('type', '')}): {vals['adjusted_count']:.2f} score ({vals['pub_count']} papers)")

def main():
    parser = argparse.ArgumentParser(description="Aggregate Biosciences works.")
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    parser.add_argument("--areas-json", default=AREAS_JSON)
    parser.add_argument("--out-dir", default=OUT_DIR)
    args = parser.parse_args()

    print("Running aggregation in both modes (Universities Only and All Research Institutions)...")
    run_aggregation(args.cache_dir, args.areas_json, args.out_dir, include_non_education=False)
    run_aggregation(args.cache_dir, args.areas_json, args.out_dir, include_non_education=True)

if __name__ == "__main__":
    main()
