#!/usr/bin/env python3
"""Global audit: the short list of findings that move published rankings.

verify.py phases 1-3 flag every venue-year on fixed thresholds, by design, so
a healthy corpus still carries hundreds of findings. This phase answers a
different question: across the whole corpus, which problems change what a
reader sees, and by how much credit? Each check aggregates to one line per
venue or institution and ranks by credit affected.

It exists because a manual audit on 2026-11-12 found all of the following
live in the published data while phases 1-3 either missed them or buried them:

  G1  a raw affiliation naming one country, mapped to an institution in
      another (Southeast University, Nanjing -> Southeast University, BD);
  G2  a company string credited to a university through a city name
      (Sony ..., Kanagawa -> Kanagawa University);
  G3  a venue with no data for a year inside the default ranking window
      (ICRA 2022, CDC 2025);
  G4  a venue-year whose credited share collapses against the venue's own
      norm (CLEO 2025 at 8% against ~80%);
  G5  a venue-year whose paper count is far off its neighbours (ICASSP 2005
      at 4,658 from digitised back-catalogue; INFOCOM 2026 at 603 vs 272);
  G6  a venue where single-author items carry a large share of credit
      (News & Views in the Nature-family journals);
  G7  front-matter records that carry authors, so chairs get credit
      (ISSCC "Session N overview");
  G8  aggregate rows in years that only a few venues cover, which stretch
      the site's year range (1981-2015 from two venues);
  G9  reference lists that cannot fail: known-strong IDs that appear nowhere
      in the data, and a missing or empty adjudication trap file;
  G10 credit that aggregate.py drops without a trace, by reason: map rows
      retyped to a non-credit type (UC Riverside stored as "other"), OpenAlex
      institutions with no type (Tampere University), venues where most
      authors carry no affiliation, and works nothing ever retried.

Run through verify.py (`--all` or `--phase 4`), or directly:
    python3 pipeline/verify_global.py [--cache-dir DIR] [--data-dir DIR]

Read-only. Python stdlib only.
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workkey import work_key, record_key  # noqa: E402
from affiliation_evidence import country_contradiction, countries_named, looks_like_company  # noqa: E402,F401

import dropped_credit  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
SITE_DATA = os.path.join(REPO_ROOT, "site", "data")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
KNOWN_JSON = os.path.join(REPO_ROOT, "data", "known-strong.json")
TRAPS_CSV = os.path.join(REPO_ROOT, "data", "adjudication-traps.csv")
EXCLUDED_CSV = os.path.join(REPO_ROOT, "data", "excluded-works.csv")
FIRST_YEARS_JSON = os.path.join(REPO_ROOT, "data", "source-first-years.json")

WINDOW_YEARS = 10            # the site's default range ends at the latest complete year

# G1/G2: approximate credits moved to one institution before it is worth a line.
MISMAP_CRITICAL = 25.0
MISMAP_HIGH = 5.0
# G4: credited share relative to the venue's own median.
COVERAGE_CRITICAL_RATIO = 0.4
COVERAGE_HIGH_RATIO = 0.7
COVERAGE_MIN_PAPERS = 30
# G5: paper count relative to the median of the nearest years.
COUNT_HIGH_RATIO = 2.0
COUNT_LOW_RATIO = 0.5
COUNT_SPIKE_RATIO = 1.5      # ...and this far above the adjacent year, so steady growth is not a spike
COUNT_NEIGHBOURS = 3
COUNT_MIN_MEDIAN = 20
COUNT_RAMP_YEARS = 2         # a venue's first years are small because it is new
# G6: share of a venue's education credit that comes from single-author works.
SOLO_CREDIT_CRITICAL = 20.0
SOLO_CREDIT_HIGH = 10.0
SOLO_MIN_WORKS = 100
# G7: front-matter records with authors, per venue, inside the window.
FRONT_MATTER_HIGH = 10
# G8: a year counts as covered when this share of the default venues has rows.
SPARSE_YEAR_SHARE = 0.25

NONRESEARCH_TYPES = {"editorial", "erratum", "letter", "book-review", "peer-review", "retraction", "other"}

FRONT_MATTER_RE = re.compile(
    r"^\s*(?:session\b|keynote|plenary|panel\b|tutorial\b|foreword|preface|welcome|message from|"
    r"in memoriam|short course|table of contents|author index|front matter|title page|"
    r".*\bevening (?:panel|session)\b)", re.I)


def empty_flags():
    return {"critical": [], "high": [], "medium": [], "low": []}


def load_map(path):
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as handle:
        return {row["raw_affiliation"]: row for row in csv.DictReader(handle)}


def load_exclusions(path):
    if not os.path.exists(path):
        return set()
    with open(path) as handle:
        return {(row.get("work_key") or "").strip() for row in csv.DictReader(handle)} - {""}


def latest_complete_year(data_dir):
    try:
        with open(os.path.join(data_dir, "manifest.json")) as handle:
            year = int(json.load(handle)["latest_complete_year"])
        if 1900 < year <= date.today().year:
            return year
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return date.today().year - 1


def accepted_education(row):
    return bool(row) and row.get("status") in ("auto", "manual") and row.get("institution_type") == "education" \
        and bool(row.get("institution_id"))


def scan_cache(cache_dir, venues, affil_map, excluded):
    """One pass over the cache. Returns per-venue-year stats and map usage."""
    stats = {}                      # (venue, year) -> Counter
    usage = Counter()               # raw string -> approximate credits resolved through the map
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
            c = Counter()
            with open(path) as handle:
                for line in handle:
                    work = json.loads(line)
                    identity = record_key(work, venue, year)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if (work.get("type") or "").lower() in NONRESEARCH_TYPES:
                        continue
                    if work_key(work, venue, year) in excluded:
                        continue
                    authors = work.get("authorships") or []
                    if not authors:
                        continue
                    c["papers"] += 1
                    weight = 1.0 / len(authors)
                    credited = 0.0
                    for author in authors:
                        institutions = author.get("institutions") or []
                        if institutions:
                            if any(i.get("type") == "education" for i in institutions):
                                credited += weight
                            continue
                        hits = [raw for raw in author.get("raw_affiliations") or []
                                if accepted_education(affil_map.get(raw))]
                        if hits:
                            credited += weight
                            for raw in hits:
                                usage[raw] += weight / len(hits)
                    c["credit"] += credited
                    if len(authors) == 1:
                        c["solo"] += 1
                        c["solo_credit"] += credited
                    if FRONT_MATTER_RE.match(work.get("title") or ""):
                        c["front_matter"] += 1
                        c["front_matter_credit"] += credited
            stats[(venue, year)] = c
    return stats, usage


def grade(amount, critical, high):
    return "critical" if amount >= critical else "high" if amount >= high else None


def check_mismapped(flags, affil_map, usage):
    """G1 and G2: accepted education rows the raw string itself contradicts."""
    for label, test in (("country", lambda raw, row: country_contradiction(raw, row.get("country_code"))),
                        ("company", lambda raw, row: looks_like_company(raw))):
        by_target = defaultdict(lambda: [0.0, 0, "", 0.0])   # credit, rows, example, example credit
        for raw, row in affil_map.items():
            if not accepted_education(row):
                continue
            evidence = test(raw, row)
            if not evidence:
                continue
            entry = by_target[(row.get("institution_name", ""), row.get("country_code", ""))]
            credit = usage.get(raw, 0.0)
            entry[0] += credit
            entry[1] += 1
            if credit >= entry[3]:
                entry[2], entry[3] = raw, credit
        tail_credit, tail_rows = 0.0, 0
        for (name, cc), (credit, rows, example, _) in sorted(by_target.items(), key=lambda kv: -kv[1][0]):
            severity = grade(credit, MISMAP_CRITICAL, MISMAP_HIGH)
            if severity is None:
                tail_credit += credit
                tail_rows += rows
                continue
            what = ("raw strings name another country" if label == "country"
                    else "company strings credited to this university")
            flags[severity].append(
                f"[map/{label}] {name} ({cc or '??'}): ~{credit:.0f} credits from {rows} rows where {what}"
                f" — e.g. {example[:90]!r}")
        if tail_rows:
            flags["medium"].append(
                f"[map/{label}] {tail_rows} more rows (~{tail_credit:.0f} credits) below {MISMAP_HIGH:.0f} credits"
                f" per institution")


def is_biennial(years):
    return len(years) >= 3 and len({y % 2 for y in years}) == 1 and all(
        b - a == 2 for a, b in zip(years, years[1:]))


def check_missing_years(flags, registry, stats, window, first_years):
    """G3: a default-on venue with no data for a year inside the window."""
    start, end = window
    for area_key, area in registry["areas"].items():
        default_on = area.get("default_on") is True
        for venue in area["venues"]:
            key = venue["key"]
            have = sorted(y for (v, y), c in stats.items() if v == key and c["papers"] > 0)
            in_window = [y for y in have if start <= y <= end]
            if not in_window:
                flags["critical" if default_on else "medium"].append(
                    f"[{area_key}/{key}] no papers in {start}–{end}")
                continue
            if is_biennial(in_window):
                continue
            declared = venue.get("years") or {}
            first = max(start, int(first_years.get(key, start)))
            missing = [y for y in range(first, end + 1) if y not in have
                       and (declared.get(str(y)) or {}).get("source") != "none"]
            if missing:
                flags["high" if default_on else "medium"].append(
                    f"[{area_key}/{key}] no papers for {_ranges(missing)} (default window {start}–{end});"
                    f" harvest them or mark the gap in data/areas.json with source \"none\"")


def _ranges(years):
    out, run = [], [years[0], years[0]]
    for y in years[1:]:
        if y == run[1] + 1:
            run[1] = y
        else:
            out.append(run)
            run = [y, y]
    out.append(run)
    return ", ".join(str(a) if a == b else f"{a}–{b}" for a, b in out)


def check_venue_years(flags, registry, stats, window):
    """G4 and G5: a venue-year far from the venue's own norm."""
    start, end = window
    default_venues = {v["key"] for a in registry["areas"].values() if a.get("default_on") is True
                      for v in a["venues"]}
    by_venue = defaultdict(dict)
    for (venue, year), c in stats.items():
        if c["papers"] > 0:
            by_venue[venue][year] = c
    for venue, years in sorted(by_venue.items()):
        ordered = sorted(years)
        shares = {y: 100.0 * years[y]["credit"] / years[y]["papers"] for y in ordered
                  if years[y]["papers"] >= COVERAGE_MIN_PAPERS}
        norm = statistics.median(shares.values()) if len(shares) >= 3 else None
        for y in ordered:
            visible = venue in default_venues and start <= y <= end
            # Unfinished years are expected to be thin on both counts.
            if y > end:
                continue
            if norm and y in shares and norm >= 20:
                ratio = shares[y] / norm
                severity = ("critical" if ratio < COVERAGE_CRITICAL_RATIO
                            else "high" if ratio < COVERAGE_HIGH_RATIO else None)
                if severity:
                    flags[severity if visible else "medium"].append(
                        f"[{venue}/{y}] {shares[y]:.0f}% of paper credit reaches a university;"
                        f" this venue's median is {norm:.0f}% ({years[y]['papers']} papers)")
            near = sorted((abs(o - y), o) for o in ordered if o != y and o <= end)[:2 * COUNT_NEIGHBOURS]
            near = [o for _, o in near if abs(o - y) <= 2 * COUNT_NEIGHBOURS]
            if len(near) >= 3:
                local = statistics.median(years[o]["papers"] for o in near)
                if local >= COUNT_MIN_MEDIAN:
                    ratio = years[y]["papers"] / local
                    later = [o for o in ordered if y < o <= end]
                    earlier = [o for o in ordered if o < y]
                    beside = years[later[0]] if later else years[earlier[-1]] if earlier else None
                    spike = ratio >= COUNT_HIGH_RATIO and (
                        beside is None or years[y]["papers"] >= COUNT_SPIKE_RATIO * beside["papers"])
                    dip = ratio <= COUNT_LOW_RATIO and ordered.index(y) >= COUNT_RAMP_YEARS
                    if spike or dip:
                        flags["high" if visible else "medium"].append(
                            f"[{venue}/{y}] {years[y]['papers']} papers, {ratio:.1f}× the median of"
                            f" nearby years ({local:.0f})")
    # The year after the window is partial, but a count far above the norm is still wrong.
    for venue, years in sorted(by_venue.items()):
        later = [y for y in years if y > end]
        inside = [years[y]["papers"] for y in years if end - 2 * COUNT_NEIGHBOURS < y <= end]
        if not later or len(inside) < 3:
            continue
        local = statistics.median(inside)
        last = years[max(o for o in years if o <= end)]["papers"]
        for y in later:
            if (local >= COUNT_MIN_MEDIAN and years[y]["papers"] / local >= COUNT_HIGH_RATIO
                    and years[y]["papers"] >= COUNT_SPIKE_RATIO * last):
                flags["high" if venue in default_venues else "medium"].append(
                    f"[{venue}/{y}] {years[y]['papers']} papers, {years[y]['papers'] / local:.1f}× the median of"
                    f" recent years ({local:.0f}); check against the official accepted count")


