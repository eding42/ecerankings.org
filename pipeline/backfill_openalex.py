#!/usr/bin/env python3
"""Backfill affiliation data into Crossref/S2-harvested works via OpenAlex DOI lookup.

A repair pass, not a harvest. Some cached works were pulled from Crossref or
Semantic Scholar and carry no affiliation data at all -- no resolved
`institutions`, no `raw_affiliations`. Their authors are invisible to
aggregate.py, so their institutions get no credit. Many of those same works
DO exist in OpenAlex with full affiliations; they were simply never matched.
This script finds them by DOI and writes OpenAlex's data back in.

Usage:
    python3 pipeline/backfill_openalex.py --pilot 500      # measure only, no writes
    python3 pipeline/backfill_openalex.py --pilot 500 --venue jlt
    python3 pipeline/backfill_openalex.py --apply          # rewrite the cache

Candidate selection (the "gap" this repairs):
    work has no `id` (never matched to an OpenAlex work)
    AND every authorship lacks both `institutions` and `raw_affiliations`
    AND the work has a DOI

Works already carrying an OpenAlex `id` are deliberately excluded: a 20-work
probe across 13 venues found 0 recoverable, i.e. OpenAlex genuinely holds no
affiliations for those. Querying them again would burn budget for nothing.

--pilot samples randomly across the whole candidate set (fixed seed) rather
than taking the first N, because candidates cluster hard by venue and year --
a head-of-list sample would measure one venue and call it the global rate.
"""

import argparse
import glob
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
API = "https://api.openalex.org/works"
MAILTO = "eding2019@gmail.com"
BATCH = 50          # OpenAlex OR-filter list length; verified working at 50
SLEEP = 0.03


def load_api_key():
    path = os.path.join(REPO_ROOT, ".env")
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        for line in fh:
            if line.startswith("OPENALEX_API_KEY"):
                return line.split("=", 1)[1].strip()
    return None


def norm_doi(doi):
    """Lowercase, strip the resolver prefix. OpenAlex returns
    'https://doi.org/10.1109/...' lowercased; the cache has mixed forms, so
    both sides must be normalized or every comparison is a phantom miss."""
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d or None


def is_candidate(work):
    """Any un-matched work with at least one author missing affiliation data.

    Deliberately NOT "every author is blank". Crossref often supplies
    affiliations for some authors of a paper and none for the rest; requiring
    all-blank skipped ~2,400 partially-covered works whose remaining authors
    are just as recoverable. Works that already carry an OpenAlex `id` stay
    excluded -- a 20-work probe across 13 venues found 0 recoverable, so
    OpenAlex genuinely holds nothing for them.
    """
    if work.get("id"):
        return False
    authorships = work.get("authorships") or []
    if not authorships:
        return False
    return any(
        not a.get("institutions") and not (a.get("raw_affiliations") or [])
        for a in authorships
    )


def scan_candidates(venue_filter=None):
    """Walk the cache and collect every repairable work.

    Returns (candidates, stats). Each candidate is a dict with the file path
    and line index so --apply can rewrite in place without a second scan.
    """
    candidates = []
    stats = Counter()
    pattern = os.path.join(CACHE_DIR, venue_filter or "*", "*", "works.jsonl")
    for path in sorted(glob.glob(pattern)):
        parts = path.split(os.sep)
        venue, year = parts[-3], parts[-2]
        with open(path) as fh:
            for idx, line in enumerate(fh):
                try:
                    work = json.loads(line)
                except json.JSONDecodeError:
                    stats["unparseable_lines"] += 1
                    continue
                if not is_candidate(work):
                    continue
                doi = norm_doi(work.get("doi"))
                if not doi:
                    stats["candidate_no_doi"] += 1
                    continue
                if "|" in doi:
                    # would break the OR-filter list
                    stats["candidate_doi_has_pipe"] += 1
                    continue
                candidates.append({
                    "path": path,
                    "line": idx,
                    "venue": venue,
                    "year": year,
                    "doi": doi,
                    "n_authors": len(work.get("authorships") or []),
                })
    return candidates, stats


