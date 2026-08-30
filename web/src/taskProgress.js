function finiteNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function firstPositive(values) {
  for (const value of values) {
    const number = finiteNumber(value)
    if (number !== null && number > 0) return number
  }
  return 0
}

function sumIfPresent(source, first, second) {
  const left = finiteNumber(source?.[first])
  const right = finiteNumber(source?.[second])
  if (left === null && right === null) return null
  return (left || 0) + (right || 0)
}

export function calculateTaskProgress(task) {
  const progress = task?.progress || {}
  const params = task?.params || {}
  const result = task?.result || {}
  const total = firstPositive([
    progress.total,
    progress.account_count,
    result.total,
    params.auto_register_count,
    params.count,
    params.account_count,
    params.account_emails_count,
    params.emails_count,
    Array.isArray(params.account_emails) ? params.account_emails.length : 0,
  ])
  const done = firstPositive([
    progress.current,
    progress.processed,
    sumIfPresent(progress, 'successful', 'failed'),
    sumIfPresent(progress, 'ok', 'failed'),
    result.successful,
  ])

  if (total > 0) {
    const current = Math.max(0, Math.min(total, done))
    return {
      text: `${current}/${total}`,
      percent: Math.max(4, Math.round((current / total) * 100)),
    }
  }
  if (task?.status === 'pending') return { text: '等待中', percent: 8 }
  return { text: '进行中', percent: 35 }
}
