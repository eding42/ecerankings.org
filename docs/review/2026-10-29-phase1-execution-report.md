# Phase 1 execution report: recent-year completeness (2026-10-29)

Responds to [the completeness audit](2026-10-29-recent-completeness-audit.md). Scope: integrate staged and held 2026 editions into `cache/`, repair 2026 affiliation holes, filter non-main-track noise. **Nothing was aggregated, split, verified, committed, or published.** `site/data/` is unchanged.

## Summary

| Item | Result |
|---|---|
| DAC 2026 | 310 staged records integrated into `cache/dac/2026/works.jsonl`. **Still partial**: official accepted research IDs number 544. |
| CVPR 2026 | **Not ingested.** No 2026 main-track DOI inventory is reachable (see below). |
| ECCE 2026 | **Not ingested.** No 2026 proceedings DOIs in Crossref or OpenAlex. |
| EMSOFT 2026 | **Ownership preserved, no set added.** ESWEEK integrates full papers into TCAD; no duplicate EMSOFT set created. |
| CLEO 2023–2026 | OpenAlex DOI backfill applied to 2,866 works. 2026 slot affiliation signal 0% → 98.3%. |
| Optica 2023–2026 | Crossref raw-affiliation fill into empty slots. 2026 41.0% → 51.6%. Residual gap is upstream. |
| Noise filter | 70 poster/demo/front-matter works added to `data/excluded-works.csv` (563 rows total). |
| Unit tests | `python3 -m unittest discover tests/`: **74 pass** (64 existing + 10 new). |

## 1. DAC 2026 (staged → cache)

