function asArray(value) {
  return Array.isArray(value) ? value : []
}

export function accountPoolAllAccounts(status) {
  if (Array.isArray(status?.all_accounts)) return status.all_accounts
  return asArray(status?.accounts)
}

export function accountPoolVisibleAccounts(status, filter, options = {}) {
  const selected = String(filter || 'all')
  if (selected === 'all') return accountPoolAllAccounts(status)

  const bucketFields = {
    available: ['available_accounts'],
    registered: ['registered_accounts'],
    unavailable: ['unavailable_accounts'],
  }[selected] || []

  for (const field of bucketFields) {
    if (Array.isArray(status?.[field])) return status[field]
  }

  const accounts = asArray(status?.accounts)
  if (options.isICloudProvider && selected === 'available' && accounts.length) {
    return accounts.filter(account => account?.status === 'available')
  }

  return accountPoolAllAccounts(status).filter(account => account?.status === selected)
}
