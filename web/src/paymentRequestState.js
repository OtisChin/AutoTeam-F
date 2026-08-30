export const PAYMENT_SUBMIT_TIMEOUT_MS = 80_000
export const PAYMENT_STATUS_TIMEOUT_MS = 25_000
export const PAYMENT_CANCEL_TIMEOUT_MS = 360_000
export const LOCAL_PAYMENT_POLL_PAUSED = 'local_paused'
export const PAYMENT_RECOVERY_BASE_DELAY_MS = 5_000
export const PAYMENT_RECOVERY_MAX_DELAY_MS = 60_000
export const PAYMENT_RECOVERY_MAX_ATTEMPTS = 5

export function createSubmissionGenerationGuard() {
  let generation = 0
  return {
    start() {
      generation += 1
      return generation
    },
    cancel() {
      generation += 1
    },
    isActive(token) {
      return Number(token) === generation
    },
  }
}

export function paymentRecoveryDelayMs(
  attempt,
  {
    random = Math.random,
    baseDelayMs = PAYMENT_RECOVERY_BASE_DELAY_MS,
    maxDelayMs = PAYMENT_RECOVERY_MAX_DELAY_MS,
  } = {},
) {
  const retryIndex = Math.max(0, Math.floor(Number(attempt || 1)) - 1)
  const exponential = Math.min(maxDelayMs, baseDelayMs * (2 ** Math.min(retryIndex, 20)))
  const randomValue = Math.max(0, Math.min(1, Number(random?.() ?? 0.5)))
  const jittered = exponential * (0.75 + randomValue * 0.5)
  return Math.max(1, Math.round(Math.min(maxDelayMs, jittered)))
}

export function isAmbiguousPaymentFailure(error) {
  const code = String(error?.code || error?.data?.detail?.code || error?.data?.code || '').trim().toLowerCase()
  const status = Number(error?.status || 0)

  if (error?.timeout || code === 'request_timeout') return true
  if (code === 'payment_job_acknowledgement_missing' || code === 'invalid_payment_job_response') return true
  if (code === 'payment_api_unreachable' || code === 'upi_scan_api_unreachable' || code === 'remote_api_unreachable') return true
  if (status >= 500) return true
  if (status > 0 || error?.data || code) return false
  return true
}
