import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
for (const name of ['IdealLinkPage.vue','MomoPage.vue','GCashPhPage.vue']) {
 const source = readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
 assert.match(source, /WorkflowWorkspace/, `${name} workflow`)
 for (const stage of ['configuration','launch','progress','result']) assert.match(source, new RegExp(`WorkflowStage[^>]+name="${stage}"`), `${name} ${stage}`)
 assert.match(source, /UiStatusBadge/)
 assert.doesNotMatch(source, /bg-\[(?:radial|linear)-gradient/)
 assert.doesNotMatch(source, /workflow-hero-surface/)
}
console.log('extraction workflow regression passed')
