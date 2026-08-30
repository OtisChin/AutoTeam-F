import { createServer } from 'node:http'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const dist = path.resolve(here, '../../src/autotoken/web/dist')
const port = Number(process.argv[2] || process.env.FRONTEND_FIXTURE_PORT || 8799)
const rowCount = Math.max(0, Number(process.argv[3] || process.env.FRONTEND_FIXTURE_ROWS || 20_000))
if (!existsSync(path.join(dist, 'index.html'))) throw new Error(`production build is missing: ${dist}`)

const now = Math.floor(Date.now() / 1000)
const accounts = Array.from({ length: rowCount }, (_, index) => ({
  email: `fixture-${index}@example.com`,
  display_email: `Fixture ${index}`,
  original_email: `fixture-${index}@example.com`,
  status: index % 11 === 0 ? 'fail' : 'active',
  raw_status: index % 11 === 0 ? 'fail' : 'personal',
  account_type: index % 4 === 0 ? 'plus' : 'free',
  seat_type: index % 4 === 0 ? 'plus' : 'free',
  trial_eligible: index % 13 === 0,
  is_main_account: index === 0,
  created_at: now - index * 60,
  registered_at: now - index * 60,
  register_at: now - index * 60,
  plus_bound_at: index % 4 === 0 ? now - index : 0,
  activated_at: now - index,
  activation_at: now - index,
  upgraded_at: index % 4 === 0 ? now - index : 0,
  last_bind_at: index % 3 === 0 ? now - index : 0,
  last_bind_provider: index % 3 === 0 ? 'paypal' : '',
  last_bind_status: index % 3 === 0 ? 'success' : '',
  last_bind_task_id: index % 3 === 0 ? `task-${index}` : '',
  last_bind_message: index % 3 === 0 ? 'bound' : '',
  last_bind_failure_stage: '',
  last_checkout_url: index % 3 === 0 ? `https://checkout.example/${index}` : '',
  last_proxy_label: index % 3 === 0 ? `proxy-${index % 20}` : '',
  kakao_link_extracted: index % 9 === 0,
  kakao_link_extracted_at: now - index,
  kakao_link_expires_at: now - index + 3600,
  kakao_link_cs_id: index % 9 === 0 ? `cs-${index}` : '',
  kakao_link_job_id: index % 9 === 0 ? `job-${index}` : '',
  credentials_exported: index % 5 === 0,
  credentials_exported_at: index % 5 === 0 ? now - index : 0,
  account_hub_synced: index % 7 === 0,
  account_hub_synced_at: index % 7 === 0 ? now - index : 0,
  hub_source_name: index % 7 === 0 ? 'fixture' : '',
  auth_file: `data/auths/fixture-${index}.json`,
  auth_session_file: `data/auth_session/fixture-${index}.json`,
  codex_auth_file: `data/auths/fixture-${index}.json`,
  codex_auth_synthetic: index % 11 === 0,
  has_codex_auth_file: index % 11 !== 0,
  needs_codex_login: index % 11 === 0,
  quota_exhausted_at: index % 10 === 0 ? now - index : null,
  quota_resets_at: now - index + 18_000,
  last_quota_check_at: now - index,
  last_quota: {
    checked_at: now - index,
    primary_pct: index % 100,
    primary_resets_at: now - index + 18_000,
    primary_window_seconds: 18_000,
    primary_reset_after_seconds: 18_000,
    weekly_pct: (index * 3) % 100,
    weekly_resets_at: now - index + 604_800,
    weekly_window_seconds: 604_800,
    weekly_reset_after_seconds: 604_800,
    kakao_link_extracted: index % 9 === 0,
    windows: {
      primary: { used_percent: index % 100, reset_at: now - index + 18_000, reset_after_seconds: 18_000, limit_window_seconds: 18_000 },
      weekly: { used_percent: (index * 3) % 100, reset_at: now - index + 604_800, reset_after_seconds: 604_800, limit_window_seconds: 604_800 },
    },
  },
}))
const fields = Object.keys(accounts[0] || {})
const accountPayload = Buffer.from(JSON.stringify({ fields, rows: accounts.map(account => fields.map(field => account[field])) }))
const etag = `"fixture-${rowCount}-${accountPayload.length}"`
const state = { configured: true, authenticated: true, authRequired: false, activeTask: false, modal: '' }
const metrics = { accountRequests: 0, apiRequests: 0, requests: [], startedAt: Date.now() }

