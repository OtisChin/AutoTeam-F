import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const navigation = readFileSync(new URL('../src/navigation.js', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const icons = readFileSync(new URL('../src/components/NavIcon.vue', import.meta.url), 'utf8')
const team = readFileSync(new URL('../src/components/TeamMembers.vue', import.meta.url), 'utf8')
assert.match(navigation, /key:\s*['"]team['"]/) 
assert.match(app, /team:\s*\(\)\s*=>\s*import\(['"]\.\/components\/TeamMembers\.vue['"]\)/)
assert.match(app, /currentPage === ['"]team['"]/) 
assert.match(icons, /team:\s*\[/)
for (const tag of ['UiPageHeader', 'UiMetricSummary', 'UiTableFrame', 'UiStatusBadge', 'UiStatePanel', 'AccessibleModal']) assert.match(team, new RegExp(`<${tag}\\b`))
assert.match(team, /createSessionStorageFacade/); assert.match(team, /state="partial"/); assert.doesNotMatch(team, /window\.confirm/)
assert.doesNotMatch(team.split('<script setup>')[0], /\b(?:bg|border)-(?:gray|slate)-(?:950|900|800)\b/)
console.log('operations team UI contracts passed')
