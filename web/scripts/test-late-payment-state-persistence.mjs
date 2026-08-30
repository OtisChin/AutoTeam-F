import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

function component(name) {
  return readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
}

for (const name of ['IndiaUpiPage.vue', 'KakaoPayPage.vue', 'BrazilPixPage.vue']) {
  const source = component(name)
  assert.match(
    source,
    /function persistJsonState\(storageKey, value\) \{\s*if \(componentUnmounted\) \{\s*storageWriter\.writeJsonNow\(storageKey, value\)\s*return\s*\}\s*storageWriter\.queueJson\(storageKey, value\)\s*\}/,
    `${name} should synchronously preserve critical state that arrives after unmount`,
  )
  assert.equal(
    (source.match(/storageWriter\.queueJson\(/g) || []).length,
    1,
    `${name} should route every JSON persistence call through the lifecycle-aware helper`,
  )
}

const india = component('IndiaUpiPage.vue')
assert.match(
  india.slice(india.indexOf('async function startWithEmails'), india.indexOf('async function start()')),
  /commitStartAckSnapshot\(startReservation, \{[\s\S]*?componentUnmounted,[\s\S]*?jobId: newJobId[\s\S]*?if \(!startAck\.shouldContinue\) return/,
  'India UPI should CAS a late start ACK into recoverable storage before stopping an unmounted instance',
)
assert.match(india.slice(india.indexOf('function savePaymentState'), india.indexOf('function loadPaymentState')), /persistJsonState\(PAYMENT_STATE_STORAGE_KEY/)

const kakao = component('KakaoPayPage.vue')
assert.match(kakao.slice(kakao.indexOf('function saveActiveJobSnapshot'), kakao.indexOf('function clearActiveJob')), /const storageKey = extractJobStorageKey\(snapshotMode\)[\s\S]*?persistJsonState\(storageKey, snapshot\)/)
assert.match(kakao.slice(kakao.indexOf('function saveKkPaymentState'), kakao.indexOf('function loadKkPaymentState')), /persistJsonState\(KK_PAYMENT_STATE_STORAGE_KEY/)

const brazil = component('BrazilPixPage.vue')
assert.match(brazil.slice(brazil.indexOf('function saveStoredPixTask'), brazil.indexOf('function clearStoredPixTask')), /persistJsonState\(PIX_TASKS_STORAGE_KEY/)
assert.match(
  brazil.slice(brazil.indexOf('async function runPaymentPair'), brazil.indexOf('function removeAccountFromPixPool')),
  /finally \{\s*paymentRunningCount\.value = Math\.max\(0, paymentRunningCount\.value - 1\)\s*savePaymentState\(\)\s*\}/,
  'Brazil PIX should explicitly persist a payment ID received after its component watcher is gone',
)

console.log('late payment state persistence contract passed')
