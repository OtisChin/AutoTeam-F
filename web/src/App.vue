<template>
  <!-- 初始配置页 -->
  <SetupPage v-if="needSetup" @configured="onSetupDone" />

  <!-- 登录页 -->
  <main v-else-if="!authenticated" class="auth-shell">
    <section class="auth-card">
      <div class="mb-7 flex items-center gap-4">
        <div class="nav-mark">AT</div>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight text-white">AutoToken</h1>
          <p class="mt-1 text-sm text-gray-400">运营控制台访问验证</p>
        </div>
      </div>
      <div v-if="authError" class="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
        {{ authError }}
      </div>
      <label class="block">
        <span class="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-gray-500">API Key</span>
        <input
          v-model.trim="inputKey"
          type="password"
          placeholder="输入控制台 API Key"
          @keyup.enter="doLogin"
          class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 text-sm text-white transition placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
        />
      </label>
      <button
        @click="doLogin"
        :disabled="!inputKey || authLoading"
        class="mt-5 w-full rounded-xl bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">
        {{ authLoading ? '验证中...' : '进入控制台' }}
      </button>
    </section>
  </main>

  <!-- 主面板 -->
  <div v-else class="app-shell">
    <!-- 侧边栏 -->
    <Sidebar :active="currentPage" :loading="loading" :auth-required="authRequired"
      @navigate="navigateTo" @refresh="refresh" @logout="doLogout" />

    <!-- 主内容区 -->
    <main class="workspace-shell">
      <div class="workspace-chrome">
        <div class="workspace-main">
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

          <section v-else-if="currentPage === 'paypal'" class="rounded-xl border border-gray-800 bg-gray-900 p-5 shadow-2xl">
            <h2 class="text-xl font-bold text-white">PayPal</h2>
            <p class="mt-2 text-sm text-gray-400">功能待定</p>
          </section>

          <IdealLinkPage v-else-if="currentPage === 'ideal'" />

          <BrazilPixPage v-else-if="currentPage === 'brazilPix'" />


          <OAuthPhonePoolPage v-else-if="currentPage === 'oauthPhones'" />

          <OAuthPhoneRecordsPage v-else-if="currentPage === 'oauthPhoneRecords'" />

          <MailAccountsPage v-else-if="currentPage === 'mailAccounts'" @task-started="onTaskStarted" />

          <TradeManagerPage v-else-if="currentPage === 'trade'" />

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
      </div>
    </main>

    <div
      v-if="busyTasks.length"
      ref="taskPanelRef"
      class="fixed z-50 w-[min(380px,calc(100vw-2rem))]"
      :style="taskPanelStyle"
    >
      <div class="mb-2 flex justify-end">
        <button
          type="button"
          title="拖动任务进度；双击恢复右上角"
          class="touch-none rounded-md border border-gray-700 bg-gray-950/95 px-2 py-1 font-mono text-xs leading-none text-gray-400 shadow-lg shadow-black/20 transition hover:border-yellow-400/40 hover:text-yellow-200"
          @pointerdown="startTaskPanelDrag"
          @dblclick="resetTaskPanelPosition"
        >
          ⋮⋮
        </button>
      </div>
      <div class="max-h-[calc(100vh-4rem)] space-y-3 overflow-y-auto">
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
import IdealLinkPage from './components/IdealLinkPage.vue'
import BrazilPixPage from './components/BrazilPixPage.vue'
import OAuthPhonePoolPage from './components/OAuthPhonePoolPage.vue'
import OAuthPhoneRecordsPage from './components/OAuthPhoneRecordsPage.vue'
import MailAccountsPage from './components/MailAccountsPage.vue'
import TradeManagerPage from './components/TradeManagerPage.vue'
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
const CURRENT_PAGE_KEY = 'autotoken_current_page'
const PAGE_KEYS = new Set(['dashboard', 'register', 'cardpool', 'bindcard', 'gopay', 'paypal', 'ideal', 'brazilPix', 'oauthPhones', 'oauthPhoneRecords', 'mailAccounts', 'trade', 'cpa2sub', 'oauth', 'tasks', 'logs', 'settings'])
const IDLE_POLL_INTERVAL_MS = 600000
const ACTIVE_POLL_INTERVAL_MS = 3000
const IDLE_POLLING_ENABLED = false
const TASK_PANEL_POSITION_KEY = 'autotoken_task_panel_position'
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
const taskPanelRef = ref(null)
const taskPanelPosition = ref(loadTaskPanelPosition())
const taskPanelDrag = ref(null)
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
const taskPanelStyle = computed(() => {
  const position = taskPanelPosition.value
  if (!position) return { top: '1rem', right: '1rem' }
  return {
    left: `${position.x}px`,
    top: `${position.y}px`,
  }
})

