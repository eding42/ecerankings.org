---
name: verify-data
description: Run data-quality checks after harvesting, normalization, or aggregation — catch pipeline bugs, data corruption, and affiliation mismatches before they reach the rankings.
---

# Verify Data

Run multi-layer quality checks against the pipeline output. Use after (a) harvesting a new venue or re-harvesting a year, (b) running `backfill_openalex.py --apply`, (c) re-running the normalizer, or (d) running aggregate — any change that could have introduced or propagated errors.

**Known blind spots — this script will not catch these, so check them by hand:**
- **Under-collected areas.** The `known-strong` tripwire only asserts non-zero. In July 2026 the `ml` area passed cleanly while NeurIPS and ICLR had *zero* works harvested and ICML was 92% missing affiliations, because Stanford/MIT/CMU/Berkeley/UCLA were all non-zero. Assert zero-work venues and per-area missing-affiliation rates yourself.
- **Silently dropped credit.** A run that writes correct data which `aggregate.py` then discards looks identical to a healthy run. Always compare the *magnitude* of adjusted counts against the previous run, not just orderings — and use low-gap areas (`comms`, `inftheory`) as a control group, since they should barely move when a backfill or normalization lands.

## Architecture & layers

The verifier runs in three phases, ordered from cheapest (works-level stats) to most expensive (ranking cross-validation). Each phase can run independently; all phases run with `--all`.

### Phase 1: Harvest integrity (works.jsonl)
- **Venue coverage**: papers per venue-year vs `expected_per_year` in `areas.json`. Flag any venue-year >30% below the floor.
- **Year coverage**: every `years{}` entry with `source != "none"` has a `works.jsonl`. Flag missing years.
- **Author completeness**: % of works with zero authors. Should be ~0%.
- **Coverage scorecard**: % of authorships with ANY affiliation signal — native `institutions[]` OR non-empty `raw_affiliations` (previously this check only looked at `raw_affiliations`, which falsely flagged every OpenAlex-native venue-year as 0% covered; fixed 2026-07-23). Computed per venue-year via a single shared scan (`compute_quality_scan`), reused by Phase 2. **Every venue-year below threshold is flagged on every run** — including known-permanent external gaps (e.g. pre-2021 IEEE Crossref metadata simply doesn't exist at the source, confirmed live against Crossref's API) — by explicit project decision, nothing is silently suppressed just because it's a known, currently-unfixable issue.
- **Coverage regression**: compares this run's per-venue-year coverage % against the previous run's snapshot (`site/data/.coverage-snapshot.json`). **Any drop at all is flagged** (not just large ones), scaled by severity: ≥50pp drop → critical, ≥10pp → high, smaller → medium. This is what catches a venue silently losing a working data source — e.g. CLEO going from ~97% (2016–22, OpenAlex-native) to 0% (2023–25, after OpenAlex stopped indexing it and the Crossref fallback carries no affiliation strings at all). First run establishes the baseline with no regression flags.
- **Duplicate check**: paper IDs should be unique within a venue-year. Flag exact-title duplicates.

### Phase 2: Normalization integrity (affiliation-map.csv + cross-reference)
- **Resolution rate**: % of distinct `raw_affiliation` strings with `status=auto` or `manual` and `institution_type=education`. Target: >65%.
- **Institution type distribution**: count of education / company / government / facility / other. Flag if education <50%.
- **Country code consistency**: For each `institution_id`, check ALL rows have the same `country_code`. A single institution mapped to both US and CN is a data bug (e.g., compound affiliation "Alibaba and UCSD" picking Alibaba's country). Flags any inconsistencies.
- **Geo-heuristic validation**: Known institution names are checked against expected countries (e.g., "University of California" → US, "Tsinghua" → CN, "TU Munich" → DE). Flag any mismatch.
- **Compound affiliation detection**: Rows where `raw_affiliation` contains "and", "&", or "/" and whose institution_id has conflicting country codes are flagged — these are likely misattributions from compound strings.
- **Acronym validation**: Re-run the acronym check from adjudication skill step 5. Flag any short matched_via strings that aren't official acronyms.
- **Campus cluster check**: Re-run `pipeline/fix_campus_clusters.py` and flag any new misattributions.
- **Ambiguous/nested institution lineage** (added 2026-07-23): flags institutions whose OpenAlex `lineage` has more than one element, meaning there's no reliable way to identify the true parent/root institution (see `aggregate.py`'s docstring — a wrong guess would silently misattribute a paper). `aggregate.py`'s own comment assumed ~5% of institutions hit this, based on a 133-institution IEDM-2022 pilot; the full-corpus rate is actually **~25% of distinct institutions** (verified 2026-07-23, ~24% of native-resolved authorship occurrences) — the pilot wasn't representative. Top offenders are typically legitimate multi-level organizations: national academy sub-institutes (e.g. University of Chinese Academy of Sciences), national labs (SLAC, LBNL), and hospital/medical-school systems (Mass General, Brigham and Women's). Reported with occurrence counts; always flagged (not currently auto-fixable — needs a real lineage-root-resolution algorithm, tracked as a known open gap, not attempted here).
- **Purity scorecard**: for venue-years that DO produce native OpenAlex institutions, % of authorships that are "perfect" — native-resolved, single-element (unambiguous) lineage, with both `country_code` and `type` present. For venue-years that are structurally raw-text-only (Crossref/Semantic-Scholar-sourced, `institutions[]` always empty by design), purity doesn't apply — instead their **resolution rate** (raw-affiliation strings that map to a real education institution) is the equivalent quality signal. Both are always flagged at absolute thresholds, and both regress-check against the snapshot (any drop flagged, same severity scale as coverage).

### Phase 3: Aggregate integrity (inst-area-year.csv)
- **Zero-count audit**: Per area, schools with known strength that show `adjusted_count = 0`. Reference: `data/known-strong.json` (maintained for all 19 default-on areas). Flag every discrepancy.
- **Venue-area contribution**: Each venue key should have at least 1 credited institution. If a venue contributes zero (all institutions dropped), flag — this indicates a normalization gap.
- **Ranking regression**: Compares the current top-50 institutions against a snapshot from the previous run. Flags institutions that moved ≥10 positions, new entries, and institutions that dropped out. Snapshot saved to `site/data/.ranking-snapshot.json`.
- **Top-N sanity**: For each area's top 5 schools, print the adjusted count. Human-visible check (no automated flag — needs domain knowledge).
- **Author cross-validation**: Same `author_id` appearing at different institutions in the same area+year. Flag if >1% of authors show this (may indicate multiple affiliations or data errors).
- **Year-over-year consistency**: Per venue, year-on-year paper count variance. Flag any year that's an outlier (>3σ from the venue's mean).
- **Institution cliff-drop detection**: Flags institutions with established presence where a single year drops >80% from the prior year.

