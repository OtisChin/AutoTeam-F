import assert from 'node:assert/strict'
import { computeGoPayBoardMetrics, computeGoPayBoardView } from '../src/gopayBoard.js'

function metrics(task, options = {}) {
  return computeGoPayBoardMetrics({ task, ...options })
}

function cards(task, options = {}) {
  return Object.fromEntries(
    computeGoPayBoardView({ task, ...options }).cards.map(card => [card.label, card])
  )
}

{
  const cardMap = cards(null)
  assert.equal(cardMap['当前账号'].value, '-')
  assert.equal(cardMap['任务进度'].value, '0/0')
  assert.equal(cardMap['绑卡成功'].value, '0')
  assert.equal(cardMap['待重试'].value, '0')
  assert.equal(cardMap['绑卡失败'].value, '0')
}

{
  const task = {
    task_id: 'task-running',
    status: 'running',
    params: { auto_register: true, auto_register_count: 10 },
    progress: {
      stage: 'gopay_pending_retry_account',
      retry_round: 2,
      max_retry_rounds: 3,
      attempt: 4,
      total: 10,
      pending_retry: 6,
    },
    progress_events: [
      { stage: 'gopay_auto_register_done', email: 'a@example.com', current: 1, total: 10 },
      { stage: 'gopay_account_bound', email: 'a@example.com', successful: 1 },
      { stage: 'gopay_auto_register_done', email: 'b@example.com', current: 2, total: 10 },
      { stage: 'gopay_pending_retry_queued', email: 'b@example.com' },
      { stage: 'gopay_pending_retry_account', email: 'b@example.com', retry_round: 2, attempt: 4, total: 10 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.successful, 1)
  assert.equal(result.progressStats.total, 10)
  assert.equal(result.pendingRetry, 7)
  assert.equal(result.pendingRetryMeta, '第 2/3 轮 · 重试第 4/10 个账号')
  assert.equal(result.failureCount, 0)
  const cardMap = cards(task)
  assert.equal(cardMap['当前账号'].value, 'b@example.com')
  assert.equal(cardMap['任务进度'].value, '4/10')
  assert.equal(cardMap['绑卡成功'].value, '1')
  assert.equal(cardMap['绑卡成功'].meta, '注册成功 2')
  assert.equal(cardMap['待重试'].value, '7')
  assert.equal(cardMap['待重试'].meta, '第 2/3 轮 · 重试第 4/10 个账号')
  assert.equal(cardMap['绑卡失败'].value, '0')
}

{
  const task = {
    task_id: 'task-final',
    status: 'completed',
    params: { account_emails: ['one@example.com', 'two@example.com', 'three@example.com'] },
    result: {
      successful_emails: ['one@example.com', 'two@example.com'],
      failed_emails: ['two@example.com', 'three@example.com'],
      pending_retry_emails: [],
      attempted_emails: ['one@example.com', 'two@example.com', 'three@example.com'],
    },
    progress_events: [
      { stage: 'gopay_account_bound', email: 'one@example.com' },
      { stage: 'gopay_account_bound', email: 'two@example.com' },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.successful, 2)
  assert.equal(result.progressStats.attempted, 3)
  assert.equal(result.failureCount, 1)
  assert.equal(result.pendingRetry, 0)
  const cardMap = cards(task)
  assert.equal(cardMap['任务进度'].value, '3/3')
  assert.equal(cardMap['绑卡成功'].value, '2')
  assert.equal(cardMap['待重试'].value, '0')
  assert.equal(cardMap['绑卡失败'].value, '1')
}

{
  const task = {
    task_id: 'task-gopay-parallel-running',
    status: 'running',
    params: {
      account_emails: ['one@example.com', 'two@example.com', 'three@example.com', 'four@example.com'],
      gopay_auto_signup: true,
      gopay_concurrency: 3,
    },
    progress: {
      stage: 'gopay_auto_signup_account_failed',
      email: 'two@example.com',
      attempt: 2,
      total: 4,
      retry_round: 0,
      max_retry_rounds: 3,
    },
    progress_events: [
      { stage: 'gopay_parallel_started', total: 4, concurrency: 3 },
      { stage: 'gopay_parallel_account', email: 'one@example.com', attempt: 1, total: 4 },
      { stage: 'gopay_parallel_account', email: 'two@example.com', attempt: 2, total: 4 },
      { stage: 'gopay_auto_signup_account_success', email: 'one@example.com', attempt: 1, total: 4, successful: 1 },
      { stage: 'gopay_pending_retry_queued', email: 'two@example.com', retry_round: 0, max_retry_rounds: 3, pending_retry: 1 },
      { stage: 'gopay_auto_signup_account_failed', email: 'two@example.com', attempt: 2, total: 4, retry_round: 0 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.total, 4)
  assert.equal(result.progressStats.attempted, 2)
  assert.equal(result.progressStats.successful, 1)
  assert.equal(result.pendingRetry, 1)
  assert.equal(result.failureCount, 0)
  const cardMap = cards(task)
  assert.equal(cardMap['当前账号'].value, 'two@example.com')
  assert.equal(cardMap['任务进度'].value, '2/4')
  assert.equal(cardMap['绑卡成功'].value, '1')
  assert.equal(cardMap['待重试'].value, '1')
  assert.equal(cardMap['绑卡失败'].value, '0')
}

{
  const task = {
    task_id: 'task-wait',
    status: 'running',
    params: { account_emails: Array.from({ length: 19 }, (_, index) => `u${index}@example.com`) },
    progress: {
      stage: 'gopay_pending_retry_wait',
      retry_round: 1,
      max_retry_rounds: 3,
      pending_retry: 5,
    },
    progress_events: [
      { stage: 'gopay_try_account', email: 'u0@example.com', attempt: 1, total: 19 },
      { stage: 'gopay_pending_retry_queued', email: 'u0@example.com' },
      { stage: 'gopay_rotate_account', email: 'u1@example.com', attempt: 2, total: 19 },
      { stage: 'gopay_account_bound', email: 'u1@example.com', successful: 1 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.total, 19)
  assert.equal(result.progressStats.attempted, 2)
  assert.equal(result.progressStats.successful, 1)
  assert.equal(result.pendingRetry, 1)
  assert.equal(result.pendingRetryMeta, '第 1/3 轮 · 1 个待重试')
  const cardMap = cards(task)
  assert.equal(cardMap['当前账号'].value, '-')
  assert.equal(cardMap['任务进度'].value, '2/19')
  assert.equal(cardMap['待重试'].meta, '第 1/3 轮 · 1 个待重试')
}

{
  const task = {
    task_id: 'task-auto-final-without-count',
    status: 'completed',
    params: { auto_register: true },
    result: {
      successful_emails: ['auto1@example.com', 'auto2@example.com'],
    },
    progress_events: [
      { stage: 'gopay_account_bound', email: 'auto1@example.com' },
      { stage: 'gopay_account_bound', email: 'auto2@example.com' },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.successful, 2)
  assert.equal(result.progressStats.attempted, 2)
  assert.equal(result.progressStats.total, 2)
}

{
  const task = {
    task_id: 'task-wallet-auth-failed',
    status: 'running',
    params: {
      account_emails: [
        'one@example.com',
        'two@example.com',
        'three@example.com',
        'four@example.com',
        'five@example.com',
        'six@example.com',
      ],
    },
    progress: {
      stage: 'gopay_try_account',
      email: 'four@example.com',
      attempt: 4,
      total: 6,
      remaining_candidates: 2,
    },
    progress_events: [
      { stage: 'gopay_try_account', email: 'one@example.com', attempt: 1, total: 6 },
      { stage: 'gopay_payment_process_failed_rotate', email: 'one@example.com', attempt: 1, total: 6 },
      { stage: 'gopay_rotate_account', email: 'two@example.com', attempt: 2, total: 6 },
      { stage: 'gopay_rate_limited_retry', email: 'two@example.com', attempt: 2, total: 6 },
      { stage: 'gopay_pending_retry_queued', email: 'two@example.com' },
      { stage: 'gopay_rotate_account', email: 'three@example.com', attempt: 3, total: 6 },
      { stage: 'gopay_try_account', email: 'four@example.com', attempt: 4, total: 6 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.attempted, 4)
  assert.equal(result.progressStats.total, 6)
  assert.equal(result.failureCount, 0)
  assert.equal(result.pendingRetry, 1)
  assert.equal(result.progressStats.successful, 0)
  const cardMap = cards(task)
  assert.equal(cardMap['当前账号'].value, 'four@example.com')
  assert.equal(cardMap['任务进度'].value, '4/6')
  assert.equal(cardMap['绑卡成功'].value, '0')
  assert.equal(cardMap['待重试'].value, '1')
  assert.equal(cardMap['绑卡失败'].value, '0')
}

{
  const task = {
    task_id: 'task-retry-round-requeued',
    status: 'running',
    params: { account_emails: ['one@example.com', 'two@example.com'] },
    progress: {
      stage: 'gopay_pending_retry_wait',
      retry_round: 2,
      max_retry_rounds: 3,
      pending_retry: 1,
    },
    progress_events: [
      { stage: 'gopay_pending_retry_queued', email: 'one@example.com', retry_round: 0 },
      { stage: 'gopay_pending_retry_account', email: 'one@example.com', retry_round: 1 },
      { stage: 'gopay_pending_retry_failed', email: 'one@example.com', retry_round: 1, max_retry_rounds: 3 },
      { stage: 'gopay_pending_retry_queued', email: 'one@example.com', retry_round: 1 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.pendingRetry, 1)
  assert.equal(result.failureCount, 0)
}

{
  const task = {
    task_id: 'task-retry-terminal-failed',
    status: 'running',
    params: { account_emails: ['one@example.com', 'two@example.com'] },
    progress: {
      stage: 'gopay_pending_retry_failed',
      retry_round: 3,
      max_retry_rounds: 3,
      pending_retry: 0,
    },
    progress_events: [
      { stage: 'gopay_pending_retry_queued', email: 'one@example.com', retry_round: 2 },
      { stage: 'gopay_pending_retry_account', email: 'one@example.com', retry_round: 3 },
      { stage: 'gopay_pending_retry_failed', email: 'one@example.com', retry_round: 3, max_retry_rounds: 3 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.pendingRetry, 0)
  assert.equal(result.failureCount, 1)
}

{
  const task = {
    task_id: 'task-batch-progress-clamped',
    status: 'running',
    params: {
      account_emails: [
        'a@example.com',
        'b@example.com',
        'c@example.com',
        'd@example.com',
        'e@example.com',
        'f@example.com',
      ],
    },
    progress: {
      stage: 'gopay_pending_retry_wait',
      email: 'f@example.com',
      attempt: 20,
      total: 20,
      pending_retry: 0,
    },
    progress_events: [
      { stage: 'gopay_try_account', email: 'a@example.com', attempt: 1, total: 6 },
      { stage: 'gopay_rotate_account', email: 'b@example.com', attempt: 2, total: 6 },
      { stage: 'gopay_rotate_account', email: 'c@example.com', attempt: 3, total: 6 },
      { stage: 'gopay_rotate_account', email: 'd@example.com', attempt: 4, total: 6 },
      { stage: 'gopay_rotate_account', email: 'e@example.com', attempt: 5, total: 6 },
      { stage: 'gopay_rotate_account', email: 'f@example.com', attempt: 6, total: 6 },
    ],
  }
  const result = metrics(task)
  assert.equal(result.progressStats.attempted, 6)
  assert.equal(result.progressStats.total, 6)
  const cardMap = cards(task)
  assert.equal(cardMap['当前账号'].value, 'f@example.com')
  assert.equal(cardMap['任务进度'].value, '6/6')
  assert.equal(cardMap['待重试'].value, '0')
}

{
  const task = {
    task_id: 'task-retry-account-progress-has-moved-on',
    status: 'running',
    params: { account_emails: ['a@example.com', 'b@example.com', 'c@example.com', 'd@example.com', 'e@example.com', 'f@example.com'] },
    progress: {
      stage: 'midtrans_load_transaction',
      email: 'b@example.com',
      retry_round: 2,
      max_retry_rounds: 3,
      pending_retry: 4,
    },
    progress_events: [
      { stage: 'gopay_pending_retry_queued', email: 'b@example.com', retry_round: 1, max_retry_rounds: 3 },
      { stage: 'gopay_pending_retry_account', email: 'b@example.com', retry_round: 2, max_retry_rounds: 3, attempt: 2, total: 5 },
      { stage: 'midtrans_load_transaction', email: 'b@example.com' },
    ],
  }
  const cardMap = cards(task)
  assert.equal(cardMap['待重试'].value, '4')
  assert.equal(cardMap['待重试'].meta, '第 2/3 轮 · 重试第 2/5 个账号')
}

{
  const task = {
    task_id: 'task-batch-result-attempted-clamped',
    status: 'completed',
    params: {
      account_emails: [
        'a@example.com',
        'b@example.com',
        'c@example.com',
        'd@example.com',
        'e@example.com',
        'f@example.com',
      ],
    },
    result: {
      attempted_emails: Array.from({ length: 20 }, (_, index) => `attempt${index}@example.com`),
      successful_emails: [],
      pending_retry_emails: [],
    },
  }
  const result = metrics(task)
  assert.equal(result.progressStats.attempted, 6)
  assert.equal(result.progressStats.total, 6)
}

{
  const task = {
    task_id: 'task-batch-selected-form-fallback',
    status: 'running',
    params: {},
    progress: {
      stage: 'gopay_rotate_account',
      attempt: 20,
      total: 20,
    },
  }
  const selected = ['a@example.com', 'b@example.com', 'c@example.com', 'd@example.com', 'e@example.com', 'f@example.com']
  const result = metrics(task, { batchActive: true, selectedBatchEmails: selected })
  assert.equal(result.progressStats.attempted, 6)
  assert.equal(result.progressStats.total, 6)
}

{
  const task = {
    task_id: 'task-single-progress-no-batch',
    status: 'running',
    params: { email: 'single@example.com' },
    progress: {
      stage: 'gopay_try_account',
      attempt: 20,
      total: 20,
    },
  }
  const result = metrics(task)
  assert.equal(result.progressStats.attempted, 1)
  assert.equal(result.progressStats.total, 1)
  const cardMap = cards(task)
  assert.equal(cardMap['当前账号'].value, 'single@example.com')
  assert.equal(cardMap['任务进度'].value, '1/1')
  assert.equal(cardMap['待重试'].value, '0')
}

console.log('gopay board metrics tests passed')
