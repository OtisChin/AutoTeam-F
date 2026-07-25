<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-2">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div class="inline-flex w-fit rounded-xl border border-gray-800 bg-gray-900/80 p-1">
          <button type="button" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-bold text-white shadow-lg shadow-emerald-950/40 transition">提链页</button>
        </div>
        <p class="px-2 text-xs text-gray-500">荷兰 iDEAL 提链页按巴西 Pix / 印度 UPI 对齐：账号池、任务输入、日志、结果和链接管理分区一致。</p>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">独立 iDEAL 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">荷兰iDEAL 提链</h2>
          <p class="mt-2 text-sm text-gray-400">在账号池中勾选一个或多个账号执行提链，结果会进入下方链接管理表。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ busy ? progressText : '本地服务在线' }}
        </span>
      </div>
    </section>

    <div class="grid grid-cols-1 items-start gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">NL 代理</h3>
        </div>
        <div class="mt-5 space-y-5">
          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">NL 代理列表</span>
            <textarea v-model.trim="form.proxies" rows="8" spellcheck="false" placeholder="每行一个代理；支持 host:port:user:pass 或 socks5h://user:pass@host:port" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" :disabled="busy"></textarea>
            <span class="mt-1 block text-xs text-gray-500">批量提链时按账号顺序轮换代理；留空使用备用出口代理或后台默认链路。</span>
          </label>
          <div class="grid gap-4 md:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="form.concurrency" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 1，最高 20。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">重试次数</span>
              <input v-model.number="form.maxAttempts" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 5。</span>
            </label>
          </div>
          <details class="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
            <summary class="cursor-pointer text-sm font-semibold text-gray-200">高级设置</summary>
            <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
              <label class="block"><span class="mb-1.5 block text-xs text-gray-400">备用出口代理</span><input v-model.trim="form.proxy" placeholder="留空使用后台默认代理" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" :disabled="busy" /></label>
              <label class="block"><span class="mb-1.5 block text-xs text-gray-400">支付页语言</span><select v-model="form.paymentLocale" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy"><option value="auto">自动跟随链路</option><option value="nl-NL">荷兰语</option><option value="en">英文</option><option value="zh-CN">简体中文</option></select></label>
              <label class="block"><span class="mb-1.5 block text-xs text-gray-400">代理链路</span><select v-model="form.proxyChainPreset" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy"><option value="default">源码默认</option><option value="dual_ideal">双链路 JP→NL + NL→NL</option><option value="JP_NL">日本 JP → 荷兰 NL</option><option value="NL_NL">荷兰 NL → 荷兰 NL</option><option value="parallel4">同时跑 4 策略</option><option value="matrix8">Matrix 8 combos</option><option value="sequential8">Sequential 8 combos</option><option value="manual">手动选择</option></select></label>
              <label class="flex items-center gap-2 self-end rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2 text-sm text-gray-300"><input v-model="form.diagnosticEnabled" type="checkbox" class="accent-blue-500" :disabled="busy" />开启诊断抓取</label>
              <template v-if="form.proxyChainPreset === 'manual'">
                <label class="block"><span class="mb-1.5 block text-xs text-gray-400">前段代理地区</span><input v-model.trim="form.checkoutProxyRegion" placeholder="例如 JP" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" /></label>
                <label class="block"><span class="mb-1.5 block text-xs text-gray-400">后段代理地区</span><input v-model.trim="form.providerProxyRegion" placeholder="例如 NL" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" /></label>
              </template>
            </div>
            <div class="mt-3 rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-400">{{ proxyChainSummary }}</div>
            <div v-if="proxyTestResult" class="mt-2 rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-xs text-gray-400">{{ proxyTestResult }}</div>
          </details>
          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="busy" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50">{{ busy ? '提取中...' : `开始提链 (${selectedEmails.length})` }}</button>
            <button v-if="busy" @click="cancelJob" :disabled="canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">{{ canceling ? '取消中...' : '取消提链' }}</button>
            <button @click="reloadAll" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号/链接</button>
            <button @click="testProxy" :disabled="busy || testingProxy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">{{ testingProxy ? '测试中...' : '测试代理' }}</button>
            <button @click="saveProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
            <button @click="retryFailedAccounts" :disabled="busy || !retryFailedEmails.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50">失败重试{{ retryFailedEmails.length ? ` (${retryFailedEmails.length})` : '' }}</button>
            <NotificationSoundControl v-model="form.notificationSoundEnabled" :disabled="busy" />
          </div>
          <div class="text-sm" :class="statusError ? 'text-rose-300' : 'text-gray-400'">{{ statusText }}</div>
        </div>
      </section>

      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
          <div><p class="text-xs font-semibold text-gray-500">账号管理</p><h3 class="mt-1 text-xl font-bold text-white">账号池选择</h3></div>
          <div class="text-sm text-gray-400">已选 <span class="font-semibold text-emerald-300">{{ selectedEmails.length }}</span> / {{ filteredAccounts.length }}</div>
        </div>
        <div class="mt-4 flex flex-col gap-3 md:flex-row md:items-center">
          <input v-model.trim="accountFilter" placeholder="搜索账号邮箱" class="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" />
          <select v-model="accountStatusFilter" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"><option value="all">全部状态</option><option value="pending">未提链</option><option value="failed">提链失败</option><option value="success">已提链</option><option value="paid">已支付</option></select>
          <div class="flex flex-wrap gap-2"><button @click="selectAllFiltered" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button><button @click="clearSelectedAccounts" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button><button @click="deleteSelectedIdealAccounts" :disabled="busy || deletingIdealAccounts.size > 0 || !selectedEmails.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">删除选中{{ selectedEmails.length ? ` (${selectedEmails.length})` : '' }}</button></div>
        </div>
        <div class="mt-4 max-h-[520px] overflow-y-auto rounded-xl border border-gray-800">
          <table class="w-full text-left text-sm"><thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500"><tr><th class="w-10 px-3 py-2"></th><th class="px-3 py-2">邮箱</th><th class="px-3 py-2">有效期</th><th class="px-3 py-2">提链状态</th><th class="px-3 py-2 text-right">操作</th></tr></thead><tbody class="divide-y divide-gray-900"><tr v-if="!filteredAccounts.length"><td colspan="5" class="px-3 py-10 text-center text-gray-500">暂无账号</td></tr><tr v-for="account in filteredAccounts" :key="account.email" class="hover:bg-gray-900/50"><td class="px-3 py-2"><input :checked="selectedAccounts.has(account.email)" type="checkbox" class="accent-emerald-500" :disabled="busy || !accountSelectable(account)" @change="toggleAccount(account.email)" /></td><td class="px-3 py-2 font-mono text-xs text-gray-300">{{ account.email }}</td><td class="px-3 py-2 text-xs text-gray-500">{{ ttlText(account.ttl_seconds) }}</td><td class="px-3 py-2 text-xs"><span class="inline-flex rounded-full border px-2 py-1 font-semibold" :class="accountStatusClass(account)" :title="accountStatusError(account)">{{ accountStatusText(account) }}</span></td><td class="px-3 py-2 text-right"><button @click="deleteIdealAccount(account.email)" :disabled="busy || deletingIdealAccounts.has(account.email)" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">{{ deletingIdealAccounts.has(account.email) ? '删除中' : '删除' }}</button></td></tr></tbody></table>
        </div>
      </section>

      <div class="space-y-5">
        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4"><div><p class="text-xs font-semibold text-gray-500">实时状态</p><h3 class="mt-1 text-xl font-bold text-white">执行日志</h3></div><span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="badgeClass(runtimeBadge.kind)">{{ runtimeBadge.text }}</span></div>
          <div ref="logRef" class="mt-4 h-72 overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-3 font-mono text-xs text-gray-400"><div v-if="!logs.length && !steps.length" class="flex h-full items-center justify-center font-sans text-sm text-gray-500">暂无执行日志</div><div v-for="(line, index) in logs" :key="`log-${index}`" class="border-b border-gray-900 py-1 last:border-b-0">{{ line }}</div><div v-for="(step, index) in steps" :key="`step-${index}`" class="grid grid-cols-[72px_52px_minmax(0,1fr)] gap-2 border-b border-gray-900 py-2 text-xs last:border-b-0"><span class="font-mono text-gray-500">{{ step.time || '-' }}</span><span class="font-semibold" :class="stepStatusClass(step.status)">{{ stepStatusLabel(step.status) }}</span><span class="min-w-0"><span class="font-semibold text-gray-300">{{ step.name || '-' }}</span><span class="ml-2 text-gray-500">{{ cleanText(step.detail) }}</span></span></div></div>
        </section>
        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4"><div><p class="text-xs font-semibold text-gray-500">当前结果</p><h3 class="mt-1 text-xl font-bold text-white">最近一次任务</h3></div><span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="result ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-gray-700 bg-gray-900 text-gray-400'">{{ result ? '有结果' : '等待提取' }}</span></div>
          <div v-if="!result" class="flex min-h-48 flex-col items-center justify-center text-center text-gray-500"><strong class="text-gray-300">尚未生成结果</strong><span class="mt-1 text-sm">从账号池勾选账号后开始提链</span></div>
          <div v-else class="mt-5 max-h-72 space-y-4 overflow-y-auto pr-1"><div class="flex flex-col items-center gap-4"><div class="flex h-44 w-44 items-center justify-center rounded-xl border border-gray-700 bg-white p-2"><img v-if="qrUrl" :src="qrUrl" alt="iDEAL QR" class="h-full w-full object-contain" /><span v-else class="text-sm text-gray-500">无二维码图片</span></div><div class="flex flex-wrap justify-center gap-2"><a :href="safeLongUrl || '#'" target="_blank" rel="noopener" class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-500" :class="!safeLongUrl ? 'pointer-events-none opacity-50' : ''">打开 iDEAL 链接</a><button @click="copyLongUrl" :disabled="!safeLongUrl" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">复制 iDEAL 链</button><button @click="downloadQr" :disabled="!qrUrl" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">下载二维码</button></div></div><div class="space-y-3 rounded-xl border border-gray-800 bg-gray-950 p-4 text-sm"><div class="text-emerald-300">Checkout Session 提取成功</div><ResultRow label="长链" :value="safeLongUrl" /><ResultRow label="CS ID / 地区 / 币种" :value="summaryText" /><ResultRow label="提取状态" :value="result.fallback ? `已回退 hosted：${result.provider_error || 'provider redirect 提取失败'}` : 'iDEAL 链提取成功'" /></div></div>
        </section>
      </div>
    </div>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between"><div><p class="text-xs font-semibold text-gray-500">链接管理</p><h3 class="mt-1 text-xl font-bold text-white">已提取 iDEAL 链接</h3></div><div class="flex flex-wrap gap-2"><button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button><button @click="exportLinks" :disabled="!links.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button><button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button><button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空</button></div></div>
      <div class="mt-4 max-h-[520px] overflow-auto rounded-xl border border-gray-800"><table class="min-w-[1120px] w-full text-left text-sm"><thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500"><tr><th class="w-10 px-3 py-2"></th><th class="px-3 py-2">时间</th><th class="px-3 py-2">账号</th><th class="px-3 py-2">金额</th><th class="px-3 py-2">CS ID</th><th class="px-3 py-2">操作</th><th class="px-3 py-2">iDEAL 链接</th></tr></thead><tbody class="divide-y divide-gray-900"><tr v-if="!links.length"><td colspan="7" class="px-3 py-10 text-center text-gray-500">暂无链接</td></tr><tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50"><td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td><td class="px-3 py-2 text-xs text-gray-500">{{ link.created_at || '-' }}</td><td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || '-' }}</td><td class="px-3 py-2 text-xs text-gray-400">{{ link.amount_display || link.amount || '-' }}</td><td class="px-3 py-2 font-mono text-xs text-gray-500">{{ link.cs_id || '-' }}</td><td class="px-3 py-2"><div class="flex flex-wrap gap-2"><a :href="link.ideal_link || link.long_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-100" :class="!(link.ideal_link || link.long_url) ? 'pointer-events-none opacity-50' : ''">打开</a><button @click="copy(link.ideal_link || link.long_url)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-100">复制链</button></div></td><td class="max-w-[460px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ link.ideal_link || link.long_url || '-' }}</td></tr></tbody></table></div>
    </section>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import NotificationSoundControl from './NotificationSoundControl.vue'
