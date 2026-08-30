import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

for (const name of ['MomoPage.vue', 'GCashPhPage.vue']) {
  const source = readFileSync(new URL(`../src/components/${name}`, import.meta.url), 'utf8')
  const label = name.replace('.vue', '')
  const start = source.indexOf('async function runExpiryClock')
  const end = source.indexOf('onMounted(', start)

  assert.ok(start >= 0 && end > start, `${label} should own a visible-page expiry clock loop`)
  const clock = source.slice(start, end)
  assert.doesNotMatch(source, /setInterval/, `${label} should not wake the component every second while hidden`)
  assert.match(source, /const expiryClock = createPollingLifecycle\(\)/)
  assert.match(clock, /await expiryClock\.wait\(1000, pollToken\)/)
  assert.match(clock, /await expiryClock\.waitUntilAvailable\(pollToken\)/)
  assert.match(
    clock,
    /waitUntilAvailable\(pollToken\)[\s\S]*?nowMs\.value = Date\.now\(\)/,
    `${label} should only publish clock ticks while visible and online`,
  )
  assert.match(
    source.slice(source.indexOf('onUnmounted(() =>'), source.indexOf('</script>')),
    /expiryClock\.dispose\(\)/,
    `${label} should cancel clock timers and availability listeners when unmounted`,
  )
}

console.log('payment expiry clock lifecycle contract passed')
