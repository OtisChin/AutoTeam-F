import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/OAuthPhonePoolPage.vue', import.meta.url), 'utf8')

assert.match(source, /const OAUTH_PHONE_PAGE_SIZE = 100/, 'OAuth phone rows should use a bounded default page size')
assert.match(source, /const page = ref\(1\)/, 'OAuth phone rows should track the current page')
assert.match(source, /const pagedItems = computed\([\s\S]*?filteredItems\.value\.slice\(start, start \+ OAUTH_PHONE_PAGE_SIZE\)/, 'OAuth phone rows should expose only one bounded page')
assert.match(source, /v-for="item in pagedItems"/, 'the table should render only the current page')
assert.doesNotMatch(source, /v-for="item in filteredItems"/, 'the table must not mount every filtered phone row')
assert.match(source, /function draftFor\(item\)/, 'editable drafts should be created lazily for rendered rows')
assert.doesNotMatch(source, /for \(const item of nextItems\)\s*\{\s*drafts\[item\.id\]/, 'refresh must not eagerly create thousands of deep reactive drafts')
assert.match(source, /const visible = pagedItems\.value\.map/, 'page selection should operate on the rendered page')
assert.match(source, /watch\(keyword, \(\) => \{ page\.value = 1 \}\)/, 'filter changes should reset pagination')
assert.match(source, /watch\(totalPages,[\s\S]*?page\.value > value[\s\S]*?page\.value = value/, 'data changes should clamp the current page')

console.log('OAuth phone pool performance contract passed')
