import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../src')
const helperPath = path.join(src, 'jobSnapshot.js')
assert.ok(existsSync(helperPath), 'job snapshot compaction helper should exist')

const {
  JOB_SNAPSHOT_LOG_LIMIT,
  compactPaymentJobSnapshot,
  createSnapshotWriteGate,
} = await import(pathToFileURL(helperPath))

const logs = Array.from({ length: 500 }, (_, index) => ({ message: `log-${index}-${'x'.repeat(180)}` }))
const result = {
  successes: Array.from({ length: 500 }, (_, index) => ({ email: `ok-${index}@example.com`, detail: 'y'.repeat(180) })),
  errors: Array.from({ length: 500 }, (_, index) => ({ email: `bad-${index}@example.com`, error: 'z'.repeat(180) })),
}
const job = { id: 'job-1', status: 'running', total: 1000, completed: 500, logs, result }
const compact = compactPaymentJobSnapshot({
  jobId: job.id,
  job,
  logs,
  result,
  statusText: 'running',
  statusError: false,
})

assert.equal(Object.hasOwn(compact.job, 'logs'), false, 'the nested job must not duplicate top-level logs')
assert.equal(Object.hasOwn(compact.job, 'result'), false, 'the nested job must not duplicate the top-level result')
assert.equal(compact.logs.length, JOB_SNAPSHOT_LOG_LIMIT, 'only the newest bounded log tail should be persisted')
assert.equal(compact.logs[0].message.startsWith('log-300-'), true)
assert.equal(compact.result, result, 'result semantics remain intact for restored terminal details')

let now = 10_000
const gate = createSnapshotWriteGate({ intervalMs: 5_000, now: () => now })
assert.equal(gate.shouldWrite('protocol'), true, 'the first snapshot should persist immediately')
now += 1_000
assert.equal(gate.shouldWrite('protocol'), false, 'one-second polling should not stringify a full snapshot each tick')
now += 4_000
assert.equal(gate.shouldWrite('protocol'), true, 'the latest snapshot should persist at the bounded interval')
now += 1
assert.equal(gate.shouldWrite('protocol', { force: true }), true, 'terminal and unmount snapshots must bypass throttling')

const page = readFileSync(path.join(src, 'components/UsPaypalPage.vue'), 'utf8')
assert.match(page, /const jobSnapshotWriteGate = createSnapshotWriteGate\(/)
assert.match(page, /jobSnapshotWriteGate\.shouldWrite\(storageKey, \{ force \}\)/)
assert.match(page, /persistLinkJobState\(\{\}, \{ force: true \}\)/)
assert.match(page, /persistProtocolJobState\(\{\}, \{ force: true \}\)/)
assert.match(page, /persistPay153JobState\(\{\}, \{ force: true \}\)/)

console.log(`job snapshot persistence performance tests passed: logs=${logs.length}->${compact.logs.length} interval=5000ms`)
