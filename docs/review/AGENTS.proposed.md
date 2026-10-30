# Proposed repository instructions

This is a review artifact, not the active repository `AGENTS.md`. Adopt it after the corresponding safe commands exist.

## Project

ECERankings counts publications at curated venues and serves a static ranking site. Preserve the counting methodology unless the user requests a change. Read `docs/methodology.md` for policy, the venue registry for current configuration, and `docs/operations.md` for commands.

## Data rules

- Count a work once per declared ownership scope. Normalize DOI and institution identifiers through shared helpers.
- Credit institutions at publication time; current author-profile affiliations are separate evidence.
- Preserve raw provider records. Store enrichment and overrides separately with source URL, checked date, reason and review status.
- A nonempty provider resolution can still be wrong. Exact reviewed overrides take precedence through one resolution path.
- Never merge institutions from a shared name alone, even with matching countries. Verify campus identity or an authoritative identifier/redirect.
- Automated title/semantic checks propose corrections or exclusions; they do not become human-reviewed decisions by being saved.
- Partial-year and incomplete-source coverage must remain visible. No data and failed data are distinct states.

## Workflow

1. Inspect the current registry, accepted release and existing evidence for the requested scope.
2. Plan exact venue-year/provider requests and estimate shared API spend. Reuse valid observations while applying the requested freshness policy.
3. Fetch into an isolated run directory. Validate pagination, identity, schema and checksums before declaring a fetch complete.
4. Generate correction proposals and unresolved findings; apply only sufficiently evidenced changes within the user's scope.
5. Build a complete candidate release and compare coverage, counts, credited share and public ranking against the accepted release.
6. Validate read-only. Promote only a complete validated release. Deployment is a distinct action authorized by the user.

Continue reversible steps already authorized by the user. Ask only for missing credentials, a consequential policy decision, or an action outside the authorized scope. Do not add a second harvesting approval to an explicit refresh request.

## Delegation

Use the model/provider requested by the user when available. Assign disjoint files or independent proposal outputs; one integrator owns shared curated tables and final publication. Include scope, budget, evidence requirements and acceptance criteria in each task. Validate worker results; a model's confidence is not source evidence. Do not hardcode tool-call syntax, provider names or synchronous wave mechanics here.

## Verification and publication

Validation must not modify curated inputs or advance accepted baselines. Treat required-data fetch errors, incomplete pagination, invalid identities, unaccounted credit changes and missing release artifacts as blocking errors. Record known external gaps explicitly without mislabelling them fixed. Check the actual release math and magnitudes, not only rank order.

Do not print credentials or authenticated URLs. Keep `.env` ignored. Follow the user's explicit instructions for committing, pushing and deployment; ordinary implementation work does not grant permission to commit or push.
