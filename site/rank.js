// Pure ranking, filter, and URL-state logic. No DOM access, so it can be
// exercised from Node (see site/tests/) as well as the browser.

// UN M49-style continents, with the Americas split into Northern America and
// Latin America. Codes not listed fall under "World" only.
const REGION_CODES = {
  'northern-america': 'US CA BM GL PM',
  'latin-america':
    'MX GT BZ SV HN NI CR PA CU DO HT JM TT BS BB PR AG DM GD KN LC VC CW AW BQ SX VG VI KY TC MS GP MQ ' +
    'BL MF AI AR BO BR CL CO EC GY PY PE SR UY VE GF FK',
  europe:
    'AL AD AT BY BE BA BG HR CY CZ DK EE FO FI FR DE GI GR GG HU IS IE IM IT JE XK LV LI LT LU MT MD MC ' +
    'ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB VA AX SJ',
  asia:
    'AF AM AZ BH BD BT BN KH CN GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY AM NP KP OM PK PS ' +
    'PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE',
  africa:
    'DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR ' +
    'MU YT MA MZ NA NE NG RE RW SH ST SN SC SL SO ZA SS SD TZ TG TN UG EH ZM ZW',
  oceania: 'AU NZ FJ PG SB VU NC PF WS TO KI FM MH NR PW TV GU MP AS CK NU NF',
};

export const REGIONS = [
  { id: 'world', label: 'World' },
  { id: 'northern-america', label: 'North America (US & Canada)' },
  { id: 'latin-america', label: 'Latin America & Caribbean' },
  { id: 'europe', label: 'Europe' },
  { id: 'asia', label: 'Asia' },
  { id: 'africa', label: 'Africa' },
  { id: 'oceania', label: 'Oceania' },
];

const REGION_SETS = Object.fromEntries(
  Object.entries(REGION_CODES).map(([k, v]) => [k, new Set(v.split(' '))]),
);

// region is 'world', a REGIONS id, or a two-letter country code.
export function regionMatches(region, country) {
  if (!region || region === 'world') return true;
  if (!country) return false;
  const set = REGION_SETS[region];
  if (set) return set.has(country);
  return country === region;
}

export function isValidRegion(region) {
  return region === 'world' || region in REGION_SETS || /^[A-Z]{2}$/.test(region);
}

// Area registry in file order. registry = parsed data/areas.json.
export function listAreas(registry) {
  return Object.entries(registry.areas).map(([id, a]) => ({
    id,
    name: a.name,
    cluster: a.cluster || 'Other',
    defaultOn: a.default_on === true,
    venues: a.venues || [],
  }));
}

export function defaultAreaIds(areas) {
  return areas.filter((a) => a.defaultOn).map((a) => a.id);
}

/**
 * Rank institutions.
 *
 * Per selected area, an institution's count is the sum of adjusted counts over
 * the inclusive year range. Score = exp(mean over ALL selected areas of
 * log1p(count)) - 1, i.e. the geometric mean of (1 + count) minus one, with
 * zero-count areas included in the mean. Institutions with no credit in any
 * selected area are omitted.
 *
 * @param {{from:number,to:number,region:string,areas:string[]}} sel
 * @param {Map<string, Array<{i:string,n:string,y:number,p:number,a:number}>>} dataByArea
 * @param {Object<string,{name:string,country:string}>} institutions
 */
export function computeRankings(sel, dataByArea, institutions) {
  const areas = sel.areas;
  const k = areas.length;
  if (k === 0) return [];
  const stats = new Map();
  areas.forEach((area, idx) => {
    const rows = dataByArea.get(area);
    if (!rows) throw new Error(`Area data not loaded: ${area}`);
    for (const r of rows) {
      if (r.y < sel.from || r.y > sel.to) continue;
      let s = stats.get(r.i);
      if (!s) {
        s = { id: r.i, fallbackName: r.n, adj: new Float64Array(k), pubs: new Float64Array(k) };
        stats.set(r.i, s);
      }
      s.adj[idx] += r.a;
      s.pubs[idx] += r.p;
    }
  });

  const out = [];
  for (const s of stats.values()) {
    const meta = institutions[s.id];
    const country = (meta && meta.country) || '';
    if (!regionMatches(sel.region, country)) continue;
    let logSum = 0;
    let adjTotal = 0;
    let pubTotal = 0;
    let active = 0;
    for (let j = 0; j < k; j++) {
      logSum += Math.log1p(s.adj[j]);
      adjTotal += s.adj[j];
      pubTotal += s.pubs[j];
      if (s.adj[j] > 0) active++;
    }
    if (adjTotal <= 0) continue;
    out.push({
      id: s.id,
      name: (meta && meta.name) || s.fallbackName || s.id,
      country,
      score: Math.expm1(logSum / k),
      adjTotal,
      pubTotal,
      active,
      perArea: areas.map((a, j) => ({ area: a, adj: s.adj[j], pubs: s.pubs[j] })),
    });
  }

  // Deterministic order: score desc, then name, then OpenAlex id.
  out.sort(
    (x, y) =>
      y.score - x.score || x.name.localeCompare(y.name, 'en') || (x.id < y.id ? -1 : x.id > y.id ? 1 : 0),
  );

  // Competition ranking ("1, 2, 2, 4"); scores equal to 1e-9 relative share a rank.
  let prev = null;
  out.forEach((r, idx) => {
    if (prev && Math.abs(prev.score - r.score) <= 1e-9 * Math.max(1, Math.abs(r.score))) {
      r.rank = prev.rank;
      r.tied = true;
      prev.tied = true;
    } else {
      r.rank = idx + 1;
    }
    prev = r;
  });
  return out;
}