def fetch_batch(dois, api_key, max_retries=5):
    """One OR-filtered request for up to BATCH DOIs. Returns {norm_doi: work}."""
    params = {
        "filter": "doi:" + "|".join(dois),
        "select": "id,doi,authorships",
        "per-page": str(len(dois)),
        "mailto": MAILTO,
    }
    if api_key:
        params["api_key"] = api_key
    url = API + "?" + urllib.parse.urlencode(params)

    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                payload = json.load(resp)
            out = {}
            for work in payload.get("results") or []:
                d = norm_doi(work.get("doi"))
                if d:
                    out[d] = work
            return out
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504):
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = float(retry_after) if retry_after else 2 ** attempt
                sys.stderr.write(f"  HTTP {exc.code}, retry in {delay:.0f}s\n")
                time.sleep(delay)
                continue
            raise
        except (OSError, json.JSONDecodeError) as exc:
            # OSError, not URLError: a mid-stream `ConnectionResetError` from the
            # socket layer is a bare OSError and slips past a URLError-only
            # handler, killing a 1000-request run outright. URLError and
            # socket.timeout are both OSError subclasses, so this covers them
            # too. HTTPError is caught above and must stay first -- it is also
            # an OSError subclass and would otherwise be swallowed here.
            delay = 2 ** attempt
            sys.stderr.write(f"  {type(exc).__name__}, retry in {delay}s\n")
            time.sleep(delay)
    sys.stderr.write(f"  BATCH FAILED after {max_retries} attempts\n")
    return {}


def classify(work):
    """How useful is this OpenAlex record? Resolved institutions are worth more
    than raw strings: they skip affiliation-map.csv and its error classes."""
    authorships = work.get("authorships") or []
    if not authorships:
        return "empty_authorships", 0, 0
    resolved = sum(1 for a in authorships if a.get("institutions"))
    raw = sum(1 for a in authorships if a.get("raw_affiliation_strings"))
    if resolved:
        return "resolved", resolved, raw
    if raw:
        return "raw_only", resolved, raw
    return "no_affil", 0, 0


def run_pilot(candidates, sample_size, api_key):
    random.seed(42)
    sample = random.sample(candidates, min(sample_size, len(candidates)))
    print(f"\nPilot: {len(sample)} DOIs sampled (seed=42) from "
          f"{len(candidates):,} candidates across "
          f"{len({c['venue'] for c in candidates})} venues")
    print(f"Requests: {(len(sample) + BATCH - 1) // BATCH}\n")

    verdicts = Counter()
    slots_total = slots_recovered = 0
    by_venue = defaultdict(Counter)
    by_year = defaultdict(Counter)
    index = {c["doi"]: c for c in sample}

    dois = [c["doi"] for c in sample]
    for i in range(0, len(dois), BATCH):
        chunk = dois[i:i + BATCH]
        found = fetch_batch(chunk, api_key)
        for doi in chunk:
            cand = index[doi]
            slots_total += cand["n_authors"]
            work = found.get(doi)
            if work is None:
                verdicts["not_in_openalex"] += 1
                by_venue[cand["venue"]]["miss"] += 1
                by_year[cand["year"]]["miss"] += 1
                continue
            verdict, resolved, raw = classify(work)
            verdicts[verdict] += 1
            if verdict == "resolved":
                slots_recovered += resolved
                by_venue[cand["venue"]]["hit"] += 1
                by_year[cand["year"]]["hit"] += 1
            else:
                by_venue[cand["venue"]]["miss"] += 1
                by_year[cand["year"]]["miss"] += 1
        done = min(i + BATCH, len(dois))
        print(f"  {done}/{len(dois)} probed", end="\r", flush=True)
        time.sleep(SLEEP)

    n = len(sample)
    hit = verdicts["resolved"]
    print(" " * 40, end="\r")
    print("=" * 66)
    print("PILOT RESULT")
    print("=" * 66)
    for k, v in verdicts.most_common():
        print(f"  {v:5d}  {v / n * 100:5.1f}%  {k}")
    print(f"\n  hit rate (resolved institutions): {hit}/{n} = {hit / n * 100:.1f}%")
    if slots_total:
        print(f"  author slots in sample: {slots_total:,}  "
              f"recovered: {slots_recovered:,} ({slots_recovered / slots_total * 100:.1f}%)")

    total_slots = sum(c["n_authors"] for c in candidates)
    print(f"\n  EXTRAPOLATED TO FULL RUN ({len(candidates):,} works, "
          f"{total_slots:,} slots):")
    if slots_total:
        rate = slots_recovered / slots_total
        print(f"    ~{int(total_slots * rate):,} author slots recoverable "
              f"({rate * 100:.1f}%)")
    print(f"    ~{(len(candidates) + BATCH - 1) // BATCH:,} requests")

    print("\n  by venue (hit / probed):")
    for venue in sorted(by_venue, key=lambda v: -(by_venue[v]["hit"] + by_venue[v]["miss"])):
        c = by_venue[venue]
        tot = c["hit"] + c["miss"]
        if tot < 3:
            continue
        print(f"    {venue:12s} {c['hit']:4d}/{tot:4d}  {c['hit'] / tot * 100:5.1f}%")

    print("\n  by year bucket (hit / probed):")
    buckets = defaultdict(Counter)
    for year, c in by_year.items():
        try:
            b = int(year) // 5 * 5
        except ValueError:
            continue
        buckets[b]["hit"] += c["hit"]
        buckets[b]["miss"] += c["miss"]
    for b in sorted(buckets):
        c = buckets[b]
        tot = c["hit"] + c["miss"]
        print(f"    {b}-{b + 4}: {c['hit']:4d}/{tot:4d}  {c['hit'] / tot * 100:5.1f}%")
    print("=" * 66)
    print("\nNo files were modified. Re-run with --apply to write.")


