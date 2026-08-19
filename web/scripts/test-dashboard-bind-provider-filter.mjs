import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '..')
const file = path.join(root, 'src', 'components', 'Dashboard.vue')
const source = fs.readFileSync(file, 'utf8')

function assertContains(needle, message) {
  if (!source.includes(needle)) {
    throw new Error(message + `\nMissing: ${needle}`)
  }
}

assertContains('v-model="bindProviderFilter"', 'filter bar should expose a binding provider select')
assertContains('accountBindProviderFilterOptions', 'binding provider select should render counted options')
assertContains("const bindProviderFilter = ref('')", 'script should store binding provider filter state')
assertContains('bindProviderFilter,', 'watch list should reset pagination when binding provider changes')
assertContains('const bindProviderNeedle = bindProviderFilter.value', 'filteredAccounts should read binding provider filter')
assertContains('if (bindProviderNeedle && accountBindProviderFilterValue(acc) !== bindProviderNeedle) return false', 'filteredAccounts should apply binding provider filter')
assertContains('bindProviderFilter.value = \'\'', 'clearFilters should reset binding provider filter')
assertContains('function accountBindProviderFilterValue(acc)', 'filter should normalize empty provider to a selectable value')

console.log('dashboard binding provider filter wiring ok')
