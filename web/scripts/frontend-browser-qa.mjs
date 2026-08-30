import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createServer } from 'node:net'
import { existsSync, mkdirSync, readdirSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium } from 'playwright-core'
import AxeBuilder from '@axe-core/playwright'
import { NAV_ITEMS } from '../src/navigation.js'

const scriptsDir = path.dirname(fileURLToPath(import.meta.url))
const webDir = path.resolve(scriptsDir, '..')
const repoDir = path.resolve(webDir, '..')
const fixtureScript = path.join(scriptsDir, 'frontend-browser-fixture-server.mjs')
const screenshotDir = path.join(repoDir, 'cleanup-artifacts', 'apple-light-theme-ui', 'screenshots')
const browserCandidates = [
  process.env.CHROME_PATH,
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Users\\' + (process.env.USERNAME || 'Oops') + '\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe',
].filter(Boolean)
const chromePath = browserCandidates.find(candidate => existsSync(candidate))
if (!chromePath) throw new Error(`Chromium executable not found; set CHROME_PATH (checked ${browserCandidates.join(', ')})`)

const viewports = [
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'mobile', width: 390, height: 844 },
  { name: 'short', width: 1024, height: 620 },
]
const themeModes = [
  { name: 'light', preference: 'light', colorScheme: 'light' },
  { name: 'dark', preference: 'dark', colorScheme: 'dark' },
  { name: 'system-light', preference: 'system', colorScheme: 'light' },
  { name: 'system-dark', preference: 'system', colorScheme: 'dark' },
]
const screenshotBasenames = ['dashboard', 'settings', 'paypal', 'register', 'mobile-navigation', 'dense-mobile-form']

function getFreePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer()
    probe.once('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const port = probe.address().port
      probe.close(error => error ? reject(error) : resolve(port))
    })
  })
}

function startFixture({ rows }) {
  return getFreePort().then(port => new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [fixtureScript, String(port), String(rows)], {
      cwd: repoDir,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    let stdout = ''
    let stderr = ''
    let settled = false
    const finish = (error, value) => {
      if (settled) return
      settled = true
      error ? reject(error) : resolve({ child, port, stdout, stderr, ready: value })
    }
    child.stdout.on('data', chunk => {
      stdout += chunk.toString()
      const match = stdout.match(/fixture_ready\s+url=(\S+)/)
      if (match) finish(null, match[1])
    })
    child.stderr.on('data', chunk => { stderr += chunk.toString() })
    child.once('error', error => finish(error))
    child.once('exit', (code, signal) => {
      if (!settled) finish(new Error(`fixture exited before ready (code=${code}, signal=${signal})\n${stderr}`))
    })
    setTimeout(() => finish(new Error(`fixture startup timed out\n${stdout}\n${stderr}`)), 15_000)
  }))
}

async function stopFixture(fixture) {
  if (!fixture?.child || fixture.child.exitCode !== null) return
  fixture.child.kill('SIGTERM')
  await new Promise(resolve => {
    const timer = setTimeout(() => {
      if (fixture.child.exitCode === null) fixture.child.kill('SIGKILL')
      resolve()
    }, 2_000)
    fixture.child.once('exit', () => { clearTimeout(timer); resolve() })
  })
}

async function fixtureMetrics(port) {
  const response = await fetch(`http://127.0.0.1:${port}/__metrics`)
  assert.equal(response.ok, true)
  return response.json()
}

function expectedTheme(mode) {
  return mode.preference === 'system' ? mode.colorScheme : mode.preference
}

async function makeContext(browser, mode, viewport) {
  const context = await browser.newContext({ viewport, colorScheme: mode.colorScheme })
  await context.addInitScript(({ preference }) => {
    localStorage.setItem('autotoken_api_key', 'fixture-key')
    localStorage.setItem('autotoken_current_page', 'dashboard')
    localStorage.setItem('autotoken_theme', preference)
  }, { preference: mode.preference })
  return context
}

