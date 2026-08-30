import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../src')
const ui = path.join(src, 'components/ui')
const required = [
  'UiMetricSummary.vue',
  'UiDataToolbar.vue',
  'UiBatchBar.vue',
  'UiPagination.vue',
  'UiTableFrame.vue',
]
for (const name of required) assert.ok(existsSync(path.join(ui, name)), `${name} should exist`)

const presentationPath = path.join(src, 'operationsPresentation.js')
assert.ok(existsSync(presentationPath), 'operationsPresentation.js should exist')
const presentation = await import(pathToFileURL(presentationPath))
assert.deepEqual(presentation.taskStatusPresentation('running'), { label: '执行中', tone: 'warning' })
assert.deepEqual(presentation.taskStatusPresentation('completed'), { label: '已完成', tone: 'success' })
assert.deepEqual(presentation.mailCheckStatusPresentation('invalid'), { label: '失效', tone: 'danger' })
assert.deepEqual(presentation.oauthPhoneStatusPresentation('available'), { label: '可用', tone: 'success' })
assert.deepEqual(presentation.teamMemberTypePresentation('invite'), { label: '待接受', tone: 'warning' })
assert.equal(presentation.accountStatusPresentation('unknown').tone, 'neutral')

const toolbar = readFileSync(path.join(ui, 'UiDataToolbar.vue'), 'utf8')
const metric = readFileSync(path.join(ui, 'UiMetricSummary.vue'), 'utf8')
const batch = readFileSync(path.join(ui, 'UiBatchBar.vue'), 'utf8')
const pagination = readFileSync(path.join(ui, 'UiPagination.vue'), 'utf8')
const table = readFileSync(path.join(ui, 'UiTableFrame.vue'), 'utf8')
const media = readFileSync(path.join(src, 'useMediaQuery.js'), 'utf8')
const css = readFileSync(path.join(src, 'style.css'), 'utf8')
assert.match(toolbar, /UiSheet/)
assert.match(toolbar, /useMediaQuery/)
assert.match(metric, /typeof item\.label === ['"]string['"]/)
assert.match(metric, /typeof item\.value === ['"]string['"] \|\| typeof item\.value === ['"]number['"]/)
assert.match(batch, /UiSheet/)
assert.match(batch, /useMediaQuery/)
assert.match(media, /addEventListener\(['"]change['"]/)
assert.match(media, /removeEventListener\(['"]change['"]/)
assert.match(pagination, /update:page/)
assert.match(pagination, /update:pageSize/)
assert.match(table, /role="region"/)
assert.match(table, /aria-busy/)
assert.doesNotMatch(css, /transition:\s*all/)
console.log('operations primitive contracts passed')
