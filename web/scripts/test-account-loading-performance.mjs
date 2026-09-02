import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { performance } from 'node:perf_hooks'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../src')
const helperPath = path.join(src, 'accountData.js')
const facetsPath = path.join(src, 'accountFacets.js')
const searchIndexPath = path.join(src, 'accountSearchIndex.js')
const actionScopePath = path.join(src, 'accountActionScope.js')
const accountOverviewPath = path.resolve(here, '../../src/autotoken/api_routes/account_overview.py')

assert.ok(existsSync(helperPath), 'account data preparation helper should exist')
assert.ok(existsSync(facetsPath), 'account facet indexing helper should exist')
assert.ok(existsSync(searchIndexPath), 'account search indexing helper should exist')
assert.ok(existsSync(actionScopePath), 'account action scope helper should exist')
assert.ok(existsSync(accountOverviewPath), 'the frontend benchmark should verify the backend Dashboard DTO contract')

const {
  buildDashboardStatusFromAccounts,
  normalizeStoredPageSize,
} = await import(pathToFileURL(helperPath))
const { buildAccountFacets } = await import(pathToFileURL(facetsPath))
const { buildAccountSearchIndex, filterAccountSearchIndex } = await import(pathToFileURL(searchIndexPath))
const {
  buildAccountActionScope,
  buildAccountSelectionIndex,
  selectAccountsFromIndex,
  buildScopedAccountActions,
} = await import(pathToFileURL(actionScopePath))

assert.equal(
  normalizeStoredPageSize(null, 50, [50, 100, 200]),
  50,
  'a missing preference must use the 50-row default instead of rendering every account',
)
assert.equal(normalizeStoredPageSize('', 50, [50, 100, 200]), 50)
assert.equal(normalizeStoredPageSize('0', 50, [50, 100, 200]), 50, 'a legacy all-rows preference must migrate to the bounded default')
assert.equal(normalizeStoredPageSize('200', 50, [50, 100, 200]), 200)
assert.equal(normalizeStoredPageSize('500', 50, [50, 100, 200]), 50, 'the legacy 500-row mode must migrate to the bounded default')
assert.equal(normalizeStoredPageSize('123', 50, [50, 100, 200]), 50)

const localDay = new Date(2026, 0, 2, 12, 0, 0)
const localDaySeconds = Math.floor(localDay.getTime() / 1000)
const accounts = [
  {
    email: 'first@example.com',
    status: ' Personal ',
    account_type: 'free',
    last_bind_provider: ' PayPal ',
    trial_eligible: true,
    credentials_exported: true,
    credentials_exported_at: localDaySeconds,
    account_hub_synced: true,
    has_codex_auth_file: true,
    auth_session_file: 'session.json',
    plus_bound_at: localDaySeconds,
    created_at: localDaySeconds,
  },
  {
    email: 'second@example.com',
    status: 'fail',
    account_type: 'plus',
    last_bind_provider: '',
    trial_eligible: false,
    credentials_exported: false,
    account_hub_synced: false,
    has_codex_auth_file: false,
  },
]

let statusIterations = 0
const statusInput = new Proxy(accounts, {
  get(target, property, receiver) {
    if (property === Symbol.iterator) {
      return function iterator() {
        statusIterations += 1
        return target[Symbol.iterator]()
      }
    }
    return Reflect.get(target, property, receiver)
  },
})

const status = buildDashboardStatusFromAccounts(statusInput)
assert.equal(statusIterations, 1, 'dashboard status normalization and summary should traverse the account payload once')
assert.equal(status.accounts[0].status, 'active')
assert.equal(status.accounts[0].raw_status, 'personal')
assert.equal(status.accounts[0].last_bind_provider, 'paypal')
assert.deepEqual(status.summary, {
  active: 1,
  standby: 0,
  stashed: 0,
  exhausted: 0,
  pending: 0,
  auth_invalid: 0,
  auth_revoked: 0,
  orphan: 0,
  fail: 1,
  free: 1,
  team: 0,
  plus: 1,
  pro: 0,
  total: 2,
})

