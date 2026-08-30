import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const recoveryUrl = new URL('../src/pollingRecovery.js', import.meta.url)
const { readPollingSnapshot } = await import(recoveryUrl)

const waits = []
const notices = []
let requests = 0
let attempt = 0
let result
for (;;) {
  result = await readPollingSnapshot({
    request: async () => {
      requests += 1
      if (requests === 1) {
        const error = new Error('temporary upstream failure')
        error.status = 503
        throw error
      }
      return { status: 'success', id: 'job-1' }
    },
    wait: async delayMs => {
      waits.push(delayMs)
      return true
    },
    attempt,
    onTransientError: (error, delayMs) => notices.push([error.status, delayMs]),
  })
  if (result.kind === 'retry') {
    attempt = result.attempt
    continue
  }
  break
}

assert.equal(requests, 2, 'a transient first failure should retry the same status request')
assert.deepEqual(waits, [1000], 'the first retry should use a bounded non-zero backoff')
assert.deepEqual(notices, [[503, 1000]], 'the page should be able to surface the retry delay')
assert.equal(result.kind, 'snapshot')
assert.equal(result.value.status, 'success')
assert.equal(result.attempt, 0, 'a successful read should reset the retry attempt')

const missing = new Error('missing')
missing.status = 404
const missingResult = await readPollingSnapshot({
  request: async () => { throw missing },
  wait: async () => { throw new Error('404 must not be retried') },
})
assert.equal(missingResult.kind, 'missing', '404 should terminate reconciliation instead of retrying forever')

const stopped = await readPollingSnapshot({
  request: async () => { throw new Error('offline') },
  wait: async () => false,
})
assert.equal(stopped.kind, 'stopped', 'unmount/disposal should stop a pending retry')

for (const file of ['BrazilPixPage.vue', 'IndiaUpiPage.vue']) {
  const source = fs.readFileSync(path.join(root, 'src', 'components', file), 'utf8')
  assert.match(source, /readPollingSnapshot\s*\(/, `${file} should reconcile transient status failures`)
  assert.match(source, /recovery\.kind === 'retry'[\s\S]{0,160}?continue/, `${file} should continue the same job after backoff`)
  assert.match(source, /recovery\.kind === 'missing'/, `${file} should handle a missing remote job explicitly`)
}

console.log('extraction polling recovery tests passed: transient reject -> retry -> terminal snapshot; 404 -> missing; dispose -> stopped')
