import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSessionStorageFacade, SESSION_OWNER_KEY } from '../src/sessionStorageScope.js'

const startAck = await import('../src/startAckCas.js')

assert.equal(typeof startAck.readStartAckCheckpoint, 'function', 'start ACK checkpoints must be readable by a remounted page')
assert.equal(typeof startAck.watchStartAckGeneration, 'function', 'a remounted page must be notified when the old instance receives its ACK')
assert.equal(typeof startAck.markStartAckGenerationUnknown, 'function', 'ambiguous start failures must retain a non-retryable checkpoint')

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

function replaceSnapshot(jobId) {
  return () => ({ jobId, status: 'queued', accountCount: 2 })
}

{
  const rawStorage = new MemoryStorage({ [SESSION_OWNER_KEY]: 'same-owner#remount' })
  const oldPageStorage = createSessionStorageFacade({ storage: rawStorage })
  const newPageStorage = createSessionStorageFacade({ storage: rawStorage })
  const storageKey = 'autotoken_gcash_ph_job'

  const oldRequest = startAck.reserveStartAckGeneration({
    storage: oldPageStorage,
    storageKey,
    generation: 'gcash-generation-1',
    clientRequestId: 'gcash-request-1',
    now: 1_700_000_000_000,
    checkpoint: { mode: 'extract', accountCount: 2, actionText: '提取' },
  })
  assert.equal(oldRequest.status, 'reserved')
  assert.equal(oldRequest.clientRequestId, 'gcash-request-1')
  assert.deepEqual(startAck.readStartAckCheckpoint({ storage: newPageStorage, storageKey }), {
    version: 1,
    status: 'starting',
    generation: 'gcash-generation-1',
    clientRequestId: 'gcash-request-1',
    startedAt: 1_700_000_000_000,
    mode: 'extract',
    accountCount: 2,
    actionText: '提取',
  }, 'the remounted page must see the pre-POST checkpoint before any job ID exists')

  const duplicate = startAck.reserveStartAckGeneration({
    storage: newPageStorage,
    storageKey,
    generation: 'gcash-generation-2',
    clientRequestId: 'gcash-request-2',
  })
  assert.equal(duplicate.status, 'occupied', 'a remounted page must not supersede an in-flight start request')
  assert.equal(duplicate.checkpoint.clientRequestId, 'gcash-request-1')

  const events = []
  const watcher = startAck.watchStartAckGeneration({
    storage: newPageStorage,
    storageKey,
    onChange: event => events.push(event),
  })
  assert.equal(watcher.checkpoint.clientRequestId, 'gcash-request-1')

  const lateAck = startAck.commitStartAckSnapshot(oldRequest, {
    componentUnmounted: true,
    createSnapshot: replaceSnapshot('gcash-job-1'),
  })
  assert.equal(lateAck.status, 'persisted')
  assert.equal(events.length, 1, 'the live remount must receive the old instance late ACK')
  assert.equal(events[0].type, 'acknowledged')
  assert.equal(events[0].snapshot.jobId, 'gcash-job-1')
  assert.equal(startAck.readStartAckCheckpoint({ storage: newPageStorage, storageKey }), null)
  assert.equal(JSON.parse(rawStorage.getItem(storageKey)).jobId, 'gcash-job-1')
  watcher.unsubscribe()
}

{
  const rawStorage = new MemoryStorage({ [SESSION_OWNER_KEY]: 'same-owner#failure' })
  const oldPageStorage = createSessionStorageFacade({ storage: rawStorage })
  const newPageStorage = createSessionStorageFacade({ storage: rawStorage })
  const storageKey = 'autotoken_momo_vn_job'
  const events = []
  const request = startAck.reserveStartAckGeneration({
    storage: oldPageStorage,
    storageKey,
    generation: 'momo-generation-1',
    clientRequestId: 'momo-request-1',
  })
  const watcher = startAck.watchStartAckGeneration({ storage: newPageStorage, storageKey, onChange: event => events.push(event) })

  const unknown = startAck.markStartAckGenerationUnknown(request, {
    componentUnmounted: true,
    error: '请求超时（20000ms）',
    now: 1_700_000_020_000,
  })
  assert.equal(unknown.status, 'unknown')
  assert.equal(events.at(-1).type, 'unknown')
  assert.equal(startAck.readStartAckCheckpoint({ storage: newPageStorage, storageKey }).status, 'unknown')
  assert.equal(startAck.reserveStartAckGeneration({ storage: newPageStorage, storageKey }).status, 'occupied', 'unknown remote outcomes must remain fenced from automatic resubmission')

  const cancelled = startAck.cancelStartAckGeneration(request, {
    componentUnmounted: true,
    error: 'definitive validation failure',
  })
  assert.equal(cancelled.status, 'cancelled')
  assert.equal(events.at(-1).type, 'cancelled')
  assert.equal(startAck.readStartAckCheckpoint({ storage: newPageStorage, storageKey }), null)
  watcher.unsubscribe()
}

{
  const rawStorage = new MemoryStorage({ [SESSION_OWNER_KEY]: 'old-owner#late' })
  const oldPageStorage = createSessionStorageFacade({ storage: rawStorage })
  const request = startAck.reserveStartAckGeneration({
    storage: oldPageStorage,
    storageKey: 'autotoken_india_upi_job',
    generation: 'india-old-owner',
  })
  rawStorage.setItem(SESSION_OWNER_KEY, 'new-owner#current')
  rawStorage.removeItem(startAck.startAckCheckpointStorageKey('autotoken_india_upi_job'))
  rawStorage.removeItem(startAck.startAckGenerationStorageKey('autotoken_india_upi_job'))
  const newPageStorage = createSessionStorageFacade({ storage: rawStorage })
  const events = []
  const watcher = startAck.watchStartAckGeneration({
    storage: newPageStorage,
    storageKey: 'autotoken_india_upi_job',
    onChange: event => events.push(event),
  })
  const lateAck = startAck.commitStartAckSnapshot(request, {
    componentUnmounted: true,
    createSnapshot: replaceSnapshot('old-owner-job'),
  })
  assert.equal(lateAck.status, 'superseded')
  assert.deepEqual(events, [], 'an ACK fenced by a session-owner change must not notify the new operator')
  watcher.unsubscribe()
}

function component(name) {
  return readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
}

for (const name of ['BrazilPixPage.vue', 'IndiaUpiPage.vue', 'KakaoPayPage.vue', 'GCashPhPage.vue', 'MomoPage.vue']) {
  const source = component(name)
  assert.match(source, /watchStartAckGeneration/, `${name} must subscribe to ACK resolution after remount`)
  assert.match(source, /checkpoint:\s*\{[\s\S]{0,500}?accountCount:/, `${name} must persist a starting checkpoint before awaiting POST`)
  assert.match(source, /clientRequestId:\s*startReservation\.clientRequestId/, `${name} must carry the checkpoint request identity into the POST and final snapshot`)
  assert.match(source, /startAckWatcher[\s\S]*?unsubscribe\(\)/, `${name} must dispose its remount subscription`)
}

console.log('start ACK remount recovery tests passed')
