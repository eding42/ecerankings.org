#!/usr/bin/env python3
"""Resolve Crossref free-text affiliation strings to OpenAlex institutions (LOCAL version).

Usage:
    python3 pipeline/normalize_affiliations_local.py --venue iedm
    python3 pipeline/normalize_affiliations_local.py --all-cached
    python3 pipeline/normalize_affiliations_local.py --venue iedm --report-only

This version uses the local institutions.json database instead of the API,
making it instant and free.
"""

import argparse
import csv
import html
import json
import os
import re
import sys
from difflib import SequenceMatcher

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(REPO_ROOT, "cache")
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
INST_DB = os.path.join(REPO_ROOT, "data", "institutions.json")

AUTO_THRESHOLD = 0.90
MIN_THRESHOLD = 0.72

MAP_FIELDS = [
    "raw_affiliation", "status", "institution_id", "institution_name",
    "institution_type", "country_code", "lineage", "score", "matched_via", "candidate",
]

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

FUNCTION_WORDS = {"of", "the", "and", "for", "de", "da", "du", "la", "le", "der", "van", "von"}

POSTAL_RE = re.compile(r"^[\d][\d\s\-]*$|^[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d?[A-Z]{0,2}$")
PAREN_RE = re.compile(r"\(([^)]*)\)")
CORP_SUFFIX_RE = re.compile(
    r"\b(inc|ltd|co|corp|corporation|llc|gmbh|plc|pvt|pte|s\.?a|n\.?v|b\.?v|ag|k\.?k|s\.?r\.?l|s\.?p\.?a|limited)\b\.?,?\s*$",
    re.I,
)
DEPT_RE = re.compile(
    r"\b(school|department|dept\.?|faculty|division|graduate institute|"
    r"laborator(y|ies)|lab\b|research group|group|centre|center|"
    r"state key lab|college of|institute of \w+ (engineering|technolog))",
    re.I,
)


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def similarity(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    if len(ta) >= 2 and len(tb) >= 2:
        overlap = len(ta & tb) / min(len(ta), len(tb))
        ratio = max(ratio, overlap * 0.97 if ta <= tb or tb <= ta else overlap * 0.85)
    return ratio


def is_acronym_like(s):
    t = (s or "").strip().strip(".")
    if not t or len(t) > 12 or " " in t.strip():
        return False
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 2:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) >= 0.6


def build_candidates(raw):
    s = html.unescape(raw or "").strip()
    if not s:
        return []

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
        stripped = CORP_SUFFIX_RE.sub("", p).strip(" .,;-")
        if len(stripped) >= 4:
            p = stripped
        if p.lower() in STOP_SEGMENTS or len(p) < 4:
            return None
        return p

    depunct = PAREN_RE.sub(" ", s)
    whole, split = [], []
    for seg in depunct.split(","):
        u = usable(seg)
        if u:
            whole.append(u)
        for piece in re.split(r"\band\b|&", seg):
            v = usable(piece)
            if v and v.lower() != (u or "").lower():
                split.append(v)

    # Adjacent comma-segment joins: "University of California, Irvine, USA"
    # splits into standalone segments ["University of California", "Irvine"],
    # and neither alone is a real institution name -- only the joined form
    # "University of California, Irvine" is. Without this, a bare fragment
    # like "University of California" falls through to the bag-of-words tier
    # and can land on a completely unrelated institution that happens to
    # share those words (confirmed: it matched "Southern California
    # University of Health Sciences"). Re-joining adjacent segments lets the
    # exact-match tier resolve the real campus first.
    joined = []
    for i in range(len(whole) - 1):
        joined.append(f"{whole[i]}, {whole[i + 1]}")
        if i + 2 < len(whole):
            joined.append(f"{whole[i]}, {whole[i + 1]}, {whole[i + 2]}")

    def rank(group):
        return sorted(group, key=lambda x: (bool(DEPT_RE.search(x)), -len(x)))

    seen = set()
    ordered = []
    for c in acronyms + rank(joined) + rank(whole) + rank(split):
        if c.lower() not in seen:
            seen.add(c.lower())
            ordered.append(c)
    return ordered[:5]


def load_inst_db():
    if not os.path.exists(INST_DB):
        print(f"Error: {INST_DB} not found. Run: python3 pipeline/build_institution_db_s3.py", file=sys.stderr)
        sys.exit(1)
    with open(INST_DB) as f:
        return json.load(f)


