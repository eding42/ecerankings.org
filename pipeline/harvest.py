#!/usr/bin/env python3
"""Harvest works from OpenAlex for a venue, one year at a time.

Usage:
    python3 pipeline/harvest.py --venue iedm --year 2022
    python3 pipeline/harvest.py --venue iedm --all-years
    python3 pipeline/harvest.py --venue jssc --year 2024
    python3 pipeline/harvest.py --venue jssc --year-range 2016 2025

Cache layout: cache/<venue_key>/<year>/works.jsonl, one JSON object per
line, checkpointed to cache/<venue_key>/<year>/.checkpoint after every page
so an interrupted run resumes instead of re-fetching. Harvesting is
year-granular by design: it mirrors how the venue registry (data/areas.json)
already tracks per-year source availability (some years are OpenAlex
sources, some are Crossref-only -- see pipeline/harvest_crossref.py for
those), and it means a multi-decade backfill can be done, inspected, and
re-run one year at a time instead of as one large unresumable-below-page-
granularity blob.

Source resolution per year, in priority order:
  1. If the venue has a `years[year]` entry in the registry with
     source == "openalex", use that year's specific source ID directly.
  2. If `years[year]` exists with source == "crossref", this script can't
     harvest it -- points you at harvest_crossref.py instead.
  3. Otherwise (no per-year entry -- true for journals, which have one
     source ID spanning all years, and for conferences not yet swept
     year-by-year): fall back to every registered `openalex_ids` entry,
     with an added `publication_year:<year>` filter. This is what makes
     journal harvesting year-chunked too, not just conferences.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
ENV_FILE = os.path.join(REPO_ROOT, ".env")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
API = "https://api.openalex.org"
MAILTO = "eding2019@gmail.com"
SELECT_FIELDS = "id,doi,title,publication_year,type,authorships"
PER_PAGE = 200


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def load_registry():
    with open(AREAS_JSON) as f:
        return json.load(f)


def find_venue(registry, venue_key):
    for area_key, area in registry["areas"].items():
        for venue in area["venues"]:
            if venue["key"] == venue_key:
                return area_key, venue
    return None, None


def api_get(path, params, api_key, retries=3):
    params = dict(params)
    params["mailto"] = MAILTO
    if api_key:
        params["api_key"] = api_key
    qs = urllib.parse.urlencode(params, safe=":,|*!")
    url = f"{API}{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": f"ecerankings-harvest (mailto:{MAILTO})"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(retry_after) if retry_after else 2 ** attempt)
                continue
            raise


def trim_work(w):
    authorships = []
    for a in w.get("authorships", []):
        author = a.get("author") or {}
        insts = []
        for i in a.get("institutions", []) or []:
            insts.append({
                "id": i.get("id"),
                "display_name": i.get("display_name"),
                "country_code": i.get("country_code"),
                "type": i.get("type"),
                "lineage": i.get("lineage"),
            })
        authorships.append({
            "author_id": author.get("id"),
            "author_name": author.get("display_name"),
            "institutions": insts,
        })
    return {
        "id": w.get("id"),
        "doi": w.get("doi"),
        "title": w.get("title"),
        "publication_year": w.get("publication_year"),
        "type": w.get("type"),
        "authorships": authorships,
    }


def resolve_year_sources(venue, year):
    """Return (source_ids, filter_extra, mode) for a given year.

    mode is "precise" (a per-year source ID, no extra filter needed) or
    "filtered" (one or more source IDs that span multiple years, so a
    publication_year filter is added). Returns (None, None, "crossref")
    if this year is registered as Crossref-only.

    NOTE: For journals, even a "precise" per-year source ID still spans all
    years of that journal — OpenAlex journals have ONE stable source ID. So we
    must still apply the publication_year filter. We detect journals by
    venue["kind"] == "journal" and force the year filter on regardless of mode.

    Some conferences (e.g. CLEO) turn out NOT to fragment into a distinct
    OpenAlex source per edition the way ISSCC/IEDM do -- they sit under one
    series-level source spanning many years, just like a journal. Trusting
    venue["kind"] alone for this would silently pull that source's ENTIRE
    multi-decade history for every single requested year (confirmed: CLEO
    2016 returned 31k works with no year filter, vs. ~2.1k expected). So
    regardless of kind, if the SAME source id is registered under more than
    one year entry, treat it like a journal and force the year filter on --
    a genuinely per-edition source id only ever appears under one year.
    """
    years = venue.get("years", {})
    entry = years.get(str(year))
    is_journal = venue.get("kind") == "journal"
    if entry:
        if entry["source"] == "openalex":
            sid = entry["id"]
            id_year_counts = {}
            for y, e in years.items():
                if e.get("source") == "openalex":
                    id_year_counts[e["id"]] = id_year_counts.get(e["id"], 0) + 1
            is_multi_year_source = id_year_counts.get(sid, 1) > 1
            year_filter = year if (is_journal or is_multi_year_source) else None
            return [sid], year_filter, "precise"
        return None, None, "crossref"
    # No per-year registry entry: fall back to filtering the venue's
    # general openalex_ids by publication_year (this is the journal path).
    ids = venue.get("openalex_ids", [])
    return ids, year, "filtered"


def harvest_year(venue_key, year, source_ids, year_filter, api_key):
    year_dir = os.path.join(CACHE_DIR, venue_key, str(year))
    os.makedirs(year_dir, exist_ok=True)
    out_path = os.path.join(year_dir, "works.jsonl")
    checkpoint_path = os.path.join(year_dir, ".checkpoint")

    source_key = "|".join(source_ids)
    cursor = "*"
    mode = "w"
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            state = json.load(f)
        if state.get("source_key") == source_key:
            if state.get("done"):
                print(f"  [{venue_key}/{year}] already complete ({state.get('count', '?')} works). Skipping.")
                return
            cursor = state.get("cursor", "*")
            mode = "a"
            print(f"  [{venue_key}/{year}] resuming from checkpoint.")

    source_filter = "|".join(source_ids)
    filter_str = f"primary_location.source.id:{source_filter},type:!paratext"
    if year_filter:
        filter_str += f",publication_year:{year_filter}"

    total = 0
    page = 0
    with open(out_path, mode) as out:
        while cursor:
            data = api_get(
                "/works",
                {
                    # Excluding paratext (proceedings front matter, TOCs) rather than
                    # allowlisting a type string: OpenAlex labels real papers differently
                    # per venue kind (e.g. "article" for journals, "conference-paper" for
                    # IEDM) so an allowlist silently drops venues that use another label.
                    "filter": filter_str,
                    "select": SELECT_FIELDS,
                    "per-page": PER_PAGE,
                    "cursor": cursor,
                },
                api_key,
            )
            results = data.get("results", [])
            for w in results:
                out.write(json.dumps(trim_work(w)) + "\n")
                total += 1
            out.flush()
            page += 1
            cursor = data.get("meta", {}).get("next_cursor")
            with open(checkpoint_path, "w") as cp:
                json.dump({"source_key": source_key, "cursor": cursor, "count": total, "done": cursor is None}, cp)
            if page % 5 == 0 or cursor is None:
                print(f"  [{venue_key}/{year}] page {page}, {total} works so far...")
            time.sleep(0.03)
    print(f"  [{venue_key}/{year}] done, {total} works written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Harvest OpenAlex works for a venue, one year at a time.")
    parser.add_argument("--venue", required=True, help="Venue key from data/areas.json")
    parser.add_argument("--year", type=int, default=None, help="Single year to harvest")
    parser.add_argument("--year-range", nargs=2, type=int, metavar=("START", "END"),
                        help="Harvest every year from START to END inclusive (useful for journals without years{} entries)")
    parser.add_argument("--all-years", action="store_true", help="Harvest every year listed in the venue's years{} registry entry")
    args = parser.parse_args()

    if not args.year and not args.all_years and not args.year_range:
        print("Specify --year <YYYY>, --year-range <START> <END>, or --all-years", file=sys.stderr)
        sys.exit(1)

    env = load_env()
    api_key = env.get("OPENALEX_API_KEY")
    registry = load_registry()

    area_key, venue = find_venue(registry, args.venue)
    if venue is None:
        print(f"[{args.venue}] not found in data/areas.json", file=sys.stderr)
        sys.exit(1)

    if args.all_years:
        years_map = venue.get("years", {})
        target_years = sorted(int(y) for y in years_map)
        if not target_years:
            print(f"[{args.venue}] has no years{{}} registry entries; use --year-range instead (likely a journal).", file=sys.stderr)
            sys.exit(1)
    elif args.year_range:
        start, end = args.year_range
        if start > end:
            print(f"Invalid range: {start} > {end}", file=sys.stderr)
            sys.exit(1)
        target_years = list(range(start, end + 1))
    else:
        target_years = [args.year]

    print(f"[{area_key}/{args.venue}] {venue['display']}: {len(target_years)} year(s) requested")
    for year in target_years:
        source_ids, year_filter, mode = resolve_year_sources(venue, year)
        if mode == "crossref":
            print(f"  [{args.venue}/{year}] registered as Crossref-only in the registry -- use pipeline/harvest_crossref.py instead.")
            continue
        if not source_ids:
            print(f"  [{args.venue}/{year}] no openalex_ids registered, skipping.", file=sys.stderr)
            continue
        harvest_year(args.venue, year, source_ids, year_filter, api_key)


if __name__ == "__main__":
    main()
