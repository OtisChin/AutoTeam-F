import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../src')
const policyPath = path.join(src, 'accountLoadPolicy.js')

assert.ok(existsSync(policyPath), 'account loading policy should isolate dashboard-only fetch decisions')

const {
  createAccountLoadAbortError,
  createAccountLoadLifecycle,
  isAccountLoadAbortError,
  shouldLoadDashboardAccounts,
} = await import(pathToFileURL(policyPath))
const apiModulePath = pathToFileURL(path.join(src, 'api.js'))

assert.equal(shouldLoadDashboardAccounts('dashboard'), true)
assert.equal(shouldLoadDashboardAccounts('paypal'), false)
assert.equal(shouldLoadDashboardAccounts('settings'), false)
assert.equal(shouldLoadDashboardAccounts(''), false)

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

{
  const pending = deferred()
  const changes = []
  let calls = 0
  const lifecycle = createAccountLoadLifecycle({
    load: async ({ signal, key }) => {
      calls += 1
      assert.equal(signal instanceof AbortSignal, true)
      assert.equal(key, 7)
      return pending.promise
    },
    prepare: accounts => ({ accounts, total: accounts.length }),
    now: () => 1234,
    onChange: state => changes.push(state),
  })

  const first = lifecycle.load(7)
  const duplicate = lifecycle.load(7)
  assert.equal(first, duplicate, 'same auth epoch should share one account request promise')
  await Promise.resolve()
  assert.equal(calls, 1)
  pending.resolve([{ email: 'one@example.com' }])
  const snapshot = await first

  assert.deepEqual(snapshot, { accounts: [{ email: 'one@example.com' }], total: 1 })
  assert.deepEqual(lifecycle.getState(), {
    snapshot,
    loading: false,
    error: '',
    lastSuccessfulAt: 1234,
  })
  assert.equal(changes.some(state => state.loading), true)
}

{
  const previousSnapshot = { accounts: [{ email: 'unchanged@example.com' }] }
  const notModified = Symbol('not-modified')
  const lifecycle = createAccountLoadLifecycle({
    load: async () => notModified,
    isNotModified: value => value === notModified,
    initialSnapshot: previousSnapshot,
    initialLastSuccessfulAt: 11,
    now: () => 22,
  })

  const result = await lifecycle.load('etag')
  assert.equal(result, previousSnapshot, '304 revalidation should reuse the exact prepared snapshot')
  assert.deepEqual(lifecycle.getState(), {
    snapshot: previousSnapshot,
    loading: false,
    error: '',
    lastSuccessfulAt: 22,
  })
}

{
  const previousSnapshot = { accounts: [{ email: 'old@example.com' }], total: 1 }
  const failure = new Error('backend unavailable')
  const lifecycle = createAccountLoadLifecycle({
    load: async () => { throw failure },
    initialSnapshot: previousSnapshot,
    initialLastSuccessfulAt: 99,
  })

  await assert.rejects(lifecycle.load('failure'), error => error === failure)
  const state = lifecycle.getState()
  assert.equal(state.snapshot, previousSnapshot, 'real failure must preserve the last usable account snapshot')
  assert.equal(state.lastSuccessfulAt, 99, 'real failure must preserve the last success timestamp')
  assert.match(state.error, /backend unavailable/)
  assert.equal(state.loading, false)
}

{
  let requestSignal = null
  const lifecycle = createAccountLoadLifecycle({
    load: ({ signal }) => {
      requestSignal = signal
      return new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(signal.reason), { once: true })
      })
    },
    initialSnapshot: { accounts: [{ email: 'cached@example.com' }] },
    initialLastSuccessfulAt: 88,
  })

  const request = lifecycle.load('logout')
  await Promise.resolve()
  const reason = createAccountLoadAbortError('auth epoch changed')
  assert.equal(lifecycle.abort(reason), true)
  assert.equal(requestSignal.aborted, true)
  assert.equal(requestSignal.reason, reason)
  assert.equal(isAccountLoadAbortError(reason), true)
  assert.equal(await request, undefined, 'intentional abort should be silent')
  assert.deepEqual(lifecycle.getState(), {
    snapshot: { accounts: [{ email: 'cached@example.com' }] },
    loading: false,
    error: '',
    lastSuccessfulAt: 88,
  })
}

{
  const pending = deferred()
  const lifecycle = createAccountLoadLifecycle({
    // Deliberately ignores AbortSignal to prove a late response cannot commit.
    load: () => pending.promise,
    initialSnapshot: { version: 'old' },
    initialLastSuccessfulAt: 77,
    now: () => 999,
  })

  const request = lifecycle.load('old-epoch')
  lifecycle.abort(createAccountLoadAbortError('unmounted'))
  pending.resolve([{ email: 'late@example.com' }])
  assert.equal(await request, undefined)
  assert.deepEqual(lifecycle.getState(), {
    snapshot: { version: 'old' },
    loading: false,
    error: '',
    lastSuccessfulAt: 77,
  })
}

