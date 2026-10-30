import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import * as history from '../site/rank-history.js';
import * as ranking from '../site/rank.js';

const mainSource = readFileSync(new URL('../site/main.js', import.meta.url), 'utf8');
const legacySource = readFileSync(new URL('../site/index.old.html', import.meta.url), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];
const rows = {
  circuits: [
    { i: 'a', y: 2020, a: 4 }, { i: 'b', y: 2020, a: 1 }, { i: 'c', y: 2020, a: 9 },
    { i: 'b', y: 2021, a: 1 }, { i: 'b', y: 2022, a: 1 },
    { i: 'a', y: 2023, a: 1 }, { i: 'b', y: 2023, a: 1 }
  ],
  control: [
    { i: 'b', y: 2020, a: 1 }, { i: 'c', y: 2020, a: 9 },
    { i: 'a', y: 2021, a: 8 }, { i: 'b', y: 2021, a: 1 },
    { i: 'b', y: 2022, a: 1 }, { i: 'a', y: 2023, a: 1 }, { i: 'b', y: 2023, a: 1 }
  ]
};
const institutions = { a: { name: 'A', country: 'US' }, b: { name: 'B', country: 'US' }, c: { name: 'C', country: 'CA' } };

function currentApp() {
  const context = vm.createContext({
    ...history, ...ranking, console, setTimeout, clearTimeout,
    document: { readyState: 'loading', addEventListener() {} }
  });
  vm.runInContext(mainSource.replace(/^import [\s\S]*? from '[^']+';$/gm, ''), context);
  const state = vm.runInContext('app', context);
  Object.assign(state, {
    data: new Map(Object.entries(rows)),
    sel: { from: 2020, to: 2023, areas: Object.keys(rows), region: 'world' },
    institutions
  });
  const compute = (from = state.sel.from, to = state.sel.to) => ranking.computeRankings(
    { ...state.sel, from, to }, state.data, institutions
  );
  return { context, state, compute };
}

function annual(app) {
  return history.computeAnnualRanks({
    startYear: app.state.sel.from, endYear: app.state.sel.to,
    rankingsForYear: year => app.compute(year, year), rankForResult: row => row.rank
  });
}

test('annual scores retain the selected-area denominator, including zero areas', () => {
  const app = currentApp();
  const result = app.compute(2020, 2020);
  assert.deepEqual(Array.from(result, row => row.id), ['c', 'a', 'b']);
  assert.ok(Math.abs(result.find(row => row.id === 'a').score - (Math.sqrt(5) - 1)) < 1e-12);
  assert.equal(result.find(row => row.id === 'b').score, 1);
  // The range table still sums each area across all selected years.
  assert.ok(Math.abs(app.compute().find(row => row.id === 'a').score - (Math.sqrt(6 * 10) - 1)) < 1e-12);
});

test('each year is ranked independently, with a gap for no output and table-consistent ties', () => {
  assert.deepEqual(history.institutionHistory(annual(currentApp()), 'a'), [
    { year: 2020, rank: 2 }, { year: 2021, rank: 1 },
    { year: 2022, rank: null }, { year: 2023, rank: 1 }
  ]);
});

test('region and area selections change the annual comparison population and scores', () => {
  const app = currentApp();
  app.state.sel.region = 'US';
  assert.equal(history.institutionHistory(annual(app), 'a')[0].rank, 1);
  app.state.sel.areas = ['control'];
  assert.equal(history.institutionHistory(annual(app), 'a')[0].rank, null);
  assert.equal(history.institutionHistory(annual(app), 'a')[1].rank, 1);
  app.state.sel.areas = [];
  assert.ok(history.institutionHistory(annual(app), 'a').every(point => point.rank === null));
});

test('annual ranks include institutions below the 150-row display limit', () => {
  const app = currentApp();
  app.state.sel.areas = ['circuits'];
  app.state.data = new Map([['circuits', Array.from({ length: 200 }, (_, index) => ({
    i: `i${index}`, y: 2020, a: 200 - index
  }))]]);
  assert.equal(annual(app)[0].ranks.get('i199'), 200);
});

test('ranking ties follow the table tolerance, and legacy ranks retain ordinal positions', () => {
  const scores = [{ id: 'a', score: 3 }, { id: 'b', score: 3 }, { id: 'c', score: 2 }];
  assert.deepEqual([...history.rankResults(scores).values()], [1, 1, 3]);
  assert.deepEqual([...history.rankResults(scores, { tieTolerance: null }).values()], [1, 2, 3]);
  assert.deepEqual([...history.rankResults([
    { id: 'a', score: 3 }, { id: 'b', score: 2.99999 }, { id: 'c', score: 2.999 }
  ]).values()], [1, 1, 3]);
});

test('single-year, constant-rank and unranked charts render without invalid geometry', () => {
  for (const points of [
    [{ year: 2020, rank: 1 }],
    [{ year: 2020, rank: 1 }, { year: 2021, rank: 1 }],
    [{ year: 2020, rank: null }]
  ]) {
    const html = history.renderRankHistory(points, 'Example');
    assert.doesNotMatch(html, /NaN|Infinity/);
    assert.match(html, /Year-by-year ranks/);
    if (points[0].rank === null) assert.match(html, /No ranked output/);
    else assert.match(html, /tabindex="0"/);
  }
  assert.equal(history.renderRankHistory([], 'Example'), '');
});

test('missing years break the line, and point labels and text ranks remain available', () => {
  const html = history.renderRankHistory([
    { year: 2020, rank: 5 }, { year: 2021, rank: null }, { year: 2022, rank: 2 }
  ], '<School & Co>');
  const path = html.match(/class="rank-trend-line" d="([^"]*)"/)[1];
  assert.equal((path.match(/M/g) || []).length, 2);
  assert.doesNotMatch(path, /L/);
  assert.match(html, /2020: rank 5/);
  assert.match(html, /<dt>2021<\/dt><dd>Not ranked/);
  assert.match(html, /&lt;School &amp; Co&gt;/);
  assert.doesNotMatch(html, /<School/);
});