function loadTaskPanelPosition() {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(TASK_PANEL_POSITION_KEY) || 'null')
    if (Number.isFinite(parsed?.x) && Number.isFinite(parsed?.y)) {
      return { x: parsed.x, y: parsed.y }
    }
  } catch {}
  return null
}

function persistTaskPanelPosition(position) {
  try {
    if (position) {
      window.localStorage.setItem(TASK_PANEL_POSITION_KEY, JSON.stringify(position))
    } else {
      window.localStorage.removeItem(TASK_PANEL_POSITION_KEY)
    }
  } catch {}
}

function clampTaskPanelPosition(x, y) {
  const el = taskPanelRef.value
  const width = el?.offsetWidth || 380
  const height = el?.offsetHeight || 120
  const margin = 8
  const maxX = Math.max(margin, window.innerWidth - width - margin)
  const maxY = Math.max(margin, window.innerHeight - height - margin)
  return {
    x: Math.min(Math.max(margin, x), maxX),
    y: Math.min(Math.max(margin, y), maxY),
  }
}

function startTaskPanelDrag(event) {
  if (typeof event.button === 'number' && event.button !== 0) return
  const rect = taskPanelRef.value?.getBoundingClientRect()
  if (!rect) return
  taskPanelDrag.value = {
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
  }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', moveTaskPanel)
  window.addEventListener('pointerup', stopTaskPanelDrag, { once: true })
  event.preventDefault()
}

function moveTaskPanel(event) {
  const drag = taskPanelDrag.value
  if (!drag) return
  taskPanelPosition.value = clampTaskPanelPosition(event.clientX - drag.offsetX, event.clientY - drag.offsetY)
}

function stopTaskPanelDrag() {
  if (taskPanelPosition.value) persistTaskPanelPosition(taskPanelPosition.value)
  taskPanelDrag.value = null
  window.removeEventListener('pointermove', moveTaskPanel)
}

function resetTaskPanelPosition() {
  taskPanelPosition.value = null
  persistTaskPanelPosition(null)
}

function keepTaskPanelInViewport() {
  if (!taskPanelPosition.value) return
  taskPanelPosition.value = clampTaskPanelPosition(taskPanelPosition.value.x, taskPanelPosition.value.y)
  persistTaskPanelPosition(taskPanelPosition.value)
}

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
    gopay_wallet_auto_signup_started: '自动注册 GoPay 钱包',
    gopay_wallet_auto_signup_rate_limited: 'GoPay 注册触发限流，任务中止',
    gopay_wallet_auto_signup_network_error: 'GoPay 注册网络中断，任务中止',
    gopay_wallet_auto_signup_done: 'GoPay 钱包已就绪',
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
  const rows = (Array.isArray(accounts) ? accounts : []).map(acc => {
    const status = String(acc?.status || '').trim().toLowerCase()
    const normalized = ['personal', 'plus'].includes(status) ? 'active' : status
    const lastBindProvider = String(acc?.last_bind_provider || '').trim().toLowerCase()
    return {
      ...acc,
      raw_status: acc?.raw_status || status,
      status: normalized,
      last_bind_provider: lastBindProvider,
    }
  })
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
  const tasksPromise = loadOrFallback(api.getTasks(), tasks.value || [], 'tasks')
  const adminPromise = loadOrFallback(api.getAdminStatus(), adminStatus.value || null, 'admin-status')
  const codexPromise = loadOrFallback(api.getMainCodexStatus(), codexStatus.value || null, 'main-codex-status')
  const manualAccountPromise = loadOrFallback(api.getManualAccountStatus(), manualAccountStatus.value || null, 'manual-account-status')
  const auxiliaryPromise = Promise.all([tasksPromise, adminPromise, codexPromise, manualAccountPromise])
    .then(([t, admin, codex, manualAccount]) => {
      tasks.value = t
      adminStatus.value = admin
      codexStatus.value = codex
      manualAccountStatus.value = manualAccount
      runningTask.value = t.find(task =>
        (task.status === 'running' || task.status === 'pending') && task.command === 'refresh-quota'
      ) || t.find(task =>
        (task.status === 'running' || task.status === 'pending') && task.exclusive !== false
      ) || null
      syncPollingWithTasks()
    })
    .catch(e => {
      if (e.status === 401) {
        authenticated.value = false
      } else {
        console.warn('辅助状态刷新失败:', e)
      }
    })
  try {
    status.value = await loadDashboardStatus()
  } catch (e) {
    if (e.status === 401) {
      authenticated.value = false
      return
    }
    console.error('刷新失败:', e)
  } finally {
    loading.value = false
  }

  void auxiliaryPromise

  refreshFullStatusInBackground()
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
  window.addEventListener('resize', keepTaskPanelInViewport)
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
  window.removeEventListener('resize', keepTaskPanelInViewport)
  window.removeEventListener('pointermove', moveTaskPanel)
  stopPolling()
})
</script>
