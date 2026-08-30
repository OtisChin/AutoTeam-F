import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
const workspace = read('settings/SettingsWorkspace.vue')
const group = read('settings/SettingsGroup.vue')
const settings = read('Settings.vue')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

for (const id of ['appearance', 'accounts', 'phone', 'payments', 'integrations', 'automation', 'maintenance']) {
  assert.match(settings, new RegExp(`id=["']${id}["']`), `missing settings group ${id}`)
}
assert.match(settings, /<ThemeSwitcher\s+mode="group"/)
for (const key of ['ArrowUp', 'ArrowDown', 'Home', 'End']) assert.match(workspace, new RegExp(key))
assert.match(workspace, /update:modelValue/)
assert.match(workspace, /role=["']tablist["']/)
assert.match(workspace, /role=["']tabpanel["']/)
assert.match(group, /disclosure/)
assert.match(group, /tone.*warning.*danger/s)
assert.match(settings, /defineEmits\(\[[^\]]*navigate/)
assert.match(settings, /emit\(['"]navigate['"],\s*['"]logs['"]\)/)
assert.match(app, /<Settings[\s\S]*@navigate="navigateTo"/)
for (const fn of ['loadOAuthPhoneSmsConfig', 'saveOAuthPhoneSmsConfig', 'exportConfig', 'importConfig', 'loadAccountHubConfig', 'saveAccountHub', 'loadRegisterDomains', 'saveRegisterDomains']) {
  assert.match(settings, new RegExp(`function ${fn}`), `${fn} must remain owned by Settings`)
}
console.log('settings workspace regression passed')
