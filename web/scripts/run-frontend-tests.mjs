import { readdirSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const scriptsDirectory = path.dirname(fileURLToPath(import.meta.url))
const tests = readdirSync(scriptsDirectory)
  .filter(name =>
    name.endsWith('.mjs') &&
    (name.startsWith('test-') || name.endsWith('-regression.mjs'))
  )
  .sort((left, right) => left.localeCompare(right))

let completed = 0
for (const test of tests) {
  const result = spawnSync(process.execPath, [path.join(scriptsDirectory, test)], {
    cwd: path.resolve(scriptsDirectory, '..'),
    env: process.env,
    stdio: 'inherit',
  })
  if (result.error) throw result.error
  if (result.status !== 0) {
    console.error(`frontend test failed: ${test} (exit ${result.status ?? 'unknown'})`)
    process.exit(result.status || 1)
  }
  completed += 1
}

console.log(`all frontend scripts passed: ${completed}/${tests.length}`)