def merge_work(cached, fresh):
    """Replace the cached record's authorships wholesale with OpenAlex's.

    Deliberately NOT a positional merge: OpenAlex's authorship array need not
    match Crossref's in order or length, so merging index-by-index would
    silently attach the wrong institution to the wrong person. A confident DOI
    match means OpenAlex's author list is the better record of the same paper.
    Side effect: author_id upgrades from synthetic 'crossref:name:*' to real
    OpenAlex author IDs.
    """
    authorships = []
    for a in fresh.get("authorships") or []:
        author = a.get("author") or {}
        authorships.append({
            "author_id": author.get("id"),
            "author_name": author.get("display_name"),
            # Keep OpenAlex's institution objects WHOLE. aggregate.py filters on
            # institutions[].type ("education") at line 199 and rolls up parents
            # via institutions[].lineage at line 218 -- cherry-picking id and
            # display_name strips both, and the failure is silent: a typeless
            # institution matches no CREDIT_TYPE, and the raw_affiliations
            # fallback at line 201 is skipped because `insts` is non-empty, so
            # every backfilled author gets dropped with the counts still looking
            # plausible.
            "institutions": [dict(i) for i in (a.get("institutions") or [])],
            "raw_affiliations": list(a.get("raw_affiliation_strings") or []),
        })
    if not authorships:
        return None
    out = dict(cached)
    out["id"] = fresh.get("id")
    out["authorships"] = authorships
    out["backfilled_from"] = "openalex"
    return out


