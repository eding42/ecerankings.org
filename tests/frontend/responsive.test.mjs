// Browser regression checks against the real static site and checked-in data.
// Install Playwright outside the repo, then set PLAYWRIGHT_MODULE to its package
// directory, or install it locally. See README.md in this directory.
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
let engines;
try { engines = require(process.env.PLAYWRIGHT_MODULE || 'playwright'); }
catch (error) {
  if (process.env.PLAYWRIGHT_MODULE || error.code !== 'MODULE_NOT_FOUND') throw error;
}
const site = fileURLToPath(new URL('../../site/', import.meta.url));
const screenshots = process.env.ECE_SCREENSHOTS;
const widths = [320, 360, 375, 390, 412, 600, 601, 768, 899, 900, 1280, 1440];

async function screenshot(page, name) {
  if (!screenshots) return;
  await mkdir(screenshots, { recursive: true });
  await page.screenshot({ path: path.join(screenshots, `${name}.png`) });
}

async function ready(page) {
  await page.waitForFunction(() => document.querySelector('.inst-row') &&
    document.querySelector('#ranking-table').getAttribute('aria-busy') === 'false');
}

async function assertFits(page) {
  const size = await page.evaluate(() => {
    const scroller = document.querySelector('.table-scroll');
    return {
      viewport: innerWidth, page: document.documentElement.scrollWidth,
      table: scroller.scrollWidth, available: scroller.clientWidth,
      tableRight: document.querySelector('.ranking').getBoundingClientRect().right,
      scoreRight: document.querySelector('.ranking > thead th:nth-child(3)').getBoundingClientRect().right,
    };
  });
  assert.ok(size.page <= size.viewport + 1, `page overflows: ${JSON.stringify(size)}`);
  assert.ok(size.table <= size.available + 1, `table overflows: ${JSON.stringify(size)}`);
  if (size.viewport <= 600) {
    assert.ok(Math.abs(size.tableRight - size.scoreRight) <= 1, `hidden columns waste table space: ${JSON.stringify(size)}`);
  }
}

