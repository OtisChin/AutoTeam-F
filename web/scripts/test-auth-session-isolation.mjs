import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

import {
  createAccountLoadAbortError,
  createAccountLoadLifecycle,
  isAccountLoadAbortError,
  shouldLoadDashboardAccounts,
} from '../src/accountLoadPolicy.js'
import { createSingleFlight } from '../src/runtimePerformance.js'

const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

function extractFunction(source, name) {
  const asyncStart = source.indexOf(`async function ${name}(`)
  const syncStart = source.indexOf(`function ${name}(`)
  const start = asyncStart === -1 ? syncStart : asyncStart
  assert.notEqual(start, -1, `${name} should exist`)

  const bodyStart = source.indexOf('{', start)
  let depth = 0
  let quote = ''
  let escaped = false
  let lineComment = false
  let blockComment = false

  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index]
    const next = source[index + 1]

    if (lineComment) {
      if (char === '\n') lineComment = false
      continue
    }
    if (blockComment) {
      if (char === '*' && next === '/') {
        blockComment = false
        index += 1
      }
      continue
    }
    if (quote) {
      if (escaped) {
        escaped = false
      } else if (char === '\\') {
        escaped = true
      } else if (char === quote) {
        quote = ''
      }
      continue
    }
    if (char === '/' && next === '/') {
      lineComment = true
      index += 1
      continue
    }
    if (char === '/' && next === '*') {
      blockComment = true
      index += 1
      continue
    }
    if (char === "'" || char === '"' || char === '`') {
      quote = char
      continue
    }
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, index + 1)
    }
  }

  throw new Error(`could not extract ${name}`)
}

