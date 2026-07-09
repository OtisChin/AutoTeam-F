<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">本地任务系统</p>
          <h2 class="mt-1 text-2xl font-bold text-white">iDEAL 链提取</h2>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full bg-emerald-400"></span>
          本地服务在线
        </span>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-4 md:p-5">
      <div class="grid gap-4 md:grid-cols-[1fr_1fr_1fr]">
        <div v-for="step in workflowSteps" :key="step.id" class="flex items-center gap-3">
          <span
            class="flex h-9 w-9 shrink-0 items-center justify-center rounded-full border text-sm font-bold"
            :class="workflowStage >= step.id ? 'border-emerald-400 bg-emerald-500 text-white' : 'border-gray-700 bg-gray-900 text-gray-500'"
          >
            {{ step.id }}
          </span>
          <div class="min-w-0">
            <div class="text-sm font-semibold" :class="workflowStage >= step.id ? 'text-white' : 'text-gray-400'">{{ step.title }}</div>
            <div class="text-xs text-gray-500">{{ step.caption }}</div>
          </div>
        </div>
      </div>
    </section>

    <div class="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(420px,0.8fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p class="text-xs font-semibold text-gray-500">任务输入</p>
            <h3 class="mt-1 text-xl font-bold text-white">授权与链路参数</h3>
          </div>
          <span class="text-sm font-semibold text-emerald-400">Token 不写入本地记录</span>
        </div>

        <div class="mt-5 space-y-5">
          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">Access Token 或 session JSON</span>
            <textarea
              v-model.trim="form.accessToken"
              rows="6"
              autocomplete="off"
              spellcheck="false"
              placeholder="粘贴已有授权 Token"
              class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white transition placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              :disabled="busy"
            ></textarea>
            <span class="mt-1 block text-xs text-gray-500">{{ tokenMeta }}</span>
          </label>

          <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">链类型</span>
              <select disabled class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2.5 text-sm text-gray-500">
                <option>iDEAL link (NL → NL)</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">支付页模式</span>
              <select v-model="form.checkoutUiMode" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
                <option value="hosted">hosted: pay.openai.com</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">支付页语言</span>
              <select v-model="form.paymentLocale" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
                <option value="auto">自动跟随链路</option>
                <option value="en">英文</option>
                <option value="nl-NL">荷兰语</option>
                <option value="zh-CN">简体中文</option>
                <option value="zh-TW">繁体中文</option>
                <option value="ja">日文</option>
                <option value="ko">韩文</option>
                <option value="de">德文</option>
                <option value="fr">法文</option>
                <option value="es">西班牙文</option>
                <option value="id">印尼文</option>
                <option value="pt-BR">葡萄牙文</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">地区</span>
              <select disabled class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2.5 text-sm text-gray-400">
                <option>荷兰 NL</option>
              </select>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">币种</span>
              <input value="EUR" readonly class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2.5 text-sm text-gray-400" />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">自定义出口代理</span>
              <input
                v-model.trim="form.proxy"
                placeholder="留空使用后台默认代理"
                class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
                :disabled="busy"
              />
            </label>
          </div>

          <details class="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
            <summary class="cursor-pointer text-sm font-semibold text-gray-200">高级设置</summary>
            <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Stripe Publishable Key</span>
                <input v-model.trim="form.stripePublishableKey" placeholder="pk_live_..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Device ID</span>
                <input v-model.trim="form.deviceId" placeholder="留空自动生成" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">客户端指纹</span>
                <select v-model="form.clientFingerprint" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
                  <option value="chrome">Chrome 桌面</option>
                  <option value="apple-safari">Apple Safari</option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">User Agent</span>
                <input v-model.trim="form.userAgent" placeholder="留空使用默认 UA" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">代理链路</span>
                <select v-model="form.proxyChainPreset" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
                  <option value="default">源码默认</option>
                  <option value="dual_ideal">双链路 JP→NL + NL→NL</option>
                  <option value="JP_NL">日本 JP → 荷兰 NL</option>
                  <option value="NL_NL">荷兰 NL → 荷兰 NL</option>
                  <option value="US_US">美国 US → 美国 US</option>
                  <option value="JP_US">日本 JP → 美国 US</option>
                  <option value="JP_US_US">JP → US → approve US</option>
                  <option value="JP_US_JP">JP → US → approve JP</option>
                  <option value="JP_JP">日本 JP → 日本 JP</option>
                  <option value="US_JP">美国 US → 日本 JP</option>
                  <option value="parallel4">同时跑 4 策略</option>
                  <option value="matrix8">Matrix 8 combos</option>
                  <option value="sequential8">Sequential 8 combos</option>
                  <option value="manual">手动选择</option>
                </select>
              </label>
              <label class="flex items-center gap-2 self-end rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2 text-sm text-gray-300">
                <input v-model="form.diagnosticEnabled" type="checkbox" class="accent-blue-500" :disabled="busy" />
                开启诊断抓取
              </label>
              <template v-if="form.proxyChainPreset === 'manual'">
                <label class="block">
                  <span class="mb-1.5 block text-xs text-gray-400">前段代理地区</span>
                  <input v-model.trim="form.checkoutProxyRegion" placeholder="例如 JP" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-xs text-gray-400">后段代理地区</span>
                  <input v-model.trim="form.providerProxyRegion" placeholder="例如 NL" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
                </label>
              </template>
            </div>
            <div class="mt-3 rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-400">{{ proxyChainSummary }}</div>
            <div v-if="proxyTestResult" class="mt-2 rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-400">{{ proxyTestResult }}</div>
          </details>

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="generate" :disabled="busy" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50">
              {{ busy ? '提取中...' : '提取 iDEAL 链' }}
            </button>
            <button @click="testProxy" :disabled="busy || testingProxy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">
              {{ testingProxy ? '测试中...' : '测试代理' }}
            </button>
            <button @click="saveProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
            <button @click="clearProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">清除保存</button>
          </div>

          <div class="text-sm" :class="statusError ? 'text-rose-300' : 'text-gray-400'">{{ statusText }}</div>
        </div>
      </section>

      <div class="space-y-5">
        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4">
            <div>
              <p class="text-xs font-semibold text-gray-500">实时状态</p>
              <h3 class="mt-1 text-xl font-bold text-white">执行日志</h3>
            </div>
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="badgeClass(runtimeBadge.kind)">{{ runtimeBadge.text }}</span>
          </div>
          <div ref="logRef" class="mt-4 h-72 overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-3">
            <div v-if="!steps.length" class="flex h-full items-center justify-center text-sm text-gray-500">暂无执行日志</div>
            <div v-for="(step, index) in steps" :key="`${step.time}-${index}`" class="grid grid-cols-[72px_52px_minmax(0,1fr)] gap-2 border-b border-gray-900 py-2 text-xs last:border-b-0">
              <span class="font-mono text-gray-500">{{ step.time || '-' }}</span>
              <span class="font-semibold" :class="stepStatusClass(step.status)">{{ stepStatusLabel(step.status) }}</span>
              <span class="min-w-0">
                <span class="font-semibold text-gray-300">{{ step.name || '-' }}</span>
                <span class="ml-2 text-gray-500">{{ cleanText(step.detail) }}</span>
              </span>
            </div>
          </div>
        </section>

        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4">
            <div>
              <p class="text-xs font-semibold text-gray-500">输出结果</p>
              <h3 class="mt-1 text-xl font-bold text-white">iDEAL 链与二维码</h3>
            </div>
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="badgeClass(resultBadge.kind)">{{ resultBadge.text }}</span>
          </div>

          <div v-if="!result" class="flex min-h-72 flex-col items-center justify-center text-center text-gray-500">
            <div class="h-32 w-32 rounded-xl border border-dashed border-gray-700 bg-gray-900/50"></div>
            <strong class="mt-4 text-gray-300">尚未生成结果</strong>
            <span class="mt-1 text-sm">任务完成后将在此显示二维码</span>
          </div>

          <div v-else class="mt-5 space-y-4">
            <div class="flex flex-col items-center gap-4">
              <div class="flex h-40 w-40 items-center justify-center rounded-xl border border-gray-700 bg-white p-2">
                <img v-if="qrUrl" :src="qrUrl" alt="iDEAL 支付链接二维码" class="h-full w-full object-contain" />
                <span v-else class="text-sm text-gray-500">正在生成二维码</span>
              </div>
              <div class="flex flex-wrap justify-center gap-2">
                <a :href="safeLongUrl" target="_blank" rel="noopener" class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-500" :class="!safeLongUrl ? 'pointer-events-none opacity-50' : ''">打开长链</a>
                <button @click="copyLongUrl" :disabled="!safeLongUrl" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">复制长链</button>
                <button @click="downloadQr" :disabled="!qrUrl" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">下载二维码</button>
              </div>
            </div>

            <div class="space-y-3 rounded-xl border border-gray-800 bg-gray-950 p-4 text-sm">
              <div class="text-emerald-300">第 {{ result.cs_count || 1 }} 个 Checkout Session 提取成功</div>
              <ResultRow label="长链" :value="safeLongUrl" />
              <ResultRow label="CS ID / 地区 / 币种" :value="summaryText" />
              <ResultRow label="提取状态" :value="result.fallback ? `已回退 hosted：${result.provider_error || 'provider redirect 提取失败'}` : 'iDEAL 链提取成功'" />
              <details class="pt-1">
                <summary class="cursor-pointer text-gray-400">原始链接信息</summary>
                <div class="mt-3 space-y-3">
                  <ResultRow label="Provider Redirect URL" :value="result.provider_redirect_url || ''" />
                  <ResultRow label="Stripe Redirect URL" :value="result.stripe_redirect_url || ''" />
                  <ResultRow label="原始 Stripe URL" :value="result.stripe_hosted_url || ''" />
                </div>
              </details>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const STORAGE_KEY = 'autotoken_ideal_form_v1'
