---
name: collect-venue-data
description: Research, verify, and register OpenAlex venue data for an ECE ranking area or a single conference/journal, then optionally harvest its works. Use for any "collect/verify/research data for <area or venue>" task.
---

# Collect venue data (OpenAlex)

You are doing **mechanical data collection** for ecerankings.org. The
methodology is settled (see `PLAN.md`); your job is to resolve venues to
OpenAlex source IDs, verify them against the checklist, update the registry,
and write a report. **Do not** redesign areas, add venues nobody asked for,
change methodology, or edit `PLAN.md`.

Input: an area key from `data/areas.json` (e.g. `circuits`) or a single venue
name. Work only on that scope.

## Default scope: last 10 years

Unless the invocation names a specific year, year range, or says something
like "all years" / "full history", scope every step — per-year source
enumeration, the year-coverage check, and any harvesting — to a rolling
**10-year window**: the current year and the 9 before it. Compute it from
`date +%Y` at run time, don't hardcode a range. E.g. if today's year is 2026,
the default window is 2016–2025 (through the last fully-registerable year;
include the current year too if the venue has published in it).

This is a default, not a ceiling — if the user later asks to backfill older
years for an already-`verified` venue, that's in scope and doesn't need
re-verifying the parts already done. Note the applied window in the report's
Summary so it's clear the venue wasn't checked further back.

## Execution mode: orchestrator vs worker

Pick your role from the scope before doing anything else:

- **One venue** (input names a single venue, or the area has only one venue in
  `data/areas.json`) → **worker mode**: run the whole procedure yourself, no
  subagents.
- **An area with 2+ venues** → **orchestrator mode**: fan out one **Sonnet**
  subagent per venue and merge their results. Workers are cheaper (Sonnet) and
  run concurrently, so an area finishes in roughly the time of its slowest
  single venue instead of the sum.

### Orchestrator mode

