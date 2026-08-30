export const EXPORT_STATUS_CONFIRM_BATCH_SIZE = 1000

function exportedEmailsFromResult(result) {
  const source = Array.isArray(result?.exported_emails) ? result.exported_emails : []
  const emails = []
  const seen = new Set()
  for (const value of source) {
    const email = String(value || '').trim().toLowerCase()
    if (!email || seen.has(email)) continue
    seen.add(email)
    emails.push(email)
  }
  return emails
}

export async function confirmExportStatusBatches(
  result,
  confirmBatch,
  { batchSize = EXPORT_STATUS_CONFIRM_BATCH_SIZE } = {},
) {
  if (typeof confirmBatch !== 'function') throw new TypeError('confirmBatch must be a function')
  const emails = exportedEmailsFromResult(result)
  const boundedBatchSize = Math.max(1, Math.min(EXPORT_STATUS_CONFIRM_BATCH_SIZE, Number(batchSize) || 1))
  let confirmedCount = 0
  let batchCount = 0

  for (let index = 0; index < emails.length; index += boundedBatchSize) {
    const batch = emails.slice(index, index + boundedBatchSize)
    try {
      await confirmBatch(batch)
    } catch (cause) {
      const detail = String(cause?.message || cause || '未知错误')
      const error = new Error(`导出状态分批确认失败：${detail}`)
      error.cause = cause
      error.confirmedCount = confirmedCount
      error.remainingCount = emails.length - confirmedCount
      error.totalCount = emails.length
      throw error
    }
    confirmedCount += batch.length
    batchCount += 1
  }

  return {
    confirmedCount,
    totalCount: emails.length,
    batchCount,
  }
}
