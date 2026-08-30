import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  SESSION_OWNER_KEY,
  clearStorageSession,
  createSessionStorageFacade,
  prepareStorageSession,
} from '../src/sessionStorageScope.js'
import { createDeferredStorageWriter } from '../src/deferredStorage.js'
import {
  commitStartAckSnapshot,
  reserveStartAckGeneration,
  startAckGenerationStorageKey,
} from '../src/startAckCas.js'

class MemoryStorage {
  constructor(entries = {}) {
    this.values = new Map(Object.entries(entries))
  }
  get length() { return this.values.size }
  key(index) { return [...this.values.keys()][index] ?? null }
  getItem(key) { return this.values.has(key) ? this.values.get(key) : null }
  setItem(key, value) { this.values.set(String(key), String(value)) }
  removeItem(key) { this.values.delete(String(key)) }
}

const storage = new MemoryStorage({
  autotoken_api_key: 'key-a',
  autotoken_current_page: 'paypal',
  autotoken_task_panel_position: '{"x":10,"y":20}',
  autotoken_us_paypal_access_token_pool: '["token-a"]',
  autotoken_us_paypal_protocol_ba_pool: '["BA-A"]',
  autotoken_us_paypal_job: '{"jobId":"job-a"}',
  autotoken_momo_vn_job: '{"jobId":"momo-a"}',
  unrelated_key: 'keep-me',
})

const first = await prepareStorageSession('key-a', { storage })
assert.equal(first.changed, false, 'adopting an unowned existing session should retain its resumable state')
assert.equal(storage.getItem('autotoken_us_paypal_job'), '{"jobId":"job-a"}')
const ownerA = storage.getItem(SESSION_OWNER_KEY)
assert.ok(ownerA && !ownerA.includes('key-a'), 'the stored owner must be an irreversible fingerprint, not the API key')

const same = await prepareStorageSession('key-a', { storage })
assert.equal(same.changed, false)
assert.equal(storage.getItem('autotoken_us_paypal_access_token_pool'), '["token-a"]')

const switched = await prepareStorageSession('key-b', { storage })
assert.equal(switched.changed, true, 'changing API-key identity should clear the previous operator state')
for (const key of [
  'autotoken_us_paypal_access_token_pool',
  'autotoken_us_paypal_protocol_ba_pool',
  'autotoken_us_paypal_job',
  'autotoken_momo_vn_job',
]) {
  assert.equal(storage.getItem(key), null, `${key} must not cross an API-key boundary`)
}
assert.equal(storage.getItem('autotoken_current_page'), 'paypal', 'non-sensitive navigation preference may survive')
assert.equal(storage.getItem('autotoken_task_panel_position'), '{"x":10,"y":20}', 'non-sensitive layout preference may survive')
assert.equal(storage.getItem('unrelated_key'), 'keep-me', 'the cleanup must not touch other applications')
assert.notEqual(storage.getItem(SESSION_OWNER_KEY), ownerA)

storage.setItem('autotoken_us_paypal_pay153_job', '{"jobId":"job-b"}')
const lateWriter = createDeferredStorageWriter({
  storage,
  schedule: () => ({ type: 'test', id: 1 }),
  cancelSchedule: () => {},
})
clearStorageSession({ storage })
assert.equal(storage.getItem('autotoken_us_paypal_pay153_job'), null, 'logout should clear state written during component unmount')
assert.equal(storage.getItem(SESSION_OWNER_KEY), 'logged-out', 'logout should leave a tombstone so the next login re-clears late writes')
assert.equal(storage.getItem('autotoken_current_page'), 'paypal')
lateWriter.writeJsonNow('autotoken_us_paypal_pay153_job', { jobId: 'late-job-b' })
assert.equal(storage.getItem('autotoken_us_paypal_pay153_job'), null, 'an in-flight callback from the unmounted session must not write after logout')

