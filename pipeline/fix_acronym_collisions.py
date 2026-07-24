#!/usr/bin/env python3
"""Fix acronym-collision misattribution in data/affiliation-map.csv.

Bug class: normalize_semantic.py ranks parenthetical acronyms first among
candidates, and an exact acronym hit (cosine ~1.0) beats the full-name
candidate. When an acronym legitimately belongs to 2+ OpenAlex institutions
("MIT" -> Massachusetts Institute of Technology AND Manukau Institute of
Technology), torch.max picks an arbitrary owner -- even when the raw string
spells out the correct institution's full name right next to the acronym.

Repair strategy, strongest signal first, applied to every auto/manual row
whose matched_via is an acronym shared by 2+ institutions (candidate set =
acronym owners + currently assigned institution):

1. Full-name containment: normalize (strip diacritics, lowercase, collapse
   punctuation) the raw string and every candidate's display_name +
   alternatives; if some candidate's full name appears in the raw string,
   assign the candidate with the longest such match. Ties between different
   institutions -> flagged, not auto-fixed.
2. Country evidence: extract country mentions from the raw string; if
   exactly one candidate's country_code matches, assign it.
3. No evidence: leave the row as-is but list it in the ambiguous report for
   LLM adjudication (see .claude/skills/adjudicate-affiliations/).

Usage:
    python3 pipeline/fix_acronym_collisions.py            # report only
    python3 pipeline/fix_acronym_collisions.py --apply    # fix + write CSV
    python3 pipeline/fix_acronym_collisions.py --apply --include-manual
"""
import argparse
import csv
import html
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
INST_DB = os.path.join(REPO_ROOT, "data", "institutions.json")

MAP_FIELDS = [
    "raw_affiliation", "status", "institution_id", "institution_name",
    "institution_type", "country_code", "lineage", "score", "matched_via", "candidate",
]

# Country name -> ISO 3166-1 alpha-2, for the country-evidence pass.
# Keys are matched as whole normalized tokens/phrases in the raw string.
COUNTRY_NAMES = {
    "usa": "US", "u s a": "US", "united states": "US", "united states of america": "US",
    "uk": "GB", "u k": "GB", "united kingdom": "GB", "england": "GB", "scotland": "GB",
    "wales": "GB", "northern ireland": "GB",
    "china": "CN", "p r china": "CN", "pr china": "CN", "peoples republic of china": "CN",
    "people s republic of china": "CN",
    "japan": "JP", "korea": "KR", "south korea": "KR", "republic of korea": "KR",
    "france": "FR", "germany": "DE", "italy": "IT", "spain": "ES", "belgium": "BE",
    "netherlands": "NL", "the netherlands": "NL", "switzerland": "CH", "sweden": "SE",
    "norway": "NO", "denmark": "DK", "finland": "FI", "austria": "AT", "poland": "PL",
    "portugal": "PT", "ireland": "IE", "greece": "GR", "russia": "RU", "india": "IN",
    "singapore": "SG", "taiwan": "TW", "hong kong": "HK", "macau": "MO",
    "australia": "AU", "new zealand": "NZ", "canada": "CA", "mexico": "MX",
    "brazil": "BR", "israel": "IL", "turkey": "TR", "egypt": "EG",
    "south africa": "ZA", "thailand": "TH", "vietnam": "VN", "viet nam": "VN",
    "malaysia": "MY", "indonesia": "ID", "philippines": "PH", "saudi arabia": "SA",
    "uae": "AE", "united arab emirates": "AE", "qatar": "QA", "kuwait": "KW",
    "iran": "IR", "iraq": "IQ", "lebanon": "LB", "jordan": "JO", "pakistan": "PK",
    "bangladesh": "BD", "sri lanka": "LK", "nepal": "NP", "kenya": "KE",
    "nigeria": "NG", "ghana": "GH", "ethiopia": "ET", "morocco": "MA",
    "tunisia": "TN", "algeria": "DZ", "czech republic": "CZ", "czechia": "CZ",
    "slovakia": "SK", "hungary": "HU", "romania": "RO", "bulgaria": "BG",
    "croatia": "HR", "serbia": "RS", "slovenia": "SI", "ukraine": "UA",
    "estonia": "EE", "latvia": "LV", "lithuania": "LT", "iceland": "IS",
    "luxembourg": "LU", "cyprus": "CY", "malta": "MT", "chile": "CL",
    "argentina": "AR", "colombia": "CO", "peru": "PE", "ecuador": "EC",
    "uruguay": "UY", "venezuela": "VE", "cuba": "CU", "myanmar": "MM",
}
# US state names in the raw string are strong US evidence too.
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
}

NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Common affiliation abbreviations expanded so "Univ. of X" matches "University of X".
TOKEN_EXPANSIONS = {
    "univ": "university", "inst": "institute", "natl": "national",
    "acad": "academy", "lab": "laboratory", "labs": "laboratories",
}


def normalize(s):
    """Lowercase, strip diacritics, expand &/abbreviations, collapse punctuation."""
    s = html.unescape(s or "").replace("&", " and ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    toks = NON_ALNUM_RE.sub(" ", s.lower()).strip().split()
    return " ".join(TOKEN_EXPANSIONS.get(t, t) for t in toks if t != "the")


def name_variants(inst, acronym_norms):
    """Normalized full-name variants usable as containment evidence.

    Excludes the acronyms themselves and anything too short/generic to be
    distinctive (fewer than 2 tokens or under 10 chars).
    """
    out = set()
    for v in [inst.get("display_name") or ""] + list(inst.get("alternatives") or []):
        n = normalize(v)
        if not n or n in acronym_norms:
            continue
        if len(n) >= 10 and len(n.split()) >= 2:
            out.add(n)
    return out


def raw_countries(norm_raw):
    """All ISO country codes evidenced by the normalized raw string."""
    padded = f" {norm_raw} "
    found = set()
    for name, code in COUNTRY_NAMES.items():
        if f" {name} " in padded:
            found.add(code)
    if "US" not in found:
        for st in US_STATES:
            if f" {st} " in padded:
                found.add("US")
                break
    return found


def load_db():
    with open(INST_DB) as f:
        return json.load(f)


def load_map():
    with open(MAP_CSV, newline="") as f:
        return list(csv.DictReader(f))


def save_map(rows):
    with open(MAP_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAP_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in MAP_FIELDS})


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="Write fixes to the CSV (default: report only)")
    ap.add_argument("--include-manual", action="store_true",
                    help="Also fix status=manual rows on full-name evidence (default: auto rows only)")
    ap.add_argument("--report", default=None, help="Write a markdown report to this path")
    args = ap.parse_args()

    db = load_db()
    by_id = db["by_id"]

    acr_owners = defaultdict(list)  # normalized acronym -> [inst_id]
    for iid, inst in by_id.items():
        for a in inst.get("acronyms") or []:
            n = normalize(a)
            if n:
                acr_owners[n].append(iid)
    collisions = {a: ids for a, ids in acr_owners.items() if len(ids) > 1}

    rows = load_map()
    variant_cache = {}

    def variants_for(iid):
        if iid not in variant_cache:
            inst = by_id.get(iid)
            if not inst:
                variant_cache[iid] = set()
            else:
                acr_norms = {normalize(a) for a in inst.get("acronyms") or []}
                variant_cache[iid] = name_variants(inst, acr_norms)
        return variant_cache[iid]

    fixes = []       # (row, new_id, reason)
    ambiguous = []   # (row, candidate_ids, note)
    kept = 0
    examined = 0

    for r in rows:
        status = r.get("status", "")
        if status not in ("auto", "manual"):
            continue
        if status == "manual" and not args.include_manual:
            continue
        mv = normalize(r.get("matched_via", ""))
        if mv not in collisions:
            continue
        examined += 1

        cur_id = r.get("institution_id", "")
        cand_ids = list(dict.fromkeys(collisions[mv] + ([cur_id] if cur_id in by_id else [])))

        norm_raw = normalize(r.get("raw_affiliation", ""))

        # Signal 1: full-name containment, longest match wins
        best_len, best_ids = 0, []
        for cid in cand_ids:
            for v in variants_for(cid):
                if v in norm_raw:
                    if len(v) > best_len:
                        best_len, best_ids = len(v), [cid]
                    elif len(v) == best_len and cid not in best_ids:
                        best_ids.append(cid)
        if best_ids:
            if cur_id in best_ids:
                kept += 1
            elif len(best_ids) == 1:
                fixes.append((r, best_ids[0], f"full name in raw string ({best_len} chars)"))
            else:
                ambiguous.append((r, best_ids, "full-name tie between candidates"))
            continue

        # Signal 2: country evidence (only meaningful if it discriminates)
        raw_cc = raw_countries(norm_raw)
        if raw_cc:
            matching = [cid for cid in cand_ids if (by_id.get(cid, {}).get("country_code") or "") in raw_cc]
            if len(matching) == 1:
                if matching[0] == cur_id:
                    kept += 1
                else:
                    fixes.append((r, matching[0], f"country evidence {sorted(raw_cc)}"))
                continue
            if matching and cur_id not in matching:
                ambiguous.append((r, matching, f"country {sorted(raw_cc)} excludes assigned inst, multiple candidates remain"))
                continue
            if matching:
                kept += 1
                continue
            # raw country matches NO candidate: assigned inst is likely wrong too
            ambiguous.append((r, cand_ids, f"raw country {sorted(raw_cc)} matches no acronym owner"))
            continue

        # Signal 3: nothing to go on
        ambiguous.append((r, cand_ids, "acronym only, no name/country evidence"))

    # ── report ──
    by_reason = defaultdict(int)
    print(f"Examined {examined} auto{'/manual' if args.include_manual else ''} rows "
          f"with collision-acronym matched_via")
    print(f"  kept (assignment confirmed): {kept}")
    print(f"  to fix: {len(fixes)}")
    print(f"  ambiguous (needs adjudication): {len(ambiguous)}\n")

    moves = defaultdict(int)
    for r, new_id, reason in fixes:
        old = r.get("institution_name", "")
        new = by_id[new_id]["display_name"]
        moves[(old, new)] += 1
    for (old, new), n in sorted(moves.items(), key=lambda x: -x[1]):
        print(f"  {n:4d}  {old}  ->  {new}")

    if ambiguous:
        print(f"\nAmbiguous rows (first 40):")
        for r, cids, note in ambiguous[:40]:
            names = [by_id.get(c, {}).get("display_name", c) for c in cids][:4]
            print(f"  [{r.get('matched_via','')}] {r['raw_affiliation'][:80]!r}")
            print(f"      now={r.get('institution_name','')}  candidates={names}  ({note})")

    report_path = args.report
    if report_path:
        with open(report_path, "w") as f:
            f.write("# Acronym-collision fix report\n\n")
            f.write(f"- examined: {examined}\n- kept: {kept}\n- fixed: {len(fixes)}\n"
                    f"- ambiguous: {len(ambiguous)}\n\n## Fixes\n\n")
            for r, new_id, reason in fixes:
                f.write(f"- `{r['raw_affiliation']}`\n  - {r.get('institution_name','')} -> "
                        f"{by_id[new_id]['display_name']} ({reason})\n")
            f.write("\n## Ambiguous (needs adjudication)\n\n")
            for r, cids, note in ambiguous:
                names = [by_id.get(c, {}).get("display_name", c) for c in cids]
                f.write(f"- `{r['raw_affiliation']}` — now: {r.get('institution_name','')}; "
                        f"candidates: {names} ({note})\n")
        print(f"\nReport written to {report_path}")

    if not args.apply:
        print("\nDry run — re-run with --apply to write fixes.")
        return

    for r, new_id, reason in fixes:
        inst = by_id[new_id]
        r["institution_id"] = new_id
        r["institution_name"] = inst["display_name"]
        r["institution_type"] = inst.get("type") or ""
        r["country_code"] = inst.get("country_code") or ""
        r["lineage"] = "|".join(inst.get("lineage") or [])
        r["status"] = "manual"
        r["matched_via"] = f"acronym-collision-fix: {reason}"

    save_map(rows)
    print(f"\nApplied {len(fixes)} fixes -> {os.path.relpath(MAP_CSV, REPO_ROOT)}")


if __name__ == "__main__":
    main()
