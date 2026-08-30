import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const { createMessageClearScheduler } = await import(new URL('../src/messageLifecycle.js', import.meta.url))

let nextTimerId = 1
const timers = new Map()
const scheduler = createMessageClearScheduler({
  setTimer(callback) {
    const id = nextTimerId
    nextTimerId += 1
    timers.set(id, () => {
      timers.delete(id)
      callback()
    })
    return id
  },
  clearTimer(id) {
    timers.delete(id)
  },
})

let message = 'first'
const scheduleCurrent = (when = () => true) => scheduler.schedule(8_000, {
  read: () => message,
  clear: () => { message = '' },
  when,
})

scheduleCurrent()
assert.equal(timers.size, 1)
message = 'second'
scheduler.cancel()
assert.equal(timers.size, 0, 'a newer message should cancel the older clear timer')
assert.equal(message, 'second')

scheduleCurrent()
message = 'third'
for (const callback of [...timers.values()]) callback()
assert.equal(message, 'third', 'a stale callback must not clear text that changed after scheduling')

scheduleCurrent(() => false)
for (const callback of [...timers.values()]) callback()
assert.equal(message, 'third', 'a failed lifecycle predicate should preserve the current message')

scheduleCurrent()
scheduler.dispose()
assert.equal(timers.size, 0, 'component disposal should release the pending timer')

const dashboard = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')
assert.match(dashboard, /watch\(message,[\s\S]*messageClearScheduler\.cancel\(\)[\s\S]*flush:\s*'sync'/, 'every replacement message should synchronously invalidate the old timer')
assert.match(dashboard, /function scheduleMessageClear\(delayMs, when/, 'Dashboard should route message expiry through one scheduler')
assert.doesNotMatch(dashboard, /setTimeout\(\(\) => \{\s*message\.value = ''\s*\}/, 'Dashboard should not retain independent stale message-clear timers')

console.log('dashboard message lifecycle passed')
