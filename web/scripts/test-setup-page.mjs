import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/SetupPage.vue', import.meta.url), 'utf8')

assert.match(
  source,
  /const providerFieldKeys = computed\([\s\S]*Object\.values\(providerFieldGroups\.value\)[\s\S]*field\.key/,
  'provider-specific fields should be derived from every schema provider instead of a hard-coded prefix list',
)
assert.match(
  source,
  /const commonFields = computed\([\s\S]*!providerFieldKeys\.value\.has\(field\.key\)/,
  'provider-specific fields must not render a second time in the common section',
)
assert.match(
  source,
  /providerOptions\.value\.find\([\s\S]*option\.value === provider\.value[\s\S]*option\?\.label/,
  'the provider section title should use the selected schema option label',
)
assert.match(
  source,
  /if \(!providerFields\.value\.length\) return ''/,
  'providers without fields should not render a misleading configuration heading',
)
assert.match(source, /if \(configured\.value \|\| saving\.value\) return/, 'setup save should reject duplicate submissions')
assert.match(source, /configured\.value = true[\s\S]*emit\('configured', result\.api_key\)/, 'setup should synchronously emit the generated key exactly once')
assert.doesNotMatch(source, /setTimeout\([\s\S]*emit\('configured'/, 'setup completion should not leave a duplicate-submit timer window')
assert.match(source, /:disabled="saving \|\| configured"/, 'the setup submit button should remain disabled after a successful save')
assert.match(source, /for="setup-mail-provider"[\s\S]*id="setup-mail-provider"/, 'the provider label should identify its select control')
assert.match(source, /:for="fieldInputId\(field\)"[\s\S]*:id="fieldInputId\(field\)"/, 'schema labels should identify their generated input controls')
assert.ok((source.match(/:required="!field\.optional"/g) || []).length >= 2, 'both provider and common required inputs should expose native required semantics')
assert.ok((source.match(/:aria-required="!field\.optional"/g) || []).length >= 2, 'both provider and common required inputs should announce required semantics')
assert.match(source, /:role="messageRole"[\s\S]*aria-live="polite"/, 'setup success and failure feedback should be announced')

console.log('setup page provider and completion contracts passed')
