---
name: verify-data
description: Verify the data we collect end to end — harvest, authors and bylines, affiliation mappings, dropped credit, aggregates, and the release — with deterministic checks plus seeded random audits against independent judges. Use after any harvest, backfill, normalizer run, adjudication, or aggregation, and before promoting any release.
---

# Verify data

This skill answers one question: **is what reaches the rankings what the publishers printed?** Answering it takes six kinds of check, because each catches failures the others cannot:

| Layer | Finds | Tool |
|---|---|---|
| 1. Rules per stage | Anything somebody already thought of: missing years, thin coverage, counts off | `verify.py` phases 1-3 |
| 2. Credit-ranked global audit | The few problems that move published credit most | `verify.py` phase 4 (`verify_global.py`) |
| 3. Author integrity | Wrong bylines: cut, repeated, group-named, garbled | `verify.py` phase 5 (`verify_authors.py`) |
| 4. Dropped-credit accounting | Credit lost silently, and why | `dropped_credit.py`, reported in phase 4 |
| 5. Seeded random audits | Errors no rule describes, with a measured error rate | `audit_map_sample.py`, `audit_bylines.py`, `check_stale_affiliations.py` |
| 6. Release comparison | What changed in the rankings, and whether it was meant | `compare_aggregates.py`, snapshots |

Layers 1-4 and 6 are deterministic: same inputs, same findings. Layer 5 is sampled, but seeded, so a sample can be replayed. It exists because a rule can only find what its author imagined. The first hand audit of the affiliation map (58 credit-weighted rows, 2026-11-12) found 3 wrong, and one of them, a company named "... Laboratories" credited to San Francisco State University, was invisible to every rule.

## When to run what

| After | Run |
|---|---|
| A harvest or re-harvest | `verify.py --phase 1`, then `--phase 5`; `audit_bylines.py` on the new venue-years |
| `backfill_openalex.py --apply` | `verify.py --phase 1` then `--phase 5`; compare adjusted totals per area against the last release (see "Magnitude" below) |
| A normalizer run | `verify.py --phase 2`, `adjudication.py check` |
| An adjudication `apply` or `replay` | `adjudication.py check`, `verify.py --phase 4` |
| Any change to affiliations or authors | the map audit (below) with a **new seed** |
| `aggregate.py` or `build_release.py` | `verify.py --all --cache-dir <cache> --data-dir <candidate>` |
| Before promotion | everything in the "Gate" checklist at the end |

Never run `aggregate.py` straight into `site/data`; the refresh runbook (`docs/refresh-runbook.md`) owns promotion.

## Which checker for which question

| Question | Command |
|---|---|
| Is the corpus or aggregate internally sound? | `python3 pipeline/verify.py --all` |
| Is a *staged* refresh sound? | `python3 pipeline/verify.py --all --cache-dir <staged cache> --data-dir <candidate data>` |
| What would a reader of the site see that is wrong? | `python3 pipeline/verify.py --phase 4` (short list, ranked by credit) |
| Are bylines right? | `python3 pipeline/verify.py --phase 5`, then `python3 pipeline/audit_bylines.py` |
| Where does dropped credit go, and why? | `python3 pipeline/dropped_credit.py` |
| Is the affiliation map trustworthy, and how wrong is it? | `adjudication.py check` (rules), `audit_map_sample.py` (measured rate) |
| Are cached affiliations stale? | `python3 pipeline/check_stale_affiliations.py` (network) measures; `refresh_openalex_affiliations.py --apply` repairs OpenAlex-native works |
| Did an ML edition meet its gates? | `python3 pipeline/harvest_ml.py --venue <v> --year <y> --stage gates` |
| Would rankings change, and why? | `python3 pipeline/compare_aggregates.py` |

Run `verify.py` read-only by default.
- `--update-snapshots` accepts the current state as the new regression baseline, and refuses unless the run is clean.
- Only pass it after the findings have been reviewed, never to make red go away.
- `--report` writes `data/reports/verify-YYYY-MM-DD.md`.

