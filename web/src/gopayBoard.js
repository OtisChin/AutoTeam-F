export function normalizeGoPayAutoRegisterCount(value) {
  const count = Number(value || 1)
  if (!Number.isFinite(count)) return 1
  return Math.max(1, Math.min(100, Math.floor(count)))
}

function normalizedEmail(value) {
  return String(value || '').trim().toLowerCase()
}

function listEmail(item) {
  return normalizedEmail((item && typeof item === 'object') ? item.email : item)
}

function taskEvents(task) {
  return Array.isArray(task?.progress_events) ? task.progress_events : []
}

function successfulEmailSet(task) {
  const result = task?.result || {}
  const progress = task?.progress || {}
  const successful = new Set()
  if (Array.isArray(result.successful_emails)) {
    for (const email of result.successful_emails) {
      const normalized = normalizedEmail(email)
      if (normalized) successful.add(normalized)
    }
  }
  if (Array.isArray(progress.successful_emails)) {
    for (const email of progress.successful_emails) {
      const normalized = normalizedEmail(email)
      if (normalized) successful.add(normalized)
    }
  }
  for (const event of taskEvents(task)) {
    if (Array.isArray(event?.successful_emails)) {
      for (const email of event.successful_emails) {
        const normalized = normalizedEmail(email)
        if (normalized) successful.add(normalized)
      }
    }
    if (String(event?.stage || '') !== 'gopay_account_bound') continue
    const normalized = normalizedEmail(event?.email)
    if (normalized) successful.add(normalized)
  }
  return successful
}

function registeredEmailSet(task) {
  const result = task?.result || {}
  const registered = new Set()
  if (Array.isArray(result.registered_emails)) {
    for (const email of result.registered_emails) {
      const normalized = normalizedEmail(email)
      if (normalized) registered.add(normalized)
    }
  }
  for (const event of taskEvents(task)) {
    if (String(event?.stage || '') !== 'gopay_auto_register_done') continue
    const normalized = normalizedEmail(event?.email)
    if (normalized) registered.add(normalized)
  }
  return registered
}

function removedEmailSet(task) {
  const result = task?.result || {}
  const removed = new Set()
  const addList = list => {
    if (!Array.isArray(list)) return
    for (const item of list) {
      const normalized = listEmail(item)
      if (normalized) removed.add(normalized)
    }
  }
  addList(result.removed_pool_emails)
  for (const event of taskEvents(task)) {
    addList(event?.removed_pool_emails)
    if (String(event?.stage || '') === 'gopay_oauth_phone_required_removed') {
      const normalized = normalizedEmail(event?.email)
      if (normalized) removed.add(normalized)
    }
  }
  return removed
}

function latestEvent(events, stages) {
  const wanted = new Set(stages)
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (wanted.has(String(event?.stage || ''))) return event
  }
  return null
}

function latestAccountEmail(events) {
  const event = latestEvent(events, [
    'gopay_pending_retry_account',
    'paypal_pending_retry_account',
    'gopay_try_account',
    'gopay_rotate_account',
    'gopay_pending_retry_queued',
    'paypal_pending_retry_queued',
    'gopay_pending_retry_failed',
    'paypal_pending_retry_failed',
    'gopay_payment_process_failed_rotate',
    'gopay_account_failed_rotate',
    'checkout_not_approved_rotate',
    'gopay_nonzero_amount_blocked_rotate',
    'gopay_account_bound',
    'gopay_auto_register_done',
  ])
  return String(event?.email || '').trim()
}