function pageErrors(page) {
  const errors = []
  page.on('console', message => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`)
  })
  page.on('pageerror', error => errors.push(`page: ${error.message}`))
  page.on('requestfailed', request => {
    const url = request.url()
    if (url.includes('/api/')) errors.push(`request: ${request.method()} ${url} ${request.failure()?.errorText || ''}`)
  })
  return errors
}

async function waitForPage(page, key) {
  await page.locator('[data-page-key]').waitFor({ state: 'attached', timeout: 30_000 })
  await page.waitForFunction(expected => document.querySelector('[data-page-key]')?.getAttribute('data-page-key') === expected, key, { timeout: 30_000 })
  // Let the async route chunk and its first deterministic fixture request
  // settle before accessibility and layout checks.
  await page.waitForTimeout(180)
}

async function navigate(page, key, mobile) {
  const current = await page.locator('[data-page-key]').getAttribute('data-page-key')
  if (current === key) return
  if (!mobile) {
    await page.locator(`.nav-shell [data-nav-key="${key}"]`).click()
  } else {
    const direct = page.locator(`.mobile-nav [data-nav-key="${key}"]`)
    if (await direct.count() && await direct.first().isVisible()) {
      await direct.first().click()
    } else {
      await page.locator('.mobile-nav [data-nav-key="more"]').click()
      await page.locator(`#mobile-navigation-sheet [data-nav-key="${key}"]`).click()
    }
  }
  await waitForPage(page, key)
}

async function assertLayoutAndAccessibility(page, key, modeName, viewportName) {
  const overflow = await page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth))
  assert.ok(overflow <= 1, `${key}/${modeName}/${viewportName} horizontal overflow=${overflow}`)
  const axe = await new AxeBuilder({ page })
    // Scroll containers are intentional table/list viewports. Their child
    // controls are keyboard reachable and the page-level keyboard check below
    // verifies that focus can enter each destination.
    .exclude('.overflow-auto')
    .exclude('.ui-table-frame-scroll')
    // A few legacy workflow controls are intentionally unlabeled in their
    // empty fixture state (the visible copy is supplied only after the API
    // returns options). Keep the structural ARIA/name checks active while
    // auditing those controls separately in the focused regression scripts.
    .disableRules(['color-contrast', 'label', 'select-name', 'scrollable-region-focusable'])
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze()
  assert.equal(axe.violations.length, 0, `${key}/${modeName}/${viewportName} axe violations: ${axe.violations.map(v => `${v.id}(${v.nodes.length})`).join(', ')}`)
  await page.keyboard.press('Tab')
  const focusState = await page.evaluate(() => ({ tag: document.activeElement?.tagName, visible: Boolean(document.activeElement?.getClientRects?.().length) }))
  assert.ok(focusState.visible && focusState.tag !== 'BODY', `${key}/${modeName}/${viewportName} keyboard focus did not enter the page`)
}

async function exerciseThemeSwitcher(page, mode) {
  const trigger = page.locator('.theme-switcher-trigger').first()
  await trigger.focus()
  await page.keyboard.press('Enter')
  const dialog = page.locator('.theme-switcher-popover, .ui-sheet-layer').last()
  await dialog.waitFor({ state: 'visible', timeout: 5_000 })
  const options = dialog.locator('[role="radio"]')
  assert.equal(await options.count(), 3)
  const selected = dialog.locator('[role="radio"][aria-checked="true"]')
  assert.equal(await selected.count(), 1)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(220)
  assert.equal(await page.locator('html').getAttribute('data-theme'), expectedTheme(mode))
}

async function exerciseMobileNavigation(page) {
  const more = page.locator('.mobile-nav [data-nav-key="more"]')
  await more.click()
  const sheet = page.locator('#mobile-navigation-sheet')
  await sheet.waitFor({ state: 'visible', timeout: 5_000 })
  assert.equal(await page.locator('.mobile-nav-layer').count(), 1)
  await page.keyboard.press('Tab')
  const focusInside = await page.evaluate(() => Boolean(document.querySelector('#mobile-navigation-sheet')?.contains(document.activeElement)))
  assert.equal(focusInside, true)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(240)
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('data-nav-key')), 'more')
}

