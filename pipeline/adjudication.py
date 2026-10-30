#!/usr/bin/env python3
"""Stable mechanics for affiliation adjudication (data/affiliation-map.csv).

The adjudicate-affiliations skill decides; this script does everything that
must come out the same every time:

  queue   Export unresolved raw strings as deterministic batches, sorted by
          credited-share impact, with the current mapping and its case/space
          variants alongside. Strings found in a cache tree but absent from
          the map (new PDF/Crossref text) are included as status "unmapped".
  search  Look up OpenAlex institutions in the local index
          (data/institutions.json) -- no API budget, same answer every run.
  apply   Validate decision files and merge them into the map. Institution
          name/type/country always come from the index, never from the
          adjudicator's text. Every accepted decision is appended to the
          ledger data/affiliation-decisions.jsonl with its evidence.
  replay  Re-apply the latest ledger decision for every string. Restores
          adjudicated rows if a normalizer rerun or a fix script overwrote them.
  check   Pure QA, no writes: known traps (data/adjudication-traps.csv),
          case/space variants mapped to different institutions, rows whose
          stored name/type/country contradict the index, non-acronym short
          matches, and company strings matched to a university by city name.
          Exits 1 when a trap fails.

Decision file format (a JSON list; one object per queued row):

  {"key": "<from queue>", "raw_affiliation": "...",
   "decision": "supported|corrected|noneducation|unresolved|needs-policy",
   "institution_id": "I123..." (required for supported/corrected; optional
                                 for noneducation, e.g. a company's OpenAlex ID),
   "evidence": "why -- what in the string identifies the institution",
   "decided_by": "model or person"}

Outcomes follow docs/review/refresh-workflow.proposed.md. A map row resolves
to ONE institution (aggregate.py's contract), so a compound string naming two
universities with no primary one is "unresolved", not a guess.

Usage:
    python3 pipeline/adjudication.py queue --out .tmp/adjudication --batch 20
    python3 pipeline/adjudication.py queue --cache-dir .tmp/ml-harvest/cache --only-unmapped
    python3 pipeline/adjudication.py search "purdue university"
    python3 pipeline/adjudication.py apply .tmp/adjudication/decisions-*.json --dry-run
    python3 pipeline/adjudication.py replay
    python3 pipeline/adjudication.py check
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAP_CSV = ROOT / "data" / "affiliation-map.csv"
INDEX_JSON = ROOT / "data" / "institutions.json"
LEDGER = ROOT / "data" / "affiliation-decisions.jsonl"
TRAPS_CSV = ROOT / "data" / "adjudication-traps.csv"
CACHE_DIR = ROOT / "cache"

DECISIONS = {"supported", "corrected", "noneducation", "unresolved", "needs-policy"}
# Map status written for each outcome. needs-policy leaves the row in review.
STATUS_FOR = {"supported": "manual", "corrected": "manual", "noneducation": "manual",
              "unresolved": "unmatched", "needs-policy": None}
TYPES = {"education", "company", "facility", "government", "nonprofit", "healthcare", "archive", "funder", "other"}
PENDING = ("review", "unmapped")

_CITY = {"tokyo", "beijing", "shanghai", "seoul", "london", "paris", "berlin", "munich", "boston",
         "san diego", "san jose", "santa clara", "dallas", "austin", "seattle", "palo alto",
         "mountain view", "sunnyvale", "cambridge", "oxford", "zurich", "geneva", "hong kong",
         "singapore", "shenzhen", "guangzhou", "nanjing", "hangzhou", "chengdu", "wuhan", "xian",
         "tianjin", "suzhou", "dresden", "stuttgart", "hamburg", "frankfurt", "aachen", "eindhoven",
         "delft", "helsinki", "stockholm", "copenhagen", "oslo", "melbourne", "sydney", "toronto",
         "vancouver", "montreal", "taipei", "hsinchu", "kyoto", "osaka", "yokohama", "nagoya",
         "bengaluru", "hyderabad", "mumbai", "delhi", "pune"}
_CORP = re.compile(r"\b(inc|ltd|gmbh|corp|corporation|llc|limited|company|co\.|research lab(?:oratories|oratory)?|ai research)\b", re.I)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fold(text):
    """Case/accent/space-insensitive form used to find variants of one string."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def row_key(raw):
    return hashlib.sha1(raw.encode("utf8")).hexdigest()[:16]


