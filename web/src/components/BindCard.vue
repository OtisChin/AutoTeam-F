<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-2">自动绑卡服务</h2>
    <p class="text-sm text-gray-400 mb-6">
      支持生成官方优惠链接，visa卡池管理，以及一键绑卡服务。
    </p>

    <div class="flex flex-wrap gap-2 mb-6">
      <button
        @click="activeTab = 'generate'"
        class="px-4 py-2 rounded-lg text-sm border transition"
        :class="activeTab === 'generate'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
        生成支付链接
      </button>
      <button
        @click="activeTab = 'pool'"
        class="px-4 py-2 rounded-lg text-sm border transition"
        :class="activeTab === 'pool'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
        卡池
      </button>
    </div>

    <div v-if="activeTab === 'generate'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
      <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <h3 class="text-lg font-semibold text-white">生成支付链接</h3>
          <p class="text-sm text-gray-400 mt-1">
            选择套餐类型和优惠活动，系统将生成官方绑卡链接。
          </p>
        </div>
      </div>

      <div v-if="message" class="mt-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)] gap-4">
        <div class="min-w-0 space-y-3">
          <div>
            <label class="block text-sm text-gray-400 mb-1">套餐类型</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="bindForm.planType = 'plus'"
                :disabled="generating"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="bindForm.planType === 'plus'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                Plus
              </button>
              <button
                @click="bindForm.planType = 'team'"
                :disabled="generating"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="bindForm.planType === 'team'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                Team
              </button>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">优惠活动</label>
            <select
              v-model="bindForm.promoId"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="promo in filteredPromoOptions" :key="promo.id" :value="promo.id">
                {{ promo.name }}
              </option>
            </select>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">号池账号</label>
            <div class="flex gap-2">
              <select
                v-model="selectedAccountEmail"
                :disabled="generating || loadingAccounts"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option value="">{{ loadingAccounts ? '加载账号中...' : '支持选择号池账号' }}</option>
                <option v-for="account in accountOptions" :key="account.email" :value="account.email">
                  {{ account.email }}
                </option>
              </select>
              <button
                @click="useAccountToken"
                :disabled="generating || loadingAccounts || loadingAccountToken || !selectedAccountEmail"
                class="shrink-0 px-4 py-2 rounded-lg text-sm border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition disabled:opacity-50">
                {{ loadingAccountToken ? '提取中...' : '提取 Token' }}
              </button>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">国家</label>
            <select
              v-model="bindForm.country"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="US">美国 (US)</option>
              <option value="GB">英国 (GB)</option>
              <option value="DE">德国 (DE)</option>
              <option value="FR">法国 (FR)</option>
              <option value="CA">加拿大 (CA)</option>
              <option value="AU">澳大利亚 (AU)</option>
              <option value="JP">日本 (JP)</option>
              <option value="SG">新加坡 (SG)</option>
              <option value="HK">香港 (HK)</option>
            </select>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">货币</label>
            <div class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white">
              {{ bindForm.currency }}
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">支付模式</label>
            <select
              v-model="bindForm.checkoutMode"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="custom">代付短链接（站内支付，推荐）</option>
              <option value="hosted">托管模式（Stripe 外部页面）</option>
            </select>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>套餐：<span class="text-gray-200">{{ bindForm.planType === 'plus' ? 'ChatGPT Plus' : 'ChatGPT Team' }}</span></div>
            <div>优惠：<span class="text-gray-200">{{ selectedPromoName }}</span></div>
            <div>国家：<span class="text-gray-200">{{ bindForm.country }}</span> / 货币：<span class="text-gray-200">{{ bindForm.currency }}</span></div>
            <div>支付模式：<span class="text-gray-200">{{ bindForm.checkoutMode === 'custom' ? '代付短链接（站内支付，推荐）' : '托管模式（Stripe 外部页面）' }}</span></div>
          </div>

        </div>

        <div class="min-w-0 min-h-0 space-y-4">
          <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 h-[270px] flex flex-col">
            <div class="mb-3 flex items-start justify-between gap-3">
              <div>
                <h3 class="text-white font-semibold">Access Token</h3>
                <div class="text-xs text-gray-500 mt-0.5">输入 ChatGPT access_token</div>
              </div>
              <button
                @click="generateLink"
                :disabled="generating || !bindForm.accessToken"
                class="shrink-0 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition disabled:opacity-50">
                {{ generating ? '生成中...' : '生成绑卡链接' }}
              </button>
            </div>
            <textarea
              v-model.trim="bindForm.accessToken"
              placeholder="输入 ChatGPT access_token"
              :disabled="generating"
              class="flex-1 min-h-0 w-full resize-none px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 h-[170px] flex flex-col">
            <div class="mb-3">
              <h3 class="text-white font-semibold">支付链接</h3>
              <div class="text-xs text-gray-500 mt-0.5">生成后可复制或直接打开</div>
            </div>
            <div class="link-panel flex-1 min-h-0 rounded-lg border border-gray-800 bg-gray-900 p-3 overflow-y-auto" style="scrollbar-width: none; -ms-overflow-style: none;">
              <div v-if="!currentLink" class="text-sm text-gray-500">
                尚未生成链接，请先配置并点击"生成绑卡链接"
              </div>
              <div v-else class="space-y-3">
                <div class="text-sm text-blue-400 whitespace-nowrap font-mono select-all overflow-x-auto" style="scrollbar-width: none; -ms-overflow-style: none;">
                  {{ currentLink }}
                </div>
              </div>
            </div>
            <div class="mt-3 flex items-center gap-3">
              <button
                @click="copyCurrentLink"
                :disabled="!currentLink"
                class="px-3 py-1.5 rounded-lg text-xs border transition disabled:opacity-50"
                :class="currentLink
                  ? 'bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border-emerald-500/30'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700'">
                复制链接
              </button>
              <button
                @click="openLink"
                :disabled="!currentLink"
                class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition disabled:opacity-50">
                打开链接
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <BindCardPool v-else />

    <div v-if="activeTab === 'generate'" class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h3 class="text-lg font-semibold text-white mb-4">历史记录</h3>
      <div class="space-y-2">
        <div v-if="!history.length" class="text-sm text-gray-500">暂无历史记录</div>
        <div
          v-for="(item, idx) in history"
          :key="idx"
          class="border border-gray-800 rounded-lg px-3 py-3 bg-gray-900/70"
        >
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-mono text-gray-500">{{ item.time }}</span>
            <span class="text-xs uppercase tracking-wide" :class="item.success ? 'text-emerald-400' : 'text-red-400'">
              {{ item.success ? '成功' : '失败' }}
            </span>
          </div>
          <div class="mt-2 text-sm text-gray-200">{{ item.plan }} / {{ item.promo }}</div>
          <div v-if="item.link" class="mt-2 text-xs text-blue-400 truncate cursor-pointer hover:text-blue-300" @click="openHistoryLink(item.link)">
            {{ item.link }}
          </div>
          <div v-if="item.error" class="mt-2 text-xs text-red-400">
            {{ item.error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import BindCardPool from './BindCardPool.vue'

const BIND_HISTORY_KEY = 'autoteam_bind_history_v1'

const activeTab = ref('generate')
const message = ref('')
const messageClass = ref('')
const generating = ref(false)
const currentLink = ref('')
const checkoutSessionId = ref('')
const rawGeneratedUrl = ref('')
const history = ref([])
const accountOptions = ref([])
const loadingAccounts = ref(false)
const loadingAccountToken = ref(false)
const selectedAccountEmail = ref('')

const bindForm = ref({
  accessToken: '',
  planType: 'plus',
  promoId: 'plus-1-month-free',
  country: 'SG',
  currency: 'SGD',
  checkoutMode: 'custom',
})

const countryCurrencyMap = {
  US: 'USD',
  GB: 'GBP',
  DE: 'EUR',
  FR: 'EUR',
  CA: 'CAD',
  AU: 'AUD',
  JP: 'JPY',
  SG: 'SGD',
  HK: 'HKD',
}

const promoOptions = [
  { id: 'plus-1-month-free', name: 'Plus 1个月免费试用', plan: 'plus' },
  { id: 'team-1-month-free', name: 'Team 1个月免费试用', plan: 'team' },
]

const filteredPromoOptions = computed(() => {
  return promoOptions.filter(p => p.plan === bindForm.value.planType)
})

const selectedPromoName = computed(() => {
  const promo = promoOptions.find(p => p.id === bindForm.value.promoId)
  return promo?.name || bindForm.value.promoId
})

function setMessage(text, ok = true) {
  message.value = text
  messageClass.value = ok
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 8000)
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(BIND_HISTORY_KEY)
    if (raw) {
      history.value = JSON.parse(raw)
    }
  } catch (e) {
    console.error('loadHistory', e)
  }
}

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const accounts = await api.getAccounts()
    accountOptions.value = (accounts || [])
      .filter(account => account?.email && account?.auth_session_file)
      .sort((a, b) => String(a.email).localeCompare(String(b.email)))
  } catch (e) {
    setMessage(`加载号池账号失败: ${e.message}`, false)
  } finally {
    loadingAccounts.value = false
  }
}

