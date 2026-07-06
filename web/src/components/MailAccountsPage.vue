<template>
  <div class="space-y-5">
    <section class="rounded-xl border border-gray-800 bg-gray-900/90 p-4 shadow-2xl">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 class="text-xl font-semibold text-white">mail邮箱管理</h2>
        </div>
        <div class="grid grid-cols-2 gap-2 text-xs sm:grid-cols-5">
          <div class="rounded-lg border border-gray-800 bg-gray-950/70 px-3 py-2">
            <div class="text-gray-500">总数</div>
            <div class="mt-1 text-lg font-bold text-white">{{ summary.total }}</div>
          </div>
          <div class="rounded-lg border border-green-500/20 bg-green-500/10 px-3 py-2">
            <div class="text-gray-500">启用</div>
            <div class="mt-1 text-lg font-bold text-green-300">{{ summary.enabled_count }}</div>
          </div>
          <div class="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2">
            <div class="text-gray-500">有效</div>
            <div class="mt-1 text-lg font-bold text-blue-300">{{ summary.valid_count }}</div>
          </div>
          <div class="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2">
            <div class="text-gray-500">失效</div>
            <div class="mt-1 text-lg font-bold text-red-300">{{ summary.invalid_count }}</div>
          </div>
          <div class="rounded-lg border border-gray-800 bg-gray-950/70 px-3 py-2">
            <div class="text-gray-500">选中</div>
            <div class="mt-1 text-lg font-bold text-white">{{ selectedEmails.length }}</div>
          </div>
        </div>
      </div>
    </section>

    <section class="dashboard-table-shell">
      <div class="dashboard-filter-bar">
        <div class="dashboard-filters">
          <select v-model="checkFilter" class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200">
            <option value="">检测: 全部</option>
            <option value="valid">检测: 有效</option>
            <option value="invalid">检测: 失效</option>
            <option value="unchecked">检测: 未检测</option>
          </select>
          <select v-model="statusFilter" class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200">
            <option value="">状态: 全部</option>
            <option value="enabled">状态: 启用</option>
            <option value="disabled">状态: 禁用</option>
          </select>
          <input
            v-model.trim="emailQuery"
            type="search"
            placeholder="搜索邮箱..."
            class="min-w-52 rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600"
          />
          <input
            v-model.trim="noteQuery"
            type="search"
            placeholder="搜索备注..."
            class="min-w-52 rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600"
          />
        </div>
        <div class="dashboard-actions">
          <button @click="openImportDialog" class="rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-500">
            导入
          </button>
          <button @click="openEditDialog(null)" class="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-600">
            新增
          </button>
          <button @click="checkRows(filteredEmails)" :disabled="busy || !filteredRows.length" class="rounded-lg bg-green-700 px-3 py-2 text-sm font-semibold text-white hover:bg-green-600 disabled:opacity-50">
            全部检测
          </button>
          <button @click="openStatusDialog" :disabled="!selectedEmails.length" class="rounded-lg bg-purple-700 px-3 py-2 text-sm font-semibold text-white hover:bg-purple-600 disabled:opacity-50">
            批量状态
          </button>
          <button @click="openNoteDialog" :disabled="!selectedEmails.length" class="rounded-lg bg-cyan-700 px-3 py-2 text-sm font-semibold text-white hover:bg-cyan-600 disabled:opacity-50">
            批量备注
          </button>
          <button @click="openPasswordDialog(selectedEmails)" :disabled="!selectedEmails.length" class="rounded-lg bg-yellow-700 px-3 py-2 text-sm font-semibold text-white hover:bg-yellow-600 disabled:opacity-50">
            批量改密
          </button>
          <button @click="exportRows" class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm font-semibold text-gray-200 hover:bg-gray-800">
            导出
          </button>
          <button @click="clearRows" :disabled="busy || !rows.length" class="rounded-lg bg-red-700 px-3 py-2 text-sm font-semibold text-white hover:bg-red-600 disabled:opacity-50">
            清空全部
          </button>
        </div>
      </div>

      <div v-if="message" class="border-b border-gray-800 px-4 py-3 text-sm" :class="messageClass">
        {{ message }}
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-[1180px] w-full text-left text-sm">
          <thead class="border-b border-gray-800 bg-gray-950/70 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="w-12 px-4 py-3">
                <input type="checkbox" :checked="allFilteredSelected" @change="toggleAllFiltered" />
              </th>
              <th class="w-14 px-3 py-3">#</th>
              <th class="px-3 py-3">邮箱</th>
              <th class="px-3 py-3">邮箱密码</th>
              <th class="px-3 py-3">GPT密码</th>
              <th class="px-3 py-3">状态</th>
              <th class="px-3 py-3">检测</th>
              <th class="px-3 py-3">备注</th>
              <th class="px-3 py-3">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800">
            <tr v-for="(row, index) in filteredRows" :key="row.email" class="bg-gray-950/30 hover:bg-gray-900/70">
              <td class="px-4 py-3">
                <input type="checkbox" :checked="selected.has(row.email)" @change="toggleSelected(row.email)" />
              </td>
              <td class="px-3 py-3 text-gray-500">{{ index + 1 }}</td>
              <td class="px-3 py-3">
                <div class="font-semibold text-gray-100">{{ row.email }}</div>
                <div class="mt-1 max-w-[280px] truncate font-mono text-xs text-gray-600" :title="row.refresh_token">
                  OpenAI RT {{ row.refresh_token_masked || '-' }}
                </div>
              </td>
              <td class="px-3 py-3">
                <button
                  type="button"
                  class="max-w-[180px] truncate rounded border border-gray-800 bg-gray-950 px-2 py-1 font-mono text-xs text-gray-300 hover:border-blue-500/50 hover:text-white"
                  :title="passwordVisible(row.email, 'mail') ? '点击隐藏邮箱密码' : '点击显示邮箱密码'"
                  @click="togglePasswordVisible(row.email, 'mail')"
                >
                  {{ displayPassword(row.mail_password, row.email, 'mail') }}
                </button>
              </td>
              <td class="px-3 py-3">
                <button
                  type="button"
                  class="max-w-[180px] truncate rounded border border-gray-800 bg-gray-950 px-2 py-1 font-mono text-xs text-gray-300 hover:border-blue-500/50 hover:text-white"
                  :title="passwordVisible(row.email, 'gpt') ? '点击隐藏 GPT 密码' : '点击显示 GPT 密码'"
                  @click="togglePasswordVisible(row.email, 'gpt')"
                >
                  {{ displayPassword(row.gpt_password, row.email, 'gpt') }}
                </button>
              </td>
              <td class="px-3 py-3">
                <span class="rounded-full px-2.5 py-1 text-xs font-semibold" :class="statusClass(row.status)">
                  {{ statusLabel(row.status) }}
                </span>
              </td>
              <td class="px-3 py-3">
                <div class="flex flex-col gap-1">
                  <span class="w-fit rounded-full px-2.5 py-1 text-xs font-semibold" :class="checkClass(row.check_status)">
                    {{ checkLabel(row.check_status) }}
                  </span>
                  <span v-if="row.last_error" class="max-w-[180px] truncate text-xs text-red-300" :title="row.last_error">
                    {{ row.last_error }}
                  </span>
                </div>
              </td>
              <td class="max-w-[220px] px-3 py-3 text-gray-400">
                <span class="line-clamp-2">{{ row.note || '-' }}</span>
              </td>
              <td class="px-3 py-3">
                <div class="flex flex-wrap gap-2">
                  <button @click="checkRows([row.email])" :disabled="busy" class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">检测</button>
                  <button @click="fetchRows([row.email])" :disabled="busy" class="rounded-lg bg-cyan-700 px-3 py-1.5 font-semibold text-white hover:bg-cyan-600 disabled:opacity-50">取件</button>
                  <button @click="openPasswordDialog([row.email])" class="rounded-lg bg-yellow-700 px-3 py-1.5 font-semibold text-white hover:bg-yellow-600">改密</button>
                  <button @click="openEditDialog(row)" class="rounded-lg bg-blue-700 px-3 py-1.5 font-semibold text-white hover:bg-blue-600">编辑</button>
                  <button @click="deleteRows([row.email])" class="rounded-lg bg-red-700 px-3 py-1.5 font-semibold text-white hover:bg-red-600">删除</button>
                </div>
              </td>
            </tr>
            <tr v-if="!filteredRows.length">
              <td colspan="9" class="px-4 py-12 text-center text-gray-500">
                暂无 mail.com 邮箱账号，点击“导入”粘贴 邮箱----GPT密码----邮箱密码----OpenAI refreshToken
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="dialog" class="fixed inset-0 z-50 grid place-items-center bg-black/70 px-4">
      <section class="w-full max-w-2xl rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
        <div class="flex items-center justify-between border-b border-gray-800 px-5 py-4">
          <h3 class="text-lg font-semibold text-white">{{ dialogTitle }}</h3>
          <button @click="closeDialog" class="text-2xl leading-none text-gray-400 hover:text-white">×</button>
        </div>

        <div class="space-y-4 px-5 py-4">
          <template v-if="dialog === 'import'">
            <p class="text-sm text-gray-400">每行格式：邮箱----GPT密码----邮箱密码----OpenAI refreshToken</p>
            <textarea v-model="importText" rows="9" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 font-mono text-sm text-white placeholder:text-gray-600" placeholder="aharvey183195@mail.com----gpt-pass----mail-pass----rt.xxxxx"></textarea>
          </template>

          <template v-else-if="dialog === 'edit'">
            <div class="grid gap-3 sm:grid-cols-2">
              <label class="block">
                <span class="mb-1 block text-xs text-gray-500">邮箱</span>
                <input v-model.trim="form.email" type="email" :disabled="!!editingEmail" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white disabled:opacity-60" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-gray-500">状态</span>
                <select v-model="form.status" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white">
                  <option value="enabled">启用</option>
                  <option value="disabled">禁用</option>
                </select>
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-gray-500">GPT密码</span>
                <input v-model="form.gptPassword" type="text" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white" />
              </label>
              <label class="block">
                <span class="mb-1 block text-xs text-gray-500">邮箱密码</span>
                <input v-model="form.mailPassword" type="text" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white" />
              </label>
            </div>
            <label class="block">
              <span class="mb-1 block text-xs text-gray-500">OpenAI refreshToken</span>
              <textarea v-model.trim="form.refreshToken" rows="4" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 font-mono text-sm text-white"></textarea>
            </label>
            <label class="block">
              <span class="mb-1 block text-xs text-gray-500">备注</span>
              <input v-model="form.note" type="text" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white" />
            </label>
          </template>

          <template v-else-if="dialog === 'password'">
            <p class="text-sm text-gray-400">
              将通过协议登录 mail.com 官网修改密码；成功后才更新本地 SQLite 保存的邮箱密码。
            </p>
            <input v-model="newPassword" type="text" placeholder="输入新密码" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600" />
            <p class="text-xs text-gray-500">建议使用 12 位以上，包含大小写字母、数字和符号；如果官网拒绝会在结果中显示具体错误。</p>
          </template>

          <template v-else-if="dialog === 'passwordResult'">
            <div class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-3 text-sm text-gray-300">
              改密结果：成功 {{ passwordSummary.updated || 0 }} 个，失败 {{ passwordSummary.failed || 0 }} 个
            </div>
            <div class="max-h-[52vh] space-y-2 overflow-y-auto pr-1">
              <article
                v-for="item in passwordResults"
                :key="item.email"
                class="rounded-lg border px-3 py-3 text-sm"
                :class="item.status === 'success' ? 'border-green-500/20 bg-green-500/10 text-green-200' : 'border-red-500/20 bg-red-500/10 text-red-200'"
              >
                <div class="font-mono">{{ item.email }}</div>
                <div class="mt-1 text-xs">
                  {{ item.status === 'success' ? '官网改密成功，已更新本地 SQLite' : (item.error || '官网改密失败') }}
                </div>
              </article>
            </div>
          </template>

          <template v-else-if="dialog === 'status'">
            <p class="text-sm text-gray-400">将为选中的 {{ selectedEmails.length }} 个账号修改状态。</p>
            <select v-model="newStatus" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white">
              <option value="enabled">启用</option>
              <option value="disabled">禁用</option>
            </select>
          </template>

          <template v-else-if="dialog === 'note'">
            <p class="text-sm text-gray-400">将为选中的 {{ selectedEmails.length }} 个账号设置相同备注。</p>
            <input v-model="newNote" type="text" placeholder="输入备注" class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600" />
          </template>

          <template v-else-if="dialog === 'fetched'">
            <div v-if="!fetchedResults.length" class="rounded-lg border border-gray-800 bg-gray-950 px-4 py-8 text-center text-sm text-gray-500">
              没有返回邮件
            </div>
            <div v-if="activeFetchedMessage" class="mb-4 rounded-xl border border-blue-500/30 bg-blue-500/10 p-4">
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-xs font-semibold text-blue-300">邮件详情</div>
                  <h4 class="mt-1 break-words text-base font-semibold text-white">{{ activeFetchedMessage.message.subject || '(无主题)' }}</h4>
                  <p class="mt-1 text-xs text-gray-400">
                    {{ activeFetchedMessage.email }} · {{ activeFetchedMessage.message.sendEmail || '-' }}
                    <span v-if="formatTime(activeFetchedMessage.message.createTime || activeFetchedMessage.message.createdAt)">
                      · {{ formatTime(activeFetchedMessage.message.createTime || activeFetchedMessage.message.createdAt) }}
                    </span>
                  </p>
                </div>
                <button @click="closeFetchedDetail" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-semibold text-blue-200 hover:bg-blue-500/20">
                  收起
                </button>
              </div>
              <iframe
                v-if="activeFetchedMessage.message.html || activeFetchedMessage.message.content"
                :srcdoc="mailDetailSrcdoc(activeFetchedMessage.message)"
                sandbox=""
                class="mt-4 h-[42vh] w-full rounded-lg border border-gray-800 bg-white"
              ></iframe>
              <pre v-else class="mt-4 max-h-[42vh] overflow-auto whitespace-pre-wrap rounded-lg border border-gray-800 bg-gray-950 p-4 text-xs leading-5 text-gray-200">{{ activeFetchedMessage.message.text || '无正文' }}</pre>
            </div>
            <div v-for="result in fetchedResults" :key="result.email" class="space-y-3">
              <div class="flex items-center justify-between gap-3">
                <div class="font-mono text-sm text-gray-200">{{ result.email }}</div>
                <span class="rounded-full px-2.5 py-1 text-xs font-semibold" :class="result.status === 'ok' ? 'bg-green-500/10 text-green-300' : 'bg-red-500/10 text-red-300'">
                  {{ result.status === 'ok' ? `返回 ${(result.messages || []).length} 封` : '取件失败' }}
                </span>
              </div>
              <div v-if="result.error" class="rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {{ result.error }}
              </div>
              <div v-else-if="!(result.messages || []).length" class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-4 text-sm text-gray-500">
                收件箱暂无邮件
              </div>
              <div v-else class="max-h-[52vh] space-y-2 overflow-y-auto pr-1">
                <article
                  v-for="message in result.messages"
                  :key="message.id || `${result.email}-${message.subject}`"
                  class="rounded-lg border border-gray-800 bg-gray-950/80 px-3 py-3"
                >
                  <div class="flex flex-wrap items-start justify-between gap-3">
                    <div class="min-w-0">
                      <h4 class="truncate text-sm font-semibold text-white">{{ message.subject || '(无主题)' }}</h4>
                      <p class="mt-1 text-xs text-gray-500">{{ message.sendEmail || '-' }}</p>
                    </div>
                    <div class="text-xs text-gray-500">{{ formatTime(message.createTime || message.createdAt) }}</div>
                  </div>
                  <p v-if="message.text" class="mt-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-gray-300">
                    {{ message.text }}
                  </p>
                  <button
                    @click="openFetchedDetail(result.email, message)"
                    class="mt-2 inline-flex text-xs font-semibold text-blue-300 hover:text-blue-200"
                  >
                    查看详情
                  </button>
                </article>
              </div>
            </div>
          </template>
        </div>

        <div class="flex justify-end gap-3 border-t border-gray-800 px-5 py-4">
          <button @click="closeDialog" class="rounded-lg border border-gray-800 bg-gray-950 px-4 py-2 text-sm font-semibold text-gray-200 hover:bg-gray-800">取消</button>
          <button v-if="!['fetched', 'passwordResult'].includes(dialog)" @click="submitDialog" :disabled="busy" class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:opacity-50">
            {{ busy ? '处理中...' : '确认' }}
          </button>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const rows = ref([])
