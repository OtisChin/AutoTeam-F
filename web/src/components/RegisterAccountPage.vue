<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-2">注册账号</h2>
    <p class="text-sm text-gray-400 mb-6">
      使用当前已配置的邮箱服务执行纯注册任务，不进行后续 OAuth / 入池流程。支持单次注册和批量注册。
    </p>

    <div class="flex items-center gap-2 mb-4">
      <button
        @click="statsMode = 'task'"
        class="px-3 py-1.5 rounded-lg text-xs border transition"
        :class="statsMode === 'task'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
        本次任务
      </button>
      <button
        @click="statsMode = 'today'"
        class="px-3 py-1.5 rounded-lg text-xs border transition"
        :class="statsMode === 'today'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
        今日统计
      </button>
    </div>

    <div v-if="statsMode === 'task'" class="mb-4 px-4 py-3 rounded-lg border bg-gray-900 border-gray-800 text-sm text-gray-300">
      <span class="text-gray-500">任务 ID：</span>
      <span class="font-mono text-white">{{ currentTaskMeta.taskId || '-' }}</span>
      <span class="mx-3 text-gray-700">|</span>
      <span class="text-gray-500">开始时间：</span>
      <span class="font-mono text-white">{{ currentTaskMeta.startedAt || '-' }}</span>
    </div>

    <div class="grid grid-cols-2 xl:grid-cols-5 gap-4 mb-6">
      <div v-for="card in statCards" :key="card.label" class="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div class="text-sm text-gray-400">{{ card.label }}</div>
        <div class="text-3xl font-bold mt-1" :class="card.color">{{ card.value }}</div>
      </div>
    </div>

    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <h3 class="text-lg font-semibold text-white">注册配置</h3>
          <p class="text-sm text-gray-400 mt-1">
            指定前缀后，邮箱格式会变成 `prefix + 5位随机字母数字 @domain`，例如 `gptteama8k3p@openaibus.com`。
          </p>
        </div>
      </div>

      <div v-if="message" class="mt-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)] gap-4">
        <div class="space-y-3">
          <div>
            <label class="block text-sm text-gray-400 mb-1">注册模式</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="registerForm.mode = 'single'"
                :disabled="registeringBusy"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="registerForm.mode === 'single'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                单次注册
              </button>
              <button
                @click="registerForm.mode = 'batch'"
                :disabled="registeringBusy"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="registerForm.mode === 'batch'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                批量注册
              </button>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">注册域名</label>
            <select
              v-if="registerForm.mode === 'single'"
              v-model="registerForm.domain"
              :disabled="registeringBusy || !registerDomainOptions.length"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="domain in registerDomainOptions" :key="domain" :value="domain">
                @{{ domain }}
              </option>
            </select>
            <div v-else class="relative">
              <button
                type="button"
                @click="toggleRegisterDomainDropdown"
                :disabled="registeringBusy || !registerDomainOptions.length"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50 flex items-center justify-between gap-3 text-left"
              >
                <span class="truncate">{{ selectedRegisterDomainsLabel }}</span>
                <span class="text-gray-500 text-xs">{{ registerDomainDropdownOpen ? '收起' : '展开' }}</span>
              </button>
              <div
                v-if="registerDomainDropdownOpen"
                class="absolute z-30 mt-2 w-full rounded-lg border border-gray-700 bg-gray-900 shadow-2xl"
              >
                <div class="flex items-center justify-between gap-3 px-3 py-2 border-b border-gray-800">
                  <div class="text-xs text-gray-400">
                    已选择 {{ selectedRegisterDomains.length }} / {{ registerDomainOptions.length }}
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      @click="selectAllRegisterDomains"
                      :disabled="registerAllDomainsSelected"
                      class="px-2 py-1 rounded-md text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                      全选
                    </button>
                    <button
                      type="button"
                      @click="clearRegisterDomains"
                      :disabled="!selectedRegisterDomains.length"
                      class="px-2 py-1 rounded-md text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                      清空
                    </button>
                  </div>
                </div>
                <div class="max-h-52 overflow-y-auto px-2 py-2 space-y-1">
                  <label
                    v-for="domain in registerDomainOptions"
                    :key="`batch-domain-${domain}`"
                    class="flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-gray-200 hover:bg-gray-800 cursor-pointer"
                  >
                    <input
                      v-model="registerForm.selectedDomains"
                      type="checkbox"
                      :value="domain"
                      class="accent-blue-500"
                    />
                    <span class="font-mono text-xs">@{{ domain }}</span>
                  </label>
                </div>
              </div>
            </div>
            <div class="mt-1 text-xs text-gray-500">
              <span v-if="registerForm.mode === 'batch'">
                已选择 {{ selectedRegisterDomains.length }} / {{ registerDomainOptions.length }} 个域名，批量注册时每个账号随机使用一个。
              </span>
              <span v-else>
                可选域名列表在“设置”页面维护。当前共 {{ registerDomainOptions.length }} 个域名。
              </span>
            </div>
          </div>

          <div v-if="registerForm.mode === 'batch'">
            <label class="block text-sm text-gray-400 mb-1">批量数量（1-1000）</label>
            <input
              v-model.number="registerForm.count"
              type="number"
              min="1"
              max="1000"
              :disabled="registeringBusy"
              class="w-full px-3 py-2 bg-gray-800 border rounded-lg text-sm text-white focus:outline-none"
              :class="validBatchCount ? 'border-gray-700 focus:border-blue-500' : 'border-red-500 focus:border-red-400'"
            />
            <div v-if="!validBatchCount" class="mt-1 text-xs text-red-400">批量数量不能超过 1000</div>
          </div>

          <div v-if="registerForm.mode === 'batch'" class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">并发数</label>
              <input
                v-model.number="registerForm.concurrency"
                type="number"
                min="1"
                max="20"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">间隔秒数</label>
              <input
                v-model.number="registerForm.intervalSeconds"
                type="number"
                min="0"
                step="0.5"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div v-if="registerForm.mode === 'batch'" class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">随机抖动最小值</label>
              <input
                v-model.number="registerForm.jitterMinSeconds"
                type="number"
                min="0"
                step="0.5"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">随机抖动最大值</label>
              <input
                v-model.number="registerForm.jitterMaxSeconds"
                type="number"
                min="0"
                step="0.5"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">邮箱前缀</label>
            <div class="flex items-center rounded-lg border border-gray-700 bg-gray-800">
              <input
                v-model.trim="registerForm.prefix"
                type="text"
                placeholder="例如 prefix"
                :disabled="registeringBusy"
                class="flex-1 px-3 py-2 bg-transparent text-sm text-white focus:outline-none"
              />
              <div class="px-3 text-xs text-gray-500 border-l border-gray-700">
                +5位随机字母数字 {{ registerDomainSuffixLabel }}
              </div>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">密码</label>
            <input
              v-model.trim="registerForm.password"
              type="text"
              placeholder="留空自动生成"
              :disabled="registeringBusy"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>预览邮箱：<span class="font-mono text-gray-200">{{ registerPreviewEmail }}</span></div>
            <div>密码：<span class="text-gray-200">{{ registerForm.password || '自动随机生成' }}</span></div>
            <div>行为：<span class="text-gray-200">{{ registerBehaviorLabel }}</span></div>
            <div v-if="registerForm.mode === 'batch'">域名轮换：<span class="text-gray-200">{{ selectedRegisterDomainsLabel }}</span></div>
            <div v-if="registerForm.mode === 'batch'">批量策略：<span class="text-gray-200">并发 {{ validConcurrency }}，固定间隔 {{ validIntervalSeconds }}s，随机抖动 {{ validJitterMinSeconds }}-{{ validJitterMaxSeconds }}s</span></div>
          </div>

          <div class="flex items-center gap-3">
            <button
              @click="submitManualRegister"
              :disabled="registeringBusy || registeringAccount || !canSubmitRegister"
              class="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition disabled:opacity-50">
              {{ registeringAccount ? '提交中...' : (registerForm.mode === 'batch' ? '开始批量注册' : '开始注册') }}
            </button>
            <button
              @click="reloadRegisterDomains"
              :disabled="registerConfigLoading"
              class="px-3 py-2 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
              {{ registerConfigLoading ? '刷新中...' : '刷新域名' }}
            </button>
          </div>
        </div>

        <div class="min-h-0">
          <div class="border border-gray-800 rounded-xl bg-gray-950/60 overflow-hidden h-full">
            <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
              <div>
                <h3 class="text-white font-semibold">注册日志</h3>
                <div class="text-xs text-gray-500 mt-0.5">显示最近的注册相关日志</div>
              </div>
              <button
                @click="loadRegisterLogs"
                :disabled="logsLoading"
                class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                {{ logsLoading ? '加载中...' : '刷新日志' }}
              </button>
            </div>
            <div ref="logsContainer" class="h-[620px] overflow-y-auto px-4 py-3 space-y-2">
              <div v-if="!registerLogs.length" class="text-sm text-gray-500">暂无注册日志</div>
              <div
                v-for="(log, idx) in registerLogs"
                :key="idx"
                class="border border-gray-800 rounded-lg px-3 py-2 bg-gray-900/70">
                <div class="flex items-center justify-between gap-3">
                  <span class="text-xs font-mono text-gray-500">{{ fmtLogTime(log.time) }}</span>
                  <span class="text-[11px] uppercase tracking-wide" :class="logLevelClass(log.level)">{{ log.level }}</span>
                </div>
                <div class="mt-1 text-sm text-gray-200 whitespace-pre-wrap break-words">{{ log.message }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'

const REGISTER_FORM_STORAGE_KEY = 'autoteam_register_form_v1'

const props = defineProps({
  runningTask: Object,
  adminStatus: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['task-started', 'refresh'])

const message = ref('')
const messageClass = ref('')
const registerConfigLoading = ref(false)
const registeringAccount = ref(false)
const registerDomainOptions = ref([])
const registerDomainDropdownOpen = ref(false)
const registerLogs = ref([])
const logsLoading = ref(false)
const logsContainer = ref(null)
const registerStats = ref({
  task: { total: 0, ok: 0, failed: 0, pendingRetry: 0, successRate: 0 },
  today: { total: 0, ok: 0, failed: 0, pendingRetry: 0, successRate: 0 },
})
const statsMode = ref('task')
const registerForm = ref({
  mode: 'single',
  count: 1,
  concurrency: 3,
  intervalSeconds: 12,
  jitterMinSeconds: 8,
  jitterMaxSeconds: 20,
  domain: '',
  selectedDomains: [],
  prefix: '',
  password: '',
})

const registeringBusy = computed(() => !!props.runningTask)
const validBatchCount = computed(() => {
  const count = Number(registerForm.value.count || 0)
  return registerForm.value.mode === 'single' ? true : count >= 1 && count <= 1000
})
const validConcurrency = computed(() => {
  const value = Number(registerForm.value.concurrency || 0)
  return Math.max(1, Math.min(20, value || 3))
})
const validIntervalSeconds = computed(() => {
  const value = Number(registerForm.value.intervalSeconds ?? 12)
  return Math.max(0, value)
})
const validJitterMinSeconds = computed(() => {
  const value = Number(registerForm.value.jitterMinSeconds ?? 8)
  return Math.max(0, value)
})
const validJitterMaxSeconds = computed(() => {
  const value = Number(registerForm.value.jitterMaxSeconds ?? 20)
  return Math.max(validJitterMinSeconds.value, value)
})
const selectedRegisterDomains = computed(() => {
  const source = registerForm.value.mode === 'batch'
    ? registerForm.value.selectedDomains
    : [registerForm.value.domain]
  const seen = new Set()
  return (Array.isArray(source) ? source : [])
    .map(domain => String(domain || '').trim().replace(/^@/, ''))
    .filter(domain => {
      if (!domain || seen.has(domain)) return false
      if (registerDomainOptions.value.length && !registerDomainOptions.value.includes(domain)) return false
      seen.add(domain)
      return true
    })
})
const selectedRegisterDomainsLabel = computed(() => {
  const domains = selectedRegisterDomains.value
  if (!domains.length) return '未选择'
  if (domains.length <= 3) return domains.map(domain => `@${domain}`).join(' / ')
  return `${domains.slice(0, 3).map(domain => `@${domain}`).join(' / ')} 等 ${domains.length} 个`
})
const registerAllDomainsSelected = computed(() => {
  if (!registerDomainOptions.value.length) return false
  const selected = new Set(selectedRegisterDomains.value)
  return registerDomainOptions.value.every(domain => selected.has(domain))
})
const registerDomainSuffixLabel = computed(() => {
  if (registerForm.value.mode === 'batch') {
    return selectedRegisterDomains.value.length
      ? `@随机域名(${selectedRegisterDomains.value.length})`
      : '@domain.com'
  }
  return `@${registerForm.value.domain || 'domain.com'}`
})
const registerPreviewEmail = computed(() => {
  const prefix = registerForm.value.prefix ? `${registerForm.value.prefix}a8k3p` : '__random__'
  const domain = registerForm.value.mode === 'batch'
    ? (selectedRegisterDomains.value[0] || 'domain.com')
    : (registerForm.value.domain || 'domain.com')
  return `${prefix}@${domain}`
})
const registerBehaviorLabel = computed(() => '只注册免费账号并保存 auth_session')
const canSubmitRegister = computed(() => {
  if (!validBatchCount.value) return false
  return registerForm.value.mode === 'batch'
    ? selectedRegisterDomains.value.length > 0
    : Boolean(registerForm.value.domain)
})
let logsTimer = null
let statsTimer = null
const statCards = computed(() => {
  const scope = statsMode.value === 'today' ? registerStats.value.today : registerStats.value.task
  const prefix = statsMode.value === 'today' ? '今日' : '本次'
  return [
    { label: `${prefix}注册`, value: scope.total, color: 'text-blue-400' },
    { label: `${prefix}成功`, value: scope.ok, color: 'text-emerald-400' },
    { label: `${prefix}失败`, value: scope.failed, color: 'text-rose-400' },
    { label: `${prefix}待重试`, value: scope.pendingRetry || 0, color: 'text-violet-300' },
    { label: `${prefix}成功率`, value: `${scope.successRate.toFixed(1)}%`, color: 'text-amber-300' },
  ]
})
const currentTaskMeta = computed(() => ({
  taskId: registerStats.value.taskMeta?.taskId || '',
  startedAt: registerStats.value.taskMeta?.startedAt || '',
}))

function setMessage(text, ok = true) {
  message.value = text
  messageClass.value = ok
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 8000)
}

function toggleRegisterDomainDropdown() {
  if (registeringBusy.value || !registerDomainOptions.value.length) return
  registerDomainDropdownOpen.value = !registerDomainDropdownOpen.value
}

function selectAllRegisterDomains() {
  registerForm.value.selectedDomains = [...registerDomainOptions.value]
}

function clearRegisterDomains() {
  registerForm.value.selectedDomains = []
}

function loadSavedRegisterForm() {
  try {
    const raw = localStorage.getItem(REGISTER_FORM_STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return
    registerForm.value = {
      ...registerForm.value,
      mode: saved.mode === 'batch' ? 'batch' : 'single',
      count: Number(saved.count || registerForm.value.count),
      concurrency: Number(saved.concurrency || registerForm.value.concurrency),
      intervalSeconds: Number(saved.intervalSeconds ?? registerForm.value.intervalSeconds),
      jitterMinSeconds: Number(saved.jitterMinSeconds ?? registerForm.value.jitterMinSeconds),
      jitterMaxSeconds: Number(saved.jitterMaxSeconds ?? registerForm.value.jitterMaxSeconds),
      domain: String(saved.domain || ''),
      selectedDomains: Array.isArray(saved.selectedDomains)
        ? saved.selectedDomains.map(domain => String(domain || '').trim()).filter(Boolean)
        : [],
      prefix: String(saved.prefix || ''),
      // 密码不持久化，避免明文留在本地存储
      password: '',
    }
  } catch (e) {
    console.error('loadSavedRegisterForm', e)
  }
}

function saveRegisterForm() {
  try {
    localStorage.setItem(
      REGISTER_FORM_STORAGE_KEY,
      JSON.stringify({
        mode: registerForm.value.mode,
        count: registerForm.value.count,
        concurrency: registerForm.value.concurrency,
        intervalSeconds: registerForm.value.intervalSeconds,
        jitterMinSeconds: registerForm.value.jitterMinSeconds,
        jitterMaxSeconds: registerForm.value.jitterMaxSeconds,
        domain: registerForm.value.domain,
        selectedDomains: selectedRegisterDomains.value,
        prefix: registerForm.value.prefix,
      })
    )
  } catch (e) {
    console.error('saveRegisterForm', e)
  }
}

async function reloadRegisterDomains() {
  registerConfigLoading.value = true
  try {
    const result = await api.getRegisterDomain()
    const domains = result.domains?.length ? result.domains : (result.domain ? [result.domain] : [])
    registerDomainOptions.value = domains
    if (!registerForm.value.domain || !domains.includes(registerForm.value.domain)) {
      registerForm.value.domain = result.domain || domains[0] || ''
    }
    const selected = selectedRegisterDomains.value.filter(domain => domains.includes(domain))
    registerForm.value.selectedDomains = selected.length
      ? selected
      : (registerForm.value.domain ? [registerForm.value.domain] : [])
  } catch (e) {
    setMessage(`读取注册域名失败: ${e.message}`, false)
  } finally {
    registerConfigLoading.value = false
  }
}

async function loadRegisterLogs() {
  logsLoading.value = true
  try {
    const result = await api.getLogs(200)
    registerLogs.value = (result.logs || []).filter(entry => {
      const msg = String(entry.message || '')
      return msg.includes('[注册账号]') || msg.includes('[直接注册]') || msg.includes('[注册]') || msg.includes('[Codex]')
    })
    await nextTick()
    if (logsContainer.value) {
      logsContainer.value.scrollTop = logsContainer.value.scrollHeight
    }
  } catch (e) {
    setMessage(`读取注册日志失败: ${e.message}`, false)
  } finally {
    logsLoading.value = false
  }
}

async function loadRegisterStats() {
  try {
    const tasks = await api.getTasks()
    const registerTasks = (tasks || []).filter(task => task.command === 'register')
    const todayStart = new Date()
    todayStart.setHours(0, 0, 0, 0)
    const todayStartTs = todayStart.getTime() / 1000

    const activeTask = registerTasks.find(task => task.status === 'running' || task.status === 'pending') || null
    const latestTask = activeTask || registerTasks[0] || null
    const taskScope = { total: 0, ok: 0, failed: 0, pendingRetry: 0 }
    const today = { total: 0, ok: 0, failed: 0, pendingRetry: 0 }

    for (const task of registerTasks) {
      const createdAt = Number(task.created_at || 0)
      const result = task.result || {}
      const count = typeof result.count === 'number' ? Number(result.count || 0) : Number(task.params?.count || 1)
      const okCount = typeof result.ok === 'number' ? Number(result.ok || 0) : 0
      const failedCount = typeof result.failed === 'number' ? Number(result.failed || 0) : 0
      const pendingRetryCount = typeof result.pending_retry === 'number' ? Number(result.pending_retry || 0) : 0

      if (createdAt >= todayStartTs) {
        today.total += count
        today.ok += okCount
        today.failed += failedCount
        today.pendingRetry += pendingRetryCount
      }
      if (latestTask && task.task_id === latestTask.task_id) {
        const progress = task.progress || null
        if (progress && (task.status === 'running' || task.status === 'pending')) {
          taskScope.total += Number(progress.total || count || 0)
          taskScope.ok += Number(progress.ok || 0)
          taskScope.failed += Number(progress.failed || 0)
          taskScope.pendingRetry += Number(progress.pending_retry || 0)
        } else {
          taskScope.total += count
          taskScope.ok += okCount
          taskScope.failed += failedCount
          taskScope.pendingRetry += pendingRetryCount
        }
      }
    }

    registerStats.value = {
      task: {
        ...taskScope,
        successRate: taskScope.total > 0 ? (taskScope.ok / taskScope.total) * 100 : 0,
      },
      today: {
        ...today,
        successRate: today.total > 0 ? (today.ok / today.total) * 100 : 0,
      },
      taskMeta: latestTask
        ? {
            taskId: latestTask.task_id || '',
            startedAt: fmtTaskTime(latestTask.started_at || latestTask.created_at || 0),
          }
        : {
            taskId: '',
            startedAt: '',
          },
    }
  } catch (e) {
    console.error('loadRegisterStats', e)
  }
}

async function submitManualRegister() {
  if (registeringBusy.value || registeringAccount.value) return
  registeringAccount.value = true
  try {
    const payload = {
      mode: registerForm.value.mode,
      count: registerForm.value.mode === 'batch' ? Number(registerForm.value.count || 1) : 1,
      concurrency: registerForm.value.mode === 'batch' ? validConcurrency.value : 1,
      interval_seconds: registerForm.value.mode === 'batch' ? validIntervalSeconds.value : 0,
      jitter_min_seconds: registerForm.value.mode === 'batch' ? validJitterMinSeconds.value : 0,
      jitter_max_seconds: registerForm.value.mode === 'batch' ? validJitterMaxSeconds.value : 0,
      domain: registerForm.value.domain,
      domains: registerForm.value.mode === 'batch' ? selectedRegisterDomains.value : [],
      prefix: registerForm.value.prefix || null,
      password: registerForm.value.password || null,
    }
    const result = await api.startAdd(payload)
    setMessage(`注册任务已提交: ${result.task_id}`)
    emit('task-started')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, false)
  } finally {
    registeringAccount.value = false
  }
}

watch(
  registerForm,
  () => {
    saveRegisterForm()
  },
  { deep: true }
)

watch(
  () => registerForm.value.mode,
  mode => {
    registerDomainDropdownOpen.value = false
    if (mode === 'batch' && !selectedRegisterDomains.value.length && registerForm.value.domain) {
      registerForm.value.selectedDomains = [registerForm.value.domain]
    }
    if (mode === 'single' && !registerForm.value.domain && selectedRegisterDomains.value.length) {
      registerForm.value.domain = selectedRegisterDomains.value[0]
    }
  }
)

onMounted(reloadRegisterDomains)
onMounted(() => {
  loadSavedRegisterForm()
  loadRegisterLogs()
  loadRegisterStats()
  logsTimer = window.setInterval(loadRegisterLogs, 3000)
  statsTimer = window.setInterval(loadRegisterStats, 3000)
})
onUnmounted(() => {
  if (logsTimer) {
    window.clearInterval(logsTimer)
    logsTimer = null
  }
  if (statsTimer) {
    window.clearInterval(statsTimer)
    statsTimer = null
  }
})
watch(() => props.runningTask?.task_id, (newId, oldId) => {
  if (oldId && !newId) {
    reloadRegisterDomains()
    loadRegisterLogs()
    loadRegisterStats()
  }
})

function fmtLogTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function fmtTaskTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function logLevelClass(level) {
  const value = String(level || '').toUpperCase()
  if (value === 'ERROR') return 'text-red-400'
  if (value === 'WARNING') return 'text-amber-300'
  if (value === 'INFO') return 'text-sky-400'
  return 'text-gray-400'
}
</script>
