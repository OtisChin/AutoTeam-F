<template>
  <div class="space-y-6 xl:h-[calc(100vh-3rem)] xl:min-h-0">
    <div class="grid shrink-0 grid-cols-1 gap-4 xl:grid-cols-[380px_minmax(0,1fr)] xl:items-stretch">
      <div class="flex flex-col justify-center">
        <h2 class="text-xl font-bold text-white">PayPal ICE</h2>
        <p class="mt-1 text-sm text-gray-400">通过 ICE API 检测试用资格并激活 ChatGPT Plus。</p>
      </div>
      <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div v-for="card in boardCards" :key="card.label" class="rounded-xl border border-gray-800 bg-gray-900/80 px-4 py-3">
          <div class="text-xs font-medium text-gray-400">{{ card.label }}</div>
          <div class="mt-2 text-xl font-semibold" :class="card.color">{{ card.value }}</div>
          <div class="mt-1 text-xs text-gray-500">{{ card.meta }}</div>
        </div>
      </div>
    </div>

    <div v-if="message" class="rounded-lg border px-4 py-3 text-sm" :class="messageOk ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/20 bg-rose-500/10 text-rose-300'">
      {{ message }}
    </div>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4 xl:h-[calc(100vh-150px)] xl:min-h-0 xl:flex xl:flex-col xl:overflow-hidden">
      <div class="grid grid-cols-1 gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[460px_minmax(0,1fr)] xl:overflow-hidden">
        <div class="space-y-4 xl:min-h-0 xl:overflow-y-auto xl:pr-2 xl:pb-2">
          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-white">ICE API 配置</h3>
                <p class="mt-1 text-xs text-gray-500">{{ configStatusText }}</p>
              </div>
              <button @click="loadIceAccount" :disabled="busy || !config.configured" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50">
                刷新额度
              </button>
            </div>
            <div class="space-y-3">
              <div>
                <label class="mb-1 block text-xs text-gray-400">接口地址</label>
                <input v-model.trim="configDraft.base_url" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">API Key</label>
                <input v-model="configDraft.api_key" type="password" :placeholder="config.api_key_masked || '输入 ICE API Key'" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <button @click="saveConfig" :disabled="busy || !configDraft.base_url" class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50">
                {{ configSaving ? '保存中...' : '保存 ICE 配置' }}
              </button>
            </div>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-white">激活账号</h3>
                <p class="mt-1 text-xs text-gray-500">{{ inputSource === 'token' ? '直接粘贴 Access Token 提交 ICE 激活。' : '选择一个账号或批量提交，Token 从本地 auth 文件读取。' }}</p>
              </div>
              <div class="flex flex-wrap justify-end gap-2">
                <div class="grid grid-cols-2 gap-1 rounded-lg border border-gray-700 bg-gray-900 p-1 text-xs">
                  <button @click="inputSource = 'account'" class="rounded-md px-3 py-1.5 transition" :class="inputSource === 'account' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'">号池</button>
                  <button @click="inputSource = 'token'" class="rounded-md px-3 py-1.5 transition" :class="inputSource === 'token' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'">Token</button>
                </div>
                <div v-if="inputSource === 'account'" class="grid grid-cols-2 gap-1 rounded-lg border border-gray-700 bg-gray-900 p-1 text-xs">
                  <button @click="mode = 'single'" class="rounded-md px-3 py-1.5 transition" :class="mode === 'single' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'">单个</button>
                  <button @click="mode = 'batch'" class="rounded-md px-3 py-1.5 transition" :class="mode === 'batch' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'">批量</button>
                </div>
              </div>
            </div>

            <template v-if="inputSource === 'account'">
              <template v-if="mode === 'single'">
                <input v-model.trim="accountKeyword" type="text" placeholder="搜索邮箱" class="mb-2 w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                <select v-model="singleEmail" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500">
                  <option value="">请选择账号</option>
                  <option v-for="account in filteredAccounts" :key="account.email" :value="account.email">{{ account.email }} · {{ account.account_type || 'free' }}</option>
                </select>
              </template>

              <div v-else class="rounded-lg border border-gray-700 bg-gray-900/70 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <div class="text-xs text-gray-500">当前选择</div>
                    <div class="mt-1 text-sm text-gray-200">{{ batchEmails.length ? `${batchEmails.length} 个账号` : '未选择' }}</div>
                  </div>
                  <button @click="pickerOpen = true" class="rounded-lg border border-blue-500/30 bg-blue-600/20 px-4 py-2 text-sm text-blue-300 transition hover:bg-blue-600/30">选择账号</button>
                </div>
                <div v-if="batchEmails.length" class="mt-2 flex flex-wrap gap-2">
                  <span v-for="email in batchPreview" :key="email" class="max-w-full truncate rounded-md border border-gray-700 bg-gray-950 px-2 py-1 font-mono text-xs text-gray-300">{{ email }}</span>
                  <span v-if="batchEmails.length > batchPreview.length" class="rounded-md border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-500">+{{ batchEmails.length - batchPreview.length }}</span>
                </div>
              </div>
            </template>

            <div v-else class="space-y-2">
              <textarea
                v-model="accessTokenText"
                rows="7"
                wrap="off"
                spellcheck="false"
                class="w-full overflow-x-auto rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-white outline-none focus:border-blue-500"
                placeholder="一行一个 Access Token，或：备注----access_token"
              ></textarea>
              <div class="flex items-center justify-between gap-3 text-xs text-gray-500">
                <span>已解析 {{ directTokenEntries.length }} 个 token</span>
                <button @click="accessTokenText = ''" :disabled="!accessTokenText.trim()" class="rounded-md border border-gray-700 bg-gray-800 px-2 py-1 text-gray-300 transition hover:bg-gray-700 disabled:opacity-50">清空</button>
              </div>
            </div>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <h3 class="text-sm font-semibold text-white">任务选项</h3>
            <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label class="mb-1 block text-xs text-gray-400">US 代理</label>
                <input v-model.trim="options.proxy" type="text" placeholder="留空使用内置代理" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">JP 代理</label>
                <input v-model.trim="options.proxy_jp" type="text" placeholder="留空使用内置代理" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">接码手机号</label>
                <input v-model.trim="options.phone" type="text" placeholder="必须与接码 API 同时填写" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">接码 API</label>
                <input v-model.trim="options.sms_api" type="text" placeholder="留空使用 ICE 内置接码" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">提链重试</label>
                <input v-model.number="options.pplink_retry" type="number" min="0" max="10" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">OTP 超时（秒）</label>
                <input v-model.number="options.otp_timeout" type="number" min="30" max="900" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
            </div>
          </div>

          <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <button @click="checkTrials" :disabled="busy || !selectedItems.length || !config.configured" class="rounded-lg border border-emerald-500/30 bg-emerald-600/15 px-4 py-2.5 text-sm text-emerald-200 transition hover:bg-emerald-600/25 disabled:opacity-50">
              {{ trialBusy ? '检测中...' : '检测 Plus 试用资格' }}
            </button>
            <button @click="activatePlus" :disabled="busy || !selectedItems.length || !config.configured" class="rounded-lg bg-blue-600 px-4 py-2.5 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50">
              {{ activationBusy ? '提交中...' : `激活 Plus (${selectedItems.length})` }}
            </button>
          </div>
        </div>

        <section class="flex min-h-[520px] flex-col rounded-xl border border-gray-800 bg-gray-950/60 p-4 xl:min-h-0">
          <div class="flex shrink-0 flex-col gap-3 border-b border-gray-800 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 class="font-semibold text-white">ICE 激活任务</h3>
              <p class="mt-1 text-xs text-gray-500">{{ resultRows.length ? `共 ${resultRows.length} 条记录，运行中任务每 3 秒刷新。` : '尚未提交检测或激活任务。' }}</p>
            </div>
            <div class="flex gap-2">
              <button @click="refreshActiveJobs" :disabled="busy || !activeJobCount" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 transition hover:bg-gray-700 disabled:opacity-50">刷新任务</button>
              <button @click="clearResults" :disabled="busy || !resultRows.length" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-400 transition hover:bg-gray-700 disabled:opacity-50">清空</button>
            </div>
          </div>

          <div class="mt-4 min-h-0 flex-1 overflow-auto">
            <table class="w-full min-w-[920px] text-left text-sm">
              <thead class="sticky top-0 bg-gray-950 text-xs text-gray-500">
                <tr>
                  <th class="px-3 py-2 font-medium">账号</th>
                  <th class="px-3 py-2 font-medium">试用资格</th>
                  <th class="px-3 py-2 font-medium">任务状态</th>
                  <th class="px-3 py-2 font-medium">计费</th>
                  <th class="px-3 py-2 font-medium">结果</th>
                  <th class="px-3 py-2 font-medium">任务 ID</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-800">
                <tr v-for="row in resultRows" :key="row.email" class="text-gray-300">
                  <td class="px-3 py-3 font-mono text-xs text-gray-200">{{ row.email }}</td>
                  <td class="px-3 py-3"><span class="rounded-md border px-2 py-1 text-xs" :class="trialClass(row.trialStatus)">{{ trialLabel(row.trialStatus) }}</span></td>
                  <td class="px-3 py-3"><span class="rounded-md border px-2 py-1 text-xs" :class="jobClass(row.status)">{{ jobLabel(row.status) }}</span></td>
                  <td class="px-3 py-3 text-xs text-gray-400">{{ row.billingStatus || '-' }}</td>
                  <td class="max-w-[280px] px-3 py-3 text-xs" :class="row.error ? 'text-rose-300' : 'text-gray-400'">{{ row.error || row.resultCode || row.resourceMode || '-' }}</td>
                  <td class="px-3 py-3 font-mono text-xs text-gray-500">{{ row.jobId || '-' }}</td>
                </tr>
                <tr v-if="!resultRows.length">
                  <td colspan="6" class="px-3 py-16 text-center text-sm text-gray-500">没有 ICE 激活记录</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>

    <div v-if="pickerOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="pickerOpen = false">
      <div class="flex max-h-[82vh] w-full max-w-3xl flex-col rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
        <div class="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-4">
          <div>
            <h4 class="text-lg font-semibold text-white">批量选择账号</h4>
            <p class="mt-1 text-xs text-gray-500">已选择 {{ batchEmails.length }} 个账号</p>
          </div>
          <button @click="pickerOpen = false" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700">关闭</button>
        </div>
        <div class="space-y-3 border-b border-gray-800 px-5 py-4">
          <input v-model.trim="pickerKeyword" type="text" placeholder="搜索邮箱" class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
          <div class="flex flex-wrap justify-end gap-2">
            <button @click="selectFiltered" class="rounded-lg border border-blue-500/30 bg-blue-600/15 px-3 py-1.5 text-xs text-blue-300 hover:bg-blue-600/25">选择当前筛选</button>
            <button @click="batchEmails = []" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700">清空选择</button>
          </div>
        </div>
        <div class="min-h-0 flex-1 overflow-y-auto px-5 py-3">
          <label v-for="account in pickerAccounts" :key="account.email" class="flex cursor-pointer items-center gap-3 border-b border-gray-800 px-2 py-3 text-sm text-gray-300 hover:bg-gray-800/60">
            <input v-model="batchEmails" type="checkbox" :value="account.email" class="accent-blue-500" />
            <span class="min-w-0 flex-1 truncate font-mono text-xs">{{ account.email }}</span>
            <span class="text-xs text-gray-500">{{ account.account_type || 'free' }}</span>
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api.js'

