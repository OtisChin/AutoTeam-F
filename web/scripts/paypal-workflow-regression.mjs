import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
const source = readFileSync(new URL('../src/components/UsPaypalPage.vue', import.meta.url), 'utf8')
assert.match(source, /UiSegmentedControl/)
assert.match(source, /WorkflowWorkspace/)
for (const stage of ['configuration','launch','progress','result']) assert.match(source, new RegExp(`WorkflowStage[^>]+name="${stage}"`))
assert.match(source, /unknown_outcome/)
assert.match(source, /paypalStatusPresentation|statusPresentation|tone/)
assert.match(source, /cancelJob|startWithEmails|startProtocol|startPay153/)
console.log('paypal workflow regression passed')
