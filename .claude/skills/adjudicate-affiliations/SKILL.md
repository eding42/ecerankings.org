---
name: adjudicate-affiliations
description: Use your LLM intelligence to resolve ambiguous Crossref affiliation strings that the deterministic script flagged for review.
---

# Adjudicate Affiliations

You are executing Tier 4 (LLM adjudication) of the affiliation resolution pipeline for ecerankings.org. 
Crossref papers contain messy, free-text affiliation strings. The deterministic script (`pipeline/normalize_affiliations.py`) tries to fuzzy-match these to OpenAlex institutions, but flags ambiguous matches (scores between 0.72 and 0.90) with `status=review` in `data/affiliation-map.csv`.

Your job is to read these `review` cases, use your intelligence to adjudicate them, and write the corrected rows back to the CSV with `status=manual`.

## Procedure

### 1. Run the deterministic script

Use the local, API-free variant first — it's instant and doesn't touch the
OpenAlex budget:
```bash
python3 pipeline/normalize_affiliations_local.py --all-cached
```
(`pipeline/normalize_affiliations.py`, the original API-backed version, still
exists as a fallback if the local `data/institutions.json` snapshot looks
stale or is missing an institution you expect to find.)

### 2. Read the review queue

Read all rows in `data/affiliation-map.csv` where `status` is `review` (a
short Python/csv script is fine). For each you'll see:
- `raw_affiliation`: the messy string from Crossref (e.g., "Peter Grunberg Institut (PGI-14) and RWTH Aachen University")
- `institution_name` / `institution_id`: the script's top candidate
- `candidate`: the specific substring the script matched on
- `score`: the fuzzy match score (0.72–0.90 range, by definition of `review`)

### 3. Adjudicate — fan out Haiku subagents

**You (the top-level agent) are the orchestrator. You never adjudicate rows
yourself and you never let a subagent write `data/affiliation-map.csv`** —
same division of labor as `collect-venue-data`'s orchestrator mode, for the
same reason: one file, one writer, avoid concurrent-write contention.

1. Split the full `review` queue into batches of **~20 rows each**.
2. Spawn one subagent per batch, with `subagent_type: general-purpose` and
   **`model: haiku`** — affiliation adjudication is pattern-matching against
   world knowledge, not deep reasoning, so Haiku is the right cost tier here.
3. **Dispatch every batch in the wave inside ONE assistant turn** — one
   message with N `Agent` tool calls, `run_in_background: false` so you
   block until the wave returns. Never spawn one batch, wait for it, then
   spawn the next — that's sequential execution costing N× the wall-clock
   for no benefit (this exact mistake has bitten this project before in
   `collect-venue-data`; don't repeat it here). Cap concurrency at ~6
   batches per wave (a subagent may need to hit `/institutions?search=...`
   for a correction, and that's still the shared OpenAlex budget even
   though Haiku itself is cheap) — batch further waves if the queue is
   larger than 6 batches.
4. Each subagent's prompt must include: its batch of rows (all 5 fields
   above), the adjudication rules below, and an explicit instruction to
   **end its turn with a fenced ` ```json ` array of decisions — one object
   per row it was given** — not to edit any file:
   ```json
   [{"raw_affiliation": "...", "decision": "confirm|correct|company|unmatched",
     "institution_id": "...", "institution_name": "...",
     "institution_type": "education|company|facility|government|nonprofit",
     "country_code": ".."}]
   ```
   Every input row must get exactly one output row back, even if the
   decision is `unmatched` — silently dropping a row is indistinguishable
   from forgetting it.

Adjudication rules for the subagent to follow, using world knowledge to
decide if `raw_affiliation` really is the candidate `institution_name` or
something else:
- **Match is correct** → `decision: "confirm"`, keep the candidate's ID/name.
- **Match is wrong, but the right institution is knowable** → `decision:
  "correct"`, find the right OpenAlex ID (query
  `https://api.openalex.org/institutions?search=...`).
- **Match is a company/industry lab** → `decision: "company"` (or whatever
  `institution_type` actually applies) — the ranking methodology filters
  non-education institutions by this field, so getting it right matters.
- **Compound affiliations** (e.g. "KAIST and Samsung") → prioritize the
  education institution. If multiple universities and no obvious primary,
  `decision: "unmatched"` rather than guessing.
- **Truly unmappable/garbage string** → `decision: "unmatched"`.

### 4. Merge subagent decisions into the CSV

Collect every batch's JSON, concatenate into one corrections list, and apply
it to `data/affiliation-map.csv` yourself in a single pass — load the CSV,
look up each row by `raw_affiliation`, write in the merged fields, save.
(`pipeline/adjudicate_review.py` is a prior one-off run of this exact
load/merge/save mechanic — its `corrections` dict is hardcoded literal Python
from that earlier session, not a reusable CLI tool, so read it purely as a
worked example of the pattern; write a fresh small script for this run's
corrections rather than trying to feed new data into the old one.)

**CRITICAL RULES FOR UPDATING**:
- Set `status` to `manual` for `confirm`/`correct`/`company` decisions — this
  tells the deterministic script to NEVER overwrite it on a future run.
  `unmatched` decisions get `status = "unmatched"` instead.
- Preserve `raw_affiliation` exactly as it appears in the CSV — it's the
  primary key.
- For `unmatched`, clear `institution_id`/`institution_name`/`institution_type`.
- `institution_type` must be a real OpenAlex type (`education`, `company`,
  `facility`, `government`, or `nonprofit`) — not free text.
- If a subagent's JSON is missing/malformed for a row, leave that row
  untouched (still `review`) and note it in your report rather than guessing.

### 5. Report

Re-run the local script with `--report-only` to show updated coverage:
```bash
python3 pipeline/normalize_affiliations_local.py --all-cached --report-only
```
Summarize how many rows were adjudicated (confirm/correct/company/unmatched
breakdown), how many batches ran, and what the trickiest cases were.
