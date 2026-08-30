import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(`../src/components/workflow/${name}`, import.meta.url), 'utf8')
const workspace = read('WorkflowWorkspace.vue')
const stage = read('WorkflowStage.vue')

assert.match(workspace, /data-page-archetype="workflow"/)
for (const slot of ['actions', 'configuration', 'progress', 'result', 'resources']) {
  assert.match(workspace, new RegExp(`<slot name="${slot}"`))
}
assert.match(stage, /data-workflow-stage/)
assert.match(stage, /configuration.*launch.*progress.*result.*resources/s)
assert.match(stage, /idle.*active.*complete.*warning.*error/s)
assert.doesNotMatch(`${workspace}\n${stage}`, /api\.js/)
console.log('workflow archetype regression passed')