import { readFileSync } from 'node:fs'
import path from 'node:path'

const root = path.resolve(process.argv[2] || '.')
const source = readFileSync(path.join(root, 'web/src/components/Dashboard.vue'), 'utf8')
const checks = {
  yellow_row_button: /@click="setupAccountTwoFactor\(acc\)"[\s\S]*?border-yellow-500\/30[\s\S]*?text-yellow-300/.test(source),
  yellow_batch_button: /@click="batchSetupAccountTwoFactor"[\s\S]*?bg-yellow-600\/10[\s\S]*?text-yellow-300/.test(source),
  local_submitting_set: /const twoFactorSubmittingEmails = ref\(new Set\(\)\)/.test(source),
  immediate_progress_label: /twoFactorSubmittingEmails\.has\([\s\S]*?\? '设置中\.\.\.' : '设置'/.test(source),
  batch_progress_label: /twoFactorSubmitting \|\| twoFactorTaskRunning[\s\S]*?\? '设置中\.\.\.'/.test(source),
}
const missing = Object.entries(checks).filter(([, passed]) => !passed).map(([name]) => name)
if (missing.length) {
  console.error(`FEATURE_CHECK_FAIL missing=${missing.join(',')}`)
  process.exit(1)
}
console.log(`FEATURE_CHECK_PASS checks=${Object.keys(checks).length}`)
