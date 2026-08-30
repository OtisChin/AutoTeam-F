export function createSingleFlight(run, { key: getKey = null } = {}) {
  let active = null
  const activeByKey = typeof getKey === 'function' ? new Map() : null

  return function singleFlight(...args) {
    const flightKey = activeByKey ? getKey(...args) : null
    const existing = activeByKey ? activeByKey.get(flightKey) : active
    if (existing) return existing

    let result
    try {
      result = run(...args)
    } catch (error) {
      return Promise.reject(error)
    }

    const current = Promise.resolve(result).finally(() => {
      if (activeByKey) {
        if (activeByKey.get(flightKey) === current) activeByKey.delete(flightKey)
      } else if (active === current) {
        active = null
      }
    })
    if (activeByKey) activeByKey.set(flightKey, current)
    else active = current
    return current
  }
}

export function createRafThrottle(callback, schedule = requestAnimationFrame, cancelSchedule = cancelAnimationFrame) {
  let frameId = null
  let latestArgs = null
  let latestThis = null

  function invoke() {
    frameId = null
    const args = latestArgs
    const context = latestThis
    latestArgs = null
    latestThis = null
    if (args) callback.apply(context, args)
  }

  function throttled(...args) {
    latestArgs = args
    latestThis = this
    if (frameId === null) frameId = schedule(invoke)
  }

  throttled.flush = () => {
    if (frameId === null) return
    cancelSchedule(frameId)
    invoke()
  }

  throttled.cancel = () => {
    if (frameId !== null) cancelSchedule(frameId)
    frameId = null
    latestArgs = null
    latestThis = null
  }

  return throttled
}
