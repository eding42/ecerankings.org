import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../site/comparison.js', import.meta.url), 'utf8');
const C = await import('data:text/javascript,' + encodeURIComponent(source));
const data = new Map([
  ['quantum', [{ i: 'A', y: 2020, a: 3, p: 5 }, { i: 'B', y: 2020, a: 1, p: 2 },
    { i: 'A', y: 2022, a: 2, p: 3 }, { i: 'B', y: 2022, a: 6, p: 8 },
    { i: 'C', y: 2020, a: 100, p: 100 }, { i: 'A', y: 2026, a: 99, p: 100 }]],
  ['control', [{ i: 'A', y: 2020, a: 4, p: 6 }, { i: 'B', y: 2020, a: 4, p: 5 }]],
]);
const institutions = { A: { name: '<Alpha & Co>', country: 'US' }, B: { name: 'Beta', country: 'US' }, C: { name: 'Gamma', country: 'US' } };
const selection = { from: 2020, to: 2022, areas: ['quantum', 'control'], region: 'US' };
const result = { sel: selection, data, rows: Object.entries(institutions).map(([id, meta]) => ({ id, name: meta.name })) };
const areaById = new Map([['quantum', { name: 'Quantum' }], ['control', { name: 'Control' }]]);

test('comparison totals add yearly credit per school, respecting the inclusive range', () => {
  const [row] = C.compareSchools(data, ['quantum'], ['A', 'B'], 2020, 2022);
  assert.deepEqual(row.values, [5, 7]);
  assert.deepEqual(row.papers, [8, 10]);
  assert.equal(row.total, 12);
  assert.deepEqual(row.years.map(y => y.values), [[3, 1], [0, 0], [2, 6]]);
});

test('comparison takes up to four schools in slot order, and swapping order mirrors values', () => {
  const [row] = C.compareSchools(data, ['quantum'], ['C', 'B', 'A'], 2020, 2022);
  assert.deepEqual(row.values, [100, 7, 5]);
  const swapped = C.compareSchools(data, ['quantum'], ['B', 'A'], 2020, 2022)[0];
  assert.deepEqual(swapped.values, [7, 5]);
  assert.equal(C.MAX_SCHOOLS, 4);
});

test('comparison follows area and venue-filtered data, with no hidden fallback to full areas', () => {
  const filtered = new Map([['quantum', [{ i: 'B', y: 2020, a: .25, p: 1 }]]]);
  const [row] = C.compareSchools(filtered, ['quantum'], ['A', 'B'], 2020, 2020);
  assert.deepEqual(row.values, [0, .25]);
  assert.equal(row.years.length, 1);
  assert.deepEqual(C.compareSchools(data, [], ['A', 'B'], 2020, 2022), []);
});

test('three schools render a three-way share bar, a value column and a line each', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B', 'C'], institutions, areaById, area: 'quantum', width: 600 });
  const quantum = html.match(/data-compare-area="quantum"[\s\S]*?<\/button>/)[0];
  assert.equal((quantum.match(/class="compare-seg/g) || []).length, 3);
  assert.equal((quantum.match(/class="compare-value/g) || []).length, 3);
  assert.doesNotMatch(quantum, / pair/);
  assert.equal((html.match(/class="compare-history-line"/g) || []).length, 3);
  assert.match(html, /Add school/);
  const four = C.renderComparison({ result, ids: ['A', 'B', 'C', 'D'], institutions: { ...institutions, D: { name: 'Delta' } }, areaById });
  assert.doesNotMatch(four, /Add school/);
});

test('single-year view changes displayed values while the full yearly history stays available', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, area: 'quantum', year: 2022 });
  assert.match(html, /<output for="compare-year">2022<\/output>/);
  assert.match(html, /&lt;Alpha &amp; Co&gt; 2.0, Beta 6.0/);
  assert.match(html, / pair/);
  assert.match(html, /data-compare-year="2020"/);
  assert.match(html, /data-compare-year="2022"/);
  assert.match(html, /compare-no-output/);
  assert.doesNotMatch(html, /NaN|Infinity/);
  assert.match(html, /&lt;Alpha &amp; Co&gt;/);
  assert.doesNotMatch(html, /<Alpha/);
});

test('empty and one-school views show only the institution pickers', () => {
  for (const ids of [[], ['A']]) {
    const html = C.renderComparison({ result, ids, institutions, areaById });
    assert.match(html, /Add school/);
    assert.match(html, /class="compare-search-input"/);
    assert.doesNotMatch(html, /compare-area-list/);
  }
});

function appContext(keepHashWriter = false) {
  const context = vm.createContext({ console, setTimeout, clearTimeout, document: { readyState: 'loading', addEventListener() {} } });
  const main = readFileSync(new URL('../../site/core/engine.js', import.meta.url), 'utf8');
  const script = main
    .replace(/^import [\s\S]*? from '[^']+';$/gm, '')
    .replace(/^export (async function|function|const|let|var)\s+/gm, '$1 ')
    .replace(/^export \{[\s\S]*?\};?\s*$/gm, '');
  vm.runInContext(script, context);
  vm.runInContext('renderTable = () => {}; updateComparison = () => {};', context);
  if (!keepHashWriter) vm.runInContext('writeHash = () => {};', context);
  const state = vm.runInContext('app', context);
  state.institutions = institutions;
  return { context, state };
}

test('institution actions pin at most four distinct schools and allow removing any', () => {
  const { context, state } = appContext();
  state.institutions = { ...institutions, D: { name: 'Delta' }, E: { name: 'Epsilon' } };
  for (const id of ['A', 'B', 'C', 'D', 'E']) context.toggleComparisonSchool(id);
  assert.deepEqual(Array.from(state.compare.ids), ['A', 'B', 'C', 'D']);
  context.toggleComparisonSchool('B');
  context.toggleComparisonSchool('E');
  assert.deepEqual(Array.from(state.compare.ids), ['A', 'C', 'D', 'E']);
  context.toggleComparisonSchool('unknown');
  assert.deepEqual(Array.from(state.compare.ids), ['A', 'C', 'D', 'E']);
});

test('renderComparison renders search input instead of a long select dropdown', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById });
  assert.match(html, /class="compare-search-input"/);
  assert.match(html, /id="compare-search-0"/);
  assert.match(html, /id="compare-search-1"/);
  assert.match(html, /id="compare-results-0"/);
  assert.match(html, /id="compare-results-1"/);
  assert.match(html, /placeholder="Search institutions…"/);
  assert.doesNotMatch(html, /<select/);
});

