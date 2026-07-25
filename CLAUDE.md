# ECERankings.org

A metrics-based ranking of ECE (Electrical & Computer Engineering) programs,
modeled on CSRankings but journal-aware and built on **OpenAlex** instead of
DBLP. Read `PLAN.md` before doing anything substantive — it defines the
methodology, area taxonomy, and venue-inclusion policy.

## Key files

- `PLAN.md` — architecture, methodology, phases. Do not change methodology
  decisions (adjusted counts, venue-inclusion policy, area list) without the
  user's explicit approval.
- `data/areas.json` — the venue registry, the project's most important curated
  file. Every ranked venue lives here with its OpenAlex source IDs and a
  `status` field (`todo` → `candidate` → `verified`). It doubles as the work
  queue for data-collection sessions.
- `data/known-strong.json` — tripwire for verification: per-area lists of
  institution IDs that MUST have non-zero scores. If any go to zero, it's a
  data bug, not a ranking insight.
- `data/excluded-works.csv` — curated list of works `aggregate.py` skips
  (editorials, columns, non-research items). Keyed by `work_key` from
  `pipeline/workkey.py`: `doi:<normalized>`, or `vt:<venue>|<year>|<title>` for
  the 2.6% of works with no DOI. Never auto-generated — see "Data quality".
- `data/reports/` — one markdown report per collection run (see skill).
- `cache/` — raw OpenAlex responses. Tracked via Git LFS; syncs across computers.
- `pipeline/` — harvest/backfill/aggregate scripts. See "Pipeline architecture".

## Ranking methodology

- Geometric mean scoring: `(∏(1+s_i))^(1/n)-1` across areas, where `n` is the
  count of *selected* areas including any scoring zero (`index.html:494`). All
  cached years included (1981–2026 as of now); no year window filter yet. See
  `PLAN.md` for the full methodology.
- When ranking, analyzing, or comparing institutions, **only include areas
  with `default_on: true`** — currently **18 of 20 areas**; `flagship` and `ml`
  are off. Verify against `data/areas.json` rather than trusting this line.
  `ml` was turned off 2026-07-25: NeurIPS and ICLR have zero works harvested
  and ICML is 88% missing affiliations, because PMLR/OpenReview papers are
  attributed to arXiv in OpenAlex rather than to the conference. Turning it
  back on requires an OpenReview-based harvester, not a config change.
  `index.html:403 getDemoAreas()` carries a *third*, drifted copy of these
  flags used only when the `areas.json` fetch fails.
- Area size skews the score, but less than raw volume suggests: a 15.4x spread
  in paper count across default-on areas compresses to a ~2.6x spread in
  contribution to the top-20 geometric means, because `log(1+s)` flattens it.
  Image/photonics/sigproc run above equal weight; embedded/ml/biomed below.
- General journals (Nature, Science, PNAS) are in the `flagship` area with
  `default_on: false` — off by default, intended to expand to other fields
  (bio, chem) later. All venues in this area are OpenAlex-native (resolved
  institutions, no affiliation-map needed).
- `site/data/inst-area-year.csv` is the canonical aggregate: `institution_id,
  area, year, pub_count, adjusted_count`. Rebuilt on every `aggregate.py` run.
- `site/data/<area>.json` — per-area JSON files, split from the CSV by
  `pipeline/split.py`. The site loads these lazily (one per selected area)
  instead of the full CSV. Run `split.py` after every `aggregate.py` run.

## Available skills

- `collect-venue-data` — resolve/verify/harvest venues for an area
- `adjudicate-affiliations` — LLM adjudication of ambiguous affiliation strings
- `verify-data` — post-pipeline quality checks (harvest, normalize, aggregate)

## Data-collection sessions

For "research/collect data for area X or venue Y" tasks, invoke the
`collect-venue-data` skill and follow it exactly. It contains the API recipes,
verification checklist, and report format. Scope discipline: only touch the
area/venue you were asked about; record ambiguities in the report instead of
guessing or blocking.

## Pipeline architecture

```
harvest.py            (OpenAlex)   ─┐
harvest_crossref.py   (Crossref)   ─┼→  cache/<venue>/<year>/works.jsonl
harvest_s2.py         (S2, ICML)   ─┘      raw Works: authors, raw_affiliations,
                                           institutions (OpenAlex path only)

backfill_openalex.py                 →  rewrites cache/*/works.jsonl in place
    Crossref/S2 works have no venue-independent affiliation data. Looks each up
    by DOI (50 per request) and writes OpenAlex's resolved institutions back in.
    Run after every Crossref/S2 harvest — see "Why the backfill exists" below.

normalize_semantic.py                →  data/affiliation-map.csv
    raw_affiliation strings → OpenAlex institution IDs (auto/manual/unmatched).
    Requires .venv. normalize_affiliations_local.py is the stdlib fallback.

detect_editorials.py                 →  data/editorial-candidates.csv
    .venv only. Scores candidate titles by semantic similarity to editorial vs
    research exemplars. PROPOSES ONLY — a human promotes accepted rows into
    data/excluded-works.csv, which is what aggregate.py actually reads.

aggregate.py --all-cached            →  site/data/inst-area-year.csv
                                        site/data/inst-venue-year.csv
                                        site/data/author-info.csv
    cache/*/works.jsonl  +  affiliation-map.csv  →  adjusted counts per (inst, area, year)

split.py                             →  site/data/<area>.json
    inst-area-year.csv  →  one minified JSON file per area (lazy-loadable by the site)

build_institutions.py                →  site/data/institutions.json
    id → {name, country} for every institution in the aggregate. The site
    fetches this at index.html:430; it is what makes country filtering work.

verify.py --all                      →  console + data/reports/ (with --report)
```

