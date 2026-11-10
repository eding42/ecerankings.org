---
name: verify-data
description: Run and interpret the deterministic data-quality checks (pipeline/verify.py, plus adjudication.py check and harvest_ml gates) after harvesting, normalization, adjudication, or aggregation — catch pipeline bugs, dropped credit, and affiliation errors before they reach the rankings.
---

# Verify data

Use after any change that can move credit:
- a harvest or re-harvest;
- `backfill_openalex.py --apply`;
- a normalizer run;
- an adjudication `apply` or `replay`;
- `aggregate.py`.

Also use before promoting any staged refresh.

**The checks are not random.** `verify.py` has no sampling, shuffling, or seeds.
- Every run scans the whole cache and aggregate.
- It uses fixed thresholds and compares against the last accepted snapshot.
- The same inputs give the same findings.

What *is* heuristic is the curated reference lists. Those can be wrong or stale, so a finding against them is a lead, not proof:
- `data/known-strong.json`;
- the geo-name list;
- campus clusters in `fix_campus_clusters.py`;
- traps in `data/adjudication-traps.csv`.

The one deliberately sampled artifact is `harvest_ml.py`'s `audit-sample.jsonl`. It holds 100 papers per edition, chosen by a stable hash, for human reading. It is labelled as a sample and certifies nothing.

## Which checker for which question

| Question | Command |
|---|---|
| Is the corpus or aggregate internally sound? | `python3 pipeline/verify.py --all` |
| Is a *staged* refresh sound, before promotion? | `python3 pipeline/verify.py --all --cache-dir <staged cache> --data-dir <candidate site/data>` |
| Is the affiliation map trustworthy? | `python3 pipeline/adjudication.py check` (exits 1 on a failed trap) |
| Did an ML edition meet its gates? | `python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage gates` |
| Would rankings change, and why? | `python3 pipeline/compare_aggregates.py` (candidate vs. baseline aggregates; see PR #1) |

Run `verify.py` read-only by default.
- `--update-snapshots` accepts the current state as the new regression baseline, and refuses unless the run is clean.
- Only pass it after the findings have been reviewed, never to make red go away.
- `--report` writes `data/reports/verify-YYYY-MM-DD.md`.

## How to read a run

1. **Compare against the previous run, not against zero.** A healthy corpus still has hundreds of open findings, because known external gaps are flagged on every run by design (see "Always-flag" below). What matters:
   - new or changed findings (diff the finding multiset against the last report);
   - regressions versus the snapshot;
   - any critical finding.
2. **Check magnitude, not just order.** A run that writes correct data which `aggregate.py` then discards looks healthy. Example: on 2026-07-25 a backfill wrote 49,554 works whose institutions lacked `type`, aggregation silently dropped them, and `verify.py` returned a byte-identical finding set. So:
   - compare adjusted-count totals per area against the last release;
   - use low-gap areas (`comms`, `inftheory`) as a control group that should barely move.
3. **Treat tripwires as data bugs until proven otherwise.** A `known-strong.json` institution at zero is a bug, not a ranking insight. The list only asserts non-zero. It cannot detect under-collection; `ml` once shipped with every tripwire green.

## What each phase checks

**Phase 1 — harvest (`cache/*/*/works.jsonl`)**
- zero-work venues (critical);
- missing registered years;
- counts versus `expected_per_year`;
- author completeness;
- per-venue-year affiliation coverage, plus regression versus snapshot;
- duplicate IDs and titles;
- solo-author share (non-research contamination);
- titles that look non-research but are still credited.

**Phase 2 — normalization (`data/affiliation-map.csv`)**
- resolution rate and type mix;
- one institution ID with conflicting countries;
- geo-heuristic name/country mismatches;
- compound strings;
- acronym and campus checks;
- ambiguous multi-element lineage (~25% of institutions; not auto-fixable);
- per-area affiliation gap;
- purity and resolution scorecards with regression.

**Phase 3 — aggregate (`site/data`)**
- `known-strong` zero audit;
- venues contributing zero credit;
- under-collected areas versus the median area;
- top-50 ranking regression;
- top-5 per area (shown for a human to read);
- authors at several institutions in one area-year;
- year-over-year outliers (>3σ);
- institution cliff drops (>80%).

## Severity

- **Critical — fix now:**
  - a registered venue or venue-year with no data;
  - a verified venue contributing zero credit;
  - a `known-strong` institution at zero;
  - any coverage, purity, or resolution regression of 50 points or more;
  - an `adjudication.py check` trap failure.
- **High — before the next aggregate:**
  - a venue-year below 70% of its expected floor;
  - coverage under 50%, purity under 30%, or resolution under 50%;
  - a regression of 10–50 points;
  - country conflicts;
  - geo violations;
  - more than 3 new campus misattributions;
  - ambiguous lineage at 20% or more.
- **Medium — investigate:** threshold bands below those; outliers; ranking moves of 10 or more positions; compound strings.
- **Low:** informational and within tolerance.

## Always-flag

Coverage, purity, resolution, and lineage findings are never suppressed for "known, unfixable" gaps such as pre-2021 IEEE Crossref metadata. This is an explicit project decision: suppression would let a new regression hide inside accepted red.

Expect long output. The signal is the diff and the regressions, not the length.

## After fixing

1. Rerun the specific phase.
2. Run `python3 pipeline/split.py` after any aggregate change.
3. Write a short report covering:
   - what was flagged;
   - what was fixed;
   - what was accepted and why;
   - the before/after totals for affected areas.

## Hard rules

- Validation is read-only. Fixes happen in the owning tool, then you re-verify:
  - harvest or backfill;
  - `adjudication.py apply`;
  - the `fix_*` scripts with `--apply` after review.
- Never edit `known-strong.json` to make a check pass. Add institutions only when they are certain to publish in that area, and only as a separate reviewed change.
- Never pass `--update-snapshots` on a run with unexplained critical or high findings.