- Source: `.tmp/refresh-2026-10-29/dac/2026/works.jsonl`, verified against `data/refresh/dac-2026-staged-2026-10-29.json`. SHA-256 `f37c3833…9328e3` matches. 310 rows, 310 unique DOIs (all `10.1145/3770743.*`), 1,906 authors, schema identical to `cache/dac/2025`.
- Written to `cache/dac/2026/works.jsonl` (byte-identical copy). No OpenAlex calls.
- **Reconciliation gap.** The official [DAC 2026 accepted research paper IDs page](https://dac.com/2026/accepted-paper-ids) lists **544** unique numeric IDs (range 4–3214). The staged set has 310 DOIs. That leaves a gap of up to 234, unless some IDs are not DOI-bearing papers. Matching requires an ID→title program mapping, which I did not build. **Do not publish DAC 2026 as complete.**
- Affiliation status of the staged set: 1,170 of 1,906 slots (61.4%) resolve through `affiliation-map.csv`; 736 (38.6%) are raw strings with no curated mapping.

## 2. CVPR 2026, ECCE 2026, EMSOFT 2026

**CVPR 2026: not ingested.**
- Crossref exact-container query for the main proceedings title returns 0 records for 2026. The only 2026 CVPR records are the Findings track (`10.1109/cvprf…`), which the registry excludes.
- OpenAlex source `S4363607701` returns 0 works for 2026.
- The CVF archive page (`openaccess.thecvf.com/CVPR2026`) returned a 3.8 KB shell with no paper listing.
- Even if a listing were reachable, CVF open-access entries carry no DOIs and no affiliations. Ingesting them would create rows that cannot earn institution credit. Defer until a DOI or proceedings source exists.

**ECCE 2026: not ingested.**
- Crossref exact-container queries for `2026 IEEE Energy Conversion Congress and Exposition (ECCE)` and the 2025-style `Conference Congress` variant both return 0.
- OpenAlex source `S4363604350` returns 0 works for 2026.
- `ieee-ecce.org/2026/` returns HTTP 403 to this environment.
- `powerelec` stays without a 2026 edition. The audit's P0 item remains open.

**EMSOFT 2026: ownership respected, no set added.**
- The ESWEEK/EMSOFT page confirms a "Journal Track: Full Paper Submission", consistent with the registry's TCAD-integrated model.
- Adding a separate EMSOFT 2026 set would double-credit papers already in TCAD (OpenAlex: 431 TCAD works for 2026). I left TCAD and TECS untouched.
- Still open: no official accepted-paper ID list has been reconciled to TCAD 2026, so EMSOFT-specific credit cannot be assigned yet.
- The registry's `exclude_dois` filter for TECS 2017/2019 (the EMSOFT overlap) is still not wired into `harvest.py`. That is outside this phase.

## 3. CLEO and Optica affiliation coverage

Measured as the share of author slots with any affiliation signal (OpenAlex institution or raw string). Before values come from the cache where I measured them directly; 2023–2024 "before" values are the audit's source-manifest figures.

**CLEO** (`pipeline/backfill_openalex.py --apply --venue cleo`, DOI lookup, only works with no OpenAlex id and no affiliations):

| Year | Before | After | After, OpenAlex-resolved institutions |
|---|---:|---:|---:|
| 2023 | 45.1% (audit) | 100.0% | 97.8% |
| 2024 | 43.9% (audit) | 99.8% | 97.8% |
| 2025 | 9.7% | 75.4% | 73.1% |
| **2026** | **0.0%** | **98.3%** | **94.5%** |

Pilot: 88.3% of 300 sampled DOIs resolved; 84.4% of sampled slots recovered. Full run: 2,866 works rewritten across 4 files, 66 batch requests. 393 DOIs are negative-cached in `cache/.backfill-negative.txt`.

**Optica** (`pipeline/backfill_crossref_affiliations.py`, new). Optica works are OpenAlex-native, so the OpenAlex backfill skips them. The new script fills only **empty** slots from Crossref raw affiliations, never overwriting OpenAlex institutions. It requires equal author counts and a family-name token match per filled slot, and skips the whole work on any mismatch.

| Year | Before | After | Slots filled | Notes |
|---|---:|---:|---:|---|
| 2023 | 55.4% | 55.4% | 0 | 119 works had no Crossref affiliations |
| 2024 | 55.1% | 56.1% | 20 | |
| 2025 | 55.4% | 60.6% | 111 | |
| **2026** | **41.0%** | **51.6%** | **228** | 6 works skipped on name mismatch |

- Residual 2026 gap is upstream. Of 1,037 empty slots after fill, Crossref has an affiliation for only 21. OpenAlex's fresh re-query gave no material change (41.0% → 42.8%).
- The Crossref-filled strings are raw text. Aggregation credits them only through `affiliation-map.csv`. Of 204 unique filled strings, 127 map (auto/manual) and 77 need adjudication (for example "Optics Valley Laboratory", "RIKEN SPring-8 Center").

**Caveat for CLEO and Optica.** Institutions from OpenAlex enter aggregation directly and **bypass the curated affiliation map** (`aggregate.py` checks the map only when `institutions` is empty). These works carry OpenAlex's own resolution errors. Run `verify.py` top-institution checks before any release.

## 4. Other 2026 additions

These already carry 95–100% raw-affiliation signal from Crossref, so the OpenAlex backfill correctly skips them. Their gap is institution normalization:

| Edition (2026) | Slots | Map-resolved | Raw, unmapped | No affiliation |
|---|---:|---:|---:|---:|
| ISSCC | 2,526 | 75.9% | 22.1% | 2.0% |
| ISCA | 1,331 | 78.1% | 17.6% | 4.4% |
| ISIT | 1,783 | 83.7% | 15.4% | 0.9% |
| ICRA | 9,973 | 79.4% | 19.8% | 0.8% |
| VLSI-Circuits | 3,123 | 55.3% | **44.7%** | 0.0% |
| INFOCOM | 3,030 | 94.6% | 4.9% | 0.5% |
| SIGCOMM (after filter below) | 1,457 | 70.8% | 29.2% | 0.0% |
| DAC (staged) | 1,906 | 61.4% | 38.6% | 0.0% |

"Map-resolved" approximates aggregate credit: a raw string maps to an auto/manual institution. It does not check education-type filtering. The unmapped strings need `adjudicate-affiliations`.

## 5. Non-main-track filter

Rule: title begins with `POSTER:`, `DEMO:`, `Poster:`, or `Demo:` (case-sensitive, colon required), or is a workshop program front-matter title. Rows keyed by `doi:` via `workkey.work_key`. Added to `data/excluded-works.csv` with `decided_by = phase1-title-prefix-rule`.

| Edition | Excluded | Remaining |
|---|---:|---:|
| SIGCOMM 2023 | 36 | 71 |
| SIGCOMM 2026 | 20 | 180 |
| INFOCOM 2026 | 11 | 602 |
| RTAS 2023 / 2024 | 1 / 1 | — |
| VLSI-Circuits 2025 ("Special Workshop Program") | 1 | — |

- The SIGCOMM 2023 remainder (71) matches the audit's ~71 main-paper estimate.
- Initial matching caught `DeMo:` (NeurIPS 2024, a method name). Case-sensitive matching excludes it.
- **Not handled:** SIGCOMM 2025 has no title markers. The audit's ~14 bundled poster/demo items there need another signal, such as the program's category list.
- These rows are rule-derived, not individually reviewed. Please confirm before the next aggregate.

## 6. Tooling changes

- `pipeline/backfill_crossref_affiliations.py`: new. Measure-only by default; `--apply` writes. Stdlib only.
- `tests/test_backfill_crossref_affiliations.py`: new, 10 tests covering name alignment, count mismatch, and empty-slot-only fills.
- `data/excluded-works.csv`: +70 rows.
- `cache/dac/2026/works.jsonl`: new. `cache/cleo/*`, `cache/optica/202{3,4,5,6}/works.jsonl`: rewritten.
- `cache/.backfill-negative.txt`: created by the OpenAlex backfill. It is **not gitignored**. Decide whether to track or ignore it before committing.

## 7. OpenAlex and Crossref usage

- OpenAlex: about 85 list requests (CLEO backfill 72, source-count probes 6, Optica fresh-fetch check 5). The key was read from `.env` and not printed.
- Crossref: about 1,100 unauthenticated requests (622 in the Optica apply run, about 500 in earlier per-DOI checks, plus exact-container probes). Polite `mailto` and 0.15 s spacing used.

## Open items and decisions for you

1. **DAC 2026 is in `cache/` but incomplete (310 of 544 official IDs).** The next `aggregate.py --all-cached` will count it. Decide whether to exclude the edition from aggregation until it is reconciled, or accept partial 2026 counts.
2. **Confirm the 70 title-rule exclusions**, especially the 1 VLSI-Circuits front-matter row and the RTAS demo rows.
3. **CLEO/Optica OpenAlex institutions bypass the affiliation map.** Run `verify.py` top-institution checks before release.
4. **Adjudication queue:** 77 Optica strings plus the unmapped strings in section 4 (VLSI-Circuits 44.7% is the largest).
5. **CVPR 2026, ECCE 2026**: need a DOI-bearing proceedings source. Options include a later Crossref deposit, IEEE Xplore access, or an accepted-ID list with a title-level match. Not resolvable from the current environment.
6. **EMSOFT 2026**: needs an official accepted-paper list matched to TCAD 2026 to assign ownership; then wire the TECS `exclude_dois` filter.
7. **SIGCOMM 2025 bundled posters/demos**: no title marker, so not yet filtered.