const summary = ref({ total: 0, enabled_count: 0, disabled_count: 0, valid_count: 0, invalid_count: 0, unchecked_count: 0 })
const selected = ref(new Set())
const busy = ref(false)
const message = ref('')
const messageType = ref('success')
const checkFilter = ref('')
const statusFilter = ref('')
const emailQuery = ref('')
const noteQuery = ref('')
const dialog = ref('')
const importText = ref('')
const editingEmail = ref('')
const form = ref(blankForm())
const dialogEmails = ref([])
const newPassword = ref('')
const newStatus = ref('enabled')
const newNote = ref('')
const fetchedResults = ref([])
const activeFetchedMessage = ref(null)
const passwordResults = ref([])
const passwordSummary = ref({ updated: 0, failed: 0 })
const visiblePasswords = ref(new Set())

const selectedEmails = computed(() => Array.from(selected.value))
const filteredRows = computed(() => {
  const emailNeedle = emailQuery.value.toLowerCase()
  const noteNeedle = noteQuery.value.toLowerCase()
  return rows.value.filter(row => {
    if (checkFilter.value && row.check_status !== checkFilter.value) return false
    if (statusFilter.value && row.status !== statusFilter.value) return false
    if (emailNeedle && !String(row.email || '').toLowerCase().includes(emailNeedle)) return false
    if (noteNeedle && !String(row.note || '').toLowerCase().includes(noteNeedle)) return false
    return true
  })
})
const filteredEmails = computed(() => filteredRows.value.map(row => row.email))
const allFilteredSelected = computed(() => filteredEmails.value.length > 0 && filteredEmails.value.every(email => selected.value.has(email)))
const messageClass = computed(() => messageType.value === 'error'
  ? 'bg-red-500/10 text-red-300'
  : 'bg-green-500/10 text-green-300')
