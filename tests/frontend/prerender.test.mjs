// The generated pages must match what the browser computes for the default
// selection. Run: node --test tests/frontend/prerender.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { build, slugOf, staleFolders } from '../../pipeline/prerender_site.mjs';

const siteDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'site');
const files = await build(siteDir);
const html = readFileSync(path.join(siteDir, 'index.html'), 'utf8');
const fix = 'Run: node pipeline/prerender_site.mjs';

test('generated files match the checked-in data', () => {
  for (const [rel, text] of files) assert.equal(readFileSync(path.join(siteDir, rel), 'utf8'), text, `${rel} is out of date. ${fix}`);
  assert.deepEqual(staleFolders(siteDir, files), [], fix);
});

test('index.html lists 100 ranked institutions and valid structured data', () => {
  const rows = html.match(/<tr class="inst-row">/g) || [];
  assert.equal(rows.length, 100);
  const ld = JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(html)[1]);
  const list = ld['@graph'].find((n) => n['@type'] === 'ItemList');
  assert.equal(list.itemListElement.length, 100);
  assert.equal(list.itemListElement[0].position, 1);
  assert.ok(html.includes(`>${list.itemListElement[0].name.replace(/&/g, '&amp;')}</button>`));
});

test('each institution has a page with the rank shown in the table, linked from the index and the sitemap', () => {
  const pages = [...files.keys()].filter((f) => /^institution\/[^/]+\/index\.html$/.test(f));
  assert.equal(pages.length, 100);
  const first = /<tr class="inst-row"><td class="num rank">(?:<span[^>]*>)?(\d+).*?<\/span>([^<]+)<\/button>.*?<td class="num score">([\d.,]+)</.exec(html);
  const page = files.get(`institution/${slugOf(first[2].replace(/&amp;/g, '&'))}/index.html`);
  assert.ok(page.includes(`<h1>${first[2]}</h1>`));
  assert.ok(page.includes(`<dd>#${first[1]}<small> of `) && page.includes(`<dd>${first[3]}</dd>`));
  for (const rel of pages) {
    const href = `/${rel.replace(/index\.html$/, '')}`;
    assert.ok(files.get('institution/index.html').includes(`href="${href}"`), `${href} missing from the index`);
    assert.ok(files.get('sitemap.xml').includes(`<loc>https://ecerankings.eding.dev${href}</loc>`), `${href} missing from the sitemap`);
    JSON.parse(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/.exec(files.get(rel))[1]);
  }
});

test('slugs are plain ASCII', () => {
  assert.equal(slugOf('Texas A&M University'), 'texas-a-and-m-university');
  assert.equal(slugOf('École Polytechnique, Montréal'), 'ecole-polytechnique-montreal');
});
