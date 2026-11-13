#!/usr/bin/env python3
"""Enrich cached works in cache_biosciences with biblio and referenced_works_count from OpenAlex.
This allows high-precision filtering of front-matter, news columns, and short perspectives.
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache_biosciences")
MAILTO = "eding2019@gmail.com"
API = "https://api.openalex.org"

VENUES = {
    "science": "S3880285",
    "cell": "S110447773",
}

def load_env():
    env = {}
    env_file = os.path.join(REPO_ROOT, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

def api_get(path, params, api_key, retries=5):
    params = dict(params)
    params["mailto"] = MAILTO
    if api_key:
        params["api_key"] = api_key
    qs = urllib.parse.urlencode(params, safe=":,|*!")
    url = f"{API}{path}?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": f"biosciences-enrich (mailto:{MAILTO})"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise

def enrich_venue(venue_key, source_id, api_key):
    vdir = os.path.join(CACHE_DIR, venue_key)
    if not os.path.isdir(vdir):
        return

    years = sorted([int(y) for y in os.listdir(vdir) if y.isdigit()], reverse=True)
    print(f"\nEnriching {venue_key} across {len(years)} years...")

    for year in years:
        ydir = os.path.join(vdir, str(year))
        wfile = os.path.join(ydir, "works.jsonl")
        if not os.path.isfile(wfile):
            continue

        # Load existing cached works
        works = []
        with open(wfile) as f:
            for line in f:
                if line.strip():
                    works.append(json.loads(line))

        # Check if already enriched
        already_done = all("referenced_works_count" in w and "biblio" in w for w in works if works)
        if already_done and len(works) > 0:
            print(f"  [{venue_key}/{year}] already has biblio and referenced_works_count ({len(works)} works).")
            continue

        # Fetch biblio and referenced_works_count by cursor for this venue and year
        print(f"  [{venue_key}/{year}] fetching metadata from OpenAlex ({len(works)} works)...")
        meta_by_id = {}
        cursor = "*"
        filter_str = f"primary_location.source.id:{source_id},publication_year:{year}"
        
        while cursor:
            params = {
                "filter": filter_str,
                "select": "id,biblio,referenced_works_count",
                "per-page": 200,
                "cursor": cursor,
            }
            try:
                res = api_get("/works", params, api_key)
            except Exception as e:
                print(f"    Error fetching cursor: {e}")
                break

            results = res.get("results", [])
            for r in results:
                wid = r.get("id")
                if wid:
                    meta_by_id[wid] = {
                        "biblio": r.get("biblio") or {},
                        "referenced_works_count": r.get("referenced_works_count") or 0
                    }
            next_cursor = res.get("meta", {}).get("next_cursor")
            if not results or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

        # Enrich works in memory and rewrite
        enriched_count = 0
        for w in works:
            wid = w.get("id")
            if wid in meta_by_id:
                w["biblio"] = meta_by_id[wid]["biblio"]
                w["referenced_works_count"] = meta_by_id[wid]["referenced_works_count"]
                enriched_count += 1
            else:
                if "biblio" not in w:
                    w["biblio"] = {}
                if "referenced_works_count" not in w:
                    w["referenced_works_count"] = None

        tmp_file = wfile + ".tmp"
        with open(tmp_file, "w") as out:
            for w in works:
                out.write(json.dumps(w, ensure_ascii=False) + "\n")
        os.replace(tmp_file, wfile)
        print(f"  [{venue_key}/{year}] Enriched {enriched_count}/{len(works)} works.")

def main():
    env = load_env()
    api_key = env.get("OPENALEX_API_KEY")
    for vkey, sid in VENUES.items():
        enrich_venue(vkey, sid, api_key)
    print("\nMetadata enrichment complete.")

if __name__ == "__main__":
    main()
