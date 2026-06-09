<template>
  <div class="space-y-6 xl:h-[calc(100vh-3rem)] xl:min-h-0">
    <div class="grid shrink-0 grid-cols-1 gap-4 xl:grid-cols-[380px_minmax(0,1fr)] xl:items-stretch">
      <div class="flex flex-col justify-center">
        <h2 class="text-xl font-bold text-white">GoPay Pro</h2>
        <p class="mt-1 text-sm text-gray-400">接入稳定主号池，自动循环注册、绑定 Plus 并释放主号。</p>
      </div>
      <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <StatCard label="任务进度" :value="`${selectedTaskMetrics.successful}/${selectedTaskMetrics.total}`" class-name="text-blue-400" />
        <StatCard label="开通成功" :value="selectedTaskMetrics.successful" class-name="text-emerald-400" />
        <StatCard label="待处理" :value="selectedTaskMetrics.pending" class-name="text-violet-300" />
        <StatCard label="开通失败" :value="selectedTaskMetrics.failed" class-name="text-red-400" />
      </div>
    </div>

    <div v-if="message" class="shrink-0 rounded-lg border px-4 py-3 text-sm" :class="messageOk ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/20 bg-rose-500/10 text-rose-300'">
      {{ message }}
    </div>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4 xl:h-[calc(100vh-150px)] xl:min-h-0 xl:flex xl:flex-col xl:overflow-hidden">
      <div class="grid grid-cols-1 gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[480px_minmax(0,1fr)] xl:overflow-hidden">
        <div class="flex flex-col gap-3 xl:min-h-0">
          <div class="shrink-0 rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="flex flex-col gap-3 sm:flex-row">
              <button
                @click="startBatch"
                :disabled="saving || !selectedAccountEmails.length"
                class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50"
              >
                {{ saving ? '提交中...' : '开始批量任务' }}
              </button>
              <button
                v-if="selectedTask && ['pending', 'running'].includes(selectedTask.status)"
                @click="cancelSelectedTask"
                :disabled="saving"
                class="w-full rounded-lg border border-red-500/30 bg-red-600/15 px-4 py-2 text-sm text-red-300 transition hover:bg-red-600/25 disabled:opacity-50"
              >
                {{ saving ? '停止中...' : '取消任务' }}
              </button>
            </div>
          </div>

          <div class="space-y-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-2 xl:pb-2">
            <div>
              <div class="mb-1 flex items-center justify-between gap-3">
                <label class="block text-sm text-gray-400">号池账号</label>
                <div class="text-xs text-gray-500">已选择 {{ selectedAccountEmails.length }} 个账号</div>
              </div>
              <div class="rounded-lg border border-gray-700 bg-gray-800/60 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="min-w-0">
                    <div class="text-xs text-gray-500">当前选择</div>
                    <div class="mt-1 truncate font-mono text-sm text-gray-200">
                      {{ selectedAccountEmails.length ? `${selectedAccountEmails.length} 个 GPT 账号` : '未选择' }}
                    </div>
                  </div>
                  <button
                    type="button"
                    @click="accountPickerOpen = true"
                    :disabled="saving || loadingAccounts"
                    class="shrink-0 rounded-lg border border-blue-500/30 bg-blue-600/20 px-4 py-2 text-sm text-blue-300 transition hover:bg-blue-600/30 disabled:opacity-50"
                  >
                    {{ loadingAccounts ? '加载中...' : '选择账号' }}
                  </button>
                </div>
                <div v-if="selectedAccountEmails.length" class="mt-2 flex flex-wrap gap-2">
                  <span v-for="email in selectedAccountPreviewEmails" :key="email" class="max-w-full truncate rounded-md border border-gray-700 bg-gray-900 px-2 py-1 font-mono text-xs text-gray-300">
                    {{ email }}
                  </span>
                  <span v-if="selectedAccountEmails.length > selectedAccountPreviewEmails.length" class="rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-500">
                    +{{ selectedAccountEmails.length - selectedAccountPreviewEmails.length }}
                  </span>
                </div>
              </div>
            </div>

            <div class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-3">
              <div class="text-sm font-medium text-emerald-100">GoPay Pro 运行配置</div>
              <div class="mt-1 text-xs leading-relaxed text-gray-400">
                稳定号完成本轮 Plus 开通并换绑释放后，会重新从注册阶段进入下一轮，直到选中的 GPT 账号处理完。
              </div>
              <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">任务启用 slot 数</label>
                  <input v-model.number="batchConcurrency" type="number" min="1" max="50" class="w-full rounded-lg border border-emerald-500/20 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500" />
                </div>
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">并发数</label>
                  <input v-model.number="configDraft.concurrency" @focus="configDraftEditing = true" @blur="finishConfigDraftEdit" @change="saveConfig({ silent: true })" type="number" min="1" max="50" class="w-full rounded-lg border border-emerald-500/20 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500" />
                </div>
              </div>
              <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">最大重试</label>
                  <input v-model.number="batchMaxAttempts" type="number" min="1" max="10" class="w-full rounded-lg border border-emerald-500/20 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-emerald-500" />
                </div>
              </div>
            </div>

            <div class="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
              <div class="mb-3">
                <h3 class="text-sm font-semibold text-white">流程动作</h3>
                <p class="mt-1 text-xs text-gray-500">启动 GoPay Pro 脚本任务。</p>
              </div>
              <div class="grid gap-2">
                <button v-for="item in taskActions" :key="item.kind" @click="startTask(item.kind)" :disabled="saving" class="flex items-center justify-between rounded-lg border border-gray-700 bg-gray-900 px-3 py-3 text-left transition hover:border-blue-500/50 hover:bg-gray-800 disabled:opacity-50">
                  <span>
                    <span class="block text-sm font-medium text-white">{{ item.label }}</span>
                    <span class="mt-0.5 block text-xs text-gray-500">{{ item.script }}</span>
                  </span>
                  <span class="text-xs text-blue-300">启动</span>
                </button>
              </div>
            </div>

            <div class="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
              <div class="mb-3">
                <h3 class="text-sm font-semibold text-white">诊断工具</h3>
                <p class="mt-1 text-xs text-gray-500">用于检查 GoPay 绑定状态和资料；仅 Linking 不发起扣款。</p>
              </div>
              <div class="grid gap-2 sm:grid-cols-3">
                <button
                  v-for="item in diagnosticActions"
                  :key="item.kind"
                  type="button"
                  @click="startTask(item.kind)"
                  :disabled="saving"
                  class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-left transition hover:border-emerald-500/50 hover:bg-gray-800 disabled:opacity-50"
                >
                  <span class="block text-sm font-medium text-white">{{ item.label }}</span>
                  <span class="mt-0.5 block text-xs text-gray-500">{{ item.script }}</span>
                </button>
              </div>
            </div>

          </div>
        </div>

        <div class="grid min-h-[520px] grid-cols-1 gap-4 xl:min-h-0 xl:grid-cols-[minmax(0,1fr)_360px] xl:overflow-hidden">
          <section class="flex min-h-0 flex-col rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="shrink-0">
              <div class="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <h3 class="font-semibold text-white">实时 GoPay Pro 日志</h3>
                  <p class="mt-1 text-xs text-gray-500">{{ selectedTask?.progress?.message || selectedTask?.error || '尚未提交 GoPay Pro 任务。' }}</p>
                </div>
                <div class="flex flex-wrap gap-2">
                  <button @click="loadStatus" :disabled="loading" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 transition hover:bg-gray-700 disabled:opacity-50">
                    {{ loading ? '刷新中...' : '刷新' }}
                  </button>
                  <button @click="cancelSelectedTask" :disabled="!selectedTask || !['pending', 'running'].includes(selectedTask.status)" class="rounded-lg border border-red-500/30 bg-red-600/15 px-3 py-2 text-sm text-red-300 transition hover:bg-red-600/25 disabled:opacity-50">停止</button>
                </div>
              </div>
              <div v-if="tasks.length > 1" class="mt-3 flex gap-2 overflow-x-auto pb-1">
                <button v-for="task in tasks" :key="task.task_id" @click="selectTask(task.task_id)" class="shrink-0 rounded-lg border px-3 py-2 text-left text-xs" :class="selectedTaskId === task.task_id ? 'border-blue-500/40 bg-blue-500/10 text-blue-100' : 'border-gray-800 bg-gray-950 text-gray-300'">
                  <div class="flex items-center gap-2">
                    <span>{{ task.params?.kind || task.command }}</span>
                    <span :class="taskStatusClass(task.status)">{{ taskStatusLabel(task.status) }}</span>
                  </div>
                </button>
              </div>
            </div>
            <pre ref="logScrollRef" class="mt-4 min-h-0 flex-1 overflow-auto rounded-lg border border-gray-800 bg-gray-950 p-3 text-xs leading-relaxed text-gray-300">{{ selectedTaskLog }}</pre>
          </section>

          <aside class="space-y-3 xl:min-h-0 xl:overflow-y-auto xl:pr-1">
            <div class="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
              <div class="mb-3">
                <h3 class="text-sm font-semibold text-white">添加换绑主号</h3>
                <p class="mt-1 text-xs text-gray-500">格式：+62xxx----接码 URL。</p>
              </div>
              <textarea v-model="numbersText" rows="3" wrap="off" spellcheck="false" class="w-full overflow-x-auto rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-white outline-none focus:border-blue-500" placeholder="+628xxxx----https://api.sms8.net/api/record?token=..."></textarea>
              <div class="mt-3 flex justify-end">
                <button @click="addNumbers" :disabled="saving || !numbersText.trim()" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white transition hover:bg-emerald-500 disabled:opacity-50">
                  追加到号池
                </button>
              </div>
            </div>

            <div class="rounded-lg border border-gray-800 bg-gray-950/60 p-3">
              <div class="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 class="text-sm font-semibold text-white">Slot 管理 <span class="text-xs font-normal text-gray-500">({{ configDraft.slots }})</span></h3>
                  <p class="mt-1 text-xs text-gray-500">{{ stateSummary || '暂无 slot 状态' }}</p>
                </div>
                <input v-model.trim="slotKeyword" type="text" placeholder="搜索 slot" class="w-32 rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs text-white outline-none focus:border-blue-500" />
              </div>
              <div class="space-y-2">
                <div v-for="slot in filteredSlots" :key="slot.id" class="rounded-lg border border-gray-800 bg-gray-900/80 p-3">
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="whitespace-nowrap font-mono text-xs text-gray-300">{{ slot.id }}</span>
                        <span class="h-2 w-2 rounded-full" :class="slotStateDotClass(slot.state)"></span>
                        <span class="whitespace-nowrap text-xs" :class="slotStateClass(slot.state)">{{ slot.state || '-' }}</span>
                        <span
                          v-if="isMidtrans202Marked(slot)"
                          class="whitespace-nowrap rounded-md border border-amber-400/30 bg-amber-500/10 px-1.5 py-0.5 text-[11px] font-medium text-amber-200"
                          title="midtrans charge denied code=202"
                        >
                          202 拒付
                        </span>
                      </div>
                      <div class="mt-1 truncate font-mono text-xs text-gray-500">{{ slot.displayPhone || '-' }} / {{ slot.account_id || '-' }}</div>
                      <div v-if="slot.error" class="mt-1 line-clamp-2 text-xs text-rose-200/90" :title="slot.error">{{ slot.error }}</div>
                    </div>
                    <select v-model="slotDrafts[slot.id]" class="shrink-0 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500">
                      <option v-for="state in slotStates" :key="state" :value="state">{{ state }}</option>
                    </select>
                  </div>
                  <div class="mt-3 flex flex-wrap gap-2">
                    <button @click="saveSlot(slot.id)" :disabled="saving" class="rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white transition hover:bg-blue-500 disabled:opacity-50">保存</button>
                    <button @click="clearSlotError(slot.id)" :disabled="saving" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-200 transition hover:bg-gray-700 disabled:opacity-50">清错</button>
                    <button @click="deleteSlot(slot.id)" :disabled="saving" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">删除</button>
                  </div>
                </div>
                <div v-if="!filteredSlots.length" class="rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-8 text-center text-sm text-gray-500">暂无 slot 数据</div>
              </div>
            </div>
          </aside>
        </div>
      </div>
    </section>

    <div
      v-if="accountPickerOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      @click.self="closeAccountPicker"
    >
      <div class="flex max-h-[82vh] w-full max-w-3xl flex-col rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
        <div class="flex items-center justify-between gap-4 border-b border-gray-800 px-5 py-4">
          <div>
            <h4 class="text-lg font-semibold text-white">批量选择账号</h4>
            <div class="mt-1 text-xs text-gray-500">{{ accountPickerHelp }}</div>
          </div>
          <button
            type="button"
            @click="closeAccountPicker"
            class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 transition hover:bg-gray-700"
          >
            关闭
          </button>
        </div>

        <div class="space-y-3 border-b border-gray-800 px-5 py-4">
          <input
            v-model.trim="accountKeyword"
            type="text"
            :disabled="loadingAccounts"
            placeholder="搜索邮箱，例如 openaibus.com"
            class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white outline-none focus:border-blue-500"
          />
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="text-xs text-gray-400">
              {{ loadingAccounts ? '加载账号中...' : selectableAccounts.length ? `当前筛选 ${selectableAccounts.length} 个账号` : '没有匹配账号' }}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                @click="selectAllAccounts"
                :disabled="loadingAccounts || !availableAccounts.length || allPickerAccountsSelected"
                class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50"
              >
                全选
              </button>
              <button
                type="button"
                @click="clearSelectedAccounts"
                :disabled="!selectedAccountEmails.length"
                class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50"
              >
                清空
              </button>
            </div>
          </div>
        </div>

        <div class="min-h-0 flex-1 space-y-1 overflow-y-auto px-5 py-4">
          <label
            v-for="account in selectableAccounts"
            :key="account.email"
            class="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-gray-200 hover:bg-gray-800"
          >
            <input v-model="selectedAccountEmails" type="checkbox" class="accent-blue-500" :value="String(account.email || '').trim().toLowerCase()" />
            <span class="break-all font-mono text-xs">{{ account.email }}</span>
          </label>
          <div v-if="!selectableAccounts.length" class="px-3 py-10 text-sm text-gray-500">
            暂无匹配账号。
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 border-t border-gray-800 px-5 py-4">
          <button
            type="button"
            @click="closeAccountPicker"
            class="rounded-lg bg-blue-600 px-5 py-2 text-sm text-white transition hover:bg-blue-500"
          >
            完成
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, h, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { api } from '../api.js'

