# Acronym-collision & name-mismatch repair — 2026-07-24

## Problem

`normalize_semantic.py` systematically misattributed affiliations in two ways:

1. **Acronym collisions**: `build_candidates` extracts parenthetical acronyms
   as candidates, and an exact acronym hit embeds at cosine ~1.0 against the
   acronym variant of *every* institution that lists it. `torch.max` then
   picks an arbitrary owner — even when the raw string spells out the correct
   full name next to the acronym. Confirmed victims: MIT → Manukau Institute
   of Technology (NZ), KTH → Khyber Teaching Hospital (PK), TUM → Technical
   University of Mombasa (KE), FAU → Florida Atlantic instead of
   Friedrich-Alexander-Universität, CNRS → National Council for Scientific
   Research (LB), DLR → Dienstleistungszentrum Ländlicher Raum, and many more.
2. **Evidence-free semantic matches**: a generic candidate segment (department
   phrase, sub-brand, city token) cosine-matches an unrelated institution
   above the 0.85 auto threshold, e.g. `"G. Marconi" University of Bologna,
   Dept. of Electrical, Electronic and Information Engineering` → "Ministry of
   Electronics and Information Technology" (IN) at 0.853, or `Ericsson, Pisa,
   Italy` → "Polymer Institute of the Slovak Academy of Sciences".

## Repair (data)

- `pipeline/fix_acronym_collisions.py` (new, permanent): for auto rows whose
  `matched_via` is an acronym shared by 2+ institutions, reassign by
  full-name-containment (strongest signal), then country evidence; remainder
  flagged. **509 rows auto-fixed.**
- `pipeline/fix_name_mismatches.py` (new, permanent): for auto rows with zero
  evidence for the assigned institution, reassign when a different
  institution's name variant matches a **whole comma-segment** of the raw
  string (mid-segment containment is only a flag — "Institute of Science"
  inside "Indian Institute of Science" must not reassign). **206 rows
  auto-fixed.**
- **830 flagged/ambiguous rows LLM-adjudicated** (adjudicate-affiliations
  skill, 42 Haiku batches): 124 confirm / 618 correct / 88 unmatched, plus 35
  city-token rows (Pisa/Genoa/SZ) fixed directly.
- Shared normalizer improvements: `&`→`and`, drop `the`, expand
  `univ/inst/natl/acad/lab(s)`, strip diacritics.

## Impact (adjusted counts, all areas)

Top transfers (before → after totals):

| Institution | Δ |
|---|---|
| Massachusetts Institute of Technology | +89.0 (Manukau IT −88.8) |
| Seoul National University | +32.2 |
| National University of Singapore | +27.6 |
| University of Luxembourg | +20.7 |
| Karlsruhe Institute of Technology | +19.8 |
| Technical University of Munich | +19.7 (TU Mombasa −18.2) |
| FAU Erlangen-Nürnberg | +18.8 (Florida Atlantic −18.8) |
| Université Paris-Saclay | +16.9 |
| IIIT Hyderabad | +15.2 |
| KTH Royal Institute of Technology | +11.6 |

CNRS gained ~150 rows of credit (government type, not ranked directly but no
longer credits Lebanon's NCSR).

## Prevention

- `normalize_semantic.py`: `build_inst_index` now marks variant texts owned
  by 2+ institutions as *ambiguous*; `resolve_batch` never auto-accepts a
  match won via an ambiguous variant or a DEPT_RE-matching candidate — such
  rows cap at `status=review` for adjudication.
- `verify.py` phase 2 gained check **2e2**: dry-runs both fixers on every
  verification pass and raises a HIGH flag if either finds fixable rows.
  Both currently report 0.

## Known remaining issues (pre-existing, unchanged by this fix)

- `data/known-strong.json` lists 4 institution IDs absent from
  `data/institutions.json` (I1286801614, I165779244, I1313843922, I47303974)
  that have always aggregated to zero; University of Idaho has no `embedded`
  credit before or after. These predate this repair — the known-strong list
  or the harvest coverage needs review.
- Harvest-quality flags (zero-author works, CVPR/DAC year floors, duplicate
  titles in automatica/cleo) are unrelated to affiliation mapping.