**Why the backfill exists**: OpenAlex holds most IEEE conference papers but
leaves `primary_location.source` **null** — they are ingested and enriched with
affiliations but linked to no venue. `harvest.py` is source-driven, so those
works are unreachable by any source ID. Crossref is the only source that knows
"this DOI belongs to ICASSP 2020" (57.1% affiliation yield); OpenAlex is the
only source with the affiliations (95.0% yield). **Crossref supplies venue
membership, OpenAlex supplies affiliations, the DOI is the join key.**

**Critical detail**: `aggregate.py:201` consults `affiliation-map.csv` **only
when `institutions` is empty**. OpenAlex-native and backfilled works therefore
bypass the curated map entirely, importing OpenAlex's resolution errors
uncorrected — e.g. "University of Pennsylvania" → *California University of
Pennsylvania* (107 occurrences, 71.3 adjusted count as of 2026-07-25). More
OpenAlex coverage means more uncurated OpenAlex mistakes.

## Data quality

- `data/affiliation-map.csv` is the bridge between Crossref free-text and
  OpenAlex institutions. It's the most valuable curated file after `areas.json`.
  Note it only applies where `institutions` is empty (see "Critical detail"),
  so it covers a shrinking share of the corpus as backfill coverage grows.
- OpenAlex's own resolutions are **not** ground truth. Cross-checking the map
  against them found 20% disagreement, with errors on both sides: OpenAlex maps
  "Northeastern University"→*Universidad del Noreste* and "Rutgers University"→
  *Rutgers Sexual and Reproductive Health and Rights*, while the map had
  "MERL"→*University of Cambridge*. Treat disagreements as an adjudication
  queue, never as automatic corrections.
- Known systematic errors in the map (fixed but can regress on re-normalization):
  - UC campuses: bare "University of California" → UCSF; "UC,<dept>,<campus>" → UCSF
  - City-name collisions: "Qualcomm, San Diego" → UC San Diego
  - Acronym mismatches: short all-alpha `matched_via` that isn't an official acronym
  - Institution type: companies with education-like names, vice versa
  - Multi-campus confusion: "University of Maryland, College Park" → UM Baltimore, etc.
- Post-adjudication QA checklist (see `.claude/skills/adjudicate-affiliations/`):
  1. Acronym validation (step 5)
  2. Institution type validation (step 6)
  3. Multi-campus cluster validation via `pipeline/fix_campus_clusters.py` (step 7)
- **Non-research contamination**: adjusted count is 1/N per author, so a
  single-author editorial or magazine column earns its institution a full 1.0 —
  4x what an author gets on a 4-author research paper. 66 single-author
  science-fiction columns ("Astromech robots in *Star Wars*") put Texas A&M at
  #1 in Science Robotics at double the runner-up. `data/excluded-works.csv` is
  the curated fix; `aggregate.py` skips those works and reports the count.
  OpenAlex types all 66 as `article`, so **no `type` filter would catch them**,
  and single-authorship alone is not a valid test — `tit` (8.2%) and
  `automatica` (6.2%) are theory venues where solo research papers are normal.
  Corpus-wide 3.48% of credited works are single-author, concentrated in
  `flagship` (nature 21.1%, science 19.2%) which is `default_on: false`.
- `pipeline/verify.py` checks: venue coverage vs expected, zero-count audits,
  author cross-validation, top-institution sanity per area.

## Conventions

- OpenAlex API: read `OPENALEX_API_KEY` from `.env` at the repo root and append
  `api_key=<key>` to every request, plus `mailto=eding2019@gmail.com`. The key
  has a ~$1/day usage budget (credit-based, not rate-based — the constraint is
  total spend, not requests/sec) — batch queries sensibly, prefer `group_by`
  over paging when aggregates suffice, and reuse `cache/` instead of
  re-fetching. Sleep ~0.03s between calls; on 429/5xx, respect a `Retry-After`
  header if present, otherwise back off exponentially (2^attempt seconds).
  Never write the key into committed files, reports, or logs (`.env` is
  gitignored — keep it that way).
- Python: stdlib only (`urllib`, `json`, `csv`, `gzip`) — no pip installs,
  except `.venv/` (sentence-transformers, PyTorch with MPS) for
  `normalize_semantic.py` only.
- `.tmp/` directory: local scratchpad, **gitignored** — do NOT put permanent
  scripts, fixes, or documents here. They won't be committed and won't survive
  to future sessions. Permanent code goes in `pipeline/`,
  `.claude/skills/`, or `data/`.
- Never commit or push without the user's explicit confirmation. Stage changes
  with `git add` and present a summary of what would be committed, then wait
  for approval. Never commit `.env`, `.tmp/`, `data/institutions.json`,
  or local settings (all gitignored). Never push without separate user confirmation.
