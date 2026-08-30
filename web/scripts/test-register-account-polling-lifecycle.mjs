import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const page = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')

function section(start, end) {
  const from = page.indexOf(start)
  const to = page.indexOf(end, from + start.length)
  assert.ok(from >= 0, `missing section start: ${start}`)
  assert.ok(to > from, `missing section end: ${end}`)
  return page.slice(from, to)
}

assert.match(
  page,
  /import \{ createPollingLifecycle \} from '\.\.\/pollingLifecycle\.js'/,
  'RegisterAccountPage should own a cancellable polling lifecycle',
)
assert.match(page, /const registerPolling = createPollingLifecycle\(\)/)

const polling = section('async function runRegisterPolling', 'onMounted(() =>')
assert.doesNotMatch(polling, /setInterval/, 'register polling should schedule after completed requests instead of overlapping intervals')
assert.match(polling, /await registerPolling\.wait\(REGISTER_POLL_INTERVAL_MS, pollToken\)/)
assert.match(polling, /await registerPolling\.waitUntilAvailable\(pollToken\)/)
assert.match(
  polling,
  /waitUntilAvailable\(pollToken\)[\s\S]*?Promise\.all\(\[loadRegisterStats\(pollToken\), loadRegisterLogs\(pollToken\)\]\)/,
  'register polling should wait for a visible, online page before issuing requests',
)
assert.match(polling, /registerPolling\.cancel\(\)/, 'stopping should settle pending cadence and availability waits')

const logLoader = section('async function loadRegisterLogs', 'async function loadRegisterStats')
const statsLoader = section('async function loadRegisterStats', 'async function submitManualRegister')
assert.ok(
  (logLoader.match(/if \(!canCommitRegisterPoll\(pollToken\)\) return/g) || []).length >= 2,
  'stale register log responses should not mutate the current page',
)
assert.ok(
  (statsLoader.match(/if \(!canCommitRegisterPoll\(pollToken\)\) return/g) || []).length >= 2,
  'stale register stats responses should not mutate the current page',
)
assert.match(
  section('onUnmounted(() =>', "watch(() => props.runningTask?.task_id"),
  /registerPolling\.dispose\(\)/,
  'unmounting should dispose polling waits and invalidate in-flight responses',
)

console.log('register account polling lifecycle contract passed')
