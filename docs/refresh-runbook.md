# Refresh and publish

Use Python 3.11+, Git LFS, a materialized source cache, and the OpenAlex key in
the ignored root `.env`. Methodology and venue decisions belong in `PLAN.md`
and `data/areas.json`; a refresh does not change them.

## Authorization

| Request | Authorized work |
|---|---|
| Refresh data / prepare a release | Collect, build, verify, report |
| Push the refresh | Commit to a review branch, push, open a PR |
| Merge / deploy | Merge the approved change or publish the accepted release |

Stage explicit paths and present the change before committing. Push requires
its own confirmation. Never infer production publication from a review-branch push.

## 1. Prepare and collect

```sh
git lfs install
git lfs pull --include='cache/**,site/data/author-info.csv'
python3 pipeline/verify.py --all
```

Save the verification output as the baseline. Do not harvest over LFS pointers.
Use staged collectors with explicit scope and request limits:

```sh
python3 pipeline/refresh_openalex.py --venue jssc --year-range 2025 2025 --dry-run
python3 pipeline/refresh_openalex.py --venue jssc --year-range 2025 2025 \
  --out-cache .tmp/refresh/journals/cache --manifest .tmp/refresh/journals.json \
  --max-list-requests 100 --refresh
python3 pipeline/refresh_conferences.py --venue iedm --years 2024 2025 \
  --output .tmp/refresh/conferences/cache --report .tmp/refresh/conferences.json
```

The journal tool clips years to `data/source-first-years.json`. Conference
membership must match the registered edition source and DOI scope. Reuse
completed outputs only when their recorded hashes match. Failed requests stay
unresolved, not empty observations. For ML, follow [ml-pipeline.md](ml-pipeline.md).

Backfill or normalize only the intended cache tree. Use the stdlib normalizer
by default; the semantic normalizer is optional and should run separately.
Adjudicate new raw strings, replay prior decisions after normalization, and run
`pipeline/adjudication.py check`. Do not accept author-profile affiliations.

## 2. Build an isolated candidate

`prepare_refresh.py` can combine complete collector outputs with an immutable
baseline. Supply `--baseline`, `--out`, `--report`, and the matching
`--journal-cache`/`--journal-manifest`, `--conference-cache`/`--conference-manifest`,
and optional `--ml-cache`/`--ml-manifest` paths. It retains unresolved scope and
quarantine evidence. Its output becomes the candidate cache below.

```sh
python3 pipeline/refresh_manifest.py --cache-dir <candidate-cache> --out .tmp/refresh.json
python3 pipeline/build_release.py --cache-dir <candidate-cache> \
  --refresh-manifest .tmp/refresh.json --out .tmp/release
```

The builder checks source hashes, rejects writes into `site/data`, reconciles
credit across CSV/JSON artifacts, and records code/input/artifact hashes.
It includes `split.py`; direct aggregation must always be followed by splitting.

## 3. Verify before promotion

```sh
cp site/data/.coverage-snapshot.json site/data/.ranking-snapshot.json .tmp/release/
python3 pipeline/verify.py --all --cache-dir <candidate-cache> --data-dir .tmp/release
python3 pipeline/compare_aggregates.py --reference site/data --candidate .tmp/release \
  --report .tmp/release-diff.json
```

Review finding changes against the baseline and explain intended credit changes.
Stop for unexplained critical/high findings, regressions, dropped publisher
membership, duplicate keys, inconsistent artifact counts, or hash mismatches.
Also stop when coverage drops more than five points, a known-strong institution
reaches zero, or default-on top-20 membership changes by more than 10% without
a documented cause. Missing source metadata is not evidence of zero papers.

Do not edit `known-strong.json`, methodology, area defaults, or gate thresholds
to clear a failure. Never advance snapshots to hide findings. Accept snapshots
with `--update-snapshots` only after the candidate has been reviewed and the
verifier reports no critical/high findings.

## 4. Promote, commit, and publish

After validation passes:

```sh
python3 pipeline/promote_release.py --cache-dir <candidate-cache> --release .tmp/release --check-only
python3 pipeline/promote_release.py --cache-dir <candidate-cache> --release .tmp/release
```

Promotion checks all source/input/artifact hashes again and writes the release
manifest last. Copy accepted coverage/ranking snapshots from the candidate to
`site/data` separately; they are not promotion artifacts. Keep the previous
release until verification and publication finish.

With commit approval, create a review branch and stage only reviewed paths:

```sh
git switch -c data/refresh-YYYY-MM-DD
git add data/areas.json data/affiliation-map.csv data/excluded-works.csv \
  data/institution-aliases.csv data/institution-metadata-overrides.json cache site/data
```

Never use `git add -A`. Exclude `.env`, `.tmp/`, `ai_temp/`, local settings,
`data/institutions.json`, and generated dependency/build directories. State the
scope, unresolved editions, coverage/credit deltas, and validation results in
the PR. Commit, push, and merge only at their authorized levels.

For an approved Cloudflare publication, package the accepted public files:

```sh
python3 pipeline/package_site.py --out dist
npx wrangler pages deploy dist --project-name ecerankings --branch main
```

The packager requires the release manifest and matching public-asset hashes;
it excludes CSVs, raw cache data, and LFS pointers, and enforces the 25 MiB asset
limit. Code-only publications still need a valid existing dataset. A Git-connected
Pages project may deploy on a `main` push; confirm that configuration before pushing.
Rollback with the previous Pages deployment or a reviewed Git revert. Do not
publish a partially promoted tree or rewrite provenance hashes to make it pass.