const compactStatus = buildDashboardStatusFromAccounts({
  fields: ['email', 'status', 'account_type', 'last_bind_provider', 'trial_eligible'],
  rows: [
    ['compact-plus@example.com', 'personal', 'plus', ' PayPal ', true],
    ['compact-free@example.com', 'fail', 'free'],
  ],
})
assert.equal(compactStatus.accounts.length, 2, 'dashboard compact rows should decode without a second JSON object payload')
assert.deepEqual(compactStatus.accounts[0], {
  email: 'compact-plus@example.com',
  status: 'active',
  account_type: 'plus',
  last_bind_provider: 'paypal',
  trial_eligible: true,
  raw_status: 'personal',
})
assert.deepEqual(compactStatus.accounts[1], {
  email: 'compact-free@example.com',
  status: 'fail',
  account_type: 'free',
  raw_status: 'fail',
  last_bind_provider: '',
})
assert.equal(compactStatus.summary.active, 1)
assert.equal(compactStatus.summary.fail, 1)
assert.equal(compactStatus.summary.plus, 1)
assert.equal(compactStatus.summary.free, 1)

let facetIterations = 0
const facetInput = new Proxy(status.accounts, {
  get(target, property, receiver) {
    if (property === Symbol.iterator) {
      return function iterator() {
        facetIterations += 1
        return target[Symbol.iterator]()
      }
    }
    return Reflect.get(target, property, receiver)
  },
})

const facets = buildAccountFacets(facetInput)
assert.equal(facetIterations, 1, 'all account filter facets should be indexed in one traversal')
assert.deepEqual([...facets.statusCounts], [
  ['auth_invalid', 0],
  ['auth_revoked', 0],
  ['stashed', 0],
  ['active', 1],
  ['fail', 1],
])
assert.deepEqual([...facets.accountTypeCounts], [['free', 1], ['plus', 1]])
assert.deepEqual([...facets.bindProviderCounts], [['paypal', 1], ['__none__', 1]])
assert.deepEqual(facets.credentialCounts, { exported: 1, unexported: 1 })
assert.deepEqual(facets.hubSyncCounts, { synced: 1, unsynced: 1 })
assert.deepEqual(facets.authCredentialCounts, { hasAuth: 1, missingAuth: 1 })
assert.equal(facets.trialEligibleCount, 1)
assert.deepEqual(facets.bindDateKeys, ['2026-01-02'])
assert.deepEqual(facets.registerDateKeys, ['2026-01-02'])
assert.deepEqual(facets.exportDateKeys, ['2026-01-02'])
assert.deepEqual(facets.bindableFreeAccounts.map(account => account.email), ['first@example.com'])
assert.deepEqual(facets.invalidCredentialAccounts.map(account => account.email), ['second@example.com'])

const indexedAccounts = buildAccountSearchIndex([
  { email: 'free@example.com', display_email: 'Visible Alias', account_type: 'free', status: 'active' },
  { email: 'older-plus@example.com', account_type: 'plus', status: 'personal', plus_bound_at: 100 },
  { email: 'newer-plus@example.com', account_type: 'plus', status: 'active', plus_bound_at: 200 },
])
assert.deepEqual(
  indexedAccounts.map(entry => entry.account.email),
  ['newer-plus@example.com', 'older-plus@example.com', 'free@example.com'],
  'the expensive plus-first ordering should be built once per account snapshot',
)
assert.deepEqual(
  filterAccountSearchIndex(indexedAccounts, { email: 'VISIBLE alias' }).map(account => account.email),
  ['free@example.com'],
  'email search should use a pre-normalized canonical/display-email index',
)
assert.deepEqual(
  filterAccountSearchIndex(indexedAccounts, { accountType: 'plus' }, 'desc').map(account => account.email),
  ['older-plus@example.com', 'newer-plus@example.com'],
  'descending display should traverse the stable index without re-sorting the account pool',
)