const dialogTitle = computed(() => ({
  import: '导入 mail 邮箱',
  edit: editingEmail.value ? '编辑 mail 邮箱' : '新增 mail 邮箱',
  password: `修改邮箱密码（${dialogEmails.value.length} 个）`,
  passwordResult: '改密结果',
  status: `批量修改状态（${selectedEmails.value.length} 个）`,
  note: `批量备注（${selectedEmails.value.length} 个）`,
  fetched: '取件结果',
})[dialog.value] || '')

function blankForm() {
  return { email: '', gptPassword: '', mailPassword: '', refreshToken: '', status: 'enabled', note: '' }
}

function setMessage(text, type = 'success') {
  message.value = text
  messageType.value = type
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => { message.value = '' }, 8000)
}

function maskPassword(value) {
  const raw = String(value || '')
  if (!raw) return '-'
  if (raw.length <= 2) return '*'.repeat(raw.length)
  return `${raw.slice(0, 1)}${'*'.repeat(Math.max(3, raw.length - 2))}${raw.slice(-1)}`
}

function passwordKey(email, type) {
  return `${String(email || '').toLowerCase()}::${type}`
}

function passwordVisible(email, type) {
  return visiblePasswords.value.has(passwordKey(email, type))
}

function togglePasswordVisible(email, type) {
  const next = new Set(visiblePasswords.value)
  const key = passwordKey(email, type)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  visiblePasswords.value = next
}

