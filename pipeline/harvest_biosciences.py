#!/usr/bin/env python3
"""Harvest works from OpenAlex for Biosciences venues (Phase 1 elite + Phase 2 disciplinary).

Supports:
- Server-side domain filtering for multidisciplinary venues (Nature, Science, PNAS):
  * Life Sciences (Domain 1)
  * Health Sciences (Domain 4)
  * Bioengineering, Biomedical Engineering, Biomaterials, Ecology subfields:
    1502, 2204, 2502, 2303, 2309
- Direct venue harvest for 32 disciplinary core journals (Mol Cell, Neuron, Immunity, etc.)
- In-flight resolution of 100-author list truncation via /works/{id}
- Preserves biblio and referenced_works_count for front-matter / news filtering

Usage:
    python3 pipeline/harvest_biosciences.py --all-venues --year-range 2016 2025
    python3 pipeline/harvest_biosciences.py --venue cell-metab --year-range 2016 2025
    python3 pipeline/harvest_biosciences.py --area neuro --year 2024
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
CACHE_DIR = os.path.join(REPO_ROOT, "cache_biosciences")
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas_biosciences.json")
ENV_FILE = os.path.join(REPO_ROOT, ".env")
API = "https://api.openalex.org"
MAILTO = "eding2019@gmail.com"
SELECT_FIELDS = "id,doi,title,publication_year,type,biblio,referenced_works_count,authorships,primary_topic"
PER_PAGE = 200

# Canonical biological subfields in Physical Sciences
SUPPLEMENTAL_BIO_SUBFIELDS = "1502|2204|2502|2303|2309"

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

def load_areas():
    with open(AREAS_JSON) as f:
        return json.load(f)

def api_get(path, params=None, api_key=None, retries=5):
    params = dict(params or {})
    params["mailto"] = MAILTO
    if api_key:
        params["api_key"] = api_key
    qs = urllib.parse.urlencode(params, safe=":,|*!")
    url = f"{API}{path}"
    if qs:
        url += f"?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": f"biosciences-harvest (mailto:{MAILTO})"})
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

def refetch_full_work(work_id, api_key):
    short_id = work_id.split("/")[-1]
    try:
        data = api_get(f"/works/{short_id}", None, api_key)
        return data.get("authorships", [])
    except Exception as e:
        print(f"    Warning: failed to refetch full authors for {work_id}: {e}")
        return None

def trim_work(w, api_key=None):
    raw_authorships = w.get("authorships", []) or []
    # If hit the 100-author limit in list response, refetch complete byline
    if len(raw_authorships) == 100 and api_key and w.get("id"):
        full_auths = refetch_full_work(w["id"], api_key)
        if full_auths and len(full_auths) > 100:
            raw_authorships = full_auths

    authorships = []
    for a in raw_authorships:
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
            "raw_affiliation_strings": a.get("raw_affiliation_strings") or [],
            "institutions": insts,
        })
    pt = w.get("primary_topic") or {}
    return {
        "id": w.get("id"),
        "doi": w.get("doi"),
        "title": w.get("title"),
        "publication_year": w.get("publication_year"),
        "type": w.get("type"),
        "biblio": w.get("biblio") or {},
        "referenced_works_count": w.get("referenced_works_count") or 0,
        "topic": {
            "name": pt.get("display_name"),
            "subfield": (pt.get("subfield") or {}).get("display_name"),
            "field": (pt.get("field") or {}).get("display_name"),
            "domain": (pt.get("domain") or {}).get("display_name"),
        },
        "authorships": authorships,
    }

def harvest_venue_year(vkey, sid, year, cache_dir, api_key, is_multidisciplinary=False, force=False):
    year_dir = os.path.join(cache_dir, vkey, str(year))
    os.makedirs(year_dir, exist_ok=True)
    out_path = os.path.join(year_dir, "works.jsonl")
    checkpoint_path = os.path.join(year_dir, ".done")

    if not force and os.path.exists(checkpoint_path) and os.path.exists(out_path):
        with open(out_path) as f:
            count = sum(1 for line in f if line.strip())
        return count

    # Determine query filters
    if is_multidisciplinary:
        # 1. Base bio/health domains (Domain 1: Life Sciences, Domain 4: Health Sciences)
        filters = [
            f"primary_location.source.id:{sid}",
            f"publication_year:{year}",
            "type:article",
            "primary_topic.domain.id:1|4"
        ]
        # 2. Supplemental bioengineering/ecology query
        supp_filters = [
            f"primary_location.source.id:{sid}",
            f"publication_year:{year}",
            "type:article",
            f"primary_topic.subfield.id:{SUPPLEMENTAL_BIO_SUBFIELDS}"
        ]
        queries = [",".join(filters), ",".join(supp_filters)]
    else:
        # Disciplinary journal:
        # Note: Genome Research (S43092948) works were labeled 'preprint' in OpenAlex CSHL mapping
        if vkey == "genome-res":
            query_str = f"primary_location.source.id:{sid},publication_year:{year}"
        else:
            query_str = f"primary_location.source.id:{sid},publication_year:{year},type:article"
        queries = [query_str]

    seen_ids = set()
    works_to_write = []

    for q in queries:
        cursor = "*"
        while cursor:
            params = {
                "filter": q,
                "select": SELECT_FIELDS,
                "per-page": PER_PAGE,
                "cursor": cursor,
            }
            data = api_get("/works", params, api_key)
            results = data.get("results", [])
            for w in results:
                wid = w.get("id")
                if wid and wid not in seen_ids:
                    seen_ids.add(wid)
                    tw = trim_work(w, api_key)
                    works_to_write.append(tw)

            next_cursor = data.get("meta", {}).get("next_cursor")
            if not results or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor

    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as out:
        for tw in works_to_write:
            out.write(json.dumps(tw, ensure_ascii=False) + "\n")
    os.replace(tmp_path, out_path)

    with open(checkpoint_path, "w") as f:
        json.dump({"done": True, "count": len(works_to_write), "timestamp": time.time()}, f)

    return len(works_to_write)

def main():
    parser = argparse.ArgumentParser(description="Harvest Biosciences works.")
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    parser.add_argument("--year-range", type=int, nargs=2, default=[2016, 2025])
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--area", default=None)
    parser.add_argument("--venue", default=None)
    parser.add_argument("--all-venues", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    env = load_env()
    api_key = env.get("OPENALEX_API_KEY")
    if not api_key:
        print("Warning: OPENALEX_API_KEY not found in .env; rate limits will apply.", file=sys.stderr)

    reg = load_areas()
    years = [args.year] if args.year else list(range(args.year_range[0], args.year_range[1] + 1))

    # Collect venues to harvest
    venues_to_run = []
    multidisciplinary_keys = {"nature", "science", "pnas"}

    for akey, ainfo in reg["areas"].items():
        if args.area and akey != args.area:
            continue
        for v in ainfo["venues"]:
            vkey = v["key"]
            if args.venue and vkey != args.venue:
                continue
            sid = v["openalex_ids"][0]
            is_multi = vkey in multidisciplinary_keys
            venues_to_run.append((vkey, v["display"], sid, is_multi))

    # Deduplicate venues (in case a venue appears in multiple areas)
    unique_venues = {}
    for item in venues_to_run:
        unique_venues[item[0]] = item

    print(f"Harvesting Biosciences: {len(unique_venues)} venue(s) across years {years[0]}..{years[-1]}")
    print(f"Target Cache: {args.cache_dir}")
    print("=" * 75)

    total_works_all = 0
    t0 = time.time()

    for idx, (vkey, vname, sid, is_multi) in enumerate(unique_venues.values(), 1):
        print(f"\n[{idx}/{len(unique_venues)}] {vname} ({vkey}) [OpenAlex {sid}]...")
        venue_total = 0
        for y in sorted(years, reverse=True):
            cnt = harvest_venue_year(vkey, sid, y, args.cache_dir, api_key, is_multidisciplinary=is_multi, force=args.force)
            venue_total += cnt
            print(f"  {y}: {cnt:4d} works")
        print(f"  -> Total {vkey}: {venue_total} works")
        total_works_all += venue_total

    elapsed = time.time() - t0
    print("\n" + "=" * 75)
    print(f"Harvest completed successfully in {elapsed:.1f}s. Total works processed: {total_works_all}")

if __name__ == "__main__":
    main()
