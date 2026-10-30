---
name: collect-venue-data
description: Add or re-verify a venue (or an area's venues) in data/areas.json — establish where its authoritative paper list lives (OpenAlex source, Crossref DOI prefix, or the publisher's own proceedings), prove membership against an official count, measure paper-specific affiliation coverage, and register it; then, only with consent, harvest into a staged tree. Use for any "collect/verify/research data for <area or venue>" task.
---

# Collect venue data

You are doing data collection for ecerankings.org. The methodology is settled (`PLAN.md`, `CLAUDE.md`). Do not redesign areas, add venues nobody asked for, or change counting rules.

**Scope** is the area key or venue the user named, and nothing else. **Default years** are the last 10 completed years, computed from `date +%Y`. The current year is a separately labelled partial observation. State the window you used in the report.

## The question that decides everything: who defines membership?

A venue's ranking is only as good as its paper list. The July 2026 version of this skill assumed OpenAlex source IDs define that list. **For ML they did not:**
- OpenAlex attributes ICLR, ICML and NeurIPS papers to arXiv;
- the Semantic Scholar venue tag had 1,772 ICLR 2025 rows against 3,703 official papers;
- `ml` shipped with these gaps while every check passed.

Settle membership first, for one or two recent editions, before anything else.

1. **Find an official count** for a recent edition. Sources, in order of preference:
   - the publisher's table of contents or proceedings site;
   - the conference fact sheet;
   - the program-chair report.

   Record the URL and what the number counts: the main track or all tracks, papers or abstracts.
2. **Count each candidate source** for that same edition.
   - **OpenAlex:** `/works?filter=primary_location.source.id:S…,publication_year:Y&group_by=publication_year`.
   - **Crossref:** exact `filter=container-title:…`, validated by DOI prefix.
   - **The publisher list itself.**
3. **The authority is the first source that reaches ≥99% of the official count, with matching titles:**

| Authority | Typical venues | Harvest path |
|---|---|---|
| OpenAlex source ID | Journals; venues OpenAlex indexes as their own source | `pipeline/harvest.py` |
| Crossref container-title + DOI prefix | IEEE/ACM conferences whose OpenAlex works have `primary_location.source = null` | `pipeline/harvest_crossref.py`, then `backfill_openalex.py` (DOI join for affiliations) |
| Publisher proceedings list | Venues on their own sites: PMLR, proceedings.neurips.cc, proceedings.iclr.cc / OpenReview, likely CVF open access | A publisher adapter in the `pipeline/harvest_ml.py` pattern: membership from the publisher, OpenAlex/arXiv/PDF for enrichment only |

If no source reaches 99%, the venue stays `candidate`, and you report the best coverage achieved and why. A complete API response proves the API is complete, **not** that the publisher's list is.

## Facts that cost this project real time; don't relearn them

- **OpenAlex conferences lag about 2 years**, and many IEEE conference works have no `primary_location.source`. Check Crossref before calling a year missing.
- **Crossref's `query.container-title` is fuzzy.**
  - Use the exact `filter=container-title:` and validate every DOI against the edition's prefix.
  - Never use a fuzzy title search as membership; ICML's search returns ICMLA and ICMLC.
- **Lookalike venues**, which you reject:
  - regional or workshop variants;
  - "Companion" or "Adjunct" proceedings;
  - EDSSC instead of ISSCC;
  - predatory "International Journal of …" titles.

  When unsure, put it under "Needs human review", never into the registry.
- **Tracks are part of identity.** Record each track and include only the ones the registry allows. Examples:
  - NeurIPS 2025 = 5,286 Conference + 497 Datasets & Benchmarks (included) + 40 Position (excluded);
  - workshops are always excluded.
- **Semantic Scholar** is an identifier lookup only.
  - Its venue tags never define membership, and its author-profile affiliations are never credited.
  - Bulk search works without a key; per-title match without a key mostly returns 429.
- **OpenReview** anonymous API calls get a 403 bot challenge. Authenticated calls work, with the login ID being the account **email** and credentials in `.env`.
- **The arXiv API** allows one request every 3 seconds on a single connection (its Terms of Use). For bulk metadata, use OAI-PMH or the Kaggle snapshot.
- **OpenAlex budget:** about $1/day, credit-based. A DOI list call is 1 credit. A `title.search` call is 10 credits ($0.001). Send `mailto` and the key from `.env`, never log the key, and prefer `group_by` over paging.

