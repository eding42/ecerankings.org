---
name: refresh-data
description: Use when asked to refresh, rebuild, validate, promote, or publish the ECERankings data end-to-end, including "push the new data", monthly/quarterly refreshes, and release packaging.
---

# Refresh and publish rankings data

Read `docs/refresh-runbook.md` in full before running anything. It is the
authoritative procedure: preflight, the validated release path, stop
conditions, commit paths, and the Cloudflare deploy step.

Do not reconstruct the steps from `README.md` or memory. The runbook exists
because the direct path (`aggregate.py` into `site/data`) bypasses the hash
gates and the regression baseline.

## Non-negotiables

- Never commit or push without explicit confirmation (`AGENTS.md`).
- "Refresh" means build + verify + report. "Push the refresh" means a branch
  and a PR. "Merge/deploy" is a separate approval.
- Stop on any critical/high `verify.py` flag, a coverage drop over 5
  percentage points, or an artifact hash mismatch. Report; do not promote.
- Use explicit `git add` paths; never `git add -A`.
- Never stage `.env`, `.tmp/`, `data/institutions.json`, or `data/reports/`.
- Do not run `normalize_semantic.py` in an automated refresh; it is
  non-deterministic and needs `.venv`.

## Handback

Report the scope, cache/works counts, coverage before and after, regressions,
top movers, the manifest path and hash, and any skipped steps. State clearly
whether the candidate was promoted and whether anything was pushed.
