import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

for (const [file, label, nextFunction, stopPattern, resumePattern] of [
  [
    'MomoPage.vue',
    'MoMo',
    'function saveProxy',
    /stopPolling\(\)/,
    /if \(!componentUnmounted && activeJobId\.value && !TERMINAL_STATUSES\.has\(activeJobStatus\.value\)\) startPolling\(\)/,
  ],
  [
    'GCashPhPage.vue',
    'GCash',
    'function saveProxy',
    /stopPolling\(\)/,
    /if \(!componentUnmounted && activeJobId\.value && !TERMINAL_STATUSES\.has\(activeJobStatus\.value\)\) startPolling\(\)/,
  ],
  [
    'KakaoPayPage.vue',
    'Kakao',
    'async function deleteKakaoAccount',
    /stopPolling\(mode\)/,
    /if \(!componentUnmounted && isExtractTaskRunning\(state\)\) startPolling\(mode\)/,
  ],
]) {
  const source = readFileSync(new URL(`../src/components/${file}`, import.meta.url), 'utf8')
  const start = source.indexOf('async function cancelJob')
  const end = source.indexOf(nextFunction, start)
  assert.ok(start >= 0 && end > start, `${label} cancel section should be present`)
  const cancel = source.slice(start, end)

  assert.match(cancel, stopPattern, `${label} should prevent a cancel request from racing an active poll`)
  const finallyBlock = cancel.slice(cancel.indexOf('finally {'))
  assert.match(finallyBlock, /cancelling\.value = false/)
  assert.match(finallyBlock, resumePattern, `${label} should resume a still-active job after cancel success or failure`)
}

console.log('cancel polling recovery contract passed')
