import { fetchWithTimeout } from './request.js'
import { PAYMENT_CANCEL_TIMEOUT_MS, PAYMENT_STATUS_TIMEOUT_MS, PAYMENT_SUBMIT_TIMEOUT_MS } from './paymentRequestState.js'

const BASE = '/api'
export const MAX_BROWSER_TIMER_DELAY_MS = 2_147_483_647
export const ACCOUNT_DATA_NOT_MODIFIED = Symbol('ACCOUNT_DATA_NOT_MODIFIED')

const dashboardAccountEtags = new Map()
let apiKeyMemory = null

export function serialOperationTimeoutMs(items, perItemMs, minimumMs, overheadMs = 10_000) {
  const count = Array.isArray(items) ? Math.max(1, items.length) : 1
  const derivedTimeoutMs = Math.max(Number(minimumMs || 0), count * Number(perItemMs || 0) + Number(overheadMs || 0))
  return Math.min(MAX_BROWSER_TIMER_DELAY_MS, derivedTimeoutMs)
}

export function getApiKey() {
  if (apiKeyMemory !== null) return apiKeyMemory
  try {
    apiKeyMemory = localStorage.getItem('autotoken_api_key') || ''
  } catch {
    apiKeyMemory = ''
  }
  return apiKeyMemory
}

export function setApiKey(key) {
  dashboardAccountEtags.clear()
  apiKeyMemory = String(key || '')
  try {
    localStorage.setItem('autotoken_api_key', apiKeyMemory)
    return true
  } catch {
    return false
  }
}

export function clearApiKey() {
  dashboardAccountEtags.clear()
  apiKeyMemory = ''
  try {
    localStorage.removeItem('autotoken_api_key')
    return true
  } catch {
    return false
  }
}

export function invalidateApiKeyMemory() {
  dashboardAccountEtags.clear()
  apiKeyMemory = ''
}

async function request(method, path, body = null, options = {}) {
  const {
    signal,
    headers: additionalHeaders = {},
    cache,
    apiKey: apiKeyOverride,
    notModifiedValue,
    onResponse,
    ...runtimeOptions
  } = options
  const headers = { 'Content-Type': 'application/json', ...additionalHeaders }
  const key = apiKeyOverride === undefined ? getApiKey() : String(apiKeyOverride || '')
  if (key) {
    headers['Authorization'] = `Bearer ${key}`
  }
  const opts = { method, headers }
  if (signal) opts.signal = signal
  if (cache) opts.cache = cache
  if (body) opts.body = JSON.stringify(body)
  const { resp, data } = await fetchWithTimeout(`${BASE}${path}`, opts, {
    ...runtimeOptions,
    consume: async resp => {
      if (resp.status === 304) return { resp, data: null }
      try {
        return { resp, data: await resp.json() }
      } catch {
        const err = new Error(`HTTP ${resp.status}: 服务器返回了非 JSON 响应`)
        err.status = resp.status
        throw err
      }
    },
  })
  if (resp.status === 304 && Object.prototype.hasOwnProperty.call(options, 'notModifiedValue')) {
    return notModifiedValue
  }
  if (!resp.ok) {
    let msg = data?.detail?.message || data?.detail || `HTTP ${resp.status}`
    if (typeof msg === 'object') {
      try {
        msg = JSON.stringify(msg)
      } catch {
        msg = String(msg)
      }
    }
    const err = new Error(msg)
    err.status = resp.status
    err.data = data
    err.code = data?.detail?.code || data?.code || ''
    throw err
  }
  if (typeof onResponse === 'function') onResponse(resp, data)
  return data
}