const SAVED_PROXY_KEY = 'autotoken_ideal_saved_proxy'

const ResultRow = defineComponent({
  props: { label: String, value: String },
  setup(props) {
    return () => h('div', { class: 'grid gap-1 md:grid-cols-[150px_minmax(0,1fr)]' }, [
      h('span', { class: 'text-gray-500' }, props.label || ''),
      h('code', { class: 'break-all rounded bg-gray-900 px-2 py-1 text-xs text-gray-300' }, props.value || '-'),
    ])
  },
})

const workflowSteps = [
  { id: 1, title: '授权信息', caption: 'Token 与链路参数' },
  { id: 2, title: '提取链接', caption: '实时执行与日志' },
  { id: 3, title: '生成二维码', caption: '查看、复制和下载' },
]

const form = ref({
  accessToken: '',
  proxy: '',
  checkoutUiMode: 'hosted',
  paymentLocale: 'auto',
  stripePublishableKey: '',
  deviceId: '',
  clientFingerprint: 'chrome',
  userAgent: '',
  diagnosticEnabled: false,
  proxyChainPreset: 'JP_NL',
  checkoutProxyRegion: '',
  providerProxyRegion: '',
})
const busy = ref(false)
const testingProxy = ref(false)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const steps = ref([])
const result = ref(null)
const qrUrl = ref('')
const currentJobId = ref('')
const pollTimer = ref(null)
const logRef = ref(null)
const proxyTestResult = ref('')
const workflowStage = ref(1)
const runtimeBadge = ref({ text: '等待任务', kind: 'neutral' })
const resultBadge = ref({ text: '等待提取', kind: 'neutral' })

