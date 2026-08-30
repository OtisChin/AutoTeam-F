import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  createSubmissionGenerationGuard,
  PAYMENT_RECOVERY_BASE_DELAY_MS,
  PAYMENT_RECOVERY_MAX_ATTEMPTS,
  PAYMENT_RECOVERY_MAX_DELAY_MS,
  paymentRecoveryDelayMs,
} from '../src/paymentRequestState.js'

const submissionGuard = createSubmissionGenerationGuard()
const firstSubmission = submissionGuard.start()
assert.equal(submissionGuard.isActive(firstSubmission), true)
submissionGuard.cancel()
assert.equal(submissionGuard.isActive(firstSubmission), false, 'cancel must permanently invalidate a sleeping submission attempt')
const replacementSubmission = submissionGuard.start()
assert.equal(submissionGuard.isActive(replacementSubmission), true)
assert.notEqual(replacementSubmission, firstSubmission)

assert.equal(PAYMENT_RECOVERY_BASE_DELAY_MS, 5_000)
assert.equal(PAYMENT_RECOVERY_MAX_DELAY_MS, 60_000)
assert.equal(PAYMENT_RECOVERY_MAX_ATTEMPTS, 5)
assert.equal(paymentRecoveryDelayMs(1, { random: () => 0.5 }), 5_000)
assert.equal(paymentRecoveryDelayMs(2, { random: () => 0.5 }), 10_000)
assert.equal(paymentRecoveryDelayMs(99, { random: () => 0.5 }), 60_000)
assert.ok(paymentRecoveryDelayMs(1, { random: () => 0 }) < PAYMENT_RECOVERY_BASE_DELAY_MS)
assert.ok(paymentRecoveryDelayMs(1, { random: () => 1 }) > PAYMENT_RECOVERY_BASE_DELAY_MS)

const __dirname = dirname(fileURLToPath(import.meta.url))
const page = readFileSync(resolve(__dirname, '../src/components/UsPaypalPage.vue'), 'utf8')
const manualProtocol = page.slice(page.indexOf('async function submitProtocolManualJob'), page.indexOf('async function resumeUnknownProtocolPaymentStart'))
const manualPay153 = page.slice(page.indexOf('async function submitPay153ManualJob'), page.indexOf('async function resumeUnknownPay153PaymentStart'))
const autoProtocol = page.slice(page.indexOf('async function reconcileProtocolAutoPayStart'), page.indexOf('async function reconcilePay153AutoPayStart'))
const autoPay153 = page.slice(page.indexOf('async function reconcilePay153AutoPayStart'), page.indexOf('function protocolManualOccupiedSlots'))
const pollProtocol = page.slice(page.indexOf('async function pollProtocolJob'), page.indexOf('async function cancelProtocolJob'))
const pollPay153 = page.slice(page.indexOf('async function pollPay153Job'), page.indexOf('async function submitPay153Otp'))

for (const source of [manualProtocol, manualPay153, autoProtocol, autoPay153]) {
  assert.match(source, /waitUntilAvailable/, 'payment recovery must pause while hidden or offline')
  assert.match(source, /paymentRecoveryDelayMs/, 'payment recovery must use capped jittered backoff')
  assert.match(source, /PAYMENT_RECOVERY_MAX_ATTEMPTS/, 'payment recovery must pause after a bounded retry budget')
  assert.match(source, /recovery_paused|recoveryPaused/, 'payment recovery must persist a paused state instead of retrying forever')
}

assert.match(page, /protocolSubmissionCancelRequested/, 'manual protocol recovery can be cancelled before a job id exists')
assert.match(page, /pay153SubmissionCancelRequested/, 'manual 153 recovery can be cancelled before a job id exists')
assert.match(page, /function cancelProtocolJob[\s\S]*protocolSubmissionCancelRequested\s*=\s*true/, 'protocol cancel pauses pre-ack reconciliation')
assert.match(page, /function cancelPay153Job[\s\S]*pay153SubmissionCancelRequested\s*=\s*true/, '153 cancel pauses pre-ack reconciliation')
assert.match(manualProtocol, /protocolSubmissionGuard\.start\(\)[\s\S]*protocolSubmissionGuard\.isActive/, 'protocol backoff should use a generation that cancel cannot accidentally re-enable')
assert.match(manualPay153, /pay153SubmissionGuard\.start\(\)[\s\S]*pay153SubmissionGuard\.isActive/, '153 backoff should use a generation that cancel cannot accidentally re-enable')
assert.match(page, /function cancelProtocolJob[\s\S]*protocolSubmissionGuard\.cancel\(\)/, 'protocol cancel should invalidate the sleeping retry generation')
assert.match(page, /function cancelPay153Job[\s\S]*pay153SubmissionGuard\.cancel\(\)/, '153 cancel should invalidate the sleeping retry generation')
assert.match(page, /function discardProtocolRecovery\(\)\s*\{\s*if \(protocolBusy\.value\)/, 'protocol occupancy cannot be discarded while the cancelled submit loop is still unwinding')
assert.match(page, /function discardPay153Recovery\(\)\s*\{\s*if \(pay153Busy\.value\)/, '153 occupancy cannot be discarded while the cancelled submit loop is still unwinding')
assert.match(page, /@click="discardProtocolRecovery"\s+:disabled="protocolBusy"/, 'the protocol discard control should remain disabled until the submit loop exits')
assert.match(page, /@click="discardPay153Recovery"\s+:disabled="pay153Busy"/, 'the 153 discard control should remain disabled until the submit loop exits')
assert.match(pollProtocol, /job\.status === 'unknown_outcome'[\s\S]*persistProtocolJobState/, 'backend-restart unknown outcomes stop protocol polling and retain the checkpoint')
assert.doesNotMatch(pollProtocol.match(/job\.status === 'unknown_outcome'[\s\S]*?return/)?.[0] || '', /releaseClaimedPhonePoolEntriesAfterJob/, 'protocol unknown outcomes keep phone reservations quarantined')
assert.match(pollPay153, /job\.status === 'unknown_outcome'[\s\S]*persistPay153JobState/, 'backend-restart unknown outcomes stop 153 polling and retain the checkpoint')
assert.doesNotMatch(pollPay153.match(/job\.status === 'unknown_outcome'[\s\S]*?return/)?.[0] || '', /releaseClaimedPhonePoolEntriesAfterJob/, '153 unknown outcomes keep phone reservations quarantined')

console.log('paypal retry backoff and restart recovery contract passed')
