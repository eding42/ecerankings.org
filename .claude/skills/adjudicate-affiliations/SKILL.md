---
name: adjudicate-affiliations
description: Use your LLM intelligence to resolve ambiguous Crossref affiliation strings that the deterministic script flagged for review.
---

# Adjudicate Affiliations

You are executing Tier 4 (LLM adjudication) of the affiliation resolution pipeline for ecerankings.org.
Crossref papers contain messy, free-text affiliation strings. The semantic script
(`pipeline/normalize_semantic.py`) embeds every affiliation with a sentence-transformer
and matches against the full OpenAlex institution index via cosine similarity on MPS/CUDA.
Ambiguous matches (cosine similarity between 0.70 and 0.85) are flagged `status=review`
in `data/affiliation-map.csv`.

Your job is to read these `review` cases, use your intelligence to adjudicate them,
and write the corrected rows back to the CSV with `status=manual`.

## Procedure

### 1. Run the semantic normalizer

Uses the venv Python (PyTorch + sentence-transformers, MPS-accelerated on Mac):
```bash
.venv/bin/python pipeline/normalize_semantic.py --all-cached
```
Add `--verbose` to see each resolution as it happens.

`pipeline/normalize_affiliations_local.py` and `pipeline/normalize_affiliations.py`
are legacy (string-similarity heuristic and OpenAlex API respectively) — **not**
the default path. They still exist as fallbacks if `data/institutions.json` is
stale or the semantic model produces obviously wrong results at scale.

### 2. Read the review queue

Read all rows in `data/affiliation-map.csv` where `status` is `review` (a
short Python/csv script is fine). For each you'll see:
- `raw_affiliation`: the messy string from Crossref (e.g., "Peter Grunberg Institut (PGI-14) and RWTH Aachen University")
- `institution_name` / `institution_id`: the script's top semantic match
- `candidate`: the specific substring the script extracted and matched
- `score`: the cosine similarity score (0.70–0.85 range, by definition of `review`)
- `matched_via`: the institution variant name that scored highest (e.g. "KAIST" matched against the "kaist" variant in the index)

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
  tells the semantic script to NEVER overwrite it on a future run.
  `unmatched` decisions get `status = "unmatched"` instead.
- Preserve `raw_affiliation` exactly as it appears in the CSV — it's the
  primary key.
- For `unmatched`, clear `institution_id`/`institution_name`/`institution_type`.
- `institution_type` must be a real OpenAlex type (`education`, `company`,
  `facility`, `government`, or `nonprofit`) — not free text.
- If a subagent's JSON is missing/malformed for a row, leave that row
  untouched (still `review`) and note it in your report rather than guessing.

### 5. Post-adjudication QA: acronym validation

After merging, validate that every `auto`/`manual` row where `matched_via` is a
short (≤5 characters, all-alpha) string is a **legitimate acronym** of the
matched institution. Run:

```bash
python3 -c "
import csv, json

with open('data/institutions.json') as f:
    db = json.load(f)

with open('data/affiliation-map.csv') as f:
    rows = list(csv.DictReader(f))

suspicious = []
for r in rows:
    if r['status'] not in ('auto', 'manual'):
        continue
    mv = r.get('matched_via', '')
    if len(mv) <= 5 and mv.isalpha():
        inst_id = r.get('institution_id', '')
        inst = db['by_id'].get(inst_id)
        if inst:
            official_acronyms = [a.lower() for a in inst.get('acronyms', [])]
            if mv.lower() not in official_acronyms:
                # Check display_name_alternatives too
                alts = [a.lower() for a in inst.get('alternatives', [])]
                if mv.lower() not in alts:
                    suspicious.append((mv, inst['display_name'], r['raw_affiliation'][:60]))
        else:
            suspicious.append((mv, 'NO DB RECORD', r['raw_affiliation'][:60]))

if suspicious:
    print(f'{len(suspicious)} row(s) where matched_via is NOT an official acronym:')
    for mv, name, raw in suspicious[:30]:
        print(f'  \"{mv}\" -> {name}')
        print(f'             {raw}')
else:
    print('All short matched_via values are legitimate acronyms.')
"
```

For each flagged row, decide whether the match is still correct (e.g. "MIT" is
the universally known shorthand for Massachusetts Institute of Technology even
if OpenAlex lists "MIT" as an alternative, not an acronym) or if the match is
a false positive (e.g. "Purdue" matching "Purdue Pharma" — correct the row).
Write corrections to the CSV as needed.

### 6. Post-adjudication QA: institution type validation

After the acronym check, verify that every `auto`/`manual` row's
`institution_type` matches the actual entity type. The semantic model's city-name
collision problem (e.g. "Qualcomm AI Research, San Diego" matched to UC San Diego)
causes false `education` classifications for companies. Run:

