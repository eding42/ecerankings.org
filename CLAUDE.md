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
- `data/reports/` — one markdown report per collection run (see skill).
- `cache/` — raw OpenAlex responses. Never commit; safe to delete.
- `pipeline/` — harvest/aggregate scripts (Phase 1–2; may not exist yet).

## Data-collection sessions

For "research/collect data for area X or venue Y" tasks, invoke the
`collect-venue-data` skill and follow it exactly. It contains the API recipes,
verification checklist, and report format. Scope discipline: only touch the
area/venue you were asked about; record ambiguities in the report instead of
guessing or blocking.

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
- Python: stdlib only (`urllib`, `json`, `csv`, `gzip`) — no pip installs.
- Put any scratch/helper scripts you generate into the `.tmp/` directory — local scratchpad, gitignored. Repo gets only: registry updates, reports, pipeline code, and the `.claude/skills/` project integrations.
- Commit registry updates, reports, pipeline code, and `.claude/skills/` with clear messages. Never commit `.env`, `cache/`, `.tmp/`, `data/institutions.json`, or local settings (all gitignored). Do not push without the user's explicit go-ahead.
