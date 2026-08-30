import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const components = [
  ['KakaoPayPage.vue', 'Kakao'],
  ['MomoPage.vue', 'MoMo'],
  ['GCashPhPage.vue', 'GCash'],
]

for (const [file, label] of components) {
  const source = readFileSync(new URL(`../src/components/${file}`, import.meta.url), 'utf8')
  const pollingLoop = source.slice(
    source.indexOf('async function runPollingLoop'),
    source.indexOf('async function cancelJob'),
  )
  assert.match(source, /createPollingLifecycle/, `${label} should use a cancellable polling lifecycle`)
  assert.doesNotMatch(source, /setInterval\s*\([^\n]*pollJob|setInterval\s*\(\(\)\s*=>\s*pollJob/, `${label} must not overlap async job polls with setInterval`)
  assert.match(source, /await .*Polling\.wait\(3000, pollToken\)/, `${label} should wait only after the current request completes`)
  assert.match(source, /isActive\(pollToken\)/, `${label} should reject stale responses and callbacks`)
  assert.match(
    pollingLoop,
    /if \(!await .*Polling\.waitUntilAvailable\(pollToken\)\) return\s+await pollJob/,
    `${label} should wait for a visible, online page before every job request`,
  )
  assert.match(source, /\.dispose\(\)/, `${label} should dispose polling during unmount`)
}

const kakaoSource = readFileSync(new URL('../src/components/KakaoPayPage.vue', import.meta.url), 'utf8')
const kakaoPoll = kakaoSource.slice(
  kakaoSource.indexOf('async function pollJob'),
  kakaoSource.indexOf('async function retryFailedAccounts'),
)
assert.match(
  kakaoPoll,
  /for \(const id of ids\) \{[\s\S]{0,360}?if \(!await modePolling\.waitUntilAvailable\(pollToken\)\) return[\s\S]{0,240}?if \(!modePolling\.isActive\(pollToken\)\) return[\s\S]{0,240}?api\.getKakaoPayJob\(id\)/,
  'Kakao should stop between job IDs when the page becomes hidden or offline',
)

console.log('payment polling lifecycle contract passed')
