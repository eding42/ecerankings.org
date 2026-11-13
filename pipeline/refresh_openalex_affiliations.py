#!/usr/bin/env python3
"""Refresh affiliations for works that OpenAlex itself supplied but had no affiliations for.

`backfill_openalex.py` repairs Crossref and S2 works and skips any work that
already carries an OpenAlex id, on the finding that OpenAlex "genuinely holds no
affiliations for those" (a 20-work probe in July). That stopped being true: on
2026-11-12 a sample of 146 such works found 48% now had affiliation text, 88%
for 2005. A cached OpenAlex work never hears about later enrichment.

This re-fetches those works by OpenAlex id and writes the new authorships back,
under three guards so a refresh can only add information:

  1. only works in which EVERY author lacks both institutions and raw strings;
  2. the fresh author list must have the same length and the same name in
     every position (family name, or the same set of name parts, since some
     cached names are stored "Family Given"), so an affiliation is never
     attached to a different person (merge_work replaces the list wholesale;
     this proves that is safe);
  3. the fresh work must carry an affiliation for at least one author.

Anything else is left alone and counted. Reruns skip works already refreshed or
found empty (`cache/.refresh-negative.txt`) unless --retry.

    python3 pipeline/refresh_openalex_affiliations.py --pilot 200
    python3 pipeline/refresh_openalex_affiliations.py --apply [--exclude-areas a,b] [--venue v]

Next: normalize the new raw strings (normalize_semantic.py or
normalize_affiliations_local.py), adjudicate, then verify.py --all.

Network. Sends the API key and work ids only. Stdlib only.
"""

import argparse
import glob
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_bylines import family_key, name_tokens  # noqa: E402
from backfill_openalex import load_api_key, merge_work  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
NEGATIVE_TXT = os.path.join(CACHE_DIR, ".refresh-negative.txt")
CHECKPOINT = os.path.join(CACHE_DIR, ".refresh-checkpoint.jsonl")
API = "https://api.openalex.org/works"
BATCH = 50
SLEEP = 0.2
USER_AGENT = "ece-rankings-refresh/1.0"
NONRESEARCH = {"editorial", "erratum", "letter", "book-review", "peer-review", "retraction", "other"}


def venues_to_refresh(exclude_areas=(), only_venue=None):
    with open(AREAS_JSON) as handle:
        registry = json.load(handle)
    venues = set()
    for key, area in registry["areas"].items():
        if key in exclude_areas or not area.get("default_on", True):
            continue
        venues.update(v["key"] for v in area["venues"])
    return {only_venue} & venues if only_venue else venues


def is_candidate(work):
    authors = work.get("authorships") or []
    return (bool(authors) and str(work.get("id") or "").startswith("https://openalex.org/W")
            and (work.get("type") or "").lower() not in NONRESEARCH
            and all(not a.get("institutions") and not a.get("raw_affiliations") for a in authors))


def scan(cache_dir, venues, skip=frozenset()):
    out, lfs = [], 0
    for venue in sorted(venues):
        for path in sorted(glob.glob(os.path.join(cache_dir, venue, "*", "works.jsonl"))):
            with open(path, "rb") as handle:
                if handle.read(40).startswith(b"version https://git-lfs"):
                    lfs += 1
                    continue
            with open(path) as handle:
                for index, line in enumerate(handle):
                    work = json.loads(line)
                    if is_candidate(work) and work["id"] not in skip:
                        out.append({"path": path, "line": index, "id": work["id"], "venue": venue,
                                    "year": os.path.basename(os.path.dirname(path)),
                                    "names": [a.get("author_name") or "" for a in work["authorships"]]})
    return out, lfs


def fetch(ids, api_key):
    query = {"filter": "openalex_id:" + "|".join(i.rsplit("/", 1)[-1] for i in ids),
             "per-page": str(len(ids)), "select": "id,doi,authorships"}
    if api_key:
        query["api_key"] = api_key
    url = API + "?" + urllib.parse.urlencode(query)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60) as r:
                return {w["id"]: w for w in json.load(r).get("results") or []}
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("OpenAlex kept failing; rerun to resume from the checkpoint")


