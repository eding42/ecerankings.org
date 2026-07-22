# Collection report: cross-area verification batch — 2026-07-22

## Summary

Orchestrated 22 parallel Sonnet workers (plus 1 relaunch after a kill) to run
the full `collect-venue-data` checklist against every `candidate`/`todo`
venue in the registry outside the four genuinely data-blocked ones (RSS,
NeurIPS, ICML, ICLR — see "Deliberately not touched" below). Combined with
the Quantum Engineering area added earlier the same day (3 venues, all
verified), this session moved the registry from **34 verified / 25 candidate
/ 1 todo** to **55 verified / 5 candidate / 0 todo**, out of 60 total venues.

21 of 22 batch venues reached `verified`. One (IMS) correctly stayed
`candidate` — its 2016–2025 history is fully resolved, but IEEE MTT-S
restructured IMS2026 into a multi-symposium umbrella, which is a scoping
decision for the user, not something a checklist resolves. Two independent
spot-checks (DAC, CVPR) against the live OpenAlex/Crossref APIs, done outside
the worker sessions, corroborated the workers' findings with no discrepancies.

Most of this batch was **re-assessment against the skill's updated "what
verified means" definition** (a DOI-validated Crossref year is legitimate
coverage; OpenAlex's conference-ingestion lag alone doesn't block `verified`)
rather than fresh research — many venues already had year-by-year Crossref
mappings from a prior session that were sitting at `candidate` under an
older, stricter reading. A handful (ISCA, ICCV, SIGCOMM) had no prior mapping
and were resolved from scratch.

## Venues

| venue | area | kind | status | key finding |
|---|---|---|---|---|
| JSAC | comms | journal | verified | clean, no issues |
| JSTSP | sigproc | journal | verified | clean, no issues |
| T-PAMI | image | journal | verified | expected_per_year raised [300,600]→[300,950] (real growth) |
| JESTPE | powerelec | journal | verified | clean, no issues |
| ToN | networking | journal | verified | **2nd OpenAlex source ID found** — journal's e-ISSN changed 2025, splitting coverage; deliberately no `years{}` (union-of-sources needed) |
| MICRO | architecture | conference | verified | fixed 2 wrong DOI prefixes (2024, 2025) |
| HPCA | architecture | conference | verified | added 2026 (provisional) |
| ASPLOS | architecture | conference | verified | added 2026; flagged "Session details:" front-matter needs filtering |
| ISCA | architecture | conference | verified | **from scratch** (was `todo`) — no OpenAlex source at all; ACM/IEEE alternation breaks twice |
| DAC | eda | conference | verified | resolved 4 mystery legacy source IDs (2001–2005 editions); found OpenAlex `publication_year` metadata bug |
| RTSS | embedded | conference | verified | fixed 3 wrong DOI prefixes |
| RTAS | embedded | conference | verified | fixed 4 wrong DOI prefixes + 4 count corrections; added 2026 |
| EMSOFT | embedded | conference | verified | resolved 2017/2019 "gaps" (papers were in joint TECS special issues) — **surfaced TECS double-count risk, unresolved** |
| ICASSP | sigproc | conference | verified | added 2026 (4,589 papers, real growth, independently plausible) |
| CVPR | image | conference | verified | confirmed Workshops exclusion is structurally sound; independently spot-checked, holds up |
| ICCV | image | conference | verified | **from scratch** — confirmed genuinely biennial (odd years only, not transitioning to annual) |
| INFOCOM | networking | conference | verified | fixed 2025 DOI prefix; added 2026 (603 papers, ~59% over ceiling, flagged) |
| SIGCOMM | networking | conference | verified | **from scratch** (after a kill + relaunch) — expected_per_year corrected [50,150]→[35,110]; found bundled poster/demo papers in 2023/2025 |
| CDC | control | conference | verified | resolved a real expected_per_year contradiction — corrected [1100,1800]→[750,1300] |
| ECCE | powerelec | conference | verified | resolved the flagged 2x volume mismatch — 3 fabricated DOI prefixes from a prior session, corrected [600,1100]→[800,1200] |
| IMS | em_rf | conference | **candidate** | 2016-2025 fully resolved (3 DOI-prefix fixes) but 2026 genuinely blocked on IEEE MTT-S's restructuring — needs a user scoping call |
| VLSI-Tech | devices | conference | verified | window correctly narrowed to 2016-2021 (pre-merger); expected_per_year corrected [100,250]→[75,115] |

