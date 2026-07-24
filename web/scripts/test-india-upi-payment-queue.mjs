import assert from 'node:assert/strict'
import {
  PAYMENT_RETRYABLE_LINK_STATUSES,
  TEMP_CDK_COOLDOWN_MS,
  extractedLinkPaymentSeed,
  indiaUpiCdkStatusClass,
  isTempCdkCoolingError,
  paymentPairUnavailableMessage,
  tempCdkCooldownUntil,
  tempCdkRemainingText,
} from '../src/indiaUpiPaymentQueue.js'

function testNeedsActionCanRetryWithNewCdk() {
  assert.equal(PAYMENT_RETRYABLE_LINK_STATUSES.has('needs_action'), true)
}

function testUnavailableMessageSeparatesMissingCdkFromMissingUrl() {
  assert.equal(
    paymentPairUnavailableMessage({ hasUsableLink: false, hasAvailableCdk: true }),
    '没有可提交的已提取 UPI 链接（链接为空或已失效）',
  )
  assert.equal(
    paymentPairUnavailableMessage({ hasUsableLink: true, hasAvailableCdk: false }),
    '没有可用的 UPI-SCAN CDK',
  )
  assert.equal(
    paymentPairUnavailableMessage({ hasUsableLink: true, hasAvailableCdk: true }),
    '没有可提交的已提取 UPI 链接',
  )
}

function testCdkStatusColorsUseGreenAvailableAndRedUsed() {
  assert.match(indiaUpiCdkStatusClass('available'), /emerald/)
  assert.match(indiaUpiCdkStatusClass('used'), /rose/)
  assert.doesNotMatch(indiaUpiCdkStatusClass('used'), /emerald/)
}

function testExtractedLinkIsPaymentUrlSeed() {
  const seed = extractedLinkPaymentSeed({
    id: 'upi-link-1',
    account_email: 'user@example.com',
    hosted_instructions_url: 'https://payments.stripe.com/upi/instructions/test/',
    upi_payment_uri: 'upi://pay',
    upi_expires_at_ts: 1800000000,
  }, { nowMs: 1700000000000 })
  assert.deepEqual(seed, {
    id: 'link-upi-link-1',
    value: 'https://payments.stripe.com/upi/instructions/test',
    paymentUri: 'upi://pay',
    status: 'pending',
    accountEmail: 'user@example.com',
    created_at: '',
    created_at_ts: 0,
    upi_expires_at_ts: 1800000000,
  })
}

function testTempCdkCoolingErrorCreatesThreeMinuteCooldown() {
  const error = { error: '临时 UPI 服务拒绝请求: CDK is already running in another task.' }
  assert.equal(isTempCdkCoolingError(error), true)
  assert.equal(TEMP_CDK_COOLDOWN_MS, 180_000)
  assert.equal(tempCdkCooldownUntil(1000, error), 1000 + TEMP_CDK_COOLDOWN_MS)
  assert.equal(tempCdkRemainingText(1000 + 125_000, 1000), '冷却 2:05')
}

testNeedsActionCanRetryWithNewCdk()
testUnavailableMessageSeparatesMissingCdkFromMissingUrl()
testCdkStatusColorsUseGreenAvailableAndRedUsed()
testExtractedLinkIsPaymentUrlSeed()
testTempCdkCoolingErrorCreatesThreeMinuteCooldown()
console.log('india-upi payment queue tests passed')
