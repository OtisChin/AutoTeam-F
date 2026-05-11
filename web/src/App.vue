<template>
  <!-- 初始配置页 -->
  <SetupPage v-if="needSetup" @configured="onSetupDone" />

  <!-- 登录页 -->
  <div v-else-if="!authenticated" class="min-h-screen flex items-center justify-center">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-8 w-full max-w-sm">
      <h1 class="text-xl font-bold text-white text-center mb-2">AutoPro</h1>
      <p class="text-sm text-gray-400 text-center mb-6">请输入 API Key 登录</p>
      <div v-if="authError" class="mb-4 px-4 py-3 rounded-lg text-sm bg-red-500/10 text-red-400 border border-red-500/20">
        {{ authError }}
      </div>
      <input
        v-model.trim="inputKey"
        type="password"
        placeholder="API Key"
        @keyup.enter="doLogin"
        class="w-full px-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 mb-4"
      />
      <button @click="doLogin" :disabled="!inputKey || authLoading"
        class="w-full px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition disabled:opacity-50">
        {{ authLoading ? '验证中...' : '登录' }}
      </button>
    </div>
  </div>

  <!-- 主面板 -->
  <div v-else class="flex min-h-screen">
    <!-- 侧边栏 -->
    <Sidebar :active="currentPage" :loading="loading" :auth-required="authRequired"
      @navigate="navigateTo" @refresh="refresh" @logout="doLogout" />

    <!-- 主内容区 -->
    <div class="flex-1 p-4 md:p-6 overflow-y-auto pb-20 md:pb-6">
      <!-- 页面内容 -->
      <Dashboard v-if="currentPage === 'dashboard'"
        :status="status" :loading="loading" :running-task="busyTask" :admin-status="adminStatus"
        @task-started="onTaskStarted" @refresh="refresh" />

<RegisterAccountPage v-else-if="currentPage === 'register'"
        :running-task="registerRunningTask" :admin-status="adminStatus"
        @task-started="onTaskStarted" @refresh="refresh" />

      <BindCardPool v-else-if="currentPage === 'cardpool'" />

      <BindCard v-else-if="currentPage === 'bindcard'" key="bindcard" @refresh="refresh" />

      <BindCard v-else-if="currentPage === 'gopay'" key="gopay" initial-tab="gopay" standalone @refresh="refresh" />

      <CpaToSub2ApiPage v-else-if="currentPage === 'cpa2sub'" />

      <OAuthPage v-else-if="currentPage === 'oauth'"
        :manual-account-status="manualAccountStatus" @refresh="refresh" @progress="onAdminProgress" />

      <TaskHistoryPage v-else-if="currentPage === 'tasks'"
        :tasks="tasks" />

      <LogViewer v-else-if="currentPage === 'logs'" />

      <Settings v-else-if="currentPage === 'settings'"
        :admin-status="adminStatus" :codex-status="codexStatus"
        @refresh="refresh" @admin-progress="onAdminProgress" />
    </div>

    <div
      v-if="busyTasks.length"
      class="fixed top-4 right-4 z-50 w-[min(380px,calc(100vw-2rem))] max-h-[calc(100vh-2rem)] overflow-y-auto space-y-3"
    >
      <div
        v-for="task in busyTasks"
        :key="taskNoticeKey(task)"
        class="rounded-lg border border-yellow-400/30 bg-gray-950/95 shadow-2xl shadow-black/40 backdrop-blur"
      >
        <div class="px-4 py-3">
        <div class="flex items-start gap-3">
          <span class="mt-1 animate-spin inline-block w-4 h-4 shrink-0 border-2 border-yellow-300 border-t-transparent rounded-full"></span>
          <div class="min-w-0 flex-1">
            <div class="flex items-center justify-between gap-3">
              <div class="text-sm font-semibold text-white truncate">{{ taskNoticeTitle(task) }}</div>
              <div class="text-xs font-mono text-yellow-200 shrink-0">{{ taskProgress(task).text }}</div>
            </div>
            <div class="mt-1 text-xs text-gray-400 truncate">{{ taskNoticeSubtitle(task) }}</div>
            <div class="mt-3 h-1.5 rounded-full bg-gray-800 overflow-hidden">
              <div
                class="h-full rounded-full bg-yellow-300 transition-all duration-300"
                :style="{ width: `${taskProgress(task).percent}%` }"
              ></div>
            </div>
          </div>
        </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { api, setApiKey, clearApiKey } from './api.js'
