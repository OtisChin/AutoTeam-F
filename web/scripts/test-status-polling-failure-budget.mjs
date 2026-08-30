import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  MAX_POLLING_TRANSIENT_FAILURES,
  isPermanentPollingError,
  isTransientPollingError,
  readPollingSnapshot,
} from '../src/pollingRecovery.js'

assert.equal(MAX_POLLING_TRANSIENT_FAILURES, 5, 'status reconciliation should have a finite consecutive-failure budget')

for (const status of [400, 401, 403, 409, 422]) {
  assert.equal(isPermanentPollingError({ status }), true, `HTTP ${status} should stop the current polling run`)
  assert.equal(isTransientPollingError({ status }), false, `HTTP ${status} should not consume retry sleeps`)
  let waited = false
  const error = Object.assign(new Error(`HTTP ${status}`), { status })
  const result = await readPollingSnapshot({
    request: async () => { throw error },
    wait: async () => { waited = true; return true },
  })
  assert.equal(result.kind, 'permanent', `HTTP ${status} should stop immediately`)
  assert.equal(waited, false, `HTTP ${status} should not wait before stopping`)
}

for (const status of [408, 425, 429, 500, 503]) {
  assert.equal(isPermanentPollingError({ status }), false, `HTTP ${status} should remain retryable`)
  assert.equal(isTransientPollingError({ status }), true, `HTTP ${status} should consume the transient budget`)
}
assert.equal(isTransientPollingError(new TypeError('fetch failed')), true, 'network failures should remain retryable')

const waits = []
let attempt = 0
let result
for (;;) {
  const error = Object.assign(new Error('upstream unavailable'), { status: 503 })
  result = await readPollingSnapshot({
    request: async () => { throw error },
    wait: async delayMs => { waits.push(delayMs); return true },
    attempt,
    maxAttempts: 3,
  })
  if (result.kind !== 'retry') break
  attempt = result.attempt
}
assert.equal(result.kind, 'paused', 'a continuously transient status endpoint should pause after its budget')
assert.equal(result.attempt, 3)
assert.deepEqual(waits, [1000, 2000], 'the final failed attempt should pause without another sleep')

function page(name) {
  return readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
}

function section(source, start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.notEqual(startIndex, -1, `missing source section ${start}`)
  assert.notEqual(endIndex, -1, `missing source section terminator ${end}`)
  return source.slice(startIndex, endIndex)
}

for (const [name, start, end, storagePattern] of [
  ['BrazilPixPage.vue', 'async function poll(jobId', 'function resumeStoredPixTask', /clearStoredPixTask/],
  ['IndiaUpiPage.vue', 'async function pollJob(jobId', 'async function cancelJob', /storageWriter\.remove\(JOB_STORAGE_KEY\)/],
]) {
  const body = section(page(name), start, end)
  assert.match(body, /\['permanent', 'paused'\]\.includes\(recovery\.kind\)/, `${name} should stop permanent failures and exhausted transient retries`)
  const pausedBranch = body.match(/if \(\['permanent', 'paused'\][\s\S]*?return\s*\}/)?.[0] || ''
  assert.ok(pausedBranch, `${name} should expose one bounded pause branch`)
  assert.doesNotMatch(pausedBranch, storagePattern, `${name} should retain the stored job for route re-entry recovery`)
}

const brazil = page('BrazilPixPage.vue')
const brazilLockSource = section(
  brazil,
  'function isBlockingPixExtractionJob',
  'function applyStartAckCheckpoint',
)
assert.match(
  brazil,
  /const PIX_EXTRACTION_TERMINAL_STATUSES = new Set\(\['success', 'error', 'failed', 'cancelled'\]\)/,
  'Brazil should distinguish acknowledged terminal snapshots from resumable jobs',
)
const brazilPendingModes = new Set()
const brazilLock = Function(
  'PIX_EXTRACTION_TERMINAL_STATUSES',
  'startAckPendingModes',
  'taskKey',
  `${brazilLockSource}; return { isBlockingPixExtractionJob, syncPixExtractionBusy }`,
)(new Set(['success', 'error', 'failed', 'cancelled']), brazilPendingModes, () => 'extract')
const brazilTask = { busy: { value: false }, currentJob: { value: { id: 'pix-original', status: 'recovery_paused' } } }
assert.equal(brazilLock.isBlockingPixExtractionJob(brazilTask.currentJob.value), true, 'Brazil recovery_paused should remain an acknowledged blocking job')
assert.equal(brazilLock.syncPixExtractionBusy(brazilTask), true, 'Brazil pause completion should keep the mutation lock engaged')
for (const status of ['success', 'error', 'failed', 'cancelled']) {
  brazilTask.currentJob.value = { id: 'pix-original', status }
  assert.equal(brazilLock.syncPixExtractionBusy(brazilTask), false, `Brazil ${status} should release the mutation lock`)
}
brazilTask.currentJob.value = null
assert.equal(brazilLock.syncPixExtractionBusy(brazilTask), false, 'Brazil missing jobs should release the mutation lock')
brazilPendingModes.add('extract')
assert.equal(brazilLock.syncPixExtractionBusy(brazilTask), true, 'Brazil should remain locked while a start acknowledgement is pending')
brazilPendingModes.clear()

