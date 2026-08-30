<template>
  <div class="trade-workspace">
    <UiPageHeader title="交易管理" eyebrow="商务 / Trade" description="生成 Plus 提取 CDK，查看额度、提取记录和有效状态。">
      <template #actions><UiButton variant="secondary" :loading="loading" @click="load">{{ loading ? '刷新中...' : '刷新' }}</UiButton></template>
    </UiPageHeader>
    <UiMetricSummary label="交易指标" :items="metricItems" />
    <div v-if="message" class="ui-inline-message" :class="messageClass" role="status">{{ message }}</div>
    <UiStatePanel v-if="loading && !summary" state="loading" title="正在加载交易数据" message="读取库存与 CDK 列表…" />
    <UiStatePanel v-else-if="!loading && !summary" state="error" title="交易数据暂时不可用" message="请检查服务连接后重试。" action-label="重试" @action="load" />

    <div class="trade-layout">
      <UiSurface as="section" variant="panel" padding="lg" labelledby="trade-create-heading">
        <template #header><div><h2 id="trade-create-heading" class="ui-surface-heading">生成 CDK</h2><p class="ui-surface-subtitle">创建一组可控额度的 Plus 提取凭证。</p></div></template>
        <UiFormField id="trade-quota" label="可提取 Plus 账号数" required help="至少 1 个账号。"><template #default="{ inputId }"><input :id="inputId" v-model.number="quotaTotal" type="number" min="1" class="ui-input" /></template></UiFormField>
        <UiFormField id="trade-note" label="备注" help="订单号或买家标记，可稍后在列表中查看。"><template #default="{ inputId }"><input :id="inputId" v-model.trim="note" type="text" placeholder="订单号或买家标记" class="ui-input" /></template></UiFormField>
        <UiButton variant="primary" :loading="creating" :disabled="!quotaTotal || quotaTotal < 1" @click="createCdk">生成 CDK</UiButton>
        <div v-if="createdCode" class="trade-created-code" role="status"><UiStatusBadge label="最新生成" tone="success" /><code>{{ createdCode }}</code><UiButton variant="quiet" size="sm" @click="copyText(createdCode)">复制</UiButton></div>
      </UiSurface>

      <UiTableFrame label="CDK 列表" :busy="loading" :empty="!pagedCdks.length" min-width="1120px">
        <template #header><span class="ui-table-frame-meta">窗口 {{ pagedCdks.length }} 条 / 共 {{ cdks.length }} 条</span></template>
        <table class="ui-data-table"><thead><tr><th>CDK</th><th>状态</th><th>额度</th><th>提取密码</th><th>最近提取</th><th>过期时间</th><th>备注</th><th>操作</th></tr></thead>
          <tbody><tr v-for="item in pagedCdks" :key="item.code"><td><code>{{ item.code }}</code></td><td><UiStatusBadge :label="statusLabel(item.status)" :tone="statusTone(item.status)" /></td><td class="ui-input-mono">{{ item.used_count }}/{{ item.quota_total }}</td><td><button v-if="item.password_set" type="button" class="ui-reveal-button" :aria-label="isPasswordVisible(item.code) ? '隐藏提取密码' : '查看提取密码'" @click="togglePassword(item.code)">{{ passwordText(item) }}</button><span v-else class="ui-muted">首次提取设置</span></td><td class="ui-muted">{{ fmtTs(item.latest_redeemed_at) }}</td><td class="ui-muted">{{ fmtTs(item.expires_at) }}</td><td class="ui-table-note">{{ item.note || '-' }}</td><td><div class="ui-toolbar-actions"><UiButton variant="quiet" size="sm" @click="copyText(item.code)">复制</UiButton><UiButton variant="secondary" size="sm" :loading="downloadingCode === item.code" :disabled="!item.used_count" @click="downloadCdkRedemptions(item.code)">下载</UiButton><UiButton variant="danger" size="sm" :loading="revokingCode === item.code" :disabled="item.status !== 'active'" @click="revokeCdk(item.code)">注销</UiButton></div></td></tr></tbody>
        </table>
        <template #footer><UiPagination v-model:page="cdkPage" v-model:page-size="cdkPageSize" :page-sizes="[50, 100, 200]" :total-items="cdks.length" item-label="条 CDK" /></template>
      </UiTableFrame>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api.js'
import UiButton from './ui/UiButton.vue'
import UiFormField from './ui/UiFormField.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiPagination from './ui/UiPagination.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'
import UiSurface from './ui/UiSurface.vue'
import UiTableFrame from './ui/UiTableFrame.vue'

