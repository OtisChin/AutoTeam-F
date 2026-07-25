<template>
  <div class="space-y-6">
    <section class="rounded-xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-sm uppercase tracking-[0.3em] text-yellow-300">Korea Kakao Pay</p>
          <h2 class="mt-1 text-2xl font-bold text-white">韩国 Kakao Pay 提链</h2>
          <p class="mt-2 text-sm text-gray-400">创建 KRW ChatGPT Plus checkout，确认 Kakao Pay 后提取 Stripe/NICEPAY 授权来链。</p>
        </div>
        <button class="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-100 hover:bg-gray-700" @click="refreshAll" :disabled="loading">
          {{ loading ? '刷新中...' : '刷新账号/链接' }}
        </button>
      </div>
    </section>

    <section class="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
      <div class="rounded-xl border border-gray-800 bg-gray-950/70 p-5">
        <h3 class="text-lg font-semibold text-white">任务输入</h3>
        <label class="mt-4 block text-sm text-gray-400">KR 代理列表</label>
        <textarea v-model="form.proxies" class="mt-2 h-28 w-full rounded-lg border border-gray-700 bg-gray-900 p-3 text-sm text-gray-100" placeholder="host:port:user-region-KR-sid-xxx-t-120:pass，每行一个"></textarea>
        <div class="mt-4 grid gap-4 sm:grid-cols-2">
          <label class="block text-sm text-gray-400">
            并发数
            <input v-model.number="form.concurrency" type="number" min="1" max="20" class="mt-2 w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-gray-100" />
          </label>
          <label class="block text-sm text-gray-400">
            单账号重试
            <input v-model.number="form.maxAttempts" type="number" min="1" max="20" class="mt-2 w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-gray-100" />
          </label>
        </div>
        <div class="mt-5 flex flex-wrap gap-3">
          <button class="rounded-lg bg-yellow-400 px-4 py-2 text-sm font-semibold text-gray-950 hover:bg-yellow-300 disabled:opacity-50" @click="startBatch" :disabled="starting || selectedEmails.length === 0">
            {{ starting ? '启动中...' : '开始提链' }}
          </button>
          <button class="rounded-lg bg-gray-800 px-4 py-2 text-sm text-gray-100 hover:bg-gray-700 disabled:opacity-50" @click="cancelJob" :disabled="!activeJobId || cancelling">取消提链</button>
        </div>
        <p class="mt-3 text-sm text-gray-400">{{ statusText }}</p>
      </div>

      <div class="rounded-xl border border-gray-800 bg-gray-950/70 p-5">
        <h3 class="text-lg font-semibold text-white">执行日志</h3>
        <div class="mt-3 h-80 overflow-y-auto rounded-lg bg-black/40 p-3 font-mono text-xs text-gray-300">
          <div v-for="(line, index) in logs" :key="index">{{ line }}</div>
          <div v-if="!logs.length" class="text-gray-500">暂无日志</div>
        </div>
      </div>
    </section>

    <section class="rounded-xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h3 class="text-lg font-semibold text-white">账号池</h3>
        <div class="flex gap-2">
          <button class="rounded bg-gray-800 px-3 py-1.5 text-sm text-gray-100" @click="selectAll">全选可用</button>
          <button class="rounded bg-gray-800 px-3 py-1.5 text-sm text-gray-100" @click="selectedEmails = []">清空</button>
        </div>
      </div>
      <div class="mt-3 max-h-80 overflow-auto rounded-lg border border-gray-800">
        <table class="min-w-full text-left text-sm">
          <thead class="bg-gray-900 text-gray-400"><tr><th class="p-3">选择</th><th class="p-3">邮箱</th><th class="p-3">状态</th><th class="p-3">错误</th></tr></thead>
          <tbody>
            <tr v-for="account in accounts" :key="account.email" class="border-t border-gray-800 text-gray-200">
              <td class="p-3"><input v-model="selectedEmails" type="checkbox" :value="account.email" :disabled="!account.kakao_selectable" /></td>
              <td class="p-3">{{ account.email }}</td>
              <td class="p-3">{{ account.kakao_status_text || account.kakao_status }}</td>
              <td class="p-3 text-xs text-red-300">{{ account.kakao_error || '-' }}</td>
            </tr>
            <tr v-if="!accounts.length"><td colspan="4" class="p-4 text-center text-gray-500">暂无账号</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="rounded-xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-wrap items-center justify-between gap-3">
        <h3 class="text-lg font-semibold text-white">已提取 Kakao 链接</h3>
        <button class="rounded bg-red-900/50 px-3 py-1.5 text-sm text-red-100" @click="clearLinks">清空链接</button>
      </div>
      <div class="mt-3 space-y-3">
        <div v-for="link in links" :key="link.id" class="rounded-lg border border-gray-800 bg-gray-900/70 p-3">
          <div class="flex flex-wrap justify-between gap-2 text-sm">
            <span class="text-white">{{ link.account_email }}</span>
            <span class="text-gray-400">{{ link.created_at }} · {{ link.amount }} KRW</span>
          </div>
          <a :href="link.kakao_link" target="_blank" class="mt-2 block break-all text-sm text-yellow-300 hover:text-yellow-200">{{ link.kakao_link }}</a>
          <div v-if="link.provider_redirect_url" class="mt-1 break-all text-xs text-gray-500">provider: {{ link.provider_redirect_url }}</div>
        </div>
        <div v-if="!links.length" class="rounded-lg border border-dashed border-gray-800 p-6 text-center text-gray-500">暂无链接</div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api.js'

