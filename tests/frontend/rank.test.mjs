// Offline tests for site/rank.js. Run: node --test tests/frontend/rank.test.mjs
// site/rank.js is an ES module under a non-module package scope, so load it
// through a data: URL instead of a plain import.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const siteDir = path.join(here, '..', '..', 'site');
const src = readFileSync(path.join(siteDir, 'rank.js'), 'utf8');
const R = await import('data:text/javascript,' + encodeURIComponent(src));

const inst = {
  A: { name: 'Alpha University', country: 'US' },
  B: { name: 'Beta University', country: 'DE' },
  C: { name: 'Gamma University', country: 'US' },
  D: { name: 'Delta University', country: '' },
};
const data = new Map([
  ['x', [
    { i: 'A', n: 'Alpha', y: 2020, p: 4, a: 3 },
    { i: 'A', n: 'Alpha', y: 2026, p: 9, a: 99 },
    { i: 'B', n: 'Beta', y: 2020, p: 2, a: 1 },
    { i: 'C', n: 'Gamma', y: 2020, p: 2, a: 1 },
    { i: 'D', n: 'Delta', y: 2020, p: 1, a: 0.5 },
  ]],
  ['y', [
    { i: 'B', n: 'Beta', y: 2021, p: 1, a: 3 },
    { i: 'C', n: 'Gamma', y: 2021, p: 1, a: 3 },
  ]],
]);
const sel = (o = {}) => ({ from: 2016, to: 2025, region: 'world', areas: ['x', 'y'], disabledVenues: [], ...o });

test('geometric mean includes zero-count areas', () => {
  const rows = R.computeRankings(sel(), data, inst);
  const a = rows.find((r) => r.id === 'A');
  // A: x=3, y=0 -> sqrt(4*1)-1 = 1
  assert.ok(Math.abs(a.score - 1) < 1e-12);
  assert.equal(a.active, 1);
  const b = rows.find((r) => r.id === 'B');
  // B: x=1, y=3 -> sqrt(2*4)-1
  assert.ok(Math.abs(b.score - (Math.sqrt(8) - 1)) < 1e-12);
});

test('year range is inclusive and excludes outside years', () => {
  const rows = R.computeRankings(sel({ to: 2026 }), data, inst);
  const a = rows.find((r) => r.id === 'A');
  assert.ok(Math.abs(a.adjTotal - 102) < 1e-12);
  const only2021 = R.computeRankings(sel({ from: 2021, to: 2021 }), data, inst);
  assert.deepEqual(only2021.map((r) => r.id).sort(), ['B', 'C']);
});

test('ties share a rank and are ordered by name', () => {
  const rows = R.computeRankings(sel(), data, inst);
  assert.deepEqual(rows.map((r) => [r.id, r.rank]), [['B', 1], ['C', 1], ['A', 3], ['D', 4]]);
  assert.ok(rows[0].tied && rows[1].tied && !rows[2].tied);
});

test('region filters after scoring; empty country only in world', () => {
  const us = R.computeRankings(sel({ region: 'US' }), data, inst);
  assert.deepEqual(us.map((r) => r.id), ['C', 'A']);
  const na = R.computeRankings(sel({ region: 'northern-america' }), data, inst);
  assert.deepEqual(na.map((r) => r.id), ['C', 'A']);
  const eu = R.computeRankings(sel({ region: 'europe' }), data, inst);
  assert.deepEqual(eu.map((r) => r.id), ['B']);
  assert.ok(R.computeRankings(sel(), data, inst).some((r) => r.id === 'D'));
});

test('missing area data throws instead of ranking without it', () => {
  assert.throws(() => R.computeRankings(sel({ areas: ['x', 'missing'] }), data, inst), /not loaded/);
});

test('no areas selected yields no rows', () => {
  assert.deepEqual(R.computeRankings(sel({ areas: [] }), data, inst), []);
});