function displayPassword(value, email, type) {
  const raw = String(value || '')
  if (!raw) return '-'
  return passwordVisible(email, type) ? raw : maskPassword(raw)
}

function statusLabel(status) {
  return status === 'disabled' ? '禁用' : '启用'
}

function statusClass(status) {
  return status === 'disabled'
    ? 'bg-gray-700/80 text-gray-300'
    : 'bg-green-500/10 text-green-300'
}

function checkLabel(status) {
  return { valid: '有效', invalid: '失效', error: '错误', unchecked: '未检测' }[status] || '未检测'
}

function checkClass(status) {
  if (status === 'valid') return 'bg-green-500/10 text-green-300'
  if (status === 'invalid' || status === 'error') return 'bg-red-500/10 text-red-300'
  return 'bg-gray-700/70 text-gray-300'
}

function syncRows(data) {
  rows.value = data.items || []
  summary.value = {
    total: data.total || rows.value.length,
    enabled_count: data.enabled_count || 0,
    disabled_count: data.disabled_count || 0,
    valid_count: data.valid_count || 0,
    invalid_count: data.invalid_count || 0,
    unchecked_count: data.unchecked_count || 0,
  }
  const existing = new Set(rows.value.map(row => row.email))
  selected.value = new Set(Array.from(selected.value).filter(email => existing.has(email)))
  visiblePasswords.value = new Set(
    Array.from(visiblePasswords.value).filter(key => existing.has(String(key).split('::')[0])),
  )
}

