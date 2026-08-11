import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(__dirname, '..')
const api = readFileSync(resolve(webRoot, 'src/api.js'), 'utf8')
const page = readFileSync(resolve(webRoot, 'src/components/UsPaypalPage.vue'), 'utf8')
const template = page.split('<script setup>')[0]
const titleSection = page.slice(page.indexOf('<h2 class="mt-1 text-2xl font-bold text-white">PayPal 任务</h2>'), page.indexOf(`<template v-if="activeTab === 'links'">`))
const pay153Section = page.slice(page.indexOf(`<section v-else-if="activeTab === 'pay153'"`), page.indexOf('</template>'))
const pay153DrainSection = page.slice(page.indexOf('async function drainPay153AutoPayQueue'), page.indexOf('function splitProtocolLines'))

for (const name of [
  'startUsPaypal153Batch',
  'getUsPaypal153Job',
  'cancelUsPaypal153Job',
  'cancelUsPaypal153RemoteByBa',
  'submitUsPaypal153Otp',
  'submitUsPaypal153Captcha',
  'getUsPaypal153SupportedCountries',
  'getUsPaypal153Stats',
]) {
  assert.match(api, new RegExp(`${name}:`), `api.js exposes ${name}`)
}

assert.match(api, /\/us-paypal\/pay153\/batch\/start/, 'Pay153 batch start endpoint is wired')
assert.match(api, /\/us-paypal\/pay153\/remote\/cancel-by-ba/, 'Pay153 remote cancel-by-BA endpoint is wired')
assert.match(api, /\/us-paypal\/pay153\/jobs\/\$\{encodeURIComponent\(jobId\)\}\/otp/, 'Pay153 OTP endpoint is wired')
assert.match(api, /\/us-paypal\/pay153\/jobs\/\$\{encodeURIComponent\(jobId\)\}\/captcha/, 'Pay153 captcha endpoint is wired')