import SetupPage from './components/SetupPage.vue'
import Sidebar from './components/Sidebar.vue'
import Dashboard from './components/Dashboard.vue'
import RegisterAccountPage from './components/RegisterAccountPage.vue'
import BindCard from './components/BindCard.vue'
import BindCardPool from './components/BindCardPool.vue'
import CpaToSub2ApiPage from './components/CpaToSub2ApiPage.vue'
import TaskHistoryPage from './components/TaskHistoryPage.vue'
import LogViewer from './components/LogViewer.vue'
import OAuthPage from './components/OAuthPage.vue'
import Settings from './components/Settings.vue'

const needSetup = ref(false)
const authenticated = ref(false)
const authRequired = ref(false)
const authLoading = ref(false)
const authError = ref('')
const inputKey = ref('')
const CURRENT_PAGE_KEY = 'autoteam_current_page'
const PAGE_KEYS = new Set(['dashboard', 'register', 'cardpool', 'bindcard', 'gopay', 'cpa2sub', 'oauth', 'tasks', 'logs', 'settings'])
const IDLE_POLL_INTERVAL_MS = 600000
const ACTIVE_POLL_INTERVAL_MS = 3000
const IDLE_POLLING_ENABLED = false
const savedPage = localStorage.getItem(CURRENT_PAGE_KEY)
const currentPage = ref(PAGE_KEYS.has(savedPage) ? savedPage : 'dashboard')

const status = ref(null)
const adminStatus = ref(null)
const codexStatus = ref(null)
const manualAccountStatus = ref(null)
const tasks = ref([])
const loading = ref(false)
const statusRefreshing = ref(false)
const runningTask = ref(null)
const activeTasks = computed(() => (tasks.value || []).filter(task => ['running', 'pending'].includes(String(task?.status || ''))))
const registerRunningTask = computed(() => activeTasks.value.find(task => task?.command === 'register') || null)
const busyTasks = computed(() => {
  const items = []
  if (adminStatus.value?.login_in_progress) {
    items.push({ command: 'admin-login', status: 'running', task_id: 'admin-login' })
  }
  if (codexStatus.value?.in_progress) {
    items.push({ command: 'main-codex-sync', status: 'running', task_id: 'main-codex-sync' })
  }
  if (manualAccountStatus.value?.in_progress) {
    items.push({ command: 'manual-account', status: 'running', task_id: 'manual-account' })
  }
  for (const task of activeTasks.value) {
    items.push(task)
  }
  return items
})
const busyTask = computed(() => busyTasks.value[0] || null)

function taskNoticeKey(task) {
  return task?.task_id || `${task?.command || 'task'}-${task?.created_at || ''}`
}

function taskNoticeTitle(task) {
  const command = String(task?.command || '')
  const label = taskCommandLabel(command)
  const status = taskStatusLabel(task?.status)
  return `${label}${status ? ` · ${status}` : ''}`
}

function taskNoticeSubtitle(task) {
  task = task || {}
  const progress = task.progress || {}
  return progress.message || taskStageLabel(progress.stage) || task.task_id || '后台任务正在执行'
}

let pollTimer = null
let pollIntervalMs = null

