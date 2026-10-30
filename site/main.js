// ECERankings front end. Plain ES module, no build step.
// Ranking math and URL state live in rank.js; this file owns fetching and DOM.

import {
  REGIONS, listAreas, defaultAreaIds, computeRankings, yearExtent,
  encodeState, decodeState, rankingsToCsv,
} from './rank.js';
import { computeAnnualRanks, institutionHistory, renderRankHistory } from './rank-history.js';
import { renderComparison } from './comparison.js?v=compare-2';

const PAGE_SIZE = 100;
const CURRENT_YEAR = new Date().getFullYear();

// Coverage caveats shown beside areas that are off by default. The registry's
// default_on flag decides what is off; these strings only explain why.
const AREA_NOTES = {
  ml: 'Off by default: proceedings membership, coverage and paper-specific affiliations are incompletely verified for NeurIPS, ICML and ICLR.',
  flagship: 'Off by default: general-science journals (Nature, Science, PNAS, …), not ECE-specific.',
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
  compare: { ids: [], mode: 'rankings', year: null, area: null, showAll: false, playing: false, playTimer: null },
};

const $ = (id) => document.getElementById(id);
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
    showFatal(`Could not load the site data (${err.message}). No rankings are shown.`);
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
  readComparisonHash();

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
  if (stamp) $('data-stamp').textContent = `Data files built ${stamp.slice(0, 10)}.`;
}

function readHash() {
  return decodeState(location.hash, app.defaults, app.areas.map((a) => a.id));
}

