---
name: adjudicate-affiliations
description: Resolve unmatched or ambiguous affiliation strings (Crossref free text, publisher-PDF author blocks, normalizer review rows) to OpenAlex institutions, using pipeline/adjudication.py so every decision is validated, evidenced, replayable, and regression-checked. Use after normalization or after any harvest that adds raw affiliation strings.
---

# Adjudicate affiliations

## What this decides and why it matters

`aggregate.py` credits a raw affiliation string through `data/affiliation-map.csv`. It does so **only when an authorship has no `institutions`**, and that covers:
- Crossref-harvested works;
- publisher-PDF affiliations from `harvest_ml.py` (about 9,000 author slots for ICLR 2025 alone);
- anything the OpenAlex backfill could not resolve.

One map row maps one raw string to one institution. A wrong row moves credit for every paper carrying that string, so a decision here outweighs a single paper.

You decide. `pipeline/adjudication.py` does the mechanics, so the same input produces the same map:
- **`queue`:** deterministic batches, highest credit share first.
- **`search`:** the local OpenAlex institution index; no API spend.
- **`apply`:** validates each decision. Name, type and country are filled from the index, never from your text. Evidence is required, and an earlier adjudication is never silently replaced. Accepted decisions are appended to the ledger `data/affiliation-decisions.jsonl`.
- **`replay`:** restores adjudicated rows after a normalizer or fix script overwrote them.
- **`check`:** pure QA. It reports trap regressions, case variants that disagree, type contradictions, false acronyms, and city-name collisions.

**Never hand-edit adjudicated rows in the CSV.** A hand edit has no evidence, does not survive a normalizer rerun, and cannot be replayed.

## Preconditions

1. **`data/institutions.json` exists.** It is a committed local index of about 54k institutions, and `apply`, `search` and `check` need it.
2. **No other writer is running.** Check with:
   ```bash
   pgrep -af "normalize_|fix_|adjudication"
   ```
   The normalizers and `fix_*.py` rewrite the whole map. `apply` refuses (exit 3) if the file changed between its read and its write. Do not retry in a loop; wait for the other writer to finish.
3. **Know where new strings live.** Usually that is `cache/`. For staged harvests, pass the staging tree with `--cache-dir`, e.g. `.tmp/ml-harvest/cache`.
4. **Optional semantic pre-pass.** `.venv/bin/python pipeline/normalize_semantic.py --all-cached` creates `auto` and `review` rows. It reads only `cache/`, and `.venv` does not exist on every machine. Without it, `queue --only-unmapped` hands you the new strings directly.

## Procedure

### 1. Baseline

```bash
python3 pipeline/adjudication.py check > .tmp/adjudication/check-before.txt
```

Note the trap failures and the counts. Your run must not add any failures.

### 2. Queue

```bash
# Normalizer review rows, weighted by how much credit each string carries:
python3 pipeline/adjudication.py queue --out .tmp/adjudication/run-<date> --batch 20

# New strings from a staged harvest that the map has never seen:
python3 pipeline/adjudication.py queue --cache-dir .tmp/ml-harvest/cache --only-unmapped \
    --out .tmp/adjudication/ml-<date> --batch 20
```

Each row in a batch carries:
- `key`;
- `raw_affiliation`;
- the current mapping;
- `matched_via` and `score`;
- `occurrences` and `credited_share`;
- `variants`: case or spacing variants already in the map, with how they are mapped.

Work top-down; the head of the queue carries most of the credit. Use `--limit` for a bounded session.

### 3. Decide

Batches can be fanned out to subagents. Put every subagent call for a wave in one assistant message, cap waves at about 6, and have workers return JSON only, never editing files. Every decision must be one of:

| decision | when | institution_id |
|---|---|---|
| `supported` | The current mapping is right. | required (education) |
| `corrected` | A different education institution is right. | required (education) |
| `noneducation` | It's a company, lab, government body, or hospital. These are never credited. | the org's own ID if known; never a university's |
| `unresolved` | Unknowable or garbage, or a compound naming two or more universities with no primary one. | none |
| `needs-policy` | Answering needs a methodology decision, e.g. a joint institute. The row stays in review. | none |

Return exactly one object per queued row:
```json
{"key": "...", "raw_affiliation": "...", "decision": "corrected",
 "institution_id": "I219193219",
 "evidence": "Case variant of 'Purdue University'; no campus named -> flagship West Lafayette",
 "decided_by": "<model or person>"}
```