function installFunctions(names, context) {
  vm.createContext(context)
  const declarations = names.map(name => extractFunction(appSource, name)).join('\n')
  const exports = names.map(name => `globalThis.${name} = ${name}`).join('\n')
  vm.runInContext(`${declarations}\n${exports}`, context)
  return Object.fromEntries(names.map(name => [name, context[name]]))
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function attachAccountLoadLifecycle(context, load = async () => context.status.value) {
  context.accountLoadLifecycle = createAccountLoadLifecycle({
    load,
    initialSnapshot: context.status.value,
    onChange(nextState) {
      context.status.value = nextState.snapshot
      context.loading.value = nextState.loading
    },
  })
  context.createAccountLoadAbortError = createAccountLoadAbortError
  return context.accountLoadLifecycle
}

function loginContext(checkAuthImpl, initialStoredKey = null) {
  let storedKey = initialStoredKey
  let epoch = 0
  let refreshCalls = 0
  let pollingCalls = 0
  let stopPollingCalls = 0

  const context = {
    api: { checkAuth: checkAuthImpl },
    authenticated: { value: false },
    authRequired: { value: true },
    authError: { value: '' },
    startupError: { value: '' },
    authLoading: { value: false },
    inputKey: { value: 'valid-key' },
    getApiKey() { return storedKey || '' },
    setApiKey(key) { storedKey = key },
    clearApiKey() { storedKey = null },
    async prepareStorageSession() { return { owner: 'test-owner' } },
    advanceAuthEpoch() { epoch += 1; return epoch },
    isCurrentAuthEpoch(candidate) { return candidate === epoch },
    stopPolling() { stopPollingCalls += 1 },
    async refresh() { refreshCalls += 1 },
    syncPollingWithTasks() { pollingCalls += 1 },
    console,
  }
  const functions = installFunctions(['checkAuth', 'doLogin'], context)
  return {
    ...functions,
    context,
    get storedKey() { return storedKey },
    get epoch() { return epoch },
    get refreshCalls() { return refreshCalls },
    get pollingCalls() { return pollingCalls },
    get stopPollingCalls() { return stopPollingCalls },
  }
}

async function loginRetainsKeyOnTimeout() {
  const error = Object.assign(new Error('request timed out'), { timeout: true })
  const fixture = loginContext(async () => { throw error }, 'recoverable-key')

  await fixture.doLogin()

  assert.equal(fixture.storedKey, 'recoverable-key', 'a timeout must not replace the owner of recoverable job state')
  assert.equal(fixture.context.inputKey.value, 'valid-key', 'the unconfirmed candidate remains available for an explicit retry')
  assert.match(fixture.context.authError.value || fixture.context.startupError.value, /连接服务超时/)
  assert.doesNotMatch(fixture.context.authError.value, /API Key 无效/)
}

async function loginRetainsKeyOnServerFailure() {
  const error = Object.assign(new Error('service unavailable'), { status: 503 })
  const fixture = loginContext(async () => { throw error }, 'recoverable-key')

  await fixture.doLogin()

  assert.equal(fixture.storedKey, 'recoverable-key', 'a 5xx response must not replace the owner of recoverable job state')
  assert.equal(fixture.context.inputKey.value, 'valid-key')
  assert.match(fixture.context.authError.value || fixture.context.startupError.value, /暂时无法连接服务/)
  assert.doesNotMatch(fixture.context.authError.value, /API Key 无效/)
}

async function loginClearsKeyOnConfirmedRejection() {
  const error = Object.assign(new Error('unauthorized'), { status: 401 })
  const fixture = loginContext(async () => { throw error })

  await fixture.doLogin()

  assert.equal(fixture.storedKey, null, 'a confirmed 401 should clear the rejected key')
  assert.equal(fixture.context.authError.value, 'API Key 无效')
}

async function loginAuthenticatesCandidateBeforeRotatingStorageOwner() {
  const events = []
  const fixture = loginContext(async key => {
    events.push(`auth:${key}`)
    return { authenticated: true, auth_required: true }
  }, 'recoverable-key')
  fixture.context.prepareStorageSession = async key => {
    events.push(`prepare:${key}:authenticated=${fixture.context.authenticated.value}`)
    return { owner: 'candidate-owner' }
  }

  await fixture.doLogin()

  assert.deepEqual(events.slice(0, 2), ['auth:valid-key', 'prepare:valid-key:authenticated=false'], 'candidate auth must be confirmed without mounting operator pages before storage ownership is ready')
  assert.equal(fixture.context.authenticated.value, true, 'the authenticated UI should commit only after owner rotation and key activation')
}

async function rejectedCandidateDoesNotRotateOrDiscardPriorOwner() {
  let prepareCalls = 0
  const fixture = loginContext(async () => {
    throw Object.assign(new Error('unauthorized'), { status: 401 })
  }, 'recoverable-key')
  fixture.context.prepareStorageSession = async () => {
    prepareCalls += 1
    return { owner: 'wrong-owner' }
  }

  await fixture.doLogin()

  assert.equal(prepareCalls, 0, 'a rejected candidate must never rotate the storage owner')
  assert.equal(fixture.storedKey, 'recoverable-key', 'a rejected different candidate must preserve the prior resumable identity')
}

async function loginStartsANewAuthEpoch() {
  const fixture = loginContext(async () => ({ authenticated: true, auth_required: true }))

  await fixture.doLogin()

  assert.equal(fixture.epoch, 1, 'setting a new key should advance the auth epoch')
  assert.equal(fixture.refreshCalls, 1)
  assert.equal(fixture.pollingCalls, 1)
}

async function loginRejectsConcurrentEnterSubmission() {
  const storagePrepare = deferred()
  const fixture = loginContext(async () => ({ authenticated: true, auth_required: true }))
  let prepareCalls = 0
  fixture.context.prepareStorageSession = async () => {
    prepareCalls += 1
    await storagePrepare.promise
    return { owner: 'test-owner' }
  }

  fixture.context.inputKey.value = 'key-a'
  const first = fixture.doLogin()
  fixture.context.inputKey.value = 'key-b'
  const second = fixture.doLogin()
  for (let attempt = 0; attempt < 10 && prepareCalls === 0; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 0))
  }

  assert.equal(prepareCalls, 1, 'a second Enter press must not start another asynchronous owner rotation')
  assert.equal(fixture.epoch, 1, 'a blocked duplicate login must not advance the auth epoch')

  storagePrepare.resolve()
  await Promise.all([first, second])
  assert.equal(fixture.storedKey, 'key-a', 'the accepted submission must use its key snapshot even if the input changes while awaiting the digest')
}

async function refreshRejectionDoesNotRestartPolling() {
  const fixture = loginContext(async () => ({ authenticated: true, auth_required: true }))
  fixture.context.refresh = async () => {
    fixture.context.authenticated.value = false
  }

  await fixture.doLogin()

  assert.equal(fixture.pollingCalls, 0, 'a refresh that rejects the session must not restart polling')
}

