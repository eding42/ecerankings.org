# Qualify a verification run before scaling

Use this when changing venue/layout, model, execution mechanism, or rendering
settings. Reuse an applicable completed qualification instead of repeating it
for every batch. User-authorized model, scope, and concurrency choices persist.

## Evidence from the October 2026 pilot

- App-managed Luna delegates repeatedly ended 15-paper assignments with work
  remaining despite continuation prompts. One native Luna test saved all 15
  papers / 109 author slots. Ten one-paper app-managed assignments all completed.
  This supports those tested assignment choices, not a universal T3 diagnosis.
- Completion did not imply accuracy: the native batch misassigned two control
  authors; five visually checked one-paper outputs matched 45 of 46 author
  answers. William T. Freeman's superscript pointed to MIT, not Stanford.
- In independent native reads of the same cropped region of Differential
  Transformer with the same symbol-first prompt, 110 DPI matched 6 of 7 authors
  and 300 DPI matched 7 of 7. One read per condition on one paper does not
  establish general accuracy. The pending queue included bylines up to 82 authors.

## Bounded pilot

1. Save the exact assignment, input hash, model/provider, execution mechanism,
   source PDF/image provenance, resolution, and output paths in ignored
   `ai_temp/pdf-affiliation-verification/<run>/`. Keep attempts separate.
2. Select papers deterministically across author-count bands: 1–5, 6–10, 11–20,
   and 21+. A useful pilot is five papers per available band, including the
   largest byline. Record selection and any undersupplied band. Cover shared,
   column, keyed/multiple-affiliation, and pre-name-mark layouts too.
3. Render from source PDFs at 300 DPI. If the image viewer reduces a large image
   or small marks remain unclear, use overlapping close-ups at readable scale
   with the legend included or paired. Preserve author identity across overlaps.
   New rendering settings must change image/batch identity; never treat an
   enlarged low-resolution PNG as recovered detail.
   Inspect full-page context and render continuation pages when the author
   crop omits footnotes or a contributor section. For dense lists, save groups
   of at most ten indexed, name-anchored mark reads before assembling the task
   order. For columns, preserve the literal lines within each named block;
   shared lines in neighboring blocks do not imply identical affiliations.
4. Use the user-selected model and the session-appropriate execution mechanism.
   Give each worker its immutable list and its own output directory. Begin with
   a scope already shown to complete on that mechanism. If continuation fails,
   preserve artifacts and reduce the assignment unit rather than escalating
   prompt wording indefinitely. An execution comparison must hold task/model
   conditions as constant as possible and state remaining differences.
5. Inspect all pilot images yourself, including every author on dense papers.
   Check transcribed marks, institution legend, mapped affiliations, and parser
   verdicts separately. Do not give expected control answers to the judge. Keep
   proposed corrections in the parent review; never silently rewrite judge
   answers or count their repaired versions as the original model's accuracy.

## Report the right denominators

- **Scope completion:** valid saved papers / assigned papers and saved author
  slots / assigned slots, with exact names/indexes/order preserved. An `unclear`
  answer can be structurally complete while providing no resolved affiliation.
- **Judge accuracy:** parent-confirmed correct author answers / all checked
  author slots. Report unresolved slots separately; do not count them as correct.
- **Paper-balanced accuracy:** average each checked paper's author accuracy,
  giving every paper equal weight. Also report papers with every author correct.
- **Density/layout results:** report checked counts, errors, and unresolved slots
  within each author-count band and layout. A stratified pilot oversamples dense
  papers; its pooled score is not a population estimate without selection weights.
- **Formal pipeline gate:** the 98% `pdf_verification` threshold measures the
  extractor against accepted image verdicts on its designated high-confidence
  sample. It is separate from model qualification and pilot accuracy. Preserve
  that sample and its denominator; do not replace it with a curated control set.

Do not scale on one favorable small control or silently excuse an extra/missing
institution as punctuation. Hold affected drafts for a fresh, independently
checked read when symbol errors recur. State what passed (completion, pilot
image audit, or formal gates) and what remains unvalidated before applying data.