assert.match(page, />\s*153支付\s*</, 'PayPal page contains the 153支付 tab')
assert.match(page, /activeTab === 'pay153'/, '153支付 tab has active state')
assert.match(page, /pay153Form/, '153支付 has dedicated form state')
assert.match(page, /pay153Form[\s\S]*country/, '153支付 form stores selected country')
assert.match(page, /pay153Form[\s\S]*smsProvider/, '153支付 form stores phone provider')
assert.match(page, /startPay153Payment/, '153支付 has submit handler')
assert.match(page, /api\.startUsPaypal153Batch/, '153支付 submits through local backend batch API')
assert.match(page, /pay153SelectedEmails/, '153支付 supports multi-select account submission')
assert.match(page, /refreshLinks\(\)/, '153支付页面支持刷新链接列表')
assert.match(page, /失败重试/, '153支付页面支持上一轮失败账号重试')
assert.match(page, /retryFailedPay153Payment/, '153支付有失败重试处理函数')
assert.match(page, /清理153卡住任务/, '153支付页支持手动清理 already processing 的远端任务')
assert.match(page, /cancelPay153RemoteByCurrentBa[\s\S]*cancelUsPaypal153RemoteByBa/, '153支付按当前 BA 调用远端清理接口')
assert.match(page, /账号支付失败自动重试最多 3 次/, '153支付页面说明账号支付失败会自动重试3次')
assert.match(page, /successfulPayPalLinkAccounts\(accounts\.value, links\.value, 'all'\)/, '153支付失败重试不受当前筛选限制')
assert.match(page, /pay153FailedEmails/, '153支付会记录上一轮失败账号')
assert.match(page, /v-model="pay153Form\.country"/, '153支付 exposes country selector')
assert.match(page, /v-model="pay153Form\.smsProvider"/, '153支付 exposes phone provider selector')
assert.match(page, /pay153LinkTimeFilter/, '153支付链接列表支持按提取时间筛选')
assert.match(page, /pay153LinkAccountOptions = computed\(\(\) => successfulPayPalLinkAccounts\(accounts\.value, links\.value, pay153LinkCountryFilter\.value, \{ timeFilter: pay153LinkTimeFilter\.value \}\)\)/, '153支付链接列表只取未支付且有效期内，并支持时间筛选')
assert.match(page, /watch\(activeTab[\s\S]*refreshPaymentLinks/, '切换到153支付会自动刷新链接列表')
assert.match(page, /async function refreshPaymentLinks[\s\S]*refreshAccounts\(\)[\s\S]*refreshLinks\(\)/, '153支付刷新链接列表同步提链页最新链接')
assert.match(page, /提取时间/, '153支付链接列表显示链接提取时间')
assert.match(page, /链接有效期/, '153支付链接列表显示链接有效期')
assert.match(page, /60 秒未收到验证码自动换号，最多 3 次/, '153支付页面说明 HeroSMS/SMSBower 自动换号策略')
assert.match(page, /phonePool/, '153支付 supports fixed SMS phone pool import')
assert.match(page, /手机号----SMS record URL/, '153支付 documents phone pool import format')
assert.match(page, /phonePool:\s*pay153Form\.value\.smsProvider === 'sms_record' \? \(phonePoolReuseEnabled\.value \? phonePoolPayloadForSubmission\(pay153Form\.value\.phonePool, 'pay153'\) : formatPhonePoolEntries\(claimedPhonePoolEntries\)\) : pay153Form\.value\.phonePool/, '153支付 sends pre-claimed phonePool payload')
assert.match(page, /phonePoolReuseEnabled:\s*phonePoolReuseEnabled\.value/, '153支付提交手机号复用开关')
assert.equal(page.includes('共享设置'), false, '手机号复用不再放在顶部长条共享设置')
assert.match(page, /savePay153Form[\s\S]{0,260}togglePhonePoolReuse/, '153支付手机号复用按钮放在保存输入旁边')
assert.match(page, /加入手机号池/, '手机号池管理采用参考图的顶部加入按钮')
assert.match(page, /清理已使用/, '手机号池管理采用参考图的顶部清理按钮')
assert.match(page, /removePhonePoolEntry/, '手机号池管理支持单条移除')
assert.match(page, /purgeUsedPhonePoolEntries/, '手机号池管理支持批量清理已使用号码')
assert.match(page, /phonePoolStatusMap/, '独立手机号池管理区维护手机号状态')
assert.match(page, /syncPhonePoolStatusFromJobResult/, '153支付结束后同步手机号状态')
assert.match(page, /usablePhonePoolEntriesFromText[\s\S]*status === 'available' \|\| status === 'failed'/, '153支付号池关闭复用时失败号码仍可再次领取')
assert.match(page, /releaseClaimedPhonePoolEntriesAfterJob[\s\S]*'failed'/, '153支付任务结束后释放本轮未成功的已领取号码为失败可复用')
assert.match(page, /pollPay153Job[\s\S]*releaseClaimedPhonePoolEntriesAfterJob/, '153支付轮询终态会释放卡住的手机号')
assert.match(page, /开启手机号复用/, '153支付页面显示手机号复用开关')
assert.match(page, /togglePhonePoolReuse/, '153支付页面可以切换手机号复用开关')
assert.match(page, /PHONE_POOL_REUSE_STORAGE_KEY/, '153支付页会持久化手机号复用开关')
assert.match(page, /extractBaTokenText|displayBaToken/, '153支付列表只展示 BA token 段')
assert.match(page, /已支付/, '153支付账号列表会标记已支付账号')
assert.match(page, /item\.paypalStatus === 'paid'/, '153支付账号列表会禁用已支付账号')
assert.match(page, /pay153PaymentAccountStatus\(item\)/, '153支付列表按当前支付任务状态显示账号状态')
assert.match(page, /pay153PaymentAccountStatusText[\s\S]*支付中/, '153支付中账号状态显示为支付中')
assert.match(page, /if \(status === 'failed' \|\| status === 'error'\) return '支付失败'/, '153支付列表失败状态统一显示支付失败')
assert.doesNotMatch(page, /function pay153PaymentAccountStatusText[\s\S]*提链失败/, '153支付列表失败状态显示为支付失败，不显示提链失败')
assert.match(page, /153支付代理池/, '153支付 exposes proxy pool input')
assert.match(page, /pay153PaymentStats/, '153支付页有当前支付数据看板')
assert.match(titleSection, /v-if="activeTab === 'pay153'"[\s\S]*153支付看板[\s\S]*pay153PaymentStats/, '153支付看板放在 PayPal 任务标题下面且只在153支付页显示')
assert.match(titleSection, /153支付看板[\s\S]*grid-cols-6[\s\S]*pay153PaymentStats/, '153支付看板指标横向排成一排')
assert.doesNotMatch(titleSection, /v-if="activeTab === 'links'"[\s\S]*153支付看板/, '提链页不显示153支付看板')
assert.doesNotMatch(pay153Section, /当前支付数据[\s\S]*153支付看板/, '153支付主体内不再放看板')
assert.match(page, /ACTIVE_TAB_STORAGE_KEY/, '刷新页面后会恢复当前 PayPal tab')
assert.match(page, /persistPay153JobState/, '153支付会持久化任务状态和日志快照')
assert.match(page, /restorePay153JobState/, '153支付刷新页面后会恢复任务状态和日志快照')
assert.match(page, /resumePay153JobStateFromStorage/, '切回153支付页会从本地快照恢复任务状态和日志')
assert.match(page, /watch\(activeTab[\s\S]*resumePay153JobStateFromStorage/, '切换回153支付页会恢复并续轮询153支付任务')
assert.match(page, /自动支付/, '153支付页提供自动支付按钮')
assert.match(page, /AUTO_PAYMENT_POLL_MS\s*=\s*60\s*\*\s*1000/, '自动支付每1分钟刷新一次链接')
assert.match(page, /AUTO_PAYMENT_IDLE_LIMIT_MS\s*=\s*30\s*\*\s*60\s*\*\s*1000/, '自动支付30分钟没有新链接后结束')
assert.match(page, /pay153AutoPayQueue/, '153支付维护自动支付队列')
assert.match(page, /pay153AutoPayActiveJobs/, '153支付自动支付维护并发运行槽')
assert.match(page, /togglePay153AutoPay/, '153支付自动支付按钮可启动或停止')
assert.match(page, /scanPay153AutoPayLinks[\s\S]*refreshPaymentLinks/, '153支付自动支付会刷新最新链接数据')
assert.match(page, /scanPay153AutoPayLinks[\s\S]*pay153AutoPayQueue/, '153支付自动支付会把新链接追加到支付队列')
assert.match(page, /drainPay153AutoPayQueue[\s\S]*availableSlots[\s\S]*launchPay153AutoPayItem/, '153支付自动队列按空闲并发槽立即补任务')
assert.doesNotMatch(pay153DrainSection, /await startPay153Payment/, '153支付自动队列不再等待上一批全部完成才启动下一批')
assert.equal(template.includes('v-model.trim="pay153ActionInputs[child.remote_job_id]"'), false, '153支付页不显示手动输入验证码的输入框')
assert.equal(template.includes('submitPay153Otp(child)'), false, '153支付页不显示手动提交验证码按钮')
assert.equal(template.includes('等待自动接码'), false, '153支付页不显示等待自动接码提示块')
assert.equal(template.includes('v-if="pay153WaitingActions.length"'), false, '153支付页不渲染等待操作卡片列表')

console.log('paypal 153 UI tests passed')
