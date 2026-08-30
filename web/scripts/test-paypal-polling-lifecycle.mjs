import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')

assert.match(source, /import \{ createSharedPollingGate \} from '\.\.\/pollingLifecycle\.js'/, 'PayPal should use a shared cancellable polling gate')
assert.match(source, /const paypalPolling = createSharedPollingGate\(\)/, 'PayPal should own one gate for concurrent job pollers')
assert.doesNotMatch(source, /setInterval\s*\(\(\)\s*=>\s*\{?\s*void scan(?:Protocol|Pay153)AutoPayLinks/, 'PayPal auto-pay scans must not overlap with setInterval')

const pollFunctions = [
  ['pollJob', 'getUsPaypalJob'],
  ['pollProtocolAutoPayJob', 'getUsPaypalProtocolJob'],
  ['pollPay153AutoPayJob', 'getUsPaypal153Job'],
  ['pollProtocolJob', 'getUsPaypalProtocolJob'],
  ['pollPay153Job', 'getUsPaypal153Job'],
]

function functionSource(name) {
  const start = source.indexOf(`async function ${name}(`)
  assert.notEqual(start, -1, `${name} should exist`)
  const next = source.indexOf('\nasync function ', start + 1)
  return source.slice(start, next === -1 ? source.length : next)
}

for (const [name, apiMethod] of pollFunctions) {
  const body = functionSource(name)
  assert.match(
    body,
    new RegExp(`if \\(!await paypalPolling\\.waitUntilAvailable\\(\\)\\) return[\\s\\S]{0,240}?api\\.${apiMethod}`),
    `${name} should not start a request while hidden or offline`,
  )
  assert.match(body, /if \(!await paypalPolling\.wait\(1000\)\) return/, `${name} should use a cancellable cadence delay`)
  assert.doesNotMatch(body, /new Promise\(resolve => window\.setTimeout\(resolve, 1000\)\)/, `${name} should not leave an unmanaged sleep on unmount`)
}

for (const [name, apiMethod] of [
  ['pollProtocolAutoPayJob', 'getUsPaypalProtocolJob'],
  ['pollPay153AutoPayJob', 'getUsPaypal153Job'],
  ['pollProtocolJob', 'getUsPaypalProtocolJob'],
  ['pollPay153Job', 'getUsPaypal153Job'],
]) {
  const body = functionSource(name)
  const requestIndex = body.indexOf(`api.${apiMethod}`)
  const firstRecoveryBranchIndex = body.indexOf("if (recovery.kind === 'retry')", requestIndex)
  assert.notEqual(requestIndex, -1, `${name} should issue its status request`)
  assert.notEqual(firstRecoveryBranchIndex, -1, `${name} should classify the status result`)
  assert.match(
    body.slice(requestIndex, firstRecoveryBranchIndex),
    /if \(componentUnmounted\) return/,
    `${name} should discard every late status outcome before mutating retained job state`,
  )
  assert.match(
    body,
    /onTransientError:\s*\([^)]*\)\s*=>\s*\{\s*if \(componentUnmounted\) return/,
    `${name} should ignore transient-error callbacks that arrive after unmount`,
  )
}

for (const mode of ['Protocol', 'Pay153']) {
  const scheduler = functionSource(`schedule${mode}AutoPayScan`)
  assert.match(scheduler, /if \(!await paypalPolling\.waitUntilAvailable\(\)\) return/, `${mode} auto-pay should wait for page availability`)
  assert.match(scheduler, new RegExp(`await scan${mode}AutoPayLinks\\([^)]*\\)`), `${mode} auto-pay should await each scan before scheduling another`)
  assert.match(scheduler, new RegExp(`schedule${mode}AutoPayScan\\([^)]*\\)`), `${mode} auto-pay should completion-schedule its next scan`)
  const scan = functionSource(`scan${mode}AutoPayLinks`)
  const generationName = mode === 'Protocol' ? 'protocolAutoPayScheduleGeneration' : 'pay153AutoPayScheduleGeneration'
  assert.match(scan, new RegExp(`async function scan${mode}AutoPayLinks\\(generation = ${generationName}\\)`), `${mode} auto-pay scans should carry their schedule generation`)
  assert.match(
    scan,
    new RegExp(`await refreshPaymentLinks\\(\\)[\\s\\S]{0,240}?generation !== ${generationName}\\) return`),
    `${mode} auto-pay should discard a scan response after stop or restart`,
  )
}

assert.match(source, /onBeforeUnmount\(\(\) => \{[\s\S]*?paypalPolling\.dispose\(\)/, 'PayPal should cancel every pending availability wait and cadence delay on unmount')

console.log('PayPal polling lifecycle contract passed')
