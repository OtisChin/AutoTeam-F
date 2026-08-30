import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')
const start = source.indexOf('function queuePaymentJobSnapshot')
const end = source.indexOf('function persistProtocolJobState', start)
assert.ok(start >= 0 && end > start, 'PayPal snapshot persistence section should exist')
const queueSnapshot = source.slice(start, end)

assert.match(
  queueSnapshot,
  /if \(componentUnmounted\) \{\s*storageWriter\.writeJsonNow\(storageKey, payload\)\s*return true\s*\}/,
  'a start response received after unmount should synchronously preserve its recoverable job ID',
)
assert.ok(
  queueSnapshot.indexOf('if (componentUnmounted)') < queueSnapshot.indexOf('jobSnapshotWriteGate.shouldWrite'),
  'late acknowledged jobs should bypass the snapshot throttle that was flushed during unmount',
)

const immediateWrites = []
const deferredWrites = []
const queuePaymentJobSnapshot = Function(
  'componentUnmounted',
  'TERMINAL_STATUSES',
  'jobSnapshotWriteGate',
  'storageWriter',
  `return (${queueSnapshot.trim()})`,
)(
  false,
  new Set(['success', 'failed', 'cancelled']),
  { shouldWrite: () => true },
  {
    writeJsonNow: (key, payload) => immediateWrites.push([key, payload]),
    queueJson: (key, payload) => deferredWrites.push([key, payload]),
  },
)

const preAck = { clientRequestId: 'request-1', submitPayload: { accountEmails: ['buyer@example.com'] }, job: null }
assert.equal(queuePaymentJobSnapshot('paypal-job', preAck, { force: true }), true)
assert.deepEqual(immediateWrites, [['paypal-job', preAck]], 'a forced pre-acknowledgement checkpoint must reach storage before the remote request starts')
assert.deepEqual(deferredWrites, [], 'a forced checkpoint must not wait for an idle callback')

const terminal = { job: { id: 'job-1', status: 'success' } }
assert.equal(queuePaymentJobSnapshot('paypal-job', terminal), true)
assert.deepEqual(immediateWrites.at(-1), ['paypal-job', terminal], 'terminal ownership changes must be persisted synchronously')

console.log('PayPal late job persistence contract passed')
