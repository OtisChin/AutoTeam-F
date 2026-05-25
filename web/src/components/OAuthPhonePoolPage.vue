<template>
  <div class="space-y-5">
    <div class="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h2 class="text-xl font-bold text-white">OAuth 手机号</h2>
        <p class="mt-1 text-sm text-gray-400">用于 OAuth 登录遇到 add-phone 时自动绑定；每个手机号最多绑定 3 个 ChatGPT 账号。</p>
      </div>
      <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatCard label="可用" :value="summary.available_count" class-name="text-emerald-300" />
        <StatCard label="已满" :value="summary.full_count" class-name="text-blue-300" />
        <StatCard label="失效" :value="summary.invalid_count" class-name="text-rose-300" />
        <StatCard label="总数" :value="summary.total" class-name="text-gray-100" />
      </div>
    </div>

    <div v-if="message" class="rounded-lg border px-4 py-3 text-sm" :class="messageOk ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/20 bg-rose-500/10 text-rose-300'">
      {{ message }}
    </div>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div class="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 class="font-semibold text-white">新增手机号</h3>
          <p class="mt-1 text-xs text-gray-500">如果号码已经绑定过账号，可以手动填写“已绑定次数”。</p>
        </div>
        <button @click="loadItems" :disabled="loading" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
      </div>
      <div class="grid gap-3 md:grid-cols-[1fr_1.7fr_120px_120px]">
        <input v-model.trim="newItem.phone_number" type="text" placeholder="+17328582987" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
        <input v-model.trim="newItem.sms_url" type="text" placeholder="https://example.com/api/record?token=..." class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
        <input v-model.number="newItem.bound_count" type="number" min="0" max="3" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
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
      <textarea v-model="importText" rows="4" spellcheck="false" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-sm text-white outline-none focus:border-blue-500" placeholder="+17328582987-------https://www.8652abc.com/adminapi/jsscript/smsInfo/ABC_sms?key=...
12096968188|https://smscloud.sbs/api/system/get_sms/7ebf82030f3c461fbe75fbe0d1ae65b7"></textarea>
    </section>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4">
      <div class="mb-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <h3 class="font-semibold text-white">手机号列表</h3>
          <p class="mt-1 text-xs text-gray-500">状态会随 OAuth 绑定结果自动更新；已满或失效号码不会再被取用。</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <input v-model.trim="keyword" type="text" placeholder="搜索手机号 / 接码链接 / 账号" class="w-64 max-w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
          <button @click="deleteSelected" :disabled="saving || !selectedIds.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">
            批量删除
          </button>
        </div>
      </div>

      <div class="overflow-x-auto rounded-lg border border-gray-800">
        <table class="min-w-full text-sm">
          <thead class="bg-gray-950 text-left text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="w-10 px-3 py-3"><input type="checkbox" class="accent-blue-500" :checked="allVisibleSelected" @change="toggleAllVisible" /></th>
              <th class="px-3 py-3">状态</th>
              <th class="px-3 py-3">手机号</th>
              <th class="px-3 py-3">接码链接</th>
              <th class="px-3 py-3">已绑定</th>
              <th class="px-3 py-3">绑定账号</th>
              <th class="px-3 py-3">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800">
            <tr v-if="!filteredItems.length">
              <td colspan="7" class="px-3 py-10 text-center text-gray-500">暂无手机号</td>
            </tr>
            <tr v-for="item in filteredItems" :key="item.id" class="align-top hover:bg-gray-800/30">
              <td class="px-3 py-3"><input v-model="selectedIds" type="checkbox" class="accent-blue-500" :value="item.id" /></td>
              <td class="px-3 py-3">
                <select v-model="drafts[item.id].status" class="rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500">
                  <option value="available">可用</option>
                  <option value="invalid">失效</option>
                  <option value="disabled">停用</option>
                  <option value="full">已满</option>
                </select>
                <div class="mt-2 flex items-center gap-2 text-xs" :class="statusClass(item.status)">
                  <span class="h-2 w-2 rounded-full" :class="statusDotClass(item.status)"></span>
                  {{ statusLabel(item.status) }}
                </div>
              </td>
              <td class="px-3 py-3">
                <input v-model.trim="drafts[item.id].phone_number" class="w-44 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-blue-500" />
              </td>
              <td class="px-3 py-3">
                <input v-model.trim="drafts[item.id].sms_url" class="min-w-[360px] rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-blue-500" />
                <input v-model.trim="drafts[item.id].invalid_reason" class="mt-2 min-w-[360px] rounded-lg border border-gray-800 bg-gray-950/80 px-2 py-1.5 text-xs text-gray-300 outline-none focus:border-blue-500" placeholder="失效原因 / 备注" />
              </td>
              <td class="px-3 py-3">
                <input v-model.number="drafts[item.id].bound_count" type="number" min="0" max="3" class="w-20 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500" />
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
    </section>
  </div>
