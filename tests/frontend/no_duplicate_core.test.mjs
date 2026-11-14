import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const siteDir = path.join(here, '..', '..', 'site');

const CORE_ENGINE_FILES = [
  'rank.js',
  'comparison.js',
  'comparison.css',
  'rank-history.js',
  'rank-history.css',
  'year-strip.js',
  'year-strip.css',
  'coverage.js',
];

test('shared core engine exists and exports lifecycle primitives', async () => {
  const enginePath = path.join(siteDir, 'core', 'engine.js');
  assert.ok(existsSync(enginePath), 'site/core/engine.js must exist');
  const engine = await import(new URL('../../site/core/engine.js', import.meta.url));
  assert.equal(typeof engine.initRankingsApp, 'function', 'initRankingsApp must be exported');
  assert.equal(typeof engine.init, 'function', 'init must be exported');
  assert.ok(engine.app && typeof engine.app === 'object', 'app state object must be exported');
});

test('sister sites do not duplicate core engine files', () => {
  for (const site of ['biology', 'earth-space']) {
    for (const file of CORE_ENGINE_FILES) {
      const duplicatePath = path.join(siteDir, site, file);
      assert.ok(
        !existsSync(duplicatePath),
        `site/${site}/${file} must not exist (should use shared site/core/${file})`
      );
    }
  }
});

test('site entrypoints are thin wrappers under 60 lines', () => {
  const entrypoints = [
    { rel: 'main.js', fieldId: 'ece' },
    { rel: 'biology/main.js', fieldId: 'biology' },
    { rel: 'earth-space/main.js', fieldId: 'earth-space' },
  ];

  for (const { rel, fieldId } of entrypoints) {
    const fullPath = path.join(siteDir, rel);
    assert.ok(existsSync(fullPath), `${rel} must exist`);
    const content = readFileSync(fullPath, 'utf8');
    const lines = content.split('\n').filter((l) => l.trim().length > 0);
    assert.ok(
      lines.length < 60,
      `${rel} should be a thin wrapper under 60 non-empty lines (found ${lines.length})`
    );
    assert.match(content, /initRankingsApp/, `${rel} must import and invoke initRankingsApp`);
    assert.match(
      content,
      new RegExp(`fieldId:\\s*['"]${fieldId}['"]`),
      `${rel} must configure fieldId '${fieldId}'`
    );
  }
});

test('discipline stylesheets deduplicate and import core/styles.css', () => {
  for (const rel of ['styles.css', 'biology/styles.css', 'earth-space/styles.css']) {
    const cssPath = path.join(siteDir, rel);
    assert.ok(existsSync(cssPath), `${rel} must exist`);
    const content = readFileSync(cssPath, 'utf8');
    assert.match(
      content,
      /@import\s+['"][^'"]*core\/styles\.css['"]/,
      `${rel} must import core/styles.css`
    );
  }
});

test('all script src and link href tags in site/**/*.html resolve to existing files', () => {
  const htmlFiles = [
    'index.html',
    'coverage.html',
    'methodology.html',
    '404.html',
    'biology/index.html',
    'biology/coverage.html',
    'biology/methodology.html',
    'earth-space/index.html',
    'earth-space/coverage.html',
    'earth-space/methodology.html',
  ];

  for (const rel of htmlFiles) {
    const fullPath = path.join(siteDir, rel);
    if (!existsSync(fullPath)) continue;
    const content = readFileSync(fullPath, 'utf8');
    const dir = path.dirname(fullPath);

    // Matches src="..." and href="..." for local assets (not http/https or # or mailto)
    const matches = content.matchAll(/(?:src|href)=["']([^"':#]+)["']/g);
    for (const match of matches) {
      let asset = match[1].split('?')[0]; // Strip query params like ?v=...
      if (!asset || asset.endsWith('.html') || asset.endsWith('/') || asset === './' || asset === '../' || asset === '/') {
        continue;
      }
      const assetPath = asset.startsWith('/')
        ? path.resolve(siteDir, '.' + asset)
        : path.resolve(dir, asset);
      assert.ok(
        existsSync(assetPath),
        `Asset '${asset}' referenced in ${rel} does not exist at ${assetPath}`
      );
    }
  }
});
