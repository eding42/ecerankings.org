// School comparison: 2–4 institutions over the same already-filtered rows as
// Rankings. Each school keeps its slot's series colour (--series-1 … -4).

export const MAX_SCHOOLS = 4;
// Row id for the sum over every selected area. Not a registry area id.
export const ALL_AREAS = 'all';

function sumAreas(rows, ids, from, to) {
  const zeros = () => ids.map(() => 0);
  const years = Array.from({ length: to - from + 1 }, (_, i) => ({ year: from + i, values: zeros(), papers: zeros() }));
  const values = zeros(), papers = zeros();
  for (const row of rows) {
    row.values.forEach((v, k) => { values[k] += v; papers[k] += row.papers[k]; });
    row.years.forEach((point, i) => point.values.forEach((v, k) => {
      years[i].values[k] += v;
      years[i].papers[k] += point.papers[k];
    }));
  }
  return { id: ALL_AREAS, values, papers, total: values.reduce((a, b) => a + b, 0), years };
}

export function compareSchools(data, areaIds, ids, from, to) {
  const slot = new Map(ids.map((id, k) => [id, k]));
  const zeros = () => ids.map(() => 0);
  return areaIds.map(id => {
    const years = Array.from({ length: to - from + 1 }, (_, i) => ({ year: from + i, values: zeros(), papers: zeros() }));
    for (const row of data.get(id) || []) {
      const k = slot.get(row.i);
      if (k === undefined || row.y < from || row.y > to) continue;
      years[row.y - from].values[k] += row.a;
      years[row.y - from].papers[k] += row.p;
    }
    const values = ids.map((_, k) => years.reduce((sum, year) => sum + year.values[k], 0));
    const papers = ids.map((_, k) => years.reduce((sum, year) => sum + year.papers[k], 0));
    return { id, values, papers, total: values.reduce((a, b) => a + b, 0), years };
  });
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const series = k => `--series:var(--series-${k + 1})`;

function searchBox(slot, currentId, result, institutions) {
  const items = result.rows.slice(0, 8).map(row => {
    const country = institutions[row.id]?.country || '';
    const selected = row.id === currentId;
    return `<button type="button" class="compare-search-item${selected ? ' selected' : ''}" data-school-side="${slot}" data-select-school="${esc(row.id)}" role="option" aria-selected="${selected}"><span class="compare-search-name">${esc(row.name)}</span>${country ? `<span class="compare-search-country">${esc(country)}</span>` : ''}</button>`;
  }).join('');
  return `<div class="compare-school-search">
      <input type="search" class="compare-search-input" id="compare-search-${slot}" data-school-side="${slot}" placeholder="Search institutions…" autocomplete="off" spellcheck="false" aria-label="Institution search">
      <div class="compare-search-results" id="compare-results-${slot}" role="listbox" aria-label="Matching institutions">${items}</div>
    </div>`;
}

function schoolCards(ids, result, institutions) {
  let html = ids.map((id, slot) => {
    const name = institutions[id]?.name || id, country = institutions[id]?.country || '';
    return `<div class="compare-school" style="${series(slot)}">
      <h3>${esc(name)}${country ? ` <abbr class="cc">${esc(country)}</abbr>` : ''}</h3>
      <div class="compare-school-actions"><details class="compare-school-edit"><summary id="compare-school-toggle-${slot}">Change</summary>${searchBox(slot, id, result, institutions)}</details><button type="button" class="link compare-remove" data-remove-school="${esc(id)}" aria-label="Remove ${esc(name)}">Remove</button></div>
    </div>`;
  }).join('');
  if (ids.length < MAX_SCHOOLS) {
    const slot = ids.length;
    html += `<div class="compare-school compare-add" style="${series(slot)}">
      <label class="compare-add-label" for="compare-search-${slot}">Add school</label>${searchBox(slot, null, result, institutions)}</div>`;
  }
  return `<div class="compare-schools">${html}</div>`;
}

export function renderComparison({ result, ids, institutions, areaById, year = null, area = null, showAll = false, playing = false, width = 640 }) {
  let html = schoolCards(ids, result, institutions);
  if (ids.length < 2) return html;
  const names = ids.map(id => institutions[id]?.name || id);
  const { from, to } = result.sel;
  const rows = compareSchools(result.data, result.sel.areas, ids, from, to);
  const ordered = [...rows].sort((a, b) => b.total - a.total);
  if (!rows.length) return html;
  // With several areas the total leads the list and is the default selection.
  const overall = rows.length > 1 ? sumAreas(rows, ids, from, to) : null;
  const initial = overall || ordered[0];
  const selectedArea = rows.find(row => row.id === area) || initial;
  const currentYear = year !== null && year >= from && year <= to ? year : null;
  const range = from === to ? `${from}` : `${from}–${to}`;
  html += `<div class="compare-time"><button type="button" class="compare-period${currentYear === null ? ' active' : ''}" data-whole-period aria-pressed="${currentYear === null}">All years</button>
    <button type="button" class="compare-play" data-play-years aria-pressed="${playing}"${from === to ? ' disabled' : ''}>${playing ? 'Pause' : '▶ Play'}</button><output for="compare-year">${currentYear ?? range}</output><button type="button" class="link compare-reset" data-reset-comparison${currentYear === null && selectedArea === initial ? ' hidden' : ''}>Reset</button>${from === to ? '' : '<div class="ys-compare" id="compare-year"></div>'}</div>`;
  const columns = `--values:repeat(${ids.length},var(--value-w))`;
  html += `<div class="compare-areas" style="${columns}"><div class="compare-head"><span>Adjusted count</span><span></span>${names.map((name, k) => `<span class="compare-key" style="${series(k)}" title="${esc(name)}"><i></i></span>`).join('')}</div><div class="compare-area-list">`;
  const visible = showAll ? ordered : ordered.slice(0, 8);
  if (selectedArea !== overall && !visible.includes(selectedArea)) visible[visible.length - 1] = selectedArea;
  if (overall) {
    const values = currentYear === null ? overall.values : overall.years[currentYear - from].values;
    html += comparisonRow(ALL_AREAS, values, 'All areas', selectedArea === overall, names, ' compare-overall');
  }
  for (const row of visible) {
    const values = currentYear === null ? row.values : row.years[currentYear - from].values;
    html += comparisonRow(row.id, values, areaById.get(row.id)?.name || row.id, row.id === selectedArea.id, names);
  }
  html += '</div>';
  if (rows.length > 8) html += `<button type="button" class="link compare-show-areas" data-show-areas aria-expanded="${showAll}">${showAll ? 'Fewer areas' : `All ${rows.length} areas`} <span aria-hidden="true">${showAll ? '↑' : '↓'}</span></button>`;
  html += '</div>';
  const name = selectedArea === overall ? 'All areas' : areaById.get(selectedArea.id)?.name || selectedArea.id;
  html += `<section class="compare-history" aria-label="${esc(name)} by year"><h3>${esc(name)} by year</h3>
    <div class="compare-history-years">${historyPlot(selectedArea.years, currentYear, width, names)}</div></section>`;
  return html;
}

function comparisonRow(id, values, name, selected, names, extra = '') {
  const total = values.reduce((a, b) => a + b, 0), max = Math.max(...values);
  const track = total > 0
    ? values.map((v, k) => `<i class="compare-seg${v > 0 ? '' : ' zero'}" style="flex-grow:${v.toFixed(4)};${series(k)}"></i>`).join('')
    : '<span>No output</span>';
  const title = `${name}: ${names.map((n, k) => `${n} ${fmt.format(values[k])}`).join(', ')}`;
  return `<button type="button" class="compare-area${extra}${selected ? ' selected' : ''}" data-compare-area="${esc(id)}" aria-pressed="${selected}" title="${esc(title)}">
    <span class="compare-area-name">${esc(name)}</span><span class="compare-track${total > 0 ? '' : ' compare-no-output'}${values.length === 2 ? ' pair' : ''}" aria-hidden="true">${track}</span>${values.map(v => `<span class="compare-value${v > 0 && v === max ? ' lead' : ''}">${fmt.format(v)}</span>`).join('')}</button>`;
}

function niceMax(value) {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value)), lead = value / power;
  return (lead <= 1 ? 1 : lead <= 2 ? 2 : lead <= 5 ? 5 : 10) * power;
}

