import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  THEME_CONTROLLER_KEY,
  THEME_STORAGE_KEY,
  createThemeController,
  normalizeThemePreference,
  resolveThemePreference,
} from '../src/themePreference.js'

class FakeEventTarget {
  constructor() { this.listeners = new Map() }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }
  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener)
  }
  dispatch(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event)
  }
  listenerCount(type) {
    return this.listeners.get(type)?.size || 0
  }
}

function createStorage(seed = {}, blocked = false) {
  const values = new Map(Object.entries(seed))
  return {
    getItem(key) {
      if (blocked) throw new DOMException('blocked', 'SecurityError')
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      if (blocked) throw new DOMException('blocked', 'SecurityError')
      values.set(key, String(value))
    },
    removeItem(key) {
      if (blocked) throw new DOMException('blocked', 'SecurityError')
      values.delete(key)
    },
    value(key) { return values.get(key) },
  }
}

const createRoot = () => ({ dataset: {}, style: {} })

assert.equal(typeof THEME_CONTROLLER_KEY, 'symbol')
assert.equal(THEME_STORAGE_KEY, 'autotoken_theme')
assert.equal(normalizeThemePreference('system'), 'system')
assert.equal(normalizeThemePreference('light'), 'light')
assert.equal(normalizeThemePreference('dark'), 'dark')
assert.equal(normalizeThemePreference('sepia'), 'system')
assert.equal(resolveThemePreference('system', false), 'light')
assert.equal(resolveThemePreference('system', true), 'dark')
assert.equal(resolveThemePreference('light', true), 'light')
assert.equal(resolveThemePreference('dark', false), 'dark')

const storage = createStorage({ [THEME_STORAGE_KEY]: 'invalid' })
const media = new FakeEventTarget()
media.matches = true
const events = new FakeEventTarget()
const root = createRoot()
const meta = { content: '' }
const controller = createThemeController({
  root,
  storage,
  mediaQueryList: media,
  eventTarget: events,
  themeColorMeta: meta,
})

assert.deepEqual(controller.getSnapshot(), { preference: 'system', resolvedTheme: 'dark' })
assert.equal(root.dataset.themePreference, 'system')
assert.equal(root.dataset.theme, 'dark')
assert.equal(root.style.colorScheme, 'dark')
assert.equal(meta.content, '#151517')
assert.equal(media.listenerCount('change'), 1)
assert.equal(events.listenerCount('storage'), 1)

const snapshots = []
const unsubscribe = controller.subscribe(snapshot => snapshots.push(snapshot))
controller.setPreference('light')
assert.deepEqual(controller.getSnapshot(), { preference: 'light', resolvedTheme: 'light' })
assert.equal(storage.value(THEME_STORAGE_KEY), 'light')
assert.equal(meta.content, '#f5f5f7')

media.matches = false
media.dispatch('change', { matches: false })
assert.equal(controller.getSnapshot().resolvedTheme, 'light')

controller.setPreference('system')
media.matches = true
media.dispatch('change', { matches: true })
assert.equal(controller.getSnapshot().resolvedTheme, 'dark')

events.dispatch('storage', { key: THEME_STORAGE_KEY, newValue: 'light' })
assert.deepEqual(controller.getSnapshot(), { preference: 'light', resolvedTheme: 'light' })
assert.ok(snapshots.length >= 3)

unsubscribe()
controller.dispose()
assert.equal(media.listenerCount('change'), 0)
assert.equal(events.listenerCount('storage'), 0)

const blockedController = createThemeController({
  root: createRoot(),
  storage: createStorage({}, true),
  mediaQueryList: Object.assign(new FakeEventTarget(), { matches: false }),
  eventTarget: new FakeEventTarget(),
  themeColorMeta: { content: '' },
})
assert.doesNotThrow(() => blockedController.setPreference('dark'))
assert.deepEqual(blockedController.getSnapshot(), { preference: 'dark', resolvedTheme: 'dark' })
blockedController.dispose()

const controllerSource = readFileSync(new URL('../src/themePreference.js', import.meta.url), 'utf8')
assert.doesNotMatch(controllerSource, /querySelectorAll|getElementsByClassName|getElementsByTagName|TreeWalker/, 'theme changes must not traverse the page DOM')

import vm from 'node:vm'

const htmlSource = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
const bootstrapSource = htmlSource.match(
  /<script data-theme-bootstrap>([\s\S]*?)<\/script>/,
)?.[1]
assert.ok(bootstrapSource, 'index.html must contain the synchronous theme bootstrap')

