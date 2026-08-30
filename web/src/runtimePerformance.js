export function createSingleFlight(run) {
  let active = null

  return function singleFlight(...args) {
    if (active) return active

    let result
    try {
      result = run(...args)
    } catch (error) {
      return Promise.reject(error)
    }

    const current = Promise.resolve(result).finally(() => {
      if (active === current) active = null
    })
    active = current
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