def check_nonresearch(flags, registry, stats, window):
    """G6 and G7: credit that comes from items which are not research papers."""
    start, end = window
    for area_key, area in registry["areas"].items():
        default_on = area.get("default_on") is True
        for venue in area["venues"]:
            key = venue["key"]
            total = Counter()
            for (v, y), c in stats.items():
                if v == key and start <= y <= end:
                    total.update(c)
            if total["papers"] >= SOLO_MIN_WORKS and total["credit"] > 0:
                share = 100.0 * total["solo_credit"] / total["credit"]
                severity = ("critical" if share >= SOLO_CREDIT_CRITICAL
                            else "high" if share >= SOLO_CREDIT_HIGH else None)
                if severity:
                    flags[severity if default_on else "medium"].append(
                        f"[{area_key}/{key}] {share:.0f}% of university credit ({total['solo_credit']:.0f} of"
                        f" {total['credit']:.0f}) comes from {total['solo']} single-author items;"
                        f" check for News & Views, columns and commentary")
            if total["front_matter"] >= FRONT_MATTER_HIGH:
                flags["high" if default_on else "medium"].append(
                    f"[{area_key}/{key}] {total['front_matter']} front-matter records carry authors"
                    f" (~{total['front_matter_credit']:.0f} credits): session overviews, keynotes, forewords")


