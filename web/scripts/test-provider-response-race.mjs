import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const dashboardSource = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')
const registerSource = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')

function extractFunction(source, name) {
  const asyncStart = source.indexOf(`async function ${name}(`)
  const start = asyncStart >= 0 ? asyncStart : source.indexOf(`function ${name}(`)
  assert.notEqual(start, -1, `${name} should exist`)

  const bodyStart = source.indexOf('{', start)
  let depth = 0
  let quote = ''
  let escaped = false
  let lineComment = false
  let blockComment = false

  for (let index = bodyStart; index < source.length; index += 1) {
    const char = source[index]
    const next = source[index + 1]

    if (lineComment) {
      if (char === '\n') lineComment = false
      continue
    }
    if (blockComment) {
      if (char === '*' && next === '/') {
        blockComment = false
        index += 1
      }
      continue
    }
    if (quote) {
      if (escaped) {
        escaped = false
      } else if (char === '\\') {
        escaped = true
      } else if (char === quote) {
        quote = ''
      }
      continue
    }
    if (char === '/' && next === '/') {
      lineComment = true
      index += 1
      continue
    }
    if (char === '/' && next === '*') {
      blockComment = true
      index += 1
      continue
    }
    if (char === "'" || char === '"' || char === '`') {
      quote = char
      continue
    }
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) return source.slice(start, index + 1)
    }
  }

  throw new Error(`could not extract ${name}`)
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function installLoader(source, name, context) {
  vm.createContext(context)
  const functionSource = extractFunction(source, name)
  vm.runInContext(`${functionSource}\nglobalThis.loader = ${name}`, context)
  return context.loader
}

async function dashboardIgnoresLatePreviousProvider() {
  const requests = new Map()
  const context = {
    api: {
      getOAuthPhoneSmsCountries(provider) {
        const request = deferred()
        requests.set(provider, request)
        return request.promise
      },
    },
    oauthPhoneSmsForm: { value: { provider: 'hero_sms' } },
    oauthPhoneSmsCountryRequestId: 0,
    oauthPhoneSmsCountryError: { value: '' },
    oauthPhoneSmsCountryDropdownOpen: { value: false },
    oauthPhoneSmsCountryOptions: { value: [] },
    oauthPhoneSmsCountrySearch: { value: '' },
    oauthPhoneSmsCountriesLoading: { value: false },
    oauthPhoneSmsCountryFallbackOptions: { hero_sms: [], smscloud: [] },
    currentOauthPhoneSmsCountryLabel: { value: 'current selection' },
    isCdkOauthPhoneProvider: provider => ['oasis', 'tujie'].includes(provider),
    normalizeOauthPhoneSmsCountryOptions: options => options.map(option => ({
      value: String(option.value || '').trim(),
      label: String(option.label || option.value || '').trim(),
    })).filter(option => option.value),
  }
  const loadCountries = installLoader(
    dashboardSource,
    'loadOauthPhoneSmsCountries',
    context,
  )

  const previousLoad = loadCountries('hero_sms')
  context.oauthPhoneSmsForm.value.provider = 'smscloud'
  const currentLoad = loadCountries('smscloud')

  requests.get('smscloud').resolve({ options: [{ value: '44', label: 'United Kingdom' }] })
  await currentLoad
  requests.get('hero_sms').resolve({ options: [{ value: '187', label: 'United States' }] })
  await previousLoad

  assert.equal(
    context.oauthPhoneSmsCountryOptions.value[0]?.value,
    '44',
    'Dashboard must retain the current provider options when the previous provider resolves last',
  )
  assert.equal(context.oauthPhoneSmsCountriesLoading.value, false)
}

async function dashboardKeepsLatestSameProviderResponse() {
  const requests = []
  const context = {
    api: {
      getOAuthPhoneSmsCountries(provider) {
        const request = deferred()
        requests.push({ provider, request })
        return request.promise
      },
    },
    oauthPhoneSmsForm: { value: { provider: 'hero_sms' } },
    oauthPhoneSmsCountryRequestId: 0,
    oauthPhoneSmsCountryError: { value: '' },
    oauthPhoneSmsCountryDropdownOpen: { value: false },
    oauthPhoneSmsCountryOptions: { value: [] },
    oauthPhoneSmsCountrySearch: { value: '' },
    oauthPhoneSmsCountriesLoading: { value: false },
    oauthPhoneSmsCountryFallbackOptions: { hero_sms: [], smscloud: [] },
    currentOauthPhoneSmsCountryLabel: { value: 'current selection' },
    isCdkOauthPhoneProvider: provider => ['oasis', 'tujie'].includes(provider),
    normalizeOauthPhoneSmsCountryOptions: options => options.map(option => ({
      value: String(option.value || '').trim(),
      label: String(option.label || option.value || '').trim(),
    })).filter(option => option.value),
  }
  const loadCountries = installLoader(dashboardSource, 'loadOauthPhoneSmsCountries', context)

  const firstA = loadCountries('hero_sms')
  context.oauthPhoneSmsForm.value.provider = 'smscloud'
  const loadB = loadCountries('smscloud')
  context.oauthPhoneSmsForm.value.provider = 'hero_sms'
  const secondA = loadCountries('hero_sms')

  requests[2].request.resolve({ options: [{ value: 'new-a', label: 'Newest A' }] })
  await secondA
  requests[1].request.resolve({ options: [{ value: 'b', label: 'Provider B' }] })
  await loadB
  requests[0].request.resolve({ options: [{ value: 'old-a', label: 'Stale A' }] })
  await firstA

  assert.equal(
    context.oauthPhoneSmsCountryOptions.value[0]?.value,
    'new-a',
    'Dashboard must reject A1 after a newer A2 request has committed during A→B→A switching',
  )
  assert.equal(context.oauthPhoneSmsCountriesLoading.value, false)
}