const selectedAccountsStorageKey = 'autotoken_gopay_pro_selected_accounts'

const slotStates = [
  'EMPTY',
  'GOPAY_REGISTERING',
  'WALLET_WAITING',
  'WALLET_READY',
  'PLUS_PAYING',
  'NO_TRIAL',
  'PLUS_DONE',
  'REBINDING',
  'RELEASED',
  'FAILED',
]

const taskActions = [
  { kind: 'register', label: '注册 GoPay', script: 'reg.cmd' },
  { kind: 'harvest', label: '启动绑定任务', script: 'harvest.cmd' },
  { kind: 'rebind', label: '单独换绑', script: 'rebind.cmd' },
  { kind: 'status', label: '检查状态', script: 'status.cmd' },
]

const diagnosticActions = [
  { kind: 'linkedapps', label: '查绑定', script: 'linkedapps.cmd' },
  { kind: 'profile', label: '查资料', script: 'profile.cmd' },
  { kind: 'link-only', label: '仅 Linking', script: 'link-only.cmd' },
]

const StatCard = (props) => h('div', { class: 'min-w-0 rounded-xl border border-gray-800 bg-gray-900 px-4 py-3' }, [
  h('div', { class: 'text-xs text-gray-400' }, props.label),
  h('div', { class: `mt-2 truncate text-xl font-bold ${props.className || 'text-white'}` }, String(props.value ?? 0)),
])

