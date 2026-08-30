import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/LogViewer.vue', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')

function loadLogMergeHelpers() {
  const helperBlock = source.match(/\/\/ BEGIN LOG MERGE HELPERS([\s\S]*?)\/\/ END LOG MERGE HELPERS/)?.[1]
  assert.ok(helperBlock, 'LogViewer should expose its pure boot-aware merge helpers for regression coverage')
  return Function(`${helperBlock}\nreturn { getLogKey, mergeLogEntries }`)()
}

const checks = [
  ['polling waits for request completion before scheduling the next timeout', () => {
    assert.doesNotMatch(source, /setInterval\s*\(/, 'async interval polling permits overlapping requests')
    assert.match(source, /function scheduleNextPoll\(/, 'poller should own a completion-scheduled timeout')
    assert.match(source, /async function runPoll\(\)[\s\S]*await fetchLogs\(\)[\s\S]*scheduleNextPoll\(\)/, 'next poll should be scheduled only after fetchLogs settles')
  }],
  ['manual and scheduled refreshes share a single-flight guard', () => {
    assert.match(source, /let requestInFlight = false/, 'component should track the active request')
    assert.match(source, /if \(requestInFlight[^\n]*\) return/, 'fetchLogs should skip while a request is active')
  }],
  ['hidden and unmounted pages stop polling and invalidate late responses', () => {
    assert.match(source, /document\.addEventListener\(['"]visibilitychange['"]/, 'component should observe page visibility')
    assert.match(source, /document\.removeEventListener\(['"]visibilitychange['"]/, 'component should remove the visibility listener')
    assert.match(source, /document\.hidden/, 'hidden pages should skip requests')
    assert.match(source, /requestGeneration/, 'late responses should be invalidated by a generation token')
    assert.match(source, /generation !== requestGeneration/, 'stale responses should be ignored')
  }],
  ['rendered rows use stable backend-or-composite keys and deduplicate repeats', () => {
    assert.match(source, /:key="log\._key"/, 'rows should render with a stable log key')
    assert.doesNotMatch(source, /:key="i"/, 'array indexes force every row to patch after truncation')
    assert.match(source, /function getLogKey\(log,\s*bootId/, 'component should derive a reusable boot-aware log key')
    assert.match(source, /log\.id/, 'backend ids should be preferred when present')
    assert.match(source, /log\.time[\s\S]*log\.level[\s\S]*log\.message/, 'id-less rows should use a stable composite key')
    assert.match(source, /const nextKeys = new Set/, 'repeated responses should be deduplicated before append')
  }],
  ['incremental polling sends the backend boot epoch with the stable log id', () => {
    assert.match(source, /let lastLogId = 0/, 'component should retain the last stable backend log id')
    assert.match(source, /let lastBootId = ['"]['"]/, 'component should retain the backend boot epoch')
    assert.match(source, /api\.getLogs\(LOG_FETCH_LIMIT, since, lastLogId, lastBootId\)/, 'polling should send both epoch and id cursors')
    assert.match(source, /lastLogId\s*=\s*Math\.max/, 'accepted responses should advance the id cursor')
    assert.match(source, /lastLogId\s*=\s*0/, 'clearing logs should reset the id cursor')
    assert.match(apiSource, /getLogs:\s*\(limit\s*=\s*1000,\s*since\s*=\s*0,\s*sinceId\s*=\s*0,\s*sinceBootId\s*=\s*['"]['"]\)/, 'the API client should accept the boot epoch cursor')
    assert.match(apiSource, /since_boot_id=\$\{encodeURIComponent\(sinceBootId\)\}/, 'the API client should encode the boot epoch in the request')
  }],
  ['a process restart resets the id cursor and retains new id 1 and 2 rows', () => {
    const { mergeLogEntries } = loadLogMergeHelpers()
    const oldEntries = Array.from({ length: 42 }, (_, index) => ({
      id: index + 1,
      time: 100 + index,
      level: 'INFO',
      message: `old ${index + 1}`,
    }))
    const oldLogs = mergeLogEntries([], oldEntries, 'boot-old', 1000)
    const nextLogs = mergeLogEntries(oldLogs, [
      { id: 1, time: 1, level: 'INFO', message: 'new one' },
      { id: 2, time: 2, level: 'INFO', message: 'new two' },
    ], 'boot-new', 1000)

    assert.equal(nextLogs.length, 44, 'new-process ids must not collide with retained old-process ids')
    assert.ok(nextLogs.some(log => log._key === 'boot-old:id:1'))
    assert.ok(nextLogs.some(log => log._key === 'boot-new:id:1'))
    assert.ok(nextLogs.some(log => log._key === 'boot-new:id:2'))
    assert.match(source, /responseBootId[\s\S]*responseBootId\s*!==\s*lastBootId[\s\S]*lastLogId\s*=\s*0/, 'an epoch change must reset the old id cursor before advancing the new epoch')
  }],
  ['the live DOM window is hard-capped at one thousand rows', () => {
    assert.match(source, /const LOG_KEEP_LIMIT = 1000\b/, 'the rendered log window should be capped at 1000 rows')
  }],
]

let failures = 0
for (const [name, check] of checks) {
  try {
    check()
    console.log('ok - ' + name)
  } catch (error) {
    failures += 1
    console.error('not ok - ' + name)
    console.error('  ' + error.message)
  }
}

if (failures > 0) {
  throw new Error(String(failures) + ' LogViewer regression contract(s) failed')
}

console.log('LogViewer polling and rendering regression contract passed')