async function dashboardDoesNotApplyDefaultsFromAStaleLoad() {
  const context = {
    oauthPhoneSmsForm: {
      value: {
        provider: 'smscloud',
        hero_sms_country: '',
        smsbower_country: '',
        smscloud_country: '',
      },
    },
  }
  const applyDefault = installLoader(
    dashboardSource,
    'applyLoadedOauthPhoneSmsDefault',
    context,
  )

  assert.equal(applyDefault('hero_sms', {
    provider: 'hero_sms',
    committed: false,
    options: [{ value: '187' }],
  }), false)
  assert.equal(context.oauthPhoneSmsForm.value.hero_sms_country, '')

  assert.equal(applyDefault('hero_sms', {
    provider: 'hero_sms',
    committed: true,
    options: [{ value: '187' }],
  }), false, 'a provider switch after await must reject the old provider default')
  assert.equal(context.oauthPhoneSmsForm.value.hero_sms_country, '')

  context.oauthPhoneSmsForm.value.provider = 'hero_sms'
  assert.equal(applyDefault('hero_sms', {
    provider: 'hero_sms',
    committed: true,
    options: [{ value: '187' }],
  }), true)
  assert.equal(context.oauthPhoneSmsForm.value.hero_sms_country, '187')
}

async function registerIgnoresLatePreviousProvider() {
  const requests = new Map()
  const context = {
    api: {
      getOAuthPhoneSmsCountries(provider) {
        const request = deferred()
        requests.set(provider, request)
        return request.promise
      },
    },
    registerForm: { value: { oauthPhoneSmsProvider: 'hero_sms' } },
    oauthPhoneSmsCountryError: { value: '' },
    oauthPhoneSmsCountryDropdownOpen: { value: false },
    oauthPhoneSmsCountryOptions: { value: [] },
    oauthPhoneSmsCountriesLoading: { value: false },
    oauthPhoneSmsCountryRequests: new Map(),
    oauthPhoneSmsCountryFallbackOptions: { hero_sms: [], smscloud: [] },
    oauthPhoneSmsCountryDisabled: provider => ['phone_pool', 'oasis', 'tujie'].includes(provider),
    normalizeOAuthPhoneSmsCountryOptions: options => options.map(option => ({
      value: String(option.value || ''),
      label: String(option.label || option.value || ''),
    })).filter(option => option.value),
    readOAuthPhoneSmsCountriesCache: () => null,
    writeOAuthPhoneSmsCountriesCache: () => {},
    syncOAuthPhoneSmsCountrySearch: () => {},
  }
  const loadCountries = installLoader(
    registerSource,
    'loadOAuthPhoneSmsCountries',
    context,
  )

  const previousLoad = loadCountries('hero_sms')
  context.registerForm.value.oauthPhoneSmsProvider = 'smscloud'
  const currentLoad = loadCountries('smscloud')

  requests.get('smscloud').resolve({ options: [{ value: '44', label: 'United Kingdom' }] })
  await currentLoad
  requests.get('hero_sms').resolve({ options: [{ value: '187', label: 'United States' }] })
  await previousLoad

  assert.equal(
    context.oauthPhoneSmsCountryOptions.value[0]?.value,
    '44',
    'Register must retain the current provider options when the previous provider resolves last',
  )
  assert.equal(context.oauthPhoneSmsCountriesLoading.value, false)
}

const checks = [
  ['Dashboard ignores a late response from the previous provider', dashboardIgnoresLatePreviousProvider],
  ['Dashboard keeps the newest response across A→B→A switching', dashboardKeepsLatestSameProviderResponse],
  ['Dashboard rejects defaults from stale provider loads', dashboardDoesNotApplyDefaultsFromAStaleLoad],
  ['Register ignores a late response from the previous provider', registerIgnoresLatePreviousProvider],
]

let failures = 0
for (const [name, check] of checks) {
  try {
    await check()
    console.log(`ok - ${name}`)
  } catch (error) {
    failures += 1
    console.error(`not ok - ${name}`)
    console.error(`  ${error.message}`)
  }
}

if (failures > 0) {
  throw new Error(`${failures} provider response race regression(s) failed`)
}

console.log('provider response race regressions passed')