const appSource = readFileSync(path.join(src, 'App.vue'), 'utf8')
assert.match(appSource, /shouldLoadDashboardAccounts\(currentPage\.value\)/, 'App should gate full account loads by page')
assert.equal((appSource.match(/api\.getAccounts\(/g) || []).length, 1, 'App should have one controlled full-pool request boundary')
const refreshSource = appSource.match(/async function performRefresh[\s\S]*?\r?\n}\r?\n\r?\nconst refreshOnce/)?.[0] || ''
assert.match(refreshSource, /if \(shouldLoadDashboardAccounts\(currentPage\.value\)\)/, 'non-dashboard refresh should only load auxiliary state')
assert.match(refreshSource, /refreshDashboardAccounts\(epoch\)/, 'dashboard refresh should demand-load its account snapshot')
const navigationSource = appSource.match(/function navigateTo[\s\S]*?\r?\n}\r?\n\r?\nfunction prefetchPage/)?.[0] || ''
assert.match(navigationSource, /void refreshDashboardAccounts\(authEpoch\)/, 'entering Dashboard should demand-load accounts')
assert.match(navigationSource, /accountLoadLifecycle\.abort\(/, 'leaving Dashboard should cancel its in-flight request')
const epochSource = appSource.match(/function advanceAuthEpoch[\s\S]*?\n}/)?.[0] || ''
assert.match(epochSource, /accountLoadLifecycle\.abort\(/, 'auth epoch changes should abort the account request')
const unmountSource = appSource.match(/onUnmounted\(\(\) => \{[\s\S]*?\n}\)/)?.[0] || ''
assert.match(unmountSource, /accountLoadLifecycle\.abort\(/, 'unmount should abort the account request')
assert.match(appSource, /:accounts-error="accountsError"/, 'Dashboard should receive account load failures')
assert.match(appSource, /:last-successful-at="lastSuccessfulAt"/, 'Dashboard should receive snapshot freshness')
assert.match(appSource, /@retry-accounts="refreshDashboardAccounts"/, 'Dashboard should be able to retry account loading')

const originalFetch = globalThis.fetch
const originalLocalStorage = globalThis.localStorage
let requestedUrl = ''
let requestedSignal = null
globalThis.localStorage = { getItem: () => '' }
globalThis.fetch = (url, init = {}) => {
  requestedUrl = String(url)
  requestedSignal = init.signal
  return new Promise((_resolve, reject) => {
    const rejectFromAbort = () => reject(init.signal.reason)
    if (init.signal?.aborted) rejectFromAbort()
    else init.signal?.addEventListener('abort', rejectFromAbort, { once: true })
  })
}

try {
  const { api } = await import(apiModulePath)
  const controller = new AbortController()
  const logoutReason = new Error('auth epoch changed')
  const request = api.getAccounts({
    includeSessionStubs: false,
    view: 'dashboard',
    timeoutMs: 50,
    signal: controller.signal,
  })
  controller.abort(logoutReason)
  await assert.rejects(request, error => error === logoutReason, 'logout should abort account response parsing immediately')
  const parsedUrl = new URL(requestedUrl, 'http://localhost')
  assert.equal(parsedUrl.pathname, '/api/accounts')
  assert.equal(parsedUrl.searchParams.get('include_session_stubs'), 'false')
  assert.equal(parsedUrl.searchParams.get('view'), 'dashboard')
  assert.equal(requestedSignal?.reason, logoutReason)
} finally {
  globalThis.fetch = originalFetch
  globalThis.localStorage = originalLocalStorage
}


{
  const originalFetchForEtag = globalThis.fetch
  const originalLocalStorageForEtag = globalThis.localStorage
  const responseRows = [{ email: 'etag@example.com' }]
  const seenRequests = []
  let responseIndex = 0
  globalThis.localStorage = {
    getItem: () => 'fixture-key',
    setItem: () => {},
    removeItem: () => {},
  }
  globalThis.fetch = async (_url, init = {}) => {
    seenRequests.push(init)
    responseIndex += 1
    if (responseIndex === 1) {
      return {
        ok: true,
        status: 200,
        headers: { get: name => String(name).toLowerCase() === 'etag' ? '"dashboard-v1"' : null },
        json: async () => responseRows,
      }
    }
    return {
      ok: false,
      status: 304,
      headers: { get: () => null },
      json: async () => { throw new Error('304 must not parse an empty response body') },
    }
  }

  try {
    const { ACCOUNT_DATA_NOT_MODIFIED, api, clearApiKey } = await import(apiModulePath)
    clearApiKey()
    const first = await api.getAccounts({ view: 'dashboard', includeSessionStubs: true })
    const unchanged = await api.getAccounts({ view: 'dashboard', includeSessionStubs: true })
    assert.equal(first, responseRows)
    assert.equal(unchanged, ACCOUNT_DATA_NOT_MODIFIED)
    assert.equal(seenRequests[0].headers['If-None-Match'], undefined)
    assert.equal(seenRequests[1].headers['If-None-Match'], '"dashboard-v1"')
    assert.equal(seenRequests[1].cache, 'no-store', 'manual ETag revalidation should expose 304 instead of reparsing the browser cache')
  } finally {
    globalThis.fetch = originalFetchForEtag
    globalThis.localStorage = originalLocalStorageForEtag
  }
}

console.log('account loading lifecycle tests passed')
