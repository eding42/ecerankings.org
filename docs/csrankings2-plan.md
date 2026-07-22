# CSRankings 2.0 — Multi-Signal Ranking Plan

A speculative extension of the CSRankings model that scores institutions on a
weighted rubric of signals, not just paper counts. Built on OpenAlex for the
same reason as ECERankings (data breadth, affiliation coverage), with curated
enrichment layers for signals OpenAlex doesn't have.

## Core philosophy

CSRankings is narrow and bulletproof: "did you publish at venue X, yes/no,
1/N per author." CSRankings 2.0 keeps the venue list as the entry gate (you
still need to publish at a top venue to be counted) but **modulates the score**
based on qualitative signals. The base formula:

```
paper_score = last_author_bonus + citation_bonus + award_bonus + talk_bonus
institution_score = sum(paper_score) over all papers at listed venues
```

No geometric mean across areas in v1 (that's a separate UX toggle). v1 ranks by
total weighted score; area breadth weighting comes later as a toggle.

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
- **"Full Score"** (toggle): adds award bonuses (Tier 2). Requires curated
  awards.json. Disclaimers about coverage gaps.
- **"Area Breadth"** (toggle): switches from sum to geometric mean, rewarding
  schools that are strong across multiple areas (same formula as current
  CSRankings/ECERankings).
- **"Faculty Placement"** (separate tab): ranks institutions by number of
  graduates who became tenure-track faculty.

## Phases

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

### Phase 4 — Program scraping (optional, high cost)
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

## Relationship to ECERankings

CSRankings 2.0 is a separate concept, not a replacement for ECERankings.
ECERankings is ECE-specific with journal-aware venue selection. CSRankings 2.0
is a methodology experiment applicable to any field (CS, ECE, or broader).
The pipeline code from ECERankings (harvest, aggregate, normalize) is reusable;
CSRankings 2.0 adds a scoring module on top of the same data.
