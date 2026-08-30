import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

import { readPollingSnapshot } from '../src/pollingRecovery.js'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/components/IdealLinkPage.vue'), 'utf8')
const api = readFileSync(resolve(root, 'src/api.js'), 'utf8')

for (const text of ['荷兰iDEAL 提链', '账号池选择', '已提取 iDEAL 链接', '开始提链']) {
  assert(page.includes(text), `IdealLinkPage should render ${text}`)
}

for (const symbol of ['accounts', 'links', 'selectedEmails', 'start', 'refreshLinks']) {
  assert(page.includes(symbol), `IdealLinkPage should manage ${symbol}`)
}

for (const helper of ['getIdealAccounts', 'startIdealBatch', 'getIdealJob', 'cancelIdealJob', 'releaseIdealUnknownJob', 'getIdealLinks', 'deleteIdealLinks', 'clearIdealLinks', 'getIdealLongLinkJobByClientRequest']) {
  assert(api.includes(helper), `api.js should expose ${helper}`)
}

assert.match(page, /const JOB_STORAGE_KEY = ['"]autotoken_ideal_active_job_v1['"]/, 'iDEAL should reserve a dedicated persisted job identity')
assert.match(page, /persistIdealJob\([^)]*kind:\s*['"]batch['"]/, 'batch start should persist the acknowledged job kind and id before polling')
assert.match(page, /persistIdealJob\([^)]*kind:\s*['"]long-link['"]/, 'long-link start should persist the acknowledged job kind and id before polling')
assert.match(page, /restoreIdealJob\(\)[\s\S]*?pollRestoredIdealJob/, 'mount should restore and resume the acknowledged job instead of starting a replacement')
assert.match(page, /onBeforeUnmount\([\s\S]*?idealPolling\.dispose\(\)/, 'unmount should stop only this component polling lifecycle')
assert.doesNotMatch(
  page.slice(page.indexOf('onBeforeUnmount(')),
  /(?:removeItem|storageWriter\.remove)\(JOB_STORAGE_KEY\)/,
  'unmount must not discard the durable iDEAL job identity',
)
assert.match(page, /account\?\.ideal_selectable === false/, 'server-side account occupancy should make an account unselectable')
assert.match(page, /:disabled="busy \|\| deletingIdealAccounts\.has\(account\.email\) \|\| !accountSelectable\(account\)"/, 'occupied accounts should not be deletable from their row')
assert.match(page, /unknown_outcome/, 'an indeterminate restored task should remain isolated rather than be treated as terminal')
assert.match(api, /releaseIdealUnknownJob:\s*\(jobId\)\s*=>\s*request\('POST', `\/ideal\/jobs\/\$\{encodeURIComponent\(jobId\)\}\/reconcile-release`\)/, 'iDEAL should expose the explicit manual reconciliation endpoint')
assert.match(page, /v-if="currentJobStatus === 'unknown_outcome'"[\s\S]{0,500}?@click="releaseUnknownIdealJob"/, 'unknown iDEAL jobs should show a dedicated manual-review release button')
const releaseUnknown = page.slice(
  page.indexOf('async function releaseUnknownIdealJob'),
  page.indexOf('async function retryFailedAccounts'),
)
assert.match(releaseUnknown, /window\.confirm\([\s\S]*?已核对[\s\S]*?不会自动重提/, 'manual release should require an explicit reviewed/no-auto-retry confirmation')
assert.match(releaseUnknown, /await api\.releaseIdealUnknownJob\(jobId\)/, 'manual release should call the job-scoped backend endpoint')
assert.match(releaseUnknown, /idealPolling\.cancel\(\)[\s\S]*?clearPersistedIdealJob\(jobId\)[\s\S]*?await reloadAll\(\)/, 'manual release should stop stale polling, clear the durable identity, and refresh accounts')
assert.doesNotMatch(releaseUnknown, /(?:startIdealBatch|start\(\)|generate\(\))/, 'manual release must never automatically resubmit remote work')

const persistJob = page.slice(
  page.indexOf('function persistIdealJob'),
  page.indexOf('function clearPersistedIdealJob'),
)
const restoreJob = page.slice(
  page.indexOf('function restoreIdealJob'),
  page.indexOf('function quarantineCurrentIdealJob'),
)
const restoredPoll = page.slice(
  page.indexOf('async function pollRestoredIdealJob'),
  page.indexOf('function badgeClass'),
)
const generateLongLink = page.slice(
  page.indexOf('async function generate'),
  page.indexOf('async function testProxy'),
)

assert.match(persistJob, /if \(!jobId && !clientRequestId\) return false/, 'a pre-acknowledgement checkpoint should persist with only clientRequestId')
assert.match(persistJob, /durable = \{ jobId, clientRequestId, kind, status, accountEmails, updatedAt:/, 'the durable checkpoint should retain the idempotency key alongside any acknowledged job id')
assert.doesNotMatch(persistJob, /accessToken|submitPayload/, 'the durable iDEAL checkpoint must not persist the access token or submission payload')
assert.match(restoreJob, /jobId \|\| clientRequestId/, 'refresh should retain an unacknowledged long-link checkpoint by clientRequestId')
assert.match(restoredPoll, /lookupRestoredIdealLongLinkJob\(saved\.clientRequestId, pollToken\)/, 'refresh should recover the original backend job by idempotency key instead of reposting')
assert.match(page, /async function lookupRestoredIdealLongLinkJob[\s\S]*?getIdealLongLinkJobByClientRequest\(clientRequestId\)/, 'the bounded recovery helper should query the original idempotency key')
assert.doesNotMatch(restoredPoll, /startIdealLongLink/, 'restoring an unknown submission must never start replacement remote work')
assert.match(generateLongLink, /const clientRequestId = createIdealClientRequestId\(\)/, 'each explicit long-link submission should create one client request id')
assert.match(
  generateLongLink,
  /persistIdealJob\(\{ jobId: '', clientRequestId, kind: 'long-link', status: 'submitting'[^}]*\}\)[\s\S]*?await api\.startIdealLongLink\(\{ \.\.\.requestPayload\(\), clientRequestId \}\)/,
  'the idempotency checkpoint must be durable before the POST begins and the same key must be sent to the backend',
)
assert.match(
  generateLongLink,
  /if \(!persistIdealJob\(\{ jobId: '', clientRequestId, kind: 'long-link', status: 'submitting'[^}]*\}\)\) \{[\s\S]*?throw new Error\([^)]*未提交远端任务[^)]*\)[\s\S]*?\}[\s\S]*?submissionStarted = true[\s\S]*?await api\.startIdealLongLink/,
  'the remote POST must fail closed when its pre-acknowledgement checkpoint cannot be persisted',
)
assert.match(generateLongLink, /isAmbiguousPaymentFailure\(error\)[\s\S]*?quarantineCurrentIdealJob\(error\)/, 'timeout, network, and 5xx submission failures should keep an unknown checkpoint')
assert.match(releaseUnknown, /jobId \|\| clientRequestId/, 'manual review should release a pre-acknowledgement checkpoint that has only a clientRequestId')
assert.doesNotMatch(releaseUnknown, /startIdealLongLink/, 'manual release must not replay the long-link POST')
assert.match(page, /createSessionStorageFacade\(\)/, 'iDEAL job and form persistence should capture the current session owner')
assert.doesNotMatch(page, /localStorage\.(?:setItem|removeItem)\(/, 'iDEAL must not bypass the session-owner fence for direct writes or removals')
assert.match(
  generateLongLink,
  /await api\.startIdealLongLink\([\s\S]*?if \(!canCommitIdealTask\(pollToken\)\) return[\s\S]*?persistIdealJob\(\{ jobId: data\.job_id/,
  'a late long-link POST response must pass the lifecycle fence before persisting its acknowledged job',
)
assert.match(
  generateLongLink,
  /await pollJob\(data\.job_id, pollToken\)\s+if \(!canCommitIdealTask\(pollToken\)\) return/,
  'long-link completion must not publish after unmount or lifecycle replacement',
)
assert.match(page, /onBeforeUnmount\(\(\) => \{\s+componentUnmounted = true\s+idealPolling\.dispose\(\)/, 'unmount should invalidate asynchronous long-link commits before disposing polling')

function section(source, start, end) {
  const startIndex = source.indexOf(start)
  const endIndex = source.indexOf(end, startIndex + start.length)
  assert.notEqual(startIndex, -1, `missing source section ${start}`)
  assert.notEqual(endIndex, -1, `missing source section terminator ${end}`)
  return source.slice(startIndex, endIndex)
}

const restoredLookupSource = section(
  page,
  'async function lookupRestoredIdealLongLinkJob',
  'async function pollRestoredIdealJob',
)
const restoredPollingSource = section(
  page,
  'async function pollRestoredIdealJob',
  'function badgeClass',
)
assert.match(restoredLookupSource, /idealPolling\.waitUntilAvailable\(pollToken\)/, 'pre-ACK lookup should respect the shared lifecycle availability gate before every request')
assert.match(restoredLookupSource, /readPollingSnapshot\s*\(\{/, 'pre-ACK lookup should share the bounded polling recovery classifier')
assert.match(restoredLookupSource, /request:\s*\(\) => api\.getIdealLongLinkJobByClientRequest\(clientRequestId\)/, 'pre-ACK lookup should retry the idempotency-key GET rather than reposting')
assert.match(restoredLookupSource, /wait:\s*delayMs => idealPolling\.wait\(delayMs, pollToken\)/, 'pre-ACK transient retries should use the same lifecycle token')
assert.match(restoredLookupSource, /attempt:\s*lookupFailures/, 'pre-ACK lookup should carry consecutive failures across retries')
assert.match(restoredLookupSource, /if \(recovery\.kind === 'retry'\) \{[\s\S]*?lookupFailures = recovery\.attempt[\s\S]*?continue/, 'pre-ACK lookup should continue after a transient retry result')
assert.match(restoredPollingSource, /if \(recovery\.kind === 'missing'\)[\s\S]*?quarantineCurrentIdealJob/, 'pre-ACK 404 should have an explicit missing-job branch')
assert.match(restoredPollingSource, /if \(recovery\.kind === 'permanent'\)[\s\S]*?quarantineCurrentIdealJob/, 'pre-ACK permanent 4xx should stop immediately in its own branch')
assert.match(restoredPollingSource, /if \(recovery\.kind === 'paused'\)[\s\S]*?quarantineCurrentIdealJob/, 'pre-ACK transient exhaustion should isolate only after the shared budget is consumed')

function createRestoredLookupHarness(sequence, options = {}) {
  const token = Symbol('ideal-recovery-token')
  let active = true
  let lookupCalls = 0
  const waits = []
  const availabilityTokens = []
  const waitTokens = []
  const persistCalls = []
  const pollCalls = []
  const quarantineCalls = []
  const statusWrites = []
  const responses = [...sequence]
  const apiHarness = {
    async getIdealLongLinkJobByClientRequest(clientRequestId) {
      lookupCalls += 1
      assert.equal(clientRequestId, 'client-original')
      const response = responses.shift()
      if (options.invalidateDuringRequest) active = false
      if (response instanceof Error) throw response
      return response
    },
  }
  const pollingHarness = {
    start: () => token,
    isActive: candidate => active && candidate === token,
    async waitUntilAvailable(candidate) {
      availabilityTokens.push(candidate)
      return active && candidate === token
    },
    async wait(delayMs, candidate) {
      waits.push(delayMs)
      waitTokens.push(candidate)
      return active && candidate === token
    },
  }
  const currentJobStatus = { value: 'submitting' }
  const runtimeBadge = { value: null }
  const busy = { value: true }
  const canCommitIdealTask = candidate => active && candidate === token
  const factory = Function(
    'api',
    'idealPolling',
    'readPollingSnapshot',
    'canCommitIdealTask',
    'setStatus',
    'cleanText',
    'persistIdealJob',
    'pollJob',
    'pollIdealJob',
    'quarantineCurrentIdealJob',
    'runtimeBadge',
    'busy',
    'isBlockingIdealJob',
    `${restoredLookupSource}\n${restoredPollingSource}; return { lookupRestoredIdealLongLinkJob, pollRestoredIdealJob }`,
  )
  const functions = factory(
    apiHarness,
    pollingHarness,
    readPollingSnapshot,
    canCommitIdealTask,
    (...args) => statusWrites.push(args),
    value => String(value?.message || value || ''),
    snapshot => { persistCalls.push(snapshot); currentJobStatus.value = snapshot.status || currentJobStatus.value; return true },
    async (jobId, candidate) => { pollCalls.push({ jobId, token: candidate }) },
    async () => { throw new Error('batch polling should not run in this harness') },
    error => { quarantineCalls.push(error); return true },
    runtimeBadge,
    busy,
    () => true,
  )
  return {
    ...functions,
    token,
    deactivate: () => { active = false },
    stats: () => ({ lookupCalls, waits, availabilityTokens, waitTokens, persistCalls, pollCalls, quarantineCalls, statusWrites, runtimeBadge, busy }),
  }
}

const transient503 = () => Object.assign(new Error('temporarily unavailable'), { status: 503 })

const recoveredHarness = createRestoredLookupHarness([transient503(), { job_id: 'ideal-original', status: 'running' }])
await recoveredHarness.pollRestoredIdealJob({ jobId: '', clientRequestId: 'client-original', kind: 'long-link', status: 'submitting' }, recoveredHarness.token)
const recoveredStats = recoveredHarness.stats()
assert.equal(recoveredStats.lookupCalls, 2, 'a transient first lookup should retry the original idempotency key')
assert.deepEqual(recoveredStats.waits, [1000], 'the first transient lookup should consume one shared backoff sleep')
assert.ok(recoveredStats.availabilityTokens.every(token => token === recoveredHarness.token), 'every lookup availability gate should receive the original poll token')
assert.ok(recoveredStats.waitTokens.every(token => token === recoveredHarness.token), 'every retry sleep should receive the original poll token')
assert.equal(recoveredStats.quarantineCalls.length, 0, 'a 503 followed by recovery must not quarantine the task')
assert.deepEqual(recoveredStats.pollCalls, [{ jobId: 'ideal-original', token: recoveredHarness.token }], 'successful lookup should continue into long-link polling with the same token')
assert.equal(recoveredStats.persistCalls.at(-1)?.jobId, 'ideal-original', 'the recovered job id should become durable before long-link polling')

for (const [label, error, expectedCalls] of [
  ['missing', Object.assign(new Error('not found'), { status: 404 }), 1],
  ['permanent', Object.assign(new Error('unprocessable'), { status: 422 }), 1],
]) {
  const harness = createRestoredLookupHarness([error])
  await harness.pollRestoredIdealJob({ jobId: '', clientRequestId: 'client-original', kind: 'long-link', status: 'submitting' }, harness.token)
  const stats = harness.stats()
  assert.equal(stats.lookupCalls, expectedCalls, `${label} lookup should stop without a transient retry`)
  assert.equal(stats.pollCalls.length, 0, `${label} lookup should not enter job-id polling`)
  assert.equal(stats.quarantineCalls.length, 1, `${label} lookup should enter its explicit isolated recovery state`)
}

const exhaustedHarness = createRestoredLookupHarness(Array.from({ length: 5 }, transient503))
await exhaustedHarness.pollRestoredIdealJob({ jobId: '', clientRequestId: 'client-original', kind: 'long-link', status: 'submitting' }, exhaustedHarness.token)
const exhaustedStats = exhaustedHarness.stats()
assert.equal(exhaustedStats.lookupCalls, 5, 'pre-ACK lookup should consume the full five-failure transient budget')
assert.deepEqual(exhaustedStats.waits, [1000, 2000, 4000, 8000], 'the final transient failure should pause without a sixth lookup or sleep')
assert.equal(exhaustedStats.pollCalls.length, 0, 'an exhausted lookup should not enter job-id polling')
assert.equal(exhaustedStats.quarantineCalls.length, 1, 'only exhausted transient recovery should quarantine the pre-ACK checkpoint')

const invalidatedHarness = createRestoredLookupHarness([{ job_id: 'late-job', status: 'running' }], { invalidateDuringRequest: true })
await invalidatedHarness.pollRestoredIdealJob({ jobId: '', clientRequestId: 'client-original', kind: 'long-link', status: 'submitting' }, invalidatedHarness.token)
const invalidatedStats = invalidatedHarness.stats()
assert.equal(invalidatedStats.persistCalls.length, 0, 'a lifecycle-invalidated lookup must not persist late state')
assert.equal(invalidatedStats.pollCalls.length, 0, 'a lifecycle-invalidated lookup must not start late polling')
assert.equal(invalidatedStats.quarantineCalls.length, 0, 'a lifecycle-invalidated lookup must not quarantine after unmount/replacement')
assert.equal(invalidatedStats.statusWrites.length, 0, 'a lifecycle-invalidated lookup must not publish late status')

console.log('ideal link page UI contract passed')
