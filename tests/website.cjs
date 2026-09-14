const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, headless: true });
  const baseURL = process.env.SITE_URL || 'http://127.0.0.1:4178';
  const context = await browser.newContext({ viewport: {width: 1440, height: 1050}, permissions: ['clipboard-read','clipboard-write'] });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('requestfailed', request => errors.push(request.url()));
  await page.goto(baseURL, {waitUntil: 'networkidle'});
  await page.getByRole('button', {name: 'Pause animation'}).click();
  for (const element of await page.locator('.reveal').all()) { await element.scrollIntoViewIfNeeded(); await page.waitForTimeout(120); }
  await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
  await page.waitForTimeout(850);
  await page.screenshot({path: '/tmp/spotlight-desktop.png', fullPage: true});
  await page.locator('.scene[data-select="1"]').click();
  assert.equal(await page.locator('#demo-command').textContent(), 'spotlight on feature/navigation');
  assert.equal(await page.locator('#preview-branch').textContent(), 'feature/navigation');
  await page.locator('.scene[data-select="2"]').click();
  assert.equal(await page.locator('#demo-command').textContent(), 'spotlight off');
  assert.equal(await page.locator('#preview-branch').textContent(), 'main');
  await page.locator('#tab-herdr').click();
  assert.equal(await page.locator('#tool-label').textContent(), 'WORKING IN HERDR');
  await page.locator('#tab-herdr').press('ArrowRight');
  assert.equal(await page.locator('#tab-conductor').getAttribute('aria-selected'), 'true');
  assert.match(await page.locator('#tool-panel h3 + p').textContent(), /built-in Spotlight first/);
  await page.locator('[data-copy="agent-prompt"]').click();
  assert.match(await page.evaluate(() => navigator.clipboard.readText()), /Don’t start mirroring yet/);
  assert.equal(await page.locator('.quickstart-content>div').count(), 3);
  assert.match(await page.locator('.quickstart').textContent(), /Turn Spotlight off and restore my main checkout/);
  assert.equal(await page.locator('#install-command').count(), 0);
  assert.equal(await page.locator('header nav a').count(), 1);
  for (const button of await page.locator('[data-copy]').all()) {
    const target = await button.getAttribute('data-copy');
    await button.click();
    assert.equal(await page.evaluate(() => navigator.clipboard.readText()), (await page.locator(`#${target}`).textContent()).trim());
  }
  assert.equal(await page.locator('.prompt-callout').count(), 5);
  assert.doesNotMatch(await page.locator('body').innerText(), /Requires access to the private GitHub repository|\b0[123]\b/);
  assert.equal(await page.locator('.install-nav a').evaluate(el => getComputedStyle(el).borderBottomWidth), '0px');

  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({width, height: 900});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Overflow at ${width}px`);
  }
  await page.setViewportSize({width: 390, height: 844});
  await page.goto(baseURL, {waitUntil: 'networkidle'});
  await page.getByRole('button', {name: 'Pause animation'}).click();
  await page.locator('.install-nav a').click();
  assert.equal(new URL(page.url()).hash, '#install');
  for (const element of await page.locator('.reveal').all()) { await element.scrollIntoViewIfNeeded(); await page.waitForTimeout(120); }
  await page.evaluate(() => window.scrollTo({top: 0, behavior: 'instant'}));
  await page.waitForTimeout(850);
  await page.screenshot({path: '/tmp/spotlight-mobile.png', fullPage: true});
  const reduced = await browser.newContext({reducedMotion: 'reduce', viewport: {width: 1000, height: 800}});
  const staticPage = await reduced.newPage();
  await staticPage.goto(baseURL);
  assert(await staticPage.getByRole('button', {name: 'Play animation'}).isVisible());
  await staticPage.waitForTimeout(5200);
  assert.equal(await staticPage.locator('.demo').getAttribute('data-scene'), '0');
  const noScript = await browser.newContext({javaScriptEnabled: false});
  const fallback = await noScript.newPage();
  await fallback.goto(baseURL);
  assert(await fallback.locator('#agent-prompt').isVisible());
  assert.equal(await fallback.locator('.reveal').first().evaluate(el => getComputedStyle(el).opacity), '1');
  assert.deepEqual(errors, []);
  console.log('PASS: demo states, tool tabs and keyboard navigation, clipboard, mobile install link, four responsive widths, reduced motion, no-JS installation, and no browser errors.');
  await browser.close();
})().catch(error => {console.error(error); process.exit(1);});
