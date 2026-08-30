export function createMessageClearScheduler({
  setTimer = (callback, delayMs) => globalThis.setTimeout(callback, delayMs),
  clearTimer = timerId => globalThis.clearTimeout(timerId),
} = {}) {
  let timerId = null
  let revision = 0

  function cancel() {
    revision += 1
    if (timerId === null) return
    clearTimer(timerId)
    timerId = null
  }

  function schedule(delayMs, { read, clear, when = () => true } = {}) {
    if (typeof read !== 'function' || typeof clear !== 'function') {
      throw new TypeError('read and clear must be functions')
    }

    cancel()
    const expectedMessage = read()
    const scheduledRevision = revision
    timerId = setTimer(() => {
      timerId = null
      if (revision !== scheduledRevision) return
      if (read() !== expectedMessage || !when()) return
      clear()
    }, Math.max(0, Number(delayMs) || 0))
  }

  return {
    cancel,
    schedule,
    dispose: cancel,
  }
}