def run_apply(candidates, api_key):
    by_file = defaultdict(list)
    for c in candidates:
        by_file[c["path"]].append(c)

    dois = [c["doi"] for c in candidates]
    resolved_works = {}
    negative = set()

    # Fetch is the long half of this run (~1000 requests). Checkpoint each batch
    # so a crash or Ctrl-C resumes instead of re-spending the whole budget; the
    # file is removed once the rewrite pass succeeds.
    ckpt_path = os.path.join(CACHE_DIR, ".backfill-checkpoint.jsonl")
    if os.path.exists(ckpt_path):
        with open(ckpt_path) as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("neg"):
                    negative.add(rec["doi"])
                elif rec.get("work"):
                    resolved_works[rec["doi"]] = rec["work"]
        done = len(resolved_works) + len(negative)
        dois = [d for d in dois if d not in resolved_works and d not in negative]
        print(f"  resuming: {done:,} DOIs already fetched, {len(dois):,} remaining")

    total_batches = (len(dois) + BATCH - 1) // BATCH
    with open(ckpt_path, "a") as ckpt:
        for i in range(0, len(dois), BATCH):
            chunk = dois[i:i + BATCH]
            found = fetch_batch(chunk, api_key)
            for doi in chunk:
                work = found.get(doi)
                verdict = classify(work)[0] if work is not None else None
                if work is not None and verdict in ("resolved", "raw_only"):
                    resolved_works[doi] = work
                    ckpt.write(json.dumps({"doi": doi, "work": work}) + "\n")
                else:
                    negative.add(doi)
                    ckpt.write(json.dumps({"doi": doi, "neg": True}) + "\n")
            ckpt.flush()
            print(f"  batch {i // BATCH + 1}/{total_batches}  "
                  f"recovered {len(resolved_works):,}", end="\r", flush=True)
            time.sleep(SLEEP)
    print()

    rewritten = files_touched = 0
    for path, cands in sorted(by_file.items()):
        targets = {c["line"]: c["doi"] for c in cands
                   if c["doi"] in resolved_works}
        if not targets:
            continue
        tmp = path + ".tmp"
        changed = 0
        with open(path) as src, open(tmp, "w") as dst:
            for idx, line in enumerate(src):
                doi = targets.get(idx)
                if doi is not None:
                    try:
                        cached = json.loads(line)
                        merged = merge_work(cached, resolved_works[doi])
                        if merged is not None:
                            line = json.dumps(merged, ensure_ascii=False) + "\n"
                            changed += 1
                    except json.JSONDecodeError:
                        pass
                dst.write(line)
        os.replace(tmp, path)
        rewritten += changed
        files_touched += 1

    neg_path = os.path.join(CACHE_DIR, ".backfill-negative.txt")
    existing = set()
    if os.path.exists(neg_path):
        with open(neg_path) as fh:
            existing = {ln.strip() for ln in fh if ln.strip()}
    with open(neg_path, "w") as fh:
        for doi in sorted(existing | negative):
            fh.write(doi + "\n")

    if os.path.exists(ckpt_path):
        os.remove(ckpt_path)

    print("=" * 66)
    print(f"  works rewritten:     {rewritten:,}")
    print(f"  files touched:       {files_touched:,}")
    print(f"  negative-cached:     {len(negative):,}  -> {neg_path}")
    print("=" * 66)
    print("\nNext: python3 pipeline/aggregate.py && python3 pipeline/split.py")
    print("Then: python3 pipeline/verify.py --all")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--pilot", type=int, metavar="N",
                   help="probe N randomly sampled DOIs, report only, write nothing")
    g.add_argument("--apply", action="store_true",
                   help="run the full backfill and rewrite the cache")
    ap.add_argument("--venue", help="restrict to a single venue key")
    args = ap.parse_args()

    api_key = load_api_key()
    if not api_key:
        sys.stderr.write("WARNING: no OPENALEX_API_KEY in .env; using the "
                         "unauthenticated pool\n")

    print("Scanning cache for repairable works...")
    candidates, stats = scan_candidates(args.venue)
    total_slots = sum(c["n_authors"] for c in candidates)
    print(f"  candidates: {len(candidates):,} works, {total_slots:,} author slots")
    for k, v in stats.most_common():
        print(f"  {k}: {v:,}")
    if not candidates:
        print("Nothing to do.")
        return

    # skip DOIs already known to be fruitless
    neg_path = os.path.join(CACHE_DIR, ".backfill-negative.txt")
    if os.path.exists(neg_path):
        with open(neg_path) as fh:
            negative = {ln.strip() for ln in fh if ln.strip()}
        before = len(candidates)
        candidates = [c for c in candidates if c["doi"] not in negative]
        if before != len(candidates):
            print(f"  skipped {before - len(candidates):,} negative-cached DOIs")

    if args.pilot:
        run_pilot(candidates, args.pilot, api_key)
    else:
        run_apply(candidates, api_key)


if __name__ == "__main__":
    main()
