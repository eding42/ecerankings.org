# ICLR 2025 checkpoint — 2026-10-29

ML remains off by default. The publisher-first pilot is staged; it is not an
accepted ranking dataset. Use [ml-pipeline.md](ml-pipeline.md) for commands.

`data/refresh/ml-harvest-2026-10-29.json`, generated at 2026-10-30T06:32:45Z,
records 3,703 works with publisher bylines and PDF-first evidence. Proceedings
and authenticated OpenReview agree on 3,703 papers; the fact sheet differs by one.

- Affiliation coverage: 17,316 / 21,270 slots (81.41%); required 90%.
- Institution resolution: 14,705 / 17,316 covered slots (84.92%); required 95%.
- Membership, byline integrity, scope purity, profile leakage, and PDF-evidence
  checks pass. PDF verification and both coverage gates remain incomplete.
- Prepared image tasks: 1,139 (804 review papers, 135 conflicts, 200 sample).
  Preparation does not establish image accuracy.
- Twenty pilot papers have reviewed drafts. Reconcile corrected drafts with
  current batch identities before acceptance; the remaining queue is unfinished.
- The affiliation ledger holds 639 entries across sessions, including the last
  repair's 154 decisions. All 17 adjudication traps pass, with other QA findings open.

ML-scoped phase-2 verification reported 0 critical, 25 high, 8 medium, and 10 low
findings, including global map metadata and ICLR lineage/purity issues. This is
not a clean release result; do not suppress findings by advancing snapshots.

Resume from the saved task lists and per-paper drafts in `.tmp/ml-harvest/` and
`ai_temp/`. Preserve source images, partial attempts, and quarantine evidence.
Validate the corrected pilot before scaling, apply only reviewed batches, then
normalize/replay adjudications and rerun the gates. Candidate aggregation follows
only after the gates pass; ML enablement and publication remain separate decisions.
