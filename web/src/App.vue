<template>
  <!-- 初始配置页 -->
  <SetupPage v-if="needSetup" @configured="onSetupDone" />

  <!-- 登录页 -->
  <main v-else-if="!authenticated" class="auth-shell">
    <div class="auth-theme-control"><ThemeSwitcher /></div>
    <section class="auth-card">
      <div class="mb-7 flex items-center gap-4">
        <div class="nav-mark">AT</div>
        <div>
          <h1 class="text-2xl font-semibold tracking-tight text-white">AutoToken</h1>
          <p class="mt-1 text-sm text-gray-400">运营控制台访问验证</p>
        </div>
      </div>
      <div v-if="authError || startupError" class="mb-4 rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300" role="alert">
        {{ authError || startupError }}
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
      <button
        v-if="startupError"
        type="button"
        :disabled="authLoading"
        class="mt-3 w-full rounded-xl border border-gray-700 bg-gray-900 px-4 py-3 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:cursor-wait disabled:opacity-50"
        @click="initializeApp"
      >
        {{ authLoading ? '正在重连...' : '重新连接' }}
      </button>
    </section>
  </main>

  <!-- 主面板 -->
  <div v-else class="app-shell">
    <!-- 侧边栏 -->
    <Sidebar :active="currentPage" :loading="loading" :auth-required="authRequired"
      @navigate="navigateTo" @prefetch="prefetchPage" @refresh="refresh" @logout="doLogout" />

    <!-- 主内容区 -->
    <main class="workspace-shell">
      <div class="workspace-chrome">
        <header class="workspace-toolbar">
          <div class="window-controls" aria-hidden="true">
            <span class="window-control window-control-close"></span>
            <span class="window-control window-control-minimize"></span>
            <span class="window-control window-control-expand"></span>
          </div>
          <div class="workspace-title-group">
            <span class="workspace-eyebrow">{{ currentPageMeta.group }}</span>
            <h2 class="workspace-title">{{ currentPageMeta.label }}</h2>
            <span class="workspace-description">{{ currentPageMeta.description }}</span>
          </div>
          <div class="workspace-toolbar-actions">
            <ThemeSwitcher />
            <span class="workspace-status" :class="busyTasks.length ? 'workspace-status-busy' : ''" aria-live="polite">
              <span class="workspace-status-dot" aria-hidden="true"></span>
              {{ busyTasks.length ? `${busyTasks.length} 个任务运行中` : '系统就绪' }}
            </span>
            <button
              type="button"
              class="toolbar-button"
              :disabled="loading"
              :aria-label="loading ? '正在刷新数据' : '刷新数据'"
              @click="refresh"
            >
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" :class="loading ? 'is-spinning' : ''">
                <path d="M20 7v5h-5M4 17v-5h5M6.1 8A7 7 0 0 1 18 6l2 6M17.9 16A7 7 0 0 1 6 18l-2-6" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" />
              </svg>
            </button>
          </div>
        </header>
        <div class="workspace-main">
          <!-- 页面内容 -->
          <Dashboard v-if="currentPage === 'dashboard'"
            :status="status" :loading="loading" :running-task="busyTask"
            :accounts-error="accountsError" :last-successful-at="lastSuccessfulAt"
            :refresh-quota-result-task="lastDashboardRefreshQuotaTask"
            :admin-status="adminStatus"
            @task-started="onTaskStarted" @refresh="refresh" @retry-accounts="refreshDashboardAccounts" />

          <RegisterAccountPage v-else-if="currentPage === 'register'"
            :running-task="registerRunningTask" :admin-status="adminStatus"
            @task-started="onTaskStarted" @refresh="refresh" />

          <BindCardPool v-else-if="currentPage === 'cardpool'" />

          <BindCard v-else-if="currentPage === 'bindcard'" key="bindcard" @refresh="refresh" />

          <BindCard v-else-if="currentPage === 'gopay'" key="gopay" initial-tab="gopay" standalone @refresh="refresh" />

          <UsPaypalPage v-else-if="currentPage === 'paypal'" />

          <IdealLinkPage v-else-if="currentPage === 'ideal'" />

          <BrazilPixPage v-else-if="currentPage === 'brazilPix'" />

          <IndiaUpiPage v-else-if="currentPage === 'indiaUpi'" />

          <KakaoPayPage v-else-if="currentPage === 'kakaoPay'" />

          <MomoPage v-else-if="currentPage === 'momoVn'" />

          <GCashPhPage v-else-if="currentPage === 'gcashPh'" />

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
      class="task-panel fixed z-50 w-[min(380px,calc(100vw-2rem))]"
      :class="taskPanelDrag ? 'task-panel-dragging' : ''"
      :style="taskPanelStyle"
      aria-live="polite"
      aria-label="后台任务进度"
    >
      <div class="mb-2 flex justify-end">
        <button
          type="button"
          title="拖动任务进度；双击恢复右上角"
          class="task-panel-handle touch-none rounded-md border border-gray-700 bg-gray-950/95 px-2 py-1 font-mono text-xs leading-none text-gray-400 shadow-lg shadow-black/20 transition hover:border-yellow-400/40 hover:text-yellow-200"
          @pointerdown="startTaskPanelDrag"
          @lostpointercapture="stopTaskPanelDrag"
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
                class="task-progress-fill h-full rounded-full bg-yellow-300"
                :style="{ transform: `scaleX(${taskProgress(task).percent / 100})` }"
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
import { computed, defineAsyncComponent, h, shallowRef, ref, onMounted, onUnmounted, nextTick } from 'vue'
import { ACCOUNT_DATA_NOT_MODIFIED, api, getApiKey, setApiKey, clearApiKey, invalidateApiKeyMemory } from './api.js'
import { buildDashboardStatusFromAccounts } from './accountData.js'
import {
  createAccountLoadAbortError,
  createAccountLoadLifecycle,
  isAccountLoadAbortError,
  shouldLoadDashboardAccounts,
} from './accountLoadPolicy.js'
import { NAV_ITEMS_BY_KEY, PAGE_KEYS } from './navigation.js'
import { createRafThrottle, createSingleFlight } from './runtimePerformance.js'
import { calculateTaskProgress } from './taskProgress.js'
import { clearStorageSession, prepareStorageSession, SESSION_OWNER_KEY } from './sessionStorageScope.js'
import SetupPage from './components/SetupPage.vue'
import Sidebar from './components/Sidebar.vue'
import PageLoading from './components/PageLoading.vue'
import PageLoadError from './components/PageLoadError.vue'
import ThemeSwitcher from './components/ThemeSwitcher.vue'

