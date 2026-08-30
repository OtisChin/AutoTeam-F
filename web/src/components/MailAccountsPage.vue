<template>
  <div class="mail-workspace">
    <UiPageHeader title="邮箱管理" eyebrow="账号 / Mail" description="集中管理 mail.com 账号、检测状态与收件结果">
      <template #actions>
        <UiButton variant="primary" @click="openImportDialog">导入邮箱</UiButton>
        <UiButton variant="secondary" @click="openEditDialog(null)">新增</UiButton>
      </template>
    </UiPageHeader>

    <UiMetricSummary :items="metricItems" label="邮箱指标" />

    <UiDataToolbar
      :result-label="`${filteredRows.length} / ${rows.length} 条记录`"
      :active-filter-count="activeFilterCount"
      clearable
      @clear-filters="clearFilters"
    >
      <template #primary>
        <UiButton variant="secondary" size="sm" :disabled="busy || !filteredRows.length" :loading="busy" @click="checkRows(filteredEmails)">全部检测</UiButton>
      </template>
      <template #filters>
        <label class="ui-inline-field"><span>检测状态</span><select v-model="checkFilter"><option value="">全部</option><option value="valid">有效</option><option value="invalid">失效</option><option value="unchecked">未检测</option></select></label>
        <label class="ui-inline-field"><span>账号状态</span><select v-model="statusFilter"><option value="">全部</option><option value="enabled">启用</option><option value="disabled">禁用</option></select></label>
        <label class="ui-inline-field"><span>邮箱</span><input v-model.trim="emailQuery" type="search" placeholder="搜索邮箱" /></label>
        <label class="ui-inline-field"><span>备注</span><input v-model.trim="noteQuery" type="search" placeholder="搜索备注" /></label>
      </template>
      <template #actions>
        <UiButton variant="quiet" size="sm" @click="exportRows">导出</UiButton>
        <UiButton variant="danger" size="sm" :disabled="busy || !rows.length" @click="requestClearRows">清空全部</UiButton>
      </template>
    </UiDataToolbar>

    <UiBatchBar :count="selectedEmails.length" :busy="busy" @clear="clearSelection">
      <UiButton variant="secondary" size="sm" :disabled="!selectedEmails.length || busy" @click="openStatusDialog">批量状态</UiButton>
      <UiButton variant="secondary" size="sm" :disabled="!selectedEmails.length || busy" @click="openNoteDialog">批量备注</UiButton>
      <UiButton variant="secondary" size="sm" :disabled="!selectedEmails.length || busy" @click="openPasswordDialog(selectedEmails)">批量改密</UiButton>
    </UiBatchBar>

    <div v-if="message" class="ui-inline-message" :class="`ui-inline-message-${messageType}`" role="status">{{ message }}</div>
    <UiStatePanel v-if="!hasLoaded && busy" state="loading" title="正在加载邮箱" message="读取账号列表…" />
    <UiStatePanel v-else-if="loadError && !rows.length" state="error" title="邮箱列表加载失败" :message="loadError" action-label="重试" @action="loadRows" />
    <UiStatePanel v-else-if="!filteredRows.length" state="empty" title="暂无匹配账号" message="调整筛选条件或导入新的 mail.com 账号。" />
    <UiStatePanel v-else-if="loadError" state="partial" title="显示上次成功数据" :message="loadError" />

    <UiTableFrame label="邮箱账号" :busy="busy" :empty="!filteredRows.length" min-width="1180px">
      <template #header><span class="ui-table-frame-meta">窗口 {{ pagedRows.length }} 条 / 总计 {{ filteredRows.length }} 条</span></template>
      <table class="ui-data-table">
        <thead><tr><th><input type="checkbox" :checked="allFilteredSelected" aria-label="选择全部筛选结果" @change="toggleAllFiltered" /></th><th>#</th><th>邮箱</th><th>邮箱密码</th><th>GPT 密码</th><th>状态</th><th>检测</th><th>备注</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="(row, index) in pagedRows" :key="row.email">
            <td><input type="checkbox" :checked="selected.has(row.email)" :aria-label="`选择 ${row.email}`" @change="toggleSelected(row.email)" /></td>
            <td class="ui-table-index">{{ accountPageOffset + index + 1 }}</td>
            <td><strong>{{ row.email }}</strong><small class="ui-table-subtext" :title="row.refresh_token">RT {{ row.refresh_token_masked || '-' }}</small></td>
            <td><button type="button" class="ui-reveal-button" :title="passwordVisible(row.email, 'mail') ? '隐藏邮箱密码' : '显示邮箱密码'" @click="togglePasswordVisible(row.email, 'mail')">{{ displayPassword(row.mail_password, row.email, 'mail') }}</button></td>
            <td><button type="button" class="ui-reveal-button" :title="passwordVisible(row.email, 'gpt') ? '隐藏 GPT 密码' : '显示 GPT 密码'" @click="togglePasswordVisible(row.email, 'gpt')">{{ displayPassword(row.gpt_password, row.email, 'gpt') }}</button></td>
            <td><UiStatusBadge :label="statusPresentation(row.status).label" :tone="statusPresentation(row.status).tone" /></td>
            <td><UiStatusBadge :label="checkPresentation(row.check_status).label" :tone="checkPresentation(row.check_status).tone" /><small v-if="row.last_error" class="ui-table-error" :title="row.last_error">{{ row.last_error }}</small></td>
            <td class="ui-table-note">{{ row.note || '-' }}</td>
            <td><UiButton variant="quiet" size="sm" :disabled="busy" @click="openRowActions(row)">操作</UiButton></td>
          </tr>
        </tbody>
      </table>
      <template #footer><UiPagination v-model:page="accountPage" v-model:page-size="accountPageSize" :page-sizes="MAIL_PAGE_SIZE_OPTIONS" :total-items="filteredRows.length" item-label="条邮箱" /></template>
    </UiTableFrame>

    <AccessibleModal v-if="dialog" :label="dialogTitle" @close="closeDialog">
      <section class="ui-modal-card">
        <header class="ui-modal-header"><h2>{{ dialogTitle }}</h2><UiButton variant="quiet" size="sm" aria-label="关闭" @click="closeDialog">关闭</UiButton></header>
        <div class="ui-modal-body">
          <template v-if="dialog === 'rowActions'">
            <p class="ui-muted">为 {{ rowActionEmails[0] }} 选择操作。</p>
            <div class="ui-action-grid"><UiButton variant="secondary" :disabled="busy" @click="runRowAction('check')">检测</UiButton><UiButton variant="secondary" :disabled="busy" @click="runRowAction('fetch')">取件</UiButton><UiButton variant="secondary" @click="runRowAction('edit')">编辑</UiButton><UiButton variant="danger" @click="runRowAction('delete')">删除</UiButton></div>
          </template>
          <template v-else-if="dialog === 'import'"><p class="ui-muted">每行格式：邮箱----邮箱密码----chatgpt密码，也兼容旧格式。</p><textarea v-model="importText" rows="9" class="ui-input ui-input-mono" placeholder="name@mail.com----mail-pass----gpt-pass" /></template>
          <template v-else-if="dialog === 'edit'"><div class="ui-form-grid"><UiFormField id="mail-email" label="邮箱" required><template #default="{ inputId, disabled }"><input :id="inputId" v-model.trim="form.email" type="email" class="ui-input" :disabled="disabled || !!editingEmail" /></template></UiFormField><UiFormField id="mail-status" label="状态"><template #default="{ inputId }"><select :id="inputId" v-model="form.status" class="ui-input"><option value="enabled">启用</option><option value="disabled">禁用</option></select></template></UiFormField><UiFormField id="mail-gpt-password" label="GPT 密码"><template #default="{ inputId }"><input :id="inputId" v-model="form.gptPassword" class="ui-input" /></template></UiFormField><UiFormField id="mail-password" label="邮箱密码"><template #default="{ inputId }"><input :id="inputId" v-model="form.mailPassword" class="ui-input" /></template></UiFormField></div><UiFormField id="mail-refresh-token" label="OpenAI refreshToken"><template #default="{ inputId }"><textarea :id="inputId" v-model.trim="form.refreshToken" rows="3" class="ui-input ui-input-mono" /></template></UiFormField><UiFormField id="mail-note" label="备注"><template #default="{ inputId }"><input :id="inputId" v-model="form.note" class="ui-input" /></template></UiFormField></template>
          <template v-else-if="dialog === 'password'"><p class="ui-muted">将通过协议登录 mail.com 官网修改密码。</p><UiFormField id="mail-new-password" label="新密码" required><template #default="{ inputId }"><input :id="inputId" v-model="newPassword" class="ui-input" /></template></UiFormField></template>
          <template v-else-if="dialog === 'passwordResult'"><div class="ui-result-summary">成功 {{ passwordSummary.updated || 0 }} 个，失败 {{ passwordSummary.failed || 0 }} 个</div><div class="ui-result-list"><article v-for="item in pagedPasswordResults" :key="item.email" class="ui-result-row"><strong>{{ item.email }}</strong><UiStatusBadge :label="item.status === 'success' ? '成功' : '失败'" :tone="item.status === 'success' ? 'success' : 'danger'" /><p>{{ item.status === 'success' ? '官网改密成功，已更新本地 SQLite' : (item.error || '官网改密失败') }}</p></article></div><UiPagination v-if="passwordResults.length" v-model:page="passwordPage" v-model:page-size="passwordPageSize" :page-sizes="MAIL_PAGE_SIZE_OPTIONS" :total-items="passwordResults.length" item-label="条结果" /></template>
          <template v-else-if="dialog === 'status'"><p class="ui-muted">将为选中的 {{ selectedEmails.length }} 个账号修改状态。</p><select v-model="newStatus" class="ui-input"><option value="enabled">启用</option><option value="disabled">禁用</option></select></template>
          <template v-else-if="dialog === 'note'"><p class="ui-muted">将为选中的 {{ selectedEmails.length }} 个账号设置备注。</p><input v-model="newNote" class="ui-input" placeholder="输入备注" /></template>
          <template v-else-if="dialog === 'fetched'"><div v-if="!fetchedResults.length" class="ui-empty">没有返回邮件</div><div v-if="activeFetchedMessage" class="ui-mail-detail"><h3>{{ activeFetchedMessage.message.subject || '(无主题)' }}</h3><p>{{ activeFetchedMessage.email }}</p><iframe v-if="activeFetchedMessage.message.html || activeFetchedMessage.message.content" :srcdoc="mailDetailSrcdoc(activeFetchedMessage.message)" sandbox="" class="ui-mail-frame" /><pre v-else>{{ activeFetchedMessage.message.text || '无正文' }}</pre></div><div class="ui-result-list"><article v-for="entry in pagedFetchedRows" :key="`${entry.result.email || 'mail'}-${entry.message?.id || entry.messageIndex}`" class="ui-result-row"><strong>{{ entry.result.email }}</strong><UiStatusBadge :label="entry.result.status === 'ok' ? `返回 ${(entry.result.messages || []).length} 封` : '取件失败'" :tone="entry.result.status === 'ok' ? 'success' : 'danger'" /><p v-if="entry.result.error">{{ entry.result.error }}</p><p v-else-if="entry.message">{{ entry.message.subject || '(无主题)' }}</p><UiButton v-if="entry.message" variant="quiet" size="sm" @click="openFetchedDetail(entry.result.email, entry.message)">查看详情</UiButton></article></div><UiPagination v-if="fetchedRowCount" v-model:page="fetchedPage" v-model:page-size="fetchedPageSize" :page-sizes="MAIL_PAGE_SIZE_OPTIONS" :total-items="fetchedRowCount" item-label="条邮件" /></template>
          <template v-else-if="dialog === 'confirm-delete'"><p>确认删除 {{ rowActionEmails.length }} 个 mail 邮箱账号？</p></template>
          <template v-else-if="dialog === 'confirm-clear'"><p>确认清空全部 mail 邮箱账号？此操作不可撤销。</p></template>
        </div>
        <footer class="ui-modal-footer"><UiButton variant="quiet" @click="closeDialog">取消</UiButton><UiButton v-if="['confirm-delete','confirm-clear'].includes(dialog)" variant="danger" :loading="busy" @click="confirmDestructiveAction">确认删除</UiButton><UiButton v-else-if="!['rowActions','fetched','passwordResult'].includes(dialog)" variant="primary" :loading="busy" @click="submitDialog">确认</UiButton></footer>
      </section>
    </AccessibleModal>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { createMessageClearScheduler } from '../messageLifecycle.js'
