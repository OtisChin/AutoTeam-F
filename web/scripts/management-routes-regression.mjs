import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const read = file => readFileSync(path.join(web, file), 'utf8')
const navigation = read('src/navigation.js')
const app = read('src/App.vue')
const pool = read('src/components/PoolPage.vue')
const sync = read('src/components/SyncPage.vue')
const taskPanel = read('src/components/TaskPanel.vue')

const expected = {
  pool: { group: '账号', label: '账号池操作', description: '轮转、检查、补位与清理' },
  sync: { group: '系统', label: '同步中心', description: '本地、CPA 与账号凭据对账' },
}
for (const [key, metadata] of Object.entries(expected)) {
  const record = navigation.match(new RegExp(`key: '${key}'[^\\n]*`))?.[0] || ''
  assert.ok(record, `${key} route exists`)
  for (const value of Object.values(metadata)) assert.match(record, new RegExp(value))
  assert.match(app, new RegExp(`${key}: \\(\\) => import\\('./components/${key === 'pool' ? 'PoolPage' : 'SyncPage'}\\.vue'\\)`))
  assert.match(app, new RegExp(`const ${key === 'pool' ? 'PoolPage' : 'SyncPage'} = shallowRef\\(asyncPage\\('${key}'\\)\\)`))
  assert.match(app, new RegExp(`currentPage === '${key}'`))
}
const keys = [...navigation.matchAll(/key: '([^']+)'/g)].map(match => match[1])
assert.equal(new Set(keys).size, keys.length, 'navigation keys are unique')
for (const [file, mode] of [[pool, 'pool'], [sync, 'sync']]) {
  assert.doesNotMatch(file, /api\.js/, 'wrapper stays API-agnostic')
  assert.match(file, new RegExp(`<TaskPanel[\\s\\S]*mode="${mode}"`))
  assert.match(file, /defineEmits\(\['task-started', 'refresh'\]\)/)
}
assert.match(taskPanel, /import \{ createMessageClearScheduler \} from '\.\.\/messageLifecycle\.js'/)
assert.match(taskPanel, /const messageClearScheduler = createMessageClearScheduler\(\)/)
assert.match(taskPanel, /const domainMessageClearScheduler = createMessageClearScheduler\(\)/)
assert.match(taskPanel, /messageClearScheduler\.dispose\(\)/)
assert.match(taskPanel, /domainMessageClearScheduler\.dispose\(\)/)
assert.doesNotMatch(taskPanel, /setTimeout\(/)
console.log('management routes regression passed')