const pageLoaders = {
  dashboard: () => import('./components/Dashboard.vue'),
  register: () => import('./components/RegisterAccountPage.vue'),
  cardpool: () => import('./components/BindCardPool.vue'),
  bindcard: () => import('./components/BindCard.vue'),
  gopay: () => import('./components/BindCard.vue'),
  paypal: () => import('./components/UsPaypalPage.vue'),
  ideal: () => import('./components/IdealLinkPage.vue'),
  brazilPix: () => import('./components/BrazilPixPage.vue'),
  indiaUpi: () => import('./components/IndiaUpiPage.vue'),
  kakaoPay: () => import('./components/KakaoPayPage.vue'),
  momoVn: () => import('./components/MomoPage.vue'),
  gcashPh: () => import('./components/GCashPhPage.vue'),
  oauthPhones: () => import('./components/OAuthPhonePoolPage.vue'),
  oauthPhoneRecords: () => import('./components/OAuthPhoneRecordsPage.vue'),
  mailAccounts: () => import('./components/MailAccountsPage.vue'),
  trade: () => import('./components/TradeManagerPage.vue'),
  cpa2sub: () => import('./components/CpaToSub2ApiPage.vue'),
  oauth: () => import('./components/OAuthPage.vue'),
  tasks: () => import('./components/TaskHistoryPage.vue'),
  logs: () => import('./components/LogViewer.vue'),
  settings: () => import('./components/Settings.vue'),
}

function asyncPage(key) {
  return defineAsyncComponent({
    loader: pageLoaders[key],
    loadingComponent: PageLoading,
    errorComponent: {
      props: { error: { type: Error, default: null } },
      setup(props) {
        return () => h(PageLoadError, {
          error: props.error,
          onRetry: () => retryPageLoad(key),
        })
      },
    },
    delay: 120,
    timeout: 30_000,
    onError(_error, retry, fail, attempts) {
      if (attempts < 2 && navigator.onLine) retry()
      else fail()
    },
  })
}

