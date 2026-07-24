import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const __dirname = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(__dirname, '..')
const page = readFileSync(resolve(webRoot, 'src/components/UsPaypalPage.vue'), 'utf8')

assert.equal(page.includes('关联账号邮箱（可选）'), false, '协议支付页不再显示手动关联账号邮箱输入项')
assert.equal(page.includes('支付成功后标记为 Plus/paid'), false, '移除关联账号邮箱输入框说明文案')
assert.equal(page.includes('HeroSMS 接码配置由后端固定读取。'), false, '协议支付页不再显示 HeroSMS 后端固定读取文案')
assert.equal(page.includes('后端会按支付国家自动选择 Country ID'), false, '协议支付页不再显示国家 ID 自动选择说明')
assert.equal(page.includes('Service 默认 ts'), false, '协议支付页不再显示固定 Service/API 配置说明')
assert.match(page, /protocolForm\.value\.accountEmail\s*=\s*selected\.email/, '选择已成功提链账号时仍自动关联账号邮箱')
assert.match(page, /<option value="hero_sms_rent">HeroSMS 长效号（已购买）<\/option>/, '协议支付页支持选择 HeroSMS 长效号')
assert.match(page, /protocolForm\.smsProvider === 'hero_sms_rent'/, 'HeroSMS 长效号模式有独立输入区')
assert.match(page, /HeroSMS 长效号码/, 'HeroSMS 长效号模式要求输入已购买号码')
assert.match(page, /请填写 HeroSMS 长效号码。/, 'HeroSMS 长效号提交前校验号码')
assert.match(page, /selectedProtocolAccountEmails/, '协议支付页支持多选已提链账号')
assert.match(page, /protocolForm\.concurrency/, '协议支付页支持配置并发支付数')
assert.match(page, /api\.startUsPaypalProtocolBatch/, '多账号协议支付使用批量启动接口')
assert.match(page, /accountEmails:\s*protocolSelectedEmails\.value/, '批量协议支付提交选中的账号邮箱')
assert.match(page, /每行一个.*长效号码/s, '批量 HeroSMS 长效号提示按行分配号码')
for (const country of ['BR', 'CA', 'GB', 'ID', 'JP', 'MX', 'PH', 'TH', 'NL']) {
  assert.match(page, new RegExp(`<option value="${country}">`), `协议支付国家下拉支持 ${country}`)
  assert.match(page, new RegExp(`PROTOCOL_COUNTRIES = new Set\\(\\[[^\\]]*'${country}'`, 's'), `协议支付校验支持 ${country}`)
}
assert.match(page, /当前协议支付支持 BR\/CA\/GB\/ID\/JP\/MX\/PH\/TH\/NL/, '协议支付错误提示列出新增国家')

console.log('paypal protocol UI tests passed')