storage.setItem('autotoken_us_paypal_job', '{"jobId":"late-direct-write"}')
await prepareStorageSession('key-c', { storage })
assert.equal(storage.getItem('autotoken_us_paypal_job'), null, 'the next owner must re-clear any direct late write after the logout tombstone')
const oldFacade = createSessionStorageFacade({ storage })
const coldOwner = storage.getItem(SESSION_OWNER_KEY)
await prepareStorageSession('key-c', { storage })
assert.equal(storage.getItem(SESSION_OWNER_KEY), coldOwner, 'a cold reload with the same key should retain the resumable session owner')
await prepareStorageSession('key-c', { storage, rotate: true })
assert.notEqual(storage.getItem(SESSION_OWNER_KEY), coldOwner, 'an explicit login must rotate the owner even when the API key is unchanged')
oldFacade.setItem('autotoken_momo_vn_job', '{"jobId":"stale-momo"}')
assert.equal(storage.getItem('autotoken_momo_vn_job'), null, 'a direct writer captured by the old owner must be fenced after a same-key re-login')
storage.setItem('autotoken_momo_vn_job', '{"jobId":"new-momo"}')
oldFacade.removeItem('autotoken_momo_vn_job')
assert.equal(storage.getItem('autotoken_momo_vn_job'), '{"jobId":"new-momo"}', 'an old owner must not delete new-session state')

let resolveOldIdealPost
const oldIdealPostFacade = createSessionStorageFacade({ storage })
const oldIdealPost = new Promise(resolve => { resolveOldIdealPost = resolve }).then((job) => {
  oldIdealPostFacade.setItem('autotoken_ideal_active_job_v1', JSON.stringify(job))
})
await prepareStorageSession('key-e', { storage })
storage.setItem('autotoken_ideal_active_job_v1', '{"jobId":"new-owner-job"}')
resolveOldIdealPost({ jobId: 'old-owner-late-job' })
await oldIdealPost
assert.equal(
  storage.getItem('autotoken_ideal_active_job_v1'),
  '{"jobId":"new-owner-job"}',
  'an old pending iDEAL POST must not persist its late job into the new session owner',
)

function jsonValue(storage, key) {
  return JSON.parse(storage.getItem(key) || '{}')
}

function scopedValue(storage, key, scopeKey) {
  const root = jsonValue(storage, key)
  return scopeKey ? root[scopeKey] : root
}

function jobIds(snapshot) {
  if (Array.isArray(snapshot?.jobIds)) return snapshot.jobIds
  return snapshot?.jobId ? [snapshot.jobId] : []
}

function replaceSnapshot(mode, jobId) {
  return () => ({
    jobId,
    jobIds: [jobId],
    mode,
    status: 'queued',
    accountCount: 1,
  })
}

function appendSnapshot(mode, jobId) {
  return current => {
    const nextIds = [...jobIds(current)]
    if (!nextIds.includes(jobId)) nextIds.push(jobId)
    return {
      ...current,
      jobId: nextIds[0],
      jobIds: nextIds,
      mode,
      status: 'queued',
      accountCount: Number(current?.accountCount || 0) + 1,
    }
  }
}

