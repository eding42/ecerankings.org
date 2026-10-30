# OpenAlex journal refresh — 2026-10-28

The accepted refresh is complete: **457 of 457 eligible journal-year scopes**, covering **442,255 works** in 42 journals. All 369 default-on scopes and 88 optional scopes are accepted. The collection covers 2016–2026, clipped to each source's earliest checked publication year. **2026 is partial; a completed query is not proof of publisher completeness.**

## Independent acceptance

The final audit, `data/refresh/journal-final-validation-2026-10-28.json`, found zero integrity issues. It binds the accepted manifest hash and independently verifies every file's SHA-256, row count, edition year, DOI/work identity, registered source IDs, exact query predicate, provider attribution, authorship structure and raw affiliation strings. There are no unresolved scopes, partial stages or checkpoints.

Accepted files contain 4,301,106 authorships and 6,077,345 raw affiliation strings (2,460,625,105 bytes). All 2,068 list records with at least 100 authorships were hydrated through the individual-work endpoint, with work-ID and DOI identity checks. Complete bylines supply the 1/N denominator.

The collector used an observed `per-page=200`, recorded in per-file query provenance. It checks pagination against the API's advertised count before atomic publication. Raw affiliations, normalized institution assertions and collection provenance are retained. The accepted provider cache is `.tmp/refresh-2026-10-28/journals/cache`; the per-scope receipt is `data/refresh/journal-works-2026-10-28.json`.

## Recovery and request accounting

The server restart erased the earlier `/tmp` collection. Recovery now uses ignored checkout storage. Two overlapping recovery writers were stopped and their outputs quarantined. Independent checks recovered 88 complete files; an exclusive cache/manifest lock and staged-row guard prevent the same race from recurring.

The subsequent single-writer Luna run encountered sandbox DNS failures: 1,476 list attempts, including 1,107 retries, produced no new accepted scopes. Those transport attempts must not be counted as charged OpenAlex calls or as missing bibliographic records. That handoff and its earlier estimate remain historical evidence in `data/refresh/interrupted-2026-10-28/journal-report-before-parent-recovery.md`.

The parent resumed with network access at 23:09 UTC on October 28. It completed the other 369 scopes. One local list ceiling stopped the run safely; after verifying the new UTC day's free allowance, one guarded resume finished the collection. The parent made **2,266 list attempts and 2,068 singleton attempts**, with one retry. Cumulative manifest counters are **4,453 list attempts, 2,068 singleton attempts and 1,108 retries**; they include prior recovery history and are not billing totals. Live free-balance snapshots are stored separately in `.tmp/refresh-2026-10-28/openalex-budget-snapshots.json`. No prepaid allowance was needed.

Historical errors are preserved in the manifest. Its final unresolved arrays are empty; repaired errors are not presented as current collection gaps. The collector now stops broad collection on exhausted network failures or rate/budget exhaustion.

## Release integration and limits

These staged observations are inputs to a separate full-corpus candidate. For registry-declared Crossref journal years, earlier publisher membership missing from an OpenAlex query is retained with an explicit count. Prior paper-specific affiliations are filled only under DOI/title and unambiguous author-identity checks; current nonempty assertions take precedence. Provider observations remain available separately.

The final release report records promotion and deployment. Collection completeness does not establish correct institution resolution, exhaustive publisher coverage or absence of non-research items. The whole project still has the limitations documented in the architecture review.

Validation: the 64-test Python safeguard suite and frontend tests pass; the journal-specific audit above independently checks the actual collected files.