function taskCommandLabel(command) {
  const value = String(command || '')
  if (value.startsWith('login:')) return 'OAuth 补登录'
  return {
    'admin-login': '管理员登录',
    'main-codex-sync': '主号 Codex 同步',
    'manual-account': 'OAuth 登录',
    register: '注册账号',
    'bind-card': '绑卡任务',
    'gopay-bind': 'GoPay 绑定',
    'login-batch': '批量补登录',
    'refresh-quota': '刷新凭证',
    check: '额度检测',
    rotate: '账号轮换',
    replace: '替换账号',
    fill: '补满账号',
    'fill-personal': '生产免费号',
    cleanup: '清理账号',
    'auto-fill': '自动补位',
    'auto-replace': '自动替换',
  }[value] || value || '后台任务'
}

function taskStatusLabel(status) {
  return {
    pending: '等待中',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }[String(status || '')] || ''
}

function taskStageLabel(stage) {
  return {
    gopay_binding: 'GoPay 绑定准备中',
    gopay_auto_register_next: '自动注册并绑定',
    gopay_pending_retry_wait: '等待重试',
    gopay_pending_retry_account: '正在重试账号',
    binding: '绑卡中',
    completed: '流程完成',
    failed: '流程失败',
  }[String(stage || '')] || ''
}

function taskProgress(task) {
  const progress = task?.progress || {}
  const params = task?.params || {}
  const result = task?.result || {}
  const total = Number(
    progress.total ||
    progress.account_count ||
    result.total ||
    params.auto_register_count ||
    params.count ||
    params.account_count ||
    params.account_emails_count ||
    params.emails_count ||
    (Array.isArray(params.account_emails) ? params.account_emails.length : 0) ||
    0
  )
  const done = Number(
    progress.current ||
    progress.processed ||
    progress.successful + progress.failed ||
    progress.ok + progress.failed ||
    result.successful ||
    0
  )
  if (total > 0) {
    const current = Math.max(0, Math.min(total, Number.isFinite(done) ? done : 0))
    return {
      text: `${current}/${total}`,
      percent: Math.max(4, Math.round((current / total) * 100)),
    }
  }
  if (task?.status === 'pending') return { text: '等待中', percent: 8 }
  return { text: '进行中', percent: 35 }
}

function withTimeout(promise, ms, label) {
  let timer = null
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      const err = new Error(`${label || 'request'} timeout`)
      err.timeout = true
      reject(err)
    }, ms)
  })
  return Promise.race([promise, timeout]).finally(() => {
    if (timer) clearTimeout(timer)
  })
}

function buildDashboardStatusFromAccounts(accounts) {
  const rows = Array.isArray(accounts) ? accounts : []
  const summary = {
    active: 0,
    standby: 0,
    exhausted: 0,
    pending: 0,
    auth_invalid: 0,
    orphan: 0,
    fail: 0,
    free: 0,
    team: 0,
    plus: 0,
    pro: 0,
    total: rows.length,
  }
  for (const acc of rows) {
    const statusKey = String(acc?.status || 'pending').toLowerCase()
    if (Object.prototype.hasOwnProperty.call(summary, statusKey)) {
      summary[statusKey] += 1
    }
    const typeKey = String(acc?.account_type || acc?.seat_type || 'free').toLowerCase()
    if (['free', 'team', 'plus', 'pro'].includes(typeKey)) {
      summary[typeKey] += 1
    }
  }
  return {
    accounts: rows,
    summary,
    quota_cache: {},
    fallback: true,
  }
}

async function loadDashboardStatus() {
  const accounts = await withTimeout(api.getAccounts(), 5000, 'accounts')
  return buildDashboardStatusFromAccounts(accounts)
}

async function refreshFullStatusInBackground() {
  if (statusRefreshing.value) return
  statusRefreshing.value = true
  try {
    const fullStatus = await withTimeout(api.getStatus(), 30000, 'status')
    status.value = fullStatus
  } catch (e) {
    if (e.status === 401) {
      authenticated.value = false
      return
    }
    console.warn('完整状态刷新失败，保留账号列表数据:', e)
  } finally {
    statusRefreshing.value = false
  }
}

async function loadOrFallback(promise, fallbackValue, label) {
  try {
    return await withTimeout(promise, 10000, label)
  } catch (e) {
    if (e.status === 401) throw e
    console.warn(`${label} 刷新失败，保留旧值:`, e)
    return fallbackValue
  }
}