import { LINK_SUCCESS_SOUND_URL, playNotificationSound } from '../notificationSounds.js'

const STORAGE_KEY = 'autotoken_ideal_form_v1'
const SAVED_PROXY_KEY = 'autotoken_ideal_saved_proxy'

const ResultRow = defineComponent({
  props: { label: String, value: String },
  setup(props) {
    return () => h('div', { class: 'grid gap-1 md:grid-cols-[150px_minmax(0,1fr)]' }, [
      h('span', { class: 'text-gray-500' }, props.label || ''),
      h('code', { class: 'break-all rounded bg-gray-900 px-2 py-1 text-xs text-gray-300' }, props.value || '-'),
    ])
  },
})

const workflowSteps = [
  { id: 1, title: '授权信息', caption: 'Token 与链路参数' },
  { id: 2, title: '提取链接', caption: '实时执行与日志' },
  { id: 3, title: '生成二维码', caption: '查看、复制和下载' },
]

const form = ref({
  accessToken: '',
  proxy: '',
  proxies: '',
  concurrency: 1,
  maxAttempts: 5,
  checkoutUiMode: 'hosted',
  paymentLocale: 'auto',
  stripePublishableKey: '',
  deviceId: '',
  clientFingerprint: 'chrome',
  userAgent: '',
  diagnosticEnabled: false,
  proxyChainPreset: 'JP_NL',
  checkoutProxyRegion: '',
  providerProxyRegion: '',
  notificationSoundEnabled: true,
})
const busy = ref(false)
const testingProxy = ref(false)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const steps = ref([])
const result = ref(null)
const qrUrl = ref('')
const currentJobId = ref('')
const pollTimer = ref(null)
const logRef = ref(null)
const proxyTestResult = ref('')
const workflowStage = ref(1)
const runtimeBadge = ref({ text: '等待任务', kind: 'neutral' })
const resultBadge = ref({ text: '等待提取', kind: 'neutral' })
const accounts = ref([])
const links = ref([])
const logs = ref([])
const accountFilter = ref('')
const accountStatusFilter = ref('all')
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const deletingIdealAccounts = ref(new Set())
const canceling = ref(false)

