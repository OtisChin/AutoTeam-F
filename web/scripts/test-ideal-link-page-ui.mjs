import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import assert from 'node:assert/strict'

const root = resolve(import.meta.dirname, '..')
const page = readFileSync(resolve(root, 'src/components/IdealLinkPage.vue'), 'utf8')
const api = readFileSync(resolve(root, 'src/api.js'), 'utf8')

for (const text of ['荷兰iDEAL 提链', '账号池选择', '已提取 iDEAL 链接', '开始提链']) {
  assert(page.includes(text), `IdealLinkPage should render ${text}`)
}

for (const symbol of ['accounts', 'links', 'selectedEmails', 'start', 'refreshLinks']) {
  assert(page.includes(symbol), `IdealLinkPage should manage ${symbol}`)
}

for (const helper of ['getIdealAccounts', 'startIdealBatch', 'getIdealJob', 'cancelIdealJob', 'getIdealLinks', 'deleteIdealLinks', 'clearIdealLinks']) {
  assert(api.includes(helper), `api.js should expose ${helper}`)
}

console.log('ideal link page UI contract passed')