const config = ref({ configured: false, api_key_masked: '', base_url: 'https://plus.iceaix.com' })
const configDraft = ref({ api_key: '', base_url: 'https://plus.iceaix.com' })
const iceAccount = ref(null)
const accounts = ref([])
const inputSource = ref('account')
const mode = ref('single')
const singleEmail = ref('')
const batchEmails = ref([])
const accessTokenText = ref('')
const accountKeyword = ref('')
const pickerKeyword = ref('')
const pickerOpen = ref(false)
const configSaving = ref(false)
const trialBusy = ref(false)
const activationBusy = ref(false)
const refreshingJobs = ref(false)
const message = ref('')
const messageOk = ref(true)
const resultRows = ref([])
const options = ref({ proxy: '', proxy_jp: '', phone: '', sms_api: '', pplink_retry: 3, otp_timeout: 180 })
let pollTimer = null

const busy = computed(() => configSaving.value || trialBusy.value || activationBusy.value || refreshingJobs.value)
const normalizedAccounts = computed(() => (accounts.value || []).filter(item => String(item?.email || '').trim()))
const filteredAccounts = computed(() => filterAccounts(normalizedAccounts.value, accountKeyword.value))
const pickerAccounts = computed(() => filterAccounts(normalizedAccounts.value, pickerKeyword.value))
const selectedEmails = computed(() => mode.value === 'single' ? (singleEmail.value ? [singleEmail.value] : []) : [...new Set(batchEmails.value)])
const directTokenEntries = computed(() => parseAccessTokenEntries(accessTokenText.value))
const selectedItems = computed(() => {
  if (inputSource.value === 'token') return directTokenEntries.value
  return selectedEmails.value.map(email => ({ key: email, label: email, clientRef: email, email }))
})
const batchPreview = computed(() => batchEmails.value.slice(0, 4))
const activeJobCount = computed(() => resultRows.value.filter(row => row.jobId && !['success', 'failed'].includes(row.status)).length)
const successCount = computed(() => resultRows.value.filter(row => row.status === 'success').length)
const configStatusText = computed(() => config.value.configured ? `已配置 · ${config.value.api_key_masked || 'API Key 已保存'}` : '尚未配置 API Key')
const boardCards = computed(() => [
  { label: 'ICE 剩余额度', value: iceAccount.value?.quota_remaining ?? '-', meta: iceAccount.value ? `总额 ${iceAccount.value.quota_total ?? '-'} / 已用 ${iceAccount.value.quota_used ?? '-'}` : '保存配置后读取', color: 'text-blue-400' },
  { label: '已选择账号', value: selectedItems.value.length, meta: inputSource.value === 'token' ? 'Access Token' : (mode.value === 'single' ? '单个模式' : '批量模式'), color: 'text-gray-100' },
  { label: '运行中任务', value: activeJobCount.value, meta: `并发上限 ${iceAccount.value?.concurrency_limit ?? '-'}`, color: 'text-amber-300' },
  { label: '激活成功', value: successCount.value, meta: `记录 ${resultRows.value.length}`, color: 'text-emerald-400' },
])

