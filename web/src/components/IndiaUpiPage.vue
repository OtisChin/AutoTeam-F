<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-400">India UPI</p>
          <h2 class="mt-1 text-2xl font-bold text-white">印度UPI 提链</h2>
          <p class="mt-2 text-sm text-gray-400">此 UI 与 API 为预留占位；后端核心提链尚未接入，当前不能提取或管理 UPI 链接。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border px-3 py-2 text-sm" :class="statusError ? 'border-rose-500/30 bg-rose-500/10 text-rose-200' : 'border-gray-800 bg-gray-900 text-gray-300'">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : statusError ? 'bg-rose-400' : 'bg-emerald-400'"></span>
          {{ busy ? '任务执行中' : '本地服务在线' }}
        </span>
      </div>
      <p class="mt-4 rounded-xl border px-3 py-2 text-sm" :class="statusError ? 'border-rose-500/30 bg-rose-500/10 text-rose-200' : 'border-gray-800 bg-gray-900/70 text-gray-400'">{{ statusText }}</p>
    </section>

    <div class="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(330px,0.8fr)_minmax(480px,1.2fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4"><p class="text-xs font-semibold text-gray-500">任务输入</p><h3 class="mt-1 text-xl font-bold text-white">IN 代理</h3></div>
        <div class="mt-5 space-y-5">
          <label class="block"><span class="mb-2 block text-sm font-semibold text-gray-300">代理列表</span><textarea v-model.trim="form.proxies" rows="8" spellcheck="false" :disabled="busy" placeholder="每行一个代理；支持 host:port:user:pass 或 socks5h://user:pass@host:port" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-emerald-500 focus:outline-none disabled:opacity-60"></textarea></label>
          <label class="block"><span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span><input v-model.number="form.concurrency" type="number" min="1" max="10" :disabled="busy" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-emerald-500 focus:outline-none disabled:opacity-60" /><span class="mt-1 block text-xs text-gray-500">默认 1，最高 10。</span></label>
          <details class="rounded-xl border border-gray-800 bg-gray-900/40 p-4"><summary class="cursor-pointer text-sm font-semibold text-gray-200">高级设置</summary><div class="mt-4 grid gap-4"><label><span class="mb-1.5 block text-xs text-gray-400">本地代理链</span><input v-model.trim="form.localProxy" :disabled="busy" placeholder="留空；仅链式 HTTP 代理时填写" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none" /></label><label><span class="mb-1.5 block text-xs text-gray-400">Kookeey Endpoint</span><input v-model.trim="form.kookeeyEndpoint" :disabled="busy" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none" /></label><div class="grid gap-4 sm:grid-cols-2"><label><span class="mb-1.5 block text-xs text-gray-400">Kookeey 用户名</span><input v-model.trim="form.kookeeyUser" :disabled="busy" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none" /></label><label><span class="mb-1.5 block text-xs text-gray-400">Kookeey 密码</span><input v-model="form.kookeeyPass" type="password" :disabled="busy" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-emerald-500 focus:outline-none" /></label></div></div></details>
          <div class="grid gap-3 sm:grid-cols-2"><button @click="start" :disabled="busy" class="rounded-xl bg-emerald-600 px-4 py-3 text-sm font-bold text-white shadow-lg shadow-emerald-950/40 transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50">{{ busy ? '提链中…' : '开始提链' }}</button><button @click="cancelJob" :disabled="!busy || canceling" class="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm font-bold text-amber-200 transition hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-50">{{ canceling ? '取消中…' : '取消提链' }}</button></div>
          <div class="grid gap-3 sm:grid-cols-2"><button @click="reloadAll" :disabled="busy" class="rounded-xl border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-bold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号 / 链接</button><button @click="saveProxy" class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm font-bold text-emerald-200 transition hover:bg-emerald-500/20">保存代理</button></div>
        </div>
      </section>

      <section class="overflow-hidden rounded-2xl border border-gray-800 bg-gray-950/70">
        <div class="flex flex-col gap-3 border-b border-gray-800 p-5 lg:flex-row lg:items-center lg:justify-between"><div><p class="text-xs font-semibold text-gray-500">账号池选择</p><h3 class="mt-1 text-xl font-bold text-white">选择提链账号</h3></div><span class="rounded-full bg-gray-900 px-3 py-1.5 text-xs font-bold text-gray-400">已选 {{ selectedEmails.length }} / {{ filteredAccounts.length }}</span></div>
        <div class="flex flex-col gap-3 p-5 sm:flex-row"><input v-model.trim="accountFilter" placeholder="搜索账号邮箱" class="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-emerald-500 focus:outline-none" /><select v-model="accountStatusFilter" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-gray-200 focus:border-emerald-500 focus:outline-none"><option value="all">全部状态</option><option value="pending">未提链</option><option value="running">提链中</option><option value="success">已提链</option><option value="failed">提链失败</option><option value="paid">已支付</option></select><button @click="selectAllFiltered" class="rounded-lg border border-gray-700 px-3 py-2 text-sm font-bold text-gray-200 hover:bg-gray-800">全选当前</button><button @click="clearSelectedAccounts" class="rounded-lg border border-gray-700 px-3 py-2 text-sm font-bold text-gray-400 hover:bg-gray-800">清空选择</button></div>
        <div class="max-h-[420px] overflow-auto border-t border-gray-800"><table class="w-full min-w-[640px] text-left text-sm"><thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500"><tr><th class="w-12 px-4 py-3"></th><th class="px-4 py-3">邮箱</th><th class="px-4 py-3">有效期</th><th class="px-4 py-3">提链状态</th></tr></thead><tbody class="divide-y divide-gray-900"><tr v-if="!filteredAccounts.length"><td colspan="4" class="px-4 py-10 text-center text-gray-500">暂无匹配账号</td></tr><tr v-for="account in filteredAccounts" :key="account.email" class="hover:bg-gray-900/50"><td class="px-4 py-3"><input type="checkbox" :checked="selectedAccounts.has(account.email)" :disabled="!accountSelectable(account)" @change="toggleAccount(account.email)" class="h-4 w-4 accent-emerald-500 disabled:opacity-40" /></td><td class="px-4 py-3 font-mono text-xs text-gray-200">{{ account.email }}</td><td class="px-4 py-3 text-gray-400">{{ ttlText(account.ttl_seconds) }}</td><td class="px-4 py-3"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="accountStatusClass(account)" :title="accountStatusUpdatedAt(account) ? `状态更新：${accountStatusUpdatedAt(account)}` : ''">{{ accountStatusText(account) }}</span><p v-if="accountStatusError(account)" class="mt-1 max-w-xs truncate text-xs text-rose-300" :title="accountStatusError(account)">{{ accountStatusError(account) }}</p></td></tr></tbody></table></div>
      </section>
    </div>

    <div class="grid grid-cols-1 gap-5 xl:grid-cols-2">
      <section class="overflow-hidden rounded-2xl border border-gray-800 bg-gray-950/70"><div class="border-b border-gray-800 p-5"><p class="text-xs font-semibold text-gray-500">执行日志</p><h3 class="mt-1 text-xl font-bold text-white">任务输出</h3></div><div class="max-h-72 overflow-auto p-4 font-mono text-xs"><p v-if="!logs.length" class="py-8 text-center font-sans text-gray-500">任务日志会显示在这里。</p><p v-for="(log, index) in logs" :key="`${index}-${log}`" class="border-b border-gray-900 py-2 text-gray-300">{{ log }}</p></div></section>
      <section class="overflow-hidden rounded-2xl border border-gray-800 bg-gray-950/70"><div class="border-b border-gray-800 p-5"><p class="text-xs font-semibold text-gray-500">最近一次任务</p><h3 class="mt-1 text-xl font-bold text-white">任务结果</h3></div><div class="space-y-3 p-5"><p class="rounded-xl border border-gray-800 bg-gray-900/50 p-3 text-sm text-gray-300">{{ currentResult?.message || '尚未执行任务。' }}</p><div v-if="currentResult?.skipped?.length" class="overflow-auto rounded-xl border border-gray-800"><table class="w-full text-left text-sm"><thead class="bg-gray-900 text-xs text-gray-500"><tr><th class="px-3 py-2">跳过账号</th><th class="px-3 py-2">原因</th></tr></thead><tbody class="divide-y divide-gray-900"><tr v-for="item in currentResult.skipped" :key="`${item.email}-${item.reason}`"><td class="px-3 py-2 font-mono text-xs text-gray-300">{{ item.email || '-' }}</td><td class="px-3 py-2 text-gray-400">{{ item.reason || '-' }}</td></tr></tbody></table></div></div></section>
    </div>

    <section class="overflow-hidden rounded-2xl border border-gray-800 bg-gray-950/70"><div class="flex flex-col gap-3 border-b border-gray-800 p-5 md:flex-row md:items-center md:justify-between"><div><p class="text-xs font-semibold text-gray-500">链接管理</p><h3 class="mt-1 text-xl font-bold text-white">已提取 UPI 链接</h3></div><div class="flex flex-wrap gap-2"><button @click="refreshLinks" class="rounded-lg border border-gray-700 px-3 py-2 text-sm font-bold text-gray-200 hover:bg-gray-800">刷新</button><button @click="exportLinks" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-sm font-bold text-blue-200 hover:bg-blue-500/20">导出 JSON</button><button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button><button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 px-3 py-2 text-sm font-bold text-rose-200 hover:bg-rose-500/10 disabled:opacity-50">清空</button></div></div><div class="max-h-[420px] overflow-auto"><table class="w-full min-w-[900px] text-left text-sm"><thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500"><tr><th class="w-12 px-4 py-3"></th><th class="px-4 py-3">时间</th><th class="px-4 py-3">账号</th><th class="px-4 py-3">金额</th><th class="px-4 py-3">操作</th><th class="px-4 py-3">UPI 链接</th></tr></thead><tbody class="divide-y divide-gray-900"><tr v-if="!links.length"><td colspan="6" class="px-4 py-10 text-center text-gray-500">暂无已提取 UPI 链接</td></tr><tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50"><td class="px-4 py-3"><input type="checkbox" :checked="selectedLinkIds.has(link.id)" @change="toggleLink(link.id)" class="h-4 w-4 accent-emerald-500" /></td><td class="px-4 py-3 text-xs text-gray-400">{{ link.created_at || link.createdAt || '-' }}</td><td class="px-4 py-3 font-mono text-xs text-gray-300">{{ link.account_email || link.accountEmail || '-' }}</td><td class="px-4 py-3 text-gray-300">{{ link.amount ?? '-' }}</td><td class="px-4 py-3"><button @click="copy(link.upi_link || link.upiLink || link.url)" class="rounded-lg border border-gray-700 px-2 py-1 text-xs text-gray-200 hover:bg-gray-800">复制</button></td><td class="max-w-md px-4 py-3 font-mono text-xs text-emerald-300"><span class="block truncate" :title="link.upi_link || link.upiLink || link.url || ''">{{ link.upi_link || link.upiLink || link.url || '-' }}</span></td></tr></tbody></table></div></section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'