const Dashboard = shallowRef(asyncPage('dashboard'))
const RegisterAccountPage = shallowRef(asyncPage('register'))
const BindCardPool = shallowRef(asyncPage('cardpool'))
const BindCard = shallowRef(asyncPage('bindcard'))
const UsPaypalPage = shallowRef(asyncPage('paypal'))
const IdealLinkPage = shallowRef(asyncPage('ideal'))
const BrazilPixPage = shallowRef(asyncPage('brazilPix'))
const IndiaUpiPage = shallowRef(asyncPage('indiaUpi'))
const KakaoPayPage = shallowRef(asyncPage('kakaoPay'))
const MomoPage = shallowRef(asyncPage('momoVn'))
const GCashPhPage = shallowRef(asyncPage('gcashPh'))
const OAuthPhonePoolPage = shallowRef(asyncPage('oauthPhones'))
const OAuthPhoneRecordsPage = shallowRef(asyncPage('oauthPhoneRecords'))
const MailAccountsPage = shallowRef(asyncPage('mailAccounts'))
const TradeManagerPage = shallowRef(asyncPage('trade'))
const CpaToSub2ApiPage = shallowRef(asyncPage('cpa2sub'))
const OAuthPage = shallowRef(asyncPage('oauth'))
const TaskHistoryPage = shallowRef(asyncPage('tasks'))
const LogViewer = shallowRef(asyncPage('logs'))
const Settings = shallowRef(asyncPage('settings'))

const retryablePages = {
  dashboard: Dashboard,
  register: RegisterAccountPage,
  cardpool: BindCardPool,
  bindcard: BindCard,
  gopay: BindCard,
  paypal: UsPaypalPage,
  ideal: IdealLinkPage,
  brazilPix: BrazilPixPage,
  indiaUpi: IndiaUpiPage,
  kakaoPay: KakaoPayPage,
  momoVn: MomoPage,
  gcashPh: GCashPhPage,
  oauthPhones: OAuthPhonePoolPage,
  oauthPhoneRecords: OAuthPhoneRecordsPage,
  mailAccounts: MailAccountsPage,
  trade: TradeManagerPage,
  cpa2sub: CpaToSub2ApiPage,
  oauth: OAuthPage,
  tasks: TaskHistoryPage,
  logs: LogViewer,
  settings: Settings,
}

function retryPageLoad(key) {
  const target = retryablePages[key]
  if (target) target.value = asyncPage(key)
}