export function computeGoPayBoardMetrics({ task, form = {}, batchActive = false, selectedBatchEmails = [] } = {}) {
  const progress = task?.progress || {}
  const result = task?.result || {}
  const params = task?.params || {}
  const events = taskEvents(task)
  const accounts = Array.isArray(params.account_emails) ? params.account_emails : []
  const isAutoRegister = Boolean(params.auto_register)
  const successful = successfulEmailSet(task)
  const removed = removedEmailSet(task)
  for (const email of removed) successful.delete(email)

  const failedEmails = new Set()
  const eventPendingEmails = new Set()
  const eventFailedEmails = new Set()
  const eventFailureAttemptKeys = new Set()
  const hasFinalResult = Boolean(task?.result)
  const lists = [
    result.rejected_emails,
    result.payment_failed_emails,
    result.nonzero_blocked_emails,
    result.bind_failed_emails,
    result.failed_emails,
    result.removed_pool_emails,
  ]
  if (hasFinalResult && !(Array.isArray(result.pending_retry_emails) && result.pending_retry_emails.length)) {
    lists.push(result.blocked_emails)
  }
  for (const list of lists) {
    if (!Array.isArray(list)) continue
    for (const [index, item] of list.entries()) {
      const normalized = listEmail(item)
      if (normalized) {
        if (!successful.has(normalized)) failedEmails.add(normalized)
      } else if (item && typeof item === 'object') {
        const current = String(item.auto_register_index || item.current || index + 1)
        failedEmails.add(`attempt:${current}`)
      }
    }
  }

  const terminalFailureStages = new Set([
    'checkout_not_approved_rotate',
    'gopay_nonzero_amount_blocked_rotate',
    'gopay_auto_register_bind_failed',
    'gopay_auto_register_failed',
    'gopay_account_failed_rotate',
    'paypal_nonzero_amount_blocked_rotate',
    'paypal_auto_register_bind_failed',
    'paypal_auto_register_failed',
    'paypal_account_failed_rotate',
  ])
  for (const event of events) {
    const stage = String(event?.stage || '')
    const email = normalizedEmail(event?.email)
    if (email) {
      if (stage === 'gopay_pending_retry_queued' || stage === 'paypal_pending_retry_queued') {
        eventPendingEmails.add(email)
        eventFailedEmails.delete(email)
      }
      if (stage === 'gopay_pending_retry_account' || stage === 'paypal_pending_retry_account') {
        eventPendingEmails.delete(email)
      }
      if (stage === 'gopay_account_bound') {
        eventPendingEmails.delete(email)
        eventFailedEmails.delete(email)
      }
      if (removed.has(email) || stage === 'gopay_oauth_phone_required_removed' || stage === 'gopay_oauth_phone_required') {
        eventPendingEmails.delete(email)
        if (!successful.has(email)) eventFailedEmails.add(email)
      }
      if (terminalFailureStages.has(stage)) {
        eventPendingEmails.delete(email)
        if (!successful.has(email)) eventFailedEmails.add(email)
      }
      if (stage === 'gopay_pending_retry_failed' || stage === 'paypal_pending_retry_failed') {
        eventPendingEmails.delete(email)
        if (!successful.has(email)) eventFailedEmails.add(email)
      }
      continue
    }

    if (!terminalFailureStages.has(stage) && stage !== 'gopay_pending_retry_failed' && stage !== 'paypal_pending_retry_failed') continue
    const current = String(event?.current || event?.attempt || event?.event_id || '')
    if (current) eventFailureAttemptKeys.add(`attempt:${current}`)
  }

  if (!hasFinalResult) {
    for (const email of eventFailedEmails) failedEmails.add(email)
    for (const key of eventFailureAttemptKeys) failedEmails.add(key)
  }

  let pendingRetry = 0
  if (Array.isArray(result.pending_retry_emails)) {
    pendingRetry = result.pending_retry_emails.filter(email => {
      const normalized = normalizedEmail(email)
      return normalized && !successful.has(normalized)
    }).length
  } else if (['gopay_pending_retry_account', 'paypal_pending_retry_account'].includes(String(progress.stage || '')) && Number.isFinite(Number(progress.pending_retry))) {
    pendingRetry = Math.max(1, Number(progress.pending_retry || 0) + 1)
  } else {
    for (const email of successful) eventPendingEmails.delete(email)
    if (eventPendingEmails.size) {
      pendingRetry = eventPendingEmails.size
    } else if (Number.isFinite(Number(progress.pending_retry))) {
      pendingRetry = Math.max(0, Number(progress.pending_retry || 0) - successful.size)
    }
  }

  const retryAccountEvent = latestEvent(events, ['gopay_pending_retry_account', 'paypal_pending_retry_account'])
  const retryInfoEvent = latestEvent(events, [
    'gopay_pending_retry_account',
    'paypal_pending_retry_account',
    'gopay_pending_retry_started',
    'paypal_pending_retry_started',
    'gopay_pending_retry_wait',
    'paypal_pending_retry_wait',
    'gopay_pending_retry_queued',
    'paypal_pending_retry_queued',
  ])
  const retryRound = Number(progress.retry_round || retryInfoEvent?.retry_round || 0)
  const maxRetryRounds = Number(progress.max_retry_rounds || retryInfoEvent?.max_retry_rounds || 0)
  const roundText = retryRound && maxRetryRounds ? `第 ${retryRound}/${maxRetryRounds} 轮` : ''
  let pendingRetryMeta = ''
  const currentStage = String(progress.stage || '')
  const activeRetryAccount = currentStage === 'gopay_pending_retry_account'
    || currentStage === 'paypal_pending_retry_account'
    ? progress
    : ['gopay_pending_retry_wait', 'gopay_pending_retry_started', 'paypal_pending_retry_wait', 'paypal_pending_retry_started'].includes(currentStage)
      ? null
      : retryAccountEvent
  if (activeRetryAccount) {
    const attempt = Number(activeRetryAccount?.attempt || 0)
    const total = Number(activeRetryAccount?.total || 0)
    const retryText = attempt && total ? `重试第 ${attempt}/${total} 个账号` : '正在重试'
    pendingRetryMeta = [roundText, retryText].filter(Boolean).join(' · ')
  } else if (
    ['gopay_pending_retry_wait', 'gopay_pending_retry_started', 'paypal_pending_retry_wait', 'paypal_pending_retry_started'].includes(currentStage)
    || ['gopay_pending_retry_wait', 'gopay_pending_retry_started', 'gopay_pending_retry_queued', 'paypal_pending_retry_wait', 'paypal_pending_retry_started', 'paypal_pending_retry_queued'].includes(String(retryInfoEvent?.stage || ''))
  ) {
    const pendingText = pendingRetry ? `${pendingRetry} 个待重试` : ''
    pendingRetryMeta = [roundText, pendingText].filter(Boolean).join(' · ')
  }

  const autoRegisterEventTotal = events.reduce((maxTotal, event) => {
    const stage = String(event?.stage || '')
    if (!(stage.startsWith('gopay_auto_register') || stage.startsWith('register_'))) return maxTotal
    const total = Number(event?.total || 0)
    return Number.isFinite(total) ? Math.max(maxTotal, total) : maxTotal
  }, 0)
  const autoRegisterCount = isAutoRegister
    ? normalizeGoPayAutoRegisterCount(params.auto_register_count || result.auto_register_count || progress.auto_register_count || autoRegisterEventTotal || 1)
    : 0
  const autoRegisterEventAttempted = isAutoRegister
    ? events.reduce((maxCurrent, event) => {
      const stage = String(event?.stage || '')
      if (!(stage.startsWith('gopay_auto_register') || stage.startsWith('register_'))) return maxCurrent
      const current = Number(event?.current || event?.attempt || 0)
      return Number.isFinite(current) ? Math.max(maxCurrent, current) : maxCurrent
    }, 0)
    : 0
  const currentAccountAttempt = !isAutoRegister
    ? events.reduce((maxCurrent, event) => {
      const stage = String(event?.stage || '')
      if (!['gopay_try_account', 'gopay_rotate_account', 'gopay_pending_retry_account', 'paypal_try_account', 'paypal_rotate_account', 'paypal_pending_retry_account'].includes(stage)) return maxCurrent
      const current = Number(event?.attempt || event?.current || 0)
      return Number.isFinite(current) ? Math.max(maxCurrent, current) : maxCurrent
    }, 0)
    : 0
  const progressSuccessful = Number.isFinite(Number(progress.successful)) ? Math.max(0, Number(progress.successful || 0)) : 0
  const resultSuccessful = Array.isArray(result.successful_emails) ? result.successful_emails.filter(email => normalizedEmail(email)).length : 0
  const adjustedProgressSuccessful = Math.max(0, progressSuccessful - removed.size)
  const adjustedResultSuccessful = Math.max(0, resultSuccessful - removed.size)
  const knownSuccessfulCount = Math.max(successful.size, adjustedProgressSuccessful, adjustedResultSuccessful)
  const baseTotal = isAutoRegister
    ? Math.max(autoRegisterCount, knownSuccessfulCount, Number(result.auto_register_attempted || 0), autoRegisterEventAttempted)
    : Number(accounts.length || (batchActive ? selectedBatchEmails.length : 0) || (params.email ? 1 : 0) || progress.total || (task?.task_id ? 1 : 0))
  const attempted = isAutoRegister
    ? Math.max(Number(result.auto_register_attempted || 0), Number(progress.attempted || progress.attempt || 0), autoRegisterEventAttempted)
    : Array.isArray(result.attempted_emails)
      ? Math.max(result.attempted_emails.length, currentAccountAttempt)
      : Math.max(Number(progress.attempted || progress.attempt || 0), currentAccountAttempt)
  const successfulCount = knownSuccessfulCount
  const rawDone = Math.max(attempted, successfulCount)
  const done = baseTotal ? Math.min(baseTotal, rawDone) : rawDone
  const total = baseTotal
  const remaining = Number.isFinite(Number(progress.remaining_candidates))
    ? Number(progress.remaining_candidates)
    : Math.max(0, total - done)

  return {
    failureCount: failedEmails.size,
    pendingRetry,
    pendingRetryMeta,
    progressStats: {
      total: Math.max(total, done),
      attempted: done,
      successful: successfulCount,
      remaining,
    },
  }
}

