import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  isAmbiguousPaymentFailure,
} from '../src/paymentRequestState.js'

const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')

function functionSource(code, name) {
  const plain = `function ${name}(`
  const async = `async function ${name}(`
  const asyncStart = code.indexOf(async)
  const start = asyncStart >= 0 ? asyncStart : code.indexOf(plain)
  assert.notEqual(start, -1, `missing function ${name}`)
  const nextFunction = /\n(?:async )?function [A-Za-z0-9_]+\(/g
  nextFunction.lastIndex = start + 1
  const next = nextFunction.exec(code)
  return code.slice(start, next ? next.index : code.length)
}

function executableFunction(code, name, dependencies = {}) {
  const names = Object.keys(dependencies)
  return Function(...names, `return (${functionSource(code, name)})`)(...names.map(key => dependencies[key]))
}

function state(value) {
  return { value }
}

function activeSubmissionUpdater(activeRef, clientRequestId, patch) {
  activeRef.value = activeRef.value.map(item => item.clientRequestId === clientRequestId ? { ...item, ...patch } : item)
}

function activeSubmissionRemover(activeRef, clientRequestId) {
  activeRef.value = activeRef.value.filter(item => item.clientRequestId !== clientRequestId)
}

const missingPaymentJobIdError = executableFunction(source, 'missingPaymentJobIdError')
const missingResponseError = missingPaymentJobIdError('HTTP 200 response omitted job_id')
assert.equal(
  isAmbiguousPaymentFailure(missingResponseError),
  true,
  'a successful HTTP response without job_id is an ambiguous start acknowledgement',
)

async function verifyManualMissingJobId({
  submitName,
  apiMethod,
  guardName,
  cancelName,
  checkpointName,
  pausedName,
  statusName,
  persistName,
}) {
  const clientRequestId = `${submitName}-stable-request`
  const submitPayload = { clientRequestId, accountEmails: ['buyer@example.com'] }
  const checkpoint = { clientRequestId, submitPayload, claimedPhonePoolKeys: ['phone-1'] }
  const apiCalls = []
  const persisted = []
  const recoveryCheckpoint = state(null)
  const recoveryPaused = state(false)
  const guard = { start: () => 1, isActive: token => token === 1 }
  const polling = {
    waitUntilAvailable: async () => true,
    wait: async () => true,
  }
  const api = {
    [apiMethod]: async (payload) => {
      apiCalls.push(payload)
      return {}
    },
  }
  const dependencies = {
    [guardName]: guard,
    [cancelName]: false,
    componentUnmounted: false,
    paypalPolling: polling,
    api,
    [pausedName]: recoveryPaused,
    [checkpointName]: recoveryCheckpoint,
    [statusName]: () => {},
    [persistName]: value => persisted.push(value),
    isAmbiguousPaymentFailure,
    missingPaymentJobIdError,
    PAYMENT_RECOVERY_MAX_ATTEMPTS: 2,
    paymentRecoveryDelayMs: () => 1,
    cleanError: error => String(error?.message || error),
  }
  const submit = executableFunction(source, submitName, dependencies)

  const result = await submit(submitPayload, checkpoint)

  assert.equal(result, null, `${submitName} should pause after bounded acknowledgement recovery`)
  assert.equal(apiCalls.length, 2, `${submitName} should treat each HTTP 200 {} as ambiguous and retry reconciliation`)
  assert.deepEqual(
    apiCalls.map(payload => payload.clientRequestId),
    [clientRequestId, clientRequestId],
    `${submitName} must reuse the original idempotency key`,
  )
  assert.equal(recoveryCheckpoint.value.clientRequestId, clientRequestId)
  assert.equal(recoveryCheckpoint.value.submitPayload, submitPayload)
  assert.equal(recoveryCheckpoint.value.recoveryPaused, true)
  assert.equal(recoveryPaused.value, true)
  assert.equal(persisted.at(-1).clientRequestId, clientRequestId)
  assert.equal(persisted.at(-1).submitPayload, submitPayload)
}

await verifyManualMissingJobId({
  submitName: 'submitProtocolManualJob',
  apiMethod: 'startUsPaypalProtocolBatch',
  guardName: 'protocolSubmissionGuard',
  cancelName: 'protocolSubmissionCancelRequested',
  checkpointName: 'protocolRecoveryCheckpoint',
  pausedName: 'protocolRecoveryPaused',
  statusName: 'setProtocolStatus',
  persistName: 'persistProtocolJobState',
})
await verifyManualMissingJobId({
  submitName: 'submitPay153ManualJob',
  apiMethod: 'startUsPaypal153Batch',
  guardName: 'pay153SubmissionGuard',
  cancelName: 'pay153SubmissionCancelRequested',
  checkpointName: 'pay153RecoveryCheckpoint',
  pausedName: 'pay153RecoveryPaused',
  statusName: 'setPay153Status',
  persistName: 'persistPay153JobState',
})

for (const [startName, nextName] of [
  ['startProtocolPayment', 'pollProtocolJob'],
  ['startPay153Payment', 'retryFailedPay153Payment'],
]) {
  const body = source.slice(source.indexOf(`async function ${startName}`), source.indexOf(`async function ${nextName}`))
  assert.ok(
    body.indexOf('if (!data) return false') < body.indexOf('if (!data.job_id)'),
    `${startName} must return with its recovery checkpoint intact when acknowledgement recovery pauses`,
  )
}

async function verifyAutoMissingJobId(kind) {
  const protocol = kind === 'protocol'
  const email = `${kind}@example.com`
  const clientRequestId = `${kind}-stable-request`
  const activeRef = state([])
  const releaseCalls = []
  const reconciliationCalls = []
  const generatedIds = []
  const apiCalls = []
  const persistCalls = []
  const form = state({
    smsProvider: 'hero_sms',
    phonePool: 'pool',
    phone: '+447700900001',
    smsRecordUrl: '',
    proxies: 'proxy-one',
    country: 'GB',
    accountEmail: email,
    proxyPreflightAttempts: 1,
    smsRecordWaitSeconds: 60,
    smsRecordPollSeconds: 1,
    paypalLink: '',
    buyerMode: 'identity_elevation',
  })
  const common = {
    componentUnmounted: false,
    autoPayCandidateStillRunnable: () => true,
    claimPhonePoolEntriesForSubmission: () => [],
    phonePoolReuseEnabled: state(false),
    phonePoolPayloadForSubmission: () => '',
    formatPhonePoolEntries: () => '',
    createPaypalClientRequestId: () => {
      generatedIds.push(clientRequestId)
      return clientRequestId
    },
    missingPaymentJobIdError,
    isAmbiguousPaymentFailure,
    cleanError: error => String(error?.message || error),
    updateAutoPayActiveSubmission: activeSubmissionUpdater,
    removeAutoPayActiveSubmission: activeSubmissionRemover,
    persistPaypalAutoPayState: value => persistCalls.push(value),
    releaseClaimedPhonePoolEntriesAfterJob: (...args) => releaseCalls.push(args),
    mergePaymentResult: (current, addition) => ({ ...(current || {}), ...addition }),
    storageWriter: { writeJsonNow: () => {} },
    PHONE_POOL_MANAGEMENT_STORAGE_KEY: 'phone-pool',
    phonePoolStatusMap: state(new Map()),
  }

  let launch
  if (protocol) {
    launch = executableFunction(source, 'launchProtocolAutoPayItem', {
      ...common,
      protocolAutoPayActive: state(true),
      protocolLinkAccountOptions: state([]),
      protocolAutoPayActiveJobs: activeRef,
      protocolPaymentAccountStatus: () => 'pending',
      protocolBusy: state(false),
      protocolSelectedEmails: state([]),
      protocolForm: form,
      validateProtocolPayment: () => true,
      saveProtocolForm: () => {},
      api: { startUsPaypalProtocolBatch: async payload => apiCalls.push(payload) && {} },
      protocolClaimedPhonePoolKeysByJob: new Map(),
      protocolAutoPayStatusText: state(''),
      reconcileProtocolAutoPayStart: (...args) => reconciliationCalls.push(args),
      pollProtocolAutoPayJob: () => {},
      protocolResult: state(null),
      drainProtocolAutoPayQueue: () => {},
    })
  } else {
    launch = executableFunction(source, 'launchPay153AutoPayItem', {
      ...common,
       pay153AutoPayActive: state(true),
       pay153Canceling: state(false),
       pay153RecoveryPaused: state(false),
       pay153LinkAccountOptions: state([]),
      pay153AutoPayActiveJobs: activeRef,
      pay153PaymentAccountStatus: () => 'pending',
      pay153Busy: state(false),
      pay153SelectedEmails: state([]),
      pay153Form: form,
      validatePay153Payment: () => true,
      savePay153Form: () => {},
      api: { startUsPaypal153Batch: async payload => apiCalls.push(payload) && {} },
      pay153ClaimedPhonePoolKeysByJob: new Map(),
      pay153AutoPayStatusText: state(''),
      reconcilePay153AutoPayStart: (...args) => reconciliationCalls.push(args),
      pollPay153AutoPayJob: () => {},
      pay153Result: state(null),
      drainPay153AutoPayQueue: () => {},
    })
  }

  await launch({ email, key: `${kind}-queue-item` })

  assert.deepEqual(generatedIds, [clientRequestId], `${kind} auto-pay must generate exactly one idempotency key`)
  assert.equal(apiCalls.length, 1)
  assert.equal(apiCalls[0].clientRequestId, clientRequestId)
  assert.equal(releaseCalls.length, 0, `${kind} auto-pay must not release a phone after HTTP 200 {}`)
  assert.equal(activeRef.value.length, 1, `${kind} auto-pay must retain its active checkpoint`)
  assert.equal(activeRef.value[0].clientRequestId, clientRequestId)
  assert.equal(activeRef.value[0].submitPayload.clientRequestId, clientRequestId)
  assert.equal(activeRef.value[0].status, 'unknown')
  assert.deepEqual(reconciliationCalls, [[email, clientRequestId]])
  assert.ok(persistCalls.length >= 2, `${kind} auto-pay should durably persist pre-submit and ambiguous states`)
}

await verifyAutoMissingJobId('protocol')
await verifyAutoMissingJobId('pay153')

console.log('paypal missing job-id acknowledgement recovery passed')
