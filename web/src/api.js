const BASE = '/api'

function getApiKey() {
  return localStorage.getItem('autotoken_api_key') || ''
}

export function setApiKey(key) {
  localStorage.setItem('autotoken_api_key', key)
}

export function clearApiKey() {
  localStorage.removeItem('autotoken_api_key')
}

async function request(method, path, body = null) {
  const headers = { 'Content-Type': 'application/json' }
  const key = getApiKey()
  if (key) {
    headers['Authorization'] = `Bearer ${key}`
  }
  const opts = { method, headers }
  if (body) opts.body = JSON.stringify(body)
  const resp = await fetch(`${BASE}${path}`, opts)
  let data
  try {
    data = await resp.json()
  } catch {
    const err = new Error(`HTTP ${resp.status}: 服务器返回了非 JSON 响应`)
    err.status = resp.status
    throw err
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
  return data
}

export const api = {
  checkAuth: () => request('GET', '/auth/check'),
  getSetupStatus: () => request('GET', '/setup/status'),
  saveSetup: (config) => request('POST', '/setup/save', config),

  getStatus: () => request('GET', '/status'),
  getAdminStatus: () => request('GET', '/admin/status'),
  getMainCodexStatus: () => request('GET', '/main-codex/status'),
  getManualAccountStatus: () => request('GET', '/manual-account/status'),
  getAccounts: (options = {}) => {
    const includeSessionStubs = Boolean(options.includeSessionStubs || options.include_session_stubs)
    return request('GET', `/accounts${includeSessionStubs ? '?include_session_stubs=true' : ''}`)
  },
  getActiveAccounts: () => request('GET', '/accounts/active'),
  getStandbyAccounts: () => request('GET', '/accounts/standby'),
  deleteAccount: (email) => request('DELETE', `/accounts/${encodeURIComponent(email)}`),
  deleteAccountsBatch: (emails, continueOnError = true) => request('POST', '/accounts/delete-batch', { emails, continue_on_error: continueOnError }),
  updateAccountType: (email, accountType) => request('POST', `/accounts/${encodeURIComponent(email)}/type`, { account_type: accountType }),
  exportAccountCredentials: (emails) => request('POST', '/accounts/export-credentials', { emails }),
  importAccountCpaAuths: (payload) => request('POST', '/accounts/import-cpa-auths', payload),
  importFinishedAccounts: (payload) => request('POST', '/accounts/import-finished', payload),
  exportAccountCpaAuths: (emails) => request('POST', '/accounts/export-cpa-auths', { emails }),
  exportAccountSubAuths: (emails) => request('POST', '/accounts/export-sub-auths', { emails }),
  convertSessionCpaAuths: (emails) => request('POST', '/accounts/convert-session-cpa-auths', { emails }),
  updateAccountsExportStatus: (emails, exported) => request('POST', '/accounts/export-status', { emails, exported }),
  loginAccount: (email, payload = {}) => request('POST', '/accounts/login', { ...payload, email }),
  loginAccountsBatch: (emails, payload = {}) => request('POST', '/accounts/login-batch', { ...payload, emails }),
  loginMailAccountsAuthSession: (emails) => request('POST', '/mail-accounts/login-auth-session', { emails }),
  refreshAccountsQuota: (emails) => request('POST', '/accounts/refresh-quota', { emails }),
  getCodexAuth: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/codex-auth`),
  getAccountAccessToken: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/access-token`),
  getAccountSubscription: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/subscription`),
  kickAccount: (email) => request('POST', `/accounts/${encodeURIComponent(email)}/kick`),
  getCpaFiles: () => request('GET', '/cpa/files'),
  inspectCpaToSub2Api: (files) => request('POST', '/cpa-to-sub2api/inspect', { files }),
  convertCpaToSub2Api: (payload) => request('POST', '/cpa-to-sub2api/convert', payload),
  openCpaToSub2ApiOutputDir: (outputDir) => request('POST', '/cpa-to-sub2api/open-output-dir', { output_dir: outputDir }),
  selectCpaToSub2ApiOutputDir: (currentDir) => request('POST', '/cpa-to-sub2api/select-output-dir', { current_dir: currentDir }),
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
  submitManualAccountCallback: (redirectUrl) => request('POST', '/manual-account/callback', { redirect_url: redirectUrl }),
  cancelManualAccount: () => request('POST', '/manual-account/cancel'),

  postSync: () => request('POST', '/sync'),
  postSyncFromCpa: () => request('POST', '/sync/from-cpa'),
  postSyncAccounts: () => request('POST', '/sync/accounts'),
  postSyncMainCodex: () => request('POST', '/sync/main-codex'),
  getAccountHubConfig: () => request('GET', '/account-hub/config'),
  saveAccountHubConfig: (config) => request('PUT', '/account-hub/config', config),
  testAccountHub: (config) => request('POST', '/account-hub/test', config),
  syncAccountHub: (emails) => request('POST', '/account-hub/sync', { emails }),
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
  getIdealLinks: () => request('GET', '/ideal/links'),
  deleteIdealLinks: (ids) => request('POST', '/ideal/links/delete', { ids }),
  clearIdealLinks: () => request('POST', '/ideal/links/clear'),
  startIdealLongLink: (payload) => request('POST', '/ideal/long-link/start', payload),
  getIdealLongLinkJob: (jobId) => request('GET', `/ideal/long-link/jobs/${encodeURIComponent(jobId)}`),
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
  submitBrazilPixPayment: (payload) => request('POST', '/brazil-pix/payment/submit', payload),
  getBrazilPixPaymentJob: (jobId, token) => request('GET', `/brazil-pix/payment/jobs/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token)}`),
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
  submitIndiaUpiPayment: (payload) => request('POST', '/india-upi/payment/submit', payload),
  getIndiaUpiPaymentJob: (jobId, token) => request('GET', `/india-upi/payment/jobs/${encodeURIComponent(jobId)}?token=${encodeURIComponent(token)}`),
  getUsPaypalAccounts: () => request('GET', '/us-paypal/accounts'),
  deleteUsPaypalAccount: (email) => request('DELETE', `/us-paypal/accounts/${encodeURIComponent(email)}`),
  deleteUsPaypalAccounts: (emails) => request('POST', '/us-paypal/accounts/delete', { emails }),
  startUsPaypal: (payload) => request('POST', '/us-paypal/start', payload),
  startUsPaypalBatch: (payload) => request('POST', '/us-paypal/batch/start', payload),
  getUsPaypalJob: (jobId) => request('GET', `/us-paypal/jobs/${encodeURIComponent(jobId)}`),
  cancelUsPaypalJob: (jobId) => request('POST', `/us-paypal/jobs/${encodeURIComponent(jobId)}/cancel`),
  startUsPaypalProtocol: (payload) => request('POST', '/us-paypal/protocol/start', payload),
  startUsPaypalProtocolBatch: (payload) => request('POST', '/us-paypal/protocol/batch/start', payload),
  getUsPaypalProtocolJob: (jobId) => request('GET', `/us-paypal/protocol/jobs/${encodeURIComponent(jobId)}`),
  cancelUsPaypalProtocolJob: (jobId) => request('POST', `/us-paypal/protocol/jobs/${encodeURIComponent(jobId)}/cancel`),
  getUsPaypalLinks: () => request('GET', '/us-paypal/links'),
  deleteUsPaypalLinks: (ids) => request('POST', '/us-paypal/links/delete', { ids }),
  clearUsPaypalLinks: () => request('POST', '/us-paypal/links/clear'),
  getIdealQrBlob: async (value) => {
    const headers = { 'Content-Type': 'application/json' }
    const key = getApiKey()
    if (key) headers['Authorization'] = `Bearer ${key}`
    const resp = await fetch('/api/ideal/qr', {
      method: 'POST',
      headers,
      body: JSON.stringify({ value }),
    })
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

  getWhatsAppOtpStatus: () => request('GET', '/whatsapp-otp/status'),
  startWhatsAppOtp: (payload = {}) => request('POST', '/whatsapp-otp/start', payload),
  stopWhatsAppOtp: () => request('POST', '/whatsapp-otp/stop'),
  clearWhatsAppOtp: () => request('POST', '/whatsapp-otp/clear'),
  getLatestWhatsAppOtp: () => request('GET', '/whatsapp-otp/latest'),

  getTasks: (detail = false) => request('GET', `/tasks${detail ? '?detail=true' : ''}`),
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
  setRegisterDomain: (domain, verify = true) => request('PUT', '/config/register-domain', { domain, verify }),
  setRegisterDomains: (domains, selected = null) => request('PUT', '/config/register-domains', { domains, selected }),
  getLogs: (limit = 1000, since = 0) => request('GET', `/logs?limit=${limit}&since=${since}`),

  getRegisterFailures: (limit = 50) => request('GET', `/register-failures?limit=${limit}`),

  getTeamMembers: () => request('GET', '/team/members'),
  removeTeamMember: (payload) => request('POST', '/team/members/remove', payload),
  generateBindLink: (payload) => request('POST', '/bind/link', payload),
  openBindLinkWithAuthSession: (payload) => request('POST', '/bind/link/open', payload),
  getCardPool: (poolType) => request('GET', `/card-pool/${encodeURIComponent(poolType)}`),
  importCardPool: (payload) => request('POST', '/card-pool/import', payload),
  deleteCardPoolItems: (payload) => request('POST', '/card-pool/delete', payload),
  updateCardPoolItem: (payload) => request('POST', '/card-pool/update', payload),
  redeemCardPoolItem: (payload) => request('POST', '/card-pool/redeem', payload),
  redeemCardPoolItems: (payload) => request('POST', '/card-pool/redeem-batch', payload),
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
  checkMailAccounts: (emails) => request('POST', '/mail-accounts/check', { emails }),
  fetchMailAccounts: (emails) => request('POST', '/mail-accounts/fetch', { emails }),
  updateMailAccountStatus: (emails, status) => request('POST', '/mail-accounts/status', { emails, status }),
  updateMailAccountNote: (emails, note) => request('POST', '/mail-accounts/note', { emails, note }),
  changeMailAccountPassword: (emails, newPassword) => request('POST', '/mail-accounts/change-password', { emails, newPassword }),
  exportMailAccounts: () => request('GET', '/mail-accounts/export'),
}
