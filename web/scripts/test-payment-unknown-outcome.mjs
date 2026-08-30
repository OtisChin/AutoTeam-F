import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const requestState = await import('../src/paymentRequestState.js').catch(() => null)
assert.ok(requestState, 'payment request state helpers should exist')
assert.equal(requestState.PAYMENT_SUBMIT_TIMEOUT_MS, 80_000)
assert.equal(requestState.PAYMENT_STATUS_TIMEOUT_MS, 25_000)
assert.equal(requestState.isAmbiguousPaymentFailure({ code: 'REQUEST_TIMEOUT', timeout: true }), true)
assert.equal(requestState.isAmbiguousPaymentFailure({ status: 502, code: 'remote_api_unreachable' }), true)
assert.equal(requestState.isAmbiguousPaymentFailure(new TypeError('fetch failed')), true)
assert.equal(requestState.isAmbiguousPaymentFailure({ status: 400, code: 'bad_body' }), false)
assert.equal(requestState.isAmbiguousPaymentFailure({ code: 'cdk_invalid', data: { ok: false } }), false)

const api = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
for (const method of ['submitBrazilPixPayment', 'submitIndiaUpiPayment', 'createKakaoPayKkPaymentOrder', 'submitKakaoPayKkPayment']) {
  assert.match(api, new RegExp(`${method}:[^\n]+PAYMENT_SUBMIT_TIMEOUT_MS`), `${method} should outlive the backend's 70-second upstream timeout`)
}
for (const method of ['getBrazilPixPaymentJob', 'getIndiaUpiPaymentJob', 'getKakaoPayKkPaymentOrder']) {
  assert.match(api, new RegExp(`${method}:[^\n]+PAYMENT_STATUS_TIMEOUT_MS`), `${method} should not abort before the backend's 20-second status timeout`)
}

function source(name) {
  if (process.env.PAYMENT_COMPONENT_FIXTURE_DIR) {
    return readFileSync(resolve(process.env.PAYMENT_COMPONENT_FIXTURE_DIR, name), 'utf8')
  }
  return readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
}

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

function pureFunction(code, name, dependencies = {}) {
  const dependencyNames = Object.keys(dependencies)
  return Function(...dependencyNames, `return (${functionSource(code, name)})`)(...dependencyNames.map(key => dependencies[key]))
}

function sourceSegment(code, startText, endText) {
  const start = code.indexOf(startText)
  assert.notEqual(start, -1, `missing segment start: ${startText}`)
  const end = code.indexOf(endText, start + startText.length)
  assert.notEqual(end, -1, `missing segment end: ${endText}`)
  return code.slice(start, end)
}

function matchCount(code, pattern) {
  return Array.from(code.matchAll(pattern)).length
}

function state(value) {
  return { value }
}

const brazil = source('BrazilPixPage.vue')
const india = source('IndiaUpiPage.vue')
const kakao = source('KakaoPayPage.vue')

const brazilHasLiveJob = pureFunction(brazil, 'paymentTaskHasLiveRemoteJob')
const indiaHasLiveJob = pureFunction(india, 'paymentTaskHasLiveRemoteJob')
const kakaoHasLiveOrder = pureFunction(kakao, 'kkPaymentHasLiveRemoteOrder')

for (const [label, helper, live, terminal, missing] of [
  ['Brazil PIX', brazilHasLiveJob,
    { jobId: 'job-1', statusToken: 'token-1', remoteTerminal: false },
    { jobId: 'job-1', statusToken: 'token-1', remoteTerminal: true },
    { jobId: 'job-1', remoteTerminal: false }],
  ['India UPI', indiaHasLiveJob,
    { jobId: 'job-1', jobToken: 'token-1', remoteTerminal: false },
    { jobId: 'job-1', jobToken: 'token-1', remoteTerminal: true },
    { statusToken: 'token-1', remoteTerminal: false }],
  ['Kakao Pay', kakaoHasLiveOrder,
    { orderId: 'order-1', customerToken: 'token-1', remoteTerminal: false },
    { orderId: 'order-1', customerToken: 'token-1', remoteTerminal: true },
    { customerToken: 'token-1', remoteTerminal: false }],
]) {
  assert.equal(helper(live), true, `${label} should quarantine an acknowledged nonterminal remote record`)
  assert.equal(helper(terminal), false, `${label} should release a confirmed terminal remote record`)
  assert.equal(helper(missing), false, `${label} should not fabricate a remote record without its identifier and credential`)
}

const normalizeBrazilPayment = pureFunction(brazil, 'normalizePaymentItem', {
  makePaymentId: () => 'generated',
  paymentTaskHasLiveRemoteJob: brazilHasLiveJob,
})
const legacyBrazilSuccess = normalizeBrazilPayment({
  id: 'legacy-success', value: 'https://pix.example/pay', status: 'success',
  jobId: 'job-1', statusToken: 'token-1', cdk: 'cdk-1',
}, 'link')
assert.equal(legacyBrazilSuccess.remoteTerminal, true, 'Brazil PIX should migrate a pre-flag successful row as terminal')
assert.equal(brazilHasLiveJob(legacyBrazilSuccess), false, 'Brazil PIX should not quarantine a legacy successful row forever')
assert.equal(normalizeBrazilPayment({
  id: 'confirmed-success', value: 'https://pix.example/pay', status: 'success',
  jobId: 'job-confirmed', statusToken: 'token-confirmed', remoteTerminal: false,
}, 'link').remoteTerminal, true, 'Brazil PIX should treat its local success state as terminal proof')
const restoredBrazilRunning = normalizeBrazilPayment({
  id: 'live-running', value: 'https://pix.example/pay', status: 'running',
  jobId: 'job-2', statusToken: 'token-2', remoteTerminal: false,
}, 'link')
assert.equal(restoredBrazilRunning.status, 'needs_action', 'Brazil PIX should make a persisted live running job queryable after reload')