async function logoutInvalidatesTheCurrentAuthEpoch() {
  let epoch = 7
  let cleared = 0
  let sessionCleared = 0
  let stopped = 0
  const context = {
    authenticated: { value: true },
    clearApiKey() { cleared += 1 },
    clearStorageSession() { sessionCleared += 1 },
    async nextTick() {},
    advanceAuthEpoch() { epoch += 1; return epoch },
    stopPolling() { stopped += 1 },
  }
  const { doLogout } = installFunctions(['doLogout'], context)

  await doLogout()

  assert.equal(epoch, 8, 'logout should invalidate every in-flight request from the old epoch')
  assert.equal(cleared, 1)
  assert.equal(stopped, 1)
  assert.equal(sessionCleared, 1)
  assert.equal(context.authenticated.value, false)
}

async function authEpochChangeClearsPreviousSessionState() {
  const context = {
    authEpoch: 4,
    status: { value: { owner: 'session-A' } },
    tasks: { value: [{ task_id: 'secret-task-A' }] },
    adminStatus: { value: { owner: 'session-A' } },
    codexStatus: { value: { owner: 'session-A' } },
    manualAccountStatus: { value: { owner: 'session-A' } },
    runningTask: { value: { task_id: 'secret-task-A' } },
    loading: { value: true },
  }
  attachAccountLoadLifecycle(context)
  const { advanceAuthEpoch } = installFunctions(['resetSessionState', 'advanceAuthEpoch'], context)

  const nextEpoch = advanceAuthEpoch()

  assert.equal(nextEpoch, 5)
  assert.equal(context.status.value, null)
  assert.equal(context.tasks.value.length, 0)
  assert.equal(context.adminStatus.value, null)
  assert.equal(context.codexStatus.value, null)
  assert.equal(context.manualAccountStatus.value, null)
  assert.equal(context.runningTask.value, null)
  assert.equal(context.loading.value, false)
}

async function newSessionTimeoutCannotFallbackToPriorSessionState() {
  const timedOut = () => Promise.reject(Object.assign(new Error('request timed out'), { timeout: true }))
  const context = {
    authEpoch: 2,
    status: { value: { owner: 'session-A' } },
    tasks: { value: [{ task_id: 'secret-task-A' }] },
    adminStatus: { value: { owner: 'session-A' } },
    codexStatus: { value: { owner: 'session-A' } },
    manualAccountStatus: { value: { owner: 'session-A' } },
    runningTask: { value: { task_id: 'secret-task-A' } },
    loading: { value: false },
    authenticated: { value: true },
    api: {
      getTasks: timedOut,
      getAdminStatus: timedOut,
      getMainCodexStatus: timedOut,
      getManualAccountStatus: timedOut,
    },
    isCurrentAuthEpoch(candidate) { return candidate === context.authEpoch },
    syncPollingWithTasks() {},
    console: { warn() {} },
  }
  attachAccountLoadLifecycle(context)
  const functions = installFunctions(
    ['loadOrFallback', 'refreshAuxiliaryState', 'resetSessionState', 'advanceAuthEpoch'],
    context,
  )

  const sessionBEpoch = functions.advanceAuthEpoch()
  await functions.refreshAuxiliaryState(sessionBEpoch)

  assert.equal(context.status.value, null)
  assert.equal(context.tasks.value.length, 0)
  assert.equal(context.adminStatus.value, null)
  assert.equal(context.codexStatus.value, null)
  assert.equal(context.manualAccountStatus.value, null)
  assert.equal(context.runningTask.value, null)
}

async function newEpochDoesNotJoinOldSingleFlight() {
  const requests = new Map()
  const calls = []
  const singleFlight = createSingleFlight(async epoch => {
    calls.push(epoch)
    const request = deferred()
    requests.set(epoch, request)
    return request.promise
  }, { key: epoch => epoch })

  const oldRequest = singleFlight(1)
  const duplicateOldRequest = singleFlight(1)
  const newRequest = singleFlight(2)

  assert.strictEqual(oldRequest, duplicateOldRequest, 'one epoch should still share overlapping work')
  assert.notStrictEqual(newRequest, oldRequest, 'a new auth epoch must start independent work')
  assert.deepEqual(calls, [1, 2])

  requests.get(1).resolve('old')
  requests.get(2).resolve('new')
  assert.equal(await oldRequest, 'old')
  assert.equal(await newRequest, 'new')
}

