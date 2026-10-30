# Group A Scope Ingestion Report (2016–2025)
**Date**: 2026-10-29  
**Status**: Completed  
**Corpus Additions**: 33,238 works across 50 venue-year editions  

---

## 1. Summary of Harvested Editions

All 5 approved Group A venues across the 10-year rolling window (2016–2025) have been completely harvested into `cache/<venue>/<year>/works.jsonl` using OpenAlex API v1 with checkpointing.

| Venue Key | Area | Full Name | Kind | Total 2016–2025 Works | Yearly Range |
|---|---|---|---|---:|---|
| **`iros`** | `robotics` | IEEE/RSJ Int. Conf. on Intelligent Robots and Systems | Conference | **11,912** | 833 – 1,988 |
| **`taslp`** | `sigproc` | IEEE/ACM Trans. on Audio, Speech, and Language Processing | Journal | **2,837** | 211 – 378 |
| **`interspeech`** | `sigproc` | Interspeech | Conference | **9,601** | 748 – 1,151 |
| **`ofc`** | `photonics` | Optical Fiber Communication Conference (OFC) | Conference | **7,493** | 531 – 1,312 |
| **`jmems`** | `devices` | IEEE/ASME Journal of Microelectromechanical Systems | Journal | **1,395** | 93 – 225 |
| **Total** | | | | **33,238** | |

---

## 2. Year-by-Year Edition Breakdown

| Year | `iros` | `taslp` | `interspeech` | `ofc` | `jmems` | Total Works |
|---|---:|---:|---:|---:|---:|---:|
| **2016** | 833 | 257 | 775 | 679 | 148 | 2,692 |
| **2017** | 884 | 265 | 795 | 739 | 173 | 2,856 |
| **2018** | 1,098 | 250 | 748 | 735 | 155 | 2,986 |
| **2019** | 934 | 211 | 914 | 648 | 137 | 2,844 |
| **2020** | 1,129 | 253 | 1,030 | 671 | 225 | 3,308 |
| **2021** | 1,039 | 281 | 963 | 627 | 147 | 3,057 |
| **2022** | 1,220 | 266 | 1,102 | 531 | 118 | 3,237 |
| **2023** | 1,200 | 339 | 1,097 | 1,312 | 93 | 4,041 |
| **2024** | 1,587 | 337 | 1,026 | 765 | 98 | 3,813 |
| **2025** | 1,988 | 378 | 1,151 | 786 | 101 | 4,404 |
| **Total** | **11,912** | **2,837** | **9,601** | **7,493** | **1,395** | **33,238** |

---

## 3. Quality & Invariants Verification

1. **Storage Layout**: Every target directory exists under `cache/<venue>/<year>/works.jsonl` with an adjacent `.checkpoint` indicating completion (`"done": true`).
2. **Authorship & Affiliation Hydration**: OpenAlex works endpoints returned full author objects including raw affiliation strings and resolved educational institutions.
3. **Unit Tests**: Full test suite passes cleanly:
   ```
   Ran 74 tests in 0.627s
   OK
   ```
4. **Site & Release Boundary**: No public site files (`site/data/`) were modified during harvesting; data is strictly staged in `cache/` awaiting release build.
