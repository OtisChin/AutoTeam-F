<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">独立 Pix 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">巴西 PIX 提链</h2>
          <p class="mt-2 text-sm text-gray-400">BR 创建 checkout → 套 0 元 promo → Stripe PIX confirm → approve → 提取二维码。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ busy ? '任务运行中' : '本地服务在线' }}
        </span>
      </div>
    </section>

    <div class="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">账号与 BR 代理</h3>
        </div>

        <div class="mt-5 space-y-5">
          <label class="block">
            <span class="mb-1.5 block text-sm font-semibold text-gray-300">账号池账号</span>
            <select v-model="form.accountEmail" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
              <option value="">不选择账号池，使用下方 Token</option>
              <option v-for="account in accounts" :key="account.email" :value="account.email">
                {{ account.email }}{{ account.ttl_seconds ? ` · ${Math.round(account.ttl_seconds / 3600)}h` : '' }}
              </option>
            </select>
          </label>

          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">Access Token 或 session JSON</span>
            <textarea
              v-model.trim="form.accessToken"
              rows="5"
              autocomplete="off"
              spellcheck="false"
              placeholder="选择账号池账号时可留空；也可粘贴 ChatGPT accessToken/session JSON"
              class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              :disabled="busy"
            ></textarea>
            <span class="mt-1 block text-xs text-gray-500">Token 只随本次任务发送给后端，不写入浏览器保存。</span>
          </label>

          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">BR 代理列表</span>
            <textarea
              v-model.trim="form.proxies"
              rows="8"
              spellcheck="false"
              placeholder="每行一个代理；支持 host:port:user:pass 或 socks5h://user:pass@host:port"
              class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              :disabled="busy"
            ></textarea>
            <span class="mt-1 block text-xs text-gray-500">ArxLabs 的 host:port:user:pass 会自动按 socks5h 使用。</span>
          </label>

          <details class="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
            <summary class="cursor-pointer text-sm font-semibold text-gray-200">高级设置</summary>
            <div class="mt-4 grid gap-4 md:grid-cols-2">
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">本地代理链</span>
                <input v-model.trim="form.localProxy" placeholder="留空；仅需链式 HTTP 代理时填写" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Kookeey 入口</span>
                <input v-model.trim="form.kookeeyEndpoint" placeholder="gate.kookeey.info:1000" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Kookeey 用户名</span>
                <input v-model.trim="form.kookeeyUser" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Kookeey 密码</span>
                <input v-model="form.kookeeyPass" type="password" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
            </div>
          </details>

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="busy" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50">
              {{ busy ? '提取中...' : '开始提取 PIX' }}
            </button>
            <button @click="reloadAccounts" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号池</button>
            <button @click="saveProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
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
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="badgeClass">{{ badgeText }}</span>
          </div>
          <div ref="logRef" class="mt-4 h-72 overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-3 font-mono text-xs text-gray-400">
            <div v-if="!logs.length" class="flex h-full items-center justify-center font-sans text-sm text-gray-500">暂无执行日志</div>
            <div v-for="(line, index) in logs" :key="index" class="border-b border-gray-900 py-1 last:border-b-0">{{ line }}</div>
          </div>
        </section>

        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4">
            <div>
              <p class="text-xs font-semibold text-gray-500">输出结果</p>
              <h3 class="mt-1 text-xl font-bold text-white">PIX 复制码与二维码</h3>
            </div>
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="result ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-gray-700 bg-gray-900 text-gray-400'">{{ result ? '已生成' : '等待提取' }}</span>
          </div>

          <div v-if="!result" class="flex min-h-72 flex-col items-center justify-center text-center text-gray-500">
            <div class="h-32 w-32 rounded-xl border border-dashed border-gray-700 bg-gray-900/50"></div>
            <strong class="mt-4 text-gray-300">尚未生成结果</strong>
            <span class="mt-1 text-sm">任务完成后将在此显示 PIX 链接和二维码</span>
          </div>

          <div v-else class="mt-5 space-y-4">
            <div class="flex flex-col items-center gap-4">
              <div class="flex h-44 w-44 items-center justify-center rounded-xl border border-gray-700 bg-white p-2">
                <img v-if="fields.image_url_png || fields.image_url_svg" :src="fields.image_url_png || fields.image_url_svg" alt="PIX QR" class="h-full w-full object-contain" />
                <span v-else class="text-sm text-gray-500">无二维码图片</span>
              </div>
              <div class="flex flex-wrap justify-center gap-2">
                <a :href="fields.hosted_instructions_url || '#'" target="_blank" rel="noopener" class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-500" :class="!fields.hosted_instructions_url ? 'pointer-events-none opacity-50' : ''">打开 PIX 链接</a>
                <button @click="copy(fields.pix_copy_paste)" :disabled="!fields.pix_copy_paste" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">复制 PIX 码</button>
                <button @click="copy(JSON.stringify(result, null, 2))" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800">复制全部结果</button>
              </div>
            </div>

            <div class="space-y-3 rounded-xl border border-gray-800 bg-gray-950 p-4 text-sm">
              <ResultRow label="账号" :value="result.account_email || '-'" />
              <ResultRow label="金额" :value="String(fields.amount || result.amount || '-')" />
              <ResultRow label="CS ID" :value="fields.cs_id || '-'" />
              <ResultRow label="PIX 链接" :value="fields.hosted_instructions_url || '-'" />
              <ResultRow label="PNG" :value="fields.image_url_png || '-'" />
              <ResultRow label="SVG" :value="fields.image_url_svg || '-'" />
              <ResultRow label="Checkout" :value="fields.chatgpt_checkout_url || '-'" />
              <label class="block">
                <span class="mb-1 block text-gray-500">PIX 复制码</span>
                <textarea readonly rows="4" :value="fields.pix_copy_paste || ''" class="w-full rounded-lg border border-gray-800 bg-gray-900 px-3 py-2 font-mono text-xs text-gray-300"></textarea>
              </label>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, ref } from 'vue'