def check_aggregate_years(flags, registry, data_dir, window):
    """G8: published rows in years that most default venues do not cover."""
    path = os.path.join(data_dir, "inst-venue-year.csv")
    if not os.path.exists(path):
        flags["medium"].append(f"[aggregate] {path} not found; year-coverage check skipped")
        return
    default_venues = {v["key"] for a in registry["areas"].values() if a.get("default_on") is True
                      for v in a["venues"]}
    venues_by_year = defaultdict(set)
    rows_by_year = Counter()
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            if row["venue"] in default_venues:
                year = int(row["year"])
                venues_by_year[year].add(row["venue"])
                rows_by_year[year] += 1
    if not venues_by_year:
        return
    need = max(1, round(SPARSE_YEAR_SHARE * len(default_venues)))
    sparse = sorted(y for y, venues in venues_by_year.items() if len(venues) < need and y < window[0])
    if sparse:
        venues = sorted(set().union(*(venues_by_year[y] for y in sparse)))
        flags["high"].append(
            f"[aggregate] {sum(rows_by_year[y] for y in sparse)} published rows in {_ranges(sparse)} come from"
            f" only {len(venues)} of {len(default_venues)} default venues ({', '.join(venues[:6])}"
            f"{'…' if len(venues) > 6 else ''}); they stretch the site's year range")


