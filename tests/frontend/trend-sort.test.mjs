// Offline tests for sorting the ranking table by trend movement.
// Run: node --test tests/frontend/trend-sort.test.mjs
// site/rank.js is an ES module under a non-module package scope, so load it
// through a data: URL instead of a plain import.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vm from 'node:vm';
import * as history from '../../site/rank-history.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..', '..');
const siteDir = path.join(root, 'site');
const src = readFileSync(path.join(siteDir, 'rank.js'), 'utf8');
const R = await import('data:text/javascript,' + encodeURIComponent(src));

const rows = [
  { id: 'a', rank: 1, name: 'Alpha' },
  { id: 'b', rank: 2, name: 'Beta' },
  { id: 'c', rank: 3, name: 'Gamma' },
  { id: 'd', rank: 4, name: 'Delta' },
  { id: 'e', rank: 5, name: 'Epsilon' },
];

test('net movement is initial rank minus final rank; null endpoints have no delta', () => {
  assert.equal(R.netRankMovement([{ year: 2016, rank: 30 }, { year: 2025, rank: 15 }]), 15);
  assert.equal(R.netRankMovement([{ year: 2016, rank: 10 }, { year: 2025, rank: 30 }]), -20);
  assert.equal(R.netRankMovement([{ year: 2016, rank: 7 }, { year: 2025, rank: 7 }]), 0);
  // Only the endpoints matter, not the path taken between them.
  assert.equal(R.netRankMovement([
    { year: 2016, rank: 4 }, { year: 2020, rank: 40 }, { year: 2025, rank: 2 },
  ]), 2);
  assert.equal(R.netRankMovement([{ year: 2016, rank: null }, { year: 2025, rank: 2 }]), null);
  assert.equal(R.netRankMovement([{ year: 2016, rank: 4 }, { year: 2025, rank: null }]), null);
  assert.equal(R.netRankMovement([{ year: 2020, rank: 4 }]), null);
  assert.equal(R.netRankMovement([]), null);
  assert.equal(R.netRankMovement(undefined), null);
});

test('the Trend header cycles score order, most improved, then least improved', () => {
  assert.equal(R.nextTrendSort('score'), 'improved');
  assert.equal(R.nextTrendSort('improved'), 'declined');
  assert.equal(R.nextTrendSort('declined'), 'score');
  assert.equal(R.nextTrendSort('unknown'), 'score');
});

test('most improved puts the largest gain first, with ties in score order and missing trends last', () => {
  const moved = new Map([
    ['a', 2], ['b', 15], ['c', 0], ['d', null], ['e', -20],
  ]);
  const sorted = R.sortRowsByTrend(rows, 'improved', (r) => moved.get(r.id));
  assert.deepEqual(sorted.map((r) => r.id), ['b', 'a', 'c', 'e', 'd']);
  // The original score order is untouched.
  assert.deepEqual(rows.map((r) => r.id), ['a', 'b', 'c', 'd', 'e']);
});

test('least improved puts the largest drop first, with ties in score order and missing trends last', () => {
  const moved = new Map([
    ['a', -2], ['b', 15], ['c', 0], ['d', -20], ['e', null],
  ]);
  const sorted = R.sortRowsByTrend(rows, 'declined', (r) => moved.get(r.id));
  assert.deepEqual(sorted.map((r) => r.id), ['d', 'a', 'c', 'b', 'e']);
});

test('equal movements fall back to score rank, including when every trend is missing', () => {
  const tied = [
    { id: 'b', rank: 2 }, { id: 'a', rank: 1 }, { id: 'c', rank: 3 },
  ];
  assert.deepEqual(
    R.sortRowsByTrend(tied, 'improved', () => 4).map((r) => r.id),
    ['a', 'b', 'c'],
  );
  assert.deepEqual(
    R.sortRowsByTrend(tied, 'declined', () => 4).map((r) => r.id),
    ['a', 'b', 'c'],
  );
  assert.deepEqual(
    R.sortRowsByTrend(tied, 'improved', () => null).map((r) => r.id),
    ['a', 'b', 'c'],
  );
});

test('score mode leaves the default ranking order alone', () => {
  const sorted = R.sortRowsByTrend(rows, 'score', () => NaN);
  assert.deepEqual(sorted.map((r) => r.id), ['a', 'b', 'c', 'd', 'e']);
});

test('the table engine filters and sorts through the shared trend helpers', () => {
  const mainSource = readFileSync(path.join(siteDir, 'main.js'), 'utf8');
  const context = vm.createContext({
    ...history, ...R, console, setTimeout, clearTimeout,
    document: { readyState: 'loading', addEventListener() {} },
  });
  vm.runInContext(mainSource.replace(/^import [\s\S]*? from '[^']+';$/gm, ''), context);
  const app = vm.runInContext('app', context);

  const data = new Map([['x', [
    { i: 'a', n: 'Alpha', y: 2020, p: 1, a: 1 },
    { i: 'b', n: 'Beta', y: 2020, p: 1, a: 3 },
    { i: 'c', n: 'Gamma', y: 2020, p: 1, a: 2 },
  ]]]);
  const sel = { from: 2020, to: 2023, region: 'world', areas: ['x'] };
  const rankings = R.computeRankings(sel, data, {
    a: { name: 'Alpha', country: 'US' },
    b: { name: 'Beta', country: 'US' },
    c: { name: 'Gamma', country: 'US' },
  });
  app.result = {
    sel, data, rows: rankings, annualRanks: [
      { year: 2020, ranks: new Map([['a', 3], ['b', 1], ['c', 2]]) },
      { year: 2023, ranks: new Map([['a', 1], ['b', 3], ['c', 2]]) },
    ],
  };

  app.sort = 'improved';
  assert.deepEqual(vm.runInContext('filteredRows()', context).map((r) => r.id), ['a', 'c', 'b']);
  app.sort = 'declined';
  assert.deepEqual(vm.runInContext('filteredRows()', context).map((r) => r.id), ['b', 'c', 'a']);
  app.sort = 'score';
  assert.deepEqual(vm.runInContext('filteredRows()', context).map((r) => r.id), ['b', 'c', 'a']);
});

test('engine and every sister site expose the Trend sort control', () => {
  for (const rel of ['index.html', 'biology/index.html', 'earth-space/index.html']) {
    const html = readFileSync(path.join(siteDir, rel), 'utf8');
    assert.match(html, /class="[^"]*trend-cell[^"]*"\s+aria-sort="none"/, rel);
    assert.match(html, /<button[^>]+data-sort="trend"/, rel);
  }
  for (const rel of ['main.js', 'biology/main.js', 'earth-space/main.js']) {
    const js = readFileSync(path.join(siteDir, rel), 'utf8');
    assert.match(js, /sortRowsByTrend/, `${rel} uses the shared trend sort`);
    assert.match(js, /nextTrendSort/, `${rel} cycles the trend sort`);
    assert.match(js, /aria-sort/, `${rel} reports the sort state`);
  }
  // A future Earth & Space package keeps the control in its generated header.
  const packager = readFileSync(path.join(root, 'pipeline', 'package_earth_space_site.py'), 'utf8');
  assert.match(packager, /data-sort="trend"/);
});
