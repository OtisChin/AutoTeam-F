export const MAX_POLLING_RETRY_DELAY_MS = 15_000
export const MAX_POLLING_TRANSIENT_FAILURES = 5
const RETRYABLE_POLLING_HTTP_STATUSES = new Set([408, 425, 429])

export function pollingRetryDelayMs(attempt, { baseMs = 1_000, maxMs = MAX_POLLING_RETRY_DELAY_MS } = {}) {
  const retryAttempt = Math.max(1, Math.trunc(Number(attempt) || 1))
  const exponent = Math.min(30, retryAttempt - 1)
  return Math.min(Math.max(1, Number(maxMs) || MAX_POLLING_RETRY_DELAY_MS), Math.max(1, Number(baseMs) || 1_000) * (2 ** exponent))
}

export function isMissingPollingJob(error) {
  return Number(error?.status || 0) === 404
}

export function isPermanentPollingError(error) {
  const status = Number(error?.status || 0)
  return status >= 400
    && status < 500
    && !RETRYABLE_POLLING_HTTP_STATUSES.has(status)
    && !isMissingPollingJob(error)
}

export function isTransientPollingError(error) {
  return !isMissingPollingJob(error) && !isPermanentPollingError(error)
}

export async function readPollingSnapshot({
  request,
  wait,
  attempt = 0,
  maxAttempts = MAX_POLLING_TRANSIENT_FAILURES,
  onTransientError = null,
} = {}) {
  try {
    return { kind: 'snapshot', value: await request(), attempt: 0, delayMs: 0 }
  } catch (error) {
    if (isMissingPollingJob(error)) return { kind: 'missing', error, attempt, delayMs: 0 }
    if (isPermanentPollingError(error)) return { kind: 'permanent', error, attempt, delayMs: 0 }
    const nextAttempt = Math.max(0, Math.trunc(Number(attempt) || 0)) + 1
    const retryBudget = Math.max(1, Math.trunc(Number(maxAttempts) || MAX_POLLING_TRANSIENT_FAILURES))
    if (nextAttempt >= retryBudget) return { kind: 'paused', error, attempt: nextAttempt, delayMs: 0 }
    const delayMs = pollingRetryDelayMs(nextAttempt)
    onTransientError?.(error, delayMs, nextAttempt)
    const retry = await wait(delayMs)
    return retry
      ? { kind: 'retry', error, attempt: nextAttempt, delayMs }
      : { kind: 'stopped', error, attempt: nextAttempt, delayMs }
  }
}
