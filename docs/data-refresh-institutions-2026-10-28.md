# Institution corrections — 2026-10-28

This pass applies exact-ID and location corrections to the curated affiliation map and adds country-only metadata overrides for records whose provider country is blank or conflicts with the current exact-ID record. Row-level before/after values, live record fields, and source URLs are in [`data/refresh/institution-corrections-2026-10-28.json`](../data/refresh/institution-corrections-2026-10-28.json). Reusable country overrides are in [`data/institution-metadata-overrides.json`](../data/institution-metadata-overrides.json).

## Applied changes

- Corrected **55 manual map rows** across ten exact institution-ID repairs: IIT Patna (16), IIT Mandi (12), IIT Tirupati (4), IIT Indore (6), IIT Palakkad (9), IIT Goa (2), NYU Tandon (2), NCTU/NYCU (2), ISTAustria (1), and Wrocław University of Science and Technology (1). Each replacement ID was returned by the live exact-ID OpenAlex batch with the expected institution name and country. The existing `manual` statuses remain unchanged; they record the prior map provenance and are not new human-review claims.
- For IIT Palakkad, the map retains `education` because the affiliation is the Indian Institute of Technology. Its current OpenAlex record and [ROR record](https://ror.org/0264cg909) both use the broad type `facility` (ROR also lists `Funder`); the [official IIT Palakkad site](https://iitpkd.ac.in/about-iit-palakkad) identifies the institution as a university. The map’s education ranking classification therefore remains explicit instead of inheriting a broad provider type that would exclude its credit. ROR is not cited as saying “education.”
- Downgraded **eight** clearly conflicting manual assignments to `review` with the institution association cleared: seven unrelated raw affiliations assigned to the U.S. Department of Health and Human Services ID, and the Huawei Future Network Theory Lab assigned to Tencent. No replacement IDs were guessed.
- Corrected **12** map country-code mismatches after checking the exact live target record and raw affiliation: ten Ministry of Education laboratory strings attached to six Chinese universities (`ME` → `CN`), one Mitsubishi Electric U.S. string (`GB` → `US`), and one University College London row (`AU` → `GB`). The exact target identities are University of Electronic Science and Technology of China, Chongqing University of Technology, Chongqing University, Beihang University, Nanjing University of Aeronautics and Astronautics, Peking University, Mitsubishi Electric (United States), and University College London.
- Removed the false ID association from the one `NYUAD,Div. of Eng,UAE` row and set it to `review`. Its current map ID is bare `I4210162871`; the exact live record is Saarbrücken Stadtwerke (Germany), type `company`, country `DE`, ROR `05h5kva18`. The UAE country proposal on that ID was rejected. The row is not reassigned to NYU or to the separate NYUAD funder ID.
- Added **seven exact metadata overrides** for country only: HKUST (Guangzhou) `CN`, Max Planck Institute for Multidisciplinary Sciences `DE`, SnT `LU`, Great Bay University `CN`, Eastern Institute of Technology, Ningbo `CN`, National Kaohsiung University of Science and Technology `TW`, and Cornell Tech `US`. Each override is keyed by the fully qualified institution ID, retains the existing name, and includes the live exact-ID fields plus official source evidence.

## Not applied / still unresolved

- **EPFL:** the proposed old ID `I83783590` was not returned by the exact-ID live batch. The map has two manual rows on that ID and the provider snapshot labels the ID EPFL in France, while the official EPFL address is in Switzerland. Because this may be a merged ID, no country-only override or replacement ID was added. Resolve the free singleton OpenAlex lookup/redirect first.
- **NYU Abu Dhabi:** the proposed country edit on `I4210162871` is wrong because that exact ID is a German utility. The map row is now under review, but the exact NYUAD institution ID remains unresolved. The OpenAlex funder record is not used as an institution ID.
- **Intel/HHS and Huawei:** the invalid manual assignments are cleared, but the seven varied raw affiliations formerly assigned to the HHS ID and the Huawei lab still need exact, per-row replacement records. They remain in review rather than being grouped by name.

The checked-in `site/data/institutions.json`, aggregate outputs, and publication artifacts were not changed. This pass corrects only the documented map rows and supplies metadata overrides; it does not establish that all institutional attribution is correct.

The integrator also refreshed stale `lineage` metadata on 18 of the repaired identity rows from the same live exact-ID records. This changes fields within the 76 corrected rows, not the number of row corrections.
# Later integration checks

The parent subsequently checked the 13 unresolved institution identifiers with
free exact-ID API lookups; all returned 404. Where the raw affiliation named a
specific institution and campus context, current OpenAlex/ROR records and
official institutional sources supported 35 identifier corrections across
UC San Diego, EPFL, TU Braunschweig, TU Chemnitz, Polytechnic University of Bari
and Sabancı University. Two ambiguous rows were cleared to review. One further
manual row incorrectly assigned Moscow Center for Advanced Studies to the ID
of QuantaSpec, a US company; that row was also cleared to review.

The evidence and per-row before/after values are in
`data/refresh/unresolved-institution-identifiers-2026-10-28.json`,
`data/refresh/invalid-manual-identifiers-corrections-2026-10-28.json` and
`data/refresh/late-institution-correction-2026-10-28.json`.
Together with the original 76 rows and the separate 284 automatic corrections,
the current map differs from the original in 398 distinct rows. All 116,940
data rows and original CSV record/embedded newline structure remain intact.
No institution alias merge or guessed country was introduced by these later
corrections.
