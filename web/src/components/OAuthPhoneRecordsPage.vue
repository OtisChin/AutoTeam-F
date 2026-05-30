<template>
  <div class="space-y-5">
    <div class="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
      <div>
        <h2 class="text-xl font-bold text-white">OAuth 取号记录</h2>
        <p class="mt-1 text-sm text-gray-400">记录动态接码平台取号、价格、绑定账号和完成状态。</p>
      </div>
      <button
        @click="loadRecords"
        :disabled="loading"
        class="self-start rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm text-gray-200 hover:bg-gray-800 disabled:opacity-50"
      >
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <div class="grid grid-cols-2 gap-3 md:grid-cols-5">
      <div v-for="card in statCards" :key="card.label" class="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <div class="text-xs text-gray-500">{{ card.label }}</div>
        <div class="mt-2 text-2xl font-bold" :class="card.class">{{ card.value }}</div>
      </div>
    </div>

    <div class="rounded-xl border border-gray-800 bg-gray-900">
      <div class="flex flex-col gap-3 border-b border-gray-800 p-4 md:flex-row md:items-center md:justify-between">
        <div>
          <h3 class="font-semibold text-white">记录列表</h3>
          <p class="mt-1 text-xs text-gray-500">最新记录在前；动态平台完成后的号码通常只在这里和服务商历史订单中可见。</p>
        </div>
        <input
          v-model.trim="keyword"
          type="text"
          placeholder="搜索手机号 / 邮箱 / activation / 服务商"
          class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500 md:w-80"
        />
      </div>

      <div v-if="message" class="mx-4 mt-4 rounded-lg px-3 py-2 text-sm" :class="messageOk ? 'bg-emerald-500/10 text-emerald-300' : 'bg-rose-500/10 text-rose-300'">
        {{ message }}
      </div>

      <div class="overflow-x-auto">
        <table class="min-w-full text-left text-sm">
          <thead class="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="px-4 py-3">时间</th>
              <th class="px-4 py-3">服务商</th>
              <th class="px-4 py-3">手机号</th>
              <th class="px-4 py-3">国家/服务</th>
              <th class="px-4 py-3">价格</th>
              <th class="px-4 py-3">账号</th>
              <th class="px-4 py-3">Activation</th>
              <th class="px-4 py-3">状态</th>
              <th class="px-4 py-3">原因</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800">
            <tr v-if="!filteredRecords.length">
              <td colspan="9" class="px-4 py-10 text-center text-gray-500">暂无取号记录</td>
            </tr>
            <tr v-for="item in filteredRecords" :key="item.id" class="text-gray-300 hover:bg-gray-800/40">
              <td class="whitespace-nowrap px-4 py-3 text-xs text-gray-500">{{ fmtTime(item.created_at) }}</td>
              <td class="px-4 py-3">
                <span class="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-xs font-semibold text-cyan-300">
                  {{ item.provider || '-' }}
                </span>
              </td>
              <td class="whitespace-nowrap px-4 py-3 font-mono text-gray-100">{{ formatPhone(item.phone_number) }}</td>
              <td class="whitespace-nowrap px-4 py-3 text-xs">
                <div class="text-gray-200">{{ item.country || '-' }}</div>
                <div class="text-gray-500">{{ item.service || '-' }}</div>
              </td>
              <td class="whitespace-nowrap px-4 py-3">
                <div class="font-mono text-gray-100">{{ priceText(item) }}</div>
                <div class="text-xs text-gray-500">{{ item.price_source || '-' }}</div>
              </td>
              <td class="max-w-[260px] truncate px-4 py-3 font-mono text-xs text-gray-300">{{ item.email || '-' }}</td>
              <td class="whitespace-nowrap px-4 py-3 font-mono text-xs text-gray-400">{{ item.activation_id || '-' }}</td>
              <td class="px-4 py-3">
                <span class="rounded-full border px-2 py-1 text-xs font-semibold" :class="statusClass(item.status)">
                  {{ statusLabel(item.status) }}
                </span>
              </td>
              <td class="max-w-[260px] truncate px-4 py-3 text-xs text-gray-500">{{ item.reason || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

const loading = ref(false)
const records = ref([])
const summary = ref({ total: 0, success_count: 0, active_count: 0, cancelled_count: 0, failed_count: 0 })
const keyword = ref('')
const message = ref('')
const messageOk = ref(true)

function setMessage(text, ok = true) {
  message.value = text
  messageOk.value = ok
}

async function loadRecords() {
  loading.value = true
  try {
    const result = await api.getOAuthPhoneRecords(500)
    records.value = result.items || []
    summary.value = result
    setMessage('')
  } catch (error) {
    setMessage(error.message || '加载取号记录失败', false)
  } finally {
    loading.value = false
  }
}

const statCards = computed(() => [
  { label: '总记录', value: summary.value.total || 0, class: 'text-white' },
  { label: '成功', value: summary.value.success_count || 0, class: 'text-emerald-400' },
  { label: '取号中', value: summary.value.active_count || 0, class: 'text-cyan-400' },
  { label: '已取消', value: summary.value.cancelled_count || 0, class: 'text-amber-300' },
  { label: '失败/冷却', value: summary.value.failed_count || 0, class: 'text-rose-400' },
])

const filteredRecords = computed(() => {
  const q = keyword.value.toLowerCase()
  if (!q) return records.value
  return records.value.filter(item => [
    item.provider,
    item.phone_number,
    item.email,
    item.activation_id,
    item.status,
    item.reason,
  ].some(value => String(value || '').toLowerCase().includes(q)))
})

function fmtTime(value) {
  const ts = Number(value || 0)
  if (!ts) return '-'
  return new Date(ts * 1000).toLocaleString()
}

function formatPhone(value) {
  const text = String(value || '').trim()
  if (!text) return '-'
  return text.startsWith('+') ? text : `+${text}`
}

function priceText(item) {
  const price = String(item.price || '').trim()
  if (price) return `${price} ${item.currency || ''}`.trim()
  const limit = String(item.price_limit || '').trim()
  return limit ? `<= ${limit}` : '-'
}

function statusLabel(status) {
  return {
    acquired: '已取号',
    success: '成功',
    success_reusable: '成功可复用',
    released: '已释放',
    cancelled: '已取消',
    failed: '失败',
    invalid: '失效',
    cooldown: '冷却',
  }[String(status || '')] || status || '-'
}

function statusClass(status) {
  const value = String(status || '')
  if (value.startsWith('success')) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (value === 'acquired') return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300'
  if (value === 'cancelled' || value === 'released') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
}

onMounted(loadRecords)
</script>
