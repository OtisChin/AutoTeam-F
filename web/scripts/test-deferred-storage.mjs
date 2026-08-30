import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const moduleUrl = new URL('../src/deferredStorage.js', import.meta.url)
let deferredStorage
try {
  deferredStorage = await import(moduleUrl)
} catch {
  deferredStorage = null
}

assert.ok(deferredStorage?.createDeferredStorageWriter, 'deferred storage writer should exist')

function fakeScheduler() {
  let nextId = 1
  const callbacks = new Map()
  return {
    callbacks,
    schedule(callback) {
      const id = nextId++
      callbacks.set(id, callback)
      return id
    },
    cancel(id) {
      callbacks.delete(id)
    },
    runNext() {
      const [id, callback] = callbacks.entries().next().value || []
      if (!callback) return
      callbacks.delete(id)
      callback()
    },
  }
}

{
  const scheduler = fakeScheduler()
  const writes = []
  const storage = {
    setItem: (key, value) => writes.push([key, value]),
    removeItem: key => writes.push([key, null]),
  }
  const writer = deferredStorage.createDeferredStorageWriter({
    storage,
    schedule: scheduler.schedule,
    cancelSchedule: scheduler.cancel,
  })

  let value = { count: 1 }
  writer.queueJson('state', () => value)
  value = { count: 2 }
  writer.queueJson('state', () => value)

  assert.equal(writes.length, 0, 'queued serialization must not block the current interaction')
  assert.equal(scheduler.callbacks.size, 1, 'updates to one key should coalesce into one idle callback')

  scheduler.runNext()
  assert.deepEqual(writes, [['state', '{"count":2}']], 'the idle write should persist only the latest state')

  writer.queueJson('state', () => ({ stale: true }))
  writer.remove('state')
  scheduler.runNext()
  assert.deepEqual(writes.at(-1), ['state', null], 'removing a key must cancel its queued stale write')

  writer.queueText('tab', () => 'payment')
  writer.dispose()
  assert.deepEqual(writes.at(-1), ['tab', 'payment'], 'dispose should flush pending state before teardown')

  assert.equal(typeof writer.writeJsonNow, 'function', 'critical late state should have an explicit synchronous persistence path')
  writer.writeJsonNow('late-job', { jobId: 'job-after-unmount' })
  assert.deepEqual(
    writes.at(-1),
    ['late-job', '{"jobId":"job-after-unmount"}'],
    'an acknowledged job ID must remain persistable after the deferred writer is disposed',
  )
}

for (const file of ['UsPaypalPage.vue', 'KakaoPayPage.vue', 'IndiaUpiPage.vue', 'BrazilPixPage.vue']) {
  const source = readFileSync(new URL(`../src/components/${file}`, import.meta.url), 'utf8')
  assert.match(source, /createDeferredStorageWriter/, `${file} should defer large browser-storage writes`)
  assert.match(source, /storageWriter\.queueJson/, `${file} should coalesce serialized state writes`)
  assert.match(source, /storageWriter\.dispose\(\)/, `${file} should flush deferred state during teardown`)
}

console.log('deferred storage regression tests passed')
