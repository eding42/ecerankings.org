// ECERankings front end. Plain ES module, no build step.
// Ranking math and URL state live in rank.js; this file owns fetching and DOM.

import {
  REGIONS, listAreas, defaultAreaIds, computeRankings, yearExtent, regionMatches,
  encodeState, decodeState, rankingsToCsv, shortVenueName, areaRanks, searchRows,
} from './rank.js?v=compare5';
import { computeAnnualRanks, institutionHistory, renderRankHistory } from './rank-history.js';
import { renderComparison, compareSchools, ALL_AREAS } from './comparison.js?v=compare5';
import { createYearStrip, denseStart } from './year-strip.js?v=compare5';

const PAGE_SIZE = 100;
const COMPARE_MAX = 4;
const shortId = (id) => id.replace('https://openalex.org/', '');
const fullId = (id) => (id.startsWith('https://openalex.org/') ? id : `https://openalex.org/${id}`);
const CURRENT_YEAR = new Date().getFullYear();

// Caveat shown beside an area that is off by default.
const AREA_NOTES = {
  ml: 'Coverage not fully verified.',
};

const app = {
  areas: [],          // [{id, name, cluster, defaultOn, venues}] in registry order
  areaById: new Map(),
  institutions: {},
  data: new Map(),    // area id -> rows, only after a successful load
  venueData: new Map(), // "area:venue" -> rows
  pending: new Map(), // area id -> in-flight promise (dedupes concurrent fetches)
  pendingVenue: new Map(), // "area:venue" -> in-flight promise
  defaults: null,     // {from, to, region, areas, disabledVenues}
  sel: null,          // live selection {from, to, region, areas, disabledVenues}
  latestComplete: CURRENT_YEAR - 1,
  extent: null,       // {min, max} over loaded area files
  runId: 0,
  result: null,       // {sel, rows} for the last completed run
  shown: PAGE_SIZE,
  query: '',
  expanded: new Set(),
  openVenues: new Set(), // set of area ids with open venue dropdown
  lastHash: null,
  revealOpen: false,  // scroll to linked expanded rows once their data loads
  compare: { ids: [], mode: 'rankings', year: null, area: null, showAll: false, playing: false, playTimer: null },
  yearStrip: null,    // main page strip, created on first use
  compareStrip: null, // {el, strip} for the strip inside the comparison panel
};