const brazilStart = section(brazil, 'async function startWithEmails', 'async function start()')
assert.match(brazilStart, /if \(syncPixExtractionBusy\(task\)\) \{[\s\S]*?return false[\s\S]*?\}/, 'Brazil start should reject an acknowledged non-terminal job inside the mutation function')
assert.ok(
  brazilStart.indexOf('syncPixExtractionBusy(task)') < brazilStart.indexOf('task.currentJob.value = null'),
  'Brazil should check the mutation lock before clearing the acknowledged job snapshot',
)
let brazilValidationCalls = 0
let brazilReservationCalls = 0
let brazilStoredJobId = 'pix-original'
brazilTask.currentJob.value = { id: brazilStoredJobId, status: 'recovery_paused' }
const runBrazilStart = Function(
  'isTempExtract',
  'tempTask',
  'extractTask',
  'syncPixExtractionBusy',
  'setStatus',
  'validateStart',
  'reserveStartAckGeneration',
  `${brazilStart}; return startWithEmails`,
)(
  { value: false },
  { busy: { value: false }, currentJob: { value: null } },
  brazilTask,
  brazilLock.syncPixExtractionBusy,
  () => {},
  () => { brazilValidationCalls += 1; return true },
  () => { brazilReservationCalls += 1; brazilStoredJobId = 'pix-replacement'; return null },
)
assert.equal(await runBrazilStart(['owner@example.com']), false)
assert.equal(brazilValidationCalls, 0, 'Brazil blocked starts should stop before validation and mutation setup')
assert.equal(brazilReservationCalls, 0, 'Brazil blocked starts should not reserve a replacement submission')
assert.equal(brazilStoredJobId, 'pix-original', 'Brazil blocked starts should preserve the durable original job id')
assert.equal(brazilTask.currentJob.value.id, 'pix-original', 'Brazil blocked starts should preserve the in-memory original job id')