</template>

<script setup>
import { computed, h, onMounted, reactive, ref } from 'vue'
import { api } from '../api.js'

const items = ref([])
const summary = reactive({ total: 0, available_count: 0, full_count: 0, invalid_count: 0, disabled_count: 0 })
const drafts = reactive({})
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const messageOk = ref(true)
const keyword = ref('')
const importText = ref('')
const selectedIds = ref([])
const newItem = reactive({ phone_number: '', sms_url: '', bound_count: 0, status: 'available' })

const StatCard = (props) => h('div', { class: 'min-w-24 rounded-xl border border-gray-800 bg-gray-900 px-4 py-3' }, [
  h('div', { class: 'text-xs text-gray-500' }, props.label),
  h('div', { class: `mt-1 text-2xl font-bold ${props.className || 'text-white'}` }, String(props.value ?? 0)),
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

const allVisibleSelected = computed(() => {
  const visible = filteredItems.value.map((item) => item.id)
  return visible.length > 0 && visible.every((id) => selectedIds.value.includes(id))
})

function setMessage(text, ok = true) {
  message.value = text
  messageOk.value = ok
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => { message.value = '' }, 7000)
}

function applyItems(payload) {
  const nextItems = Array.isArray(payload?.items) ? payload.items : []
  items.value = nextItems
  summary.total = Number(payload?.total ?? nextItems.length)
  summary.available_count = Number(payload?.available_count ?? nextItems.filter((item) => item.status === 'available').length)
  summary.full_count = Number(payload?.full_count ?? nextItems.filter((item) => item.status === 'full').length)
  summary.invalid_count = Number(payload?.invalid_count ?? nextItems.filter((item) => item.status === 'invalid').length)
  summary.disabled_count = Number(payload?.disabled_count ?? nextItems.filter((item) => item.status === 'disabled').length)
  for (const item of nextItems) {
    drafts[item.id] = {
      id: item.id,
      phone_number: item.phone_number || '',
      sms_url: item.sms_url || '',
      status: item.status || 'available',
      bound_count: Number(item.bound_count || 0),
      bound_emails: item.bound_emails || [],
      invalid_reason: item.invalid_reason || '',
      note: item.note || '',
    }
  }
  selectedIds.value = selectedIds.value.filter((id) => nextItems.some((item) => item.id === id))
}

async function loadItems() {
  loading.value = true
  try {
    applyItems(await api.getOAuthPhonePool())
  } catch (error) {
    setMessage(error.message || '加载手机号池失败', false)
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
  const visible = filteredItems.value.map((item) => item.id)
  if (event.target.checked) {
    selectedIds.value = Array.from(new Set([...selectedIds.value, ...visible]))
  } else {
    const visibleSet = new Set(visible)
    selectedIds.value = selectedIds.value.filter((id) => !visibleSet.has(id))
  }
}

function statusLabel(status) {
  return { available: '可用', full: '已满', invalid: '失效', disabled: '停用' }[status] || status || '-'
}

function statusClass(status) {
  return {
    available: 'text-emerald-300',
    full: 'text-blue-300',
    invalid: 'text-rose-300',
    disabled: 'text-gray-400',
  }[status] || 'text-gray-400'
}

function statusDotClass(status) {
  return {
    available: 'bg-emerald-400',
    full: 'bg-blue-400',
    invalid: 'bg-rose-400',
    disabled: 'bg-gray-500',
  }[status] || 'bg-gray-500'
}

onMounted(loadItems)
</script>
