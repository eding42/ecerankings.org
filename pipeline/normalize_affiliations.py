#!/usr/bin/env python3
"""Resolve Crossref free-text affiliation strings to OpenAlex institutions.

Usage:
    python3 pipeline/normalize_affiliations.py --venue iedm
    python3 pipeline/normalize_affiliations.py --venue iedm --year 2023
    python3 pipeline/normalize_affiliations.py --all-cached
    python3 pipeline/normalize_affiliations.py --venue iedm --report-only

Reads raw_affiliations[] from cached Crossref works, resolves each DISTINCT
string once via the OpenAlex /institutions endpoint, and records every
decision in data/affiliation-map.csv. aggregate.py joins that map at read
time, so the cache stays raw and improving the map never requires
re-harvesting.

Why resolve against OpenAlex rather than fuzzy-matching a local list:
OpenAlex returns the institution `type` (education / company / government /
facility / nonprofit), which is exactly what aggregate.py needs for its
education-only filter. A purely local match couldn't classify an
institution it had never seen.

Conservative by design
----------------------
A wrong match silently misattributes papers, which is worse than no match
at all, so every resolution is tiered by confidence and only the top tier
is trusted automatically:

    auto      score >= AUTO_THRESHOLD   -- used for credit
    manual    human-entered             -- used for credit, never overwritten
    review    MIN_THRESHOLD <= score    -- NOT used; awaiting human decision
    unmatched below MIN_THRESHOLD       -- NOT used

`review` and `unmatched` rows are written to the map with their score,
which candidate segment produced them, and which institution name they
matched against, so a human can audit and either fix the row and set
status=manual, or leave it dropped. This file IS the manual-curation
surface described in PLAN.md Phase 1b.

The matcher was built against three real failure modes found in IEDM 2023
data (see git history / PLAN.md):

 1. FALSE POSITIVE via acronyms. "Applied Materials, Inc.,Santa Clara,CA,USA"
    split on commas yields a bare "Inc." segment; searching it returns 1045
    hits, and "Institut de Chimie" carries the acronym "INC", scoring a
    perfect 1.00. Fixed by (a) never searching corporate-suffix/noise
    segments, and (b) only scoring against an institution's acronyms when
    the candidate is itself acronym-shaped.

 2. LONG NAMES RETURN ZERO HITS. OpenAlex institution search behaves
    phrase-like: "Korea Advanced Institute of Science and Technology (KAIST)"
    returns 0 hits, though bare "KAIST" matches exactly, and "Applied
    Materials Inc." returns 0 while "Applied Materials" returns 9. Fixed by
    stripping parentheticals and corporate suffixes from the main candidate
    while ALSO trying the parenthetical content as its own candidate (which
    is how "(KAIST)", "(AIST)", "(KNU)" resolve).

 3. COMPOUND AFFILIATIONS. "Peter Grunberg Institut (PGI-14) and RWTH Aachen
    University" returns 0 hits whole, but splitting on " and " recovers
    "RWTH Aachen University". Fixed by splitting on " and "/" & " as well as
    commas.
"""

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(REPO_ROOT, ".env")
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
API = "https://api.openalex.org/institutions"
MAILTO = "eding2019@gmail.com"

AUTO_THRESHOLD = 0.90
MIN_THRESHOLD = 0.72

MAP_FIELDS = [
    "raw_affiliation", "status", "institution_id", "institution_name",
    "institution_type", "country_code", "lineage", "score", "matched_via", "candidate",
]

# Segments that must never be searched on their own: corporate suffixes and
# bare legal-entity tokens. Failure mode 1 above.
STOP_SEGMENTS = {
    "inc", "inc.", "ltd", "ltd.", "co", "co.", "corp", "corp.", "corporation",
    "llc", "l.l.c.", "gmbh", "plc", "pvt", "pvt.", "pte", "pte.", "sa", "s.a.",
    "nv", "n.v.", "bv", "b.v.", "ag", "kk", "k.k.", "srl", "s.r.l.", "spa",
    "s.p.a.", "ab", "oy", "as", "a/s", "limited", "company", "the",
}

