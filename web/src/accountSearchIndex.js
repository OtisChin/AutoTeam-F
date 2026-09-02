function normalizedStatus(value) {
  const status = String(value || '').trim().toLowerCase()
  return ['personal', 'plus'].includes(status) ? 'active' : status
}

function normalizedText(value) {
  return String(value || '').trim().toLowerCase()
}

function numericTimestamp(value) {
  if (value === null || value === undefined || value === '') return 0
  const timestamp = Number(value)
  if (Number.isFinite(timestamp)) return timestamp
  const parsed = Date.parse(String(value))
  return Number.isFinite(parsed) ? Math.floor(parsed / 1000) : 0
}

function displayEmail(account) {
  return account?.display_email || account?.original_email || account?.email || ''
}

function hasCodexAuthFile(account) {
  if (account?.has_codex_auth_file !== undefined) return Boolean(account.has_codex_auth_file)
  const file = String(account?.codex_auth_file || account?.auth_file || '').replace(/\\/g, '/').toLowerCase()
  return file.includes('/data/auths/') || file.includes('/auths/codex-') || file.includes('data/auths/')
}

function accountTwoFactorStatus(account) {
  return account?.two_factor_enabled === true || normalizedText(account?.totp_status) === 'enabled'
    ? 'enabled'
    : 'disabled'
}

function inRange(value, range) {
  const start = numericTimestamp(range?.start)
  const end = numericTimestamp(range?.end)
  if (!start && !end) return true
  if (!value) return false
  return (!start || value >= start) && (!end || value <= end)
}

export function buildAccountSearchIndex(accounts) {
  const source = Array.isArray(accounts) ? accounts : []
  const index = new Array(source.length)

  for (let position = 0; position < source.length; position += 1) {
    const account = source[position]
    const bindTimestamp = numericTimestamp(account?.plus_bound_at || account?.last_bind_at)
    index[position] = {
      account,
      position,
      email: `${account?.email || ''} ${displayEmail(account)}`.trim().toLowerCase(),
      status: normalizedStatus(account?.status),
      accountType: String(account?.account_type || 'unknown'),
      trialEligible: Boolean(account?.trial_eligible),
      bindProvider: normalizedText(account?.last_bind_provider) || '__none__',
      registerTimestamp: numericTimestamp(account?.created_at || account?.registered_at || account?.register_at),
      updateTimestamp: numericTimestamp(
        account?.updated_at
        ?? account?.updatedAt
        ?? account?.last_updated_at
        ?? account?.lastUpdatedAt
        ?? account?.modified_at
        ?? account?.modifiedAt
        ?? account?.last_active_at
        ?? account?.lastActiveAt
        ?? account?.created_at
        ?? account?.createdAt
      ),
      exportStatus: account?.credentials_exported ? 'exported' : 'unexported',
      exportTimestamp: numericTimestamp(account?.credentials_exported_at),
      hubSyncStatus: account?.account_hub_synced ? 'synced' : 'unsynced',
      authStatus: hasCodexAuthFile(account) ? 'has_auth' : 'missing_auth',
      twoFactorStatus: accountTwoFactorStatus(account),
      bindTimestamp,
      plus: normalizedText(account?.account_type) === 'plus',
    }
  }

  index.sort((left, right) => {
    const updateDifference = right.updateTimestamp - left.updateTimestamp
    if (updateDifference) return updateDifference
    return left.position - right.position
  })

  return index
}

export function filterAccountSearchIndex(index, filters = {}, order = 'desc') {
  const source = Array.isArray(index) ? index : []
  const email = normalizedText(filters.email)
  const status = String(filters.status || '')
  const accountType = String(filters.accountType || '')
  const trial = String(filters.trial || '')
  const bindProvider = String(filters.bindProvider || '')
  const credentialExport = String(filters.credentialExport || '')
  const hubSync = String(filters.hubSync || '')
  const authCredential = String(filters.authCredential || '')
  const twoFactor = String(filters.twoFactor || '')
  const ascending = order === 'asc'
  const matches = []

  for (let offset = 0; offset < source.length; offset += 1) {
    const entry = source[ascending ? source.length - 1 - offset : offset]
    if (email && !entry.email.includes(email)) continue
    if (status && entry.status !== status) continue
    if (accountType && entry.accountType !== accountType) continue
    if (trial === 'eligible' && !entry.trialEligible) continue
    if (trial === 'not_eligible' && entry.trialEligible) continue
    if (bindProvider && entry.bindProvider !== bindProvider) continue
    if (!inRange(entry.registerTimestamp, filters.registerRange)) continue
    if (credentialExport && entry.exportStatus !== credentialExport) continue
    if (!inRange(entry.exportTimestamp, filters.exportRange)) continue
    if (hubSync && entry.hubSyncStatus !== hubSync) continue
    if (authCredential && entry.authStatus !== authCredential) continue
    if (twoFactor && entry.twoFactorStatus !== twoFactor) continue
    if (!inRange(entry.bindTimestamp, filters.bindRange)) continue
    matches.push(entry.account)
  }

  return matches
}