const loading = ref(false)
const creating = ref(false)
const revokingCode = ref('')
const downloadingCode = ref('')
const summary = ref(null)
const cdks = ref([])
const quotaTotal = ref(1)
const note = ref('')
const createdCode = ref('')
const message = ref('')
const messageClass = ref('')
const revealedPasswords = ref(new Set())
const cdkPage = ref(1)
const cdkPageSize = ref(100)
const totalPages = computed(() => Math.max(1, Math.ceil(cdks.value.length / Math.max(1, Number(cdkPageSize.value) || 100))))
const safePage = computed(() => Math.min(totalPages.value, Math.max(1, Number(cdkPage.value) || 1)))
const pagedCdks = computed(() => {
  const size = Math.max(1, Number(cdkPageSize.value) || 100)
  const start = (safePage.value - 1) * size
  return cdks.value.slice(start, start + size)
})
const metricItems = computed(() => { const s = summary.value || {}; return [{ key: 'stock', label: '可用库存', value: s.stock_available || 0, tone: 'success' }, { key: 'exported', label: '已导出', value: s.stock_exported || 0, tone: 'info' }, { key: 'active', label: '活跃 CDK', value: s.cdk_active || 0, tone: 'success' }, { key: 'exhausted', label: '已用完', value: s.cdk_exhausted || 0, tone: 'warning' }, { key: 'revoked', label: '已注销', value: s.cdk_revoked || 0, tone: 'danger' }] })
let messageTimer = null

function showMessage(text, kind = 'success') {
  if (messageTimer !== null) {
    window.clearTimeout(messageTimer)
    messageTimer = null
  }
  message.value = text
  messageClass.value = kind === 'error'
    ? 'ui-inline-message-error'
    : 'ui-inline-message-success'
  messageTimer = window.setTimeout(() => {
    message.value = ''
    messageTimer = null
  }, 6000)
}

async function load() {
  loading.value = true
  try {
    const [s, list] = await Promise.all([
      api.getTradeSummary(),
      api.getTradeCdks(),
    ])
    summary.value = s
    cdks.value = Array.isArray(list?.items) ? list.items : (Array.isArray(list) ? list : [])
    cdkPage.value = Math.min(safePage.value, totalPages.value)
  } catch (e) {
    showMessage(e.message, 'error')
  } finally {
    loading.value = false
  }
}

async function createCdk() {
  creating.value = true
  try {
    const cdk = await api.createTradeCdk(quotaTotal.value, note.value)
    createdCode.value = cdk.code
    note.value = ''
    showMessage(`已生成 ${cdk.code}`)
    await load()
  } catch (e) {
    showMessage(e.message, 'error')
  } finally {
    creating.value = false
  }
}

async function revokeCdk(code) {
  const ok = window.confirm(`确认注销 ${code}？注销后用户不能继续提取。`)
  if (!ok) return
  revokingCode.value = code
  try {
    await api.revokeTradeCdk(code)
    showMessage(`已注销 ${code}`)
    await load()
  } catch (e) {
    showMessage(e.message, 'error')
  } finally {
    revokingCode.value = ''
  }
}

function saveBase64File(filename, contentType, contentBase64) {
  const binary = atob(contentBase64 || '')
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  const blob = new Blob([bytes], { type: contentType || 'application/octet-stream' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'download.zip'
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

async function downloadCdkRedemptions(code) {
  downloadingCode.value = code
  try {
    const payload = await api.downloadTradeCdkRedemptions(code)
    saveBase64File(payload.filename, payload.content_type, payload.content_base64)
    showMessage(`已下载 ${payload.count || 0} 个账号`)
  } catch (e) {
    showMessage(e.message, 'error')
  } finally {
    downloadingCode.value = ''
  }
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  showMessage('已复制')
}

function statusLabel(status) {
  return {
    active: '有效',
    expired: '已过期',
    exhausted: '已用完',
    revoked: '已注销',
  }[String(status || '')] || status || '-'
}

function statusTone(status) {
  if (status === 'active') return 'success'
  if (status === 'exhausted') return 'warning'
  if (status === 'revoked' || status === 'expired') return 'danger'
  return 'neutral'
}

function isPasswordVisible(code) {
  return revealedPasswords.value.has(code)
}

function togglePassword(code) {
  const next = new Set(revealedPasswords.value)
  if (next.has(code)) {
    next.delete(code)
  } else {
    next.add(code)
  }
  revealedPasswords.value = next
}

function passwordText(item) {
  const raw = String(item.password || '')
  if (!raw) return '旧记录无明文'
  return isPasswordVisible(item.code) ? raw : maskPassword(raw)
}

function maskPassword(value) {
  const raw = String(value || '')
  if (!raw) return '-'
  if (raw.length <= 2) return '*'.repeat(raw.length)
  return `${raw.slice(0, 1)}${'*'.repeat(Math.max(3, raw.length - 2))}${raw.slice(-1)}`
}

function fmtTs(ts) {
  const value = Number(ts || 0)
  if (!value) return '-'
  const d = new Date(value * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

watch([cdks, cdkPageSize], () => {
  if (cdkPage.value !== safePage.value) cdkPage.value = safePage.value
})

onMounted(load)
onBeforeUnmount(() => {
  if (messageTimer !== null) window.clearTimeout(messageTimer)
})
</script>