const loading = ref(false)
const loadingAccounts = ref(false)
const saving = ref(false)
const message = ref('')
const messageOk = ref(true)
const root = ref('')
const config = reactive({ slots: 0, concurrency: 0, gptMode: '', numberPoolFile: '', tokenFile: '' })
const configDraft = reactive({ slots: 1, concurrency: 1 })
const counts = reactive({ numbers: 0, tokens: 0 })
const slots = ref([])
const slotDrafts = reactive({})
const stateCounts = ref({})
const tasks = ref([])
const taskDetails = ref({})
const accounts = ref([])
const numbersText = ref('')
const selectedTaskId = ref('')
const slotKeyword = ref('')
const accountKeyword = ref('')
const accountPickerOpen = ref(false)
const selectedAccountEmails = ref(loadSelectedAccountEmails())
const batchConcurrency = ref(0)
const batchMaxAttempts = ref(3)
const configDraftEditing = ref(false)
const logScrollRef = ref(null)
let pollTimer = null
let statusRequestInFlight = false

watch(selectedAccountEmails, (emails) => {
  persistSelectedAccountEmails(emails)
}, { deep: true })

const filteredSlots = computed(() => {
  const q = slotKeyword.value.toLowerCase()
  if (!q) return slots.value
  return slots.value.filter((slot) => [
    slot.id,
    slot.state,
    slot.full_phone,
    slot.phone,
    slot.displayPhone,
    slot.account_id,
    slot.error,
    isMidtrans202Marked(slot) ? '202 midtrans charge denied 拒付' : '',
  ].some((value) => String(value || '').toLowerCase().includes(q)))
})

