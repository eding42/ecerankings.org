// The ranking written into site/index.html must be the one the browser
// computes for the default selection. Run: node --test tests/frontend/prerender.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { render } from '../../pipeline/prerender_site.mjs';

const siteDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'site');
const html = readFileSync(path.join(siteDir, 'index.html'), 'utf8');

test('index.html matches the checked-in data', async () => {
  assert.equal(html, await render(siteDir), 'Run: node pipeline/prerender_site.mjs');
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
