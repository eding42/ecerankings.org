# Recent-year data completeness audit (2026-10-29)

## Executive finding

The release and accepted refresh are structurally validated, but **recent-year data are not uniformly complete at publisher-membership or institution-attribution level**. The production manifest marks 2025 as the latest complete calendar year and explicitly warns that publisher coverage may still be incomplete. The refresh accepted all 457 eligible journal scopes and 232 of 233 registered conference edition queries; it separately retains nine unverified 2026 conference scopes. A staged 2026 DAC set and current authoritative program pages show that at least four of those nine are already-held editions and should no longer be described as merely future or unavailable.

For 2023–2025, the local conference source files have DOI and edition-year coverage for every returned row, but source-row membership is not equivalent to an independently reconciled accepted-paper list. In the staged source files, journal authorship-affiliation signals range from 94.1% to 98.5% in 2023–2026; conference signals are lower at 89.7%–92.2% in 2023–2025 and 81.7% in the partial 2026 set. These signal rates mean an author has at least one raw affiliation string or institution record; they do **not** mean that the institution was correctly normalized or credited.

The highest-priority actions are: (1) reconcile and stage the held 2026 CVPR, DAC, ECCE and EMSOFT editions; (2) backfill paper-level affiliation evidence for 2026 additions and repair the severe CLEO/Optica affiliation holes; (3) separate main papers from SIGCOMM poster/demo records; (4) finish the ML membership and DOI/author-affiliation recovery; and (5) correct the power-area 2026 ECCE omission and review whether its conference scope is too narrow.

## Snapshot and method

Audit date: 2026-10-29. I read the current registry, release manifest, accepted-refresh manifests and validation reports, staged DAC manifest, and cached source rows. Derived DOI, year, byline and affiliation-signal percentages below were computed from local staged records without writing to canonical data. The conference source-count table reports rows in the collected files, not a certified count of eligible research papers. The two recent-year tables give every registered journal and conference key represented in the 2023–2026 scope.

The relevant repository evidence is [data/areas.json](../../data/areas.json), [site/data/manifest.json](../../site/data/manifest.json), [accepted refresh manifest](../../data/refresh/accepted-refresh-2026-10-28.json), [journal source manifest](../../data/refresh/journal-works-2026-10-28.json), [conference source manifest](../../data/refresh/conference-works-2026-10-28.json), [conference validator output](../../data/refresh/conference-final-validation-2026-10-28.json), [ML recovery manifest](../../data/refresh/ml-works-2026-10-28.json), and [staged DAC receipt](../../data/refresh/dac-2026-staged-2026-10-29.json).

The release contains 639,728 source records in 794 files. Journal validation passed 457/457 scopes (442,255 records); conference validation passed 232/233 edition queries (135,074 records), with VLSI Technology 2021 blocked; ML recovery checked 95 files (58,145 records). The conference validator confirms hashes, counts, edition years, unique normalized DOI/work IDs, registered DOI-prefix/explicit-set checks, provider identity, and byline/affiliation structure. These gates establish integrity against the stored source query and manifest, not exhaustive publisher acceptance-list equivalence.

### Publication and indexing lag

The latest complete calendar year is 2025. The journal collector also returned 44,010 records for 2026 across all 42 journals, versus 50,811 for 2025 (86.6%); that single snapshot is a partial-year signal, not a forecast or proof of a 2026 shortfall. The refresh explicitly retained 3,485 publisher journal-membership records missing from fresh OpenAlex journal queries. The stored evidence does not break those 3,485 records down by year or give first-online-to-index lag distributions, so a median/percentile day-lag cannot be honestly reported from this audit.

For conferences, 2026 event-end-to-audit intervals are 144 days for CVPR (June 7), 92 days for DAC (July 29), 21 days for ECCE (October 8), and 20 days for EMSOFT/ESWEEK (October 9). These are elapsed event intervals, **not measured publisher DOI-publication delays**. They show why event status and proceedings availability must be tracked separately. Crossref issue dates, journal publication dates, online-first dates and conference dates are not interchangeable.

