# Accepted refresh and publication — 2026-10-28

**Published:** [ecerankings.pages.dev](https://ecerankings.pages.dev), Cloudflare Pages production deployment `01d1f3d8-7bad-4dc7-8d38-62e1da164c91`. The requested custom domain `ecerankings.eding.dev` is associated with the project but remains pending: Cloudflare reports **CNAME record not set**, and public DNS returns NXDOMAIN. Add a proxied CNAME named `ecerankings` in the `eding.dev` zone, targeting `ecerankings.pages.dev`. Existing Wrangler authentication supports publication but lacks DNS-edit permission; MCP is not required.

The complete review is [2026-10-28-project-review.md](review/2026-10-28-project-review.md), with 22 verified findings, severity, evidence and migration priorities. The short agent contract and refresh workflow are **proposals**, in [AGENTS.proposed.md](review/AGENTS.proposed.md) and [refresh-workflow.proposed.md](review/refresh-workflow.proposed.md). Active legacy instructions were not replaced.

## Accepted data

| Collection | Accepted result | Meaning |
|---|---:|---|
| Journals | 457/457 eligible scopes; 442,255 records | All 42 registered journals, 2016–2026 clipped to checked source foundation years. |
| Conferences | 232/233 registered scopes; 135,074 records | 212 Crossref and 20 primarily OpenAlex files; VLSI Technology 2021 replacement remains blocked. |
| ML recovery | 95 checked files; 58,145 source records | 15,868 records / 15,866 distinct DOIs receive accepted paper-specific affiliations; proceedings membership remains incomplete. |
| Institution metadata | 14,750 live exact-ID records | Includes a final five-list-call top-up of 426 newly observed IDs. |
| Curated affiliation map | 398 distinct rows changed | Among changed rows: 284 retain automatic status, 102 are manual, 12 incorrect/ambiguous bindings are cleared for review. |
| Canonical release | 639,728 records in 794 files | 784 refreshed or checked-enrichment files; 10 carried forward. These are records, not globally distinct papers. |

Source observations and baselines are durable under ignored checkout storage `.tmp/refresh-2026-10-28/`. All 775 baseline paths were recovered and checked against committed pointer SHA-256/size or committed empty blobs before use. The final canonical cache is materialized in `cache/`, and changed files were stored through the required local Git LFS filter. **No files were staged in Git, no commit was created and no push was performed.** Source code and evidence remain local uncommitted changes; the deployed manifest identifies actual file hashes rather than claiming the Git baseline alone reproduces the working tree.

## Accuracy and recovery changes

- The journal collector preserves raw affiliations, source/query provenance and full bylines. It hydrated 2,068 large-list records and independently checked 4,301,106 accepted authorships. All journal scopes are complete observations; historical failures remain in the log but not in final unresolved arrays.
- Recovery now uses durable checkout storage, exclusive cache/manifest locks, committed pagination counts and actual staged-row checks. Overlapping journal writers were stopped and quarantined. The later sandbox DNS failures were distinguished from provider records missing from a successful response; a network-enabled parent run completed the remaining 369 scopes.
- Publisher reconciliation repaired seven historical conference source entries and restored five independently verified ISSCC/CLEO papers absent from list-index results. Incomplete native source generations and alternative DOI representations were not blindly unioned.
- A current-year pass added six exact 2026 proceedings sets: ISSCC (350), ISCA (189), ISIT (574), ICRA (1,882), CLEO (1,574) and joint VLSI (255). The joint event follows existing ownership under circuits. IMS successor symposia and CVPR Findings were not silently added.
- Preparation retained 80,439 prior paper-specific author assertions under DOI/title and unambiguous author identity checks. Fresh full bylines remain the denominator; explicit fresh assertions take precedence. It retained 3,485 publisher records missing from the fresh journal queries.
- Canonical preparation quarantined 1,062 out-of-edition VLSI records and four pre-2013 ICLR records, applied the documented DAC edition-year corrections, and removed two residual within-file duplicate records. Provider collectors already deduplicate their own inputs. Aggregation enforces the curated TECS/EMSOFT ownership decision and normalizes/deduplicates canonical institution affiliations before splitting author credit.
- ML recovery preserves all 25,301 author-profile affiliation strings separately. They do not supply historical credit. Accepted matches pass DOI, title and source-publication-year checks; byline changes do not erase the separate profile evidence. ML remains off by default.

Institution corrections were supported by exact raw names, live institution metadata, official sites and identifier checks, not a bulk name-only merger. The final metadata has one unresolved country: the historical Beibu Gulf University identifier `I4210128032` returns no current record. It remains in World results and is omitted from country/region filters; geography was not guessed.

## Measured release impact

The independent comparison uses the same **18 default areas and 2016–2025 window** on both releases. Total adjusted credit changes from **217,882.95126 to 221,383.77447 (+1.61%)**. Robotics increases 5.13%; Embedded Systems decreases 2.19%, including the corrected ownership/deduplication behavior. These changes combine indexing, attribution, exclusions and deduplication; increasing a score is not itself evidence of greater accuracy. The complete per-area and top-50 comparison is in `data/refresh/release-comparison-2026-10-28.json`, with a [standalone comparison chart](review/refresh-comparison-2026-10-28.html).

The default World list changes from 5,316 to 5,138 institution identifiers: 601 disappear and 423 appear. The disappearing identifiers held 345.45798 old adjusted credit. This is not treated as a completeness verdict. Samples show corrections from TH Bingen to Tübingen, The London College to University College London, Kensington College of Business to Imperial College London, and other earlier false assignments. Several manual rows used nonexistent or unrelated institution identifiers. The samples and full disappearing-ID inventory are in `data/refresh/default-ranking-impact-2026-10-28.json`; unsampled disappearances were not individually adjudicated.

Current USC results, independently reproduced from CSV:

| Selection, 2016–2025 | World rank | US rank | Adjusted credit | Paper count |
|---|---:|---:|---:|---:|
| Default 18 areas | 39 | 13 | 973.74411 | 1,703 |
| Robotics | 36 | 13 | 116.60120 | 199 |

## Validation and publication

The candidate build passes all eight structural gates: unique aggregate keys, finite nonnegative credit bounded by paper counts, venue ownership, venue/area reconciliation, exact JSON/CSV agreement, complete metadata keys, author/area reconciliation within the declared rounding bound, and nonempty default areas. It contains **139,332 aggregate rows, 8,564 institution IDs, all 20 areas and all 69 venue entries**, spanning accepted years 1987–2026. Every venue has credited output. Publication was staged and promoted only after the full candidate passed; scoped aggregation cannot overwrite the public release.

The independent Python calculation from CSV matches the actual browser ranking module over JSON in **seven selections and 25,739 institution-selection comparisons**: default World/US, robotics World/US, ML, all areas and all available years/areas. Institution sets, ranks, scores, adjusted totals and paper counts match. The 64-test Python safeguard suite and frontend ranking/region/URL/CSV fixtures pass; final `git diff --check` passes with Git LFS available. Earlier desktop/mobile layout checks preceded the final data release; no post-deployment interactive browser test is claimed.

Wrangler 4.154.0 deployed the validated allowlist package: 33 files, 14.8 MiB. **All 32 served public assets match the local package byte-for-byte**, the homepage matches the packaged index, and unknown, secret, pipeline and author-CSV paths return the intended 404 behavior. The `_headers` file configures Cloudflare rather than being a served content file. The live release manifest SHA-256 is:

`123bd9343220755dda42de9be6ce2f425cbc7c4eae14b739aa4cedea3b543361`

Publication evidence: `data/refresh/cloudflare-deployment-2026-10-28.json`, `deployment-validation-2026-10-28.json` and `custom-domain-status-2026-10-28.json`. The deployed Git revision field names the baseline at build time; its dirty-tree marker and code hashes describe the actual uncommitted implementation. Promotion and deployment did not commit or push code.

## Remaining limits and proposals

The exact current-year proceedings source remains unverified for MICRO, DAC, ICCAD, RTSS, EMSOFT, main CVPR, CDC, ECCE and IEDM. These nine availability gaps are distinct from the one blocked registered VLSI 2021 query. Some events occur later in the calendar year. ICCV's no-edition year, post-merger VLSI ownership and the user-recorded IMS hiatus are explicit exceptions. Current-year availability evidence is in `data/refresh/conference-2026-scope-notes-2026-10-28.json` and is included in the deployed coverage manifest. Missing source observations do not establish zero publications.

ML has 31,788 no-DOI source records and 10,489 DOI-bearing rows without accepted paper-specific affiliations. The accepted corpus is not a publisher-complete faculty census. Provider institution resolution, branch-campus identity, bibliographic duplicates and non-research item classification remain imperfect.

The central architectural recommendation is to retain a curated venue registry, an offline data pipeline and a dependency-light static site. Next consolidate provider assertions and work identities, implement one explicit evidence/override precedence path, make source membership/coverage states first-class, isolate optional normalization dependencies, and add CI for repeatable release contracts. A small transactional canonical store can help if repeated JSONL scans become costly; a frontend framework or production database server is not necessary for this site.

The wider migration, unified override precedence, retirement of legacy commands, replacement of active agent instructions and faculty-roster methodology remain proposals. The release's focused counting, recovery, publication and frontend improvements are implemented. **The sole hosting step left for the requested address is its DNS CNAME.**