async function checkAuth() {
  try {
    const result = await api.checkAuth()
    authenticated.value = result.authenticated
    authRequired.value = result.auth_required
    return result.authenticated
  } catch (e) {
    if (e.status === 401) {
      authenticated.value = false
      authRequired.value = true
      return false
    }
    authenticated.value = true
    authRequired.value = false
    return true
  }
}

async function doLogin() {
  authError.value = ''
  authLoading.value = true
  try {
    setApiKey(inputKey.value)
    const ok = await checkAuth()
    if (!ok) {
      clearApiKey()
      authError.value = 'API Key 无效'
    } else {
      inputKey.value = ''
      await refresh()
      syncPollingWithTasks()
    }
  } catch (e) {
    clearApiKey()
    authError.value = e.message
  } finally {
    authLoading.value = false
  }
}

function doLogout() {
  clearApiKey()
  authenticated.value = false
  stopPolling()
}

function navigateTo(page) {
  currentPage.value = PAGE_KEYS.has(page) ? page : 'dashboard'
  try {
    localStorage.setItem(CURRENT_PAGE_KEY, currentPage.value)
  } catch {}
}

async function refresh() {
  loading.value = true
  try {
    const [s, t, admin, codex, manualAccount] = await Promise.all([
      loadDashboardStatus(),
      loadOrFallback(api.getTasks(), tasks.value || [], 'tasks'),
      loadOrFallback(api.getAdminStatus(), adminStatus.value || null, 'admin-status'),
      loadOrFallback(api.getMainCodexStatus(), codexStatus.value || null, 'main-codex-status'),
      loadOrFallback(api.getManualAccountStatus(), manualAccountStatus.value || null, 'manual-account-status'),
    ])
    status.value = s
    tasks.value = t
    adminStatus.value = admin
    codexStatus.value = codex
    manualAccountStatus.value = manualAccount
    runningTask.value = t.find(task =>
      (task.status === 'running' || task.status === 'pending') && task.command === 'refresh-quota'
    ) || t.find(task =>
      (task.status === 'running' || task.status === 'pending') && task.exclusive !== false
    ) || null
    refreshFullStatusInBackground()
    syncPollingWithTasks()
  } catch (e) {
    if (e.status === 401) {
      authenticated.value = false
      return
    }
    console.error('刷新失败:', e)
  } finally {
    loading.value = false
  }
}

function onTaskStarted() {
  startPolling(ACTIVE_POLL_INTERVAL_MS)
  refresh()
}

function onAdminProgress() {
  startPolling(ACTIVE_POLL_INTERVAL_MS)
  refresh()
}

function startPolling(interval = IDLE_POLL_INTERVAL_MS) {
  if (pollTimer && pollIntervalMs === interval) {
    return
  }
  stopPolling()
  if (interval >= IDLE_POLL_INTERVAL_MS && !IDLE_POLLING_ENABLED && !busyTask.value) {
    return
  }
  pollIntervalMs = interval
  pollTimer = setInterval(async () => {
    await refresh()
  }, interval)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  pollIntervalMs = null
}

function syncPollingWithTasks() {
  if (busyTasks.value.length) {
    startPolling(ACTIVE_POLL_INTERVAL_MS)
  } else {
    startPolling(IDLE_POLL_INTERVAL_MS)
  }
}

async function checkSetup() {
  try {
    const result = await api.getSetupStatus()
    return result.configured
  } catch {
    return true // 接口不存在说明是旧版本，跳过
  }
}

function onSetupDone() {
  needSetup.value = false
  checkAuth().then(async ok => {
    if (ok) {
      await refresh()
      syncPollingWithTasks()
    }
  })
}

onMounted(async () => {
  const setupOk = await checkSetup()
  if (!setupOk) {
    needSetup.value = true
    return
  }
  const ok = await checkAuth()
  if (ok) {
    await refresh()
    syncPollingWithTasks()
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>