const mimeTypes = { '.css': 'text/css; charset=utf-8', '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2' }
function sendJson(response, value, status = 200, headers = {}) {
  const payload = Buffer.from(JSON.stringify(value))
  response.writeHead(status, { 'Cache-Control': 'no-store', 'Content-Length': payload.length, 'Content-Type': 'application/json; charset=utf-8', ...headers })
  response.end(payload)
}
function readBody(request) {
  return new Promise(resolve => {
    let body = ''
    request.on('data', chunk => { body += chunk })
    request.on('end', () => { try { resolve(body ? JSON.parse(body) : {}) } catch { resolve({}) } })
  })
}
function emptyList() { return { items: [], total: 0 } }
function genericApi(pathname, method) {
  // API methods pass paths relative to /api; the HTTP server sees the
  // /api prefix. Normalize it once so every fixture branch matches the
  // contract consumed by the Vue pages.
  const route = pathname.replace(/^\/api(?=\/|$)/, '') || '/'
  if (route === '/tasks' || route === '/tasks/') return []
  if (route === '/logs' || route === '/register-failures') return route === '/logs' ? { logs: [], boot_id: 'fixture-boot' } : []
  if (route === '/team/members') return { members: [] }
  if (route === '/trade/summary') return { stock_available: 0, stock_exported: 0, stock_discarded: 0, stock_missing_credentials: 0, cdk_active: 0, cdk_exhausted: 0, cdk_revoked: 0 }
  if (route.startsWith('/trade/cdks')) return route === '/trade/cdks' ? { items: [] } : {}
  if (route === '/oauth-phone-pool') return { items: [], total: 0 }
  if (route === '/oauth-phone-records') return { items: [], total: 0, success_count: 0, active_count: 0, cancelled_count: 0, failed_count: 0 }
  if (route === '/mail-accounts' || route === '/mail-accounts/pool-status') return route.endsWith('pool-status') ? { total: 0 } : { items: [], total: 0 }
  if (/\/accounts$/.test(route)) return []
  if (route.includes('/cpa/files')) return { files: [] }
  if (route.includes('/config/')) return {}
  if (route.includes('/admin/status') || route.includes('/main-codex/status') || route.includes('/manual-account/status')) return {}
  if (route.includes('/ideal/') || route.includes('/brazil-pix/') || route.includes('/india-upi/') || route.includes('/kakao-pay/') || route.includes('/momo-vn/') || route.includes('/gcash-ph/') || route.includes('/us-paypal/')) {
    if (route.endsWith('/accounts') || route.endsWith('/links')) return []
    return { status: 'idle', items: [] }
  }
  if (method === 'GET') return {}
  return { ok: true }
}
function serveStatic(response, pathname) {
  const requested = pathname === '/' ? '/index.html' : pathname
  const resolved = path.resolve(dist, `.${requested}`)
  if (!resolved.startsWith(`${dist}${path.sep}`) || !existsSync(resolved) || !statSync(resolved).isFile()) { response.writeHead(404); response.end(); return }
  const payload = readFileSync(resolved)
  response.writeHead(200, { 'Cache-Control': 'no-store', 'Content-Length': payload.length, 'Content-Type': mimeTypes[path.extname(resolved)] || 'application/octet-stream' })
  response.end(payload)
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`)
  metrics.requests.push(url.pathname)
  if (url.pathname.startsWith('/api/')) metrics.apiRequests += 1
  if (url.pathname === '/__metrics') { sendJson(response, { ...metrics, requests: [...metrics.requests] }); return }
  if (url.pathname === '/__fixture/state') {
    if (request.method === 'POST') Object.assign(state, await readBody(request))
    sendJson(response, state)
    return
  }
  if (url.pathname === '/favicon.ico') { response.writeHead(204); response.end(); return }
  if (url.pathname === '/api/setup/status') { sendJson(response, { configured: Boolean(state.configured) }); return }
  if (url.pathname === '/api/auth/check') {
    if (!state.authenticated) { sendJson(response, { authenticated: false, auth_required: true }, 401); return }
    sendJson(response, { authenticated: true, auth_required: Boolean(state.authRequired) }); return
  }
  if (url.pathname === '/api/accounts') {
    metrics.accountRequests += 1
    if (request.headers['if-none-match'] === etag) { response.writeHead(304, { ETag: etag, 'Cache-Control': 'no-store' }); response.end(); return }
    response.writeHead(200, { ETag: etag, 'Cache-Control': 'no-store', 'Content-Length': accountPayload.length, 'Content-Type': 'application/json; charset=utf-8' }); response.end(accountPayload); return
  }
  if (url.pathname === '/api/status') { sendJson(response, { status: 'ok' }); return }
  if (url.pathname === '/api/ideal/qr') { response.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'no-store' }); response.end(Buffer.from('89504e470d0a1a0a', 'hex')); return }
  if (url.pathname.startsWith('/api/')) { sendJson(response, genericApi(url.pathname, request.method)); return }
  serveStatic(response, url.pathname)
})

server.listen(port, '127.0.0.1', () => console.log(`fixture_ready url=http://127.0.0.1:${port}/ rows=${rowCount} payload_bytes=${accountPayload.length}`))
process.on('SIGTERM', () => server.close(() => process.exit(0)))
process.on('SIGINT', () => server.close(() => process.exit(0)))
