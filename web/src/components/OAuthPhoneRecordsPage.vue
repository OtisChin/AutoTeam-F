<template>
  <div class="oauth-records-workspace">
    <UiPageHeader title="OAuth 取号记录" eyebrow="授权 / 手机记录" description="动态接码平台取号、价格、绑定账号和完成状态。">
      <template #actions><UiButton variant="secondary" :loading="loading" @click="loadRecords">{{ loading ? '刷新中...' : '刷新' }}</UiButton></template>
    </UiPageHeader>

    <UiMetricSummary label="取号指标" :items="metricItems" />

    <UiDataToolbar
      :result-label="`${filteredRecords.length} / ${records.length} 条记录`"
      :active-filter-count="keyword ? 1 : 0"
      clearable
      @clear-filters="keyword = ''"
    >
      <template #filters><label class="ui-inline-field"><span>搜索记录</span><input v-model.trim="keyword" type="search" placeholder="手机号 / 邮箱 / activation / 服务商" /></label></template>
    </UiDataToolbar>

    <div v-if="message" class="ui-inline-message" :class="messageOk ? 'ui-inline-message-success' : 'ui-inline-message-error'" role="status">{{ message }}</div>

    <UiTableFrame label="OAuth 取号记录" :busy="loading" :empty="!filteredRecords.length" min-width="1120px">
      <template #header><span class="ui-table-frame-meta">窗口 {{ pagedRecords.length }} 条 / 总计 {{ filteredRecords.length }} 条</span></template>
      <template #empty>
        <UiStatePanel v-if="loading" state="loading" title="正在加载取号记录" message="读取最近 500 条记录…" />
        <UiStatePanel v-else-if="loadError" state="error" title="取号记录加载失败" :message="loadError" action-label="重试" @action="loadRecords" />
        <UiStatePanel v-else state="empty" title="暂无匹配记录" message="调整搜索条件或等待新的 OAuth 取号任务。" />
      </template>
      <table class="ui-data-table">
        <thead><tr><th>时间</th><th>服务商</th><th>手机号</th><th>国家 / 服务</th><th>价格</th><th>账号</th><th>Activation</th><th>状态</th><th>原因</th></tr></thead>
        <tbody>
          <tr v-for="item in pagedRecords" :key="item.id || `${item.created_at}-${item.phone_number}-${item.activation_id}`">
            <td class="ui-table-subtext">{{ fmtTime(item.created_at) }}</td>
            <td><UiStatusBadge :label="item.provider || '-'" tone="info" /></td>
            <td><strong class="ui-input-mono">{{ formatPhone(item.phone_number) }}</strong></td>
            <td><strong>{{ item.country || '-' }}</strong><small class="ui-table-subtext">{{ item.service || '-' }}</small></td>
            <td><strong class="ui-input-mono">{{ priceText(item) }}</strong><small class="ui-table-subtext">{{ item.price_source || '-' }}</small></td>
            <td class="ui-table-note" :title="item.email || ''">{{ item.email || '-' }}</td>
            <td class="ui-table-note ui-input-mono">{{ item.activation_id || '-' }}</td>
            <td><UiStatusBadge :label="statusLabel(item.status)" :tone="statusTone(item.status)" /></td>
            <td class="ui-table-note" :title="item.reason || ''">{{ item.reason || '-' }}</td>
          </tr>
        </tbody>
      </table>
      <template #footer v-if="filteredRecords.length"><UiPagination v-model:page="page" v-model:page-size="pageSize" :page-sizes="[50, 100, 200]" :total-items="filteredRecords.length" item-label="条记录" /></template>
    </UiTableFrame>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import UiDataToolbar from './ui/UiDataToolbar.vue'
import UiButton from './ui/UiButton.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiPagination from './ui/UiPagination.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'
import UiTableFrame from './ui/UiTableFrame.vue'

const OAUTH_PHONE_RECORDS_PAGE_SIZE = 100
const loading = ref(false)
const records = ref([])
const summary = ref({ total: 0, success_count: 0, active_count: 0, cancelled_count: 0, failed_count: 0 })
const keyword = ref('')
const message = ref('')
const messageOk = ref(true)
const loadError = ref('')
const page = ref(1)
const pageSize = ref(OAUTH_PHONE_RECORDS_PAGE_SIZE)

function setMessage(text, ok = true) { message.value = text; messageOk.value = ok }

async function loadRecords() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try {
    const result = await api.getOAuthPhoneRecords(500)
    records.value = Array.isArray(result?.items) ? result.items : []
    summary.value = result || {}
    page.value = 1
    setMessage('')
  } catch (error) {
    loadError.value = error?.message || '加载取号记录失败'
    setMessage(loadError.value, false)
  } finally { loading.value = false }
}

const filteredRecords = computed(() => {
  const q = keyword.value.toLowerCase()
  if (!q) return records.value
  return records.value.filter(item => [item.provider, item.phone_number, item.email, item.activation_id, item.status, item.reason, item.country, item.service].some(value => String(value || '').toLowerCase().includes(q)))
})
const totalPages = computed(() => Math.max(1, Math.ceil(filteredRecords.value.length / Math.max(1, Number(pageSize.value) || OAUTH_PHONE_RECORDS_PAGE_SIZE))))
const pagedRecords = computed(() => {
  const currentPage = Math.min(totalPages.value, Math.max(1, Number(page.value) || 1))
  const size = Math.max(1, Number(pageSize.value) || OAUTH_PHONE_RECORDS_PAGE_SIZE)
  return filteredRecords.value.slice((currentPage - 1) * size, currentPage * size)
})
const metricItems = computed(() => [
  { key: 'total', label: '总记录', value: Number(summary.value.total || records.value.length), tone: 'neutral' },
  { key: 'success', label: '成功', value: Number(summary.value.success_count || 0), tone: 'success' },
  { key: 'active', label: '取号中', value: Number(summary.value.active_count || 0), tone: 'info' },
  { key: 'cancelled', label: '已取消', value: Number(summary.value.cancelled_count || 0), tone: 'warning' },
  { key: 'failed', label: '失败 / 冷却', value: Number(summary.value.failed_count || 0), tone: 'danger' },
])

watch([filteredRecords, pageSize], () => {
  // Filtering and page-size changes can invalidate the current page; clamp it
  // synchronously so the table never renders an empty out-of-range window.
  page.value = Math.min(Math.max(1, Number(page.value) || 1), totalPages.value)
})

function fmtTime(value) { const ts = Number(value || 0); return ts ? new Date(ts * 1000).toLocaleString() : '-' }
function formatPhone(value) { const text = String(value || '').trim(); return text ? (text.startsWith('+') ? text : `+${text}`) : '-' }
function priceText(item) { const price = String(item.price || '').trim(); if (price) return `${price} ${item.currency || ''}`.trim(); const limit = String(item.price_limit || '').trim(); return limit ? `<= ${limit}` : '-' }
function statusLabel(status) { return { acquired: '已取号', success: '成功', success_reusable: '成功可复用', released: '已释放', cancelled: '已取消', failed: '失败', invalid: '失效', cooldown: '冷却' }[String(status || '')] || status || '-' }
function statusTone(status) { const value = String(status || ''); if (value.startsWith('success')) return 'success'; if (value === 'acquired') return 'info'; if (value === 'cancelled' || value === 'released') return 'warning'; return 'danger' }

onMounted(loadRecords)
</script>
