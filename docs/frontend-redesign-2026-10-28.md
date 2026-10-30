# Frontend redesign — 2026-10-28

## Design thesis

The site is a reference table, not a product page. It should read like an
academic resource in the CSRankings tradition: white page, system fonts, one
restrained link blue, a compact numeric table that starts in the first
viewport, and native controls whose state is visible at a glance. Everything
that is not the ranking itself — methodology, provenance, caveats — is plain
prose one click away, or a short notice placed next to the setting that
triggers it.

Explicitly avoided: gradients, glass, dark themes, oversized heroes, pills,
card grids, decorative icons, web fonts, generated imagery, ornamental motion.
The only glyphs are the ▸/▾ disclosure triangles on expandable rows, which
carry function.

## Layout

- Header: site name, nav (Rankings · Methodology · Source).
- H1 + one-paragraph lede stating what is ranked (institutions, at time of
  publication, 1/N split, not departments or faculty rosters).
- One filter bar: Region, From, To (native `<select>`s), "Find institution"
  search, Download CSV.
- Notices (only when relevant): partial year in range; default-off area
  selected (ML coverage caveat, Flagship scope).
- Two columns ≥900px: areas list (260px, left, like CSRankings) and the table.
  Below 900px the area list collapses into a `<details>` above the table and
  lays out in two CSS columns. Below 600px the Papers/Areas columns are hidden.
- Table columns: #, Institution (+ country code), Score, Adj. count, Papers,
  Areas-with-credit. Clicking a name expands a per-area breakdown (adjusted
  count and papers for every selected area, zeros shown muted) with a link to
  the OpenAlex record.
- First table row at y≈316 on 1280×800 (previously y≈782 because the old CSS
  class names did not match the HTML and the sidebar rendered full width).

## Behaviour

- **Math unchanged:** `score = exp(mean_i log1p(s_i)) − 1` over *all* selected
  areas, zeros included (`site/rank.js computeRankings`). Region filters after
  scoring. Areas default from `areas.json .areas[*].default_on` (18 of 20).
- **Deterministic order:** score desc, then name, then OpenAlex id.
  Competition ranking (1, 2, 2, 4) for scores equal within 1e-9 relative.
- **No silent cap:** first 100 rows, then "Show 100 more" / "Show all N".
  Search filters the rendered list without changing ranks.
- **Loading:** `loadArea` caches the in-flight promise per area (dedupes
  concurrent fetches); failures are removed from the cache so Retry refetches.
  Each update snapshots the selection and a run id; results from superseded
  runs are discarded. While loading, the old table is dimmed and `aria-busy`.
- **Failure:** if any selected area file fails (network, HTTP, bad JSON,
  non-array), the table is cleared, export disabled, and an alert lists the
  failed areas with a Retry button. A missing `areas.json` or
  `institutions.json` shows a fatal message and no table. There is no
  fallback/demo data.
- **Years:** options are derived from the loaded area files (union of their
  extents, so it grows when e.g. Devices' 1981 data is loaded). Default is the
  ten years ending at the latest complete calendar year (`currentYear − 1`,
  i.e. 2016–2025 today). Years after that are labelled "(partial)" and trigger
  a notice. If an optional `data/manifest.json` exists, `latest_complete_year`
  overrides the default and `generated_at` / `generated` / `built_at`
  (ISO date) is shown in the footer. Nothing claims the latest refresh is
  complete.
- **Regions:** World, United States, six UN-M49-style regions, and every
  country present in `institutions.json` (names via `Intl.DisplayNames`).
  Institutions with no country appear only under World.
- **URL state:** `#from=…&to=…&region=…&areas=a,b` via `history.replaceState`;
  defaults are omitted, unknown areas/regions ignored, reversed years swapped.
  `hashchange` re-applies a pasted link.
- **Export:** real CSV (all ranked rows for the current selection, not just
  the visible page) with per-area adjusted-count columns; filename encodes
  region, years, and area count.

## Files

| Path | Status |
|---|---|
| `site/index.html` | rewritten |
| `site/styles.css` | rewritten |
| `site/main.js` | rewritten (DOM, fetching, state) |
| `site/rank.js` | new — pure ranking/region/URL/CSV logic, no DOM |
| `site/methodology.html` | new — methodology and caveats |
| `site/methodology.js` | new — renders venue list from `data/areas.json` |
| `tests/frontend/rank.test.mjs` | new — Node tests for `rank.js` |

`site/index.old.html` was left untouched (it still contains the drifted
`getDemoAreas()` copy); it is no longer referenced and can be deleted.

## Validation

- `node --test tests/frontend/rank.test.mjs`: 10/10 pass. Covers zero-area
  geometric mean, inclusive year range, tie ranks/order, region filtering,
  missing-area throw, URL round-trip and garbage input, CSV quoting, year
  extent, and a cross-check of the full default selection on real data against
  an independent log-sum computation.
- Independent Python computation on `site/data` (default 18 areas,
  2016–2025): 5,316 institutions; top 5 Tsinghua 166.7487, SJTU 111.8362,
  Zhejiang 74.4369, Georgia Tech 66.8282, NTU 65.1450 — identical to the page.
  US filter: 882 institutions, Georgia Tech / UIUC / MIT top 3 — identical.
- Browser (own preview tab against the parent's server on :8765):
  - region change, row expand (`aria-expanded`), year from > to clamps,
    2026 partial notice, hash updates;
  - injected HTTP 503 for `ml.json` → error listing "Machine Learning
    (data/ml.json: HTTP 503)", zero table rows, export disabled; Retry after
    restoring fetch → 5,322 institutions over 19 areas with the ML caveat;
  - delayed `flagship.json` (1.5s) selected then deselected → stale run
    discarded, final table is the 18-area default;
  - Show more → 200 rows; search "california" → 38 matches;
  - CSV export → 5,317 lines (header + 5,316), per-area columns;
  - fixture server without `institutions.json` → fatal message, no table,
    controls disabled;
  - 390×844 (iPhone 12 Pro) and 1280×800 layouts.

## Open items for the parent

- `data/manifest.json` is optional; if the data refresh produces one, use the
  keys above (`latest_complete_year`, `generated_at`) or tell me the schema.
- The year selector reflects only *loaded* areas; selecting a deep-history
  area extends it. A manifest with a global extent would avoid that.
- `tests/frontend/` is outside `site/` so it is not deployed.
- Country codes come from `institutions.json`; 609 institutions have none.