1. Read `data/areas.json`; list the venue keys in the requested area.
2. Get today's date once (`date +%F`) and pass the same stamp to every worker.
3. Spawn one subagent per venue **in parallel**. **This means literally
   issuing every `Agent` tool call for the wave inside ONE assistant
   turn** — one message containing N tool-call blocks, all with
   `run_in_background: false` so you block until the whole wave returns.
   **Never call `Agent` for one venue, wait for its result, and only then
   call `Agent` for the next venue** — that is sequential execution wearing
   parallel clothing, it costs N× the wall-clock time, and it is the exact
   mistake to avoid here. If you catch yourself about to send a single-agent
   message while other venues in this wave are still undispatched, stop and
   batch them instead.
   Each subagent gets `subagent_type: general-purpose`, `model: sonnet`, and
   a prompt that:
   - names the single venue key and pastes its current registry fields
     (`display`, `kind`, `openalex_ids`, `expected_per_year`, `status`);
   - states the resolved year window explicitly (e.g. "scope: 2016–2025") —
     workers can't see the user's original invocation, so the orchestrator
     must apply the "Default scope" rule itself and pass the concrete years
     down, never leave a worker to guess;
   - tells it to follow **this skill's steps 2–5 in worker mode** for that ONE
     venue, reading `PLAN.md` and this `SKILL.md` for the rules;
   - tells it to write its report to `data/reports/<venue_key>-<date>.md`;
   - tells it to **NOT edit `data/areas.json`** — instead end its turn with a
     single fenced ` ```json ` block holding the proposed registry entry
     (`{"key","openalex_ids","status","notes","years"?}`).
   - Budget guard: cap concurrency at ~4 workers. If the area has more venues,
     batch in waves of 4 — all N calls of a wave still go in one message;
     only a *second* wave (waiting for the first to fully return) is
     legitimately sequential.
4. Collect each worker's returned JSON. **You** apply all of them to
   `data/areas.json` in a single pass. Workers never write the registry — that
   is the one file with write contention, so only the orchestrator touches it.
   If a worker's JSON is missing/malformed, leave that venue untouched and note
   it in the rollup.
5. Write an area rollup `data/reports/<area>-<date>.md`: a short summary plus a
   table of per-venue outcomes (verified / candidate / failed) linking each
   `data/reports/<venue_key>-<date>.md`.
6. Now go to Procedure step 6 (harvesting) **yourself, once, for the whole
   area** — workers never harvest, and never skip straight to harvesting
   without asking.

Hard limits: workers run in worker mode only — never let a worker spawn its own
subagents (no second layer), and never let a worker write `data/areas.json`.

## OpenAlex ground rules

- Base URL `https://api.openalex.org`. Append `&mailto=eding2019@gmail.com`
  AND `&api_key=<value of OPENALEX_API_KEY from .env at repo root>` to every
  request. The key has a ~$1/day budget, and it's **credit-based, not
  rate-based** — the constraint is total spend, not requests/sec, so don't
  over-throttle. Prefer `group_by` over full paging when aggregates suffice,
  and never re-download what's already in `cache/`. Never paste the key into
  reports, registry files, or logs. Sleep ~0.03s between calls (not more —
  this isn't a hard rate limit); on HTTP 429/5xx, respect a `Retry-After`
  header if present, otherwise back off exponentially (2^attempt seconds,
  retry up to 3×). Python stdlib only.
- Useful endpoints:
  - `/sources?search=<name>&per-page=25` — find venues.
  - `/works?filter=primary_location.source.id:S...,publication_year:YYYY` —
    papers. Add `&group_by=publication_year` for per-year counts,
    `&group_by=authorships.institutions.lineage` for institution counts
    (top 200 only), `&per-page=200&cursor=*` for full paging.
  - Filter `type:article|proceedings-article` on journals to skip
    editorials/errata/paratext.
- **Journals** have ONE stable source ID covering all years.
- **Conferences are fragmented**: each year's proceedings is often a separate
  source (`"2022 IEEE International Solid-State Circuits Conference (ISSCC)"`),
  sometimes plus a catch-all series source. You must enumerate ALL of them
  within the in-scope year window (default: last 10 years — see "Default
  scope" above).
- **Conferences lag ~2 years in OpenAlex.** Confirmed on IEDM/ISSCC/DAC/ISCA:
  the newest per-year source is typically 2 years behind the current date.
  Don't assume a missing recent year means the conference wasn't held —
  check Crossref (step 3a) before concluding it's a real gap.

## Crossref fallback (for conference years missing in OpenAlex)

No key needed. `api.crossref.org/works?query.container-title=<venue name>
&filter=from-pub-date:YYYY-MM-DD,until-pub-date:YYYY-MM-DD,type:proceedings-article
&mailto=eding2019@gmail.com`. `query.container-title` is fuzzy — verify hits
by DOI prefix (e.g. all real IEDM papers are `10.1109/iedm...`), not by trusting
the result count. Each item's `author[].affiliation[].name` is a free-text
string (e.g. `"KAIST,School ofElectrical Engineering,Daejeon,Korea"`), not a
resolved institution — do not try to match it against `institutions.csv`
yourself; that normalization step belongs to `pipeline/normalize-affiliations.py`
(Phase 1b in PLAN.md), not this skill. Your job here is just to confirm
Crossref *has* the missing year and note it in the report.

## Procedure

### 1. Read the registry entry

Open `data/areas.json`, find the venue(s) in scope. Each entry has
`display`, `kind` (journal/conference), any known `openalex_ids`,
`expected_per_year` (a rough sanity range — papers/yr in recent years), and
`status`.

### 2. Resolve candidate sources

Search `/sources` with several variants: full name, acronym, "IEEE <name>",
"Proceedings of <name>". For conferences, also try
`/sources?filter=display_name.search:<acronym or key phrase>&per-page=100`
and page through. Collect every plausible candidate with its ID, display_name,
type, works_count, and host organization.

**Lookalike traps — reject these.** Similar names ≠ same venue:
- "International Conference on Electron Devices and Solid-State Circuits"
  (EDSSC, regional) is NOT ISSCC.
- Workshop/companion/adjunct/"poster session"/regional variants
  (e.g. "... Workshops", "... Companion", "Asian ...", "European ..." when the
  target is the flagship) are excluded unless the registry says otherwise.
- Predatory or lookalike journals ("International Journal of ...") — check the
  host organization is IEEE/ACM/Optica/Nature/Elsevier as expected.
- If genuinely unsure whether a candidate is the target venue, use WebSearch
  to check the venue's official site/ISSN, and if still unsure, list it under
  "needs human review" in the report — never guess it into the registry.

### 3. Verify each accepted source (checklist)

**What "verified" means: we're confident this is the right venue and we know
how to get every in-window year's data — not that every year is already
sitting in OpenAlex with resolved institutions.** OpenAlex's ~2-year
ingestion lag on conferences (and occasional unlinked-source gaps, e.g. a
work exists with `raw_source_name` set but `primary_location.source` null)
is *normal*, not a defect — under the old, stricter reading almost no
conference would ever reach `verified`. A Crossref-covered year with a
DOI-prefix-validated count is legitimate "coverage" for this checklist; it
just means affiliation resolution for that year is deferred to Phase 1b
(`harvest_crossref.py` / `normalize_affiliations.py`), not that source
identification failed.

For every source ID you intend to register, ALL of:

1. **Identity**: fetch 5 sample works from a recent year; titles must read as
   papers from that venue's field. Host organization matches expectations.
2. **Year coverage**: `group_by=publication_year` → build a coverage table for
   the in-scope year window (default: last 10 years — see "Default scope"
   above; use the user's stated range instead if they gave one). For
   conferences, merge coverage across all per-year sources and flag missing
   years within that window (biennial venues: note the cadence). For any gap,
   check Crossref before flagging it as a real gap — record in the report
   whether Crossref has it (validate by DOI prefix, not just result count).
   **A year fully covered by a DOI-verified Crossref count passes this
   check** — it doesn't need to be natively in OpenAlex. Only an actual
   missing year (absent from both OpenAlex and Crossref, e.g. venue
   cancelled/not-yet-held) is a real gap.
3. **Volume sanity**: recent-year counts (from whichever source covers that
   year — OpenAlex or DOI-verified Crossref) fall inside `expected_per_year`
   from the registry (these ranges are rough — up to ~30% outside is worth a
   note, 2× outside means you probably have the wrong source or missing/extra
   IDs).
4. **Affiliation coverage**: on ~25 sampled recent works **from the years
   that are natively in OpenAlex**, ≥85% of authorships must have a
   non-empty `institutions` list. If ALL in-window years are Crossref-only
   (no native OpenAlex year exists to sample), skip this check and note why
   — it isn't evaluable yet, and that's fine, it doesn't block `verified`.
   A real failure here (OpenAlex data exists but coverage is low, e.g. whole
   affiliation blocks missing from the record) DOES block `verified` — that's
   a genuine data-quality problem with this specific source, not a
   Crossref-fallback situation.
5. **Institution sniff test**: `group_by=authorships.institutions.lineage`
   (recent 5 years, on whichever years have native OpenAlex data) → record
   the top 10. They should look like that subfield's known leaders (plus
   industry labs — fine, they're filtered at aggregation time, not here).

### 4. Update the registry

**Worker mode (running under an orchestrator): do NOT edit `data/areas.json`.**
Instead, end your turn with a single fenced ` ```json ` block — the proposed
entry the orchestrator will merge:

```json
{"key": "<venue_key>", "openalex_ids": [...], "status": "verified|candidate",
 "notes": "...", "years": { ... }}
```

Include `years` only if you resolved per-year sources; omit it otherwise.

**Solo / orchestrator mode: edit the venue's entry in `data/areas.json`:**
- `openalex_ids`: the verified ID list (journals: one; conferences: many,
  sorted oldest→newest coverage).
- `status`: `"verified"` if the checklist passed under the "what verified
  means" reading in step 3 above — every in-window year has *some* confirmed
  source (native OpenAlex or DOI-verified Crossref), volume/identity/sniff
  checks pass, and affiliation coverage is either ≥85% on the OpenAlex-native
  years or not-yet-evaluable (no native year exists). Having Crossref-only
  years does NOT by itself block `verified` — that's expected conference-lag
  behavior, not an unresolved checklist item. Use `"candidate"` for genuine
  unresolved issues instead: an actual missing year (absent from both
  OpenAlex and Crossref), a real affiliation-coverage failure on OpenAlex
  data that does exist, an unconfirmed identity, or anything else you can't
  close out — say specifically what's unresolved in `notes`.
- Never invent IDs; never mark `verified` without having run every check.

### 5. Write the report

Create `data/reports/<scope>-<YYYY-MM-DD>.md` (get the date from `date`
command). Structure:

```markdown
# Collection report: <area or venue> — <date>

## Summary
2-4 sentences: what was resolved, overall confidence, anything odd.

## Venues
| venue | kind | source IDs | years covered | ~papers/yr recent | affil. % | status |

## Year-coverage gaps
Per venue: missing years, and for gaps in the most recent 2 years, whether
Crossref has the data (OpenAlex ingestion lag — expected, needs Phase 1b
harvest later) or not (genuine gap — explain if known, e.g. venue cancelled).

## Top-10 institutions (recent 5y, per venue)
Sanity-check lists.

## Needs human review
Every ambiguity, rejected lookalike worth a second opinion, or checklist
failure. Empty section = explicitly write "None."
```

### 6. Harvest works — always ask first, never assume

Steps 1–5 only *resolve and verify* venues; they never write paper data to
`cache/`. Harvesting is a distinct, separately-consented step — **never do it
just because verification succeeded, and never skip asking because it seems
obviously wanted.**

**This ask must come from the top-level agent talking to the actual user in
this session — never from a worker subagent** (its output isn't seen live by
the user, and it has no business making cache-writing decisions on its own
scope). In orchestrator mode: finish steps 1–5 for every venue in the wave
first (registry merged, rollup report written), *then* ask once, covering the
whole area. In worker/solo mode, ask after step 5 for that one venue.

Once steps 1–5 are done for the run's full scope, call `AskUserQuestion`:
one question, header e.g. "Harvest data?", asking whether to harvest
paper/authorship data now for the venue(s) just processed, options along the
lines of:
- Yes, harvest the newly-verified venue(s) now (only `status: "verified"`)
- Yes, harvest everything in scope including `candidate` (be explicit that
  candidates may have unresolved checklist issues, e.g. low affiliation
  coverage, that will carry into the cached data)
- No, stop here — registry + reports only

Respect the answer exactly — "no" means stop, do not harvest "just the easy
one anyway."

**If yes, harvest per venue per registry `years{}` entry — do not hand-roll
either fetch, both scripts already exist and match each other's cache layout
(`cache/<venue_key>/<year>/works.jsonl`), cursor-paged and resumable:**

- Years with no `years{}` entry, or `years[year].source == "openalex"`: use
  `pipeline/harvest.py`. It resolves a precise per-year OpenAlex ID when one
  is registered, otherwise falls back to the venue's general `openalex_ids`
  with a `publication_year` filter (how journals get chunked by year despite
  one ID spanning decades).
  ```
  python3 pipeline/harvest.py --venue <venue_key> --year <YYYY>
  python3 pipeline/harvest.py --venue <venue_key> --all-years
  ```
  `--all-years` will correctly skip any year registered `"source": "crossref"`
  (writes an empty done-stub, not data) — that's expected, not a bug; run the
  Crossref command below to actually fill those years.
- Years with `years[year].source == "crossref"`: use
  `pipeline/harvest_crossref.py` (Phase 1b — see `PLAN.md`). It validates every
  DOI against the registered `doi_prefix` and buckets by the registry's
  edition year, not Crossref's `issued` date.
  ```
  python3 pipeline/harvest_crossref.py --venue <venue_key> --year <YYYY>
  python3 pipeline/harvest_crossref.py --venue <venue_key> --all-years
  ```
  Crossref-harvested authorships carry free-text `raw_affiliations`, not
  resolved `institutions` — do not attempt to normalize them yourself; that's
  `pipeline/normalize_affiliations.py` / the `adjudicate-affiliations` skill,
  a separate step outside this skill's scope.

Report back to the user what was actually harvested (venue, years, work
counts, which script handled which years) — don't just say "done."

## Hard rules

- Scope: only the requested area/venue. Finish it before touching anything else.
- Ambiguity goes in the report's "Needs human review" — do not block waiting
  for the user, and do not guess.
- Registry edits and reports are the ONLY repo changes you make (plus cache
  files if harvesting).
- Rate limits: this is a shared free API — stay polite (sleep between calls).
