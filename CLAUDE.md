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
- `data/reports/` — one markdown report per collection run (see skill).
- `cache/` — raw OpenAlex responses. Tracked via Git LFS; syncs across computers.
- `pipeline/` — harvest/aggregate scripts (Phase 1–2; may not exist yet).

## Ranking methodology

- Default-on: 19 areas. Geometric mean scoring: `(∏(1+s_i))^(1/n)-1` across
  areas. All cached years included (1981–2026 as of now); no year window
  filter yet. See `PLAN.md` for the full methodology.
- When ranking, analyzing, or comparing institutions, **only include areas
  with `default_on: true`** (currently 16 of 21 areas). Always confirm with
  the user before including `default_on: false` areas (flagship, ML, biomed,
  nature_ece, quantum).
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
harvest.py / harvest_crossref.py     →  cache/<venue>/<year>/works.jsonl
    raw Works (authors, raw_affiliations, empty institutions for Crossref)

normalize_semantic.py                →  data/affiliation-map.csv
    ~59K raw_affiliation strings → OpenAlex institution IDs (auto/manual/unmatched)

aggregate.py                         →  site/data/inst-area-year.csv
    cache/*/works.jsonl  +  affiliation-map.csv  →  adjusted counts per (inst, area, year)

split.py                             →  site/data/<area>.json
    inst-area-year.csv  →  one minified JSON file per area (lazy-loadable by the site)
```

**Critical detail**: All 60 venues in `data/areas.json` are Crossref-sourced
(`openalex_ids: []`), so `works.jsonl` always has `institutions: []`.
`aggregate.py` must fall back to `affiliation-map.csv` via `raw_affiliations`
to credit institutions. Without this, **zero venues contribute** — this exact
bug existed before 2026-07-23.

## Data quality

- `data/affiliation-map.csv` is the bridge between Crossref free-text and
  OpenAlex institutions. It's the most valuable curated file after `areas.json`.
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