const DEFAULT_PROXY_CHAIN_BY_TYPE = {
  ideal: { checkout: 'JP', provider: 'NL' },
}

const PROXY_CHAIN_PRESETS = {
  JP_NL: { checkout: 'JP', provider: 'NL', label: '日本 JP → 荷兰 NL' },
  NL_NL: { checkout: 'NL', provider: 'NL', label: '荷兰 NL → 荷兰 NL' },
  US_US: { checkout: 'US', provider: 'US', label: '美国 US → 美国 US' },
  JP_US: { checkout: 'JP', provider: 'US', label: '日本 JP → 美国 US' },
  JP_US_US: { checkout: 'JP', provider: 'US', approve: 'US', label: 'JP → US → approve US' },
  JP_US_JP: { checkout: 'JP', provider: 'US', approve: 'JP', label: 'JP → US → approve JP' },
  JP_JP: { checkout: 'JP', provider: 'same', label: '日本 JP → 日本 JP' },
  US_JP: { checkout: 'US', provider: 'JP', label: '美国 US → 日本 JP' },
}

const PROXY_CHAIN_STRATEGIES = new Set(['dual_ideal', 'parallel4', 'matrix8', 'sequential8'])
const SOURCE_DEFAULT_CHAIN_PRESETS = new Set(['default', 'manual', ...PROXY_CHAIN_STRATEGIES])
const SAME_PROVIDER_VALUES = new Set(['same', 'none', 'off', 'no', 'false', '0', '不切换', '不使用'])

