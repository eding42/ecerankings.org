const escape = (value) => String(value).replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = new Intl.NumberFormat('en-US');

function gapMessage(gap) {
  const reason = String(gap.reason || '');
  if (/missing precise|no.*source|no.*metadata|not.*verified/i.test(reason)) return 'An exact proceedings source is not yet verified.';
  if (/reported.*count|incomplete pages|pagination.*count/i.test(reason)) return 'The source changed during collection; its results did not reconcile.';
  if (/budget|rate limit/i.test(reason)) return 'The collection limit was reached before this scope was validated.';
  if (/zero|empty/i.test(reason)) return 'No acceptable replacement records were returned by the source.';
  return 'A complete, validated source observation could not be collected.';
}

async function renderCoverage() {
  const status = document.getElementById('release-status');
  try {
    const load = async (url) => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    };
    const [manifest, registry] = await Promise.all([load('data/manifest.json'), load('data/areas.json')]);
    if (manifest.validation?.status !== 'passed' || !Array.isArray(manifest.refresh?.files)) {
      throw new Error('Release coverage information is unavailable');
    }
    const byArea = new Map();
    const venueArea = new Map();
    const venueNames = new Map();
    for (const [id, area] of Object.entries(registry.areas)) {
      byArea.set(id, {name:area.name, defaultOn:area.default_on, fresh:0, retained:0, works:0, slots:0, covered:0});
      for (const venue of area.venues) {
        venueArea.set(venue.key, id);
        venueNames.set(venue.key, venue.display || venue.name || venue.key);
      }
    }
    for (const file of manifest.refresh.files) {
      const area = byArea.get(venueArea.get(file.venue));
      if (!area) continue;
      if (file.source_state === 'refreshed') area.fresh++; else area.retained++;
      area.works += file.works;
      area.slots += file.author_slots;
      area.covered += file.slots_with_affiliation_signal;
    }
    document.getElementById('coverage-rows').innerHTML = [...byArea.values()].map((a) =>
      `<tr><th scope="row">${escape(a.name)}${a.defaultOn ? '' : ' (off by default)'}</th>` +
      `<td class="num">${number.format(a.fresh)}</td><td class="num">${number.format(a.retained)}</td>` +
      `<td class="num">${number.format(a.works)}</td><td class="num">${a.slots ? (100*a.covered/a.slots).toFixed(1)+'%' : 'Unavailable'}</td></tr>`).join('');
    const gaps = manifest.refresh.unresolved_scopes || [];
    if (gaps.length) {
      document.getElementById('gap-rows').innerHTML = gaps.map((g) =>
        `<tr><th scope="row">${escape(venueNames.get(g.venue) || g.venue)}</th>` +
        `<td>${escape(g.year)}</td><td>${escape(gapMessage(g))}</td></tr>`).join('');
      document.getElementById('collection-gaps').hidden = false;
    }
    status.textContent = `Release built ${manifest.generated_at.slice(0,10)}. Coverage describes the selected source observations, including retained data.`;
    document.getElementById('coverage-content').hidden = false;
  } catch (error) {
    status.textContent = `Could not load release coverage (${error.message}). No coverage figures are shown.`;
  }
}

renderCoverage();
