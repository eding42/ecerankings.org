# CSRankings 2.0 — Multi-Signal Ranking Plan

A speculative extension of the CSRankings model that scores institutions on a
weighted rubric of signals, not just paper counts. Built on OpenAlex for the
same reason as ECERankings (data breadth, affiliation coverage), with curated
enrichment layers for signals OpenAlex doesn't have.

## Core philosophy

CSRankings is narrow and bulletproof: "did you publish at venue X, yes/no,
1/N per author." CSRankings 2.0 keeps the venue list as the entry gate (you
still need to publish at a top venue to be counted) but **modulates the score**
based on qualitative signals.

v1 ranks by total weighted score; area breadth weighting (geometric mean) comes
later as a toggle.

## Per-capita normalization

CSRankings' biggest blind spot: a school with 30 faculty naturally beats one
with 10, even if every single one of the 10 publishes at top venues. Per-capita
divides total score by estimated faculty count, revealing which departments are
research-dense vs. just large.

**What it would do to CSRankings (US, all areas) — computed from actual data:**

| Rank | Current (total) | Per-capita (adj. count ÷ faculty) |
|------|----------------|-----------------------------------|
| 1 | Carnegie Mellon (201 fac., 2407 pts) | Stanford (63 fac., 20.3 pts/fac.) |
| 2 | MIT (115, 1673) | UC Berkeley (91, 15.1) |
| 3 | UIUC (134, 1494) | MIT (115, 14.6) |
| 4 | UCSD (137, 1394) | UCLA (51, 13.9) |
| 5 | UC Berkeley (91, 1373) | Columbia (58, 13.4) |
| 6 | Stanford (63, 1277) | UW Seattle (81, 13.1) |
| 7 | Georgia Tech (159, 1128) | TTI Chicago (14, 13.1) |
| 8 | Cornell (111, 1092) | UPenn (73, 12.7) |
| 9 | UW Seattle (81, 1061) | Harvard (43, 12.7) |
| 10 | UMD College Park (110, 993) | UT Austin (67, 12.7) |