## Recent-year identifier, byline and affiliation coverage

The percentages below come from the accepted source rows as they are stored. For journals and conferences, “affiliation signal” is an author slot containing either a raw affiliation or an institution value. It does not verify that institution’s identity, geography, historical affiliation, or final ranking attribution. The conference byline is publisher/provider-reported and not independently compared with every official program author list.

| Corpus and year | Source rows | Rows with DOI | Rows with a nonempty byline | Author slots with affiliation signal | Edition/scope coverage |
|---|---:|---:|---:|---:|---:|
| Journals (OpenAlex), 2023 | 39,730 | 39,730 (100.0%) | 38,375/39,730 (96.59%) | 434,479/448,304 (96.92%) | 42/42 |
| Conferences (accepted source rows), 2023 | 15,407 | 15,407 (100.0%) | Source-reported author entries; no publisher-complete byline denominator | 72,439/78,526 (92.25%) | 23/27 plan slots* |
| Journals (OpenAlex), 2024 | 44,758 | 44,758 (100.0%) | 43,465/44,758 (97.11%) | 478,918/486,216 (98.50%) | 42/42 |
| Conferences (accepted source rows), 2024 | 14,680 | 14,680 (100.0%) | Source-reported author entries; no publisher-complete byline denominator | 70,448/77,485 (90.92%) | 22/27 plan slots* |
| Journals (OpenAlex), 2025 | 50,811 | 50,811 (100.0%) | 49,478/50,811 (97.38%) | 529,332/562,594 (94.09%) | 42/42 |
| Conferences (accepted source rows), 2025 | 17,545 | 17,545 (100.0%) | Source-reported author entries; no publisher-complete byline denominator | 88,209/98,310 (89.73%) | 23/27 plan slots* |
| Journals (OpenAlex), 2026 | 44,010 | 44,010 (100.0%) | 43,038/44,010 (97.79%) | 478,923/503,689 (95.08%) | 42/42 |
| Conferences (accepted source rows), 2026 | 10,527 | 10,527 (100.0%) | Source-reported author entries; no publisher-complete byline denominator | 46,988/57,547 (81.65%) | 12/27 plan slots* |

* Conference plan-slot denominator is 27 registry conference keys, including three ML keys whose separate Semantic Scholar baseline is detailed below. ECE conference source sets were 23/24, 22/24, 23/24 and 12/24 for 2023–2026. Non-applicable years include biennial ICCV, post-merger VLSI-Tech ownership, and the user-recorded IMS hiatus/restructuring decision. A dash in a venue table means no accepted conference source row; for 2026, the nine unverified ECE scopes are itemized below.

### Journals: source rows by registered venue

Counts are OpenAlex query rows from the October 28 refresh. “Complete” means the query finished and passed staged-file checks, not that a publisher archive has been compared exhaustively.