## Corrections found (bugs from prior sessions, now fixed)

Several venues had DOI prefixes that were simply wrong or nonexistent in
Crossref — silent time bombs that would have zeroed out those years on any
future `harvest_crossref.py` run:

- **MICRO**: 2024, 2025
- **RTSS**: 2019, 2024, 2025
- **RTAS**: 2020, 2022, 2023, 2025 (plus 4 slightly-off counts)
- **INFOCOM**: 2025
- **IMS**: 2016-2019 (wrong prefix pattern entirely), 2022, 2025
- **ECCE**: 2023, 2024, 2025 — the big one; these three years' "verified" counts had never actually been DOI-checked, which is why they ran ~2x over the expected range

Several `expected_per_year` ranges were corrected from miscalibrated original
guesses to match real, DOI-verified volume: CDC, ECCE, SIGCOMM, VLSI-Tech,
ICCV, T-PAMI.

## Needs human review (carried forward, unresolved)

1. **TECS/EMSOFT double-count risk** (highest priority). EMSOFT's 2017 and
   2019 papers were published as joint ACM TECS special issues and are native
   OpenAlex records under `S136160450` — the same source already registered
   as this area's separate `tecs` venue. Harvesting both as currently
   structured double-counts ~55 papers. Needs one of: (a) exclude these DOIs
   from `tecs`'s harvest, (b) exclude from `emsoft`'s harvest and let `tecs`
   absorb them, (c) dedupe by DOI at aggregation time.
2. **IMS 2026 scoping**. IEEE MTT-S split IMS into "IMS RFTT" (~half,
   confirmed) and "IMS RFSA" (~other half, absorbs the old separate RFIC
   conference, not yet in Crossref). Pick: RFTT-only, RFTT+RFSA combined, or
   treat 2026 as a hiatus year and revisit in 2027.
3. **ICASSP/INFOCOM volume growth**: 2026 counts are 43-59% over their
   registered `expected_per_year` ceilings. Confirmed real (not contamination)
   by each worker, but the ranges themselves are now stale and worth an
   area-wide recalibration pass.
4. **ASPLOS/SIGCOMM harvest-time filtering**: both venues bundle non-paper
   content into some years' main DOI prefix (ASPLOS: "Session details:"
   front matter in 2017/2019; SIGCOMM: poster/demo papers in 2023/2025) —
   `pipeline/harvest_crossref.py` will need a title-pattern filter, not just
   DOI-prefix + type, when it eventually runs against these venues.
5. **DAC pre-window metadata bug**: two of DAC's legacy source IDs
   (2001, 2003 editions) have OpenAlex `publication_year` fields that
   disagree with the true DOI-derived edition year — a future pre-2017
   backfill must bucket by DOI-derived year, not a `publication_year` filter,
   or it will silently return zero works for those two years.

## Deliberately not touched (bucket C — genuinely data-blocked)

RSS, NeurIPS, ICML, and ICLR were not sent to a verify-subagent. Their prior
registry notes already document why: RSS has 0% Crossref affiliation
strings and only ~45-50% OpenAlex fallback coverage; NeurIPS/ICML/ICLR are
OpenReview-hosted and largely absent from both OpenAlex and Crossref at their
real submission volume. These need a research or methodology decision
(alternate source, accept degraded data, or exclude), not another checklist
run — reported to the user as open decisions rather than forced to a verdict.

## Independent verification

Two of this batch's `verified` calls (DAC, CVPR) were independently
spot-checked against the live OpenAlex/Crossref APIs outside the worker
sessions — confirmed source IDs, works_counts, and DOI resolutions all
matched the workers' claims with no discrepancies (see chat log; not
re-duplicated here).

## Registry status after this batch

60 venues total: **55 verified, 5 candidate, 0 todo** (up from 34 verified,
25 candidate, 1 todo at the start of this session).

No harvesting was performed for any venue in this batch — registry and
reports only, per the skill's ask-first rule on cache-writing steps.
