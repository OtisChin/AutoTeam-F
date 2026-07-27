export const bindPlanOptions = [
  { value: 'plus_trial', label: 'Plus 试用', planName: 'chatgptplusplan', checkoutFlow: 'plus_trial' },
  { value: 'plus', label: 'Plus', planName: 'chatgptplusplan' },
  { value: 'pro5x', label: 'Pro 5x', planName: 'chatgptprolite' },
  { value: 'pro20x', label: 'Pro 20x', planName: 'chatgptpro' },
  { value: 'team', label: 'Team', planName: 'chatgptteamplan' },
]

export const bindCountryOptions = [
  { country: 'PH', currency: 'PHP', label: '菲律宾（PHP）' },
  { country: 'EG', currency: 'EGP', label: '埃及（EGP）' },
  { country: 'US', currency: 'USD', label: '美国（USD）' },
  { country: 'JP', currency: 'JPY', label: '日本（JPY）' },
  { country: 'KR', currency: 'KRW', label: '韩国（KRW）' },
  { country: 'IN', currency: 'INR', label: '印度（INR）' },
]

export const countryCurrencyMap = Object.fromEntries(
  bindCountryOptions.map((item) => [item.country, item.currency]),
)

export function bindPlanLabel(planType) {
  return bindPlanOptions.find((item) => item.value === planType)?.label || String(planType || '')
}

export function buildBindLinkPayload({
  accessToken,
  planType = 'plus',
  country = 'PH',
  teamWorkspaceName = 'MyWorkspace',
  teamPriceInterval = 'month',
  teamSeatQuantity = 5,
} = {}) {
  const selectedPlan = bindPlanOptions.find((item) => item.value === planType) || bindPlanOptions[0]
  const normalizedCountry = String(country || 'PH').trim().toUpperCase() || 'PH'
  const billingDetails = {
    country: normalizedCountry,
    currency: countryCurrencyMap[normalizedCountry] || 'USD',
  }

  const payload = {
    access_token: accessToken,
    billing_details: billingDetails,
    checkout_ui_mode: 'hosted',
    entry_point: selectedPlan.value === 'team' ? 'team_workspace_purchase_modal' : 'all_plans_pricing_modal',
    plan_name: selectedPlan.planName,
  }

  if (selectedPlan.checkoutFlow) {
    payload.checkout_flow = selectedPlan.checkoutFlow
  }

  if (selectedPlan.value === 'team') {
    payload.team_plan_data = {
      workspace_name: String(teamWorkspaceName || '').trim() || 'MyWorkspace',
      price_interval: String(teamPriceInterval || '').trim() || 'month',
      seat_quantity: Number(teamSeatQuantity) || 5,
    }
  }

  return payload
}

export function resolveCheckoutLink(result) {
  if (result?.checkout_session_id) {
    const sessionId = result.checkout_session_id
    const processorEntity = String(result?.processor_entity || 'openai_llc').trim() || 'openai_llc'
    return {
      link: `https://chatgpt.com/checkout/${processorEntity}/${sessionId}`,
      sessionId,
      rawGeneratedUrl: result?.url || '',
    }
  }
  if (result?.url) {
    return {
      link: result.url,
      sessionId: '',
      rawGeneratedUrl: result.url,
    }
  }
  return null
}
