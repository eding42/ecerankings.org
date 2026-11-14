# ECERankings.org — Agent Guide

A metrics-based ranking of ECE (Electrical & Computer Engineering) programs, modeled on CSRankings but journal-aware and built on **OpenAlex** instead of DBLP.

> Read `PLAN.md` before doing anything substantive — it defines the methodology, area taxonomy, and venue-inclusion policy.

---

## Instruction Files & Multi-Agent Conventions

* **`AGENTS.md` is canonical.** All AI assistants (Antigravity, Gemini, Claude Code, Cursor, Copilot, Codex, Aider) read this file.
* **`CLAUDE.md` is a one-line `@AGENTS.md` import** for Claude Code sessions. Edit `AGENTS.md`, never `CLAUDE.md`.
* **Skills are cross-platform.** All skills are maintained as physical files across:
  * `.agents/skills/<name>/SKILL.md` (Standard / Open Agent convention)
  * `.gemini/skills/<name>/SKILL.md` (Google Gemini & Antigravity)
  * `.claude/skills/<name>/SKILL.md` (Anthropic Claude Code)

---

## Available Skills

Before starting specialized tasks, consult the corresponding skill. Each skill defines recipes, verification gates, safety checklists, and expected reporting formats.

| Skill | Category | When to invoke | Primary files & outputs |
| :--- | :--- | :--- | :--- |
| **[`collect-venue-data`](.agents/skills/collect-venue-data/SKILL.md)** | Ingestion | Add or re-verify a venue or area; check source coverage | `data/areas.json`, OpenAlex/Crossref API |
| **[`adjudicate-affiliations`](.agents/skills/adjudicate-affiliations/SKILL.md)** | Normalization | Resolve unmatched or ambiguous affiliations to OpenAlex IDs | `pipeline/adjudication.py`, `data/affiliation-map.csv` |
| **[`verify-data`](.agents/skills/verify-data/SKILL.md)** | QA & Gates | Verify data end to end after any harvest, backfill, normalization, adjudication, or aggregation, and before promotion | `pipeline/verify.py` (phases 1-5), `dropped_credit.py`, seeded audits (`audit_map_sample.py`, `audit_bylines.py`, `check_stale_affiliations.py`) |
| **[`verify-pdf-affiliations`](.agents/skills/verify-pdf-affiliations/SKILL.md)** | QA & Vision | Audit PDF-extracted author affiliations against rendered page images | `pipeline/harvest_ml.py`, checkpoint audits |
| **[`refresh-data`](.agents/skills/refresh-data/SKILL.md)** | Operations | End-to-end rebuild, validation, promotion, and release deployment | `docs/refresh-runbook.md`, release packaging |
| **[`clean-copy`](.agents/skills/clean-copy/SKILL.md)** | Frontend / UX | Review or edit user-facing copy; eliminate defensive stubs and noise | `site/`, labels, hints, empty states, toasts |
| **[`find-implicit-state-machines`](.agents/skills/find-implicit-state-machines/SKILL.md)** | Architecture | Audit codebase for unmodeled boolean clusters, races, and drift | Read-only audit report, state diagrams, unions |

### Skill Highlights & Usage Guide

#### 1. `collect-venue-data`
* **Trigger:** *"Research/collect data for area X or venue Y"*
* **Scope discipline:** Only touch the specific area/venue requested. Establish authoritative paper lists (OpenAlex source vs. Crossref DOI prefix vs. publisher proceedings), measure paper-specific affiliation coverage, and register candidates in `data/areas.json`.

#### 2. `adjudicate-affiliations`
* **Trigger:** Following normalization runs or harvests that introduce unmapped affiliation strings.
* **Safety:** Every decision is validated, evidenced, replayable, and regression-checked using `pipeline/adjudication.py`. Always run the trap regression check before and after changes.

#### 3. `verify-data`
* **Trigger:** Post-harvest, post-normalization, or pre-promotion validation.
* **Checks:** Catches pipeline bugs, dropped credit, wrong bylines (cut, repeated, group-named, garbled), affiliation errors, and missing institution metadata (`pipeline/verify.py --all`) before rankings reach the public static build.
* **Random audits:** rules find only what someone imagined, so the skill also runs seeded, blind audits that measure the error rate of the affiliation map and of cached bylines. Use a fresh seed after every fix.

#### 4. `verify-pdf-affiliations`
* **Trigger:** After `pipeline/harvest_ml.py` PDF stage or whenever publisher PDFs need manual extraction verification.
* **Process:** Compares LLM PDF extraction drafts against rendered page images, saving individual checkpoints per paper.

#### 5. `refresh-data`
* **Trigger:** Monthly/quarterly data updates, "push the new data", release candidate builds.
* **Authority:** Follow `docs/refresh-runbook.md` strictly. Never run direct ad-hoc scripts (`aggregate.py` into `site/data`) that bypass checksum verification and hash gates.

