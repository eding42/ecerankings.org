# ML pilot checkpoint — 2026-10-29

This checkpoint preserves the publisher-first implementation and evidence. It
is not an accepted ML dataset or a release. ML remains off by default.
The implementation plan is [ml-fix-plan-2026-10-29.md](ml-fix-plan-2026-10-29.md).

## Current saved state

The manifest `data/refresh/ml-harvest-2026-10-29.json` was generated at
2026-10-30T06:32:45Z. It records 3,703 ICLR 2025 works with publisher bylines,
paper-specific evidence, and PDF-first precedence. Proceedings and authenticated
OpenReview membership agree on 3,703 papers; the fact sheet's 3,704 differs by one.

- Paper-specific affiliation coverage: 17,316 / 21,270 slots (81.41%); gate 90%.
- Institution resolution: 14,705 / 17,316 covered slots (84.92%); gate 95%.
- Membership, byline integrity, scope purity, profile leakage, and PDF-evidence
  checks pass. PDF verification and both coverage gates remain incomplete.
- Image preparation saved 1,139 tasks: 804 review papers, 135 conflicts, and
  a fixed 200-paper sample. Preparation is not image verification.
- The previous session reviewed a 20-paper pilot and saved corrected drafts.
  Those drafts still need reconciliation with the current batch identities
  before acceptance. The full remaining queue has not been completed.
- Affiliation corrections are saved in `data/affiliation-decisions.jsonl`;
  639 ledger entries exist across sessions. The last repair applied 154 decisions.
  All 17 adjudication traps currently pass.
- Native Luna concurrency was tested separately: ten active workers reached a
  barrier together and were released. This test performed no PDF verification.

## Validation during check-in preparation

`pipeline/adjudication.py check` passes all 17 traps, but reports other map QA
findings. `pipeline/verify.py --phase 2 --area ml --cache-dir .tmp/ml-harvest/cache`
reports 0 critical, 25 high, 8 medium, and 10 low findings. These include global
map metadata issues and ICLR native-lineage/purity findings; this is not a clean
release check. Do not advance verification snapshots to suppress these findings.

The prepared cache, rendered images, checkpoint drafts, and quarantined attempts
remain local under `.tmp/ml-harvest/` and `ai_temp/`. They are deliberately not
part of the source check-in. Preserve these directories until the queue is done.

## Resume

1. Validate the corrected pilot against current tasks and source images.
2. Process the remaining tasks with the authorized Luna workers, retaining one
   complete checkpoint per paper and holding uncertain author-mark mappings.
3. Apply only validated batches, normalize new strings, replay adjudications,
   and rerun map QA and ML gates.
4. Build and compare an isolated aggregate after the gates pass. Promotion,
   publication, and changing ML's default are separate decisions.