After verifying and fixing, re-run `split.py` to regenerate per-area JSONs:
```bash
python3 pipeline/split.py
```

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
- Coverage/purity/resolution regression ≥50pp vs. the last snapshot — this is the "something that used to work just broke" signal (e.g. a source silently switching from OpenAlex-native to affiliation-free Crossref, like CLEO 2023). Treat exactly like a known-strong-school-hit-zero bug: don't assume it's a permanent gap without checking whether it's new.

### High (fix before next aggregate run)
- Venue-year below 70% of expected floor
- Venue-year coverage <50%, purity <30%, or resolution <50% (absolute thresholds — flagged every run, including known-permanent gaps, by design; see "Always-flag philosophy" below)
- Coverage/purity/resolution regression 10–50pp vs. the last snapshot
- Phase 2 resolution rate drop >5% from previous run
- Country code conflicts for the same institution ID
- Geo-heuristic violations (e.g., UC campus with country=CN)
- >3 new misattributions found by `fix_campus_clusters.py`
- Ambiguous-lineage rate ≥20% of native-resolved authorships

### Medium (investigate)
- Venue-year coverage 50–80%, purity 30–60%, or resolution 50–80%
- Coverage/purity/resolution regression <10pp vs. the last snapshot (still real — any drop is flagged, per project decision — just less urgent)
- Author consistency flags (>1% multi-institution authors)
- Year-over-year outliers (may be legitimate: pandemic year, publishing delay)
- Ranking regression with ≥10 position moves
- Compound affiliation flags (may require manual split into separate rows)
- Top-N sanity failures (may reflect real publication shifts, not data errors)
- Ambiguous-lineage rate 10–20%

### Low (informational)
- Coverage stats for venues with `status != "verified"`
- Phase 1 stats that are within tolerance bands
- New entries or drops from top 50 (expected on first run)
- Individual ambiguous-lineage institutions (top 10, listed for visibility once the aggregate rate is already flagged above)

## Always-flag philosophy (coverage / purity / resolution / lineage)

Unlike most other checks in this file, the coverage/purity/resolution/lineage scorecard does **not** suppress known, currently-unfixable issues (e.g. pre-2021 IEEE Crossref metadata gaps, verified as a real external limitation, not a pipeline bug). Every venue-year is flagged against absolute thresholds on every single run, by explicit project decision — the alternative (suppressing "already known" gaps) risks a regression hiding inside a pile of accepted red. Regressions (any drop vs. the last snapshot) are flagged separately and more urgently than static absolute-threshold flags, since those mean something that used to work has broken. Expect Phase 1/2 output to be long — that volume is intentional, not a bug in the checker.

## Data quality snapshot (`site/data/.coverage-snapshot.json`)

Written after every `--phase 1`, `--phase 2`, or `--all` run (shared by both phases, computed once via `compute_quality_scan` to avoid rescanning `cache/` twice). Stores per-venue-year `coverage_pct`, `purity_pct` (native-capable venues only), and `resolution_pct` (raw-only venues only), plus a `global` rollup. The *next* run diffs against this file before overwriting it — this is what powers regression detection. Like `site/data/.ranking-snapshot.json`, this file is local pipeline state, not curated data; it's fine for it to just get overwritten each run.

## Report format

When running with `--report`, the verifier writes `data/reports/verify-YYYY-MM-DD.md` containing:
1. **Data Quality Scorecard**: top-line global coverage %, purity %, resolution % (new, always first)
2. Phase 1: venue-year table (missing years, paper counts vs. floor, author completeness, coverage, coverage regressions)
3. Phase 2: resolution %, type distribution, country conflicts, geo violations, compound flags, ambiguous-lineage top offenders, purity/resolution scorecard and regressions
4. Phase 3: zero-count audit failures, ranking regression, top-N display, year-outlier table
5. Recommended actions: ordered list of what to fix first (read top-down by severity — critical/high first)

## Known-strong institutions

`data/known-strong.json` is a curated file mapping area keys to lists of institution IDs that MUST appear with a non-zero score. If any of these show 0, it's a data bug — not a ranking insight. Currently covers all 19 default-on areas with 5–6 top institutions each.

Build this file conservatively: only add schools you're 100% certain publish in that area.
