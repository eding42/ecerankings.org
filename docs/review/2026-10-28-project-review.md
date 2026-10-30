# ECERankings project review and migration proposal

Review date: 2026-10-28. Baseline: commit `24c738f`. Findings in this document describe that baseline unless a later implementation is explicitly identified. The accompanying refresh manifests and frontend redesign report describe work performed after the review. A source lookup, a complete API pull, and a publisher-complete bibliography are different levels of evidence.

## Assessment

Keep the central architecture: a curated venue registry, bibliographic ingestion, institution attribution, offline aggregation, and a static public site. It fits the scale, permits independent inspection, avoids a production database, and makes the ranking formula reproducible. The main weakness is the boundary between those stages. Files that serve as source evidence are also rewritten as enrichment output; commands silently publish scoped results; verification modifies its inputs; registry notes encode executable rules that the code ignores; and the public site does not identify an exact data release.

This is primarily a correctness and operations problem, followed by a presentation problem. A framework migration, a web backend, an agent framework, or a more elaborate ranking formula would not resolve it. The first goal should be a demonstrably correct release of the existing methodology.

## What was inspected

All 17 baseline Python modules, the active HTML/JavaScript/CSS and obsolete inline frontend, the venue registry, curated corrections and institution snapshot, generated CSV/JSON, README, PLAN, CLAUDE instructions, three repository collection/adjudication/verification skills, reports, tracked files, ignore/LFS rules, git history, and the running frontend. The raw corpus was unavailable initially because Git LFS was not installed or configured. Its public LFS objects were recovered into an isolated temporary tree and every downloaded object was checked against its committed SHA-256 and byte count.

Baseline measurements:

| Item | Observed |
|---|---:|
| Areas / default-on areas | 20 / 18 |
| Venues / journal / conference | 69 / 42 / 27 |
| Cached venue-year work files | 775 |
| LFS pointer work files / empty placeholders | 767 / 8 |
| Raw cached work records after LFS recovery | 595,446 |
| Raw work bytes referenced by work-file pointers | 1,469,557,198 |
| Aggregate institution-area-year rows | 137,781 |
| Aggregate institution-venue-year rows | 252,045 |
| Unique aggregate institution identifiers | 8,894 |
| Aggregate year extent | 1981–2026 |
| Repeated DOI/OpenAlex identities within a single file | 294 extra occurrences |
| Records whose publication year differs from their cache bucket | 1,393 |
| TECS records explicitly assigned to EMSOFT in registry but still counted under both | 55 |

Positive checks also matter: the baseline aggregate has no duplicate institution-area-year keys; all 20 per-area JSON files exactly reproduce the area CSV; venue adjusted counts reconcile to area adjusted counts within rounding tolerance; both registry copies are byte-identical; and every registered venue contributes some credit. Those facts establish consistency between generated files, not correctness of the underlying bibliography or attribution.

## Highest-priority findings

### R01 — A scoped aggregation overwrites the full public dataset

**Critical.** `pipeline/aggregate.py:main` chooses only the requested `--venue`/`--year` scope, then opens the three fixed public output paths with mode `w`. Its docstring says the outputs still cover the full cache; the code does not. A perfectly reasonable `--venue jssc --year 2025` diagnostic can replace the site's complete ranking corpus with one journal-year. Atomic writes alone would not fix the semantic mistake.

Require an explicit output directory for scoped runs; make full publication a separate command consuming a full validated build. Produce all outputs in a release directory, validate them together, then publish that directory. Add an integration test that hashes an existing complete release, runs a scoped command, and proves the release is unchanged.

### R02 — Verification can rewrite curated affiliation data

**Critical.** `pipeline/verify.py:phase2_normalization` runs `fix_campus_clusters.py` as a subprocess. That module executes at import/script top level and rewrites `data/affiliation-map.csv` whenever it finds matches. Consequently an alleged check can change manual decisions after aggregate files were built. It does not inspect the subprocess return code. The fixer also assigns `US` to a missing country whenever the target ID contains `openalex.org/I`, which is true for institutions around the world.

Separate a pure detector returning proposals from an explicit correction applicator. Verification must not write curated data or advance the accepted baseline. Treat a detector failure as an error, not a clean result. Test both file immutability and error propagation.

