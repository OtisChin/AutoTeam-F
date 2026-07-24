export const PAYMENT_RETRYABLE_LINK_STATUSES = new Set(['pending', 'imported', 'needs_action'])
export const TEMP_CDK_COOLDOWN_MS = 3 * 60 * 1000

export function paymentPairUnavailableMessage({ hasUsableLink = false, hasAvailableCdk = false } = {}) {
  if (!hasUsableLink) return '没有可提交的已提取 UPI 链接（链接为空或已失效）'
  if (!hasAvailableCdk) return '没有可用的 UPI-SCAN CDK'
  return '没有可提交的已提取 UPI 链接'
}

export function indiaUpiCdkStatusClass(status) {
  const text = String(status || 'available')
  if (text === 'reserved') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (text === 'cooling') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (text === 'used') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (text === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
}

function timestampMs(value) {
  if (value === null || value === undefined || value === '') return 0
  if (typeof value === 'number') return value > 10_000_000_000 ? value : value * 1000
  const raw = String(value || '').trim()
  if (!raw) return 0
  if (/^\d+$/.test(raw)) return timestampMs(Number(raw))
  const parsed = Date.parse(raw.includes('T') ? raw : raw.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : 0
}

function normalizePaymentUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

export function extractedLinkPaymentSeed(link, { nowMs = Date.now(), ttlMs = 5 * 60 * 1000, makeId = () => `upi-${nowMs}` } = {}) {
  if (!link || typeof link !== 'object') return null
  const value = normalizePaymentUrl(link.value || link.upi_link || link.hosted_instructions_url || link.link || link.url || '')
  if (!value) return null
  const createdAtTs = link.created_at_ts || link.createdAtTs || 0
  const explicitExpiresAt = timestampMs(link.upi_expires_at_ts ?? link.upiExpiresAtTs ?? link.upiExpiresAt)
  const createdExpiresAt = timestampMs(createdAtTs) ? timestampMs(createdAtTs) + ttlMs : 0
  const expiresAt = explicitExpiresAt || createdExpiresAt
  if (!expiresAt || expiresAt <= nowMs) return null
  return {
    id: `link-${link.id || makeId()}`,
    value,
    paymentUri: String(link.paymentUri || link.upi_payment_uri || link.qr_image_url_svg || link.qr_image_url_png || '').trim(),
    status: 'pending',
    accountEmail: String(link.account_email || link.accountEmail || '').trim(),
    created_at: link.created_at || link.createdAt || '',
    created_at_ts: createdAtTs,
    upi_expires_at_ts: link.upi_expires_at_ts || link.upiExpiresAtTs || link.upiExpiresAt || 0,
  }
}

export function isTempCdkCoolingError(error) {
  const text = String(error?.error || error?.message || error || '').trim().toLowerCase()
  return Boolean(error?.cdk_cooling)
    || text.includes('cdk is already running in another task')
    || text.includes('cdk already running in another task')
    || text.includes('cdk is running in another task')
    || text.includes('already running in another task')
    || text.includes('cdk 正在其他任务中运行')
    || text.includes('cdk正在其他任务中运行')
}

export function tempCdkCooldownUntil(nowMs = Date.now(), error = {}) {
  const seconds = Number(error?.cdk_cooldown_seconds || 0)
  const duration = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : TEMP_CDK_COOLDOWN_MS
  return Number(nowMs || Date.now()) + duration
}

export function tempCdkRemainingText(cooldownUntilMs, nowMs = Date.now()) {
  const remaining = Math.max(0, Number(cooldownUntilMs || 0) - Number(nowMs || 0))
  if (!remaining) return ''
  const seconds = Math.ceil(remaining / 1000)
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `冷却 ${minutes}:${String(rest).padStart(2, '0')}`
}
