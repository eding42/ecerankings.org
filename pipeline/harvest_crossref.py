#!/usr/bin/env python3
"""Harvest works from Crossref for venue-years that have no OpenAlex source.

Usage:
    python3 pipeline/harvest_crossref.py --venue iedm --year 2023
    python3 pipeline/harvest_crossref.py --venue iedm --all-years
    python3 pipeline/harvest_crossref.py --venue iedm --year 2023 --dry-run

Mirrors pipeline/harvest.py's interface and cache layout
(cache/<venue>/<year>/works.jsonl) so downstream aggregation doesn't care
which source a year came from. Handles years registered in data/areas.json
as {"source": "crossref", "doi_prefix": ..., ...}; years registered as
"openalex" are skipped with a pointer back to harvest.py.

Query strategy (validated 2026-07-19 against IEDM 2016-2025)
------------------------------------------------------------
Crossref's `query.container-title` is FUZZY full-text search, not an exact
filter: for IEDM 2023 it returns ~30,198 results of which only 231 are real.
Deep-paging that and filtering client-side works but is wasteful and gives
no guarantee the tail is complete.

Instead we use Crossref's EXACT `filter=container-title:<title>`, which
returned exactly the right count for 8/8 IEDM years tested (matching
independent DOI-prefix verification on 7 of 8; the 8th, 2017, differs by 1
paper -- the exact filter found 229 vs 228 from relevance-capped sampling,
and the exact filter is the more authoritative of the two).

The catch: the exact container title VARIES per edition and is not
derivable from the venue name. Real examples from one venue:
    2016 -> "2016 IEEE International Electron Devices Meeting (IEDM)"
    2023 -> "2023 International Electron Devices Meeting (IEDM)"   <- no "IEEE"
So container_title is stored per-year in the registry (like doi_prefix,
which also varies per edition: iedm.2016 / iedm19573.2019 / iedm45741.2023).
If a year has no stored container_title, this script auto-discovers it via
a relevance-ranked fuzzy query, keeping only hits whose DOI matches the
registered doi_prefix, and prints the result so it can be stored.

Every fetched record is validated against doi_prefix regardless; anything
that doesn't match is dropped and counted, so a wrong container_title
surfaces as a large drop count rather than silently poisoning the cache.

Output shape and its limits
---------------------------
Records are written in the same envelope as the OpenAlex path, with two
deliberate differences:
  * `authorships[].institutions` is ALWAYS an empty list. Crossref gives
    free-text affiliation strings, not resolved institution IDs, so the
    raw strings are preserved in `authorships[].raw_affiliations` and
    resolved later by pipeline/normalize_affiliations.py. aggregate.py
    joins them at read time, which means re-running normalization after
    improving the mapping never requires re-harvesting.
  * `authorships[].author_id` is a SYNTHETIC name-based id
    ("crossref:name:<slug>"). Crossref exposes no stable author identifier
    for these records -- a 238-author sample of IEDM 2023 had zero ORCIDs.
    These ids are NOT disambiguated (two distinct researchers sharing a
    name collide) and are NOT joinable with OpenAlex author ids, so the
    same person appears as different authors across OpenAlex-sourced and
    Crossref-sourced years. Institution-level output is unaffected (it
    depends only on the affiliation and the 1/N split); author-level
    output for Crossref years should be treated as provisional.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
API = "https://api.crossref.org/works"
MAILTO = "eding2019@gmail.com"
ROWS = 500


def load_registry():
    with open(AREAS_JSON) as f:
        return json.load(f)


def find_venue(registry, venue_key):
    for area_key, area in registry["areas"].items():
        for venue in area["venues"]:
            if venue["key"] == venue_key:
                return area_key, venue
    return None, None


def api_get(params, retries=3):
    params = dict(params)
    params["mailto"] = MAILTO
    qs = urllib.parse.urlencode(params, safe=":,*")
    url = f"{API}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": f"ecerankings-harvest-crossref (mailto:{MAILTO})"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(5)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(5)
                continue
            raise


def author_slug(given, family):
    """Synthesize a stable-but-NOT-disambiguated author key from a name.

    See module docstring: Crossref gives no author identifier for these
    records, so identical names collapse to one key. Institution-level
    aggregation does not depend on this being correct.
    """
    name = f"{given or ''} {family or ''}".strip()
    folded = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")
    return slug or "unknown"


def clean_text(s):
    """Crossref embeds HTML entities (&#x0026;, &#x00FC;) in titles/affiliations."""
    return html.unescape(s or "").strip()


def year_date_filter(year, venue_kind):
    """Return (doc_type, from_date, until_date) for this venue kind.

    Conferences: one edition = one container-title, but Crossref sometimes
    deposits proceedings in the following January, so keep a 3-month grace
    window past year-end (matches discover_container_title's original
    window). Journals: a SINGLE container-title spans every year, so the
    date filter is the only thing that scopes a query to one year -- it
    must be exact calendar-year bounds, not padded, or years bleed into
    each other.
    """
    if venue_kind == "journal":
        return "journal-article", f"{year}-01-01", f"{year}-12-31"
    return "proceedings-article", f"{year}-01-01", f"{year + 1}-03-31"


def discover_container_title(venue_display, year, doi_prefix, venue_kind="conference"):
    """Find the exact Crossref container-title for this edition.

    Uses a relevance-ranked fuzzy query restricted to IEEE's registrant
    prefix and a window around the conference date, then keeps only hits
    whose DOI matches the registered per-year prefix and returns the most
    common container-title among them.
    """
    doc_type, date_from, date_until = year_date_filter(year, venue_kind)
    query_name = re.sub(r"\s*\([^)]*\)\s*", " ", venue_display).strip()
    data = api_get({
        "query.container-title": query_name,
        "filter": f"from-pub-date:{date_from},until-pub-date:{date_until},type:{doc_type}",
        "rows": 60,
        "select": "DOI,container-title",
    })
    titles = {}
    for item in data.get("message", {}).get("items", []):
        doi = (item.get("DOI") or "").lower()
        if doi_prefix and not doi.startswith(doi_prefix.lower()):
            continue
        for ct in item.get("container-title", []) or []:
            titles[ct] = titles.get(ct, 0) + 1
    if not titles:
        return None
    return max(titles, key=titles.get)


def trim_work(item, edition_year):
    authorships = []
    for a in item.get("author", []) or []:
        raw_affs = []
        for aff in a.get("affiliation", []) or []:
            name = clean_text(aff.get("name"))
            if name:
                raw_affs.append(name)
        authorships.append({
            "author_id": f"crossref:name:{author_slug(a.get('given'), a.get('family'))}",
            "author_name": clean_text(f"{a.get('given','')} {a.get('family','')}"),
            # Always empty here; filled by joining data/affiliation-map.csv at
            # aggregate time. See module docstring.
            "institutions": [],
            "raw_affiliations": raw_affs,
        })
    titles = item.get("title") or []
    issued = (item.get("issued") or {}).get("date-parts") or [[None]]
    issued_year = issued[0][0] if issued and issued[0] else None
    return {
        "id": None,
        "doi": f"https://doi.org/{item['DOI']}" if item.get("DOI") else None,
        "title": clean_text(titles[0]) if titles else None,
        # Bucket by conference EDITION year (the registry year), not Crossref's
        # `issued` date -- proceedings are sometimes deposited in January of the
        # following year, which would otherwise scatter one edition across two
        # ranking years. Crossref's own value is kept for reference.
        "publication_year": edition_year,
        "crossref_issued_year": issued_year,
        "type": item.get("type"),
        "source": "crossref",
        "authorships": authorships,
    }


def harvest_year(venue_key, venue_display, year, entry, dry_run=False, venue_kind="conference"):
    doi_prefix = entry.get("doi_prefix")
    container_title = entry.get("container_title")
    discovered = False
    doc_type, date_from, date_until = year_date_filter(year, venue_kind)

    if not container_title:
        print(f"  [{venue_key}/{year}] no container_title in registry, discovering...")
        container_title = discover_container_title(venue_display, year, doi_prefix, venue_kind)
        time.sleep(0.3)
        if not container_title:
            print(f"  [{venue_key}/{year}] FAILED to discover a container-title matching doi_prefix={doi_prefix!r}. Skipping.", file=sys.stderr)
            return
        discovered = True
        print(f"  [{venue_key}/{year}] discovered container_title={container_title!r}")

    filter_str = f"container-title:{container_title},type:{doc_type},from-pub-date:{date_from},until-pub-date:{date_until}"
    expected = entry.get("count")
    head = api_get({"filter": filter_str, "rows": 0})
    total = head.get("message", {}).get("total-results", 0)
    time.sleep(0.3)
    print(f"  [{venue_key}/{year}] exact-filter total={total}" + (f" (registry expected {expected})" if expected else ""))
    if expected and total and abs(total - expected) > max(5, 0.1 * expected):
        print(f"  [{venue_key}/{year}] WARNING: total {total} differs from registry count {expected} by >10%.", file=sys.stderr)
    if total == 0:
        print(f"  [{venue_key}/{year}] nothing to harvest, skipping.", file=sys.stderr)
        return

    if dry_run:
        print(f"  [{venue_key}/{year}] dry-run, not writing." + (f" Store container_title={container_title!r} in the registry." if discovered else ""))
        return

    year_dir = os.path.join(CACHE_DIR, venue_key, str(year))
    os.makedirs(year_dir, exist_ok=True)
    out_path = os.path.join(year_dir, "works.jsonl")
    checkpoint_path = os.path.join(year_dir, ".checkpoint")
    # Includes the full filter, not just container_title: a checkpoint from
    # before the date filter existed (crossref:<title>) must NOT match here,
    # or a stale done:true from the old unscoped query would silently skip
    # re-harvesting under the corrected, year-scoped query.
    source_key = f"crossref:{filter_str}"

    if os.path.exists(checkpoint_path):
        with open(checkpoint_path) as f:
            state = json.load(f)
        if state.get("source_key") == source_key and state.get("done"):
            print(f"  [{venue_key}/{year}] already complete ({state.get('count','?')} works). Skipping.")
            return

    cursor = "*"
    written = 0
    dropped = 0
    page = 0
    with open(out_path, "w") as out:
        while cursor:
            data = api_get({
                "filter": filter_str,
                "rows": ROWS,
                "cursor": cursor,
                "select": "DOI,title,author,issued,type,container-title",
            })
            msg = data.get("message", {})
            items = msg.get("items", [])
            if not items:
                break
            for item in items:
                doi = (item.get("DOI") or "").lower()
                # Guard against a wrong/ambiguous container_title: anything whose
                # DOI doesn't match the registered edition prefix is not this
                # conference edition.
                if doi_prefix and not doi.startswith(doi_prefix.lower()):
                    dropped += 1
                    continue
                out.write(json.dumps(trim_work(item, year)) + "\n")
                written += 1
            out.flush()
            page += 1
            cursor = msg.get("next-cursor")
            with open(checkpoint_path, "w") as cp:
                json.dump({"source_key": source_key, "count": written, "done": False}, cp)
            time.sleep(0.3)

    with open(checkpoint_path, "w") as cp:
        json.dump({"source_key": source_key, "count": written, "done": True}, cp)

    print(f"  [{venue_key}/{year}] done, {written} works written to {out_path}" + (f" ({dropped} dropped: DOI outside {doi_prefix})" if dropped else ""))
    if discovered:
        print(f"  [{venue_key}/{year}] NOTE: add \"container_title\": {container_title!r} to this year's registry entry to skip discovery next run.")
    if written == 0:
        print(f"  [{venue_key}/{year}] WARNING: 0 works kept -- container_title and doi_prefix likely disagree.", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Harvest Crossref works for venue-years with no OpenAlex source.")
    parser.add_argument("--venue", required=True, help="Venue key from data/areas.json")
    parser.add_argument("--year", type=int, default=None, help="Single year to harvest")
    parser.add_argument("--all-years", action="store_true", help="Harvest every crossref-registered year for this venue")
    parser.add_argument("--dry-run", action="store_true", help="Report counts and discovered titles without writing cache")
    args = parser.parse_args()

    if not args.year and not args.all_years:
        print("Specify --year <YYYY> or --all-years", file=sys.stderr)
        sys.exit(1)

    registry = load_registry()
    area_key, venue = find_venue(registry, args.venue)
    if venue is None:
        print(f"[{args.venue}] not found in data/areas.json", file=sys.stderr)
        sys.exit(1)

    years_map = venue.get("years", {})
    if not years_map:
        print(f"[{args.venue}] has no years{{}} registry entries -- run the collect-venue-data skill first to map per-year sources.", file=sys.stderr)
        sys.exit(1)

    if args.all_years:
        target_years = sorted(int(y) for y in years_map)
    else:
        target_years = [args.year]

    print(f"[{area_key}/{args.venue}] {venue['display']}: {len(target_years)} year(s) requested")
    for year in target_years:
        entry = years_map.get(str(year))
        if entry is None:
            print(f"  [{args.venue}/{year}] not in registry years{{}}, skipping.", file=sys.stderr)
            continue
        if entry.get("source") != "crossref":
            print(f"  [{args.venue}/{year}] registered as {entry.get('source')} -- use pipeline/harvest.py instead.")
            continue
        harvest_year(args.venue, venue["display"], year, entry, dry_run=args.dry_run, venue_kind=venue.get("kind", "conference"))


if __name__ == "__main__":
    main()