async function loadRows() {
  busy.value = true
  try {
    syncRows(await api.getMailAccounts())
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    busy.value = false
  }
}

function toggleSelected(email) {
  const next = new Set(selected.value)
  if (next.has(email)) next.delete(email)
  else next.add(email)
  selected.value = next
}

function toggleAllFiltered() {
  const next = new Set(selected.value)
  if (allFilteredSelected.value) {
    for (const email of filteredEmails.value) next.delete(email)
  } else {
    for (const email of filteredEmails.value) next.add(email)
  }
  selected.value = next
}

function openImportDialog() {
  importText.value = ''
  dialog.value = 'import'
}

function openEditDialog(row) {
  editingEmail.value = row?.email || ''
  form.value = row
    ? {
        email: row.email || '',
        gptPassword: row.gpt_password || '',
        mailPassword: row.mail_password || '',
        refreshToken: row.refresh_token || '',
        status: row.status || 'enabled',
        note: row.note || '',
      }
    : blankForm()
  dialog.value = 'edit'
}

function openPasswordDialog(emails) {
  dialogEmails.value = emails
  newPassword.value = ''
  passwordResults.value = []
  passwordSummary.value = { updated: 0, failed: 0 }
  dialog.value = 'password'
}

function openStatusDialog() {
  newStatus.value = 'enabled'
  dialog.value = 'status'
}

