#!/usr/bin/env python3
"""Author integrity: is the byline of every paper what the publisher printed?

Credit is 1/N per author, so every problem with the author list moves credit
even when the affiliations are perfect. A survey of the cache on 2026-11-12
found all of these in default-on venues:

  A1  a venue-year whose share of author-less works jumps far above that
      venue's own norm. 17,164 works (2.8%) have no authors, but nearly all
      are front matter (blank pages, staff lists, advertisements) or Nature
      News & Views, which correctly credit nothing. A spike means authors
      stopped arriving;
  A2  author lists cut at the API cap: 786 works have exactly 100 authors
      against 12 with 99. OpenAlex returns at most 100 authorships per work
      in list responses, so a 400-author collaboration paper splits its
      credit 100 ways and the other 300 authors get none;
  A3  the same author twice in one byline (512 works). The paper's credit
      is split one share too many and that person is counted twice;
  A4  group names filed as authors ("The Supernova Cosmology Project",
      "the Cassini RADAR Team"). They take a 1/N share that no university
      can ever receive;
  A5  garbled names: replacement characters, mojibake, HTML entities. Names
      are what synthetic author ids are built from, so one person becomes
      several;
  A6  authors with five or more institutions on one paper, which means an
      affiliation list was attached to every author instead of to its own
      author (the credit is spread over institutions the author does not
      belong to).

Each check aggregates to one line per venue, ranked by the credit it moves.
Run through verify.py (`--all` or `--phase 5`) or directly:

    python3 pipeline/verify_authors.py [--cache-dir DIR] [--all-areas]

Read-only. Python stdlib only.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from workkey import record_key, work_key  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AREAS_JSON = os.path.join(REPO_ROOT, "data", "areas.json")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
EXCLUDED_CSV = os.path.join(REPO_ROOT, "data", "excluded-works.csv")

NONRESEARCH_TYPES = {"editorial", "erratum", "letter", "book-review", "peer-review", "retraction", "other"}

AUTHOR_CAP = 100             # OpenAlex returns at most this many authorships per work in list responses
CAP_MIN_WORKS = 5            # works at the cap before a venue is worth a line...
CAP_SPIKE_RATIO = 3          # ...and they must outnumber the neighbouring counts this much
CAP_CRITICAL, CAP_HIGH = 50, 10
ZERO_SPIKE_RATIO = 2.0       # a venue-year's author-less share against the venue's median year
ZERO_MIN_SHARE, ZERO_MIN_WORKS = 0.25, 20
ZERO_CRITICAL_SHARE = 0.60
CREDIT_CRITICAL, CREDIT_HIGH = 25.0, 5.0          # duplicate and group-name credit per venue
GARBLED_HIGH, GARBLED_MEDIUM = 20, 3
SPREAD_INSTITUTIONS = 5
SPREAD_MEDIUM_SHARE = 0.02

GROUP_RE = re.compile(
    r"collaboration|consortium|\bteam\b|working group|study group|\bcommittee\b|\bthe\b.+\b(?:project|survey|experiment|mission)\b|"
    r"^\(.*\)$", re.I)
GARBLED_RE = re.compile(r"�|Ã[\u0080-¿¡-ÿ]|â€|Â[ -¿]|&#x?[0-9a-fA-F]+;|&[a-z]{2,6};|[\x00-\x08\x0b-\x1f]")


def is_group_name(name):
    return bool(GROUP_RE.search(name or ""))


def is_garbled(name):
    name = name or ""
    return bool(GARBLED_RE.search(name)) or (bool(name) and not re.search(r"[^\W\d_]", name))


def normalize_name(name):
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def load_excluded(path=EXCLUDED_CSV):
    import csv
    if not os.path.exists(path):
        return set()
    with open(path, newline="") as handle:
        return {(row.get("work_key") or "").strip() for row in csv.DictReader(handle)} - {""}


def scan(cache_dir, registry, excluded=frozenset(), all_areas=False):
    """One pass over the default-on cache. Returns per-venue counters."""
    venues = [v["key"] for a in registry["areas"].values() if all_areas or a.get("default_on", True)
              for v in a["venues"]]
    out = {"venues": {}, "zero": defaultdict(Counter), "examples": defaultdict(list)}
    for venue in sorted(set(venues)):
        venue_dir = os.path.join(cache_dir, venue)
        if not os.path.isdir(venue_dir):
            continue
        c = Counter()
        sizes = Counter()
        seen = set()
        for entry in sorted(os.listdir(venue_dir)):
            path = os.path.join(venue_dir, entry, "works.jsonl")
            if not entry.isdigit() or not os.path.exists(path):
                continue
            year = int(entry)
            with open(path) as handle:
                for line in handle:
                    work = json.loads(line)
                    identity = record_key(work, venue, year)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if (work.get("type") or "").lower() in NONRESEARCH_TYPES:
                        continue
                    if work_key(work, venue, year) in excluded:
                        continue
                    authors = work.get("authorships") or []
                    c["works"] += 1
                    out["zero"][(venue, year)]["works"] += 1
                    if not authors:
                        c["zero_author_works"] += 1
                        out["zero"][(venue, year)]["zero"] += 1
                        continue
                    n = len(authors)
                    sizes[n] += 1
                    share = 1.0 / n
                    ids = Counter(a.get("author_id") for a in authors if a.get("author_id"))
                    extra = sum(k - 1 for k in ids.values() if k > 1)
                    if extra:
                        c["dup_works"] += 1
                        c["dup_credit"] += extra * share
                        if len(out["examples"][(venue, "dup")]) < 2:
                            out["examples"][(venue, "dup")].append(work.get("doi") or work.get("title"))
                    for author in authors:
                        name = author.get("author_name") or ""
                        c["authorships"] += 1
                        if is_group_name(name):
                            c["group_authors"] += 1
                            c["group_credit"] += share
                            if len(out["examples"][(venue, "group")]) < 2:
                                out["examples"][(venue, "group")].append(name)
                        if is_garbled(name):
                            c["garbled"] += 1
                            if len(out["examples"][(venue, "garbled")]) < 3:
                                out["examples"][(venue, "garbled")].append(name)
                        if len(author.get("institutions") or []) >= SPREAD_INSTITUTIONS:
                            c["spread"] += 1
        c["at_cap"] = sizes[AUTHOR_CAP]
        c["below_cap"] = max(sizes[AUTHOR_CAP - 1], sizes[AUTHOR_CAP - 2], 1)
        out["venues"][venue] = c
    return out


def check(flags, result):
    """Turn the scan into severity-ranked lines."""
    rows = result["venues"]
    for venue, c in sorted(rows.items(), key=lambda kv: -kv[1]["at_cap"]):
        if c["at_cap"] >= CAP_MIN_WORKS and c["at_cap"] >= CAP_SPIKE_RATIO * c["below_cap"]:
            severity = "critical" if c["at_cap"] >= CAP_CRITICAL else "high" if c["at_cap"] >= CAP_HIGH else "medium"
            flags[severity].append(
                f"[authors/truncated] {venue}: {c['at_cap']} works have exactly {AUTHOR_CAP} authors against "
                f"{c['below_cap']} just below; the author list was cut at the API cap, so these papers split their"
                f" credit {AUTHOR_CAP} ways and drop every later author")
    by_venue = defaultdict(dict)
    for (venue, year), c in result["zero"].items():
        if c["works"] >= 10:
            by_venue[venue][year] = (c["zero"] / c["works"], c["zero"], c["works"])
    for venue, years in sorted(by_venue.items()):
        shares = sorted(share for share, _, _ in years.values())
        median = shares[len(shares) // 2]
        for year, (share, zero, works) in sorted(years.items()):
            if zero >= ZERO_MIN_WORKS and share >= ZERO_MIN_SHARE and share >= ZERO_SPIKE_RATIO * max(median, 0.01):
                severity = "critical" if share >= ZERO_CRITICAL_SHARE else "high"
                flags[severity].append(
                    f"[authors/none] {venue} {year}: {zero} of {works} works ({share:.0%}) carry no authors against a"
                    f" venue median of {median:.0%}; authors stopped arriving, and those papers credit nothing")
    for venue, c in rows.items():
        for key, label, what in (
                ("dup_credit", "duplicate", "lists the same author twice, so each paper's credit is split one share too many"),
                ("group_credit", "group", "files group names as authors; their share can never reach a university")):
            credit = c[key]
            severity = "critical" if credit >= CREDIT_CRITICAL else "high" if credit >= CREDIT_HIGH else None
            if severity:
                count = c["dup_works"] if key == "dup_credit" else c["group_authors"]
                sample = (result["examples"].get((venue, "dup" if key == "dup_credit" else "group")) or [""])[0]
                flags[severity].append(
                    f"[authors/{label}] {venue}: ~{credit:.0f} credits across {count} {'works' if key == 'dup_credit' else 'authors'};"
                    f" the byline {what} (e.g. {sample!r})")
        if c["garbled"] >= GARBLED_MEDIUM:
            severity = "high" if c["garbled"] >= GARBLED_HIGH else "medium"
            flags[severity].append(
                f"[authors/garbled] {venue}: {c['garbled']} author names are corrupted (e.g. "
                f"{', '.join(repr(x) for x in result['examples'].get((venue, 'garbled'), [])[:3])})")
        if c["authorships"] and c["spread"] / c["authorships"] >= SPREAD_MEDIUM_SHARE and c["spread"] >= 20:
            flags["medium"].append(
                f"[authors/spread] {venue}: {c['spread']} authorships ({c['spread'] / c['authorships']:.1%}) carry "
                f"{SPREAD_INSTITUTIONS}+ institutions; an affiliation list was probably attached to every author")
    return flags


def run(registry, cache_dir=None, area=None, all_areas=False):
    cache_dir = cache_dir or CACHE_DIR
    if area and area != "all":
        registry = {**registry, "areas": {area: registry["areas"][area]}}
    flags = {"critical": [], "high": [], "medium": [], "low": []}
    print("\n── Phase 5: Author integrity ──")
    result = scan(cache_dir, registry, load_excluded(), all_areas)
    check(flags, result)
    total = Counter()
    for c in result["venues"].values():
        total.update(c)
    flags["low"].append(
        f"[authors/summary] {total['works']:,} works: {total['zero_author_works']:,} without authors, "
        f"{total['at_cap']:,} at the {AUTHOR_CAP}-author cap, {total['dup_works']:,} with a repeated author, "
        f"{total['group_authors']:,} group-name authors, {total['garbled']:,} garbled names")
    print(f"  {len(flags['critical'])} critical, {len(flags['high'])} high, {len(flags['medium'])} medium")
    return flags


def main():
    parser = argparse.ArgumentParser(description="Author-list integrity of the ECERankings corpus.")
    parser.add_argument("--cache-dir", default=CACHE_DIR)
    parser.add_argument("--all-areas", action="store_true", help="include areas that are off by default")
    parser.add_argument("--area", default=None)
    args = parser.parse_args()
    with open(AREAS_JSON) as handle:
        registry = json.load(handle)
    flags = run(registry, os.path.realpath(args.cache_dir), args.area, args.all_areas)
    for severity, icon in (("critical", "🔴"), ("high", "🟠"), ("medium", "🟡"), ("low", "⚪")):
        if flags[severity]:
            print(f"\n{icon} {severity.upper()}:")
            for item in flags[severity]:
                print(f"  {item}")
    return 2 if flags["critical"] or flags["high"] else 0


if __name__ == "__main__":
    sys.exit(main())
