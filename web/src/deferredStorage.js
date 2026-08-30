import { SESSION_OWNER_KEY } from './sessionStorageScope.js'

function scheduleWhenIdle(callback) {
  if (typeof globalThis.requestIdleCallback === 'function') {
    return { type: 'idle', id: globalThis.requestIdleCallback(callback, { timeout: 500 }) }
  }
  return { type: 'timeout', id: globalThis.setTimeout(callback, 0) }
}

function cancelIdleSchedule(handle) {
  if (!handle) return
  if (handle.type === 'idle' && typeof globalThis.cancelIdleCallback === 'function') {
    globalThis.cancelIdleCallback(handle.id)
    return
  }
  globalThis.clearTimeout(handle.id)
}

export function createDeferredStorageWriter({
  storage = globalThis.localStorage,
  schedule = scheduleWhenIdle,
  cancelSchedule = cancelIdleSchedule,
  onError = (error, key) => console.error(`Failed to persist browser state for ${key}`, error),
} = {}) {
  const pendingWrites = new Map()
  let scheduledHandle = null
  let disposed = false
  let sessionOwner = null
  const sessionOwnerTracked = typeof storage?.getItem === 'function'
  try {
    if (sessionOwnerTracked) sessionOwner = storage.getItem(SESSION_OWNER_KEY)
  } catch {}

  function sessionIsCurrent() {
    if (!sessionOwnerTracked) return true
    try {
      return storage.getItem(SESSION_OWNER_KEY) === sessionOwner
    } catch {
      return false
    }
  }

  function drain() {
    const writes = [...pendingWrites.entries()]
    pendingWrites.clear()
    if (!sessionIsCurrent()) return
    for (const [key, write] of writes) {
      try {
        const value = typeof write.value === 'function' ? write.value() : write.value
        storage.setItem(key, write.serialize(value))
      } catch (error) {
        onError(error, key)
      }
    }
  }

  function scheduleDrain() {
    if (scheduledHandle !== null || disposed) return
    scheduledHandle = schedule(() => {
      scheduledHandle = null
      drain()
    })
  }

  function queue(key, value, serialize) {
    if (disposed) return
    pendingWrites.set(key, { value, serialize })
    scheduleDrain()
  }

  function queueJson(key, value) {
    queue(key, value, JSON.stringify)
  }

  function queueText(key, value) {
    queue(key, value, item => String(item ?? ''))
  }

  function writeNow(key, value, serialize) {
    pendingWrites.delete(key)
    if (!pendingWrites.size && scheduledHandle !== null) {
      cancelSchedule(scheduledHandle)
      scheduledHandle = null
    }
    if (!sessionIsCurrent()) return
    try {
      const resolved = typeof value === 'function' ? value() : value
      storage.setItem(key, serialize(resolved))
    } catch (error) {
      onError(error, key)
    }
  }

  function writeJsonNow(key, value) {
    writeNow(key, value, JSON.stringify)
  }

  function remove(key) {
    pendingWrites.delete(key)
    if (!sessionIsCurrent()) return
    try {
      storage.removeItem(key)
    } catch (error) {
      onError(error, key)
    }
  }

  function flush() {
    if (scheduledHandle !== null) {
      cancelSchedule(scheduledHandle)
      scheduledHandle = null
    }
    drain()
  }

  function dispose() {
    if (disposed) return
    flush()
    disposed = true
  }

  return { queueJson, queueText, writeJsonNow, remove, flush, dispose }
}
