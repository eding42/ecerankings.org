#!/usr/bin/env python3
"""Propose repairs for map rows the raw string itself contradicts.

Finds accepted education rows where the string names a different country than
the mapped institution, or describes a company, and writes adjudication
decisions for `adjudication.py apply`. It never edits the map: every repair
goes through apply, so it is validated, recorded in the ledger and replayable.

Two files are written to --out (default .tmp/adjudication/evidence-fixes/):

  country-corrections.json   String names country X, and exactly one education
                             institution with the matched name is in X.
                             Mechanical; safe to apply after a skim.
  company-noneducation.json  Company string credited to a university.
                             Read before applying: the rule is a pattern.

Rows with a country contradiction but no single same-named institution, rows
naming no country that sit on an institution whose other strings mostly point
at its namesake elsewhere, and
rows that were already adjudicated (status manual), are listed in
needs-adjudication.csv. `adjudication.py queue --suspect` batches them, and
the company rows, for the adjudicate-affiliations skill.

Usage:
    python3 pipeline/fix_country_mismatches.py            # write proposals, print a summary
    python3 pipeline/adjudication.py apply --dry-run .tmp/adjudication/evidence-fixes/country-corrections.json
    python3 pipeline/adjudication.py apply .tmp/adjudication/evidence-fixes/country-corrections.json
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from affiliation_evidence import (  # noqa: E402
    academic_evidence, build_name_index, countries_named, country_contradiction, looks_like_company,
    same_name_abroad)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
INDEX_JSON = os.path.join(REPO_ROOT, "data", "institutions.json")
DEFAULT_OUT = os.path.join(REPO_ROOT, ".tmp", "adjudication", "evidence-fixes")
DECIDED_BY = "fix_country_mismatches.py"
MIN_CLASH = 5        # same-name clashes before an institution's country-less rows are queued
CLASH_RATIO = 3      # ... and they must outnumber the consistent rows by this factor


def short_id(value):
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def propose(rows, by_id):
    """Return (corrections, companies, unresolved) for accepted education rows.

    corrections and companies are decisions for auto rows. unresolved is
    (raw, row, named countries, same-named institution there or "", reason).
    """
    name_index = build_name_index(by_id)
    corrections, companies, unresolved = [], [], []
    silent = {}          # institution id -> accepted rows whose string names no country
    agree, clash = Counter(), {}
    for row in rows:
        if row["status"] not in ("auto", "manual") or row["institution_type"] != "education" \
                or not row["institution_id"]:
            continue
        raw = row["raw_affiliation"]
        # The index, not the row, says where the institution is: some rows
        # carry a stale country_code from an earlier match.
        inst = by_id.get(row["institution_id"])
        if inst and (inst.get("country_code") or "") != row.get("country_code", ""):
            row = {**row, "country_code": inst.get("country_code") or ""}
        named = country_contradiction(raw, row.get("country_code", ""))
        if not countries_named(raw):
            silent.setdefault(row["institution_id"], []).append(row)
        elif not named:
            agree[row["institution_id"]] += 1
        if named:
            other = same_name_abroad(raw, row, by_id, name_index)
            if other:
                clash.setdefault(row["institution_id"], Counter())[other["id"]] += 1
            if other and row["status"] == "manual":
                # A person or model already decided this one; it is re-decided, not overwritten.
                unresolved.append((raw, row, named, f"{other['display_name']} ({other['country_code']})", "country"))
            elif other:
                corrections.append({
                    "raw_affiliation": raw, "decision": "corrected", "institution_id": short_id(other["id"]),
                    "evidence": (f"String names {'/'.join(sorted(named))}; {row['institution_name']} "
                                 f"({row['country_code']}) shares the name, and {other['display_name']} "
                                 f"({other['country_code']}) is the only education institution with it there."),
                    "decided_by": DECIDED_BY, "was": row["institution_name"], "was_status": row["status"]})
            else:
                unresolved.append((raw, row, named, "", "country"))
        elif looks_like_company(raw) and row["status"] == "manual":
            continue
        elif looks_like_company(raw):
            companies.append({
                "raw_affiliation": raw, "decision": "noneducation", "institution_id": None,
                "evidence": (f"Company string with no academic unit; it was credited to "
                             f"{row['institution_name']} via {row.get('matched_via') or 'a name fragment'!r}."),
                "decided_by": DECIDED_BY, "was": row["institution_name"], "was_status": row["status"]})
        elif row["status"] == "auto" and inst and not academic_evidence(raw, inst):
            # Neither an academic word nor the institution's own name: matched on a city or fragment.
            unresolved.append((raw, row, set(), "", "evidence"))
    # A string with no country cannot contradict anything, but when nearly every
    # string that does name one points at the same-named institution elsewhere,
    # the silent ones ('School of Automation, Southeast University') are suspect too.
    for iid, twins in clash.items():
        twin, n = twins.most_common(1)[0]
        if n >= MIN_CLASH and n >= CLASH_RATIO * agree[iid]:
            other = by_id[twin]
            for row in silent.get(iid, ()):
                if row["status"] == "auto":
                    unresolved.append((row["raw_affiliation"], row, set(),
                                       f"{other['display_name']} ({other['country_code']}), which {n} of "
                                       f"{n + agree[iid]} strings naming a country point to", "namesake"))
    return corrections, companies, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--map", default=MAP_CSV)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--show", type=int, default=12)
    args = parser.parse_args()

    with open(INDEX_JSON, encoding="utf8") as handle:
        by_id = json.load(handle)["by_id"]
    with open(args.map, newline="", encoding="utf8") as handle:
        rows = list(csv.DictReader(handle))
    corrections, companies, unresolved = propose(rows, by_id)

    os.makedirs(args.out, exist_ok=True)
    for name, decisions in (("country-corrections.json", corrections), ("company-noneducation.json", companies)):
        with open(os.path.join(args.out, name), "w", encoding="utf8") as handle:
            json.dump(decisions, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
    with open(os.path.join(args.out, "needs-adjudication.csv"), "w", newline="", encoding="utf8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["raw_affiliation", "status", "mapped_to", "mapped_country", "string_names",
                         "same_name_there", "reason"])
        for raw, row, named, suggestion, reason in unresolved:
            writer.writerow([raw, row["status"], row["institution_name"], row["country_code"],
                             "/".join(sorted(named)), suggestion, reason])

    print(f"country corrections:  {len(corrections)}")
    for (was, to), n in Counter((d["was"], by_id["https://openalex.org/" + d["institution_id"]]["display_name"] + " ("
                                 + by_id["https://openalex.org/" + d["institution_id"]]["country_code"] + ")")
                                for d in corrections).most_common(args.show):
        print(f"  {n:4d}  {was} -> {to}")
    print(f"company -> noneducation: {len(companies)}")
    for was, n in Counter(d["was"] for d in companies).most_common(args.show):
        print(f"  {n:4d}  credited to {was}")
    print(f"needs adjudication: {len(unresolved)}  {dict(Counter(u[4] for u in unresolved))}")
    for (name, cc), n in Counter((row["institution_name"], row["country_code"]) for _, row, _, _, _ in unresolved).most_common(args.show):
        print(f"  {n:4d}  {name} ({cc})")
    print(f"\nwrote proposals to {os.path.relpath(args.out, REPO_ROOT)}/; the map is unchanged.")
    print("next: python3 pipeline/adjudication.py apply --dry-run "
          f"{os.path.relpath(os.path.join(args.out, 'country-corrections.json'), REPO_ROOT)}")
    print("      python3 pipeline/adjudication.py queue --suspect --out .tmp/adjudication/suspect   # batches for the rest")


if __name__ == "__main__":
    main()