function auxiliaryContext(getTasks) {
  let epoch = 1
  let pollingCalls = 0
  const context = {
    api: {
      getTasks,
      getAdminStatus: async () => ({ owner: 'old' }),
      getMainCodexStatus: async () => ({ owner: 'old' }),
      getManualAccountStatus: async () => ({ owner: 'old' }),
    },
    tasks: { value: [{ task_id: 'current' }] },
    adminStatus: { value: { owner: 'current' } },
    codexStatus: { value: { owner: 'current' } },
    manualAccountStatus: { value: { owner: 'current' } },
    runningTask: { value: { task_id: 'current' } },
    authenticated: { value: true },
    isCurrentAuthEpoch(candidate) { return candidate === epoch },
    syncPollingWithTasks() { pollingCalls += 1 },
    console,
  }
  const functions = installFunctions(['loadOrFallback', 'refreshAuxiliaryState'], context)
  return {
    ...functions,
    context,
    advanceEpoch() { epoch += 1 },
    get pollingCalls() { return pollingCalls },
  }
}

async function staleAuxiliarySuccessCannotCommitOrRestartPolling() {
  const taskRequest = deferred()
  const fixture = auxiliaryContext(() => taskRequest.promise)

  const refresh = fixture.refreshAuxiliaryState(1)
  fixture.advanceEpoch()
  taskRequest.resolve([{ task_id: 'old', status: 'running', command: 'refresh-quota' }])
  await refresh

  assert.equal(fixture.context.tasks.value[0].task_id, 'current', 'old tasks must not commit into the new session')
  assert.equal(fixture.context.adminStatus.value.owner, 'current')
  assert.equal(fixture.context.codexStatus.value.owner, 'current')
  assert.equal(fixture.context.manualAccountStatus.value.owner, 'current')
  assert.equal(fixture.pollingCalls, 0, 'an old response must not restart polling after logout')
}

async function staleAuxiliary401CannotEjectNewSession() {
  const taskRequest = deferred()
  const fixture = auxiliaryContext(() => taskRequest.promise)

  const refresh = fixture.refreshAuxiliaryState(1)
  fixture.advanceEpoch()
  taskRequest.reject(Object.assign(new Error('old key rejected'), { status: 401 }))
  await refresh

  assert.equal(fixture.context.authenticated.value, true, 'an old 401 must not change the new session auth state')
  assert.equal(fixture.pollingCalls, 0)
}

async function staleAuthCheckCannotCommit() {
  const request = deferred()
  let epoch = 1
  const context = {
    api: { checkAuth: () => request.promise },
    authenticated: { value: true },
    authRequired: { value: true },
    startupError: { value: 'current' },
    isCurrentAuthEpoch(candidate) { return candidate === epoch },
  }
  const { checkAuth } = installFunctions(['checkAuth'], context)

  const result = checkAuth(1)
  epoch = 2
  request.resolve({ authenticated: false, auth_required: false })
  await result

  assert.equal(context.authenticated.value, true, 'a stale auth result must not overwrite the current session')
  assert.equal(context.authRequired.value, true)
  assert.equal(context.startupError.value, 'current')
}

function refreshContext(loadDashboardStatusOnce) {
  const context = {
    authEpoch: 1,
    currentPage: { value: 'dashboard' },
    loading: { value: false },
    status: { value: { owner: 'current' } },
    tasks: { value: [] },
    adminStatus: { value: null },
    codexStatus: { value: null },
    manualAccountStatus: { value: null },
    runningTask: { value: null },
    authenticated: { value: true },
    refreshAuxiliaryStateOnce: async () => {},
    shouldLoadDashboardAccounts,
    isAccountLoadAbortError,
    createAccountLoadAbortError,
    stopPolling() {},
    Date,
    console,
  }
  attachAccountLoadLifecycle(context, loadDashboardStatusOnce)
  const functions = installFunctions(
    ['resetSessionState', 'advanceAuthEpoch', 'isCurrentAuthEpoch', 'refreshDashboardAccounts', 'performRefresh'],
    context,
  )
  return {
    ...functions,
    context,
    advanceEpoch() {
      const epoch = functions.advanceAuthEpoch()
      context.status.value = { owner: 'current' }
      context.loading.value = true
      return epoch
    },
  }
}