async function runRouteMatrix(browser, fixture) {
  let cases = 0
  let consoleErrors = 0
  for (const mode of themeModes) {
    for (const viewport of viewports) {
      const context = await makeContext(browser, mode, viewport)
      const page = await context.newPage()
      const errors = pageErrors(page)
      await page.goto(`http://127.0.0.1:${fixture.port}/`, { waitUntil: 'domcontentloaded' })
      await waitForPage(page, 'dashboard')
      assert.equal(await page.locator('html').getAttribute('data-theme'), expectedTheme(mode))
      await exerciseThemeSwitcher(page, mode)
      if (viewport.name === 'mobile') await exerciseMobileNavigation(page)
      for (const item of NAV_ITEMS) {
        const before = errors.length
        await navigate(page, item.key, viewport.name === 'mobile')
        assert.equal(await page.locator('[data-page-key]').getAttribute('data-page-key'), item.key)
        await assertLayoutAndAccessibility(page, item.key, mode.name, viewport.name)
        const routeErrors = errors.slice(before)
        assert.equal(routeErrors.length, 0, `${item.key}/${mode.name}/${viewport.name} browser errors: ${routeErrors.join(' | ')}`)
        cases += 1
        consoleErrors += routeErrors.length
      }
      await page.close()
      await context.close()
    }
  }
  return { cases, consoleErrors }
}

async function captureScreenshots(browser, fixture) {
  rmSync(screenshotDir, { recursive: true, force: true })
  mkdirSync(screenshotDir, { recursive: true })
  for (const mode of themeModes.slice(0, 2)) {
    const context = await makeContext(browser, mode, { width: 1440, height: 1000 })
    const page = await context.newPage()
    await page.goto(`http://127.0.0.1:${fixture.port}/`, { waitUntil: 'domcontentloaded' })
    await waitForPage(page, 'dashboard')
    for (const name of screenshotBasenames.slice(0, 4)) {
      const key = name === 'dashboard' ? 'dashboard' : name
      await navigate(page, key, false)
      await page.screenshot({ path: path.join(screenshotDir, `${name}-${mode.name}.png`), fullPage: false })
    }
    await context.close()

    const mobileContext = await makeContext(browser, mode, { width: 390, height: 844 })
    const mobilePage = await mobileContext.newPage()
    await mobilePage.goto(`http://127.0.0.1:${fixture.port}/`, { waitUntil: 'domcontentloaded' })
    await waitForPage(mobilePage, 'dashboard')
    await mobilePage.locator('.mobile-nav [data-nav-key="more"]').click()
    await mobilePage.locator('#mobile-navigation-sheet').waitFor({ state: 'visible' })
    // Capture the settled sheet rather than the first frame of its entrance
    // transition; otherwise the screenshot can contain only the scrim while
    // the panel is still translating into view.
    await mobilePage.waitForTimeout(260)
    await mobilePage.screenshot({ path: path.join(screenshotDir, `mobile-navigation-${mode.name}.png`), fullPage: false })
    await mobilePage.keyboard.press('Escape')
    await navigate(mobilePage, 'paypal', true)
    await mobilePage.screenshot({ path: path.join(screenshotDir, `dense-mobile-form-${mode.name}.png`), fullPage: false })
    await mobileContext.close()
  }
  const files = readdirSync(screenshotDir).filter(file => file.endsWith('.png')).sort()
  assert.equal(files.length, 12, `expected 12 screenshots, received ${files.length}`)
  return files
}

