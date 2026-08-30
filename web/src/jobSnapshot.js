export const JOB_SNAPSHOT_LOG_LIMIT = 200

function compactJob(job) {
  if (!job || typeof job !== 'object') return null
  const { logs: _logs, result: _result, ...metadata } = job
  return metadata
}

export function compactPaymentJobSnapshot({
  jobId,
  job,
  logs,
  result,
  statusText,
  statusError,
  fallback = {},
} = {}) {
  const logTail = Array.isArray(logs) ? logs.slice(-JOB_SNAPSHOT_LOG_LIMIT) : []
  return {
    ...fallback,
    jobId: jobId || job?.id || fallback.jobId || '',
    accountCount: Number(job?.total || fallback.accountCount || 1),
    concurrency: Number(job?.concurrency || fallback.concurrency || 1),
    startedAt: fallback.startedAt || job?.startedAt || job?.started_at || Date.now(),
    updatedAt: Date.now(),
    job: compactJob(job),
    logs: logTail,
    result: result || null,
    statusText: String(statusText || ''),
    statusError: Boolean(statusError),
  }
}

export function createSnapshotWriteGate({ intervalMs = 5_000, now = Date.now } = {}) {
  const lastWriteAt = new Map()

  function shouldWrite(key, { force = false } = {}) {
    const timestamp = Number(now())
    const previous = lastWriteAt.get(key)
    if (!force && previous !== undefined && timestamp >= previous && timestamp - previous < intervalMs) return false
    lastWriteAt.set(key, timestamp)
    return true
  }

  function reset(key) {
    if (key === undefined) lastWriteAt.clear()
    else lastWriteAt.delete(key)
  }

  return { shouldWrite, reset }
}