### R03 — Duplicate work identities inflate credit

**High.** Aggregation does not deduplicate work identities. A fixture containing the same one-author DOI twice produces `pub_count=2` and `adjusted_count=2.0`. The recovered corpus contains 294 extra within-file occurrences. The largest concentrations include PRX Quantum 2026 (53), Quantum Science and Technology 2026 (29), npj Quantum Information 2026 (23), and RA-L 2026 (21). These identity counts do not assert that duplicate records have byte-identical metadata.

Normalize DOI identities once through `workkey.py`, record duplicate/conflicting source records, and resolve them deterministically before attribution. Keep work identity separate from venue membership: one work can be represented by several providers and can appear in more than one publication channel. Tests should cover repeated pages, same DOI/different OpenAlex IDs, missing DOI, and conflicting records with different affiliation completeness.

### R04 — An explicit TECS/EMSOFT ownership decision is not implemented

**High.** The registry's `tecs.exclude_dois` lists 55 papers assigned to EMSOFT by a recorded user decision. `harvest.py` and `aggregate.py` never read this field. All 55 are present under both cached venues. Because both venues belong to Embedded Systems, those papers inflate even a single-area ranking.

Enforce ownership at canonicalization/aggregation, not only at harvest: older caches must also obey the decision. A fixture should place the same DOI in TECS and EMSOFT and require exactly one paper's institutional credit. Do not infer exclusions from author count or title alone.

### R05 — Source IDs are confused with edition-year constraints

**High.** `harvest.py:resolve_year_sources` omits the publication-year filter for an allegedly precise conference ID unless the registry already reuses that ID in multiple years. That assumes the source's scope from registry structure instead of evidence. `vlsi-tech/2021` actually contains records dating from 1981; 1,062 of its records have a different publication year. DAC 2001 and 2003 account for another 331 discrepancies: their registry already documents a provider year-label error, but aggregation credits the provider year without applying the edition correction.

Store `edition_year` and `publication_year` separately. Use explicit, validated source membership rules per edition. Apply a year filter where appropriate, and preserve a narrowly evidenced edition-year override where the provider is wrong. Do not silently discard valid archival records just to make a bucket look clean. Reconcile changed live counts before replacement.

### R06 — Native OpenAlex ingestion discards evidence needed for repair

**High.** `harvest.py:trim_work` removes raw affiliation strings, raw names, truncation information, and reported author-count evidence. Aggregation divides by the retained authorship array length. OpenAlex's list endpoint returns at most the first 100 authorships; its single-work endpoint supplies the longer byline. Thus a large-collaboration paper can be credited with the wrong denominator and missing later authors, with no flag surviving ingestion. The baseline has many exactly-100-author records, especially in general-science journals; exactly 100 is a diagnostic signal, not proof of truncation for each record.

