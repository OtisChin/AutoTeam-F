import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const bindCard = readFileSync(new URL('../src/components/BindCard.vue', import.meta.url), 'utf8')
const idealPage = readFileSync(new URL('../src/components/IdealLinkPage.vue', import.meta.url), 'utf8')

assert.match(bindCard, /const bindTaskPolling = createPollingLifecycle\(\)/, 'BindCard should guard bind-task polling with a lifecycle token')
assert.match(bindCard, /const goPayTaskPolling = createPollingLifecycle\(\)/, 'BindCard should guard GoPay polling with a lifecycle token')
assert.ok((bindCard.match(/if \(!bindTaskPolling\.isActive\(pollToken\)\) return/g) || []).length >= 3, 'BindCard should reject stale bind-task responses and callbacks')
assert.ok((bindCard.match(/if \(!goPayTaskPolling\.isActive\(pollToken\)\) return/g) || []).length >= 3, 'BindCard should reject stale GoPay responses and callbacks')
assert.match(bindCard, /if \(bindTaskPolling\.isActive\(pollToken\)\) void pollBindTask\(taskId, pollToken\)/, 'BindCard should only reschedule the active bind poll')
assert.match(bindCard, /if \(goPayTaskPolling\.isActive\(pollToken\)\) void pollGoPayTask\(taskId, pollToken\)/, 'BindCard should only reschedule the active GoPay poll')
assert.match(bindCard, /if \(!await bindTaskPolling\.waitUntilAvailable\(pollToken\)\) return/, 'BindCard should pause bind-task requests while hidden or offline')
assert.match(bindCard, /if \(!await goPayTaskPolling\.waitUntilAvailable\(pollToken\)\) return/, 'BindCard should pause GoPay requests while hidden or offline')
assert.match(bindCard, /function scheduleBindTaskPoll\(taskId, pollToken\)/, 'BindCard should centralize bind-task retry scheduling')
assert.match(bindCard, /function scheduleGoPayTaskPoll\(taskId, pollToken\)/, 'BindCard should centralize GoPay retry scheduling')
assert.match(bindCard, /bindTaskPolling\.dispose\(\)/, 'BindCard should dispose bind polling during unmount')
assert.match(bindCard, /goPayTaskPolling\.dispose\(\)/, 'BindCard should dispose GoPay polling during unmount')

const bindAccountLoader = bindCard.slice(
  bindCard.indexOf('async function loadAccounts'),
  bindCard.indexOf('function isBindableFreeAccount'),
)
const bindCardLoader = bindCard.slice(
  bindCard.indexOf('async function loadCards'),
  bindCard.indexOf('function saveHistory'),
)
const bindTaskPoll = bindCard.slice(
  bindCard.indexOf('async function pollBindTask'),
  bindCard.indexOf('async function pollGoPayTask'),
)
const goPayTaskPoll = bindCard.slice(
  bindCard.indexOf('async function pollGoPayTask'),
  bindCard.indexOf('function isTaskActive'),
)

