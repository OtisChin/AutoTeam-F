import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const fixturePort = 8809
const browserPort = 9229
const userDataDir = mkdtempSync(join(tmpdir(), 'autotoken-2fa-browser-'))
const here = dirname(fileURLToPath(import.meta.url))
const children = []

function spawnChild(command, args, options = {}) {
  const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'], ...options })
  children.push(child)
  return child
}

function waitForOutput(child, pattern, timeoutMs = 10_000) {
  return new Promise((resolve, reject) => {
    let output = ''
    const timer = setTimeout(() => reject(new Error(`timeout waiting for ${pattern}: ${output}`)), timeoutMs)
    const onData = chunk => {
      output += chunk.toString()
      if (pattern.test(output)) {
        clearTimeout(timer)
        resolve(output)
      }
    }
    child.stdout.on('data', onData)
    child.stderr.on('data', onData)
    child.once('exit', code => {
      clearTimeout(timer)
      reject(new Error(`process exited with ${code}: ${output}`))
    })
  })
}

function browserPath() {
  const candidates = [
    join(process.env['ProgramFiles(x86)'] || '', 'Microsoft/Edge/Application/msedge.exe'),
    join(process.env.ProgramFiles || '', 'Microsoft/Edge/Application/msedge.exe'),
    join(process.env.LOCALAPPDATA || '', 'Google/Chrome/Application/chrome.exe'),
    join(process.env.ProgramFiles || '', 'Google/Chrome/Application/chrome.exe'),
    join(process.env['ProgramFiles(x86)'] || '', 'Google/Chrome/Application/chrome.exe'),
  ]
  return candidates.find(candidate => candidate && existsSync(candidate))
}

async function waitForJson(url, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url)
      if (response.ok) return response.json()
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw lastError || new Error(`timeout fetching ${url}`)
}

function createCdpClient(wsUrl) {
  const ws = new WebSocket(wsUrl)
  let id = 0
  const pending = new Map()
  const sessions = new Map()

  ws.addEventListener('message', event => {
    const message = JSON.parse(String(event.data || '{}'))
    const key = message.sessionId ? `${message.sessionId}:${message.id}` : String(message.id)
    const callbacks = pending.get(key)
    if (callbacks) {
      pending.delete(key)
      if (message.error) callbacks.reject(new Error(message.error.message || JSON.stringify(message.error)))
      else callbacks.resolve(message.result || {})
      return
    }
    if (message.method === 'Target.attachedToTarget' && message.params?.sessionId) {
      sessions.set(message.params.targetInfo?.targetId, message.params.sessionId)
    }
  })

  return new Promise((resolve, reject) => {
    ws.addEventListener('open', () => {
      resolve({
        send(method, params = {}, sessionId = '') {
          const nextId = ++id
          const payload = sessionId ? { id: nextId, method, params, sessionId } : { id: nextId, method, params }
          const key = sessionId ? `${sessionId}:${nextId}` : String(nextId)
          const promise = new Promise((resolve, reject) => pending.set(key, { resolve, reject }))
          ws.send(JSON.stringify(payload))
          return promise
        },
        sessionForTarget(targetId) {
          return sessions.get(targetId)
        },
        close() {
          ws.close()
        },
      })
    }, { once: true })
    ws.addEventListener('error', reject, { once: true })
  })
}

async function main() {
  const fixture = spawnChild(process.execPath, [join(here, 'dashboard-browser-fixture-server.mjs'), String(fixturePort), '12'])
  await waitForOutput(fixture, /fixture_ready/)

  const executable = browserPath()
  assert.ok(executable, 'Chrome or Edge executable is required for browser verification')
  const browser = spawnChild(executable, [
    '--headless=new',
    '--disable-gpu',
    '--no-first-run',
    '--no-default-browser-check',
    `--user-data-dir=${userDataDir}`,
    `--remote-debugging-port=${browserPort}`,
    'about:blank',
  ])
  await waitForJson(`http://127.0.0.1:${browserPort}/json/version`)

  const { webSocketDebuggerUrl } = await waitForJson(`http://127.0.0.1:${browserPort}/json/version`)
  const cdp = await createCdpClient(webSocketDebuggerUrl)
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' })
  await cdp.send('Target.attachToTarget', { targetId, flatten: true })
  const deadline = Date.now() + 5000
  let sessionId = ''
  while (!sessionId && Date.now() < deadline) {
    sessionId = cdp.sessionForTarget(targetId) || ''
    if (!sessionId) await new Promise(resolve => setTimeout(resolve, 50))
  }
  assert.ok(sessionId, 'CDP target session should attach')

  await cdp.send('Runtime.enable', {}, sessionId)
  await cdp.send('Page.enable', {}, sessionId)
  await cdp.send('Page.navigate', { url: `http://127.0.0.1:${fixturePort}/` }, sessionId)

  const expression = `new Promise(async (resolve, reject) => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const waitFor = async (fn, label, timeout = 8000) => {
      const end = Date.now() + timeout;
      let value;
      while (Date.now() < end) {
        value = await fn();
        if (value) return value;
        await sleep(100);
      }
      throw new Error('timeout: ' + label);
    };
    try {
      const enabledButton = await waitFor(() => [...document.querySelectorAll('button')]
        .find(button => button.textContent.trim() === '已设置'), 'enabled 2FA button');
      enabledButton.click();
      await waitFor(() => document.body.textContent.includes('2FA 验证码'), '2FA dialog');
      await waitFor(() => document.body.textContent.includes('JBSWY3DPEHPK3PXP')
        && document.body.textContent.includes('399592'), 'secret and code');
      const dialog = [...document.querySelectorAll('[role="dialog"]')].find(element => element.textContent.includes('2FA 验证码'));
      const refreshButton = [...dialog.querySelectorAll('button')]
        .find(button => button.textContent.trim() === '刷新');
      refreshButton.click();
      await waitFor(async () => {
        const metrics = await fetch('/__metrics').then(r => r.json());
        return metrics.requests.filter(path => path.includes('/2fa/totp')).length >= 2 ? metrics : null;
      }, 'refresh request');
      const metrics = await fetch('/__metrics').then(r => r.json());
      resolve({
        ok: true,
        enabledButtonText: enabledButton.textContent.trim(),
        hasDialog: document.body.textContent.includes('2FA 验证码'),
        hasSecret: document.body.textContent.includes('JBSWY3DPEHPK3PXP'),
        hasCode: document.body.textContent.includes('399592'),
        totpRequests: metrics.requests.filter(path => path.includes('/2fa/totp')).length,
      });
    } catch (error) {
      reject(error);
    }
  })`
  const result = await cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }, sessionId)
  if (result.exceptionDetails) {
    throw new Error(result.exceptionDetails.text || 'browser verification failed')
  }
  const value = result.result?.value
  assert.equal(value.ok, true)
  assert.equal(value.enabledButtonText, '已设置')
  assert.equal(value.hasDialog, true)
  assert.equal(value.hasSecret, true)
  assert.equal(value.hasCode, true)
  assert.ok(value.totpRequests >= 2, 'refresh should request the latest TOTP details again')
  cdp.close()
  console.log('dashboard 2FA TOTP view browser regression passed')
}

try {
  await main()
} finally {
  for (const child of children.reverse()) {
    if (!child.killed) child.kill()
  }
  try {
    rmSync(userDataDir, { recursive: true, force: true })
  } catch {
    // best-effort cleanup for browser temp profile
  }
}
