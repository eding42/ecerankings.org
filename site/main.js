// ECERankings front end. Plain ES module, no build step.
// Ranking math and URL state live in rank.js; this file owns fetching and DOM.

import {
  REGIONS, listAreas, defaultAreaIds, computeRankings, yearExtent,
  encodeState, decodeState, rankingsToCsv,
} from './rank.js';

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
  pending: new Map(), // area id -> in-flight promise (dedupes concurrent fetches)
  defaults: null,     // {from, to, region, areas}
  sel: null,          // live selection {from, to, region, areas}
  latestComplete: CURRENT_YEAR - 1,
  extent: null,       // {min, max} over loaded area files
  runId: 0,
  result: null,       // {sel, rows} for the last completed run
  shown: PAGE_SIZE,
  query: '',
  expanded: new Set(),
  openVenues: new Set(), // set of area ids with open venue dropdown
  lastHash: null,
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
  };
  app.sel = readHash();

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
  const hash = encodeState(sel, app.defaults);
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
            return `<li>${kind}${esc(label)}</li>`;
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
  for (const cb of $('area-groups').querySelectorAll('input[type=checkbox]')) cb.checked = on.has(cb.value);
  const countEl = $('area-count');
  if (countEl) countEl.textContent = '';
}

function setAreas(ids) {
  const on = new Set(ids);
  app.sel.areas = app.areas.map((a) => a.id).filter((id) => on.has(id));
  syncControls();
  update();
}

function bindStaticEvents() {
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
      return;
    }

    const b = e.target.closest('button[data-group]');
    if (!b) return;
    const on = new Set(app.sel.areas);
    for (const cb of $('area-groups').querySelectorAll(`input[data-group="${b.dataset.group}"]`)) {
      if (b.dataset.on === '1') on.add(cb.value); else on.delete(cb.value);
    }
    setAreas([...on]);
  });
  document.querySelector('.area-actions').addEventListener('click', (e) => {
    const b = e.target.closest('button[data-select]');
    if (!b || !app.areas.length) return;
    const mode = b.dataset.select;
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

  $('ranking-body').addEventListener('click', (e) => {
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
}

// ---- Update cycle ----------------------------------------------------------

async function update() {
  // Snapshot the selection: controls may change while files load.
  const sel = { ...app.sel, areas: [...app.sel.areas] };
  const run = ++app.runId;
  writeHash(sel);
  renderNotices(sel);
  const countEl = $('area-count');
  if (countEl) countEl.textContent = '';
  hideError();

  if (sel.areas.length === 0) {
    app.result = null;
    setBusy(false);
    setStatus('Select at least one research area to rank institutions.');
    clearTable();
    return;
  }

  const missing = sel.areas.filter((a) => !app.data.has(a));
  if (missing.length) {
    setStatus(`Loading ${missing.length} area file${missing.length > 1 ? 's' : ''}…`);
    setBusy(true);
  }
  const settled = await Promise.allSettled(sel.areas.map(loadArea));
  if (run !== app.runId) return; // a newer selection superseded this run

  setBusy(false);
  const failed = sel.areas
    .map((id, i) => ({ id, r: settled[i] }))
    .filter((x) => x.r.status === 'rejected');
  if (failed.length) {
    app.result = null;
    clearTable();
    showAreaError(failed);
    return;
  }

  const ext = yearExtent(app.data);
  if (ext && (!app.extent || ext.min !== app.extent.min || ext.max !== app.extent.max)) {
    app.extent = ext;
    renderYearOptions();
  }

  const rows = computeRankings(sel, app.data, app.institutions);
  app.result = { sel, rows };
  app.shown = PAGE_SIZE;
  renderTable();
}

function setBusy(on) {
  $('ranking-table').setAttribute('aria-busy', on ? 'true' : 'false');
  $('ranking-table').classList.toggle('stale', on);
  $('export').disabled = on || !app.result;
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
      `papers are still being published and indexed, so counts for ${partial.length > 1 ? 'these years' : 'this year'} are lower than a full year's.</p>`);
  }
  for (const id of sel.areas) {
    const a = app.areaById.get(id);
    if (a && !a.defaultOn) {
      out.push(`<p><strong>${esc(a.name)} is selected.</strong> ${esc(AREA_NOTES[id] || 'This area is off by default.')}</p>`);
    }
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
    const did = `detail-${r.id.replace(/\W/g, '')}`;
    html += `<tr class="inst-row${open ? ' open' : ''}">` +
      `<td class="num rank">${r.tied ? `<span title="Tied">${r.rank}</span>` : r.rank}</td>` +
      `<td class="name"><button type="button" class="inst" data-id="${esc(r.id)}" aria-expanded="${open}" aria-controls="${did}">` +
      `<span class="tri" aria-hidden="true">${open ? '▾' : '▸'}</span>${esc(r.name)}</button>` +
      (r.country ? ` <abbr class="cc" title="${esc(countryName(r.country))}">${esc(r.country)}</abbr>` : '') +
      `</td>` +
      `<td class="num score">${fmt2.format(r.score)}</td>` +
      `<td class="num">${fmt1.format(r.adjTotal)}</td>` +
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

function detailRow(r, did) {
  const items = r.perArea
    .map((x, idx) => ({ ...x, idx, name: app.areaById.get(x.area)?.name || x.area }))
    .sort((a, b) => b.adj - a.adj || a.idx - b.idx);
  const body = items.map((x) =>
    `<tr${x.adj > 0 ? '' : ' class="zero"'}><th scope="row">${esc(x.name)}</th>` +
    `<td class="num">${fmt1.format(x.adj)}</td><td class="num">${fmtInt.format(x.pubs)}</td></tr>`).join('');
  return `<tr class="detail" id="${did}"><td></td><td colspan="4">` +
    `<table class="breakdown"><caption>Per-area counts, ${esc(String(app.result.sel.from))}–${esc(String(app.result.sel.to))}` +
    ` · <a href="${esc(r.id)}">OpenAlex record</a></caption>` +
    `<thead><tr><th scope="col">Area</th><th scope="col" class="num">Adj. count</th><th scope="col" class="num">Papers</th></tr></thead>` +
    `<tbody>${body}</tbody></table></td></tr>`;
}

function exportCsv() {
  if (!app.result || !app.result.rows.length) return;
  const { sel, rows } = app.result;
  const csv = rankingsToCsv(rows, sel.areas);
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `ecerankings_${sel.region}_${sel.from}-${sel.to}_${sel.areas.length}areas.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else init();