const midtrans202Count = computed(() => slots.value.filter((slot) => isMidtrans202Marked(slot)).length)
const stateSummary = computed(() => {
  const parts = Object.entries(stateCounts.value || {}).map(([key, value]) => `${key}: ${value}`)
  if (midtrans202Count.value) parts.push(`202标记: ${midtrans202Count.value}`)
  return parts.join(' / ')
})

const filteredAccounts = computed(() => {
  const q = accountKeyword.value.toLowerCase()
  if (!q) return accounts.value
  return accounts.value.filter((account) => [
    account.email,
    account.status,
    account.account_type,
    account.seat_type,
  ].some((value) => String(value || '').toLowerCase().includes(q)))
})

const availableAccounts = computed(() => accounts.value.filter(isAccountSelectable))
const selectableAccounts = computed(() => filteredAccounts.value.filter(isAccountSelectable))

const selectedAccountPreviewEmails = computed(() => selectedAccountEmails.value.slice(0, 4))

const accountPickerHelp = computed(() => `已选择 ${selectedAccountEmails.value.length} / ${availableAccounts.value.length} 个账号`)

const allPickerAccountsSelected = computed(() => {
  if (!availableAccounts.value.length) return false
  const selected = new Set(selectedAccountEmails.value.map((email) => String(email || '').trim().toLowerCase()))
  return availableAccounts.value.every((account) => selected.has(String(account.email || '').toLowerCase()))
})