const DEFAULT_PROXY_CHAIN_BY_TYPE = {
  ideal: { checkout: 'JP', provider: 'NL' },
}

const PROXY_CHAIN_PRESETS = {
  JP_NL: { checkout: 'JP', provider: 'NL', label: '日本 JP → 荷兰 NL' },
  NL_NL: { checkout: 'NL', provider: 'NL', label: '荷兰 NL → 荷兰 NL' },
  US_US: { checkout: 'US', provider: 'US', label: '美国 US → 美国 US' },
  JP_US: { checkout: 'JP', provider: 'US', label: '日本 JP → 美国 US' },
  JP_US_US: { checkout: 'JP', provider: 'US', approve: 'US', label: 'JP → US → approve US' },
  JP_US_JP: { checkout: 'JP', provider: 'US', approve: 'JP', label: 'JP → US → approve JP' },
  JP_JP: { checkout: 'JP', provider: 'same', label: '日本 JP → 日本 JP' },
  US_JP: { checkout: 'US', provider: 'JP', label: '美国 US → 日本 JP' },
}

const PROXY_CHAIN_STRATEGIES = new Set(['dual_ideal', 'parallel4', 'matrix8', 'sequential8'])
const SOURCE_DEFAULT_CHAIN_PRESETS = new Set(['default', 'manual', ...PROXY_CHAIN_STRATEGIES])
const SAME_PROVIDER_VALUES = new Set(['same', 'none', 'off', 'no', 'false', '0', '不切换', '不使用'])