async function staleDashboardSuccessCannotCommit() {
  const request = deferred()
  const fixture = refreshContext(() => request.promise)

  const refresh = fixture.performRefresh(1)
  fixture.advanceEpoch()
  fixture.context.loading.value = true
  request.resolve({ owner: 'old' })
  await refresh

  assert.equal(fixture.context.status.value.owner, 'current', 'old dashboard data must not commit into the new session')
  assert.equal(fixture.context.loading.value, true, 'old cleanup must not clear the new epoch loading state')
}

async function staleDashboard401CannotEjectNewSession() {
  const request = deferred()
  const fixture = refreshContext(() => request.promise)

  const refresh = fixture.performRefresh(1)
  fixture.advanceEpoch()
  fixture.context.loading.value = true
  request.reject(Object.assign(new Error('old key rejected'), { status: 401 }))
  await refresh

  assert.equal(fixture.context.authenticated.value, true, 'an old dashboard 401 must not eject the new session')
  assert.equal(fixture.context.loading.value, true)
}

function startupContext(functionName) {
  let pollingCalls = 0
  const setupEvents = []
  const context = {
    authEpoch: 0,
    startupError: { value: '' },
    authLoading: { value: false },
    needSetup: { value: functionName === 'onSetupDone' },
    authenticated: { value: true },
    isCurrentAuthEpoch: epoch => epoch === 0,
    checkSetup: async () => true,
    prepareStorageSession: async (key, options = {}) => {
      setupEvents.push({ phase: 'prepare', key, rotate: Boolean(options.rotate), needSetup: context.needSetup.value })
      return { owner: 'test-owner' }
    },
    getApiKey: () => 'stored-key',
    checkAuth: async () => {
      setupEvents.push({ phase: 'auth', needSetup: context.needSetup.value })
      return true
    },
    refresh: async () => { context.authenticated.value = false },
    syncPollingWithTasks: () => { pollingCalls += 1 },
  }
  const functions = installFunctions([functionName], context)
  return {
    ...functions,
    context,
    get pollingCalls() { return pollingCalls },
    get setupEvents() { return setupEvents },
  }
}

async function initializationRefreshRejectionDoesNotRestartPolling() {
  const fixture = startupContext('initializeApp')

  await fixture.initializeApp()

  assert.equal(fixture.pollingCalls, 0, 'startup refresh rejection must not restart polling')
}

async function setupRefreshRejectionDoesNotRestartPolling() {
  const fixture = startupContext('onSetupDone')

  await fixture.onSetupDone()

  assert.equal(fixture.pollingCalls, 0, 'post-setup refresh rejection must not restart polling')
}

async function setupBindsGeneratedKeyBeforeMountingAuthenticatedPages() {
  const fixture = startupContext('onSetupDone')

  await fixture.onSetupDone('generated-key')

  assert.deepEqual(fixture.setupEvents.slice(0, 2), [
    { phase: 'prepare', key: 'generated-key', rotate: true, needSetup: true },
    { phase: 'auth', needSetup: false },
  ], 'post-setup storage ownership must rotate to the generated key before authenticated pages mount')
}

async function initializationStopsBeforeNetworkWhenStorageOwnerIsUnavailable() {
  const fixture = startupContext('initializeApp')
  let setupChecks = 0
  fixture.context.prepareStorageSession = async () => ({ owner: '' })
  fixture.context.checkSetup = async () => { setupChecks += 1; return true }

  await fixture.initializeApp()

  assert.equal(setupChecks, 0, 'startup must not mount or authenticate an ownerless storage session')
  assert.equal(fixture.context.authenticated.value, false)
  assert.match(fixture.context.startupError.value, /浏览器存储不可用/)
}

async function loginStopsBeforePersistingWhenStorageOwnerIsUnavailable() {
  const fixture = loginContext(async () => ({ authenticated: true, auth_required: true }))
  fixture.context.prepareStorageSession = async () => ({ owner: '' })

  await fixture.doLogin()

  assert.equal(fixture.storedKey, null, 'an ownerless login must not expose authenticated pages or persist the submitted key')
  assert.match(fixture.context.authError.value || fixture.context.startupError.value, /浏览器存储不可用/)
}

