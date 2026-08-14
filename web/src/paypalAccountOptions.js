function normalizeCountry(value) {
  return String(value || '').trim().toUpperCase()
}

function normalizeEmail(value) {
  return String(value || '').trim().toLowerCase()
}

function statusOf(account) {
  return String(account?.paypal_status || account?.paypalStatus || account?.status || 'pending').trim().toLowerCase()
}

function statusMatchesFilter(status, statusFilter = 'all') {
  const cleanStatus = String(status || '').trim().toLowerCase()
  const filter = String(statusFilter || 'all').trim().toLowerCase()
  if (!filter || filter === 'all') return true
  if (filter === 'failed') return cleanStatus === 'failed' || cleanStatus === 'error'
  return cleanStatus === filter
}

function linkCountry(link) {
  const billing = link?.billing && typeof link.billing === 'object' ? link.billing : {}
  return normalizeCountry(link?.target_country || link?.targetCountry || link?.paypal_country || link?.paypalCountry || link?.country || link?.region || billing.country)
}

function linkUrl(link) {
  return String(link?.paypal_link || link?.paypalLink || link?.provider_redirect_url || link?.providerRedirectUrl || link?.stripe_redirect_url || link?.stripeRedirectUrl || '').trim()
}

function timestampOf(value) {
  const raw = value?.updated_at ?? value?.updatedAt ?? value?.last_active_at ?? value?.lastActiveAt ?? value?.created_at ?? value?.createdAt ?? 0
  if (typeof raw === 'number') return Number.isFinite(raw) ? raw : 0
  const parsed = Date.parse(String(raw || ''))
  return Number.isFinite(parsed) ? parsed : 0
}

export const PAYPAL_LINK_TTL_MS = 3 * 60 * 60 * 1000

export function paypalLinkCreatedAtMs(link) {
  const explicit = link?.created_at_ts ?? link?.createdAtTs
  if (explicit !== undefined && explicit !== null && explicit !== '') {
    const numeric = Number(explicit)
    if (Number.isFinite(numeric) && numeric > 0) return numeric < 100000000000 ? numeric * 1000 : numeric
  }
  return timestampOf({ created_at: link?.created_at ?? link?.createdAt })
}

export function paypalLinkExpiresAtMs(link) {
  const explicit = link?.paypal_expires_at_ts ?? link?.paypalExpiresAtTs ?? link?.expires_at_ts ?? link?.expiresAtTs
  if (explicit !== undefined && explicit !== null && explicit !== '') {
    const numeric = Number(explicit)
    if (Number.isFinite(numeric) && numeric > 0) return numeric < 100000000000 ? numeric * 1000 : numeric
  }
  const createdAt = paypalLinkCreatedAtMs(link)
  return createdAt ? createdAt + PAYPAL_LINK_TTL_MS : 0
}

export function paypalLinkIsActive(link, nowMs = Date.now()) {
  const expiresAt = paypalLinkExpiresAtMs(link)
  return Boolean(expiresAt && expiresAt > nowMs)
}

export function paypalLinkMatchesTimeFilter(link, timeFilter = 'all', nowMs = Date.now()) {
  const filter = String(timeFilter || 'all').trim().toLowerCase()
  if (filter === 'all') return true
  const minutes = Number(filter.replace(/m$/, ''))
  if (!Number.isFinite(minutes) || minutes <= 0) return true
  const createdAt = paypalLinkCreatedAtMs(link)
  return Boolean(createdAt && createdAt >= nowMs - minutes * 60 * 1000)
}

function latestLinksByEmail(links, nowMs = Date.now()) {
  const byEmail = new Map()
  for (const link of Array.isArray(links) ? links : []) {
    const email = normalizeEmail(link?.account_email || link?.accountEmail || link?.email)
    const url = linkUrl(link)
    if (!email || !url) continue
    if (!paypalLinkIsActive(link, nowMs)) continue
    const previous = byEmail.get(email)
    if (!previous || timestampOf(link) >= timestampOf(previous)) byEmail.set(email, link)
  }
  return byEmail
}

export function successfulPayPalLinkAccounts(accounts, links, countryFilter = 'all', options = {}) {
  const nowMs = Number(options.nowMs || Date.now())
  const timeFilter = options.timeFilter || 'all'
  const statusFilter = options.statusFilter || 'all'
  const sortOrder = String(options.sortOrder || 'desc').trim().toLowerCase() === 'asc' ? 'asc' : 'desc'
  const targetCountry = normalizeCountry(countryFilter)
  const byEmail = latestLinksByEmail(
    (Array.isArray(links) ? links : []).filter(link => paypalLinkMatchesTimeFilter(link, timeFilter, nowMs)),
    nowMs,
  )
  return (Array.isArray(accounts) ? accounts : [])
    .map((account) => {
      const email = normalizeEmail(account?.email)
      const link = byEmail.get(email)
      const country = linkCountry(link) || normalizeCountry(account?.paypal_country || account?.paypalCountry)
      return {
        email: String(account?.email || '').trim(),
        country,
        paypalLink: linkUrl(link),
        paypalStatus: statusOf(account),
        account,
        link,
        sortAt: Math.max(timestampOf(account), timestampOf(link)),
      }
    })
    .filter((item) => (
      item.email
      && item.paypalLink
      && item.paypalStatus !== 'paid'
      && statusMatchesFilter(item.paypalStatus, statusFilter)
      && (!targetCountry || targetCountry === 'ALL' || item.country === targetCountry)
    ))
    .sort((a, b) => {
      const delta = sortOrder === 'asc' ? a.sortAt - b.sortAt : b.sortAt - a.sortAt
      return delta || a.email.localeCompare(b.email)
    })
}

export function paypalAccountCountryOptions(accounts, links, options = {}) {
  return Array.from(new Set(successfulPayPalLinkAccounts(accounts, links, 'all', options).map((item) => item.country).filter(Boolean))).sort()
}

export function resolveSelectedPayPalLinkAccount(accounts, links, selectedEmail, options = {}) {
  const target = normalizeEmail(selectedEmail)
  const item = successfulPayPalLinkAccounts(accounts, links, 'all', options).find((candidate) => normalizeEmail(candidate.email) === target)
  if (!item) return null
  return { email: item.email, country: item.country, paypalLink: item.paypalLink }
}