import { accountHubSyncPresentation, mailAccountStatusPresentation, mailCheckStatusPresentation } from '../operationsPresentation.js'
import AccessibleModal from './AccessibleModal.vue'
import UiBatchBar from './ui/UiBatchBar.vue'
import UiButton from './ui/UiButton.vue'
import UiDataToolbar from './ui/UiDataToolbar.vue'
import UiFormField from './ui/UiFormField.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiPagination from './ui/UiPagination.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'
import UiTableFrame from './ui/UiTableFrame.vue'

const DEFAULT_MAIL_PAGE_SIZE = 100
const MAIL_PAGE_SIZE_OPTIONS = Object.freeze([50, 100, 200, 500])
const MAIL_AUTH_SESSION_BATCH_MAX_ITEMS = 1_000
const MAIL_ACCOUNT_BATCH_MAX_ITEMS = 2_000

const emit = defineEmits(['task-started'])

const rows = ref([])
const summary = ref({ total: 0, enabled_count: 0, disabled_count: 0, valid_count: 0, invalid_count: 0, unchecked_count: 0 })
const selected = ref(new Set())
const busy = ref(false)
const message = ref('')
const messageType = ref('success')
const hasLoaded = ref(false)
const loadError = ref('')
const messageClearScheduler = createMessageClearScheduler()
const checkFilter = ref('')
const statusFilter = ref('')
const emailQuery = ref('')
const noteQuery = ref('')
const accountPage = ref(1)
const accountPageSize = ref(DEFAULT_MAIL_PAGE_SIZE)
const dialog = ref('')
const importText = ref('')
const editingEmail = ref('')
const form = ref(blankForm())
const dialogEmails = ref([])
const newPassword = ref('')
const newStatus = ref('enabled')
const newNote = ref('')
const fetchedResults = ref([])
const fetchedPage = ref(1)
const fetchedPageSize = ref(DEFAULT_MAIL_PAGE_SIZE)
const activeFetchedMessage = ref(null)
const passwordResults = ref([])
const passwordSummary = ref({ updated: 0, failed: 0 })
const passwordPage = ref(1)
const passwordPageSize = ref(DEFAULT_MAIL_PAGE_SIZE)
const visiblePasswords = ref(new Set())
const rowActionEmails = ref([])

