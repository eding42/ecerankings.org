# Acronym-collision fix report

- examined: 230
- kept: 223
- proposed: 4
- ambiguous: 3

## Fixes

- `Department of Electrical Engineering, Information Technology University (ITU), Lahore`
  - Istanbul Technical University -> Information Technology University (full name in raw string (33 chars))
- `Department of Electrical Engineering, Information Technology University (ITU), Lahore, Pakistan`
  - Istanbul Technical University -> Information Technology University (full name in raw string (33 chars))
- `Educational Testing Service (ETS), San Francisco, CA, USA`
  - École de Technologie Supérieure -> Educational Testing Service (full name in raw string (27 chars))
- `General Motors R&D (GM), Warren, MI, USA`
  - GeoModelling Solutions (Switzerland) -> General Motors (United States) (country evidence ['US'])

## Ambiguous (needs adjudication)

- `GM` — now: GeoModelling Solutions (Switzerland); candidates: ['General Motors (India)', 'General Motors (Germany)', 'General Motors (United States)', 'GeoModelling Solutions (Switzerland)'] (acronym only, no name/country evidence)
- `ITU` — now: Istanbul Technical University; candidates: ['Istanbul Technical University', 'International Technological University', 'International Telecommunication Union', 'Information Technology University'] (acronym only, no name/country evidence)
- `Koala Electronics s.r.l, Via A. Palladio, 11 Tavagnacco (UD), Italy` — now: Universidad del Desarrollo; candidates: ['University of Dubai', 'University of Dallas', 'University of Djibouti', 'Universidad Distrital Francisco José de Caldas', 'University of Delaware', 'Universidad del Desarrollo'] (raw country ['IT'] matches no acronym owner)