const FORM_STORAGE_KEY = 'autotoken_india_upi_form'
const JOB_STORAGE_KEY = 'autotoken_india_upi_job'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented'])
const ACCOUNT_STATUS_TEXT = { pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', paid: '已支付' }

const form = ref({ proxies: '', concurrency: 1, localProxy: '', kookeeyEndpoint: 'gate.kookeey.info:1000', kookeeyUser: '', kookeeyPass: '' })
const accounts = ref([])
const links = ref([])
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const busy = ref(false)
const canceling = ref(false)
const currentJob = ref(null)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const currentResult = ref(null)
const accountFilter = ref('')
const accountStatusFilter = ref('all')

const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const filteredAccounts = computed(() => accounts.value.filter((account) => {
  const status = accountJobStatus(account)?.status || account.upi_status || 'pending'
  return (!accountFilter.value || String(account.email || '').toLowerCase().includes(accountFilter.value.toLowerCase())) && (accountStatusFilter.value === 'all' || status === accountStatusFilter.value)
}))

function setStatus(message, error = false) { statusText.value = message; statusError.value = error }
function cleanError(error) { return String(error?.message || error || '未知错误') }
function accountJobStatus(account) { const statuses = currentJob.value?.account_statuses || {}; return statuses[account.email] || statuses[String(account.email || '').toLowerCase()] }
function ttlText(seconds) { const value = Number(seconds); if (!Number.isFinite(value) || value < 0) return '-'; if (value < 60) return `${Math.floor(value)}s`; if (value < 3600) return `${Math.ceil(value / 60)}m`; return `${Math.ceil(value / 3600)}h` }
function accountStatusText(account) { const jobStatus = accountJobStatus(account); if (jobStatus) return jobStatus.status_text || ACCOUNT_STATUS_TEXT[jobStatus.status] || '未提链'; return account.upi_status_text || ACCOUNT_STATUS_TEXT[account.upi_status] || '未提链' }
function accountStatusUpdatedAt(account) { return account.upi_status_updated_at || '' }
function accountStatusClass(account) { const status = accountJobStatus(account)?.status || account.upi_status || 'pending'; return ({ running: 'border-blue-500/30 bg-blue-500/10 text-blue-300', success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300', failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300', paid: 'border-violet-500/30 bg-violet-500/10 text-violet-300' })[status] || 'border-gray-700 bg-gray-900 text-gray-400' }
function accountStatusError(account) { return accountJobStatus(account)?.error || account.upi_error || '' }
function accountSelectable(account) { return account.upi_selectable !== false && (accountJobStatus(account)?.status || account.upi_status) !== 'paid' }
function toggleAccount(email) { const account = accounts.value.find(item => item.email === email); if (!account || !accountSelectable(account)) return; const next = new Set(selectedAccounts.value); next.has(email) ? next.delete(email) : next.add(email); selectedAccounts.value = next }
function selectAllFiltered() { selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).map(account => account.email)) }
function clearSelectedAccounts() { selectedAccounts.value = new Set() }
function toggleLink(id) { const next = new Set(selectedLinkIds.value); next.has(id) ? next.delete(id) : next.add(id); selectedLinkIds.value = next }