const selectedEmails = computed(() => Array.from(selected.value))
const activeFilterCount = computed(() => [checkFilter.value, statusFilter.value, emailQuery.value, noteQuery.value].filter(Boolean).length)
const metricItems = computed(() => [
  { key: 'total', label: '总数', value: summary.value.total, tone: 'neutral' },
  { key: 'enabled', label: '启用', value: summary.value.enabled_count, tone: 'success' },
  { key: 'valid', label: '有效', value: summary.value.valid_count, tone: 'info' },
  { key: 'invalid', label: '失效', value: summary.value.invalid_count, tone: 'danger' },
  { key: 'selected', label: '选中', value: selectedEmails.value.length, tone: 'warning' },
])
const batchSelectionLimitError = computed(() => mailAccountBatchLimitError(selectedEmails.value))
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
const effectiveAccountPageSize = computed(() => normalizeMailPageSize(accountPageSize.value))
const accountTotalPages = computed(() => Math.max(1, Math.ceil(filteredRows.value.length / effectiveAccountPageSize.value)))
const accountPageOffset = computed(() => (clampPage(accountPage.value, accountTotalPages.value) - 1) * effectiveAccountPageSize.value)
const pagedRows = computed(() => pageRows(filteredRows.value, accountPage.value, effectiveAccountPageSize.value))
const allFilteredSelected = computed(() => filteredEmails.value.length > 0 && filteredEmails.value.every(email => selected.value.has(email)))
const fetchedWindow = computed(() => buildFetchedPage(fetchedResults.value, fetchedPage.value, fetchedPageSize.value))
const pagedFetchedRows = computed(() => fetchedWindow.value.rows)
const fetchedRowCount = computed(() => fetchedWindow.value.totalRows)
const fetchedTotalPages = computed(() => fetchedWindow.value.totalPages)
const effectivePasswordPageSize = computed(() => normalizeMailPageSize(passwordPageSize.value))
const passwordTotalPages = computed(() => Math.max(1, Math.ceil(passwordResults.value.length / effectivePasswordPageSize.value)))
const pagedPasswordResults = computed(() => pageRows(passwordResults.value, passwordPage.value, effectivePasswordPageSize.value))
const messageClass = computed(() => {
  if (messageType.value === 'error') return 'bg-red-500/10 text-red-300'
  if (messageType.value === 'warning') return 'bg-amber-500/10 text-amber-200'
  return 'bg-green-500/10 text-green-300'
})
const dialogTitle = computed(() => ({
  import: '导入 mail 邮箱',
  edit: editingEmail.value ? '编辑 mail 邮箱' : '新增 mail 邮箱',
  password: `修改邮箱密码（${dialogEmails.value.length} 个）`,
  passwordResult: '改密结果',
  status: `批量修改状态（${selectedEmails.value.length} 个）`,
  note: `批量备注（${selectedEmails.value.length} 个）`,
  fetched: '取件结果',
  rowActions: '账号操作',
  'confirm-delete': '确认删除',
  'confirm-clear': '确认清空',
})[dialog.value] || '')

