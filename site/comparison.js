// Publication credit comparisons use the same already-filtered rows as Rankings.
// A null balance means neither school has counted output, rather than a tie.
export function creditBalance(left, right) {
  return left + right > 0 ? (right - left) / (left + right) : null;
}

export function compareSchools(data, areaIds, ids, from, to) {
  const [leftId, rightId] = ids;
  return areaIds.map(id => {
    const years = Array.from({ length: to - from + 1 }, (_, i) => ({
      year: from + i, left: 0, right: 0, leftPapers: 0, rightPapers: 0,
    }));
    for (const row of data.get(id) || []) {
      if (row.y < from || row.y > to) continue;
      const side = row.i === leftId ? 'left' : row.i === rightId ? 'right' : null;
      if (!side) continue;
      years[row.y - from][side] += row.a;
      years[row.y - from][`${side}Papers`] += row.p;
    }
    const totals = years.reduce((sum, year) => {
      for (const key of ['left', 'right', 'leftPapers', 'rightPapers']) sum[key] += year[key];
      year.balance = creditBalance(year.left, year.right);
      return sum;
    }, { left: 0, right: 0, leftPapers: 0, rightPapers: 0 });
    return { id, ...totals, balance: creditBalance(totals.left, totals.right), years };
  });
}

function esc(value) {
  return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
const fmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 1, minimumFractionDigits: 1 });

export function renderComparison({ result, ids, institutions, areaById, year = null, area = null, showAll = false, playing = false, width = 640 }) {
  const candidates = new Map(result.rows.map(row => [row.id, row.name]));
  for (const id of ids) candidates.set(id, institutions[id]?.name || id);
  const names = ids.map(id => institutions[id]?.name || id);
  const options = [...candidates].sort((a, b) => a[1].localeCompare(b[1], 'en'));
  const pickers = [0, 1].map(side => {
    const id = ids[side];
    const name = id ? institutions[id]?.name || id : 'Choose an institution';
    const country = id ? institutions[id]?.country || '' : '';
    return `<div class="compare-school compare-school-${side}">
      <span class="compare-school-label"><i class="compare-swatch" aria-hidden="true"></i>${country ? esc(country) : 'Institution'}</span>
      <h3>${esc(name)}</h3>
      <div class="compare-school-actions"><details class="compare-school-edit"${id ? '' : ' open'}>
        <summary id="compare-school-toggle-${side}">${id ? 'Change school' : 'Choose school'}</summary>
        <select id="compare-school-${side}" aria-label="${side === 0 ? 'Left' : 'Right'} school" data-school-side="${side}"${side === 1 && !ids[0] ? ' disabled' : ''}><option value="">Choose an institution…</option>${options.map(([key, label]) => `<option value="${esc(key)}"${id === key ? ' selected' : ''}>${esc(label)}</option>`).join('')}</select>
      </details>${id ? `<button type="button" class="link compare-remove" data-remove-school="${esc(id)}" aria-label="Remove ${esc(name)}">Remove</button>` : ''}</div>
    </div>`;
  }).join('<span class="compare-versus" aria-hidden="true">vs</span>');
  let html = `<div class="compare-schools">${pickers}</div>`;
  if (ids.length < 2 || !ids[0] || !ids[1]) {
    return html + `<div class="compare-empty"><h3>Choose two schools to compare</h3><p>Choose schools above, or open an institution in Rankings and select “Add to comparison.”</p><button type="button" data-browse-schools>Browse rankings</button></div>`;
  }
  const rows = compareSchools(result.data, result.sel.areas, ids, result.sel.from, result.sel.to);
  const ordered = [...rows].sort((a, b) => (b.left + b.right) - (a.left + a.right));
  const selectedArea = rows.find(row => row.id === area) || ordered[0];
  if (!selectedArea) return html;
  const from = result.sel.from, to = result.sel.to;
  const currentYear = year !== null && year >= from && year <= to ? year : null;
  const range = from === to ? `${from}` : `${from}–${to}`;
  html += `<div class="compare-time"><button type="button" class="compare-period${currentYear === null ? ' active' : ''}" data-whole-period aria-pressed="${currentYear === null}">${range} total</button>
    <button type="button" class="compare-play" data-play-years aria-pressed="${playing}"${from === to ? ' disabled' : ''}>${playing ? 'Pause' : '▶ Play years'}</button><label class="visually-hidden" for="compare-year">Single year</label><input type="range" id="compare-year" min="${from}" max="${to}" value="${currentYear ?? to}"${from === to ? ' disabled' : ''} aria-label="Comparison year"><output for="compare-year">${currentYear ?? range}</output></div>
    <p class="compare-explainer">Adjusted publication credit · ${currentYear ?? range}. Each area is balanced at the center. Select one to explore its history.</p>
    <div class="compare-column-labels"><span>Research area</span><span class="compare-side-labels"><span>${esc(names[0])}</span><span class="compare-even">Equal share</span><span>${esc(names[1])}</span></span></div>
    <div class="compare-area-list">`;
  const visible = showAll ? ordered : ordered.slice(0, 8);
  if (!visible.includes(selectedArea)) visible[visible.length - 1] = selectedArea;
  for (const row of visible) {
    const point = currentYear === null ? row : row.years[currentYear - from];
    html += comparisonRow(row, point, areaById.get(row.id)?.name || row.id, row.id === selectedArea.id, names);
  }
  html += `</div>${rows.length > 8 ? `<button type="button" class="link compare-show-areas" data-show-areas aria-expanded="${showAll}">${showAll ? 'Show fewer areas' : `Show all ${rows.length} areas`} <span aria-hidden="true">${showAll ? '↑' : '↓'}</span></button>` : ''}`;
  const name = areaById.get(selectedArea.id)?.name || selectedArea.id;
  html += `<section class="compare-history" aria-label="${esc(name)} comparison over time"><div class="compare-history-heading"><div><span class="compare-eyebrow">Year by year</span><h3>${esc(name)}</h3></div><span>${range}</span></div>
    <p class="compare-history-key"><span>← ${esc(names[0])}</span><span>Equal share</span><span>${esc(names[1])} →</span></p>
    <div class="compare-history-years">${historyPlot(selectedArea.years, currentYear, width, names)}</div>
    <p class="compare-footnote">Select a year to update the comparison. Numbers show adjusted publication credit in the selected venues.</p></section>`;
  return html;
}

