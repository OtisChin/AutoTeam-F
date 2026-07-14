<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">独立 PIX 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">巴西PIX 提链</h2>
          <p class="mt-2 text-sm text-gray-400">在账号池中勾选一个或多个账号执行提链，结果会进入下方链接管理表。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ busy ? progressText : '本地服务在线' }}
        </span>
      </div>
    </section>

    <div class="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">BR 代理</h3>
        </div>

        <div class="mt-5 space-y-5">
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

          <label class="block">
            <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
            <input
              v-model.number="form.concurrency"
              type="number"
              min="1"
              max="10"
              class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none"
              :disabled="busy"
            />
            <span class="mt-1 block text-xs text-gray-500">默认 1，最高 10；并发越高越依赖代理质量。</span>
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
              {{ busy ? '提取中...' : `开始提链 (${selectedEmails.length})` }}
            </button>
            <button v-if="busy" @click="cancelJob" :disabled="canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
              {{ canceling ? '取消中...' : '取消提链' }}
            </button>
            <button @click="reloadAll" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号/链接</button>
            <button @click="saveProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
          </div>

          <div class="text-sm" :class="statusError ? 'text-rose-300' : 'text-gray-400'">{{ statusText }}</div>
        </div>
      </section>

      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p class="text-xs font-semibold text-gray-500">账号管理</p>
            <h3 class="mt-1 text-xl font-bold text-white">账号池选择</h3>
          </div>
          <div class="text-sm text-gray-400">已选 <span class="font-semibold text-emerald-300">{{ selectedEmails.length }}</span> / {{ filteredAccounts.length }}</div>
        </div>

        <div class="mt-4 flex flex-col gap-3 md:flex-row md:items-center">
          <input v-model.trim="accountFilter" placeholder="搜索账号邮箱" class="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" />
          <div class="flex flex-wrap gap-2">
            <button @click="selectAllFiltered" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
            <button @click="clearSelectedAccounts" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
          </div>
        </div>

        <div class="mt-4 max-h-[520px] overflow-y-auto rounded-xl border border-gray-800">
          <table class="w-full text-left text-sm">
            <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th class="w-10 px-3 py-2"></th>
                <th class="px-3 py-2">邮箱</th>
                <th class="px-3 py-2">有效期</th>
                <th class="px-3 py-2">提链状态</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-900">
              <tr v-if="!filteredAccounts.length">
                <td colspan="4" class="px-3 py-10 text-center text-gray-500">暂无账号</td>
              </tr>
              <tr v-for="account in filteredAccounts" :key="account.email" class="hover:bg-gray-900/50">
                <td class="px-3 py-2">
                  <input :checked="selectedAccounts.has(account.email)" type="checkbox" class="accent-emerald-500" :disabled="busy" @change="toggleAccount(account.email)" />
                </td>
                <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ account.email }}</td>
                <td class="px-3 py-2 text-xs text-gray-500">{{ ttlText(account.ttl_seconds) }}</td>
                <td class="px-3 py-2 text-xs">
                  <span class="inline-flex rounded-full border px-2 py-1 font-semibold" :class="accountStatusClass(account)" :title="accountStatusError(account)">
                    {{ accountStatusText(account) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
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
              <p class="text-xs font-semibold text-gray-500">当前结果</p>
              <h3 class="mt-1 text-xl font-bold text-white">最近一次任务</h3>
            </div>
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="currentResult ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-gray-700 bg-gray-900 text-gray-400'">{{ currentResult ? '有结果' : '等待提取' }}</span>
          </div>

          <div v-if="!currentResult" class="flex min-h-48 flex-col items-center justify-center text-center text-gray-500">
            <strong class="text-gray-300">尚未生成结果</strong>
            <span class="mt-1 text-sm">从账号池勾选账号后开始提链</span>
          </div>

          <div v-else-if="currentResult.batch" class="mt-5 space-y-3 text-sm">
            <div class="rounded-xl border border-gray-800 bg-gray-950 p-4 text-gray-300">
              本次完成：成功 <span class="font-semibold text-emerald-300">{{ currentResult.successes?.length || 0 }}</span>，失败 <span class="font-semibold text-rose-300">{{ currentResult.errors?.length || 0 }}</span>，跳过 <span class="font-semibold text-gray-300">{{ currentResult.skipped?.length || 0 }}</span>
            </div>
            <div v-for="item in currentResult.successes || []" :key="item.email" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
              <div class="font-mono text-emerald-200">{{ item.email }}</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="item.link?.hosted_instructions_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!item.link?.hosted_instructions_url ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(item.link?.pix_copy_paste)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制码</button>
                <button @click="copy(item.link?.hosted_instructions_url)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制链</button>
              </div>
            </div>
            <div v-for="item in currentResult.errors || []" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {{ item.email }}：{{ item.error }}
            </div>
            <div v-for="item in currentResult.skipped || []" :key="item.email" class="rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-2 text-xs text-gray-300">
              {{ item.email }}：{{ item.reason || '已跳过' }}
            </div>
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
              </div>
            </div>
            <ResultDetails :result="currentResult" />
          </div>
        </section>
      </div>
    </div>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="text-xs font-semibold text-gray-500">链接管理</p>
          <h3 class="mt-1 text-xl font-bold text-white">已提取 PIX 链接</h3>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button>
          <button @click="exportLinks" :disabled="!links.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button>
          <button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
          <button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空</button>
        </div>
      </div>

      <div class="mt-4 max-h-[520px] overflow-auto rounded-xl border border-gray-800">
        <table class="min-w-[1180px] w-full text-left text-sm">
          <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="w-10 px-3 py-2"></th>
              <th class="px-3 py-2">时间</th>
              <th class="px-3 py-2">账号</th>
              <th class="px-3 py-2">金额</th>
              <th class="px-3 py-2">CS ID</th>
              <th class="px-3 py-2">操作</th>
              <th class="px-3 py-2">PIX 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!links.length">
              <td colspan="7" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ link.created_at }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || '-' }}</td>
              <td class="px-3 py-2 text-xs text-gray-400">{{ link.amount || '-' }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-400">{{ link.cs_id || '-' }}</td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-2">
                  <a :href="link.hosted_instructions_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!link.hosted_instructions_url ? 'pointer-events-none opacity-50' : ''">打开</a>
                  <button @click="copy(link.pix_copy_paste)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200">复制码</button>
                  <button @click="copy(link.hosted_instructions_url)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200">复制链</button>
                </div>
              </td>
              <td class="max-w-[360px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ link.hosted_instructions_url || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
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

const ResultDetails = defineComponent({
  props: { result: Object },
  setup(props) {
    return () => {
      const result = props.result || {}
      const fields = result.fields || {}
      return h('div', { class: 'space-y-3 rounded-xl border border-gray-800 bg-gray-950 p-4 text-sm' }, [
        h(ResultRow, { label: '账号', value: result.account_email || '-' }),
        h(ResultRow, { label: '金额', value: String(fields.amount || result.amount || '-') }),
        h(ResultRow, { label: 'CS ID', value: fields.cs_id || '-' }),
        h(ResultRow, { label: 'PIX 链接', value: fields.hosted_instructions_url || '-' }),
        h(ResultRow, { label: 'PNG', value: fields.image_url_png || '-' }),
        h(ResultRow, { label: 'Checkout', value: fields.chatgpt_checkout_url || '-' }),
        h('label', { class: 'block' }, [
          h('span', { class: 'mb-1 block text-gray-500' }, 'PIX 复制码'),
          h('textarea', { readonly: true, rows: 4, value: fields.pix_copy_paste || '', class: 'w-full rounded-lg border border-gray-800 bg-gray-900 px-3 py-2 font-mono text-xs text-gray-300' }),
        ]),
      ])
    }
  },
})

const form = ref({
  proxies: '',
  concurrency: 1,
  localProxy: '',
  kookeeyUser: '',
  kookeeyPass: '',
  kookeeyEndpoint: 'gate.kookeey.info:1000',
})
const accounts = ref([])
const links = ref([])
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const accountFilter = ref('')
const busy = ref(false)
const canceling = ref(false)
const currentJob = ref(null)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const currentResult = ref(null)
const logRef = ref(null)

const fields = computed(() => currentResult.value?.fields || {})
const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const filteredAccounts = computed(() => {
  const needle = accountFilter.value.toLowerCase()
  if (!needle) return accounts.value
  return accounts.value.filter(account => String(account.email || '').toLowerCase().includes(needle))
})
const progressText = computed(() => {
  const total = currentJob.value?.total || 0
  const completed = currentJob.value?.completed || 0
  const concurrency = currentJob.value?.concurrency || 1
  const running = currentJob.value?.running_count || 0
  const status = currentJob.value?.status || ''
  if (status === 'cancelling') return total ? `取消中 ${completed}/${total} · 活跃 ${running}` : '取消中'
  return total ? `运行中 ${completed}/${total} · 活跃 ${running}${concurrency > 1 ? ` · 并发 ${concurrency}` : ''}` : '任务运行中'
})
const badgeText = computed(() => {
  if (busy.value) return progressText.value
  if (currentJob.value?.status === 'cancelled') return '已取消'
  return statusError.value ? '失败' : '待命'
})
const badgeClass = computed(() => {
  if (busy.value) return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (currentJob.value?.status === 'cancelled') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
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

function ttlText(seconds) {
  const value = Number(seconds || 0)
  if (!value) return '-'
  if (value < 3600) return `${Math.round(value / 60)}m`
  return `${Math.round(value / 3600)}h`
}

function accountJobStatus(account) {
  const email = String(account?.email || '')
  const statuses = currentJob.value?.account_statuses || {}
  return statuses[email] || statuses[email.toLowerCase()] || null
}

function accountStatus(account) {
  return accountJobStatus(account)?.status || account?.pix_status || 'pending'
}

function accountStatusText(account) {
  const status = accountStatus(account)
  if (status === 'running') return '提链中'
  if (status === 'success') return '已提链'
  if (status === 'failed') return '提链失败'
  return '未提链'
}

function accountStatusError(account) {
  return accountJobStatus(account)?.error || account?.pix_error || ''
}

function accountStatusClass(account) {
  const status = accountStatus(account)
  if (status === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
}

function toggleAccount(email) {
  const next = new Set(selectedAccounts.value)
  if (next.has(email)) next.delete(email)
  else next.add(email)
  selectedAccounts.value = next
}

function selectAllFiltered() {
  selectedAccounts.value = new Set(filteredAccounts.value.map(account => account.email))
}

function clearSelectedAccounts() {
  selectedAccounts.value = new Set()
}

function toggleLink(id) {
  const next = new Set(selectedLinkIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedLinkIds.value = next
}

async function reloadAccounts() {
  try {
    const data = await api.getBrazilPixAccounts()
    accounts.value = Array.isArray(data.accounts) ? data.accounts : []
    const available = new Set(accounts.value.map(account => account.email))
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => available.has(email)))
  } catch (error) {
    setStatus(`账号池读取失败：${cleanText(error.message || error)}`, true)
  }
}

async function refreshLinks() {
  try {
    const data = await api.getBrazilPixLinks()
    links.value = Array.isArray(data.links) ? data.links : []
    const available = new Set(links.value.map(link => link.id))
    selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => available.has(id)))
  } catch (error) {
    setStatus(`链接读取失败：${cleanText(error.message || error)}`, true)
  }
}

async function reloadAll() {
  await Promise.all([reloadAccounts(), refreshLinks()])
}

async function poll(jobId) {
  let lastSyncedCompleted = 0
  for (;;) {
    const data = await api.getBrazilPixJob(jobId)
    const completed = Number(data.completed || 0)
    const total = Number(data.total || 0)
    const shouldSyncIncremental = data.result && completed > lastSyncedCompleted && ['running', 'cancelling'].includes(data.status)
    currentJob.value = data
    if (data.result) currentResult.value = data.result
    logs.value = Array.isArray(data.logs) ? data.logs : []
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (shouldSyncIncremental) {
      lastSyncedCompleted = completed
      await refreshLinks()
    }
    if (data.status === 'success') {
      currentResult.value = data.result || {}
      setStatus('提链任务已完成，链接已写入管理表。')
      await Promise.all([refreshLinks(), reloadAccounts()])
      return
    }
    if (data.status === 'cancelled') {
      currentResult.value = data.result || { batch: true, successes: [], errors: [], skipped: data.skipped || [] }
      setStatus('提链任务已取消；已完成的链接已写入管理表。')
      await Promise.all([refreshLinks(), reloadAccounts()])
      return
    }
    if (data.status === 'error') {
      currentResult.value = data.result || null
      await Promise.all([refreshLinks(), reloadAccounts()])
      throw new Error(data.error || '生成失败')
    }
    setStatus(total ? `任务执行中，已完成 ${completed}/${total}，已记录 ${logs.value.length} 条日志。` : `任务执行中，已记录 ${logs.value.length} 条日志。`)
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
}

function validateStart() {
  if (!selectedEmails.value.length) {
    setStatus('请在账号池中选择至少一个账号。', true)
    return false
  }
  form.value.concurrency = Math.max(1, Math.min(10, Number(form.value.concurrency || 1)))
  if (!form.value.proxies.trim() && (!form.value.kookeeyUser || !form.value.kookeeyPass)) {
    setStatus('请填写 BR 代理列表，或在高级设置填写 Kookeey 用户名/密码。', true)
    return false
  }
  return true
}

async function start() {
  if (!validateStart()) return
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  currentJob.value = null
  setStatus(`任务已提交，正在为 ${selectedEmails.value.length} 个账号提取 PIX，并发 ${form.value.concurrency}。`)
  try {
    saveProxy()
    const payload = { ...form.value }
    const data = await api.startBrazilPixBatch({ ...payload, accountEmails: selectedEmails.value })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    currentJob.value = { id: data.job_id, status: 'queued', total: selectedEmails.value.length, completed: 0, concurrency: form.value.concurrency, running_count: 0 }
    await poll(data.job_id)
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
  } finally {
    busy.value = false
    canceling.value = false
  }
}

async function cancelJob() {
  const jobId = currentJob.value?.id
  if (!jobId || canceling.value) return
  canceling.value = true
  try {
    await api.cancelBrazilPixJob(jobId)
    setStatus('已发送取消请求，正在停止未开始的账号。')
  } catch (error) {
    setStatus(`取消失败：${cleanText(error.message || error)}`, true)
    canceling.value = false
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

async function deleteSelectedLinks() {
  const ids = Array.from(selectedLinkIds.value)
  if (!ids.length) return
  const data = await api.deleteBrazilPixLinks(ids)
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已删除 ${data.deleted || ids.length} 条链接。`)
}

async function clearLinks() {
  const data = await api.clearBrazilPixLinks()
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已清空 ${data.deleted || 0} 条链接。`)
}

function exportLinks() {
  const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `brazil-pix-links-${Date.now()}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  setStatus('链接 JSON 已导出。')
}

onMounted(() => {
  form.value.proxies = localStorage.getItem(PROXY_STORAGE_KEY) || ''
  reloadAll()
})
</script>