const tokenMeta = computed(() => {
  const token = readAccessTokenInput()
  if (!token) return ''
  return token.includes('.') ? '已识别 JWT access token' : '已输入授权内容'
})
const safeLongUrl = computed(() => safeHttpUrl(result.value?.long_url || ''))
const summaryText = computed(() => {
  if (!result.value) return ''
  const amount = result.value.amount_display || (result.value.amount ? `amount=${result.value.amount}` : '')
  return `${result.value.cs_id || ''} / ${result.value.billing_country || ''} / ${result.value.currency || ''} / ${result.value.link_type || 'ideal'}${amount ? ` / ${amount}` : ''}`
})
const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const progressText = computed(() => {
  if (!currentJobId.value) return '提链中...'
  return `任务 ${currentJobId.value.slice(0, 8)} 执行中`
})
const filteredAccounts = computed(() => {
  const keyword = accountFilter.value.toLowerCase()
  return accounts.value.filter((account) => {
    const email = String(account.email || '').toLowerCase()
    const status = String(account.ideal_status || 'pending')
    const matchesKeyword = !keyword || email.includes(keyword)
    const matchesStatus = accountStatusFilter.value === 'all' || status === accountStatusFilter.value
    return matchesKeyword && matchesStatus
  })
})
const retryFailedEmails = computed(() => accounts.value
  .filter(account => account.ideal_status === 'failed' && accountSelectable(account))
  .map(account => account.email)
  .filter(Boolean))

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function safeHttpUrl(value) {
  const text = String(value || '').trim()
  return /^https?:\/\//i.test(text) ? text : ''
}

function normalizeProxyRegionInput(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const lower = raw.toLowerCase()
  if (SAME_PROVIDER_VALUES.has(lower) || SAME_PROVIDER_VALUES.has(raw)) return 'same'
  return raw.toUpperCase()
}