```bash
python3 -c "
import csv

EDU_NAMES = {'University', 'College', 'Institute of Technology', 'Hochschule',
             'Universität', 'École', 'Politecnico', 'Instituto', 'Institut',
             'Academy', 'School of'}

with open('data/affiliation-map.csv') as f:
    rows = list(csv.DictReader(f))

# Check 1: institutions named like education but classified as company
false_company = []
for r in rows:
    if r['status'] in ('auto', 'manual') and r.get('institution_type') == 'company':
        name = r.get('institution_name', '')
        if any(kw.lower() in name.lower() for kw in EDU_NAMES):
            false_company.append(r)

# Check 2: education matches where raw_affiliation mentions a company
# and matched_via is a location (city/country), not the institution name
CITY_WORDS = {'tokyo', 'beijing', 'shanghai', 'seoul', 'london', 'paris',
              'berlin', 'munich', 'boston', 'san diego', 'san jose', 'santa clara',
              'dallas', 'austin', 'seattle', 'palo alto', 'mountain view',
              'sunnyvale', 'cambridge', 'oxford', 'zurich', 'geneva', 'hong kong',
              'singapore', 'shenzhen', 'guangzhou', 'nanjing', 'hangzhou',
              'chengdu', 'wuhan', 'xian', 'tianjin', 'suzhou', 'dresden',
              'stuttgart', 'hamburg', 'frankfurt', 'aachen', 'eindhoven',
              'delft', 'helsinki', 'stockholm', 'copenhagen', 'oslo',
              'melbourne', 'sydney', 'toronto', 'vancouver', 'montreal',
              'taipei', 'hsinchu', 'kyoto', 'osaka', 'tokyo', 'yokohama',
              'nagoya', 'bengaluru', 'hyderabad', 'mumbai', 'delhi', 'pune'}

corp_keywords = {'inc', 'inc.', 'ltd', 'ltd.', 'gmbh', 'corp', 'corp.',
                 'corporation', 'llc', 'co.', 'limited', 'company'}

false_education = []
for r in rows:
    if r['status'] in ('auto', 'manual') and r.get('institution_type') == 'education':
        raw = r.get('raw_affiliation', '').lower()
        mv = r.get('matched_via', '').lower()
        score = float(r.get('score', 0))
        # Flag if raw contains company keywords AND matched_via is a city name
        has_corp = any(kw in raw for kw in corp_keywords)
        is_city = mv in CITY_WORDS
        if has_corp and is_city and score < 0.90:
            false_education.append(r)

if false_company:
    print(f'=== Companies named like education ({len(false_company)}) ===')
    for r in false_company:
        print(f'  {r[\"institution_name\"][:50]} | via={r[\"matched_via\"][:20]}')
        print(f'    raw={r[\"raw_affiliation\"][:70]}')

if false_education:
    print(f'\\n=== Education matches that look like companies ({len(false_education)}) ===')
    for r in false_education[:30]:
        print(f'  score={r[\"score\"]} {r[\"institution_name\"][:50]}')
        print(f'    via={r[\"matched_via\"][:20]} raw={r[\"raw_affiliation\"][:70]}')
    if len(false_education) > 30:
        print(f'  ... and {len(false_education)-30} more')

if not false_company and not false_education:
    print('All institution types look correct.')
"
```

For each flagged company, decide if it's really a company (most Chinese "Research
Institutes" are state-owned enterprises → `company` is correct) or a misclassified
education institution (e.g. "Medical University of Vienna" → `education`). For
each flagged education match, the raw affiliation is likely a company that the
model matched to a nearby university by city name — set `institution_type` to
`company` and clear the `institution_id` if unknown. Write corrections to the CSV.

### 7. Post-adjudication QA: UC campus validation

After fixing type errors, validate that every `auto`/`manual` row containing
`"University of California"` in the raw affiliation is mapped to the **correct
campus**. The semantic model's city-name collision problem routinely maps bare
"University of California" or "University of California,<dept>" to UCSF
(`I180670191`), even when the raw string contains a specific campus name
(e.g. "Los Angeles", "San Diego", "Berkeley").

Run:
```bash
python3 -c "
import csv

CAMPUS_KEYWORDS = {
    ('los angeles', 'ucla'): ('https://openalex.org/I161318765', 'University of California, Los Angeles'),
    ('berkeley',): ('https://openalex.org/I95457486', 'University of California, Berkeley'),
    ('san diego', 'ucsd', 'la jolla'): ('https://openalex.org/I36258959', 'University of California San Diego'),
    ('santa barbara', 'ucsb'): ('https://openalex.org/I154570441', 'University of California, Santa Barbara'),
    ('irvine', 'uci'): ('https://openalex.org/I204250578', 'University of California, Irvine'),
    ('davis',): ('https://openalex.org/I84218800', 'University of California, Davis'),
    ('santa cruz', 'ucsc'): ('https://openalex.org/I185103710', 'University of California, Santa Cruz'),
    ('riverside', 'ucr'): ('https://openalex.org/I103635307', 'University of California, Riverside'),
    ('merced',): ('https://openalex.org/I156087764', 'University of California, Merced'),
    ('san francisco', 'ucsf'): ('https://openalex.org/I180670191', 'University of California, San Francisco'),
}

mismatches = []
with open('data/affiliation-map.csv') as f:
    for r in csv.DictReader(f):
        raw = r['raw_affiliation'].lower()
        if 'university of california' not in raw:
            continue
        for keywords, (expected_id, expected_name) in CAMPUS_KEYWORDS.items():
            if any(kw in raw for kw in keywords):
                if r['institution_id'] != expected_id:
                    mismatches.append((raw[:70], r['institution_name'], expected_name))
                break

if mismatches:
    print(f'{len(mismatches)} UC campus mismatches found:')
    for raw, current, expected in mismatches[:30]:
        print(f'  {raw}')
        print(f'    {current} -> should be {expected}')
else:
    print('All UC campus assignments are correct.')
"
```

For each mismatch, update the row's `institution_id`, `institution_name` to the
correct campus, set `status` to `manual`, and ensure `country_code` is `US` and
`institution_type` is `education`.

**Known edge cases**: "Davis" can be a person's surname — the keyword check
above may produce false positives in strings like "Davis Research Group,
University of California..." Verify each flagged Davis case by checking if
"Davis" appears at the end of a comma-separated token or adjacent to "CA"/"USA".

### 8. Report

Re-run the semantic script with `--report-only` to show updated coverage:
```bash
.venv/bin/python pipeline/normalize_semantic.py --all-cached --report-only
```
Summarize how many rows were adjudicated (confirm/correct/company/unmatched
breakdown), how many batches ran, and what the trickiest cases were.