function assertStartAckLifecycle({
  page,
  storageKey,
  scopeKey = '',
  seed = {},
  otherStorage = {},
  createSnapshot,
  expectedOldIds,
  expectedNewIds,
  assertIsolation = () => {},
}) {
  const makeStorage = () => new MemoryStorage({
    [SESSION_OWNER_KEY]: 'same-session#start-ack-tests',
    [storageKey]: JSON.stringify(seed),
    ...otherStorage,
  })

  const supersededStorage = makeStorage()
  const supersededFacade = createSessionStorageFacade({ storage: supersededStorage })
  const oldReservation = reserveStartAckGeneration({
    storage: supersededFacade,
    storageKey,
    scopeKey,
    generation: `${page}:old`,
  })
  const newReservation = reserveStartAckGeneration({
    storage: supersededFacade,
    storageKey,
    scopeKey,
    generation: `${page}:new`,
    supersede: true,
  })
  const oldAck = commitStartAckSnapshot(oldReservation, {
    componentUnmounted: true,
    createSnapshot: createSnapshot('old-job'),
  })
  assert.equal(oldAck.status, 'superseded', `${page}: a successor generation must fence the old ACK`)
  const newAck = commitStartAckSnapshot(newReservation, {
    componentUnmounted: false,
    createSnapshot: createSnapshot('new-job'),
  })
  assert.equal(newAck.status, 'active', `${page}: the current generation must accept its ACK`)
  assert.deepEqual(jobIds(scopedValue(supersededStorage, storageKey, scopeKey)), expectedNewIds, `${page}: the old ACK must not overwrite the successor job`)
  assertIsolation(supersededStorage)

  const orphanStorage = makeStorage()
  const orphanFacade = createSessionStorageFacade({ storage: orphanStorage })
  const orphanReservation = reserveStartAckGeneration({
    storage: orphanFacade,
    storageKey,
    scopeKey,
    generation: `${page}:orphan`,
  })
  const orphanAck = commitStartAckSnapshot(orphanReservation, {
    componentUnmounted: true,
    createSnapshot: createSnapshot('old-job'),
  })
  let uiUpdates = 0
  let pollStarts = 0
  if (orphanAck.shouldContinue) {
    uiUpdates += 1
    pollStarts += 1
  }
  assert.equal(orphanAck.status, 'persisted', `${page}: an unmounted ACK without a successor must remain recoverable`)
  assert.deepEqual(jobIds(scopedValue(orphanStorage, storageKey, scopeKey)), expectedOldIds, `${page}: the orphan-prone ACK must be persisted for re-entry recovery`)
  assert.equal(uiUpdates, 0, `${page}: an unmounted instance must not update UI after persisting its ACK`)
  assert.equal(pollStarts, 0, `${page}: an unmounted instance must not start polling after persisting its ACK`)
  assertIsolation(orphanStorage)
}

for (const scopeKey of ['extract', 'tempExtract']) {
  const otherScope = scopeKey === 'extract' ? 'tempExtract' : 'extract'
  assertStartAckLifecycle({
    page: `BrazilPixPage.vue/${scopeKey}`,
    storageKey: 'autotoken_brazil_pix_tasks',
    scopeKey,
    seed: {
      extract: { jobId: 'existing-extract', mode: 'extract' },
      tempExtract: { jobId: 'existing-temp', mode: 'temp' },
    },
    createSnapshot: jobId => replaceSnapshot(scopeKey === 'tempExtract' ? 'temp' : 'extract', jobId),
    expectedOldIds: ['old-job'],
    expectedNewIds: ['new-job'],
    assertIsolation: scenarioStorage => {
      const expectedOther = otherScope === 'extract' ? 'existing-extract' : 'existing-temp'
      assert.equal(scopedValue(scenarioStorage, 'autotoken_brazil_pix_tasks', otherScope).jobId, expectedOther, 'Brazil task-map CAS must not overwrite the other mode')
    },
  })
}

for (const mode of ['extract', 'tempExtract']) {
  assertStartAckLifecycle({
    page: `IndiaUpiPage.vue/${mode}`,
    storageKey: 'autotoken_india_upi_job',
    seed: { jobId: 'existing-india', mode: mode === 'extract' ? 'tempExtract' : 'extract' },
    createSnapshot: jobId => replaceSnapshot(mode, jobId),
    expectedOldIds: ['old-job'],
    expectedNewIds: ['new-job'],
  })
}

for (const [page, storageKey] of [
  ['GCashPhPage.vue', 'autotoken_gcash_ph_job'],
  ['MomoPage.vue', 'autotoken_momo_vn_job'],
]) {
  assertStartAckLifecycle({
    page,
    storageKey,
    createSnapshot: jobId => replaceSnapshot('extract', jobId),
    expectedOldIds: ['old-job'],
    expectedNewIds: ['new-job'],
  })
}