## What each phase checks

**Phase 1: harvest** (`cache/*/*/works.jsonl`)
- zero-work venues (critical); missing registered years; counts versus `expected_per_year`;
- author completeness; per-venue-year affiliation coverage and regression versus snapshot;
- duplicate IDs and titles; solo-author share; titles that look non-research but are still credited.

**Phase 2: normalization** (`data/affiliation-map.csv`)
- resolution rate and type mix; one institution ID with conflicting countries; geo-heuristic mismatches;
- compound strings; acronym and campus checks; ambiguous lineage; per-area affiliation gap; purity and resolution scorecards.

**Phase 3: aggregate** (`site/data`)
- `known-strong` zero audit; venues contributing zero credit; under-collected areas;
- top-50 ranking regression; top-5 per area; authors at several institutions in one area-year; year-over-year outliers; institution cliff drops.

**Phase 4: global audit.** Read this first; its critical and high lines print above the others. Each line is one venue or institution, ranked by credit.
- `[map/country]`: a raw string naming one country, mapped to an institution in another (Southeast University, Nanjing, credited to Southeast University in Bangladesh);
- `[map/company]`: a company string credited to a university through a city name;
- a default-window venue with no papers for a year; a venue-year whose credited share collapses against the venue's own median; a paper count far off its neighbours; single-author items carrying large credit; front matter with authors; years only a few venues cover;
- reference lists that cannot fail (`known-strong` IDs found nowhere, a missing or empty trap file);
- `[drop/retyped]`, `[drop/untyped]`: institutions whose credit is dropped because a map row is typed as a non-credit type, or OpenAlex gave no type, while the index says education (UC Riverside stored as "other");
- `[drop/no-affiliation]`, `[drop/stale]`: venues where most authors carry no affiliation anywhere, and works nothing ever retried.

**Phase 5: author integrity.**
- `[authors/truncated]`: works with exactly 100 authors against few just below. OpenAlex caps list responses at 100 authorships, so a 400-author paper splits credit 100 ways and the other 300 authors get none;
- `[authors/none]`: a venue-year whose author-less share jumps far above the venue's own norm. Author-less works in general are front matter and correctly credit nothing, so only a spike is a finding;
- `[authors/duplicate]`: the same author twice in one byline, so the paper's credit is split one share too many;
- `[authors/group]`: collaboration or team names filed as authors, whose share no university can receive;
- `[authors/garbled]`: replacement characters, mojibake, HTML entities. Synthetic author IDs come from names, so one person becomes several;
- `[authors/spread]`: authors with five or more institutions on one paper, meaning an affiliation list was attached to every author.

## Random audits

Sampling is seeded, so a sample is replayable, and judged blind, so the judge cannot agree with the current answer by copying it.

### Affiliation map: how often is it wrong?

```bash
python3 pipeline/audit_map_sample.py draw --seed <new seed> --size 300
# judge every .tmp/map-audit/seed-<seed>/blind-batch-*.json (see "Judging"), save decisions-NN.json beside them
python3 pipeline/audit_map_sample.py score --seed <seed>
```

The sample is stratified: **credit** (drawn in proportion to the credit a string carries; this stratum alone estimates misassigned credits), **short** strings, **manual** rows, rows with **no academic evidence**, rows **not credited** (the false-negative direction), and **unmatched** rows. Each stratum is reported separately because a rare failure shows up in a risky stratum long before it moves the overall rate.

`score` writes `data/reports/map-audit-<date>-seed<seed>.md` and `disagreements.json` in adjudication format. It applies nothing.

