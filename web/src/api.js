const BASE = '/api'

function getApiKey() {
  return localStorage.getItem('autoteam_api_key') || ''
}

export function setApiKey(key) {
  localStorage.setItem('autoteam_api_key', key)
}

export function clearApiKey() {
  localStorage.removeItem('autoteam_api_key')
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
  exportAccountCredentials: (emails, lineFormat) => request('POST', '/accounts/export-credentials', { emails, line_format: lineFormat }),
  exportAccountCpaAuths: (emails) => request('POST', '/accounts/export-cpa-auths', { emails }),
  exportAccountSubAuths: (emails) => request('POST', '/accounts/export-sub-auths', { emails }),
  convertSessionCpaAuths: (emails) => request('POST', '/accounts/convert-session-cpa-auths', { emails }),
  updateAccountsExportStatus: (emails, exported) => request('POST', '/accounts/export-status', { emails, exported }),
  loginAccount: (email) => request('POST', '/accounts/login', { email }),
  loginAccountsBatch: (emails) => request('POST', '/accounts/login-batch', { emails }),
  refreshAccountsQuota: (emails) => request('POST', '/accounts/refresh-quota', { emails }),
  getCodexAuth: (email) => request('GET', `/accounts/${encodeURIComponent(email)}/codex-auth`),
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

  startRotate: (target = 5) => request('POST', '/tasks/rotate', { target }),
  startCheck: () => request('POST', '/tasks/check'),
  startAdd: (payload = {}) => request('POST', '/tasks/add', payload),
  startFill: (target = 5) => request('POST', '/tasks/fill', { target, leave_workspace: false }),
  startFillPersonal: (count = 1) => request('POST', '/tasks/fill', { target: count, leave_workspace: true }),
  startCleanup: (maxSeats = null) => request('POST', '/tasks/cleanup', { max_seats: maxSeats }),
  startBindCard: (payload) => request('POST', '/tasks/bind-card', payload),
  startGoPayBind: (payload) => request('POST', '/tasks/gopay-bind', payload),
  startPayPal: (payload) => request('POST', '/tasks/paypal', payload),
  getWhatsAppOtpStatus: () => request('GET', '/whatsapp-otp/status'),
  startWhatsAppOtp: (payload = {}) => request('POST', '/whatsapp-otp/start', payload),
  stopWhatsAppOtp: () => request('POST', '/whatsapp-otp/stop'),
  clearWhatsAppOtp: () => request('POST', '/whatsapp-otp/clear'),
  getLatestWhatsAppOtp: () => request('GET', '/whatsapp-otp/latest'),

  getTasks: (detail = false) => request('GET', `/tasks${detail ? '?detail=true' : ''}`),
  getTask: (id) => request('GET', `/tasks/${id}`),
  cancelTask: (params = null) => request('POST', '/tasks/cancel', params),
  skipCurrentTask: () => request('POST', '/tasks/skip-current'),

  getAutoCheckConfig: () => request('GET', '/config/auto-check'),
  setAutoCheckConfig: (cfg) => request('PUT', '/config/auto-check', cfg),
  getAutoRefreshQuotaConfig: () => request('GET', '/config/auto-refresh-quota'),
  setAutoRefreshQuotaConfig: (cfg) => request('PUT', '/config/auto-refresh-quota', cfg),
  getMailProviderConfig: () => request('GET', '/config/mail-provider'),
  saveMailProviderConfig: (cfg) => request('PUT', '/config/mail-provider', cfg),
  importOutlookAccounts: (content, filename = '') => request('POST', '/config/outlook-accounts/import', { content, filename }),
  getGoPayAutoSignupConfig: () => request('GET', '/config/gopay-auto-signup'),
  saveGoPayAutoSignupConfig: (cfg) => request('PUT', '/config/gopay-auto-signup', cfg),
  getRekberinajaConfig: () => request('GET', '/config/rekberinaja'),
  saveRekberinajaConfig: (cfg) => request('PUT', '/config/rekberinaja', cfg),
  exportConfig: () => request('GET', '/config/export'),
  importConfig: (payload) => request('POST', '/config/import', payload),

  getRegisterDomain: () => request('GET', '/config/register-domain'),
  setRegisterDomain: (domain, verify = true) => request('PUT', '/config/register-domain', { domain, verify }),
  setRegisterDomains: (domains, selected = null) => request('PUT', '/config/register-domains', { domains, selected }),
  getLogs: (limit = 100, since = 0) => request('GET', `/logs?limit=${limit}&since=${since}`),

  getRegisterFailures: (limit = 50) => request('GET', `/register-failures?limit=${limit}`),

  getTeamMembers: () => request('GET', '/team/members'),
  removeTeamMember: (payload) => request('POST', '/team/members/remove', payload),
  generateBindLink: (payload) => request('POST', '/bind/link', payload),
  getCardPool: (poolType) => request('GET', `/card-pool/${encodeURIComponent(poolType)}`),
  importCardPool: (payload) => request('POST', '/card-pool/import', payload),
  deleteCardPoolItems: (payload) => request('POST', '/card-pool/delete', payload),
  updateCardPoolItem: (payload) => request('POST', '/card-pool/update', payload),
  redeemCardPoolItem: (payload) => request('POST', '/card-pool/redeem', payload),
  redeemCardPoolItems: (payload) => request('POST', '/card-pool/redeem-batch', payload),
  fetchCardPoolSms: (url) => request('POST', '/card-pool/fetch-sms', { url }),
}