Preserve raw affiliation strings and available author-count/truncation fields. Fetch the individual work when the list is truncated or the returned count indicates a longer byline; explicitly record uncertainty at any upstream hard limit. Add a >100-author fixture and require conserved per-author credit. See [OpenAlex authorship documentation](https://help.openalex.org/data/authorships/).

### R07 — Affiliation overrides do not apply consistently

**High.** `aggregate.py` uses the curated map only when the author's native `institutions` array is empty. A wrong but nonempty native resolution bypasses every correction in that map. Conversely, map rows that say education can credit an ID that actually represents a hospital, company, or unrelated institution. The institution audit found concrete manual name/ID conflicts, including NYU Tandon labelled with MIT's ID and NCTU labelled with UNC's ID.

Use one resolution path with explicit precedence: exact work/authorship override, exact verified raw-string override, verified provider assertion, deterministic candidate, unresolved. Preserve the losing assertions and the reason for the chosen result. Never equate a large cosine similarity with verified identity. Validate target IDs live before applying corrections; historical affiliation must remain attached to the paper, not to an author's current profile.

### R08 — Backfill can erase known information and make transient failures permanent

**High.** `backfill_openalex.py:merge_work` replaces the entire byline. That avoids unsafe positional matching, but can discard valid Crossref authors/affiliations when OpenAlex is partial. `fetch_batch` returns `{}` after exhausted transport failures; the caller treats that as missing DOI data and writes permanent negative-cache entries. Negative entries have no expiry. Native-ID records are excluded from repair based on a historical 20-work probe, so improvements at the provider cannot be recovered.

Keep source bylines and affiliation assertions separately. Merge only under explicit identity/evidence rules, require a non-regression check on usable information, and quarantine conflicts. Distinguish HTTP failure, authenticated successful empty result, no DOI match, and a match with no affiliations. Give negative observations dates and a retry policy.

### R09 — Semantic Scholar author-profile affiliations are used as historical paper affiliations

**High.** `harvest_s2.py` joins paper authors to the separate authors dataset, then writes author-profile `affiliations` into every historical paper. That does not establish affiliation at publication. It violates the meaning of the default mode even if the organization identity is correct. Exact venue-name matching and a substring check for NeurIPS are also an insufficient definition of accepted archival proceedings.

Use official accepted-paper/proceedings lists for venue membership and paper-specific affiliation evidence for attribution. Profile affiliations may be stored as a separate current-profile assertion, but must not supply historical credit. Keep ML off by default until coverage and temporal validity are established. Official proceedings counts do not by themselves supply affiliation data.

### R10 — Checkpoints implement “download once”, not refresh

**High.** A `done` checkpoint causes harvests to skip indefinitely, including a current-year partial harvest. The OpenAlex source fingerprint excludes important request semantics; its resumed count restarts at zero, and a crash between appending a page and recording its cursor can replay that page. Crossref checkpoints do not retain a resumable cursor and interrupted runs restart by truncating the output. Neither path publishes a clearly validated immutable fetch.

Introduce an explicit refresh operation; bind checkpoints to all query semantics and the run ID. Use transactional page receipts or a temporary generation plus final deduplication and count validation. Expire partial-year observations. A completed fetch means that query completed at that time, not that a venue-year is permanently complete.

### R11 — The verifier cannot serve as a publication gate

**High.** Critical/high findings print but `main` exits successfully. Phase 3's supposed per-venue contribution check reads the area CSV, so a dead venue can hide behind another venue in the same area. Ranking regression uses all-area raw adjusted-count totals rather than the public selected-area geometric mean/year window. Uniform loss of half the credit can preserve rank order and pass the strongest checks. Snapshot files are overwritten even after a bad/scoped run; the next run can then “pass” against the failure.

Return structured findings and a nonzero exit status for release-blocking failures. Compare paper counts, credited shares, unresolved share, each venue's contribution, and the actual public ranking selection against an explicitly accepted release. Keep accepted snapshots immutable until a separate promotion step. Maintain known source gaps visibly, while distinguishing them from new regressions.

## Additional findings

### R12 — Institution identity formats and aliases are under-specified

The alias table mixes bare IDs and full URLs; lookup is exact-string based. Four bare alias sources can miss URL-form cached IDs. Alias graphs have no baseline cycle/chain validation in the application, and canonicalization happens after the multi-affiliation divisor is chosen. A fixture with two aliases of one university plus a second university credits 2/3 to the first and 1/3 to the second, rather than splitting between two unique institutions. Same name and country are not sufficient evidence for generic “Government Medical College” merges. Define and validate canonical identifiers, resolve the graph, deduplicate canonical affiliations, then calculate credit.

### R13 — Country fallback guesses make geographic rankings wrong

`build_institutions.py` uses substring rules such as `university of south`, `georgia`, `polytechnique`, and `eth`. Executed fixtures classify University of South Africa as US, University of Nottingham Malaysia as GB, and Bethlehem University as CH. These are fallback behavior demonstrations; they do not mean all those names are misclassified in the published file when an authoritative country exists. The institution audit identified actual wrong-country and blank-country rows. Prefer canonical institution metadata, then exact reviewed overrides; leave unresolved geography explicit instead of guessing from city/name fragments.

### R14 — The public data has no release identity or coverage contract

There is no manifest tying the registry, corrections, cached inputs, generated tables and site assets to one build. No reliable per-venue-year freshness, accepted count, source status, partial-year state, or hash is available to a visitor. Add a manifest with the code revision, policy/schema versions, input hashes, generated timestamp, artifact hashes, refreshed and carried-forward scopes, coverage gaps, and validation results. Avoid a single “fresh as of today” claim when parts of the corpus were retained from older observations.

### R15 — Public file generation can leave mixed releases

Aggregate CSVs and split JSON files are overwritten sequentially. `split.py` copies the registry before checking its inputs, reports missing inputs without failing the build, and does not remove stale venue files. Institution metadata can be built from a different aggregate generation. Build into a clean staging directory; verify all expected files and cross-file sums; only then publish an immutable artifact directory.

### R16 — Baseline frontend suppresses missing area files

`site/main.js:fetchAreaData` catches every failure and returns `[]`; ranking still uses the selected area's denominator while silently giving every institution zero in that area. Request state is read from mutable selection after `await`, with no generation token. Concurrent updates can publish an incompletely loaded newer selection. Required-data failure must stop ranking and identify the failed area; pending fetches should be shared and outdated render runs suppressed. The Opus redesign implements these repairs and moves the math into a pure module.

### R17 — Baseline frontend layout and accessibility are broken

The active `index.html` uses `.app-layout`, `.sidebar`, `.pill-btn`, and `.clean-table`, while most CSS styles a different component tree. Browser measurements at 1280×800 show the sidebar at full 1280-pixel width with block display, ranking content beginning below 782 pixels, unlabelled year/region controls and no pressed state on area pills. The Methodology link points to `#`; the GitHub link names the wrong owner; “Export” only invokes print; the table silently stops at 150 of 5,458 institutions. The typography imports Inter but requests Outfit in CSS. These are functional mismatches, beyond subjective taste. The academic redesign replaces the inconsistent tree, provides native controls, real CSV export, pagination, methodology, stable URL filters and responsive layout.

### R18 — Documentation is not an authoritative description of behavior

README says the public frontend does not exist. CLAUDE refers to line numbers in an older inline page, says all cached years are selected without a year filter, and says NeurIPS/ICLR have no works, despite the current corpus. PLAN has 21 proposed areas vs 20 actual, old counts, contrary general-journal placement, parent-rollup promises the aggregator does not implement, and “no API key needed” guidance. `data/institutions.json` is described as ignored but is tracked; a 14 MB `.bak` file is also tracked. `data/reports/` is ignored, even though skills require durable reports there. Correct the overview and separate normative policy, current implementation, historical decisions and future experiments. Keep dated discoveries in evidence reports rather than continually appending them to instructions.

### R19 — Agent skills encode a fragile orchestration mechanism

There is no repository `AGENTS.md` at baseline. CLAUDE is approximately 11 KB and the skills add extensive repeated model-specific directions. They hardcode Sonnet/Haiku, provider-only tools and synchronous dispatch mechanics, contradict ten-year window examples, and require a second harvesting consent even when the user asked for a refresh. The adjudication skill promotes world-knowledge decisions without a mandatory evidence URL; automatic fixers mark heuristic repairs `manual`, conflating “persisted” with “reviewed”.

Keep the useful domain rules: exact venue identity, conference edition validation, no name-only merges, deliberate exclusion curation, one writer for shared curated files, budget accounting, and ambiguity recording. Replace provider choreography with task inputs/outputs, ownership, state transitions, and acceptance criteria. Select models at dispatch from user preference and live capability. Routine authorized steps should continue without extra approval. Agents should investigate and propose evidence; deterministic validators should control acceptance. Concrete proposed instructions are in `AGENTS.proposed.md` and `refresh-workflow.proposed.md` beside this review.

### R20 — No reproducible toolchain or meaningful baseline test suite

The baseline has no package metadata, CI workflow, automated fixtures, schema validation, pinned semantic model revision, or dependency lock for Torch/sentence-transformers. A promise of “stdlib only” coexists with two semantic scripts and model downloads. Semantic index variants are built by iterating sets, so tied matches can depend on ordering. `--report-only` loads the model and builds its entire index, then returns before printing its promised coverage report. A documented `--workers` option is not implemented. Add a small supported Python version range and optional ML extra with exact model provenance; keep the default pipeline stdlib if desired. Pin deployment tooling. Test contracts and failure recovery, not incidental code structure.

### R21 — Historical methodology experiments are mixed into operational plans

`docs/csrankings2-plan.md` proposes citation, award, last-author and per-capita signals, including using authors as a faculty-count proxy. These require separate validity research and user decisions. Institution-level output is not an ECE faculty census; a recent OpenAlex affiliation is not proof of a current faculty appointment. Preserve the existing transparent 1/N/geometric-mean method during cleanup. If experiments remain, label them as a separate research document, not a roadmap silently changing this ranking.

### R22 — Diagnostics conflate missing data, legitimate exclusions and uncertainty

“No education institution” includes industry-only papers, provider omissions, wrong types, unresolved raw text and schema defects. Purity penalizes valid multi-level organizations while raw-resolution metrics condition on strings that exist, potentially making missing data look healthy. A median-institution-count threshold can mistake a small field for an under-collected one. Report the actual partitions and denominator: source coverage, byline completeness, unresolved author share, education credit, deliberately noneducation share, discarded records and conflicts. Retain source-specific thresholds and use paper samples as independent checks.

## Proposed target structure

This is a migration target, not a request to rewrite everything at once:

```text
AGENTS.md                         short repository contract and safe commands
README.md                         run/build/verify/deploy; current behavior
docs/methodology.md                normative counting/attribution policy
docs/decisions/                    dated scope and ownership decisions
docs/operations.md                 refresh, budgets, failure recovery, publication
data/registry/                     venues + typed edition membership rules
data/overrides/                    exact corrections with evidence and reviewer status
data/refresh/                      durable per-run observations and manifests
pipeline/
  cli.py                          plan / fetch / resolve / build / validate / publish
  providers/                      OpenAlex, Crossref, official proceedings adapters
  model.py                        schema + DOI/ID normalization
  resolve.py                      provider assertions + explicit override precedence
  aggregate.py                    pure counting logic over canonical records
  validate.py                     pure structured findings, exit policy
  release.py                      staged artifacts + manifest + promotion
site/                             static ES modules, HTML, CSS
tests/                            provider fixtures, credit invariants, build and UI checks
wrangler.jsonc                    narrow target hostname and static asset directory
```

For the corpus itself, compressed immutable provider JSONL plus a manifest is a reasonable near-term choice. SQLite using the standard library is a sensible next step for canonical works, provider assertions, venue membership and corrections if repeated scans become costly: unique constraints and transactions directly address duplicate and partial-write problems. It does not require a production SQL server. Do not migrate solely to introduce ORM abstractions. Serve only compact public aggregates and methodology/coverage metadata; raw caches, scripts, credentials and development files do not belong in the deployed site.

## Execution order and acceptance criteria

1. **Protect publication first.** Make validation pure, add explicit staging/output paths, reject LFS pointers before parsing, require full-scope publication, fail on critical findings, and give every build a manifest. Acceptance: an interrupted/scoped/bad refresh cannot change the live release or accepted baseline.
2. **Repair known counting defects.** Apply TECS ownership, stable work identity, canonical affiliation deduplication, exact year rules, preserved raw evidence and full bylines. Acceptance: fixtures conserve credit; all removals/reassignments have a reason; known duplicate and year-contamination cases have explicit outcomes.
3. **Refresh and reconcile.** Check all venue identities and date-specific source availability, fetch complete staged data under a shared budget, resolve high-impact affiliation conflicts, and compare absolute credit/coverage against the previous release. Acceptance: per-file completeness/hashes are recorded; failed scopes retain their prior validated data and are labelled retained; no provider completeness is invented.
4. **Ship the academic frontend.** Keep the site dependency-light, expose the formula and institutional scope, use accessible native inputs, remove decorative chrome, distinguish failure from zero output, and make filters linkable. Acceptance: independent score calculation matches; race/error fixtures, mobile layout, keyboard controls and CSV work.
5. **Consolidate the pipeline.** Extract shared HTTP/error/auth, identifiers, schema validation and provider adapters; retire one-off correction code into declarative override data. Acceptance: retry and resume semantics are exercised with deterministic fixtures; optional ML dependencies are isolated; main commands are documented and CI-enforced.
6. **Then automate recurrence.** A scheduled job creates a candidate release/report, rather than directly committing or publishing unreviewed data. Acceptance: one full dry-run reproduces an accepted release, refresh deltas explain the next, and promotion is explicit and auditable.

Estimated effort should be reassessed after the first complete refresh: core publication/counting repairs are days of focused engineering; the attribution and ML coverage work is an ongoing data-curation problem. A large framework rewrite would delay those highest-value improvements.

## What this session changes

The broad architectural migration remains a proposal. The user separately authorized a frontend redesign and publication at `ecerankings.eding.dev`, so the Opus frontend implementation is actual work, not merely a mockup. Luna's refresh scripts run against isolated destinations; the final refresh/release report records which outputs were accepted and which gaps remain. No commit or push is implied by a local build or a Cloudflare deployment.

The focused implementation now includes these safeguards:

- Scoped aggregation requires an isolated output directory, rejects symlink routes into public data, and rejects unmaterialized LFS inputs before opening outputs.
- Aggregation enforces TECS/EMSOFT DOI ownership, normalizes institution IDs, resolves alias chains with cycle detection, and divides credit between unique canonical institutions. DOI/OpenAlex/S2 identities prevent repeated source rows from inflating credit.
- Verification returns failure for critical/high findings and failed detector processes, checks actual per-venue contributions, and advances snapshots only with explicit `--update-snapshots` after clean checks. The campus fixer proposes changes unless invoked with `--apply`.
- The three bounded refresh commands stage provider observations separately. The release preparer accounts for retained source memberships, quarantined edition contamination, deduplication, paper-specific affiliation retention and withheld author-profile strings.
- The release builder checks cache hashes, stable curated inputs, unique aggregate keys, venue/area/author credit reconciliation and exact JSON/CSV agreement. Its manifest binds metadata, corrections, code and artifacts; the public coverage page distinguishes refreshed, retained and unsuccessful scopes.
- The site packager accepts a validated release and an explicit asset allowlist. Publication uses Cloudflare Pages Direct Upload through Wrangler, as requested; the earlier repository example uses Workers and was not copied as the hosting product.

These changes do not complete R07's unified override precedence, migrate source/enrichment records into a new canonical schema, retire the legacy harvest/backfill/normalization commands, create a faculty census, establish publisher-complete ML proceedings, or replace active CLAUDE/skill instructions. Those remain explicit proposals or data limitations. The new tests cover the repaired contracts and failure modes; they do not prove every bibliographic record or institution assignment correct.

Integration also exposed a recovery-run failure: two journal processes wrote to the same cache and checkpoint paths. The manifest hash check rejected the resulting partial output before publication. Both writers were stopped, their original files were quarantined, and only files passing independent hash/count/year/byline checks were retained. The journal command now holds exclusive OS locks on both its output cache and manifest, and checks actual staged row count against its committed pagination count before publishing a file. Regression fixtures exercise both concurrent-writer rejection and staged-row loss. Recovery outputs now reside in ignored checkout storage instead of the server's ephemeral `/tmp`.

Publisher reconciliation repaired seven conference source entries: ICCAD 2017/2022, ISIT 2016–2018, CDC 2025 and SIGCOMM 2026. A successful native query was not sufficient acceptance evidence: ICCAD 2017 returned 65 alternative-identifier records against 154 verified IEEE papers. Its exact publisher set was recovered instead. Five independently verified ISSCC/CLEO records supplement current list-index omissions; alternate CLEO DOI representations were not re-added. The conference inventory now has 226 accepted editions and one retained gap, VLSI Technology 2021. This demonstrates why baseline membership and absolute count checks must accompany API pagination checks.

The final current-year check also replaced stale July availability observations. Exact publisher queries added six 2026 editions (ISSCC, ISCA, ISIT, ICRA, CLEO and joint VLSI), bringing accepted conference queries to 232 of 233 registered scopes. Nine other current-year sources remain unverified and are exposed separately from query completion; ICCV's no-edition year, post-merger VLSI ownership and the user-recorded IMS hiatus are preserved. This distinction is part of R10/R18/R22: an unregistered source, a successful empty query and a verified no-edition year must not share a zero-publication interpretation.

The network-enabled parent completed all 457 journal scopes and independently audited 442,255 records, including 2,068 hydrated large bylines. Exact metadata was topped up to 14,750 institution records. The final release report and its bound manifest give the accepted counts, empirical default-ranking comparison, remaining limitations and actual publication status. Broader schema, override-precedence and legacy-instruction changes remain proposals.
