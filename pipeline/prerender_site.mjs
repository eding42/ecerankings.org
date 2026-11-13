#!/usr/bin/env node
// Write the default ranking into site/index.html, so the institution names
// are in the page before any script runs, plus one page per ranked institution
// under site/institution/ and the sitemap that lists them. Uses site/rank.js,
// so the numbers are the ones the browser computes for the default selection.
//
//   node pipeline/prerender_site.mjs           rewrite the generated files
//   node pipeline/prerender_site.mjs --check   exit 1 if any is out of date

import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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
    `<td class="num opt">${fmtInt.format(r.pubTotal)}</td>` +
    '<td class="num opt trend-cell"></td></tr>'; // main.js fills the trend in once it has computed it
}

export const slugOf = (name) => name.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
  .replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

// Site-relative links in a fragment of index.html, made root-relative.
const rooted = (html) => html
  .replace(/ aria-current="page"/g, '')
  .replace(/href="(?!https?:|\/|#)([^"]*)"/g, (m, href) => `href="/${href === './' ? '' : href.replace(/\.html$/, '')}"`);

function page({ title, description, url, ld, header, footer, version, body, mainClass = 'wrap prose' }) {
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>${esc(title)}</title>
  <meta name="description" content="${esc(description)}">
  <meta name="color-scheme" content="light dark">
  <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#141619" media="(prefers-color-scheme: dark)">
  <link rel="icon" href="/favicon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="ECERankings">
  <meta property="og:title" content="${esc(title)}">
  <meta property="og:description" content="${esc(description)}">
  <meta property="og:url" content="${url}">
  <meta property="og:image" content="${ORIGIN}og.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <link rel="canonical" href="${url}">
  <script type="application/ld+json">${JSON.stringify(ld).replace(/</g, '\\u003c')}</script>
  <link rel="stylesheet" href="/styles.css?v=${version}">
</head>
<body>
  ${header}

  <main class="${mainClass}">
${body}
  </main>

  ${footer}
</body>
</html>
`;
}

// Rank in each year, best at the top. Every point carries its rank as text.
function yearChart(history, name) {
  const pts = history.filter((h) => h.rank !== null);
  if (pts.length < 2) return '';
  // Same visual language as the table's annual-rank sparkline (rank-history.js): a thin line, rank 1 at the
  // top, only the latest rank labelled (the axis gives the rest), every year on hover or focus.
  const W = 420, H = 160, left = 36, right = 36, top = 12, bottom = 24;
  const best = Math.min(...pts.map((h) => h.rank)), worst = Math.max(...pts.map((h) => h.rank));
  // At least four ranks of height, so a move between #1 and #2 doesn't read as a collapse.
  const pad = Math.max(1, Math.round((worst - best) * 0.1));
  let lo = Math.max(1, best - pad), hi = Math.max(worst + pad, lo + 4);
  const step = [1, 2, 5, 10, 20, 50, 100, 200, 500].find((n) => (hi - lo) / n <= 4) ?? 1000;
  lo = Math.max(1, Math.floor(lo / step) * step); hi = Math.ceil(hi / step) * step;
  const x = (i) => left + (i * (W - left - right)) / (history.length - 1);
  const y = (rank) => top + ((rank - lo) / (hi - lo)) * (H - top - bottom);
  const f = (n) => n.toFixed(1);
  const ticks = lo === 1 ? [1] : [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) if (t >= 1 && (ticks.length === 0 || t - ticks.at(-1) >= step * 0.75)) ticks.push(t);
  let d = '', pen = false;
  history.forEach((h, i) => {
    if (h.rank === null) { pen = false; return; }
    d += `${pen ? 'L' : 'M'}${f(x(i))},${f(y(h.rank))}`;
    pen = true;
  });
  const firstI = history.findIndex((h) => h.rank !== null), lastI = history.findLastIndex((h) => h.rank !== null);
  const points = history.map((h, i) => {
    if (h.rank === null) return '';
    const px = x(i), py = y(h.rank), tipY = py - 12 < top ? py + 20 : py - 10;
    const end = i === firstI || i === lastI ? ' end' : '';
    return `<g class="pt${end}" tabindex="0"><title>${h.year}: #${h.rank}</title>` +
      `<circle class="hit" cx="${f(px)}" cy="${f(py)}" r="10"/><circle class="dot" cx="${f(px)}" cy="${f(py)}" r="3"/>` +
      `<text class="tip" x="${f(px)}" y="${f(tipY)}" text-anchor="middle">${h.year} · #${h.rank}</text></g>`;
  }).join('');
  return `<svg class="inst-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`${name}: US rank by year. ${history.map((h) => `${h.year} ${h.rank === null ? 'unranked' : `#${h.rank}`}`).join(', ')}`)}">` +
    ticks.map((t) => `<line class="g" x1="${left}" x2="${W - right}" y1="${f(y(t))}" y2="${f(y(t))}"/><text class="a" x="${left - 10}" y="${f(y(t) + 4)}" text-anchor="end">#${t}</text>`).join('') +
    `<text class="a" x="${f(x(0))}" y="${H - 4}" text-anchor="middle">${history[0].year}</text>` +
    `<text class="a" x="${f(x(history.length - 1))}" y="${H - 4}" text-anchor="middle">${history.at(-1).year}</text>` +
    `<path class="line" d="${d}"/>${points}` +
    `<text class="v now" x="${f(x(lastI) + 8)}" y="${f(y(history[lastI].rank) + 4)}">#${history[lastI].rank}</text></svg>`;
}

export async function build(siteDir = path.join(ROOT, 'site')) {
  const read = (rel) => readFileSync(path.join(siteDir, rel));
  const json = (rel) => JSON.parse(read(rel).toString('utf8'));
  const load = (rel) => import('data:text/javascript,' + encodeURIComponent(read(rel).toString('utf8')));
  const R = await load('rank.js');
  const H = await load('rank-history.js');

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
  const institutions = json('data/institutions.json');
  const ranked = R.computeRankings(sel, data, institutions);
  const rows = ranked.slice(0, PAGE_SIZE);
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
  const files = new Map([['index.html', html]]);

  // ---- One page per ranked institution ----
  const header = rooted(/<header class="site-header">[\s\S]*?<\/header>/.exec(html)[0]);
  const footer = rooted(/<footer class="site-footer">[\s\S]*?<\/footer>/.exec(html)[0]).replace(/\s*<noscript>[\s\S]*?<\/noscript>/, '');
  const version = /styles\.css\?v=([\w-]+)/.exec(html)[1];
  const areaRank = R.areaRanks(ranked);
  const annual = H.computeAnnualRanks({
    startYear: sel.from, endYear: sel.to, rankForResult: (row) => row.rank,
    rankingsForYear: (year) => R.computeRankings({ ...sel, from: year, to: year }, data, institutions),
  });
  const areaName = new Map(allAreas.map((a) => [a.id, a.name]));
  const scope = `US institutions in electrical and computer engineering research, ${sel.from}–${sel.to}`;
  const scopeLine = `Electrical and computer engineering research, ${sel.from}–${sel.to}.`;
  const slugs = rows.map((r) => slugOf(r.name));
  if (new Set(slugs).size !== slugs.length || slugs.some((s) => !s)) throw new Error('Institution slugs are not unique');
  const urlOf = (i) => `${ORIGIN}institution/${slugs[i]}/`;
  const link = (i) => `<a href="/institution/${slugs[i]}/">${esc(rows[i].name)}</a>`;
  const crumbs = (items) => ({
    '@type': 'BreadcrumbList',
    itemListElement: items.map(([name, item], i) => ({ '@type': 'ListItem', position: i + 1, name, item })),
  });

  const card = (i, dir) => i < 0 || i >= rows.length ? '<span></span>'
    : `<a class="inst-near ${dir}" href="/institution/${slugs[i]}/"><span class="k">${dir === 'prev' ? '← ' : ''}#${rows[i].rank}${dir === 'next' ? ' →' : ''}</span>${esc(rows[i].name)}</a>`;

  rows.forEach((r, i) => {
    const byRank = r.perArea.map((a) => ({ ...a, name: areaName.get(a.area), rank: a.adj > 0 ? areaRank.get(a.area)?.get(r.id) ?? null : null }))
      .sort((p, q) => (p.rank ?? Infinity) - (q.rank ?? Infinity));
    const maxAdj = Math.max(...byRank.map((a) => a.adj));
    const areaRows = byRank.map((a) =>
      `        <tr${a.rank ? '' : ' class="zero"'}><th scope="row">${esc(a.name)}</th>` +
      `<td class="num${a.rank && a.rank <= 10 ? ' top' : ''}">${a.rank ? `#${a.rank}` : '–'}</td>` +
      `<td class="bar"><span style="width:${((100 * a.adj) / maxAdj).toFixed(1)}%"></span></td>` +
      `<td class="num">${fmt1.format(a.adj)}</td><td class="num">${fmtInt.format(a.pubs)}</td></tr>`).join('\n');
    const history = H.institutionHistory(annual, r.id);
    const description = `${r.name} ranks #${r.rank} of ${fmtInt.format(ranked.length)} ${scope}, with its rank in each research area and year.`;
    files.set(`institution/${slugs[i]}/index.html`, page({
      title: `${r.name} ECE research ranking · ECERankings`,
      description, url: urlOf(i), header, footer, version, mainClass: 'wrap inst-page',
      ld: { '@context': 'https://schema.org', '@graph': [
        { '@type': 'WebPage', '@id': urlOf(i), url: urlOf(i), name: `${r.name} ECE research ranking`, description, dateModified: generated,
          isPartOf: { '@id': `${ORIGIN}#website` }, about: { '@type': 'CollegeOrUniversity', name: r.name, sameAs: r.id } },
        crumbs([['Rankings', ORIGIN], ['Institutions', `${ORIGIN}institution/`], [r.name, urlOf(i)]]),
      ] },
      body: `    <p class="crumb"><a href="/institution/">Institutions</a></p>
    <h1>${esc(r.name)}</h1>
    <p class="lede">${scopeLine}</p>

    <dl class="inst-stats">
      <div class="lead"><dt>US rank</dt><dd>#${r.rank}<small> of ${fmtInt.format(ranked.length)}</small></dd></div>
      <div><dt><a href="/methodology">Score</a></dt><dd>${fmt2.format(r.score)}</dd></div>
      <div><dt>Adjusted count</dt><dd>${fmt1.format(r.adjTotal)}</dd></div>
      <div><dt>Papers</dt><dd>${fmtInt.format(r.pubTotal)}</dd></div>
    </dl>

    <div class="inst-grid">
      <section>
        <h2>By research area</h2>
        <table class="inst-areas">
          <thead><tr><th scope="col">Area</th><th scope="col" class="num">US rank</th><th scope="col" colspan="2" class="num">Adj. count</th><th scope="col" class="num">Papers</th></tr></thead>
          <tbody>
${areaRows}
          </tbody>
        </table>
      </section>
      <section>
        <h2>US rank by year</h2>
        ${yearChart(history, r.name)}
        <p class="inst-open"><a href="/#open=${esc(r.id.replace('https://openalex.org/', ''))}">Open in the rankings table</a> to change the region, years or areas.</p>
        <nav class="inst-nears" aria-label="Ranked next to it">${card(i - 1, 'prev')}${card(i + 1, 'next')}</nav>
      </section>
    </div>
    <p class="stamp">Updated ${updated}</p>`,
    }));
  });

  const listUrl = `${ORIGIN}institution/`;
  const listDescription = `The top ${rows.length} ${scope}, each with its rank by research area and by year.`;
  files.set('institution/index.html', page({
    title: `Top ${rows.length} US institutions in ECE research · ECERankings`,
    description: listDescription, url: listUrl, header, footer, version,
    ld: { '@context': 'https://schema.org', '@graph': [
      { '@type': 'CollectionPage', '@id': listUrl, url: listUrl, name: `Top ${rows.length} US institutions in ECE research`, description: listDescription,
        dateModified: generated, isPartOf: { '@id': `${ORIGIN}#website` } },
      crumbs([['Rankings', ORIGIN], ['Institutions', listUrl]]),
    ] },
    body: `    <h1>Institutions</h1>
    <p class="lede">The top ${rows.length} ${scope}.</p>
    <p class="stamp">Updated ${updated}</p>
    <ol class="inst-index">
${rows.map((r, i) => `      <li><span class="n">${r.rank}</span>${link(i)}<span class="s">${fmt2.format(r.score)}</span></li>`).join('\n')}
    </ol>`,
    mainClass: 'wrap inst-page',
  }));

  const locs = ['', 'methodology', 'coverage', 'biology/', 'earth-space/', 'institution/', ...slugs.map((s) => `institution/${s}/`)];
  files.set('sitemap.xml', `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${locs.map((l) => `  <url><loc>${ORIGIN}${l}</loc></url>`).join('\n')}
</urlset>
`);
  return files;
}

// Generated institution folders on disk that the current data no longer produces.
export function staleFolders(siteDir, files) {
  const dir = path.join(siteDir, 'institution');
  if (!existsSync(dir)) return [];
  return readdirSync(dir, { withFileTypes: true })
    .filter((e) => e.isDirectory() && !files.has(`institution/${e.name}/index.html`)).map((e) => e.name);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const siteDir = path.join(ROOT, 'site');
  const files = await build(siteDir);
  const changed = [...files].filter(([rel, text]) => {
    const target = path.join(siteDir, rel);
    return !existsSync(target) || readFileSync(target, 'utf8') !== text;
  });
  const stale = staleFolders(siteDir, files);
  if (process.argv.includes('--check')) {
    if (changed.length || stale.length) {
      console.error(`${changed.length + stale.length} generated files are out of date. Run: node pipeline/prerender_site.mjs`);
      process.exit(1);
    }
    console.log(`${files.size} generated files match the current data.`);
  } else {
    for (const [rel, text] of changed) {
      mkdirSync(path.dirname(path.join(siteDir, rel)), { recursive: true });
      writeFileSync(path.join(siteDir, rel), text);
    }
    for (const name of stale) rmSync(path.join(siteDir, 'institution', name), { recursive: true });
    console.log(`Wrote ${changed.length} of ${files.size} generated files; removed ${stale.length} stale.`);
  }
}
