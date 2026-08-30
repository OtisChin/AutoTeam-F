export const DEFAULT_REQUEST_TIMEOUT_MS = 20_000

export function createRequestTimeoutError(timeoutMs) {
  const error = new Error(`请求超时（${timeoutMs}ms）`)
  error.code = 'REQUEST_TIMEOUT'
  error.timeout = true
  return error
}

export async function fetchWithTimeout(
  input,
  init = {},
  { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, fetchImpl = globalThis.fetch } = {},
) {
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    return fetchImpl(input, init)
  }

  const controller = new AbortController()
  const timeoutError = createRequestTimeoutError(timeoutMs)
  const externalSignal = init.signal
  const abortFromExternal = () => controller.abort(externalSignal.reason)

  if (externalSignal?.aborted) {
    controller.abort(externalSignal.reason)
  } else {
    externalSignal?.addEventListener('abort', abortFromExternal, { once: true })
  }

  const timeoutId = setTimeout(() => controller.abort(timeoutError), timeoutMs)
  try {
    return await fetchImpl(input, { ...init, signal: controller.signal })
  } catch (error) {
    if (controller.signal.reason === timeoutError) throw timeoutError
    throw error
  } finally {
    clearTimeout(timeoutId)
    externalSignal?.removeEventListener('abort', abortFromExternal)
  }
}
