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
import re
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workkey import work_key  # noqa: E402  (shared work-identity helper)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
SITE_DATA = os.path.join(REPO_ROOT, "site", "data")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
KNOWN_JSON = os.path.join(REPO_ROOT, "data", "known-strong.json")
INST_JSON = os.path.join(REPO_ROOT, "data", "institutions.json")
REPORTS_DIR = os.path.join(REPO_ROOT, "data", "reports")
COVERAGE_SNAPSHOT = os.path.join(SITE_DATA, ".coverage-snapshot.json")

# Severity thresholds for the coverage/purity/lineage scorecard. Every
# venue-year is flagged on absolute thresholds EVERY run (no suppression
# for known-permanent external gaps, e.g. pre-2021 IEEE Crossref metadata
# gaps) -- by explicit project decision, so nothing is silently
# deprioritized. Regressions (any drop vs. the last recorded snapshot) are
# flagged separately and more urgently, since those indicate something
# that used to work has broken (e.g. the CLEO 2023 OpenAlex->Crossref
# source switch that silently zeroed out affiliation coverage).
COVERAGE_HIGH = 50      # < this %: high severity
COVERAGE_MEDIUM = 80    # < this %: medium severity
PURITY_HIGH = 30
PURITY_MEDIUM = 60
RESOLUTION_HIGH = 50
RESOLUTION_MEDIUM = 80
NESTED_LINEAGE_HIGH = 20    # global % of distinct institutions
NESTED_LINEAGE_MEDIUM = 10
REGRESSION_EPSILON = 0.5    # pp; below this is float/rounding noise, not a real drop
REGRESSION_CRITICAL_DROP = 50
REGRESSION_HIGH_DROP = 10

# ── Under-collection thresholds (added 2026-07-25) ────────────────────
# These close a blind spot that let the `ml` area ship in the live default
# selection while NeurIPS and ICLR had ZERO works harvested and ICML was 88%
# missing affiliations. Every pre-existing check passed: the known-strong
# tripwire only asserts non-zero, and Stanford/MIT/CMU/Berkeley/UCLA all had
# non-zero counts off the ~8% of ICML that did resolve. Nothing asked whether
# the area had enough data to rank at all.
AREA_GAP_CRITICAL = 50   # % of an area's author slots with NO affiliation signal
AREA_GAP_HIGH = 25
AREA_GAP_MEDIUM = 15
# Relative floor: an area holding a small fraction of the median area's
# institution count is under-collected, not merely niche. Relative rather than
# absolute so it self-calibrates as the corpus grows.
AREA_INST_CRITICAL_FRAC = 0.15
AREA_INST_HIGH_FRAC = 0.30

# ── Non-research contamination (added 2026-07-25) ─────────────────────
# Adjusted count is 1/N per author, so a single-author non-research item earns
# its institution a full 1.0 -- 4x what an author gets on a 4-author paper.
# 66 single-author science-fiction columns in Science Robotics were enough to
# put one institution at #1 in that venue at double the runner-up. Single
# authorship is a PRIOR, not a verdict: tit (8.2%) and automatica (6.2%) are
# theory venues where solo-authored research is entirely normal. So this only
# flags venues for review; pipeline/detect_editorials.py does the semantic
# scoring and a human curates data/excluded-works.csv.
SOLO_SHARE_HIGH = 15     # % of a venue's credited works that are single-author
SOLO_SHARE_MEDIUM = 8
SOLO_MIN_WORKS = 200     # below this, the share is too noisy to act on
# Titles that are non-research on their face. Cheap stdlib backstop for items
# the semantic pass hasn't been run on yet.
NONRESEARCH_TITLE_RE = re.compile(
    r"\b(editorial|erratum|corrigendum|obituary|in memoriam|book review|"
    r"news and views|in this issue|retraction of|letter to the editor)\b", re.I)


# ════════════════════════════════════════════════════════════════════
# Shared: affiliation map + one-pass authorship quality scan
# ════════════════════════════════════════════════════════════════════

def load_affiliation_map_dict():
    """Load affiliation-map.csv as {raw_affiliation: row} for resolution lookups."""
    mapping = {}
    if not os.path.exists(MAP_CSV):
        return mapping
    with open(MAP_CSV, newline="") as f:
        for r in csv.DictReader(f):
            mapping[r["raw_affiliation"]] = r
    return mapping


def raw_affiliations_resolve_to_education(raw_affils, affil_map):
    """True if ANY raw affiliation string resolves to a mapped education institution."""
    for raw in raw_affils:
        row = affil_map.get(raw)
        if row and row.get("status") in ("auto", "manual") and row.get("institution_type") == "education":
            return True
    return False


