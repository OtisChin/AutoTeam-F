import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const dashboardSource = readFileSync(path.resolve(here, '../src/components/Dashboard.vue'), 'utf8')

assert.match(dashboardSource, /accountsError:\s*\{/, 'Dashboard should accept the account load failure state')
assert.match(dashboardSource, /lastSuccessfulAt:\s*\{/, 'Dashboard should accept the last successful snapshot timestamp')
assert.match(dashboardSource, /v-if="accountsError"[^>]*class="dashboard-stale-warning"/, 'an old snapshot should stay visible with a stale warning')
assert.match(dashboardSource, /v-else-if="accountsError"[^>]*role="alert"/, 'a first-load failure should render a visible alert instead of a blank workspace')
assert.match(dashboardSource, /emit\(['"]retry-accounts['"]\)/, 'the failure state should expose a direct retry action')
assert.match(dashboardSource, /账号数据加载失败/, 'the first-load error should explain what failed')
assert.match(dashboardSource, /保留上次成功数据/, 'stale-snapshot copy should explain that existing rows remain available')

console.log('dashboard account load state tests passed')