def check_reference_lists(flags, data_dir):
    """G9: tripwires that cannot trip."""
    credited = set()
    path = os.path.join(data_dir, "inst-area-year.csv")
    if os.path.exists(path):
        with open(path, newline="") as handle:
            credited = {row["institution_id"] for row in csv.DictReader(handle)}
    index = {}
    try:
        with open(os.path.join(data_dir, "institutions.json")) as handle:
            index = json.load(handle)
    except (OSError, ValueError):
        pass
    if os.path.exists(KNOWN_JSON) and credited:
        with open(KNOWN_JSON) as handle:
            known = json.load(handle)
        ids = sorted({i for values in known.values() if isinstance(values, list) for i in values
                      if isinstance(i, str) and i.startswith("http")})
        unknown = [i for i in ids if i not in credited and i not in index]
        if unknown:
            flags["critical"].append(
                f"[known-strong] {len(unknown)} IDs appear nowhere in the data, so their tripwires can never"
                f" pass: {', '.join(i.rsplit('/', 1)[-1] for i in unknown)}")
    traps = 0
    if os.path.exists(TRAPS_CSV):
        with open(TRAPS_CSV, newline="") as handle:
            traps = sum(1 for _ in csv.DictReader(handle))
    if not traps:
        flags["critical"].append(
            f"[traps] {os.path.relpath(TRAPS_CSV, REPO_ROOT)} is missing or empty; `adjudication.py check`"
            f" passes with nothing to check, so a fixed mapping can silently regress")


# G10: dropped credit. Bugs are graded by the credit one institution loses.
DROP_BUG_CRITICAL = MISMAP_CRITICAL
DROP_BUG_HIGH = MISMAP_HIGH
# A venue whose authors mostly carry no affiliation at all.
NOAFF_HIGH_SHARE, NOAFF_HIGH_CREDIT = 0.25, 500.0
NOAFF_MEDIUM_SHARE, NOAFF_MEDIUM_CREDIT = 0.10, 100.0
STALE_WORKS_MEDIUM = 100     # works in one venue-year that nothing ever retried


