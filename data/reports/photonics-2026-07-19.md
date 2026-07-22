# Collection report: photonics — 2026-07-19

## Summary

This supersedes an earlier same-day pass (Crossref-only, done while the
OpenAlex API budget was exhausted). This run completes the OpenAlex
verification that pass left pending: an orchestrated collection for the
`photonics` area (3 venues: `jlt`, `optica`, `cleo`), each run by a dedicated
Sonnet worker in parallel, scoped to the default 10-year window (2016–2025).
One venue (`jlt`) graduated to `verified`; two (`optica`, `cleo`) stay
`candidate` — `optica` on a genuine affiliation-coverage failure, `cleo`
because its 3 most recent years are Crossref-only and haven't gone through
the not-yet-run Phase 1b harvest. No lookalike-trap venues were admitted;
all rejections are logged per-venue below.

## Venues

| venue | kind | source IDs | years covered | ~papers/yr recent | affil. % | status |
|---|---|---|---|---|---|---|
| jlt | journal | S2307745 | 2016–2025 (native OpenAlex, cross-checked vs. existing Crossref years) | 816–1356 | 93.8% | verified |
| optica | journal | S4210197940 | 2016–2025 (native OpenAlex 2014–2026, no gaps) | 193–275 | ~51% | candidate |
| cleo | conference | S4306418073 | 2016–2022 native OpenAlex; 2023–2025 Crossref-confirmed | 1553–2710 | 86.4–99.5% | candidate |

## Year-coverage gaps

- **jlt**: no gaps in-window. OpenAlex counts for 2024/2025 run 3–21% below
  the existing Crossref-sourced `years{}` counts for the same years — likely
  OpenAlex ingestion lag on the newest year, not a wrong-source signal.
- **optica**: no gaps in-window; native OpenAlex tracks Crossref within
  single digits every year.
- **cleo**: 2023–2025 absent from OpenAlex. This is *not* the usual ~2-year
  ingestion lag seen on IEDM/ISSCC/DAC — the works exist in OpenAlex with
  `raw_source_name` literally `"CLEO 2023"`/`"2024"`/`"2025"` but
  `primary_location.source` is null (an unlinked-source gap, a distinct
  failure mode worth tracking separately). Confirmed present in Crossref by
  DOI-prefix (`10.1364/cleo_`) + container-title match: 1704 (2023), 1907
  (2024), 1553 (2025).

## Top-10 institutions (recent 5y, per venue)

- **jlt**: CAS, BUPT, HUST, Fudan, SJTU, Zhejiang, Tsinghua, NTT Japan —
  consistent with the earlier pass's list (Nokia Bell Labs, Stanford, UCL,
  Chalmers, Hokkaido, Univ. of Ottawa, CityU HK, DTU, Eindhoven, SJTU, CAS);
  all expected photonics/optical-comms leaders, no anomalies.
- **optica**: CAS, DOE, CNRS, Stanford, Office of Science, Max Planck, ETH
  domain, USTC, Helmholtz, NIST — matches a top-tier general photonics
  journal (earlier pass: NIST/UC Colorado, UCSB, Stanford, MIT, ETH Zurich,
  Caltech, CAS, Paris-Saclay/CNRS — same tier of institutions).
- **cleo**: not separately itemized in this run's worker report beyond
  passing the sniff test; earlier pass listed MIT, Stanford, Harvard,
  Caltech, UCSB, Columbia, U. Rochester, SJTU, HUST, Fudan — plausible for
  this venue, treat as unconfirmed by this pass.

## Needs human review

- **optica affiliation coverage (51%, well below the 85% bar)**: not a
  matching-script problem — many unresolved authorships have *empty*
  `raw_affiliation_strings` too (whole affiliation blocks missing from
  OpenAlex's record, e.g. an entire DTU author group on one paper). This is
  a structural OpenAlex data gap specific to this venue. A future session
  should check whether Crossref's affiliation strings are more complete for
  `optica`; if so, prefer `harvest_crossref.py` over native OpenAlex works
  here even though OpenAlex has full year coverage.
- **cleo tiering decision** (carried over from the earlier pass): at
  1553–2710 papers/year, CLEO is comparable in volume to ICASSP or CDC.
  2019 alone ran ~35% over the registry's `expected_per_year` upper bound
  (2000). Recommend a tier-2-or-exclusion call per `PLAN.md`'s
  volume-balance policy — not decided here, methodology is out of this
  skill's scope.
- **cleo unlinked-source gap**: flag to a future session as a new OpenAlex
  failure mode distinct from the already-documented ~2-year ingestion lag —
  the works exist but aren't linked to a Source entity.
- **OFC not yet registered** (carried over from the earlier pass): Optical
  Fiber Communication Conference, another major photonics venue (~1500
  papers/year) — not added here since it wasn't in scope, noted for a
  future session.
- Lookalike checks resolved cleanly this pass, logged for completeness:
  `optica` ruled out the sibling journal "Optica Quantum" (separate ISSN);
  `cleo` ruled out CLEO-PR and CLEO/Europe contamination (separate DOI
  namespace, zero contamination found in a ~1400-work sample) and resolved
  the open question of whether CLEO's 3 tracks are separate OpenAlex sources
  (they are not — same source ID, distinguished only by DOI sub-prefix).

Per-venue detail: `data/reports/jlt-2026-07-19.md`,
`data/reports/optica-2026-07-19.md`, `data/reports/cleo-2026-07-19.md`.
