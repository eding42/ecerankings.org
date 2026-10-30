# Exact institution-name affiliation corrections — 2026-10-28

I reviewed the 398 proposed full-name mismatch corrections and four proposed
acronym-collision corrections in the existing reports. I changed only auto
rows where the target had verified live OpenAlex metadata, the raw affiliation
contained its exact full name or an exact company name plus an explicit
country, no explicit raw country contradicted the target record, and no second
institution made the single-map choice ambiguous. The target ID, name, type,
country, and lineage were copied together from the same metadata record.

Each changed row retains `status=auto`. Its `matched_via` value is
`exact-full-name-reviewed-2026-10-28`, and `candidate` records the verified
target name. Existing manual rows and the existing attribution method were
left intact.

## Results

- Applied 284 corrections, including 13 additional corrections after the
  unresolved targets were verified against the expanded live metadata.
- Retained seven current assignments because the raw text contains a full-name
  or standalone-acronym signal for the assigned institution.
- Left 111 proposals ambiguous: 101 compound affiliations with multiple
  named organizations, nine with multiple live IDs matching the same exact
  name and country, and one explicit raw-country conflict. All 16 former
  metadata gaps now have live records; three remain ambiguous because of
  compound affiliations or two indistinguishable Nikon IDs.
- The separate detector-flagged sets (944 name-mismatch ambiguities and three
  acronym ambiguities) remain unchanged.
- All 9,178 existing manual rows are field-for-field identical after CSV
  round-tripping. The map still has 116,940 data rows and the original CRLF
  record endings, including embedded newlines inside quoted affiliation text.

The applied set includes 20 corrections to Oak Ridge National Laboratory, 12
to Lawrence Berkeley National Laboratory, eight to Draper Laboratory, and
seven to Jet Propulsion Laboratory. One Jet Propulsion proposal was retained
because the raw string also spells out the currently assigned California
Institute of Technology.

The followup verified six institution IDs in one batch, searched seven exact
company names, and used two free Nikon singleton lookups. It applied 13 of the
16 newly verified cases: Airbus (France), Amazon (Germany), Aselsan (Turkey),
Microsoft Research (India), Mitsubishi Electric (Japan), Toyota Motor
Corporation (Japan), Volvo Cars (Sweden), the Bernstein Center in Tübingen,
Inter-University Centre for Astronomy and Astrophysics, Leitat, and three
Dodd-Walls Centre records. The live records' type, country, and lineage were
copied from the same target IDs; company rows remain company type.

The complete per-proposal record in
[`data/refresh/exact-affiliation-corrections-2026-10-28.json`](../data/refresh/exact-affiliation-corrections-2026-10-28.json)
contains each before/after map row, decision reason, raw-string evidence,
target metadata, source report, map hashes, and the rows/counts that were
preserved. Live target queries were kept within the 30-call allowance.

The manual-row immutability check above describes this automatic-only pass.
The parent's later integration audit separately corrected 35 exact institution
identifiers that returned 404, moved two ambiguous manual rows to review, and
cleared one contradictory Moscow/QuantaSpec binding. Those changes have their
own before/after evidence in `invalid-manual-identifiers-corrections-2026-10-28.json`
and `late-institution-correction-2026-10-28.json`; they are not part of the 284
automatic corrections reported here.
The followup used eight of its 20 allowed list calls and two singleton lookups.