#### 6. `clean-copy`
* **Trigger:** Writing or reviewing labels, hints, empty states, button text, or status notices.
* **The Ladder:** 
  1. *Does this need to surface at all?* (Don't plant unprompted worries).
  2. *Does the label need to exist?* (Don't restate what the control already shows).
  3. *Is it pre-empting something the user never had to consider?* (No bug scar tissue or defensive hedging).
  4. *Delete empty elements* instead of leaving stubs.

#### 7. `find-implicit-state-machines`
* **Trigger:** Auditing complex frontend UI, async fetch workflows, or state management logic.
* **Analysis:** Discovers emergent boolean clusters (`isLoading`, `hasError`, `isSuccess`), out-of-sync URL state, and async race conditions. Recommends minimal fixes (derived state → discriminated unions → centralized reducers).

---

## Multi-Discipline Architecture & Field Registry

The repository maintains ranking engines across multiple academic disciplines unified by a shared frontend core and parameterized pipeline:
* **`ece`** (Electrical & Computer Engineering) — Flagship discipline at `site/` (`site/data/`), registry `data/areas.json`, cache `cache/`.
* **`biology`** (Biological & Biomedical Sciences) — Sister discipline at `site/biology/` (`site/biology/data/`), registry `data/areas_biosciences.json`, cache `cache_biosciences/`.
* **`earth-space`** (Earth, Planetary & Space Sciences) — Sister discipline at `site/earth-space/` (`site/earth-space/data/`), registry `data/areas_earth_space.json`, cache `cache/`.

### Field Scoping Rules for Agents
* **Always specify `--field <ece|biology|earth-space>`** when running operational pipeline tools (`pipeline/aggregate.py`, `pipeline/split.py`, `pipeline/verify.py`, `pipeline/package_site.py`).
* **Shared frontend core:** Common ranking, history, comparison, year-strip, coverage, and table engine logic lives exclusively in `site/core/`. **Never re-duplicate core files into sister sites.** Each discipline directory (`site/biology/`, `site/earth-space/`) holds only thin wrapper entrypoints (`main.js`, `index.html`) and palette overrides.
* **Never mix caches across disciplines:** ECE and Earth & Space read `cache/`, while Biosciences reads `cache_biosciences/`. Never cross-contaminate venue registries or aggregate outputs.

---

## Key Files

* `PLAN.md` — Architecture, methodology, phases. Do not change methodology decisions (adjusted counts, venue-inclusion policy, area list) without explicit user approval.
* `data/fields.json` & `pipeline/fields.py` — Central field registry defining paths, credit types, capabilities, and aliases across disciplines.
* `data/areas.json` (ECE), `data/areas_biosciences.json` (Biology), `data/areas_earth_space.json` (Earth & Space) — The venue registries. Every ranked venue lives here with OpenAlex source IDs and a `status` field (`todo` → `candidate` → `verified`).
* `data/known-strong.json` — Verification tripwire: per-area lists of institution IDs that must have non-zero scores. If any score zero, it is a data pipeline bug.
* `data/excluded-works.csv` — Curated list of non-research items `aggregate.py` skips (editorials, columns, tributes). Keyed by `work_key` (`doi:<normalized>` or `vt:<venue>|<year>|<title>`).
* `data/institution-aliases.csv` — Duplicate OpenAlex institution IDs folded onto canonical IDs. **Merges require matching name AND country.**
* `data/affiliation-map.csv` — Maps raw Crossref author affiliation strings to OpenAlex institution IDs.
* `data/adjudication-traps.csv` — Regression traps for the map: strings whose resolution was once wrong. `adjudication.py check` fails if one regresses, or if the file is missing.
* `cache/` & `cache_biosciences/` — Raw OpenAlex/Crossref responses. Managed via Git LFS.
* `site/core/` — Unified static frontend core (engine, ranking math, comparison, history, strip, coverage).
* `site/` — ECE frontend; `site/biology/` — Biology frontend; `site/earth-space/` — Earth & Space frontend. Zero runtime dependencies.

---

## Ranking Methodology

* **Geometric mean scoring:** `(∏(1 + s_i))^(1/n) - 1` across areas, where `n` is the count of *selected* areas (including those scoring zero).
* **Default areas:** Only include areas with `default_on: true` (currently **18 of 20 areas**; `flagship` and `ml` are off by default). Verify against `data/areas.json`.
* **Publication credit:** Each paper is worth 1.0, split evenly among its listed authors ($1/N$). Each author's share is credited to the institutions they explicitly listed on that publication.
* **Institutions, not departments:** Rankings reflect whole institutions, not ECE department rosters or faculty listings.

---

## Pipeline Architecture

```
harvest.py            (OpenAlex)   ─┐
harvest_crossref.py   (Crossref)   ─┼→  cache/<venue>/<year>/works.jsonl
harvest_s2.py         (S2, ICML)   ─┘      raw Works: authors, raw_affiliations,
                                           institutions (OpenAlex path only)

refresh_openalex_affiliations.py     →  rewrites cache/*/works.jsonl in place
    OpenAlex-native works harvested before OpenAlex had their affiliations never
    heard about them. Re-fetches works whose authors ALL lack affiliations by
    OpenAlex id; accepts a result only if the author list matches position by
    position. Run after backfill; then normalize and adjudicate the new strings.

backfill_openalex.py                 →  rewrites cache/*/works.jsonl in place
    Crossref/S2 works lack venue-independent affiliation data. Looks up DOIs
    in batches of 50 and writes OpenAlex's resolved institutions into cache.

normalize_semantic.py                →  data/affiliation-map.csv
    raw_affiliation strings → OpenAlex institution IDs (auto/manual/unmatched).
    Requires .venv. pipeline/normalize_affiliations_local.py is the stdlib fallback.

detect_editorials.py                 →  data/editorial-candidates.csv
    Proposes non-research candidates for manual promotion to data/excluded-works.csv.

aggregate.py --field <id> --all-cached            →  <site_data>/inst-area-year.csv
    Filters non-research types and excluded works, folds aliases, and calculates
    adjusted fractional counts per institution, area, and year. Resolves field
    defaults (cache, areas registry, credit types, output dir).

split.py --field <id>                             →  <site_data>/<area>.json
    Splits aggregate CSV into minified per-area JSON files for lazy frontend loading.

build_institutions.py                             →  site/data/institutions.json
    Generates id → {name, country} metadata used for country/regional filtering.

package_site.py --field <id>                      →  dist/
    Validates and packages static distribution bundles per discipline.

verify.py --field <id> --phase <1-5>              →  Console and data/reports/ report.
    Field-aware quality checks across harvest, normalization, aggregation,
    global audit, and author bylines.

audit_map_sample.py / audit_bylines.py / check_stale_affiliations.py
    Seeded random audits that measure the map's and the cache's error rates.
```

### Critical Pipeline Details

* **Why the backfill exists:** OpenAlex holds most IEEE conference papers but leaves `primary_location.source` null, making them unreachable by source ID queries. Crossref supplies venue membership; OpenAlex supplies author affiliations; the DOI is the join key.
* **Affiliation resolution priority:** `aggregate.py` consults `affiliation-map.csv` **only when `institutions` is empty**. Native OpenAlex works bypass the curated map. OpenAlex resolutions are checked for errors (e.g. multi-campus collisions) via `pipeline/fix_campus_clusters.py` and trap checks in `pipeline/adjudication.py`.

---

## Data Quality & Affiliation Traps

* **`data/affiliation-map.csv` is not ground truth:** Cross-checking found ~20% disagreement between OpenAlex native resolutions and curated strings (errors exist on both sides). Treat disagreements as an adjudication queue, never as automatic corrections.
* **Known systematic resolution traps:**
  * **UC campuses:** Bare "University of California" or "UC,<dept>,<campus>" frequently mistakenly resolved to UCSF.
  * **City-name collisions:** E.g., "Qualcomm, San Diego" resolving to UC San Diego.
  * **Acronym collisions:** Short all-alpha acronyms matching unrelated global institutions.
  * **Multi-campus confusion:** E.g., "University of Maryland, College Park" resolving to UM Baltimore.
  * **Name collisions across countries:** Merging institutions requires matching BOTH name and country code (e.g., Northeastern University US vs. Northeastern University CN/Shenyang).
* **Non-research contamination:**
  * Adjusted count is $1/N$ per author, so single-author editorials or magazine columns award a full 1.0 (4x what an author receives on a 4-author research paper).
  * Curated exclusion lists live in `data/excluded-works.csv`. `aggregate.py` filters these out before tallying scores.

---

## Conventions & Constraints

* **API Keys & Environment:**
  * Read `OPENALEX_API_KEY` from `.env` at repo root (`api_key=<key>&mailto=eding2019@gmail.com`).
  * Never commit `.env`, log API keys, or expose them in public assets.
* **Python Environment:**
  * Python stdlib only (`urllib`, `json`, `csv`, `gzip`) for core harvest, aggregate, and verification scripts.
  * `.venv/` is reserved only for optional semantic tools (`sentence-transformers`, `torch`).
* **Scratches & Temporary Files:**
  * `.tmp/` is gitignored scratch space. Do not store permanent fixes, scripts, or release candidate outputs in `.tmp/`.
* **Git & Commit Guardrails:**
  * **Never commit or push without explicit confirmation.**
  * Stage specific paths with `git add <files>`; never `git add -A` or `git add .`.
  * Never commit `.env`, `.tmp/`, `data/institutions.json`, or local settings.
  * "Push" authorizes pushing to a feature/fix branch or PR, not directly deploying to production.