const selectedTask = computed(() => {
  const fallback = tasks.value.find((task) => task.task_id === selectedTaskId.value) || tasks.value[0] || null
  const id = selectedTaskId.value || fallback?.task_id || ''
  return taskDetails.value[id] || fallback
})

const selectedTaskMetrics = computed(() => {
  const progress = selectedTask.value?.progress || {}
  const result = selectedTask.value?.result || {}
  const total = Number(progress.total ?? result.total ?? selectedTask.value?.params?.account_emails_count ?? 0)
  const successful = Number(progress.successful ?? result.successful ?? 0)
  const failed = Number(progress.failed ?? result.failed ?? 0)
  const pending = Math.max(0, Number(progress.pending ?? result.pending ?? total - successful - failed))
  const completed = Math.max(0, total - pending)
  return {
    total,
    successful,
    failed,
    pending,
    percent: total ? Math.min(100, Math.round((completed / total) * 100)) : 0,
  }
})

const selectedTaskLog = computed(() => {
  const task = selectedTask.value
  if (!task) return '等待任务启动'
  const events = Array.isArray(task.progress_events) ? task.progress_events : []
  const lines = events
    .map((event) => String(event?.message || event?.line || event?.stage || '').trim())
    .filter(Boolean)
  if (lines.length) return lines.join('\n')
  return task?.progress?.log_tail || task?.progress?.message || task?.error || '等待任务启动'
})

function setMessage(text, ok = true) {
  message.value = text
  messageOk.value = ok
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => { message.value = '' }, 7000)
}

function applyStatus(payload) {
  root.value = payload?.root || ''
  Object.assign(config, payload?.config || {})
  if (!configDraftEditing.value) {
    configDraft.slots = Number(config.slots || 1)
    configDraft.concurrency = Number(config.concurrency || 1)
  }
  if (!batchConcurrency.value) batchConcurrency.value = Number(config.concurrency || 1)
  Object.assign(counts, payload?.counts || {})
  slots.value = Array.isArray(payload?.slots) ? payload.slots : []
  stateCounts.value = payload?.stateCounts || {}
  tasks.value = Array.isArray(payload?.tasks) ? payload.tasks : []
  for (const slot of slots.value) {
    slotDrafts[slot.id] = slot.state || 'EMPTY'
  }
  if (!selectedTaskId.value && tasks.value.length) selectedTaskId.value = tasks.value[0].task_id
}