export const api = {
  checkAuth: (apiKey) => request('GET', '/auth/check', null, apiKey === undefined ? {} : { apiKey }),
  getSetupStatus: () => request('GET', '/setup/status'),
  saveSetup: (config) => request('POST', '/setup/save', config),

  getStatus: () => request('GET', '/status'),
  getAdminStatus: (options = {}) => request('GET', '/admin/status', null, options),
  getMainCodexStatus: (options = {}) => request('GET', '/main-codex/status', null, options),
  getManualAccountStatus: (options = {}) => request('GET', '/manual-account/status', null, options),
  getAccounts: (options = {}) => {
    const includeSessionStubs = options.includeSessionStubs ?? options.include_session_stubs
    const params = new URLSearchParams()
    if (includeSessionStubs !== undefined) {
      params.set('include_session_stubs', includeSessionStubs ? 'true' : 'false')
    }
    const view = String(options.view || '').trim().toLowerCase()
    if (view) params.set('view', view)
    const requestOptions = {
      ...(Number.isFinite(options.timeoutMs) ? { timeoutMs: options.timeoutMs } : {}),
      ...(options.signal ? { signal: options.signal } : {}),
    }
    if (view === 'dashboard') {
      const etagKey = `${getApiKey()}\u0000${includeSessionStubs === false ? 'false' : 'true'}`
      const etag = dashboardAccountEtags.get(etagKey)
      Object.assign(requestOptions, {
        cache: 'no-store',
        headers: etag ? { 'If-None-Match': etag } : {},
        notModifiedValue: ACCOUNT_DATA_NOT_MODIFIED,
        onResponse(response) {
          const nextEtag = String(response?.headers?.get?.('etag') || '').trim()
          if (nextEtag) dashboardAccountEtags.set(etagKey, nextEtag)
        },
      })
    }
    const query = params.toString()
    return request('GET', `/accounts${query ? `?${query}` : ''}`, null, requestOptions)
  },
  getActiveAccounts: () => request('GET', '/accounts/active'),
  getStandbyAccounts: () => request('GET', '/accounts/standby'),
  deleteAccount: (email) => request('DELETE', `/accounts/${encodeURIComponent(email)}`, null, { timeoutMs: 320_000 }),
  deleteAccountsBatch: (emails, continueOnError = true) => request('POST', '/accounts/delete-batch', { emails, continue_on_error: continueOnError }, { timeoutMs: serialOperationTimeoutMs(emails, 30_000, 320_000, 140_000) }),
  updateAccountType: (email, accountType) => request('POST', `/accounts/${encodeURIComponent(email)}/type`, { account_type: accountType }),
  updateAccountMetadata: (email, payload) => request('PATCH', `/accounts/${encodeURIComponent(email)}/metadata`, payload),
  updateAccountsMetadataBatch: (payload) => request('PATCH', '/accounts/metadata-batch', payload),
  exportAccountCredentials: (emails) => request('POST', '/accounts/export-credentials', { emails }),
  importExternalAccounts: (text) => request('POST', '/accounts/import-external', { text }),
  importAccountCpaAuths: (payload) => request('POST', '/accounts/import-cpa-auths', payload),
  importFinishedAccounts: (payload) => request('POST', '/accounts/import-finished', payload),
  exportAccountCpaAuths: (emails) => request('POST', '/accounts/export-cpa-auths', { emails }, { timeoutMs: 0 }),
  exportAccountSubAuths: (emails) => request('POST', '/accounts/export-sub-auths', { emails }, { timeoutMs: 0 }),
  convertSessionCpaAuths: (emails) => request('POST', '/accounts/convert-session-cpa-auths', { emails }),
  updateAccountsExportStatus: (emails, exported) => request('POST', '/accounts/export-status', { emails, exported }),
  loginAccount: (email, payload = {}) => request('POST', '/accounts/login', { ...payload, email }),
  loginAccountsBatch: (emails, payload = {}) => request('POST', '/accounts/login-batch', { ...payload, emails }),
  appendLoginAccountsBatch: (emails, taskId = '') => request('POST', '/accounts/login-batch/append', { emails, task_id: taskId }),
  loginMailAccountsAuthSession: (emails) => request('POST', '/mail-accounts/login-auth-session', { emails }),
  refreshAccountsQuota: (emails) => request('POST', '/accounts/refresh-quota', { emails }),
  getCodexAuth: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/codex-auth`),
  getAccountAccessToken: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/access-token`),
  exportAccountAccessTokens: (emails) => request('POST', '/accounts/export-access-tokens', { emails }),
  getAccountSubscription: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/subscription`, null, { timeoutMs: 270_000 }),
  getAccountLatestMail: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/latest-mail`, null, { timeoutMs: 0 }),
  kickAccount: (email) => request('POST', `/accounts/${encodeURIComponent(email)}/kick`, null, { timeoutMs: 320_000 }),
  getCpaFiles: () => request('GET', '/cpa/files'),
  inspectCpaToSub2Api: (files) => request('POST', '/cpa-to-sub2api/inspect', { files }),
  convertCpaToSub2Api: (payload) => request('POST', '/cpa-to-sub2api/convert', payload),
  openCpaToSub2ApiOutputDir: (outputDir) => request('POST', '/cpa-to-sub2api/open-output-dir', { output_dir: outputDir }),
  selectCpaToSub2ApiOutputDir: (currentDir) => request('POST', '/cpa-to-sub2api/select-output-dir', { current_dir: currentDir }, { timeoutMs: 0 }),
  getCpaToSub2ApiDefaultOutputDir: () => request('GET', '/cpa-to-sub2api/default-output-dir'),

  startAdminLogin: (email) => request('POST', '/admin/login/start', { email }),
  submitAdminSession: (email, sessionToken) => request('POST', '/admin/login/session', { email, session_token: sessionToken }),
  submitAdminPassword: (password) => request('POST', '/admin/login/password', { password }),
  submitAdminCode: (code) => request('POST', '/admin/login/code', { code }),
  submitAdminWorkspace: (optionId) => request('POST', '/admin/login/workspace', { option_id: optionId }),
  cancelAdminLogin: () => request('POST', '/admin/login/cancel'),
  logoutAdmin: () => request('POST', '/admin/logout'),
  startMainCodexSync: () => request('POST', '/main-codex/start'),
  submitMainCodexPassword: (password) => request('POST', '/main-codex/password', { password }),
  submitMainCodexCode: (code) => request('POST', '/main-codex/code', { code }),
  cancelMainCodexSync: () => request('POST', '/main-codex/cancel'),
  startManualAccount: (email = '') => request('POST', '/manual-account/start', { email }),
  submitManualAccountCallback: (redirectUrl) => request('POST', '/manual-account/callback', { redirect_url: redirectUrl }, { timeoutMs: 140_000 }),
  cancelManualAccount: () => request('POST', '/manual-account/cancel'),

  postSync: () => request('POST', '/sync', null, { timeoutMs: 0 }),
  postSyncFromCpa: () => request('POST', '/sync/from-cpa', null, { timeoutMs: 0 }),
  postSyncAccounts: () => request('POST', '/sync/accounts', null, { timeoutMs: 320_000 }),
  postSyncMainCodex: () => request('POST', '/sync/main-codex'),
  getAccountHubConfig: () => request('GET', '/account-hub/config'),
  saveAccountHubConfig: (config) => request('PUT', '/account-hub/config', config),
  testAccountHub: (config) => request('POST', '/account-hub/test', config),
  syncAccountHub: (emails) => request('POST', '/account-hub/sync', { emails }, { timeoutMs: serialOperationTimeoutMs(emails, 65_000, 80_000) }),
  getTradeSummary: () => request('GET', '/trade/summary'),
  getTradeCdks: (limit = 200) => request('GET', `/trade/cdks?limit=${encodeURIComponent(limit)}`),
  createTradeCdk: (quotaTotal, note = '') => request('POST', '/trade/cdks', { quota_total: quotaTotal, note }),
  getTradeCdk: (code) => request('GET', `/trade/cdks/${encodeURIComponent(code)}`),
  revokeTradeCdk: (code) => request('POST', `/trade/cdks/${encodeURIComponent(code)}/revoke`),
  downloadTradeCdkRedemptions: (code) => request('GET', `/trade/cdks/${encodeURIComponent(code)}/redemptions/download`),

  startRotate: (target = 5) => request('POST', '/tasks/rotate', { target }),
  startCheck: () => request('POST', '/tasks/check'),
  startAdd: (payload = {}) => request('POST', '/tasks/add', payload),
  startFill: (target = 5) => request('POST', '/tasks/fill', { target, leave_workspace: false }),
  startCleanup: (maxSeats = null) => request('POST', '/tasks/cleanup', { max_seats: maxSeats }),
  startBindCard: (payload) => request('POST', '/tasks/bind-card', payload),
  startGoPayBind: (payload) => request('POST', '/tasks/gopay-bind', payload),
  getIdealAccounts: () => request('GET', '/ideal/accounts'),
  deleteIdealAccount: (email) => request('DELETE', `/ideal/accounts/${encodeURIComponent(email)}`),
  deleteIdealAccounts: (emails) => request('POST', '/ideal/accounts/delete', { emails }),
  startIdealBatch: (payload) => request('POST', '/ideal/batch/start', payload),
  getIdealJob: (jobId) => request('GET', `/ideal/jobs/${encodeURIComponent(jobId)}`),
  cancelIdealJob: (jobId) => request('POST', `/ideal/jobs/${encodeURIComponent(jobId)}/cancel`),
  releaseIdealUnknownJob: (jobId) => request('POST', `/ideal/jobs/${encodeURIComponent(jobId)}/reconcile-release`),
  getIdealLinks: () => request('GET', '/ideal/links'),
  deleteIdealLinks: (ids) => request('POST', '/ideal/links/delete', { ids }),
  clearIdealLinks: () => request('POST', '/ideal/links/clear'),
  startIdealLongLink: (payload) => request('POST', '/ideal/long-link/start', payload),
  getIdealLongLinkJob: (jobId) => request('GET', `/ideal/long-link/jobs/${encodeURIComponent(jobId)}`),
  getIdealLongLinkJobByClientRequest: (clientRequestId) => request('GET', `/ideal/long-link/jobs/by-client-request/${encodeURIComponent(clientRequestId)}`),
  testIdealProxyChain: (payload) => request('POST', '/ideal/proxy-chain-test', payload),
  getBrazilPixAccounts: () => request('GET', '/brazil-pix/accounts'),
  deleteBrazilPixAccount: (email) => request('DELETE', `/brazil-pix/accounts/${encodeURIComponent(email)}`),
  deleteBrazilPixAccounts: (emails) => request('POST', '/brazil-pix/accounts/delete', { emails }),
  startBrazilPix: (payload) => request('POST', '/brazil-pix/start', payload),
  startBrazilPixBatch: (payload) => request('POST', '/brazil-pix/batch/start', payload),
  startBrazilPixTempBatch: (payload) => request('POST', '/brazil-pix/temp/batch/start', payload),
  getBrazilPixTempCdkStatus: (payload) => request('POST', '/brazil-pix/temp/cdk/status', payload),
  getBrazilPixJob: (jobId) => request('GET', `/brazil-pix/jobs/${encodeURIComponent(jobId)}`),
  cancelBrazilPixJob: (jobId) => request('POST', `/brazil-pix/jobs/${encodeURIComponent(jobId)}/cancel`),
  getBrazilPixLinks: () => request('GET', '/brazil-pix/links'),
  deleteBrazilPixLinks: (ids) => request('POST', '/brazil-pix/links/delete', { ids }),
  clearBrazilPixLinks: () => request('POST', '/brazil-pix/links/clear'),
  submitBrazilPixPayment: (payload) => request('POST', '/brazil-pix/payment/submit', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  getBrazilPixPaymentJob: (jobId, token) => request('GET', `/brazil-pix/payment/jobs/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  getIndiaUpiAccounts: () => request('GET', '/india-upi/accounts'),
  deleteIndiaUpiAccount: (email) => request('DELETE', `/india-upi/accounts/${encodeURIComponent(email)}`),
  deleteIndiaUpiAccounts: (emails) => request('POST', '/india-upi/accounts/delete', { emails }),
  startIndiaUpi: (payload) => request('POST', '/india-upi/start', payload),
  startIndiaUpiBatch: (payload) => request('POST', '/india-upi/batch/start', payload),
  startIndiaUpiTempBatch: (payload) => request('POST', '/india-upi/temp/batch/start', payload),
  getIndiaUpiJob: (jobId) => request('GET', `/india-upi/jobs/${encodeURIComponent(jobId)}`),
  cancelIndiaUpiJob: (jobId) => request('POST', `/india-upi/jobs/${encodeURIComponent(jobId)}/cancel`),
  getIndiaUpiLinks: () => request('GET', '/india-upi/links'),
  deleteIndiaUpiLinks: (ids) => request('POST', '/india-upi/links/delete', { ids }),
  clearIndiaUpiLinks: () => request('POST', '/india-upi/links/clear'),
  submitIndiaUpiPayment: (payload) => request('POST', '/india-upi/payment/submit', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  getIndiaUpiPaymentJob: (jobId, token) => request('GET', `/india-upi/payment/jobs/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  getKakaoPayAccounts: () => request('GET', '/kakao-pay/accounts'),
  deleteKakaoPayAccount: (email) => request('DELETE', `/kakao-pay/accounts/${encodeURIComponent(email)}`),
  deleteKakaoPayAccounts: (emails) => request('POST', '/kakao-pay/accounts/delete', { emails }),
  startKakaoPay: (payload) => request('POST', '/kakao-pay/start', payload),
  startKakaoPayBatch: (payload) => request('POST', '/kakao-pay/batch/start', payload),
  startKakaoPayTempBatch: (payload) => request('POST', '/kakao-pay/temp/batch/start', payload),
  getKakaoPayJob: (jobId) => request('GET', `/kakao-pay/jobs/${encodeURIComponent(jobId)}`),
  cancelKakaoPayJob: (jobId) => request('POST', `/kakao-pay/jobs/${encodeURIComponent(jobId)}/cancel`),
  getKakaoPayLinks: () => request('GET', '/kakao-pay/links'),
  deleteKakaoPayLinks: (ids) => request('POST', '/kakao-pay/links/delete', { ids }),
  clearKakaoPayLinks: () => request('POST', '/kakao-pay/links/clear'),
  createKakaoPayTempOrder: (payload) => request('POST', '/kakao-pay/temp/orders', payload),
  getKakaoPayTempOrder: (orderId, cdk, channel = 'masi') => request('GET', `/kakao-pay/temp/orders/${encodeURIComponent(orderId)}?cdk=${encodeURIComponent(cdk)}&channel=${encodeURIComponent(channel)}`),
  getKakaoPayTempTicketStatus: (cdk, channel = 'masi') => request('GET', `/kakao-pay/temp/tickets/status?cdk=${encodeURIComponent(cdk)}&channel=${encodeURIComponent(channel)}`),
  createKakaoPayKkPaymentOrder: (payload) => request('POST', '/kakao-pay/kk-payment/orders', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  submitKakaoPayKkPayment: (payload) => request('POST', '/kakao-pay/kk-payment/submit', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  getKakaoPayKkPaymentCdkStatus: (cdk) => request('GET', `/kakao-pay/kk-payment/cdk/status?cdk=${encodeURIComponent(cdk)}`),
  getKakaoPayKkPaymentOrder: (orderId, token = '', cdk = '', accountEmail = '') => request('GET', `/kakao-pay/kk-payment/orders/${encodeURIComponent(orderId)}?token=${encodeURIComponent(token)}&cdk=${encodeURIComponent(cdk)}&accountEmail=${encodeURIComponent(accountEmail)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  getMomoVnAccounts: () => request('GET', '/momo-vn/accounts'),
  deleteMomoVnAccount: (email) => request('DELETE', `/momo-vn/accounts/${encodeURIComponent(email)}`),
  deleteMomoVnAccounts: (emails) => request('POST', '/momo-vn/accounts/delete', { emails }),
  startMomoVn: (payload) => request('POST', '/momo-vn/start', payload),
  startMomoVnBatch: (payload) => request('POST', '/momo-vn/batch/start', payload),
  getMomoVnJob: (jobId) => request('GET', `/momo-vn/jobs/${encodeURIComponent(jobId)}`),
  cancelMomoVnJob: (jobId) => request('POST', `/momo-vn/jobs/${encodeURIComponent(jobId)}/cancel`),
  getMomoVnLinks: () => request('GET', '/momo-vn/links'),
  deleteMomoVnLinks: (ids) => request('POST', '/momo-vn/links/delete', { ids }),
  clearMomoVnLinks: () => request('POST', '/momo-vn/links/clear'),
  getGCashPhAccounts: () => request('GET', '/gcash-ph/accounts'),
  deleteGCashPhAccount: (email) => request('DELETE', `/gcash-ph/accounts/${encodeURIComponent(email)}`),
  deleteGCashPhAccounts: (emails) => request('POST', '/gcash-ph/accounts/delete', { emails }),
  startGCashPh: (payload) => request('POST', '/gcash-ph/start', payload),
  startGCashPhBatch: (payload) => request('POST', '/gcash-ph/batch/start', payload),
  getGCashPhJob: (jobId) => request('GET', `/gcash-ph/jobs/${encodeURIComponent(jobId)}`),
  cancelGCashPhJob: (jobId) => request('POST', `/gcash-ph/jobs/${encodeURIComponent(jobId)}/cancel`),
  getGCashPhLinks: () => request('GET', '/gcash-ph/links'),
  deleteGCashPhLinks: (ids) => request('POST', '/gcash-ph/links/delete', { ids }),
  clearGCashPhLinks: () => request('POST', '/gcash-ph/links/clear'),
  getUsPaypalAccounts: () => request('GET', '/us-paypal/accounts'),
  deleteUsPaypalAccount: (email) => request('DELETE', `/us-paypal/accounts/${encodeURIComponent(email)}`),
  deleteUsPaypalAccounts: (emails) => request('POST', '/us-paypal/accounts/delete', { emails }),
  startUsPaypal: (payload) => request('POST', '/us-paypal/start', payload),
  startUsPaypalBatch: (payload) => request('POST', '/us-paypal/batch/start', payload),
  getUsPaypalJob: (jobId) => request('GET', `/us-paypal/jobs/${encodeURIComponent(jobId)}`),
  cancelUsPaypalJob: (jobId) => request('POST', `/us-paypal/jobs/${encodeURIComponent(jobId)}/cancel`),
  startUsPaypalProtocol: (payload) => request('POST', '/us-paypal/protocol/start', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  startUsPaypalProtocolBatch: (payload) => request('POST', '/us-paypal/protocol/batch/start', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  getUsPaypalProtocolJob: (jobId) => request('GET', `/us-paypal/protocol/jobs/${encodeURIComponent(jobId)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  getUsPaypalProtocolJobByClientRequest: (clientRequestId) => request('GET', `/us-paypal/protocol/jobs/by-client-request/${encodeURIComponent(clientRequestId)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  cancelUsPaypalProtocolJob: (jobId) => request('POST', `/us-paypal/protocol/jobs/${encodeURIComponent(jobId)}/cancel`),
  startUsPaypal153Batch: (payload) => request('POST', '/us-paypal/pay153/batch/start', payload, { timeoutMs: PAYMENT_SUBMIT_TIMEOUT_MS }),
  getUsPaypal153Job: (jobId) => request('GET', `/us-paypal/pay153/jobs/${encodeURIComponent(jobId)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  getUsPaypal153JobByClientRequest: (clientRequestId) => request('GET', `/us-paypal/pay153/jobs/by-client-request/${encodeURIComponent(clientRequestId)}`, null, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  cancelUsPaypal153Job: (jobId) => request('POST', `/us-paypal/pay153/jobs/${encodeURIComponent(jobId)}/cancel`, null, { timeoutMs: PAYMENT_CANCEL_TIMEOUT_MS }),
  cancelUsPaypal153RemoteByBa: (payload) => request('POST', '/us-paypal/pay153/remote/cancel-by-ba', payload, { timeoutMs: PAYMENT_CANCEL_TIMEOUT_MS }),
  releaseUsPaypalPaymentOccupancy: (payload) => request('POST', '/us-paypal/payment-jobs/reconcile-release', payload, { timeoutMs: PAYMENT_STATUS_TIMEOUT_MS }),
  submitUsPaypal153Otp: (jobId, payload) => request('POST', `/us-paypal/pay153/jobs/${encodeURIComponent(jobId)}/otp`, payload, { timeoutMs: 40_000 }),
  submitUsPaypal153Captcha: (jobId, payload) => request('POST', `/us-paypal/pay153/jobs/${encodeURIComponent(jobId)}/captcha`, payload, { timeoutMs: 40_000 }),
  getUsPaypal153SupportedCountries: () => request('GET', '/us-paypal/pay153/supported-countries'),
  getUsPaypal153Stats: () => request('GET', '/us-paypal/pay153/stats'),
  getUsPaypalLinks: () => request('GET', '/us-paypal/links'),
  deleteUsPaypalLinks: (ids) => request('POST', '/us-paypal/links/delete', { ids }),
  clearUsPaypalLinks: () => request('POST', '/us-paypal/links/clear'),
  getIdealQrBlob: async (value, options = {}) => {
    const headers = { 'Content-Type': 'application/json' }
    const key = getApiKey()
    if (key) headers['Authorization'] = `Bearer ${key}`
    return fetchWithTimeout('/api/ideal/qr', {
      method: 'POST',
      headers,
      body: JSON.stringify({ value }),
    }, {
      ...options,
      consume: async resp => {
        if (!resp.ok) {
          let message = `HTTP ${resp.status}`
          try {
            const data = await resp.json()
            message = data?.detail || message
          } catch {}
          throw new Error(message)
        }
        return resp.blob()
      },
    })
  },

  getWhatsAppOtpStatus: () => request('GET', '/whatsapp-otp/status'),
  startWhatsAppOtp: (payload = {}) => request('POST', '/whatsapp-otp/start', payload),
  stopWhatsAppOtp: () => request('POST', '/whatsapp-otp/stop'),
  clearWhatsAppOtp: () => request('POST', '/whatsapp-otp/clear'),
  getLatestWhatsAppOtp: () => request('GET', '/whatsapp-otp/latest'),

  getTasks: (detail = false, options = {}) => request('GET', `/tasks${detail ? '?detail=true' : ''}`, null, options),
  getTask: (id) => request('GET', `/tasks/${id}`),
  cancelTask: (params = null) => request('POST', '/tasks/cancel', params),
  skipCurrentTask: () => request('POST', '/tasks/skip-current'),
  updateGoPayRuntimeControl: (payload) => request('POST', '/tasks/gopay/runtime-control', payload),

  getAutoCheckConfig: () => request('GET', '/config/auto-check'),
  setAutoCheckConfig: (cfg) => request('PUT', '/config/auto-check', cfg),
  getAutoRefreshQuotaConfig: () => request('GET', '/config/auto-refresh-quota'),
  setAutoRefreshQuotaConfig: (cfg) => request('PUT', '/config/auto-refresh-quota', cfg),
  getMailProviderConfig: () => request('GET', '/config/mail-provider'),
  saveMailProviderConfig: (cfg) => request('PUT', '/config/mail-provider', cfg),
  importOutlookAccounts: (content, filename = '') => request('POST', '/config/outlook-accounts/import', { content, filename }),
  getOutlookAccountsStatus: () => request('GET', '/config/outlook-accounts/status'),
  deleteOutlookAccounts: (emails) => request('POST', '/config/outlook-accounts/delete', { emails }),
  importICloudAccounts: (content, filename = '') => request('POST', '/config/icloud-accounts/import', { content, filename }),
  getICloudAccountsStatus: (includeAll = false) => request('GET', `/config/icloud-accounts/status${includeAll ? '?include_all=true' : ''}`),
  deleteICloudAccounts: (emails) => request('POST', '/config/icloud-accounts/delete', { emails }),
  importGenericApiAccounts: (content, filename = '') => request('POST', '/config/generic-api-accounts/import', { content, filename }),
  getGenericApiAccountsStatus: (includeAll = false) => request('GET', `/config/generic-api-accounts/status${includeAll ? '?include_all=true' : ''}`),
  deleteGenericApiAccounts: (emails) => request('POST', '/config/generic-api-accounts/delete', { emails }),
  getGoPayAutoSignupConfig: () => request('GET', '/config/gopay-auto-signup'),
  saveGoPayAutoSignupConfig: (cfg) => request('PUT', '/config/gopay-auto-signup', cfg),
  queryGoPayHeroSmsPrices: (cfg) => request('POST', '/config/gopay-auto-signup/hero-sms/prices', cfg),
  queryGoPaySmsbowerPrices: (cfg) => request('POST', '/config/gopay-auto-signup/smsbower/prices', cfg),
  queryGoPaySmscodePrices: (cfg) => request('POST', '/config/gopay-auto-signup/smscode/prices', cfg),
  getOAuthPhoneSmsConfig: () => request('GET', '/config/oauth-phone-sms'),
  getOAuthPhoneSmsCountries: (provider = '') => request('GET', `/config/oauth-phone-sms/countries${provider ? `?provider=${encodeURIComponent(provider)}` : ''}`),
  saveOAuthPhoneSmsConfig: (cfg) => request('PUT', '/config/oauth-phone-sms', cfg),
  getRekberinajaConfig: () => request('GET', '/config/rekberinaja'),
  saveRekberinajaConfig: (cfg) => request('PUT', '/config/rekberinaja', cfg),
  getRoxyBrowserConfig: () => request('GET', '/config/roxybrowser'),
  getRoxyBrowserWorkspaces: () => request('GET', '/config/roxybrowser/workspaces'),
  getRoxyBrowserProfiles: () => request('GET', '/config/roxybrowser/profiles'),
  saveRoxyBrowserConfig: (cfg) => request('PUT', '/config/roxybrowser', cfg),
  exportConfig: () => request('GET', '/config/export'),
  importConfig: (payload) => request('POST', '/config/import', payload),

  getRegisterDomain: () => request('GET', '/config/register-domain'),
  setRegisterDomain: (domain, verify = true) => request('PUT', '/config/register-domain', { domain, verify }, { timeoutMs: verify ? 360_000 : 20_000 }),
  setRegisterDomains: (domains, selected = null) => request('PUT', '/config/register-domains', { domains, selected }),
  getLogs: (limit = 1000, since = 0, sinceId = 0, sinceBootId = '') => request('GET', `/logs?limit=${limit}&since=${since}&since_id=${sinceId}&since_boot_id=${encodeURIComponent(sinceBootId)}`),

  getRegisterFailures: (limit = 50) => request('GET', `/register-failures?limit=${limit}`),

  getTeamMembers: () => request('GET', '/team/members', null, { timeoutMs: 320_000 }),
  removeTeamMember: (payload) => request('POST', '/team/members/remove', payload, { timeoutMs: 320_000 }),
  generateBindLink: (payload) => request('POST', '/bind/link', payload, { timeoutMs: payload?.checkout_flow === 'plus_trial' ? 0 : 110_000 }),
  openBindLinkWithAuthSession: (payload) => request('POST', '/bind/link/open', payload, { timeoutMs: 0 }),
  getCardPool: (poolType) => request('GET', `/card-pool/${encodeURIComponent(poolType)}`),
  importCardPool: (payload) => request('POST', '/card-pool/import', payload),
  deleteCardPoolItems: (payload) => request('POST', '/card-pool/delete', payload),
  updateCardPoolItem: (payload) => request('POST', '/card-pool/update', payload),
  redeemCardPoolItem: (payload) => request('POST', '/card-pool/redeem', payload, { timeoutMs: serialOperationTimeoutMs([payload], 35_000, 45_000) }),
  redeemCardPoolItems: (payload) => request('POST', '/card-pool/redeem-batch', payload, { timeoutMs: serialOperationTimeoutMs(payload?.item_ids, 35_000, 45_000) }),
  fetchCardPoolSms: (url) => request('POST', '/card-pool/fetch-sms', { url }),
  getOAuthPhonePool: () => request('GET', '/oauth-phone-pool'),
  getOAuthPhoneRecords: (limit = 300) => request('GET', `/oauth-phone-records?limit=${encodeURIComponent(limit)}`),
  importOAuthPhonePool: (text) => request('POST', '/oauth-phone-pool/import', { text }),
  saveOAuthPhonePoolItem: (item) => item?.id
    ? request('PUT', `/oauth-phone-pool/${encodeURIComponent(item.id)}`, item)
    : request('POST', '/oauth-phone-pool', item),
  deleteOAuthPhonePoolItems: (ids) => request('POST', '/oauth-phone-pool/delete', { ids }),

  getMailAccounts: () => request('GET', '/mail-accounts'),
  importMailAccounts: (text, options = {}) => request('POST', '/mail-accounts/import', { text, ...options }),
  getMailAccountsPoolStatus: () => request('GET', '/mail-accounts/pool-status'),
  syncMailAccountsToAccountPool: (emails = []) => request('POST', '/mail-accounts/sync-account-pool', { emails }),
  saveMailAccount: (item, originalEmail = '') => originalEmail
    ? request('PUT', `/mail-accounts/${encodeURIComponent(originalEmail)}`, item)
    : request('POST', '/mail-accounts', item),
  deleteMailAccounts: (emails) => request('POST', '/mail-accounts/delete', { emails }),
  clearMailAccounts: () => request('POST', '/mail-accounts/clear'),
  checkMailAccounts: (emails) => request('POST', '/mail-accounts/check', { emails }, { timeoutMs: serialOperationTimeoutMs(emails, 35_000, 45_000) }),
  fetchMailAccounts: (emails) => request('POST', '/mail-accounts/fetch', { emails }, { timeoutMs: serialOperationTimeoutMs(emails, 800_000, 810_000) }),
  updateMailAccountStatus: (emails, status) => request('POST', '/mail-accounts/status', { emails, status }),
  updateMailAccountNote: (emails, note) => request('POST', '/mail-accounts/note', { emails, note }),
  changeMailAccountPassword: (emails, newPassword) => request('POST', '/mail-accounts/change-password', { emails, newPassword }, { timeoutMs: serialOperationTimeoutMs(emails, 160_000, 180_000) }),
  exportMailAccounts: () => request('GET', '/mail-accounts/export'),
}
