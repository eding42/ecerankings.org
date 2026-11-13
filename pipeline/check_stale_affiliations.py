#!/usr/bin/env python3
"""How stale are the cached affiliations? Ask OpenAlex what it has now.

`backfill_openalex.py` only revisits Crossref and S2 works. A work harvested
from OpenAlex itself keeps whatever OpenAlex had that day, so when OpenAlex
later attaches affiliations the cache never hears about it. On 2026-11-12 a
sample of 146 such works found 48% now had affiliation text, 88% for 2005.

This measures the gap; it never writes the cache. It samples works from
default-on venues in which every author lacks both an institution and a raw
affiliation, fetches them from OpenAlex by ID, and reports how many now have
affiliations, by venue and by year, so a refetch can be aimed where it pays.

    python3 pipeline/check_stale_affiliations.py [--seed 2026] [--size 150]

Network, opt-in. Reads OPENALEX_API_KEY from .env and sends only the key and
work IDs (no contact email). Stdlib only.
"""

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
USER_AGENT = "ece-rankings-stale-affiliation-check/1.0"
NONRESEARCH = {"editorial", "erratum", "letter", "book-review", "peer-review", "retraction", "other"}
CREDIT_TYPES = {"education"}


def api_key():
    path = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(path):
        with open(path) as handle:
            for line in handle:
                if line.startswith("OPENALEX_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'")
    return None


def stale_candidates(cache_dir, registry):
    """Works from OpenAlex where no author has an institution or a raw affiliation."""
    venues = sorted({v["key"] for a in registry["areas"].values() if a.get("default_on", True) for v in a["venues"]})
    out = []
    for venue in venues:
        base = os.path.join(cache_dir, venue)
        if not os.path.isdir(base):
            continue
        for year in sorted(os.listdir(base)):
            path = os.path.join(base, year, "works.jsonl")
            if not year.isdigit() or not os.path.exists(path):
                continue
            with open(path) as handle:
                for line in handle:
                    work = json.loads(line)
                    authors = work.get("authorships") or []
                    if (authors and str(work.get("id") or "").startswith("https://openalex.org/W")
                            and (work.get("type") or "").lower() not in NONRESEARCH
                            and all(not a.get("institutions") and not a.get("raw_affiliations") for a in authors)):
                        out.append((venue, int(year), work["id"]))
    return out


def get(url, tries=5):
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            time.sleep(5 * (attempt + 1))
    raise RuntimeError("OpenAlex kept returning 429")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--size", type=int, default=150)
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    args = parser.parse_args()
    with open(AREAS_JSON) as handle:
        registry = json.load(handle)
    pool = stale_candidates(os.path.realpath(args.cache_dir), registry)
    sample = random.Random(args.seed).sample(pool, min(args.size, len(pool)))
    key, fetched = api_key(), {}
    for start in range(0, len(sample), 50):
        ids = "|".join(w.rsplit("/", 1)[-1] for _, _, w in sample[start:start + 50])
        query = {"filter": "openalex_id:" + ids, "per-page": "50", "select": "id,authorships"}
        if key:
            query["api_key"] = key
        for work in get("https://api.openalex.org/works?" + urllib.parse.urlencode(query))["results"]:
            fetched[work["id"]] = work.get("authorships") or []
        time.sleep(1)
    by_venue, by_year = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    resolved = n = anyaff = 0
    for venue, year, wid in sample:
        if wid not in fetched:
            continue
        authors = fetched[wid]
        has = any(a.get("institutions") or a.get("raw_affiliation_strings") for a in authors)
        credit = sum(1 for a in authors if any(i.get("type") in CREDIT_TYPES for i in a.get("institutions") or []))
        n += 1
        anyaff += has
        resolved += credit / max(len(authors), 1)
        for table, k in ((by_venue, venue), (by_year, year)):
            table[k][1] += 1
            table[k][0] += has
    if not n:
        print("no works fetched")
        return 1
    print(f"candidate works (every author lacks an affiliation): {len(pool):,}; sampled {n}")
    print(f"now have affiliation text in OpenAlex: {anyaff}/{n} ({100 * anyaff / n:.0f}%)")
    print(f"credit already resolved to an institution of a credit type: {100 * resolved / n:.0f}% "
          f"(the rest is raw text that still needs the map)")
    print("\nby year (has/sampled):", {k: tuple(v) for k, v in sorted(by_year.items())})
    print("by venue (has/sampled):", {k: tuple(v) for k, v in sorted(by_venue.items(), key=lambda kv: -kv[1][1])[:12]})
    if anyaff / n >= 0.25:
        print(f"\nA refetch is worth it: about {anyaff / n:.0%} of {len(pool):,} works would gain affiliation text.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
