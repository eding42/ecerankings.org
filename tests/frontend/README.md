Run the ranking and history checks without dependencies:

```sh
node --test tests/frontend/rank.test.mjs tests/test_rank_history.mjs
```

The optional responsive browser suite loads the real site and checked-in data
without a server or network requests. It checks 320–1440px layouts, touch targets,
expanded counts, area and venue selections, search, CSV downloads, shared links,
landscape, and pagination. It asserts that resizing preserves names and scores.

Install Playwright and its browsers in a temporary directory, keeping the static
site free of runtime dependencies:

```sh
npm install --prefix /tmp/ece-browser-check playwright
/tmp/ece-browser-check/node_modules/.bin/playwright install chromium firefox webkit
PLAYWRIGHT_MODULE=/tmp/ece-browser-check/node_modules/playwright \
  ECE_BROWSERS=chromium,firefox,webkit \
  ECE_SCREENSHOTS=.tmp/mobile-review \
  node --test tests/frontend/responsive.test.mjs
```

Linux may also need Playwright's browser system dependencies. `ECE_BROWSERS`
defaults to `chromium`; screenshots are optional. These are engine and touch
emulation checks; final device QA should include iOS Safari and Android Chrome.