- The report gives the credit-weighted error rate with a 95% interval and the credits it implies. Above 3% the run exits 2 and the map is not promotable.
- Review `disagreements.json` with the `adjudicate-affiliations` skill, `apply --dry-run` it, then apply. A disagreement is a lead: the judge can be wrong too.
- Every confirmed error gets either a trap row in `data/adjudication-traps.csv` or a new rule, so the same class is caught without sampling next time.
- **Use a fresh seed after fixing.** Re-scoring the sample you just repaired measures nothing.

**Judging.** A cheaper model is enough. Give it one blind batch (key and `raw_affiliation` only), tell it to use `python3 pipeline/adjudication.py search "<name>"` against the local index, and have it return JSON only:

```json
[{"key": "...", "decision": "education", "institution_id": "I...", "evidence": "...", "decided_by": "<model>"}]
```

`decision` is `education` (with the institution), `noneducation` (a company, hospital, or government lab), or `unresolved` (the string cannot identify one institution). The judge must not see the map's answer, the stratum, or other batches. Send disagreements the judge and the map cannot settle to a stronger model or to the user.

### Bylines: are authors in the right places?

```bash
python3 pipeline/audit_bylines.py --seed <seed> --size 200
```

Compares a random sample of cached bylines with Crossref's publisher-deposited author list, position by position. Outcomes: `exact`, `reordered` (positions wrong), `names_differ` (a name wrong or cut), `cache_short` (list cut or authors lost), `cache_long`, `different`. Exits 2 when more than 5% mismatch. Crossref itself has quirks (an author's family name given as a single letter), so read the examples before acting. Sends only DOIs.

### Stale affiliations

```bash
python3 pipeline/check_stale_affiliations.py
```

`backfill_openalex.py` revisits only Crossref and S2 works, so an OpenAlex-native work keeps whatever affiliations OpenAlex had the day it was harvested. This samples works whose every author lacks an affiliation and asks OpenAlex what it has now. On 2026-11-12, 48% had gained affiliation text (88% for 2005). It measures; it never writes the cache. Reads `OPENALEX_API_KEY` from `.env`; sends no contact email.

To repair, run `python3 pipeline/refresh_openalex_affiliations.py --pilot 200`, then `--apply`. It re-fetches those works by OpenAlex id and writes them back only when the author list matches position by position (same length, same names; "Family Given" names count as the same), so an affiliation is never attached to a different person. Afterwards normalize the new raw strings, adjudicate, and re-verify.

**The backfill's negative list goes stale.** `cache/.backfill-negative.txt` records DOIs OpenAlex once had nothing for, and `backfill_openalex.py` never asks again. On 2026-11-12, 42 of 50 sampled CLEO 2025 DOIs on that list were in OpenAlex with affiliations, which was why CLEO 2025 credit was 8% against a 78% median. After a new year's proceedings land, or whenever a venue-year's coverage looks collapsed, probe a sample of its negatives and clear the file if most have appeared.

## How to read a run

1. **Compare against the previous run, not against zero.** A healthy corpus still has hundreds of open findings, because known external gaps are flagged on every run by design (see "Always-flag"). What matters: new or changed findings, regressions versus the snapshot, and any critical finding.
2. **Check magnitude, not just order.** A run that writes correct data which `aggregate.py` then discards looks healthy. On 2026-07-25 a backfill wrote 49,554 works whose institutions lacked `type`, aggregation silently dropped them, and `verify.py` returned a byte-identical finding set. So compare adjusted-count totals per area against the last release, use low-gap areas (`comms`, `inftheory`) as a control that should barely move, and read `dropped_credit.py` for the reasons credit is lost.
3. **Treat tripwires as data bugs until proven otherwise.** A `known-strong.json` institution at zero is a bug, not a ranking insight. The list only asserts non-zero; it cannot detect under-collection.
4. **A drop is not always a bug.** 5% of default-on credit goes to company and hospital authors, correctly. `[drop/retyped]` and `[drop/untyped]` are bugs; `openalex_noncredit` is a judgement call; `no_affiliation` is a collection question.
5. **Do not trust a rule you have not tried to beat.** When a random audit finds an error no rule flagged, fixing the row is half the job. The other half is the rule.