watch([checkFilter, statusFilter, emailQuery, noteQuery, accountPageSize], () => {
  accountPage.value = 1
})

watch(accountTotalPages, value => {
  accountPage.value = clampPage(accountPage.value, value)
}, { flush: 'sync' })

watch(fetchedPageSize, () => {
  fetchedPage.value = 1
})

watch(fetchedTotalPages, value => {
  fetchedPage.value = clampPage(fetchedPage.value, value)
}, { flush: 'sync' })

watch(passwordPageSize, () => {
  passwordPage.value = 1
})

watch(passwordTotalPages, value => {
  passwordPage.value = clampPage(passwordPage.value, value)
}, { flush: 'sync' })

function normalizeMailPageSize(value) {
  const size = Number(value)
  return MAIL_PAGE_SIZE_OPTIONS.includes(size) ? size : DEFAULT_MAIL_PAGE_SIZE
}

function clampPage(value, totalPages) {
  const lastPage = Math.max(1, Math.trunc(Number(totalPages) || 1))
  const page = Math.max(1, Math.trunc(Number(value) || 1))
  return Math.min(page, lastPage)
}

function pageRows(items, page, pageSize) {
  const source = Array.isArray(items) ? items : []
  const size = normalizeMailPageSize(pageSize)
  const totalPages = Math.max(1, Math.ceil(source.length / size))
  const currentPage = clampPage(page, totalPages)
  const start = (currentPage - 1) * size
  return source.slice(start, start + size)
}