function findToken(value) {
  if (!value) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) {
    for (const item of value) {
      const token = findToken(item)
      if (token) return token
    }
  }
  if (typeof value === 'object') {
    for (const key of ['accessToken', 'access_token', 'token']) {
      if (typeof value[key] === 'string' && value[key].trim()) return value[key].trim()
    }
    for (const item of Object.values(value)) {
      const token = findToken(item)
      if (token) return token
    }
  }
  return ''
}

function readAccessTokenInput() {
  const raw = String(form.value.accessToken || '').trim()
  if (!raw) return ''
  if (raw.startsWith('{') || raw.startsWith('[')) {
    try {
      return findToken(JSON.parse(raw)) || raw
    } catch {
      return raw
    }
  }
  return raw
}

function setStatus(text, isError = false) {
  statusText.value = text
  statusError.value = isError
}

function badgeClass(kind) {
  return {
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    error: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  }[kind] || 'border-gray-700 bg-gray-900 text-gray-400'
}

function stepStatusLabel(status) {
  return { ok: '成功', fail: '失败', warn: '警告', info: '执行' }[String(status || '').toLowerCase()] || '执行'
}

function stepStatusClass(status) {
  return {
    ok: 'text-emerald-300',
    fail: 'text-rose-300',
    warn: 'text-amber-300',
    info: 'text-blue-300',
  }[String(status || '').toLowerCase()] || 'text-blue-300'
}

function proxyPayload() {
  const preset = form.value.proxyChainPreset
  const usesDefault = SOURCE_DEFAULT_CHAIN_PRESETS.has(preset)
  const chain = usesDefault
    ? DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
    : PROXY_CHAIN_PRESETS[preset] || DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
  return {
    link_type: 'ideal',
    proxy: form.value.proxy,
    proxy_chain_strategy: PROXY_CHAIN_STRATEGIES.has(preset) ? preset : '',
    diagnostic_enabled: form.value.diagnosticEnabled,
    approve_proxy_region: preset === 'manual' ? '' : chain.approve || '',
    checkout_proxy_region: preset === 'manual' ? normalizeProxyRegionInput(form.value.checkoutProxyRegion) : chain.checkout,
    provider_proxy_region: preset === 'manual' ? normalizeProxyRegionInput(form.value.providerProxyRegion) : chain.provider,
  }
}

function formatProbeResult(title, result) {
  if (!result) return ''
  const ok = result.ok && result.match
  const skipped = result.skipped ? '，沿用前段' : ''
  const ip = result.ip ? `，IP ${result.ip}` : ''
  const detail = result.error ? `，错误：${result.error}` : ''
  return `${ok ? '通过' : '不匹配'} ${title}${skipped}：期望 ${result.expected_region || '-'}，实际 ${result.actual_region || '-'}${ip}${detail}`
}

function proxyChainHint() {
  const preset = form.value.proxyChainPreset
  const usesDefault = SOURCE_DEFAULT_CHAIN_PRESETS.has(preset)
  const chain = usesDefault
    ? DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
    : PROXY_CHAIN_PRESETS[preset] || DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
  if (preset === 'dual_ideal') return '双链路 iDEAL：同时测试 JP→NL 和 NL→NL，任一成功即停止'
  if (preset === 'parallel4') return '并发代理链路：执行 US→US、JP→US、JP→JP、US→JP 等策略'
  if (preset === 'matrix8') return 'Matrix 8 链路：按源码矩阵组合执行'
  if (preset === 'sequential8') return 'Sequential 8 链路：按源码顺序组合执行'
  if (preset === 'manual') return `手动代理链路：前段 ${normalizeProxyRegionInput(form.value.checkoutProxyRegion) || '-'} → 后段 ${normalizeProxyRegionInput(form.value.providerProxyRegion) || '-'}`
  const label = preset === 'default' ? '源码默认链路' : `预设链路 ${PROXY_CHAIN_PRESETS[preset]?.label || preset}`
  return `${label}：前段 ${chain.checkout || '-'} → 后段 ${chain.provider || '-'}${chain.approve ? ` → approve ${chain.approve}` : ''}`
}

function applyDefaultProxyChain() {
  const preset = form.value.proxyChainPreset
  const usesDefault = SOURCE_DEFAULT_CHAIN_PRESETS.has(preset)
  const chain = usesDefault
    ? DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
    : PROXY_CHAIN_PRESETS[preset] || DEFAULT_PROXY_CHAIN_BY_TYPE.ideal
  form.value.checkoutProxyRegion = chain.checkout
  form.value.providerProxyRegion = chain.provider
}