function openNoteDialog() {
  newNote.value = ''
  dialog.value = 'note'
}

function closeDialog() {
  dialog.value = ''
  activeFetchedMessage.value = null
}

function formatTime(value) {
  const n = Number(value || 0)
  if (!Number.isFinite(n) || n <= 0) return ''
  const ms = n > 10_000_000_000 ? n : n * 1000
  try {
    return new Date(ms).toLocaleString()
  } catch {
    return ''
  }
}

function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function mailDetailSrcdoc(mail) {
  const raw = String(mail?.html || mail?.content || '').trim()
  const body = raw
    ? raw.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    : `<pre style="white-space:pre-wrap;font-family:system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.6">${escapeHtml(mail?.text || '无正文')}</pre>`
  return `<!doctype html>
<html>
<head>
  <base target="_blank">
  <meta charset="utf-8">
  <style>
    body { margin: 16px; color: #111827; font-family: system-ui, -apple-system, Segoe UI, sans-serif; line-height: 1.6; }
    img { max-width: 100%; height: auto; }
    table { max-width: 100%; }
    a { color: #2563eb; }
  </style>
</head>
<body>${body}</body>
</html>`
}

function openFetchedDetail(email, mail) {
  activeFetchedMessage.value = { email, message: mail }
}

function closeFetchedDetail() {
  activeFetchedMessage.value = null
}

