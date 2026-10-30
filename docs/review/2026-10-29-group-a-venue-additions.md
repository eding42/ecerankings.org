# Group A Venue Additions — Execution Report (2026-10-29)

## Summary

In response to the scope gap audit, Group A candidate additions have been approved and integrated into `data/areas.json` and synchronized with `site/data/areas.json`. All 74 unit tests pass.

| Area | Venue Key | Full Name | Kind | OpenAlex Source ID(s) | Expected Works/Year | Annual Volume (2024) |
|---|---|---|---|---|---|---:|
| `robotics` | `iros` | IEEE/RSJ International Conference on Intelligent Robots and Systems (IROS) | conference | `S4393918188` | [800, 2000] | 1,587 |
| `sigproc` | `taslp` | IEEE/ACM Transactions on Audio, Speech, and Language Processing | journal | `S199497470`, `S4210169297`, `S5407042752` | [200, 450] | 339 |
| `sigproc` | `interspeech` | Interspeech | conference | `S4393918409` | [700, 1300] | 1,026 |
| `photonics` | `ofc` | Optical Fiber Communication Conference (OFC) | conference | `S4306420648` | [500, 1400] | 765 |
| `devices` | `jmems` | IEEE/ASME Journal of Microelectromechanical Systems | journal | `S4210187724`, `S167509434` | [100, 250] | 115 |

## Verification Details

1. **Robotics (`iros`)**:
   - Sole authority: IEEE/RSJ. OpenAlex `S4393918188` contains 27,586 works spanning 1988–2025.
   - Balances ICRA by adding the second universal flagship in robotics.

2. **Signal Processing (`taslp` & `interspeech`)**:
   - `taslp`: OpenAlex partitioned the title across three IDs: `S199497470` (2006–2013), `S4210169297` (2014–2024), and `S5407042752` (2025–2026). Including all three ensures continuous 20-year coverage without historical gaps.
   - `interspeech`: `S4393918409` contains 18,489 works with stable ~1,000 papers/year. Resolves the severe underrepresentation of speech processing faculty in ECERankings.

3. **Photonics (`ofc`)**:
   - `S4306420648` contains 24,416 works. Flagship optical communications conference co-sponsored by IEEE Photonics Society and Optica.

4. **Devices (`jmems`)**:
   - `S4210187724` contains 4,684 works spanning 1992–2026 with consistent ~120–160 papers/year. Accurately represents MEMS, micro-transducers, and sensor researchers.

## Testing and Verification
- Unit test suite: `python3 -m unittest discover tests/` passes 74/74 tests.
