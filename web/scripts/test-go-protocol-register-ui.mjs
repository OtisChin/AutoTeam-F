import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')
const loadForm = page.slice(page.indexOf('function loadSavedRegisterForm()'), page.indexOf('function saveRegisterForm()'))
const saveForm = page.slice(page.indexOf('function saveRegisterForm()'), page.indexOf('async function reloadRegisterDomains()'))

assert.match(page, /Go 协议注册/, 'page exposes a distinct Go protocol label')
assert.match(page, /registerEngine:\s*'browser'/, 'form uses one engine value')
assert.match(page, /v-model="registerForm\.registerEngine"/, 'engine controls share one model')
for (const engine of ['browser', 'protocol', 'go_protocol', 'roxy', 'cloak']) {
  assert.match(page, new RegExp(`value="${engine}"`), `page exposes ${engine} engine`)
}
assert.match(
  page,
  /go_protocol_register:\s*!isPhoneCpaFlow\.value\s*&&\s*registerForm\.value\.registerEngine\s*===\s*'go_protocol'/,
  'payload sends dedicated Go flag',
)
assert.match(saveForm, /registerEngine:\s*registerForm\.value\.registerEngine/, 'saved form persists the engine')
assert.doesNotMatch(saveForm, /protocolRegister:|useRoxyBrowser:|useCloakBrowser:/, 'saved form drops legacy booleans')
assert.doesNotMatch(page, /v-model="registerForm\.(?:goProtocolRegister|protocolRegister|useRoxyBrowser|useCloakBrowser)"/, 'mode is not represented by independent checkboxes')
assert.doesNotMatch(
  page,
  /registerForm(?:\.value)?\.(?:goProtocolRegister|protocolRegister|useRoxyBrowser|useCloakBrowser)/,
  'rendered behavior never reads removed mode fields',
)

const migrationPrecedence = [
  'REGISTER_ENGINE_VALUES.includes',
  'Boolean(saved.useCloakBrowser)',
  'Boolean(saved.useRoxyBrowser)',
  'Boolean(saved.goProtocolRegister)',
  'Boolean(saved.protocolRegister)',
]
let previousMigrationIndex = -1
for (const token of migrationPrecedence) {
  const index = loadForm.indexOf(token)
  assert.ok(index > previousMigrationIndex, `saved engine migration preserves precedence at ${token}`)
  previousMigrationIndex = index
}

console.log('go protocol register UI tests passed')
