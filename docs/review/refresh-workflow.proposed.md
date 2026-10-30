# Proposed collection skill contract

Replace the current collection/adjudication choreography with a provider-independent contract. The domain checks remain; repeated model instructions and mandatory extra approvals for already-authorized refreshes do not.

## Inputs

`scope`: explicit venue keys, edition years, and requested freshness; `budget`: a shared request/spend cap; `destination`: an isolated run directory; `policy_version`: the accepted counting/ownership rules; `baseline`: the last accepted release. If no years were requested, state the chosen ten-year completed-year window and handle the current year as a separately labelled partial observation.

## States

`planned → fetching → fetched → canonicalized → validated → candidate-release → accepted`

Failures and insufficient evidence enter `blocked` or `needs-review` for the affected scope, with a concrete reason. An HTTP failure is never a successful empty result. A complete API response is not proof that the provider has every publisher record. A registry identity status and data coverage status are separate fields.

Run one connectivity probe in the actual execution environment before a broad pull. Stop a shared transport failure rather than repeating it across every venue-year. Distinguish attempted local requests from requests charged by the provider; use the provider's live balance for spend decisions.

## Worker output

Every requested venue-year gets one structured result: provider/query parameters without secrets, exact evidence URLs, observed and expected counts and their semantics, pagination receipts, duplicate/conflict counts, byline and affiliation coverage, artifact SHA-256, checked timestamp, status, and unresolved questions. Proposals contain exact before/after fields and the evidence for each; no prose-only or malformed response is silently accepted.

## Validation

Validate venue identity, edition-year assignment, archival track, complete pagination, source-count reconciliation, DOI ownership, schema, byline completeness, credit conservation, institution/country identity and cross-file artifact reconciliation. A small sampled affiliation percentage is labelled sampled; it does not certify all years. Counts are compared by like type and time window. Official accepted-paper totals and indexed research-work totals may differ and need a stated reconciliation.

## Adjudication

Sort unresolved affiliations by occurrence and estimated credited-share impact. Provide the worker the raw paper-specific string, candidates, conflicting provider assertions and existing overrides. Require exact institutional identity evidence, with no guessed campus or author identity. Outcomes are `supported`, `corrected`, `noneducation`, `unresolved`, or `needs-policy`; automated and human-reviewed states remain distinct. A compound string can resolve to several organizations; do not force all evidence into one arbitrary institution.

## Integration

Workers write disjoint observations/proposals. One integrator verifies target IDs, applies accepted patches once, builds a complete candidate, and publishes a report explaining absolute changes and retained gaps. Validation is pure. Acceptance advances the baseline explicitly. Existing user authorization determines whether fetching and publication are allowed; the skill does not repeatedly ask for already-authorized operations.

Use durable checkout storage for long-running observations and checkpoints. Enforce one process writer per cache and manifest with an OS lock. Retain a running command's session identifier: a yielded command is still running and must be resumed, not launched again. Before accepting a staged fetch, reconcile its actual rows with checkpointed page counts and verify its published bytes against the manifest.
