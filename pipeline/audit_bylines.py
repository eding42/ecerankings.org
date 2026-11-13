#!/usr/bin/env python3
"""Compare cached bylines with an independent source, one work at a time.

verify_authors.py finds author-list problems the cache can show on its own.
This finds the ones it cannot: a byline in the wrong order, authors missing or
added, a list cut short. It draws a seeded random sample of works with a DOI,
asks Crossref for the publisher-deposited author list, and compares position
by position on normalized family names.

Credit is 1/N per author and the affiliation belongs to a position, so a
shifted or truncated list moves credit even when every institution is right.

    python3 pipeline/audit_bylines.py [--seed 2026] [--size 200] [--max-bad 0.05]

Per work the outcome is one of:
    exact        same authors in the same order
    reordered    same authors, different order (positions are wrong)
    names_differ same length and mostly the same authors, but a name is wrong or cut
    cache_short  the cache has fewer authors than Crossref (list cut or authors lost)
    cache_long   the cache has more authors than Crossref
    different    the lists share too few names to be the same byline
    no_reference Crossref has no authors for the DOI (not counted)

Network, opt-in. Sends only DOIs. Writes data/reports/byline-audit-*.md.
Stdlib only.
"""

import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_map_sample import wilson  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
REPORT_DIR = os.path.join(REPO_ROOT, "data", "reports")
USER_AGENT = "ece-rankings-byline-audit/1.0"
NONRESEARCH = {"editorial", "erratum", "letter", "book-review", "peer-review", "retraction", "other"}
BAD = ("reordered", "names_differ", "cache_short", "cache_long", "different")
MIN_OVERLAP = 0.6


def family_key(name):
    """Last token of a name, ASCII-folded. 'Hector J. Sussmann' -> 'sussmann'."""
    name = re.sub("[\u2010-\u2015\u2212]", "-", name or "")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"\b(jr|sr|ii|iii|phd|sj)\b\.?", "", name)
    parts = re.findall(r"[a-z]+", name)
    return parts[-1] if parts else ""


def name_tokens(name):
    """Sorted name parts, so "Hwang Wan Sik" equals "Wan-Sik Hwang" and "Vincent K. N. Lau"."""
    name = re.sub("[\u2010-\u2015\u2212]", "-", name or "")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return sorted(re.findall(r"[a-z]+", name))


def crossref_keys(message):
    return [family_key(" ".join(filter(None, [a.get("given"), a.get("family") or a.get("name")])))
            for a in message.get("author") or []]


def compare(cached, reference):
    """Outcome of comparing two lists of family-name keys."""
    if not reference:
        return "no_reference"
    if cached == reference:
        return "exact"
    if reference[:len(cached)] == cached:
        return "cache_short"
    if cached[:len(reference)] == reference:
        return "cache_long"
    overlap = len(Counter(cached) & Counter(reference)) / max(len(set(reference)), 1)
    if overlap < MIN_OVERLAP:
        return "different"
    if sorted(cached) == sorted(reference):
        return "reordered"
    if len(cached) == len(reference):
        return "names_differ"
    return "cache_short" if len(cached) < len(reference) else "cache_long"


def collect(cache_dir, registry, seed, size, all_areas=False):
    venues = sorted({v["key"] for a in registry["areas"].values() if all_areas or a.get("default_on", True)
                     for v in a["venues"]})
    pool = []
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
                    if work.get("doi") and authors and (work.get("type") or "").lower() not in NONRESEARCH:
                        pool.append((venue, int(year), work["doi"].replace("https://doi.org/", ""),
                                     [family_key(a.get("author_name")) for a in authors]))
    random.Random(seed).shuffle(pool)
    return pool[:size], len(pool)


def fetch(doi):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=30) as r:
                return json.load(r)["message"]
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            time.sleep(3 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError):
            time.sleep(3 * (attempt + 1))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--size", type=int, default=200)
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    parser.add_argument("--all-areas", action="store_true")
    parser.add_argument("--max-bad", type=float, default=0.05, help="exit 2 above this share of mismatched bylines")
    args = parser.parse_args()
    with open(AREAS_JSON) as handle:
        registry = json.load(handle)
    sample, pool_size = collect(os.path.realpath(args.cache_dir), registry, args.seed, args.size, args.all_areas)
    results, by_venue, examples = Counter(), defaultdict(Counter), defaultdict(list)
    for venue, year, doi, cached in sample:
        message = fetch(doi)
        outcome = compare(cached, crossref_keys(message)) if message else "no_reference"
        results[outcome] += 1
        by_venue[venue][outcome] += 1
        if outcome in BAD and len(examples[outcome]) < 6:
            examples[outcome].append(f"{venue} {year} {doi}: cache {len(cached)} authors, "
                                     f"Crossref {len(crossref_keys(message))}")
        time.sleep(0.15)
    judged = sum(v for k, v in results.items() if k != "no_reference")
    bad = sum(results[k] for k in BAD)
    p, low, high = wilson(bad, judged)
    lines = [f"# Byline audit, seed {args.seed}, {date.today().isoformat()}", "",
             f"{len(sample)} works sampled from {pool_size:,}; {judged} had a Crossref author list.", "",
             "| outcome | works |", "|---|---|"] + [f"| {k} | {v} |" for k, v in results.most_common()]
    lines += ["", f"**Mismatched bylines: {p:.1%} (95% interval {low:.1%} to {high:.1%}).**", ""]
    for outcome, rows in examples.items():
        lines += [f"## {outcome}"] + [f"- {r}" for r in rows] + [""]
    worst = sorted(((sum(c[k] for k in BAD) / max(sum(v for kk, v in c.items() if kk != 'no_reference'), 1), v, sum(c.values()))
                    for v, c in by_venue.items() if sum(c.values()) >= 5), reverse=True)[:8]
    if worst:
        lines += ["## Worst venues (at least 5 sampled)"] + [f"- {v}: {100 * r:.0f}% of {n}" for r, v, n in worst]
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"byline-audit-{date.today().isoformat()}-seed{args.seed}.md")
    with open(path, "w", encoding="utf8") as handle:
        handle.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nreport: {os.path.relpath(path, REPO_ROOT)}")
    return 2 if p > args.max_bad else 0


if __name__ == "__main__":
    sys.exit(main())
