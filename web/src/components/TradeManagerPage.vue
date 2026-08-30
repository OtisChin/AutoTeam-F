<template>
  <div class="space-y-6">
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <div>
        <h2 class="text-xl font-semibold text-white">交易管理</h2>
        <p class="mt-1 text-sm text-gray-400">生成 Plus 提取 CDK，查看额度、提取记录和有效状态。</p>
      </div>
      <button
        @click="load"
        :disabled="loading"
        class="self-start rounded-lg border border-gray-700 bg-gray-800 px-4 py-2 text-sm text-gray-300 transition hover:bg-gray-700 hover:text-white disabled:opacity-50"
      >
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </div>

    <div class="grid grid-cols-2 gap-4 lg:grid-cols-7">
      <div v-for="card in summaryCards" :key="card.label" class="rounded-xl border border-gray-800 bg-gray-900 p-4">
        <div class="text-xs text-gray-500">{{ card.label }}</div>
        <div class="mt-2 text-2xl font-semibold" :class="card.color">{{ card.value }}</div>
      </div>
    </div>

    <div v-if="message" class="rounded-lg border px-4 py-3 text-sm" :class="messageClass">
      {{ message }}
    </div>

    <div class="grid gap-6 xl:grid-cols-[380px_1fr]">
      <section class="rounded-xl border border-gray-800 bg-gray-900 p-5">
        <h3 class="text-lg font-semibold text-white">生成 CDK</h3>
        <div class="mt-5 space-y-4">
          <label class="block">
            <span class="mb-1 block text-sm text-gray-400">可提取 Plus 账号数</span>
            <input
              v-model.number="quotaTotal"
              type="number"
              min="1"
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
            />
          </label>
          <label class="block">
            <span class="mb-1 block text-sm text-gray-400">备注</span>
            <input
              v-model.trim="note"
              type="text"
              placeholder="订单号或买家标记"
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
            />
          </label>
          <button
            @click="createCdk"
            :disabled="creating || !quotaTotal || quotaTotal < 1"
            class="w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-500 disabled:opacity-50"
          >
            {{ creating ? '生成中...' : '生成 CDK' }}
          </button>
        </div>
        <div v-if="createdCode" class="mt-5 rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-4">
          <div class="text-xs text-emerald-300">最新生成</div>
          <div class="mt-2 break-all font-mono text-lg text-white">{{ createdCode }}</div>
          <button
            @click="copyText(createdCode)"
            class="mt-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-1.5 text-xs text-emerald-300 transition hover:bg-emerald-500/20"
          >
            复制
          </button>
        </div>
      </section>

      <section class="overflow-hidden rounded-xl border border-gray-800 bg-gray-900">
        <div class="flex flex-col gap-3 border-b border-gray-800 px-4 py-4 md:flex-row md:items-center md:justify-between">
          <h3 class="text-lg font-semibold text-white">CDK 列表</h3>
          <div class="text-xs text-gray-500">共 {{ cdks.length }} 条</div>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-gray-800 text-left text-gray-400">
                <th class="px-4 py-3 font-medium">CDK</th>
                <th class="px-4 py-3 font-medium">状态</th>
                <th class="px-4 py-3 pr-8 font-medium text-right">额度</th>
                <th class="px-8 py-3 font-medium">密码</th>
                <th class="px-4 py-3 font-medium">最近提取时间</th>
                <th class="px-4 py-3 font-medium">过期时间</th>
                <th class="px-4 py-3 font-medium">备注</th>
                <th class="px-4 py-3 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!cdks.length">
                <td colspan="8" class="px-4 py-10 text-center text-gray-500">暂无 CDK</td>
              </tr>
              <tr v-for="item in cdks" :key="item.code" class="border-b border-gray-800/60 hover:bg-gray-800/30">
                <td class="px-4 py-3">
                  <div class="font-mono text-xs text-gray-100">{{ item.code }}</div>
                </td>
                <td class="px-4 py-3">
                  <span class="inline-flex rounded-full px-2 py-0.5 text-xs font-medium" :class="statusClass(item.status)">
                    {{ statusLabel(item.status) }}
                  </span>
                </td>
                <td class="px-4 py-3 pr-8 text-right font-mono text-gray-200">{{ item.used_count }}/{{ item.quota_total }}</td>
                <td class="px-8 py-3">
                  <button
                    v-if="item.password_set"
                    type="button"
                    @click="togglePassword(item.code)"
                    class="group relative inline-flex min-w-[126px] max-w-[190px] items-center justify-center overflow-hidden rounded-lg border border-gray-700 bg-gray-800/80 px-3 py-1.5 font-mono text-xs text-gray-100 transition hover:border-gray-600 hover:bg-gray-800"
                    :aria-label="isPasswordVisible(item.code) ? '隐藏提取密码' : '查看提取密码'"
                  >
                    <span class="truncate" :class="isPasswordVisible(item.code) ? '' : 'select-none blur-sm opacity-70'">
                      {{ passwordText(item) }}
                    </span>
                    <span
                      v-if="!isPasswordVisible(item.code)"
                      class="absolute inset-0 flex items-center justify-center bg-slate-700/45 text-[11px] font-medium text-slate-100 backdrop-blur-md transition group-hover:bg-slate-600/55"
                    >
                      点击查看
                    </span>
                  </button>
                  <span v-else class="text-gray-500">首次提取设置</span>
                </td>
                <td class="px-4 py-3 text-xs text-gray-400">{{ fmtTs(item.latest_redeemed_at) }}</td>
                <td class="px-4 py-3 text-xs text-gray-400">{{ fmtTs(item.expires_at) }}</td>
                <td class="max-w-[220px] truncate px-4 py-3 text-gray-400">{{ item.note || '-' }}</td>
                <td class="px-4 py-3">
                  <div class="flex justify-end gap-2">
                    <button @click="copyText(item.code)" class="rounded-lg border border-gray-700 bg-gray-800 px-2 py-1 text-xs text-gray-300 hover:bg-gray-700">复制</button>
                    <button
                      @click="downloadCdkRedemptions(item.code)"
                      :disabled="downloadingCode === item.code || !item.used_count"
                      class="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-xs text-cyan-300 hover:bg-cyan-500/20 disabled:opacity-40"
                    >
                      {{ downloadingCode === item.code ? '下载中' : '下载' }}
                    </button>
                    <button
                      @click="revokeCdk(item.code)"
                      :disabled="revokingCode === item.code || item.status !== 'active'"
                      class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-300 hover:bg-rose-500/20 disabled:opacity-40"
                    >
                      {{ revokingCode === item.code ? '注销中' : '注销' }}
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'

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

