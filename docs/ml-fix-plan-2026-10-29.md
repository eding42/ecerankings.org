# ML area repair plan — 2026-10-29

## Recommendation

Keep `ml` at `default_on: false` until the three venues have publisher-defined
membership, paper-specific affiliation evidence, and pass the gates below. The
October 28 Semantic Scholar set is useful as a discovery/reconciliation list,
but it cannot be the membership source of truth. Replace the one-off path with
a venue-aware `harvest_ml.py`: enumerate accepted proceedings records from each
publisher, then enrich those records by DOI and, where needed, the final
publisher paper. Keep the familiar `cache/<venue>/<year>/works.jsonl` envelope
so `aggregate.py` can consume the staged output without a second aggregation
format.

The practical first ranking window should be **2017 onward**, with historical
editions staged separately and admitted only year by year after the same gates
pass. This is the first common window with dependable ICLR/OpenReview API
coverage, while ICML's PMLR source begins in 2013 and NeurIPS' official archive
goes back to 1987. ICLR 2015–2016 need special archival reconciliation, and the
pre-2013 ICML and pre-2017 NeurIPS years need separate historical affiliation
work. Do not interpret years outside the declared window as measured zeroes.

## Verified facts from the checkout and primary sources

### Why the current data are not ranking-ready

The 95 Semantic Scholar files contain **58,145 works**. Of those, **31,788
(54.7%) have no DOI**; the other 26,357 rows represent **26,355 distinct
DOIs**. The OpenAlex recovery accepted paper-level DOI/title/year matches for
**15,868 rows / 15,866 distinct DOIs**, or **27.3% of all rows**. A further
**10,489 DOI-bearing works** had no accepted OpenAlex affiliation match. The
recovery made 264 DOI batches and 305 OpenAlex list attempts, with 45 of its
350-attempt allowance unused and no retries or singleton hydration. It
preserved 78,994 complete author records for matched works. These figures are
from the October 28 recovery report and manifest; they are not publisher
membership totals.

The source baseline is missing papers as well as affiliations. OpenAlex tends
to index these works under arXiv or another repository source instead of the
conference proceedings. A source/venue query therefore misses accepted
PMLR/OpenReview papers even when an OpenAlex work is available by DOI. The
Semantic Scholar extractor also joins its author dataset and writes those
profile affiliation strings to the paper cache; the October 28 recovery
correctly moved them to a separate profile-only field and withheld them from
historical credit. The cache has not been reconciled against publisher
accepted-paper lists.

The existing OpenAlex recovery is a useful reusable component: batch distinct
DOIs, require normalized DOI plus strong title and publication-year identity,
hydrate an incomplete author list through the singleton work endpoint, retain
conflicts/gaps, checkpoint requests, and write a manifest with hashes and
counts. The existing Crossref conference harvester also demonstrates the
`works.jsonl` envelope and cursor/checkpoint pattern. Keep those identity and
resumability rules; replace S2's venue/year discovery step.

The per-edition audit table shows affiliation recovery falling far below
complete in recent years: ICLR 2025 622/1,772 (35.1%), ICML 2025 1,555/2,695
(57.7%), and NeurIPS 2025 140/3,159 (4.4%). These are S2 collector snapshots,
not the number of official accepted papers. The audit reports 58,145 works in
95 files, 26,355 distinct DOIs, 15,868 accepted backfills, 10,489 unresolved
DOI works, and 31,788 no-DOI works. See the [ML recovery note](../data-refresh-ml-2026-10-28.md)
and [recent completeness audit](../review/2026-10-29-recent-completeness-audit.md).

The current `site/data/ml.json` contains **2,788 institution/year aggregate
rows** over 39 years from 1987 to 2026. Those are derived ranking outputs, not
a count of accepted papers; they cannot establish publisher-list completeness
and include gaps in the year sequence.

### Membership sources and verified year coverage