const malformedEmailAccount = { email: null, status: 'active' }
const actionAccounts = [accounts[0], accounts[1], malformedEmailAccount]
const actionScope = buildAccountActionScope(actionAccounts, new Set(['first@example.com']), {
  canOauthAuthorize: account => account.status !== 'fail',
  canRelogin: account => account.status === 'fail',
  hasCodexAuthFile: account => Boolean(account.has_codex_auth_file),
})
assert.deepEqual(actionScope.selectableEmails, ['first@example.com', 'second@example.com'])
assert.deepEqual(actionScope.selectedEmails, ['first@example.com'])
assert.deepEqual(actionScope.scopedAccounts.map(account => account.email), ['first@example.com'])
assert.deepEqual(actionScope.oauthAuthorizableAccounts.map(account => account.email), ['first@example.com'])
assert.deepEqual(actionScope.reloginableAccounts, [])
assert.deepEqual(actionScope.cpaExportableAccounts.map(account => account.email), ['first@example.com'])
assert.deepEqual(actionScope.refreshableQuotaAccounts.map(account => account.email), ['first@example.com'])

const selectionIndex = buildAccountSelectionIndex(actionAccounts)
assert.deepEqual(selectionIndex.selectableEmails, ['first@example.com', 'second@example.com'])
const indexedSelection = selectAccountsFromIndex(selectionIndex, new Set(['second@example.com', 'first@example.com']))
assert.deepEqual(
  indexedSelection.map(account => account.email),
  ['first@example.com', 'second@example.com'],
  'indexed selection should preserve current filtered order without rescanning the account pool',
)
const indexedActions = buildScopedAccountActions(indexedSelection, {
  canOauthAuthorize: account => account.status !== 'fail',
  canRelogin: account => account.status === 'fail',
  hasCodexAuthFile: account => Boolean(account.has_codex_auth_file),
})
assert.deepEqual(indexedActions.oauthAuthorizableAccounts.map(account => account.email), ['first@example.com'])
assert.deepEqual(indexedActions.reloginableAccounts.map(account => account.email), ['second@example.com'])

