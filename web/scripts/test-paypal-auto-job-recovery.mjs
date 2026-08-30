import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')

assert.match(source, /const PAYPAL_AUTO_PAY_STATE_STORAGE_KEY = ['"]autotoken_us_paypal_auto_pay_state['"]/, 'auto-pay remote job handles should have durable storage')
assert.match(source, /function persistPaypalAutoPayState\(/, 'auto-pay state should have an explicit persistence boundary')
assert.match(source, /function restorePaypalAutoPayState\(/, 'auto-pay state should be restorable after navigation')
assert.match(source, /function createPaypalClientRequestId\(/, 'auto-pay starts should have a client-generated correlation key before submission')
assert.match(source, /function reconcileProtocolAutoPayStart\(/, 'protocol auto-pay should reconcile a lost start acknowledgement')
assert.match(source, /function reconcilePay153AutoPayStart\(/, '153 auto-pay should reconcile a lost start acknowledgement')

const protocolScan = source.slice(source.indexOf('async function scanProtocolAutoPayLinks'), source.indexOf('async function scanPay153AutoPayLinks'))
const pay153Scan = source.slice(source.indexOf('async function scanPay153AutoPayLinks'), source.indexOf('function mergePaymentResult'))
assert.match(protocolScan, /protocolAutoPayActiveJobs[\s\S]*?activeEmails\.has\(item\.email\)/, 'protocol scanner should exclude accounts with a restored remote job')
assert.match(pay153Scan, /pay153AutoPayActiveJobs[\s\S]*?activeEmails\.has\(item\.email\)/, '153 scanner should exclude accounts with a restored remote job')
assert.match(protocolScan, /item\.paypalStatus !== 'success'/, 'protocol auto-pay should only enqueue an account whose latest link is ready')
assert.match(pay153Scan, /item\.paypalStatus !== 'success'/, '153 auto-pay should only enqueue an account whose latest link is ready')
assert.match(protocolScan, /protocolBusy[\s\S]*?protocolSelectedEmails[\s\S]*?protocolPaymentAccountStatus/, 'protocol scanner should exclude a manual payment before its first status response')
assert.match(pay153Scan, /pay153Busy[\s\S]*?pay153SelectedEmails[\s\S]*?pay153PaymentAccountStatus/, '153 scanner should exclude a manual payment before its first status response')

for (const [name, nextName, activeRef] of [
  ['launchProtocolAutoPayItem', 'launchPay153AutoPayItem', 'protocolAutoPayActiveJobs'],
  ['launchPay153AutoPayItem', 'pollProtocolAutoPayJob', 'pay153AutoPayActiveJobs'],
]) {
  const body = source.slice(source.indexOf(`async function ${name}`), source.indexOf(`async function ${nextName}`))
  assert.match(body, new RegExp(`${activeRef}\\.value[\\s\\S]*?claimedPhonePoolKeys`), `${name} should checkpoint phone claims with the active item before submit`)
  assert.match(body, /clientRequestId[\s\S]*?persistPaypalAutoPayState\(\{ force: true \}\)/, `${name} should checkpoint its correlation key before submit`)
  assert.match(body, /autoPayCandidateStillRunnable/, `${name} should revalidate a stale queue item immediately before submit`)
  assert.match(body, /persistPaypalAutoPayState\(\{ force: true \}\)/, `${name} should synchronously checkpoint both pre-acknowledgement and acknowledged state`)
}

const restore = source.slice(source.indexOf('function restorePaypalAutoPayState'), source.indexOf('function stopProtocolAutoPay'))
assert.match(restore, /protocolClaimedPhonePoolKeysByJob\.set[\s\S]*?pollProtocolAutoPayJob/, 'protocol jobs and phone claims should resume polling')
assert.match(restore, /pay153ClaimedPhonePoolKeysByJob\.set[\s\S]*?pollPay153AutoPayJob/, '153 jobs and phone claims should resume polling')
assert.match(restore, /!item\.jobId[\s\S]*?item\.clientRequestId[\s\S]*?reconcileProtocolAutoPayStart/, 'a jobless protocol record should resolve its correlation key after restore')
assert.match(restore, /!item\.jobId[\s\S]*?item\.clientRequestId[\s\S]*?reconcilePay153AutoPayStart/, 'a jobless 153 record should resolve its correlation key after restore')

assert.match(source, /clearLegacyUnresolvedAutoPayJobs/, 'legacy jobless records should expose an explicit confirmed resolution path')
assert.match(
  source,
  /\['recovery_paused', 'unknown_outcome', 'unknown'\]\.includes\(String\(item\.status \|\| ''\)\)/,
  'an idempotency conflict marked unknown should expose the same manual resolution path as other quarantined outcomes',
)

for (const [name, nextName] of [
  ['pollProtocolAutoPayJob', 'pollPay153AutoPayJob'],
  ['pollPay153AutoPayJob', 'drainProtocolAutoPayQueue'],
]) {
  const body = source.slice(source.indexOf(`async function ${name}`), source.indexOf(`async function ${nextName}`))
  assert.match(body, /readPollingSnapshot\s*\(/, `${name} should classify status errors through the shared finite recovery policy`)
  assert.match(body, /recovery\.kind === 'retry'[\s\S]*?continue/, `${name} should retry status reconciliation without recursion or a tight loop`)
  const pausedBranch = body.match(/if \(\['permanent', 'paused'\][\s\S]*?return\s*\}/)?.[0] || ''
  assert.match(pausedBranch, /recovery_paused/, `${name} should persist a resumable pause after its retry budget`)
  assert.doesNotMatch(pausedBranch, /releaseClaimedPhonePoolEntriesAfterJob|removeAutoPayActiveJob/, `${name} should retain remote job ownership on an indeterminate status stop`)
  assert.doesNotMatch(body, name.includes('Protocol') ? /protocolJob\.value\s*=\s*job/ : /pay153Job\.value\s*=\s*job/, `${name} should not overwrite the manual job selected by the cancel button`)
}

const mounted = source.slice(source.indexOf('onMounted(async () =>'), source.indexOf('watch(form,'))
assert.match(mounted, /restorePaypalAutoPayState\(\)/, 'mount should restore auto-pay jobs after durable forms and phone state')

const unmount = source.slice(source.indexOf('onBeforeUnmount(() =>'))
assert.match(unmount, /persistPaypalAutoPayState\(\{ force: true \}\)[\s\S]*?storageWriter\.dispose\(\)/, 'unmount should synchronously checkpoint remote jobs before disposing storage')

const protocolValidate = source.slice(source.indexOf('function validateProtocolPayment'), source.indexOf('async function startProtocolPayment'))
const pay153Validate = source.slice(source.indexOf('function validatePay153Payment'), source.indexOf('async function startPay153Payment'))
assert.match(protocolValidate, /protocolAutoPayActiveJobs[\s\S]*?不能重复提交/, 'manual protocol payment should reject an account owned by auto-pay')
assert.match(pay153Validate, /pay153AutoPayActiveJobs[\s\S]*?不能重复提交/, 'manual 153 payment should reject an account owned by auto-pay')

console.log('paypal auto-pay job recovery contract passed')
