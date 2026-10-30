# Conference metadata refresh — 2026-10-28

## Scope and result

The refresh covers 227 registered editions from 24 non-ML conference venues. NeurIPS, ICML, and ICLR are handled separately. After publisher-source reconciliation, the manifest records **226 complete editions with 130,250 works**. VLSI Technology 2021 remains blocked for a fresh replacement; its valid baseline membership is retained downstream. Seven edition source entries were corrected in the registry. Tracked cache files have not yet been promoted.

The accepted cache is staged at `.tmp/refresh-2026-10-28/conferences/cache/`, with Crossref raw pages at `.tmp/refresh-2026-10-28/conferences/raw-crossref/`. The canonical manifest is [`conference-works-2026-10-28.json`](../data/refresh/conference-works-2026-10-28.json). The prior manifest, which described files lost in the restart, is preserved as interrupted evidence at [`interrupted-2026-10-28/conference-works-2026-10-28-before-recovery.json`](../data/refresh/interrupted-2026-10-28/conference-works-2026-10-28-before-recovery.json); its old complete counts do not describe current coverage. Default-sandbox DNS failures and the interrupted SIGCOMM attempt are retained under `.tmp/refresh-2026-10-28/conferences/attempts/`.

The recovery worker initially checked 220 complete files. The parent then checked publisher DOI evidence against the baseline and repaired incomplete source identities. Final acceptance requires every file to parse as JSONL, match its recorded work count and SHA-256, have the registered edition year, and contain no repeated DOI. Crossref works match their registered DOI prefix or explicit DOI set; native OpenAlex works came from the registered source and exact publication-year filter. Five individually verified publisher records supplement list queries that omitted them. These checks do not establish publisher completeness.

## Baseline recovery

All 775 tracked `cache/*/*/works.jsonl` baseline paths were copied to `.tmp/refresh-2026-10-28/baseline/cache/` without smudging tracked files or changing the index. Of these, 767 LFS objects passed SHA-256 and declared-size checks (1,469,557,198 bytes total); the remaining 8 paths were verified as committed empty Git blobs and staged as empty files. The staged baseline supported exact DOI and full-byline alignment for Crossref records.

Across the 219 completed editions with readable baseline works, the baseline held 125,701 works and the new files held 126,010; 125,502 DOIs overlap. The refresh preserved baseline metadata only when the DOI and normalized full byline matched: 86,544 papers aligned, retaining 105,953 existing author-institution links, 109,388 OpenAlex author IDs, and 128,670 raw affiliation strings where the provider record lacked one.

## Crossref scope and decoding

Crossref exact-container queries used cursor pagination. Comma-bearing titles used a fully paged fuzzy container-title query constrained by owner prefix, type, and date, followed by local exact title-family and registered DOI checks. For ASPLOS, a registered Volume 2 title accepts other numbered volumes only when the edition-family title matches and the DOI is under a registered prefix. Workshops and unrelated title extensions are rejected. No registry count was used to pad an accepted result.

| ASPLOS edition | Accepted | Registered count | Baseline works | Raw Crossref records |
| --- | ---: | ---: | ---: | ---: |
| 2023 | 144 | 153 | 144 | 28,790 |
| 2024 | 198 | 198 | 198 | 35,511 |
| 2025 | 179 | 150 | 179 | 36,325 |
| 2026 | 135 | 155 | 135 | 30,009 |

The ASPLOS results match the baseline DOI sets exactly. SIGCOMM 2020 returned 53 accepted records from 25,279 raw Crossref results. Raw pages for broad queries are retained in the durable staging tree for rechecks.

The refresh ran with `--no-enrich` to avoid optional DOI-to-OpenAlex enrichment. The final decoding audit covers 206 Crossref files (106,480 works), recording 683 changed titles and 22,433 changed affiliation strings while preserving original provider values. There are 20 files primarily collected from OpenAlex, including one independently verified Crossref singleton supplement for CLEO 2021. Native OpenAlex hydration had zero eligible works and zero attempts.

## Publisher-source reconciliation

The initial seven blocked scopes included stale registry identities that could be repaired. Exact publisher container and DOI-prefix checks produced these accepted editions:

| Edition | Publisher identity | Accepted records |
| --- | --- | ---: |
| ICCAD 2017 | IEEE `10.1109/iccad.2017` | 154 |
| ICCAD 2022 | ACM `10.1145/3508352` | 164 |
| ISIT 2016 | IEEE `10.1109/isit.2016` | 626 |
| ISIT 2017 | IEEE `10.1109/isit.2017` | 652 |
| ISIT 2018 | IEEE `10.1109/isit.2018` | 546 |
| CDC 2025 | IEEE `10.1109/cdc57313.2025` | 1,015 |
| SIGCOMM 2026 | ACM `10.1145/3789240` | 200 |

ICCAD 2017's native source returned only 65 records with alternative bibliographic identifiers; replacing the baseline with those records would have lost verified IEEE papers. Its recovered publisher DOI set contains all 154 baseline papers. ICCAD 2022's exact publisher container has 219 records: 164 paper DOIs under the article prefix and 55 separate “Session details” records outside that prefix. The 55 were not used to pad the paper set. All seven exact publisher containers were also checked without a publication-date restriction; the accepted year-constrained paper sets did not omit eligible article-prefix records.

Four ISSCC papers (one in 2018, one in 2021 and two in 2023) and one CLEO 2021 paper were restored after individual Crossref DOI records confirmed the edition, title and publisher identity. Other apparent CLEO losses were represented by alternate DOI records already in the fresh set; they were not added a second time. SIGCOMM 2026's 200 records include main papers, posters and demos; the dataset does not claim a full-length-main-paper-only selection.

Evidence and before/after source entries are in [`conference-source-reconciliation-2026-10-28.json`](../data/refresh/conference-source-reconciliation-2026-10-28.json). These source corrections retain the existing venues and counting policy.

## Remaining blocked edition

| Edition | Result |
| --- | --- |
| VLSI Technology 2021 | OpenAlex returned 53 against the independently verified baseline of 79; off-year records were not used to fill the gap. |

VLSI Technology 2021 remains blocked. A Crossref search returned the distinct VLSI Circuits proceedings; those records were not substituted into Technology. The earlier CVPR, ICCV, ICRA and SIGCOMM pagination failures are resolved.

## Request accounting and validation

The recovery worker recorded 253 OpenAlex list calls: 71 from the first successful run and 182 from the resumed run, within the 500-call allocation. Parent publisher reconciliation used no OpenAlex calls. No optional OpenAlex DOI-enrichment calls or eligible-work hydration calls were made. The original Crossref counter records 720 attempts; at least 45 additional requests from an interrupted SIGCOMM query were outside that counter. Parent source retrieval added 12 counted Crossref list attempts. Source-discovery, date-scope and DOI-singleton probes are recorded separately and are not included in the 720-attempt counter. The first default-sandbox run failed DNS resolution and produced no source data.

Focused tests: `python tests/test_refresh_conferences.py` passed all 19 tests. They cover year/source scoping, cursor pagination, registered DOI and title filtering, entity decoding with provider-text preservation, baseline alignment, durable caller-supplied cache paths, and atomic writes.

This is a source-retrieval and metadata-coverage report. Downstream release construction, aggregation, and publication remain with the parent workflow.
