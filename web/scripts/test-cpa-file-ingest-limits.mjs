import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  MAX_CPA_TO_SUB2API_BYTES,
  MAX_CPA_TO_SUB2API_FILES,
  validateCpaFileSelection,
} from '../src/cpaFileLimits.js'

const page = readFileSync(new URL('../src/components/CpaToSub2ApiPage.vue', import.meta.url), 'utf8')

const tooMany = Array.from({ length: MAX_CPA_TO_SUB2API_FILES + 1 }, (_, index) => ({
  name: `account-${index}.json`,
  size: 1,
}))
assert.equal(validateCpaFileSelection([], tooMany).code, 'too_many_files')

const oversized = [{ name: 'huge.json', size: MAX_CPA_TO_SUB2API_BYTES + 1 }]
assert.equal(validateCpaFileSelection([], oversized).code, 'content_too_large')

const replacement = validateCpaFileSelection(
  [{ filename: 'same.json', byteSize: MAX_CPA_TO_SUB2API_BYTES }],
  [{ name: 'same.json', size: 1 }],
)
assert.equal(replacement.ok, true, 'replacing a file should not double-count the previous content')
assert.equal(replacement.totalBytes, 1)

assert.match(page, /validateCpaFileSelection\(sourceFiles\.value, files\)/, 'the page should validate count and byte size before reading')
const validationIndex = page.indexOf('validateCpaFileSelection(sourceFiles.value, files)')
const firstReadIndex = page.indexOf('await file.text()')
assert.ok(validationIndex >= 0 && firstReadIndex > validationIndex, 'no selected file should be read before validation succeeds')
assert.doesNotMatch(page, /Promise\.all\([\s\S]{0,300}?file\.text\(\)/, 'file contents should not be read concurrently into memory')
assert.match(page, /byteSize:\s*Number\(file\.size \|\| 0\)/, 'loaded entries should retain their measured byte size for later replacement checks')

console.log('CPA file ingest limits passed')