const proxyChainSummary = computed(() => proxyChainHint())

function requestPayload() {
  return {
    accessToken: readAccessTokenInput(),
    ...proxyPayload(),
    billing_country: 'NL',
    checkout_ui_mode: form.value.checkoutUiMode,
    payment_locale: form.value.paymentLocale,
    stripe_publishable_key: form.value.stripePublishableKey,
    device_id: form.value.deviceId,
    client_fingerprint: form.value.clientFingerprint,
    user_agent: form.value.userAgent,
  }
}

function batchPayload(accountEmails = selectedEmails.value) {
  return {
    accountEmails,
    proxies: form.value.proxies,
    proxy: form.value.proxy,
    concurrency: form.value.concurrency,
    maxAttempts: form.value.maxAttempts,
    ...proxyPayload(),
    checkoutUiMode: form.value.checkoutUiMode,
    paymentLocale: form.value.paymentLocale,
    stripePublishableKey: form.value.stripePublishableKey,
    deviceId: form.value.deviceId,
    clientFingerprint: form.value.clientFingerprint,
    userAgent: form.value.userAgent,
  }
}

function ttlText(seconds) {
  const value = Number(seconds || 0)
  if (!value) return '-'
  if (value < 60) return `${value} 秒`
  if (value < 3600) return `${Math.floor(value / 60)} 分钟`
  if (value < 86400) return `${Math.floor(value / 3600)} 小时`
  return `${Math.floor(value / 86400)} 天`
}

function accountSelectable(account) {
  return String(account?.ideal_status || 'pending') !== 'paid' && Boolean(account?.email)
}

function accountStatusText(account) {
  return account?.ideal_status_text || ({ pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', paid: '已支付' }[account?.ideal_status] || '未提链')
}

function accountStatusError(account) {
  return account?.ideal_error || ''
}

function accountStatusClass(account) {
  return {
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    paid: 'border-violet-500/30 bg-violet-500/10 text-violet-300',
  }[String(account?.ideal_status || 'pending')] || 'border-gray-700 bg-gray-900 text-gray-400'
}

function toggleAccount(email) {
  const next = new Set(selectedAccounts.value)
  if (next.has(email)) next.delete(email)
  else next.add(email)
  selectedAccounts.value = next
}

function selectAllFiltered() {
  selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).map(account => account.email))
}

function clearSelectedAccounts() {
  selectedAccounts.value = new Set()
}

function toggleLink(id) {
  const next = new Set(selectedLinkIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedLinkIds.value = next
}

async function copy(value) {
  const text = String(value || '')
  if (!text) return
  await navigator.clipboard?.writeText(text)
  setStatus('已复制。')
}

async function refreshAccounts() {
  const data = await api.getIdealAccounts()
  accounts.value = Array.isArray(data.accounts) ? data.accounts : []
  const live = new Set(accounts.value.map(account => account.email).filter(Boolean))
  selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => live.has(email)))
}

async function refreshLinks() {
  const data = await api.getIdealLinks()
  links.value = Array.isArray(data.links) ? data.links : []
  const live = new Set(links.value.map(link => link.id).filter(Boolean))
  selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => live.has(id)))
}

async function reloadAll() {
  setStatus('正在刷新账号和链接。')
  await Promise.all([refreshAccounts(), refreshLinks()])
  setStatus('账号和链接已刷新。')
}

async function pollIdealJob(jobId) {
  currentJobId.value = jobId
  for (;;) {
    const data = await api.getIdealJob(jobId)
    logs.value = Array.isArray(data.logs) ? data.logs : []
    if (data.current_result) result.value = data.current_result
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (data.status === 'success' || data.status === 'error' || data.status === 'cancelled') {
      const lastSuccess = Array.isArray(data.successes) && data.successes.length ? data.successes[data.successes.length - 1] : null
      if (lastSuccess?.result) result.value = lastSuccess.result
      if (result.value?.long_url) {
        try { await renderQr(result.value.long_url) } catch {}
      }
      if (data.status === 'success') {
        runtimeBadge.value = { text: '执行完成', kind: 'success' }
        resultBadge.value = { text: '二维码就绪', kind: result.value ? 'success' : 'neutral' }
        setStatus(`任务完成：成功 ${data.successes?.length || 0}，失败 ${data.errors?.length || 0}。`)
        if ((data.successes || []).length) playNotificationSound(LINK_SUCCESS_SOUND_URL, form.value.notificationSoundEnabled)
      } else if (data.status === 'cancelled') {
        runtimeBadge.value = { text: '已取消', kind: 'error' }
        setStatus('任务已取消。', true)
      } else {
        runtimeBadge.value = { text: '执行失败', kind: 'error' }
        setStatus(data.error || '任务执行失败。', true)
      }
      await reloadAll()
      return
    }
    setStatus(`任务执行中：${data.completed || 0}/${data.total || 0}。`)
    await new Promise(resolve => {
      pollTimer.value = window.setTimeout(resolve, 1200)
    })
  }
}