const tokenMeta = computed(() => {
  const token = readAccessTokenInput()
  if (!token) return ''
  return token.includes('.') ? '已识别 JWT access token' : '已输入授权内容'
})
const safeLongUrl = computed(() => safeHttpUrl(result.value?.long_url || ''))
const summaryText = computed(() => {
  if (!result.value) return ''
  const amount = result.value.amount_display || (result.value.amount ? `amount=${result.value.amount}` : '')
  return `${result.value.cs_id || ''} / ${result.value.billing_country || ''} / ${result.value.currency || ''} / ${result.value.link_type || 'ideal'}${amount ? ` / ${amount}` : ''}`
})

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function safeHttpUrl(value) {
  const text = String(value || '').trim()
  return /^https?:\/\//i.test(text) ? text : ''
}

function normalizeProxyRegionInput(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const lower = raw.toLowerCase()
  if (SAME_PROVIDER_VALUES.has(lower) || SAME_PROVIDER_VALUES.has(raw)) return 'same'
  return raw.toUpperCase()
}

function findToken(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    for (const item of value) {
      const token = findToken(item)
      if (token) return token
    }
  }
  if (typeof value === 'object') {
    for (const key of ['accessToken', 'access_token', 'token']) {
      if (typeof value[key] === 'string' && value[key].trim()) return value[key].trim()
    }
    for (const item of Object.values(value)) {
      const token = findToken(item)
      if (token) return token
    }
  }
  return ''
}

function readAccessTokenInput() {
  const raw = String(form.value.accessToken || '').trim()
  if (!raw) return ''
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      return findToken(JSON.parse(raw)) || raw
    } catch {
      return raw
    }
  }
  return raw
}

function setStatus(text, isError = false) {
  statusText.value = text
  statusError.value = isError
}

function badgeClass(kind) {
  return {
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    error: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  }[kind] || 'border-gray-700 bg-gray-900 text-gray-400'
}

function stepStatusLabel(status) {
  return { ok: '成功', fail: '失败', warn: '警告', info: '执行' }[String(status || '').toLowerCase()] || '执行'
}

function stepStatusClass(status) {
  return {
    ok: 'text-emerald-300',
    fail: 'text-rose-300',
    warn: 'text-amber-300',
    info: 'text-blue-300',
  }[String(status || '').toLowerCase()] || 'text-blue-300'
}

function proxyPayload() {
  const preset = form.value.proxyChainPreset
  const usesDefault = SOURCE_DEFAULT_CHAIN_PRESETS.has(preset)
  const chain = usesDefault
    ? DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
    : PROXY_CHAIN_PRESETS[preset] || DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
  return {
    link_type: 'ideal',
    proxy: form.value.proxy,
    proxy_chain_strategy: PROXY_CHAIN_STRATEGIES.has(preset) ? preset : '',
    diagnostic_enabled: form.value.diagnosticEnabled,
    approve_proxy_region: preset === 'manual' ? '' : chain.approve || '',
    checkout_proxy_region: preset === 'manual' ? normalizeProxyRegionInput(form.value.checkoutProxyRegion) : chain.checkout,
    provider_proxy_region: preset === 'manual' ? normalizeProxyRegionInput(form.value.providerProxyRegion) : chain.provider,
  }
}

