import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')

function section(start, end) {
  const startIndex = page.indexOf(start)
  const endIndex = page.indexOf(end, startIndex + start.length)
  assert.notEqual(startIndex, -1, `missing ${start}`)
  assert.notEqual(endIndex, -1, `missing ${end}`)
  return page.slice(startIndex, endIndex)
}

assert.match(page, /@click="startPay153Payment"\s+:disabled="pay153Busy \|\| pay153Canceling"/, 'manual 153 start should be disabled during cancellation or cleanup')
assert.match(page, /@click="togglePay153AutoPay"[^>]*:disabled="pay153Canceling && !pay153AutoPayActive"/, 'automatic 153 start should be disabled during cleanup while an active scheduler remains stoppable')

const start = section('async function startPay153Payment', 'async function retryFailedPay153Payment')
assert.match(start, /if \(pay153Canceling\.value\)[\s\S]*?return false/, 'programmatic manual starts should reject the cancellation window')

const toggle = section('async function togglePay153AutoPay', 'async function scanProtocolAutoPayLinks')
assert.match(toggle, /if \(pay153Canceling\.value\)[\s\S]*?return/, 'programmatic auto-pay starts should reject the cancellation window')

const launch = section('async function launchPay153AutoPayItem', 'async function pollProtocolAutoPayJob')
assert.match(launch, /pay153Canceling\.value/, 'an already scheduled automatic item should re-check the mutation lock before submission')

const drain = section('async function drainPay153AutoPayQueue', 'function splitProtocolLines')
assert.match(drain, /pay153Canceling\.value/, 'the automatic queue should not launch another mutation while cancellation is running')

const cleanup = section('async function cancelPay153RemoteByCurrentBa', 'async function pollPay153Job')
assert.match(cleanup, /isAmbiguousPaymentFailure\(error\)[\s\S]*?recoveryPaused:\s*true[\s\S]*?unknownOutcome:\s*true/, 'an ambiguous cleanup result should create a durable unknown-outcome checkpoint')
assert.match(cleanup, /setBaPoolStatus\('pay153',[\s\S]*?'unknown_outcome'/, 'an ambiguous BA cleanup should quarantine the selected BA')

const discard = section('async function discardPay153Recovery', 'function savePay153Form')
assert.match(discard, /cleanupByBa/, 'the existing manual review path should be able to resolve a cleanup-only checkpoint without resubmitting')

const cancel = section('async function cancelPay153Job', 'onMounted(async () =>')
const ambiguousCancel = cancel.match(/catch \(error\) \{[\s\S]*?\n  \}/)?.[0] || ''
assert.match(ambiguousCancel, /isAmbiguousPaymentFailure\(error\)[\s\S]*?persistPay153JobState/, 'an ambiguous cancel result should retain the job checkpoint')
assert.doesNotMatch(ambiguousCancel, /releaseClaimedPhonePoolEntriesAfterJob/, 'an ambiguous cancel must retain phone ownership')

console.log('Pay153 cancellation deadline, mutation lock, and unknown-outcome contract passed')