// One line per school on a shared axis. Each year gets a full-height hit
// column carrying its crosshair and readout.
function historyPlot(years, currentYear, width, names) {
  const w = Math.max(300, Math.round(width)), h = 220;
  const left = 38, right = w - 20, top = 12, bottom = h - 26;
  const max = niceMax(Math.max(...years.flatMap(point => point.values)));
  const step = years.length > 1 ? (right - left) / (years.length - 1) : 0;
  const x = i => years.length > 1 ? left + i * step : (left + right) / 2;
  const y = value => bottom - value / max * (bottom - top);
  const tick = value => Number.isInteger(value) ? String(value) : value.toFixed(1);
  const labelEvery = step ? Math.ceil(44 / step) : 1;
  let html = `<svg class="compare-history-plot" viewBox="0 0 ${w} ${h}" style="height:${h}px" role="group" aria-label="Adjusted count by year">`;
  for (const value of [0, max / 2, max]) {
    html += `<line class="compare-history-grid${value ? '' : ' base'}" x1="${left}" x2="${right}" y1="${y(value)}" y2="${y(value)}"/><text class="compare-history-tick" x="${left - 10}" y="${y(value) + 4}" text-anchor="end">${tick(value)}</text>`;
  }
  years.forEach((point, i) => {
    if ((years.length - 1 - i) % labelEvery) return;
    html += `<text class="compare-history-year${point.year === currentYear ? ' selected' : ''}" x="${x(i).toFixed(1)}" y="${h - 6}" text-anchor="middle">${point.year}</text>`;
  });
  names.forEach((_, k) => {
    html += `<g class="compare-history-series" style="${series(k)}"><path class="compare-history-line" d="${years.map((point, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(point.values[k]).toFixed(1)}`).join(' ')}"/>`;
    years.forEach((point, i) => { html += `<circle class="compare-history-dot" cx="${x(i).toFixed(1)}" cy="${y(point.values[k]).toFixed(1)}" r="4"/>`; });
    html += '</g>';
  });
  const band = step || right - left, tipWidth = 86, tipHeight = 28 + names.length * 17;
  years.forEach((point, i) => {
    const selected = point.year === currentYear, px = x(i);
    const tipX = px + 10 + tipWidth > w ? px - 10 - tipWidth : px + 10;
    const label = `${point.year}: ${names.map((n, k) => `${n} ${fmt.format(point.values[k])}`).join(', ')}`;
    html += `<g class="compare-year-point${selected ? ' selected' : ''}" data-compare-year="${point.year}" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${esc(label)}">
      <rect class="compare-history-hit" x="${(px - band / 2).toFixed(1)}" y="0" width="${band.toFixed(1)}" height="${h}"/>
      <line class="compare-history-cross" x1="${px.toFixed(1)}" x2="${px.toFixed(1)}" y1="${top}" y2="${bottom}"/>
      <g class="compare-history-tip" transform="translate(${tipX.toFixed(1)},${top})"><rect width="${tipWidth}" height="${tipHeight}" rx="3"/>
        <text class="compare-history-tip-year" x="10" y="18">${point.year}</text>${point.values.map((v, k) => `<line style="${series(k)}" x1="10" x2="24" y1="${33 + k * 17}" y2="${33 + k * 17}"/><text x="32" y="${37 + k * 17}">${fmt.format(v)}</text>`).join('')}</g></g>`;
  });
  return html + '</svg>';
}