async function start() {
  if (!selectedEmails.value.length) {
    setStatus('请先选择至少一个 iDEAL 账号。', true)
    return
  }
  busy.value = true
  result.value = null
  steps.value = []
  logs.value = []
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = ''
  runtimeBadge.value = { text: '正在执行', kind: 'running' }
  resultBadge.value = { text: '等待结果', kind: 'neutral' }
  setStatus(`任务已提交，正在为 ${selectedEmails.value.length} 个账号提取 iDEAL 链。`)
  try {
    persistForm()
    const data = await api.startIdealBatch(batchPayload())
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    await pollIdealJob(data.job_id)
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
    runtimeBadge.value = { text: '执行失败', kind: 'error' }
  } finally {
    busy.value = false
  }
}

async function cancelJob() {
  if (!currentJobId.value) return
  canceling.value = true
  try {
    await api.cancelIdealJob(currentJobId.value)
    setStatus('已请求取消任务。')
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
  } finally {
    canceling.value = false
  }
}

async function retryFailedAccounts() {
  if (!retryFailedEmails.value.length) return
  selectedAccounts.value = new Set(retryFailedEmails.value)
  await start()
}

async function deleteIdealAccount(email) {
  const target = String(email || '').trim()
  if (!target || deletingIdealAccounts.value.has(target)) return
  if (!window.confirm(`确认从 iDEAL 账号池和仪表盘账号池中删除 ${target}？`)) return
  deletingIdealAccounts.value = new Set([...deletingIdealAccounts.value, target])
  try {
    const data = await api.deleteIdealAccount(target)
    selectedAccounts.value.delete(target)
    setStatus(`已删除账号 ${target}，清理 iDEAL 链接 ${data.links_deleted || 0} 条。`)
    await reloadAll()
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
  } finally {
    const next = new Set(deletingIdealAccounts.value)
    next.delete(target)
    deletingIdealAccounts.value = next
  }
}

async function deleteSelectedIdealAccounts() {
  const emails = selectedEmails.value
  if (!emails.length || deletingIdealAccounts.value.size) return
  if (!window.confirm(`确认批量删除选中的 ${emails.length} 个账号？这些账号会同时从 iDEAL 账号池和仪表盘账号池删除。`)) return
  deletingIdealAccounts.value = new Set(emails)
  try {
    const data = await api.deleteIdealAccounts(emails)
    selectedAccounts.value = new Set()
    setStatus(`已批量删除 ${data.deleted || 0} 个账号。`)
    await reloadAll()
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
  } finally {
    deletingIdealAccounts.value = new Set()
  }
}

