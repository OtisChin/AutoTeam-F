import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { readPollingSnapshot } from '../src/pollingRecovery.js'

const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')

function functionSource(code, name) {
  const signature = `function ${name}(`
  const signatureStart = code.indexOf(signature)
  assert.notEqual(signatureStart, -1, `missing function ${name}`)
  const start = code.slice(Math.max(0, signatureStart - 6), signatureStart) === 'async '
    ? signatureStart - 6
    : signatureStart
  const bodyStartMarker = code.indexOf(') {', signatureStart + signature.length)
  const bodyStart = bodyStartMarker < 0 ? -1 : bodyStartMarker + 2
  assert.notEqual(bodyStart, -1, `missing body for ${name}`)

  let depth = 0
  let quote = ''
  let escaped = false
  let lineComment = false
  let blockComment = false
  for (let index = bodyStart; index < code.length; index += 1) {
    const current = code[index]
    const next = code[index + 1]
    if (lineComment) {
      if (current === '\n') lineComment = false
      continue
    }
    if (blockComment) {
      if (current === '*' && next === '/') {
        blockComment = false
        index += 1
      }
      continue
    }
    if (quote) {
      if (escaped) {
        escaped = false
      } else if (current === '\\') {
        escaped = true
      } else if (current === quote) {
        quote = ''
      }
      continue
    }
    if (current === '/' && next === '/') {
      lineComment = true
      index += 1
      continue
    }
    if (current === '/' && next === '*') {
      blockComment = true
      index += 1
      continue
    }
    if (current === "'" || current === '"' || current === '`') {
      quote = current
      continue
    }
    if (current === '{') depth += 1
    if (current === '}') {
      depth -= 1
      if (depth === 0) return code.slice(start, index + 1)
    }
  }
  throw new Error(`unterminated function ${name}`)
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function state(value) {
  return { value }
}

function executablePaymentFlow({ startName, pollName, cancelName, cancelFlag, dependencies }) {
  const names = Object.keys(dependencies)
  return Function(
    ...names,
    `let ${cancelFlag} = false
${functionSource(source, startName)}
${functionSource(source, pollName)}
${functionSource(source, cancelName)}
return { start: ${startName}, cancel: ${cancelName}, cancelRequested: () => ${cancelFlag} }`,
  )(...names.map(name => dependencies[name]))
}

function executableRecoveryFlow({ resumeName, cancelFlag, dependencies }) {
  const names = Object.keys(dependencies)
  return Function(
    ...names,
    `let ${cancelFlag} = true
${functionSource(source, resumeName)}
return ${resumeName}`,
  )(...names.map(name => dependencies[name]))
}

function commonDependencies(events) {
  return {
    componentUnmounted: false,
    paypalPolling: {
      waitUntilAvailable: async () => true,
      wait: async () => true,
    },
    readPollingSnapshot,
    AUTO_PAYMENT_STATUS_RETRY_MS: 5_000,
    activeTab: state('links'),
    phonePoolReuseEnabled: state(false),
    claimPhonePoolEntriesForSubmission: () => [],
    phonePoolPayloadForSubmission: () => '',
    formatPhonePoolEntries: () => '',
    createPaypalClientRequestId: kind => `${kind}-request`,
    cleanError: error => String(error?.message || error),
    missingPaymentJobIdError: message => new Error(message),
    setBaPoolStatus: () => {},
    syncBaPoolFromJob: () => {},
    syncPhonePoolStatusFromJobResult: () => {},
    releaseClaimedPhonePoolEntriesAfterJob: (...args) => events.push(['release', args[1]]),
    nextTick: async () => {},
    refreshAccounts: async () => {},
    storageWriter: { remove: key => events.push(['remove', key]) },
  }
}

async function verifyProtocolCancelledAfterDeferredAcknowledgement() {
  const acknowledgement = deferred()
  const events = []
  const protocolRecoveryCheckpoint = state(null)
  const protocolRecoveryPaused = state(false)
  const protocolJob = state(null)
  const protocolForm = state({
    smsProvider: 'hero_sms',
    phonePool: '',
    paypalLink: '',
    phone: '',
    smsRecordUrl: '',
    proxies: '',
    country: 'US',
    accountEmail: '',
    concurrency: 1,
    proxyPreflightAttempts: 5,
    smsRecordWaitSeconds: 300,
    smsRecordPollSeconds: 3,
  })
  const dependencies = {
    ...commonDependencies(events),
    protocolRecoveryPaused,
    protocolSubmissionGuard: { cancel: () => events.push(['submission-guard-cancel']) },
    protocolSelectedEmails: state([]),
    protocolLinkSelectableEmails: state(new Set()),
    selectedProtocolAccountEmails: state(new Set()),
    validateProtocolPayment: () => true,
    selectedProtocolBaItems: state([{ id: 'protocol-ba', paypalLink: 'https://paypal.example/BA-PROTOCOL' }]),
    protocolForm,
    protocolBusy: state(false),
    protocolCanceling: state(false),
    protocolLogs: state([]),
    protocolResult: state(null),
    protocolJob,
    protocolLogRef: state(null),
    protocolRecoveryCheckpoint,
    protocolClaimedPhonePoolKeysByJob: new Map(),
    PROTOCOL_JOB_STORAGE_KEY: 'protocol-job',
    saveProtocolForm: () => {},
    persistProtocolJobState: (snapshot, options) => events.push(['persist', snapshot, options]),
    setProtocolStatus: message => events.push(['status', message]),
    submitProtocolManualJob: () => {
      events.push(['start-requested'])
      return acknowledgement.promise
    },
    drainProtocolAutoPayQueue: () => {},
    api: {
      cancelUsPaypalProtocolJob: async (jobId) => {
        events.push(['cancel-response', jobId, 'cancelling'])
        return { id: jobId, status: 'cancelling' }
      },
      getUsPaypalProtocolJob: async (jobId) => {
        events.push(['get-response', jobId, 'cancelled'])
        return { id: jobId, status: 'cancelled', total: 1, completed: 0, logs: [], result: {} }
      },
    },
  }
  const flow = executablePaymentFlow({
    startName: 'startProtocolPayment',
    pollName: 'pollProtocolJob',
    cancelName: 'cancelProtocolJob',
    cancelFlag: 'protocolSubmissionCancelRequested',
    dependencies,
  })

  const running = flow.start()
  await Promise.resolve()
  assert.deepEqual(events.filter(event => event[0] === 'start-requested'), [['start-requested']])
  await flow.cancel()
  assert.equal(flow.cancelRequested(), true, 'a pre-ACK cancel must remain visible to the ACK continuation')

  acknowledgement.resolve({ job_id: 'protocol-job-1' })
  const result = await running

  assert.equal(result, false, 'a cancelled start should preserve its false result after terminal reconciliation')
  assert.deepEqual(
    events.filter(event => event[0] === 'cancel-response' || event[0] === 'get-response'),
    [
      ['cancel-response', 'protocol-job-1', 'cancelling'],
      ['get-response', 'protocol-job-1', 'cancelled'],
    ],
    'protocol must keep polling after a cancelling response until GET confirms cancelled',
  )
  assert.equal(protocolJob.value.status, 'cancelled')
  assert.equal(events.filter(event => event[0] === 'release' && event[1] === 'protocol').length, 1)
}

async function verifyPay153UnknownOutcomeAfterDeferredAcknowledgement() {
  const acknowledgement = deferred()
  const events = []
  const pay153RecoveryCheckpoint = state(null)
  const pay153RecoveryPaused = state(false)
  const pay153Job = state(null)
  const pay153Form = state({
    smsProvider: 'hero_sms',
    phonePool: '',
    paypalLink: '',
    phone: '',
    smsRecordUrl: '',
    proxies: 'proxy',
    country: 'US',
    buyerMode: 'identity_elevation',
    concurrency: 1,
    smsRecordWaitSeconds: 300,
    smsRecordPollSeconds: 3,
  })
  const dependencies = {
    ...commonDependencies(events),
    pay153RecoveryPaused,
    pay153SubmissionGuard: { cancel: () => events.push(['submission-guard-cancel']) },
    pay153SelectedEmails: state([]),
    pay153LinkSelectableEmails: state(new Set()),
    selectedPay153AccountEmails: state(new Set()),
    validatePay153Payment: () => true,
    selectedPay153BaItems: state([{ id: 'pay153-ba', paypalLink: 'https://paypal.example/BA-153' }]),
    pay153Form,
    pay153Busy: state(false),
    pay153Canceling: state(false),
    pay153Logs: state([]),
    pay153Result: state(null),
    pay153Job,
    pay153LogRef: state(null),
    pay153WaitingActions: state([]),
    pay153RecoveryCheckpoint,
    pay153ClaimedPhonePoolKeysByJob: new Map(),
    PAY153_JOB_STORAGE_KEY: 'pay153-job',
    savePay153Form: () => {},
    persistPay153JobState: (snapshot, options) => events.push(['persist', snapshot, options]),
    setPay153Status: message => events.push(['status', message]),
    submitPay153ManualJob: () => {
      events.push(['start-requested'])
      return acknowledgement.promise
    },
    drainPay153AutoPayQueue: () => {},
    api: {
      cancelUsPaypal153Job: async (jobId) => {
        events.push(['cancel-response', jobId, 'cancelling'])
        return { id: jobId, status: 'cancelling' }
      },
      getUsPaypal153Job: async (jobId) => {
        events.push(['get-response', jobId, 'unknown_outcome'])
        return {
          id: jobId,
          status: 'unknown_outcome',
          total: 1,
          completed: 0,
          logs: [],
          result: {},
          error: 'remote result unknown',
        }
      },
    },
  }
  const flow = executablePaymentFlow({
    startName: 'startPay153Payment',
    pollName: 'pollPay153Job',
    cancelName: 'cancelPay153Job',
    cancelFlag: 'pay153SubmissionCancelRequested',
    dependencies,
  })

  const running = flow.start()
  await Promise.resolve()
  assert.deepEqual(events.filter(event => event[0] === 'start-requested'), [['start-requested']])
  await flow.cancel()
  assert.equal(flow.cancelRequested(), true, 'a pre-ACK 153 cancel must remain visible to the ACK continuation')

  acknowledgement.resolve({ job_id: 'pay153-job-1' })
  const result = await running

  assert.equal(result, false, 'an indeterminate cancelled start should preserve its false result after reconciliation')
  assert.deepEqual(
    events.filter(event => event[0] === 'cancel-response' || event[0] === 'get-response'),
    [
      ['cancel-response', 'pay153-job-1', 'cancelling'],
      ['get-response', 'pay153-job-1', 'unknown_outcome'],
    ],
    '153 must keep polling after a cancelling response until GET confirms unknown_outcome',
  )
  assert.equal(pay153Job.value.status, 'unknown_outcome')
  assert.equal(pay153RecoveryPaused.value, true)
  assert.equal(pay153RecoveryCheckpoint.value.unknownOutcome, true)
  assert.equal(events.filter(event => event[0] === 'release' && event[1] === 'pay153').length, 0)
}

async function verifyRecoveredAcknowledgementContinuesCancellationPolling() {
  for (const mode of [
    {
      resumeName: 'resumeUnknownProtocolPaymentStart',
      cancelFlag: 'protocolSubmissionCancelRequested',
      prefix: 'protocol',
      jobId: 'protocol-recovered-job',
    },
    {
      resumeName: 'resumeUnknownPay153PaymentStart',
      cancelFlag: 'pay153SubmissionCancelRequested',
      prefix: 'pay153',
      jobId: 'pay153-recovered-job',
    },
  ]) {
    const events = []
    const recoveryCheckpoint = state(null)
    const recoveryPaused = state(true)
    const job = state(null)
    const claimedKeysByJob = new Map()
    const upperPrefix = mode.prefix === 'protocol' ? 'Protocol' : 'Pay153'
    const dependencies = {
      [`${mode.prefix}RecoveryCheckpoint`]: recoveryCheckpoint,
      [`submit${upperPrefix}ManualJob`]: async () => ({ job_id: mode.jobId }),
      componentUnmounted: false,
      missingPaymentJobIdError: message => new Error(message),
      [`${mode.prefix}ClaimedPhonePoolKeysByJob`]: claimedKeysByJob,
      [`${mode.prefix}Job`]: job,
      [`${mode.prefix}RecoveryPaused`]: recoveryPaused,
      [`persist${upperPrefix}JobState`]: () => {},
      [`cancel${upperPrefix}Job`]: async () => events.push(['cancel', mode.jobId]),
      [`poll${upperPrefix}Job`]: async jobId => events.push(['poll', jobId]),
    }
    const resume = executableRecoveryFlow({
      resumeName: mode.resumeName,
      cancelFlag: mode.cancelFlag,
      dependencies,
    })

    await resume({ submitPayload: {}, claimedPhonePoolKeys: ['phone-1'], accountCount: 1, concurrency: 1 })

    assert.deepEqual(
      events,
      [['cancel', mode.jobId], ['poll', mode.jobId]],
      `${mode.resumeName} must reconcile the accepted job to terminal after replaying a deferred cancel`,
    )
    assert.equal(job.value.id, mode.jobId)
    assert.deepEqual(claimedKeysByJob.get(mode.jobId), ['phone-1'])
  }
}

const selectedCase = process.argv[2] || 'all'
assert.ok(['all', 'protocol', 'pay153'].includes(selectedCase), `unknown case: ${selectedCase}`)
if (selectedCase === 'all' || selectedCase === 'protocol') {
  await verifyProtocolCancelledAfterDeferredAcknowledgement()
}
if (selectedCase === 'all' || selectedCase === 'pay153') {
  await verifyPay153UnknownOutcomeAfterDeferredAcknowledgement()
}
if (selectedCase === 'all') {
  await verifyRecoveredAcknowledgementContinuesCancellationPolling()
}

console.log('PayPal pre-ACK cancel terminal polling regression passed')
