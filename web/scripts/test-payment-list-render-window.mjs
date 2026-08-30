import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const sources = new Map()

function componentSource(file) {
  if (!sources.has(file)) {
    sources.set(file, readFileSync(new URL(`../src/components/${file}`, import.meta.url), 'utf8'))
  }
  return sources.get(file)
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function assertRenderWindow(file, {
  label,
  sourceName,
  visibleName,
  countName,
  hiddenName,
  showMoreName,
  directLoop,
}) {
  const source = componentSource(file)
  const sourcePattern = escapeRegExp(sourceName)
  const visiblePattern = escapeRegExp(visibleName)
  const countPattern = escapeRegExp(countName)
  const hiddenPattern = escapeRegExp(hiddenName)
  const showMorePattern = escapeRegExp(showMoreName)

  assert.match(source, new RegExp(`const ${countPattern} = ref\\(100\\)`), `${label} should start with a 100-row render budget`)
  assert.match(
    source,
    new RegExp(`const ${visiblePattern} = computed\\([\\s\\S]{0,500}?${sourcePattern}\\.value[\\s\\S]{0,240}?\\.slice\\(0, ${countPattern}\\.value\\)`),
    `${label} should slice a derived view instead of truncating its source array`,
  )
  assert.match(
    source,
    new RegExp(`const ${hiddenPattern} = computed\\([\\s\\S]{0,240}?${sourcePattern}\\.value\\.length - ${visiblePattern}\\.value\\.length`),
    `${label} should expose the exact remaining row count`,
  )
  assert.match(source, new RegExp(`v-for="[^"]+ in ${visiblePattern}"`), `${label} should render only the windowed rows`)
  assert.doesNotMatch(source, directLoop, `${label} must not render its full source array directly`)
  assert.match(
    source,
    new RegExp(`v-if="${hiddenPattern} > 0"[\\s\\S]{0,900}?剩余 \\{\\{ ${hiddenPattern} \\}\\}[\\s\\S]{0,500}?@click="${showMorePattern}"[\\s\\S]{0,300}?加载更多`),
    `${label} should show remaining rows and an explicit load-more action`,
  )
  assert.match(
    source,
    new RegExp(`function ${showMorePattern}\\(\\) \\{[\\s\\S]{0,240}?${countPattern}\\.value = Math\\.min\\(${sourcePattern}\\.value\\.length, ${countPattern}\\.value \\+ 100\\)`),
    `${label} should grow its render budget in bounded 100-row steps`,
  )
}

function assertRecentResultWindow(file, label) {
  const source = componentSource(file)

  assert.match(source, /const recentResultVisibleCount = ref\(100\)/, `${label} recent results should start at 100 mounted rows`)
  assert.match(source, /const visibleRecentResultSuccesses = computed\([\s\S]{0,500}?currentResultSuccesses\.value\.slice\(0, recentResultVisibleCount\.value\)/, `${label} should window successful recent results`)
  assert.match(source, /const visibleRecentResultErrors = computed\([\s\S]{0,700}?recentResultVisibleCount\.value - visibleRecentResultSuccesses\.value\.length[\s\S]{0,300}?currentResultErrors\.value\.slice\(0, remaining\)/, `${label} should give failures only the remaining global row budget`)
  assert.match(source, /const visibleRecentResultSkipped = computed\([\s\S]{0,700}?recentResultVisibleCount\.value - visibleRecentResultSuccesses\.value\.length - visibleRecentResultErrors\.value\.length[\s\S]{0,300}?currentResultSkipped\.value\.slice\(0, remaining\)/, `${label} should give skipped rows only the remaining global row budget`)
  assert.match(source, /const visibleRecentResultCount = computed\([\s\S]{0,300}?visibleRecentResultSuccesses\.value\.length \+ visibleRecentResultErrors\.value\.length \+ visibleRecentResultSkipped\.value\.length/, `${label} should count the unified mounted result window`)
  assert.match(source, /const hiddenRecentResultCount = computed\([\s\S]{0,240}?filteredRecentResultCount\.value - visibleRecentResultCount\.value/, `${label} should expose remaining recent results`)
  assert.match(source, /v-for="item in visibleRecentResultSuccesses"/, `${label} should render windowed successes`)
  assert.match(source, /v-for="item in visibleRecentResultErrors"/, `${label} should render windowed failures`)
  assert.match(source, /v-for="item in visibleRecentResultSkipped"/, `${label} should render windowed skipped rows`)
  assert.doesNotMatch(source, /v-for="item in currentResult(?:Successes|Errors|Skipped)"/, `${label} must not mount complete recent-result groups`)
  assert.match(source, /v-if="hiddenRecentResultCount > 0"[\s\S]{0,900}?剩余 \{\{ hiddenRecentResultCount \}\}[\s\S]{0,500}?@click="showMoreRecentResults"[\s\S]{0,300}?加载更多/, `${label} should show and expand hidden recent results`)
  assert.match(source, /function showMoreRecentResults\(\) \{[\s\S]{0,240}?recentResultVisibleCount\.value = Math\.min\(filteredRecentResultCount\.value, recentResultVisibleCount\.value \+ 100\)/, `${label} should expand recent results by 100`)
  assert.match(source, /watch\(recentResultFilter, \(\) => \{ recentResultVisibleCount\.value = 100 \}\)/, `${label} should reset its result window when filtering changes`)
}

function assertReplacementReset(file, label, sourceName, countName) {
  const source = componentSource(file)
  const sourcePattern = escapeRegExp(sourceName)
  const countPattern = escapeRegExp(countName)
  assert.match(
    source,
    new RegExp(`watch\\(${sourcePattern}, \\(\\) => \\{ ${countPattern}\\.value = 100 \\}\\)`),
    `${label} should reset to 100 rows when its source data is replaced`,
  )
}

assertRenderWindow('IdealLinkPage.vue', {
  label: 'iDEAL stored links',
  sourceName: 'links', visibleName: 'visibleLinks', countName: 'linkVisibleCount', hiddenName: 'hiddenLinkCount', showMoreName: 'showMoreLinks',
  directLoop: /v-for="link in links"/,
})

for (const [file, label] of [
  ['BrazilPixPage.vue', 'PIX'],
  ['IndiaUpiPage.vue', 'UPI'],
]) {
  assertRenderWindow(file, {
    label: `${label} payment links`,
    sourceName: 'paymentLinks', visibleName: 'visiblePaymentLinks', countName: 'paymentLinkVisibleCount', hiddenName: 'hiddenPaymentLinkCount', showMoreName: 'showMorePaymentLinks',
    directLoop: /v-for="(?:\(item, index\)|item) in paymentLinks"/,
  })
  assertRenderWindow(file, {
    label: `${label} payment CDKs`,
    sourceName: 'paymentCdks', visibleName: 'visiblePaymentCdks', countName: 'paymentCdkVisibleCount', hiddenName: 'hiddenPaymentCdkCount', showMoreName: 'showMorePaymentCdks',
    directLoop: /v-for="(?:\(item, index\)|cdk) in paymentCdks"/,
  })
}

assertRenderWindow('IndiaUpiPage.vue', {
  label: 'UPI temporary CDKs',
  sourceName: 'tempCdks', visibleName: 'visibleTempCdks', countName: 'tempCdkVisibleCount', hiddenName: 'hiddenTempCdkCount', showMoreName: 'showMoreTempCdks',
  directLoop: /v-for="item in tempCdks"/,
})

assertRenderWindow('KakaoPayPage.vue', {
  label: 'Kakao temporary CDKs',
  sourceName: 'visibleTempCdks', visibleName: 'windowedTempCdks', countName: 'tempCdkVisibleCount', hiddenName: 'hiddenTempCdkCount', showMoreName: 'showMoreTempCdks',
  directLoop: /v-for="item in (?:tempCdks|visibleTempCdks)"/,
})
assertRenderWindow('KakaoPayPage.vue', {
  label: 'Kakao payment CDKs',
  sourceName: 'visibleKkPaymentCdks', visibleName: 'windowedKkPaymentCdks', countName: 'kkPaymentCdkVisibleCount', hiddenName: 'hiddenKkPaymentCdkCount', showMoreName: 'showMoreKkPaymentCdks',
  directLoop: /v-for="(?:item|cdk) in (?:kkPaymentCdks|visibleKkPaymentCdks)"/,
})
assertRenderWindow('KakaoPayPage.vue', {
  label: 'Kakao filtered payment links',
  sourceName: 'filteredKkPaymentLinks', visibleName: 'visibleKkPaymentLinks', countName: 'kkPaymentLinkVisibleCount', hiddenName: 'hiddenKkPaymentLinkCount', showMoreName: 'showMoreKkPaymentLinks',
  directLoop: /v-for="item in (?:kkPaymentLinks|filteredKkPaymentLinks)"/,
})

for (const [file, label] of [
  ['BrazilPixPage.vue', 'PIX'],
  ['IndiaUpiPage.vue', 'UPI'],
  ['KakaoPayPage.vue', 'Kakao'],
  ['MomoPage.vue', 'MoMo'],
  ['GCashPhPage.vue', 'GCash'],
]) {
  assertRenderWindow(file, {
    label: `${label} stored links`,
    sourceName: 'links', visibleName: 'visibleLinks', countName: 'linkVisibleCount', hiddenName: 'hiddenLinkCount', showMoreName: 'showMoreLinks',
    directLoop: /v-for="link in links"/,
  })
  assertRecentResultWindow(file, label)
  assert.match(componentSource(file), /JSON\.stringify\(links\.value, null, 2\)/, `${label} export must continue using the complete source array`)
}

assert.match(componentSource('IdealLinkPage.vue'), /JSON\.stringify\(links\.value, null, 2\)/, 'iDEAL export must continue using the complete source array')
assert.match(componentSource('KakaoPayPage.vue'), /watch\(kkPaymentStatusFilter, \(\) => \{ kkPaymentLinkVisibleCount\.value = 100 \}\)/, 'Kakao payment filtering should reset the link render window')

for (const [file, label, sourceName, countName] of [
  ['IdealLinkPage.vue', 'iDEAL stored links', 'links', 'linkVisibleCount'],
  ['BrazilPixPage.vue', 'PIX stored links', 'links', 'linkVisibleCount'],
  ['BrazilPixPage.vue', 'PIX payment links', 'paymentLinks', 'paymentLinkVisibleCount'],
  ['BrazilPixPage.vue', 'PIX payment CDKs', 'paymentCdks', 'paymentCdkVisibleCount'],
  ['BrazilPixPage.vue', 'PIX recent results', 'currentResult', 'recentResultVisibleCount'],
  ['IndiaUpiPage.vue', 'UPI stored links', 'links', 'linkVisibleCount'],
  ['IndiaUpiPage.vue', 'UPI payment links', 'paymentLinks', 'paymentLinkVisibleCount'],
  ['IndiaUpiPage.vue', 'UPI payment CDKs', 'paymentCdks', 'paymentCdkVisibleCount'],
  ['IndiaUpiPage.vue', 'UPI temporary CDKs', 'tempCdks', 'tempCdkVisibleCount'],
  ['IndiaUpiPage.vue', 'UPI recent results', 'currentResult', 'recentResultVisibleCount'],
  ['KakaoPayPage.vue', 'Kakao stored links', 'links', 'linkVisibleCount'],
  ['KakaoPayPage.vue', 'Kakao temporary CDKs', 'tempCdks', 'tempCdkVisibleCount'],
  ['KakaoPayPage.vue', 'Kakao payment CDKs', 'kkPaymentCdks', 'kkPaymentCdkVisibleCount'],
  ['KakaoPayPage.vue', 'Kakao payment links', 'kkPaymentLinks', 'kkPaymentLinkVisibleCount'],
  ['KakaoPayPage.vue', 'Kakao recent results', 'currentResult', 'recentResultVisibleCount'],
  ['MomoPage.vue', 'MoMo stored links', 'links', 'linkVisibleCount'],
  ['MomoPage.vue', 'MoMo recent results', 'currentResult', 'recentResultVisibleCount'],
  ['GCashPhPage.vue', 'GCash stored links', 'links', 'linkVisibleCount'],
  ['GCashPhPage.vue', 'GCash recent results', 'currentResult', 'recentResultVisibleCount'],
]) {
  assertReplacementReset(file, label, sourceName, countName)
}

for (const spec of [
  {
    label: 'PayPal access-token pool',
    sourceName: 'filteredAccessTokenPool', visibleName: 'visibleAccessTokenPool', countName: 'accessTokenVisibleCount', hiddenName: 'hiddenAccessTokenCount', showMoreName: 'showMoreAccessTokens',
    directLoop: /v-for="item in filteredAccessTokenPool"/,
  },
  {
    label: 'PayPal stored links',
    sourceName: 'filteredLinks', visibleName: 'visibleLinks', countName: 'linkVisibleCount', hiddenName: 'hiddenLinkCount', showMoreName: 'showMoreLinks',
    directLoop: /v-for="link in filteredLinks"/,
  },
  {
    label: 'PayPal protocol account options',
    sourceName: 'protocolLinkAccountOptions', visibleName: 'visibleProtocolLinkAccountOptions', countName: 'protocolLinkVisibleCount', hiddenName: 'hiddenProtocolLinkCount', showMoreName: 'showMoreProtocolLinks',
    directLoop: /v-for="item in protocolLinkAccountOptions"/,
  },
  {
    label: 'PayPal 153 account options',
    sourceName: 'pay153LinkAccountOptions', visibleName: 'visiblePay153LinkAccountOptions', countName: 'pay153LinkVisibleCount', hiddenName: 'hiddenPay153LinkCount', showMoreName: 'showMorePay153Links',
    directLoop: /v-for="item in pay153LinkAccountOptions"/,
  },
  {
    label: 'PayPal protocol BA pool',
    sourceName: 'filteredProtocolBaPool', visibleName: 'visibleProtocolBaPool', countName: 'protocolBaVisibleCount', hiddenName: 'hiddenProtocolBaCount', showMoreName: 'showMoreProtocolBaPool',
    directLoop: /v-for="item in filteredProtocolBaPool"/,
  },
  {
    label: 'PayPal 153 BA pool',
    sourceName: 'filteredPay153BaPool', visibleName: 'visiblePay153BaPool', countName: 'pay153BaVisibleCount', hiddenName: 'hiddenPay153BaCount', showMoreName: 'showMorePay153BaPool',
    directLoop: /v-for="item in filteredPay153BaPool"/,
  },
  {
    label: 'PayPal protocol phone pool',
    sourceName: 'protocolPhonePoolEntries', visibleName: 'visibleProtocolPhonePoolEntries', countName: 'protocolPhoneVisibleCount', hiddenName: 'hiddenProtocolPhoneCount', showMoreName: 'showMoreProtocolPhones',
    directLoop: /v-for="item in phonePoolEntriesFor\(protocolForm\.phonePool, 'protocol'\)"/,
  },
  {
    label: 'PayPal 153 phone pool',
    sourceName: 'pay153PhonePoolEntries', visibleName: 'visiblePay153PhonePoolEntries', countName: 'pay153PhoneVisibleCount', hiddenName: 'hiddenPay153PhoneCount', showMoreName: 'showMorePay153Phones',
    directLoop: /v-for="item in phonePoolEntriesFor\(pay153Form\.phonePool, 'pay153'\)"/,
  },
]) {
  assertRenderWindow('UsPaypalPage.vue', spec)
}

assertRecentResultWindow('UsPaypalPage.vue', 'PayPal')

for (const [label, sourceName, countName] of [
  ['PayPal access-token pool', 'accessTokenPool', 'accessTokenVisibleCount'],
  ['PayPal stored links', 'links', 'linkVisibleCount'],
  ['PayPal protocol BA pool', 'protocolBaPool', 'protocolBaVisibleCount'],
  ['PayPal 153 BA pool', 'pay153BaPool', 'pay153BaVisibleCount'],
  ['PayPal recent results', 'currentResult', 'recentResultVisibleCount'],
]) {
  assertReplacementReset('UsPaypalPage.vue', label, sourceName, countName)
}

const paypalSource = componentSource('UsPaypalPage.vue')
for (const [label, filterName, countName] of [
  ['access-token status', 'accessTokenStatusFilter', 'accessTokenVisibleCount'],
  ['stored-link country', 'linkCountryFilter', 'linkVisibleCount'],
  ['protocol BA status', 'protocolBaStatusFilter', 'protocolBaVisibleCount'],
  ['153 BA status', 'pay153BaStatusFilter', 'pay153BaVisibleCount'],
]) {
  assert.match(paypalSource, new RegExp(`watch\\(${filterName}, \\(\\) => \\{ ${countName}\\.value = 100 \\}\\)`), `PayPal ${label} filtering should reset its render window`)
}
for (const [label, formName, countName] of [
  ['protocol phone pool', 'protocolForm', 'protocolPhoneVisibleCount'],
  ['153 phone pool', 'pay153Form', 'pay153PhoneVisibleCount'],
]) {
  assert.match(paypalSource, new RegExp(`watch\\(\\(\\) => ${formName}\\.value\\.phonePool, \\(\\) => \\{ ${countName}\\.value = 100 \\}\\)`), `PayPal ${label} replacement should reset its render window`)
}
assert.match(paypalSource, /watch\(protocolLinkCountryFilter, \(\) => \{[\s\S]{0,500}?protocolLinkVisibleCount\.value = 100/, 'PayPal protocol country filtering should reset its render window')
assert.match(paypalSource, /watch\(protocolLinkTimeFilter, \(\) => \{[\s\S]{0,500}?protocolLinkVisibleCount\.value = 100/, 'PayPal protocol time filtering should reset its render window')
assert.match(paypalSource, /watch\(protocolLinkStatusFilter, \(\) => \{[\s\S]{0,500}?protocolLinkVisibleCount\.value = 100/, 'PayPal protocol status filtering should reset its render window')
assert.match(paypalSource, /watch\(protocolLinkSortOrder, \(\) => \{ protocolLinkVisibleCount\.value = 100 \}\)/, 'PayPal protocol sorting should reset its render window')
assert.match(paypalSource, /watch\(pay153LinkCountryFilter, \(\) => \{[\s\S]{0,500}?pay153LinkVisibleCount\.value = 100/, 'PayPal 153 country filtering should reset its render window')
assert.match(paypalSource, /watch\(pay153LinkTimeFilter, \(\) => \{[\s\S]{0,500}?pay153LinkVisibleCount\.value = 100/, 'PayPal 153 time filtering should reset its render window')
assert.match(paypalSource, /watch\(pay153LinkStatusFilter, \(\) => \{[\s\S]{0,500}?pay153LinkVisibleCount\.value = 100/, 'PayPal 153 status filtering should reset its render window')
assert.match(paypalSource, /watch\(pay153LinkSortOrder, \(\) => \{ pay153LinkVisibleCount\.value = 100 \}\)/, 'PayPal 153 sorting should reset its render window')
assert.match(paypalSource, /watch\(\[accounts, links\], \(\) => \{[\s\S]{0,700}?protocolLinkVisibleCount\.value = 100[\s\S]{0,300}?pay153LinkVisibleCount\.value = 100/, 'PayPal account/link replacement should reset both payment-account windows')

assert.match(paypalSource, /logs\.value = Array\.isArray\(job\.logs\) \? job\.logs\.slice\(-200\) : \[\]/, 'PayPal live extraction logs should keep only the newest 200 rows')
assert.match(paypalSource, /protocolLogs\.value = Array\.isArray\(job\.logs\) \? job\.logs\.slice\(-200\) : \[\]/, 'PayPal live protocol logs should keep only the newest 200 rows')
assert.match(paypalSource, /pay153Logs\.value = Array\.isArray\(job\.logs\) \? job\.logs\.slice\(-200\) : \[\]/, 'PayPal live 153 logs should keep only the newest 200 rows')
assert.match(paypalSource, /return compactPaymentJobSnapshot\(\{ jobId, job, logs, result, statusText, statusError, fallback \}\)/, 'PayPal should retain the shared compact snapshot helper contract')
assert.match(paypalSource, /JSON\.stringify\(filteredLinks\.value, null, 2\)/, 'PayPal export should continue using the complete filtered source instead of the DOM window')
assert.match(paypalSource, /selectedAccessTokenIds\.value = new Set\(filteredAccessTokenPool\.value\.filter/, 'PayPal access-token bulk selection should continue using the complete filtered source')
assert.match(paypalSource, /selectedProtocolAccountEmails\.value = new Set\(protocolLinkAccountOptions\.value\.filter/, 'PayPal protocol bulk selection should continue using the complete filtered source')
assert.match(paypalSource, /selectedPay153AccountEmails\.value = new Set\(pay153LinkAccountOptions\.value\.filter/, 'PayPal 153 bulk selection should continue using the complete filtered source')

console.log('payment list render-window contract passed')