def compute_quality_scan(areas, args, affil_map):
    """One pass over every cached work, classifying each authorship into:
      - native_clean:  institutions[] resolved AND unambiguous lineage (len 1)
                        AND has country_code AND has type  ("perfect")
      - native_flawed: institutions[] resolved but lineage is ambiguous
                        (len > 1) or missing country_code/type
      - raw_resolved:  no native institutions, but raw_affiliations resolves
                        to a mapped education institution
      - raw_unresolved: raw_affiliations present but none resolve
      - empty:         neither institutions[] nor raw_affiliations present

    Returns per-(venue,year) stats, a global rollup, and a registry of
    nested-lineage institutions (id -> {count, name}) for Phase 2's
    ambiguous-lineage check.
    """
    v2a = {}
    for ak, area in areas["areas"].items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        for v in area["venues"]:
            v2a[v["key"]] = ak

    vy_stats = {}  # (vkey, year) -> counts dict
    nested_institutions = {}  # inst_id -> {"count": n, "name": str}

    def blank():
        return {"total": 0, "native_clean": 0, "native_flawed": 0,
                "raw_resolved": 0, "raw_unresolved": 0, "empty": 0}

    for vkey in sorted(v2a):
        vdir = os.path.join(CACHE_DIR, vkey)
        if not os.path.isdir(vdir):
            continue
        for yd in sorted(os.listdir(vdir)):
            if not yd.isdigit():
                continue
            wf = os.path.join(vdir, yd, "works.jsonl")
            if not os.path.exists(wf):
                continue
            year = int(yd)
            key = (vkey, year)
            vy_stats[key] = blank()
            s = vy_stats[key]

            with open(wf) as f:
                for line in f:
                    w = json.loads(line)
                    for a in w.get("authorships", []):
                        s["total"] += 1
                        insts = a.get("institutions") or []
                        raw = a.get("raw_affiliations") or []

                        if insts:
                            clean = True
                            for inst in insts:
                                iid = inst.get("id")
                                lineage = inst.get("lineage") or [iid]
                                if len(lineage) > 1:
                                    clean = False
                                    entry = nested_institutions.setdefault(
                                        iid, {"count": 0, "name": inst.get("display_name", "")}
                                    )
                                    entry["count"] += 1
                                if not inst.get("country_code") or not inst.get("type"):
                                    clean = False
                            if clean:
                                s["native_clean"] += 1
                            else:
                                s["native_flawed"] += 1
                        elif raw:
                            if raw_affiliations_resolve_to_education(raw, affil_map):
                                s["raw_resolved"] += 1
                            else:
                                s["raw_unresolved"] += 1
                        else:
                            s["empty"] += 1

    # Global rollup
    global_stats = blank()
    for s in vy_stats.values():
        for k in global_stats:
            global_stats[k] += s[k]

    return vy_stats, global_stats, nested_institutions


def pct(numer, denom):
    return 100.0 * numer / denom if denom else 0.0


def coverage_pct(s):
    """Any affiliation signal at all (native or raw), regardless of quality."""
    return pct(s["native_clean"] + s["native_flawed"] + s["raw_resolved"] + s["raw_unresolved"], s["total"])


def purity_pct(s):
    """Strict 'perfect record' rate: native-resolved, unambiguous, complete."""
    return pct(s["native_clean"], s["total"])


def resolution_pct(s):
    """Of raw-affiliation-only authorships, how many resolved to a real institution.
    None if this venue-year has no raw-only authorships to score (e.g. purely
    OpenAlex-native, or purely empty)."""
    raw_total = s["raw_resolved"] + s["raw_unresolved"]
    if raw_total == 0:
        return None
    return pct(s["raw_resolved"], raw_total)


def is_native_capable(s):
    """Whether this venue-year has ever produced OpenAlex-native institutions
    (vs. being structurally Crossref/S2-only, which can never hit 'purity')."""
    return (s["native_clean"] + s["native_flawed"]) > 0


def load_snapshot():
    if os.path.exists(COVERAGE_SNAPSHOT):
        with open(COVERAGE_SNAPSHOT) as f:
            return json.load(f)
    return None


def save_snapshot(vy_stats, global_stats, nested_institutions, affil_map):
    data = {
        "generated": date.today().isoformat(),
        "global": {
            "coverage_pct": round(coverage_pct(global_stats), 2),
            "purity_pct": round(purity_pct(global_stats), 2),
            "resolution_pct": round(resolution_pct(global_stats), 2) if resolution_pct(global_stats) is not None else None,
        },
        "venue_years": {
            f"{vk}/{yr}": {
                "coverage_pct": round(coverage_pct(s), 2),
                "purity_pct": round(purity_pct(s), 2) if is_native_capable(s) else None,
                "resolution_pct": round(resolution_pct(s), 2) if resolution_pct(s) is not None else None,
            }
            for (vk, yr), s in vy_stats.items()
        },
    }
    with open(COVERAGE_SNAPSHOT, "w") as f:
        json.dump(data, f, indent=2)


# ════════════════════════════════════════════════════════════════════
# Phase 1: Harvest integrity
# ════════════════════════════════════════════════════════════════════

