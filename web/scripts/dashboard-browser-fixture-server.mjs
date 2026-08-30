import { createServer } from 'node:http'
import { existsSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const dist = path.resolve(here, '../../src/autotoken/web/dist')
const port = Number(process.argv[2] || 8799)
const rowCount = Number(process.argv[3] || 20_000)

if (!existsSync(path.join(dist, 'index.html'))) {
  throw new Error(`production build is missing: ${dist}`)
}

const nowSeconds = Math.floor(Date.now() / 1000)
const accounts = Array.from({ length: rowCount }, (_, index) => ({
  email: `benchmark-${index}@example.com`,
  display_email: `Benchmark ${index}`,
  original_email: `benchmark-${index}@example.com`,
  status: index % 11 === 0 ? 'fail' : 'active',
  raw_status: index % 11 === 0 ? 'fail' : 'personal',
  account_type: index % 4 === 0 ? 'plus' : 'free',
  seat_type: index % 4 === 0 ? 'plus' : 'free',
  trial_eligible: index % 13 === 0,
  is_main_account: index === 0,
  created_at: nowSeconds - index * 60,
  registered_at: nowSeconds - index * 60,
  register_at: nowSeconds - index * 60,
  plus_bound_at: index % 4 === 0 ? nowSeconds - index : 0,
  activated_at: nowSeconds - index,
  activation_at: nowSeconds - index,
  upgraded_at: index % 4 === 0 ? nowSeconds - index : 0,
  last_bind_at: index % 3 === 0 ? nowSeconds - index : 0,
  last_bind_provider: index % 3 === 0 ? 'paypal' : '',
  last_bind_status: index % 3 === 0 ? 'success' : '',
  last_bind_task_id: index % 3 === 0 ? `task-${index}` : '',
  last_bind_message: index % 3 === 0 ? 'bound' : '',
  last_bind_failure_stage: '',
  last_checkout_url: index % 3 === 0 ? `https://checkout.example/${index}` : '',
  last_proxy_label: index % 3 === 0 ? `proxy-${index % 20}` : '',
  kakao_link_extracted: index % 9 === 0,
  kakao_link_extracted_at: nowSeconds - index,
  kakao_link_expires_at: nowSeconds - index + 3600,
  kakao_link_cs_id: index % 9 === 0 ? `cs-${index}` : '',
  kakao_link_job_id: index % 9 === 0 ? `job-${index}` : '',
  credentials_exported: index % 5 === 0,
  credentials_exported_at: index % 5 === 0 ? nowSeconds - index : 0,
  account_hub_synced: index % 7 === 0,
  account_hub_synced_at: index % 7 === 0 ? nowSeconds - index : 0,
  hub_source_name: index % 7 === 0 ? 'primary' : '',
  auth_file: `data/auths/benchmark-${index}.json`,
  auth_session_file: `data/auth_session/benchmark-${index}.json`,
  codex_auth_file: `data/auths/benchmark-${index}.json`,
  codex_auth_synthetic: index % 11 === 0,
  has_codex_auth_file: index % 11 !== 0,
  needs_codex_login: index % 11 === 0,
  quota_exhausted_at: index % 10 === 0 ? nowSeconds - index : null,
  quota_resets_at: nowSeconds - index + 18_000,
  last_quota_check_at: nowSeconds - index,
  last_quota: {
    checked_at: nowSeconds - index,
    primary_pct: index % 100,
    primary_resets_at: nowSeconds - index + 18_000,
    primary_window_seconds: 18_000,
    primary_reset_after_seconds: 18_000,
    weekly_pct: (index * 3) % 100,
    weekly_resets_at: nowSeconds - index + 604_800,
    weekly_window_seconds: 604_800,
    weekly_reset_after_seconds: 604_800,
    kakao_link_extracted: index % 9 === 0,
    windows: {
      primary: {
        used_percent: index % 100,
        reset_at: nowSeconds - index + 18_000,
        reset_after_seconds: 18_000,
        limit_window_seconds: 18_000,
      },
      weekly: {
        used_percent: (index * 3) % 100,
        reset_at: nowSeconds - index + 604_800,
        reset_after_seconds: 604_800,
        limit_window_seconds: 604_800,
      },
    },
  },
}))
const accountFields = Object.keys(accounts[0] || {})
const accountPayload = Buffer.from(JSON.stringify({
  fields: accountFields,
  rows: accounts.map(account => accountFields.map(field => account[field])),
}))
const metrics = { accountRequests: 0, requests: [] }

const mimeTypes = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
}

function sendJson(response, value, status = 200) {
  const payload = Buffer.from(JSON.stringify(value))
  response.writeHead(status, {
    'Cache-Control': 'no-store',
    'Content-Length': payload.length,
    'Content-Type': 'application/json; charset=utf-8',
  })
  response.end(payload)
}

function serveStatic(response, pathname) {
  const requested = pathname === '/' ? '/index.html' : pathname
  const resolved = path.resolve(dist, `.${requested}`)
  if (!resolved.startsWith(`${dist}${path.sep}`) || !existsSync(resolved) || !statSync(resolved).isFile()) {
    sendJson(response, { detail: 'not found' }, 404)
    return
  }
  const payload = readFileSync(resolved)
  response.writeHead(200, {
    'Cache-Control': 'no-store',
    'Content-Length': payload.length,
    'Content-Type': mimeTypes[path.extname(resolved)] || 'application/octet-stream',
  })
  response.end(payload)
}

const server = createServer((request, response) => {
  const url = new URL(request.url || '/', `http://${request.headers.host || '127.0.0.1'}`)
  metrics.requests.push(url.pathname)

  if (url.pathname === '/__metrics') {
    sendJson(response, metrics)
    return
  }
  if (url.pathname === '/api/setup/status') {
    sendJson(response, { configured: true })
    return
  }
  if (url.pathname === '/api/auth/check') {
    sendJson(response, { authenticated: true, auth_required: false })
    return
  }
  if (url.pathname === '/api/accounts') {
    metrics.accountRequests += 1
    response.writeHead(200, {
      'Cache-Control': 'no-store',
      'Content-Length': accountPayload.length,
      'Content-Type': 'application/json; charset=utf-8',
    })
    response.end(accountPayload)
    return
  }
  if (url.pathname === '/api/tasks') {
    sendJson(response, [])
    return
  }
  if (url.pathname.startsWith('/api/')) {
    sendJson(response, {})
    return
  }
  serveStatic(response, url.pathname)
})

server.listen(port, '127.0.0.1', () => {
  console.log(`fixture_ready url=http://127.0.0.1:${port}/ rows=${rowCount} payload_bytes=${accountPayload.length}`)
})