def short_id(value):
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def full_id(value):
    value = short_id(value)
    return f"https://openalex.org/{value}" if value else ""


# --------------------------------------------------------------------------
# Files

class ConcurrentWrite(RuntimeError):
    pass


def _stamp(path):
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


def read_map(path=None):
    """Return (fieldnames, rows, stamp). The stamp guards write_map."""
    path = Path(path or MAP_CSV)
    stamp = _stamp(path)
    with open(path, newline="", encoding="utf8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader), stamp


def write_map(fieldnames, rows, path=None, expect_stamp=None):
    """Atomic rewrite. Refuses if the file changed since it was read.

    normalize_semantic.py, normalize_affiliations_local.py and the fix_*
    scripts all rewrite this file whole; two writers interleaving would
    silently drop one side's rows.
    """
    path = Path(path or MAP_CSV)
    if expect_stamp is not None and path.exists() and _stamp(path) != expect_stamp:
        raise ConcurrentWrite(f"{path} changed since it was read (another writer running?); nothing written")
    mode = os.stat(path).st_mode & 0o777 if path.exists() else 0o644
    fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        os.chmod(temp, mode)
        if expect_stamp is not None and path.exists() and _stamp(path) != expect_stamp:
            raise ConcurrentWrite(f"{path} changed while writing (another writer running?); nothing written")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def load_index(path=None):
    path = Path(path or INDEX_JSON)
    if not path.exists():
        raise SystemExit(f"{path} is missing (committed local index). Check git checkout or rebuild it before adjudicating.")
    with open(path, encoding="utf8") as handle:
        return json.load(handle)["by_id"]


def read_ledger(path=None):
    path = Path(path or LEDGER)
    if not path.exists():
        return []
    with open(path, encoding="utf8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def append_ledger(entries, path=None):
    if not entries:
        return
    with open(path or LEDGER, "a", encoding="utf8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


# --------------------------------------------------------------------------
# queue

def string_weights(cache_dirs):
    """raw string -> (occurrences, credited-share) over authorships the map serves.

    aggregate.py consults the map only when an authorship has no institutions,
    so only those authorships count toward a string's impact.
    """
    occ, share = Counter(), Counter()
    for cache_dir in cache_dirs:
        for path in sorted(glob.glob(os.path.join(cache_dir, "*", "*", "works.jsonl"))):
            with open(path, "rb") as handle:
                if handle.read(40).startswith(b"version https://git-lfs"):
                    continue
            with open(path, encoding="utf8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    work = json.loads(line)
                    authors = work.get("authorships") or []
                    for author in authors:
                        if author.get("institutions"):
                            continue
                        raws = author.get("raw_affiliations") or []
                        for raw in raws:
                            occ[raw] += 1
                            share[raw] += 1.0 / (len(authors) * len(raws))
    return occ, share


def cmd_queue(args):
    fieldnames, rows, _ = read_map()
    by_raw = {r["raw_affiliation"]: r for r in rows}
    variants = defaultdict(list)
    for r in rows:
        variants[fold(r["raw_affiliation"])].append(r)
    occ, share = string_weights(args.cache_dir or [str(CACHE_DIR)])
    pending = [] if args.only_unmapped else [r for r in rows if r["status"] in args.status]
    # New strings in the cache that the map has never seen.
    for raw in occ:
        if raw not in by_raw:
            pending.append({"raw_affiliation": raw, "status": "unmapped", "institution_id": "",
                            "institution_name": "", "institution_type": "", "country_code": "",
                            "matched_via": "", "score": "", "candidate": ""})
    pending.sort(key=lambda r: (-share.get(r["raw_affiliation"], 0.0), -occ.get(r["raw_affiliation"], 0), r["raw_affiliation"]))
    if args.limit:
        pending = pending[:args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    batches = [pending[i:i + args.batch] for i in range(0, len(pending), args.batch)]
    for number, batch in enumerate(batches, 1):
        items = []
        for r in batch:
            raw = r["raw_affiliation"]
            items.append({
                "key": row_key(raw), "raw_affiliation": raw, "status": r["status"],
                "current": {k: r.get(k, "") for k in ("institution_id", "institution_name", "institution_type", "country_code")},
                "matched_via": r.get("matched_via", ""), "score": r.get("score", ""),
                "occurrences": occ.get(raw, 0), "credited_share": round(share.get(raw, 0.0), 4),
                "variants": [{"raw_affiliation": v["raw_affiliation"], "status": v["status"],
                              "institution_name": v["institution_name"], "institution_type": v["institution_type"]}
                             for v in variants.get(fold(raw), []) if v["raw_affiliation"] != raw][:5],
            })
        (out / f"batch-{number:04d}.json").write_text(json.dumps({"batch": number, "rows": items}, ensure_ascii=False, indent=1))
    print(f"queued {len(pending)} strings in {len(batches)} batches of <= {args.batch} -> {out}")
    print(f"  by status: {dict(Counter(r['status'] for r in pending))}")
    print(f"  credited share covered: {sum(share.get(r['raw_affiliation'], 0) for r in pending):.1f}")


# --------------------------------------------------------------------------
# search

def cmd_search(args):
    index = load_index()
    query = set(fold(args.query).split())
    scored = []
    for inst in index.values():
        names = [inst["display_name"]] + list(inst.get("alternatives") or []) + list(inst.get("acronyms") or [])
        best = 0.0
        for name in names:
            tokens = set(fold(name).split())
            if tokens:
                best = max(best, len(query & tokens) / len(query | tokens))
        if best > 0:
            scored.append((best, inst))
    scored.sort(key=lambda x: (-x[0], x[1]["display_name"], x[1]["id"]))
    for score, inst in scored[:args.limit]:
        print(f"{score:.2f}  {short_id(inst['id']):12s}  {inst['type']:11s} {inst.get('country_code') or '--'}  {inst['display_name']}")


# --------------------------------------------------------------------------
# apply / replay

def validate(decision, index):
    """Return (row_fields, error). row_fields come from the index, not the decision."""
    kind = decision.get("decision")
    if kind not in DECISIONS:
        return None, f"unknown decision {kind!r}"
    if not str(decision.get("evidence") or "").strip():
        return None, "evidence is required"
    if not decision.get("raw_affiliation"):
        return None, "raw_affiliation is required"
    if decision.get("key") and decision["key"] != row_key(decision["raw_affiliation"]):
        return None, "key does not match raw_affiliation (string altered?)"
    iid = full_id(decision.get("institution_id"))
    if kind in ("supported", "corrected") and not iid:
        return None, f"{kind} requires institution_id"
    if iid:
        inst = index.get(iid)
        if not inst:
            return None, f"{short_id(iid)} is not in data/institutions.json"
        if kind in ("supported", "corrected") and inst.get("type") != "education":
            return None, f"{inst['display_name']} is type {inst.get('type')}; use noneducation"
        if kind == "noneducation" and inst.get("type") == "education":
            return None, f"{inst['display_name']} is education; noneducation contradicts the index"
        lineage = inst.get("lineage") or [iid]
        return {"institution_id": iid, "institution_name": inst["display_name"],
                "institution_type": inst.get("type") or "", "country_code": inst.get("country_code") or "",
                "lineage": "|".join(lineage)}, None
    if kind == "noneducation":
        return {"institution_id": "", "institution_name": "", "institution_type": "company",
                "country_code": "", "lineage": ""}, None
    return {"institution_id": "", "institution_name": "", "institution_type": "",
            "country_code": "", "lineage": ""}, None


def merge(rows, fieldnames, decisions, index, override=False, source="apply"):
    by_raw = {r["raw_affiliation"]: r for r in rows}
    accepted, rejected = [], []
    for d in decisions:
        fields, error = validate(d, index)
        raw = d.get("raw_affiliation", "")
        current = by_raw.get(raw)
        if not error and current and current["status"] == "manual" and not override and source == "apply":
            same = short_id(current.get("institution_id")) == short_id((fields or {}).get("institution_id")) \
                and STATUS_FOR[d["decision"]] == "manual"
            if not same:
                error = (f"already manual -> {current.get('institution_name') or '(none)'}; "
                         "pass --override to replace an earlier adjudication")
        if error:
            rejected.append({"raw_affiliation": raw, "error": error})
            continue
        status = STATUS_FOR[d["decision"]]
        if status:
            row = current or {name: "" for name in fieldnames}
            if not current:
                row["raw_affiliation"] = raw
                rows.append(row)
                by_raw[raw] = row
            row.update({k: v for k, v in fields.items() if k in fieldnames})
            row["status"] = status
            row["matched_via"] = f"adjudicated:{d['decision']}"
        accepted.append(d)
    return accepted, rejected


def cmd_apply(args):
    index = load_index()
    fieldnames, rows, stamp = read_map()
    decisions = []
    for pattern in args.files:
        for path in sorted(glob.glob(pattern)):
            data = json.loads(Path(path).read_text(encoding="utf8"))
            decisions.extend(data if isinstance(data, list) else data.get("decisions", []))
    accepted, rejected = merge(rows, fieldnames, decisions, index, override=args.override)
    print(f"decisions: {len(decisions)}  accepted: {len(accepted)}  rejected: {len(rejected)}")
    print(f"  by outcome: {dict(Counter(d['decision'] for d in accepted))}")
    for r in rejected[:40]:
        print(f"  REJECTED {r['raw_affiliation'][:60]!r}: {r['error']}")
    if args.dry_run or not accepted:
        print("map and ledger unchanged" + (" (dry run)" if args.dry_run else " (nothing accepted)"))
        return 1 if rejected else 0
    write_map(fieldnames, rows, expect_stamp=stamp)
    stamp = utc_now()
    append_ledger([{**{k: d.get(k) for k in ("raw_affiliation", "decision", "evidence", "decided_by")},
                    "institution_id": short_id(d.get("institution_id")) or None, "at": stamp} for d in accepted])
    print(f"wrote {MAP_CSV} and appended {len(accepted)} entries to {LEDGER}")
    return 1 if rejected else 0


def cmd_replay(args):
    index = load_index()
    fieldnames, rows, stamp = read_map()
    latest = {}
    for entry in read_ledger():
        latest[entry["raw_affiliation"]] = entry
    before = {r["raw_affiliation"]: (r["status"], short_id(r["institution_id"]), r["institution_type"]) for r in rows}
    accepted, rejected = merge(rows, fieldnames, list(latest.values()), index, override=True, source="replay")
    changed = [r["raw_affiliation"] for r in rows
               if before.get(r["raw_affiliation"]) != (r["status"], short_id(r["institution_id"]), r["institution_type"])]
    print(f"ledger decisions: {len(latest)}  re-applied: {len(accepted)}  invalid now: {len(rejected)}  rows restored: {len(changed)}")
    for raw in changed[:20]:
        print(f"  restored {raw[:70]!r}")
    for r in rejected[:20]:
        print(f"  INVALID {r['raw_affiliation'][:60]!r}: {r['error']}")
    if not args.dry_run and changed:
        write_map(fieldnames, rows, expect_stamp=stamp)
    return 1 if rejected else 0


# --------------------------------------------------------------------------
# check

def load_traps(path=None):
    path = Path(path or TRAPS_CSV)
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf8") as handle:
        return [r for r in csv.DictReader(handle) if not r["raw_affiliation"].startswith("#")]


def trap_result(trap, row):
    """None when the row satisfies the expectation, else a failure message."""
    if row is None:
        return None if trap.get("absent_ok") == "yes" else "string not in map"
    expect = trap["expect"]
    resolved = row["status"] in ("auto", "manual")
    iid, itype = short_id(row["institution_id"]), row["institution_type"]
    for clause in expect.split(";"):
        kind, _, value = clause.strip().partition(":")
        if kind == "id" and not (resolved and iid == value):
            return f"expected {value}, map has {iid or '(none)'} [{row['status']}]"
        if kind == "not" and resolved and iid == value:
            return f"mapped to forbidden {value} ({row['institution_name']}) [{row['status']}]"
        if kind == "noneducation" and resolved and itype == "education":
            return f"credited as education: {row['institution_name']} [{row['status']}]"
    return None


def cmd_check(args):
    _, rows, _ = read_map()
    by_raw = {r["raw_affiliation"]: r for r in rows}
    index = load_index() if Path(INDEX_JSON).exists() else {}
    failures = 0

    traps = load_traps()
    print(f"== traps ({TRAPS_CSV}): {len(traps)}")
    for trap in traps:
        message = trap_result(trap, by_raw.get(trap["raw_affiliation"]))
        if message:
            failures += 1
            print(f"  FAIL {trap['raw_affiliation'][:55]!r}: {message}  -- {trap['why']}")
    print(f"  {len(traps) - failures} pass, {failures} fail")

    print("== variants of one string mapped to different institutions (at least one credited as education)")
    groups = defaultdict(list)
    for r in rows:
        if r["status"] in ("auto", "manual") and r["institution_id"]:
            groups[fold(r["raw_affiliation"])].append(r)
    split = {k: g for k, g in groups.items() if len({short_id(r["institution_id"]) for r in g}) > 1
             and any(r["institution_type"] == "education" for r in g)}
    for k, group in sorted(split.items(), key=lambda kv: -len(kv[1]))[:args.show]:
        print(f"  {k[:60]!r}: " + "; ".join(f"[{r['status']}] {r['raw_affiliation'][:30]!r}->{r['institution_name'][:30]}" for r in group[:4]))
    print(f"  {len(split)} variant groups disagree")

    incoherent = []
    if index:
        for r in rows:
            if r["status"] in ("auto", "manual") and r["institution_id"]:
                inst = index.get(full_id(r["institution_id"]))
                if inst and (inst.get("type") or "") != r["institution_type"]:
                    incoherent.append((r, inst))
    # Older manual rows sometimes kept a university's ID but retyped it to
    # block credit ("Alibaba Group and UCSD" -> company). New decisions use
    # "noneducation" without the university's ID instead; review these.
    print(f"== rows whose institution_type contradicts the index: {len(incoherent)}")
    for r, inst in incoherent[:args.show]:
        print(f"  [{r['status']}] {r['raw_affiliation'][:45]!r} -> {inst['display_name'][:35]} row={r['institution_type'] or '-'} index={inst.get('type')}")

    acr = []
    for r in rows:
        mv = r.get("matched_via", "")
        if (r["status"] in ("auto", "manual") and r["institution_type"] == "education"
                and len(mv) <= 5 and mv.isalpha() and index):
            inst = index.get(full_id(r["institution_id"]))
            known = {a.lower() for a in (inst or {}).get("acronyms", []) + (inst or {}).get("alternatives", [])}
            if mv.lower() not in known:
                acr.append(r)
    print(f"== education credit via a short matched_via that is not an official acronym/alternative: {len(acr)}")
    for r in acr[:args.show]:
        print(f"  {r['matched_via']!r} -> {r['institution_name'][:40]}  raw={r['raw_affiliation'][:50]!r}")

    city = [r for r in rows if r["status"] in ("auto", "manual") and r["institution_type"] == "education"
            and r.get("matched_via", "").lower() in _CITY and _CORP.search(r["raw_affiliation"])]
    print(f"== company strings credited to a university via a city name: {len(city)}")
    for r in city[:args.show]:
        print(f"  [{r['status']}] {r['raw_affiliation'][:55]!r} -> {r['institution_name'][:35]}")

    print("== also run (each prints proposals; --apply only after review):")
    print("  python3 pipeline/fix_acronym_collisions.py --report")
    print("  python3 pipeline/fix_name_mismatches.py --report")
    print("  python3 pipeline/fix_campus_clusters.py")
    return 1 if failures else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("queue")
    q.add_argument("--out", default=str(ROOT / ".tmp" / "adjudication"))
    q.add_argument("--batch", type=int, default=20)
    q.add_argument("--status", nargs="+", default=["review"])
    q.add_argument("--cache-dir", action="append", help="Cache tree(s) to weight strings by (default: cache/)")
    q.add_argument("--only-unmapped", action="store_true", help="Only strings absent from the map")
    q.add_argument("--limit", type=int, default=None)
    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    a = sub.add_parser("apply")
    a.add_argument("files", nargs="+")
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--override", action="store_true", help="Replace rows that are already manual")
    r = sub.add_parser("replay")
    r.add_argument("--dry-run", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--show", type=int, default=15)
    args = parser.parse_args(argv)
    handler = {"queue": cmd_queue, "search": cmd_search, "apply": cmd_apply, "replay": cmd_replay, "check": cmd_check}[args.command]
    try:
        return handler(args) or 0
    except ConcurrentWrite as exc:
        print(f"adjudication: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
