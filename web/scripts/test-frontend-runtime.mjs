import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../src')
const runtimePath = path.join(src, 'runtimePerformance.js')
const requestPath = path.join(src, 'request.js')
const progressPath = path.join(src, 'taskProgress.js')

assert.ok(existsSync(runtimePath), 'runtime performance module should exist')
assert.ok(existsSync(requestPath), 'abortable request module should exist')
assert.ok(existsSync(progressPath), 'task progress module should exist')

const { createRafThrottle, createSingleFlight } = await import(pathToFileURL(runtimePath))
const { fetchWithTimeout } = await import(pathToFileURL(requestPath))
const { calculateTaskProgress } = await import(pathToFileURL(progressPath))

{
  let calls = 0
  let release
  const singleFlight = createSingleFlight(async () => {
    calls += 1
    if (calls === 1) return await new Promise(resolve => { release = resolve })
    return 'ready'
  })

  const first = singleFlight()
  const second = singleFlight()
  assert.equal(calls, 1, 'overlapping refreshes should share one execution')
  assert.strictEqual(first, second, 'overlapping refreshes should share one promise')
  release('ready')
  assert.equal(await first, 'ready')
  assert.equal(await second, 'ready')
  assert.equal(await singleFlight(), 'ready')
  assert.equal(calls, 2, 'a new execution should start after the first settles')
}

{
  const frames = []
  const values = []
  const throttled = createRafThrottle(value => values.push(value), callback => {
    frames.push(callback)
    return frames.length
  }, () => {})

  throttled(1)
  throttled(2)
  throttled(3)
  assert.equal(frames.length, 1, 'pointer events should be coalesced into one frame')
  frames.shift()(16)
  assert.deepEqual(values, [3], 'the frame should apply the newest pointer position')
}

{
  let observedSignal
  const fetchImpl = (_input, init) => new Promise((_resolve, reject) => {
    observedSignal = init.signal
    init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true })
  })

  await assert.rejects(
    fetchWithTimeout('/slow', {}, { timeoutMs: 5, fetchImpl }),
    error => error?.code === 'REQUEST_TIMEOUT' && /5ms/.test(error.message),
    'a stalled API request should abort with a typed timeout error',
  )
  assert.equal(observedSignal.aborted, true)
}

{
  let observedSignal
  const fetchImpl = async (_input, init) => {
    observedSignal = init.signal
    return {
      json: () => new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(init.signal.reason), { once: true })
      }),
    }
  }

  await assert.rejects(
    fetchWithTimeout('/slow-body', {}, {
      timeoutMs: 5,
      fetchImpl,
      consume: response => response.json(),
    }),
    error => error?.code === 'REQUEST_TIMEOUT',
    'the timeout must remain armed while a response body is being consumed',
  )
  assert.equal(observedSignal.aborted, true)
}

{
  const response = { ok: true, status: 200 }
  let consumeCalls = 0
  const result = await fetchWithTimeout('/no-timeout', {}, {
    timeoutMs: 0,
    fetchImpl: async () => response,
    consume: async resp => {
      consumeCalls += 1
      return { resp, data: { ok: true } }
    },
  })

  assert.equal(consumeCalls, 1, 'disabling the timeout must still consume the response body')
  assert.deepEqual(result, { resp: response, data: { ok: true } }, 'no-timeout requests should preserve the API response envelope')
}

{
  assert.deepEqual(
    calculateTaskProgress({ progress: { total: '3', successful: '1', failed: '2' } }),
    { text: '3/3', percent: 100 },
    'string counters should be added numerically instead of concatenated',
  )
  assert.deepEqual(
    calculateTaskProgress({ progress: { total: 0 }, status: 'pending' }),
    { text: '等待中', percent: 8 },
  )
}

const appSource = readFileSync(path.join(src, 'App.vue'), 'utf8')
const apiSource = readFileSync(path.join(src, 'api.js'), 'utf8')
assert.match(appSource, /defineAsyncComponent/, 'large pages should be loaded asynchronously')
assert.doesNotMatch(appSource, /setInterval\s*\(/, 'root polling must not overlap through setInterval')
assert.match(appSource, /visibilitychange/, 'root polling should pause while the page is hidden')
const suspendedPollBranch = appSource.slice(
  appSource.indexOf("if (document.visibilityState === 'hidden' || !navigator.onLine)"),
  appSource.indexOf('try {', appSource.indexOf("if (document.visibilityState === 'hidden' || !navigator.onLine)")),
)
assert.doesNotMatch(suspendedPollBranch, /scheduleNextPoll/, 'hidden or offline polling should stay dormant until a visibility/online event resumes it')
const checkAuthSource = appSource.slice(appSource.indexOf('async function checkAuth'), appSource.indexOf('async function doLogin'))
const checkSetupSource = appSource.slice(appSource.indexOf('async function checkSetup'), appSource.indexOf('function onSetupDone'))
assert.doesNotMatch(checkAuthSource, /catch[\s\S]*authenticated\.value\s*=\s*true/, 'network failures must not bypass authentication')
assert.doesNotMatch(checkSetupSource, /catch\s*\{\s*return true/, 'setup network failures must not be treated as configured')
assert.match(checkSetupSource, /e\.status\s*===\s*404/, 'only a missing legacy setup endpoint may be treated as configured')
assert.match(appSource, /startupError/, 'startup failures should expose a retryable error state')
assert.match(
  apiSource,
  /openBindLinkWithAuthSession:\s*\(payload\)\s*=>\s*request\('POST',\s*'\/bind\/link\/open',\s*payload,\s*\{\s*timeoutMs:\s*0\s*\}\)/,
  'the synchronous browser-opening endpoint must not abort while backend navigation is still running',
)

console.log('frontend runtime performance tests passed')
