export function shouldLoadDashboardAccounts(page) {
  return String(page || '') === 'dashboard'
}

export function createAccountLoadAbortError(message = '账号请求已取消') {
  if (typeof DOMException === 'function') {
    return new DOMException(message, 'AbortError')
  }
  const error = new Error(message)
  error.name = 'AbortError'
  error.code = 'ABORT_ERR'
  return error
}

export function isAccountLoadAbortError(error) {
  return error?.name === 'AbortError' || error?.code === 'ABORT_ERR'
}

function accountLoadErrorMessage(error) {
  const message = String(error?.message || '').trim()
  if (error?.timeout) return '账号池加载超时，请重试'
  return message ? `账号池加载失败：${message}` : '账号池加载失败，请重试'
}

export function createAccountLoadLifecycle({
  load,
  prepare = value => value,
  now = () => Date.now(),
  onChange = () => {},
  formatError = accountLoadErrorMessage,
  isNotModified = () => false,
  initialSnapshot = null,
  initialLastSuccessfulAt = null,
} = {}) {
  if (typeof load !== 'function') throw new TypeError('load must be a function')

  let active = null
  let state = {
    snapshot: initialSnapshot,
    loading: false,
    error: '',
    lastSuccessfulAt: initialLastSuccessfulAt,
  }

  function getState() {
    return { ...state }
  }

  function publish(patch = {}) {
    state = { ...state, ...patch }
    onChange(getState())
  }

  function abort(reason = createAccountLoadAbortError()) {
    if (!active) return false
    const record = active
    active = null
    record.cancelled = true
    if (!record.controller.signal.aborted) record.controller.abort(reason)
    if (state.loading) publish({ loading: false })
    return true
  }

  function loadOnce(key = 'default') {
    if (active?.key === key) return active.promise
    if (active) abort(createAccountLoadAbortError('账号请求已被新会话替代'))

    const controller = new AbortController()
    const record = { key, controller, cancelled: false, promise: null }
    active = record
    publish({ loading: true, error: '' })

    record.promise = Promise.resolve()
      .then(() => load({ key, signal: controller.signal }))
      .then(value => {
        if (record.cancelled || active !== record) return undefined
        if (isNotModified(value)) {
          publish({
            error: '',
            lastSuccessfulAt: now(),
          })
          return state.snapshot
        }
        const snapshot = prepare(value)
        publish({
          snapshot,
          error: '',
          lastSuccessfulAt: now(),
        })
        return snapshot
      })
      .catch(error => {
        if (record.cancelled || active !== record || isAccountLoadAbortError(error)) return undefined
        publish({ error: formatError(error) })
        throw error
      })
      .finally(() => {
        if (active !== record) return
        active = null
        if (state.loading) publish({ loading: false })
      })

    return record.promise
  }

  function reset({ snapshot = null, lastSuccessfulAt = null } = {}) {
    abort(createAccountLoadAbortError('账号会话已重置'))
    publish({
      snapshot,
      loading: false,
      error: '',
      lastSuccessfulAt,
    })
  }

  return {
    abort,
    getState,
    load: loadOnce,
    reset,
  }
}
