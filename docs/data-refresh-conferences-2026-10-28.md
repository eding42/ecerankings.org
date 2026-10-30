# Conference refresh — 2026-10-28

The accepted inventory contains **232 of 233 registered edition queries**, covering **135,074 works**: 212 Crossref files (111,304 works) and 20 primarily OpenAlex files (23,770 works, including one independently verified Crossref supplement). **VLSI Technology 2021 is the one blocked replacement.** Its 79 valid-year baseline records are retained; 1,062 records from other years are quarantined during canonical preparation.

## Acceptance and evidence

`data/refresh/conference-final-validation-2026-10-28.json` passes with zero errors. It independently checks the entire registered query plan, every accepted file hash and count, edition and provider-issued years, normalized DOI/work-ID uniqueness, exact registered DOI prefixes or explicit DOI sets, provider identity, byline/raw affiliation structure and large native bylines. The one mixed-provider supplement in CLEO 2021 must match its exact DOI, publisher URL and independently recorded membership proof; it is not accepted through a generic provider exception.

Accepted normalized observations are in `.tmp/refresh-2026-10-28/conferences/cache`. Raw Crossref pages are retained in `.tmp/refresh-2026-10-28/conferences/raw-crossref`. The manifest is `data/refresh/conference-works-2026-10-28.json`. Current decoding provenance covers 212 Crossref files, 711 titles and 22,777 affiliation strings; changed provider text is preserved separately.

## Reconciliation after Luna recovery

The Luna recovery accepted 220 editions and restored all 775 baseline paths from verified committed LFS objects or committed empty blobs. Parent reconciliation then accepted six previously blocked editions and replaced the incomplete ICCAD 2017 source, reaching 226 editions. Publisher evidence repaired seven entries: ICCAD 2017/2022, ISIT 2016–2018, CDC 2025 and SIGCOMM 2026. See `data/refresh/conference-source-reconciliation-2026-10-28.json`.

ICCAD 2017's native source returned 65 alternative-identifier records versus 154 verified IEEE papers; the sets were not blindly unioned. ICCAD 2022's exact container has 164 article-prefix records and 55 separate session-detail DOIs. Five independently verified ISSCC/CLEO papers supplement current list-index omissions. Alternate CLEO DOI representations were not re-added. SIGCOMM 2026's 200 records include posters and demos; this is not a claim of main-full-paper-only coverage.

A further current-year discovery pass superseded stale July availability notes. Six exact publisher proceedings queries added **4,824 records**:

| 2026 edition | Records |
|---|---:|
| ISSCC | 350 |
| ISCA | 189 |
| ISIT | 574 |
| ICRA | 1,882 |
| CLEO | 1,574 |
| Joint VLSI Technology and Circuits | 255 |

The joint VLSI event follows the existing post-2021 ownership under the circuits entry and is not duplicated under the pre-merger technology key. Current-year evidence is in `data/refresh/conference-2026-accepted-2026-10-28.json`. Initial rate-limited discovery requests were retried sequentially; failed metadata requests were not interpreted as empty proceedings.

## Current-year gaps and limits

Nine other 2026 edition sources remain unverified in the registry: MICRO, DAC, ICCAD, RTSS, EMSOFT, main CVPR, CDC, ECCE and IEDM. Some events fall later in the calendar year; this report does not equate unverified availability with zero publications. `data/refresh/conference-2026-scope-notes-2026-10-28.json` records these separately from completed query scopes. ICCV has no 2026 edition under its biennial schedule; VLSI Technology's post-merger event is owned by the circuits entry; the user-recorded IMS hiatus/restructuring decision is preserved. CVPR Findings, ASP-DAC, the unrelated ICCAD acronym match, CCDC and regional/other conference lookalikes were excluded.

The earlier OpenAlex collection used 253 list calls; no optional DOI enrichment was run in this recovery. New 2026 files therefore retain publisher bylines/raw affiliations without claiming a fresh OpenAlex affiliation lookup. Earlier paper-specific evidence is retained only under checked paper/author identity; complete fresh bylines remain the denominator. Source membership, historical affiliation coverage and institutional resolution are separate limitations. ML proceedings membership remains outside this conference query plan and is documented separately.

A completed API query is not exhaustive publisher certification. The final release report records canonical transformations, coverage, comparison, local promotion and deployment. No Git commit or push was performed by this refresh.
