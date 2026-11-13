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


def api_get(path, params, api_key, retries=5):
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
        except (urllib.error.HTTPError, urllib.error.URLError, ConnectionResetError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                retry_after = getattr(e, "headers", {}).get("Retry-After") if hasattr(e, "headers") and e.headers else None
                if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                    wait = max(5.0, float(retry_after) if retry_after else 5.0 * (2 ** attempt))
                else:
                    wait = float(retry_after) if retry_after else 2 ** attempt
                time.sleep(wait)
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
            norm_ids = [x.rsplit('/', 1)[-1] for x in venue.get("openalex_ids", [])]
            is_series_source = sid in norm_ids or entry.get("filter_year")
            year_filter = year if (is_journal or is_multi_year_source or is_series_source) else None
            return [sid], year_filter, "precise"
        return None, None, "crossref"
    # No per-year registry entry: fall back to filtering the venue's
    # general openalex_ids by publication_year (this is the journal path).
    ids = venue.get("openalex_ids", [])
    return ids, year, "filtered"


def harvest_year(venue_key, year, source_ids, year_filter, api_key, cache_dir=None, extra_filter=None):
    year_dir = os.path.join(cache_dir or CACHE_DIR, venue_key, str(year))
    os.makedirs(year_dir, exist_ok=True)
    out_path = os.path.join(year_dir, "works.jsonl")
    checkpoint_path = os.path.join(year_dir, ".checkpoint")

    source_key = "|".join(source_ids)
    source_filter = "|".join(source_ids)
    filter_str = f"primary_location.source.id:{source_filter},type:!paratext"
    if extra_filter:
        filter_str += f",{extra_filter}"
    if year_filter:
        filter_str += f",publication_year:{year_filter}"

    cursor = "*"
    page = 1
    mode = "w"
    total = 0
    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            state = json.load(f)
        filter_match = state.get("filter") is None or state.get("filter") == filter_str
        if state.get("source_key") == source_key and filter_match:
            if state.get("done"):
                print(f"  [{venue_key}/{year}] already complete ({state.get('count', '?')} works). Skipping.")
                return
            cursor = state.get("cursor", "*")
            page = state.get("page", 1) + 1 if "page" in state else 1
            mode = "a"
            # Appending to works.jsonl, so the checkpoint count must stay
            # cumulative rather than restarting at this run's first page.
            total = state.get("count", 0)
            print(f"  [{venue_key}/{year}] resuming from checkpoint ({total} works already written).")

    has_more = True
    with open(out_path, mode) as out:
        while has_more:
            params = {
                "filter": filter_str,
                "select": SELECT_FIELDS,
                "per-page": PER_PAGE,
            }
            if api_key:
                params["cursor"] = cursor
            else:
                params["page"] = page

            data = api_get("/works", params, api_key)
            results = data.get("results", [])
            for w in results:
                out.write(json.dumps(trim_work(w)) + "\n")
                total += 1
            out.flush()

            meta = data.get("meta", {})
            if api_key:
                cursor = meta.get("next_cursor")
                has_more = bool(cursor)
                with open(checkpoint_path, "w") as cp:
                    json.dump({"source_key": source_key, "filter": filter_str, "cursor": cursor, "count": total, "done": not has_more}, cp)
            else:
                total_meta = meta.get("count", 0)
                has_more = len(results) == PER_PAGE and (page * PER_PAGE < total_meta)
                with open(checkpoint_path, "w") as cp:
                    json.dump({"source_key": source_key, "filter": filter_str, "page": page, "count": total, "done": not has_more}, cp)
                page += 1

            if page % 5 == 0 or not has_more:
                print(f"  [{venue_key}/{year}] page {page - 1 if not api_key else page}, {total} works so far...")
            time.sleep(0.15)
    print(f"  [{venue_key}/{year}] done, {total} works written to {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Harvest OpenAlex works for a venue, one year at a time.")
    parser.add_argument("--venue", required=True, help="Venue key from data/areas.json")
    parser.add_argument("--year", type=int, default=None, help="Single year to harvest")
    parser.add_argument("--year-range", nargs=2, type=int, metavar=("START", "END"),
                        help="Harvest every year from START to END inclusive (useful for journals without years{} entries)")
    parser.add_argument("--all-years", action="store_true", help="Harvest every year listed in the venue's years{} registry entry")
    parser.add_argument("--cache-dir", default=None, help="Root cache directory to write to (defaults to cache/)")
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

    extra_filter = venue.get("openalex_filter")

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
        harvest_year(args.venue, year, source_ids, year_filter, api_key, cache_dir=args.cache_dir, extra_filter=extra_filter)


if __name__ == "__main__":
    main()
