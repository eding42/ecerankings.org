// Lists every ranked venue by area, straight from the registry.
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
const out = document.getElementById('venues');

try {
  const res = await fetch('data/areas.json');
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const { areas } = await res.json();
  out.innerHTML = Object.values(areas).map((area) =>
    `<section><h2>${esc(area.name)}${area.default_on ? '' : ' <span class="muted">off by default</span>'}</h2>` +
    `<ul>${(area.venues || []).map((v) => `<li>${esc(v.display || v.key)}</li>`).join('')}</ul></section>`).join('');
} catch {
  out.innerHTML = '<p class="error">Could not load the venue list.</p>';
}