function formatProbeResult(title, result) {
  if (!result) return ''
  const ok = result.ok && result.match
  const skipped = result.skipped ? '，沿用前段' : ''
  const ip = result.ip ? `，IP ${result.ip}` : ''
  const detail = result.error ? `，错误：${result.error}` : ''
  return `${ok ? '通过' : '不匹配'} ${title}${skipped}：期望 ${result.expected_region || '-'}，实际 ${result.actual_region || '-'}${ip}${detail}`
}

function proxyChainHint() {
  const preset = form.value.proxyChainPreset
  const usesDefault = SOURCE_DEFAULT_CHAIN_PRESETS.has(preset)
  const chain = usesDefault
    ? DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
    : PROXY_CHAIN_PRESETS[preset] || DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
  if (preset === 'dual_ideal') return '双链路 iDEAL：同时测试 JP→NL 和 NL→NL，任一成功即停止'
  if (preset === 'parallel4') return '并发代理链路：执行 US→US、JP→US、JP→JP、US→JP 等策略'
  if (preset === 'matrix8') return 'Matrix 8 链路：按源码矩阵组合执行'
  if (preset === 'sequential8') return 'Sequential 8 链路：按源码顺序组合执行'
  if (preset === 'manual') return `手动代理链路：前段 ${normalizeProxyRegionInput(form.value.checkoutProxyRegion) || '-'} → 后段 ${normalizeProxyRegionInput(form.value.providerProxyRegion) || '-'}`
  const label = preset === 'default' ? '源码默认链路' : `预设链路 ${PROXY_CHAIN_PRESETS[preset]?.label || preset}`
  return `${label}：前段 ${chain.checkout || '-'} → 后段 ${chain.provider || '-'}${chain.approve ? ` → approve ${chain.approve}` : ''}`
}

function applyDefaultProxyChain() {
  const preset = form.value.proxyChainPreset
  const usesDefault = SOURCE_DEFAULT_CHAIN_PRESETS.has(preset)
  const chain = usesDefault
    ? DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
    : PROXY_CHAIN_PRESETS[preset] || DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
  form.value.checkoutProxyRegion = chain.checkout
  form.value.providerProxyRegion = chain.provider
}

const proxyChainSummary = computed(() => proxyChainHint())

function requestPayload() {
  return {
    accessToken: readAccessTokenInput(),
    ...proxyPayload(),
    billing_country: 'NL',
    checkout_ui_mode: form.value.checkoutUiMode,
    payment_locale: form.value.paymentLocale,
    stripe_publishable_key: form.value.stripePublishableKey,
    device_id: form.value.deviceId,
    client_fingerprint: form.value.clientFingerprint,
    user_agent: form.value.userAgent,
  }
}

async function renderQr(value) {
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = ''
  const blob = await api.getIdealQrBlob(value)
  qrUrl.value = URL.createObjectURL(blob)
}

async function pollJob(jobId) {
  currentJobId.value = jobId
  for (;;) {
    const data = await api.getIdealLongLinkJob(jobId)
    steps.value = Array.isArray(data.steps) ? data.steps : []
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (data.status === 'done') {
      result.value = data.result || {}
      workflowStage.value = 3
      runtimeBadge.value = { text: '执行完成', kind: 'success' }
      resultBadge.value = { text: '生成二维码', kind: 'running' }
      const url = safeHttpUrl(result.value.long_url || '')
      if (url) {
        await renderQr(url)
        resultBadge.value = { text: '二维码就绪', kind: 'success' }
      } else {
        resultBadge.value = { text: '无有效长链', kind: 'error' }
      }
      setStatus('iDEAL 链与二维码已生成。')
      return
    }
    if (data.status === 'error') {
      if (data.result) result.value = data.result
      runtimeBadge.value = { text: '执行失败', kind: 'error' }
      resultBadge.value = { text: '未生成', kind: 'error' }
      throw new Error(data.error || '生成失败')
    }
    setStatus(`任务执行中，已记录 ${steps.value.length} 条日志。`)
    await new Promise(resolve => {
      pollTimer.value = window.setTimeout(resolve, 900)
    })
  }
}