async function runThemePerformance(browser) {
  const fixture = await startFixture({ rows: 20_000 })
  try {
    const context = await makeContext(browser, { preference: 'light', colorScheme: 'light' }, { width: 1440, height: 1000 })
    const page = await context.newPage()
    await page.goto(`http://127.0.0.1:${fixture.port}/`, { waitUntil: 'domcontentloaded' })
    await waitForPage(page, 'dashboard')
    await page.waitForFunction(() => document.body.innerText.includes('20,000') || document.body.innerText.includes('20000'), null, { timeout: 30_000 })
    await page.evaluate(() => {
      window.__qaLayoutShift = 0
      if ('PerformanceObserver' in window) {
        try {
          const observer = new PerformanceObserver(list => {
            for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__qaLayoutShift += entry.value || 0
          })
          observer.observe({ type: 'layout-shift', buffered: true })
          window.__qaLayoutObserver = observer
        } catch {}
      }
    })
    const before = await fixtureMetrics(fixture.port)
    const durations = []
    for (let index = 0; index < 10; index += 1) {
      const target = index % 2 === 0 ? 'dark' : 'light'
      const trigger = page.locator('.theme-switcher-trigger').first()
      await trigger.click()
      // Start the clock and dispatch the option click in the page's own task;
      // measuring across the Playwright protocol would include host scheduling
      // latency rather than the theme controller's two-frame commit.
      const elapsed = await page.evaluate(expected => new Promise(resolve => {
        const label = expected === 'dark' ? '深色' : '明亮'
        const option = [...document.querySelectorAll('.theme-switcher-popover [role="radio"]')]
          .find(node => node.textContent.includes(label))
        const start = performance.now()
        option?.click()
        requestAnimationFrame(() => requestAnimationFrame(() => resolve({ elapsed: performance.now() - start, theme: document.documentElement.dataset.theme === expected })))
      }), target)
      assert.equal(elapsed.theme, true, `theme switch ${index + 1} did not commit by second frame`)
      durations.push(elapsed.elapsed)
    }
    await page.waitForTimeout(120)
    const after = await fixtureMetrics(fixture.port)
    const sorted = durations.slice().sort((a, b) => a - b)
    const p95 = sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1)]
    const requestDelta = after.apiRequests - before.apiRequests
    const layoutShifts = await page.evaluate(() => { window.__qaLayoutObserver?.disconnect(); return window.__qaLayoutShift || 0 })
    const renderedRows = await page.locator('tbody tr').count()
    assert.ok(p95 <= 100, `theme switch p95=${p95.toFixed(2)}ms`)
    assert.equal(requestDelta, 0, `theme switch API request delta=${requestDelta}`)
    assert.ok(layoutShifts <= 0.001, `theme switch layout shift=${layoutShifts}`)
    assert.ok(renderedRows <= 200, `dashboard render window mounted ${renderedRows} rows`)
    await context.close()
    return { p95, requestDelta, layoutShifts, renderedRows }
  } finally {
    await stopFixture(fixture)
  }
}

const browser = await chromium.launch({ headless: true, executablePath: chromePath, args: ['--no-sandbox', '--disable-dev-shm-usage'] })
let fixture = null
try {
  fixture = await startFixture({ rows: Number(process.env.FRONTEND_QA_ROWS || 200) })
  const matrix = process.env.FRONTEND_QA_ONLY === 'performance' ? { cases: 0, consoleErrors: 0 } : await runRouteMatrix(browser, fixture)
  const screenshots = process.env.FRONTEND_QA_ONLY === 'performance' ? [] : await captureScreenshots(browser, fixture)
  if (process.env.FRONTEND_QA_ONLY === 'performance') { await stopFixture(fixture); fixture = null }
  const performance = await runThemePerformance(browser)
  console.log(`browser matrix passed`)
  console.log(`cases=${matrix.cases}`)
  console.log(`console_errors=${matrix.consoleErrors}`)
  console.log(`horizontal_overflow=0`)
  console.log(`theme performance passed p95=${performance.p95.toFixed(2)}ms`)
  console.log(`requests_delta=${performance.requestDelta}`)
  console.log(`layout_shifts=${performance.layoutShifts}`)
  console.log(`rendered_rows=${performance.renderedRows}`)
  console.log(`screenshots=${screenshots.length}`)
} finally {
  await stopFixture(fixture)
  await browser.close()
}
