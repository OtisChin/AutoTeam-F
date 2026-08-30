import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')
assert.match(source, /WorkflowWorkspace/)
for (const stage of ['configuration','launch','progress','result']) assert.match(source, new RegExp(`WorkflowStage[^>]+name="${stage}"`))
assert.match(source, /AccessibleModal|UiSheet/)
assert.doesNotMatch(source, /<section[^>]+role="dialog"/)
assert.match(source, /async function submitManualRegister/)
assert.match(source, /async function cancelRegisterTask/)
assert.match(source, /function startRegisterPolling/)
assert.match(source, /defineEmits\(\['task-started', 'refresh'\]\)/)
console.log('registration workflow regression passed')
