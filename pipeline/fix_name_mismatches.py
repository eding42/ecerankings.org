#!/usr/bin/env python3
"""Fix full-name mismatches in data/affiliation-map.csv.

Bug class (complement of fix_acronym_collisions.py): a row is assigned to
institution X, but the raw affiliation string contains the *full name* of a
different institution Y, and nothing in the string supports X. Produced by
normalize_semantic.py when a generic candidate segment (department name,
division, sub-brand) cosine-matches an unrelated institution -- e.g.
'"G. Marconi" University of Bologna, Dept. of Electrical, Electronic and
Information Engineering' -> "Ministry of Electronics and Information
Technology" (IN) at score 0.853, or "Memory Solution Division (MSD), Taiwan
Semiconductor Manufacturing Company" -> "MSD (Norway)".

Detection: for every auto row, find all institutions whose normalized name
variant (>=10 chars, >=2 tokens) appears at token boundaries inside the
normalized raw string (token-trigram index keeps this fast). Then:

- assigned institution has any contained name-variant evidence -> keep
- assigned has NO evidence at all (no name variant, no acronym/alias token)
  and some other institution's variant matches a WHOLE comma-segment of the
  raw string (or a join of adjacent segments, or a parenthetical) -> reassign
  to the longest such whole-segment match if unique (unless the raw string's
  country evidence contradicts it -> flag)
- anything else (assigned has acronym-token evidence, candidates tie, or the
  foreign name is merely contained mid-segment -- e.g. "Institute of Science"
  inside "Indian Institute of Science") -> flagged for adjudication only

Whole-segment matching is what makes reassignment safe: a mid-segment
substring is usually a fragment of a longer institution name, but a full
segment ("Purdue University", "Peking University Shenzhen Graduate School")
is how affiliations actually denote the institution.

Usage:
    python3 pipeline/fix_name_mismatches.py                # report only
    python3 pipeline/fix_name_mismatches.py --apply
    python3 pipeline/fix_name_mismatches.py --apply --report data/reports/x.md
"""
import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fix_acronym_collisions import (
    normalize, raw_countries, load_db, load_map, save_map, MAP_FIELDS,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")

MIN_VARIANT_CHARS = 10


def build_indexes(by_id):
    """variant -> inst_ids; trigram/bigram token-prefix index; short-alias index."""
    variant_owners = defaultdict(set)
    short_tokens = defaultdict(set)  # inst_id -> normalized acronym/short-alias tokens
    for iid, inst in by_id.items():
        names = [inst.get("display_name") or ""] + list(inst.get("alternatives") or [])
        acrs = list(inst.get("acronyms") or [])
        for v in names:
            n = normalize(v)
            if not n:
                continue
            toks = n.split()
            if len(n) >= MIN_VARIANT_CHARS and len(toks) >= 2:
                variant_owners[n].add(iid)
            else:
                short_tokens[iid].add(n)
        for a in acrs:
            n = normalize(a)
            if n:
                short_tokens[iid].add(n)

    tri_index = defaultdict(list)   # first-3-token key -> [variant]
    bi_index = defaultdict(list)    # 2-token variants, keyed by themselves
    for v in variant_owners:
        toks = v.split()
        if len(toks) == 2:
            bi_index[v].append(v)
        else:
            tri_index[" ".join(toks[:3])].append(v)
    return variant_owners, tri_index, bi_index, short_tokens


PAREN_RE_B = re.compile(r"\(([^)]*)\)")


def raw_segments(raw):
    """Normalized whole segments of a raw affiliation: comma/semicolon segments,
    joins of 2-3 adjacent segments, and parenthetical contents; each also with
    a leading 'the' stripped."""
    parens = PAREN_RE_B.findall(raw or "")
    body = PAREN_RE_B.sub(" ", raw or "")
    parts = [normalize(p) for p in re.split(r"[,;:]", body)]
    parts = [p for p in parts if p]
    segs = set(parts)
    for i in range(len(parts) - 1):
        segs.add(f"{parts[i]} {parts[i+1]}")
        if i + 2 < len(parts):
            segs.add(f"{parts[i]} {parts[i+1]} {parts[i+2]}")
    for p in parens:
        n = normalize(p)
        if n:
            segs.add(n)
    for s in list(segs):
        if s.startswith("the "):
            segs.add(s[4:])
    return segs


def contained_variants(norm_raw, tri_index, bi_index):
    """All indexed variants that appear at token boundaries in norm_raw."""
    toks = norm_raw.split()
    padded = f" {norm_raw} "
    hits = set()
    seen_keys = set()
    for i in range(len(toks)):
        if i + 1 < len(toks):
            bik = f"{toks[i]} {toks[i+1]}"
            if bik in bi_index and bik not in seen_keys:
                seen_keys.add(bik)
                if len(bik) >= MIN_VARIANT_CHARS:
                    hits.add(bik)
        if i + 2 < len(toks):
            trik = f"{toks[i]} {toks[i+1]} {toks[i+2]}"
            if trik in seen_keys:
                continue
            seen_keys.add(trik)
            for v in tri_index.get(trik, ()):
                if f" {v} " in padded:
                    hits.add(v)
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="Write fixes to the CSV")
    ap.add_argument("--report", default=None, help="Write a markdown report to this path")
    ap.add_argument("--limit-print", type=int, default=40)
    args = ap.parse_args()

    db = load_db()
    by_id = db["by_id"]
    variant_owners, tri_index, bi_index, short_tokens = build_indexes(by_id)
    rows = load_map()

    fixes, flagged, kept = [], [], 0
    examined = 0

    for r in rows:
        if r.get("status") != "auto":
            continue
        cur_id = r.get("institution_id", "")
        if not cur_id:
            continue
        examined += 1
        norm_raw = normalize(r.get("raw_affiliation", ""))
        hits = contained_variants(norm_raw, tri_index, bi_index)
        if not hits:
            continue

        if any(cur_id in variant_owners[v] for v in hits):
            # assigned institution has full-name evidence anywhere in the string
            kept += 1
            continue

        # Reassignment evidence: variants matching a WHOLE segment only
        segs = raw_segments(r.get("raw_affiliation", ""))
        best_by_inst = defaultdict(int)
        for v in hits:
            if v not in segs:
                continue
            for iid in variant_owners[v]:
                if len(v) > best_by_inst[iid]:
                    best_by_inst[iid] = len(v)
        if not best_by_inst:
            # foreign names only mid-segment: fragment of a longer name, skip
            continue
        global_best = max(best_by_inst.values())
        top = [iid for iid, l in best_by_inst.items() if l == global_best]

        # Does the raw string contain a standalone short alias/acronym of assigned?
        raw_toks = set(norm_raw.split())
        cur_token_evidence = any(
            t in raw_toks or (len(t.split()) > 1 and f" {t} " in f" {norm_raw} ")
            for t in short_tokens.get(cur_id, ())
        )

        if len(top) == 1 and not cur_token_evidence:
            new_id = top[0]
            cc = raw_countries(norm_raw)
            new_cc = by_id[new_id].get("country_code") or ""
            if cc and new_cc and new_cc not in cc:
                flagged.append((r, top, f"country {sorted(cc)} contradicts {new_cc}"))
            else:
                fixes.append((r, new_id, f"full name in raw ({global_best} chars), no evidence for assigned"))
        else:
            note = "assigned has acronym-token evidence" if cur_token_evidence else f"{len(top)} tied candidates"
            flagged.append((r, top, note))

    print(f"Examined {examined} auto rows; kept {kept} with name evidence for assigned")
    print(f"  to fix: {len(fixes)}\n  flagged for adjudication: {len(flagged)}\n")

    moves = defaultdict(int)
    for r, new_id, _ in fixes:
        moves[(r.get("institution_name", ""), by_id[new_id]["display_name"])] += 1
    for (old, new), n in sorted(moves.items(), key=lambda x: -x[1])[:args.limit_print]:
        print(f"  {n:4d}  {old}  ->  {new}")

    if args.report:
        with open(args.report, "w") as f:
            f.write("# Full-name mismatch fix report\n\n")
            f.write(f"- examined: {examined}\n- kept: {kept}\n- fixed: {len(fixes)}\n"
                    f"- flagged: {len(flagged)}\n\n## Fixes\n\n")
            for r, new_id, reason in fixes:
                f.write(f"- `{r['raw_affiliation']}`\n  - {r.get('institution_name','')} -> "
                        f"{by_id[new_id]['display_name']} ({reason})\n")
            f.write("\n## Flagged (needs adjudication)\n\n")
            for r, top, note in flagged:
                names = [by_id.get(c, {}).get("display_name", c) for c in top][:5]
                f.write(f"- `{r['raw_affiliation']}` — now: {r.get('institution_name','')}; "
                        f"candidates: {names} ({note})\n")
        print(f"\nReport written to {args.report}")

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
        r["matched_via"] = f"name-mismatch-fix: {reason}"

    save_map(rows)
    print(f"\nApplied {len(fixes)} fixes -> {os.path.relpath(MAP_CSV, REPO_ROOT)}")


if __name__ == "__main__":
    main()
