<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" @click.self="close">
      <section class="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
        <header class="flex shrink-0 flex-col gap-4 border-b border-gray-800 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h3 class="text-lg font-semibold text-white">ICE 手机号池</h3>
            <p class="mt-1 text-xs text-gray-500">每个运行中的 ICE 任务独占一个号码，任务结束后自动释放。</p>
          </div>
          <div class="flex items-center gap-2">
            <button type="button" :disabled="loading" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700 disabled:opacity-50" @click="loadPool">
              {{ loading ? '刷新中...' : '刷新' }}
            </button>
            <button type="button" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-300 hover:bg-gray-700" @click="close">关闭</button>
          </div>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <div class="grid grid-cols-2 border-b border-gray-800 sm:grid-cols-5">
            <div v-for="item in statItems" :key="item.label" class="border-r border-gray-800 px-4 py-3 last:border-r-0">
              <div class="text-xs text-gray-500">{{ item.label }}</div>
              <div class="mt-1 text-xl font-semibold" :class="item.color">{{ item.value }}</div>
            </div>
          </div>

          <div v-if="message" class="mx-5 mt-4 rounded-lg border px-4 py-3 text-sm" :class="messageOk ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/20 bg-rose-500/10 text-rose-300'">
            {{ message }}
          </div>

          <div class="grid gap-5 p-5 lg:grid-cols-2">
            <section>
              <h4 class="text-sm font-semibold text-white">新增号码</h4>
              <div class="mt-3 space-y-3">
                <input v-model.trim="newItem.phone_number" type="text" placeholder="手机号，例如 08080051197" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                <input v-model.trim="newItem.sms_api" type="text" placeholder="https://.../getphonecode?order_no=..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-blue-500" />
                <div class="flex gap-3">
                  <input v-model.trim="newItem.note" type="text" placeholder="备注（可选）" class="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                  <button type="button" :disabled="saving || !newItem.phone_number || !newItem.sms_api" class="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50" @click="addPhone">
                    添加
                  </button>
                </div>
              </div>
            </section>

            <section>
              <div class="flex items-center justify-between gap-3">
                <h4 class="text-sm font-semibold text-white">批量导入</h4>
                <button type="button" :disabled="saving || !importText.trim()" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50" @click="importPhones">
                  导入
                </button>
              </div>
              <textarea v-model="importText" rows="5" spellcheck="false" class="mt-3 w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-xs text-white outline-none focus:border-blue-500" placeholder="手机号----接码 API&#10;手机号|接码 API"></textarea>
            </section>
          </div>

          <section class="border-t border-gray-800 p-5">
            <div class="mb-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <h4 class="text-sm font-semibold text-white">号码列表</h4>
                <p class="mt-1 text-xs text-gray-500">停用和错误号码不会被任务分配。</p>
              </div>
              <button type="button" :disabled="saving || !selectedIds.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-200 hover:bg-rose-500/20 disabled:opacity-50" @click="deletePhones(selectedIds)">
                删除所选 ({{ selectedIds.length }})
              </button>
            </div>

            <div class="overflow-x-auto rounded-lg border border-gray-800">
              <table class="w-full min-w-[980px] text-left text-sm">
                <thead class="bg-gray-950 text-xs text-gray-500">
                  <tr>
                    <th class="w-10 px-3 py-3"><input type="checkbox" class="accent-blue-500" :checked="allSelected" @change="toggleAll" /></th>
                    <th class="px-3 py-3 font-medium">状态</th>
                    <th class="px-3 py-3 font-medium">手机号</th>
                    <th class="px-3 py-3 font-medium">接码 API</th>
                    <th class="px-3 py-3 font-medium">备注</th>
                    <th class="px-3 py-3 font-medium">当前任务</th>
                    <th class="px-3 py-3 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-800">
                  <tr v-if="!items.length">
                    <td colspan="7" class="px-3 py-12 text-center text-gray-500">{{ loading ? '正在加载...' : '手机号池为空' }}</td>
                  </tr>
                  <tr v-for="item in items" :key="item.id" class="align-top text-gray-300">
                    <td class="px-3 py-3"><input v-model="selectedIds" type="checkbox" :value="item.id" class="accent-blue-500" :disabled="item.status === 'in_use'" /></td>
                    <td class="px-3 py-3">
                      <select v-model="drafts[item.id].status" :disabled="item.status === 'in_use'" class="rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500 disabled:opacity-50">
                        <option value="available">可用</option>
                        <option value="disabled">停用</option>
                        <option value="error">错误</option>
                      </select>
                    </td>
                    <td class="px-3 py-3">
                      <input v-model.trim="drafts[item.id].phone_number" :disabled="item.status === 'in_use'" class="w-40 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-blue-500 disabled:opacity-50" />
                    </td>
                    <td class="px-3 py-3">
                      <input v-model.trim="drafts[item.id].sms_api" :disabled="item.status === 'in_use'" class="min-w-[330px] rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 font-mono text-xs text-white outline-none focus:border-blue-500 disabled:opacity-50" />
                    </td>
                    <td class="px-3 py-3">
                      <input v-model.trim="drafts[item.id].note" :disabled="item.status === 'in_use'" class="w-40 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1.5 text-xs text-white outline-none focus:border-blue-500 disabled:opacity-50" />
                      <div v-if="item.error_message" class="mt-1 max-w-40 text-[11px] text-rose-300">{{ item.error_message }}</div>
                    </td>
                    <td class="px-3 py-3 font-mono text-xs text-gray-500">{{ item.current_job_id || '-' }}</td>
                    <td class="px-3 py-3">
                      <div class="flex gap-2">
                        <button type="button" :disabled="saving || item.status === 'in_use'" class="rounded-lg bg-blue-600 px-3 py-1.5 text-xs text-white hover:bg-blue-500 disabled:opacity-50" @click="savePhone(item.id)">保存</button>
                        <button type="button" :disabled="saving || item.status === 'in_use'" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50" @click="deletePhones([item.id])">删除</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({ open: Boolean })