| Venue | Membership authority | Earliest coverage / caveat | 2025 official reference |
|---|---|---|---|
| NeurIPS | The official [proceedings archive](https://proceedings.neurips.cc/) and its linked proceedings books. The archive lists NIPS 1987 through NeurIPS 2025. | **1987** for archived proceedings membership. The archive distinguishes the 2021 Datasets & Benchmarks volume; from 2022 that track is inside the main proceedings. Preserve track labels and exclude workshops and the separate 2025 Creative AI book unless the area scope explicitly adds them. | The NeurIPS 2025 main-conference book lists **5,823 papers** across its listed tracks. The official program-chair report separately says **5,290 accepted main-track papers**. These are not interchangeable totals: reconcile track membership and state which track set the ranking includes. [Proceedings book](https://proceedings.neurips.cc/paper_files/paper/2025/vol38-main-conference) · [NeurIPS fact sheet](https://media.neurips.cc/Conferences/NeurIPS2025/press/NeurIPS2025-Fact_Sheet.pdf) · [Program-chair report](https://blog.neurips.cc/2025/09/30/reflections-on-the-2025-review-process-from-the-program-committee-chairs/) |
| ICML | One official PMLR volume per ICML edition at [proceedings.mlr.press](https://proceedings.mlr.press/). | **2013** is the first ICML volume in PMLR (volume 28). ICML proceedings exist earlier, but those editions are not in PMLR; 2010 proceedings are on the official ICML site and pre-2013 volumes need an older-source adapter. Do not use Crossref's fuzzy `ICML` container-title search as membership: it returns lookalikes such as ICMLA/ICMLC. [PMLR volume 28](https://proceedings.mlr.press/v28/) | ICML's 2025 fact sheet reports **3,260 main-track papers accepted**. Compare the PMLR volume 267 paper IDs/titles with that track-specific total; workshops are separate and excluded. [ICML 2025 fact sheet](https://media.icml.cc/Conferences/ICML2025/ICML2025_Fact_Sheet.pdf) · [PMLR volume 267](https://proceedings.mlr.press/v267/) |
| ICLR | OpenReview accepted conference submissions, reconciled to the official [ICLR proceedings archive/FAQ](https://iclr.cc/FAQ/Proceedings). | **2013** is the earliest official accepted-paper list. The ICLR FAQ says accepted papers for 2013–2025 are on OpenReview. API history is not uniform: 2013–2014 use legacy API/invitation forms; the public venue listing omits 2015 and shows 2016, and an API study reports that 2015 is unavailable and 2016's page is workshop-only. Recover 2015–2016 from official archived proceedings/title lists and treat them as exceptions, not as a clean API range. **2017 onward** is the recommended initial continuous window. [OpenReview venue list](https://openreview.net/venue?id=ICLR.cc) · [OpenReview API versions](https://docs.openreview.net/getting-started/using-the-api) · [ICLR API coverage study](https://openreview.net/pdf/93dcbe29d119b89ce59796ae38f793cbbce787dd.pdf) | The ICLR 2025 fact sheet reports **3,704 accepted**; the official proceedings book currently lists **3,703 papers**. Reconcile the one-record difference against accepted OpenReview IDs and the final proceedings list before setting the expected count. Exclude workshops, blog posts, tiny-paper tracks, and other side venues. [ICLR 2025 fact sheet](https://media.iclr.cc/Conferences/ICLR2025/ICLR2025_Fact_Sheet.pdf) · [ICLR 2025 proceedings](https://proceedings.iclr.cc/paper_files/paper/2025) |

The NeurIPS 5,823 figure is the official book's total, not the fact sheet's
main-track-only accepted count. The ICLR 3,704/3,703 difference is a real
reconciliation item; do not silently pick one. Official ICLR 2025 fact-sheet
and proceedings pages support those respective figures. Treat both examples
as scope checks, not values to hard-code without comparing record IDs.

### Affiliation evidence: what counts

1. **OpenAlex by DOI (preferred when present).** Use the work's `authorships`
   array and accept only exact normalized DOI plus title/byline/year identity.
   OpenAlex documents an authorship as a *work-author join* with the raw
   affiliation text printed on the work and institution resolution. This is
   paper-specific evidence even when OpenAlex classifies the work's source as
   arXiv; use it to enrich the publisher's canonical membership row, never to
   decide membership. [OpenAlex authorships](https://help.openalex.org/data/authorships/)
2. **Crossref by DOI (secondary structured source).** Crossref exposes the
   publisher-deposited record; some publishers deposit author affiliations and
   many do not. Use a populated affiliation only when attached to that DOI's
   author record, preserve its raw text, and resolve institutions with the
   existing local normalization workflow. Crossref remains an unreliable
   membership source for these three venues. [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api)
3. **Final publisher PDF / paper page (fallback, especially for no-DOI works).**
   Extract the author-by-author affiliation block from the *accepted/final*
   PMLR, NeurIPS, or ICLR proceedings paper. Preserve the PDF/page URL and
   extracted string, and route uncertain author-to-affiliation mappings to
   review. Batch text extraction first; OCR only image-only PDFs. OpenReview
   author IDs or author profiles alone are not paper-level evidence.
4. **DBLP signature affiliations (optional cross-check).** Update the old
   premise that DBLP has no affiliations: since September 2026 DBLP reports
   both manually curated person affiliations and automatically extracted
   signature (paper-author) affiliations. It says signature affiliations
   cover about 60% overall, coverage is uneven and more recent data are still
   processing; DBLP itself warns against institution rankings. Use signature
   affiliations only as a sourced secondary cross-check, never to fill a
   historical gap without per-edition coverage validation. [DBLP affiliation
   launch and limits](https://blog.dblp.org/2026/09/21/institutions-as-first-class-citizens-introducing-affiliations-in-dblp/)

**Never credit OpenReview or Semantic Scholar author-profile affiliations as
historical paper affiliations.** An author profile says where the person is
associated now (or during a profile snapshot), not where they were when this
paper was published. The S2 API documents affiliations on author objects, and
the repository's S2 baseline similarly reads affiliations from the separate
author shard; neither establishes the affiliation on a particular paper.
Keep those values, if useful, in profile-only audit metadata. Do not copy them
into `raw_affiliations` or `institutions`. [Semantic Scholar Academic Graph
API](https://api.semanticscholar.org/api-docs/graphs)

CSRankings uses DBLP as its publication source and splits credit across all
coauthors; institution attribution comes from its maintained faculty roster
and DBLP author identities, not from every paper's publisher affiliation
metadata. It answers a different question (current eligible faculty's
publication counts), not historical institution attribution across all paper
authors. Historically, DBLP primarily indexed bibliographic records and did
not systematically attach affiliations to publication-author signatures;
publishers often did not supply that metadata, and DBLP says affiliations are
difficult to determine. Its person-page affiliation notes were not per-paper
history. As of September 2026 DBLP has added both person affiliations and
signature-level affiliations, but the latter's uneven 60% coverage and DBLP's
own warning still make it a cross-check, not the corpus authority.
[CSRankings FAQ](https://csrankings.org/faq) · [DBLP affiliation launch and
limits](https://blog.dblp.org/2026/09/21/institutions-as-first-class-citizens-introducing-affiliations-in-dblp/)
· [DBLP affiliation metadata FAQ](https://dblp.org/faq/How%2Bare%2Bdata%2Bannotations%2Bused%2Bin%2Bdblp%2Bxml.html)

## Proposed implementation: `pipeline/harvest_ml.py`

This is a design sketch, not an implementation request.

### Inputs and source adapters

- CLI: `--venue {iclr,icml,neurips}`, `--year` or `--year-range`,
  `--cache-dir`, `--manifest`, `--resume`, and optional `--membership-only` /
  `--enrich-only`.
- Each adapter retrieves the official accepted/proceedings list and emits
  canonical records with publisher paper ID/URL, normalized title, ordered
  authors, edition year, track, and DOI if supplied. Keep the raw publisher
  response or page reference in the manifest for audit.
- **ICLR:** query accepted records by year-specific OpenReview venue ID and
  accepted decision/venue ID. Use API v1 for legacy editions and API v2 for
  current editions, with a year configuration rather than guessed uniform
  invitation strings. For 2015–2016, use the official archived final-paper
  lists and reconcile IDs/titles manually if API records are missing.
- **ICML:** enumerate only the ICML edition volume from PMLR (2013+), not every
  workshop volume; store volume number and each article's canonical slug/DOI.
  Treat 2010–2012 as a separate pre-PMLR adapter and exclude from the first
  enabled window.
- **NeurIPS:** enumerate official edition book records from the proceedings
  archive, retain volume and track labels, and apply an explicit configured
  include/exclude list. Exclude workshop proceedings and the separate Creative
  AI book by default. Preserve the 2021 Datasets & Benchmarks split; from 2022
  use its track label within the main proceedings.

### Staging, DOI enrichment, and deduplication

1. Stage membership first at
   `cache/<venue>/<year>/works.jsonl`; do not write the production cache during
   collection. Keep an adjacent per-edition manifest/checkpoint with source
   URL/version, official list count, page cursor, included/excluded track
   counts, duplicate counts, DOI counts, SHA-256, and completion status.
2. Represent each canonical accepted paper once. Set `source` to the venue
   proceedings adapter, `publication_year` to the conference edition year,
   `type` to `proceedings-article`, and preserve membership ID/URL/track in
   extra fields. The standard `id`, `doi`, `title`, and `authorships` fields
   remain compatible with `aggregate.py`.
3. Deduplicate the publisher set by DOI first; when DOI is absent, use exact
   publisher paper ID/URL, then normalized title plus ordered author names as
   a reviewable fallback. Never add an arXiv record as a second corpus item:
   the official proceedings row is canonical, and an OpenAlex/arXiv version
   may only supply identity-checked authorship evidence for that row. Keep
   DOI/title/byline/year conflicts visible rather than merging silently.
4. Batch distinct DOI lookups against OpenAlex using the pattern in
   `refresh_ml.py`; require DOI/title/year identity, verify returned byline
   order/count, and hydrate truncated OpenAlex author lists. If OpenAlex is
   absent or affiliations are empty, inspect DOI-specific Crossref metadata,
   then the final proceedings PDF. Store affiliation provenance per author
   (e.g. `openalex-work`, `crossref-doi`, `publisher-pdf`, `dblp-signature`),
   raw text, resolved institution IDs, and extraction confidence. Profile
   evidence lives under an explicitly profile-only field and never populates
   historical attribution.
5. Checkpoint membership pagination and DOI batches independently. A restart
   must resume from the last committed cursor/batch, retain useful partial
   work, and never count a request failure as a negative lookup. Write each
   output atomically after its completed stage; emit input/output hashes and
   reconciliation totals like `refresh_ml.py`.
6. For no-DOI papers, publisher PDF author blocks are the main fallback.
   Keep `vt:<venue>|<year>|<normalized-title>` identity available through the
   existing `workkey.py` convention. Extract affiliations from the final
   paper PDF, not a current profile or an anonymous review submission.

OpenReview documents its venue ID in the submission page URL and maintains
both API v1 and v2; older venues still use v1. It does not publish a simple
fixed request-rate budget on the docs page, and its terms allow service-side
limits. Use serial/low-concurrency pagination, honor `Retry-After`, back off
on 429/5xx, cache raw responses, and pilot one year before scheduling the
full backfill. [OpenReview venue IDs](https://docs.openreview.net/getting-started/frequently-asked-questions/how-do-i-find-a-venue-id) · [API versions](https://docs.openreview.net/getting-started/using-the-api) · [Terms](https://openreview.net/legal/terms)

## Coverage gates before `default_on: true`

Apply every gate per venue-year and publish a machine-readable reconciliation
in the refresh manifest. The numeric targets below are **proposals**.

| Gate | Proposed threshold |
|---|---|
| Publisher membership | At least **99%** of included official accepted-paper IDs/titles represented, and at least **99%** of cached rows reconciled to an official included record. No unexplained extra workshop, rejected, duplicate, or preprint-only row. Record exact scope differences by track; a count alone cannot satisfy this gate. |
| Official count anchor | Reconcile count and IDs against the official per-track list. Specifically explain NeurIPS 2025's 5,823 proceedings-book entries versus 5,290 fact-sheet main-track accepts, ICML's 3,260 main-track accepted papers, and ICLR's 3,704 fact-sheet accepts versus 3,703 proceedings entries. Allow no more than **1%** unexplained difference after track definitions are aligned. |
| Paper-specific affiliations | At least **90% of author slots** have a paper-specific affiliation string or institution from OpenAlex-by-DOI, Crossref-by-DOI, or the final publisher paper. Do not count profile affiliation fields. Report coverage both by author slot and by paper. |
| Institution resolution | Resolve or manually adjudicate at least **95%** of paper-specific affiliation strings. Keep source-text coverage separate from OpenAlex institution resolution; unresolved companies/non-education organizations may remain uncredited under current aggregation policy. |
| Identity and byline integrity | Every DOI match passes normalized DOI, strong title, year, and author/byline checks; no silent conflicting DOI, title, year, track, or author count. Full author list is present, not truncated. |
| Scope purity | Every row has an official membership ID/URL and allowed track. No workshop or duplicate arXiv version survives sampling. Audit at least 100 titles per large venue-year (or all entries below 100) and all exceptions. |
| Ranking tripwire | Add known-strong ML institutions to `data/known-strong.json` as a separate later change; require every configured institution to have nonzero ML credit and inspect any zero before turning the area on. |
| Window completeness | All three venues pass every year in the declared initial window (recommend 2017–2025); 2026 stays partial/staged until its official inventory is complete. Older years are either separately gated or explicitly outside the reported ML window. |

The `known-strong` check must test data plumbing, not assert a desired rank.
Choose institutions only after the corpus passes membership and affiliation
audits, using a diverse sample of expected institutions visible in the
verified papers. Do not edit the tripwire as part of this research plan.

## Effort and execution order (proposal)

- **ICLR first for the pilot (moderate effort):** implement the OpenReview
  adapter against 2025, reconcile 3,704 vs 3,703, then 2024 and the 2017–2023
  years. Expect tens of paginated public API requests for the recent window,
  depending on page size; calls are per-page/year, not per paper. Separately
  recover 2015–2016 from official archives if desired.
- **ICML second (low-to-moderate membership effort):** parse the PMLR edition
  volumes, beginning with 2025 volume 267 (3,260 main-track accepts) and then
  2013–2024. The main uncertainty is affiliation recovery from DOI metadata or
  PDFs, not PMLR membership. Keep pre-2013 editions out of the first window.
- **NeurIPS third (moderate-to-high effort):** adapter for official books is
  straightforward, but track transitions and the 1987–present archive make
  scope QA and historical PDF affiliation work largest. Pilot 2025 first and
  resolve track counts before applying the parser to all years.
- **OpenAlex budget:** the existing S2 DOI universe took 264 distinct-DOI
  batches (305 list attempts, including pagination). The new publisher-defined
  2017–2025 corpus is likely on the order of **40k–55k papers** across these
  venues; with a planning assumption of 45–60% DOI availability, budget roughly
  **180–330 batches of up to 100 DOIs**, plus pagination/retries (plan for
  **250–450 list attempts**). This is an estimate, not a measured API quote;
  use a 2025 pilot to replace it with observed DOI rate, match rate, pagination,
  and retry counts before the full run.
- **Affiliation recovery effort:** expect publisher-PDF extraction and QA to
  dominate cost: roughly **16k–30k no/weak-DOI records** under that planning
  range, plus the existing 10,489 DOI-bearing OpenAlex misses. Prefer bulk
  text extraction, not OCR; manually review low-confidence author mappings.
  Do not use OpenReview or Semantic Scholar profiles to close the gap.
- **OpenReview operation:** no fixed public rate figure was established from
  the official docs during this review. Keep calls low-concurrency, paginated,
  resumable, and polite; API v1/v2 changes and the 2015–2016 holes make ICLR
  the highest API-maintenance risk, even though it is the best first pilot.

Suggested phase sequence: (1) freeze track policy and define the 2017–2025
window; (2) implement ICLR 2025 membership-only pilot and manifest, then add
DOI/PDF affiliations; (3) finish ICLR window, measuring 2015–2016 archival
recoverability; (4) add ICML PMLR membership/affiliation; (5) add NeurIPS
track-aware membership/affiliation; (6) reconcile all three against official
lists, rerun aggregation in isolated staging, review gate report and tripwire,
then separately decide whether to promote the area. No registry/cache/site
changes are part of this plan.

## Decision summary

The root cause is two separable errors: **source-driven discovery does not
represent publisher acceptance** for these proceedings, and **profile
affiliations are not historical paper affiliations**. Fix membership with the
publisher's canonical edition list; fix affiliation attribution with a
paper-specific DOI join and final-paper fallback. Once official membership,
historical affiliations, and all gates are measured, the user can make a
defensible decision about `default_on` and the supported historical window.
