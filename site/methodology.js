// Renders the venue list on methodology.html from data/areas.json.

import { listAreas } from './rank.js';

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

async function render() {
  const el = document.getElementById('venue-list');
  let registry;
  try {
    const res = await fetch('data/areas.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    registry = await res.json();
  } catch (err) {
    el.innerHTML = `<p class="error">Could not load the venue registry (${esc(err.message)}). It is also available in the repository as <code>data/areas.json</code>.</p>`;
    return;
  }
  let html = '';
  let cluster = null;
  for (const a of listAreas(registry)) {
    if (a.cluster !== cluster) {
      cluster = a.cluster;
      html += `<h3>${esc(cluster)}</h3>`;
    }
    html += `<table class="venues"><caption class="visually-hidden">${esc(a.name)} venues</caption>` +
      `<thead><tr><th scope="col">${esc(a.name)}${a.defaultOn ? '' : ' <span class="muted">(off by default)</span>'}</th>` +
      `<th scope="col">Type</th><th scope="col">Status</th></tr></thead><tbody>`;
    for (const v of a.venues) {
      html += `<tr><td>${esc(v.display || v.key)}</td><td class="kind">${esc(v.kind || '')}</td>` +
        `<td class="status">${v.status === 'verified' ? 'verified' : esc(v.status || 'unknown') + ' — not yet verified'}</td></tr>`;
    }
    html += `</tbody></table>`;
  }
  el.innerHTML = html;
}

render();
