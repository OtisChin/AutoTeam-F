const BLOCKED_BINDABLE_STATUSES = new Set([
  'fail',
  'auth_invalid',
  'auth_revoked',
  'orphan',
  'exhausted',
  'standby',
])

function normalizedStatus(value) {
  const status = String(value || '').trim().toLowerCase()
  return ['personal', 'plus'].includes(status) ? 'active' : status
}

function localDateKeyFromSeconds(value) {
  const seconds = Number(value || 0) || 0
  if (!seconds) return ''
  const date = new Date(seconds * 1000)
  if (Number.isNaN(date.getTime())) return ''
  const pad = number => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function hasCodexAuthFile(account) {
  if (account?.has_codex_auth_file !== undefined) return Boolean(account.has_codex_auth_file)
  const file = String(account?.codex_auth_file || account?.auth_file || '').replace(/\\/g, '/').toLowerCase()
  return file.includes('/data/auths/') || file.includes('/auths/codex-') || file.includes('data/auths/')
}

function isBindableFreeAccount(account) {
  if (!account?.email || account?.is_main_account) return false
  if (String(account?.account_type || '').toLowerCase() !== 'free') return false
  if (!account?.auth_session_file) return false
  return !BLOCKED_BINDABLE_STATUSES.has(normalizedStatus(account?.status))
}

function increment(counts, key) {
  counts.set(key, (counts.get(key) || 0) + 1)
}

export function buildAccountFacets(accounts) {
  const source = Array.isArray(accounts) ? accounts : []
  const statusCounts = new Map([
    ['auth_invalid', 0],
    ['auth_revoked', 0],
    ['stashed', 0],
  ])
  const accountTypeCounts = new Map()
  const bindProviderCounts = new Map()
  const bindDateKeys = new Set()
  const registerDateKeys = new Set()
  const exportDateKeys = new Set()
  const credentialCounts = { exported: 0, unexported: 0 }
  const hubSyncCounts = { synced: 0, unsynced: 0 }
  const authCredentialCounts = { hasAuth: 0, missingAuth: 0 }
  const bindableFreeAccounts = []
  const invalidCredentialAccounts = []
  let trialEligibleCount = 0

  for (const account of source) {
    const status = normalizedStatus(account?.status)
    if (status) increment(statusCounts, status)

    const accountType = String(account?.account_type || 'unknown')
    increment(accountTypeCounts, accountType)

    const provider = String(account?.last_bind_provider || '').trim().toLowerCase() || '__none__'
    increment(bindProviderCounts, provider)

    if (account?.trial_eligible) trialEligibleCount += 1
    credentialCounts[account?.credentials_exported ? 'exported' : 'unexported'] += 1
    hubSyncCounts[account?.account_hub_synced ? 'synced' : 'unsynced'] += 1

    if (!account?.is_main_account) {
      authCredentialCounts[hasCodexAuthFile(account) ? 'hasAuth' : 'missingAuth'] += 1
      if (status === 'fail') invalidCredentialAccounts.push(account)
    }
    if (isBindableFreeAccount(account)) bindableFreeAccounts.push(account)

    const bindDate = localDateKeyFromSeconds(account?.plus_bound_at || account?.last_bind_at)
    const registerDate = localDateKeyFromSeconds(account?.created_at || account?.registered_at || account?.register_at)
    const exportDate = localDateKeyFromSeconds(account?.credentials_exported_at)
    if (bindDate) bindDateKeys.add(bindDate)
    if (registerDate) registerDateKeys.add(registerDate)
    if (exportDate) exportDateKeys.add(exportDate)
  }

  const descending = values => Array.from(values).sort((a, b) => b.localeCompare(a))
  return {
    statusCounts,
    accountTypeCounts,
    bindProviderCounts,
    trialEligibleCount,
    credentialCounts,
    hubSyncCounts,
    authCredentialCounts,
    bindDateKeys: descending(bindDateKeys),
    registerDateKeys: descending(registerDateKeys),
    exportDateKeys: descending(exportDateKeys),
    bindableFreeAccounts,
    invalidCredentialAccounts,
  }
}