async function refreshAccounts() {
  const data = await api.getIndiaUpiAccounts()
  accounts.value = Array.isArray(data.accounts) ? data.accounts : []
  const available = new Set(accounts.value.filter(accountSelectable).map(account => account.email))
  selectedAccounts.value = new Set(selectedEmails.value.filter(email => available.has(email)))
}

async function refreshLinks() {
  const data = await api.getIndiaUpiLinks()
  links.value = Array.isArray(data.links) ? data.links : []
  const available = new Set(links.value.map(link => link.id))
  selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => available.has(id)))
}

async function start() {
  if (!selectedEmails.value.length) {
    statusText.value = '请先选择要提链的账号。'
    statusError.value = true
    return
  }
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  statusError.value = false
  try {
    form.value.concurrency = Math.max(1, Math.min(10, Number(form.value.concurrency || 1)))
    const data = await api.startIndiaUpiBatch({ ...form.value, accountEmails: selectedEmails.value })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    currentJob.value = { id: data.job_id, status: 'queued', total: selectedEmails.value.length, completed: 0 }
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({ jobId: data.job_id, savedAt: Date.now() }))
    await pollJob(data.job_id)
  } catch (error) {
    setStatus(`提交任务失败：${cleanError(error)}`, true)
  } finally {
    busy.value = false
    canceling.value = false
  }
}

