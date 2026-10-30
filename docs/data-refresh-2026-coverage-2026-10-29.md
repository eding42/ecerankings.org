# Current-year coverage audit — 2026-10-29

The released rankings include partial 2026 data. They do not represent a complete publication year. The default 18-area USC US ranks, recomputed with site/rank.js over the current site/data release, are 14 (2021–2026), 11 (2022–2026), 11 (2023–2026), 11 (2024–2026), 10 (2025–2026), and 9 (2026 only). Worldwide ranks respectively are 52, 52, 54, 58, 59, 74. These are snapshot results, not evidence of a definitive single-year improvement.

## DAC: newly verified source, staged collection

The official archive https://dac.com/63rd-dac links the main proceedings at https://dl.acm.org/doi/proceedings/10.1145/3770743, separately from engineering proceedings. Crossref confirms exact container `Proceedings of the 63rd ACM/IEEE Design Automation Conference`, with edition year 2026 and DOI prefix `10.1145/3770743`.

One exact-container API request returned all 310 advertised records, with 310 unique edition DOIs and 1,906 authors. Every author has raw affiliation text. The separate output is `.tmp/refresh-2026-10-29/dac/2026/works.jsonl`; its SHA-256 and query receipt are in `data/refresh/dac-2026-staged-2026-10-29.json`. Independent readback verified checksum, row count, and DOI uniqueness. No OpenAlex requests were used.

This is API-complete for the exact query, not verified publisher-complete. Reconcile against the official accepted IDs and program before accepting full coverage: https://dac.com/2026/accepted-paper-ids and the program linked from the archive. The publisher HTML was blocked by HTTP 403 in the web tool. There are 678 distinct affiliation strings; 238 have existing exact mapping entries, including unresolved entries, and 440 have no exact entry. Resolve and independently audit attribution before ranking these records. No raw-string Southern California match was found; this is not proof of no USC papers in the full proceedings.

## Other actionable gaps

- Main CVPR 2026 has an official paper repository at https://openaccess.thecvf.com/CVPR2026. The all-papers endpoint returned HTTP 403 in the web tool. Establish exact main-conference paper membership and publication-time affiliations; do not substitute workshops or Findings.
- ECCE took place October 4–8 according to https://www.ieee-ecce.org/2026/. Its registry gap must not be described as a future conference. Exact proceedings source remains unresolved in this pass.
- The previous availability ledger also lists MICRO, ICCAD, RTSS, EMSOFT, CDC and IEDM as unverified. Distinguish future events, already-held events awaiting metadata, and genuinely uncollected proceedings. EMSOFT journal publications require membership checks and TCAD deduplication.
- Preserve the existing no-duplicate treatment of joint VLSI proceedings and the user-approved IMS scope decision.

## Release work still required

1. Resolve and audit new DAC affiliations; reconcile proceedings membership.
2. Establish CVPR main-conference inventory and exact ECCE source; investigate the other availability gaps.
3. Verify affiliation coverage for the six 2026 editions added in the prior release without fresh OpenAlex enrichment.
4. Rebuild a separate candidate release, compare ranking changes and coverage, then publish after validation.

This pass changed staging data and audit documentation only. It did not alter canonical rankings, registry methodology, or the deployed release. No collector remains running.
