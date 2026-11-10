---
name: find-implicit-state-machines
description: Audit codebases for implicit state machines — emergent boolean clusters, nullable fields, out-of-order async callbacks, or scattered status flags instead of explicit state machines or discriminated unions.
---

# Find implicit state machines

Read-only audit: identify and rank implicit state machines in the codebase. Do not edit code unless requested.

## Definition & Signals

An implicit state machine exists when state transitions and modes are unmodeled—emerging accidentally from:
- **Flag clusters:** N booleans (`isLoading`, `hasError`, `isSuccess`) where $2^N$ combinations exist but few are valid.
- **Mutual exclusion by convention:** Nullable fields where field $A$ is only valid when $B$ is null.
- **Scattered status writes:** Multiple event handlers or endpoints writing to the same state/database columns without centralized guards.
- **URL/Storage drift:** In-memory state out of sync with URL hash, query params, or local cache.
- **Async concurrency hazards:** Timeouts, retries, or fetches arriving late, twice, or out of order.

**Do NOT report:**
- Single independent boolean toggles (`isOpen` for a modal).
- Pure derived values computed dynamically on render.
- Static config flags.

## Process

1. **Map:** Review directories, entry points, and state stores.
2. **Trace:** Verify read and write sites before reporting. Never infer a bug from variable names alone.
3. **Cluster:** Group repeated patterns into a single row marked `(pattern, N occurrences)`.
4. **Classify Evidence:**
   - **Confirmed:** Concrete code path provably reaches an invalid or frozen state.
   - **Likely:** State model permits illegal combinations; no guard prevents them.
   - **Theoretical:** Possible in principle, negligible real-world blast radius.
5. **Recommend Smallest Fix:**
   1. Delete redundant state / derive it.
   2. Discriminated union / enum (illegal states unrepresentable).
   3. Centralized reducer / transition function with guards.
   4. Formal FSM library (only for 4+ states with high-impact async flows).

## Output Format

### Part 1: Summary Table
| # | Title | 1-Sentence Summary | Evidence | Risk | Key Files | Fix (Level 1–4) |
|---|-------|--------------------|:--------:|:----:|-----------|:---------------:|
*Sort by Risk (High > Med > Low), then Evidence (Confirmed > Likely).*

### Part 2: Deep Dives (Top 3–5 High-Risk or Confirmed Bugs)
For each:
- **States & Mermaid `stateDiagram-v2`**
- **Trigger Path:** Step-by-step how the illegal state is reached, citing `file:line`.
- **Consequence:** User impact, data corruption, or UI freeze.
- **Concrete Sketch:** Proposed discriminated union or transition guard.
- **Regression Test:** Scenario/assertion that catches this bug.

### Part 3: Systemic Next Steps
- Top 3 fixes to prioritize.
- Prevention mechanism (lint rule, TypeScript discriminated union pattern, or PR review checklist).

## Rules

- Every claim must cite `file:line`. If you can't cite it, label it as a hypothesis.
- Prefer fewer, well-evidenced findings over a long noisy list.
- If the codebase is too large to cover fully, say what you covered and what you skipped.
