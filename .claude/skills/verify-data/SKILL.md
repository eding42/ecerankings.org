---
name: verify-data
description: Run data-quality checks after harvesting, normalization, or aggregation — catch pipeline bugs, data corruption, and affiliation mismatches before they reach the rankings.
---

# Verify Data

Run multi-layer quality checks against the pipeline output. Use after (a) harvesting a new venue or re-harvesting a year, (b) re-running the normalizer, or (c) running aggregate — any change that could have introduced or propagated errors.

## Architecture & layers

The verifier runs in three phases, ordered from cheapest (works-level stats) to most expensive (ranking cross-validation). Each phase can run independently; all phases run with `--all`.

### Phase 1: Harvest integrity (works.jsonl)
- **Venue coverage**: papers per venue-year vs `expected_per_year` in `areas.json`. Flag any venue-year >30% below the floor.
- **Year coverage**: every `years{}` entry with `source != "none"` has a `works.jsonl`. Flag missing years.
- **Author completeness**: % of works with zero authors. Should be ~0%.
- **Affiliation presence**: % of authorships with at least one `raw_affiliations` entry. Flag if <80%.
- **Duplicate check**: paper IDs should be unique within a venue-year. Flag exact-title duplicates.

### Phase 2: Normalization integrity (affiliation-map.csv + cross-reference)
- **Resolution rate**: % of distinct `raw_affiliation` strings with `status=auto` or `manual` and `institution_type=education`. Target: >65%.
- **Institution type distribution**: count of education / company / government / facility / other. Flag if education <50%.
- **Suspicious default matches per cluster**: re-run `pipeline/fix_campus_clusters.py` and flag any new misattributions (since the last run should have caught everything).
- **Acronym validation**: re-run the acronym check from adjudication skill step 5. Flag any new mismatches.
- **Type validation**: re-run the type check from adjudication skill step 6. Flag any new company/education misclassifications.

### Phase 3: Aggregate integrity (inst-area-year.csv)
- **Zero-count audit**: per area, schools with known strength that show `adjusted_count = 0`. Reference: `data/known-strong.json` (user-curated, maintain outside this script). Flag every discrepancy.
- **Venue-area contribution**: each venue key should have at least 1 credited institution. If a venue contributes zero (all institutions dropped), flag — this indicates a normalization gap.
- **Top-N sanity**: for each area's top 5 schools, print the adjusted count. Human-visible check (no automated flag — needs domain knowledge).
- **Author cross-validation**: same `author_id` appearing at different institutions in the same area+year. Flag if >1% of authors show this (may indicate multiple affiliations or data errors).
- **Year-over-year consistency**: per venue, year-on-year paper count variance. Flag any year that's an outlier (>3σ from the venue's mean).

## Usage

```bash
python3 pipeline/verify.py --all                     # Run all three phases
python3 pipeline/verify.py --phase 1                 # Only harvest integrity
python3 pipeline/verify.py --phase 2                 # Only normalization
python3 pipeline/verify.py --phase 3                 # Only aggregation
python3 pipeline/verify.py --phase 3 --area architecture  # Single area
python3 pipeline/verify.py --area all --report       # Write report to data/reports/
```

## Interpreting results

### Critical (fix immediately)
- Venue-year with 0 papers that should have data (source != "none" but no cache)
- Any verified venue contributing 0 to aggregate (all institutions dropped by normalization)
- Known-strong school showing 0 in an area they should score in (check `data/known-strong.json`)

### High (fix before next aggregate run)
- Venue-year below 70% of expected floor
- Phase 2 resolution rate drop >5% from previous run
- >3 new misattributions found by `fix_campus_clusters.py`

### Medium (investigate)
- Author consistency flags (>1% multi-institution authors)
- Year-over-year outliers (may be legitimate: pandemic year, publishing delay)
- Top-N sanity failures (may reflect real publication shifts, not data errors)

### Low (informational)
- Coverage stats for venues with `status != "verified"`
- Phase 1 stats that are within tolerance bands

## Report format

When running with `--report`, the verifier writes `data/reports/verify-YYYY-MM-DD.md` containing:
1. Summary: green/yellow/red counts per phase
2. Phase 1 table: venue, year, expected, actual, delta%
3. Phase 2 summary: resolution %, type distribution, cluster misattribution count
4. Phase 3 table: zero-count audit failures, top-N display, year-outlier table
5. Recommended actions: ordered list of what to fix first

## Known-strong institutions

`data/known-strong.json` is a curated file mapping area keys to lists of institution IDs that MUST appear with a non-zero score. If any of these show 0, it's a data bug — not a ranking insight. Example:

```json
{
  "architecture": ["I63966007", "I161318765", "I95457486", ...],
  "photonics": ["I63966007", "I161318765", ...],
  ...
}
```

Build this file conservatively: only add schools you're 100% certain publish in that area.