{
  const storageKey = 'autotoken_gcash_ph_job'
  const ownerStorage = new MemoryStorage({ [SESSION_OWNER_KEY]: 'old-owner' })
  const oldOwnerFacade = createSessionStorageFacade({ storage: ownerStorage })
  const reservation = reserveStartAckGeneration({
    storage: oldOwnerFacade,
    storageKey,
    generation: 'gcash:old-owner',
  })
  ownerStorage.setItem(SESSION_OWNER_KEY, 'new-owner')
  ownerStorage.setItem(storageKey, JSON.stringify({ jobId: 'new-owner-job' }))
  const lateAck = commitStartAckSnapshot(reservation, {
    componentUnmounted: true,
    createSnapshot: replaceSnapshot('extract', 'old-owner-job'),
  })
  assert.equal(lateAck.status, 'superseded', 'a start ACK from a prior session owner must be fenced')
  assert.equal(jsonValue(ownerStorage, storageKey).jobId, 'new-owner-job', 'an old-owner ACK must not overwrite the new session job')
}

{
  const storageKey = 'autotoken_brazil_pix_tasks'
  const concurrentStorage = new MemoryStorage({
    [SESSION_OWNER_KEY]: 'same-session#brazil-interleave',
    [storageKey]: JSON.stringify({
      extract: {},
      tempExtract: { jobId: 'temp-running', completed: 0 },
    }),
  })
  const facade = createSessionStorageFacade({ storage: concurrentStorage })
  const reservation = reserveStartAckGeneration({
    storage: facade,
    storageKey,
    scopeKey: 'extract',
    generation: 'brazil:extract:pending',
  })
  const sidecarKey = startAckGenerationStorageKey(storageKey, 'extract')
  assert.equal(jsonValue(concurrentStorage, storageKey).extract.startGeneration, undefined, 'Brazil start generation must not share the task-map payload')
  assert.equal(concurrentStorage.getItem(sidecarKey), 'brazil:extract:pending')
  facade.setItem(storageKey, JSON.stringify({
    extract: {},
    tempExtract: { jobId: 'temp-running', completed: 1 },
  }))
  const ack = commitStartAckSnapshot(reservation, {
    createSnapshot: replaceSnapshot('extract', 'extract-new'),
  })
  assert.equal(ack.status, 'active', 'a concurrent Brazil temp-task snapshot must not erase the extract start reservation')
  assert.deepEqual(jobIds(scopedValue(concurrentStorage, storageKey, 'extract')), ['extract-new'])
  assert.equal(scopedValue(concurrentStorage, storageKey, 'tempExtract').completed, 1, 'Brazil CAS must merge the newest other-scope snapshot')
  assert.equal(concurrentStorage.getItem(sidecarKey), null, 'an accepted Brazil ACK must consume its sidecar generation')
}

{
  const storageKey = 'autotoken_kakao_pay_job'
  const concurrentStorage = new MemoryStorage({
    [SESSION_OWNER_KEY]: 'same-session#kakao-interleave',
    [storageKey]: JSON.stringify({ jobId: 'existing', jobIds: ['existing'], status: 'running', completed: 0, accountCount: 1 }),
  })
  const facade = createSessionStorageFacade({ storage: concurrentStorage })
  const reservation = reserveStartAckGeneration({
    storage: facade,
    storageKey,
    generation: 'kakao:append:pending',
  })
  const sidecarKey = startAckGenerationStorageKey(storageKey)
  facade.setItem(storageKey, JSON.stringify({ jobId: 'existing', jobIds: ['existing'], status: 'running', completed: 1, accountCount: 1 }))
  const ack = commitStartAckSnapshot(reservation, {
    createSnapshot: appendSnapshot('extract', 'append-new'),
  })
  assert.equal(ack.status, 'active', 'a Kakao active-job poll snapshot must not erase an append start reservation')
  assert.deepEqual(jobIds(jsonValue(concurrentStorage, storageKey)), ['existing', 'append-new'])
  assert.equal(jsonValue(concurrentStorage, storageKey).completed, 1, 'Kakao append CAS must merge the newest poll snapshot')
  assert.equal(concurrentStorage.getItem(sidecarKey), null, 'an accepted Kakao append ACK must consume its sidecar generation')
}