## Severity

- **Critical, fix now:** a registered venue or venue-year with no data; a verified venue with zero credit; a `known-strong` institution at zero; a coverage, purity, or resolution regression of 50 points or more; an `adjudication.py check` trap failure or no traps loaded; 25 or more credits mapped across a country or to a company string; a venue-year under 40% of its venue's credited-share median; 50 or more works cut at the author cap; 25 or more credits lost to duplicate or group-name authors; 25 or more credits dropped to a retyped row.
- **High, before the next aggregate:** a venue-year below 70% of its expected floor; coverage under 50%, purity under 30%, or resolution under 50%; a regression of 10-50 points; country conflicts; geo violations; 10 or more works cut at the author cap; an author-less spike; 20 or more garbled names in a venue; a venue with 25% or more of its credit unaffiliated.
- **Medium, investigate:** threshold bands below those; outliers; ranking moves of 10 or more positions; compound strings; the stale-works and affiliation-spread lines.
- **Low:** informational and within tolerance, including the `[drop/summary]` and `[authors/summary]` lines.

## Always-flag

Coverage, purity, resolution, and lineage findings are never suppressed for "known, unfixable" gaps such as pre-2021 IEEE Crossref metadata. This is an explicit project decision: suppression would let a new regression hide inside accepted red. Expect long output. The signal is the diff and the regressions, not the length.

## Known blind spots

- OpenAlex-resolved works keep no raw string in the cache, so the `[map/...]` checks cannot see a wrong resolution on that path. Only the random audits and the byline audit reach it indirectly.
- Author-list truncation is detected as a spike at exactly 100. Whether the cache stored OpenAlex's `is_authors_truncated` flag, and whether a single-work fetch returns the full list, is unconfirmed; check before building a repair.
- The `known-strong` list and the geo-name list are curated and can be stale. A finding against them is a lead, not proof.
- `harvest_ml.py`'s `audit-sample.jsonl` (100 papers per edition, chosen by a stable hash) is for human reading and certifies nothing.

## Gate before promotion

All of these, on the candidate, in this order:

1. `verify.py --all --cache-dir <candidate cache> --data-dir <candidate data>`: no unexplained critical or high.
2. `adjudication.py check`: every trap passes.
3. `audit_map_sample.py` with a fresh seed: credit-weighted error rate within 3%.
4. `audit_bylines.py`: mismatched bylines within 5%.
5. `compare_aggregates.py` against the live release: every credit change explained.
6. Coverage has not dropped more than five points; no `known-strong` institution at zero; default-on top-20 membership has not changed by more than 10% without a documented cause.

Then follow the `refresh-data` skill. Do not edit `known-strong.json`, methodology, area defaults, or any threshold to clear a failure. Never advance snapshots to hide findings.

## After fixing

1. Rerun the specific phase.
2. Run `python3 pipeline/split.py` after any aggregate change.
3. Write a short report: what was flagged, what was fixed, what was accepted and why, and the before and after totals for affected areas.

## Hard rules

- Validation is read-only. Fixes happen in the owning tool, then you re-verify: harvest or backfill; `adjudication.py apply`; the `fix_*` scripts with `--apply` after review.
- A Phase 4 `[map/...]` finding is repaired with the `adjudicate-affiliations` skill (`fix_country_mismatches.py` writes proposals, `adjudication.py apply` records them), and the fixed string is added to `data/adjudication-traps.csv`.
- Never edit `known-strong.json` to make a check pass. Add institutions only when they are certain to publish in that area, as a separate reviewed change.
- Never pass `--update-snapshots` on a run with unexplained critical or high findings.
- Never show a judge the map's answer, the stratum, or a previous verdict.
- An intentional gap in a venue's years is recorded in `data/areas.json` as `"source": "none"` with a note, never by raising a threshold.
