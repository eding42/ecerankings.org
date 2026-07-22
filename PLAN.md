# ECERankings.org — Implementation Plan

A metrics-based ranking of Electrical & Computer Engineering programs, modeled on
[CSRankings](https://csrankings.org) but built for how ECE actually publishes
(journal-heavy, IEEE-centric), using [OpenAlex](https://openalex.org) as the
primary data source.

## Why this architecture

CSRankings' lesson: the site is static; all ranking math runs in the browser over
a pre-computed CSV. The hard assets are (1) a curated venue list per area and
(2) a faculty→institution database. We keep the static-site architecture, but
replace DBLP with OpenAlex because:

- DBLP is CS-centric — weak on core-EE journals (power, devices, EM, photonics).
- OpenAlex covers all IEEE/Optica venues and ships **author→institution
  affiliations per paper** (~98% coverage in our probes), which lets us bootstrap
  without CSRankings' decade of crowdsourced faculty CSVs.
- Known risks (validated by probing): conference proceedings are fragmented into
  per-year source IDs; affiliation strings occasionally misparse. We accept these
  for v1 and keep a manual-override layer for when we must hand-curate.
- **OpenAlex conference ingestion lags ~2 years.** Probed on IEDM: 2021/2022
  exist as proper per-year sources; 2023/2024 do not (confirmed absent —
  searched every plausible name variant). Same pattern on ISSCC/DAC/ISCA.
  Journals are unaffected (JSSC, T-ED, etc. are current through 2024/2025).
  Crossref, which OpenAlex ingests from, already has 2023/2024 IEDM with
  clean per-author affiliation strings (100% coverage in a sampled check) —
  see Phase 1b.

## Ranking methodology (ported from CSRankings)

- **Adjusted count**: each paper is worth 1.0, split evenly across its N authors
  (1/N per author). Institution credit = sum over its authors' shares.
- **Institution score** = geometric mean of (1 + adjusted count) across the
  *selected* areas — rewards breadth, resists single-area dominance.
- **No citations** — publication counts at selective venues only (hard to game).
- **Education-only**: filter OpenAlex institutions to `type=education`
  (drops Samsung/Intel/Qualcomm research labs). Keep a manual allow/deny list.
- **Two attribution modes, both first-class (not a v1-vs-fixed split)**:
  CSRankings credits a faculty member's *entire career output* to their
  *current* institution (one hand-curated CSV, one affiliation per person;
  when someone moves, a PR retroactively re-credits their whole back catalog
  to the new school). That measures **cumulative career track record of the
  current roster** — a talent-acquisition/retention metric, erasing where the
  work actually happened.

  We instead default to crediting each paper to whatever institution the
  author listed **on that specific paper** (affiliation-at-publication-time).
  That measures **output realized under an institution's banner, at the time
  it happened** — a blend of "who was there" and "what that place enabled
  during that period," without letting a person's later reputation carry
  earlier institutions' contributions forward (or backward).

  Neither is more correct; they answer different questions. Both will be
  exposed as a toggle on the site, named for what they literally do rather
  than implying one is authoritative:
  - **"At Time of Publication"** (default) — implemented; this is exactly
    what `pipeline/aggregate.py` computes today, validated end-to-end on the
    IEDM 2022 pilot.
  - **"Current Faculty"** — not yet implemented, but does not require
    CSRankings' decade of crowdsourced curation. OpenAlex's own author
    records expose `last_known_institutions` (confirmed via spot-check) plus
    a full `affiliations` history with per-institution year ranges. The path:
    batch-resolve `last_known_institutions` for every author_id already in
    our cached works (`/authors?filter=ids.openalex:A1|A2|...`, ~50/call),
    then re-run the same aggregation keyed on that institution instead of the
    per-paper one. Known rough edge: `affiliations` includes noisy single-year
    entries (visiting stints, one-off collaborations) that a naive "most
    recent" read would need a threshold (e.g. ≥2 distinct years) to filter
    out before treating something as a real faculty appointment.

## Proposed area taxonomy (v1)

Areas mirror how ECE departments organize. 2–4 flagship venues per area,
journals + flagship conferences. Venue list lives in `data/areas.json` — the
single most important curated file in the project.

| # | Area | Key venues (journal / conference) |
|---|------|-----------------------------------|
| 1 | Circuits & VLSI | JSSC / ISSCC, VLSI Symp. |
| 2 | Computer Architecture | — / ISCA, MICRO, HPCA, ASPLOS |
| 3 | Design Automation (EDA) | TCAD / DAC, ICCAD |
| 4 | Embedded & Real-Time Systems | TECS / EMSOFT, RTSS, RTAS |
| 5 | Signal Processing | T-SP, JSTSP / ICASSP |
| 6 | Image Processing & Vision | T-IP / (CVPR, ICCV — optional toggle, CS overlap) |
| 7 | Communications & Information Theory | T-COM, TWC, JSAC, T-IT / ISIT |
| 8 | Networking | IEEE/ACM ToN / INFOCOM |
| 9 | Control Systems | TAC, Automatica / CDC |
| 10 | Robotics | T-RO / ICRA, RSS |
| 11 | Power Electronics | TPEL, JESTPE / ECCE, APEC |
| 12 | Power & Energy Systems | TPWRS, T-Smart Grid / — |
| 13 | Semiconductor Devices | T-ED, EDL / IEDM, VLSI Tech. |
| 14 | Photonics & Optics | JLT, Optica / CLEO |
| 15 | Electromagnetics, Antennas & RF | T-AP, T-MTT / IMS |
| 16 | MEMS & Microsystems (optional) | J-MEMS / IEEE MEMS |
| 17 | Hardware Security (optional) | T-IFS, T-Info Forensics / CHES, HOST |
| 18 | Machine Learning (optional, default-off) | — / NeurIPS, ICML, ICLR |
| 19 | Biomedical Engineering (optional) | T-BME / — |
| 20 | Quantum Engineering (optional) | npj Quantum Information, PRX Quantum, Quantum Science and Technology / — |
| 21 | Nature family — ECE (optional) | Nature Electronics, Nature Photonics, Light: Sci. & Appl. |

Deferred: audio/speech (fold into SP for now).

## Venue-inclusion policy

A venue joins an area only if it passes both tests:
1. **Selectivity**: among the hardest places to publish in that subfield.
2. **Scope**: its content is substantially (~>80%) within the area, so counting
   *everything* in it imports no noise. Scoping is done by journal choice,
   never by per-paper topic classification — the venue list must stay 100%
   auditable ("you can check every paper we counted").

Consequences:
- **Field-scoped Nature children** (Nature Electronics ~200 papers/yr,
  Nature Photonics ~230, Light ~310 — all brutally selective and ~100%
  in-scope) are first-class venues. Rather than mixing them into Devices/
  Photonics, they form their own toggleable area ("Nature family — ECE") so
  subfield areas stay purely IEEE/Optica and comparable to how those
  communities self-evaluate, while flagship-tier output is visible as its own
  axis. Nature Nanotechnology is borderline (~half chemistry/bio) — out of v1.
- **Multidisciplinary parents are excluded** (Nature, Science, Science
  Advances, Nature Communications). Probed: parent Nature 2024 is ~88% non-ECE
  (Medicine 19%, bio 15%, social science 9%...); since v1 credits institutions
  (not departments), including them would rank schools by biomedical output.
  Phase 4 option: once the ECE author universe exists, count parent-Nature/
  Science papers only when authored by someone who also publishes in
  registered ECE venues — an author-level filter that stays explainable,
  unlike a topic classifier.
- **Within-area volume balance**: venues in one area should have roughly
  comparable volume/selectivity (CSRankings' rule). Where a field has a
  high-volume workhorse journal (e.g., T-ED ~1,200/yr) next to selective
  flagships (IEDM, EDL), use a default-on top tier and a toggleable
  second tier ("below the line") rather than letting bulk volume dominate.

Open questions to settle with the community: split vs. merge power areas;
whether CS-overlap areas (architecture, ML, vision) default on or off;
second-tier venue tiers (CSRankings' "below the line" venues).

## Data model

```
pipeline outputs (checked into repo, served statically):

inst-area-year.csv     institution_id, area, year, pub_count, adjusted_count
author-info.csv        author_id, name, institution_id, area, year, adjusted_count
institutions.csv       institution_id, display_name, country, region, homepage, type
areas.json             area -> { name, venues: [ {openalex_source_ids | title_patterns,
                                                  type, notes} ] }
overrides/             manual corrections: venue-id fixes, institution merges,
                       author aliases, exclusions
```

## Phases

### Phase 0 — Feasibility probes ✅ (done)
- OpenAlex has all 29 probed flagship venues; journals have single stable IDs.
- 98% authorship→institution coverage on JSSC 2023 sample.
- `group_by=authorships.institutions.lineage` sanity-check ranking looks right.
- Confirmed: conferences fragment into per-year sources; industry labs need filtering.

### Phase 1 — Venue registry + harvester
1. `data/areas.json`: curate every area's venues. For journals: pin OpenAlex
   source IDs. For conferences: a `resolve-venues.py` script that searches
   OpenAlex sources by title pattern, proposes per-year proceeding IDs, and
   writes them to the registry for human review (this is the accepted
   manual-curation surface).
2. `pipeline/harvest.py`: year-native harvester, one year per invocation
   (`--venue X --year YYYY`, or `--all-years` to sweep everything in the
   venue's `years{}` registry entry). Cursor-paged, resumable, `per-page=200`,
   polite-pool mailto, cached to `cache/<venue>/<year>/works.jsonl` so re-runs
   and partial backfills are both free. Chunking by year (not just by venue)
   was a deliberate choice: it mirrors how the registry already tracks
   per-year source availability (some years OpenAlex, some Crossref-only),
   lets a multi-decade backfill be done and inspected incrementally, and
   keeps a single invocation's blast radius to one year if something's wrong
   with a specific year's source.
3. Estimated volume: ~300–800k works → a few thousand API calls — comfortably
   inside OpenAlex rate limits (10 req/s, 100k/day). No API key needed.

### Phase 1b — Crossref fallback

Purpose: cover conference years OpenAlex hasn't linked to a source. Revised
2026-07-19 after a 10-year IEDM sweep (2016-2025): originally framed as
patching "the newest 1-2 years," but the sweep found only 2 of 10 years
(2021, 2022) have real OpenAlex per-year sources — the other 8 needed
Crossref. **Simple rule, no lag-modeling**: try OpenAlex, if a year's not
there, use Crossref. An early theory that OpenAlex retains richer "orphaned"
work records (no source link, but full resolved institutions) for missing
years was tested and dropped — institution resolution on those orphaned
records was inconsistent (fully resolved for some DOIs, empty for others),
not reliable enough to build a special path around. Crossref-as-fallback is
simpler and just as effective.

1. `data/areas.json` tracks source availability **per year** via each
   venue's `years{}` object: `{"2023": {"source": "crossref", "doi_prefix":
   "10.1109/iedm45741.2023", "count": 231}, "2022": {"source": "openalex",
   "id": "S4363605317", "count": 230, ...}, ...}`. DOI prefixes are NOT
   constant across years for a venue (IEEE reassigns a different `iedmXXXXX`
   identifier each edition) — a single venue-level prefix field doesn't
   work; this must be tracked per year.
2. `pipeline/harvest_crossref.py` mirrors `harvest.py`'s
   `--venue X --year YYYY` interface. For years registered `source:
   "crossref"`, queries `api.crossref.org/works?query.container-title=<venue
   name>&filter=from-pub-date:YYYY-MM-DD,until-pub-date:YYYY-MM-DD,type:
   proceedings-article` (no key; add `&mailto=...`), verifies hits by DOI
   prefix (`query.container-title` is fuzzy full-text search and can return
   large numbers of false positives), writes to the same
   `cache/<venue>/<year>/works.jsonl` layout as the OpenAlex path.
3. Crossref gives free-text affiliation strings per author, not resolved
   institution IDs (e.g. `"KAIST,School ofElectrical Engineering,Daejeon,Korea"`).
   `pipeline/normalize_affiliations.py` strips department/city/country noise
   and fuzzy-matches the remainder against `institutions.csv`; unmatched
   strings get logged to `overrides/unmatched-affiliations.csv` for manual
   mapping (grows the override layer, same as CSRankings' human-curated data).
4. Each cached work is tagged with its source (`openalex` or `crossref`) so
   QA and future backfills can find Crossref-sourced years; if OpenAlex ever
   links a source for a year already covered via Crossref, re-harvesting
   that year via `harvest.py` and updating the registry's `years{}` entry
   supersedes it on the next `aggregate.py` run.
5. Rejected: **IEEE Xplore API** as a data backbone. Checked its Terms of Use —
   non-commercial/institution-internal use only, no bulk storage, no
   redistribution, no bulk display ("only in response to an individual
   query"). Directly incompatible with a cached, published, static-site
   pipeline. Not usable even as a fallback.

### Phase 2 — Aggregation
1. `pipeline/aggregate.py`: works → (institution, area, year) adjusted counts;
   institutions resolved via lineage (credit parent university), filtered to
   `type=education`, deduped per paper (one author twice ≠ double credit;
   multi-affiliation authors split their share).
2. Emit the three CSVs + a compact gzipped JSON for the frontend.
3. QA notebook: compare our top-20 per area against known dept strengths;
   spot-check 10 random papers per area for venue correctness.

### Phase 3 — Frontend (static site)
1. Single-page app, CSRankings-style: area checkboxes grouped by cluster
   (Circuits/Hardware, Signals/ML, Comms/Networking, Power/Energy, Devices/Photonics,
   Systems/Control), year-range slider, region filter, expandable
   school → authors → per-area counts.
2. Plain TypeScript compiled to one JS bundle; no framework; data loaded from
   the static CSVs. Geometric-mean scoring computed client-side (identical to
   CSRankings so results are explainable).
3. FAQ page documenting methodology, differences from CSRankings, and known
   data caveats. Deploy on GitHub Pages behind ecerankings.org.

### Phase 4 — Accuracy layer (the long game)
1. Build the **"Current Faculty"** attribution mode (see Ranking methodology
   above): batch-resolve `last_known_institutions` for every harvested
   author_id, filter noisy single-year `affiliations` entries, re-aggregate
   keyed on current institution. Ships as a toggle alongside "At Time of
   Publication," not a replacement for it.
2. Optional, only if (1)'s automated data proves unreliable at scale: a
   hand-curated faculty CSV (`ecerankings-[a-z].csv`) accepting community PRs
   like CSRankings — fallback, not the default path, since OpenAlex's own
   author records may make this unnecessary.
3. Monthly refresh via GitHub Action (harvest → aggregate → commit → deploy).
4. Submission form for corrections; overrides directory grows as the
   manual-curation layer.

## Directory layout

```
ecerankings.org/
├── README.md                 # Project overview
├── PLAN.md                   # This file: architecture, methodology, phases
├── data/
│   ├── areas.json            # curated venue registry (the crown jewel)
│   ├── affiliation-map.csv   # curated Crossref-affiliation -> institution map
│   ├── institutions.json     # OpenAlex dump (gitignored, regenerable)
│   └── reports/              # one markdown report per collection run
├── pipeline/
│   ├── harvest.py            # OpenAlex works downloader, one venue-year per run (cached, resumable)
│   ├── harvest_crossref.py   # Crossref fallback, same --venue/--year interface, for years with no OpenAlex source
│   ├── normalize_affiliations.py       # Crossref affiliation strings -> institutions
│   ├── normalize_affiliations_local.py # local version using institutions.json
│   ├── adjudicate_review.py            # apply corrections to affiliation map
│   └── aggregate.py          # adjusted counts -> site data
├── site/
│   ├── index.html
│   ├── src/*.ts
│   └── data/                 # generated CSVs/JSON (committed)
├── .claude/skills/           # project integrations for Claude Code (committed)
├── cache/                    # cache/<venue>/<year>/works.jsonl, raw API responses (gitignored)
└── .tmp/                     # one-off scratch scripts (gitignored, local scratchpad)
```

## Immediate next steps

1. Continue working the venue registry: 8 venues verified, 26 candidate,
   20 todo (see data/areas.json status fields; use the collect-venue-data
   skill per venue).
2. Finish affiliation adjudication for Crossref-sourced years
   (pipeline/adjudicate_review.py + the adjudicate-affiliations skill).
3. Phase 3: build the static frontend on top of site/data/*.csv.