assert.match(bindTaskPoll, /catch \(e\) \{[\s\S]{0,500}?scheduleBindTaskPoll\(taskId, pollToken\)/, 'BindCard should retry an active bind poll after a transient request error')
assert.match(goPayTaskPoll, /catch \(e\) \{[\s\S]{0,500}?scheduleGoPayTaskPoll\(taskId, pollToken\)/, 'BindCard should retry an active GoPay poll after a transient request error')

assert.match(bindAccountLoader, /async function loadAccounts\(shouldCommit = \(\) => true\)/, 'BindCard account loading should accept a lifecycle commit guard')
assert.ok((bindAccountLoader.match(/if \(!shouldCommit\(\)\) return/g) || []).length >= 3, 'BindCard account loading should guard its start, response, and error side effects')
assert.match(bindAccountLoader, /finally \{\s+if \(shouldCommit\(\)\) loadingAccounts\.value = false\s+\}/, 'BindCard account loading should not publish completion after its lifecycle expires')

assert.match(bindCardLoader, /async function loadCards\(shouldCommit = \(\) => true\)/, 'BindCard card loading should accept a lifecycle commit guard')
assert.ok((bindCardLoader.match(/if \(!shouldCommit\(\)\) return/g) || []).length >= 3, 'BindCard card loading should guard its start, response, and error side effects')
assert.match(bindCardLoader, /finally \{\s+if \(shouldCommit\(\)\) loadingCards\.value = false\s+\}/, 'BindCard card loading should not publish completion after its lifecycle expires')

assert.match(
  bindTaskPoll,
  /if \(!bindTaskPolling\.isActive\(pollToken\)\) return\s+await loadCards\(\(\) => bindTaskPolling\.isActive\(pollToken\)\)\s+if \(!bindTaskPolling\.isActive\(pollToken\)\) return/,
  'BindCard should guard both sides of its terminal card-pool load and pass the lifecycle into the loader',
)
assert.match(
  goPayTaskPoll,
  /if \(!goPayTaskPolling\.isActive\(pollToken\)\) return\s+await loadAccounts\(\(\) => goPayTaskPolling\.isActive\(pollToken\)\)\s+if \(!goPayTaskPolling\.isActive\(pollToken\)\) return/,
  'BindCard should guard both sides of its terminal account-pool load and pass the lifecycle into the loader',
)

assert.match(idealPage, /const idealPolling = createPollingLifecycle\(\)/, 'IdealLinkPage should own a cancellable polling lifecycle')
assert.ok((idealPage.match(/if \(!idealPolling\.isActive\(pollToken\)\) return/g) || []).length >= 6, 'IdealLinkPage should reject stale responses in both polling loops')
assert.match(idealPage, /await idealPolling\.wait\(1200, pollToken\)/, 'iDEAL batch polling should use a cancellable delay')
assert.match(idealPage, /await idealPolling\.wait\(900, pollToken\)/, 'iDEAL long-link polling should use a cancellable delay')
assert.equal((idealPage.match(/if \(!await idealPolling\.waitUntilAvailable\(pollToken\)\) return/g) || []).length, 5, 'both iDEAL polling loops, pre-ACK recovery, and terminal network steps should pause while hidden or offline')
assert.match(idealPage, /idealPolling\.dispose\(\)/, 'IdealLinkPage should settle polling delays during unmount')
assert.doesNotMatch(idealPage, /pollTimer/, 'IdealLinkPage should not leave an externally-cleared unresolved timeout promise')

const idealBatchPoll = idealPage.slice(
  idealPage.indexOf('async function pollIdealJob'),
  idealPage.indexOf('async function start'),
)
const idealLongLinkPoll = idealPage.slice(
  idealPage.indexOf('async function pollJob'),
  idealPage.indexOf('async function generate'),
)
const idealQrRenderer = idealPage.slice(
  idealPage.indexOf('async function renderQr'),
  idealPage.indexOf('async function pollJob'),
)
const idealReload = idealPage.slice(
  idealPage.indexOf('async function refreshAccounts'),
  idealPage.indexOf('async function pollIdealJob'),
)

assert.match(
  idealQrRenderer,
  /async function renderQr\(value, pollToken\)[\s\S]*?if \(!idealPolling\.isActive\(pollToken\)\) return false[\s\S]*?const blob = await api\.getIdealQrBlob\(value\)\s+if \(!idealPolling\.isActive\(pollToken\)\) return false[\s\S]{0,200}?qrUrl\.value = URL\.createObjectURL\(blob\)/,
  'iDEAL QR rendering should reject a stale poll both before fetching and before creating an object URL',
)
assert.match(
  idealBatchPoll,
  /for \(;;\) \{\s+if \(!idealPolling\.isActive\(pollToken\)\) return\s+if \(!await idealPolling\.waitUntilAvailable\(pollToken\)\) return\s+if \(!idealPolling\.isActive\(pollToken\)\) return\s+const recovery = await readPollingSnapshot\(\{\s+request: \(\) => api\.getIdealJob/,
  'iDEAL batch polling should gate every request on page availability',
)
assert.match(
  idealBatchPoll,
  /if \(!idealPolling\.isActive\(pollToken\)\) return\s+try \{ await renderQr\(result\.value\.long_url, pollToken\) \} catch \{\}\s+if \(!idealPolling\.isActive\(pollToken\)\) return/,
  'iDEAL batch completion should guard both sides of asynchronous QR rendering',
)
assert.match(
  idealBatchPoll,
  /if \(!idealPolling\.isActive\(pollToken\)\) return\s+await reloadAll\(pollToken\)\s+if \(!idealPolling\.isActive\(pollToken\)\) return/,
  'iDEAL batch completion should guard both sides of its terminal refresh',
)
assert.match(
  idealLongLinkPoll,
  /for \(;;\) \{\s+if \(!idealPolling\.isActive\(pollToken\)\) return\s+if \(!await idealPolling\.waitUntilAvailable\(pollToken\)\) return\s+if \(!idealPolling\.isActive\(pollToken\)\) return\s+const recovery = await readPollingSnapshot\(\{\s+request: \(\) => api\.getIdealLongLinkJob/,
  'iDEAL long-link polling should gate every request on page availability',
)
assert.match(
  idealLongLinkPoll,
  /if \(!idealPolling\.isActive\(pollToken\)\) return\s+await renderQr\(url, pollToken\)\s+if \(!idealPolling\.isActive\(pollToken\)\) return[\s\S]*?setStatus\('iDEAL 链与二维码已生成。'\)[\s\S]*?playNotificationSound/,
  'iDEAL long-link completion should not publish status or sound after asynchronous QR rendering goes stale',
)
assert.match(
  idealBatchPoll,
  /readPollingSnapshot\(\{[\s\S]*?wait: delayMs => idealPolling\.wait\(delayMs, pollToken\)[\s\S]*?recovery\.kind === 'retry'[\s\S]*?continue/,
  'iDEAL batch status polling should lifecycle-gate retries after transient GET failures',
)
assert.match(
  idealLongLinkPoll,
  /readPollingSnapshot\(\{[\s\S]*?wait: delayMs => idealPolling\.wait\(delayMs, pollToken\)[\s\S]*?recovery\.kind === 'retry'[\s\S]*?continue/,
  'iDEAL long-link status polling should lifecycle-gate retries after transient GET failures',
)
assert.ok(
  (idealReload.match(/if \(!canCommitIdealRefresh\(pollToken\)\) return/g) || []).length >= 5,
  'iDEAL terminal refresh loaders should reject stale results before mutating account, link, or status state',
)
assert.match(
  idealQrRenderer,
  /if \(!await idealPolling\.waitUntilAvailable\(pollToken\)\) return false\s+if \(!idealPolling\.isActive\(pollToken\)\) return false\s+const blob = await api\.getIdealQrBlob/,
  'iDEAL should not start terminal QR work while hidden or offline',
)
assert.match(
  idealReload,
  /if \(pollToken !== undefined\) \{\s+if \(!await idealPolling\.waitUntilAvailable\(pollToken\)\) return\s+if \(!idealPolling\.isActive\(pollToken\)\) return\s+\}/,
  'iDEAL should not start its terminal refresh while hidden or offline',
)

const { createPollingLifecycle, createSharedPollingGate } = await import('../src/pollingLifecycle.js')

function fakeTimers() {
  let nextId = 1
  const scheduled = new Map()
  return {
    scheduled,
    setTimer(callback) {
      const id = nextId++
      scheduled.set(id, callback)
      return id
    },
    clearTimer(id) {
      scheduled.delete(id)
    },
  }
}

function fakeEventTarget() {
  const listeners = new Map()
  return {
    listeners,
    addEventListener(type, callback) {
      if (!listeners.has(type)) listeners.set(type, new Set())
      listeners.get(type).add(callback)
    },
    removeEventListener(type, callback) {
      listeners.get(type)?.delete(callback)
    },
    dispatch(type) {
      for (const callback of [...(listeners.get(type) || [])]) callback()
    },
  }
}

{
  const timers = fakeTimers()
  const lifecycle = createPollingLifecycle({
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  const firstToken = lifecycle.start()
  const pendingDelay = lifecycle.wait(1000, firstToken)

  assert.equal(timers.scheduled.size, 1, 'active polling should schedule one delay')
  const secondToken = lifecycle.start()
  assert.equal(await pendingDelay, false, 'superseding polling should settle the old delay as cancelled')
  assert.equal(timers.scheduled.size, 0, 'superseding polling should clear the old timer')
  assert.equal(lifecycle.isActive(firstToken), false, 'the old poll token should be invalidated')
  assert.equal(lifecycle.isActive(secondToken), true, 'the newest poll token should stay active')
}

{
  const timers = fakeTimers()
  const lifecycle = createPollingLifecycle({
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  const token = lifecycle.start()
  const pendingDelay = lifecycle.wait(1000, token)

  lifecycle.dispose()

  assert.equal(await pendingDelay, false, 'disposing should settle a pending polling delay')
  assert.equal(timers.scheduled.size, 0, 'disposing should clear pending timers')
  assert.equal(lifecycle.isActive(token), false, 'disposing should invalidate in-flight requests')
  assert.equal(lifecycle.start(), null, 'disposed polling must not restart after an in-flight request returns')
}

{
  const timers = fakeTimers()
  const lifecycle = createPollingLifecycle({
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
  })
  const firstToken = lifecycle.start()
  const pendingDelay = lifecycle.wait(1000, firstToken)

  lifecycle.cancel()

  assert.equal(await pendingDelay, false, 'cancelling should settle the current polling delay')
  assert.equal(lifecycle.isActive(firstToken), false, 'cancelling should invalidate the current token')
  assert.equal(timers.scheduled.size, 0, 'cancelling should clear the current timer')
  const secondToken = lifecycle.start()
  assert.equal(lifecycle.isActive(secondToken), true, 'cancelled polling should remain restartable')
}

{
  const timers = fakeTimers()
  const documentTarget = Object.assign(fakeEventTarget(), { visibilityState: 'hidden' })
  const windowTarget = fakeEventTarget()
  let online = true
  const lifecycle = createPollingLifecycle({
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    documentTarget,
    windowTarget,
    getOnline: () => online,
  })
  const token = lifecycle.start()
  const resumed = lifecycle.waitUntilAvailable(token)

  assert.equal(timers.scheduled.size, 0, 'hidden polling should wait for an event without a wake-up timer')
  assert.equal(documentTarget.listeners.get('visibilitychange')?.size, 1)
  documentTarget.visibilityState = 'visible'
  documentTarget.dispatch('visibilitychange')
  assert.equal(await resumed, true, 'a visible online page should resume the active polling token')
  assert.equal(documentTarget.listeners.get('visibilitychange')?.size, 0, 'availability listeners should be removed after resuming')
  assert.equal(windowTarget.listeners.get('online')?.size, 0)

  online = false
  const offlineWait = lifecycle.waitUntilAvailable(token)
  windowTarget.dispatch('online')
  online = true
  windowTarget.dispatch('online')
  assert.equal(await offlineWait, true, 'the online event should resume an otherwise visible page')

  documentTarget.visibilityState = 'hidden'
  const cancelledWait = lifecycle.waitUntilAvailable(token)
  lifecycle.cancel()
  assert.equal(await cancelledWait, false, 'cancelling should settle an event-based availability wait')
  assert.equal(documentTarget.listeners.get('visibilitychange')?.size, 0)
  assert.equal(windowTarget.listeners.get('online')?.size, 0)
}

{
  const timers = fakeTimers()
  const documentTarget = Object.assign(fakeEventTarget(), { visibilityState: 'hidden' })
  const windowTarget = fakeEventTarget()
  const gate = createSharedPollingGate({
    setTimer: timers.setTimer,
    clearTimer: timers.clearTimer,
    documentTarget,
    windowTarget,
    getOnline: () => true,
  })

  const first = gate.waitUntilAvailable()
  const second = gate.waitUntilAvailable()
  assert.equal(timers.scheduled.size, 0, 'a shared hidden-page gate should not use wake-up timers')
  assert.equal(documentTarget.listeners.get('visibilitychange')?.size, 1, 'concurrent pollers should share one visibility listener')
  assert.equal(windowTarget.listeners.get('online')?.size, 1, 'concurrent pollers should share one online listener')

  documentTarget.visibilityState = 'visible'
  documentTarget.dispatch('visibilitychange')
  assert.deepEqual(await Promise.all([first, second]), [true, true], 'all active pollers should resume when the page becomes available')
  assert.equal(documentTarget.listeners.get('visibilitychange')?.size, 0)
  assert.equal(windowTarget.listeners.get('online')?.size, 0)

  const delayA = gate.wait(1000)
  const delayB = gate.wait(1000)
  assert.equal(timers.scheduled.size, 2, 'concurrent pollers may own independent cadence delays')
  gate.dispose()
  assert.deepEqual(await Promise.all([delayA, delayB]), [false, false], 'disposing should settle every shared cadence delay')
  assert.equal(timers.scheduled.size, 0, 'disposing should clear all shared cadence timers')
  assert.equal(await gate.waitUntilAvailable(), false, 'a disposed shared gate must not resume new pollers')
}

console.log('polling lifecycle regression contract passed')