COUNTRIES = {
    "usa", "u.s.a.", "us", "u.s.", "united states", "united states of america",
    "uk", "u.k.", "united kingdom", "england", "scotland", "wales", "china",
    "p.r. china", "pr china", "people's republic of china", "japan", "korea",
    "south korea", "republic of korea", "north korea", "france", "germany",
    "italy", "spain", "belgium", "netherlands", "the netherlands", "switzerland",
    "sweden", "norway", "denmark", "finland", "austria", "poland", "portugal",
    "ireland", "greece", "russia", "india", "singapore", "taiwan", "r.o.c.",
    "taiwan, r.o.c.", "hong kong", "macau", "australia", "new zealand", "canada",
    "mexico", "brazil", "israel", "turkey", "egypt", "south africa", "thailand",
    "vietnam", "malaysia", "indonesia", "philippines", "saudi arabia", "uae",
}

# US state names/abbreviations and other pure-geography tokens.
US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
    "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
    "washington", "west virginia", "wisconsin", "wyoming",
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
    "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
    "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
    "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
    "wi", "wy",
}

POSTAL_RE = re.compile(r"^[\d][\d\s\-]*$|^[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d?[A-Z]{0,2}$")
PAREN_RE = re.compile(r"\(([^)]*)\)")
CORP_SUFFIX_RE = re.compile(
    r"\b(inc|ltd|co|corp|corporation|llc|gmbh|plc|pvt|pte|s\.?a|n\.?v|b\.?v|ag|k\.?k|s\.?r\.?l|s\.?p\.?a|limited)\b\.?,?\s*$",
    re.I,
)
# Segments that describe a sub-unit rather than an institution. These are
# still searched, but only after non-department segments.
DEPT_RE = re.compile(
    r"\b(school|department|dept\.?|faculty|division|graduate institute|"
    r"laborator(y|ies)|lab\b|research group|group|centre|center|"
    r"state key lab|college of|institute of \w+ (engineering|technolog))",
    re.I,
)


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


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def similarity(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    # Token containment lets "Peking University" match "Peking University,
    # Beijing". Restricted to multi-token candidates on BOTH sides: a
    # single-token candidate like the city "Daejeon" is fully contained in
    # "Daejeon University" and would otherwise score 0.97 and be auto-accepted,
    # silently crediting a city mention to an unrelated university.
    ta, tb = set(na.split()), set(nb.split())
    if len(ta) >= 2 and len(tb) >= 2:
        overlap = len(ta & tb) / min(len(ta), len(tb))
        ratio = max(ratio, overlap * 0.97 if ta <= tb or tb <= ta else overlap * 0.85)
    return ratio


def is_acronym_like(s):
    """Acronym-shaped candidates may be matched against institution acronyms.

    Guards failure mode 1: without this, a stray "Inc." segment matches the
    acronym "INC" of an unrelated institute at score 1.00.
    """
    t = (s or "").strip().strip(".")
    if not t or len(t) > 12 or " " in t.strip():
        return False
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 2:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.6


def build_candidates(raw):
    """Split a messy affiliation string into searchable candidate names."""
    s = html.unescape(raw or "").strip()
    if not s:
        return []

    # Parenthetical acronyms are the highest-signal candidates: OpenAlex
    # resolves "KAIST"/"A*STAR" exactly where the spelled-out name returns
    # zero hits, so they are tried first and never crowded out by the cap.
    acronyms = []
    for p in PAREN_RE.findall(s):
        p = p.strip()
        if len(p) >= 2 and p.lower() not in STOP_SEGMENTS and not POSTAL_RE.match(p):
            acronyms.append(p)

    def usable(p):
        p = re.sub(r"\s+", " ", p).strip(" .;-")
        if not p or len(p) < 4:
            return None
        low = p.lower().strip(" .")
        if low in STOP_SEGMENTS or low in COUNTRIES or low in US_STATES:
            return None
        if POSTAL_RE.match(p):
            return None
        # Strip a trailing corporate suffix, which makes OpenAlex search fail
        # outright ("Applied Materials Inc." -> 0 hits) (failure mode 2).
        stripped = CORP_SUFFIX_RE.sub("", p).strip(" .,;-")
        if len(stripped) >= 4:
            p = stripped
        if p.lower() in STOP_SEGMENTS or len(p) < 4:
            return None
        return p

    depunct = PAREN_RE.sub(" ", s)
    # Comma segments kept WHOLE first -- splitting on "and" would destroy
    # legitimate names like "Korea Advanced Institute of Science and Technology".
    whole, split = [], []
    for seg in depunct.split(","):
        u = usable(seg)
        if u:
            whole.append(u)
        # ...but also keep the conjunction-split pieces as fallbacks, which is
        # what recovers "RWTH Aachen University" from a compound string
        # (failure mode 3).
        for piece in re.split(r"\band\b|&", seg):
            v = usable(piece)
            if v and v.lower() != (u or "").lower():
                split.append(v)

    def rank(group):
        return sorted(group, key=lambda x: (bool(DEPT_RE.search(x)), -len(x)))

    seen = set()
    ordered = []
    for c in acronyms + rank(whole) + rank(split):
        if c.lower() not in seen:
            seen.add(c.lower())
            ordered.append(c)
    return ordered[:5]


def api_get(params, api_key, retries=3):
    params = dict(params)
    params["mailto"] = MAILTO
    if api_key:
        params["api_key"] = api_key
    qs = urllib.parse.urlencode(params, safe=":,|*!")
    req = urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": f"ecerankings-normalize (mailto:{MAILTO})"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                time.sleep(float(retry_after) if retry_after else 2 ** attempt)
                continue
            if e.code == 400:
                return {"results": []}
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise


def resolve(raw, api_key, verbose=False):
    """Return a map row dict for one raw affiliation string."""
    best = {"score": 0.0, "inst": None, "via": None, "candidate": None}

    for cand in build_candidates(raw):
        data = api_get({
            "search": cand,
            "per-page": 3,
            "select": "id,display_name,display_name_alternatives,display_name_acronyms,type,country_code,lineage",
        }, api_key)
        time.sleep(0.03)
        for inst in data.get("results", []):
            names = [inst.get("display_name") or ""]
            names += [n for n in (inst.get("display_name_alternatives") or []) if n]
            # Only consider acronyms when the candidate is itself acronym-shaped
            # (failure mode 1).
            if is_acronym_like(cand):
                names += [n for n in (inst.get("display_name_acronyms") or []) if n]
            for n in names:
                score = similarity(cand, n)
                if score > best["score"]:
                    best = {"score": score, "inst": inst, "via": n, "candidate": cand}
        if best["score"] >= 0.97:
            break

    inst = best["inst"]
    if inst and best["score"] >= AUTO_THRESHOLD:
        status = "auto"
    elif inst and best["score"] >= MIN_THRESHOLD:
        status = "review"
    else:
        status = "unmatched"

    row = {
        "raw_affiliation": raw,
        "status": status,
        "institution_id": (inst or {}).get("id", "") if inst else "",
        "institution_name": (inst or {}).get("display_name", "") if inst else "",
        "institution_type": (inst or {}).get("type", "") if inst else "",
        "country_code": (inst or {}).get("country_code", "") or "" if inst else "",
        "lineage": "|".join((inst or {}).get("lineage") or []) if inst else "",
        "score": f"{best['score']:.3f}",
        "matched_via": best["via"] or "",
        "candidate": best["candidate"] or "",
    }
    if status != "auto":
        # Keep the near-miss visible for auditing, but make clear it is unused.
        row["institution_id"] = row["institution_id"] if status == "review" else ""
    if verbose:
        print(f"    [{status:9s}] {best['score']:.2f} {raw[:52]!r} -> {row['institution_name'][:38]!r}")
    return row


def load_map():
    rows = {}
    if os.path.exists(MAP_CSV):
        with open(MAP_CSV, newline="") as f:
            for r in csv.DictReader(f):
                rows[r["raw_affiliation"]] = r
    return rows


def save_map(rows):
    os.makedirs(os.path.dirname(MAP_CSV), exist_ok=True)
    with open(MAP_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_FIELDS)
        w.writeheader()
        for raw in sorted(rows):
            row = {k: rows[raw].get(k, "") for k in MAP_FIELDS}
            w.writerow(row)


def find_cached_years(venue_key):
    venue_dir = os.path.join(CACHE_DIR, venue_key)
    if not os.path.isdir(venue_dir):
        return []
    return sorted(
        int(e) for e in os.listdir(venue_dir)
        if e.isdigit() and os.path.exists(os.path.join(venue_dir, e, "works.jsonl"))
    )


def collect_raw_affiliations(venue_key, year=None):
    strings = {}
    for y in find_cached_years(venue_key):
        if year is not None and y != year:
            continue
        path = os.path.join(CACHE_DIR, venue_key, str(y), "works.jsonl")
        with open(path) as f:
            for line in f:
                w = json.loads(line)
                for a in w.get("authorships", []):
                    for s in a.get("raw_affiliations", []) or []:
                        strings[s] = strings.get(s, 0) + 1
    return strings


def main():
    parser = argparse.ArgumentParser(description="Resolve Crossref affiliation strings to OpenAlex institutions.")
    parser.add_argument("--venue", action="append", default=[], help="Venue key (repeatable)")
    parser.add_argument("--all-cached", action="store_true", help="Every venue with cached works")
    parser.add_argument("--year", type=int, default=None, help="Restrict to one year")
    parser.add_argument("--report-only", action="store_true", help="Don't call the API; just report map coverage")
    parser.add_argument("--verbose", action="store_true", help="Print each resolution")
    args = parser.parse_args()

    venues = args.venue
    if args.all_cached:
        venues = sorted(d for d in os.listdir(CACHE_DIR) if os.path.isdir(os.path.join(CACHE_DIR, d))) if os.path.isdir(CACHE_DIR) else []
    if not venues:
        print("Specify --venue <key> or --all-cached", file=sys.stderr)
        sys.exit(1)

    env = load_env()
    api_key = env.get("OPENALEX_API_KEY")
    mapping = load_map()

    all_strings = {}
    for v in venues:
        for s, n in collect_raw_affiliations(v, args.year).items():
            all_strings[s] = all_strings.get(s, 0) + n

    if not all_strings:
        print("No Crossref-sourced affiliation strings found in cache (OpenAlex years need no normalization).")
        return

    todo = [s for s in all_strings if s not in mapping]
    print(f"{len(all_strings)} distinct affiliation strings across {len(venues)} venue(s); {len(mapping)} already mapped; {len(todo)} to resolve.")

    if args.report_only:
        todo = []

    resolved = 0
    for i, s in enumerate(sorted(todo), 1):
        try:
            mapping[s] = resolve(s, api_key, verbose=args.verbose)
        except Exception as e:
            print(f"    ERROR resolving {s[:60]!r}: {type(e).__name__}: {e}", file=sys.stderr)
            mapping[s] = {
                "raw_affiliation": s, "status": "unmatched", "institution_id": "",
                "institution_name": "", "institution_type": "", "country_code": "",
                "lineage": "", "score": "0.000", "matched_via": "", "candidate": "",
            }
        resolved += 1
        if resolved % 25 == 0:
            print(f"  resolved {resolved}/{len(todo)}...")
            save_map(mapping)

    if todo:
        save_map(mapping)

    # --- Coverage report, weighted by how often each string actually appears ---
    by_status = {}
    weighted = {}
    edu_strings = 0
    edu_occurrences = 0
    for s, count in all_strings.items():
        row = mapping.get(s)
        st = row["status"] if row else "unmapped"
        by_status[st] = by_status.get(st, 0) + 1
        weighted[st] = weighted.get(st, 0) + count
        if row and row["status"] in ("auto", "manual") and row["institution_type"] == "education":
            edu_strings += 1
            edu_occurrences += count

    total_occ = sum(all_strings.values())
    print(f"\nMap written to {MAP_CSV}")
    print(f"{'status':<12}{'distinct':>10}{'occurrences':>14}{'% of occurrences':>18}")
    for st in ("auto", "manual", "review", "unmatched", "unmapped"):
        if st in by_status:
            print(f"{st:<12}{by_status[st]:>10}{weighted[st]:>14}{100*weighted[st]/max(total_occ,1):>17.1f}%")
    print(f"\nCredited (auto+manual, type=education): {edu_strings} distinct strings, {edu_occurrences} occurrences ({100*edu_occurrences/max(total_occ,1):.1f}%)")
    if by_status.get("review"):
        print(f"\n{by_status['review']} string(s) need human review (scored {MIN_THRESHOLD}-{AUTO_THRESHOLD}).")
        print(f"Edit {os.path.relpath(MAP_CSV, REPO_ROOT)}: fix the institution_* columns and set status=manual to credit them,")
        print("or leave them as-is to keep them excluded. status=manual rows are never overwritten.")


if __name__ == "__main__":
    main()