test('selectComparisonSchool assigns, swaps, and clears school sides', () => {
  const { context, state } = appContext();
  context.selectComparisonSchool(0, 'A');
  assert.deepEqual(Array.from(state.compare.ids), ['A']);
  context.selectComparisonSchool(1, 'B');
  assert.deepEqual(Array.from(state.compare.ids), ['A', 'B']);
  context.selectComparisonSchool(0, 'B');
  assert.deepEqual(Array.from(state.compare.ids), ['B', 'A']);
  context.selectComparisonSchool(2, 'C');
  assert.deepEqual(Array.from(state.compare.ids), ['B', 'A', 'C']);
  context.selectComparisonSchool(1, null);
  assert.deepEqual(Array.from(state.compare.ids), ['B', 'C']);
});

test('shared comparison state validates school IDs, years and areas on reload', () => {
  const { context, state } = appContext();
  const a = 'https://openalex.org/I1', b = 'https://openalex.org/I2';
  state.institutions = { [a]: { name: 'A' }, [b]: { name: 'B' } };
  state.sel = selection;
  context.location = { hash: '#compare=I1,I1,I2,unknown&open=I2,bogus&view=compare&compare-area=quantum&compare-year=2021' };
  context.URLSearchParams = URLSearchParams;
  context.readComparisonHash();
  assert.deepEqual(Array.from(state.compare.ids), [a, b]);
  context.readOpenHash();
  assert.deepEqual([...state.expanded], [b]);
  assert.equal(state.revealOpen, true);
  assert.equal(state.compare.mode, 'compare');
  assert.equal(state.compare.year, 2021);
  assert.equal(state.compare.area, 'quantum');
  context.location.hash = '#compare=unknown&view=bogus&compare-area=missing&compare-year=999999';
  context.readComparisonHash();
  assert.equal(state.compare.ids.length, 0);
  assert.equal(state.compare.mode, 'rankings');
  assert.equal(state.compare.area, null);
  assert.equal(state.compare.year, null);
});

test('venue fetches use the result selection snapshot rather than controls changed mid-load', async () => {
  const { context, state } = appContext();
  state.areaById = new Map([['quantum', { venues: [{ key: 'one' }, { key: 'two' }] }]]);
  state.sel = { disabledVenues: ['quantum:two'] };
  vm.runInContext("loadVenue = async (area, venue) => [{ venue }]; loadArea = async () => [{ full: true }];", context);
  const rows = await context.loadAreaData('quantum', { disabledVenues: ['quantum:one'] });
  assert.deepEqual(Array.from(rows, row => row.venue), ['two']);
});

test('comparison URLs preserve filters and both schools while default rankings URLs stay clean', () => {
  const { context, state } = appContext(true);
  state.defaults = selection;
  state.sel = selection;
  state.compare.area = 'quantum';
  context.URLSearchParams = URLSearchParams;
  context.encodeState = () => '';
  context.location = { hash: '', href: 'https://example.com/', pathname: '/', search: '' };
  let written;
  context.history = { replaceState: (a, b, url) => { written = url; } };
  context.writeHash(selection);
  assert.equal(state.lastHash, '');
  state.compare.ids = ['https://openalex.org/I1', 'https://openalex.org/I2', 'https://openalex.org/I3'];
  state.expanded = new Set(['https://openalex.org/I9']);
  state.compare.mode = 'compare';
  state.compare.year = 2021;
  context.encodeState = () => '#areas=quantum&disabled_venues=quantum%3Aone';
  context.writeHash(selection);
  const params = new URLSearchParams(written.split('#')[1]);
  assert.equal(params.get('areas'), 'quantum');
  assert.equal(params.get('disabled_venues'), 'quantum:one');
  assert.equal(params.get('compare'), 'I1,I2,I3');
  assert.equal(params.get('open'), 'I9');
  assert.equal(params.get('view'), 'compare');
  assert.equal(params.get('compare-year'), '2021');
});