function filterAccounts(rows, keyword) {
  const query = String(keyword || '').trim().toLowerCase()
  return query ? rows.filter(item => String(item.email || '').toLowerCase().includes(query)) : rows
}

function setMessage(text, ok = true) {
  message.value = text
  messageOk.value = ok
}

function ensureRow(email) {
  let row = resultRows.value.find(item => item.email === email)
  if (!row) {
    row = { email, trialStatus: '', status: '', billingStatus: '', resultCode: '', resourceMode: '', error: '', jobId: '' }
    resultRows.value.unshift(row)
  }
  return row
}

function shortTokenLabel(token, index) {
  const value = String(token || '').trim()
  if (!value) return `Token ${index + 1}`
  if (value.length <= 18) return `Token ${index + 1} · ${value}`
  return `Token ${index + 1} · ${value.slice(0, 8)}...${value.slice(-6)}`
}

function parseAccessTokenEntries(text) {
  const seen = new Set()
  return String(text || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      let label = ''
      let token = line
      if (line.includes('----')) {
        const parts = line.split('----')
        label = parts.shift().trim()
        token = parts.join('----').trim()
      } else if (line.includes('|')) {
        const parts = line.split('|')
        label = parts.shift().trim()
        token = parts.join('|').trim()
      }
      token = token.replace(/^Bearer\s+/i, '').trim()
      const key = token.toLowerCase()
      if (!token || seen.has(key)) return null
      seen.add(key)
      return {
        key: `token:${key}`,
        label: label || shortTokenLabel(token, index),
        clientRef: label || `manual-token-${index + 1}`,
        token,
      }
    })
    .filter(Boolean)
}