import { api } from '../api.js'

const PROXY_STORAGE_KEY = 'autotoken_brazil_pix_proxies'

const ResultRow = defineComponent({
  props: { label: String, value: String },
  setup(props) {
    return () => h('div', { class: 'grid gap-1 md:grid-cols-[120px_minmax(0,1fr)]' }, [
      h('span', { class: 'text-gray-500' }, props.label || ''),
      h('code', { class: 'break-all rounded bg-gray-900 px-2 py-1 text-xs text-gray-300' }, props.value || '-'),
    ])
  },
})

const form = ref({
  accountEmail: '',
  accessToken: '',
  proxies: '',
  localProxy: '',
  kookeeyUser: '',
  kookeeyPass: '',
  kookeeyEndpoint: 'gate.kookeey.info:1000',
})
const accounts = ref([])
const busy = ref(false)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const result = ref(null)
const logRef = ref(null)

const fields = computed(() => result.value?.fields || {})
const badgeText = computed(() => busy.value ? '运行中' : (statusError.value ? '失败' : '待命'))
const badgeClass = computed(() => {
  if (busy.value) return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (statusError.value) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
})

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function setStatus(text, isError = false) {
  statusText.value = text
  statusError.value = isError
}

async function reloadAccounts() {
  try {
    const data = await api.getBrazilPixAccounts()
    accounts.value = Array.isArray(data.accounts) ? data.accounts : []
  } catch (error) {
    setStatus(`账号池读取失败：${cleanText(error.message || error)}`, true)
  }
}

async function poll(jobId) {
  for (;;) {
    const data = await api.getBrazilPixJob(jobId)
    logs.value = Array.isArray(data.logs) ? data.logs : []
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (data.status === 'success') {
      result.value = data.result || {}
      setStatus('PIX 链接已生成。')
      return
    }
    if (data.status === 'error') {
      if (data.result) result.value = data.result
      throw new Error(data.error || '生成失败')
    }
    setStatus(`任务执行中，已记录 ${logs.value.length} 条日志。`)
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
}

async function start() {
  if (!form.value.accountEmail && !form.value.accessToken.trim()) {
    setStatus('请选择账号池账号或粘贴 Access Token。', true)
    return
  }
  if (!form.value.proxies.trim() && (!form.value.kookeeyUser || !form.value.kookeeyPass)) {
    setStatus('请填写 BR 代理列表，或在高级设置填写 Kookeey 用户名/密码。', true)
    return
  }
  busy.value = true
  logs.value = []
  result.value = null
  setStatus('任务已提交，正在提取 PIX。')
  try {
    saveProxy()
    const data = await api.startBrazilPix({ ...form.value })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    await poll(data.job_id)
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
  } finally {
    busy.value = false
  }
}

function saveProxy() {
  localStorage.setItem(PROXY_STORAGE_KEY, form.value.proxies || '')
  if (!busy.value) setStatus('代理列表已保存。')
}

async function copy(value) {
  const text = String(value || '')
  if (!text) return
  await navigator.clipboard?.writeText(text)
  setStatus('已复制。')
}

onMounted(() => {
  form.value.proxies = localStorage.getItem(PROXY_STORAGE_KEY) || ''
  reloadAccounts()
})
</script>