const needSetup = ref(false)
const authenticated = ref(false)
const authRequired = ref(false)
const authLoading = ref(false)
const authError = ref('')
const startupError = ref('')
const inputKey = ref('')
const CURRENT_PAGE_KEY = 'autotoken_current_page'
const IDLE_POLL_INTERVAL_MS = 600000
const ACTIVE_POLL_INTERVAL_MS = 1500
const IDLE_POLLING_ENABLED = false
const TASK_PANEL_POSITION_KEY = 'autotoken_task_panel_position'
const savedPage = (() => {
  try {
    return localStorage.getItem(CURRENT_PAGE_KEY)
  } catch {
    return null
  }
})()
const currentPage = ref(PAGE_KEYS.has(savedPage) ? savedPage : 'dashboard')
const currentPageMeta = computed(() => NAV_ITEMS_BY_KEY[currentPage.value] || NAV_ITEMS_BY_KEY.dashboard)
const status = shallowRef(null)
const accountsError = ref('')
const lastSuccessfulAt = ref(null)
const adminStatus = ref(null)
const codexStatus = ref(null)
const manualAccountStatus = ref(null)
const tasks = ref([])
const loading = ref(false)
const runningTask = ref(null)
const accountLoadLifecycle = createAccountLoadLifecycle({
  load: ({ signal }) => api.getAccounts({
    includeSessionStubs: true,
    view: 'dashboard',
    timeoutMs: 20_000,
    signal,
  }),
  prepare: buildDashboardStatusFromAccounts,
  isNotModified: value => value === ACCOUNT_DATA_NOT_MODIFIED,
  onChange(nextState) {
    status.value = nextState.snapshot
    loading.value = nextState.loading
    accountsError.value = nextState.error
    lastSuccessfulAt.value = nextState.lastSuccessfulAt
  },
})
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
const lastDashboardRefreshQuotaTask = computed(() =>
  (tasks.value || []).find(task => {
    if (task?.command !== 'refresh-quota') return false
    return !['running', 'pending'].includes(String(task?.status || ''))
  }) || null
)
const taskPanelStyle = computed(() => {
  const position = taskPanelPosition.value
  if (!position) return { top: '1rem', right: '1rem' }
  return {
    left: '0',
    top: '0',
    transform: `translate3d(${position.x}px, ${position.y}px, 0)`,
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

function taskPanelBounds() {
  const rect = taskPanelRef.value?.getBoundingClientRect()
  const margin = 8
  return {
    margin,
    maxX: Math.max(margin, window.innerWidth - (rect?.width || 380) - margin),
    maxY: Math.max(margin, window.innerHeight - (rect?.height || 120) - margin),
  }
}

function clampTaskPanelPosition(x, y, bounds = taskPanelBounds()) {
  return {
    x: Math.min(Math.max(bounds.margin, x), bounds.maxX),
    y: Math.min(Math.max(bounds.margin, y), bounds.maxY),
  }
}

function startTaskPanelDrag(event) {
  if (typeof event.button === 'number' && event.button !== 0) return
  const rect = taskPanelRef.value?.getBoundingClientRect()
  if (!rect) return
  taskPanelDrag.value = {
    offsetX: event.clientX - rect.left,
    offsetY: event.clientY - rect.top,
    bounds: taskPanelBounds(),
  }
  event.currentTarget?.setPointerCapture?.(event.pointerId)
  window.addEventListener('pointermove', moveTaskPanel)
  window.addEventListener('pointerup', stopTaskPanelDrag, { once: true })
  window.addEventListener('pointercancel', stopTaskPanelDrag, { once: true })
  event.preventDefault()
}

const applyTaskPanelMove = createRafThrottle((x, y, bounds) => {
  taskPanelPosition.value = clampTaskPanelPosition(x, y, bounds)
})

function moveTaskPanel(event) {
  const drag = taskPanelDrag.value
  if (!drag) return
  applyTaskPanelMove(event.clientX - drag.offsetX, event.clientY - drag.offsetY, drag.bounds)
}

function stopTaskPanelDrag() {
  applyTaskPanelMove.flush()
  if (taskPanelPosition.value) persistTaskPanelPosition(taskPanelPosition.value)
  taskPanelDrag.value = null
  window.removeEventListener('pointermove', moveTaskPanel)
  window.removeEventListener('pointerup', stopTaskPanelDrag)
  window.removeEventListener('pointercancel', stopTaskPanelDrag)
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
let pollingEpoch = null
let authEpoch = 0

function resetSessionState() {
  accountLoadLifecycle.reset()
  tasks.value = []
  adminStatus.value = null
  codexStatus.value = null
  manualAccountStatus.value = null
  runningTask.value = null
}

function advanceAuthEpoch() {
  accountLoadLifecycle.abort(createAccountLoadAbortError('认证会话已变更'))
  authEpoch += 1
  resetSessionState()
  return authEpoch
}

function isCurrentAuthEpoch(epoch) {
  return epoch === authEpoch
}

function taskCommandLabel(command) {
  const value = String(command || '')
  if (value.startsWith('login:')) return 'OAuth授权'
  return {
    'admin-login': '管理员登录',
    'main-codex-sync': '主号 Codex 同步',
    'manual-account': 'OAuth 登录',
    register: '注册账号',
    'bind-card': '绑卡任务',
    'gopay-bind': 'GoPay 绑定',
    'login-batch': '批量OAuth授权/补登录',
    'setup-2fa': '协议设置2FA',
    'refresh-quota': '刷新额度',
    check: '额度检测',
    rotate: '账号轮换',
    replace: '替换账号',
    fill: '补满账号',
    'fill-personal': '免费号生产（已禁用）',
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

const taskProgress = calculateTaskProgress

async function refreshDashboardAccounts(epoch = authEpoch) {
  if (!isCurrentAuthEpoch(epoch) || !shouldLoadDashboardAccounts(currentPage.value)) return
  try {
    const nextStatus = await accountLoadLifecycle.load(epoch)
    if (nextStatus === undefined || !isCurrentAuthEpoch(epoch)) return
  } catch (error) {
    if (!isCurrentAuthEpoch(epoch) || isAccountLoadAbortError(error)) return
    if (error?.status === 401) {
      authenticated.value = false
      stopPolling()
      return
    }
    console.warn('账号池刷新失败，保留旧值:', error)
  }
}

async function refreshAuxiliaryState(epoch = authEpoch) {
  if (!isCurrentAuthEpoch(epoch)) return
  try {
    const [t, admin, codex, manualAccount] = await Promise.all([
      loadOrFallback(api.getTasks(false, { timeoutMs: 10000 }), tasks.value || [], 'tasks'),
      loadOrFallback(api.getAdminStatus({ timeoutMs: 10000 }), adminStatus.value || null, 'admin-status'),
      loadOrFallback(api.getMainCodexStatus({ timeoutMs: 10000 }), codexStatus.value || null, 'main-codex-status'),
      loadOrFallback(api.getManualAccountStatus({ timeoutMs: 10000 }), manualAccountStatus.value || null, 'manual-account-status'),
    ])
    if (!isCurrentAuthEpoch(epoch)) return
    tasks.value = t
    adminStatus.value = admin
    codexStatus.value = codex
    manualAccountStatus.value = manualAccount
    runningTask.value = t.find(task =>
      (task.status === 'running' || task.status === 'pending') && task.command === 'refresh-quota'
    ) || t.find(task =>
      (task.status === 'running' || task.status === 'pending') && task.exclusive !== false
    ) || null
    syncPollingWithTasks(epoch)
  } catch (e) {
    if (!isCurrentAuthEpoch(epoch)) return
    if (e.status === 401) {
      authenticated.value = false
      stopPolling()
    } else {
      console.warn('辅助状态刷新失败:', e)
    }
  }
}

const refreshAuxiliaryStateOnce = createSingleFlight(refreshAuxiliaryState, { key: epoch => epoch })

async function loadOrFallback(promise, fallbackValue, label) {
  try {
    return await promise
  } catch (e) {
    if (e.status === 401) throw e
    console.warn(`${label} 刷新失败，保留旧值:`, e)
    return fallbackValue
  }
}

async function checkAuth(epoch = authEpoch, apiKey, commit = true) {
  try {
    const result = await api.checkAuth(apiKey)
    if (!isCurrentAuthEpoch(epoch)) return commit ? false : null
    if (!commit) return result
    authenticated.value = result.authenticated
    authRequired.value = result.auth_required
    startupError.value = ''
    return result.authenticated
  } catch (e) {
    if (!isCurrentAuthEpoch(epoch)) return false
    if (e.status === 401) {
      if (!commit) return { authenticated: false, auth_required: true }
      authenticated.value = false
      authRequired.value = true
      startupError.value = ''
      return false
    }
    startupError.value = e?.timeout
      ? '连接服务超时，请检查后端状态后重试'
      : '暂时无法连接服务，请稍后重试'
    throw e
  }
}

async function doLogin() {
  if (authLoading.value) return
  const submittedKey = String(inputKey.value || '')
  if (!submittedKey) return
  authError.value = ''
  startupError.value = ''
  authLoading.value = true
  const loginEpoch = advanceAuthEpoch()
  stopPolling()
  try {
    const authProbe = await checkAuth(loginEpoch, submittedKey, false)
    if (!isCurrentAuthEpoch(loginEpoch)) return
    if (!authProbe?.authenticated) {
      if (getApiKey() === submittedKey) clearApiKey()
      authError.value = 'API Key 无效'
      return
    }
    const session = await prepareStorageSession(submittedKey, { rotate: true })
    if (!isCurrentAuthEpoch(loginEpoch)) return
    if (!session?.owner) {
      authenticated.value = false
      authError.value = '浏览器存储不可用，请允许此站点使用本地存储后重试'
      return
    }
    setApiKey(submittedKey)
    authenticated.value = true
    authRequired.value = Boolean(authProbe.auth_required)
    startupError.value = ''
    inputKey.value = ''
    await refresh()
    if (!isCurrentAuthEpoch(loginEpoch) || !authenticated.value) return
    syncPollingWithTasks()
  } catch (e) {
    if (!isCurrentAuthEpoch(loginEpoch)) return
    startupError.value = ''
    authError.value = e?.timeout
      ? '连接服务超时，请检查后端状态后重试'
      : '暂时无法连接服务，请稍后重试'
  } finally {
    if (isCurrentAuthEpoch(loginEpoch)) authLoading.value = false
  }
}

async function doLogout() {
  advanceAuthEpoch()
  clearApiKey()
  authenticated.value = false
  stopPolling()
  await nextTick()
  clearStorageSession()
}

function navigateTo(page) {
  const previousPage = currentPage.value
  const nextPage = PAGE_KEYS.has(page) ? page : 'dashboard'
  currentPage.value = nextPage
  try {
    localStorage.setItem(CURRENT_PAGE_KEY, currentPage.value)
  } catch {}
  if (previousPage === 'dashboard' && nextPage !== 'dashboard') {
    accountLoadLifecycle.abort(createAccountLoadAbortError('已离开账号仪表盘'))
  } else if (previousPage !== 'dashboard' && shouldLoadDashboardAccounts(currentPage.value) && authenticated.value) {
    void refreshDashboardAccounts(authEpoch)
  }
}

function prefetchPage(page) {
  if (!PAGE_KEYS.has(page) || !navigator.onLine) return
  void pageLoaders[page]().catch(() => {})
}

async function performRefresh(epoch = authEpoch) {
  if (!isCurrentAuthEpoch(epoch)) return
  const auxiliaryPromise = refreshAuxiliaryStateOnce(epoch)
  if (shouldLoadDashboardAccounts(currentPage.value)) {
    await Promise.all([auxiliaryPromise, refreshDashboardAccounts(epoch)])
  } else {
    await auxiliaryPromise
  }
}

const refreshOnce = createSingleFlight(performRefresh, { key: epoch => epoch })

function refresh() {
  return refreshOnce(authEpoch)
}

async function refreshTaskStateOnly(epoch = authEpoch) {
  if (!isCurrentAuthEpoch(epoch)) return
  const hadBusyTasks = busyTasks.value.length > 0
  await refreshAuxiliaryStateOnce(epoch)
  if (!isCurrentAuthEpoch(epoch)) return
  if (hadBusyTasks && !busyTasks.value.length) {
    if (shouldLoadDashboardAccounts(currentPage.value)) await refreshDashboardAccounts(epoch)
    return
  }
}

const refreshTaskStateOnlyOnce = createSingleFlight(refreshTaskStateOnly, { key: epoch => epoch })

function onTaskStarted() {
  startPolling(ACTIVE_POLL_INTERVAL_MS)
  refresh()
}

function onAdminProgress() {
  startPolling(ACTIVE_POLL_INTERVAL_MS)
  refresh()
}

function startPolling(interval = IDLE_POLL_INTERVAL_MS, epoch = authEpoch) {
  if (!isCurrentAuthEpoch(epoch)) return
  if (pollIntervalMs === interval && pollingEpoch === epoch) return
  stopPolling()
  if (interval >= IDLE_POLL_INTERVAL_MS && !IDLE_POLLING_ENABLED && !busyTask.value) {
    return
  }
  pollIntervalMs = interval
  pollingEpoch = epoch
  scheduleNextPoll(interval, epoch)
}

function scheduleNextPoll(delay = pollIntervalMs, epoch = pollingEpoch) {
  if (!pollIntervalMs || pollingEpoch !== epoch || !isCurrentAuthEpoch(epoch)) return
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = setTimeout(async () => {
    pollTimer = null
    if (pollingEpoch !== epoch || !isCurrentAuthEpoch(epoch)) return
    if (document.visibilityState === 'hidden' || !navigator.onLine) {
      return
    }
    try {
      await refreshTaskStateOnlyOnce(epoch)
    } finally {
      if (pollingEpoch === epoch && isCurrentAuthEpoch(epoch)) {
        scheduleNextPoll(pollIntervalMs, epoch)
      }
    }
  }, delay)
}

function stopPolling() {
  if (pollTimer) {
    clearTimeout(pollTimer)
    pollTimer = null
  }
  pollIntervalMs = null
  pollingEpoch = null
}

function resumePollingWhenAvailable() {
  if (
    document.visibilityState !== 'hidden'
    && navigator.onLine
    && pollIntervalMs
    && pollingEpoch !== null
    && isCurrentAuthEpoch(pollingEpoch)
  ) {
    scheduleNextPoll(0, pollingEpoch)
  }
}

function syncPollingWithTasks(epoch = authEpoch) {
  if (!isCurrentAuthEpoch(epoch)) return
  if (busyTasks.value.length) {
    startPolling(ACTIVE_POLL_INTERVAL_MS, epoch)
  } else {
    startPolling(IDLE_POLL_INTERVAL_MS, epoch)
  }
}

async function checkSetup() {
  try {
    const result = await api.getSetupStatus()
    return result.configured
  } catch (e) {
    if (e.status === 404) return true // 旧版本没有 setup 接口
    throw e
  }
}

async function initializeApp() {
  const epoch = authEpoch
  startupError.value = ''
  authLoading.value = true
  try {
    const session = await prepareStorageSession(getApiKey())
    if (!isCurrentAuthEpoch(epoch)) return
    if (!session?.owner) {
      authenticated.value = false
      startupError.value = '浏览器存储不可用，请允许此站点使用本地存储后重试'
      return
    }
    const setupOk = await checkSetup()
    if (!isCurrentAuthEpoch(epoch)) return
    if (!setupOk) {
      needSetup.value = true
      return
    }
    const ok = await checkAuth(epoch)
    if (!isCurrentAuthEpoch(epoch)) return
    if (ok) {
      await refresh()
      if (isCurrentAuthEpoch(epoch) && authenticated.value) syncPollingWithTasks(epoch)
    }
  } catch (e) {
    if (!isCurrentAuthEpoch(epoch)) return
    authenticated.value = false
    startupError.value = e?.timeout
      ? '连接服务超时，请检查后端状态后重试'
      : '初始化失败，请确认服务已启动后重试'
  } finally {
    if (isCurrentAuthEpoch(epoch)) authLoading.value = false
  }
}

async function onSetupDone(configuredKey = '') {
  if (authLoading.value) return
  const epoch = authEpoch
  authLoading.value = true
  startupError.value = ''
  try {
    const setupKey = String(configuredKey || getApiKey() || '')
    const session = await prepareStorageSession(setupKey, { rotate: true })
    if (!isCurrentAuthEpoch(epoch)) return
    needSetup.value = false
    if (!session?.owner) {
      authenticated.value = false
      startupError.value = '浏览器存储不可用，请允许此站点使用本地存储后重试'
      return
    }
    const ok = await checkAuth(epoch)
    if (!isCurrentAuthEpoch(epoch)) return
    if (ok) {
      await refresh()
      if (isCurrentAuthEpoch(epoch) && authenticated.value) syncPollingWithTasks(epoch)
    }
  } catch (e) {
    if (!isCurrentAuthEpoch(epoch)) return
    startupError.value = e?.timeout
      ? '连接服务超时，请检查后端状态后重试'
      : '暂时无法连接服务，请稍后重试'
  } finally {
    if (isCurrentAuthEpoch(epoch)) authLoading.value = false
  }
}

function handleExternalStorageChange(event) {
  if (event?.key !== 'autotoken_api_key' && event?.key !== SESSION_OWNER_KEY) return
  advanceAuthEpoch()
  invalidateApiKeyMemory()
  authenticated.value = false
  authRequired.value = true
  needSetup.value = false
  authError.value = ''
  startupError.value = '登录状态已在其他标签页变更，请重新进入控制台'
  stopPolling()
}

onMounted(async () => {
  window.addEventListener('resize', keepTaskPanelInViewport)
  window.addEventListener('online', resumePollingWhenAvailable)
  document.addEventListener('visibilitychange', resumePollingWhenAvailable)
  window.addEventListener('storage', handleExternalStorageChange)
  await initializeApp()
})

onUnmounted(() => {
  accountLoadLifecycle.abort(createAccountLoadAbortError('应用已卸载'))
  window.removeEventListener('resize', keepTaskPanelInViewport)
  window.removeEventListener('online', resumePollingWhenAvailable)
  window.removeEventListener('pointermove', moveTaskPanel)
  window.removeEventListener('pointerup', stopTaskPanelDrag)
  window.removeEventListener('pointercancel', stopTaskPanelDrag)
  document.removeEventListener('visibilitychange', resumePollingWhenAvailable)
  window.removeEventListener('storage', handleExternalStorageChange)
  applyTaskPanelMove.cancel()
  stopPolling()
})
</script>