const $ = (id) => (document.getElementById ? document.getElementById(id) : null);
const fmt1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmt2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
let countryNames = null;
try { countryNames = new Intl.DisplayNames(['en'], { type: 'region' }); } catch { /* old browser */ }
const countryName = (cc) => {
  if (!cc) return '';
  try { return (countryNames && countryNames.of(cc)) || cc; } catch { return cc; }
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

const isPartialYear = (y) => y > app.latestComplete;

// ---- Fetching --------------------------------------------------------------

async function fetchJson(url) {
  let res;
  try {
    res = await fetch(url);
  } catch (err) {
    throw new Error(`${url}: network error`);
  }
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  try {
    return await res.json();
  } catch {
    throw new Error(`${url}: not valid JSON`);
  }
}

function loadArea(id) {
  if (app.data.has(id)) return Promise.resolve(app.data.get(id));
  let p = app.pending.get(id);
  if (!p) {
    p = fetchJson(`data/${encodeURIComponent(id)}.json`)
      .then((rows) => {
        if (!Array.isArray(rows)) throw new Error(`data/${id}.json: expected an array`);
        app.data.set(id, rows);
        return rows;
      })
      .finally(() => app.pending.delete(id)); // failures are retried on the next run
    app.pending.set(id, p);
  }
  return p;
}

function loadVenue(areaId, venueKey) {
  const cacheKey = `${areaId}:${venueKey}`;
  if (app.venueData.has(cacheKey)) return Promise.resolve(app.venueData.get(cacheKey));
  let p = app.pendingVenue.get(cacheKey);
  if (!p) {
    p = fetchJson(`data/${encodeURIComponent(areaId)}/${encodeURIComponent(venueKey)}.json`)
      .then((rows) => {
        if (!Array.isArray(rows)) throw new Error(`data/${areaId}/${venueKey}.json: expected an array`);
        app.venueData.set(cacheKey, rows);
        return rows;
      })
      .finally(() => app.pendingVenue.delete(cacheKey));
    app.pendingVenue.set(cacheKey, p);
  }
  return p;
}

function getDisabledVenuesForArea(areaId, sel = app.sel) {
  const set = new Set();
  const prefix = `${areaId}:`;
  for (const item of (sel?.disabledVenues || [])) {
    if (item.startsWith(prefix)) {
      set.add(item.slice(prefix.length));
    }
  }
  return set;
}

async function loadAreaData(areaId, sel = app.sel) {
  const disabledSet = getDisabledVenuesForArea(areaId, sel);
  const area = app.areaById.get(areaId);
  const venues = (area && area.venues) || [];

  if (venues.length === 0 || disabledSet.size === 0) {
    return await loadArea(areaId);
  }

  const activeVenues = venues.filter((v) => !disabledSet.has(v.key));
  if (activeVenues.length === 0) return [];

  const rowsList = await Promise.all(activeVenues.map((v) => loadVenue(areaId, v.key)));
  return rowsList.flat();
}

// Optional build manifest. Absent is normal; only well-formed fields are used.
async function loadManifest() {
  try {
    const res = await fetch('data/manifest.json', { cache: 'no-cache' });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

// ---- Init ------------------------------------------------------------------

async function init() {
  bindStaticEvents();
  let registry;
  try {
    const [reg, inst, manifest] = await Promise.all([
      fetchJson('data/areas.json'),
      fetchJson('data/institutions.json'),
      loadManifest(),
    ]);
    if (!reg || typeof reg.areas !== 'object') throw new Error('data/areas.json: missing "areas"');
    registry = reg;
    app.institutions = inst || {};
    applyManifest(manifest);
  } catch (err) {
    showFatal(`Could not load site data (${err.message}).`);
    return;
  }

  app.areas = listAreas(registry);
  app.areas.forEach((a) => app.areaById.set(a.id, a));
  app.defaults = {
    from: app.latestComplete - 9,
    to: app.latestComplete,
    region: 'US',
    areas: defaultAreaIds(app.areas),
    disabledVenues: [],
  };
  app.sel = readHash();
  // index.html ships with the default ranking; drop it for any other selection.
  if (encodeState(app.sel, app.defaults)) $('ranking-body').innerHTML = '';
  readComparisonHash();
  readOpenHash();

  renderRegionOptions();
  renderAreaGroups();
  renderYearOptions();
  syncControls();
  ['region', 'year-from', 'year-to'].forEach((id) => { $(id).disabled = false; });
  update();
}

function applyManifest(m) {
  if (!m || typeof m !== 'object') return;
  const y = Number(m.latest_complete_year);
  if (Number.isInteger(y) && y > 1900 && y <= CURRENT_YEAR) app.latestComplete = y;
  const stamp = [m.generated_at, m.generated, m.built_at].find(
    (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}/.test(v),
  );
  if (stamp) {
    const date = new Date(`${stamp.slice(0, 10)}T00:00:00Z`);
    $('data-stamp').textContent = `Updated ${date.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' })}`;
  }
}

function readHash() {
  return decodeState(location.hash, app.defaults, app.areas.map((a) => a.id));
}

function writeHash(sel) {
  const params = new URLSearchParams(encodeState(sel, app.defaults).replace(/^#/, ''));
  if (app.expanded.size) params.set('open', [...app.expanded].map(shortId).join(','));
  if (app.compare.ids.length) params.set('compare', app.compare.ids.map(shortId).join(','));
  if (app.compare.mode === 'compare') params.set('view', 'compare');
  if (app.compare.ids.length >= 2 && app.compare.area) params.set('compare-area', app.compare.area);
  if (app.compare.ids.length >= 2 && app.compare.year !== null) params.set('compare-year', String(app.compare.year));
  const hash = params.size ? `#${params.toString().replace(/%2C/g, ',')}` : '';
  app.lastHash = hash;
  if (hash !== location.hash || location.href.endsWith('#')) {
    history.replaceState(null, '', location.pathname + location.search + hash);
  }
}

// ---- Controls --------------------------------------------------------------

function renderRegionOptions() {
  const counts = new Map();
  for (const meta of Object.values(app.institutions)) {
    if (meta.country) counts.set(meta.country, (counts.get(meta.country) || 0) + 1);
  }
  const countries = [...counts.keys()]
    .map((cc) => ({ cc, name: countryName(cc) }))
    .sort((a, b) => a.name.localeCompare(b.name, 'en'));
  const sel = $('region');
  sel.innerHTML =
    `<option value="US">United States</option>` +
    `<option value="world">World</option>` +
    `<optgroup label="Regions">${REGIONS.filter((r) => r.id !== 'world')
      .map((r) => `<option value="${r.id}">${esc(r.label)}</option>`).join('')}</optgroup>` +
    `<optgroup label="Countries">${countries
      .map((c) => `<option value="${c.cc}">${esc(c.name)}</option>`).join('')}</optgroup>`;
  // A region from a shared link that no institution has still needs an option.
  if (![...sel.options].some((o) => o.value === app.sel.region)) {
    sel.insertAdjacentHTML('beforeend', `<option value="${esc(app.sel.region)}">${esc(countryName(app.sel.region))}</option>`);
  }
}

function renderYearOptions() {
  const ext = app.extent || { min: app.defaults.from, max: Math.max(app.defaults.to, CURRENT_YEAR) };
  const lo = Math.min(ext.min, app.sel.from);
  const hi = Math.max(ext.max, app.sel.to);
  const key = `${lo}-${hi}-${app.latestComplete}`;
  if (renderYearOptions.key === key) return;
  renderYearOptions.key = key;
  let html = '';
  for (let y = hi; y >= lo; y--) {
    html += `<option value="${y}">${y}${isPartialYear(y) ? ' (partial)' : ''}</option>`;
  }
  $('year-from').innerHTML = html;
  $('year-to').innerHTML = html;
  $('year-from').value = String(app.sel.from);
  $('year-to').value = String(app.sel.to);
}

function renderAreaGroups() {
  const clusters = new Map();
  for (const a of app.areas) {
    if (!clusters.has(a.cluster)) clusters.set(a.cluster, []);
    clusters.get(a.cluster).push(a);
  }
  let html = '';
  let gi = 0;
  const disabled = new Set(app.sel?.disabledVenues || []);

  for (const [cluster, areas] of clusters) {
    gi++;
    html += `<fieldset class="area-group"><legend>${esc(cluster)}` +
      ` <span class="group-actions"><button type="button" class="link" data-group="${gi}" data-on="1" aria-label="Select all ${esc(cluster)} areas">all</button>` +
      ` · <button type="button" class="link" data-group="${gi}" data-on="0" aria-label="Clear all ${esc(cluster)} areas">none</button></span></legend>`;
    for (const a of areas) {
      const note = !a.defaultOn ? (AREA_NOTES[a.id] || '') : '';
      const noteId = note ? ` aria-describedby="note-${esc(a.id)}"` : '';
      const venues = a.venues || [];
      const isOpen = app.openVenues.has(a.id);
      const vListId = `venues-${esc(a.id)}`;

      html += `<div class="area-row${a.defaultOn ? '' : ' off-default'}">` +
        `<div class="area-header">` +
        `<input type="checkbox" id="area-${esc(a.id)}" value="${esc(a.id)}" data-group="${gi}"${noteId}>` +
        `<label for="area-${esc(a.id)}">${esc(a.name)}</label>`;

      if (venues.length > 0) {
        html += `<button type="button" class="area-venues-toggle" data-area-toggle="${esc(a.id)}" ` +
          `aria-expanded="${isOpen}" aria-controls="${vListId}" title="Toggle journals & conferences for ${esc(a.name)}" ` +
          `aria-label="Toggle journals & conferences for ${esc(a.name)}">${isOpen ? '▾' : '▸'}</button>`;
      }
      html += `</div>`;

      if (venues.length > 0 && isOpen) {
        html += `<ul class="area-venues-list" id="${vListId}">` +
          venues.map((v) => {
            const full = v.display || v.key || '';
            const isChecked = !disabled.has(`${a.id}:${v.key}`);
            return `<li class="venue-row">` +
              `<input type="checkbox" id="venue-${esc(a.id)}-${esc(v.key)}" ` +
              `data-area="${esc(a.id)}" data-venue="${esc(v.key)}"` +
              `${isChecked ? ' checked' : ''}>` +
              `<label for="venue-${esc(a.id)}-${esc(v.key)}" title="${esc(full)}">${esc(shortVenueName(full))}</label>` +
              `</li>`;
          }).join('') +
          `</ul>`;
      }

      if (note) {
        html += `<p class="area-note" id="note-${esc(a.id)}">${esc(note)}</p>`;
      }
      html += `</div>`;
    }
    html += `</fieldset>`;
  }
  $('area-groups').innerHTML = html;
}

function syncControls() {
  const s = app.sel;
  $('region').value = s.region;
  renderYearOptions();
  $('year-from').value = String(s.from);
  $('year-to').value = String(s.to);
  const on = new Set(s.areas);
  const disabled = new Set(s.disabledVenues || []);

  for (const a of app.areas) {
    const areaCb = $(`area-${a.id}`);
    const isAreaSelected = on.has(a.id);
    const venues = a.venues || [];

    for (const v of venues) {
      const vCb = $(`venue-${a.id}-${v.key}`);
      if (vCb) {
        vCb.checked = isAreaSelected ? !disabled.has(`${a.id}:${v.key}`) : false;
      }
    }

    if (areaCb) {
      if (!isAreaSelected) {
        areaCb.checked = false;
        areaCb.indeterminate = false;
      } else {
        const disabledCount = venues.filter((v) => disabled.has(`${a.id}:${v.key}`)).length;
        if (venues.length > 0 && disabledCount > 0 && disabledCount < venues.length) {
          areaCb.checked = true;
          areaCb.indeterminate = true;
        } else {
          areaCb.checked = true;
          areaCb.indeterminate = false;
        }
      }
    }
  }

  const countEl = $('area-count');
  if (countEl) countEl.textContent = `${s.areas.length} of ${app.areas.length}`;
}

function setAreas(ids) {
  const on = new Set(ids);
  const disabled = new Set(app.sel.disabledVenues || []);
  for (const a of app.areas) {
    if (on.has(a.id) && !app.sel.areas.includes(a.id)) {
      for (const item of [...disabled]) {
        if (item.startsWith(`${a.id}:`)) disabled.delete(item);
      }
    }
  }
  app.sel.areas = app.areas.map((a) => a.id).filter((id) => on.has(id));
  // Unchecked areas must not leave venue exclusions behind: they would leak
  // into the URL hash for an area that is no longer selected.
  const activeAreaSet = new Set(app.sel.areas);
  app.sel.disabledVenues = [...disabled].filter((item) => activeAreaSet.has(item.split(':')[0]));
  syncControls();
  update();
}

function toggleVenue(areaId, venueKey, isChecked) {
  const item = `${areaId}:${venueKey}`;
  const disabled = new Set(app.sel.disabledVenues || []);
  if (isChecked) {
    disabled.delete(item);
  } else {
    disabled.add(item);
  }
  app.sel.disabledVenues = [...disabled];

  const area = app.areaById.get(areaId);
  const venues = (area && area.venues) || [];
  const areaSet = new Set(app.sel.areas);

  const activeCount = venues.filter((v) => !disabled.has(`${areaId}:${v.key}`)).length;
  if (activeCount === 0) {
    areaSet.delete(areaId);
  } else {
    areaSet.add(areaId);
  }

  app.sel.areas = app.areas.map((a) => a.id).filter((id) => areaSet.has(id));
  syncControls();
  update();
}

function bindStaticEvents() {
  bindComparisonEvents();
  $('filters').addEventListener('submit', (e) => {
    e.preventDefault();
    // Dismiss a phone's search keyboard so the matching institutions are visible.
    $('search').blur();
  });
  $('region').addEventListener('change', (e) => {
    app.sel.region = e.target.value;
    update();
  });
  $('year-from').addEventListener('change', (e) => {
    app.sel.from = Number(e.target.value);
    if (app.sel.from > app.sel.to) app.sel.to = app.sel.from;
    syncControls();
    update();
  });
  $('year-to').addEventListener('change', (e) => {
    app.sel.to = Number(e.target.value);
    if (app.sel.to < app.sel.from) app.sel.from = app.sel.to;
    syncControls();
    update();
  });

  $('area-groups').addEventListener('change', (e) => {
    if (e.target.type !== 'checkbox') return;
    if (e.target.dataset.venue) {
      toggleVenue(e.target.dataset.area, e.target.dataset.venue, e.target.checked);
      return;
    }
    const on = new Set(app.sel.areas);
    if (e.target.checked) on.add(e.target.value); else on.delete(e.target.value);
    setAreas([...on]);
  });

  $('area-groups').addEventListener('click', (e) => {
    const toggle = e.target.closest('button[data-area-toggle]');
    if (toggle) {
      const areaId = toggle.dataset.areaToggle;
      if (app.openVenues.has(areaId)) {
        app.openVenues.delete(areaId);
      } else {
        app.openVenues.add(areaId);
      }
      renderAreaGroups();
      syncControls();
      // Rendering replaces the disclosure button; retain keyboard/touch focus.
      $(`area-${areaId}`).closest('.area-header').querySelector('button').focus({ preventScroll: true });
      return;
    }

    const b = e.target.closest('button[data-group]');
    if (!b) return;
    const on = new Set(app.sel.areas);
    const disabled = new Set(app.sel.disabledVenues || []);
    for (const cb of $('area-groups').querySelectorAll(`input[data-group="${b.dataset.group}"]`)) {
      if (b.dataset.on === '1') {
        on.add(cb.value);
        for (const item of [...disabled]) {
          if (item.startsWith(`${cb.value}:`)) disabled.delete(item);
        }
      } else {
        on.delete(cb.value);
      }
    }
    app.sel.disabledVenues = [...disabled];
    setAreas([...on]);
  });

  document.querySelector('.area-actions').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-select]');
    if (!b || !app.areas.length) return;
    const mode = b.dataset.select;
    app.sel.disabledVenues = [];
    setAreas(mode === 'all' ? app.areas.map((a) => a.id) : mode === 'none' ? [] : app.defaults.areas);
  });

  $('search').addEventListener('input', (e) => {
    app.query = e.target.value.trim().toLowerCase();
    app.shown = PAGE_SIZE;
    renderTable();
  });
  $('show-more')?.addEventListener('click', () => { app.shown += PAGE_SIZE; renderTable(); });
  $('show-all')?.addEventListener('click', () => { app.shown = Infinity; renderTable(); });
  $('export').addEventListener('click', exportCsv);
  $('areas-done').addEventListener('click', () => {
    $('areas-panel').open = false;
    const summary = $('areas-panel').querySelector('summary');
    summary.focus({ preventScroll: true });
    summary.scrollIntoView({ block: 'start' });
  });

  $('ranking-body').addEventListener('click', (e) => {
    const compare = e.target.closest('button[data-compare-id]');
    if (compare) {
      const id = compare.dataset.compareId;
      toggleComparisonSchool(id);
      const again = $('ranking-body').querySelector(`button[data-compare-id="${CSS.escape(id)}"]`);
      if (again) again.focus();
      return;
    }
    const b = e.target.closest('button.inst');
    if (!b) return;
    const id = b.dataset.id;
    if (app.expanded.has(id)) app.expanded.delete(id); else app.expanded.add(id);
    renderTable();
    writeHash(app.result ? app.result.sel : app.sel);
    const again = $('ranking-body').querySelector(`button.inst[data-id="${CSS.escape(id)}"]`);
    if (again) again.focus();
  });

  window.addEventListener('hashchange', () => {
    if (!app.defaults || location.hash === app.lastHash) return;
    app.sel = readHash();
    readComparisonHash();
    readOpenHash();
    syncControls();
    if ([...$('region').options].every((o) => o.value !== app.sel.region)) renderRegionOptions();
    $('region').value = app.sel.region;
    update();
  });

  // Area list is open beside the table on wide screens, collapsed on narrow ones.
  const wide = window.matchMedia('(min-width: 900px)');
  const applyWidth = () => { $('areas-panel').open = wide.matches; };
  applyWidth();
  wide.addEventListener('change', applyWidth);

  // Match styles.css: hidden phone columns must not leave phantom table columns
  // when an expanded detail row spans the table, including after rotation.
  const compact = window.matchMedia('(max-width: 600px)');
  compact.addEventListener('change', () => {
    document.querySelectorAll('tr.detail > td').forEach((cell) => {
      cell.colSpan = compact.matches ? 3 : 6;
    });
  });
}

// ---- Update cycle ----------------------------------------------------------

async function update() {
  stopComparisonPlayback();
  // Snapshot the selection: controls may change while files load.
  const sel = {
    ...app.sel,
    areas: [...app.sel.areas],
    disabledVenues: [...(app.sel.disabledVenues || [])],
  };
  const run = ++app.runId;
  writeHash(sel);
  const countEl = $('area-count');
  if (countEl) countEl.textContent = `${sel.areas.length} of ${app.areas.length}`;
  hideError();

  if (sel.areas.length === 0) {
    app.result = null;
    setBusy(false);
    setStatus('Select a research area.');
    clearTable();
    hideYearStrip();
    updateComparison();
    return;
  }

  setStatus('Loading…');
  setBusy(true);

  try {
    const settled = await Promise.allSettled(sel.areas.map((id) => loadAreaData(id, sel)));
    // A newer selection owns the busy state from here on.
    if (run !== app.runId) return;

    const failed = sel.areas
      .map((id, i) => ({ id, r: settled[i] }))
      .filter((x) => x.r.status === 'rejected');
    if (failed.length) {
      app.result = null;
      clearTable();
      hideYearStrip();
      updateComparison();
      showAreaError(failed);
      return;
    }

    const activeData = new Map();
    sel.areas.forEach((id, i) => {
      activeData.set(id, settled[i].value);
    });

    const ext = yearExtent(activeData);
    if (ext && (!app.extent || ext.min !== app.extent.min || ext.max !== app.extent.max)) {
      app.extent = ext;
      renderYearOptions();
    }

    const rows = computeRankings(sel, activeData, app.institutions);
    app.result = { sel, rows, data: activeData, annualRanks: null };
    app.shown = PAGE_SIZE;
    renderYearStrip(sel, activeData);
    revealOpenRows();
    renderTable();
    updateComparison();
    writeHash(sel);
    if (app.revealOpen) {
      app.revealOpen = false;
      const first = document.querySelector?.('tr.detail');
      first?.previousElementSibling?.scrollIntoView({ block: 'center' });
    }
  } finally {
    if (run === app.runId) setBusy(false);
  }
}

// ---- Year strip ------------------------------------------------------------

function hideYearStrip() {
  const root = $('year-strip');
  if (root) root.hidden = true;
}

// Bars are the adjusted count per year for the selected areas and region.
function renderYearStrip(sel, data) {
  const root = $('year-strip');
  if (!root) return;
  if (!app.yearStrip) {
    app.yearStrip = createYearStrip(root, {
      label: 'Publication years',
      onPreview: (from, to) => {
        $('year-from').value = String(from);
        $('year-to').value = String(to);
      },
      onChange: (from, to) => {
        app.sel.from = from;
        app.sel.to = to;
        syncControls();
        update();
      },
    });
  }
  const inRegion = new Map();
  const totals = new Map();
  for (const rows of data.values()) {
    for (const r of rows) {
      let ok = inRegion.get(r.i);
      if (ok === undefined) {
        ok = regionMatches(sel.region, app.institutions[r.i]?.country || '');
        inRegion.set(r.i, ok);
      }
      if (ok) totals.set(r.y, (totals.get(r.y) || 0) + r.a);
    }
  }
  const first = denseStart(totals, sel.from);
  const last = Math.max(sel.to, app.extent ? app.extent.max : sel.to);
  const years = [];
  for (let y = first; y <= last; y++) {
    const total = totals.get(y) || 0;
    years.push({
      year: y, values: [total], partial: isPartialYear(y),
      text: `${y} · adjusted count ${fmtInt.format(total)}${isPartialYear(y) ? ' · partial year' : ''}`,
    });
  }
  root.hidden = false;
  app.yearStrip.setData(years);
  app.yearStrip.setRange(sel.from, sel.to);
}

// The comparison panel's strip picks one year inside the selected range.
// Bars are each school's adjusted count over all selected areas.
function syncCompareStrip(panel) {
  const el = panel.querySelector('#compare-year');
  if (!el) { app.compareStrip = null; return; }
  const { sel, data } = app.result;
  if (!app.compareStrip || app.compareStrip.el !== el) {
    const setYear = (year) => {
      stopComparisonPlayback();
      app.compare.year = year;
      updateComparison(true);
    };
    const strip = createYearStrip(el, {
      mode: 'single',
      label: 'Year',
      onPreview: setYear,
      onChange: (year) => { setYear(year); writeHash(app.sel); },
    });
    const areas = compareSchools(data, sel.areas, app.compare.ids, sel.from, sel.to);
    const years = [];
    for (let y = sel.from; y <= sel.to; y++) {
      const values = app.compare.ids.map((_, k) => areas.reduce((sum, a) => sum + a.years[y - sel.from].values[k], 0));
      years.push({ year: y, values, partial: isPartialYear(y), text: `${y} · all areas ${values.map((v) => fmt1.format(v)).join(' · ')}` });
    }
    strip.setData(years);
    app.compareStrip = { el, strip };
  }
  app.compareStrip.strip.setRange(app.compare.year);
}

function setBusy(on) {
  $('ranking-table').setAttribute('aria-busy', on ? 'true' : 'false');
  $('ranking-table').classList.toggle('stale', on);
  $('export').disabled = on || !app.result;
  $('comparison-view').setAttribute('aria-busy', on ? 'true' : 'false');
}

function setStatus(text) { $('status').textContent = text; }

function clearTable() {
  $('ranking-body').innerHTML = '';
  $('pager').hidden = true;
  $('export').disabled = true;
}

function hideError() { $('error').hidden = true; $('error').innerHTML = ''; }

function showAreaError(failed) {
  const names = failed.map((f) => `${esc(app.areaById.get(f.id)?.name || f.id)} <span class="muted">(${esc(f.r.reason?.message || 'unknown error')})</span>`);
  setStatus('Rankings unavailable.');
  $('error').innerHTML =
    `<p><strong>Could not load data for ${failed.length === 1 ? 'one selected area' : `${failed.length} selected areas`}:</strong></p>` +
    `<ul>${names.map((n) => `<li>${n}</li>`).join('')}</ul>` +
    `<p><button type="button" id="retry">Try again</button></p>`;
  $('error').hidden = false;
  $('retry').addEventListener('click', () => update());
}

function showFatal(message) {
  setStatus('');
  $('error').innerHTML = `<p><strong>${esc(message)}</strong></p><p><button type="button" onclick="location.reload()">Reload</button></p>`;
  $('error').hidden = false;
  $('area-groups').innerHTML = '<p class="muted">Areas unavailable.</p>';
}

// ---- Table -----------------------------------------------------------------

function filteredRows() {
  if (!app.result) return [];
  const q = app.query;
  return searchRows(app.result.rows, q);
}

function renderTable() {
  if (!app.result) return;
  const { sel, rows: all } = app.result;
  if (sel.from !== sel.to) scheduleTrends(app.result);
  const rows = filteredRows();
  const visible = rows.slice(0, app.shown);
  let status;
  if (!all.length) status = 'No institutions with credit.';
  else if (app.query) status = `${fmtInt.format(rows.length)} of ${fmtInt.format(all.length)} institutions`;
  else status = `${fmtInt.format(all.length)} institutions`;
  setStatus(status);

  let html = '';
  for (const r of visible) {
    const open = app.expanded.has(r.id);
    const did = `detail-${r.id.replace(/\\W/g, '')}`;
    html += `<tr class="inst-row${open ? ' open' : ''}">` +
      `<td class="num rank">${r.tied ? `<span title="Tied">${r.rank}</span>` : r.rank}</td>` +
      `<td class="name"><div class="inst-name-line"><span class="inst-name-main"><button type="button" class="inst" data-id="${esc(r.id)}" aria-expanded="${open}" aria-controls="${did}">` +
      `<span class="tri" aria-hidden="true">${open ? '▾' : '▸'}</span>${esc(r.name)}</button>` +
      (r.country ? ` <abbr class="cc" title="${esc(countryName(r.country))}">${esc(r.country)}</abbr>` : '') +
      `</span>${open ? comparisonAction(r) : ''}</div></td>` +
      `<td class="num score">${fmt2.format(r.score)}</td>` +
      `<td class="num opt">${fmt1.format(r.adjTotal)}</td>` +
      `<td class="num opt">${fmtInt.format(r.pubTotal)}</td>` +
      `<td class="num opt trend-cell">${trendCell(r, app.result)}</td></tr>`;
    if (open) html += detailRow(r, did);
  }
  $('ranking-body').innerHTML = html;
  $('export').disabled = !all.length;

  const left = rows.length - visible.length;
  $('pager').hidden = left <= 0;
  if (left > 0) {
    $('show-more').textContent = `Show ${fmtInt.format(Math.min(PAGE_SIZE, left))} more`;
    $('show-all').textContent = `Show all ${fmtInt.format(rows.length)}`;
  }
}

// Rank in each year of the range, under the same areas, venues and region.
function ensureAnnualRanks(result) {
  if (result.annualRanks) return;
  result.annualRanks = computeAnnualRanks({
    startYear: result.sel.from, endYear: result.sel.to,
    rankingsForYear: year => computeRankings(
      { ...result.sel, from: year, to: year }, result.data, app.institutions
    ),
    rankForResult: row => row.rank,
  });
}

// Yearly ranks take a pass over the data per year, so the table paints first
// and the trend column fills in afterwards.
function scheduleTrends(result) {
  if (result.annualRanks || result.trendsPending) return;
  result.trendsPending = true;
  setTimeout(() => {
    ensureAnnualRanks(result);
    if (app.result === result) renderTable();
  }, 0);
}

// Sparkline of yearly rank (up is better) and places moved, first year to last.
// Unfinished years are left out: their ranks move as papers are indexed.
function trendCell(r, result) {
  if (!result.annualRanks) return '';
  const history = institutionHistory(result.annualRanks, r.id).filter((h) => !isPartialYear(h.year));
  const points = history.filter((h) => h.rank !== null);
  if (history.length < 2 || points.length < 2) return '';
  const ranks = points.map((h) => h.rank);
  const best = Math.min(...ranks), worst = Math.max(...ranks);
  const W = 64, H = 20, pad = 3;
  const x = (year) => pad + ((year - history[0].year) / (history[history.length - 1].year - history[0].year)) * (W - 2 * pad);
  const y = (rank) => (worst === best ? H / 2 : pad + ((rank - best) / (worst - best)) * (H - 2 * pad));
  // Break the line across years with no credit instead of bridging them.
  let d = '';
  let pen = false;
  for (const h of history) {
    if (h.rank === null) { pen = false; continue; }
    d += `${pen ? 'L' : 'M'}${x(h.year).toFixed(1)},${y(h.rank).toFixed(1)}`;
    pen = true;
  }
  const first = history[0], last = history[history.length - 1];
  const end = points[points.length - 1];
  let delta = '';
  if (first.rank !== null && last.rank !== null) {
    const moved = first.rank - last.rank;
    delta = moved === 0
      ? '<span class="trend-delta">–</span>'
      : `<span class="trend-delta ${moved > 0 ? 'up' : 'down'}">${moved > 0 ? '▲' : '▼'}${fmtInt.format(Math.abs(moved))}</span>`;
  }
  const label = `Rank by year: ${history.map((h) => `${h.year} ${h.rank === null ? 'unranked' : `#${h.rank}`}`).join(', ')}`;
  return `<span class="trend" title="${esc(label)}"><svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(label)}">` +
    `<path d="${d}"/><circle cx="${x(end.year).toFixed(1)}" cy="${y(end.rank).toFixed(1)}" r="2.5"/></svg>${delta}</span>`;
}

function comparisonAction(row) {
  const selected = app.compare.ids.includes(row.id);
  const disabled = app.compare.ids.length >= COMPARE_MAX && !selected;
  const label = `${selected ? 'Remove' : 'Add'} ${row.name} ${selected ? 'from' : 'to'} comparison`;
  const icon = selected ? '<path d="m3 7 3 3 5-6"/>' : '<rect x="2" y="5" width="7" height="7" rx="1"/><path d="M5 5V2h7v7H9"/>';
  return `<button type="button" class="inst-compare${selected ? ' selected' : ''}" data-compare-id="${esc(row.id)}" aria-pressed="${selected}" aria-label="${esc(label)}" title="${disabled ? `Compare holds ${COMPARE_MAX} schools` : esc(label)}"${disabled ? ' disabled' : ''}><svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">${icon}</svg><span>${selected ? 'Added' : 'Compare'}</span></button>`;
}

function detailRow(r, did) {
  const columns = typeof matchMedia === 'function' && matchMedia('(max-width: 600px)').matches ? 3 : 6;
  const result = app.result;
  ensureAnnualRanks(result);
  const trend = renderRankHistory(
    institutionHistory(result.annualRanks, r.id), r.name, 'selected areas, venues and region'
  );
  if (!result.areaRanks) result.areaRanks = areaRanks(result.rows);
  const items = r.perArea
    .map((x, idx) => ({ ...x, idx, rank: result.areaRanks.get(x.area)?.get(r.id), name: app.areaById.get(x.area)?.name || x.area }))
    .sort((a, b) => b.adj - a.adj || a.idx - b.idx);
  const body = items.map((x) =>
    `<tr class="${x.adj === 0 ? 'zero' : ''}">` +
    `<td>${esc(x.name)}</td>` +
    `<td class="num">${x.rank ? `#${fmtInt.format(x.rank)}` : '—'}</td>` +
    `<td class="num">${fmt1.format(x.adj)}</td>` +
    `<td class="num">${fmtInt.format(x.pubs)}</td></tr>`,
  ).join('');
  return `<tr class="detail" id="${did}"><td colspan="${columns}">` +
    `${trend}` +
    `<dl class="institution-totals" aria-label="Institution totals">` +
    `<div><dt>Adjusted count</dt><dd>${fmt1.format(r.adjTotal)}</dd></div>` +
    `<div><dt>Papers</dt><dd>${fmtInt.format(r.pubTotal)}</dd></div></dl>` +
    `<table class="breakdown"><caption>Credit by research area</caption>` +
    `<thead><tr><th scope="col">Area</th><th scope="col" class="num">Rank</th><th scope="col" class="num">Adj. count</th><th scope="col" class="num">Papers</th></tr></thead>` +
    `<tbody>${body}</tbody></table></td></tr>`;
}

// ---- Comparison mode -------------------------------------------------------

function readComparisonHash() {
  const params = new URLSearchParams(location.hash.replace(/^#/, ''));
  const ids = (params.get('compare') || '').split(',').filter(Boolean)
    .map(fullId).filter(id => Object.hasOwn(app.institutions, id));
  app.compare.ids = [...new Set(ids)].slice(0, COMPARE_MAX);
  app.compare.mode = params.get('view') === 'compare' ? 'compare' : 'rankings';
  if (app.compare.mode !== 'compare') stopComparisonPlayback();
  const year = Number(params.get('compare-year'));
  app.compare.year = params.has('compare-year') && Number.isInteger(year) && year >= app.sel.from && year <= app.sel.to ? year : null;
  app.compare.area = app.sel.areas.includes(params.get('compare-area')) ? params.get('compare-area') : null;
}

function readOpenHash() {
  const params = new URLSearchParams(location.hash.replace(/^#/, ''));
  const ids = (params.get('open') || '').split(',').filter(Boolean)
    .map(fullId).filter(id => Object.hasOwn(app.institutions, id));
  app.expanded = new Set(ids);
  app.revealOpen = ids.length > 0;
}

// A shared link may open a school beyond the first page; show enough rows.
function revealOpenRows() {
  if (!app.revealOpen || !app.result) return;
  const rows = filteredRows();
  const last = Math.max(-1, ...rows.map((r, i) => (app.expanded.has(r.id) ? i : -1)));
  if (last >= 0) app.shown = Math.max(PAGE_SIZE, Math.ceil((last + 1) / PAGE_SIZE) * PAGE_SIZE);
}

function setComparisonMode(mode) {
  if (mode !== 'compare') stopComparisonPlayback();
  app.compare.mode = mode;
  updateComparison();
  if (mode === 'rankings') renderTable();
  writeHash(app.sel);
}

function toggleComparisonSchool(id) {
  stopComparisonPlayback();
  const ids = app.compare.ids;
  const index = ids.indexOf(id);
  if (index >= 0) ids.splice(index, 1);
  else if (ids.length < COMPARE_MAX && Object.hasOwn(app.institutions, id)) ids.push(id);
  renderTable();
  updateComparison();
  writeHash(app.sel);
}

function selectComparisonSchool(slot, id) {
  const ids = app.compare.ids;
  if (!id) ids.splice(slot, 1);
  else {
    const existing = ids.indexOf(id);
    if (existing >= 0 && slot < ids.length) { ids[existing] = ids[slot]; ids[slot] = id; }
    else if (existing < 0 && slot < ids.length) ids[slot] = id;
    else if (existing < 0 && ids.length < COMPARE_MAX) ids.push(id);
  }
  if (ids.length < 2) stopComparisonPlayback();
  renderTable();
  updateComparison();
  writeHash(app.sel);
  $(`compare-school-toggle-${Math.min(slot, ids.length - 1)}`)?.focus();
}

// Back to the whole period and all areas; the chosen schools stay.
function resetComparison() {
  stopComparisonPlayback();
  app.compare.year = null;
  app.compare.area = null;
  updateComparison();
  writeHash(app.sel);
  document.querySelector?.('[data-whole-period]')?.focus({ preventScroll: true });
}

function clearComparison() {
  stopComparisonPlayback();
  app.compare.ids = [];
  app.compare.year = null;
  app.compare.area = null;
  renderTable();
  updateComparison();
  writeHash(app.sel);
}

function renderComparisonSearchResults(slot, query) {
  const container = $(`compare-results-${slot}`);
  if (!container || !app.result) return;
  const currentId = app.compare.ids[slot];
  const ranked = app.result.rows.map(r => ({ id: r.id, name: r.name }));
  let candidates = searchRows(ranked, query || '').slice(0, query?.trim() ? 15 : 10);
  if (query?.trim() && candidates.length < 10) {
    // Institutions outside the current selection can still be compared.
    const seen = new Set(ranked.map(r => r.id));
    const rest = Object.entries(app.institutions).filter(([id]) => !seen.has(id)).map(([id, meta]) => ({ id, name: meta.name || id }));
    candidates = candidates.concat(searchRows(rest, query).slice(0, 15 - candidates.length));
  }
  if (!candidates.length) {
    container.innerHTML = `<div class="compare-search-empty">No institutions match “${esc(query)}”</div>`;
    return;
  }
  container.innerHTML = candidates.map(c => {
    const isCur = c.id === currentId, country = app.institutions[c.id]?.country || '';
    return `<button type="button" class="compare-search-item${isCur ? ' selected' : ''}" data-school-side="${slot}" data-select-school="${esc(c.id)}" role="option" aria-selected="${isCur}"><span class="compare-search-name">${esc(c.name)}</span>${country ? `<span class="compare-search-country">${esc(country)}</span>` : ''}</button>`;
  }).join('');
}

function bindComparisonEvents() {
  $('view-rankings').addEventListener('click', () => setComparisonMode('rankings'));
  $('view-compare').addEventListener('click', () => setComparisonMode('compare'));
  $('comparison-tray').addEventListener('click', e => {
    const remove = e.target.closest('[data-remove-school]');
    if (remove) toggleComparisonSchool(remove.dataset.removeSchool);
    if (e.target.closest('[data-open-comparison]')) setComparisonMode('compare');
    if (e.target.closest('[data-clear-comparison]')) clearComparison();
  });
  const panel = $('comparison-view');
  panel.addEventListener('input', e => {
    if (e.target.matches('.compare-search-input')) {
      const side = Number(e.target.dataset.schoolSide);
      renderComparisonSearchResults(side, e.target.value);
    }
  });
  panel.addEventListener('focusin', e => {
    if (e.target.matches('.compare-search-input')) {
      const side = Number(e.target.dataset.schoolSide);
      renderComparisonSearchResults(side, e.target.value);
    }
  });
  panel.addEventListener('click', e => {
    const reset = e.target.closest('[data-reset-comparison]');
    if (reset) { resetComparison(); return; }
    const item = e.target.closest('[data-select-school]');
    if (item) {
      const side = Number(item.dataset.schoolSide);
      const id = item.dataset.selectSchool;
      selectComparisonSchool(side, id);
      return;
    }
    if (e.target.closest('[data-play-years]')) {
      if (app.compare.playing) stopComparisonPlayback();
      else startComparisonPlayback();
      return;
    }
    if (e.target.closest('[data-show-areas]')) {
      app.compare.showAll = !app.compare.showAll;
      updateComparison(true);
      panel.querySelector('[data-show-areas]')?.focus({ preventScroll: true });
      return;
    }
    const remove = e.target.closest('[data-remove-school]');
    if (remove) { toggleComparisonSchool(remove.dataset.removeSchool); return; }
    const area = e.target.closest('[data-compare-area]');
    const year = e.target.closest('[data-compare-year]');
    if (area) app.compare.area = area.dataset.compareArea === ALL_AREAS ? null : area.dataset.compareArea;
    else if (year) { stopComparisonPlayback(); app.compare.year = Number(year.dataset.compareYear); }
    else if (e.target.closest('[data-whole-period]')) { stopComparisonPlayback(); app.compare.year = null; }
    else return;
    updateComparison(true);
    writeHash(app.sel);
    const selector = area ? `[data-compare-area="${CSS.escape(area.dataset.compareArea)}"]`
      : year ? `[data-compare-year="${year.dataset.compareYear}"]` : '[data-whole-period]';
    panel.querySelector(selector)?.focus({ preventScroll: true });
  });
  panel.addEventListener('keydown', e => {
    if (e.target.matches('.compare-search-input')) {
      const side = Number(e.target.dataset.schoolSide);
      const list = $(`compare-results-${side}`);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        list?.querySelector('.compare-search-item')?.focus();
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const first = list?.querySelector('.compare-search-item');
        if (first) selectComparisonSchool(side, first.dataset.selectSchool);
      } else if (e.key === 'Escape') {
        e.preventDefault();
        const details = e.target.closest('details');
        if (details) details.open = false;
        const toggle = $(`compare-school-toggle-${side}`);
        if (toggle) toggle.focus(); else document.activeElement?.blur();
      }
      return;
    }
    if (e.target.matches('.compare-search-item')) {
      const side = Number(e.target.dataset.schoolSide);
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const next = e.target.nextElementSibling;
        if (next?.matches('.compare-search-item')) next.focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = e.target.previousElementSibling;
        if (prev?.matches('.compare-search-item')) prev.focus();
        else $(`compare-search-${side}`)?.focus();
      } else if (e.key === 'Escape') {
        e.preventDefault();
        const details = e.target.closest('details');
        if (details) details.open = false;
        const toggle = $(`compare-school-toggle-${side}`);
        if (toggle) toggle.focus(); else document.activeElement?.blur();
      }
      return;
    }
    const point = e.target.closest('[data-compare-year]');
    if (point && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      point.dispatchEvent(new Event('click', { bubbles: true }));
    }
  });
  panel.addEventListener('toggle', e => {
    if (e.target.matches('.compare-school-edit') && e.target.open) {
      const input = e.target.querySelector('.compare-search-input');
      if (input) {
        input.value = '';
        const side = Number(input.dataset.schoolSide);
        renderComparisonSearchResults(side, '');
        setTimeout(() => input.focus(), 30);
      }
    }
  }, true);
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopComparisonPlayback(); });
  let lastWidth = 0;
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(entries => {
    const width = Math.round(entries[0].contentRect.width);
    if (width > 0 && width !== lastWidth) {
      lastWidth = width;
      if (app.compare.mode === 'compare' && app.result) updateComparison(true);
    }
  }).observe(panel);
}

function stopComparisonPlayback() {
  clearTimeout(app.compare.playTimer);
  app.compare.playTimer = null;
  app.compare.playing = false;
  const button = document.querySelector?.('[data-play-years]');
  if (button) { button.textContent = '▶ Play'; button.setAttribute('aria-pressed', 'false'); }
}

function startComparisonPlayback() {
  if (!app.result || app.result.sel.from === app.result.sel.to || app.compare.ids.length < 2) return;
  app.compare.playing = true;
  const advance = () => {
    if (!app.compare.playing || app.compare.mode !== 'compare' || !app.result || app.compare.ids.length < 2) { stopComparisonPlayback(); return; }
    const { from, to } = app.result.sel;
    app.compare.year = app.compare.year === null || app.compare.year >= to ? from : app.compare.year + 1;
    updateComparison(true);
    writeHash(app.sel);
    app.compare.playTimer = setTimeout(advance, 1000);
  };
  advance();
}

function updateComparison(preserveControls = false) {
  if (app.compare.ids.length < 2) stopComparisonPlayback();
  const active = app.compare.mode === 'compare';
  $('ranking-view').hidden = active;
  $('comparison-view').hidden = !active;
  $('view-rankings').setAttribute('aria-pressed', String(!active));
  $('view-compare').setAttribute('aria-pressed', String(active));
  $('comparison-count').textContent = app.compare.ids.length ? `(${app.compare.ids.length})` : '';
  $('search').closest('.field').hidden = active;
  $('export').closest('.field').hidden = active;
  const names = app.compare.ids.map(id => app.institutions[id]?.name || id);
  $('comparison-tray').hidden = active;
  $('comparison-tray').innerHTML = names.map((name, i) => `<span class="compare-chip">${esc(name)}<button type="button" data-remove-school="${esc(app.compare.ids[i])}" aria-label="Remove ${esc(name)} from comparison">×</button></span>`).join('')
    + (names.length && !active ? (names.length >= 2 ? '<button type="button" class="link" data-open-comparison>Compare →</button> ' : '') + '<button type="button" class="link" data-clear-comparison>Clear</button>' : '');
  const panel = $('comparison-view');
  if (!app.result) {
    panel.innerHTML = '';
    return;
  }
  const { sel } = app.result;
  if (app.compare.year !== null && (app.compare.year < sel.from || app.compare.year > sel.to)) app.compare.year = null;
  if (app.compare.area && !sel.areas.includes(app.compare.area)) app.compare.area = null;
  const segments = row => [...row.querySelectorAll('.compare-seg')].map(seg => seg.style.flexGrow);
  const previous = new Map([...panel.querySelectorAll('[data-compare-area]')].map(row => [row.dataset.compareArea, segments(row)]));
  const html = renderComparison({ result: app.result, ids: app.compare.ids, institutions: app.institutions,
    areaById: app.areaById, year: app.compare.year, area: app.compare.area, showAll: app.compare.showAll,
    playing: app.compare.playing, width: Math.max(300, panel.clientWidth || 640) });
  if (preserveControls && panel.querySelector('.compare-areas')) {
    // Keep the year strip alive while dragging so it retains pointer capture.
    const template = document.createElement('template');
    template.innerHTML = html;
    for (const selector of ['.compare-areas', '.compare-history']) {
      panel.querySelector(selector).replaceWith(template.content.querySelector(selector));
    }
    panel.querySelector('.compare-time output').textContent = app.compare.year ?? (sel.from === sel.to ? String(sel.from) : `${sel.from}–${sel.to}`);
    panel.querySelector('[data-reset-comparison]').hidden = template.content.querySelector('[data-reset-comparison]').hidden;
    const total = panel.querySelector('[data-whole-period]');
    total.setAttribute('aria-pressed', String(app.compare.year === null));
    total.classList.toggle('active', app.compare.year === null);
    const play = panel.querySelector('[data-play-years]');
    play.textContent = app.compare.playing ? 'Pause' : '▶ Play';
    play.setAttribute('aria-pressed', String(app.compare.playing));
  } else panel.innerHTML = html;
  syncCompareStrip(panel);
  if (active) setStatus('');
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (const row of panel.querySelectorAll('[data-compare-area]')) {
    const before = previous.get(row.dataset.compareArea);
    if (!before) continue;
    row.querySelectorAll('.compare-seg').forEach((seg, k) => {
      const after = seg.style.flexGrow;
      if (seg.animate && before[k] !== undefined && before[k] !== after) {
        seg.animate([{ flexGrow: before[k] }, { flexGrow: after }], { duration: 420, easing: 'cubic-bezier(.22,.8,.2,1)' });
      }
    });
  }
}

// ---- Export ----------------------------------------------------------------

function exportCsv() {
  if (!app.result || !app.result.rows.length) return;
  const csv = rankingsToCsv(app.result.rows, app.result.sel.areas);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ecerankings-${app.result.sel.region}-${app.result.sel.from}-${app.result.sel.to}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

document.addEventListener('DOMContentLoaded', init);
