import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const kakaoPage = readFileSync(new URL('../src/components/KakaoPayPage.vue', import.meta.url), 'utf8')

assert.match(kakaoPage, /const JOB_STORAGE_KEY = 'autotoken_kakao_pay_job'/, 'Kakao Pay page has a stable job storage key')
assert.match(kakaoPage, /const TEMP_JOB_STORAGE_KEY = 'autotoken_kakao_pay_temp_job'/, 'Kakao Pay temp extraction has an independent stable job storage key')
assert.match(kakaoPage, /function saveActiveJobSnapshot\(/, 'Kakao Pay page persists active job snapshots')
assert.match(kakaoPage, /const storageKey = extractJobStorageKey\(snapshotMode\)[\s\S]*?persistJsonState\(storageKey, snapshot\)/, 'Kakao Pay page defers active-job persistence while mounted and preserves late acknowledged jobs after unmount')
assert.match(kakaoPage, /sessionStorage\.getItem\(extractJobStorageKey\(mode\)\)/, 'Kakao Pay page reads the saved job through the session-owner fence for the requested extraction mode')
assert.match(kakaoPage, /async function restoreActiveJob\(mode = 'extract'\)/, 'Kakao Pay page restores normal and temp jobs independently')
assert.match(kakaoPage, /await Promise\.all\(\[restoreActiveJob\('extract'\), restoreActiveJob\('tempExtract'\), restoreRunningKkPaymentOrders\(\)\]\)/, 'Kakao Pay page invokes both extraction restores during mount')
assert.match(kakaoPage, /state\.logs = Array\.isArray\(saved\.logs\) \? saved\.logs : \[\]/, 'Kakao Pay page restores bounded logs from its persisted snapshot')
assert.match(kakaoPage, /if \(terminal\) return\s+if \(!componentUnmounted\) startPolling\(mode\)/, 'Kakao Pay page resumes polling only for mounted non-terminal jobs')
assert.match(kakaoPage, /function clearActiveJob\(\{ removeStored = true, mode = isTempExtract\.value \? 'tempExtract' : 'extract' \} = \{\}\)/, 'Kakao Pay page can clear a selected saved job')
assert.match(kakaoPage, /return String\(link\?\.provider_redirect_url \|\| link\?\.kakao_link \|\| link\?\.stripe_redirect_url \|\| link\?\.paymentUrl \|\| link\?\.payment_url \|\| link\?\.value \|\| ''\)\.trim\(\)/, 'Kakao Pay page copies/opens Nicepay provider URL before Stripe intermediate and legacy URL fields')
assert.doesNotMatch(kakaoPage, /复制 provider/, 'Kakao Pay page does not render a separate provider-copy button')
assert.doesNotMatch(kakaoPage, /copy\(link\.provider_redirect_url\)/, 'Kakao Pay page only exposes one copy-link action')