const summaryCards = computed(() => {
  const s = summary.value || {}
  return [
    { label: '库存', value: s.stock_available || 0, color: 'text-emerald-300' },
    { label: '已导出', value: s.stock_exported || 0, color: 'text-cyan-300' },
    { label: '已废弃', value: s.stock_discarded || 0, color: 'text-orange-300' },
    { label: '缺凭证', value: s.stock_missing_credentials || 0, color: 'text-red-300' },
    { label: '活跃CDK', value: s.cdk_active || 0, color: 'text-emerald-300' },
    { label: '已用完', value: s.cdk_exhausted || 0, color: 'text-amber-300' },
    { label: '已注销', value: s.cdk_revoked || 0, color: 'text-rose-300' },
  ]
})

function showMessage(text, kind = 'success') {
  message.value = text
  messageClass.value = kind === 'error'
    ? 'border-red-500/20 bg-red-500/10 text-red-300'
    : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300'
  setTimeout(() => { message.value = '' }, 6000)
}

async function load() {
  loading.value = true
  try {
    const [s, list] = await Promise.all([
      api.getTradeSummary(),
      api.getTradeCdks(),
    ])
    summary.value = s
    cdks.value = list.items || []
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

function statusClass(status) {
  return {
    active: 'bg-emerald-500/10 text-emerald-300',
    expired: 'bg-gray-500/10 text-gray-400',
    exhausted: 'bg-amber-500/10 text-amber-300',
    revoked: 'bg-rose-500/10 text-rose-300',
  }[String(status || '')] || 'bg-gray-500/10 text-gray-400'
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
  return item.password || '旧记录无明文'
}

function fmtTs(ts) {
  const value = Number(ts || 0)
  if (!value) return '-'
  const d = new Date(value * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

onMounted(load)
</script>