test('URL state round-trips and omits defaults', () => {
  const defaults = { from: 2016, to: 2025, region: 'US', areas: ['x', 'y'], disabledVenues: [] };
  const known = ['x', 'y', 'z'];
  assert.equal(R.encodeState({ ...defaults, region: 'US' }, defaults), '');
  const s = { from: 2010, to: 2026, region: 'europe', areas: ['z', 'x'], disabledVenues: ['x:v1'] };
  const h = R.encodeState(s, defaults);
  assert.equal(h, '#from=2010&to=2026&region=europe&areas=x,z&disabled_venues=x%3Av1');
  assert.deepEqual(R.decodeState(h, defaults, known), {
    from: 2010, to: 2026, region: 'europe', areas: ['x', 'z'], disabledVenues: ['x:v1'],
  });
  assert.deepEqual(R.decodeState('#areas=none', defaults, known).areas, []);
  // garbage is ignored, reversed years are swapped
  const g = R.decodeState('#from=2030&to=2001&region=<x>&areas=bogus&disabled_venues=invalid,x:ok', defaults, known);
  assert.deepEqual(g, { from: 2001, to: 2030, region: 'US', areas: ['x', 'y'], disabledVenues: ['x:ok'] });
});

test('CSV quotes fields and lists every ranked row', () => {
  const rows = R.computeRankings(sel(), data, {
    ...inst, A: { name: 'Alpha, "The" University', country: 'US' },
  });
  const csv = R.rankingsToCsv(rows, ['x', 'y']);
  const lines = csv.trim().split('\r\n');
  assert.equal(lines.length, rows.length + 1);
  assert.match(lines[0], /^rank,institution,openalex_id,country,score,adjusted_count_total,papers_total,areas_with_credit,adj_x,adj_y$/);
  assert.ok(lines.some((l) => l.includes('"Alpha, ""The"" University"')));
});

test('untrusted URL years cannot create an unbounded option list', () => {
  const defaults = { from: 2016, to: 2025, region: 'US', areas: ['x'], disabledVenues: [] };
  const value = R.decodeState('#from=-100000000&to=999999999', defaults, ['x']);
  assert.equal(value.from, 2016);
  assert.equal(value.to, 2025);
});

test('yearExtent spans loaded rows', () => {
  assert.deepEqual(R.yearExtent(data), { min: 2020, max: 2026 });
  assert.equal(R.yearExtent(new Map()), null);
});

// Cross-check against the real site data when it is present.
test('real data: default selection matches an independent computation', { skip: !existsSync(path.join(siteDir, 'data', 'areas.json')) }, () => {
  const registry = JSON.parse(readFileSync(path.join(siteDir, 'data', 'areas.json'), 'utf8'));
  const institutions = JSON.parse(readFileSync(path.join(siteDir, 'data', 'institutions.json'), 'utf8'));
  const areas = R.defaultAreaIds(R.listAreas(registry));
  assert.ok(!areas.includes('ml') && !areas.includes('flagship'));
  const d = new Map(areas.map((a) => [a, JSON.parse(readFileSync(path.join(siteDir, 'data', `${a}.json`), 'utf8'))]));
  const rows = R.computeRankings({ from: 2016, to: 2025, region: 'world', areas }, d, institutions);
  // independent: per-institution log-sum
  const per = new Map();
  areas.forEach((a) => {
    const sums = new Map();
    for (const r of d.get(a)) if (r.y >= 2016 && r.y <= 2025) sums.set(r.i, (sums.get(r.i) || 0) + r.a);
    for (const [i, v] of sums) per.set(i, (per.get(i) || 0) + Math.log1p(v));
  });
  assert.equal(rows.length, [...per.keys()].length);
  for (const r of rows.slice(0, 50)) {
    assert.ok(Math.abs(r.score - Math.expm1(per.get(r.id) / areas.length)) < 1e-9, r.name);
  }
  for (let i = 1; i < rows.length; i++) assert.ok(rows[i - 1].score >= rows[i].score);
});

test('granular venue data matches subset ranking', { skip: !existsSync(path.join(siteDir, 'data', 'circuits', 'jssc.json')) }, () => {
  const institutions = JSON.parse(readFileSync(path.join(siteDir, 'data', 'institutions.json'), 'utf8'));
  const jsscRows = JSON.parse(readFileSync(path.join(siteDir, 'data', 'circuits', 'jssc.json'), 'utf8'));
  const d = new Map([['circuits', jsscRows]]);
  const rows = R.computeRankings({ from: 2016, to: 2025, region: 'world', areas: ['circuits'] }, d, institutions);
  assert.ok(rows.length > 0);
  // Rank 1 institution has positive score
  assert.ok(rows[0].score > 0);
  assert.equal(rows[0].active, 1);
});
