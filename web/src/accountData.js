const SUMMARY_STATUS_KEYS = [
  'active',
  'standby',
  'stashed',
  'exhausted',
  'pending',
  'auth_invalid',
  'auth_revoked',
  'orphan',
  'fail',
]

const SUMMARY_TYPE_KEYS = ['free', 'team', 'plus', 'pro']

function normalizedStatus(value) {
  const status = String(value || '').trim().toLowerCase()
  return ['personal', 'plus'].includes(status) ? 'active' : status
}

const UNSAFE_ACCOUNT_FIELD_NAMES = new Set(['__proto__', 'constructor', 'prototype'])

function forEachDashboardAccount(payload, visit) {
  if (Array.isArray(payload)) {
    for (const account of payload) visit(account)
    return
  }

  const fields = Array.isArray(payload?.fields) ? payload.fields : []
  const rows = Array.isArray(payload?.rows) ? payload.rows : []
  if (!fields.length || !rows.length) return

  for (const row of rows) {
    if (!Array.isArray(row)) continue
    const account = {}
    const valueCount = Math.min(fields.length, row.length)
    for (let index = 0; index < valueCount; index += 1) {
      const field = fields[index]
      if (typeof field !== 'string' || !field || UNSAFE_ACCOUNT_FIELD_NAMES.has(field)) continue
      account[field] = row[index]
    }
    visit(account)
  }
}

export function normalizeStoredPageSize(value, defaultValue, allowedValues) {
  if (value === null || value === undefined || String(value).trim() === '') return defaultValue
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return defaultValue
  return allowedValues.includes(numeric) ? numeric : defaultValue
}

export function buildDashboardStatusFromAccounts(payload) {
  const accounts = []
  const summary = Object.fromEntries([
    ...SUMMARY_STATUS_KEYS.map(key => [key, 0]),
    ...SUMMARY_TYPE_KEYS.map(key => [key, 0]),
    ['total', 0],
  ])

  forEachDashboardAccount(payload, rawAccount => {
    const rawStatus = String(rawAccount?.status || '').trim().toLowerCase()
    const account = {
      ...rawAccount,
      raw_status: rawAccount?.raw_status || rawStatus,
      status: normalizedStatus(rawStatus),
      last_bind_provider: String(rawAccount?.last_bind_provider || '').trim().toLowerCase(),
    }
    accounts.push(account)
    summary.total += 1

    const statusKey = account.status || 'pending'
    if (SUMMARY_STATUS_KEYS.includes(statusKey)) summary[statusKey] += 1

    const typeKey = String(account.account_type || account.seat_type || 'free').toLowerCase()
    if (SUMMARY_TYPE_KEYS.includes(typeKey)) summary[typeKey] += 1
  })

  return {
    accounts,
    summary,
    quota_cache: {},
    fallback: true,
  }
}