## Verification checklist (per source you register)

1. **Identity:** 5 titles from a recent edition read as this venue's field, and the host organization matches.
2. **Membership:** the count reconciles with the official count, to within 1%, after aligning track definitions. Record the semantics of both numbers. `expected_per_year` is a coarse sanity range, not an anchor.
3. **Year coverage:** every in-window year has a source, or the gap is explained (cancelled or biennial venue, not yet held).
4. **Affiliation evidence:** measure on the harvested or staged edition, not on a 25-work sample presented as all years. Count only paper-specific evidence:
   - OpenAlex work-author joins;
   - Crossref affiliations deposited for that DOI;
   - the final publisher PDF.

   Report author-slot coverage. Any sampled figure must be labelled as sampled.
5. **Institution sanity:** the top 10 institutions over recent years look like the subfield's known leaders. Industry labs are fine; they are filtered at aggregation.

`verified` means identity, membership, and year coverage pass and the harvest path is known. Low affiliation coverage on a correct source is a data-quality finding, not an identity failure: report it, and leave `default_on` decisions to the user.

## Registry update and report

**Registry update:**
- **Single venue:** edit the entry in `data/areas.json` yourself. Set:
  - `openalex_ids`;
  - per-year `years{}` (with `source`, `doi_prefix` and `container_title` where they apply);
  - `status`;
  - a `notes` field that cites the membership authority and the count reconciliation.
- **An area with two or more venues:** fan out one subagent per venue, with every call for a wave in one message and waves of about 4. Workers never edit `data/areas.json`. Each worker returns:
  ```json
  {"key": "...", "status": "verified|candidate",
   "membership_authority": "openalex|crossref|publisher",
   "official_count": {"edition": 2025, "count": 0, "scope": "...", "url": "..."},
   "observed_count": 0, "openalex_ids": [], "years": {}, "notes": "...",
   "needs_review": []}
  ```
  You merge all returned entries in one pass. A missing or malformed result leaves that venue untouched and is noted.
- Never invent IDs. Never mark `verified` without running every check.

**Report:** write `data/reports/<scope>-<YYYY-MM-DD>.md` with these sections:
- **Summary:** window, authority per venue, confidence.
- **Venues table:** sources, membership authority, official vs observed count, years covered, affiliation coverage (labelled sampled or measured), status.
- **Gaps:** each gap with its explanation.
- **Top-10 institutions.**
- **Needs human review:** write "None." if empty.

## Harvest: ask first, stage, never overwrite live data

Steps above only resolve and register. Harvesting is a separate step that needs consent.
- Ask once per run, from the top-level agent, after registry and report are done. The options:
  - verified venues only;
  - include candidates, with their issues stated;
  - stop.

  If the user has already authorized fetching for this scope in the session, don't ask again.
- **Stage into an isolated tree with a manifest; don't write `cache/` directly for a refresh:**
  - publisher-path venues use `harvest_ml.py`-style staging (`--stage-root`);
  - conference refreshes use `pipeline/refresh_conferences.py --output <dir>`.

  Every venue-year needs a result row: status, counts, SHA-256, and gaps. An HTTP failure is a failure, never an empty result. Promotion into the live cache (`prepare_refresh.py` / `promote_release.py`) is a separate, user-approved step.
- **After harvest:**
  1. `backfill_openalex.py`, for Crossref- and Semantic-Scholar-sourced works;
  2. the `adjudicate-affiliations` skill, for new raw strings: `python3 pipeline/adjudication.py queue --cache-dir <staged> --only-unmapped`;
  3. the `verify-data` skill with `--cache-dir <staged>`.
- **Report what was actually harvested:** venue, years, work counts, which tool handled each year, and coverage. Not just "done".

## Hard rules

- Scope stays the requested venues. Put ambiguity in "Needs human review"; don't block and don't guess.
- Only paper-specific affiliation evidence is ever credited.
- One writer per file: workers return proposals, and one integrator writes the registry.
- Never commit or push. Stage changes and summarize them for the user (see CLAUDE.md).
