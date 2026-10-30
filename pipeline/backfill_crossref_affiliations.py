#!/usr/bin/env python3
"""Fill empty author-slot affiliations in OpenAlex-native cache rows from Crossref.

Some OpenAlex-native venues (Optica is the case in point) carry works whose
author slots have neither resolved `institutions` nor `raw_affiliations`,
while Crossref holds the publisher's own affiliation strings for the same DOI.
backfill_openalex.py skips these works because they already have an OpenAlex
id, so this repair is the complement: it adds Crossref raw strings to slots
that are empty, never overwriting OpenAlex's resolved institutions.

aggregate.py credits raw_affiliations only when a slot has no `institutions`,
and then resolves them through data/affiliation-map.csv. The filled strings
therefore go through the curated map, not OpenAlex's resolution.

Alignment is conservative. A work is touched only when Crossref's author
count equals the cached authorship count and, for every slot that would be
filled, the Crossref family name appears among the OpenAlex author-name tokens.
Any mismatch skips the whole work and is reported.

Usage:
    python3 pipeline/backfill_crossref_affiliations.py --venue optica --years 2023 2026        # measure only
    python3 pipeline/backfill_crossref_affiliations.py --venue optica --years 2023 2026 --apply

Crossref is queried per DOI (no key, polite mailto). Works already having
Crossref-sourced or fully affiliated slots are not re-queried.
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
API = "https://api.crossref.org/works/"
MAILTO = "eding2019@gmail.com"
SLEEP = 0.15
MAX_RETRIES = 5


def norm_doi(doi):
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^https?://(dx\.)?doi\.org/", "", d)
    return d or None


def norm_token(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", text.lower())


def family_in_name(family, openalex_name):
    """True when the Crossref family name appears as a contiguous run of tokens in the OpenAlex display name.

    Hyphenated families ("Lopez-Ruiz") match a display name that splits them
    ("Ana Lopez Ruiz"); a family must match whole tokens, never a substring.
    """
    fam = [norm_token(t) for t in re.split(r"[\s\-]+", family or "")]
    fam = [t for t in fam if t]
    tokens = [norm_token(t) for t in re.split(r"[\s\-]+", openalex_name or "")]
    tokens = [t for t in tokens if t]
    if not fam or len(fam) > len(tokens):
        return False
    return any(tokens[i:i + len(fam)] == fam for i in range(len(tokens) - len(fam) + 1))


def crossref_affiliations(author):
    out = []
    for aff in author.get("affiliation") or []:
        name = (aff.get("name") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def fetch_crossref_work(doi, state):
    url = API + urllib.parse.quote(doi, safe="/") + "?" + urllib.parse.urlencode({"mailto": MAILTO})
    headers = {"User-Agent": f"ecerankings-refresh (mailto:{MAILTO})"}
    for attempt in range(MAX_RETRIES):
        try:
            time.sleep(SLEEP)
            state["calls"] += 1
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as resp:
                return json.load(resp).get("message")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (429, 500, 502, 503, 504):
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = float(retry_after) if retry_after else 2 ** attempt
                sys.stderr.write(f"  HTTP {exc.code}, retry in {delay:.0f}s\n")
                time.sleep(delay)
                continue
            raise
        except (OSError, json.JSONDecodeError) as exc:
            delay = 2 ** attempt
            sys.stderr.write(f"  {type(exc).__name__}, retry in {delay}s\n")
            time.sleep(delay)
    sys.stderr.write(f"  FAILED after {MAX_RETRIES} attempts: {doi}\n")
    return None


def slot_is_empty(authorship):
    return not authorship.get("institutions") and not authorship.get("raw_affiliations")


def plan_work(work, cr_message):
    """Return (fills, status). fills maps slot index -> list of raw affiliation strings."""
    authorships = work.get("authorships") or []
    cr_authors = (cr_message or {}).get("author") or []
    if not any(slot_is_empty(a) for a in authorships):
        return {}, "no-empty-slots"
    if not cr_authors:
        return {}, "crossref-no-authors"
    if len(cr_authors) != len(authorships):
        return {}, "author-count-mismatch"
    fills = {}
    for idx, (slot, cr_author) in enumerate(zip(authorships, cr_authors)):
        if not slot_is_empty(slot):
            continue
        affs = crossref_affiliations(cr_author)
        if not affs:
            continue
        if not family_in_name(cr_author.get("family"), slot.get("author_name")):
            return {}, "name-misaligned"
        fills[idx] = affs
    return fills, "filled" if fills else "crossref-no-affiliations"


def coverage(works):
    slots = aff = 0
    for w in works:
        for a in w.get("authorships") or []:
            slots += 1
            aff += bool(a.get("institutions") or a.get("raw_affiliations"))
    return slots, aff


def process_venue(venue, years, apply_changes):
    state = {"calls": 0}
    stats = Counter()
    for year in years:
        path = os.path.join(CACHE_DIR, venue, str(year), "works.jsonl")
        if not os.path.isfile(path):
            print(f"  {venue} {year}: no cache file, skipped")
            continue
        with open(path) as fh:
            works = [json.loads(line) for line in fh if line.strip()]
        before = coverage(works)
        filled_slots = 0
        candidates = [w for w in works if w.get("source") == "openalex"
                      and any(slot_is_empty(a) for a in w.get("authorships") or [])]
        year_status = Counter()
        for work in candidates:
            doi = norm_doi(work.get("doi"))
            if not doi:
                year_status["no-doi"] += 1
                continue
            message = fetch_crossref_work(doi, state)
            if message is None:
                year_status["crossref-missing"] += 1
                continue
            fills, status = plan_work(work, message)
            year_status[status] += 1
            if not fills:
                continue
            for idx, affs in fills.items():
                work["authorships"][idx]["raw_affiliations"] = affs
                filled_slots += 1
            work.setdefault("provenance", {})["crossref_affiliation_fill"] = {
                "source": "crossref", "slots_filled": len(fills)}
        after = coverage(works)
        stats[year] = filled_slots
        print(f"  {venue} {year}: slots {before[1]}/{before[0]} "
              f"({100 * before[1] / max(before[0], 1):.1f}%) -> {after[1]}/{after[0]} "
              f"({100 * after[1] / max(after[0], 1):.1f}%); filled {filled_slots}; "
              f"works {dict(year_status)}")
        if apply_changes and filled_slots:
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                for w in works:
                    fh.write(json.dumps(w, ensure_ascii=False) + "\n")
            os.replace(tmp, path)
            print(f"    rewrote {os.path.relpath(path, REPO_ROOT)}")
    print(f"  Crossref HTTP calls: {state['calls']}")
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--venue", required=True, help="venue key, e.g. optica")
    ap.add_argument("--years", nargs=2, type=int, required=True, metavar=("FIRST", "LAST"))
    ap.add_argument("--apply", action="store_true", help="rewrite cache files (default: measure only)")
    args = ap.parse_args(argv)
    years = list(range(args.years[0], args.years[1] + 1))
    print(f"{'Applying' if args.apply else 'Measuring'} Crossref affiliation fill for {args.venue} {years[0]}-{years[-1]}")
    process_venue(args.venue, years, args.apply)
    if not args.apply:
        print("No files were modified. Re-run with --apply to write.")


if __name__ == "__main__":
    main()