const emit = defineEmits(['close', 'stats'])

const items = ref([])
const stats = ref({ total: 0, available: 0, in_use: 0, disabled: 0, error: 0 })
const drafts = reactive({})
const newItem = reactive({ phone_number: '', sms_api: '', note: '' })
const importText = ref('')
const selectedIds = ref([])
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const messageOk = ref(true)

const statItems = computed(() => [
  { label: '总数', value: stats.value.total || 0, color: 'text-gray-100' },
  { label: '可用', value: stats.value.available || 0, color: 'text-emerald-300' },
  { label: '使用中', value: stats.value.in_use || 0, color: 'text-blue-300' },
  { label: '停用', value: stats.value.disabled || 0, color: 'text-gray-400' },
  { label: '错误', value: stats.value.error || 0, color: 'text-rose-300' },
])
const selectableIds = computed(() => items.value.filter(item => item.status !== 'in_use').map(item => item.id))
const allSelected = computed(() => selectableIds.value.length > 0 && selectableIds.value.every(id => selectedIds.value.includes(id)))

watch(() => props.open, value => {
  if (value) loadPool()
})

function close() {
  emit('close')
}

function applyPayload(payload) {
  items.value = Array.isArray(payload?.items) ? payload.items : []
  stats.value = payload?.stats || stats.value
  for (const item of items.value) {
    drafts[item.id] = {
      phone_number: item.phone_number || '',
      sms_api: item.sms_api || '',
      status: item.status === 'in_use' ? 'available' : (item.status || 'available'),
      note: item.note || '',
      error_message: item.error_message || '',
    }
  }
  selectedIds.value = selectedIds.value.filter(id => selectableIds.value.includes(id))
  emit('stats', stats.value)
}

function notify(text, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function loadPool() {
  loading.value = true
  try {
    applyPayload(await api.getPayPalIcePhonePool())
  } catch (error) {
    notify(error.message || '加载手机号池失败', false)
  } finally {
    loading.value = false
  }
}

async function addPhone() {
  saving.value = true
  try {
    applyPayload(await api.addPayPalIcePhone({ ...newItem }))
    newItem.phone_number = ''
    newItem.sms_api = ''
    newItem.note = ''
    notify('手机号已添加')
  } catch (error) {
    notify(error.message || '添加手机号失败', false)
  } finally {
    saving.value = false
  }
}

async function importPhones() {
  saving.value = true
  try {
    const result = await api.importPayPalIcePhones(importText.value)
    importText.value = ''
    notify(result.message || '导入完成')
    await loadPool()
  } catch (error) {
    notify(error.message || '导入失败', false)
  } finally {
    saving.value = false
  }
}

async function savePhone(id) {
  saving.value = true
  try {
    await api.updatePayPalIcePhone(id, { ...drafts[id] })
    notify('手机号已保存')
    await loadPool()
  } catch (error) {
    notify(error.message || '保存失败', false)
  } finally {
    saving.value = false
  }
}

async function deletePhones(ids) {
  if (!ids.length) return
  saving.value = true
  try {
    applyPayload(await api.deletePayPalIcePhones([...ids]))
    notify(`已删除 ${ids.length} 个手机号`)
  } catch (error) {
    notify(error.message || '删除失败', false)
  } finally {
    saving.value = false
  }
}

function toggleAll(event) {
  selectedIds.value = event.target.checked ? [...selectableIds.value] : []
}
</script>
