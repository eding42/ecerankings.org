# USC power / power-electronics audit — independent review

- Date: 2026-10-29
- Reviewer: Claude (independent research sub-agent)
- Subject: University of Southern California (OpenAlex `I1174212`), areas `power` and `powerelec`
- Scope: read-only. Nothing in `data/`, `pipeline/`, `site/` or `cache/` was changed. Nothing was deployed. No paid OpenAlex calls were made. Evidence comes from the materialized `cache/`, the free public Crossref REST API, and official USC, IEEE and conference web pages.
- Scratch scripts: `.tmp/usc_scan.py` and `.tmp/xref_usc.py` (gitignored, not permanent).

## 0. Bottom line

**USC's low power scores are mostly real.** The data pipeline is not losing USC's papers. The venue list is a minor factor that cannot explain the gap. Confidence: high for "no affiliation misses in the five registered venues", medium-high for "USC has no dedicated power-systems or power-electronics research faculty".

1. **Reproduced exactly.** I recomputed the figures from `site/data/power.json` with the US filter from `site/data/institutions.json`, years 2016–2025:
   - `power`: 2.700 adjusted, US rank 104 of 215 nonzero.
   - `powerelec`: 0.2 adjusted, US rank **220** of 232 nonzero.
   - The parent agent reported powerelec rank 218. The difference probably comes from tie handling or the institution set used; it changes nothing. USC ranks 12th in `control` (107.7), which is where its energy-adjacent faculty actually publish.
2. **No affiliation misses found.** I scanned every TPWRS, TSG, TPEL, JESTPE and ECCE record in the cache (36,357 records, 2016–2025) on three signals:
   - the resolved USC ID;
   - raw-affiliation regexes (USC, Viterbi, Ming Hsieh, 90089);
   - the names of 18 USC faculty with energy-adjacent work.

   All hits were already credited to USC. The only other matches were false positives: "Andrew and Erna Viterbi Faculty", Technion; and same-name authors such as Iannuzzo (Aalborg), Milan Jovanović (Delta) and Prasanna Piya (Saskatchewan).
3. **USC has no dedicated power-systems or power-electronics research faculty.** The official ECE pages show:
   - Mohammed Beshir, a teaching-track Professor of Practice;
   - Martin Gundersen, emeritus, working on pulsed power, which is not grid or converter research;
   - an endowed "Lloyd F. Hunt Chair of Electrical Power Engineering" held by computer architect Murali Annavaram.

   Every credited power paper comes from controls, operations-research or devices faculty publishing occasionally in power venues.
4. **There is some venue bias, but it is small.** USC-affiliated energy work outside the registered venues does exist: PES regional conferences, ISGT, ACM e-Energy and IEEE TCNS. Confirmed USC credit from it is roughly 3.5 adjusted over 10 years. Adding +5 to USC alone would move it from US #104 to about #63. Expanding the venue list would also add credit for every other institution, so the real move would be smaller.

## 1. What the 2.70 consists of (all from cache)

Credit = 1/N per author. USC authors were identified through resolved institutions; the raw strings were checked as well.