| Venue key | 2023 | 2024 | 2025 | 2026* |
|---|---:|---:|---:|---:|
| automatica | 565 | 494 | 589 | 439 |
| edl | 515 | 678 | 618 | 494 |
| jestpe | 396 | 579 | 680 | 570 |
| jlt | 902 | 1124 | 1079 | 959 |
| jsac | 294 | 237 | 444 | 200 |
| jssc | 335 | 412 | 436 | 369 |
| jstsp | 67 | 132 | 130 | 89 |
| light-sa | 297 | 322 | 395 | 393 |
| nat-comms | 8524 | 10929 | 12646 | 10933 |
| nat-electronics | 201 | 207 | 211 | 197 |
| nat-photonics | 210 | 237 | 233 | 210 |
| nat-phys | 432 | 418 | 404 | 370 |
| nature | 4321 | 4386 | 4554 | 3703 |
| npjqi | 125 | 136 | 217 | 226 |
| optica | 218 | 214 | 249 | 249 |
| pnas | 3627 | 3955 | 4367 | 4142 |
| prl | 2184 | 2520 | 3280 | 2432 |
| prx | 194 | 243 | 340 | 262 |
| prxquantum | 192 | 243 | 319 | 220 |
| qst | 130 | 210 | 260 | 297 |
| ral | 1194 | 1502 | 1668 | 1639 |
| sci-adv | 2137 | 2319 | 3181 | 3056 |
| science | 1965 | 2044 | 2056 | 1692 |
| scirobotics | 95 | 138 | 132 | 96 |
| tac | 705 | 744 | 697 | 529 |
| tap | 1085 | 1059 | 1098 | 972 |
| tbme | 316 | 346 | 433 | 387 |
| tcad | 332 | 452 | 496 | 399 |
| tcom | 628 | 766 | 879 | 863 |
| tecs | 164 | 89 | 171 | 82 |
| ted | 1145 | 1171 | 1015 | 895 |
| tip | 482 | 477 | 610 | 767 |
| tit | 459 | 425 | 524 | 439 |
| tmtt | 616 | 637 | 790 | 605 |
| ton | 239 | 280 | 336 | 341 |
| tpami | 679 | 676 | 942 | 857 |
| tpel | 1333 | 1611 | 1726 | 1363 |
| tpwrs | 536 | 407 | 373 | 266 |
| tro | 282 | 261 | 314 | 206 |
| tsg | 416 | 345 | 468 | 471 |
| tsp | 335 | 378 | 325 | 304 |
| twc | 858 | 955 | 1126 | 1027 |

* 2026 is an in-progress publication year as of October 29. The default current-year rank is partial even though all 42 configured query scopes completed.

### Conferences: source rows by registered venue and edition

Counts are records in accepted conference source files. They may include non-research/front matter or presentation categories beyond main full papers. The 310 DAC records are separately marked staged and excluded from the accepted release.

| Area | Venue key | 2023 | 2024 | 2025 | 2026 | Audit note |
|---|---|---:|---:|---:|---:|---|
| architecture | asplos | 144 | 198 | 179 | 135 | 2023/2025 prefix sets include bundled volume and ancillary-content concerns; count/source membership should reconcile by DOI and program. |
| control | cdc | 1121 | 1109 | 1015 | — | 2026 source missing; official event is in December (future). |
| photonics | cleo | 1704 | 1907 | 1553 | 1574 | Very weak author-affiliation signal in 2023–2025; see affiliation table below. |
| image | cvpr | 2368 | 2724 | 2881 | — | 2026 main conference held; official source reports 4,089 accepted paper presentations. 2026 absent locally. |
| eda | dac | 326 | 370 | 458 | 310 staged* | 310-work exact-container Crossref set is staged only; accepted-ID/program and affiliation audit open. |
| powerelec | ecce | 1016 | 1151 | 933 | — | 2026 event held October 4–8; no 2026 edition file. Power Electronics priority. |
| embedded | emsoft | 9 | 10 | 7 | — | 2026 ESWEEK/EMSOFT held October 4–9; reconcile membership through TCAD-integrated publication and deduplicate. |
| architecture | hpca | 104 | 93 | 133 | 123 | 2026 source in registry remains provisional; exact Crossref result is present. |
| sigproc | icassp | 2726 | 2712 | 3312 | 4589 |  |
| eda | iccad | 205 | 239 | 316 | — | 2026 conference is November 8–12 (future); no source file. |
| image | iccv | 2163 | — | 2709 | — | Biennial, odd-year editions; no 2024 or 2026 edition expected. |
| robotics | icra | 1347 | 1766 | 1610 | 1882 |  |
| devices | iedm | 231 | 277 | 298 | — | 2026 meeting is December 12–16 (future); no source file. |
| em_rf | ims | 314 | 278 | 287 | — | 2026 hiatus/restructuring per recorded scope decision; successors not mapped to IMS. |
| networking | infocom | 257 | 262 | 272 | 613 |  |
| architecture | isca | 84 | 98 | 135 | 189 |  |
| inftheory | isit | 476 | 631 | 503 | 574 |  |
| circuits | isscc | 260 | 322 | 339 | 350 |  |
| architecture | micro | 101 | 124 | 123 | — | 2026 meeting starts October 31 (future at audit date); no 2026 source file. |
| embedded | rtas | 41 | 44 | 44 | 43 |  |
| embedded | rtss | 62 | 54 | 68 | — | 2026 meeting is December 9–11 (future); no source file. |
| networking | sigcomm | 107 | 62 | 88 | 200 | 2023 includes 25 poster + 11 demo records; 2025 includes 14 short poster/demo-style records. Main-paper counts require filtering. |
| circuits | vlsi-circuits | 241 | 249 | 282 | 255 | Post-merger ownership; 2026 joint proceedings are recorded here once. |
| devices | vlsi-tech | — | — | — | — | Pre-merger source only through 2021; no separate 2023+ edition. |

