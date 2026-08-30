export const TASK_HISTORY_PAGE_SIZE = 50

const text = value => {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  try { return JSON.stringify(value) } catch { return String(value) }
}

export function filterTaskHistory(tasks, { query = '', status = '', command = '' } = {}) {
  const source = Array.isArray(tasks) ? tasks : []
  const queryNeedle = String(query ?? '').trim().toLowerCase()
  const statusNeedle = String(status ?? '').trim().toLowerCase()
  const commandNeedle = String(command ?? '').trim().toLowerCase()
  return source.filter(task => {
    const taskStatus = String(task?.status ?? '').toLowerCase()
    const taskCommand = String(task?.command ?? '').toLowerCase()
    if (statusNeedle && taskStatus !== statusNeedle) return false
    if (commandNeedle && !taskCommand.includes(commandNeedle)) return false
    if (!queryNeedle) return true
    return [task?.task_id, task?.id, task?.command, task?.params, task?.error, task?.result]
      .some(value => text(value).toLowerCase().includes(queryNeedle))
  })
}

export function pageTaskHistory(tasks, page = 1, pageSize = TASK_HISTORY_PAGE_SIZE) {
  const source = Array.isArray(tasks) ? tasks : []
  const size = Math.max(1, Math.trunc(Number(pageSize) || TASK_HISTORY_PAGE_SIZE))
  const totalItems = source.length
  const totalPages = Math.max(1, Math.ceil(totalItems / size))
  const currentPage = Math.min(totalPages, Math.max(1, Math.trunc(Number(page) || 1)))
  const start = (currentPage - 1) * size
  return { page: currentPage, pageSize: size, totalItems, totalPages, rows: source.slice(start, start + size) }
}

export function summarizeTaskHistory(tasks) {
  const source = Array.isArray(tasks) ? tasks : []
  return source.reduce((summary, task) => {
    summary.total += 1
    const status = String(task?.status ?? '').toLowerCase()
    if (status === 'pending' || status === 'running') summary.active += 1
    else if (status === 'completed') summary.completed += 1
    else if (status === 'failed') summary.failed += 1
    return summary
  }, { total: 0, active: 0, completed: 0, failed: 0 })
}