async function submitDialog() {
  busy.value = true
  let shouldClose = true
  try {
    if (dialog.value === 'import') {
      const result = await api.importMailAccounts(importText.value)
      syncRows(result)
      setMessage(`导入 ${result.imported || 0} 条，跳过 ${result.skipped || 0} 条`)
    } else if (dialog.value === 'edit') {
      await api.saveMailAccount(form.value, editingEmail.value)
      setMessage('mail 邮箱账号已保存')
      await loadRows()
    } else if (dialog.value === 'password') {
      const result = await api.changeMailAccountPassword(dialogEmails.value, newPassword.value)
      passwordResults.value = result.results || []
      passwordSummary.value = { updated: result.updated || 0, failed: result.failed || 0 }
      setMessage(`改密成功 ${result.updated || 0} 个，失败 ${result.failed || 0} 个`)
      await loadRows()
      if ((result.failed || 0) > 0 || passwordResults.value.length) {
        dialog.value = 'passwordResult'
        shouldClose = false
      }
    } else if (dialog.value === 'status') {
      const result = await api.updateMailAccountStatus(selectedEmails.value, newStatus.value)
      setMessage(`已更新 ${result.updated || 0} 个账号状态`)
      await loadRows()
    } else if (dialog.value === 'note') {
      const result = await api.updateMailAccountNote(selectedEmails.value, newNote.value)
      setMessage(`已更新 ${result.updated || 0} 个账号备注`)
      await loadRows()
    }
    if (shouldClose) closeDialog()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function checkRows(emails) {
  if (!emails.length) return
  busy.value = true
  try {
    const result = await api.checkMailAccounts(emails)
    setMessage(`检测完成：${result.checked || 0} 个账号`)
    await loadRows()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function fetchRows(emails) {
  busy.value = true
  try {
    const result = await api.fetchMailAccounts(emails)
    fetchedResults.value = result.results || []
    activeFetchedMessage.value = null
    dialog.value = 'fetched'
    const count = fetchedResults.value.reduce((sum, item) => sum + ((item.messages || []).length), 0)
    setMessage(`取件完成：${result.fetched || 0} 个账号，返回 ${count} 封邮件`)
    await loadRows()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function deleteRows(emails) {
  if (!emails.length || !window.confirm(`确认删除 ${emails.length} 个 mail 邮箱账号？`)) return
  busy.value = true
  try {
    const result = await api.deleteMailAccounts(emails)
    setMessage(`已删除 ${result.deleted || 0} 个账号`)
    await loadRows()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function clearRows() {
  if (!window.confirm('确认清空全部 mail 邮箱账号？')) return
  busy.value = true
  try {
    const result = await api.clearMailAccounts()
    selected.value = new Set()
    setMessage(`已清空 ${result.deleted || 0} 个账号`)
    await loadRows()
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    busy.value = false
  }
}

async function exportRows() {
  try {
    const result = await api.exportMailAccounts()
    const blob = new Blob([result.content || ''], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `mail-accounts-${new Date().toISOString().slice(0, 10)}.txt`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  } catch (e) {
    setMessage(e.message, 'error')
  }
}

onMounted(loadRows)
</script>
