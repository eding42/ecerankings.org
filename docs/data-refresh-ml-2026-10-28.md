# ML proceedings affiliation recovery — 2026-10-28

This bounded recovery uses the committed Semantic Scholar cache for ICML, ICLR,
and NeurIPS as its work list, then checks each distinct DOI against OpenAlex.
It does not verify that these venue/year sets equal the complete publisher
proceedings archives. No DOI means the work remains unresolved. ML stays off by
default.

## Attribution and identity rules

An OpenAlex work is eligible only when its normalized DOI exactly matches the
cached DOI and its normalized title is exact or has `SequenceMatcher` similarity
of at least `0.88`. A source row is backfilled only when its publication year
also matches OpenAlex. Rows that fail DOI, title, or year identity remain on
their original work record without historical affiliations. Duplicate
OpenAlex records for a DOI are ranked by byline and affiliation richness, title
score, then stable work ID; differing titles, bylines, or years are recorded as
conflicts.

OpenAlex paper-level authorships provide historical affiliation evidence.
Author lists marked truncated, short relative to their advertised count, or at
least 100 authors are hydrated through the singleton work endpoint and checked
for matching work ID and DOI. The final staged cache is also checked for
complete bylines, matching DOI and title, unchanged publication year, source
row counts, and input/output SHA-256 values.

Semantic Scholar author-profile affiliations are never credited as publication
affiliations. When source and OpenAlex bylines align exactly, profile strings
remain on the matching author under `profile_affiliations`. When they do not,
the source names, IDs, and strings remain in
`semanticscholar_profile_authorships` at work level. Both forms are explicitly
scoped as current author-profile evidence. The audit confirms that every source
profile string is retained and that none enters historical `raw_affiliations`
or `institutions` fields from the Semantic Scholar evidence.

## Reproducibility and handoff

Restore the 95 original ML files from their committed Git LFS pointers into
`.tmp/refresh-2026-10-28/ml-baseline/cache`. Each file was checked against the
pointer's SHA-256 and byte size; all 95 source hashes also match the preserved
prior manifest. Run the recovery with:

```sh
python pipeline/refresh_ml.py \
  --baseline .tmp/refresh-2026-10-28/ml-baseline/cache \
  --output .tmp/refresh-2026-10-28/ml/cache \
  --manifest data/refresh/ml-works-2026-10-28.json \
  --max-list-calls 350
```

The key is read from `.env` and sent only in the Bearer authorization header.
The run made 264 DOI batches and 305 OpenAlex list attempts, counted retries
within that attempt total, used zero retries and zero singleton calls, and left
45 list attempts unused. API request failures are not treated as negative DOI
lookups. Partial staging is retained if a run stops before all batches finish.

`data/refresh/ml-works-2026-10-28.json` is the integration manifest for
`pipeline/prepare_refresh.py`. It contains the per-file input/output hashes,
checks, match counts, remaining gaps, and API execution totals. Durable restore,
preservation, and independent verification helpers and logs are under
`.tmp/refresh-2026-10-28/`.

## Verified outcome

The restored source contains 58,145 works across 95 files and 26,355 distinct
DOIs. It has 31,788 works without a DOI and 25,301 Semantic Scholar profile
affiliation strings. OpenAlex returned 16,828 DOI candidates with an exact DOI
and strong title match. After publication-year checks, 15,868 work records for
15,866 distinct DOIs were backfilled with 78,994 full byline author records.
There were 9,315 DOI lookups with no OpenAlex record, 212 title identity
rejections, and 962 source rows rejected for publication-year mismatch. Thus
10,489 DOI-bearing works remain without accepted paper-specific OpenAlex
affiliations; the 31,788 no-DOI works remain unresolved as well.

All 25,301 profile affiliation strings remain separate from historical credit.
For 1,318 aligned byline authors, profile evidence is attached to the matching
author; 4,889 profile-bearing author records whose bylines could not be aligned
are kept in the separate work-level snapshot. No singleton hydration was
needed. The independent verifier checked all 95 input/output checksums, row
counts, DOI/title/year identity, profile-string preservation, and byline
completeness. The manifest and audit describe Semantic Scholar venue/year
membership as unverified for publisher completeness; they do not recalculate
whole-institution totals.