function selectTask(taskId) {
  selectedTaskId.value = taskId
  loadSelectedTaskDetail({ silent: true })
}

async function loadSelectedTaskDetail(options = {}) {
  const id = selectedTaskId.value || tasks.value[0]?.task_id || ''
  if (!id) return
  const shouldStickToBottom = isLogNearBottom()
  try {
    const detail = await api.getTask(id)
    taskDetails.value = {
      ...taskDetails.value,
      [id]: detail,
    }
    await scrollLogToBottomIfNeeded({ ...options, force: options.force || shouldStickToBottom })
  } catch (error) {
    if (!options.silent) setMessage(error.message || '加载任务日志失败', false)
  }
}

function isLogNearBottom() {
  const el = logScrollRef.value
  if (!el) return true
  return el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

async function scrollLogToBottomIfNeeded(options = {}) {
  await nextTick()
  const el = logScrollRef.value
  if (!el) return
  const force = Boolean(options.force)
  if (force || isLogNearBottom()) {
    el.scrollTop = el.scrollHeight
  }
}

function isAccountSelectable(account) {
  return Boolean(account?.email)
    && Boolean(account?.has_codex_auth_file || account?.auth_session_file)
    && String(account.status || '').toLowerCase() !== 'plus'
    && String(account.account_type || '').toLowerCase() !== 'plus'
}

function isMidtrans202Marked(slot) {
  return Boolean(slot?.midtransCharge202 || slot?.midtrans_charge_202)
}

function normalizeSelectedAccountEmails(emails) {
  return Array.from(new Set(
    (Array.isArray(emails) ? emails : [])
      .map((email) => String(email || '').trim().toLowerCase())
      .filter(Boolean),
  ))
}

function loadSelectedAccountEmails() {
  try {
    return normalizeSelectedAccountEmails(JSON.parse(window.localStorage.getItem(selectedAccountsStorageKey) || '[]'))
  } catch {
    return []
  }
}

function persistSelectedAccountEmails(emails) {
  try {
    window.localStorage.setItem(selectedAccountsStorageKey, JSON.stringify(normalizeSelectedAccountEmails(emails)))
  } catch {
    // The page still works when browser storage is unavailable.
  }
}

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const payload = await api.getAccounts({ includeSessionStubs: true })
    accounts.value = Array.isArray(payload) ? payload : (payload?.accounts || [])
    const validEmails = new Set(availableAccounts.value.map((account) => String(account.email || '').trim().toLowerCase()))
    selectedAccountEmails.value = normalizeSelectedAccountEmails(selectedAccountEmails.value)
      .filter((email) => email && validEmails.has(email))
  } catch (error) {
    setMessage(error.message || '加载 GPT 账号池失败', false)
  } finally {
    loadingAccounts.value = false
  }
}

function selectAllAccounts() {
  selectedAccountEmails.value = Array.from(new Set([
    ...selectedAccountEmails.value,
    ...availableAccounts.value.map((account) => String(account.email || '').trim().toLowerCase()).filter(Boolean),
  ]))
}

function clearSelectedAccounts() {
  selectedAccountEmails.value = []
}

function closeAccountPicker() {
  accountPickerOpen.value = false
}

function finishConfigDraftEdit() {
  window.setTimeout(() => {
    configDraftEditing.value = false
  }, 0)
}

async function startBatch() {
  saving.value = true
  try {
    const task = await api.startGoPayProBatch({
      account_emails: selectedAccountEmails.value,
      concurrency: batchConcurrency.value || configDraft.concurrency || 1,
      max_attempts: batchMaxAttempts.value || 3,
    })
    selectedTaskId.value = task.task_id
    setMessage(`GoPay Pro 全自动批量已启动，共 ${selectedAccountEmails.value.length} 个账号`)
    await loadStatus()
    await scrollLogToBottomIfNeeded({ force: true })
  } catch (error) {
    setMessage(error.message || '启动 GoPay Pro 批量失败', false)
  } finally {
    saving.value = false
  }
}

async function cancelSelectedTask() {
  if (!selectedTask.value?.task_id) return
  saving.value = true
  try {
    await api.cancelTask({ task_id: selectedTask.value.task_id })
    setMessage('已请求停止 GoPay Pro 任务')
    await loadStatus()
  } catch (error) {
    setMessage(error.message || '停止任务失败', false)
  } finally {
    saving.value = false
  }
}

