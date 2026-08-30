import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const dashboard = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')
const apiSource = readFileSync(new URL('../src/api.js', import.meta.url), 'utf8')
const { confirmExportStatusBatches } = await import(new URL('../src/exportCommit.js', import.meta.url))

function sliceFunction(startMarker, endMarker) {
  const start = dashboard.indexOf(startMarker)
  const end = dashboard.indexOf(endMarker, start + startMarker.length)
  assert.notEqual(start, -1, `missing ${startMarker}`)
  assert.notEqual(end, -1, `missing ${endMarker}`)
  return dashboard.slice(start, end)
}

assert.match(
  dashboard,
  /async function confirmDownloadedExport\(result\)[\s\S]*confirmExportStatusBatches\(\s*result,[\s\S]*api\.updateAccountsExportStatus\(emails, true\)/,
  'downloaded exports should be committed through the explicit export-status endpoint',
)
assert.match(
  apiSource,
  /exportAccountSubAuths:\s*\(emails\)\s*=>\s*request\('POST',\s*'\/accounts\/export-sub-auths',\s*\{\s*emails\s*\},\s*\{\s*timeoutMs:\s*0\s*\}\)/,
  'large Sub2API exports should not be aborted by the generic 20-second request deadline',
)

const credentialExport = sliceFunction(
  'async function downloadCredentials()',
  'async function exportSelectedAccessTokens()',
)
assert.ok(
  credentialExport.indexOf('a.click()') < credentialExport.indexOf('await confirmDownloadedExport(result)'),
  'credential export must trigger the browser download before committing exported status',
)

const cpaExport = sliceFunction('async function exportCpaAuths()', 'async function exportSubAuths()')
assert.ok(
  cpaExport.indexOf('downloadBase64File(') < cpaExport.indexOf('await confirmDownloadedExport(result)'),
  'CPA export must trigger the browser download before committing exported status',
)

const subExport = sliceFunction('async function exportSubAuths()', 'async function batchUpdateExportStatus(')
assert.ok(
  subExport.indexOf('downloadBase64File(') < subExport.indexOf('await confirmDownloadedExport(result)'),
  'Sub2API export must trigger the browser download before committing exported status',
)

const confirmedBatches = []
const batchResult = await confirmExportStatusBatches(
  { exported_emails: Array.from({ length: 1002 }, (_, index) => `USER${index}@example.com`) },
  async emails => { confirmedBatches.push(emails) },
)
assert.deepEqual(confirmedBatches.map(batch => batch.length), [1000, 2], 'the 1000-email backend limit should be respected')
assert.equal(batchResult.confirmedCount, 1002)
assert.equal(confirmedBatches[0][0], 'user0@example.com')

let attemptedBatch = 0
await assert.rejects(
  () => confirmExportStatusBatches(
    { exported_emails: Array.from({ length: 1002 }, (_, index) => `user${index}@example.com`) },
    async () => {
      attemptedBatch += 1
      if (attemptedBatch === 2) throw new Error('offline')
    },
  ),
  error => {
    assert.equal(error.confirmedCount, 1000)
    assert.equal(error.remainingCount, 2)
    assert.match(error.message, /offline/)
    return true
  },
)

console.log('export commit order passed')