function buildFetchedPage(results, page, pageSize) {
  const source = Array.isArray(results) ? results : []
  const size = normalizeMailPageSize(pageSize)
  let totalRows = 0
  for (const result of source) {
    const messages = Array.isArray(result?.messages) ? result.messages : []
    totalRows += result?.error ? 1 : Math.max(1, messages.length)
  }

  const totalPages = Math.max(1, Math.ceil(totalRows / size))
  const currentPage = clampPage(page, totalPages)
  const start = (currentPage - 1) * size
  const end = start + size
  const visible = []
  let offset = 0

  for (const result of source) {
    const messages = Array.isArray(result?.messages) ? result.messages : []
    const resultRowCount = result?.error ? 1 : Math.max(1, messages.length)
    const resultStart = offset
    const resultEnd = resultStart + resultRowCount
    offset = resultEnd

    if (resultEnd <= start) continue
    if (resultStart >= end) break

    if (result?.error || !messages.length) {
      visible.push({ result, message: null, messageIndex: -1 })
      continue
    }

    const messageStart = Math.max(0, start - resultStart)
    const messageEnd = Math.min(messages.length, end - resultStart)
    for (let messageIndex = messageStart; messageIndex < messageEnd; messageIndex += 1) {
      visible.push({ result, message: messages[messageIndex], messageIndex })
    }
  }

  return { rows: visible, totalRows, totalPages, page: currentPage, pageSize: size }
}

