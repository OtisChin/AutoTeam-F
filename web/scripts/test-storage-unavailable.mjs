import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
assert.match(
  appSource,
  /const savedPage = \(\(\) => \{[\s\S]*?try \{[\s\S]*?localStorage\.getItem\(CURRENT_PAGE_KEY\)[\s\S]*?catch/,
  'a blocked saved-page read must not throw while the root component module initializes',
)

const blockedStorage = {
  getItem() { throw new DOMException('blocked', 'SecurityError') },
  setItem() { throw new DOMException('blocked', 'SecurityError') },
  removeItem() { throw new DOMException('blocked', 'SecurityError') },
}
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: blockedStorage })

let authorization = null
globalThis.fetch = async (_url, options) => {
  authorization = options?.headers?.Authorization || null
  return {
    ok: true,
    status: 200,
    headers: { get: () => null },
    async json() { return { authenticated: true, auth_required: true } },
  }
}

const apiModule = await import(`../src/api.js?storage-unavailable=${Date.now()}`)
assert.equal(typeof apiModule.getApiKey, 'function', 'API key reads should expose the shared guarded accessor')
assert.doesNotThrow(() => apiModule.setApiKey('memory-key'), 'blocked storage must not crash a setup/login action')
assert.equal(apiModule.getApiKey(), 'memory-key', 'the active request may use its in-memory key while storage diagnostics run')
await apiModule.api.checkAuth()
assert.equal(authorization, 'Bearer memory-key', 'request construction must not crash when localStorage throws')
assert.doesNotThrow(() => apiModule.clearApiKey(), 'blocked storage must not crash logout cleanup')
assert.equal(apiModule.getApiKey(), '')

const sharedValues = new Map()
const sharedStorage = {
  getItem(key) { return sharedValues.has(key) ? sharedValues.get(key) : null },
  setItem(key, value) { sharedValues.set(key, String(value)) },
  removeItem(key) { sharedValues.delete(key) },
}
Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: sharedStorage })
const tabA = await import(`../src/api.js?tab-a=${Date.now()}`)
tabA.setApiKey('key-a')
assert.equal(tabA.getApiKey(), 'key-a')
const tabB = await import(`../src/api.js?tab-b=${Date.now()}`)
assert.equal(tabB.getApiKey(), 'key-a')
tabB.setApiKey('key-b')
assert.equal(tabA.getApiKey(), 'key-a', 'another tab must not silently change the in-flight network identity')
assert.equal(typeof tabA.invalidateApiKeyMemory, 'function', 'the root app needs a non-persisting cross-tab invalidation hook')
tabA.invalidateApiKeyMemory()
assert.equal(tabA.getApiKey(), '', 'cross-tab invalidation should fence requests without overwriting the other tab storage value')

assert.match(appSource, /function handleExternalStorageChange\(event\)[\s\S]*advanceAuthEpoch\(\)[\s\S]*invalidateApiKeyMemory\(\)[\s\S]*authenticated\.value = false/, 'an external owner or key change should invalidate the old UI/auth epoch')
assert.match(appSource, /addEventListener\('storage', handleExternalStorageChange\)/, 'the app should observe cross-tab identity changes')
assert.match(appSource, /removeEventListener\('storage', handleExternalStorageChange\)/, 'the app should release its cross-tab listener')

console.log('blocked browser storage degrades without crashing API module initialization or requests')