def resolve_local(raw, db):
    """Resolve using local database with optimized matching."""
    best = {"score": 0.0, "inst": None, "via": None, "candidate": None}
    by_name = db["by_name"]
    by_id = db["by_id"]
    
    # Build fast lookup: lowercase name -> inst_id
    # Already have by_name, just use it

    for cand in build_candidates(raw):
        cand_lower = cand.lower().strip()
        
        # 1. Exact name match (instant)
        if cand_lower in by_name:
            inst_id = by_name[cand_lower]
            inst = by_id.get(inst_id)
            if inst:
                best = {"score": 1.0, "inst": inst, "via": cand, "candidate": cand}
                break
        
        # 2. Acronym match (instant)
        if is_acronym_like(cand):
            for name_key, inst_id in by_name.items():
                inst = by_id.get(inst_id)
                if not inst:
                    continue
                if cand_lower in [a.lower() for a in inst.get("acronyms", [])]:
                    best = {"score": 1.0, "inst": inst, "via": cand, "candidate": cand}
                    break
            if best["score"] >= 0.97:
                break
        
        # 3. Prefix match: a short informal name fully covering the start of a
        # longer institution name (e.g. "Stanford" -> "Stanford University").
        # name_key is floored at 5 chars: shorter keys are almost always
        # acronym/alias entries (by_name includes acronyms as keys, e.g. "ti"
        # for Tinbergen Institute's "TI"), and letting those participate in
        # blind prefix matching means any candidate that happens to start
        # with those 2-4 letters collides with a totally unrelated
        # institution -- confirmed: "Tianjin" (a Chinese city, no relation)
        # was matching "Tinbergen Institute" (Netherlands) purely because
        # "tianjin".startswith("ti") and "ti" was the first such collision
        # hit in dict iteration order. Acronym-style short keys already have
        # a dedicated, properly-gated path in step 2 (is_acronym_like(cand)
        # required); this step is NOT that path and must not overlap it.
        # Score by real coverage ratio and always keep the single best
        # match found, not whichever prefix hit is encountered first --
        # the old flat 0.85-for-any-hit score made "best" meaningless since
        # every hit tied, so the first one in dict order silently won.
        if 3 <= len(cand_lower) <= 8:
            for name_key, inst_id in by_name.items():
                if len(name_key) < 5:
                    continue
                if name_key.startswith(cand_lower) or cand_lower.startswith(name_key):
                    inst = by_id.get(inst_id)
                    if inst:
                        shorter, longer = sorted((cand_lower, name_key), key=len)
                        score = 0.72 + 0.25 * (len(shorter) / len(longer))
                        if score > best["score"]:
                            best = {"score": score, "inst": inst, "via": name_key, "candidate": cand}
            if best["score"] >= 0.97:
                break
        
        # 4. Token containment, gated on real content-word coverage. Plain
        # bag-of-words subset matching (any candidate whose tokens are all
        # present somewhere in a name) is too loose: "University of
        # California" vs "Southern California University of Health
        # Sciences" share the tokens {university, of, california} but are
        # unrelated institutions -- the shared words are exactly the
        # generic ones ("university", "of"), and the candidate covers only
        # a small fraction of the name's actual content. Strip function
        # words before comparing, require the candidate to be a subset of
        # the name's content words, AND require it to cover a majority of
        # them (not just be present) -- score by that coverage ratio so a
        # candidate matching most of a name scores high and one matching a
        # sliver of a much longer name scores too low to auto-credit.
        cand_tokens = set(cand_lower.split())
        if len(cand_tokens) >= 2:
            cand_content = cand_tokens - FUNCTION_WORDS
            for name_key, inst_id in by_name.items():
                name_content = set(name_key.split()) - FUNCTION_WORDS
                if not cand_content or not name_content:
                    continue
                if not cand_content.issubset(name_content):
                    continue
                ratio = len(cand_content) / len(name_content)
                if ratio < 0.55:
                    continue
                inst = by_id.get(inst_id)
                if inst:
                    score = 0.72 + 0.25 * ratio
                    if score > best["score"]:
                        best = {"score": score, "inst": inst, "via": name_key, "candidate": cand}
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
        "institution_id": inst["id"] if inst and status in ("auto", "review") else "",
        "institution_name": inst["display_name"] if inst and status in ("auto", "review") else "",
        "institution_type": inst["type"] if inst and status in ("auto", "review") else "",
        "country_code": inst["country_code"] if inst and status in ("auto", "review") else "",
        "lineage": "|".join(inst.get("lineage", [])) if inst and status in ("auto", "review") else "",
        "score": f"{best['score']:.3f}",
        "matched_via": best["via"] or "",
        "candidate": best["candidate"] or "",
    }
    
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
    parser = argparse.ArgumentParser(description="Resolve Crossref affiliation strings to OpenAlex institutions (LOCAL).")
    parser.add_argument("--venue", action="append", default=[], help="Venue key (repeatable)")
    parser.add_argument("--all-cached", action="store_true", help="Every venue with cached works")
    parser.add_argument("--year", type=int, default=None, help="Restrict to one year")
    parser.add_argument("--report-only", action="store_true", help="Don't resolve; just report map coverage")
    parser.add_argument("--verbose", action="store_true", help="Print each resolution")
    args = parser.parse_args()

    venues = args.venue
    if args.all_cached:
        venues = sorted(d for d in os.listdir(CACHE_DIR) if os.path.isdir(os.path.join(CACHE_DIR, d))) if os.path.isdir(CACHE_DIR) else []
    if not venues:
        print("Specify --venue <key> or --all-cached", file=sys.stderr)
        sys.exit(1)

    db = load_inst_db()
    mapping = load_map()

    all_strings = {}
    for v in venues:
        for s, n in collect_raw_affiliations(v, args.year).items():
            all_strings[s] = all_strings.get(s, 0) + n

    if not all_strings:
        print("No Crossref-sourced affiliation strings found in cache.")
        return

    todo = [s for s in all_strings if s not in mapping]
    print(f"{len(all_strings)} distinct affiliation strings across {len(venues)} venue(s); {len(mapping)} already mapped; {len(todo)} to resolve.")

    if args.report_only:
        todo = []

    resolved = 0
    for i, s in enumerate(sorted(todo), 1):
        mapping[s] = resolve_local(s, db)
        resolved += 1
        if resolved % 50 == 0:
            print(f"  resolved {resolved}/{len(todo)}...")
            save_map(mapping)
        if args.verbose:
            print(f"    [{mapping[s]['status']:9s}] {mapping[s]['score']} {s[:52]!r} -> {mapping[s]['institution_name'][:38]!r}")

    if todo:
        save_map(mapping)

    # Coverage report
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
        print(f"Edit {os.path.relpath(MAP_CSV, REPO_ROOT)}: fix the institution_* columns and set status=manual to credit them.")
    if by_status.get("unmatched"):
        print(f"\n{by_status['unmatched']} string(s) unmatched (scored <{MIN_THRESHOLD}).")


if __name__ == "__main__":
    main()