for (const mode of ['extract', 'tempExtract']) {
  const storageKey = mode === 'tempExtract' ? 'autotoken_kakao_pay_temp_job' : 'autotoken_kakao_pay_job'
  const otherKey = mode === 'tempExtract' ? 'autotoken_kakao_pay_job' : 'autotoken_kakao_pay_temp_job'
  assertStartAckLifecycle({
    page: `KakaoPayPage.vue/${mode}/append`,
    storageKey,
    seed: { jobId: 'existing-kakao', jobIds: ['existing-kakao'], mode, status: 'running', accountCount: 2 },
    otherStorage: { [otherKey]: JSON.stringify({ jobId: 'other-mode-job', jobIds: ['other-mode-job'], mode: mode === 'tempExtract' ? 'extract' : 'tempExtract' }) },
    createSnapshot: jobId => appendSnapshot(mode, jobId),
    expectedOldIds: ['existing-kakao', 'old-job'],
    expectedNewIds: ['existing-kakao', 'new-job'],
    assertIsolation: scenarioStorage => {
      assert.deepEqual(jobIds(jsonValue(scenarioStorage, otherKey)), ['other-mode-job'], 'Kakao start ACK CAS must not overwrite the other mode')
    },
  })
}

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const app = fs.readFileSync(path.join(root, 'src', 'App.vue'), 'utf8')
assert.match(app, /async function doLogout\(\)[\s\S]*?authenticated\.value = false[\s\S]*?await nextTick\(\)[\s\S]*?clearStorageSession/, 'logout must clear after child components finish their forced unmount writes')
assert.match(app, /async function doLogin\(\)[\s\S]*?if \(authLoading\.value\) return[\s\S]*?prepareStorageSession\(submittedKey, \{ rotate: true \}\)/, 'explicit login must be single-flight and rotate storage ownership before mounting the new operator pages')
assert.match(app, /async function initializeApp\(\)[\s\S]*?prepareStorageSession\(/, 'startup must bind persisted state to the stored API-key identity')
assert.match(app, /async function onSetupDone\([^)]*\)[\s\S]*?prepareStorageSession\(setupKey, \{ rotate: true \}\)[\s\S]*?needSetup\.value = false/, 'setup completion must bind the generated API key before mounting resumable operator pages')

for (const file of [
  'BindCard.vue',
  'BrazilPixPage.vue',
  'Dashboard.vue',
  'GCashPhPage.vue',
  'IdealLinkPage.vue',
  'IndiaUpiPage.vue',
  'KakaoPayPage.vue',
  'MomoPage.vue',
  'RegisterAccountPage.vue',
  'TeamMembers.vue',
  'UsPaypalPage.vue',
]) {
  const source = fs.readFileSync(path.join(root, 'src', 'components', file), 'utf8')
  assert.match(source, /createSessionStorageFacade/, `${file} should fence direct sensitive writes by session owner`)
  assert.doesNotMatch(source, /(?:window\.)?localStorage\.(?:getItem|setItem|removeItem)/, `${file} should not bypass its owner-fenced storage facade`)
}
for (const file of ['BrazilPixPage.vue', 'IndiaUpiPage.vue', 'KakaoPayPage.vue', 'GCashPhPage.vue', 'MomoPage.vue']) {
  const source = fs.readFileSync(path.join(root, 'src', 'components', file), 'utf8')
  assert.match(source, /reserveStartAckGeneration/, `${file} must reserve a same-session start generation before awaiting its start ACK`)
  assert.match(source, /commitStartAckSnapshot/, `${file} must CAS the returned job snapshot against its start generation`)
  assert.match(source, /if \(!startAck\.shouldContinue\) return/, `${file} must persist-but-stop or skip a late ACK before touching unmounted UI or polling`)
}

console.log('storage session isolation tests passed: same owner retained; key switch and post-unmount logout cleared sensitive autotoken state')