async function setupStopsBeforeAuthWhenStorageOwnerIsUnavailable() {
  const fixture = startupContext('onSetupDone')
  fixture.context.prepareStorageSession = async () => ({ owner: '' })

  await fixture.onSetupDone('generated-key')

  assert.equal(fixture.setupEvents.some(event => event.phase === 'auth'), false, 'ownerless setup completion must not authenticate or refresh')
  assert.equal(fixture.context.authenticated.value, false)
  assert.equal(fixture.context.needSetup.value, false, 'the saved backend setup should transition to the storage error login surface')
  assert.match(fixture.context.startupError.value, /浏览器存储不可用/)
}

async function externalStorageIdentityChangeInvalidatesCurrentEpoch() {
  let epoch = 3
  let invalidated = 0
  let stopped = 0
  const context = {
    SESSION_OWNER_KEY: 'autotoken_storage_session_owner_v1',
    authEpoch: epoch,
    authenticated: { value: true },
    authRequired: { value: false },
    needSetup: { value: false },
    authError: { value: 'old' },
    startupError: { value: '' },
    advanceAuthEpoch() { epoch += 1; return epoch },
    invalidateApiKeyMemory() { invalidated += 1 },
    stopPolling() { stopped += 1 },
  }
  const { handleExternalStorageChange } = installFunctions(['handleExternalStorageChange'], context)

  handleExternalStorageChange({ key: 'autotoken_api_key' })

  assert.equal(epoch, 4)
  assert.equal(invalidated, 1)
  assert.equal(stopped, 1)
  assert.equal(context.authenticated.value, false)
  assert.match(context.startupError.value, /其他标签页/)
}

const checks = [
  ['timeout retains the newly entered key', loginRetainsKeyOnTimeout],
  ['5xx retains the newly entered key', loginRetainsKeyOnServerFailure],
  ['401 clears the rejected key', loginClearsKeyOnConfirmedRejection],
  ['candidate auth precedes storage-owner rotation', loginAuthenticatesCandidateBeforeRotatingStorageOwner],
  ['rejected candidate preserves prior recoverable owner', rejectedCandidateDoesNotRotateOrDiscardPriorOwner],
  ['new key advances the auth epoch', loginStartsANewAuthEpoch],
  ['concurrent Enter cannot race storage ownership', loginRejectsConcurrentEnterSubmission],
  ['refresh rejection does not restart polling', refreshRejectionDoesNotRestartPolling],
  ['logout advances the auth epoch', logoutInvalidatesTheCurrentAuthEpoch],
  ['auth epoch change clears previous session state', authEpochChangeClearsPreviousSessionState],
  ['new-session timeout cannot fallback to prior-session state', newSessionTimeoutCannotFallbackToPriorSessionState],
  ['single-flight work is isolated by auth epoch', newEpochDoesNotJoinOldSingleFlight],
  ['stale auxiliary success cannot commit or restart polling', staleAuxiliarySuccessCannotCommitOrRestartPolling],
  ['stale auxiliary 401 cannot eject the new session', staleAuxiliary401CannotEjectNewSession],
  ['stale auth-check response cannot commit', staleAuthCheckCannotCommit],
  ['stale dashboard success cannot commit', staleDashboardSuccessCannotCommit],
  ['stale dashboard 401 cannot eject the new session', staleDashboard401CannotEjectNewSession],
  ['startup refresh rejection does not restart polling', initializationRefreshRejectionDoesNotRestartPolling],
  ['post-setup refresh rejection does not restart polling', setupRefreshRejectionDoesNotRestartPolling],
  ['post-setup generated key owns resumable storage before mount', setupBindsGeneratedKeyBeforeMountingAuthenticatedPages],
  ['startup refuses ownerless browser storage', initializationStopsBeforeNetworkWhenStorageOwnerIsUnavailable],
  ['login refuses ownerless browser storage', loginStopsBeforePersistingWhenStorageOwnerIsUnavailable],
  ['post-setup refuses ownerless browser storage', setupStopsBeforeAuthWhenStorageOwnerIsUnavailable],
  ['cross-tab identity change invalidates the current epoch', externalStorageIdentityChangeInvalidatesCurrentEpoch],
]

let failures = 0
for (const [name, check] of checks) {
  try {
    await check()
    console.log(`ok - ${name}`)
  } catch (error) {
    failures += 1
    console.error(`not ok - ${name}`)
    console.error(`  ${error.message}`)
  }
}

if (failures > 0) {
  throw new Error(`${failures} auth/session isolation regression(s) failed`)
}

console.log('auth/session isolation regressions passed')