async function generate() {
  const accessToken = readAccessTokenInput()
  if (!accessToken) {
    setStatus('Access Token 不能为空。', true)
    return
  }
  busy.value = true
  result.value = null
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = ''
  workflowStage.value = 2
  runtimeBadge.value = { text: '正在执行', kind: 'running' }
  resultBadge.value = { text: '等待结果', kind: 'neutral' }
  steps.value = [{ time: new Date().toLocaleTimeString('zh-CN', { hour12: false }), status: 'info', name: '任务已提交', detail: '后端正在创建支付链路。' }]
  setStatus('任务已提交，正在提取 iDEAL 链。')
  try {
    persistForm()
    const data = await api.startIdealLongLink(requestPayload())
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    await pollJob(data.job_id)
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
    runtimeBadge.value = { text: '执行失败', kind: 'error' }
    resultBadge.value = { text: '未生成', kind: 'error' }
  } finally {
    busy.value = false
  }
}

async function testProxy() {
  testingProxy.value = true
  proxyTestResult.value = '正在测试代理出口'
  setStatus('正在测试代理。')
  try {
    const data = await api.testIdealProxyChain(proxyPayload())
    const lines = [formatProbeResult('前段', data.checkout), formatProbeResult('后段', data.provider)].filter(Boolean)
    proxyTestResult.value = lines.join(' | ')
    setStatus(data.ok ? '代理出口与选择一致。' : '代理出口与选择不一致。', !data.ok)
  } catch (error) {
    const message = cleanText(error.message || error)
    proxyTestResult.value = message
    setStatus('代理测试失败。', true)
  } finally {
    testingProxy.value = false
  }
}

async function copyLongUrl() {
  if (!safeLongUrl.value) return
  await navigator.clipboard?.writeText(safeLongUrl.value)
  setStatus('长链已复制。')
}

function downloadQr() {
  if (!qrUrl.value) return
  const a = document.createElement('a')
  const name = String(result.value?.cs_id || Date.now()).replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80)
  a.href = qrUrl.value
  a.download = `ideal-${name}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setStatus('二维码已下载。')
}

function saveProxy() {
  localStorage.setItem(SAVED_PROXY_KEY, form.value.proxy || '')
  persistForm()
  setStatus('代理配置已保存。')
}

function clearProxy() {
  form.value.proxy = ''
  localStorage.removeItem(SAVED_PROXY_KEY)
  persistForm()
  setStatus('已清除保存代理。')
}

function persistForm() {
  const {
    accessToken,
    proxyChainPreset,
    checkoutProxyRegion,
    providerProxyRegion,
    ...safeForm
  } = form.value
  localStorage.setItem(STORAGE_KEY, JSON.stringify(safeForm))
}

function loadForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    const {
      proxyChainPreset,
      checkoutProxyRegion,
      providerProxyRegion,
      ...savedWithoutChain
    } = saved
    form.value = { ...form.value, ...savedWithoutChain, accessToken: '' }
  } catch {}
  const savedProxy = localStorage.getItem(SAVED_PROXY_KEY)
  if (savedProxy) form.value.proxy = savedProxy
  form.value.proxyChainPreset = 'JP_NL'
  applyDefaultProxyChain()
}

watch(() => form.value.proxyChainPreset, applyDefaultProxyChain)

onMounted(loadForm)

onBeforeUnmount(() => {
  if (pollTimer.value) window.clearTimeout(pollTimer.value)
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
})
</script>
