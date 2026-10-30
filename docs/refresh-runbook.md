# Data refresh and publish runbook

End-to-end procedure for turning new harvests into published rankings. It is
written for a human or an agent: follow it in order, and stop at the gates
instead of improvising around them.

For code-only changes, see [Deploying code changes](#deploying-code-changes).
For the pipeline architecture and methodology, see `AGENTS.md` and `PLAN.md`.

## Where to run

Run from a checkout that has `.env` (the OpenAlex key) and a materialized LFS
cache. On the current machine that is the main checkout (`~/ecerankings.org`),
not a fresh worktree. A fresh worktree usually has LFS pointers and no `.env`;
if you must use one, run `git lfs pull --include="cache/**"` and provide
`OPENALEX_API_KEY` through the environment.

```bash
git lfs version                 # must be installed
test -f .env && echo "env present"
python3 --version               # 3.11+
git status --short              # understand every line before staging anything
```

## Authorization levels

`AGENTS.md` says never commit or push without explicit confirmation. That still
applies. Treat these as separate approvals:

| User says | Agent may |
|---|---|
| "refresh the data" / "prepare a release" | harvest, build a candidate, verify, report; no commit, no push |
| "push the refresh" | commit to `data/refresh-YYYY-MM`, push that branch, open a PR; no merge to `main` |
| "merge it" / "deploy it" | merge the PR (or push `main`) and watch the Cloudflare deployment |

If the user says "push the new everything," ask which of the three they mean.
Do not infer.

## Preflight

1. `git lfs install`
2. `git lfs pull --include="cache/**"` — otherwise `works.jsonl` files are
   130-byte pointers.
3. If `author-info.csv` will be compared:
   `git lfs pull --include="site/data/author-info.csv"` (274 MB).
4. Run `python3 pipeline/verify.py --all` on the current live data and save the
   output as the baseline.
5. Confirm `.env` contains `OPENALEX_API_KEY`. Never print or commit it.

## Path A — validated release (preferred)

Builds in `.tmp/`, validates hashes, and promotes atomically. Use this for any
refresh that will be published.

### A1. Harvest, backfill, normalize

```bash
python3 pipeline/harvest.py --venue <key> --year <year>
# or, for a conference year OpenAlex lacks:
python3 pipeline/harvest_crossref.py --venue <key> --year <year>
python3 pipeline/backfill_openalex.py --pilot 500
python3 pipeline/backfill_openalex.py --apply
```

Normalization is optional and non-deterministic. Prefer the stdlib fallback, or
run the semantic normalizer outside the agent session:

```bash
python3 pipeline/normalize_affiliations_local.py --all-cached
# .venv/bin/python pipeline/normalize_semantic.py --all-cached  # local only
```

### A2. Build the candidate

```bash
python3 pipeline/refresh_manifest.py --cache-dir cache --out .tmp/refresh.json
python3 pipeline/build_release.py \
  --cache-dir cache \
  --refresh-manifest .tmp/refresh.json \
  --out .tmp/release
```

`build_release.py` refuses to write into `site/data`, refuses a cache that does
not match the manifest, and records code/input/artifact hashes in
`.tmp/release/manifest.json`.

### A3. Verify the candidate against the live baseline

```bash
cp site/data/.coverage-snapshot.json site/data/.ranking-snapshot.json .tmp/release/
python3 pipeline/verify.py --all --data-dir .tmp/release --report --update-snapshots
python3 pipeline/compare_aggregates.py \
  --reference site/data --candidate .tmp/release \
  --report .tmp/release-diff.json
```

`verify.py --data-dir` audits the candidate, using the copied snapshots as the
regression baseline. `--update-snapshots` accepts the candidate baseline for
the next run, but only when no critical/high flags were raised. The snapshots
it writes stay in `.tmp/release`; copy them to `site/data` after promotion
(step A4). `compare_aggregates.py` exits non-zero on any identity/name/count
mismatch or credit difference above `1e-4`; read the JSON report, not just the
exit code.

### A4. Promote, only if A3 passes

```bash
python3 pipeline/promote_release.py --cache-dir cache --release .tmp/release --check-only
python3 pipeline/promote_release.py --cache-dir cache --release .tmp/release
```

`--check-only` re-verifies every artifact hash, cache hash, and curated input
hash. The real promotion writes `site/data/manifest.json` last, so an
interrupted promotion is detectable. It does not commit or deploy.

The verify snapshots are not part of the release manifest. After promotion,
copy the accepted baseline forward:

```bash
cp .tmp/release/.coverage-snapshot.json .tmp/release/.ranking-snapshot.json site/data/
```

### A5. Commit on a branch

```bash
git switch -c data/refresh-$(date +%Y-%m-%d)
git add data/areas.json data/affiliation-map.csv data/excluded-works.csv \
        data/institution-aliases.csv data/institution-metadata-overrides.json \
        cache site/data
git status --short
git commit -m "data: refresh <scope> (<YYYY-MM>)"
```

Do not use `git add -A`. Do not stage `.env`, `.tmp/`, `data/institutions.json`,
`data/reports/`, or unrelated local edits. If `git status` shows files you did
not expect, stop and report.

### A6. Push and open a PR

```bash
# Write .tmp/release-summary.md from the report template below first.
git push -u origin data/refresh-$(date +%Y-%m-%d)
gh pr create --title "data: refresh <scope> (<YYYY-MM>)" \
  --body-file .tmp/release-summary.md
```

Attach the manifest path, verify report, compare report, top-20 movers, and
coverage deltas. Do not merge or push `main` without a separate confirmation.

## Path B — direct rebuild (fallback)

Use only if the release tooling is unavailable. It overwrites `site/data` in
place and has no hash gate.

```bash
python3 pipeline/harvest.py --venue <key> --year <year>
python3 pipeline/backfill_openalex.py --apply
python3 pipeline/aggregate.py --all-cached
python3 pipeline/split.py
python3 pipeline/build_institutions.py
python3 pipeline/verify.py --all --report --update-snapshots
```

Then commit the same explicit paths and push. `split.py` is required even for a
registry-only change because it copies `data/areas.json` to
`site/data/areas.json`. `--update-snapshots` advances the regression baseline,
but only when the run has no critical/high flags.

## Stop conditions

Stop and report; do not promote or push if any of these is true:

- `verify.py` reports a `high` severity finding or any regression.
- Coverage drops more than 5 percentage points for any venue-year, or a
  `known-strong` institution goes to zero.
- Top-20 membership changes by more than 10% in a default-on area without a
  clear cause.
- `build_release.py` validation fails, an artifact hash differs, or a cache
  file is missing/extra.
- `compare_aggregates.py` reports a column change, duplicate key, or credit
  difference above tolerance.
- The change requires editing methodology, area defaults, or venue-inclusion
  policy (needs explicit approval).
- The OpenAlex key is missing or the budget is exhausted.
- `git status` shows unrelated changes that would be swept into the commit.

## Deploying code changes

Code changes use the same git path but do not need the data gates:

```bash
git add site/ pipeline/ data/areas.json
git commit -m "site: ..."
git push origin main
```

If the Cloudflare Pages project is Git-connected to `main` with output
directory `site`, the push is the deploy. Confirm in **Workers & Pages →
project → Settings → Build** that the production branch is `main` and the
output directory is `site`. If the project uses direct upload instead, run
`npx wrangler pages deploy site --project-name <project> --branch main`.

## Cloudflare notes

- There is no `wrangler.toml` or `_headers` in the repo; project settings live
  in the dashboard. Confirm the production branch and output directory before
  relying on push-to-deploy.
- After a data deploy, purge the Cloudflare cache or bump the data version;
  `main.js` does not append a cache-busting query yet.
- `site/data/author-info.csv` is 274 MB in LFS and exceeds the Pages 25 MB/file
  limit. It is not fetched by the frontend. Keep it out of the deployed
  artifact.
- `index.old.html` is publicly reachable at `/index.old.html`.

## Report template

```text
Scope: <venue(s)> <year(s)>
Cache: <n> files, <n> new/changed
Works: <n> added, <n> removed, <n> re-backfilled
Coverage: <before>% -> <after>% (worst venue-year)
Regressions: <none | list>
Top movers: <area>: <institution> <delta>
Artifacts: .tmp/release/manifest.json (<sha256>)
Diff: .tmp/release-diff.json
Commands skipped: <none | reason>
Open questions: <none | list>
```

## Rollback

- Before merge: delete the branch; nothing is live.
- After merge: `git revert <merge-sha>` and push, or use the Cloudflare
  dashboard's deployment rollback. Reverting data also reverts the LFS
  pointers; the previous objects remain.
- If a promotion was interrupted: `site/data/manifest.json` is written last, so
  its absence (or a hash mismatch) means the tree is mixed. Re-run
  `promote_release.py --check-only`; do not deploy a mixed tree.

## Known traps

- LFS pointers look like tiny files and parse as empty/garbage.
  `refresh_manifest.py` refuses them; `aggregate.py` does not. Always
  `git lfs pull` first.
- `data/institutions.json` is 27 MB and tracked despite the README saying it is
  gitignored. Never `git add` it.
- `data/affiliation-map.csv.bak` is 14 MB and tracked. Leave it alone.
- `normalize_semantic.py` is non-deterministic and needs `.venv`; do not run it
  in an automated refresh.
- `aggregate.py` writes `author-info.csv` (274 MB); committing it goes through
  LFS. Budget the bandwidth.
- `compare_aggregates.py` compares `author-info.csv` too; if it is a pointer,
  pull it first.
- `site/data` is about 72 MB, but the site fetches about 14 MB. Do not add the
  CSVs to the Pages artifact.