function planMailAuthSessionLogin(emails) {
  const source = Array.isArray(emails) ? emails : []
  const supportedEmails = source.slice(0, MAIL_AUTH_SESSION_BATCH_MAX_ITEMS)
  return {
    emails: supportedEmails,
    total: source.length,
    deferred: Math.max(0, source.length - supportedEmails.length),
  }
}

function mailAccountBatchLimitError(emails) {
  const count = Array.isArray(emails) ? emails.length : 0
  if (count <= MAIL_ACCOUNT_BATCH_MAX_ITEMS) return ''
  return `已选择 ${count} 个 mail 邮箱账号，单次最多支持 ${MAIL_ACCOUNT_BATCH_MAX_ITEMS} 个；请筛选或取消部分选择后重试。`
}

function formatMailImportOutcome(result, loginPlan, loginError = '') {
  const imported = Number(result?.imported || 0)
  const skipped = Number(result?.skipped || 0)
  const started = Number(loginPlan?.emails?.length || 0)
  const deferred = Number(loginPlan?.deferred || 0)
  const base = `导入 ${imported} 条，跳过 ${skipped} 条`
  if (loginError) {
    const deferredMessage = deferred > 0
      ? `；另有 ${deferred} 个因单批上限 ${MAIL_AUTH_SESSION_BATCH_MAX_ITEMS} 未启动`
      : ''
    return `${base}；导入已完成，但后续 auth_session 登录启动失败：${String(loginError)}${deferredMessage}`
  }
  if (!started) return base
  if (deferred > 0) {
    return `${base}；auth_session 登录仅启动前 ${started} 个，剩余 ${deferred} 个未启动（单批上限 ${MAIL_AUTH_SESSION_BATCH_MAX_ITEMS}）`
  }
  return `${base}，已启动 ${started} 个登陆获取 auth_session`
}

function ensureMailAccountBatchWithinLimit(emails) {
  const error = mailAccountBatchLimitError(emails)
  if (!error) return true
  setMessage(error, 'error')
  return false
}

function currentMailAccountDialogBatchEmails() {
  if (dialog.value === 'password') return dialogEmails.value
  if (dialog.value === 'status' || dialog.value === 'note') return selectedEmails.value
  return null
}

function blankForm() {
  return { email: '', gptPassword: '', mailPassword: '', refreshToken: '', status: 'enabled', note: '' }
}

function setMessage(text, type = 'success') {
  message.value = text
  messageType.value = type
  messageClearScheduler.schedule(8000, { read: () => message.value, clear: () => { message.value = '' } })
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
  return mailAccountStatusPresentation(status).label
}

