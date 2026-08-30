<template>
  <div class="space-y-5">
    <UiPageHeader title="OAuth 手机号" eyebrow="授权 / 手机池" description="管理固定号码、接码链接和 OAuth 绑定额度。">
      <template #actions><UiButton variant="secondary" :loading="loading" @click="loadItems">{{ loading ? '刷新中...' : '刷新' }}</UiButton></template>
    </UiPageHeader>
    <UiMetricSummary label="手机号池指标" :items="metricItems" />
    <UiDataToolbar :result-label="`${filteredItems.length} / ${items.length} 条记录`" :active-filter-count="keyword ? 1 : 0" clearable @clear-filters="keyword = ''">
      <template #filters><label class="ui-inline-field"><span>搜索手机号池</span><input v-model.trim="keyword" type="search" placeholder="手机号 / 接码链接 / 账号" /></label></template>
    </UiDataToolbar>
    <UiBatchBar v-if="selectedIds.length" :count="selectedIds.length" :busy="saving" @clear="selectedIds = []">
      <UiButton variant="danger" size="sm" :disabled="!selectedIds.length || saving" @click="deleteSelected">删除已选</UiButton>
    </UiBatchBar>

    <div v-if="message" class="ui-inline-message" :class="messageOk ? 'ui-inline-message-success' : 'ui-inline-message-error'" role="status">{{ message }}</div>
    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 class="font-semibold text-white">新增手机号</h3>
          <p class="mt-1 text-xs text-gray-500">如果号码已经绑定过账号，可以手动填写“已绑定次数”。</p>
        </div>
      </div>
      <div class="grid gap-3 md:grid-cols-[1fr_1.7fr_120px_120px]">
        <input v-model.trim="newItem.phone_number" aria-label="新手机号" type="text" placeholder="+17328582987" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
        <input v-model.trim="newItem.sms_url" aria-label="新手机号接码链接" type="text" placeholder="https://example.com/api/record?token=..." class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
        <input v-model.number="newItem.bound_count" aria-label="新手机号已绑定次数" type="number" min="0" max="3" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
        <button @click="addItem" :disabled="saving || !newItem.phone_number || !newItem.sms_url" class="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50">
          {{ saving ? '保存中...' : '添加' }}
        </button>
      </div>
    </section>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div class="mb-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 class="font-semibold text-white">批量导入</h3>
          <p class="mt-1 text-xs text-gray-500">格式：手机号----接码链接，或 12096968188|接码链接；纯数字会自动补 +，导入时按手机号去重。</p>
        </div>
        <button @click="importItems" :disabled="saving || !importText.trim()" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50">
          导入并去重
        </button>
      </div>
      <textarea v-model="importText" aria-label="批量导入手机号内容" rows="4" spellcheck="false" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-sm text-white outline-none focus:border-blue-500" placeholder="+17328582987-------https://www.8652abc.com/adminapi/jsscript/smsInfo/ABC_sms?key=...