def phase1_harvest(areas, args, vy_stats, global_stats, prev_snapshot):
    """Check venue-year coverage, author completeness, affiliation coverage,
    and coverage regressions vs. the last recorded run."""
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

        # 1a-0. Registered but never harvested at all.
        # 1a below only fires for venues carrying an explicit `years` map, so a
        # venue registered with nothing but openalex_ids — NeurIPS and ICLR were
        # exactly this — produced no finding of any kind while contributing zero
        # papers to a default-on area.
        if not cached_years:
            flags["critical"].append(
                f"[{vkey}] registered in area '{ak}' (status={vdef.get('status', '?')}) "
                f"but has ZERO cached works — never harvested"
            )

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

            yr_str = str(yr)
            if yr_str in expected_years:
                expected_count = expected_years[yr_str].get("count")
                if expected_count and expected_floor:
                    pctf = count / expected_floor * 100 if expected_floor else 100
                    if pctf < 70:
                        flags["high"].append(
                            f"[{vkey}/{yr}] {count} papers ({pctf:.0f}% of floor {expected_floor})"
                        )
                    elif pctf < 90:
                        flags["medium"].append(
                            f"[{vkey}/{yr}] {count} papers ({pctf:.0f}% of floor {expected_floor})"
                        )

            # 1c. Author completeness
            if no_author > 0:
                flags["high"].append(
                    f"[{vkey}/{yr}] {no_author}/{count} works have zero authors"
                )

            # 1e. Title duplicates
            for title, pids in seen_titles.items():
                if len(pids) > 1 and len(title) > 10:
                    flags["medium"].append(
                        f"[{vkey}/{yr}] {len(pids)} papers with duplicate title: {title[:60]}..."
                    )

    # 1e-2. Non-research contamination sweep.
    # Rankings credit a single-author item at a full 1.0, so commentary counted
    # as a research paper is worth 4x a 4-author paper to its institution. This
    # does NOT decide anything -- it flags venues worth running
    # detect_editorials.py against, and names titles that are non-research on
    # their face and not yet excluded.
    excluded_keys = set()
    excl_csv = os.path.join(REPO_ROOT, "data", "excluded-works.csv")
    if os.path.exists(excl_csv):
        with open(excl_csv) as f:
            excluded_keys = {r["work_key"] for r in csv.DictReader(f) if r.get("work_key")}

    solo = defaultdict(int)
    credited_works = defaultdict(int)
    blatant = []
    for vkey in sorted(v2a):
        vdir = os.path.join(CACHE_DIR, vkey)
        if not os.path.isdir(vdir):
            continue
        for yd in sorted(os.listdir(vdir)):
            if not yd.isdigit():
                continue
            wf = os.path.join(vdir, yd, "works.jsonl")
            if not os.path.exists(wf):
                continue
            with open(wf) as f:
                for line in f:
                    try:
                        w = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    aus = w.get("authorships") or []
                    if not any(i.get("type") == "education"
                               for a in aus for i in (a.get("institutions") or [])):
                        continue
                    # Measure the share that SURVIVES exclusion -- otherwise the
                    # flag never clears no matter how much curation happens, and
                    # a stuck warning is one people learn to ignore.
                    k = work_key(w, vkey, yd)
                    if k in excluded_keys:
                        continue
                    credited_works[vkey] += 1
                    if len(aus) == 1:
                        solo[vkey] += 1
                    title = re.sub(r"<[^>]+>", "", w.get("title") or "")
                    if NONRESEARCH_TITLE_RE.search(title):
                        blatant.append((vkey, yd, title[:70]))

    if excluded_keys:
        print(f"  Exclusion list active: {len(excluded_keys)} works "
              f"(data/excluded-works.csv)")
    for vkey in sorted(credited_works, key=lambda k: -solo[k] / max(credited_works[k], 1)):
        n = credited_works[vkey]
        if n < SOLO_MIN_WORKS:
            continue
        share = solo[vkey] / n * 100
        if share < SOLO_SHARE_MEDIUM:
            continue
        msg = (f"[{vkey}] {share:.1f}% of credited works are single-author "
               f"({solo[vkey]}/{n}) — each earns a full 1.0; run "
               f"detect_editorials.py --venue {vkey} to check for commentary")
        flags["high" if share >= SOLO_SHARE_HIGH else "medium"].append(msg)

    for vkey, yd, title in blatant[:40]:
        flags["medium"].append(
            f"[{vkey}/{yd}] non-research title still credited: {title}")
    if len(blatant) > 40:
        flags["medium"].append(
            f"...and {len(blatant) - 40} more non-research titles "
            f"(truncated; run detect_editorials.py for the full list)")

    # 1f. Summary stats
    total_venue_years = sum(len(list(vdef.get("years", {}).keys())) for ak, vdef in v2a.values())
    cached_count = 0
    for vk in v2a:
        vdir = os.path.join(CACHE_DIR, vk)
        if not os.path.isdir(vdir):
            continue
        for yd in os.listdir(vdir):
            if yd.isdigit() and os.path.exists(os.path.join(vdir, yd, "works.jsonl")):
                cached_count += 1
    print(f"  Venue-years cached:   {cached_count}")
    print(f"  Venue-years expected: {total_venue_years}")

    # 1g. Coverage scorecard (any affiliation signal at all: native or raw).
    # ALWAYS flagged at absolute thresholds -- by explicit decision, known-
    # permanent external gaps (pre-2021 IEEE Crossref metadata, etc.) are not
    # suppressed. Every venue-year shows up every run.
    print(f"\n  Coverage (any affiliation signal): {coverage_pct(global_stats):.1f}% overall")
    n_flagged = 0
    for (vk, yr), s in sorted(vy_stats.items()):
        if args.area and args.area != "all" and v2a.get(vk, (None,))[0] != args.area:
            continue
        cov = coverage_pct(s)
        if s["total"] == 0:
            continue
        if cov < COVERAGE_HIGH:
            flags["high"].append(f"[{vk}/{yr}] coverage {cov:.0f}% ({s['total']} authorships)")
            n_flagged += 1
        elif cov < COVERAGE_MEDIUM:
            flags["medium"].append(f"[{vk}/{yr}] coverage {cov:.0f}% ({s['total']} authorships)")
            n_flagged += 1
    print(f"  Venue-years below {COVERAGE_MEDIUM}% coverage: {n_flagged}")

    # 1h. Coverage regression vs. last snapshot (ANY drop is flagged, per
    # explicit decision -- this is the check that would have caught CLEO's
    # 97%->0% collapse from the OpenAlex->Crossref source switch).
    if prev_snapshot:
        prev_vy = prev_snapshot.get("venue_years", {})
        regressions = []
        for (vk, yr), s in sorted(vy_stats.items()):
            key = f"{vk}/{yr}"
            prev = prev_vy.get(key)
            if not prev or prev.get("coverage_pct") is None:
                continue
            cur_cov = coverage_pct(s)
            drop = prev["coverage_pct"] - cur_cov
            if drop > REGRESSION_EPSILON:
                regressions.append((drop, vk, yr, prev["coverage_pct"], cur_cov))
        regressions.sort(reverse=True)
        for drop, vk, yr, prev_cov, cur_cov in regressions:
            msg = f"[{vk}/{yr}] coverage regression: {prev_cov:.1f}% -> {cur_cov:.1f}% ({drop:.1f}pp drop)"
            if drop >= REGRESSION_CRITICAL_DROP:
                flags["critical"].append(msg)
            elif drop >= REGRESSION_HIGH_DROP:
                flags["high"].append(msg)
            else:
                flags["medium"].append(msg)
        if regressions:
            print(f"  Coverage regressions vs. last snapshot: {len(regressions)}")
    else:
        print("  No prior snapshot -- this run establishes the coverage baseline.")

    return flags