| Venue | Year | DOI | USC authors / N | Credit | USC unit |
|---|---|---|---|---|---|
| TPWRS | 2017 | [10.1109/tpwrs.2017.2695964](https://doi.org/10.1109/tpwrs.2017.2695964) | Atakan, Sen / 3 | 0.667 | Epstein ISE |
| TSG | 2016 | [10.1109/tsg.2016.2616881](https://doi.org/10.1109/tsg.2016.2616881) | Sen / 2 | 0.5 | Epstein ISE |
| TSG | 2016 | [10.1109/tsg.2016.2623275](https://doi.org/10.1109/tsg.2016.2623275) | Nayyar / 5 | 0.2 | Ming Hsieh EE |
| TSG | 2017 | [10.1109/tsg.2017.2702655](https://doi.org/10.1109/tsg.2017.2702655) | R. Jain / 2 | 0.5 | EE |
| TSG | 2018 | [10.1109/tsg.2018.2844307](https://doi.org/10.1109/tsg.2018.2844307) | Ziyu He / 6 | 0.167 | ISE |
| TSG | 2020 | [10.1109/tsg.2020.3044903](https://doi.org/10.1109/tsg.2020.3044903) | Bogdan, Jonckheere / 3 | 0.667 | EE |
| **power total** | | | | **2.700** (6 papers) | |
| JESTPE | 2019 | [10.1109/jestpe.2019.2912978](https://doi.org/10.1109/jestpe.2019.2912978) | Han Wang / 5 | 0.2 | Ming Hsieh EE (GaN devices) |
| **powerelec total** | | | | **0.2** (1 paper) | |

These numbers match the parent agent's figures exactly. Half of the `power` credit comes from Industrial and Systems Engineering, not ECE. That is correct under the institution-level policy, but it is worth knowing.

## 2. Faculty evidence (official sources)

The fetches succeeded through a web reader; direct curl was blocked by USC's Cloudflare.

- **ECE research-area page** ["Electromagnetics and Energy Conversion"](https://minghsiehece.usc.edu/research/area/electromagnetics-and-energy-conversion-research-area/), last updated 24 Sep 2026.
  - Topic tags include "Electric Power Systems" and "Pulsed Power". There is no "power electronics" tag.
  - Listed faculty: Dapkus (emeritus), Gundersen (emeritus), Khajavikhan, E.S. Kim, Kuehl (emeritus), Lazzi, Madhukar, Moghaddam, Prata, Ravichandran, Sideris. None of them works on grid operations or power conversion.
  - The only power-related lab listed is "Pulsed Power – Martin Gundersen".
- **[Faculty profile: Mohammed Beshir](https://minghsiehece.usc.edu/directory/faculty/profile/?lname=Beshir&fname=Mohammed).** The headline title is "Professor of Electrical and Computer Engineering Practice", while the biography says "Associate Professor of Engineering Practice"; the page is internally inconsistent. His interests include "power system design and analysis, grid reliability planning, renewable energy resources, smart-grid development … electric vehicle grid integration". He is teaching-track, which is consistent with low output in top venues.
- **[ECE faculty directory](https://minghsiehece.usc.edu/faculty-directory/).** The only power-titled appointment is Murali Annavaram, "Lloyd F. Hunt Chair of Electrical Power Engineering…". His cached work is in ISCA, MICRO, HPCA and ASPLOS, i.e. computer architecture.
- **[USC Online MS in Electric Power](https://online.usc.edu/programs/electric-power-ms/).** The degree exists; the page names no faculty.
- **Historical.** [Viterbi obituary for Tsen-Chung Cheng](https://viterbi.usc.edu/news/news/2011/tsen-chung-cheng.htm) (2011) describes him as an "Authority on Power Grids" who held the Hunt chair. That confirms USC had a power-systems faculty member before the 2016–2025 window. I did not find a successor research hire in official pages.

**Caveat.** The directory lists titles, not research areas per person. Someone in another department (CEE, ISE, CS) could do grid research. Ketan Savla (CEE) and Prasanna (ECE/CS) do adjacent work; see §3.

## 3. USC energy research outside the registered venues

These came from free Crossref lookups. For each paper the affiliation was confirmed on the Crossref record itself, not inferred from the author's name.

| DOI | Venue | USC authors (Crossref affiliation) | Hypothetical credit |
|---|---|---|---|
| [10.1109/tdc-la.2016.7805675](https://doi.org/10.1109/tdc-la.2016.7805675) | IEEE PES T&D Latin America 2016 | Jiang, Tian, Beshir / 5 — "Ming Hsieh Department of Electrical Engineering, University of Southern California" | 0.6 |
| [10.1109/tpec60005.2024.10472198](https://doi.org/10.1109/tpec60005.2024.10472198) | IEEE Texas Power & Energy Conf. 2024 | Liu, Beshir, Alhajraf / 4 | 0.75 |
| [10.1145/3137133.3137145](https://doi.org/10.1145/3137133.3137145) | ACM BuildSys 2017 (Crossref: "Proceedings of the 4th ACM International Conference…") | Kuppannagari, Prasanna / 3 | 0.667 |
| [10.1145/3447555.3466586](https://doi.org/10.1145/3447555.3466586) | ACM e-Energy 2021 | 4 / 4 USC | 1.0 |
| [10.1109/tcns.2022.3165070](https://doi.org/10.1109/tcns.2022.3165070) | IEEE TCNS 2022 (electricity markets) | R. Jain / 2 | 0.5 |

These are plausibly USC, but Crossref has no affiliation data, so they are **not verified**: [ISGT 2016 EV charging (Beshir)](https://doi.org/10.1109/isgt.2016.7781228), [ISGT 2017](https://doi.org/10.1109/isgt.2017.8086001) and [ISGT 2018](https://doi.org/10.1109/isgt.2018.8403335) (Prasanna group), [SmartGridComm 2018](https://doi.org/10.1109/smartgridcomm.2018.8587464), [TPDS 2016 "MATCH for the Prosumer Smart Grid"](https://doi.org/10.1109/tpds.2016.2544316), [ACC 2016 DC power networks (Savla)](https://doi.org/10.1109/acc.2016.7526600), [ACC 2020 electricity markets (Jain)](https://doi.org/10.23919/acc45564.2020.9147522).

Grid-themed papers in CDC are already scored, but under `control`, because area is decided by venue. Examples are the Jain and Nayyar electricity-market papers, such as [10.1109/cdc40024.2019.9029538](https://doi.org/10.1109/cdc40024.2019.9029538). This is the methodology working as designed, not a miss. It does mean USC's energy research shows up as control strength.

Name-only Crossref hits were discarded. For example, `10.1109/temc.2025.3607560` is by Abduselam Hamid **Beshir, Aalborg**, not USC. Many "M. Jovanović" and "Rahul Jain" energy papers belong to different people.

## 4. Data-integrity checks

| Check | Result |
|---|---|
| Raw strings mentioning USC but resolved elsewhere, in the 5 venues | **0** |
| USC faculty names in the 5 venues with a non-USC or empty institution | **0** (all same-name false positives) |
| USC duplicate OpenAlex ID | `I150972724` → `I1174212` alias exists (`data/institution-aliases.csv`) |
| University of South Carolina conflation | Separate ID `I155781252`. Its 2016–2025 US results: power 0.5 (#154), powerelec 23.19 (#47). No South Carolina string was assigned to `I1174212`, and the USC regex excludes "South Carolina". |
| Works with no authorships, which cannot be credited | TPWRS 189, TSG 144, TPEL 384, JESTPE 86, ECCE 72 (2016–2025). Some are paratext such as "IEEE Power & Energy Society" cover items. A USC paper could hide here, but at about 3.5% of records the expected loss for a low-volume institution is about 0.1 adjusted. |
| ECCE 2023–2025 | About 99% of works have no OpenAlex institutions, only raw strings, so credit depends entirely on `affiliation-map.csv`. No USC raw strings appear there. |
| Cache volume vs Crossref (journal-article DOIs, 2016–2025 total) | TPWRS 5,367 vs 5,638 (−4.8%). TSG 4,659 vs 4,781. TPEL 12,212 vs 12,000. JESTPE 4,324 vs 4,181. Year-by-year counts diverge a lot (e.g. TPWRS 2024 407 vs 652) because of online-first vs issue dating, but the totals agree. A 2016-issue TPWRS paper with a 2015 OpenAlex year (`10.1109/tpwrs.2015.2451592`) is absent from the cache: a small year-boundary leak. |
| Crossref `query.affiliation` as a cross-check | **Not usable for negative evidence.** It returned only 1 of the 3 cached USC TPWRS papers and 0 of the 6 TSG papers, because IEEE deposits affiliations sparsely. I did not treat "not found in Crossref" as absence. |

**Side finding outside power, for the owner.** `data/affiliation-map.csv` has `auto` rows that send USC strings to the wrong institution:
- "Department of Industrial and Systems Engineering, University of Southern California in Los Angeles" → **UCLA** (`I161318765`);
- "Facebook and University of Southern California" → Meta;
- "Peking University;University of Southern California" → Peking only.

There are 18 of 319 USC strings not mapped to USC; most are `review` status, which `aggregate.py:226` ignores. I did not fix these, since the task was read-only. They should go to the adjudication queue.

## 5. Objections to methodology and to the parent agent's interpretation

1. **Do not present "rank 104" as a finding about USC's quality.** 215 US institutions have nonzero `power` scores, and the score is spread thinly:
   - rank 50 is at 11.3, rank 75 at 5.8, rank 100 at 2.9;
   - USC's +2 sensitivity is 104 → 83.

   Below roughly rank 60 the ordering reflects one or two stray papers, not programs. The site should consider a minimum-evidence threshold or show ties or bands.
2. **The absence finding rests on titles.** The directory exposes titles, not areas. The conclusion "no dedicated power faculty" combines that with the fact that no USC author has more than 1 paper in any of the five registered venues over 10 years. It does not rest on a search returning nothing. It could still be overturned by an official CEE or ISE grid-research profile I did not open.
3. **The `power` area is structurally thinner than its peers.** It has 2 journals and no conference. Most other areas include their flagship conference (e.g. ICASSP, CDC, ICRA). The power community's main meetings, PES General Meeting and PSCC, are omitted. Its peer PES transactions (TPWRD, TSTE, TEC) are omitted too, while the neighbouring `powerelec` area has 3 venues. This hurts institutions whose energy work is in grid operations and markets rather than in TPWRS/TSG. USC's ISGT and e-Energy output is an example, but those venues would probably fail the selectivity test anyway.
4. **The PLAN.md venue policy is not applied consistently.** See §6.

## 6. Are all 69 registered venues consistently high-visibility and selective?

I did not cite any acceptance rate: none were verified from a primary source in this session. The volumes below are average cached records per year, 2016–2025, from `cache/`.

**Within-area volume balance is violated in several areas** (PLAN.md §Venue-inclusion policy, "Within-area volume balance"):

| Area | Pairing | Volume per year |
|---|---|---|
| sigproc | ICASSP vs JSTSP | 2,004 vs 129 (15.5×) |
| photonics | CLEO vs Optica | 1,924 vs 254 (7.6×). JLT adds 1,281. CLEO is an abstract-format conference ([DOIs `10.1364/cleo_si...`](https://doi.org/10.1364/cleo_si.2024.stu3p.2)). |
| robotics | ICRA + RA-L vs Science Robotics | 1,148 + 976 vs 88 |
| powerelec | TPEL + ECCE vs JESTPE | 1,221 + 980 vs 432 |
| devices | TED vs VLSI-Tech | 999 vs 58 |
| em_rf | TAP vs IMS | 1,042 vs 364 |

PLAN.md itself names T-ED as the "workhorse" that should be below the line, yet TED is `default_on` at full weight.

**Coverage holes that look like data gaps, not real absences** (years with records out of 10):
- `vlsi-circuits` 4/10 and `vlsi-tech` 6/10 (both are annual);
- `isca` 9, `dac` 9, `iccad` 9, `sigcomm` 9 (all annual);
- `prxquantum` 6 (launched 2020, so plausible);
- `iccv` 5 is correct, since it is biennial;
- `nat-electronics` 9 (launched 2018, so plausible).

The VLSI Symposia and the missing ISCA/DAC/ICCAD years deserve a `verify-data` pass. They depress the circuits, devices and EDA areas for everyone.

**Single-venue or thin areas:**
- `biomed` has TBME only.
- `quantum` has three venues totalling about 370 per year.
- `power` has 2 venues (see §5.3).

**Policy contradictions:**
- PLAN.md says "Multidisciplinary parents are excluded (Nature, Science, Science Advances, Nature Communications)", but the registry has them in `flagship`. The area is `default_on: false`, which limits the harm, but the docs and registry disagree.
- PLAN.md quotes Light: Science & Applications at about 310 per year; the cache has 228.
- RA-L is a letters journal at about 976 per year, sitting next to T-RO at 207.

## 7. Priority list of omitted ECE venues

The venues below were checked against primary or official listings. Volumes are 2024 Crossref `journal-article` DOI counts from the free API (journals only).

| Priority | Venue | Official source | 2024 vol. | Rationale / caution |
|---|---|---|---|---|
| 1 | **IEEE Trans. Power Delivery (TPWRD)**, ISSN 0885-8977 | [IEEE PES Transactions list](https://ieee-pes.org/publications/transactions/) | 357 | A PES flagship transaction next to TPWRS and TSG, in scope. Lowest-effort fix for the thin `power` area. |
| 1 | **IEEE Trans. Sustainable Energy (TSTE)**, 1949-3029 | [PES TSTE](https://ieee-pes.org/publications/transactions-on-sustainable-energy/editorial-board/) | 242 | In scope; renewables integration. |
| 2 | **IEEE Trans. Energy Conversion (TEC)**, 0885-8969 | PES Transactions list | 243 | Machines and converters. Overlaps `powerelec`, so decide which area it belongs to. |
| 2 | **PSCC** / **PES General Meeting** | PES | — | The only candidate conference tier for `power`. PES GM is very large; consider it below the line. |
| 2 | **TCAS-I** (1549-8328) | [ieee-cas.org/publication/TCAS-I](https://ieee-cas.org/publication/TCAS-I) | 605 | The core CAS regular-paper journal. Scope is broad: it includes power electronics and control, so check the >80% scope test. |
| 3 | **TCAS-II** (1549-7747) | [ieee-cas.org/publication/TCAS-II](https://ieee-cas.org/publication/TCAS-II) | 1,059 | Express briefs at high volume. Below the line at most. |
| 2 | **TVLSI** (1063-8210) | [CAS publications](https://ieee-cas.org/publications) | 269 | Fits circuits/EDA, with modest volume. |
| 2 | **DATE** | [date-conference.com](https://www.date-conference.com/) | — | Major EDA conference (DATE 2027 is in Dresden). It would balance DAC and ICCAD. |
| 3 | **ASP-DAC** | [aspdac.com](https://www.aspdac.com/) (redirects to the ASP-DAC 2027 site) | — | Regional EDA conference; below the line. |
| 2 | **IJRR** (0278-3649, SAGE) | Crossref journal record | 115 | Low volume and in scope. It would balance ICRA and RA-L volume. |
| 2 | **IROS** | IEEE/RSJ | — | ICRA's peer at similar volume. Adding it without a tier worsens the volume imbalance. |
| ? | **"TAS" is ambiguous** | — | — | It could mean IEEE Trans. Applied Superconductivity (1051-8223; 1,152 articles in 2024, many conference-proceedings papers) or T-ASE, Automation Science & Engineering (1545-5955; 627). The parent agent should say which. Applied Superconductivity looks like a poor selectivity fit. |
| 3 | TIE (0278-0046, 1,689) / TIA (0093-9994, 793) | IEEE IES/IAS | — | Large; overlap with `powerelec`. Below the line. |
| — | TEMPR (2771-9626, 62) | PES | — | New and small; watch list. |

For USC specifically, none of these additions would change the conclusion. I did not measure USC's output in TPWRD, TSTE or TEC, because that needs harvesting; that is an unresolved gap.

## 8. Unresolved gaps

1. **USC counts in TPWRD, TSTE, TEC, PSCC and PES GM are unknown.** Measuring them requires harvesting, which means paid OpenAlex calls; not done.
2. **Possible grid researchers outside ECE are not checked.** I did not open official CEE or ISE profile pages for possible grid researchers, e.g. Savla (CEE) or Sen and Pang (ISE).
3. **Seven ISGT, SmartGridComm, TPDS and ACC papers lack Crossref affiliations.** They are plausibly USC but not verified.
4. **The ~875 author-less records in the five venues were not resolved.** They cover 2016–2025.
5. **No official acceptance rates were collected.** The IEEE PES Author's Kit reportedly states one, but I could not fetch it directly (Cloudflare) and have not quoted it.
6. **The powerelec rank differs: 220 here vs 218 from the parent.** The cause was not traced.