const appSource = readFileSync(path.join(src, 'App.vue'), 'utf8')
assert.match(appSource, /import\s*\{[^}]*shallowRef[^}]*\}\s*from\s*['"]vue['"]/, 'large immutable account snapshots should use shallowRef')
assert.match(appSource, /const status = shallowRef\(null\)/, 'account snapshots must not be recursively proxied')

const dashboardSource = readFileSync(path.join(src, 'components/Dashboard.vue'), 'utf8')
assert.match(dashboardSource, /const accountFacets = computed\(\(\) => buildAccountFacets\(allAccounts\.value\)\)/)
assert.match(dashboardSource, /normalizeStoredPageSize\(value, DEFAULT_ACCOUNT_PAGE_SIZE, ACCOUNT_PAGE_SIZE_VALUES\)/)
assert.match(dashboardSource, /v-for="\(acc, i\) in paginatedAccounts"/, 'the account table should render only its current page')
assert.doesNotMatch(dashboardSource, /\{\s*value:\s*0,\s*label:\s*['"]全部['"]\s*\}/, 'the dashboard must not expose an unbounded DOM rendering mode')
assert.doesNotMatch(dashboardSource, /\{\s*value:\s*500,\s*label:\s*['"]500['"]\s*\}/, 'the dashboard must not mount a 500-row rich table')
assert.match(dashboardSource, /const effectiveAccountPageSize = computed\(\(\) => normalizeAccountPageSize\(accountPageSize\.value\)\)/, 'invalid or legacy page sizes should stay bounded at runtime')
assert.match(dashboardSource, /const deferredEmailFilter = ref\(['"]['"]\)/, 'email search must defer full-pool filtering while the operator is typing')
assert.match(dashboardSource, /buildAccountSearchIndex\(allAccounts\.value\)/, 'the dashboard should build normalized search/order metadata once per snapshot')
assert.match(dashboardSource, /buildAccountSelectionIndex\(filteredAccounts\.value\)/, 'filtered accounts should build one reusable selection index')
assert.match(dashboardSource, /selectAccountsFromIndex\(accountSelectionIndex\.value, selectedSet\.value\)/, 'selection changes should use indexed lookups instead of rescanning the pool')
assert.match(dashboardSource, /buildScopedAccountActions\(scopedAccounts\.value,/, 'bulk-action predicates should scan only the selected scope when a selection exists')
const accountRowTemplate = dashboardSource.match(/<tr v-for="\(acc, i\) in paginatedAccounts"[\s\S]*?<\/tr>/)?.[0] || ''
assert.ok(accountRowTemplate, 'the paginated account row template should remain discoverable')
assert.match(accountRowTemplate, /v-memo=/, 'stable account rows should skip unrelated reactive patches')
assert.ok(
  (accountRowTemplate.match(/<button\b/g) || []).length <= 2,
  'each rich account row should mount only the requested 2FA setup button plus one shared action trigger',
)
assert.match(dashboardSource, /v-if="accountActionMenuAccount"[^>]*role="dialog"/, 'row actions should mount once in an on-demand shared dialog')
assert.match(dashboardSource, /<Teleport to="body">[\s\S]*v-if="accountActionMenuAccount"[\s\S]*<\/Teleport>/, 'the shared action dialog should escape the clipped table scroll container')

const LARGE_ACCOUNT_COUNT = 20_000
const largeAccounts = Array.from({ length: LARGE_ACCOUNT_COUNT }, (_, index) => ({
  email: `benchmark-${index}@example.com`,
  display_email: `Benchmark ${index}`,
  original_email: `benchmark-${index}@example.com`,
  status: index % 5 === 0 ? 'fail' : 'active',
  raw_status: index % 5 === 0 ? 'fail' : 'personal',
  account_type: index % 3 === 0 ? 'plus' : 'free',
  seat_type: index % 3 === 0 ? 'plus' : 'free',
  trial_eligible: index % 7 === 0,
  is_main_account: index === 0,
  created_at: localDaySeconds + index,
  registered_at: localDaySeconds + index,
  register_at: localDaySeconds + index,
  plus_bound_at: localDaySeconds + index,
  activated_at: localDaySeconds + index,
  activation_at: localDaySeconds + index,
  upgraded_at: localDaySeconds + index,
  last_bind_at: localDaySeconds + index,
  last_bind_provider: index % 2 === 0 ? 'paypal' : '',
  last_bind_status: index % 2 === 0 ? 'success' : '',
  last_bind_task_id: index % 2 === 0 ? `task-${index}` : '',
  last_bind_message: index % 2 === 0 ? 'bound' : '',
  last_bind_failure_stage: '',
  last_checkout_url: index % 2 === 0 ? `https://checkout.example/${index}` : '',
  last_proxy_label: index % 2 === 0 ? `proxy-${index % 20}` : '',
  kakao_link_extracted: index % 9 === 0,
  kakao_link_extracted_at: localDaySeconds + index,
  kakao_link_expires_at: localDaySeconds + index + 3600,
  kakao_link_cs_id: index % 9 === 0 ? `cs-${index}` : '',
  kakao_link_job_id: index % 9 === 0 ? `job-${index}` : '',
  credentials_exported: index % 4 === 0,
  credentials_exported_at: localDaySeconds + index,
  account_hub_synced: index % 6 === 0,
  account_hub_synced_at: localDaySeconds + index,
  hub_source_name: index % 6 === 0 ? 'primary' : '',
  auth_file: `data/auths/benchmark-${index}.json`,
  auth_session_file: `data/auth_session/benchmark-${index}.json`,
  codex_auth_file: `data/auths/benchmark-${index}.json`,
  codex_auth_synthetic: index % 11 === 0,
  has_codex_auth_file: index % 3 !== 0,
  needs_codex_login: index % 3 === 0,
  quota_exhausted_at: index % 10 === 0 ? localDaySeconds + index : null,
  quota_resets_at: localDaySeconds + index + 18_000,
  last_quota_check_at: localDaySeconds + index,
  last_quota: {
    checked_at: localDaySeconds + index,
    primary_pct: index % 100,
    primary_resets_at: localDaySeconds + index + 18_000,
    primary_window_seconds: 18_000,
    primary_reset_after_seconds: 18_000,
    weekly_pct: (index * 3) % 100,
    weekly_resets_at: localDaySeconds + index + 604_800,
    weekly_window_seconds: 604_800,
    weekly_reset_after_seconds: 604_800,
    monthly_window_seconds: 2_592_000,
    kakao_link_extracted: index % 9 === 0,
    windows: {
      primary: {
        used_percent: index % 100,
        reset_at: localDaySeconds + index + 18_000,
        reset_after_seconds: 18_000,
        limit_window_seconds: 18_000,
      },
      weekly: {
        used_percent: (index * 3) % 100,
        reset_at: localDaySeconds + index + 604_800,
        reset_after_seconds: 604_800,
        limit_window_seconds: 604_800,
      },
    },
  },
}))
const compactFields = Object.keys(largeAccounts[0])
assert.equal(compactFields.length, 44, 'the 20k benchmark must cover the full production Dashboard DTO field set')
const accountOverviewSource = readFileSync(accountOverviewPath, 'utf8')
function pythonStringTuple(name) {
  const body = accountOverviewSource.match(new RegExp(`${name}\\s*=\\s*\\(([\\s\\S]*?)\\n\\)`))?.[1] || ''
  return [...body.matchAll(/["']([^"']+)["']/g)].map(match => match[1])
}
assert.deepEqual(
  compactFields,
  pythonStringTuple('DASHBOARD_ACCOUNT_FIELDS'),
  'the 20k browser benchmark field order must match the backend compact DTO exactly',
)
assert.deepEqual(
  Object.keys(largeAccounts[0].last_quota || {}).filter(key => key !== 'windows'),
  pythonStringTuple('DASHBOARD_QUOTA_FIELDS'),
  'the benchmark quota keys must match the backend projection exactly',
)
assert.deepEqual(
  Object.keys(largeAccounts[0].last_quota?.windows?.primary || {}),
  pythonStringTuple('DASHBOARD_QUOTA_WINDOW_FIELDS'),
  'the benchmark quota-window keys must match the backend projection exactly',
)
assert.deepEqual(
  Object.keys(largeAccounts[0].last_quota || {}).sort(),
  [
    'checked_at',
    'kakao_link_extracted',
    'monthly_window_seconds',
    'primary_pct',
    'primary_reset_after_seconds',
    'primary_resets_at',
    'primary_window_seconds',
    'weekly_pct',
    'weekly_reset_after_seconds',
    'weekly_resets_at',
    'weekly_window_seconds',
    'windows',
  ],
  'the 20k benchmark must exercise the quota keys rendered by Dashboard',
)
const legacyPayloadJson = JSON.stringify(largeAccounts)
const compactPayloadJson = JSON.stringify({
  fields: compactFields,
  rows: largeAccounts.map(account => compactFields.map(field => account[field])),
})
assert.ok(
  compactPayloadJson.length < legacyPayloadJson.length * 0.6,
  `compact dashboard transport should remove repeated object keys: compact=${compactPayloadJson.length} legacy=${legacyPayloadJson.length}`,
)
const compactDecodeStartedAt = performance.now()
const decodedLargeStatus = buildDashboardStatusFromAccounts(JSON.parse(compactPayloadJson))
const compactDecodeDurationMs = performance.now() - compactDecodeStartedAt
assert.equal(decodedLargeStatus.summary.total, LARGE_ACCOUNT_COUNT)
assert.ok(
  compactDecodeDurationMs < 300,
  `20k compact JSON parse and account preparation exceeded the 300ms budget: ${compactDecodeDurationMs.toFixed(2)}ms`,
)
const benchmarkStartedAt = performance.now()
const largeStatus = buildDashboardStatusFromAccounts(largeAccounts)
const largeFacets = buildAccountFacets(largeStatus.accounts)
const largeSearchIndex = buildAccountSearchIndex(largeStatus.accounts)
const benchmarkDurationMs = performance.now() - benchmarkStartedAt
const defaultFirstPage = largeStatus.accounts.slice(
  0,
  normalizeStoredPageSize(null, 50, [50, 100, 200]),
)
const legacyAllFirstPage = largeStatus.accounts.slice(
  0,
  normalizeStoredPageSize('0', 50, [50, 100, 200]),
)

for (let iteration = 0; iteration < 5; iteration += 1) {
  filterAccountSearchIndex(largeSearchIndex, { email: `benchmark-${iteration}` })
}
const filterSamplesMs = []
for (let iteration = 0; iteration < 30; iteration += 1) {
  const filterStartedAt = performance.now()
  filterAccountSearchIndex(largeSearchIndex, {
    email: `benchmark-${iteration % 10}`,
    status: iteration % 2 ? 'active' : '',
    accountType: iteration % 3 ? '' : 'plus',
  })
  filterSamplesMs.push(performance.now() - filterStartedAt)
}
const sortedFilterSamplesMs = [...filterSamplesMs].sort((a, b) => a - b)
const filterP95Ms = sortedFilterSamplesMs[Math.ceil(sortedFilterSamplesMs.length * 0.95) - 1]
const filterMaxMs = sortedFilterSamplesMs.at(-1)
const actionScopeSamplesMs = []
for (let iteration = 0; iteration < 30; iteration += 1) {
  const selected = new Set(iteration % 2 ? ['benchmark-19999@example.com'] : [])
  const actionStartedAt = performance.now()
  buildAccountActionScope(largeStatus.accounts, selected, {
    canOauthAuthorize: account => account.status === 'active',
    canRelogin: account => account.status === 'fail',
    hasCodexAuthFile: account => Boolean(account.has_codex_auth_file),
  })
  actionScopeSamplesMs.push(performance.now() - actionStartedAt)
}
const sortedActionScopeSamplesMs = [...actionScopeSamplesMs].sort((a, b) => a - b)
const actionScopeP95Ms = sortedActionScopeSamplesMs[Math.ceil(sortedActionScopeSamplesMs.length * 0.95) - 1]

const largeSelectionIndex = buildAccountSelectionIndex(largeStatus.accounts)
const indexedSelectionSamplesMs = []
for (let iteration = 0; iteration < 30; iteration += 1) {
  const selected = new Set([`benchmark-${LARGE_ACCOUNT_COUNT - 1 - iteration}@example.com`])
  const selectionStartedAt = performance.now()
  const selectedAccounts = selectAccountsFromIndex(largeSelectionIndex, selected)
  buildScopedAccountActions(selectedAccounts, {
    canOauthAuthorize: account => account.status === 'active',
    canRelogin: account => account.status === 'fail',
    hasCodexAuthFile: account => Boolean(account.has_codex_auth_file),
  })
  indexedSelectionSamplesMs.push(performance.now() - selectionStartedAt)
}
const sortedIndexedSelectionSamplesMs = [...indexedSelectionSamplesMs].sort((a, b) => a - b)
const indexedSelectionP95Ms = sortedIndexedSelectionSamplesMs[Math.ceil(sortedIndexedSelectionSamplesMs.length * 0.95) - 1]

assert.equal(largeStatus.summary.total, LARGE_ACCOUNT_COUNT)
assert.equal(largeFacets.statusCounts.get('fail'), LARGE_ACCOUNT_COUNT / 5)
assert.equal(defaultFirstPage.length, 50, 'a first visit should mount 50 account rows, not the entire account pool')
assert.equal(legacyAllFirstPage.length, 50, 'a saved all-rows preference should no longer mount the full 20k-row table')
assert.ok(
  benchmarkDurationMs < 200,
  `20k-account normalization, facets, and search indexing exceeded the 200ms budget: ${benchmarkDurationMs.toFixed(2)}ms`,
)
assert.ok(filterP95Ms < 100, `20k-account indexed filter p95 exceeded 100ms: ${filterP95Ms.toFixed(2)}ms`)
assert.ok(filterMaxMs < 200, `20k-account indexed filter max exceeded 200ms: ${filterMaxMs.toFixed(2)}ms`)
assert.ok(actionScopeP95Ms < 100, `20k-account consolidated action scope p95 exceeded 100ms: ${actionScopeP95Ms.toFixed(2)}ms`)
assert.ok(indexedSelectionP95Ms < 5, `20k-account indexed single-selection p95 exceeded 5ms: ${indexedSelectionP95Ms.toFixed(2)}ms`)

console.log(
  `account loading performance tests passed: rows=${LARGE_ACCOUNT_COUNT} compact_bytes=${compactPayloadJson.length} legacy_bytes=${legacyPayloadJson.length} compact_parse_prepare=${compactDecodeDurationMs.toFixed(2)}ms prepare=${benchmarkDurationMs.toFixed(2)}ms filter_p95=${filterP95Ms.toFixed(2)}ms filter_max=${filterMaxMs.toFixed(2)}ms actions_p95=${actionScopeP95Ms.toFixed(2)}ms indexed_selection_p95=${indexedSelectionP95Ms.toFixed(2)}ms firstPaint=${defaultFirstPage.length}`,
)
