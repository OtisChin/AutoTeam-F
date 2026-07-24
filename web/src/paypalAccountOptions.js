function normalizeCountry(value) {
  return String(value || '').trim().toUpperCase()
}

function normalizeEmail(value) {
  return String(value || '').trim().toLowerCase()
}

function statusOf(account) {
  return String(account?.paypal_status || account?.paypalStatus || account?.status || 'pending').trim().toLowerCase()
}

function linkCountry(link) {
  const billing = link?.billing && typeof link.billing === 'object' ? link.billing : {}
  return normalizeCountry(link?.country || link?.region || billing.country)
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

function latestLinksByEmail(links) {
  const byEmail = new Map()
  for (const link of Array.isArray(links) ? links : []) {
    const email = normalizeEmail(link?.account_email || link?.accountEmail || link?.email)
    const url = linkUrl(link)
    if (!email || !url) continue
    const previous = byEmail.get(email)
    if (!previous || timestampOf(link) >= timestampOf(previous)) byEmail.set(email, link)
  }
  return byEmail
}

export function successfulPayPalLinkAccounts(accounts, links, countryFilter = 'all') {
  const targetCountry = normalizeCountry(countryFilter)
  const byEmail = latestLinksByEmail(links)
  return (Array.isArray(accounts) ? accounts : [])
    .map((account) => {
      const email = normalizeEmail(account?.email)
      const link = byEmail.get(email)
      const country = linkCountry(link) || normalizeCountry(account?.paypal_country || account?.paypalCountry)
      return {
        email: String(account?.email || '').trim(),
        country,
        paypalLink: linkUrl(link),
        account,
        link,
        sortAt: Math.max(timestampOf(account), timestampOf(link)),
      }
    })
    .filter((item) => (
      item.email
      && item.paypalLink
      && statusOf(item.account) === 'success'
      && (!targetCountry || targetCountry === 'ALL' || item.country === targetCountry)
    ))
    .sort((a, b) => b.sortAt - a.sortAt || a.email.localeCompare(b.email))
}

export function paypalAccountCountryOptions(accounts, links) {
  return Array.from(new Set(successfulPayPalLinkAccounts(accounts, links).map((item) => item.country).filter(Boolean))).sort()
}

export function resolveSelectedPayPalLinkAccount(accounts, links, selectedEmail) {
  const target = normalizeEmail(selectedEmail)
  const item = successfulPayPalLinkAccounts(accounts, links).find((candidate) => normalizeEmail(candidate.email) === target)
  if (!item) return null
  return { email: item.email, country: item.country, paypalLink: item.paypalLink }
}
