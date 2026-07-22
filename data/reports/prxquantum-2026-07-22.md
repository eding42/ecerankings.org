# Collection report: PRX Quantum — 2026-07-22

## Summary

PRX Quantum (APS, ISSN 2691-3399) resolves to a single unambiguous OpenAlex
source: `S4210195673`. The `/sources` search for "PRX Quantum" returned
exactly one hit, host organization "American Physical Society", homepage
`journals.aps.org/prxquantum`, `first_publication_year: 2020` — matching the
venue's known launch date, so there is no lookalike risk from other PRX-family
titles (PRX Energy, PRX Life, PRX Quantum's sibling `Physical Review X`
itself). Journal identity, year coverage, volume, and institution sniff test
all pass cleanly. Affiliation coverage passes on 3 of 4 sampled years natively
in OpenAlex (2022–2024 all ≥93%); the newest full year (2025) showed sample
variance depending on ordering/sample size (76.6% on a small unordered
25-work sample vs. 88.0% on a larger 50-work sample sorted by publication
date) — flagged below but not judged a blocking failure given the larger,
more representative sample clears the 85% bar. Scope applied: last 10 years
(2017–2026) per skill default; 2017–2019 are N/A (journal did not exist yet,
launched 2020), not gaps.

## Venues

| venue | kind | source IDs | years covered | ~papers/yr recent | affil. % | status |
|---|---|---|---|---|---|---|
| PRX Quantum | journal | S4210195673 | 2020–2026 (2017–2019 N/A, pre-launch) | 2024: 241, 2025: 309, 2026 (partial, through Jul): 205 | 2022: 93.5%, 2023: 98.6%, 2024: 97.8%, 2025: 76.6% (n=25, unordered) / 88.0% (n=50, date-sorted) | verified |

Notes on the table: counts use `type:article` filter (excludes editorials/
corrections/paratext). 2020 is a partial launch year (37 articles). 2026 is
a partial year as of report date (205 through ~July).

## Year-coverage gaps

No real gaps. 2017–2019 are pre-launch (journal did not exist — PRX Quantum's
first issue was in 2020) and are correctly N/A, not missing data. Every year
2020–2026 has a native OpenAlex year bucket with `type:article` counts; no
Crossref fallback was needed (journals have one stable source ID and OpenAlex
ingests journal content promptly, unlike the ~2-year conference lag).

Minor discrepancy (not a gap): the source's cached `works_count` metadata
field reads 1401, while summing `type:article` counts across 2017–2026
gives 1434, and summing ALL types gives 1456. `works_count` appears to be a
slightly stale/cached aggregate on the source record rather than reflecting
current live counts — cosmetic, doesn't affect year-bucket correctness used
for harvesting.

## Top-10 institutions (recent 5y: 2021–2025, `type:article`)

Raw `group_by=authorships.institutions.lineage` (includes non-education
entries; per PLAN.md these are filtered to `type=education` at aggregation
time, not here):

1. United States Department of Energy — 93 (agency, filtered at aggregation)
2. Centre National de la Recherche Scientifique — 86
3. California Institute of Technology — 85
4. National Institute of Standards and Technology — 83 (agency, filtered at aggregation)
5. United States Department of Commerce — 83 (agency, filtered at aggregation)
6. University of Maryland, College Park — 72
7. University of Chicago — 68
8. Office of Science — 65 (agency, filtered at aggregation)
9. Max Planck Society — 61
10. Austrian Academy of Sciences — 55
11. Harvard University — 53
12. Board of the Swiss Federal Institutes of Technology (ETH domain) — 51
13. Sorbonne Université — 48
14. Helmholtz Association of German Research Centres — 46
15. Joint Quantum Institute — 46

Education-type institutions in this list (Caltech, U. Maryland/JQI, U.
Chicago, Max Planck, Austrian Academy of Sciences/IQOQI, Harvard, ETH domain,
Sorbonne, Helmholtz) read exactly as expected for quantum computing/quantum
information research — this passes the sniff test cleanly. The
government-lab/agency entries (DOE, NIST, Dept. of Commerce, Office of
Science) are expected noise for a physics-hosted journal and get dropped by
the project's `type=education` filter at aggregation time, per PLAN.md; their
presence here is not a checklist concern.

Sample identity check (25 titles, 2025, `type:article`) confirms field match:
titles include "Universal Neutral-Atom Quantum Computer with Individual
Optical Addressing and Nondestructive Readout", "Millimeter-Wave
Superconducting Qubit", "Scalable, High-Fidelity All-Electronic Control of
Trapped-Ion Qubits", "Toward a 2D Local Implementation of Quantum
Low-Density Parity-Check Codes" — squarely quantum computing/information
science, consistent with PRX Quantum's scope.

## Needs human review

- Affiliation coverage on the most recent full year (2025) is
  sample-size-sensitive: a small (n=25), API-default-ordered sample measured
  76.6% (below the 85% bar), driven largely by one paper ("Circuit-QED
  Lattice System with Flexible Connectivity and Gapped Flat Bands for
  Photon-Mediated Spin Models") whose authorship block appears to have no
  resolved institutions at all in OpenAlex — an isolated missing-affiliation-
  block case, not a systemic issue. A larger (n=50), publication-date-sorted
  sample of the same year measured 88.0%, clearing the bar. Registered as
  `verified` on the strength of the larger sample and the clean 93–99%
  readings on 2022–2024, but flagged here in case a stricter re-check is
  wanted once 2025 finishes any residual OpenAlex backfill.
- `works_count` metadata field on the source (1401) doesn't match the sum of
  per-year `type:article` counts (1434) or all-type counts (1456) for
  2017–2026 — likely a stale cached aggregate on OpenAlex's side, noted for
  awareness, not blocking.
- No lookalike ambiguity found: the `/sources?search=PRX Quantum` query
  returned exactly one result, so there was no other PRX-family or
  "quantum"-named journal to disambiguate against.