async function pollJob(jobId) {
  if (!isMounted) return
  const job = await api.getIndiaUpiJob(jobId)
  if (!isMounted) return
  currentJob.value = job
  logs.value = Array.isArray(job.logs) ? job.logs : []
  currentResult.value = job.result || null
  busy.value = !TERMINAL_STATUSES.has(String(job.status || ''))
  statusText.value = job.error || currentResult.value?.message || '任务状态已更新。'
  statusError.value = ['error', 'failed'].includes(String(job.status || ''))
  if (TERMINAL_STATUSES.has(String(job.status || ''))) { localStorage.removeItem(JOB_STORAGE_KEY); await Promise.all([refreshAccounts(), refreshLinks()]); return }
  localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({ jobId, savedAt: Date.now() }))
  await new Promise(resolve => window.setTimeout(resolve, 1000))
  if (isMounted && busy.value) await pollJob(jobId)
}

async function reloadAll() { try { await Promise.all([refreshAccounts(), refreshLinks()]); setStatus('账号和链接已刷新。') } catch (error) { setStatus(`刷新失败：${cleanError(error)}`, true) } }
async function cancelJob() { const jobId = currentJob.value?.id; if (!jobId || canceling.value) return; canceling.value = true; try { await api.cancelIndiaUpiJob(jobId); setStatus('已发送取消请求，正在同步任务状态。'); await pollJob(jobId) } catch (error) { setStatus(`取消失败：${cleanError(error)}`, true) } finally { canceling.value = false } }
function saveProxy() { localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value)); setStatus('代理和高级设置已保存。') }
async function deleteSelectedLinks() { const ids = Array.from(selectedLinkIds.value); if (!ids.length) return; try { const data = await api.deleteIndiaUpiLinks(ids); links.value = Array.isArray(data.links) ? data.links : []; selectedLinkIds.value = new Set(); setStatus(`已删除 ${data.deleted || ids.length} 条链接。`) } catch (error) { setStatus(`删除失败：${cleanError(error)}`, true) } }
async function clearLinks() { if (!links.value.length) return; try { const data = await api.clearIndiaUpiLinks(); links.value = Array.isArray(data.links) ? data.links : []; selectedLinkIds.value = new Set(); setStatus(`已清空 ${data.deleted || 0} 条链接。`) } catch (error) { setStatus(`清空失败：${cleanError(error)}`, true) } }
function exportLinks() { const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const anchor = document.createElement('a'); anchor.href = url; anchor.download = `india-upi-links-${Date.now()}.json`; anchor.click(); URL.revokeObjectURL(url); setStatus('链接 JSON 已导出。') }
async function copy(value) { const text = String(value || ''); if (!text) return; if (!navigator.clipboard?.writeText) { setStatus('当前环境不支持复制。', true); return } try { await navigator.clipboard.writeText(text); setStatus('已复制 UPI 链接。') } catch (error) { setStatus(`复制失败：${cleanError(error)}`, true) } }

let isMounted = true
onUnmounted(() => { isMounted = false })
onMounted(async () => {
  try { Object.assign(form.value, JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) || '{}')) } catch { /* ignore malformed local state */ }
  await reloadAll()
  try { const saved = JSON.parse(localStorage.getItem(JOB_STORAGE_KEY) || '{}'); if (saved.jobId) { busy.value = true; await pollJob(saved.jobId) } } catch (error) { localStorage.removeItem(JOB_STORAGE_KEY); currentJob.value = null; busy.value = false; setStatus(`恢复任务失败：${cleanError(error)}`, true) }
})
watch(form, () => localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value)), { deep: true })
</script>
