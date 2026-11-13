#!/usr/bin/env python3
"""Measure how often the affiliation map is wrong, by seeded random sampling.

Every other check in verify.py is a rule: it finds the errors somebody already
thought of. This one finds the rest. It draws a reproducible random sample of
map rows, has an independent judge decide each string without seeing the
current answer, and reports the error rate with a confidence interval.

Why it exists: the first hand audit (2026-11-12, 58 credit-weighted rows) found
3 wrong, about 5%, and one of the three (a company named "... Laboratories"
credited to San Francisco State University) was invisible to every rule.

    draw   --seed 2026 --size 300      write the sample and blind batches
    score  --seed 2026 decisions...    compare the judge's decisions, write the report

Strata (shares of --size). Each is reported on its own, because a rare failure
shows up in a risky stratum long before it moves the overall rate:

    credit        50%  accepted education rows, drawn in proportion to the credit
                       they carry. This stratum alone estimates how many credits
                       are misassigned.
    short         10%  strings of two words or fewer: acronyms, bare names
    manual        10%  rows a person or model already decided
    no_evidence   10%  accepted rows with no academic word and no trace of the
                       institution's name in the string
    not_credited  10%  rows credited to nobody (company, unresolved), drawn by credit:
                       the false-negative direction
    unmatched     10%  review/unmatched rows, drawn by credit

The judge sees only `raw_affiliation`. It may use `adjudication.py search`.
Decisions use the adjudication format: key, decision (education | supported |
corrected | noneducation | unresolved), institution_id, evidence, decided_by.

Read-only apart from its own output directory and the report. Stdlib only.
"""

import argparse
import csv
import glob
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adjudication  # noqa: E402
from affiliation_evidence import academic_evidence  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAP_CSV = os.path.join(REPO_ROOT, "data", "affiliation-map.csv")
ALIASES_CSV = os.path.join(REPO_ROOT, "data", "institution-aliases.csv")
REPORT_DIR = os.path.join(REPO_ROOT, "data", "reports")
DEFAULT_OUT = os.path.join(REPO_ROOT, ".tmp", "map-audit")
BATCH = 25
CREDIT_TYPES = {"education"}
STRATA = (("credit", 0.50), ("short", 0.10), ("manual", 0.10), ("no_evidence", 0.10),
          ("not_credited", 0.10), ("unmatched", 0.10))
MAX_ERROR_DEFAULT = 0.03


def short_id(value):
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def wilson(errors, n, z=1.96):
    """95% Wilson interval for a proportion."""
    if n == 0:
        return 0.0, 0.0, 1.0
    p = errors / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return p, max(0.0, centre - half), min(1.0, centre + half)


def load_aliases(path=ALIASES_CSV):
    if not os.path.exists(path):
        return {}
    with open(path, newline="") as handle:
        return {short_id(r["duplicate_id"]): short_id(r["canonical_id"]) for r in csv.DictReader(handle)}


def credited(row):
    return row["status"] in ("auto", "manual") and bool(row["institution_id"]) and row["institution_type"] in CREDIT_TYPES


def accepted_education(row):
    return credited(row) and row["institution_type"] == "education"


def pps(rows, weights, k, rng):
    """k draws with replacement, probability proportional to weight."""
    total = sum(weights)
    if not total or not rows:
        return Counter()
    return Counter(rng.choices(range(len(rows)), weights=weights, k=k))


def draw_sample(rows, share, index, size, seed):
    """Return {raw: item}. Deterministic for a given map, cache and seed."""
    rng = random.Random(seed)
    rows = sorted(rows, key=lambda r: r["raw_affiliation"])
    quota = {name: max(1, round(size * frac)) for name, frac in STRATA}
    weight = lambda r: share.get(r["raw_affiliation"], 0.0)  # noqa: E731
    pools = {
        "credit": [r for r in rows if accepted_education(r)],
        "short": [r for r in rows if accepted_education(r) and len(r["raw_affiliation"].split()) <= 2],
        "manual": [r for r in rows if r["status"] == "manual" and credited(r)],
        "no_evidence": [r for r in rows if r["status"] == "auto" and accepted_education(r)
                        and index.get(r["institution_id"]) and not academic_evidence(r["raw_affiliation"], index[r["institution_id"]])],
        "not_credited": [r for r in rows if r["status"] in ("auto", "manual") and not credited(r) and weight(r) > 0],
        "unmatched": [r for r in rows if r["status"] in ("review", "unmatched") and weight(r) > 0],
    }
    sample = {}
    for name, _ in STRATA:
        pool = pools[name]
        if not pool:
            continue
        if name in ("credit", "not_credited", "unmatched"):
            draws = pps(pool, [weight(r) for r in pool], quota[name], rng)
            picked = [(pool[i], count) for i, count in sorted(draws.items())]
        else:
            picked = [(r, 1) for r in rng.sample(pool, min(quota[name], len(pool)))]
        for row, count in picked:
            raw = row["raw_affiliation"]
            entry = sample.setdefault(raw, {
                "key": adjudication.row_key(raw), "raw_affiliation": raw, "strata": {},
                "current": {k: row.get(k, "") for k in ("status", "institution_id", "institution_name",
                                                        "institution_type", "country_code", "matched_via")},
                "credit_share": round(share.get(raw, 0.0), 4)})
            entry["strata"][name] = entry["strata"].get(name, 0) + count
    return sample, {name: len(pools[name]) for name, _ in STRATA}


