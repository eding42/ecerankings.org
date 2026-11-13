#!/usr/bin/env node
// Write the default ranking into site/index.html, so the institution names
// are in the page before any script runs. Uses site/rank.js, so the rows are
// the ones the browser computes for the default selection.
//
//   node pipeline/prerender_site.mjs           rewrite site/index.html
//   node pipeline/prerender_site.mjs --check   exit 1 if it is out of date

import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const ORIGIN = 'https://ecerankings.eding.dev/';
const PAGE_SIZE = 100; // matches site/main.js
const DEFAULT_REGION = 'US';

const fmt1 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmt2 = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });
const countryNames = new Intl.DisplayNames(['en'], { type: 'region' });
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function replaceOnce(html, pattern, replacement, what) {
  const found = html.match(new RegExp(pattern.source, pattern.flags.replace('g', '') + 'g')) || [];
  if (found.length !== 1) throw new Error(`index.html: expected one ${what}, found ${found.length}`);
  return html.replace(pattern, () => replacement);
}

// Same markup as renderTable() in site/main.js, for a collapsed row.
function rowHtml(r) {
  const did = `detail-${r.id.replace(/\\W/g, '')}`;
  return '<tr class="inst-row">' +
    `<td class="num rank">${r.tied ? `<span title="Tied">${r.rank}</span>` : r.rank}</td>` +
    `<td class="name"><div class="inst-name-line"><span class="inst-name-main"><button type="button" class="inst" data-id="${esc(r.id)}" aria-expanded="false" aria-controls="${did}">` +
    `<span class="tri" aria-hidden="true">▸</span>${esc(r.name)}</button>` +
    (r.country ? ` <abbr class="cc" title="${esc(countryNames.of(r.country) || r.country)}">${esc(r.country)}</abbr>` : '') +
    '</span></div></td>' +
    `<td class="num score">${fmt2.format(r.score)}</td>` +
    `<td class="num opt">${fmt1.format(r.adjTotal)}</td>` +
    `<td class="num opt">${fmtInt.format(r.pubTotal)}</td></tr>`;
}

export async function render(siteDir = path.join(ROOT, 'site')) {
  const read = (rel) => readFileSync(path.join(siteDir, rel));
  const json = (rel) => JSON.parse(read(rel).toString('utf8'));
  const R = await import('data:text/javascript,' + encodeURIComponent(read('rank.js').toString('utf8')));

  const manifestBytes = read('data/manifest.json');
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  const manifestHash = createHash('sha256').update(manifestBytes).digest('hex');
  const to = Number(manifest.latest_complete_year);
  if (!Number.isInteger(to)) throw new Error('manifest.json: latest_complete_year is missing');
  const generated = String(manifest.generated_at || '').slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(generated)) throw new Error('manifest.json: generated_at is missing');

  const registry = json('data/areas.json');
  const allAreas = R.listAreas(registry);
  const areas = R.defaultAreaIds(allAreas);
  const sel = { from: to - 9, to, region: DEFAULT_REGION, areas, disabledVenues: [] };
  const data = new Map(areas.map((id) => [id, json(`data/${id}.json`)]));
  const rows = R.computeRankings(sel, data, json('data/institutions.json')).slice(0, PAGE_SIZE);
  if (rows.length < PAGE_SIZE) throw new Error(`Only ${rows.length} institutions ranked`);
  const extent = R.yearExtent(new Map(allAreas.map((a) => [a.id, json(`data/${a.id}.json`)])));

  const updated = new Date(`${generated}T00:00:00Z`)
    .toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
  const description = 'Institutions ranked by papers in selective electrical and computer engineering journals and conferences, ' +
    'by research area and year. Each paper is worth 1, split evenly among its authors and credited to the institutions they listed.';
  const graph = [
    { '@type': 'WebSite', '@id': `${ORIGIN}#website`, name: 'ECERankings', url: ORIGIN },
    {
      '@type': 'Dataset', '@id': `${ORIGIN}#dataset`,
      name: 'ECERankings: research output of electrical and computer engineering institutions',
      description, url: ORIGIN,
      keywords: ['electrical and computer engineering', 'ECE rankings', 'graduate program rankings', 'research output', 'university rankings'],
      creator: { '@type': 'Person', name: 'Edward Ding', url: 'https://eding.dev/' },
      isBasedOn: ['https://openalex.org/', 'https://www.crossref.org/'],
      isAccessibleForFree: true,
      temporalCoverage: `${extent.min}/${extent.max}`,
      dateModified: generated,
      includedInDataCatalog: { '@id': `${ORIGIN}#website` },
    },
    {
      '@type': 'ItemList', '@id': `${ORIGIN}#ranking`,
      name: `Top ${rows.length} US institutions in electrical and computer engineering research, ${sel.from}–${sel.to}`,
      itemListOrder: 'https://schema.org/ItemListOrderAscending',
      numberOfItems: rows.length,
      itemListElement: rows.map((r) => ({ '@type': 'ListItem', position: r.rank, name: r.name })),
    },
  ];
  const ld = JSON.stringify({ '@context': 'https://schema.org', '@graph': graph }).replace(/</g, '\\u003c');

  let html = read('index.html').toString('utf8');
  html = replaceOnce(html, /<script type="application\/ld\+json">[\s\S]*?<\/script>/,
    `<script type="application/ld+json">${ld}</script>`, 'structured-data script');
  html = replaceOnce(html, /<p class="stamp" id="data-stamp">[^<]*<\/p>/,
    `<p class="stamp" id="data-stamp">Updated ${updated}</p>`, 'data stamp');
  html = replaceOnce(html, /<tbody id="ranking-body"[^>]*>[\s\S]*?<\/tbody>/,
    `<tbody id="ranking-body" data-prerender="${manifestHash}">\n${rows.map(rowHtml).join('\n')}\n</tbody>`, 'ranking body');
  return html;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const target = path.join(ROOT, 'site', 'index.html');
  const html = await render();
  const current = readFileSync(target, 'utf8');
  if (process.argv.includes('--check')) {
    if (html !== current) {
      console.error('site/index.html is out of date. Run: node pipeline/prerender_site.mjs');
      process.exit(1);
    }
    console.log('site/index.html matches the current data.');
  } else if (html === current) {
    console.log('site/index.html already matches the current data.');
  } else {
    writeFileSync(target, html);
    console.log('Wrote the default ranking into site/index.html.');
  }
}