function saveHistory() {
  try {
    localStorage.setItem(BIND_HISTORY_KEY, JSON.stringify(history.value.slice(0, 50)))
  } catch (e) {
    console.error('saveHistory', e)
  }
}

function formatDate() {
  const d = new Date()
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

watch(
  () => bindForm.value.planType,
  (planType) => {
    const nextPromo = promoOptions.find(p => p.plan === planType)
    if (nextPromo && nextPromo.id !== bindForm.value.promoId) {
      bindForm.value.promoId = nextPromo.id
    }
    bindForm.value.country = 'SG'
    bindForm.value.currency = 'SGD'
    if (planType === 'team') {
      bindForm.value.checkoutMode = 'custom'
    } else if (!['custom', 'hosted'].includes(bindForm.value.checkoutMode)) {
      bindForm.value.checkoutMode = 'custom'
    }
  }
)

watch(
  () => bindForm.value.country,
  (country) => {
    bindForm.value.currency = countryCurrencyMap[country] || 'USD'
  },
  { immediate: true }
)

async function useAccountToken() {
  if (!selectedAccountEmail.value) {
    setMessage('请先选择号池账号', false)
    return
  }
  loadingAccountToken.value = true
  try {
    const result = await api.getCodexAuth(selectedAccountEmail.value)
    const token = result?.codex_auth?.tokens?.access_token || ''
    if (!token) {
      throw new Error('对应 auth_session 文件中没有 accessToken')
    }
    bindForm.value.accessToken = token
    setMessage(`已提取 ${selectedAccountEmail.value} 的 access_token`)
  } catch (e) {
    setMessage(`提取 access_token 失败: ${e.message}`, false)
  } finally {
    loadingAccountToken.value = false
  }
}

async function generateLink() {
  if (generating.value) return
  if (!bindForm.value.accessToken) {
    setMessage('请输入 access_token', false)
    return
  }
  generating.value = true
  currentLink.value = ''
  checkoutSessionId.value = ''
  rawGeneratedUrl.value = ''

  try {
    const planName = bindForm.value.planType === 'plus' ? 'chatgptplusplan' : 'chatgptteamplan'

    const payload = {
      access_token: bindForm.value.accessToken,
      plan_name: planName,
      promo_campaign: {
        promo_campaign_id: bindForm.value.promoId,
        is_coupon_from_query_param: bindForm.value.planType === 'team',
      },
      billing_details: {
        country: bindForm.value.country,
        currency: bindForm.value.currency,
      },
      checkout_ui_mode: bindForm.value.checkoutMode,
    }

    if (bindForm.value.planType === 'team') {
      payload.team_plan_data = {
        workspace_name: 'Sam Altman',
        price_interval: 'month',
        seat_quantity: 5,
      }
    }

    const result = await api.generateBindLink(payload)
    
    let link = ''
    let sessionId = ''
    let success = false

    if (result.url) {
      link = result.url
      sessionId = result.checkout_session_id || ''
      rawGeneratedUrl.value = result.url
      success = true
      setMessage('生成成功！请点击链接或复制到浏览器打开')
    } else if (result.checkout_session_id) {
      sessionId = result.checkout_session_id
      link = bindForm.value.planType === 'team'
        ? `https://chatgpt.com/checkout/openai_ie/${sessionId}`
        : `https://chatgpt.com/checkout/openai_llc/${sessionId}`
      success = true
      setMessage('生成成功！请点击链接或复制到浏览器打开')
    } else {
      const errorMsg = result.detail || JSON.stringify(result)
      setMessage(`生成失败: ${errorMsg}`, false)
      history.value.unshift({
        time: formatDate(),
        plan: bindForm.value.planType.toUpperCase(),
        promo: selectedPromoName.value,
        link: '',
        error: errorMsg,
        success: false,
      })
      saveHistory()
    }

    if (success) {
      currentLink.value = link
      checkoutSessionId.value = sessionId
      history.value.unshift({
        time: formatDate(),
        plan: bindForm.value.planType.toUpperCase(),
        promo: selectedPromoName.value,
        link: link,
        error: '',
        success: true,
      })
      saveHistory()
    }
  } catch (e) {
    setMessage(`生成失败: ${e.message}`, false)
    history.value.unshift({
      time: formatDate(),
      plan: bindForm.value.planType.toUpperCase(),
      promo: selectedPromoName.value,
      link: '',
      error: e.message,
      success: false,
    })
    saveHistory()
  } finally {
    generating.value = false
  }
}

function copyCurrentLink() {
  if (currentLink.value) {
    navigator.clipboard.writeText(currentLink.value)
    setMessage('链接已复制到剪贴板')
  }
}

function openLink() {
  if (currentLink.value) {
    window.open(currentLink.value, '_blank')
  }
}

function openBackupLink() {
  if (checkoutSessionId.value) {
    const link = bindForm.value.planType === 'team'
      ? `https://chatgpt.com/checkout/openai_ie/${checkoutSessionId.value}`
      : `https://chatgpt.com/checkout/openai_llc/${checkoutSessionId.value}`
    window.open(link, '_blank')
  }
}

function openHistoryLink(link) {
  if (link) {
    window.open(link, '_blank')
  }
}

onMounted(() => {
  loadHistory()
  loadAccounts()
})

watch(activeTab, (tab) => {
  if (tab === 'generate') {
    loadAccounts()
  }
})
</script>

<style scoped>
.link-panel::-webkit-scrollbar {
  display: none;
}

.link-panel [style*="overflow-x-auto"]::-webkit-scrollbar {
  display: none;
}
</style>