function runBootstrap({ stored = null, systemDark = false, blocked = false } = {}) {
  const root = { dataset: {}, style: {} }
  const meta = { content: '' }
  vm.runInNewContext(bootstrapSource, {
    document: {
      documentElement: root,
      querySelector(selector) {
        return selector === 'meta[name="theme-color"]' ? meta : null
      },
    },
    localStorage: {
      getItem(key) {
        assert.equal(key, THEME_STORAGE_KEY)
        if (blocked) throw new DOMException('blocked', 'SecurityError')
        return stored
      },
    },
    matchMedia(query) {
      assert.equal(query, '(prefers-color-scheme: dark)')
      return { matches: systemDark }
    },
  })
  return { root, meta }
}

assert.equal(runBootstrap().root.dataset.theme, 'light')
assert.equal(runBootstrap({ systemDark: true }).root.dataset.theme, 'dark')
assert.equal(runBootstrap({ stored: 'light', systemDark: true }).root.dataset.theme, 'light')
assert.equal(runBootstrap({ stored: 'dark' }).root.dataset.theme, 'dark')
assert.equal(runBootstrap({ stored: 'invalid' }).root.dataset.themePreference, 'system')
assert.doesNotThrow(() => runBootstrap({ blocked: true }))

const mainSource = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8')
assert.match(mainSource, /createThemeController\(\)/)
assert.match(mainSource, /provide\(THEME_CONTROLLER_KEY,\s*themeController\)/)
assert.match(mainSource, /themeController\.dispose\(\)/)

const styleSource = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
const tailwindSource = readFileSync(new URL('../tailwind.config.js', import.meta.url), 'utf8')
const componentSources = [
  'BrazilPixPage.vue',
  'IndiaUpiPage.vue',
  'KakaoPayPage.vue',
].map(name => readFileSync(
  new URL('../src/components/' + name, import.meta.url),
  'utf8',
)).join('\n')

assert.match(styleSource, /html\[data-theme=['"]light['"]\]/)
assert.match(styleSource, /--surface-base:\s*#f5f5f7/i)
assert.match(styleSource, /--surface-window:\s*#fff(?:fff)?/i)
assert.match(styleSource, /--text-main:\s*#1d1d1f/i)
assert.match(styleSource, /--accent-fill:\s*#0071e3/i)
assert.match(styleSource, /html\[data-theme=['"]dark['"]\]/)
assert.match(styleSource, /--text-on-accent:\s*#fff(?:fff)?/i)
assert.match(styleSource, /forced-colors:\s*active/)
assert.match(styleSource, /prefers-reduced-motion:\s*reduce/)
assert.doesNotMatch(styleSource, /transition\s*:\s*all/i)
assert.doesNotMatch(styleSource, /\btransition-all\b/)
assert.match(tailwindSource, /<alpha-value>/)
assert.match(tailwindSource, /--tw-neutral-950/)
assert.match(tailwindSource, /--rgb-success-text/)
assert.doesNotMatch(styleSource, /background-color:\s*#0d0e11\s*!important/)
assert.doesNotMatch(styleSource, /background-color:\s*#17181c\s*!important/)
assert.match(tailwindSource, /indigo:\s*tone\(/)
assert.match(tailwindSource, /teal:\s*tone\(/)
assert.match(styleSource, /\.bg-indigo-600[\s\S]*\.text-white/)
assert.match(styleSource, /\.bg-teal-600[\s\S]*\.text-white/)
assert.doesNotMatch(componentSources, /linear-gradient\(135deg,rgba\(15,23,42,0\.96\)/)
assert.match(componentSources, /workflow-hero-surface/)

console.log('theme controller regression tests passed')

const primitiveNames = [
  'UiPageHeader', 'UiSurface', 'UiButton', 'UiStatusBadge',
  'UiFormField', 'UiSegmentedControl', 'UiStatePanel', 'UiSheet',
]
for (const name of primitiveNames) {
  const source = readFileSync(
    new URL('../src/components/ui/' + name + '.vue', import.meta.url),
    'utf8',
  )
  assert.ok(source.length > 0, name + ' must exist')
}

const segmentedSource = readFileSync(
  new URL('../src/components/ui/UiSegmentedControl.vue', import.meta.url),
  'utf8',
)
assert.match(segmentedSource, /role="radiogroup"/)
assert.match(segmentedSource, /role="radio"/)
assert.match(segmentedSource, /aria-checked/)
assert.match(segmentedSource, /ArrowDown/)
assert.match(segmentedSource, /ArrowUp/)
assert.match(segmentedSource, /defineExpose\(\{\s*focusSelected\s*\}\)/)

const sheetSource = readFileSync(
  new URL('../src/components/ui/UiSheet.vue', import.meta.url),
  'utf8',
)
assert.match(sheetSource, /<Teleport to="body">/)
assert.match(sheetSource, /aria-modal="true"/)
assert.match(sheetSource, /trapFocus/)
assert.match(sheetSource, /restoreBackground/)
assert.match(sheetSource, /opener/)
assert.match(sheetSource, /@keydown\.esc/)
