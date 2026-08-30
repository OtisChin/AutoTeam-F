import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

function source(name) {
  return readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
}

function section(text, start, end) {
  const from = text.indexOf(start)
  const to = text.indexOf(end, from + start.length)
  assert.ok(from >= 0, `missing section start: ${start}`)
  assert.ok(to > from, `missing section end: ${end}`)
  return text.slice(from, to)
}

function assertAvailabilityBeforeRequest(text, requestPattern, label) {
  const availabilityIndex = text.search(/await networkPollingGate\.waitUntilAvailable\(\)/)
  const requestIndex = text.search(requestPattern)
  assert.ok(availabilityIndex >= 0, `${label} should wait for visible/online availability`)
  assert.ok(requestIndex > availabilityIndex, `${label} should wait for availability before requesting`)
}

function assertLifecycleExpiryClock(text, unmountHook, label) {
  assert.match(text, /const expiryClock = createPollingLifecycle\(\)/)
  assert.match(text, /let expiryClockToken = null/)

  const loop = section(text, 'async function runExpiryClock', 'function startExpiryClock')
  assert.match(loop, /while \(expiryClock\.isActive\(pollToken\)\)/)
  const delayIndex = loop.search(/await expiryClock\.wait\(1000, pollToken\)/)
  const availabilityIndex = loop.search(/await expiryClock\.waitUntilAvailable\(pollToken\)/)
  const tickIndex = loop.indexOf('nowMs.value = Date.now()')
  assert.ok(delayIndex >= 0, `${label} expiry clock should use a cancellable one-second lifecycle wait`)
  assert.ok(availabilityIndex > delayIndex, `${label} expiry clock should wait for page availability after each delay`)
  assert.ok(tickIndex > availabilityIndex, `${label} expiry clock should only update reactive time while available`)
  assert.match(loop, /releaseExpiredTempCdkCooldowns\(\)/)

  const mounted = section(text, 'onMounted(async () => {', `${unmountHook}(() => {`)
  assert.match(mounted, /startExpiryClock\(\)/)
  assert.doesNotMatch(mounted, /setInterval/)

  const unmounted = section(text, `${unmountHook}(() => {`, '</script>')
  assert.match(unmounted, /expiryClock\.dispose\(\)/)
  assert.match(unmounted, /expiryClockToken = null/)
  assert.doesNotMatch(unmounted, /clearInterval/)
}

const brazil = source('BrazilPixPage.vue')
assert.match(brazil, /import \{ createSharedPollingGate \} from '\.\.\/pollingLifecycle\.js'/)
assert.match(brazil, /const networkPollingGate = createSharedPollingGate\(\)/)

const brazilPayment = section(brazil, 'async function waitPaymentJob', 'async function runPaymentPair')
assertAvailabilityBeforeRequest(brazilPayment, /api\.getBrazilPixPaymentJob/, 'Brazil payment polling')
assert.match(brazilPayment, /await networkPollingGate\.wait\(2000\)/)
assert.doesNotMatch(brazilPayment, /setTimeout/)

const brazilExtract = section(brazil, 'async function poll(jobId', 'function resumeStoredPixTasks')
assertAvailabilityBeforeRequest(brazilExtract, /api\.getBrazilPixJob/, 'Brazil extract polling')
assert.match(brazilExtract, /await networkPollingGate\.wait\(1000\)/)
assert.doesNotMatch(brazilExtract, /setTimeout/)

const brazilCdkCheck = section(brazil, 'async function checkTempCdkStatus', 'function stopTempCdkStatusPolling')
assertAvailabilityBeforeRequest(brazilCdkCheck, /api\.getBrazilPixTempCdkStatus/, 'Brazil temporary CDK polling')
assert.match(brazilCdkCheck, /await networkPollingGate\.wait\(TEMP_CDK_STATUS_REQUEST_DELAY_MS\)/)
assert.doesNotMatch(brazilCdkCheck, /setTimeout/)

const brazilCdkLoop = section(brazil, 'function startTempCdkStatusPolling', 'function scheduleTempCdkStatusPolling')
assert.doesNotMatch(brazilCdkLoop, /setInterval/)
assert.match(brazilCdkLoop, /runTempCdkStatusPolling/)
assert.match(brazil, /await networkPollingGate\.wait\(TEMP_CDK_STATUS_POLL_MS\)/)
assert.match(section(brazil, 'onBeforeUnmount', '</script>'), /networkPollingGate\.dispose\(\)/)

const india = source('IndiaUpiPage.vue')
assert.match(india, /import \{ createPollingLifecycle, createSharedPollingGate \} from '\.\.\/pollingLifecycle\.js'/)
assert.match(india, /const networkPollingGate = createSharedPollingGate\(\)/)

const indiaPayment = section(india, 'async function waitPaymentJob', 'async function runPaymentTask')
assertAvailabilityBeforeRequest(indiaPayment, /api\.getIndiaUpiPaymentJob/, 'India payment polling')
assert.match(indiaPayment, /await networkPollingGate\.wait\(2000\)/)
assert.doesNotMatch(indiaPayment, /setTimeout/)

const indiaExtract = section(india, 'async function pollJob', 'async function cancelJob')
assertAvailabilityBeforeRequest(indiaExtract, /api\.getIndiaUpiJob/, 'India extract polling')
assert.match(indiaExtract, /await networkPollingGate\.wait\(1000\)/)
assert.doesNotMatch(indiaExtract, /setTimeout/)
assert.match(section(india, 'onBeforeUnmount', '</script>'), /networkPollingGate\.dispose\(\)/)
assertLifecycleExpiryClock(india, 'onBeforeUnmount', 'India')

const kakao = source('KakaoPayPage.vue')
assert.match(kakao, /createSharedPollingGate/)
assert.match(kakao, /const networkPollingGate = createSharedPollingGate\(\)/)

const kakaoPayment = section(kakao, 'async function waitKkPaymentOrder', 'async function runKkPaymentTask')
assertAvailabilityBeforeRequest(kakaoPayment, /api\.getKakaoPayKkPaymentOrder/, 'Kakao payment polling')
assert.match(kakaoPayment, /await networkPollingGate\.wait\(2000\)/)
assert.doesNotMatch(kakaoPayment, /setTimeout/)
assert.match(section(kakao, 'onUnmounted', '</script>'), /networkPollingGate\.dispose\(\)/)
assertLifecycleExpiryClock(kakao, 'onUnmounted', 'Kakao')

const kakaoCancel = section(kakao, 'async function cancelJob', 'function saveProxy')
const cancelFinallyIndex = kakaoCancel.indexOf('finally {')
const cancelRestartIndex = kakaoCancel.indexOf('startPolling(mode)', cancelFinallyIndex)
assert.ok(cancelFinallyIndex >= 0, 'Kakao cancel should always settle through finally')
assert.ok(cancelRestartIndex > cancelFinallyIndex, 'Kakao cancel should restore polling from finally after request failures')
assert.match(
  kakaoCancel.slice(cancelFinallyIndex),
  /!componentUnmounted\s*&&\s*isExtractTaskRunning\(state\)/,
  'Kakao cancel should only restore polling for mounted, non-terminal active jobs',
)

console.log('shared payment polling gate contract passed')
