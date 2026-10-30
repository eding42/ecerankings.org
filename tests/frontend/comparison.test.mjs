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

test('comparison totals add yearly credit, respect the inclusive range and selected pair', () => {
  const [row] = C.compareSchools(data, ['quantum'], ['A', 'B'], 2020, 2022);
  assert.equal(row.left, 5);
  assert.equal(row.right, 7);
  assert.equal(row.leftPapers, 8);
  assert.equal(row.rightPapers, 10);
  assert.equal(row.years.length, 3);
  assert.equal(row.balance, 1 / 6);
  assert.deepEqual(row.years.map(y => [y.left, y.right]), [[3, 1], [0, 0], [2, 6]]);
});

test('balance distinguishes no counted output from a tie, and mirrors swapped schools', () => {
  assert.equal(C.creditBalance(0, 0), null);
  assert.equal(C.creditBalance(4, 4), 0);
  assert.equal(C.creditBalance(3, 1), -.5);
  assert.equal(C.creditBalance(1, 3), .5);
  assert.equal(C.creditBalance(5, 0), -1);
  assert.equal(C.creditBalance(0, 5), 1);
  const original = C.compareSchools(data, ['quantum'], ['A', 'B'], 2020, 2022)[0];
  const swapped = C.compareSchools(data, ['quantum'], ['B', 'A'], 2020, 2022)[0];
  assert.equal(original.left, swapped.right);
  assert.equal(original.balance, -swapped.balance);
});

test('comparison follows area and venue-filtered data, with no hidden fallback to full areas', () => {
  const filtered = new Map([['quantum', [{ i: 'B', y: 2020, a: .25, p: 1 }]]]);
  const [row] = C.compareSchools(filtered, ['quantum'], ['A', 'B'], 2020, 2020);
  assert.equal(row.left, 0);
  assert.equal(row.right, .25);
  assert.equal(row.years.length, 1);
  assert.equal(row.balance, 1);
  assert.deepEqual(C.compareSchools(data, [], ['A', 'B'], 2020, 2022), []);
});

test('single-year view changes displayed values while the full yearly history stays available', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, area: 'quantum', year: 2022 });
  assert.match(html, /Adjusted publication credit · 2022/);
  assert.match(html, /&lt;Alpha &amp; Co&gt; 2.0, Beta 6.0/);
  assert.match(html, /data-compare-year="2020"/);
  assert.match(html, /data-compare-year="2022"/);
  assert.match(html, /compare-no-output/);
  assert.doesNotMatch(html, /NaN|Infinity/);
  assert.match(html, /&lt;Alpha &amp; Co&gt;/);
  assert.doesNotMatch(html, /<Alpha/);
});

test('empty and one-school views guide users back to institution actions', () => {
  for (const ids of [[], ['A']]) {
    const html = C.renderComparison({ result, ids, institutions, areaById });
    assert.match(html, /Choose two schools/);
    assert.match(html, /Add to comparison/);
    assert.doesNotMatch(html, /compare-area-list/);
  }
});

function appContext(keepHashWriter = false) {
  const context = vm.createContext({ console, setTimeout, clearTimeout, document: { readyState: 'loading', addEventListener() {} } });
  const main = readFileSync(new URL('../../site/main.js', import.meta.url), 'utf8');
  vm.runInContext(main.replace(/^import [\s\S]*? from '[^']+';$/gm, ''), context);
  vm.runInContext('renderTable = () => {}; updateComparison = () => {};', context);
  if (!keepHashWriter) vm.runInContext('writeHash = () => {};', context);
  const state = vm.runInContext('app', context);
  state.institutions = institutions;
  return { context, state };
}

test('institution actions pin at most two distinct schools and allow removing either', () => {
  const { context, state } = appContext();
  context.toggleComparisonSchool('A');
  context.toggleComparisonSchool('B');
  context.toggleComparisonSchool('C');
  assert.deepEqual(Array.from(state.compare.ids), ['A', 'B']);
  context.toggleComparisonSchool('A');
  context.toggleComparisonSchool('C');
  assert.deepEqual(Array.from(state.compare.ids), ['B', 'C']);
  context.toggleComparisonSchool('unknown');
  assert.deepEqual(Array.from(state.compare.ids), ['B', 'C']);
});

test('shared comparison state validates school IDs, years and areas on reload', () => {
  const { context, state } = appContext();
  const a = 'https://openalex.org/I1', b = 'https://openalex.org/I2';
  state.institutions = { [a]: { name: 'A' }, [b]: { name: 'B' } };
  state.sel = selection;
  context.location = { hash: '#compare=I1,I1,I2,unknown&view=compare&compare-area=quantum&compare-year=2021' };
  context.URLSearchParams = URLSearchParams;
  context.readComparisonHash();
  assert.deepEqual(Array.from(state.compare.ids), [a, b]);
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
  state.compare.ids = ['https://openalex.org/I1', 'https://openalex.org/I2'];
  state.compare.mode = 'compare';
  state.compare.year = 2021;
  context.encodeState = () => '#areas=quantum&disabled_venues=quantum%3Aone';
  context.writeHash(selection);
  const params = new URLSearchParams(written.split('#')[1]);
  assert.equal(params.get('areas'), 'quantum');
  assert.equal(params.get('disabled_venues'), 'quantum:one');
  assert.equal(params.get('compare'), 'I1,I2');
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

test('the yearly plot connects valid dots and leaves a gap for years without output', () => {
  const html = C.renderComparison({ result, ids: ['A', 'B'], institutions, areaById, area: 'quantum', width: 390 });
  const path = html.match(/class="compare-history-line" d="([^"]*)"/)[1];
  assert.equal((path.match(/M/g) || []).length, 2);
  assert.doesNotMatch(path, /L/);
  assert.match(html, /compare-history-dot/);
  assert.match(html, /No output/);
  assert.match(html, /data-play-years/);
  assert.doesNotMatch(html, /NaN|Infinity/);
});