const normalizeIndiaPayment = pureFunction(india, 'normalizePaymentItem', {
  normalizePaymentUrl: value => String(value || '').trim().replace(/\/+$/, ''),
  makePaymentId: () => 'generated',
})
const legacyIndiaSuccess = normalizeIndiaPayment({
  id: 'legacy-success', value: 'https://upi.example/pay', status: 'success',
  jobId: 'job-1', statusToken: 'token-1', cdk: 'cdk-1',
})
assert.equal(legacyIndiaSuccess.remoteTerminal, true, 'India UPI should migrate a pre-flag successful row as terminal')
assert.equal(indiaHasLiveJob(legacyIndiaSuccess), false, 'India UPI should not quarantine a legacy successful row forever')
assert.equal(normalizeIndiaPayment({
  id: 'confirmed-success', value: 'https://upi.example/pay', status: 'success',
  jobId: 'job-confirmed', statusToken: 'token-confirmed', remoteTerminal: false,
}).remoteTerminal, true, 'India UPI should treat its local success state as terminal proof')
const restoredIndiaRunning = normalizeIndiaPayment({
  id: 'live-running', value: 'https://upi.example/pay', status: 'running',
  jobId: 'job-2', statusToken: 'token-2', remoteTerminal: false,
})
assert.equal(restoredIndiaRunning.status, 'needs_action', 'India UPI should make a persisted live running job queryable after reload')
assert.equal(indiaHasLiveJob(restoredIndiaRunning), true)
const indiaRunnable = pureFunction(india, 'paymentTaskRunnable', {
  paymentTaskHasLiveRemoteJob: indiaHasLiveJob,
  paymentLinkInvalid: () => true,
  PAYMENT_RETRYABLE_LINK_STATUSES: new Set(),
  paymentCdks: state([]),
  paymentCdkReusable: () => false,
})
assert.equal(indiaRunnable(restoredIndiaRunning), true, 'India UPI should query a restored live job even if its local link is no longer usable')

const normalizeKakaoPayment = pureFunction(kakao, 'normalizeKkPaymentItem', {
  normalizeKkPaymentUrl: value => String(value || '').trim().replace(/\/+$/, ''),
  kakaoLinkUrl: () => '',
  kkPaymentOrderMissing: () => false,
  makeKkPaymentId: () => 'generated',
})
const ordinaryKakaoFailure = normalizeKakaoPayment({
  id: 'local-queue-id', paymentUrl: 'https://kakao.example/pay', status: 'needs_action',
  cdk: 'cdk-1', orderId: '', customerToken: '',
})
assert.equal(ordinaryKakaoFailure.orderId, '', 'Kakao should never derive a remote order id from the local queue id')
assert.equal(kakaoHasLiveOrder(ordinaryKakaoFailure), false, 'Kakao should not quarantine an ordinary pre-submit rejection')
const legacyKakaoSuccess = normalizeKakaoPayment({
  id: 'legacy-success', paymentUrl: 'https://kakao.example/pay', status: 'success',
  orderId: 'order-1', customerToken: 'token-1', cdk: 'cdk-1',
})
assert.equal(legacyKakaoSuccess.remoteTerminal, true, 'Kakao should migrate a pre-flag successful row as terminal')
assert.equal(kakaoHasLiveOrder(legacyKakaoSuccess), false, 'Kakao should not quarantine a legacy successful row forever')
assert.equal(normalizeKakaoPayment({
  id: 'confirmed-success', paymentUrl: 'https://kakao.example/pay', status: 'success',
  orderId: 'order-confirmed', customerToken: 'token-confirmed', remoteTerminal: false,
}).remoteTerminal, true, 'Kakao should treat its local success state as terminal proof')

const brazilClearable = pureFunction(brazil, 'paymentTaskClearable', { paymentTaskHasLiveRemoteJob: brazilHasLiveJob })
const indiaClearable = pureFunction(india, 'paymentTaskClearable', {
  paymentTaskHasLiveRemoteJob: indiaHasLiveJob,
  paymentLinkInvalid: () => false,
})
for (const [label, helper, credentials] of [
  ['Brazil PIX', brazilClearable, { jobId: 'job-1', statusToken: 'token-1' }],
  ['India UPI', indiaClearable, { jobId: 'job-1', statusToken: 'token-1' }],
]) {
  assert.equal(helper({ ...credentials, status: 'failed', remoteTerminal: false }), false, `${label} cleanup should retain every live remote job regardless of local display status`)
  assert.equal(helper({ ...credentials, status: 'failed', remoteTerminal: true }), true, `${label} cleanup should remove the same row after terminal confirmation`)
}

for (const [name, page] of [['BrazilPixPage.vue', brazil], ['IndiaUpiPage.vue', india]]) {
  const wait = functionSource(page, 'waitPaymentJob')
  const runName = name.startsWith('Brazil') ? 'runPaymentPair' : 'runPaymentTask'
  const run = functionSource(page, runName)
  const remove = functionSource(page, 'removePaymentLink')
  const clear = functionSource(page, 'clearPaymentLinks')
  const finished = functionSource(page, 'clearFinishedPayments')
  assert.match(wait, /status: LOCAL_PAYMENT_POLL_PAUSED/, `${name} should distinguish a local polling pause from a remote terminal result`)
  assert.match(wait, /PAYMENT_TERMINAL_STATUSES\.has\(status\)/, `${name} should return a confirmed terminal status from polling`)
  assert.match(run, /status = hasExistingJob \? 'needs_action' : 'unknown'/, `${name} should quarantine an ambiguous remote outcome`)
  assert.match(remove, /if \(paymentTaskHasLiveRemoteJob\(item\)\) \{[\s\S]*?return[\s\S]*?\}/, `${name} single-row removal should return before deleting a live job`)
  assert.match(clear, /const retained = paymentLinks\.value\.filter\(paymentTaskHasLiveRemoteJob\)/, `${name} clear-all should positively select live jobs for retention`)
  assert.match(clear, /paymentLinks\.value = retained/, `${name} clear-all should assign the retained live-job set`)
  assert.match(finished, /paymentLinks\.value = paymentLinks\.value\.filter\(item => !paymentTaskClearable\(item\)\)/, `${name} finished cleanup should keep non-clearable live jobs`)
}