## Current-year edition membership and collection lag

The release has 12 ECE conference source sets for 2026 (10,527 source rows), nine unverified source sets, and three explicit no-edition/out-of-scope cases. “Unverified” must not be rendered as zero publications.

| 2026 edition | Status at 2026-10-29 | Evidence and repair |
|---|---|---|
| CVPR | Held June 5–7; no local 2026 file | Official CVPR reports 4,089 accepted paper presentations; the official CVF repository exposes the main-paper archive, but its all-papers endpoint returned HTTP 403 to this browser. Download publisher inventory through the already-authorized public archive path, reconcile exact main-conference IDs and exclude Findings/workshops, then enrich DOI-matched paper affiliations. [Official dates](https://cvpr.thecvf.com/Conferences/2026/Dates), [CVPR closing report](https://cvpr.thecvf.com/Conferences/2026/News/Closing), [CVF 2026 paper archive](https://openaccess.thecvf.com/CVPR2026). |
| DAC | Held July 26–29; 310 records staged, not published | Exact Crossref container query returned 310 rows, 310 unique DOIs and 1,906 authors; raw affiliation text exists for 1,906/1,906 authors. No OpenAlex calls were used for the staged set. Its 678 distinct raw affiliation strings have 238 exact existing map entries and 440 with no exact entry; existing entries are not necessarily verified. Reconcile the 310 DOI set against the official accepted research-paper IDs and full program; then audit/resolve affiliations, compare against the separate engineering proceedings, validate and rebuild a candidate. [DAC dates and program links](https://dac.com/2026/), [accepted paper IDs](https://dac.com/2026/accepted-paper-ids), [research submission/proceedings process](https://dac.com/2026/research-manuscript-submissions). The publisher HTML was previously 403 in the source pass; this audit did not repeat API calls. |
| ECCE | Held October 4–8; no local 2026 file | This is a material gap in `powerelec`, not a future event. Discover the exact 2026 IEEE proceedings source, reconcile program membership, and enrich author affiliations. Prior accepted rows: 1,016 (2023), 1,151 (2024), 933 (2025). [Official ECCE 2026 dates and scope](https://www.ieee-ecce.org/2026/). |
| EMSOFT | Held October 4–9 with ESWEEK; no separate 2026 membership set | The official ESWEEK publication model says accepted full papers from EMSOFT/CASES/CODES appear in TCAD, so membership may already exist in the 2026 journal rows but is not necessarily tagged to EMSOFT. Match official IDs to TCAD DOI/title/authors and enforce one credit owner; also revisit the documented 2017/2019 TECS–EMSOFT overlap. [ESWEEK 2026 dates and CFP](https://esweek.org/wp-content/uploads/2025/12/ESWeek2026_CFP_v0.5.pdf), [EMSOFT information](https://esweek.org/emsoft/). |
| MICRO | Future at audit date; scheduled October 31–November 4 | Keep as pending until event/proceedings metadata land; record the DOI source and query again after the event. [MICRO 2026 official site](https://www.microarch.org/micro59/). |
| ICCAD | Future; November 8–12 | Pending event; no zero-publication inference. Add the exact IEEE/ACM proceedings source after publication. [IEEE CEDA 2026 CFP](https://ieee-ceda.org/files/ieeeceda/2026-02/iccad26-cfp_web-04.pdf). |
| RTSS | Future; December 9–11 | Pending event. The official page already lists 32 accepted and 18 conditionally accepted papers; that is not a proceedings DOI inventory. [Official RTSS site](https://2026.rtss.org/). |
| CDC | Future; December 15–18 | Pending event; add publisher records after the proceedings become available. [Official CDC 2026 site](https://cdc2026.ieeecss.org/). |
| IEDM | Future; December 12–16 | Pending event; add exact IEEE proceedings membership after the meeting/publisher release. [Official IEDM site](https://ieee-iedm.org/). |
| ICCV | No 2026 edition | Correct non-applicable biennial year. |
| VLSI Technology | Separate key ended after 2021 merger | Do not duplicate the joint VLSI Technology and Circuits source stored under `vlsi-circuits`. |
| IMS | No source by recorded scope decision | 2026 MTT-S restructuring into successor symposia remains outside the historic IMS key pending a scope decision. |

The authoritative event pages establish event timing and the presence of official program/paper inventories. They do not by themselves establish that every accepted item belongs in the ranked proceedings corpus. In particular, the EMSOFT integrated journal model and DAC’s separately listed engineering proceedings require identity and ownership checks before any release change.

## ML: source membership and affiliation recovery remain the weakest data stream

The 95-file Semantic Scholar baseline covers ICLR, ICML and NeurIPS but has **not** been reconciled to each publisher’s complete proceedings archive. The October 28 recovery used DOI lookups against OpenAlex and accepted only matches that passed DOI, title and year identity checks. It did not use Semantic Scholar current author-profile affiliations as historical paper affiliations.

| Venue | Year | Semantic Scholar rows | Rows receiving accepted paper-level OpenAlex affiliation evidence | Unmatched rows | Backfill share |
|---|---:|---:|---:|---:|---:|
| iclr | 2023 | 2,081 | 1,464 | 617 | 70.4% |
| iclr | 2024 | 2,845 | 1,985 | 860 | 69.8% |
| iclr | 2025 | 1,772 | 622 | 1,150 | 35.1% |
| iclr | 2026 | 13 | 11 | 2 | 84.6% |
| icml | 2023 | 1,914 | 1,321 | 593 | 69.0% |
| icml | 2024 | 2,696 | 1,783 | 913 | 66.1% |
| icml | 2025 | 2,695 | 1,555 | 1,140 | 57.7% |
| icml | 2026 | 17 | 15 | 2 | 88.2% |
| neurips | 2023 | 3,787 | 1,406 | 2,381 | 37.1% |
| neurips | 2024 | 4,834 | 1,686 | 3,148 | 34.9% |
| neurips | 2025 | 3,159 | 140 | 3,019 | 4.4% |
| neurips | 2026 | 50 | 45 | 5 | 90.0% |

Across all years in the 95 files, the baseline has 58,145 works and 26,355 distinct DOI-bearing works. The recovery backfilled 15,868 work rows for 15,866 distinct DOIs, with 78,994 full byline author records. Another 10,489 DOI-bearing works lacked an accepted OpenAlex paper match; 31,788 works had no DOI and remained unresolved to this recovery. Thus only 27.3% of all baseline work rows received accepted paper-level backfill in this pass. All 25,301 Semantic Scholar profile-affiliation strings were retained separately and withheld from historical credit. No publisher-complete membership claim is supported. ML remains off by default, limiting impact on the default ranking but leaving the optional ML view materially incomplete.

The 2026 ML rows (13 ICLR, 17 ICML, 50 NeurIPS) are plainly not full year inventories. NeurIPS is still future at the audit date; ICLR and ICML have held their 2026 events, so their small repository counts are source-lag/coverage warnings requiring official accepted-set comparison. Exact per-venue/edition values above should be treated as collector snapshots, not accepted-paper totals.

## Affiliation and membership defects beyond missing 2026 editions

1. **CLEO and Optica metadata are not ranking-ready without a repair.** The conference source manifest reports author-affiliation coverage of only 45.09% (CLEO 2023), 43.89% (2024), and 3.60% (2025). In the journal cache, author slots with any affiliation signal are 52.4% for Optica 2025 and 41.0% for Optica 2026. Re-run exact DOI matching/enrichment for these editions, identify metadata truncation versus absent publisher affiliations, and report institution-resolution separately. The 2026 CLEO set is among six newly accepted proceedings with no fresh OpenAlex enrichment.
2. **All six new 2026 proceedings lack fresh OpenAlex affiliation enrichment.** The accepted set added ISSCC (350), ISCA (189), ISIT (574), ICRA (1,882), CLEO (1,574), and joint VLSI (255): 4,824 records total. Their manifest state is `not-run-new-edition`. Publisher bylines/raw affiliations therefore need identity-checked DOI enrichment and attribution review before claiming institution-complete 2026 results. ICRA is included here even though its source exists; source membership is not affiliation enrichment.
3. **SIGCOMM category contamination changes research-paper counts.** The registry documents 25 posters and 11 demos inside the SIGCOMM 2023 DOI-prefix set, making about 71 of 107 records main papers; 2025 includes 14 short poster/demo-style entries, about 74 of 88 main papers. Filter against official paper category/program records and show the remaining count before altering canonical output. The 2026 count of 200 explicitly includes posters and demos.
4. **Count drift needs membership adjudication, not blind count forcing.** In conference editions with a non-null registry `registered_count`, it equals the current `api_count` in only 15/21 (2023), 16/20 (2024), 13/20 (2025), and 2/5 (2026). The existing pipeline deliberately records these deltas rather than coercing provider results to stale expected counts. Resolve each material delta against publisher DOI/paper inventories; count mismatch alone is not evidence of missing/extra research papers.
5. **One older source scope remains blocked.** The conference validator reports VLSI Technology 2021 as blocked (`expected 79, got 53`); the 79-record valid-year baseline is retained and 1,062 out-of-year records are quarantined during canonical preparation. This does not affect 2023–2026 ownership, but it remains a known edition-level gap.
6. **Power scope is unusually narrow.** `powerelec` contains TPEL, JESTPE and ECCE; `power` contains TPWRS and TSG and no conference. The most immediate data repair is ECCE 2026, but a separate venue-scope review should check whether IEEE PES General Meeting, PSCC or IEEE PowerTech meet the repository’s selectivity and ≥80% in-area rules. Do not add them on acronym/topic resemblance alone.

## Prioritized repair plan with acceptance criteria

| Priority | Repair | Acceptance evidence |
|---|---|---|
| P0 | CVPR 2026 main program | Exact DOI or official paper-ID set; show 4,089 official accepted presentations against main-paper records; distinguish Findings/workshops; author/affiliation match denominator and source hash; no release until validation. |
| P0 | ECCE 2026 | Exact IEEE proceedings DOI inventory and official-program reconciliation; verify edition-year dates; populate 2026 power-electronics rows and paper-level affiliations. |
| P0 | DAC 2026 staged records | Compare all 310 staged DOIs with accepted research IDs/program, confirm engineering-proceedings exclusion, independently validate 310-row file/hash and bylines, then resolve the 440 unmapped exact affiliation strings and audit all 678. |
| P0 | EMSOFT 2026 / TCAD | Reconcile official accepted full-paper IDs to TCAD and any conference proceedings records; make one venue own each paper; retain paper-level byline and publication-year evidence. |
| P1 | 2026 six-edition attribution | DOI-enrich ISSCC, ISCA, ISIT, ICRA, CLEO and VLSI (4,824 rows); measure byline completeness, raw affiliation coverage, normalized institution coverage and unresolved author slots separately. |
| P1 | CLEO/Optica coverage | Diagnose the 2023–2026 low coverage against publisher source and OpenAlex by DOI; quantify recovered author slots and exact institution-mapping resolution; never substitute current author profiles for historical paper affiliations. |
| P1 | ML corpus | Reconcile all 95 source editions to official ICLR/ICML/NeurIPS inventories; then report by year DOI availability, DOI-match failures, title/year rejections, full byline/affiliation slots, and unresolved no-DOI records. Resolve paper-specific evidence only. |
| P1 | SIGCOMM 2023/2025 and 2026 | Match official paper type to each DOI; exclude demos/posters if policy is main research papers only; publish record and retained-paper counts per edition. |
| P2 | Remaining future 2026 editions | Recheck MICRO, ICCAD, RTSS, CDC and IEDM after each official event and publisher publication. Keep current-year release explicitly partial until source plus membership checks pass. |
| P2 | Power-area venue scope | Document which power systems/power electronics venues satisfy selectivity and topic share; record inclusion/exclusion rationale and historical coverage before adding any venue. |
| P2 | Lag instrumentation | Store first-public-online, proceedings publication, provider-ingest and collection timestamps by DOI; calculate median and p90 delay by venue/provider. Present year-to-date separately from completed-year coverage. |

## Evidence limits

- OpenAlex “complete” journal scopes are complete responses to the selected source/year query, not publisher-census proofs. The 3,485 retained Crossref journal memberships demonstrate that OpenAlex misses some publisher-indexed records, but the current audit evidence does not identify their year distribution.
- Crossref exact-container/prefix queries provide strong DOI-based membership evidence, but author names, affiliation strings and type labels may be absent, inconsistent or include front matter. Publisher accepted lists/programs remain the stronger set comparison where accessible.
- “Has affiliation signal” is not “institution correctly credited.” Mapping coverage, campus resolution, historical affiliation time and ambiguous/incorrect map entries are separate checks. The DAC map audit illustrates this directly.
- An official accepted-paper count is not automatically identical to proceedings DOI count: withdrawals, journal-integrated proceedings, demos, posters, Findings, late-breaking work, front matter and separate engineering tracks can differ.
- 2026 calendar-year ranking and all in-progress proceedings are partial. The deployment manifest’s structural ranking validation does not remove these collection limits.
- Source checks were read-only. No collector was run, no paid API request or credential was used, and no canonical data or release artifact was changed. Only this review document is added.

## Public source references

- [CVPR 2026 official dates](https://cvpr.thecvf.com/Conferences/2026/Dates), [CVPR closing report and accepted presentation count](https://cvpr.thecvf.com/Conferences/2026/News/Closing), and [CVF official paper archive](https://openaccess.thecvf.com/CVPR2026).
- [DAC 2026 official conference/program](https://dac.com/2026/), [research accepted IDs](https://dac.com/2026/accepted-paper-ids), [main research proceedings process](https://dac.com/2026/research-manuscript-submissions), and [ACM DL proceedings DOI](https://dl.acm.org/doi/proceedings/10.1145/3770743).
- [ECCE 2026 official event](https://www.ieee-ecce.org/2026/).
- [ESWEEK 2026 CFP and integrated publication model](https://esweek.org/wp-content/uploads/2025/12/ESWeek2026_CFP_v0.5.pdf) and [EMSOFT 2026 information](https://esweek.org/emsoft/).
- Future editions: [MICRO 2026](https://www.microarch.org/micro59/), [ICCAD 2026 IEEE CEDA CFP](https://ieee-ceda.org/files/ieeeceda/2026-02/iccad26-cfp_web-04.pdf), [RTSS 2026](https://2026.rtss.org/), [CDC 2026](https://cdc2026.ieeecss.org/), [IEDM 2026](https://ieee-iedm.org/).