**Biggest risers**: TTI Chicago (#63→#7, +56), Caltech (#49→#16, +33),
UCLA (#19→#4, +15), Harvard (#25→#9, +16), Brown (#45→#24, +21).

**Biggest fallers**: Georgia Tech (#7→#33, −26), Northeastern (#15→#39, −24),
CMU (#1→#11, −10, largest CS dept in US at 201), UCSD (#4→#14, −10).

The pattern is clean: per-capita rewards small, selective departments where
every faculty member publishes at top venues (Stanford, Caltech, Harvard,
Columbia, TTI Chicago). It penalizes large, broad departments where many
faculty may be in less publication-intensive areas or have heavier teaching
loads (Georgia Tech, Northeastern, CMU).

**Implementation**: count unique authors from each institution across all
listed venues in the measurement window. This overcounts slightly (visiting
scholars, postdocs) but is a consistent denominator. A better approach: only
count authors who appear as last author on at least one paper in the window
(proxy for PI/faculty status). Toggleable.

## Scoring formula

```
paper_score = last_author_bonus + citation_bonus + award_bonus + talk_bonus
institution_score = sum(paper_score) / faculty_count   # when per-capita toggled on
```

## Signals — ranked by data availability

### Tier 1: Available from OpenAlex (Phase 1, fully automatable)

**Last-author bonus**: +0.5 to +1.0 per paper where the credited institution's
author is the last author. OpenAlex authorships[] includes
`author.position: "first"|"middle"|"last"` — no inference needed.
- Rationale: last author is typically the PI/senior author in ECE fields.
- Implement as a toggleable multiplier (0 = no bonus, 1 = +1.0 for last author).
- Per-attribution-mode: under "At Time of Publication," check the last author's
  listed affiliation on that paper. Under "Current Faculty," check if the last
  author is a known faculty member at the credited institution.

**Citation bonus**: +log₂(1 + cited_by_count) per paper.
- Available per-work on OpenAlex as `cited_by_count`.
- Log compresses the long tail (a paper with 10,000 cites gets ~13.3 pts, not
  dominating the count).
- Concerns: gaming via self-citation, citation rings, review-paper inflation.
- Mitigation: exclude self-citations where citing author shares an institution
  with cited author (OpenAlex exposes citing works' author affiliations).
  Toggleable: "raw citations" vs "self-citation adjusted."
- Known issue: citations accumulate over time, so older papers get more. A
  year-normalized variant (cites per year since publication) is the better
  default.

### Tier 2: Curatable (Phase 2, manual but finite)

**Best paper awards**: +100 per award.
- The set of awards at listed venues is finite and knowable:
  - ISSCC: Jack Kilby Award, Lewis Winner Award, Beatrice Winner Award
  - ISCA: Test of Time, Best Paper
  - DAC: Best Paper, Test of Time (25-year Retrospective)
  - JSSC: Best Paper Award
  - IEDM: Best Student Paper
  - ~20 venues × ~3 awards each = ~60 award types to track.
- Implementation: maintain `data/awards.json` — a curated list of award names,
  venue, years available, with known winning paper DOIs. Crowdsource additions
  via PR.
- Loses some nuance (not every venue has awards; some have multiple categories)
  but stays auditable.

**Test-of-time awards**: +500 per award.
- Same mechanism as best paper, separate multiplier. Higher value because ToT
  awards are rarer and signal lasting impact.
- At most venues: one ToT per year (or none). Very finite curation surface.

### Tier 3: Inference-based (Phase 3, expensive but doable)

**Faculty placement score**: +50 × (placement count) for each graduate who
becomes a tenure-track faculty member.
- Inference: take every author who published as a PhD student at institution A,
  then later (≥3 year gap) published as faculty at institution B. The gap
  filters for career stage transition.
- Requires: OpenAlex author records with full institution history
  (`authors/affiliations[]`). Expensive API calls (one per author), but a
  one-time batch.
- Circularity concern originally raised was wrong — this is a separate axis
  (placement power), not folded into research output. Display as its own
  separate ranking tab, like CSRankings' faculty placement view.

### Tier 4: Program-scraped (Phase 4, high maintenance)

**Invited talks at workshops of top conferences**: +10 per talk.
**Keynotes at top conferences**: +100 per keynote.
- No existing structured data source. Would need to scrape conference programs
  (typically HTML/PDF schedules) and match speaker names to OpenAlex author IDs.
- Maintenance burden: each conference's website is different; programs change
  yearly. Likely not worth the effort for v1/v2 — viable only if automated
  scraping per venue is built and the community helps surface corrections.
- Alternative: skip entirely and proxy via invitation-only publication venues
  (e.g., IEDM itself, the Proceedings of the IEEE).

### Tier 5: Second-order signals (experimental, research-phase)

These are derived from data already harvested — no new API calls — but their
interpretation is less established. Ship as experimental toggles with clear
documentation.

**Consistency multiplier**: reward schools that publish *every year* in a
venue cluster vs. those that spike one year and disappear.
- For each institution-area pair, compute the fraction of years in the
  measurement window where the institution had ≥1 paper at any of the area's
  venues. Multiply area score by 1 + 0.5 × (fraction of active years).
- A school publishing every year in a 5-year window gets a 1.5× multiplier;
  one publishing in only 2 of 5 years gets 1.2×.
- Rationale: sustained research groups are a stronger signal than a single
  star hire who publishes heavily then leaves.
- Data: already in the aggregated per-year counts. Free to compute.

**Co-author network quality**: not just "did you publish at ISCA" but "who
were your co-authors?" A paper co-authored with the top groups in the field
is a second-order signal that the institution is at the research frontier.
- For each paper, compute the mean adjusted count of all co-authors'
  institutions (excluding the paper itself). Weight the paper's contribution
  by 1 + log₂(1 + mean_coauthor_score).
- Rationale: papers co-authored with leading groups have higher visibility
  and impact, even controlling for venue. Also corrects for the case where a
  paper's topic fits the venue but the institution is peripheral to the field.
- Data: entirely from cached works (co-author institution graph). Complex but
  automatable.
- Risk: circular — strong institutions become stronger if this is a multiplier.

**Citation gravity** (distinct citing institutions): instead of raw cite count,
measure how many *different institutions* have cited the paper.
- A paper cited by 100 labs across 30 countries is qualitatively different
  from one cited by 100 researchers inside a single corporate lab.
- Compute: for each paper, count distinct citing-institution lineages.
  Score: +log₂(1 + distinct_citing_insts).
- Harder to game than raw citations (self-citation rings from one institution
  don't inflate it). Requires cursor-paging each work's `/cited_by` API
  endpoint — expensive (1–2 extra calls per paper). Skip for v1; probe on
  a sample first.

**Implementation status**: all Tier 5 signals are research-phase. Ship as
experimental toggles behind a "beta" flag on the site, with tooltips
explaining what each one does and why it's experimental.

## The LLM rubric angle

The original idea of "a single codex/gpt call using our own custom rubric" is
separate from the structured signals above. It would work like:

1. Harvest all papers at listed venues (same as CSRankings).
2. For each paper, prompt an LLM with the title+abstract+PDF text:
   "Score this paper 0-10 on: novelty, methodological rigor, potential impact."
3. Sum the rubric scores per institution.

**Problems**:
- **Reproducibility**: different models/prompts/API versions give different
  scores. The ranking would shift every time the model is updated.
- **Auditability**: "Why did MIT get 8.3 on rigor?" — no answer except "the
  model said so."
- **Cost** (budget: ~$1/day): ~5k–10k papers/venue × ~20 venues = 100k–200k
  papers. Even at $0.001/paper (cheap, local model), that's $100–200 per run.
  At GPT-4o prices, it's prohibitive.
- **Gaming**: authors optimize abstracts for the rubric.

**Recommendation**: skip LLM-based scoring entirely. The structured signals
are more transparent, cheaper, and more defensible.

## Interaction with attribution modes

Scoring depends on which institution gets credit:

| Signal | Under "At Time of Publication" | Under "Current Faculty" |
|--------|------|------|
| Last-author bonus | Check last author's affiliation on paper | Check if last author is current faculty at institution |
| Citation bonus | Attached to paper, credits wherever paper is attributed | Same |
| Awards | Attached to paper, same | Same |
| Placement | N/A (separate view) | N/A (separate view) |

Awards and citations travel with the paper itself, so their attribution follows
whichever institution the paper is credited to.

## Ranking displays

- **"Standard Score"** (default): sum of (last-author + citation bonus) across
  selected areas. Just the Tier 1 signals. Toggleable areas, year range, region
  filter — same UX as CSRankings.
- **"Per-Capita"** (toggle): divides score by estimated faculty count. Reveals
  research density vs. raw scale.
- **"Full Score"** (toggle): adds award bonuses (Tier 2). Requires curated
  awards.json. Disclaimers about coverage gaps.
- **"Consistency"** (beta toggle): applies the consistency multiplier (Tier 5).
- **"Area Breadth"** (toggle): switches from sum to geometric mean, rewarding
  schools that are strong across multiple areas (same formula as current
  CSRankings/ECERankings).
- **"Faculty Placement"** (separate tab): ranks institutions by number of
  graduates who became tenure-track faculty.

## Phases

### Phase 0 — Per-capita normalization (trivial, ship first)
1. Count unique authors per institution across all harvested works in the
   measurement window. Optionally filter to last-author-only as PI proxy.
2. Add `faculty_count` to the aggregation output.
3. Compute per-capita score = adjusted_count / faculty_count.
4. Ship as a toggle alongside raw count. This is the single biggest
   correction to CSRankings' blind spots and costs nothing to compute.

### Phase 1 — Tier 1 signals (automatic, no new data)
1. Extend aggregator to read `authorships[].author.position` from cached works.
2. Implement last-author bonus: for each paper, for each institution, check if
   any author from that institution holds the `"last"` position.
3. Implement citation bonus: read `cited_by_count`, compute log₂(1 + c).
4. Optional: self-citation filter — compare citing/cited institution overlap.
5. Ship both as toggles on the site alongside the existing plain count.

### Phase 2 — Tier 2 signals (curation layer)
1. Create `data/awards.json` — award name, venue, DOI-based winning papers.
2. Create `data/tests-of-time.json` — same structure, separate multiplier.
3. Extend aggregator to match work DOIs against award lists.
4. Add "Full Score" view on site.

### Phase 3 — Placement inference
1. Batch-resolve author histories for every author in cached works.
2. Detect career transitions: identify authors who published with institution A
   in early years and institution B in later years (≥3 year gap).
3. Rank institutions by number of placed faculty.
4. Ship as separate visualization tab.

### Phase 4 — Tier 5 second-order signals (experimental)
1. **Consistency multiplier**: compute per-year per-area publishing activity
   from already-aggregated data. Apply multiplier in aggregator.
2. **Co-author network quality**: for each paper, look up co-author institutions'
   adjusted counts from the same dataset. Weight paper score accordingly.
   Watch for circularity — ship as beta-only.
3. **Citation gravity (probe)**: on a sample of ~1,000 works, fetch
   `/cited_by` and measure distinct citing institutions. If the API cost
   (1–2 extra calls/paper) is acceptable and the signal correlates well
   with expert judgment, promote to Tier 1.

### Phase 5 — Program scraping (optional, high cost)
1. Build per-venue conference-program scrapers for recent years.
2. Match speaker names to OpenAlex author IDs.
3. Add talk/keynote bonuses.

## Data challenges specific to CSRankings 2.0

| Challenge | Impact | Mitigation |
|-----------|--------|------------|
| Citations favor older papers | Senior institutions dominate | Use cites/year since publication |
| Author position conventions vary | Last author ≠ PI in all subfields | Toggleable; document the assumption |
| Self-citation gaming | Inflates citation bonus | Self-citation filter (same-institution) |
| Awards curation is incomplete | Unfair to venues with no awards | Present as "with known awards" toggle |
| Placement inference is noisy | Visiting stints mistaken for faculty jobs | Require ≥3 year gap + ≥2 distinct years |
| Per-capita denominator noisy | Postdocs/visitors inflate faculty count | Count only authors with ≥1 last-author paper in window |
| Consistency window choice | Short window penalizes young depts | Use 10-year default; make window adjustable |
| Co-author network circularity | Rich-get-richer feedback loop | Ship as experimental toggle only |
| Citation gravity API cost | 1–2 extra calls per work | Probe on sample first; skip if cost prohibitive |

## Relationship to ECERankings

CSRankings 2.0 is a separate concept, not a replacement for ECERankings.
ECERankings is ECE-specific with journal-aware venue selection. CSRankings 2.0
is a methodology experiment applicable to any field (CS, ECE, or broader).
The pipeline code from ECERankings (harvest, aggregate, normalize) is reusable;
CSRankings 2.0 adds a scoring module on top of the same data.
