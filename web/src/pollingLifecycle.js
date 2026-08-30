export function createPollingLifecycle({
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
  documentTarget = globalThis.document,
  windowTarget = globalThis.window,
  getOnline = () => globalThis.navigator?.onLine !== false,
} = {}) {
  let generation = 0
  let disposed = false
  const pendingWaits = new Set()

  function settlePendingWaits() {
    generation += 1
    for (const pending of [...pendingWaits]) {
      if (pending.timerId !== null) clearTimer(pending.timerId)
      pending.settle(false)
    }
  }

  function start() {
    if (disposed) return null
    settlePendingWaits()
    return generation
  }

  function isActive(token) {
    return !disposed && token !== null && token === generation
  }

  function wait(delayMs, token) {
    if (!isActive(token)) return Promise.resolve(false)

    return new Promise(resolve => {
      const pending = {
        timerId: null,
        cleanup: null,
        settle(value) {
          if (!pendingWaits.delete(pending)) return
          pending.cleanup?.()
          resolve(value)
        },
      }
      pending.timerId = setTimer(() => pending.settle(isActive(token)), delayMs)
      pendingWaits.add(pending)
    })
  }

  function pageAvailable() {
    const hidden = documentTarget?.visibilityState === 'hidden' || documentTarget?.hidden === true
    return !hidden && getOnline()
  }

  function waitUntilAvailable(token) {
    if (!isActive(token)) return Promise.resolve(false)
    if (pageAvailable()) return Promise.resolve(true)

    return new Promise(resolve => {
      const check = () => {
        if (!isActive(token)) {
          pending.settle(false)
        } else if (pageAvailable()) {
          pending.settle(true)
        }
      }
      const pending = {
        timerId: null,
        cleanup() {
          documentTarget?.removeEventListener?.('visibilitychange', check)
          windowTarget?.removeEventListener?.('online', check)
        },
        settle(value) {
          if (!pendingWaits.delete(pending)) return
          pending.cleanup()
          resolve(value)
        },
      }
      pendingWaits.add(pending)
      documentTarget?.addEventListener?.('visibilitychange', check)
      windowTarget?.addEventListener?.('online', check)
    })
  }

  function cancel() {
    if (disposed) return
    settlePendingWaits()
  }

  function dispose() {
    disposed = true
    settlePendingWaits()
  }

  return { start, isActive, wait, waitUntilAvailable, cancel, dispose }
}

export function createSharedPollingGate({
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
  documentTarget = globalThis.document,
  windowTarget = globalThis.window,
  getOnline = () => globalThis.navigator?.onLine !== false,
} = {}) {
  let disposed = false
  let listeningForAvailability = false
  const delayedWaits = new Set()
  const availabilityWaiters = new Set()

  function pageAvailable() {
    const hidden = documentTarget?.visibilityState === 'hidden' || documentTarget?.hidden === true
    return !hidden && getOnline()
  }

  function stopAvailabilityListeners() {
    if (!listeningForAvailability) return
    listeningForAvailability = false
    documentTarget?.removeEventListener?.('visibilitychange', checkAvailability)
    windowTarget?.removeEventListener?.('online', checkAvailability)
  }

  function settleAvailabilityWaiters(value) {
    const waiters = [...availabilityWaiters]
    availabilityWaiters.clear()
    stopAvailabilityListeners()
    for (const resolve of waiters) resolve(value)
  }

  function checkAvailability() {
    if (disposed) settleAvailabilityWaiters(false)
    else if (pageAvailable()) settleAvailabilityWaiters(true)
  }

  function waitUntilAvailable() {
    if (disposed) return Promise.resolve(false)
    if (pageAvailable()) return Promise.resolve(true)

    return new Promise(resolve => {
      availabilityWaiters.add(resolve)
      if (listeningForAvailability) return
      listeningForAvailability = true
      documentTarget?.addEventListener?.('visibilitychange', checkAvailability)
      windowTarget?.addEventListener?.('online', checkAvailability)
    })
  }

  function wait(delayMs) {
    if (disposed) return Promise.resolve(false)
    if (!Number.isFinite(delayMs) || delayMs <= 0) return Promise.resolve(true)

    return new Promise(resolve => {
      const pending = {
        timerId: null,
        settle(value) {
          if (!delayedWaits.delete(pending)) return
          if (pending.timerId !== null) clearTimer(pending.timerId)
          pending.timerId = null
          resolve(value)
        },
      }
      pending.timerId = setTimer(() => pending.settle(!disposed), delayMs)
      delayedWaits.add(pending)
    })
  }

  function dispose() {
    if (disposed) return
    disposed = true
    for (const pending of [...delayedWaits]) pending.settle(false)
    settleAvailabilityWaiters(false)
  }

  return { wait, waitUntilAvailable, dispose }
}
