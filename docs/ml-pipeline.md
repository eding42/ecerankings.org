# Publisher-first ML collection

`pipeline/harvest_ml.py` stages ICLR, ICML, and NeurIPS works in the existing
`works.jsonl` envelope. It never writes the production cache or enables ML.
Publisher membership and bylines remain canonical; an enrichment record cannot
admit another paper or change the author-credit denominator.

## Sources and evidence

- ICLR: official proceedings, reconciled with authenticated OpenReview.
- ICML: the edition's PMLR volume, with main-track filtering.
- NeurIPS: the official proceedings book and configured track labels.
- Affiliations: identity-checked OpenAlex work authorships or the final publisher
  PDF. PDF evidence takes precedence; `--prefer-openalex` reverses that choice.
- Semantic Scholar supplies DOI/arXiv discovery hints only. Author-profile
  affiliations cannot earn historical credit.

Supported editions and included tracks live in `EDITIONS` in the script.
Unsupported years fail explicitly. Follow the source-specific membership
checks instead of treating a search-result count as a proceedings total.

## Collect and inspect

Python 3.11+ is sufficient. PDF stages also need `pdftotext` and `pdftoppm`.
Read API keys from the ignored root `.env`. OpenReview reconciliation needs an
`OPENREVIEW_TOKEN` or the account's `OPENREVIEW_USERNAME` and `OPENREVIEW_PASSWORD`.
Never copy credentials into reports or checkpoints.

```sh
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage all
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage gates
```

`all` runs membership, discovery, OpenAlex enrichment, PDF extraction, build,
and gates. Each stage checkpoints inputs and outputs. Failed lookups stay
retryable; an HTTP challenge never becomes an empty proceedings list.

- `--stage-root` selects isolated storage (default `.tmp/ml-harvest/`).
- `--max-list-calls` and `--max-search-calls` cap OpenAlex usage for the run.
- `--offline` reuses cached responses; it cannot finish missing enrichment.
- `--restart-stage` invalidates the selected stage and downstream checkpoints.
- `--stage reconcile-openreview` compares accepted notes with publisher membership.
- `--stage normalize` resolves this edition's strings in the shared affiliation
  map. It is explicit because it writes curated data; it is never part of `all`.

Builds go to `<stage-root>/cache/<venue>/<year>/works.jsonl`. Membership,
identifier discovery, OpenAlex evidence, PDF text, state, and review queues stay
under the same staging root. Extractor-version changes reparse saved text.
Partial extractions stay in review; they are not silently credited.

## Verify PDF evidence

```sh
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage verify-prep
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage verify-status
```

Use the [verification skill](../.agents/skills/verify-pdf-affiliations/SKILL.md)
with the user's selected model and scope. Workers read source images and save
one complete draft per paper. The parent checks batch identity, every author's
name/index/order, and image accuracy before accepting results. Draft completion
alone is not proof of affiliation accuracy. Preserve incomplete attempts and
unclear marks for review.

```sh
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage verify-apply
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage build
python3 pipeline/harvest_ml.py --venue iclr --year 2025 --stage gates
```

Resolve new strings through the adjudication workflow, replay earlier decisions
after normalization, and rerun map QA. Do not edit historical author credit from
knowledge of an author's current employer.

## Acceptance

An edition stays `staged` unless every gate passes: membership discrepancy at
most 1%, paper-specific affiliation coverage at least 90%, institution resolution
at least 95%, and extractor accuracy at least 98% on the designated image sample.
Byline integrity, track purity, and zero profile-affiliation leakage are also
required. Do not change thresholds or the sample to make a run pass.

Passing an edition's gates permits candidate preparation, not automatic
promotion. Follow the [release runbook](refresh-runbook.md) and preserve current
limitations in the [pilot checkpoint](ml-pilot-status-2026-10-29.md).