const brazilRemoveCdk = functionSource(brazil, 'removePaymentCdk')
assert.match(brazilRemoveCdk, /const linkedLiveJob = paymentLinks\.value\.find\(item => paymentTaskHasLiveRemoteJob\(item\)/, 'Brazil PIX single-CDK removal should identify its exact live job')
assert.match(brazilRemoveCdk, /if \(linkedLiveJob\) \{[\s\S]*?return[\s\S]*?\}/, 'Brazil PIX single-CDK removal should return before deleting a live reservation')
const brazilFinished = functionSource(brazil, 'clearFinishedPayments')
assert.match(brazilFinished, /const protectedJobs = paymentLinks\.value\.filter\(paymentTaskHasLiveRemoteJob\)/)
assert.match(brazilFinished, /protectedCdkIds\.has\(item\.id\)[\s\S]*protectedCdkValues\.has\(item\.value\)[\s\S]*protectedLinkIds\.has\(item\.linkId\)/, 'Brazil PIX finished cleanup should retain all CDK associations for live jobs')

const indiaClearCdks = functionSource(india, 'clearPaymentCdks')
assert.match(indiaClearCdks, /if \(paymentTaskHasLiveRemoteJob\(link\)\) continue/, 'India UPI clear-all should not detach a live job from its CDK')
assert.match(indiaClearCdks, /paymentCdks\.value = paymentCdks\.value\.filter\(paymentCdkSupportsLiveRemoteJob\)/, 'India UPI clear-all should positively retain live-job CDKs')
const indiaExpired = functionSource(india, 'clearExpiredPaymentLinks')
assert.match(indiaExpired, /paymentLinkInvalid\(item\) && !paymentTaskHasLiveRemoteJob\(item\)/, 'India UPI expiry cleanup should exclude live jobs')
const indiaFinished = functionSource(india, 'clearFinishedPayments')
assert.match(indiaFinished, /paymentCdkSupportsLiveRemoteJob\(item\) \|\| !\['used', 'failed'\]\.includes\(item\.status\)/, 'India UPI finished cleanup should retain a used or failed CDK that still supports a live job')

const kakaoCanRemove = functionSource(kakao, 'kkPaymentCanRemove')
assert.match(kakaoCanRemove, /if \(kkPaymentHasLiveRemoteOrder\(item\)\) return false/, 'Kakao removal eligibility should reject a live order')
const kakaoRemove = functionSource(kakao, 'removeKkPaymentLink')
assert.match(kakaoRemove, /if \(kkPaymentHasLiveRemoteOrder\(item\)\) \{[\s\S]*?return[\s\S]*?\}/, 'Kakao single-row removal should return before deleting a live order')
const kakaoClear = functionSource(kakao, 'clearKkPaymentLinks')
assert.match(kakaoClear, /const retained = kkPaymentLinks\.value\.filter\(kkPaymentHasLiveRemoteOrder\)/, 'Kakao clear-all should positively select live orders for retention')
assert.match(kakaoClear, /kkPaymentLinks\.value = retained/, 'Kakao clear-all should assign the retained live-order set')
const kakaoDetach = functionSource(kakao, 'detachKkPaymentCdkFromLinks')
assert.match(kakaoDetach, /if \(kkPaymentHasLiveRemoteOrder\(link\)\) continue/, 'Kakao CDK detach should skip live orders')
const kakaoRemoveCdk = functionSource(kakao, 'removeKkPaymentCdk')
assert.match(kakaoRemoveCdk, /if \(kkPaymentCdkHasLiveRemoteOrder\(target\)\) \{[\s\S]*?return[\s\S]*?\}/, 'Kakao single-CDK removal should return before deleting a live reservation')
const kakaoClearUsedCdks = functionSource(kakao, 'clearUsedKkPaymentCdks')
assert.match(kakaoClearUsedCdks, /kkPaymentCdkDisplayStatus\(item\) === 'used' && !kkPaymentCdkHasLiveRemoteOrder\(item\)/, 'Kakao used-CDK cleanup should exclude live-order reservations')
const kakaoClearCdks = functionSource(kakao, 'clearKkPaymentCdks')
assert.match(kakaoClearCdks, /const retained = kkPaymentCdks\.value\.filter\(kkPaymentCdkHasLiveRemoteOrder\)/, 'Kakao clear-all should positively select live-order CDKs for retention')
assert.match(kakaoClearCdks, /kkPaymentCdks\.value = retained/, 'Kakao clear-all should assign the retained live-order CDK set')
const kakaoInvalid = functionSource(kakao, 'clearInvalidKkPaymentLinks')
assert.match(kakaoInvalid, /kkPaymentLinkInvalid\(item\) && !kkPaymentHasLiveRemoteOrder\(item\)/, 'Kakao invalid-link cleanup should exclude live orders')
const kakaoFinished = functionSource(kakao, 'clearFinishedKkPayments')
assert.match(kakaoFinished, /!kkPaymentHasLiveRemoteOrder\(item\) && \(kkPaymentLinkInvalid\(item\) \|\| removableStatuses\.includes\(item\.status\)\)/, 'Kakao finished cleanup should exclude live orders')
assert.match(kakaoFinished, /kkPaymentCdkHasLiveRemoteOrder\(item\) \|\| !\['used', 'failed'\]\.includes\(item\.status\)/, 'Kakao finished cleanup should retain live-order CDKs')

const addOrUpdateKakao = functionSource(kakao, 'addOrUpdateKkPaymentLink')
assert.match(addOrUpdateKakao, /remoteTerminal: existing\.remoteTerminal/, 'Kakao link refresh should preserve terminal reconciliation state')
assert.match(addOrUpdateKakao, /&& !kkPaymentHasLiveRemoteOrder\(row\)/, 'Kakao stale-link replacement should exclude live orders')
assert.match(functionSource(kakao, 'removeAccountFromKakaoPool'), /\|\| kkPaymentHasLiveRemoteOrder\(item\)/, 'Kakao account-pool cleanup should retain live orders')
assert.match(functionSource(kakao, 'reExtractKkPaymentLink'), /if \(kkPaymentHasLiveRemoteOrder\(item\)\) \{[\s\S]*?return/, 'Kakao relinking should reject a live order')

const kakaoRestorable = pureFunction(kakao, 'kkPaymentOrderRestorable', { kkPaymentHasLiveRemoteOrder: kakaoHasLiveOrder })
const expiredAmbiguousOrder = {
  orderId: 'order-1', customerToken: 'token-1', cdk: 'cdk-1', remoteTerminal: false,
  status: 'needs_action', message: '网络超时；远端结果未知，已锁定关联 CDK，避免重复支付。',
  kakao_expires_at_ts: 1,
}
assert.equal(kakaoRestorable(expiredAmbiguousOrder), true, 'Kakao should reconcile a live ambiguous order even when its payment link expired')
assert.match(functionSource(kakao, 'kkPaymentOrderRestorable'), /return kkPaymentHasLiveRemoteOrder\(item\)/, 'Kakao restorability should key on acknowledged nonterminal order identity, not link TTL or message text')
const kakaoRunnable = pureFunction(kakao, 'kkPaymentTaskRunnable', {
  kkPaymentHasLiveRemoteOrder: kakaoHasLiveOrder,
  kkPaymentLinkInvalid: () => true,
  KK_PAYMENT_RETRYABLE_STATUSES: new Set(),
  kkPaymentCdks: state([]),
  kkPaymentCdkUsable: () => false,
})
assert.equal(kakaoRunnable(expiredAmbiguousOrder), true, 'Kakao submit-all should query a live order before rejecting an expired local link')

// Execute representative destructive paths so an inverted filter or guard polarity fails the contract.
{
  const live = { id: 'live', status: 'needs_action', jobId: 'job-live', statusToken: 'token-live', remoteTerminal: false }
  const done = { id: 'done', status: 'needs_action', jobId: 'job-done', statusToken: 'token-done', remoteTerminal: true }
  const paymentLinks = state([live, done])
  const paymentCdks = state([
    { id: 'cdk-live', linkId: 'live', status: 'reserved' },
    { id: 'cdk-done', linkId: 'done', status: 'reserved' },
  ])
  const clear = pureFunction(brazil, 'clearPaymentLinks', {
    paymentLinks, paymentCdks, paymentBusy: state(false), paymentStatusText: state(''),
    paymentTaskHasLiveRemoteJob: brazilHasLiveJob,
  })
  clear()
  assert.deepEqual(paymentLinks.value.map(item => item.id), ['live'])
  assert.equal(paymentCdks.value[0].status, 'reserved', 'Brazil PIX should keep the live job CDK reserved')
  assert.equal(paymentCdks.value[1].status, 'available', 'Brazil PIX should release a confirmed terminal row CDK')

  const remove = pureFunction(brazil, 'removePaymentLink', {
    paymentLinks, paymentCdks, paymentStatusText: state(''), paymentTaskHasLiveRemoteJob: brazilHasLiveJob,
  })
  remove('live')
  assert.deepEqual(paymentLinks.value.map(item => item.id), ['live'], 'Brazil PIX should reject deletion of a live row')
  live.remoteTerminal = true
  remove('live')
  assert.deepEqual(paymentLinks.value, [], 'Brazil PIX should allow deletion after terminal confirmation')
}

{
  const live = { id: 'live', status: 'needs_action', jobId: 'job-live', statusToken: 'token-live', remoteTerminal: false, cdkId: 'cdk-live', cdk: 'live-value' }
  const done = { id: 'done', status: 'needs_action', jobId: 'job-done', statusToken: 'token-done', remoteTerminal: true, cdkId: 'cdk-done', cdk: 'done-value' }
  const paymentLinks = state([live, done])
  const paymentCdks = state([
    { id: 'cdk-live', value: 'live-value', linkId: 'live', status: 'reserved' },
    { id: 'cdk-done', value: 'done-value', linkId: 'done', status: 'reserved' },
  ])
  const releaseReservedCdkForLink = pureFunction(india, 'releaseReservedCdkForLink', { paymentCdks })
  const clearLinks = pureFunction(india, 'clearPaymentLinks', {
    paymentLinks, paymentStatusText: state(''), paymentTaskHasLiveRemoteJob: indiaHasLiveJob,
    releaseReservedCdkForLink, savePaymentState: () => {},
  })
  clearLinks()
  assert.deepEqual(paymentLinks.value.map(item => item.id), ['live'])
  assert.equal(paymentCdks.value[0].status, 'reserved', 'India UPI should keep the live job CDK reserved')
  assert.equal(paymentCdks.value[1].status, 'available', 'India UPI should release a confirmed terminal row CDK')

  paymentLinks.value = [live, done]
  paymentCdks.value[1] = { id: 'cdk-done', value: 'done-value', linkId: 'done', status: 'reserved' }
  const paymentCdkSupportsLiveRemoteJob = pureFunction(india, 'paymentCdkSupportsLiveRemoteJob', {
    paymentLinks, paymentTaskHasLiveRemoteJob: indiaHasLiveJob,
  })
  const clearCdks = pureFunction(india, 'clearPaymentCdks', {
    paymentLinks, paymentCdks, paymentStatusText: state(''), paymentTaskHasLiveRemoteJob: indiaHasLiveJob,
    paymentCdkSupportsLiveRemoteJob, savePaymentState: () => {},
  })
  clearCdks()
  assert.deepEqual(paymentCdks.value.map(item => item.id), ['cdk-live'], 'India UPI should retain only the live-job CDK during clear-all')
  assert.equal(live.cdkId, 'cdk-live')
  assert.equal(done.cdkId, '', 'India UPI should detach a confirmed terminal row from a cleared CDK')

  const removableLive = { ...live, remoteTerminal: false }
  const removableDone = { ...done, remoteTerminal: true }
  paymentLinks.value = [removableLive, removableDone]
  paymentCdks.value = [
    { id: 'cdk-live', value: 'live-value', linkId: 'live', status: 'reserved' },
    { id: 'cdk-done', value: 'done-value', linkId: 'done', status: 'reserved' },
  ]
  const removeLink = pureFunction(india, 'removePaymentLink', {
    paymentLinks, paymentStatusText: state(''), paymentTaskHasLiveRemoteJob: indiaHasLiveJob,
    releaseReservedCdkForLink, savePaymentState: () => {},
  })
  removeLink('live')
  assert.deepEqual(paymentLinks.value.map(item => item.id), ['live', 'done'], 'India UPI should reject deletion of a live row')
  removeLink('done')
  assert.deepEqual(paymentLinks.value.map(item => item.id), ['live'], 'India UPI should allow deletion after terminal confirmation')
}

{
  const live = { id: 'live', status: 'needs_action', orderId: 'order-live', customerToken: 'token-live', remoteTerminal: false, cdkId: 'cdk-live', cdk: 'live-value' }
  const done = { id: 'done', status: 'needs_action', orderId: 'order-done', customerToken: 'token-done', remoteTerminal: true, cdkId: 'cdk-done', cdk: 'done-value' }
  const kkPaymentLinks = state([live, done])
  const released = []
  const clearLinks = pureFunction(kakao, 'clearKkPaymentLinks', {
    kkPaymentLinks, kkPaymentStatusText: state(''), kkPaymentHasLiveRemoteOrder: kakaoHasLiveOrder,
    releaseKkPaymentCdkForLink: id => released.push(id), collapseKkPaymentDetails: () => {}, saveKkPaymentState: () => {},
  })
  clearLinks()
  assert.deepEqual(kkPaymentLinks.value.map(item => item.id), ['live'])
  assert.deepEqual(released, ['done'], 'Kakao clear-all should release only confirmed terminal rows')

  const kkPaymentCdks = state([
    { id: 'cdk-live', value: 'live-value', status: 'used' },
    { id: 'cdk-done', value: 'done-value', status: 'used' },
  ])
  const kkPaymentCdkHasLiveRemoteOrder = pureFunction(kakao, 'kkPaymentCdkHasLiveRemoteOrder', {
    kkPaymentLinks, kkPaymentHasLiveRemoteOrder: kakaoHasLiveOrder,
  })
  const detached = []
  const clearUsed = pureFunction(kakao, 'clearUsedKkPaymentCdks', {
    kkPaymentCdks, kkPaymentStatusText: state(''), kkPaymentCdkDisplayStatus: item => item.status,
    kkPaymentCdkHasLiveRemoteOrder, detachKkPaymentCdkFromLinks: cdk => detached.push(cdk.id), saveKkPaymentState: () => {},
  })
  clearUsed()
  assert.deepEqual(kkPaymentCdks.value.map(item => item.id), ['cdk-live'], 'Kakao used-CDK cleanup should retain a live-order CDK')
  assert.deepEqual(detached, ['cdk-done'], 'Kakao used-CDK cleanup should detach only the terminal CDK')

  const removableLive = { ...live, remoteTerminal: false }
  const removableDone = { ...done, remoteTerminal: true }
  kkPaymentLinks.value = [removableLive, removableDone]
  const removeLink = pureFunction(kakao, 'removeKkPaymentLink', {
    kkPaymentLinks, kkPaymentStatusText: state(''), kkPaymentHasLiveRemoteOrder: kakaoHasLiveOrder,
    kkPaymentCanRemove: () => true, releaseKkPaymentCdkForLink: () => {}, collapseKkPaymentDetails: () => {}, saveKkPaymentState: () => {},
  })
  removeLink('live')
  assert.deepEqual(kkPaymentLinks.value.map(item => item.id), ['live', 'done'], 'Kakao should reject deletion of a live row')
  removeLink('done')
  assert.deepEqual(kkPaymentLinks.value.map(item => item.id), ['live'], 'Kakao should allow deletion after terminal confirmation')
}

// Execute acknowledgement, local-pause, terminal, and ambiguous-error transitions.
{
  const makeRunner = (waitPaymentJob, submit = async () => ({ job_id: 'job-new', status_token: 'token-new' })) => pureFunction(brazil, 'runPaymentPair', {
    paymentRunningCount: state(0), api: { submitBrazilPixPayment: submit }, normalizePaymentUrl: value => value,
    cleanText: value => String(value?.message || value || ''), waitPaymentJob, LOCAL_PAYMENT_POLL_PAUSED: 'local_pause',
    removeAccountFromPixPool: () => {}, reloadAccounts: () => {}, isCdkBusyPaymentError: () => false,
    isCdkUnavailablePaymentError: () => false, paymentErrorCode: () => '', isAmbiguousPaymentFailure: error => error?.ambiguous === true,
    paymentTaskHasLiveRemoteJob: brazilHasLiveJob,
    setPaymentFailure: (link, cdk) => { link.status = 'failed'; if (cdk) cdk.status = 'available' },
    savePaymentState: () => {},
  })
  const cdk = { value: 'cdk-1', status: 'available', linkId: 'link-1' }
  const acknowledged = { id: 'link-1', value: 'https://pix.example/pay', status: 'pending', remoteTerminal: true }
  await makeRunner(async link => {
    assert.equal(link.jobId, 'job-new')
    assert.equal(link.statusToken, 'token-new')
    assert.equal(link.remoteTerminal, false, 'Brazil PIX acknowledgement should clear a stale terminal marker before polling')
    return { status: 'local_pause', message: 'paused' }
  })(acknowledged, cdk)
  assert.equal(acknowledged.remoteTerminal, false, 'Brazil PIX local pause should retain the live marker')

  const terminal = { id: 'link-2', value: 'x', status: 'needs_action', jobId: 'job-2', statusToken: 'token-2', remoteTerminal: false }
  await makeRunner(async () => ({ status: 'declined' }))(terminal, { status: 'reserved' })
  assert.equal(terminal.remoteTerminal, true, 'Brazil PIX should set terminal only after terminal polling returns')

  const ambiguous = { id: 'link-3', value: 'x', status: 'needs_action', jobId: 'job-3', statusToken: 'token-3', remoteTerminal: false }
  await makeRunner(async () => { throw Object.assign(new Error('timeout'), { ambiguous: true }) })(ambiguous, { status: 'reserved' })
  assert.equal(ambiguous.remoteTerminal, false, 'Brazil PIX ambiguous polling errors should retain the live marker')
}

{
  const paymentCdks = state([])
  const makeRunner = (waitPaymentJob, pairCdk = null) => pureFunction(india, 'runPaymentTask', {
    paymentTaskRunnable: () => true, paymentCdks, nextPaymentPair: () => pairCdk ? { cdk: pairCdk } : null,
    paymentRunningCount: state(0), paymentStatusText: state(''), api: { submitIndiaUpiPayment: async () => ({ job_id: 'job-new', status_token: 'token-new' }) },
    cleanText: value => String(value || ''), normalizePaymentUrl: value => value, waitPaymentJob, LOCAL_PAYMENT_POLL_PAUSED: 'local_pause',
    removeAccountFromUpiPool: () => {}, refreshAccounts: () => {}, cleanError: error => String(error?.message || error),
    paymentErrorCode: () => '', isCdkBusyPaymentError: () => false, isCdkUnavailablePaymentError: () => false,
    isAmbiguousPaymentFailure: error => error?.ambiguous === true, setPaymentFailure: (item, cdk) => { item.status = 'failed'; if (cdk) cdk.status = 'available' },
    paymentLinkStatusText: value => value, savePaymentState: () => {},
  })
  const cdk = { id: 'cdk-1', value: 'cdk-1', status: 'available' }
  const acknowledged = { id: 'link-1', value: 'https://upi.example/pay', status: 'pending', remoteTerminal: true }
  await makeRunner(async item => {
    assert.equal(item.jobId, 'job-new')
    assert.equal(item.statusToken, 'token-new')
    assert.equal(item.remoteTerminal, false, 'India UPI acknowledgement should clear a stale terminal marker before polling')
    return { status: 'local_pause', message: 'paused' }
  }, cdk)(acknowledged)
  assert.equal(acknowledged.remoteTerminal, false, 'India UPI local pause should retain the live marker')

  const terminalCdk = { id: 'cdk-2', value: 'cdk-2', status: 'reserved' }
  paymentCdks.value = [terminalCdk]
  const terminal = { id: 'link-2', value: 'x', status: 'needs_action', jobId: 'job-2', statusToken: 'token-2', cdkId: 'cdk-2', remoteTerminal: false }
  await makeRunner(async () => ({ status: 'declined', remoteTerminal: true }))(terminal)
  assert.equal(terminal.remoteTerminal, true, 'India UPI should set terminal only after polling returns a terminal marker')

  const ambiguous = { id: 'link-3', value: 'x', status: 'needs_action', jobId: 'job-3', statusToken: 'token-3', cdkId: 'cdk-2', remoteTerminal: false }
  await makeRunner(async () => { throw Object.assign(new Error('timeout'), { ambiguous: true }) })(ambiguous)
  assert.equal(ambiguous.remoteTerminal, false, 'India UPI ambiguous polling errors should retain the live marker')
}

{
  const kkPaymentCdks = state([])
  const makeRunner = (waitKkPaymentOrder, pairCdk = null) => pureFunction(kakao, 'runKkPaymentTask', {
    kkPaymentTaskRunnable: () => true, kkPaymentOrderRestorable: kakaoRestorable, kkPaymentCdks,
    nextKkPaymentPair: () => pairCdk ? { cdk: pairCdk } : null, kkPaymentRunningCount: state(0), kkPaymentStatusText: state(''),
    kkPaymentMethod: state('kakao'), api: { submitKakaoPayKkPayment: async () => ({ order: { id: 'order-new' }, customerToken: 'token-new' }) },
    kkCustomerOrderPayload: data => ({ payload: data, order: data.order || data }), applyKkOrderWorkerInfo: () => {},
    applyKkPaymentCdkSnapshot: () => false, markKkPaymentCdkSubmitted: () => {}, waitKkPaymentOrder,
    KK_PAYMENT_TERMINAL_STATUSES: new Set(['failed', 'success']), kkPaymentStatusFromOrderStatus: status => status,
    kkOrderProblemReason: (_data, fallback) => fallback, externalOrderStatusText: status => status, kkPaymentOrderMissing: () => false,
    kkPaymentLinkStatusText: status => status, cleanError: error => String(error?.message || error),
    isAmbiguousPaymentFailure: error => error?.ambiguous === true, kkPaymentOrderMissingError: () => false,
    releaseSubmittedKkPaymentCdk: () => {}, releaseKkPaymentCdkForLink: () => {}, removeAccountFromKakaoPool: () => {},
    refreshAccounts: async () => {}, refreshLinks: async () => {}, saveKkPaymentState: () => {},
  })
  const cdk = { id: 'cdk-1', value: 'cdk-1', status: 'available' }
  const acknowledged = { id: 'link-1', paymentUrl: 'https://kakao.example/pay', accountEmail: 'a@example.com', status: 'pending', remoteTerminal: true }
  await makeRunner(async item => {
    assert.equal(item.orderId, 'order-new')
    assert.equal(item.customerToken, 'token-new')
    assert.equal(item.remoteTerminal, false, 'Kakao acknowledgement should clear a stale terminal marker before polling')
    return { status: 'needs_action' }
  }, cdk)(acknowledged)
  assert.equal(acknowledged.remoteTerminal, false, 'Kakao local pause should retain the live marker')

  const terminalCdk = { id: 'cdk-2', value: 'cdk-2', status: 'reserved' }
  kkPaymentCdks.value = [terminalCdk]
  const terminal = { id: 'link-2', paymentUrl: 'x', status: 'needs_action', orderId: 'order-2', customerToken: 'token-2', cdkId: 'cdk-2', remoteTerminal: false }
  await makeRunner(async () => ({ status: 'failed' }))(terminal)
  assert.equal(terminal.remoteTerminal, true, 'Kakao should set terminal only after polling returns a terminal order status')

  const ambiguous = { id: 'link-3', paymentUrl: 'x', status: 'needs_action', orderId: 'order-3', customerToken: 'token-3', cdkId: 'cdk-2', remoteTerminal: false }
  await makeRunner(async () => { throw Object.assign(new Error('timeout'), { ambiguous: true }) })(ambiguous)
  assert.equal(ambiguous.remoteTerminal, false, 'Kakao ambiguous polling errors should retain the live marker')
}

const brazilRun = functionSource(brazil, 'runPaymentPair')
const indiaRun = functionSource(india, 'runPaymentTask')
const kakaoRun = functionSource(kakao, 'runKkPaymentTask')
assert.equal(matchCount(brazilRun, /remoteTerminal\s*=\s*true/g), 1, 'Brazil PIX should have one terminal transition in its payment runner')
assert.doesNotMatch(sourceSegment(brazilRun, '} catch (error) {', '} finally {'), /remoteTerminal\s*=\s*true/, 'Brazil PIX error handling should not fabricate terminal confirmation')
assert.equal(matchCount(indiaRun, /remoteTerminal\s*=\s*true/g), 1, 'India UPI should have one conditional terminal transition in its payment runner')
assert.match(indiaRun, /if \(job\.remoteTerminal === true\) item\.remoteTerminal = true/, 'India UPI terminal assignment should require the polling marker')
assert.doesNotMatch(sourceSegment(indiaRun, '} catch (error) {', '} finally {'), /remoteTerminal\s*=\s*true/, 'India UPI error handling should not fabricate terminal confirmation')
assert.equal(matchCount(kakaoRun, /remoteTerminal\s*=\s*true/g), 2, 'Kakao should mark terminal only for a terminal poll or confirmed missing order')
assert.match(kakaoRun, /if \(KK_PAYMENT_TERMINAL_STATUSES\.has\([\s\S]*?\)\) item\.remoteTerminal = true/, 'Kakao polling should condition terminal assignment on a terminal order status')
const kakaoCatch = sourceSegment(kakaoRun, '} catch (error) {', '} finally {')
assert.equal(matchCount(kakaoCatch, /remoteTerminal\s*=\s*true/g), 1)
assert.match(kakaoCatch, /if \(kkPaymentOrderMissingError\(error\)\) \{[\s\S]*?item\.remoteTerminal = true/, 'Kakao catch should mark terminal only for a confirmed missing order')
assert.match(kakaoCatch, /if \(!ambiguous\)[\s\S]*?releaseKkPaymentCdkForLink/, 'Kakao should release a pre-submit reservation only after a definitive rejection')

// PayPal protocol/153 account and BA targets remain quarantined until the backend
// confirms a terminal outcome or the operator explicitly reconciles the job.
const paypal = source('UsPaypalPage.vue')
const paymentTargetSelectable = pureFunction(paypal, 'paymentTargetSelectable')
for (const status of ['queued', 'running', 'cancelling', 'unknown', 'unknown_outcome', 'paid']) {
  assert.equal(paymentTargetSelectable(status), false, `${status} PayPal targets must not be selectable`)
}
for (const status of ['pending', 'success', 'failed', 'error', 'cancelled']) {
  assert.equal(paymentTargetSelectable(status), true, `${status} PayPal targets should be released`)
}

const paymentLinkAccountSelectable = pureFunction(paypal, 'paymentLinkAccountSelectable', { paymentTargetSelectable })
assert.equal(paymentLinkAccountSelectable({ paypalStatus: 'success', account: { paypal_selectable: true } }, item => item.paypalStatus), true)
assert.equal(paymentLinkAccountSelectable({ paypalStatus: 'running', account: { paypal_selectable: true } }, item => item.paypalStatus), false)
assert.equal(paymentLinkAccountSelectable({ paypalStatus: 'success', account: { paypal_selectable: false } }, item => item.paypalStatus), false)

const baPoolItemSelectable = pureFunction(paypal, 'baPoolItemSelectable', { paymentTargetSelectable })
assert.equal(baPoolItemSelectable({ status: 'failed' }), true)
assert.equal(baPoolItemSelectable({ status: 'running' }), false)
assert.equal(baPoolItemSelectable({ status: 'unknown_outcome' }), false)

{
  const protocolBaPool = state([
    { id: 'available', status: 'failed' },
    { id: 'live', status: 'running' },
    { id: 'unknown', status: 'unknown_outcome' },
  ])
  const pay153BaPool = state([])
  const selectedProtocolBaIds = state(new Set())
  const selectedPay153BaIds = state(new Set())
  const filteredProtocolBaPool = state(protocolBaPool.value)
  const filteredPay153BaPool = state([])
  const toggle = pureFunction(paypal, 'toggleBaPoolItem', {
    protocolBaPool, pay153BaPool, selectedProtocolBaIds, selectedPay153BaIds, baPoolItemSelectable,
  })
  toggle('protocol', 'live')
  toggle('protocol', 'unknown')
  toggle('protocol', 'available')
  assert.deepEqual([...selectedProtocolBaIds.value], ['available'], 'BA toggles must ignore live and unknown targets')

  selectedProtocolBaIds.value = new Set()
  const selectAll = pureFunction(paypal, 'selectAllBaPool', {
    filteredProtocolBaPool, filteredPay153BaPool, selectedProtocolBaIds, selectedPay153BaIds, baPoolItemSelectable,
  })
  selectAll('protocol')
  assert.deepEqual([...selectedProtocolBaIds.value], ['available'], 'BA select-all must exclude live and unknown targets')
}

{
  const protocolBaPool = state([{ id: 'BA-UNKNOWN', baToken: 'BA-UNKNOWN', status: 'running', error: '' }])
  const pay153BaPool = state([])
  const sync = pureFunction(paypal, 'syncBaPoolFromJob', {
    protocolBaPool, pay153BaPool,
    displayBaToken: value => String(value || '').trim(),
    saveBaPool: () => {},
  })
  sync('protocol', {
    status: 'unknown_outcome',
    target_ba_tokens: ['BA-UNKNOWN'],
    account_statuses: { 'BA-UNKNOWN': { status: 'unknown_outcome', error: 'remote result unknown' } },
    result: { errors: [{ email: 'BA-UNKNOWN', error: 'remote result unknown', unknown_outcome: true }] },
  })
  assert.equal(protocolBaPool.value[0].status, 'unknown_outcome', 'unknown BA sync must not downgrade to ordinary failed')
}

const resultErrorRetryable = pureFunction(paypal, 'paymentResultErrorRetryable')
assert.equal(resultErrorRetryable({ email: 'failed@example.com', error: 'declined' }), true)
assert.equal(resultErrorRetryable({ email: 'unknown@example.com', error: 'timeout', unknown_outcome: true }), false)

for (const [name, resolver] of [
  ['selectAllProtocolAccounts', 'protocolPaymentAccountStatus'],
  ['selectFirstProtocolAccounts', 'protocolPaymentAccountStatus'],
  ['selectAllPay153Accounts', 'pay153PaymentAccountStatus'],
  ['selectFirstPay153Accounts', 'pay153PaymentAccountStatus'],
]) {
  assert.match(functionSource(paypal, name), new RegExp(`paymentLinkAccountSelectable\\(item, ${resolver}\\)`), `${name} must exclude live and unknown accounts`)
}
assert.match(functionSource(paypal, 'toggleProtocolAccount'), /protocolLinkSelectableEmails\.value\.has\(target\)/)
assert.match(functionSource(paypal, 'togglePay153Account'), /pay153LinkSelectableEmails\.value\.has\(target\)/)
assert.match(paypal, /:disabled="protocolBusy \|\| !paymentLinkAccountSelectable\(item, protocolPaymentAccountStatus\)"/, 'protocol option/checkbox controls must disable live and unknown accounts')
assert.match(paypal, /:disabled="pay153Busy \|\| !paymentLinkAccountSelectable\(item, pay153PaymentAccountStatus\)"/, '153 checkbox controls must disable live and unknown accounts')
assert.match(paypal, /:disabled="protocolBusy \|\| !baPoolItemSelectable\(item\)"/, 'protocol BA checkboxes must disable live and unknown rows')
assert.match(paypal, /:disabled="pay153Busy \|\| !baPoolItemSelectable\(item\)"/, '153 BA checkboxes must disable live and unknown rows')

const apiSource = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
assert.match(apiSource, /releaseUsPaypalPaymentOccupancy:\s*\(payload\)\s*=>\s*request\('POST', '\/us-paypal\/payment-jobs\/reconcile-release'/, 'manual release must have a backend API')
const releaseUnknownPaymentOccupancy = pureFunction(paypal, 'releaseUnknownPaymentOccupancy', {
  api: {
    releaseUsPaypalPaymentOccupancy: async payload => ({ ok: true, payload }),
  },
})
const releaseResult = await releaseUnknownPaymentOccupancy('paypal_protocol_payment', {
  jobId: 'job-unknown', clientRequestId: 'request-unknown', submitPayload: { accountEmails: ['buyer@example.com'] },
})
assert.equal(releaseResult.ok, true)
assert.deepEqual(releaseResult.payload, {
  kind: 'paypal_protocol_payment',
  jobId: 'job-unknown',
  clientRequestId: 'request-unknown',
  accountEmails: ['buyer@example.com'],
})

for (const name of ['discardProtocolRecovery', 'discardPay153Recovery', 'clearLegacyUnresolvedAutoPayJobs']) {
  const release = functionSource(paypal, name)
  assert.match(release, /await releaseUnknownPaymentOccupancy\(/, `${name} must reconcile backend occupancy before local cleanup`)
  assert.ok(
    release.indexOf('await releaseUnknownPaymentOccupancy(') < release.search(/storageWriter\.remove|activeRef\.value\s*=/),
    `${name} must not clear local state before backend reconciliation`,
  )
}

console.log('payment unknown-outcome safeguards passed')
