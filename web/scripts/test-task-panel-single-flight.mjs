import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/TaskPanel.vue', import.meta.url), 'utf8')

assert.match(source, /const executingAction = ref\(['"]['"]\)/, 'TaskPanel should own an immediate local action lock')
assert.match(
  source,
  /function isDisabled\(action\) \{[\s\S]{0,220}?executingAction\.value/,
  'every action button should disable while a submission is in flight',
)
assert.match(
  source,
  /async function doExecute\(action, param\) \{[\s\S]{0,180}?if \(executingAction\.value\) return[\s\S]{0,180}?executingAction\.value = action\.key/,
  'the handler should reject duplicate clicks before its first await',
)
assert.match(
  source,
  /async function doExecute\(action, param\) \{[\s\S]*?finally \{[\s\S]{0,180}?executingAction\.value = ['"][\s\S]{0,20}?['"]/,
  'the local action lock should always release after success or failure',
)

console.log('TaskPanel single-flight contract passed')