const brazilResume = section(brazil, 'function resumeStoredPixTask', 'function resumeStoredPixTasks')
assert.match(brazilResume, /\.finally\(\(\) => \{[\s\S]*?syncPixExtractionBusy\(task\)/, 'Brazil restored polling should resynchronize busy from both acknowledgement and job state')
assert.match(brazilStart, /finally \{[\s\S]*?syncPixExtractionBusy\(task\)/, 'Brazil start completion should resynchronize busy from both acknowledgement and job state')
assert.match(brazil, /v-if="busy && currentJob\?\.id"[\s\S]{0,180}?@click="cancelJob"/, 'Brazil should retain the cancel/recovery action while the mutation lock is active')

const india = page('IndiaUpiPage.vue')
const indiaLockSource = section(
  india,
  'function isBlockingUpiExtractionJob',
  'function applyStartAckCheckpoint',
)
const indiaBusy = { value: false }
const indiaStartAckPending = { value: false }
const indiaCurrentJob = { value: { id: 'upi-original', status: 'recovery_paused' } }
const indiaLock = Function(
  'TERMINAL_STATUSES',
  'busy',
  'startAckPending',
  'currentJob',
  `${indiaLockSource}; return { isBlockingUpiExtractionJob, syncUpiExtractionBusy }`,
)(new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented']), indiaBusy, indiaStartAckPending, indiaCurrentJob)
assert.equal(indiaLock.isBlockingUpiExtractionJob(indiaCurrentJob.value), true, 'India recovery_paused should remain an acknowledged blocking job')
assert.equal(indiaLock.syncUpiExtractionBusy(), true, 'India pause completion should keep the mutation lock engaged')
for (const status of ['success', 'error', 'failed', 'cancelled', 'not_implemented']) {
  indiaCurrentJob.value = { id: 'upi-original', status }
  assert.equal(indiaLock.syncUpiExtractionBusy(), false, `India ${status} should release the mutation lock`)
}
indiaCurrentJob.value = null
assert.equal(indiaLock.syncUpiExtractionBusy(), false, 'India missing jobs should release the mutation lock')
indiaStartAckPending.value = true
assert.equal(indiaLock.syncUpiExtractionBusy(), true, 'India should remain locked while a start acknowledgement is pending')
indiaStartAckPending.value = false

const indiaStart = section(india, 'async function startWithEmails', 'async function start()')
assert.match(indiaStart, /if \(syncUpiExtractionBusy\(\)\) \{[\s\S]*?return false[\s\S]*?\}/, 'India start should reject an acknowledged non-terminal job inside the mutation function')
assert.ok(
  indiaStart.indexOf('syncUpiExtractionBusy()') < indiaStart.indexOf('currentJob.value = null'),
  'India should check the mutation lock before clearing the acknowledged job snapshot',
)
let indiaValidationCalls = 0
let indiaReservationCalls = 0
let indiaStoredJobId = 'upi-original'
indiaCurrentJob.value = { id: indiaStoredJobId, status: 'running' }
const runIndiaStart = Function(
  'isTempExtract',
  'syncUpiExtractionBusy',
  'setStatus',
  'validateStart',
  'reserveStartAckGeneration',
  `${indiaStart}; return startWithEmails`,
)(
  { value: false },
  indiaLock.syncUpiExtractionBusy,
  () => {},
  () => { indiaValidationCalls += 1; return true },
  () => { indiaReservationCalls += 1; indiaStoredJobId = 'upi-replacement'; return null },
)
assert.equal(await runIndiaStart(['owner@example.com']), false)
assert.equal(indiaValidationCalls, 0, 'India blocked starts should stop before validation and mutation setup')
assert.equal(indiaReservationCalls, 0, 'India blocked starts should not reserve a replacement submission')
assert.equal(indiaStoredJobId, 'upi-original', 'India blocked starts should preserve the durable original job id')
assert.equal(indiaCurrentJob.value.id, 'upi-original', 'India blocked starts should preserve the in-memory original job id')

const indiaRestore = section(india, 'function restoreActiveJob', 'onMounted(async () =>')
assert.match(indiaRestore, /finally \{[\s\S]*?syncUpiExtractionBusy\(\)/, 'India restored polling should resynchronize busy from both acknowledgement and job state')
assert.match(indiaStart, /finally \{[\s\S]*?syncUpiExtractionBusy\(\)/, 'India start completion should resynchronize busy from both acknowledgement and job state')
assert.match(india, /v-if="busy && currentJob\?\.id"[\s\S]{0,180}?@click="cancelJob"/, 'India should retain the cancel/recovery action while the mutation lock is active')

const ideal = page('IdealLinkPage.vue')
for (const [start, end] of [
  ['async function pollIdealJob', 'async function start()'],
  ['async function pollJob', 'async function generate()'],
]) {
  const body = section(ideal, start, end)
  assert.match(body, /readPollingSnapshot\s*\(/, `${start} should use shared status classification and retry budgeting`)
  assert.match(body, /\['missing', 'permanent', 'paused'\]/, `${start} should quarantine every indeterminate stop`)
  assert.match(body, /quarantineCurrentIdealJob/, `${start} should retain the job and account quarantine`)
}

const paypal = page('UsPaypalPage.vue')
for (const [start, end] of [
  ['async function pollProtocolJob', 'async function cancelProtocolJob'],
  ['async function pollPay153Job', 'async function submitPay153Otp'],
  ['async function pollProtocolAutoPayJob', 'async function pollPay153AutoPayJob'],
  ['async function pollPay153AutoPayJob', 'async function drainProtocolAutoPayQueue'],
]) {
  const body = section(paypal, start, end)
  assert.match(body, /readPollingSnapshot\s*\(/, `${start} should use the shared finite retry policy`)
  assert.match(body, /recovery_paused/, `${start} should retain a resumable paused checkpoint`)
  const pauseBranch = body.match(/if \(\['permanent', 'paused'\][\s\S]*?return\s*\}/)?.[0] || ''
  assert.ok(pauseBranch, `${start} should stop permanent errors and exhausted transient failures`)
  assert.doesNotMatch(pauseBranch, /releaseClaimedPhonePoolEntriesAfterJob|removeAutoPayActiveJob/, `${start} should keep account and phone ownership quarantined`)
}

console.log('status polling failure classification and bounded recovery contract passed')
