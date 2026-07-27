import assert from 'node:assert/strict'
import {
  bindPlanOptions,
  bindCountryOptions,
  countryCurrencyMap,
  buildBindLinkPayload,
  bindPlanLabel,
  resolveCheckoutLink,
} from '../src/bindLinkPayload.js'

function testPlanAndCountryOptions() {
  assert.deepEqual(bindPlanOptions.map((item) => item.value), ['plus_trial', 'plus', 'pro5x', 'pro20x', 'team'])
  assert.deepEqual(
    bindCountryOptions.map((item) => `${item.country}:${item.currency}`),
    ['PH:PHP', 'EG:EGP', 'US:USD', 'JP:JPY', 'KR:KRW', 'IN:INR'],
  )
  assert.equal(countryCurrencyMap.PH, 'PHP')
  assert.equal(countryCurrencyMap.EG, 'EGP')
  assert.equal(countryCurrencyMap.KR, 'KRW')
  assert.equal(countryCurrencyMap.IN, 'INR')
  assert.equal(bindPlanLabel('plus_trial'), 'Plus 试用')
  assert.equal(bindPlanLabel('pro5x'), 'Pro 5x')
}

function testPlusTrialPayloadSelectsDedicatedExtractionFlow() {
  const payload = buildBindLinkPayload({
    accessToken: 'token-trial',
    planType: 'plus_trial',
    country: 'PH',
  })
  assert.deepEqual(payload, {
    access_token: 'token-trial',
    billing_details: { country: 'PH', currency: 'PHP' },
    checkout_ui_mode: 'hosted',
    entry_point: 'all_plans_pricing_modal',
    plan_name: 'chatgptplusplan',
    checkout_flow: 'plus_trial',
  })
  assert.equal(Object.hasOwn(payload, 'promo_campaign'), false)
}

function testPlusPayloadHasNoPromoAndUsesHostedPricingModal() {
  const payload = buildBindLinkPayload({
    accessToken: 'token-plus',
    planType: 'plus',
    country: 'US',
  })
  assert.deepEqual(payload, {
    access_token: 'token-plus',
    billing_details: { country: 'US', currency: 'USD' },
    checkout_ui_mode: 'hosted',
    entry_point: 'all_plans_pricing_modal',
    plan_name: 'chatgptplusplan',
  })
  assert.equal(Object.hasOwn(payload, 'promo_campaign'), false)
}

function testProPayloadsUsePhilippinesCurrency() {
  assert.equal(
    buildBindLinkPayload({ accessToken: 'token-pro5', planType: 'pro5x', country: 'PH' }).plan_name,
    'chatgptprolite',
  )
  assert.deepEqual(
    buildBindLinkPayload({ accessToken: 'token-pro20', planType: 'pro20x', country: 'PH' }),
    {
      access_token: 'token-pro20',
      billing_details: { country: 'PH', currency: 'PHP' },
      checkout_ui_mode: 'hosted',
      entry_point: 'all_plans_pricing_modal',
      plan_name: 'chatgptpro',
    },
  )
}

function testTeamPayloadKeepsTeamDataOnly() {
  const payload = buildBindLinkPayload({
    accessToken: 'token-team',
    planType: 'team',
    country: 'PH',
    teamWorkspaceName: 'MyWorkspace',
    teamPriceInterval: 'month',
    teamSeatQuantity: 5,
  })
  assert.deepEqual(payload, {
    access_token: 'token-team',
    billing_details: { country: 'PH', currency: 'PHP' },
    checkout_ui_mode: 'hosted',
    entry_point: 'team_workspace_purchase_modal',
    plan_name: 'chatgptteamplan',
    team_plan_data: {
      workspace_name: 'MyWorkspace',
      price_interval: 'month',
      seat_quantity: 5,
    },
  })
  assert.equal(Object.hasOwn(payload, 'promo_code'), false)
}

function testCheckoutLinkResolutionMatchesChatgptRedirectShape() {
  assert.deepEqual(
    resolveCheckoutLink({
      checkout_session_id: 'cs_hosted',
      url: 'https://pay.openai.com/c/pay/cs_hosted#fid',
    }),
    {
      link: 'https://chatgpt.com/checkout/openai_llc/cs_hosted',
      sessionId: 'cs_hosted',
      rawGeneratedUrl: 'https://pay.openai.com/c/pay/cs_hosted#fid',
    },
  )
  assert.deepEqual(
    resolveCheckoutLink({ checkout_session_id: 'cs_123', url: '' }),
    { link: 'https://chatgpt.com/checkout/openai_llc/cs_123', sessionId: 'cs_123', rawGeneratedUrl: '' },
  )
  assert.deepEqual(
    resolveCheckoutLink({ checkout_session_id: 'cs_ie', processor_entity: 'openai_ie', url: '' }),
    { link: 'https://chatgpt.com/checkout/openai_ie/cs_ie', sessionId: 'cs_ie', rawGeneratedUrl: '' },
  )
  assert.deepEqual(
    resolveCheckoutLink({ url: 'https://pay.openai.com/c/pay/cs_demo#fid' }),
    { link: 'https://pay.openai.com/c/pay/cs_demo#fid', sessionId: '', rawGeneratedUrl: 'https://pay.openai.com/c/pay/cs_demo#fid' },
  )
}

testPlanAndCountryOptions()
testPlusTrialPayloadSelectsDedicatedExtractionFlow()
testPlusPayloadHasNoPromoAndUsesHostedPricingModal()
testProPayloadsUsePhilippinesCurrency()
testTeamPayloadKeepsTeamDataOnly()
testCheckoutLinkResolutionMatchesChatgptRedirectShape()
console.log('bind link payload tests passed')
