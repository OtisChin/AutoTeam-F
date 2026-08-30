import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
for (const [name, model] of [['BrazilPixPage.vue','activePixTab'],['IndiaUpiPage.vue','activeUpiTab'],['KakaoPayPage.vue','activeKakaoTab']]) {
 const source = readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
 assert.match(source, /UiSegmentedControl/, `${name} segmented control`)
 assert.match(source, new RegExp(`v-model="${model}"`))
 assert.match(source, /WorkflowWorkspace/)
 for (const stage of ['configuration','launch','progress','result']) assert.match(source, new RegExp(`WorkflowStage[^>]+name="${stage}"`), `${name} ${stage}`)
 assert.doesNotMatch(source, /bg-\[(?:radial|linear)-gradient/)
 assert.doesNotMatch(source, /linear-gradient\(/)
 assert.match(source, /unknown|needs_action|待处理|结果待核对/i)
}
console.log('dual-mode payment workflow regression passed')