function extractAccessToken(payload) {
  return String(
    payload?.codex_auth?.tokens?.access_token
    || payload?.codex_auth?.access_token
    || payload?.tokens?.access_token
    || payload?.access_token
    || ''
  ).trim()
}

async function tokenForEmail(email) {
  const payload = await api.getCodexAuth(email)
  const token = extractAccessToken(payload)
  if (!token) throw new Error('本地 auth 文件没有 access_token')
  return token
}

async function tokenForItem(item) {
  if (item.token) return item.token
  return tokenForEmail(item.email)
}

async function runPool(items, worker) {
  const pending = [...items]
  const concurrency = Math.max(1, Math.min(Number(iceAccount.value?.concurrency_limit || 2), 5))
  await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, async () => {
    while (pending.length) {
      const item = pending.shift()
      await worker(item)
    }
  }))
}

async function loadConfig() {
  try {
    config.value = await api.getPayPalIceConfig()
    configDraft.value.base_url = config.value.base_url || 'https://plus.iceaix.com'
  } catch (error) {
    setMessage(`读取 ICE 配置失败: ${error.message}`, false)
  }
}

async function saveConfig() {
  configSaving.value = true
  try {
    config.value = await api.savePayPalIceConfig(configDraft.value)
    configDraft.value.api_key = ''
    setMessage(config.value.message || 'PayPal ICE 配置已保存')
    await loadIceAccount()
  } catch (error) {
    setMessage(`保存 ICE 配置失败: ${error.message}`, false)
  } finally {
    configSaving.value = false
  }
}

async function loadIceAccount() {
  try {
    iceAccount.value = await api.getPayPalIceAccount()
  } catch (error) {
    iceAccount.value = null
    setMessage(`读取 ICE 额度失败: ${error.message}`, false)
  }
}