async function deleteSelectedLinks() {
  const ids = Array.from(selectedLinkIds.value)
  if (!ids.length) return
  const data = await api.deleteIdealLinks(ids)
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已删除 ${data.deleted || 0} 条 iDEAL 链接。`)
}

async function clearLinks() {
  if (!links.value.length || !window.confirm('确认清空所有已提取 iDEAL 链接？')) return
  const data = await api.clearIdealLinks()
  links.value = []
  selectedLinkIds.value = new Set()
  setStatus(`已清空 ${data.deleted || 0} 条 iDEAL 链接。`)
}

function exportLinks() {
  const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `ideal-links-${Date.now()}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

async function renderQr(value) {
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = ''
  const blob = await api.getIdealQrBlob(value)
  qrUrl.value = URL.createObjectURL(blob)
}

async function pollJob(jobId) {
  currentJobId.value = jobId
  for (;;) {
    const data = await api.getIdealLongLinkJob(jobId)
    steps.value = Array.isArray(data.steps) ? data.steps : []
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (data.status === 'done') {
      result.value = data.result || {}
      workflowStage.value = 3
      runtimeBadge.value = { text: '执行完成', kind: 'success' }
      resultBadge.value = { text: '生成二维码', kind: 'running' }
      const url = safeHttpUrl(result.value.long_url || '')
      if (url) {
        await renderQr(url)
        resultBadge.value = { text: '二维码就绪', kind: 'success' }
      } else {
        resultBadge.value = { text: '无有效长链', kind: 'error' }
      }
      setStatus('iDEAL 链与二维码已生成。')
      if (url) playNotificationSound(LINK_SUCCESS_SOUND_URL, form.value.notificationSoundEnabled)
      return
    }
    if (data.status === 'error') {
      if (data.result) result.value = data.result
      runtimeBadge.value = { text: '执行失败', kind: 'error' }
      resultBadge.value = { text: '未生成', kind: 'error' }
      throw new Error(data.error || '生成失败')
    }
    setStatus(`任务执行中，已记录 ${steps.value.length} 条日志。`)
    await new Promise(resolve => {
      pollTimer.value = window.setTimeout(resolve, 900)
    })
  }
}

async function generate() {
  const accessToken = readAccessTokenInput()
  if (!accessToken) {
    setStatus('Access Token 不能为空。', true)
    return
  }
  busy.value = true
  result.value = null
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
  qrUrl.value = ''
  workflowStage.value = 2
  runtimeBadge.value = { text: '正在执行', kind: 'running' }
  resultBadge.value = { text: '等待结果', kind: 'neutral' }
  steps.value = [{ time: new Date().toLocaleTimeString('zh-CN', { hour12: false }), status: 'info', name: '任务已提交', detail: '后端正在创建支付链路。' }]
  setStatus('任务已提交，正在提取 iDEAL 链。')
  try {
    persistForm()
    const data = await api.startIdealLongLink(requestPayload())
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    await pollJob(data.job_id)
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
    runtimeBadge.value = { text: '执行失败', kind: 'error' }
    resultBadge.value = { text: '未生成', kind: 'error' }
  } finally {
    busy.value = false
  }
}

async function testProxy() {
  testingProxy.value = true
  proxyTestResult.value = '正在测试代理出口'
  setStatus('正在测试代理。')
  try {
    const data = await api.testIdealProxyChain(proxyPayload())
    const lines = [formatProbeResult('前段', data.checkout), formatProbeResult('后段', data.provider)].filter(Boolean)
    proxyTestResult.value = lines.join(' | ')
    setStatus(data.ok ? '代理出口与选择一致。' : '代理出口与选择不一致。', !data.ok)
  } catch (error) {
    const message = cleanText(error.message || error)
    proxyTestResult.value = message
    setStatus('代理测试失败。', true)
  } finally {
    testingProxy.value = false
  }
}

async function copyLongUrl() {
  if (!safeLongUrl.value) return
  await navigator.clipboard?.writeText(safeLongUrl.value)
  setStatus('长链已复制。')
}

function downloadQr() {
  if (!qrUrl.value) return
  const a = document.createElement('a')
  const name = String(result.value?.cs_id || Date.now()).replace(/[^a-zA-Z0-9_-]/g, '-').slice(0, 80)
  a.href = qrUrl.value
  a.download = `ideal-${name}.png`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setStatus('二维码已下载。')
}

function saveProxy() {
  localStorage.setItem(SAVED_PROXY_KEY, form.value.proxy || '')
  persistForm()
  setStatus('代理配置已保存。')
}

function clearProxy() {
  form.value.proxy = ''
  localStorage.removeItem(SAVED_PROXY_KEY)
  persistForm()
  setStatus('已清除保存代理。')
}

function persistForm() {
  const {
    accessToken,
    proxyChainPreset,
    checkoutProxyRegion,
    providerProxyRegion,
    ...safeForm
  } = form.value
  localStorage.setItem(STORAGE_KEY, JSON.stringify(safeForm))
}

function loadForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    const {
      proxyChainPreset,
      checkoutProxyRegion,
      providerProxyRegion,
      ...savedWithoutChain
    } = saved
    form.value = { ...form.value, ...savedWithoutChain, accessToken: '' }
  } catch {}
  const savedProxy = localStorage.getItem(SAVED_PROXY_KEY)
  if (savedProxy) form.value.proxy = savedProxy
  form.value.proxyChainPreset = 'JP_NL'
  applyDefaultProxyChain()
}

watch(() => form.value.proxyChainPreset, applyDefaultProxyChain)

onMounted(() => {
  loadForm()
  reloadAll().catch(error => setStatus(cleanText(error.message || error), true))
})

onBeforeUnmount(() => {
  if (pollTimer.value) window.clearTimeout(pollTimer.value)
  if (qrUrl.value) URL.revokeObjectURL(qrUrl.value)
})
</script>