// Year extent across loaded area rows.
export function yearExtent(dataByArea) {
  let min = Infinity;
  let max = -Infinity;
  for (const rows of dataByArea.values()) {
    for (const r of rows) {
      if (r.y < min) min = r.y;
      if (r.y > max) max = r.y;
    }
  }
  return Number.isFinite(min) ? { min, max } : null;
}

// ---- URL state -----------------------------------------------------------
// Hash form: #from=2016&to=2025&region=europe&areas=circuits,eda&disabled_venues=circuits:isscc
// Keys equal to their defaults are omitted to keep shared links short.

export function encodeState(sel, defaults) {
  const p = new URLSearchParams();
  if (sel.from !== defaults.from) p.set('from', String(sel.from));
  if (sel.to !== defaults.to) p.set('to', String(sel.to));
  const defRegion = (defaults && defaults.region) || 'US';
  if (sel.region !== defRegion) p.set('region', sel.region);
  const a = [...sel.areas].sort().join(',');
  if (a !== [...defaults.areas].sort().join(',')) p.set('areas', a || 'none');
  if (sel.disabledVenues && sel.disabledVenues.length > 0) {
    p.set('disabled_venues', [...sel.disabledVenues].sort().join(','));
  }
  const s = p.toString().replace(/%2C/g, ',');
  return s ? `#${s}` : '';
}

export function decodeState(hash, defaults, knownAreaIds) {
  const p = new URLSearchParams((hash || '').replace(/^#/, ''));
  const known = new Set(knownAreaIds);
  const defRegion = (defaults && defaults.region) || 'US';
  const sel = {
    from: defaults.from,
    to: defaults.to,
    region: defRegion,
    areas: [...defaults.areas],
    disabledVenues: [],
  };
  const from = parseInt(p.get('from'), 10);
  const to = parseInt(p.get('to'), 10);
  // Bound untrusted URL values before the UI creates a year option per year.
  // Actual availability is subsequently determined from the loaded data.
  if (Number.isInteger(from) && from >= 1600 && from <= 2200) sel.from = from;
  if (Number.isInteger(to) && to >= 1600 && to <= 2200) sel.to = to;
  if (sel.from > sel.to) [sel.from, sel.to] = [sel.to, sel.from];
  const region = p.get('region');
  if (region && isValidRegion(region)) sel.region = region;
  const areas = p.get('areas');
  if (areas === 'none') sel.areas = [];
  else if (areas) {
    const ids = areas.split(',').filter((a) => known.has(a));
    if (ids.length) sel.areas = ids;
  }
  // Keep registry order so per-area columns are stable.
  sel.areas = knownAreaIds.filter((id) => sel.areas.includes(id));

  const dv = p.get('disabled_venues');
  if (dv) {
    sel.disabledVenues = dv
      .split(',')
      .map((x) => x.trim())
      .filter((x) => /^[a-z0-9_-]+:[a-z0-9_-]+$/.test(x));
  }
  return sel;
}

export function clampYears(sel, extent) {
  if (!extent) return sel;
  const c = (y) => Math.min(extent.max, Math.max(extent.min, y));
  return { ...sel, from: c(sel.from), to: c(sel.to) };
}

// ---- CSV -----------------------------------------------------------------

function csvCell(v) {
  const s = String(v ?? '');
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function rankingsToCsv(rows, areaIds) {
  const header = [
    'rank', 'institution', 'openalex_id', 'country', 'score', 'adjusted_count_total',
    'papers_total', 'areas_with_credit', ...areaIds.map((a) => `adj_${a}`),
  ];
  const lines = [header.join(',')];
  for (const r of rows) {
    lines.push(
      [
        r.rank, r.name, r.id, r.country, r.score.toFixed(4), r.adjTotal.toFixed(4), Math.round(r.pubTotal),
        r.active, ...r.perArea.map((x) => x.adj.toFixed(4)),
      ].map(csvCell).join(','),
    );
  }
  return lines.join('\r\n') + '\r\n';
}