def check_dropped_credit(flags, result):
    """G10: credit the aggregator drops, split into bugs and judgement calls."""
    total = result["total"] or 1.0
    for reason in dropped_credit.BUGS:
        for name, credit in result["institutions"][reason].most_common():
            severity = grade(credit, DROP_BUG_CRITICAL, DROP_BUG_HIGH) or ("medium" if credit >= 1.0 else None)
            if severity:
                what = ("its map rows are typed as a non-credit type but the index says education"
                        if reason == "retyped_row" else "OpenAlex gives it no type but the index says education")
                flags[severity].append(f"[drop/{reason.split('_')[0]}] {name}: ~{credit:.0f} credits dropped; {what}")
    for venue, counts in sorted(result["by_venue"].items(), key=lambda kv: -sum(
            v for k, v in kv[1].items() if k.startswith("no_affiliation"))):
        venue_total = counts["total"] or 1.0
        none = sum(v for k, v in counts.items() if k.startswith("no_affiliation"))
        share = none / venue_total
        severity = ("high" if share >= NOAFF_HIGH_SHARE and none >= NOAFF_HIGH_CREDIT else
                    "medium" if share >= NOAFF_MEDIUM_SHARE and none >= NOAFF_MEDIUM_CREDIT else None)
        if severity:
            never = counts["no_affiliation:never_backfilled"]
            flags[severity].append(
                f"[drop/no-affiliation] {venue}: {share:.0%} of its credit ({none:.0f}) has no affiliation anywhere"
                f" in the cache; {never:.0f} of it was never retried (check_stale_affiliations.py measures how much"
                f" OpenAlex has now)")
    for (venue, year), n in result["stale_works"].most_common():
        if n >= STALE_WORKS_MEDIUM:
            flags["medium"].append(
                f"[drop/stale] {venue} {year}: {n} works where every author lacks an affiliation and the backfill"
                f" never retried them")
    parts = ", ".join(f"{reason} {100 * credit / total:.1f}%" for reason, credit in result["reasons"].most_common())
    flags["low"].append(f"[drop/summary] dropped credit by reason (default-on areas): {parts}")


def run(registry, cache_dir=None, data_dir=None, area=None):
    """Run every global check. Returns the usual {severity: [messages]} flags."""
    cache_dir = cache_dir or CACHE_DIR
    data_dir = data_dir or SITE_DATA
    if area and area != "all":
        registry = {**registry, "areas": {area: registry["areas"][area]}}
    flags = empty_flags()
    latest = latest_complete_year(data_dir)
    window = (latest - WINDOW_YEARS + 1, latest)
    affil_map = load_map(MAP_CSV)
    first_years = {}
    if os.path.exists(FIRST_YEARS_JSON):
        with open(FIRST_YEARS_JSON) as handle:
            first_years = json.load(handle)
    venues = [v["key"] for a in registry["areas"].values() for v in a["venues"]]
    stats, usage = scan_cache(cache_dir, venues, affil_map, load_exclusions(EXCLUDED_CSV))

    print(f"\n── Phase 4: Global audit (window {window[0]}–{window[1]}) ──")
    check_mismapped(flags, affil_map, usage)
    check_missing_years(flags, registry, stats, window, first_years)
    check_venue_years(flags, registry, stats, window)
    check_nonresearch(flags, registry, stats, window)
    check_aggregate_years(flags, registry, data_dir, window)
    check_reference_lists(flags, data_dir)
    if os.path.exists(dropped_credit.INDEX_JSON):
        affil, types = dropped_credit.load_context()
        check_dropped_credit(flags, dropped_credit.scan(
            cache_dir, registry, affil, types, load_exclusions(EXCLUDED_CSV), dropped_credit.load_negative()))
    else:
        flags["medium"].append("[drop] data/institutions.json is missing, so dropped credit could not be classified")
    print(f"  {len(flags['critical'])} critical, {len(flags['high'])} high, {len(flags['medium'])} medium")
    return flags


def main():
    parser = argparse.ArgumentParser(description="Global audit of the ECERankings corpus.")
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    parser.add_argument("--data-dir", default=SITE_DATA)
    parser.add_argument("--areas-json", default=AREAS_JSON, help="Path to areas registry (default: data/areas.json)")
    parser.add_argument("--area", default=None)
    args = parser.parse_args()
    with open(args.areas_json) as handle:
        registry = json.load(handle)
    flags = run(registry, os.path.realpath(args.cache_dir), os.path.realpath(args.data_dir), args.area)
    for severity, icon in (("critical", "🔴"), ("high", "🟠"), ("medium", "🟡")):
        if flags[severity]:
            print(f"\n{icon} {severity.upper()}:")
            for item in flags[severity]:
                print(f"  {item}")
    return 2 if flags["critical"] or flags["high"] else 0


if __name__ == "__main__":
    sys.exit(main())