def write_sample(out, sample, meta):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "sample.json"), "w", encoding="utf8") as handle:
        json.dump({"meta": meta, "items": list(sample.values())}, handle, ensure_ascii=False, indent=1)
    items = [{"key": s["key"], "raw_affiliation": s["raw_affiliation"]} for s in sample.values()]
    random.Random(meta["seed"]).shuffle(items)          # the judge must not see strata or order
    for old in glob.glob(os.path.join(out, "blind-batch-*.json")):
        os.remove(old)
    for number, start in enumerate(range(0, len(items), BATCH), 1):
        with open(os.path.join(out, f"blind-batch-{number:04d}.json"), "w", encoding="utf8") as handle:
            json.dump({"batch": number, "rows": items[start:start + BATCH]}, handle, ensure_ascii=False, indent=1)
    return (len(items) + BATCH - 1) // BATCH


def load_decisions(paths):
    decisions = {}
    for pattern in paths:
        for path in sorted(glob.glob(pattern)):
            with open(path, encoding="utf8") as handle:
                data = json.load(handle)
            for d in data["decisions"] if isinstance(data, dict) and "decisions" in data else data:
                key = d.get("key") or adjudication.row_key(d.get("raw_affiliation", ""))
                decisions[key] = d
    return decisions


def judge_verdict(decision):
    kind = (decision.get("decision") or "").lower()
    if kind in ("education", "supported", "corrected"):
        return "education", short_id(decision.get("institution_id"))
    if kind == "noneducation":
        return "noneducation", ""
    return "unresolved", ""


def classify(item, decision, aliases):
    """correct | wrong_institution | wrong_credited | missed_credit | undecidable"""
    verdict, judged = judge_verdict(decision)
    current = item["current"]
    was_credited = credited({**current, "institution_type": current["institution_type"]})
    if verdict == "unresolved":
        return "undecidable" if was_credited else "correct"
    if was_credited:
        if verdict == "noneducation":
            return "wrong_credited"
        mine = short_id(current["institution_id"])
        return "correct" if aliases.get(mine, mine) == aliases.get(judged, judged) else "wrong_institution"
    return "missed_credit" if verdict == "education" else "correct"


def score(sample, decisions, aliases):
    items = sample["items"]
    per_stratum = defaultdict(Counter)
    outcomes = {}
    for item in items:
        decision = decisions.get(item["key"])
        if not decision:
            continue
        outcome = classify(item, decision, aliases)
        outcomes[item["key"]] = (item, decision, outcome)
        for stratum, count in item["strata"].items():
            per_stratum[stratum][outcome] += count
            per_stratum[stratum]["n"] += count
    return per_stratum, outcomes


def render_report(sample, per_stratum, outcomes, seed, credited_total, max_error):
    lines = [f"# Affiliation map audit, seed {seed}, {date.today().isoformat()}", "",
             f"{sum(1 for _ in sample['items'])} strings sampled, {len(outcomes)} judged.", "",
             "| stratum | judged | wrong | missed credit | undecidable | error rate | 95% interval |",
             "|---|---|---|---|---|---|---|"]
    failing = False
    estimate = None
    for name, _ in STRATA:
        c = per_stratum.get(name)
        if not c:
            continue
        wrong = c["wrong_institution"] + c["wrong_credited"]
        missed = c["missed_credit"]
        decided = c["n"] - c["undecidable"]
        p, low, high = wilson(wrong + missed, decided)
        lines.append(f"| {name} | {c['n']} | {wrong} | {missed} | {c['undecidable']} | {p:.1%} | {low:.1%} to {high:.1%} |")
        if name == "credit":
            estimate = (wrong, decided)
    if estimate:
        wrong, decided = estimate
        p, low, high = wilson(wrong, decided)
        lines += ["", f"**Credit-weighted error rate: {p:.1%} (95% interval {low:.1%} to {high:.1%}).** "
                      f"Of {credited_total:,.0f} credits that flow through accepted education rows, about "
                      f"{p * credited_total:,.0f} are misassigned (range {low * credited_total:,.0f} to {high * credited_total:,.0f})."]
        failing = p > max_error
        lines.append(f"Gate: point estimate {'above' if failing else 'within'} {max_error:.0%}.")
    misses = [(i, d, o) for i, d, o in outcomes.values() if o in ("wrong_institution", "wrong_credited", "missed_credit")]
    if misses:
        lines += ["", "## Disagreements", ""]
        for item, decision, outcome in sorted(misses, key=lambda t: -t[0]["credit_share"]):
            cur = item["current"]
            lines.append(f"- `{item['raw_affiliation'][:110]}`  \n  map: {cur['institution_name'] or '(none)'} "
                         f"[{cur['status']}]; judge: {decision.get('decision')} {decision.get('institution_id') or ''}"
                         f" ({outcome}, credit {item['credit_share']}). {decision.get('evidence', '')}")
    return "\n".join(lines) + "\n", failing


