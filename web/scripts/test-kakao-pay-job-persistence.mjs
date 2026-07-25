import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const kakaoPage = readFileSync(new URL('../src/components/KakaoPayPage.vue', import.meta.url), 'utf8')

assert.match(kakaoPage, /const JOB_STORAGE_KEY = 'autotoken_kakao_pay_job'/, 'Kakao Pay page has a stable job storage key')
assert.match(kakaoPage, /function saveActiveJobSnapshot\(/, 'Kakao Pay page persists active job snapshots')
assert.match(kakaoPage, /localStorage\.setItem\(JOB_STORAGE_KEY/, 'Kakao Pay page writes active job id to localStorage')
assert.match(kakaoPage, /localStorage\.getItem\(JOB_STORAGE_KEY/, 'Kakao Pay page reads saved job id from localStorage')
assert.match(kakaoPage, /async function restoreActiveJob\(\)/, 'Kakao Pay page restores a saved job on mount')
assert.match(kakaoPage, /await restoreActiveJob\(\)/, 'Kakao Pay page invokes job restore during mount')
assert.match(kakaoPage, /api\.getKakaoPayJob\(activeJobId\.value\)/, 'Kakao Pay page reloads job status and logs from backend')
assert.match(kakaoPage, /logs\.value = Array\.isArray\(job\.logs\) \? job\.logs : \[\]/, 'Kakao Pay page restores logs from job payload')
assert.match(kakaoPage, /if \(!componentUnmounted && activeJobId\.value && !TERMINAL_STATUSES\.has\(activeJobStatus\.value\)\) startPolling\(\)/, 'Kakao Pay page resumes polling only for mounted non-terminal jobs')
assert.match(kakaoPage, /clearActiveJob\(\{ removeStored = true \} = \{\}\)/, 'Kakao Pay page can clear stale saved jobs')
assert.match(kakaoPage, /return String\(link\?\.provider_redirect_url \|\| link\?\.kakao_link \|\| link\?\.stripe_redirect_url \|\| ''\)\.trim\(\)/, 'Kakao Pay page copies/opens Nicepay provider URL before Stripe intermediate URL')
assert.doesNotMatch(kakaoPage, /复制 provider/, 'Kakao Pay page does not render a separate provider-copy button')
assert.doesNotMatch(kakaoPage, /copy\(link\.provider_redirect_url\)/, 'Kakao Pay page only exposes one copy-link action')