export function computeGoPayBoardView({ task, form = {}, batchActive = false, selectedBatchEmails = [] } = {}) {
  const metrics = computeGoPayBoardMetrics({ task, form, batchActive, selectedBatchEmails })
  const progress = task?.progress || {}
  const result = task?.result || {}
  const params = task?.params || {}
  const events = taskEvents(task)
  const stats = metrics.progressStats
  const currentStage = String(progress.stage || '')

  const waitingForRetry = ['gopay_pending_retry_wait', 'gopay_pending_retry_started', 'paypal_pending_retry_wait', 'paypal_pending_retry_started'].includes(currentStage)
  let currentAccount = progress.email || (waitingForRetry ? '' : latestAccountEmail(events)) || result.email || result.email_used || params.email || form.email || ''
  if (!currentAccount && params.auto_register) {
    const current = Number(progress.current || progress.attempt || 0)
    const total = normalizeGoPayAutoRegisterCount(params.auto_register_count || result.auto_register_count || 1)
    currentAccount = current > 0 ? `第 ${current}/${total} 个` : `自动注册 ${total} 个`
  }
  if (!currentAccount) currentAccount = '-'

  const registered = registeredEmailSet(task).size
  const registrationMeta = params.auto_register ? `注册成功 ${registered}` : ''
  const progressText = stats.total ? `${Math.max(stats.attempted, stats.successful)}/${stats.total}` : '0/0'

  return {
    currentAccount,
    progressText,
    successfulCount: stats.successful || 0,
    registrationMeta,
    pendingRetryCount: metrics.pendingRetry,
    pendingRetryMeta: metrics.pendingRetryMeta,
    failureCount: metrics.failureCount,
    metrics,
    cards: [
      {
        label: '当前账号',
        value: currentAccount,
        color: 'text-cyan-300 font-mono text-base',
        meta: '',
      },
      {
        label: '任务进度',
        value: progressText,
        color: 'text-blue-400',
        meta: '',
      },
      {
        label: '绑卡成功',
        value: String(stats.successful || 0),
        color: 'text-emerald-400',
        meta: registrationMeta,
      },
      {
        label: '待重试',
        value: String(metrics.pendingRetry),
        color: 'text-violet-300',
        meta: metrics.pendingRetryMeta,
      },
      {
        label: '绑卡失败',
        value: String(metrics.failureCount),
        color: 'text-red-400',
        meta: '',
      },
    ],
  }
}