function writeHash(sel) {
  const params = new URLSearchParams(encodeState(sel, app.defaults).replace(/^#/, ''));
  if (app.compare.ids.length) params.set('compare', app.compare.ids.map(id => id.replace('https://openalex.org/', '')).join(','));
  if (app.compare.mode === 'compare') params.set('view', 'compare');
  if (app.compare.ids.length === 2 && app.compare.area) params.set('compare-area', app.compare.area);
  if (app.compare.ids.length === 2 && app.compare.year !== null) params.set('compare-year', String(app.compare.year));
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
      const note = !a.defaultOn ? (AREA_NOTES[a.id] || 'Off by default.') : '';
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
            const label = v.display || v.key || '';
            const kind = v.kind ? `<span class="venue-badge">${esc(v.kind)}</span>` : '';
            const isChecked = !disabled.has(`${a.id}:${v.key}`);
            return `<li class="venue-row">` +
              `<input type="checkbox" id="venue-${esc(a.id)}-${esc(v.key)}" ` +
              `data-area="${esc(a.id)}" data-venue="${esc(v.key)}"` +
              `${isChecked ? ' checked' : ''}>` +
              `<label for="venue-${esc(a.id)}-${esc(v.key)}">${kind}<span>${esc(label)}</span></label>` +
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
  app.sel.disabledVenues = [...disabled];
  app.sel.areas = app.areas.map((a) => a.id).filter((id) => on.has(id));
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
  $('show-more').addEventListener('click', () => { app.shown += PAGE_SIZE; renderTable(); });
  $('show-all').addEventListener('click', () => { app.shown = Infinity; renderTable(); });
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
    const again = $('ranking-body').querySelector(`button.inst[data-id="${CSS.escape(id)}"]`);
    if (again) again.focus();
  });

  window.addEventListener('hashchange', () => {
    if (!app.defaults || location.hash === app.lastHash) return;
    app.sel = readHash();
    readComparisonHash();
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
      cell.colSpan = compact.matches ? 3 : 5;
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
  renderNotices(sel);
  const countEl = $('area-count');
  if (countEl) countEl.textContent = `${sel.areas.length} of ${app.areas.length}`;
  hideError();

  if (sel.areas.length === 0) {
    app.result = null;
    setBusy(false);
    setStatus('Select at least one research area to rank institutions.');
    clearTable();
    updateComparison();
    return;
  }

  setStatus('Loading research area data…');
  setBusy(true);

  const settled = await Promise.allSettled(sel.areas.map((id) => loadAreaData(id, sel)));
  if (run !== app.runId) return; // a newer selection superseded this run

  setBusy(false);
  const failed = sel.areas
    .map((id, i) => ({ id, r: settled[i] }))
    .filter((x) => x.r.status === 'rejected');
  if (failed.length) {
    app.result = null;
    clearTable();
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
  renderTable();
  updateComparison();
  writeHash(sel);
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
    `<p>No ranking is shown, because leaving an area out would change every institution's score. ` +
    `<button type="button" id="retry">Try again</button></p>`;
  $('error').hidden = false;
  $('retry').addEventListener('click', () => update());
}

function showFatal(message) {
  setStatus('');
  $('error').innerHTML = `<p><strong>${esc(message)}</strong></p><p><button type="button" onclick="location.reload()">Reload</button></p>`;
  $('error').hidden = false;
  $('area-groups').innerHTML = '<p class="muted">Areas unavailable.</p>';
}

function renderNotices(sel) {
  const out = [];
  if (isPartialYear(sel.to)) {
    const partial = [];
    for (let y = Math.max(sel.from, app.latestComplete + 1); y <= sel.to; y++) partial.push(y);
    out.push(`<p><strong>Partial year.</strong> ${partial.join(', ')} ${partial.length > 1 ? 'are' : 'is'} not complete: ` +
      `recent papers and citations are still being indexed by OpenAlex, and rankings for incomplete years will fluctuate.</p>`);
  }
  const offDefaultActive = sel.areas.filter((id) => !app.areaById.get(id)?.defaultOn);
  if (offDefaultActive.length) {
    const names = offDefaultActive.map((id) => esc(app.areaById.get(id)?.name || id));
    out.push(`<p><strong>Preliminary coverage.</strong> ${names.join(', ')} ${names.length > 1 ? 'are' : 'is'} enabled. ` +
      `See each research area's note for verification status.</p>`);
  }
  if (sel.disabledVenues && sel.disabledVenues.length > 0) {
    out.push(`<p><strong>Filtered venues.</strong> Some individual conferences or journals have been deselected.</p>`);
  }
  $('notices').innerHTML = out.join('');
}

// ---- Table -----------------------------------------------------------------

function filteredRows() {
  if (!app.result) return [];
  const q = app.query;
  return q ? app.result.rows.filter((r) => r.name.toLowerCase().includes(q)) : app.result.rows;
}

function regionLabel(region) {
  if (region === 'world') return 'World';
  const r = REGIONS.find((x) => x.id === region);
  return r ? r.label : countryName(region);
}

function renderTable() {
  if (!app.result) return;
  const { sel, rows: all } = app.result;
  const rows = filteredRows();
  const visible = rows.slice(0, app.shown);
  const years = sel.from === sel.to ? `${sel.from}` : `${sel.from}–${sel.to}`;
  let status;
  if (!all.length) status = `No institutions have credit for ${years} in ${regionLabel(sel.region)}.`;
  else if (app.query) status = `${fmtInt.format(rows.length)} of ${fmtInt.format(all.length)} ranked institutions match “${app.query}”.`;
  else status = `${fmtInt.format(all.length)} institutions · ${regionLabel(sel.region)} · ${years}.`;
  if (visible.length < rows.length) status += ` Showing the first ${fmtInt.format(visible.length)}.`;
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
      `<td class="num opt">${fmtInt.format(r.pubTotal)}</td></tr>`;
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

function comparisonAction(row) {
  const selected = app.compare.ids.includes(row.id);
  const disabled = app.compare.ids.length === 2 && !selected;
  const label = `${selected ? 'Remove' : 'Add'} ${row.name} ${selected ? 'from' : 'to'} comparison`;
  const icon = selected ? '<path d="m3 7 3 3 5-6"/>' : '<rect x="2" y="5" width="7" height="7" rx="1"/><path d="M5 5V2h7v7H9"/>';
  return `<button type="button" class="inst-compare${selected ? ' selected' : ''}" data-compare-id="${esc(row.id)}" aria-pressed="${selected}" aria-label="${esc(label)}" title="${disabled ? 'Remove a selected school before adding another' : esc(label)}"${disabled ? ' disabled' : ''}><svg width="13" height="13" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">${icon}</svg><span>${selected ? 'Added' : 'Compare'}</span></button>`;
}

function detailRow(r, did) {
  const columns = typeof matchMedia === 'function' && matchMedia('(max-width: 600px)').matches ? 3 : 5;
  const result = app.result;
  if (!result.annualRanks) {
    result.annualRanks = computeAnnualRanks({
      startYear: result.sel.from, endYear: result.sel.to,
      rankingsForYear: year => computeRankings(
        { ...result.sel, from: year, to: year }, result.data, app.institutions
      ),
      rankForResult: row => row.rank,
    });
  }
  const trend = renderRankHistory(
    institutionHistory(result.annualRanks, r.id), r.name, 'selected areas, venues and region'
  );
  const items = r.perArea
    .map((x, idx) => ({ ...x, idx, name: app.areaById.get(x.area)?.name || x.area }))
    .sort((a, b) => b.adj - a.adj || a.idx - b.idx);
  const body = items.map((x) =>
    `<tr class="${x.adj === 0 ? 'zero' : ''}">` +
    `<td>${esc(x.name)}</td>` +
    `<td class="num">${fmt1.format(x.adj)}</td>` +
    `<td class="num">${fmtInt.format(x.pubs)}</td></tr>`,
  ).join('');
  return `<tr class="detail" id="${did}"><td colspan="${columns}">` +
    `${trend}` +
    `<dl class="institution-totals" aria-label="Institution totals">` +
    `<div><dt>Adjusted count</dt><dd>${fmt1.format(r.adjTotal)}</dd></div>` +
    `<div><dt>Papers</dt><dd>${fmtInt.format(r.pubTotal)}</dd></div></dl>` +
    `<table class="breakdown"><caption>Credit by research area</caption>` +
    `<thead><tr><th scope="col">Area</th><th scope="col" class="num">Adj. count</th><th scope="col" class="num">Papers</th></tr></thead>` +
    `<tbody>${body}</tbody></table></td></tr>`;
}

// ---- Comparison mode -------------------------------------------------------

function readComparisonHash() {
  const params = new URLSearchParams(location.hash.replace(/^#/, ''));
  const ids = (params.get('compare') || '').split(',').filter(Boolean)
    .map(id => id.startsWith('https://openalex.org/') ? id : `https://openalex.org/${id}`)
    .filter(id => Object.hasOwn(app.institutions, id));
  app.compare.ids = [...new Set(ids)].slice(0, 2);
  app.compare.mode = params.get('view') === 'compare' ? 'compare' : 'rankings';
  const year = Number(params.get('compare-year'));
  app.compare.year = params.has('compare-year') && Number.isInteger(year) && year >= app.sel.from && year <= app.sel.to ? year : null;
  app.compare.area = app.sel.areas.includes(params.get('compare-area')) ? params.get('compare-area') : null;
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
  else if (ids.length < 2 && Object.hasOwn(app.institutions, id)) ids.push(id);
  renderTable();
  updateComparison();
  writeHash(app.sel);
}

function bindComparisonEvents() {
  $('view-rankings').addEventListener('click', () => setComparisonMode('rankings'));
  $('view-compare').addEventListener('click', () => setComparisonMode('compare'));
  $('comparison-tray').addEventListener('click', e => {
    const remove = e.target.closest('[data-remove-school]');
    if (remove) toggleComparisonSchool(remove.dataset.removeSchool);
    if (e.target.closest('[data-open-comparison]')) setComparisonMode('compare');
  });
  const panel = $('comparison-view');
  panel.addEventListener('change', e => {
    if (!e.target.matches('[data-school-side]')) return;
    const side = Number(e.target.dataset.schoolSide), id = e.target.value;
    if (!id) app.compare.ids.splice(side, 1);
    else {
      const other = side === 0 ? 1 : 0;
      if (app.compare.ids[other] === id) {
        app.compare.ids[other] = app.compare.ids[side];
      }
      app.compare.ids[side] = id;
      app.compare.ids = app.compare.ids.filter(Boolean);
    }
    renderTable();
    updateComparison();
    writeHash(app.sel);
    $(`compare-school-toggle-${side}`)?.focus();
  });
  panel.addEventListener('input', e => {
    if (e.target.id !== 'compare-year') return;
    stopComparisonPlayback();
    app.compare.year = Number(e.target.value);
    updateComparison(true);
    writeHash(app.sel);
  });
  panel.addEventListener('click', e => {
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
    if (e.target.closest('[data-browse-schools]')) { setComparisonMode('rankings'); return; }
    const area = e.target.closest('[data-compare-area]');
    const year = e.target.closest('[data-compare-year]');
    if (area) app.compare.area = area.dataset.compareArea;
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
    const point = e.target.closest('[data-compare-year]');
    if (point && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault();
      point.dispatchEvent(new Event('click', { bubbles: true }));
    }
  });
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
  if (button) { button.textContent = '▶ Play years'; button.setAttribute('aria-pressed', 'false'); }
}

function startComparisonPlayback() {
  if (!app.result || app.result.sel.from === app.result.sel.to) return;
  app.compare.playing = true;
  const advance = () => {
    if (!app.compare.playing || app.compare.mode !== 'compare' || !app.result) { stopComparisonPlayback(); return; }
    const { from, to } = app.result.sel;
    app.compare.year = app.compare.year === null || app.compare.year >= to ? from : app.compare.year + 1;
    updateComparison(true);
    writeHash(app.sel);
    app.compare.playTimer = setTimeout(advance, 1000);
  };
  advance();
}

function updateComparison(preserveControls = false) {
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
    + (names.length && !active ? names.length === 2 ? '<button type="button" class="link" data-open-comparison>Compare these schools →</button>' : '<span>Add one more school from the rankings.</span>' : '');
  const panel = $('comparison-view');
  if (!app.result) {
    panel.innerHTML = '<p class="muted">Select research areas and load their data to compare schools.</p>';
    return;
  }
  const { sel } = app.result;
  if (app.compare.year !== null && (app.compare.year < sel.from || app.compare.year > sel.to)) app.compare.year = null;
  if (!sel.areas.includes(app.compare.area)) app.compare.area = sel.areas[0] || null;
  const previous = new Map([...panel.querySelectorAll('[data-compare-area], [data-compare-year]')].map(row => {
    const track = row.querySelector('.compare-track');
    return [row.dataset.compareArea || row.dataset.compareYear, track?.getAttribute('style')];
  }));
  const oldDots = new Map([...panel.querySelectorAll('[data-compare-year]')].map(row => [row.dataset.compareYear, row.querySelector('.compare-history-dot')?.getAttribute('cx')]));
  const oldLine = panel.querySelector('.compare-history-line')?.getAttribute('d');
  const html = renderComparison({ result: app.result, ids: app.compare.ids, institutions: app.institutions,
    areaById: app.areaById, year: app.compare.year, area: app.compare.area, showAll: app.compare.showAll,
    playing: app.compare.playing, width: Math.max(300, panel.clientWidth || 640) });
  if (preserveControls && panel.querySelector('.compare-area-list')) {
    // Keep the range input alive while dragging so it retains pointer capture.
    const template = document.createElement('template');
    template.innerHTML = html;
    for (const selector of ['.compare-area-list', '.compare-history', '.compare-explainer']) {
      panel.querySelector(selector).replaceWith(template.content.querySelector(selector));
    }
    const more = panel.querySelector('[data-show-areas]'), nextMore = template.content.querySelector('[data-show-areas]');
    if (more && nextMore) more.replaceWith(nextMore);
    panel.querySelector('.compare-time output').textContent = app.compare.year ?? (sel.from === sel.to ? String(sel.from) : `${sel.from}–${sel.to}`);
    panel.querySelector('#compare-year').value = app.compare.year ?? sel.to;
    const total = panel.querySelector('[data-whole-period]');
    total.setAttribute('aria-pressed', String(app.compare.year === null));
    total.classList.toggle('active', app.compare.year === null);
    const play = panel.querySelector('[data-play-years]');
    play.textContent = app.compare.playing ? 'Pause' : '▶ Play years';
    play.setAttribute('aria-pressed', String(app.compare.playing));
  } else panel.innerHTML = html;
  if (active) setStatus(`Comparing ${names.length} schools · ${sel.from}–${sel.to} · ${sel.areas.length} selected areas.`);
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  for (const row of panel.querySelectorAll('[data-compare-area], [data-compare-year]')) {
    const old = previous.get(row.dataset.compareArea || row.dataset.compareYear);
    if (!old) continue;
    const style = document.createElement('span').style;
    style.cssText = old;
    const track = row.querySelector('.compare-track');
    if (!track) continue;
    const before = name => style.getPropertyValue(name);
    const after = name => track.style.getPropertyValue(name);
    const fill = track.querySelector('.compare-fill'), knot = track.querySelector('.compare-knot');
    if (!fill.animate) continue;
    fill.animate([{ left: before('--pull-start'), width: before('--pull-width') }, { left: after('--pull-start'), width: after('--pull-width') }], { duration: 420, easing: 'cubic-bezier(.22,.8,.2,1)' });
    knot.animate([{ left: `calc(${before('--pull-position')} - 5px)` }, { left: `calc(${after('--pull-position')} - 5px)` }], { duration: 420, easing: 'cubic-bezier(.22,.8,.2,1)' });
  }
  for (const row of panel.querySelectorAll('[data-compare-year]')) {
    const dot = row.querySelector('.compare-history-dot'), before = oldDots.get(row.dataset.compareYear);
    if (dot?.animate && before) dot.animate([{ cx: `${before}px` }, { cx: `${dot.getAttribute('cx')}px` }], { duration: 420, easing: 'cubic-bezier(.22,.8,.2,1)' });
  }
  const line = panel.querySelector('.compare-history-line');
  if (line?.animate && oldLine && CSS.supports('d', `path("${oldLine}")`)) {
    line.animate([{ d: `path("${oldLine}")` }, { d: `path("${line.getAttribute('d')}")` }], { duration: 420, easing: 'cubic-bezier(.22,.8,.2,1)' });
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
