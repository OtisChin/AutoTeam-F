import assert from 'node:assert/strict'
import {
  successfulPayPalLinkAccounts,
  paypalAccountCountryOptions,
  resolveSelectedPayPalLinkAccount,
} from '../src/paypalAccountOptions.js'

const accounts = [
  { email: 'new-nl@example.com', paypal_status: 'success', paypal_country: 'NL', last_active_at: 300 },
  { email: 'old-us@example.com', paypal_status: 'success', paypal_country: 'US', last_active_at: 100 },
  { email: 'failed-nl@example.com', paypal_status: 'failed', paypal_country: 'NL', last_active_at: 400 },
  { email: 'paid-br@example.com', paypal_status: 'paid', paypal_country: 'BR', last_active_at: 500 },
]
const links = [
  { id: 'link-us', account_email: 'old-us@example.com', country: 'US', paypal_link: 'https://paypal.test/us', updated_at: 200 },
  { id: 'link-nl', account_email: 'new-nl@example.com', country: 'NL', paypal_link: 'https://paypal.test/nl', updated_at: 350 },
  { id: 'link-orphan', account_email: 'orphan@example.com', country: 'GB', paypal_link: 'https://paypal.test/gb', updated_at: 600 },
]

function testSuccessfulAccountsJoinLatestLinkAndFilterByCountry() {
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'NL').map((item) => ({ email: item.email, country: item.country, link: item.paypalLink })),
    [{ email: 'new-nl@example.com', country: 'NL', link: 'https://paypal.test/nl' }],
  )
  assert.deepEqual(
    successfulPayPalLinkAccounts(accounts, links, 'all').map((item) => item.email),
    ['new-nl@example.com', 'old-us@example.com'],
  )
}

function testCountryOptionsComeFromSuccessfulLinkedAccounts() {
  assert.deepEqual(paypalAccountCountryOptions(accounts, links), ['NL', 'US'])
}

function testSelectedAccountPopulatesProtocolFormFields() {
  assert.deepEqual(resolveSelectedPayPalLinkAccount(accounts, links, 'new-nl@example.com'), {
    email: 'new-nl@example.com',
    country: 'NL',
    paypalLink: 'https://paypal.test/nl',
  })
}

testSuccessfulAccountsJoinLatestLinkAndFilterByCountry()
testCountryOptionsComeFromSuccessfulLinkedAccounts()
testSelectedAccountPopulatesProtocolFormFields()
console.log('paypal account option tests passed')
