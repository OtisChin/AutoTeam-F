import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const dist = path.resolve(here, '../../src/autotoken/web/dist')
const html = readFileSync(path.join(dist, 'index.html'), 'utf8')
const entryMatch = html.match(/<script[^>]+src="\/?(assets\/index-[^"]+\.js)"/)
assert.ok(entryMatch, 'production HTML should reference a hashed JavaScript entry')

const entryPath = path.join(dist, entryMatch[1])
const entryBytes = statSync(entryPath).size
const jsChunks = readdirSync(path.join(dist, 'assets')).filter(name => name.endsWith('.js'))

assert.ok(entryBytes <= 250 * 1024, `initial JavaScript should stay within 250 KiB (received ${entryBytes} bytes)`)
assert.ok(jsChunks.length >= 8, `route splitting should produce at least 8 JavaScript chunks (received ${jsChunks.length})`)

console.log(`frontend bundle budget passed: entry=${entryBytes} bytes chunks=${jsChunks.length}`)