async function loadAccounts() {
  try {
    const result = await api.getAccounts({ includeSessionStubs: true })
    accounts.value = Array.isArray(result) ? result : (result?.accounts || [])
  } catch (error) {
    setMessage(`读取号池失败: ${error.message}`, false)
  }
}

function validateSelection() {
  if (!selectedItems.value.length) {
    throw new Error(inputSource.value === 'token' ? '请先输入 Access Token' : '请先选择账号')
  }
  if ((options.value.phone && !options.value.sms_api) || (!options.value.phone && options.value.sms_api)) {
    throw new Error('自定义接码必须同时填写手机号和接码 API')
  }
}

async function checkTrials() {
  trialBusy.value = true
  try {
    validateSelection()
    await runPool(selectedItems.value, async (item) => {
      const row = ensureRow(item.label)
      row.trialStatus = 'checking'
      row.error = ''
      try {
        const token = await tokenForItem(item)
        const result = await api.checkPayPalIceTrial({ token, proxy_jp: options.value.proxy_jp || '' })
        row.trialStatus = result.eligible ? 'eligible' : (result.blocked ? 'blocked' : 'ineligible')
        row.resourceMode = result.resource_mode || ''
        row.error = result.status && !result.eligible ? result.status : ''
      } catch (error) {
        row.trialStatus = 'error'
        row.error = error.message
      }
    })
    setMessage('Plus 试用资格检测完成')
  } catch (error) {
    setMessage(error.message, false)
  } finally {
    trialBusy.value = false
  }
}

async function activatePlus() {
  activationBusy.value = true
  try {
    validateSelection()
    await runPool(selectedItems.value, async (item) => {
      const row = ensureRow(item.label)
      row.status = 'submitting'
      row.error = ''
      try {
        const token = await tokenForItem(item)
        const result = await api.createPayPalIceJob({
          input: token,
          client_ref: item.clientRef,
          proxy: options.value.proxy || '',
          proxy_jp: options.value.proxy_jp || '',
          phone: options.value.phone || '',
          sms_api: options.value.sms_api || '',
          pplink_retry: Number(options.value.pplink_retry || 3),
          otp_timeout: Number(options.value.otp_timeout || 180),
          idempotency_key: `autotoken-${item.clientRef}-${Date.now()}`,
        })
        row.jobId = result.job_id || ''
        row.status = result.status || 'queued'
        row.resourceMode = result.resource_mode || ''
      } catch (error) {
        row.status = 'failed'
        row.error = error.message
      }
    })
    setMessage('PayPal ICE 激活任务已提交')
    await refreshActiveJobs()
  } catch (error) {
    setMessage(error.message, false)
  } finally {
    activationBusy.value = false
  }
}

async function refreshActiveJobs() {
  if (refreshingJobs.value) return
  const active = resultRows.value.filter(row => row.jobId && !['success', 'failed'].includes(row.status))
  if (!active.length) return
  refreshingJobs.value = true
  try {
    await runPool(active, async (row) => {
      try {
        const result = await api.getPayPalIceJob(row.jobId)
        row.status = result.status || row.status
        row.billingStatus = result.billing_status || ''
        row.resultCode = result.result_code || ''
        row.resourceMode = result.resource_mode || row.resourceMode
        row.error = result.error_message || ''
      } catch (error) {
        row.error = error.message
      }
    })
  } finally {
    refreshingJobs.value = false
  }
}

function clearResults() {
  resultRows.value = []
}

function selectFiltered() {
  batchEmails.value = [...new Set([...batchEmails.value, ...pickerAccounts.value.map(item => item.email)])]
}

function trialLabel(status) {
  return { checking: '检测中', eligible: '可试用', ineligible: '不可试用', blocked: '已阻断', error: '检测失败' }[status] || '未检测'
}

function trialClass(status) {
  return {
    checking: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    eligible: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    blocked: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    error: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  }[status] || 'border-gray-700 bg-gray-900 text-gray-400'
}

function jobLabel(status) {
  return { submitting: '提交中', queued: '排队中', running: '运行中', otp_pending: '等待验证码', success: '成功', failed: '失败' }[status] || '未提交'
}

function jobClass(status) {
  return {
    submitting: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    queued: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    otp_pending: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  }[status] || 'border-gray-700 bg-gray-900 text-gray-400'
}

onMounted(async () => {
  await Promise.all([loadConfig(), loadAccounts()])
  if (config.value.configured) await loadIceAccount()
  pollTimer = setInterval(refreshActiveJobs, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
