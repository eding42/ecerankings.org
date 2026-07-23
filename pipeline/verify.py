"""Multi-layer data quality verifier for ECERankings pipeline.

Run after harvest, normalization, or aggregation to catch pipeline bugs,
data corruption, and affiliation mismatches before they reach the rankings.

Usage:
    python3 pipeline/verify.py --all                 # All three phases
    python3 pipeline/verify.py --phase 1             # Harvest integrity only
    python3 pipeline/verify.py --phase 3 --area architecture  # Single area
    python3 pipeline/verify.py --report              # Write report file
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
SITE_DATA = os.path.join(REPO_ROOT, "site", "data")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
KNOWN_JSON = os.path.join(REPO_ROOT, "data", "known-strong.json")
INST_JSON = os.path.join(REPO_ROOT, "data", "institutions.json")
REPORTS_DIR = os.path.join(REPO_ROOT, "data", "reports")


# ════════════════════════════════════════════════════════════════════
# Phase 1: Harvest integrity
# ════════════════════════════════════════════════════════════════════

def phase1_harvest(areas, args):
    """Check venue-year coverage, author completeness, affiliation presence."""
    print("\n═══ Phase 1: Harvest Integrity ═══")
    flags = {"critical": [], "high": [], "medium": [], "low": []}
    venue_years_covered = defaultdict(set)

    # Build venue-to-area mapping
    v2a = {}
    for ak, area in areas["areas"].items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        for v in area["venues"]:
            v2a[v["key"]] = (ak, v)

    # Check every venue's cached years
    for vkey, (ak, vdef) in sorted(v2a.items()):
        expected_years = vdef.get("years", {})
        expected_floor = vdef.get("expected_per_year", [None, None])[0]
        cached_years = set()
        vdir = os.path.join(CACHE_DIR, vkey)

        if os.path.isdir(vdir):
            for yd in sorted(os.listdir(vdir)):
                if not yd.isdigit():
                    continue
                wf = os.path.join(vdir, yd, "works.jsonl")
                if os.path.exists(wf):
                    cached_years.add(int(yd))

        # 1a. Missing years: registered but no cache
        for yr_str, yr_info in expected_years.items():
            yr = int(yr_str)
            if yr_info.get("source") != "none" and yr not in cached_years:
                flags["critical"].append(
                    f"[{vkey}] year {yr} registered (source={yr_info['source']}) but cache/ missing"
                )

        # 1b. Paper count vs expected
        for yr in sorted(cached_years):
            wf = os.path.join(vdir, str(yr), "works.jsonl")
            count = 0
            no_author = 0
            no_affil = 0
            total_authorships = 0
            seen_ids = set()
            seen_titles = defaultdict(list)

            with open(wf) as f:
                for line in f:
                    w = json.loads(line)
                    count += 1
                    pid = w.get("id", "")
                    if pid and pid in seen_ids:
                        flags["medium"].append(f"[{vkey}/{yr}] duplicate paper ID: {pid}")
                    seen_ids.add(pid)
                    title = w.get("title", "")
                    if title:
                        seen_titles[title.lower().strip()].append(pid)

                    authorships = w.get("authorships", [])
                    if not authorships:
                        no_author += 1
                    for a in authorships:
                        total_authorships += 1
                        if not a.get("raw_affiliations"):
                            no_affil += 1

            yr_str = str(yr)
            if yr_str in expected_years:
                expected_count = expected_years[yr_str].get("count")
                if expected_count and expected_floor:
                    pct = count / expected_floor * 100 if expected_floor else 100
                    if pct < 70:
                        flags["high"].append(
                            f"[{vkey}/{yr}] {count} papers ({pct:.0f}% of floor {expected_floor})"
                        )
                    elif pct < 90:
                        flags["medium"].append(
                            f"[{vkey}/{yr}] {count} papers ({pct:.0f}% of floor {expected_floor})"
                        )

            # 1c. Author completeness
            if no_author > 0:
                flags["high"].append(
                    f"[{vkey}/{yr}] {no_author}/{count} works have zero authors"
                )

            # 1d. Affiliation presence
            if total_authorships > 0:
                affil_pct = (total_authorships - no_affil) / total_authorships * 100
                if affil_pct < 80:
                    flags["medium"].append(
                        f"[{vkey}/{yr}] only {affil_pct:.0f}% authorships have raw_affiliations"
                    )

            # 1e. Title duplicates
            for title, pids in seen_titles.items():
                if len(pids) > 1 and len(title) > 10:
                    flags["medium"].append(
                        f"[{vkey}/{yr}] {len(pids)} papers with duplicate title: {title[:60]}..."
                    )

    # 1f. Summary stats
    total_venue_years = sum(len(list(v["years"].keys())) for v in v2a.values())
    cached_count = sum(1 for vdirs in
                       [os.listdir(os.path.join(CACHE_DIR, vk))
                        for vk in v2a
                        if os.path.isdir(os.path.join(CACHE_DIR, vk))]
                       for yd in vdirs
                       if yd.isdigit() and
                       os.path.exists(os.path.join(CACHE_DIR, vk, yd, "works.jsonl")))
    print(f"  Venue-years cached:   {cached_count}")
    print(f"  Venue-years expected: {total_venue_years}")

    return flags


# ════════════════════════════════════════════════════════════════════
# Phase 2: Normalization integrity
# ════════════════════════════════════════════════════════════════════

def phase2_normalization(areas, args):
    """Check resolution rate, type distribution, cluster misattributions, acronyms."""
    print("\n═══ Phase 2: Normalization Integrity ═══")
    flags = {"critical": [], "high": [], "medium": [], "low": []}

    if not os.path.exists(MAP_CSV):
        flags["critical"].append("affiliation-map.csv not found")
        return flags

    rows = []
    with open(MAP_CSV) as f:
        for r in csv.DictReader(f):
            rows.append(r)

    total = len(rows)
    status_counts = defaultdict(int)
    type_counts = defaultdict(int)
    for r in rows:
        status_counts[r.get("status", "unknown")] += 1
        itype = r.get("institution_type", "")
        if itype:
            type_counts[itype] += 1
        else:
            type_counts["(empty)"] += 1

    resolved = status_counts.get("auto", 0) + status_counts.get("manual", 0)
    edu = type_counts.get("education", 0)
    company = type_counts.get("company", 0)

    print(f"  Total distinct affiliations: {total}")
    print(f"  Resolved (auto+manual):      {resolved} ({resolved/total*100:.1f}%)")
    print(f"  Education:                   {edu} ({edu/total*100:.1f}%)")
    print(f"  Company:                     {company} ({company/total*100:.1f}%)")
    print(f"  Unmatched:                   {status_counts.get('unmatched', 0)} ({status_counts['unmatched']/total*100:.1f}%)")
    print(f"  Review:                      {status_counts.get('review', 0)} ({status_counts.get('review', 0)/total*100:.1f}%)")

    if resolved / total < 0.65:
        flags["high"].append(f"Resolution rate below 65%: {resolved/total*100:.1f}%")
    if edu / total < 0.50:
        flags["high"].append(f"Education rate below 50%: {edu/total*100:.1f}%")

    # 2a. Acronym check
    inst_db = None
    if os.path.exists(INST_JSON):
        with open(INST_JSON) as f:
            inst_db = json.load(f)["by_id"]

    short_acronym_mismatches = 0
    if inst_db:
        for r in rows:
            if r["status"] not in ("auto", "manual"):
                continue
            mv = r.get("matched_via", "")
            if len(mv) <= 5 and mv.isalpha():
                iid = r.get("institution_id", "")
                inst = inst_db.get(iid)
                if inst:
                    official = [a.lower() for a in inst.get("acronyms", [])]
                    alts = [a.lower() for a in inst.get("alternatives", [])]
                    if mv.lower() not in official and mv.lower() not in alts:
                        short_acronym_mismatches += 1
        if short_acronym_mismatches > 0:
            flags["medium"].append(f"{short_acronym_mismatches} rows where short matched_via is not an official acronym")

    # 2b. Campus cluster check (re-run the fixer and count changes)
    import subprocess
    cluster_script = os.path.join(REPO_ROOT, "pipeline", "fix_campus_clusters.py")
    if os.path.exists(cluster_script):
        result = subprocess.run(
            ["python3", cluster_script],
            capture_output=True, text=True, timeout=120
        )
        # Extract fix count from script output
        fix_match = None
        for line in result.stdout.splitlines():
            if line.startswith("Fixed:"):
                try:
                    fix_match = int(line.split(":")[1].strip())
                except ValueError:
                    pass
        if fix_match and fix_match > 0:
            flags["high"].append(
                f"fix_campus_clusters.py found {fix_match} new misattributions — run and re-aggregate"
            )

    return flags


# ════════════════════════════════════════════════════════════════════
# Phase 3: Aggregate integrity
# ════════════════════════════════════════════════════════════════════

def phase3_aggregate(areas, args):
    """Check zero-count audit, venue contribution, top-N sanity, author consistency."""
    print("\n═══ Phase 3: Aggregate Integrity ═══")
    flags = {"critical": [], "high": [], "medium": [], "low": []}

    inst_csv = os.path.join(SITE_DATA, "inst-area-year.csv")
    author_csv = os.path.join(SITE_DATA, "author-info.csv")

    if not os.path.exists(inst_csv):
        flags["critical"].append("inst-area-year.csv not found — run aggregate.py first")
        return flags

    # Build institution lookup
    inst_names = {}
    if os.path.exists(INST_JSON):
        with open(INST_JSON) as f:
            db = json.load(f)["by_id"]
        for iid, v in db.items():
            inst_names[iid] = v.get("display_name", "")

    # 3a. Venue contribution check
    v2a = {}
    for ak, area in areas["areas"].items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        for v in area["venues"]:
            v2a[v["key"]] = ak

    venue_credited = defaultdict(int)
    area_insts = defaultdict(set)

    with open(inst_csv) as f:
        for r in csv.DictReader(f):
            venue_credited[r["area"]] += float(r.get("adjusted_count", 0))
            area_insts[r["area"]].add(r["institution_id"])

    for vkey, ak in sorted(v2a.items()):
        if ak not in area_insts or not area_insts[ak]:
            flags["high"].append(f"[{vkey}] area '{ak}' has zero credited institutions")

    # Area summary
    for ak in sorted(area_insts.keys()):
        area_name = areas["areas"][ak]["name"]
        n_insts = len(area_insts[ak])
        if n_insts == 0:
            flags["critical"].append(f"[{ak}] {area_name} — zero institutions credited")
        print(f"  [{ak}] {area_name:35s}  {n_insts:>5d} institutions")

    # 3b. Zero-count audit (known-strong institutions)
    if os.path.exists(KNOWN_JSON):
        with open(KNOWN_JSON) as f:
            known_strong = json.load(f)

        area_scores = defaultdict(lambda: defaultdict(float))
        with open(inst_csv) as f:
            for r in csv.DictReader(f):
                area_scores[r["area"]][r["institution_id"]] += float(r["adjusted_count"])

        for ak, strong_ids in known_strong.items():
            if args.area and args.area != "all" and ak != args.area:
                continue
            scores = area_scores.get(ak, {})
            for sid in strong_ids:
                sc = scores.get(sid, 0)
                if sc == 0:
                    name = inst_names.get(sid, sid)
                    flags["critical"].append(
                        f"[{ak}] known-strong {name} has zero count"
                    )

    # 3c. Top-N per area
    print("\n  Top institutions per area:")
    area_scores = defaultdict(lambda: defaultdict(float))
    with open(inst_csv) as f:
        for r in csv.DictReader(f):
            area_scores[r["area"]][r["institution_id"]] += float(r["adjusted_count"])

    for ak in sorted(area_scores.keys()):
        if args.area and args.area != "all" and ak != args.area:
            continue
        area_name = areas["areas"][ak]["name"]
        top = sorted(area_scores[ak].items(), key=lambda x: -x[1])[:5]
        print(f"  [{ak}] {area_name}")
        for iid, sc in top:
            name = inst_names.get(iid, iid.split("/")[-1])
            print(f"         {sc:>8.1f}  {name}")

    # 3d. Author cross-validation
    if os.path.exists(author_csv):
        author_insts = defaultdict(set)
        with open(author_csv) as f:
            for r in csv.DictReader(f):
                key = (r["author_id"], r["area"], r["year"])
                author_insts[key].add(r["institution_id"])

        multi_inst_authors = sum(1 for v in author_insts.values() if len(v) > 1)
        total_keys = len(author_insts)
        if total_keys > 0 and multi_inst_authors / total_keys > 0.01:
            flags["medium"].append(
                f"{multi_inst_authors}/{total_keys} author-area-year tuples have multiple institutions ({multi_inst_authors/total_keys*100:.1f}%)"
            )

    # 3e. Year-over-year row count consistency per area
    area_years = defaultdict(lambda: defaultdict(int))
    with open(inst_csv) as f:
        for r in csv.DictReader(f):
            area_years[r["area"]][int(r["year"])] += 1

    for ak, year_counts in area_years.items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        years = sorted(year_counts.keys())
        if len(years) < 3:
            continue
        counts = [year_counts[y] for y in years]
        mean = sum(counts) / len(counts)
        if mean == 0:
            continue
        std = (sum((c - mean) ** 2 for c in counts) / len(counts)) ** 0.5
        if std == 0:
            continue
        for y, c in zip(years, counts):
            if abs(c - mean) > 3 * std:
                flags["low"].append(
                    f"[{ak}] outlier year {y}: {c} rows vs mean {mean:.0f}±{std:.0f}"
                )

    # 3f. Institution year-over-year cliff drops
    # Flag institutions with established presence (≥3 years, ≥10.0 total adj)
    # where a single year drops >80% from prior year AND prior year ≥3.0.
    # Excludes the most recent year (typically incomplete due to publication lag).
    inst_year_scores = defaultdict(lambda: defaultdict(float))
    all_years_set = set()
    with open(inst_csv) as f:
        for r in csv.DictReader(f):
            yr = int(r["year"])
            all_years_set.add(yr)
            key = (r["institution_id"], r["area"])
            inst_year_scores[key][yr] += float(r["adjusted_count"])

    max_year = max(all_years_set) if all_years_set else 9999

    for (iid, ak), yr_scores in inst_year_scores.items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        years = sorted(yr_scores.keys())
        if len(years) < 3:
            continue
        total = sum(yr_scores.values())
        if total < 10.0:
            continue

        for i in range(1, len(years)):
            prev = yr_scores[years[i - 1]]
            curr = yr_scores[years[i]]
            if years[i] == max_year:
                continue  # skip current partial year
            if prev < 3.0:
                continue
            drop_pct = (prev - curr) / prev * 100 if prev > 0 else 0
            if drop_pct > 80 and curr < 1.0:
                name = inst_names.get(iid, iid.split("/")[-1])
                area_name = areas["areas"][ak]["name"]
                flags["high"].append(
                    f"[{ak}] {name} — {years[i-1]}={prev:.1f} → {years[i]}={curr:.2f} ({drop_pct:.0f}% drop)"
                )

    return flags


# ════════════════════════════════════════════════════════════════════
# Report & main
# ════════════════════════════════════════════════════════════════════

def write_report(all_flags, args):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = date.today().isoformat()
    path = os.path.join(REPORTS_DIR, f"verify-{today}.md")
    with open(path, "w") as f:
        f.write(f"# Verification Report — {today}\n\n")
        f.write(f"Area: {args.area or 'all'}  |  Phases: {args.phase or 'all'}\n\n")

        total_flags = 0
        for phase_name, flags in all_flags.items():
            f.write(f"## {phase_name}\n\n")
            for severity in ["critical", "high", "medium", "low"]:
                items = flags.get(severity, [])
                if not items:
                    continue
                emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}[severity]
                f.write(f"### {emoji} {severity.upper()} ({len(items)})\n\n")
                for item in items:
                    f.write(f"- {item}\n")
                f.write("\n")
                total_flags += len(items)

        f.write(f"\n**Total flags: {total_flags}**\n")
        if total_flags == 0:
            f.write("\n✅ All checks passed.\n")
    print(f"\nReport written to {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Verify ECE rankings pipeline data quality.")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], default=None,
                        help="Run a specific phase only (1=harvest, 2=normalize, 3=aggregate)")
    parser.add_argument("--all", action="store_true", help="Run all three phases")
    parser.add_argument("--area", type=str, default=None,
                        help="Filter to a single area key (e.g. 'architecture') or 'all'")
    parser.add_argument("--report", action="store_true", help="Write report to data/reports/")
    args = parser.parse_args()

    if not args.all and not args.phase:
        parser.print_help()
        sys.exit(1)

    # Validate area filter
    areas = json.load(open(AREAS_JSON))
    if args.area and args.area != "all" and args.area not in areas["areas"]:
        print(f"Unknown area: {args.area}. Known areas: {list(areas['areas'].keys())}", file=sys.stderr)
        sys.exit(1)

    all_flags = {}

    if args.all or args.phase == 1:
        all_flags["Phase 1: Harvest Integrity"] = phase1_harvest(areas, args)
    if args.all or args.phase == 2:
        all_flags["Phase 2: Normalization Integrity"] = phase2_normalization(areas, args)
    if args.all or args.phase == 3:
        all_flags["Phase 3: Aggregate Integrity"] = phase3_aggregate(areas, args)

    # Summary
    print("\n" + "=" * 60)
    total = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for phase_name, flags in all_flags.items():
        phase_total = sum(len(v) for v in flags.values())
        crit = len(flags.get("critical", []))
        high = len(flags.get("high", []))
        med = len(flags.get("medium", []))
        total["critical"] += crit
        total["high"] += high
        total["medium"] += med
        total["low"] += len(flags.get("low", []))
        print(f"{phase_name}: {crit}c {high}h {med}m  ({phase_total} total)")

    print(f"\nTOTAL: {total['critical']} critical, {total['high']} high, "
          f"{total['medium']} medium, {total['low']} low")

    # Print flux-critical/high items
    if total["critical"]:
        print("\n🔴 CRITICAL:")
        for phase_name, flags in all_flags.items():
            for item in flags.get("critical", []):
                print(f"  {item}")

    if total["high"]:
        print("\n🟠 HIGH:")
        for phase_name, flags in all_flags.items():
            for item in flags.get("high", []):
                print(f"  {item}")

    if args.report:
        write_report(all_flags, args)


if __name__ == "__main__":
    main()
