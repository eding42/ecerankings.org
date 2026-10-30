# Secondary Semantic Scholar discovery

`pipeline/s2_discovery.py` provides a standard-library client and audit helpers.
It does not write ranking works or choose conference membership. Canonical
records must come from publisher proceedings; their titles and ordered author
names are inputs, not values to replace from S2.

```python
from pipeline.s2_discovery import Client, discover, reconcile

client = Client()  # .tmp/s2_cache; S2_API_KEY from environment, then .env
canonical = {"title": "Canonical title", "authors": ["Full Author Name"], "year": 2025}
result = discover(canonical, client.search(canonical["title"]))
# result['openalex_lookups'] on a unique match supplies DOI lookup hints.
# Require OpenAlex DOI/title/byline/year identity before accepting authorships.

papers = client.batch(["DOI:10.1234/example", "CorpusId:12345"])
metrics = client.batch(["CorpusId:12345"], metrics=True)
report = reconcile([canonical], [p for p in papers if p])
```

`discover` also accepts local Graph-shaped candidates. It requires the complete
ordered byline and exact normalized title, permits a one-year publication offset,
and reports ambiguity instead of choosing between versions. Conservative matching
can leave punctuation/name variants unresolved; review these rather than reducing
identity checks. CorpusId and ACL identifiers are retained for audit; DOI and
arXiv identifiers produce OpenAlex lookup hints. Batch resolves known identifiers,
not free-text titles. Missing batch entries retain their positions as nulls.

A client shares a capacity-one limiter across its callers, with at least 1.1 seconds
between attempts even with a key. Separate processes need external coordination.
429, 5xx and transport failures receive bounded exponential backoff plus jitter;
Retry-After seconds or dates can extend the delay. Exhausted requests raise
`S2Error`, never a negative lookup. Successful raw JSON is atomically cached by
method, URL and request body; keys are excluded from cache identity. Offline cache
misses raise errors. Raw cache files may contain unexpected upstream fields;
public search, batch and discovery results allowlist bibliographic fields and
exclude all profile affiliations. Metrics are opt-in informational metadata only;
no ranking or frontend formula is changed. Metrics use the same persistent cache;
remove their cached responses when a fresh snapshot is needed.

`harvest_ml.Fetcher.get_json` routes Graph API requests through this client under
its own `<stage-root>/raw/s2` directory, preserving offline and resumable behavior.
Legacy cache entries from its older HTTP implementation are not migrated.
`harvest_s2.py` now stages local venue-tag candidates under
`.tmp/s2-discovery/<venue>/<year>/candidates.jsonl`; it cannot overwrite production
ranking caches. Its profile strings are explicitly audit-only, with empty
`raw_affiliations` and `institutions`. Existing published/staged caches are not
rewritten by this change.

Rate choices follow the [S2 API tutorial](https://www.semanticscholar.org/product/api/tutorial):
introductory API keys receive one request per second, batching is preferred, and
keyless callers share a throttled pool. No successful access is guaranteed by
local pacing.

Run verification with:

```sh
python -m unittest tests.test_s2_discovery tests.test_harvest_ml tests.test_refresh_ml
```