function statusClass(status) {
  return mailAccountStatusPresentation(status).tone
}

function checkLabel(status) {
  return mailCheckStatusPresentation(status).label
}

function checkClass(status) {
  return mailCheckStatusPresentation(status).tone
}

function statusPresentation(status) { return mailAccountStatusPresentation(status) }
function checkPresentation(status) { return mailCheckStatusPresentation(status) }

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
    loadError.value = ''
    hasLoaded.value = true
  } catch (e) {
    loadError.value = e?.message || '读取邮箱列表失败'
    hasLoaded.value = true
    setMessage(loadError.value, 'error')
  } finally {
    busy.value = false
  }
}

function clearSelection() { selected.value = new Set() }
function clearFilters() { checkFilter.value = ''; statusFilter.value = ''; emailQuery.value = ''; noteQuery.value = '' }
function openRowActions(row) { rowActionEmails.value = row?.email ? [row.email] : []; dialog.value = 'rowActions' }
async function runRowAction(action) {
  const emails = rowActionEmails.value.slice()
  closeDialog()
  if (action === 'check') return checkRows(emails)
  if (action === 'fetch') return fetchRows(emails)
  if (action === 'edit') return openEditDialog(rows.value.find(row => row.email === emails[0]))
  if (action === 'delete') { rowActionEmails.value = emails; dialog.value = 'confirm-delete' }
}
function requestClearRows() { dialog.value = 'confirm-clear' }
async function confirmDestructiveAction() {
  const action = dialog.value
  const emails = rowActionEmails.value.slice()
  closeDialog()
  if (action === 'confirm-clear') return clearRows(true)
  if (action === 'confirm-delete') return deleteRows(emails, true)
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
  const dialogBatchEmails = currentMailAccountDialogBatchEmails()
  if (dialogBatchEmails && !ensureMailAccountBatchWithinLimit(dialogBatchEmails)) return
  busy.value = true
  let shouldClose = true
  try {
    if (dialog.value === 'import') {
      const result = await api.importMailAccounts(importText.value)
      syncRows(result)
      const loginEmails = Array.isArray(result.login_emails)
        ? result.login_emails.map(email => String(email || '').trim().toLowerCase()).filter(Boolean)
        : []
      const loginPlan = planMailAuthSessionLogin(loginEmails)
      let importMessage = formatMailImportOutcome(result, loginPlan)
      let importMessageType = loginPlan.deferred > 0 ? 'warning' : 'success'
      if (loginPlan.emails.length) {
        try {
          await api.loginMailAccountsAuthSession(loginPlan.emails)
          emit('task-started')
        } catch (loginError) {
          importMessage = formatMailImportOutcome(result, loginPlan, loginError.message)
          importMessageType = 'warning'
        }
      }
      setMessage(importMessage, importMessageType)
    } else if (dialog.value === 'edit') {
      await api.saveMailAccount(form.value, editingEmail.value)
      setMessage('mail 邮箱账号已保存')
      await loadRows()
    } else if (dialog.value === 'password') {
      const result = await api.changeMailAccountPassword(dialogEmails.value, newPassword.value)
      passwordPage.value = 1
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
  if (!emails.length || !ensureMailAccountBatchWithinLimit(emails)) return
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
  if (!emails.length || !ensureMailAccountBatchWithinLimit(emails)) return
  busy.value = true
  try {
    const result = await api.fetchMailAccounts(emails)
    fetchedPage.value = 1
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

async function deleteRows(emails, confirmed = false) {
  if (!emails.length || !ensureMailAccountBatchWithinLimit(emails)) return
  if (!confirmed) { rowActionEmails.value = emails.slice(); dialog.value = 'confirm-delete'; return }
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

async function clearRows(confirmed = false) {
  if (!confirmed) { dialog.value = 'confirm-clear'; return }
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
onBeforeUnmount(() => { messageClearScheduler.dispose() })
</script>