**Find IDs locally first.** Run `python3 pipeline/adjudication.py search "<name>"`. Use the OpenAlex API (`/institutions?search=`, with key and mailto from `.env`) only when the local index has no candidate.

**Rules.** Each comes from a real error in this map.
- **Identify by name, never by location.** A city or country is not an institution. Examples:
  - "Qualcomm, San Diego" is not UCSD;
  - "Mitsubishi Electric Research Lab, Cambridge, MA" is not the University of Cambridge;
  - "AMD, Austin" is not UT Austin.

  `check` lists more than 200 live cases of this.
- **Multi-campus systems need a named campus.** This covers University of California / Texas / Maryland, Purdue, IIT, TU and similar.
  - The bare system name is `unresolved`. Example: "University of California" must never become UCSF.
  - A named campus or city that identifies the campus decides it.
  - Order matters: check San Francisco before San Diego.
- **Variants must agree.** If `variants` shows "Purdue University" adjudicated to West Lafayette, then "PURDUE UNIVERSITY" gets the same answer unless the string itself says otherwise.
- **Accept an acronym only if it is official for that institution.** "MIT" is Massachusetts Institute of Technology, not Manukau. An acronym clash with no supporting text is `unresolved`.
- **Same name, different country.** Northeastern US vs CN (Shenyang), Southeast CN vs BD, Northwestern US vs PH, Soochow CN vs TW. Decide on country or city evidence in the string. With no evidence, the answer is `unresolved`.
- **Compound strings** ("KAIST and Samsung") credit the education institution if exactly one is present. With two or more universities and no primary one, the answer is `unresolved`.
- **Evidence quotes the string.** Write what in the text identifies the institution, not what you believe about the authors. Author-profile knowledge ("this person is at X now") is never evidence for a paper's affiliation.

### 4. Apply

```bash
python3 pipeline/adjudication.py apply .tmp/adjudication/run-<date>/decisions-*.json --dry-run
python3 pipeline/adjudication.py apply .tmp/adjudication/run-<date>/decisions-*.json
```

Fix or drop every rejected decision; don't force them through. `--override` replaces an earlier `manual` row. Use it only with evidence that the earlier decision was wrong, and say so in that decision's `evidence`.

### 5. QA

```bash
python3 pipeline/adjudication.py check          # traps must not regress (exit 0 when all pass)
python3 pipeline/fix_acronym_collisions.py --report
python3 pipeline/fix_name_mismatches.py --report
python3 pipeline/fix_campus_clusters.py
```

The `fix_*` scripts propose. Review their output, then either run them with `--apply`, or turn individual proposals into ledger decisions so they replay.

**When you find a new class of error, add a trap row** to `data/adjudication-traps.csv`. The format is `raw_affiliation, expect, why, absent_ok`, where `expect` is one of:
- `id:I…`
- `not:I…`
- `noneducation`

Clauses can be combined with `;`. That is how this skill stays stable: a fixed error stays fixed or turns red.

### 6. After any normalizer rerun

```bash
python3 pipeline/adjudication.py replay --dry-run
python3 pipeline/adjudication.py replay
```

Normalizers can overwrite rows. The ledger is the record of what was decided.

### 7. Report

Write `data/reports/adjudication-<date>.md` covering:
- strings decided, by outcome;
- the credited share covered;
- rejected decisions and why;
- trap and `check` counts before and after;
- new traps added;
- `needs-policy` items for the user.

Then use the `verify-data` skill (phase 2, plus phase 3 after aggregating).

## PDF versus OpenAlex conflicts (per paper, not per string)

`harvest_ml.py` records `evidence.pdf_openalex_conflicts` where a high-confidence PDF affiliation and an OpenAlex affiliation disagree for the same author. These are not map rows. The final PDF is the version of record, so resolve them against the page itself:

```bash
pdftoppm -f 1 -l 1 -r 110 -png <pdf> /tmp/page
```

Then read the image. In the ICLR 2025 image check, OpenAlex was wrong in 38 of 45 such slots, usually affiliations shifted by one author in two-column layouts. Record verdicts in the edition's report. The build credits the PDF first (user decision, 2026-10-30); `--prefer-openalex` reverses that.