12096968188|https://smscloud.sbs/api/system/get_sms/7ebf82030f3c461fbe75fbe0d1ae65b7"></textarea>
    </section>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div class="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h3 class="font-semibold text-white">手机号列表</h3>
          <p class="mt-1 text-xs text-gray-500">状态会随 OAuth 绑定结果自动更新；已满或失效号码不会再被取用。</p>
        </div>
        <div class="flex flex-wrap gap-2">
        </div>
      </div>

      <UiStatePanel v-if="loadError && filteredItems.length" state="partial" title="显示上次成功数据" :message="loadError" />
      <UiTableFrame label="手机号列表" :busy="loading" :empty="!pagedItems.length" min-width="980px">
      <template #header><span class="ui-table-frame-meta">窗口 {{ pagedItems.length }} 条 / 总计 {{ filteredItems.length }} 条</span></template>
      <template #empty>
        <UiStatePanel v-if="loading && !items.length" state="loading" title="正在加载手机号池" message="读取号码和绑定状态…" />
        <UiStatePanel v-else-if="loadError" state="error" title="手机号池加载失败" :message="loadError" action-label="重试" @action="loadItems" />
        <UiStatePanel v-else state="empty" title="暂无匹配号码" message="添加号码或调整搜索条件。" />
      </template>
      <div class="overflow-x-auto rounded-lg border border-gray-800">
        <table class="min-w-full text-sm">
          <thead class="bg-gray-950 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="w-10 px-3 py-3"><input type="checkbox" class="accent-blue-500" aria-label="选择当前页全部手机号" :checked="allVisibleSelected" @change="toggleAllVisible" /></th>
              <th class="px-3 py-3">状态</th>
              <th class="px-3 py-3">手机号</th>
              <th class="px-3 py-3">接码链接</th>
              <th class="px-3 py-3">已绑定</th>
              <th class="px-3 py-3">绑定账号</th>
              <th class="px-3 py-3">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800">
            <tr v-for="item in pagedItems" :key="item.id" class="align-top hover:bg-gray-800/30">
              <td class="px-3 py-3"><input v-model="selectedIds" type="checkbox" class="accent-blue-500" :aria-label="`选择手机号 ${item.phone_number || item.id}`" :value="item.id" /></td>
              <td class="px-3 py-3">
                <select v-model="draftFor(item).status" :aria-label="`手机号 ${item.phone_number || item.id} 状态`" class="rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500">
                  <option value="available">可用</option>
                  <option value="cooldown">冷却</option>
                  <option value="invalid">失效</option>
                  <option value="disabled">停用</option>
                  <option value="full">已满</option>
                </select>
                <div class="mt-2"><UiStatusBadge :label="statusLabel(item.status)" :tone="statusTone(item.status)" /></div>
                <div v-if="item.status === 'cooldown'" class="mt-1 text-[11px] text-amber-300/80">
                  剩余 {{ formatCooldown(item.cooldown_remaining_seconds) }}
                </div>
              </td>
              <td class="px-3 py-3">
                <input v-model.trim="draftFor(item).phone_number" :aria-label="`手机号 ${item.phone_number || item.id}`" class="w-44 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-blue-500" />
              </td>
              <td class="px-3 py-3">
                <input v-model.trim="draftFor(item).sms_url" :aria-label="`手机号 ${item.phone_number || item.id} 接码链接`" class="min-w-[360px] rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-blue-500" />
                <input v-model.trim="draftFor(item).invalid_reason" :aria-label="`手机号 ${item.phone_number || item.id} 失效原因或备注`" class="mt-2 min-w-[360px] rounded-lg border border-gray-800 bg-gray-950/80 px-2 py-1.5 text-xs text-gray-300 outline-none focus:border-blue-500" placeholder="失效原因 / 备注" />
              </td>
              <td class="px-3 py-3">
                <input v-model.number="draftFor(item).bound_count" :aria-label="`手机号 ${item.phone_number || item.id} 已绑定次数`" type="number" min="0" max="3" class="w-20 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500" />
                <div class="mt-2 text-xs text-gray-500">剩余 {{ item.remaining }}</div>
              </td>
              <td class="max-w-xs px-3 py-3">
                <div class="space-y-1">
                  <span v-for="email in item.bound_emails" :key="email" class="inline-block rounded border border-gray-700 bg-gray-950 px-2 py-1 font-mono text-[11px] text-gray-300">{{ email }}</span>
                  <span v-if="!item.bound_emails?.length" class="text-xs text-gray-600">-</span>
                </div>
              </td>
              <td class="px-3 py-3">
                <div class="flex gap-2">
                  <button @click="saveItem(item.id)" :disabled="saving" class="rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-500 disabled:opacity-50">保存</button>
                  <button @click="deleteItems([item.id])" :disabled="saving" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      </UiTableFrame>
      <UiPagination v-if="filteredItems.length" v-model:page="page" :page-size="OAUTH_PHONE_PAGE_SIZE" :page-sizes="[100]" :total-items="filteredItems.length" item-label="条手机号" />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '../api.js'
import UiBatchBar from './ui/UiBatchBar.vue'
import UiButton from './ui/UiButton.vue'
import UiDataToolbar from './ui/UiDataToolbar.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiPagination from './ui/UiPagination.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'
import UiTableFrame from './ui/UiTableFrame.vue'

const OAUTH_PHONE_PAGE_SIZE = 100
const items = ref([])
const summary = reactive({ total: 0, available_count: 0, full_count: 0, cooldown_count: 0, invalid_count: 0, disabled_count: 0 })
const drafts = reactive({})
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const messageOk = ref(true)
const loadError = ref('')
const keyword = ref('')
const importText = ref('')
const selectedIds = ref([])
const page = ref(1)
const newItem = reactive({ phone_number: '', sms_url: '', bound_count: 0, status: 'available' })

const metricItems = computed(() => [
  { key: 'available', label: '可用', value: summary.available_count, tone: 'success' },
  { key: 'full', label: '已满', value: summary.full_count, tone: 'info' },
  { key: 'cooldown', label: '冷却', value: summary.cooldown_count, tone: 'warning' },
  { key: 'invalid', label: '失效', value: summary.invalid_count, tone: 'danger' },
  { key: 'total', label: '总数', value: summary.total, tone: 'neutral' },
])

const filteredItems = computed(() => {
  const q = keyword.value.toLowerCase()
  if (!q) return items.value
  return items.value.filter((item) => [
    item.phone_number,
    item.sms_url,
    item.status,
    item.invalid_reason,
    ...(item.bound_emails || []),
  ].some((value) => String(value || '').toLowerCase().includes(q)))
})

const totalPages = computed(() => Math.max(1, Math.ceil(filteredItems.value.length / OAUTH_PHONE_PAGE_SIZE)))
const pagedItems = computed(() => {
  const start = (page.value - 1) * OAUTH_PHONE_PAGE_SIZE
  return filteredItems.value.slice(start, start + OAUTH_PHONE_PAGE_SIZE)
})