for (const name of (process.env.ECE_BROWSERS || 'chromium').split(',')) {
  test(`${name}: responsive rankings`, {
    timeout: 120_000,
    skip: !engines && 'Optional Playwright dependency is not installed; see tests/frontend/README.md.',
  }, async (t) => {
    const browser = await engines[name].launch();
    t.after(() => browser.close());
    const context = await browser.newContext({
      viewport: { width: 390, height: 844 }, hasTouch: true,
      ...(name === 'firefox' ? {} : { isMobile: true }),
      deviceScaleFactor: 1,
    });
    t.after(() => context.close());
    // Serve local files without an external server or network. Missing resources
    // remain real 404s; no substitute CSS, markup or ranking data is injected.
    const serveSite = async (route) => {
      const pathname = new URL(route.request().url()).pathname;
      const filename = path.resolve(site, `.${pathname === '/' ? '/index.html' : pathname}`);
      assert.ok(filename.startsWith(site));
      try { await route.fulfill({ path: filename }); }
      catch { await route.fulfill({ status: 404, body: 'Not found' }); }
    };
    await context.route('http://ece.test/**', serveSite);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    await page.goto('http://ece.test/');
    await ready(page);
    const initialRows = await page.locator('.inst-row').evaluateAll((rows) =>
      rows.map((row) => [row.querySelector('.inst').textContent, row.querySelector('.score').textContent]));

    for (const width of widths) {
      await t.test(`${width}px layout and controls`, async () => {
        await page.setViewportSize({ width, height: 844 });
        await assertFits(page);
        assert.equal(await page.locator('#areas-panel').evaluate((el) => el.open), width >= 900);
        assert.equal(await page.locator('.ranking > thead th:visible').count(), width <= 600 ? 3 : 5);
        assert.equal(await page.locator('#area-count').textContent(), '18 of 20');
        assert.deepEqual(await page.locator('.inst-row').evaluateAll((rows) =>
          rows.map((row) => [row.querySelector('.inst').textContent, row.querySelector('.score').textContent])), initialRows);
        if (width <= 600) {
          for (const selector of ['#region', '#year-from', '#year-to', '#search', '#export', '.areas summary', '.site-header nav a']) {
            for (const el of await page.locator(selector).all()) {
              assert.ok((await el.boundingBox()).height >= 43.99, `${selector}: small tap target`);
            }
          }
          assert.ok(await page.locator('#search').evaluate((el) => parseFloat(getComputedStyle(el).fontSize) >= 16));
        }
        if ([320, 390, 768, 1280].includes(width)) await screenshot(page, `${name}-${width}`);
      });
    }

    await t.test('phone details preserve totals and all per-area counts', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator('.inst').first().tap();
      assert.equal(await page.locator('.inst').first().getAttribute('aria-expanded'), 'true');
      assert.equal(await page.locator('.institution-totals:visible').count(), 1);
      assert.equal(await page.locator('.breakdown thead th:visible').count(), 3);
      assert.equal(await page.locator('.breakdown tbody tr').count(), 18);
      await assertFits(page);
      await page.locator('.inst-row').first().evaluate((el) => el.scrollIntoView({ block: 'start' }));
      await screenshot(page, `${name}-390-details`);
      await page.setViewportSize({ width: 320, height: 667 });
      await assertFits(page);
      await page.setViewportSize({ width: 900, height: 667 });
      assert.equal(await page.locator('.detail > td').getAttribute('colspan'), '5');
      await assertFits(page);
      await page.setViewportSize({ width: 320, height: 667 });
      assert.equal(await page.locator('.detail > td').getAttribute('colspan'), '3');
      await assertFits(page);
      await page.locator('.inst').first().tap();
      assert.equal(await page.locator('.detail').count(), 0);
    });

    await t.test('touch area and venue controls, keyboard focus, and empty state', async () => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.locator('.areas summary').tap();
      await page.locator('[data-area-toggle="circuits"]').tap();
      assert.equal(await page.locator('[data-area-toggle="circuits"]').evaluate((el) => el === document.activeElement), true);
      for (const selector of ['.area-venues-toggle', '.area-header label', '.venue-row label', '.area-actions button', '.group-actions button']) {
        for (const el of await page.locator(`${selector}:visible`).all()) {
          assert.ok((await el.boundingBox()).height >= 43.99, `${selector}: small tap target`);
        }
      }
      await page.locator('label[for="venue-circuits-jssc"]').tap();
      await ready(page);
      assert.ok(page.url().includes('disabled_venues=circuits%3Ajssc'));
      assert.equal(await page.locator('#area-circuits').evaluate((el) => el.indeterminate), true);
      await assertFits(page);
      await screenshot(page, `${name}-390-areas`);
      await page.locator('[data-select="none"]').tap();
      assert.equal(await page.locator('.inst-row').count(), 0);
      assert.equal(await page.locator('#area-count').textContent(), '0 of 20');
      assert.equal(await page.locator('#export').isDisabled(), true);
      assert.equal(await page.locator('#pager').isVisible(), false);
      await page.locator('[data-select="defaults"]').tap();
      await ready(page);
      await page.locator('#areas-done').tap();
      assert.equal(await page.locator('#areas-panel').evaluate((el) => el.open), false);
      assert.equal(await page.locator('.areas summary').evaluate((el) => el === document.activeElement), true);
      assert.ok((await page.locator('.areas summary').boundingBox()).y >= -1);
      await assertFits(page);
    });

    await t.test('search keyboard, region, year range, export, and shared state', async () => {
      await page.locator('#region').selectOption('GB');
      await ready(page);
      await page.locator('#year-from').selectOption('2020');
      await page.locator('#year-to').selectOption('2024');
      await ready(page);
      await page.locator('#search').fill('Cambridge');
      assert.ok(await page.locator('.inst-row').count() > 0);
      for (const name of await page.locator('.inst').allTextContents()) assert.match(name, /cambridge/i);
      await page.locator('#search').press('Enter');
      assert.notEqual(await page.evaluate(() => document.activeElement.id), 'search');
      const downloadPromise = page.waitForEvent('download');
      await page.locator('#export').tap();
      const download = await downloadPromise;
      assert.equal(download.suggestedFilename(), 'ecerankings-GB-2020-2024.csv');
      await page.reload();
      await ready(page);
      assert.equal(await page.locator('#region').inputValue(), 'GB');
      assert.equal(await page.locator('#year-from').inputValue(), '2020');
      assert.equal(await page.locator('#year-to').inputValue(), '2024');
      await page.locator('#search').fill('NoSuchInstitution_12345');
      assert.equal(await page.locator('.inst-row').count(), 0);
      assert.match(await page.locator('#status').textContent(), /^0 of /);
      assert.equal(await page.locator('#pager').isVisible(), false);
    });

    await t.test('landscape and pagination', async () => {
      await page.goto('http://ece.test/');
      await ready(page);
      await page.setViewportSize({ width: 844, height: 390 });
      await assertFits(page);
      await page.locator('#show-more').tap();
      assert.equal(await page.locator('.inst-row').count(), 200);
      await page.locator('#show-all').tap();
      assert.ok(await page.locator('.inst-row').count() > 200);
      assert.equal(await page.locator('#pager').isVisible(), false);
      await assertFits(page);
    });

    await t.test('desktop mouse layout and expanded details', async () => {
      const desktop = await browser.newPage({ viewport: { width: 1280, height: 900 } });
      try {
        await desktop.route('http://ece.test/**', serveSite);
        await desktop.goto('http://ece.test/');
        await ready(desktop);
        await assertFits(desktop);
        assert.equal(await desktop.locator('#areas-panel').evaluate((el) => el.open), true);
        await screenshot(desktop, `${name}-desktop`);
        await desktop.locator('.inst').first().click();
        await assertFits(desktop);
      } finally { await desktop.close(); }
    });

    await t.test('runtime has no JavaScript errors', () => assert.deepEqual(errors, []));
  });
}
