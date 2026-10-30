# Queued Semantic Scholar Integrations (2026-10-29)

## Purpose

While raw Semantic Scholar (S2) dumps cannot serve as the primary source of truth for venue membership or historical publication-time affiliations, S2 provides significant value as a **secondary discovery, enrichment, and disambiguation layer**.

---

## Queued Tasks for Semantic Scholar

### 1. Title-to-DOI Discovery Engine for No-DOI Proceedings Papers
- **Application**: In ML (ICLR/ICML/NeurIPS) and historical proceedings (ISCA, DAC, ISSCC pre-2010), many papers lack publisher-deposited DOIs.
- **Workflow**:
  - Feed the canonical title + author list from publisher proceedings into S2's Paper Search/Match endpoint (`/graph/v1/paper/search?query=...` or `/graph/v1/paper/batch`).
  - Extract external identifiers (`DOI`, `ArXiv`, `ACL`, `CorpusId`).
  - Route discovered DOIs to OpenAlex for paper-level affiliation retrieval.

### 2. Author Disambiguation & Co-Author Graph Assistance
- **Application**: Resolving common name collisions in fractional author attribution ($\frac{1}{N}$).
- **Workflow**:
  - When an author name is ambiguous across multiple departments or institutions, query S2's author graph (`/graph/v1/author/{author_id}?fields=papers,coauthors`).
  - Use co-authorship clusters to confirm which institution the author belonged to during the paper's publication window.

### 3. Proceedings Reconciliation & Sanity Cross-Check
- **Application**: Spotting missing papers and identifying errata.
- **Workflow**:
  - Cross-check our publisher-scraped proceedings lists (PMLR, OpenReview, NeurIPS.cc) against S2's crawled venue corpora to catch any missed papers, title misspellings, or author count differences.

### 4. Secondary Metric Enrichment (Front-End & Research Metrics)
- **Application**: Supplementary analytics on the static site (without altering the core publication-count ranking formula).
- **Workflow**:
  - Ingest S2 citation counts and "Influential Citation Counts" as opt-in informational metadata displayed on institution and venue exploration pages.

---

## Implementation Policy & Safeguards
1. **Never use S2 author-profile affiliations for historical ranking attribution**: Always require paper-specific affiliations from OpenAlex work-author joins, Crossref deposited metadata, or PDF first-page headers.
2. **Never use S2 venue tags to define conference membership**: Canonical paper lists must originate from official publishers (OpenReview, PMLR, NeurIPS.cc, IEEE Xplore, ACM DL).
