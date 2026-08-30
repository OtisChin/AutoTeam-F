function normalizedEmail(account) {
  return String(account?.email || '').trim().toLowerCase()
}

export function buildAccountSelectionIndex(accounts) {
  const source = Array.isArray(accounts) ? accounts : []
  const selectableEmails = []
  const recordsByEmail = new Map()

  for (let index = 0; index < source.length; index += 1) {
    const account = source[index]
    if (account?.is_main_account) continue
    const email = normalizedEmail(account)
    if (!email) continue
    selectableEmails.push(account.email)
    if (!recordsByEmail.has(email)) recordsByEmail.set(email, { account, index })
  }

  return { source, selectableEmails, recordsByEmail }
}

export function selectAccountsFromIndex(selectionIndex, selectedEmailSet) {
  const selected = selectedEmailSet instanceof Set ? selectedEmailSet : new Set()
  const recordsByEmail = selectionIndex?.recordsByEmail instanceof Map
    ? selectionIndex.recordsByEmail
    : new Map()
  const records = []
  const seen = new Set()

  for (const rawEmail of selected) {
    const email = String(rawEmail || '').trim().toLowerCase()
    if (!email || seen.has(email)) continue
    seen.add(email)
    const record = recordsByEmail.get(email)
    if (record) records.push(record)
  }

  records.sort((left, right) => left.index - right.index)
  return records.map(record => record.account)
}

export function buildScopedAccountActions(accounts, predicates = {}) {
  const source = Array.isArray(accounts) ? accounts : []
  const oauthAuthorizableAccounts = []
  const reloginableAccounts = []
  const cpaExportableAccounts = []
  const refreshableQuotaAccounts = []
  const canOauthAuthorize = predicates.canOauthAuthorize || (() => false)
  const canRelogin = predicates.canRelogin || (() => false)
  const hasCodexAuthFile = predicates.hasCodexAuthFile || (() => false)

  for (const account of source) {
    if (canOauthAuthorize(account)) oauthAuthorizableAccounts.push(account)
    if (canRelogin(account)) reloginableAccounts.push(account)
    if (account?.is_main_account) continue
    if (hasCodexAuthFile(account)) cpaExportableAccounts.push(account)
    if (String(account?.status || '').toLowerCase() !== 'fail') refreshableQuotaAccounts.push(account)
  }

  return {
    oauthAuthorizableAccounts,
    reloginableAccounts,
    cpaExportableAccounts,
    refreshableQuotaAccounts,
  }
}

export function buildAccountActionScope(accounts, selectedEmailSet, predicates = {}) {
  const selectionIndex = buildAccountSelectionIndex(accounts)
  const selectedAccounts = selectAccountsFromIndex(selectionIndex, selectedEmailSet)
  const scopedAccounts = selectedAccounts.length ? selectedAccounts : selectionIndex.source

  return {
    selectableEmails: selectionIndex.selectableEmails,
    selectedEmails: selectedAccounts.map(account => account.email),
    scopedAccounts,
    exportableAccounts: scopedAccounts,
    ...buildScopedAccountActions(scopedAccounts, predicates),
  }
}