def cmd_draw(args):
    index = adjudication.load_index()
    with open(MAP_CSV, newline="", encoding="utf8") as handle:
        rows = list(csv.DictReader(handle))
    _, share = adjudication.string_weights([os.path.join(REPO_ROOT, "cache")])
    sample, pool_sizes = draw_sample(rows, share, index, args.size, args.seed)
    out = args.out or os.path.join(DEFAULT_OUT, f"seed-{args.seed}")
    batches = write_sample(out, sample, {"seed": args.seed, "size": args.size, "pools": pool_sizes,
                                         "map_rows": len(rows), "drawn": date.today().isoformat()})
    counts = Counter(s for item in sample.values() for s in item["strata"])
    print(f"sampled {len(sample)} distinct strings ({dict(counts)}) -> {out}")
    print(f"{batches} blind batches of <= {BATCH}; the judge sees only raw_affiliation")
    print(f"next: judge each batch, save decisions-*.json in {out}, then: "
          f"python3 pipeline/audit_map_sample.py score --seed {args.seed} '{out}/decisions-*.json'")


def cmd_score(args):
    out = args.out or os.path.join(DEFAULT_OUT, f"seed-{args.seed}")
    with open(os.path.join(out, "sample.json"), encoding="utf8") as handle:
        sample = json.load(handle)
    decisions = load_decisions(args.decisions or [os.path.join(out, "decisions-*.json")])
    per_stratum, outcomes = score(sample, decisions, load_aliases())
    missing = len(sample["items"]) - len(outcomes)
    with open(MAP_CSV, newline="", encoding="utf8") as handle:
        rows = list(csv.DictReader(handle))
    _, share = adjudication.string_weights([os.path.join(REPO_ROOT, "cache")])
    credited_total = sum(share.get(r["raw_affiliation"], 0.0) for r in rows if accepted_education(r))
    report, failing = render_report(sample, per_stratum, outcomes, args.seed, credited_total, args.max_error)
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"map-audit-{date.today().isoformat()}-seed{args.seed}.md")
    with open(report_path, "w", encoding="utf8") as handle:
        handle.write(report)
    fixes = []
    for item, decision, outcome in outcomes.values():
        if outcome in ("wrong_institution", "wrong_credited", "missed_credit"):
            verdict, judged = judge_verdict(decision)
            fixes.append({"raw_affiliation": item["raw_affiliation"],
                          "decision": "noneducation" if verdict == "noneducation" else "corrected",
                          "institution_id": None if verdict == "noneducation" else judged,
                          "evidence": decision.get("evidence") or "blind re-judgement disagreed with the map",
                          "decided_by": decision.get("decided_by") or "map-audit"})
    fix_path = os.path.join(out, "disagreements.json")
    with open(fix_path, "w", encoding="utf8") as handle:
        json.dump(fixes, handle, ensure_ascii=False, indent=1)
    print(report)
    if missing:
        print(f"WARNING: {missing} sampled strings have no decision; their strata are underfilled.")
    print(f"report: {os.path.relpath(report_path, REPO_ROOT)}")
    print(f"{len(fixes)} disagreements -> {os.path.relpath(fix_path, REPO_ROOT)}; "
          f"review, then `adjudication.py apply --dry-run` it. Nothing was applied.")
    return 2 if failing or missing == len(sample["items"]) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draw")
    d.add_argument("--seed", type=int, required=True)
    d.add_argument("--size", type=int, default=300)
    d.add_argument("--out")
    s = sub.add_parser("score")
    s.add_argument("--seed", type=int, required=True)
    s.add_argument("--out")
    s.add_argument("--max-error", type=float, default=MAX_ERROR_DEFAULT)
    s.add_argument("decisions", nargs="*", help="decision JSON files or globs (default: <out>/decisions-*.json)")
    args = parser.parse_args()
    return cmd_draw(args) if args.command == "draw" else cmd_score(args)


if __name__ == "__main__":
    sys.exit(main())