test('legacy history respects country and venue-filtered rows without using name search', () => {
  const context = vm.createContext({ console, document: {} });
  // Initialization fetches are irrelevant to this calculation test.
  vm.runInContext(legacySource.replace(/\(async function init\(\) \{[\s\S]*?\}\)\(\);/, ''), context);
  context.fixtureRows = Object.entries(rows).flatMap(([area, data]) => data.map(row => ({ ...row, area })));
  context.fixtureMeta = institutions;
  vm.runInContext(`
    INST_AREA_YEAR = fixtureRows;
    INSTITUTIONS_META = fixtureMeta;
    selectedAreas = new Set(['circuits', 'control']);
    selectedCountry = 'US';
  `, context);
  const options = {
    startYear: 2020, endYear: 2023, tieTolerance: null,
    idForResult: row => row.institution_id,
    rankingsForYear: year => context.computeRankings(year, year)
  };
  assert.equal(history.institutionHistory(history.computeAnnualRanks(options), 'a')[0].rank, 1);
  // A venue selection replaces the current rows; no separate data source is used for history.
  vm.runInContext("INST_AREA_YEAR = fixtureRows.filter(row => row.i === 'b')", context);
  assert.ok(history.institutionHistory(history.computeAnnualRanks(options), 'a').every(point => point.rank === null));
});

test('expanded details render the trend first and cache against the displayed selection', () => {
  const app = currentApp();
  app.state.result = { sel: { ...app.state.sel }, data: app.state.data, rows: app.compute(), annualRanks: null };
  const school = app.state.result.rows.find(row => row.id === 'a');
  const html = app.context.detailRow(school, 'test-detail');
  assert.ok(html.indexOf('rank-trend') < html.indexOf('class="breakdown"'));
  const cached = app.state.result.annualRanks;
  assert.equal(history.institutionHistory(cached, 'a')[0].rank, 2);
  // Controls can change during a fetch. Details must still describe the displayed result.
  app.state.sel = { ...app.state.sel, from: 2022, to: 2022, region: 'US' };
  app.context.detailRow(school, 'test-detail');
  assert.equal(app.state.result.annualRanks, cached);
  assert.equal(cached.length, 4);
  // A completed update installs a new result and invalidates the old history.
  app.state.result = { sel: app.state.sel, data: app.state.data, rows: app.compute(), annualRanks: null };
  app.context.detailRow(app.state.result.rows[0], 'test-detail');
  assert.equal(app.state.result.annualRanks.length, 1);
});
