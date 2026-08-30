import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')

for (const [startName, nextName, submitName, persistName] of [
  ['startProtocolPayment', 'pollProtocolJob', 'submitProtocolManualJob', 'persistProtocolJobState'],
  ['startPay153Payment', 'retryFailedPay153Payment', 'submitPay153ManualJob', 'persistPay153JobState'],
]) {
  const body = source.slice(source.indexOf(`async function ${startName}`), source.indexOf(`async function ${nextName}`))
  assert.match(body, /createPaypalClientRequestId[\s\S]*?clientRequestId[\s\S]*?submitPayload/, `${startName} should create a durable idempotency checkpoint before submit`)
  assert.match(body, new RegExp(`${persistName}\\([\\s\\S]*?clientRequestId[\\s\\S]*?submitPayload[\\s\\S]*?force: true`), `${startName} should persist its pre-acknowledgement checkpoint synchronously`)
  assert.match(body, new RegExp(`await ${submitName}\\(`), `${startName} should reconcile ambiguous starts with the same client request ID`)
}

assert.match(source, /async function resumeUnknownProtocolPaymentStart\(/, 'a jobless manual protocol checkpoint should be resumable')
assert.match(source, /async function resumeUnknownPay153PaymentStart\(/, 'a jobless manual 153 checkpoint should be resumable')

for (const [pollName, nextName, requestName, persistName] of [
  ['pollProtocolJob', 'cancelProtocolJob', 'getUsPaypalProtocolJob', 'persistProtocolJobState'],
  ['pollPay153Job', 'submitPay153Otp', 'getUsPaypal153Job', 'persistPay153JobState'],
]) {
  const body = source.slice(source.indexOf(`async function ${pollName}`), source.indexOf(`async function ${nextName}`))
  assert.match(body, new RegExp(`readPollingSnapshot\\s*\\(\\{[\\s\\S]*?request: \\(\\) => api\\.${requestName}\\(jobId\\)`), `${pollName} should classify status errors through the shared recovery policy`)
  assert.match(body, /recovery\.kind === 'retry'[\s\S]*?continue/, `${pollName} should retry only within the finite budget`)
  const pausedBranch = body.match(/if \(\['permanent', 'paused'\][\s\S]*?return\s*\}/)?.[0] || ''
  assert.match(pausedBranch, new RegExp(`${persistName}\\([\\s\\S]*?force: true`), `${pollName} should persist its paused checkpoint`)
  assert.doesNotMatch(pausedBranch, /releaseClaimedPhonePoolEntriesAfterJob/, `${pollName} should not release a claimed phone after an indeterminate status stop`)
}

console.log('paypal manual job recovery contract passed')
