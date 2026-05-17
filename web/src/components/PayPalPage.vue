<template>
  <div class="space-y-6">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 class="text-xl font-bold text-white">PayPal</h2>
          <p class="mt-1 text-sm text-gray-400">
            迁移自 Gpt-Agreement-Payment 的 PayPal 运行器，支持单次、批量、daemon 和补号模式。
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="px-3 py-2 rounded-lg text-sm border transition"
            :class="running ? 'border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20' : 'border-gray-700 bg-gray-900 text-gray-300 hover:bg-gray-800'"
            :disabled="busy"
            @click="running ? stopTask() : refreshTask()"
          >
            {{ running ? '停止任务' : '刷新状态' }}
          </button>
          <button
            class="px-3 py-2 rounded-lg text-sm border transition border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20 disabled:opacity-50"
            :disabled="busy || running"
            @click="startTask"
          >
            {{ busy ? '提交中...' : '开始运行' }}
          </button>
        </div>
      </div>

      <div class="mt-5 grid grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)] gap-4">
        <div class="space-y-4">
          <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
            <div class="text-sm font-semibold text-white mb-3">运行参数</div>
            <div class="space-y-3">
              <div>
                <label class="block text-xs text-gray-400 mb-1">项目目录</label>
                <input v-model.trim="form.project_path" type="text" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" placeholder="D:\\code\\OpenSource\\Gpt-Agreement-Payment" />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">配置文件</label>
                <input v-model.trim="form.config_path" type="text" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" placeholder="CTF-pay/config.paypal.json" />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">Python 可执行文件</label>
                <input v-model.trim="form.python_executable" type="text" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" placeholder="python" />
              </div>

              <div>
                <label class="block text-xs text-gray-400 mb-1">模式</label>
                <select v-model="form.mode" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500">
                  <option v-for="opt in modeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
              </div>

              <div v-if="form.mode === 'batch'" class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">batch</label>
                  <input v-model.number="form.batch" type="number" min="1" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label class="block text-xs text-gray-400 mb-1">workers</label>
                  <input v-model.number="form.workers" type="number" min="1" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" />
                </div>
              </div>

              <div v-if="form.mode === 'self_dealer'" class="grid grid-cols-1 gap-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">成员数</label>
                  <input v-model.number="form.self_dealer" type="number" min="1" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" />
                </div>
              </div>

              <div v-if="form.mode === 'free_register'" class="grid grid-cols-1 gap-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">注册数</label>
                  <input v-model.number="form.count" type="number" min="0" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" />
                </div>
              </div>

              <div class="grid grid-cols-1 gap-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">目标账号</label>
                  <textarea v-model.trim="emailsText" rows="3" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" placeholder="每行一个邮箱，留空则按项目默认选择"></textarea>
                </div>
                <div>
                  <label class="block text-xs text-gray-400 mb-1">额外参数</label>
                  <input v-model.trim="form.extra_args" type="text" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" placeholder="如 --paypal --daemon" />
                </div>
              </div>

              <div class="grid grid-cols-2 gap-2 pt-1">
                <label class="flex items-center gap-2 text-sm text-gray-300">
                  <input v-model="form.register_only" type="checkbox" class="rounded border-gray-700 bg-gray-950 text-blue-500 focus:ring-blue-500" :disabled="form.pay_only" />
                  只注册
                </label>
                <label class="flex items-center gap-2 text-sm text-gray-300">
                  <input v-model="form.pay_only" type="checkbox" class="rounded border-gray-700 bg-gray-950 text-blue-500 focus:ring-blue-500" />
                  只支付
                </label>
                <label class="flex items-center gap-2 text-sm text-gray-300">
                  <input v-model="form.rt_only" type="checkbox" class="rounded border-gray-700 bg-gray-950 text-blue-500 focus:ring-blue-500" />
                  只补 RT
                </label>
                <label class="flex items-center gap-2 text-sm text-gray-300">
                  <input v-model="form.use_xvfb" type="checkbox" class="rounded border-gray-700 bg-gray-950 text-blue-500 focus:ring-blue-500" />
                  使用 xvfb-run
                </label>
              </div>

              <div>
                <label class="block text-xs text-gray-400 mb-1">超时（秒）</label>
                <input v-model.number="form.timeout_seconds" type="number" min="0" class="w-full px-3 py-2 rounded-lg bg-gray-950 border border-gray-700 text-sm text-white focus:outline-none focus:border-blue-500" />
              </div>
            </div>
          </div>
        </div>

        <div class="space-y-4 min-w-0">
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <div class="text-xs text-gray-400">任务状态</div>
              <div class="mt-2 text-lg font-semibold text-white">{{ running ? '执行中' : (lastTask?.status || '空闲') }}</div>
            </div>
            <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <div class="text-xs text-gray-400">进度</div>
              <div class="mt-2 text-lg font-semibold text-blue-300">{{ progressText }}</div>
            </div>
            <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <div class="text-xs text-gray-400">退出码</div>
              <div class="mt-2 text-lg font-semibold" :class="lastTask?.status === 'completed' ? 'text-emerald-300' : 'text-rose-300'">{{ lastTask?.result?.exit_code ?? lastTask?.exit_code ?? '-' }}</div>
            </div>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/80 min-h-[480px] flex flex-col">
            <div class="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-800">
              <div>
                <div class="text-sm font-semibold text-white">实时日志</div>
                <div class="text-xs text-gray-400">展示当前任务与最近执行记录</div>
              </div>
              <button class="px-3 py-1.5 rounded-lg text-xs border border-gray-700 bg-gray-900 text-gray-300 hover:bg-gray-800" @click="refreshTask">
                刷新
              </button>
            </div>
            <div class="flex-1 overflow-y-auto p-4 space-y-2">
              <div v-if="!selectedTask" class="text-sm text-gray-500">暂无任务</div>
              <div v-for="line in visibleLogs" :key="line.seq || line.ts || line.line" class="rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="text-[11px] text-gray-500">{{ formatTs(line.ts) }}</div>
                    <div class="mt-1 text-sm text-gray-100 whitespace-pre-wrap break-words">{{ line.line || line.message || line.stage }}</div>
                  </div>
                  <span class="text-[11px] shrink-0 rounded-full px-2 py-0.5 border" :class="line.statusClass">{{ line.level || line.stage || 'INFO' }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api.js'

const busy = ref(false)
const running = ref(false)
const lastTask = ref(null)
const selectedTask = ref(null)
const pollTimer = ref(null)
const form = ref({
  project_path: 'D:\\code\\OpenSource\\Gpt-Agreement-Payment',
  config_path: 'CTF-pay/config.paypal.json',
  python_executable: 'python',
  mode: 'single',
  batch: 1,
  workers: 3,
  self_dealer: 1,
  count: 0,
  register_only: false,
  pay_only: false,
  rt_only: false,
  register_mode: 'browser',
  target_emails: [],
  extra_args: '',
  use_xvfb: true,
  timeout_seconds: 0,
})
const emailsText = ref('')
const modeOptions = [
  { value: 'single', label: '单次' },
  { value: 'batch', label: '批量' },
  { value: 'self_dealer', label: 'self_dealer' },
  { value: 'daemon', label: 'daemon' },
  { value: 'free_register', label: 'free_register' },
  { value: 'free_backfill_rt', label: 'free_backfill_rt' },
]

function formatTs(ts) {
  if (!ts) return ''
  const d = new Date(Number(ts) * 1000)
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

function normalizeEmails() {
  const rows = String(emailsText.value || '')
    .split(/\r?\n|,/g)
    .map(v => v.trim())
    .filter(Boolean)
  form.value.target_emails = [...new Set(rows)]
}

const progressText = computed(() => {
  const progress = lastTask.value?.progress || {}
  const total = Number(progress.total || lastTask.value?.params?.batch || lastTask.value?.params?.count || 0)
  const current = Number(progress.current || progress.processed || 0)
  if (total > 0) return `${current}/${total}`
  return running.value ? '进行中' : '-'
})

const visibleLogs = computed(() => {
  const task = selectedTask.value
  if (!task) return []
  const events = Array.isArray(task.progress_events) ? task.progress_events : []
  return events.slice(-200).map((item) => ({
    ...item,
    line: item.message || item.line || item.stage || '',
    level: item.level || 'INFO',
    statusClass: item.level === 'error' ? 'border-rose-500/30 text-rose-300' : item.level === 'warn' ? 'border-amber-500/30 text-amber-300' : 'border-gray-700 text-gray-300',
  }))
})

async function refreshTask() {
  try {
    const tasks = await api.getTasks(true)
    const paypalTasks = Array.isArray(tasks) ? tasks.filter(task => task?.command === 'paypal') : []
    const active = paypalTasks.find(task => ['running', 'pending'].includes(String(task?.status || '')))
    selectedTask.value = active || paypalTasks[0] || null
    lastTask.value = selectedTask.value
    running.value = Boolean(active)
  } catch (error) {
    console.warn('PayPal 任务刷新失败:', error)
  }
}

async function startTask() {
  normalizeEmails()
  busy.value = true
  try {
    const payload = {
      ...form.value,
      target_emails: [...form.value.target_emails],
    }
    const task = await api.startPayPal(payload)
    lastTask.value = task
    selectedTask.value = task
    running.value = true
  } finally {
    busy.value = false
    await refreshTask()
  }
}

async function stopTask() {
  busy.value = true
  try {
    const task_id = selectedTask.value?.task_id || lastTask.value?.task_id || ''
    await api.cancelTask(task_id ? { task_id } : null)
  } catch (error) {
    console.warn('停止 PayPal 任务失败:', error)
  } finally {
    busy.value = false
    await refreshTask()
  }
}

onMounted(async () => {
  await refreshTask()
  pollTimer.value = setInterval(refreshTask, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>