const allVisibleSelected = computed(() => {
  const visible = pagedItems.value.map((item) => item.id)
  return visible.length > 0 && visible.every((id) => selectedIds.value.includes(id))
})

function draftFor(item) {
  if (drafts[item.id]) return drafts[item.id]
  drafts[item.id] = {
    id: item.id,
    phone_number: item.phone_number || '',
    sms_url: item.sms_url || '',
    status: item.status || 'available',
    bound_count: Number(item.bound_count || 0),
    bound_emails: item.bound_emails || [],
    invalid_reason: item.invalid_reason || '',
    cooldown_until: item.cooldown_until || null,
    note: item.note || '',
  }
  return drafts[item.id]
}

function setMessage(text, ok = true) {
  message.value = text
  messageOk.value = ok
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => { message.value = '' }, 7000)
}

function applyItems(payload) {
  const nextItems = Array.isArray(payload?.items) ? payload.items : []
  items.value = nextItems
  page.value = 1
  summary.total = Number(payload?.total ?? nextItems.length)
  summary.available_count = Number(payload?.available_count ?? nextItems.filter((item) => item.status === 'available').length)
  summary.full_count = Number(payload?.full_count ?? nextItems.filter((item) => item.status === 'full').length)
  summary.cooldown_count = Number(payload?.cooldown_count ?? nextItems.filter((item) => item.status === 'cooldown').length)
  summary.invalid_count = Number(payload?.invalid_count ?? nextItems.filter((item) => item.status === 'invalid').length)
  summary.disabled_count = Number(payload?.disabled_count ?? nextItems.filter((item) => item.status === 'disabled').length)
  for (const id of Object.keys(drafts)) delete drafts[id]
  const nextIds = new Set(nextItems.map((item) => item.id))
  selectedIds.value = selectedIds.value.filter((id) => nextIds.has(id))
}

async function loadItems() {
  loading.value = true
  loadError.value = ''
  try {
    applyItems(await api.getOAuthPhonePool())
  } catch (error) {
    loadError.value = error.message || '加载手机号池失败'
    setMessage(loadError.value, false)
  } finally {
    loading.value = false
  }
}

async function addItem() {
  saving.value = true
  try {
    await api.saveOAuthPhonePoolItem({ ...newItem })
    newItem.phone_number = ''
    newItem.sms_url = ''
    newItem.bound_count = 0
    setMessage('手机号已添加')
    await loadItems()
  } catch (error) {
    setMessage(error.message || '添加手机号失败', false)
  } finally {
    saving.value = false
  }
}

async function importItems() {
  saving.value = true
  try {
    const result = await api.importOAuthPhonePool(importText.value)
    importText.value = ''
    setMessage(`导入完成：新增 ${result.added_count || 0}，跳过重复 ${result.skipped_count || 0}`)
    await loadItems()
  } catch (error) {
    setMessage(error.message || '导入失败', false)
  } finally {
    saving.value = false
  }
}

async function saveItem(id) {
  saving.value = true
  try {
    await api.saveOAuthPhonePoolItem({ ...drafts[id], id })
    setMessage('手机号已保存')
    await loadItems()
  } catch (error) {
    setMessage(error.message || '保存失败', false)
  } finally {
    saving.value = false
  }
}

async function deleteItems(ids) {
  if (!ids.length) return
  saving.value = true
  try {
    await api.deleteOAuthPhonePoolItems(ids)
    setMessage(`已删除 ${ids.length} 个手机号`)
    await loadItems()
  } catch (error) {
    setMessage(error.message || '删除失败', false)
  } finally {
    saving.value = false
  }
}

function deleteSelected() {
  deleteItems([...selectedIds.value])
}

function toggleAllVisible(event) {
  const visible = pagedItems.value.map((item) => item.id)
  if (event.target.checked) {
    selectedIds.value = Array.from(new Set([...selectedIds.value, ...visible]))
  } else {
    const visibleSet = new Set(visible)
    selectedIds.value = selectedIds.value.filter((id) => !visibleSet.has(id))
  }
}

watch(keyword, () => { page.value = 1 })
watch(totalPages, (value) => {
  if (page.value > value) page.value = value
})

function statusLabel(status) {
  return { available: '可用', full: '已满', cooldown: '冷却', invalid: '失效', disabled: '停用' }[status] || status || '-'
}

function statusTone(status) {
  if (status === 'available') return 'success'
  if (status === 'full') return 'info'
  if (status === 'cooldown') return 'warning'
  if (status === 'invalid') return 'danger'
  return 'neutral'
}

function formatCooldown(seconds) {
  const total = Math.max(0, Number(seconds || 0))
  if (!total) return '0 分钟'
  const minutes = Math.ceil(total / 60)
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (hours > 0) return `${hours} 小时${rest ? ` ${rest} 分钟` : ''}`
  return `${minutes} 分钟`
}

onMounted(loadItems)
</script>