function historyPlot(years, currentYear, width, names) {
  const w = Math.max(300, Math.round(width)), left = 100, right = w - 54;
  const mid = (left + right) / 2, height = years.length * 30 + 8;
  const points = years.map((point, i) => ({ ...point, x: point.balance === null ? null : mid + point.balance * (right - left) / 2, y: 18 + i * 30 }));
  let path = '', connected = false;
  for (const point of points) {
    if (point.x === null) { connected = false; continue; }
    path += `${connected ? 'L' : 'M'}${point.x.toFixed(2)},${point.y} `;
    connected = true;
  }
  let html = `<svg class="compare-history-plot" viewBox="0 0 ${w} ${height}" style="height:${height}px" role="group" aria-label="Yearly publication credit balance"><line class="compare-history-center" x1="${mid}" x2="${mid}" y1="4" y2="${height - 4}"/><path class="compare-history-line" d="${path}"/>`;
  for (const point of points) {
    const selected = point.year === currentYear;
    html += `<g class="compare-year-point${selected ? ' selected' : ''}" data-compare-year="${point.year}" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${point.year}: ${esc(names[0])} ${fmt.format(point.left)}, ${esc(names[1])} ${fmt.format(point.right)} adjusted credit">
      <title>${point.year}: ${esc(names[0])} ${fmt.format(point.left)} · ${esc(names[1])} ${fmt.format(point.right)}</title>
      <rect class="compare-history-hit" x="0" y="${point.y - 14}" width="${w}" height="29" rx="4"/>
      <text class="compare-history-year" x="0" y="${point.y + 4}">${point.year}</text>
      <text class="compare-history-credit-a" x="76" y="${point.y + 4}" text-anchor="end">${fmt.format(point.left)}</text>
      <text class="compare-history-credit-b" x="${w}" y="${point.y + 4}" text-anchor="end">${fmt.format(point.right)}</text>`;
    if (point.x === null) html += `<text class="compare-history-empty" x="${mid}" y="${point.y + 4}" text-anchor="middle">No output</text>`;
    else html += `<circle class="compare-history-halo" cx="${point.x}" cy="${point.y}" r="8"/><circle class="compare-history-dot ${point.balance <= 0 ? 'side-a' : 'side-b'}" cx="${point.x}" cy="${point.y}" r="4"/>`;
    html += '</g>';
  }
  return html + '</svg>';
}

function pullTrack(point) {
  const b = point.balance;
  const position = b === null ? 50 : 50 + b * 50;
  const side = b === null || b === 0 ? 'even' : b < 0 ? 'left' : 'right';
  return `<span class="compare-track compare-pull-${side}${b === null ? ' compare-no-output' : ''}" style="--pull-start:${Math.min(position, 50)}%;--pull-width:${Math.abs(position - 50)}%;--pull-position:${position}%" aria-hidden="true"><i class="compare-fill"></i><i class="compare-knot"></i>${b === null ? '<span>No output</span>' : ''}</span>`;
}

function comparisonRow(row, point, name, selected, names) {
  const b = point.balance;
  const advantage = b === null ? 'No counted output' : b === 0 ? 'Equal credit' : `${Math.round(Math.max(point.left, point.right) / (point.left + point.right) * 100)}% ${b < 0 ? 'left' : 'right'}`;
  return `<button type="button" class="compare-area${selected ? ' selected' : ''}" data-compare-area="${esc(row.id)}" aria-pressed="${selected}" title="${esc(name)}: ${esc(names[0])} ${fmt.format(point.left)}, ${esc(names[1])} ${fmt.format(point.right)} adjusted credit. ${advantage}.">
    <span class="compare-area-name">${esc(name)}</span><span class="compare-value compare-value-left">${fmt.format(point.left)}</span>${pullTrack(point)}<span class="compare-value compare-value-right">${fmt.format(point.right)}</span></button>`;
}
