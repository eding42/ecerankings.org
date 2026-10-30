# ECERankings.org

A static ranking of Electrical & Computer Engineering programs, based on
publications in curated journals and conferences. The browser computes rankings
from precomputed institutional counts. See [PLAN.md](PLAN.md) for methodology
and [data/areas.json](data/areas.json) for the venue registry.

Each paper contributes one unit, divided equally among its authors and then
among an author's education institutions. Overall scores use the geometric mean
of `1 + adjusted_count` across selected areas, including zero-scoring areas.
Affiliations belong to the paper at publication time; current author profiles
never supply historical credit. Citations do not affect scores.

## View and test

Serve `site/` with any static web server, for example:

```sh
python3 -m http.server --directory site 8000
```

Python 3.11+ runs the pipeline and tests without installed packages. The semantic
normalizer is optional and uses the existing `.venv/`. Frontend tests require Node.js.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/frontend/*.test.mjs
```

## Data workflow

OpenAlex supplies works and paper-specific affiliations. Crossref supplies exact
conference-edition membership where OpenAlex's venue indexing is incomplete.
ML membership comes from publisher proceedings; Semantic Scholar only discovers
identifiers. ML remains off by default while coverage and PDF-verification gates
are incomplete.

1. Materialize required `cache/` files with Git LFS. A pointer is not a dataset.
2. Put `OPENALEX_API_KEY` in the ignored root `.env` file. Reuse cached responses
   and set request budgets when collecting data.
3. Harvest into a staged cache, resolve new affiliations, and review ambiguous
   mappings with `pipeline/adjudication.py`.
4. Build and verify an isolated candidate before replacing published data.

Use the [refresh runbook](docs/refresh-runbook.md) for commands, release gates,
and publication. Use the [ML guide](docs/ml-pipeline.md) for publisher collection
and PDF verification. Do not rebuild `site/data/` directly during scoped work.

## Files to maintain

| Path | Purpose |
|---|---|
| `data/areas.json` | Venue sources, edition scope, area defaults, verification status |
| `data/affiliation-map.csv` | Raw affiliation strings mapped to institutions |
| `data/institution-aliases.csv` | Reviewed duplicate institution IDs |
| `data/excluded-works.csv` | Curated non-research exclusions |
| `data/source-first-years.json` | Earliest source years used by the journal refresher |
| `cache/<venue>/<year>/works.jsonl` | Source works, tracked through Git LFS |
| `site/data/` | Generated ranking CSVs, per-area/per-venue JSON, and release manifest |
| `.agents/skills/` | Collection, adjudication, and verification procedures |

`data/institutions.json` is the local institution index; it is separate from the
frontend's `site/data/institutions.json`. Do not stage changes to the local index.
Run checkpoints and drafts live under ignored `.tmp/` and `ai_temp/`. Active
refresh manifests and institution metadata stay in `data/refresh/`; historical
run reports and recovery evidence remain available in Git history.

## Contributing

Changes to methodology, venue inclusion, or institution identity need supporting
evidence. Follow [AGENTS.md](AGENTS.md); commit, push, merge, and deployment are
separate approvals. Deterministic parallel builds and their cache behavior are
documented in [docs/pipeline-performance.md](docs/pipeline-performance.md).

The scoring approach is adapted from [CSRankings](https://csrankings.org).
Bibliographic sources are [OpenAlex](https://openalex.org),
[Crossref](https://www.crossref.org), and the relevant publisher proceedings.