test('year playback advances, wraps within the selected range, and stops cleanly', () => {
  const { context, state } = appContext();
  let next, cancelled;
  context.setTimeout = callback => { next = callback; return 1; };
  context.clearTimeout = timer => { cancelled = timer; };
  state.result = result;
  state.sel = selection;
  state.compare.mode = 'compare';
  state.compare.ids = ['A', 'B'];
  context.startComparisonPlayback();
  assert.equal(state.compare.year, 2020);
  assert.equal(state.compare.playing, true);
  next(); assert.equal(state.compare.year, 2021);
  next(); assert.equal(state.compare.year, 2022);
  next(); assert.equal(state.compare.year, 2020);
  context.stopComparisonPlayback();
  assert.equal(cancelled, 1);
  assert.equal(state.compare.playing, false);
  assert.equal(state.compare.playTimer, null);
});

test('the yearly plot draws one line per school across every year, zero years included', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, area: 'quantum', width: 390 });
  const paths = [...html.matchAll(/class="compare-history-line" d="([^"]*)"/g)].map(match => match[1]);
  assert.equal(paths.length, 2);
  for (const path of paths) assert.equal(path.split(' ').length, 3);
  assert.equal((html.match(/class="compare-history-dot"/g) || []).length, 6);
  assert.match(html, /data-play-years/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});

test('Reset appears only once a year or a non-default area is chosen', () => {
  const visibleReset = html => /data-reset-comparison>/.test(html);
  assert.doesNotMatch(C.renderComparison({ result, ids: ['A'], institutions, areaById }), /data-reset-comparison/);
  // All areas is the default, so choosing any single area is a change.
  assert.equal(visibleReset(C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById })), false);
  assert.equal(visibleReset(C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, area: 'quantum' })), true);
  assert.equal(visibleReset(C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, area: 'control' })), true);
  assert.equal(visibleReset(C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, year: 2021 })), true);
});

test('Reset returns to all years and the default area but keeps the chosen schools', () => {
  const { context, state } = appContext();
  state.compare.ids = ['A', 'B'];
  state.compare.year = 2021;
  state.compare.area = 'quantum';
  state.compare.playing = true;
  state.compare.playTimer = 123;
  context.resetComparison();
  assert.deepEqual(Array.from(state.compare.ids), ['A', 'B']);
  assert.equal(state.compare.year, null);
  assert.equal(state.compare.area, null);
  assert.equal(state.compare.playing, false);
  assert.equal(state.compare.playTimer, null);
  context.clearComparison();
  assert.deepEqual(Array.from(state.compare.ids), []);
});


test('the year control is a strip mount point, absent when the range is a single year', async () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById });
  assert.match(html, /<div class="ys-compare" id="compare-year"><\/div>/);
  assert.doesNotMatch(html, /type="range"/);
  const oneYear = { ...result, sel: { ...result.sel, from: 2022, to: 2022 } };
  assert.doesNotMatch(C.renderComparison({ result: oneYear, ids: ['A', 'B'], institutions, areaById }), /id="compare-year"/);
  const { denseStart } = await import('../../site/year-strip.js');
  const totals = new Map([[1981, 5], [2001, 150], [2016, 9000], [2025, 12000]]);
  assert.equal(denseStart(totals, 2016), 2016);
  assert.equal(denseStart(totals, 2005), 2005);
  assert.equal(denseStart(new Map(), 2016), 2016);
});

test('an All areas row totals the selected areas, leads the list and is the default selection', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById });
  const overall = html.match(/data-compare-area="all"[\s\S]*?<\/button>/)[0];
  assert.match(overall, /All areas/);
  assert.match(overall, />9\.0<[\s\S]*>11\.0</);
  assert.ok(html.indexOf('data-compare-area="all"') < html.indexOf('data-compare-area="quantum"'));
  assert.match(html, /class="compare-area compare-overall selected"/);
  assert.match(html, /All areas by year/);
  const year = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, year: 2020 });
  assert.match(year.match(/data-compare-area="all"[\s\S]*?<\/button>/)[0], />7\.0<[\s\S]*>5\.0</);
  // One selected area is already the total.
  const single = { ...result, sel: { ...selection, areas: ['quantum'] } };
  assert.doesNotMatch(C.renderComparison({ result: single, ids: ['A', 'B'], institutions, areaById }), /data-compare-area="all"/);
});