async function loadStatus(options = {}) {
  if (statusRequestInFlight) return
  statusRequestInFlight = true
  const silent = Boolean(options.silent)
  if (!silent) loading.value = true
  try {
    applyStatus(await api.getGoPayProStatus())
    await loadSelectedTaskDetail({ silent: true })
  } catch (error) {
    if (!silent) setMessage(error.message || '加载 GoPay Pro 状态失败', false)
  } finally {
    statusRequestInFlight = false
    if (!silent) loading.value = false
  }
}

async function saveConfig(options = {}) {
  const silent = Boolean(options.silent)
  if (!silent) saving.value = true
  try {
    const status = await api.saveGoPayProConfig({
      concurrency: configDraft.concurrency,
    })
    configDraftEditing.value = false
    applyStatus(status)
    if (!silent) setMessage('池配置已保存')
  } catch (error) {
    configDraftEditing.value = false
    setMessage(error.message || '保存池配置失败', false)
  } finally {
    if (!silent) saving.value = false
  }
}

async function addNumbers() {
  saving.value = true
  try {
    const result = await api.importGoPayProNumbers(numbersText.value)
    numbersText.value = ''
    applyStatus(result.status)
    setMessage(`新增 ${result.added || 0} 个稳定号，跳过 ${result.duplicates || 0} 个重复`)
  } catch (error) {
    setMessage(error.message || '导入稳定号失败', false)
  } finally {
    saving.value = false
  }
}

async function startTask(kind) {
  saving.value = true
  try {
    const task = await api.startGoPayProTask(kind)
    selectedTaskId.value = task.task_id
    setMessage('GoPay Pro 任务已启动')
    await loadStatus()
    await scrollLogToBottomIfNeeded({ force: true })
  } catch (error) {
    setMessage(error.message || '启动任务失败', false)
  } finally {
    saving.value = false
  }
}

async function saveSlot(id) {
  await slotAction({ id, action: 'set-state', state: slotDrafts[id] })
}

async function clearSlotError(id) {
  await slotAction({ id, action: 'clear-error' })
}

async function deleteSlot(id) {
  if (!window.confirm(`删除 ${id}？`)) return
  await slotAction({ id, action: 'delete' })
}

async function slotAction(payload) {
  saving.value = true
  try {
    const result = await api.updateGoPayProSlot(payload)
    applyStatus(result.status)
    setMessage('Slot 已更新')
  } catch (error) {
    setMessage(error.message || '更新 Slot 失败', false)
  } finally {
    saving.value = false
  }
}

function slotStateClass(state) {
  if (['WALLET_READY', 'RELEASED', 'PLUS_DONE'].includes(state)) return 'text-emerald-300'
  if (['GOPAY_REGISTERING', 'WALLET_WAITING', 'PLUS_PAYING', 'REBINDING'].includes(state)) return 'text-blue-300'
  if (['NO_TRIAL', 'FAILED'].includes(state)) return 'text-rose-300'
  return 'text-gray-400'
}

function slotStateDotClass(state) {
  if (['WALLET_READY', 'RELEASED', 'PLUS_DONE'].includes(state)) return 'bg-emerald-400'
  if (['GOPAY_REGISTERING', 'WALLET_WAITING', 'PLUS_PAYING', 'REBINDING'].includes(state)) return 'bg-blue-400'
  if (['NO_TRIAL', 'FAILED'].includes(state)) return 'bg-rose-400'
  return 'bg-gray-500'
}

function taskStatusLabel(status) {
  return { pending: '等待中', running: '执行中', completed: '已完成', failed: '失败', cancelled: '已取消' }[status] || status || '-'
}

function taskStatusClass(status) {
  return {
    pending: 'text-amber-300',
    running: 'text-blue-300',
    completed: 'text-emerald-300',
    failed: 'text-rose-300',
    cancelled: 'text-gray-400',
  }[status] || 'text-gray-400'
}

onMounted(() => {
  loadStatus()
  loadAccounts()
  pollTimer = window.setInterval(() => loadStatus({ silent: true }), 3000)
})

onUnmounted(() => {
  if (pollTimer) window.clearInterval(pollTimer)
})
</script>