def verdict(candidate, fresh):
    """accept | no_affiliation | author_count | author_names"""
    authors = fresh.get("authorships") or []
    if len(authors) != len(candidate["names"]):
        return "author_count"
    for old, new in zip(candidate["names"], authors):
        new = (new.get("author") or {}).get("display_name") or ""
        if family_key(old) != family_key(new) and name_tokens(old) != name_tokens(new):
            return "author_names"
    if not any(a.get("institutions") or a.get("raw_affiliation_strings") for a in authors):
        return "no_affiliation"
    return "accept"


def load_negative():
    if not os.path.exists(NEGATIVE_TXT):
        return set()
    with open(NEGATIVE_TXT) as handle:
        return {line.strip() for line in handle if line.strip()}


def run(candidates, api_key, apply):
    fetched, outcomes = {}, Counter()
    if apply and os.path.exists(CHECKPOINT):
        with open(CHECKPOINT) as handle:
            for line in handle:
                rec = json.loads(line)
                fetched[rec["id"]] = rec.get("work")
        print(f"  resuming: {len(fetched):,} works already fetched")
    todo = [c for c in candidates if c["id"] not in fetched]
    checkpoint = open(CHECKPOINT, "a") if apply else None
    for start in range(0, len(todo), BATCH):
        chunk = todo[start:start + BATCH]
        found = fetch([c["id"] for c in chunk], api_key)
        for c in chunk:
            fetched[c["id"]] = found.get(c["id"])
            if checkpoint:
                checkpoint.write(json.dumps({"id": c["id"], "work": found.get(c["id"])}, ensure_ascii=False) + "\n")
        if checkpoint:
            checkpoint.flush()
        print(f"  fetched {min(start + BATCH, len(todo)):,}/{len(todo):,}", end="\r", flush=True)
        time.sleep(SLEEP)
    print()
    accepted, empty = {}, set()
    by_year = defaultdict(Counter)
    for c in candidates:
        fresh = fetched.get(c["id"])
        result = "missing" if fresh is None else verdict(c, fresh)
        outcomes[result] += 1
        by_year[c["year"]][result] += 1
        if result == "accept":
            accepted[c["id"]] = fresh
        elif result in ("no_affiliation", "missing"):
            empty.add(c["id"])
    print(f"  candidates {len(candidates):,}: " + ", ".join(f"{k} {v:,}" for k, v in outcomes.most_common()))
    print("  accepted by year:", {y: c["accept"] for y, c in sorted(by_year.items()) if c["accept"]})
    if not apply:
        return
    by_file = defaultdict(dict)
    for c in candidates:
        if c["id"] in accepted:
            by_file[c["path"]][c["line"]] = c["id"]
    rewritten = 0
    for path, targets in sorted(by_file.items()):
        tmp = path + ".tmp"
        with open(path) as src, open(tmp, "w") as dst:
            for index, line in enumerate(src):
                if index in targets:
                    merged = merge_work(json.loads(line), accepted[targets[index]])
                    if merged is not None:
                        merged.pop("backfilled_from", None)
                        merged["refreshed_from"] = "openalex"
                        line = json.dumps(merged, ensure_ascii=False) + "\n"
                        rewritten += 1
                dst.write(line)
        os.replace(tmp, path)
    with open(NEGATIVE_TXT, "w") as handle:
        handle.write("\n".join(sorted(load_negative() | empty)) + "\n")
    checkpoint.close()
    os.remove(CHECKPOINT)
    print(f"  works rewritten: {rewritten:,} in {len(by_file):,} files; {len(empty):,} found empty -> {NEGATIVE_TXT}")
    print("Next: normalize the new raw strings, adjudicate, then python3 pipeline/verify.py --all")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", type=int, metavar="N", help="fetch N random candidates, report, write nothing")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--exclude-areas", default="", help="comma-separated area keys to leave untouched")
    parser.add_argument("--venue")
    parser.add_argument("--retry", action="store_true", help="include works previously found empty")
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    args = parser.parse_args()
    api_key = load_api_key()
    venues = venues_to_refresh({a for a in args.exclude_areas.split(",") if a}, args.venue)
    candidates, lfs = scan(os.path.realpath(args.cache_dir), venues, set() if args.retry else load_negative())
    print(f"{len(venues)} venues, {len(candidates):,} candidate works" + (f" ({lfs} LFS pointer files skipped)" if lfs else ""))
    if args.pilot:
        candidates = random.Random(2026).sample(candidates, min(args.pilot, len(candidates)))
    run(candidates, api_key, args.apply)


if __name__ == "__main__":
    main()