# ════════════════════════════════════════════════════════════════════
# Phase 2: Normalization integrity
# ════════════════════════════════════════════════════════════════════

def phase2_normalization(areas, args, vy_stats, global_stats, nested_institutions, prev_snapshot):
    """Check resolution rate, type distribution, cluster misattributions,
    acronyms, ambiguous institution lineage, and purity/resolution regressions."""
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

    # 2a. Country code consistency check
    inst_countries = defaultdict(set)
    for r in rows:
        iid = r.get("institution_id", "")
        cc = r.get("country_code", "")
        if iid and cc:
            inst_countries[iid].add(cc)

    country_conflicts = 0
    for iid, ccs in inst_countries.items():
        if len(ccs) > 1:
            country_conflicts += 1
            if country_conflicts <= 10:
                sample = next((r for r in rows if r.get("institution_id") == iid), None)
                name = (sample.get("institution_name", "") if sample else "")[:40]
                flags["high"].append(
                    f"[{iid.split('/')[-1]}] {name} has conflicting country codes: {ccs}"
                )
    if country_conflicts > 10:
        flags["high"].append(f"... and {country_conflicts - 10} more institutions with conflicting country codes")

    # 2b. Geo-heuristic validation
    known_geo = {
        "US": ["University of California", "Georgia Tech", "MIT", "Stanford",
               "University of Texas", "University of Michigan", "Virginia Tech",
               "Purdue", "Carnegie Mellon", "Caltech", "University of Illinois",
               "University of Washington", "University of Wisconsin",
               "University of Maryland", "University of Minnesota",
               "University of Colorado", "University of Florida",
               "Ohio State", "Pennsylvania State", "Texas A&M",
               "University of Pennsylvania", "Columbia University",
               "Cornell University", "Princeton University",
               "University of Chicago", "Yale University", "Harvard University",
               "Duke University", "Northwestern University",
               "University of California San Diego", "UCSD",
               "University of California, Berkeley", "UCLA",
               "University of California, Los Angeles",
               "University of California, Irvine", "UC Irvine",
               "University of California, Santa Barbara",
               "University of California, Davis", "UC Davis",
               "University of California, Riverside",
               "Michigan State", "Arizona State", "University of Arizona",
               "University of Utah", "University of Colorado",
               "North Carolina State", "University of Pittsburgh",
               "University of Rochester", "Rutgers", "Boston University",
               "Northeastern University", "University of Florida",
               "University of Central Florida", "Florida State",
               "Johns Hopkins", "Rice University", "Vanderbilt",
               "Dartmouth", "Brown University"],
        "CN": ["Tsinghua", "Peking University", "Zhejiang University",
               "Shanghai Jiao Tong", "Fudan", "Nanjing University",
               "Huazhong", "Harbin Institute", "Beihang",
               "Xi'an Jiaotong", "Sun Yat-sen", "Southeast University",
               "Tianjin University", "Beijing Institute of Technology",
               "University of Electronic Science and Technology",
               "South China University", "University of Science and Technology Beijing",
               "Jilin University", "Nankai University", "Xiamen University",
               "Wuhan University", "Tongji University",
               "University of Chinese Academy of Sciences",
               "China Agricultural University"],
        "KR": ["Seoul National", "KAIST", "Korea University", "Yonsei",
               "POSTECH", "Sungkyunkwan", "Hanyang", "Gwangju Institute",
               "Ewha Womans", "Kyungpook", "Pusan National"],
        "SG": ["National University of Singapore", "Nanyang Technological",
               "Singapore University of Technology"],
        "JP": ["University of Tokyo", "Kyoto University", "Tokyo Institute",
               "Osaka University", "Nagoya University", "Tohoku University",
               "Kyushu University", "Hokkaido University", "Waseda",
               "Keio University", "Institute of Science Tokyo"],
        "CH": ["ETH Zurich", "EPFL", "University of Zurich"],
        "GB": ["University of Cambridge", "University of Oxford", "Imperial College",
               "University College London", "University of Edinburgh",
               "University of Manchester", "University of Southampton",
               "University of Birmingham", "University of Bristol",
               "University of Glasgow", "University of Sheffield",
               "University of Nottingham", "University of Leeds",
               "King's College London", "Queen Mary"],
        "DE": ["Technical University of Munich", "TU Munich",
               "RWTH Aachen", "Karlsruhe Institute", "KIT,",
               "TU Berlin", "TU Darmstadt", "TU Dresden",
               "University of Stuttgart", "University of Freiburg",
               "University of Bonn", "LMU Munich"],
        "FR": ["Sorbonne", "Université Paris", "CNRS",
               "École Polytechnique", "Grenoble INP",
               "Université Grenoble", "Institut polytechnique",
               "CentraleSupélec", "Télécom Paris"],
        "CA": ["University of Toronto", "University of British Columbia",
               "McGill University", "University of Waterloo",
               "University of Alberta", "University of Montreal",
               "McMaster University", "University of Calgary",
               "University of Ottawa", "Queen's University",
               "Simon Fraser University", "University of Victoria",
               "University of Western Ontario"],
        "TW": ["National Taiwan University", "National Tsing Hua",
               "National Yang Ming Chiao Tung", "National Cheng Kung",
               "National Chiao Tung"],
        "NL": ["Delft University", "TU Delft", "Eindhoven University",
               "University of Amsterdam", "University of Groningen",
               "Utrecht University", "Leiden University",
               "Wageningen University", "Vrije Universiteit Amsterdam"],
        "IL": ["Technion", "Weizmann", "Tel Aviv University",
               "Hebrew University of Jerusalem"],
        "AU": ["University of Melbourne", "University of Sydney",
               "UNSW Sydney", "Australian National University",
               "Monash University", "University of Queensland",
               "University of Adelaide", "University of Western Australia"],
        "SE": ["KTH Royal Institute", "Chalmers", "Lund University",
               "Uppsala University", "Stockholm University"],
        "DK": ["Technical University of Denmark", "DTU",
               "University of Copenhagen", "Aalborg University"],
        "FI": ["Aalto University", "University of Helsinki"],
        "IE": ["Trinity College Dublin", "University College Dublin"],
        "IT": ["Politecnico di Milano", "Politecnico di Torino",
               "Sapienza", "University of Bologna",
               "University of Padua", "University of Milan"],
        "ES": ["Polytechnic University of Catalonia", "UPC",
               "University of Barcelona", "Universidad Politécnica de Madrid"],
        "AT": ["TU Wien", "Johannes Kepler", "University of Vienna"],
        "BE": ["KU Leuven", "Ghent University", "Université Catholique de Louvain"],
        "IN": ["Indian Institute of Technology", "IIT "],
        "HK": ["University of Hong Kong", "Hong Kong University",
               "Hong Kong Polytechnic", "City University of Hong Kong",
               "Hong Kong University of Science"],
    }

    geo_conflicts = 0
    for r in rows:
        if r["status"] not in ("auto", "manual"):
            continue
        name = r.get("institution_name", "")
        actual_cc = r.get("country_code", "")
        if not name or not actual_cc:
            continue
        for expected_cc, keywords in known_geo.items():
            for kw in keywords:
                if kw.lower() in name.lower():
                    if actual_cc != expected_cc and actual_cc != "":
                        geo_conflicts += 1
                        if geo_conflicts <= 10:
                            flags["high"].append(
                                f"'{name[:45]}' has country={actual_cc}, expected {expected_cc} (contains '{kw}')"
                            )
                    break
            else:
                continue
            break
    if geo_conflicts > 10:
        flags["high"].append(f"... and {geo_conflicts - 10} more geo-heuristic violations")

    # 2c. Compound affiliation detection
    compound_flags = 0
    for r in rows:
        if r["status"] != "manual":
            continue
        raw = r.get("raw_affiliation", "")
        if any(sep in raw for sep in [" and ", " & ", " / "]):
            iid = r.get("institution_id", "")
            if iid:
                ccs = inst_countries.get(iid, set())
                if len(ccs) > 1:
                    compound_flags += 1
                    if compound_flags <= 5:
                        flags["medium"].append(
                            f"Compound affiliation likely: '{raw[:60]}' -> {r['institution_name'][:30]} (cc conflicts: {ccs})"
                        )
    if compound_flags > 0:
        print(f"  Compound affiliations flagged: {compound_flags}")

    # 2d. Acronym check
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

    # 2e. Campus cluster check (re-run the fixer and count changes)
    import subprocess
    cluster_script = os.path.join(REPO_ROOT, "pipeline", "fix_campus_clusters.py")
    if os.path.exists(cluster_script):
        result = subprocess.run(
            ["python3", cluster_script],
            capture_output=True, text=True, timeout=120
        )
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

    # 2e2. Acronym-collision and full-name-mismatch checks (dry-run the fixers).
    # These catch the two systematic semantic-matcher bug classes found
    # 2026-07-24: (1) ambiguous acronyms ("MIT", "KTH", "CNRS") resolved to an
    # arbitrary owner even when the raw string spells out the right full name;
    # (2) rows assigned to an institution with zero evidence in the raw string
    # while a different institution's full name matches a whole segment.
    for script_name, label in (
        ("fix_acronym_collisions.py", "acronym-collision"),
        ("fix_name_mismatches.py", "full-name-mismatch"),
    ):
        script = os.path.join(REPO_ROOT, "pipeline", script_name)
        if not os.path.exists(script):
            continue
        result = subprocess.run(
            ["python3", script],
            capture_output=True, text=True, timeout=600
        )
        n_fix = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("to fix:"):
                try:
                    n_fix = int(line.split(":")[1].strip())
                except ValueError:
                    pass
        if n_fix and n_fix > 0:
            flags["high"].append(
                f"{script_name} found {n_fix} {label} misattributions — run with --apply and re-aggregate"
            )

    # 2f. Ambiguous / nested institution lineage.
    # aggregate.py's docstring assumed ~5% of institutions have lineage
    # length > 1 (no reliable root) based on a small 133-institution pilot
    # (IEDM 2022). At full-corpus scale this is much higher -- verified
    # 2026-07-23: ~25% of distinct institutions, ~24% of occurrences. This
    # is a real, ongoing accuracy gap: those institutions are credited
    # unrolled (to their own id) rather than to their true parent, which
    # silently fragments a parent institution's score across itself and
    # its sub-entities. ALWAYS flagged (no suppression), per project
    # decision -- this is not yet fixable without a real lineage-root
    # resolution algorithm, but it must stay visible.
    n_nested = len(nested_institutions)
    print(f"\n  Ambiguous-lineage institutions (>1 element, no reliable parent): {n_nested}")
    if n_nested > 0:
        top_nested = sorted(nested_institutions.items(), key=lambda kv: -kv[1]["count"])[:15]
        print("  Top offenders by occurrence count:")
        for iid, info in top_nested:
            print(f"    {info['count']:6d}  {info['name'][:45]:45s} {iid}")
        nested_occurrences = sum(v["count"] for v in nested_institutions.values())
        global_native = global_stats["native_clean"] + global_stats["native_flawed"]
        nested_rate = pct(nested_occurrences, global_native) if global_native else 0
        msg = (f"{n_nested} distinct institutions have ambiguous lineage "
               f"({nested_occurrences} authorship occurrences, {nested_rate:.1f}% of native-resolved authorships)")
        if nested_rate >= NESTED_LINEAGE_HIGH:
            flags["high"].append(msg)
        elif nested_rate >= NESTED_LINEAGE_MEDIUM:
            flags["medium"].append(msg)
        else:
            flags["low"].append(msg)
        for iid, info in top_nested[:10]:
            flags["low"].append(f"  ambiguous lineage: {info['name'][:50]} ({iid}) — {info['count']} occurrences")

    # 2g. Purity & resolution scorecard (per venue-year), ALWAYS flagged at
    # absolute thresholds, plus regression vs. last snapshot (any drop).
    print(f"\n  Purity (native-clean 'perfect' rate): {purity_pct(global_stats):.1f}% overall")
    v2a = {}
    for ak, area in areas["areas"].items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        for v in area["venues"]:
            v2a[v["key"]] = ak

    n_purity_flagged = 0
    n_resolution_flagged = 0
    for (vk, yr), s in sorted(vy_stats.items()):
        if args.area and args.area != "all" and v2a.get(vk) != args.area:
            continue
        if s["total"] == 0:
            continue
        if is_native_capable(s):
            pur = purity_pct(s)
            if pur < PURITY_HIGH:
                flags["high"].append(f"[{vk}/{yr}] purity {pur:.0f}% (native-resolved but flawed lineage/metadata)")
                n_purity_flagged += 1
            elif pur < PURITY_MEDIUM:
                flags["medium"].append(f"[{vk}/{yr}] purity {pur:.0f}%")
                n_purity_flagged += 1
        else:
            res = resolution_pct(s)
            if res is not None:
                if res < RESOLUTION_HIGH:
                    flags["high"].append(f"[{vk}/{yr}] resolution {res:.0f}% of raw affiliations mapped to education institutions")
                    n_resolution_flagged += 1
                elif res < RESOLUTION_MEDIUM:
                    flags["medium"].append(f"[{vk}/{yr}] resolution {res:.0f}%")
                    n_resolution_flagged += 1
    print(f"  Venue-years below {PURITY_MEDIUM}% purity: {n_purity_flagged}")
    print(f"  Venue-years below {RESOLUTION_MEDIUM}% resolution: {n_resolution_flagged}")

    if prev_snapshot:
        prev_vy = prev_snapshot.get("venue_years", {})
        regressions = []
        for (vk, yr), s in sorted(vy_stats.items()):
            key = f"{vk}/{yr}"
            prev = prev_vy.get(key)
            if not prev:
                continue
            if is_native_capable(s) and prev.get("purity_pct") is not None:
                cur = purity_pct(s)
                drop = prev["purity_pct"] - cur
                if drop > REGRESSION_EPSILON:
                    regressions.append((drop, "purity", vk, yr, prev["purity_pct"], cur))
            elif not is_native_capable(s) and prev.get("resolution_pct") is not None:
                cur = resolution_pct(s)
                if cur is not None:
                    drop = prev["resolution_pct"] - cur
                    if drop > REGRESSION_EPSILON:
                        regressions.append((drop, "resolution", vk, yr, prev["resolution_pct"], cur))
        regressions.sort(reverse=True)
        for drop, metric, vk, yr, prev_v, cur_v in regressions:
            msg = f"[{vk}/{yr}] {metric} regression: {prev_v:.1f}% -> {cur_v:.1f}% ({drop:.1f}pp drop)"
            if drop >= REGRESSION_CRITICAL_DROP:
                flags["critical"].append(msg)
            elif drop >= REGRESSION_HIGH_DROP:
                flags["high"].append(msg)
            else:
                flags["medium"].append(msg)
        if regressions:
            print(f"  Purity/resolution regressions vs. last snapshot: {len(regressions)}")

    # 2z. Per-AREA affiliation gap.
    # The venue-year coverage scorecard above can look acceptable venue by venue
    # while an entire area is mostly blind, because a bad venue's slots are
    # diluted across many good venue-years. Rankings are computed per area and
    # combined by geometric mean, so a systematically blind area silently
    # distorts every institution's overall score. Roll the same scan up by area.
    v2a = {}
    for ak, area in areas["areas"].items():
        if args.area and args.area != "all" and ak != args.area:
            continue
        for v in area["venues"]:
            v2a[v["key"]] = ak

    area_empty = defaultdict(int)
    area_total = defaultdict(int)
    for (vkey, _yr), s in vy_stats.items():
        ak = v2a.get(vkey)
        if ak is None:
            continue
        area_empty[ak] += s["empty"]
        area_total[ak] += s["total"]

    if area_total:
        print("\n  Per-area affiliation gap (author slots with no institution and no raw string):")
        for ak in sorted(area_total, key=lambda k: -area_empty[k] / max(area_total[k], 1)):
            total = area_total[ak]
            if total == 0:
                continue
            gap = area_empty[ak] / total * 100
            default_on = areas["areas"][ak].get("default_on", False)
            tag = "" if default_on else "  (default_off)"
            print(f"    {ak:14s} {gap:5.1f}%  ({area_empty[ak]:,}/{total:,}){tag}")

            msg = (f"[{ak}] area is {gap:.1f}% missing affiliations "
                   f"({area_empty[ak]:,}/{total:,} author slots)")
            # A default-off area is a known-incomplete area the user has already
            # excluded from ranking, so the same gap is one severity lower —
            # flagged for visibility, not treated as a live ranking defect.
            if gap >= AREA_GAP_CRITICAL:
                flags["critical" if default_on else "high"].append(msg)
            elif gap >= AREA_GAP_HIGH:
                flags["high" if default_on else "medium"].append(msg)
            elif gap >= AREA_GAP_MEDIUM:
                flags["medium"].append(msg)

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

    # 3a-2. Under-collected areas.
    # Zero institutions is caught above, but the dangerous case is NON-zero and
    # far too small: `ml` shipped with 322 institutions against a ~1,700 median
    # and every existing check passed. Compare each area to the median rather
    # than a fixed floor so the test survives corpus growth.
    counts = {ak: len(v) for ak, v in area_insts.items() if v}
    if len(counts) >= 5:
        ordered = sorted(counts.values())
        median = ordered[len(ordered) // 2]
        for ak in sorted(counts, key=lambda k: counts[k]):
            n_insts = counts[ak]
            frac = n_insts / median if median else 1.0
            if frac >= AREA_INST_HIGH_FRAC:
                continue
            default_on = areas["areas"].get(ak, {}).get("default_on", False)
            msg = (f"[{ak}] only {n_insts} institutions credited vs median {median} "
                   f"({frac * 100:.0f}% of median) — area looks under-collected")
            if frac < AREA_INST_CRITICAL_FRAC:
                flags["critical" if default_on else "high"].append(msg)
            else:
                flags["high" if default_on else "medium"].append(msg)

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

    # 3f. Ranking regression check
    ranking_snapshot_path = os.path.join(SITE_DATA, ".ranking-snapshot.json")
    current_ranking = []
    inst_total = defaultdict(float)
    with open(inst_csv) as f:
        for r in csv.DictReader(f):
            inst_total[r["institution_id"]] += float(r.get("adjusted_count", 0))
    for iid, total in sorted(inst_total.items(), key=lambda x: -x[1]):
        current_ranking.append((iid, total, inst_names.get(iid, iid.split("/")[-1])))
    current_top50 = {iid: (rank, name) for rank, (iid, _, name) in enumerate(current_ranking[:50], 1)}

    if os.path.exists(ranking_snapshot_path):
        with open(ranking_snapshot_path) as f:
            prev_top50 = json.load(f)
        big_movers = []
        new_entries = []
        disappeared = []
        for iid, (cur_rank, name) in current_top50.items():
            prev_info = prev_top50.get(iid)
            if prev_info:
                prev_rank = prev_info["rank"]
                delta = prev_rank - cur_rank
                if abs(delta) >= 10:
                    big_movers.append((name, prev_rank, cur_rank, delta))
            else:
                new_entries.append((name, cur_rank))
        for iid, prev_info in prev_top50.items():
            if iid not in current_top50:
                disappeared.append((prev_info["name"], prev_info["rank"]))
        if big_movers:
            flags["medium"].append(f"Ranking regression: {len(big_movers)} institution(s) moved ≥10 positions:")
            for name, prev, cur, delta in big_movers[:10]:
                direction = "↑" if delta > 0 else "↓"
                flags["medium"].append(f"  {direction} {name}: #{prev} → #{cur}")
        if new_entries:
            flags["low"].append(f"New in top 50: {', '.join(n for n, _ in new_entries[:5])}")
        if disappeared:
            flags["low"].append(f"Dropped from top 50: {', '.join(n for n, _ in disappeared[:5])}")

    # Save current snapshot
    snapshot_data = {}
    for iid, (rank, name) in current_top50.items():
        snapshot_data[iid] = {"rank": rank, "name": name}
    with open(ranking_snapshot_path, "w") as f:
        json.dump(snapshot_data, f, indent=2)

    # 3g. Institution year-over-year cliff drops
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
                continue
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

def write_report(all_flags, args, global_stats=None):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    today = date.today().isoformat()
    path = os.path.join(REPORTS_DIR, f"verify-{today}.md")
    with open(path, "w") as f:
        f.write(f"# Verification Report — {today}\n\n")
        f.write(f"Area: {args.area or 'all'}  |  Phases: {args.phase or 'all'}\n\n")

        if global_stats:
            f.write("## Data Quality Scorecard\n\n")
            f.write(f"- Coverage (any affiliation signal): **{coverage_pct(global_stats):.1f}%**\n")
            f.write(f"- Purity (native-resolved, unambiguous, complete — \"perfect\"): **{purity_pct(global_stats):.1f}%**\n")
            res = resolution_pct(global_stats)
            if res is not None:
                f.write(f"- Resolution (raw-affiliation strings mapped to education institutions): **{res:.1f}%**\n")
            f.write("\n")

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

    areas = json.load(open(AREAS_JSON))
    if args.area and args.area != "all" and args.area not in areas["areas"]:
        print(f"Unknown area: {args.area}. Known areas: {list(areas['areas'].keys())}", file=sys.stderr)
        sys.exit(1)

    all_flags = {}

    # Phases 1 and 2 both need the same per-authorship quality scan
    # (coverage, purity, resolution, nested lineage). Compute it once and
    # share it, rather than re-scanning cache/ per phase.
    need_scan = args.all or args.phase in (1, 2)
    vy_stats = global_stats = nested_institutions = prev_snapshot = None
    if need_scan:
        print("Scanning cache/ for authorship quality (coverage/purity/lineage)...")
        affil_map = load_affiliation_map_dict()
        vy_stats, global_stats, nested_institutions = compute_quality_scan(areas, args, affil_map)
        prev_snapshot = load_snapshot()

    if args.all or args.phase == 1:
        all_flags["Phase 1: Harvest Integrity"] = phase1_harvest(areas, args, vy_stats, global_stats, prev_snapshot)
    if args.all or args.phase == 2:
        all_flags["Phase 2: Normalization Integrity"] = phase2_normalization(
            areas, args, vy_stats, global_stats, nested_institutions, prev_snapshot
        )
    if args.all or args.phase == 3:
        all_flags["Phase 3: Aggregate Integrity"] = phase3_aggregate(areas, args)

    # Persist the new snapshot AFTER both phases have diffed against the
    # previous one, so this run's regression checks compare against the
    # prior run, not against themselves.
    if need_scan:
        affil_map = load_affiliation_map_dict()
        save_snapshot(vy_stats, global_stats, nested_institutions, affil_map)

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
        write_report(all_flags, args, global_stats)


if __name__ == "__main__":
    main()
