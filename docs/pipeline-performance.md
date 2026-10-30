# Parallel aggregation and reproducible releases

The release builder uses all available CPUs by default. Ordinary CPython runs
spawned worker processes; free-threaded CPython with its GIL disabled runs worker
threads. Both execute the same venue kernel and reduce results in sorted venue
order. Use Python 3.11 or newer; no additional Python packages are required.

```bash
python3 pipeline/build_release.py \
  --cache-dir /path/to/candidate-cache \
  --refresh-manifest /path/to/refresh-manifest.json \
  --out .tmp/new-release --workers 16
```

`--executor processes` selects spawned processes explicitly. A free-threaded
interpreter can use `--executor threads`, for example:

```bash
/path/to/free-threaded/python -X gil=0 pipeline/build_release.py \
  --cache-dir /path/to/candidate-cache \
  --refresh-manifest /path/to/refresh-manifest.json \
  --out .tmp/new-free-threaded-release --executor threads --workers 16
```

Thread execution requires `sys._is_gil_enabled()` to remain false after imports
and aggregation. A normal Python installation cannot disable its GIL with a
runtime flag alone. See [CPython's free-threading documentation](https://docs.python.org/3.14/howto/free-threading-python.html).
`--sequential --no-aggregation-cache` remains available for diagnosis.

## Cache and correctness boundaries

Raw JSONL remains the source of truth. The separate aggregate cache defaults to
`.tmp/aggregation-cache`; choose another location with `--aggregation-cache-dir`
or recompute everything with `--no-aggregation-cache`.

Each cache entry contains one complete venue across its selected years. Editing,
adding, or removing an edition invalidates that venue. This intentionally
reprocesses unchanged years to preserve first-occurrence deduplication across
years. Publication year remains independent of the source directory year.

Cache fingerprints cover raw SHA-256 hashes, curated registry/mapping/alias/
exclusion inputs, effective resolver settings, aggregation code, schema, year
filter, and interpreter version. Metadata-only edits regenerate release metadata
without invalidating credit calculation. JSON shards preserve unrounded floats,
paper counts, missing author IDs, names, audit metrics, and lineage evidence.
Malformed entries or mismatched hashes are recomputed. Atomic file replacement
and a digest-bearing completion record protect against interrupted writes.

When every input is unchanged, a second content-addressed cache can restore the
complete CSV export. Its completion record covers all three CSV hashes, the full
ordered venue fingerprint, and audit metrics. Every restored file is hashed
before and after copying. A changed edition misses this complete-export cache
and reuses only unaffected venue shards; a corrupt export is regenerated.
Release reconciliation still runs on every restored export.

Workers own their mutable state. Shared resolver tables are read-only. Reduction
preserves the sequential last-observation name rule and first-observation lineage
rule. Explicit identity tie breakers make CSV ordering independent of worker
count, completion order, hash seed, and cache hits. The author denominator still
includes every byline slot; only unique canonical education institutions divide
that author's share. Geometric-mean scoring and default-on areas are unchanged.

Every release verifies its complete declared raw inventory, including cache hits,
and rechecks raw/curated/code stability before finalizing its manifest. Generated
CSV/JSON artifacts are independently reconciled and hashed. Execution metadata
and elapsed times live in `aggregation-stats.log` and the manifest's `aggregation`
field, outside reproducible data artifacts. A failed Git status query marks the
tree conservatively dirty; actual code and input hashes remain mandatory.

## Verification and measurement

```bash
python3 -m unittest discover -s tests

python3 pipeline/compare_aggregates.py \
  --reference /path/to/sequential-reference \
  --candidate /path/to/candidate-release \
  --report .tmp/aggregate-comparison.json

python3 pipeline/verify.py --all \
  --cache-dir /path/to/candidate-cache --data-dir /path/to/candidate-release
```

The comparator checks every identity, institution/author name, integer count,
and credit cell. It also compares geometric-mean scores across default-on areas,
including zero-count areas, over the full corpus and three recent year windows.
The absolute numeric tolerance defaults to `1e-4`. The existing quality verifier
still reports source coverage and affiliation limitations independently of whether
the faster build matches its reference.

For timing, run aggregate commands against a frozen input tree and separate output
directories. Supply `--stats /path/to/run-stats.json` to capture runtime, workers,
cache hits/misses, and venue fingerprints. Measure cold and warm caches separately;
retain a forced-recomputation reference and compare artifacts before accepting a
speedup. Concurrent refreshes must use separate source trees.

## Initial measurements, 2026-10-29

On this 16-CPU machine, a frozen 974-edition, 69-venue corpus produced 158,313
institution-area rows, 290,502 institution-venue rows, and 2,714,571 author rows.
These are individual observations, not repeated-run medians; interpreter builds
and compilers also differ.

| Configuration | Cold aggregation | Unchanged-input aggregation |
|---|---:|---:|
| Original CPython 3.14.7, sequential | 48.8 s | Full recomputation |
| Optimized CPython 3.14.7, 16 processes | 32.4 s | 3.4 s |
| Free-threaded CPython 3.14.8, 16 threads | 35.2 s | 1.7 s |
| Free-threaded CPython 3.15.2, 16 threads | 35.8 s | 1.6 s |

All six optimized cold/warm exports had identical SHA-256 hashes. Comparison
against the original sequential implementation preserved every key, name, and
integer count. The largest credit difference was `0.00001` in one area cell;
default-area geometric-mean scores matched in all four tested windows. Free
threading passed correctness checks but did not beat processes on the cold run.
The initial 2× cold-aggregation target was not reached. Unchanged-input aggregation
exceeded the 5× target, and the complete cold release exceeded the 25% reduction
target. The remaining cold cost includes deterministic reduction, global sorting,
and full export generation.

The original 974-file inventory lacked five default-on venues and correctly failed
full release validation. Full candidate-release tests therefore use a separate
1,024-file snapshot containing those venues. Local logs, manifests, timings, and
comparison reports are under `.tmp/pipeline-optimization-2026-10-29/`; these are
benchmark artifacts, not a published dataset.

On the complete 1,024-file snapshot, the original release builder took 67.5 s,
the parallel cold build took 48.6 s, and the unchanged-input build took 23.0 s.
All passed structural release validation. The free-threaded 3.15 incremental
build reused 69 venue aggregates and computed only the five added venues; its
data-artifact hashes matched both standard-Python releases exactly. Comparison
against the original complete release covered 3,230,355 CSV rows and preserved
all identities, names, paper counts, and default-area ranking scores.

The independent phase-3 verifier still exits with findings on both the original
and optimized builds: 7 critical, 644 high, 1 medium, and 2 low. Its findings match
as a multiset; only tied diagnostic ordering differs. These source/ranking audit
findings remain open and are not cleared by a successful performance comparison.
