# OpenAlex journal works refresh (2026-10-28)

**Recovery in progress:** the single-writer Luna handoff below was unable to
reach OpenAlex from its restricted network context. A parent-owned collector
resumed with network access at 23:09 UTC on October 28. Its completed scopes
have passed the collector's pagination, identity, year and checksum gates;
all default-on scopes are collected. Final independent totals will replace
this status after the optional journals finish. The earlier attempt-based
credit estimate below is historical, not a live balance.

`pipeline/refresh_openalex.py` refreshes every registered journal venue in
`data/areas.json` for 2016 through 2026. It clips a journal's starting year to
the earliest `first_publication_year` in the checked source audit, so years
before the journal existed are not queried. The 2026 collection is year to
date. OpenAlex indexing and source counts do not establish publisher-level
completeness.

The refresh output is staged separately at
`.tmp/refresh-2026-10-28/journals/cache/<venue>/<year>/works.jsonl`. The repository's
existing cache is not modified. Each year file contains normalized OpenAlex
work fields, normalized authorships with OpenAlex institutions and the source
`raw_affiliation_strings`, source attribution, and query/check time provenance.
TECS `exclude_dois` are applied. Paratext is excluded, matching the established
harvest filter; other work types remain eligible.

The CLI requires `--refresh` for network requests and accepts repeated
`--venue`, `--year-range START END`, `--out-cache`, `--manifest`,
`--max-requests`, and `--max-list-requests`. The overall attempt ceiling
includes singleton requests; the separate list ceiling limits `/works` calls.
API keys prefer `OPENALEX_API_KEY` in the environment, then `.env`, and are sent
in an Authorization header. A live one-page probe accepted `per-page=200`
(200 results returned). Current OpenAlex help documentation says 100 is the
supported maximum and describes 200 as deprecated, so the collector records
200 as the observed behavior and hydrates any 100-author list byline through
the singleton route. A year is atomically published only
after every page matches the API's reported count and the records are
deduplicated. List records with 100 or more authorships are hydrated through
the singleton works route, then checked against the original work ID and DOI.
Interrupted years retain a request-bound checkpoint and staged
pages for resume; completed files are checksummed in the manifest.

For years registered as Crossref sources, the matching OpenAlex source IDs are
still queried. If OpenAlex returns zero works, the year is marked
`skipped_crossref_preserved_openalex_zero` and no empty OpenAlex file is
published. This isolated cache does not replace or merge any existing
Crossref cache.

Run the mocked safeguards with:

```sh
python3 -m unittest tests/test_refresh_openalex.py -v
```

The execution record, per-year counts, query parameters, completion states,
checksums, and any errors are in
`data/refresh/journal-works-2026-10-28.json`.

For the 2026-10-28 restart recovery, the prior canonical manifest is preserved
as interrupted evidence under `data/refresh/interrupted-2026-10-28/`. It records
historical completion claims only; its missing output files are not current
coverage.

## Guarded recovery run result

One process was launched against the isolated cache and canonical journal
manifest with both exclusive locks enabled. It traversed the full 457-scope
plan in default-on-area order, followed by the off-default flagship journals.
The process exited with status 1 because 369 scope requests exhausted the
bounded retry policy with `OpenAlex network failure: URLError`. No unresolved
scope was labeled complete. The 88 validated recovery files were retained; no
new scope completed, and no historical error was repaired during this run.

The independent final audit is saved at
`.tmp/refresh-2026-10-28/journals/final-audit.json`. It verified all 88 accepted
files in `.tmp/refresh-2026-10-28/journals/cache/`: checksums, exact source ID,
year and query provenance, API and file counts, unique work IDs and DOI/ID
identities, source attribution, and authorship/raw affiliation structure. The
files contain 25,919 works, 119,218 authorships, and 140,794 raw affiliation
strings (62,438,553 bytes). No accepted byline has 100 or more entries, and the
audit found zero partial stages, checkpoints, or integrity issues. These are
OpenAlex-indexed records and do not establish publisher completeness.

There are 369 unresolved scopes: 149 with the pre-existing
`integrity_error` status and 220 with no prior scope record. Each has a failed
request recorded in `data/refresh/journal-works-2026-10-28.json`; the manifest's
`unresolved_scopes` and `unresolved_errors` arrays contain the complete list.
The other 88 scopes are accepted retained recovery outputs (74 directly
verified files and 14 reconciled alternate generations).

Usage counters are cumulative high-water totals in the manifest. Before this
run the list-call high-water was 711; afterward it was 2,187. The run therefore
made 1,476 new list attempts, 0 singleton attempts, and 1,107 retries. The
cumulative totals are 2,187 list attempts, 0 singleton attempts, and 1,107
retries. No calls were made beyond the 1,850-new-list-attempt ceiling. From the
reported starting balance of 2,034 free list credits, the conservative
attempt-based estimate is 558 free credits remaining, including the untouched
184-credit conference reserve and 374 credits still available under the
journal allowance. A live balance could not be rechecked after the network
failures.

Focused safeguards passed:

```text
python3 -m unittest tests/test_refresh_openalex.py -v
Ran 11 tests — OK
```
