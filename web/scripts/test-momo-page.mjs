import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const sidebar = readFileSync(new URL('../src/components/Sidebar.vue', import.meta.url), 'utf8')
const dashboard = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')
const momoPage = readFileSync(new URL('../src/components/MomoPage.vue', import.meta.url), 'utf8')

assert.match(api, /getMomoVnAccounts:\s*\(\)\s*=>\s*request\('GET',\s*'\/momo-vn\/accounts'\)/, 'API exposes MoMo VN accounts route')
assert.match(api, /startMomoVnBatch:\s*\(payload\)\s*=>\s*request\('POST',\s*'\/momo-vn\/batch\/start',\s*payload\)/, 'API exposes MoMo VN batch start route')
assert.match(api, /getMomoVnJob:\s*\(jobId\)\s*=>\s*request\('GET',\s*`\/momo-vn\/jobs\/\$\{encodeURIComponent\(jobId\)\}`\)/, 'API exposes MoMo VN job query route')
assert.match(api, /getMomoVnLinks:\s*\(\)\s*=>\s*request\('GET',\s*'\/momo-vn\/links'\)/, 'API exposes MoMo VN links route')

assert.match(app, /import MomoPage from '\.\/components\/MomoPage\.vue'/, 'App registers Momo page component import')
assert.match(app, /<MomoPage v-else-if="currentPage === 'momoVn'"/, 'App renders Momo page for momoVn route')
assert.match(app, /'momoVn'/, 'App page key list includes momoVn')

assert.match(sidebar, /key: 'momoVn'[\s\S]*label: '越南MoMo'/, 'Sidebar exposes 越南MoMo navigation entry')

assert.match(dashboard, /momo_vn:\s*'MoMo'/, 'Dashboard renders MoMo binding provider label')
assert.match(dashboard, /momo_vn:\s*'bg-pink-500\/10 text-pink-300'/, 'Dashboard renders MoMo binding provider color class')

assert.match(momoPage, /仅检测资格/, 'Momo page renders qualification-only button')
assert.match(momoPage, /startQualificationOnly\(/, 'Momo page exposes qualification-only action')
assert.match(momoPage, /qualificationOnly:\s*qualificationOnly/, 'Qualification-only action sends qualificationOnly payload field')
assert.match(momoPage, /api\.startMomoVnBatch\(\{[\s\S]*qualificationOnly:/, 'Momo page starts MoMo batch jobs through dedicated API')
assert.match(momoPage, /accountVisibleCount\s*=\s*ref\(100\)/, 'Momo account pool initially renders only 100 accounts')
assert.match(momoPage, /visibleAccounts\s*=\s*computed\(\(\)\s*=>\s*filteredAccounts\.value\.slice\(0,\s*accountVisibleCount\.value\)\)/, 'Momo account table renders visible account slice')
assert.match(momoPage, /v-for="account in visibleAccounts"/, 'Momo account table uses visibleAccounts instead of full filteredAccounts')
assert.match(momoPage, /hiddenAccountCount\s*>\s*0[\s\S]*加载更多/, 'Momo account table exposes load-more footer')
assert.match(momoPage, /watch\(\[accountFilter,\s*accountStatusFilter\],[\s\S]*accountVisibleCount\.value\s*=\s*100/, 'Momo account filters reset visible account count')