const accounts = ref([])
const links = ref([])
const selectedEmails = ref([])
const logs = ref([])
const loading = ref(false)
const starting = ref(false)
const cancelling = ref(false)
const activeJobId = ref('')
const statusText = ref('请选择账号并填写 KR 代理后开始提链。')
const form = ref({ proxies: localStorage.getItem('kakao_pay_proxies') || '', concurrency: 1, maxAttempts: 5 })
let timer = null

async function refreshAll() {
  loading.value = true
  try {
    const [accountData, linkData] = await Promise.all([api.getKakaoPayAccounts(), api.getKakaoPayLinks()])
    accounts.value = Array.isArray(accountData.accounts) ? accountData.accounts : []
    links.value = Array.isArray(linkData.links) ? linkData.links : []
  } finally {
    loading.value = false
  }
}

function selectAll() {
  selectedEmails.value = accounts.value.filter(item => item.kakao_selectable).map(item => item.email)
}

async function startBatch() {
  starting.value = true
  localStorage.setItem('kakao_pay_proxies', form.value.proxies || '')
  try {
    const data = await api.startKakaoPayBatch({
      accountEmails: selectedEmails.value,
      proxies: form.value.proxies,
      concurrency: form.value.concurrency,
      maxAttempts: form.value.maxAttempts,
      region: 'KR',
    })
    activeJobId.value = data.job_id
    statusText.value = `任务已创建：${data.job_id}`
    logs.value = []
    startPolling()
  } catch (error) {
    statusText.value = error?.message || String(error)
  } finally {
    starting.value = false
  }
}

async function pollJob() {
  if (!activeJobId.value) return
  const job = await api.getKakaoPayJob(activeJobId.value)
  logs.value = Array.isArray(job.logs) ? job.logs : []
  statusText.value = `状态：${job.status}，完成 ${job.completed || 0}/${job.total || 0}`
  if (['success', 'error', 'failed', 'cancelled'].includes(String(job.status || ''))) {
    stopPolling()
    await refreshAll()
  }
}

function startPolling() {
  stopPolling()
  pollJob()
  timer = window.setInterval(pollJob, 3000)
}

function stopPolling() {
  if (timer) window.clearInterval(timer)
  timer = null
}

async function cancelJob() {
  if (!activeJobId.value) return
  cancelling.value = true
  try {
    await api.cancelKakaoPayJob(activeJobId.value)
    await pollJob()
  } finally {
    cancelling.value = false
  }
}

async function clearLinks() {
  await api.clearKakaoPayLinks()
  await refreshAll()
}

onMounted(refreshAll)
onUnmounted(stopPolling)
</script>
