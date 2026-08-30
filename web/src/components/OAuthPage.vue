<template>
  <div class="oauth-workspace">
    <WorkflowWorkspace
      title="OAuth 登录"
      eyebrow="授权 / 手动登录"
      description="生成链接、完成授权并提交回调，状态会在当前工作区持续更新。"
      :status-label="manualAccountBusy ? '授权进行中' : (manualAccountStatus?.status === 'completed' ? '授权完成' : '工作区就绪')"
      :status-tone="manualAccountBusy ? 'info' : (manualAccountStatus?.status === 'completed' ? 'success' : 'neutral')"
    >
      <template #configuration>
        <WorkflowStage name="configuration" title="生成链接" description="输入账号邮箱并启动 OAuth 会话。">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">OAuth 登录</h2>
          <p class="text-sm text-gray-400 mt-1">
            参考 CLIProxyAPI 的手动 OAuth 思路：系统先生成认证链接，你在浏览器中手动完成登录，最后把回调 URL 粘贴回来完成认证。
          </p>
        </div>
      </div>

      <div v-if="message" class="mb-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div
        v-if="manualAccountStatus?.status === 'completed' && manualAccountStatus?.account"
        class="mb-4 px-4 py-3 rounded-lg text-sm border bg-green-500/10 text-green-400 border-green-500/20"
      >
        {{ manualAccountStatus.message || `已添加账号 ${manualAccountStatus.account.email}` }}
      </div>

      <div
        v-else-if="manualAccountStatus?.status === 'error' && manualAccountStatus?.error"
        class="mb-4 px-4 py-3 rounded-lg text-sm border bg-red-500/10 text-red-400 border-red-500/20"
      >
        {{ manualAccountStatus.error }}
      </div>

      <div v-if="!manualAccountBusy" class="space-y-3">
        <input
          v-model.trim="manualEmail"
          aria-label="OAuth 账号邮箱"
          type="email"
          autocomplete="username"
          placeholder="输入账号邮箱，用于自动获取验证码"
          :disabled="manualSubmitting"
          class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
        />
        <button
          @click="startManualAccount"
          :disabled="manualSubmitting || !manualEmail"
          class="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ manualSubmitting ? '生成中...' : '生成 OAuth 链接' }}
        </button>
      </div>

      <div v-else class="space-y-4">
        <div class="text-sm text-gray-300">
          已生成 OAuth 链接。若当前机器可访问 <span class="font-mono">localhost:1455</span>，系统会自动接收回调；否则请手动粘贴最终回调 URL。
        </div>

        <div
          class="px-4 py-3 rounded-lg text-sm border"
          :class="manualAccountStatus?.auto_callback_available
            ? 'bg-blue-500/10 text-blue-300 border-blue-500/20'
            : 'bg-amber-500/10 text-amber-300 border-amber-500/20'"
        >
          {{
            manualAccountStatus?.auto_callback_available
              ? (manualAccountStatus?.playwright_available
                ? 'Playwright OAuth 已启动：系统会从邮箱服务读取验证码并自动填写，成功后会直接完成认证。'
                : '本地自动回调服务已启动：OpenAI 跳回 localhost:1455 后会自动完成认证。')
              : `本地自动回调不可用：${manualAccountStatus?.auto_callback_error || '请改用手动粘贴回调 URL'}`
          }}
        </div>

        <div
          v-if="manualAccountStatus?.playwright_error || manualAccountStatus?.helper_error"
          class="px-4 py-3 rounded-lg text-sm border bg-amber-500/10 text-amber-300 border-amber-500/20"
        >
          自动登录不可用：{{ manualAccountStatus.playwright_error || manualAccountStatus.helper_error }}
        </div>

        <div class="space-y-2">
          <div class="text-xs text-gray-500">OAuth 链接</div>
          <div class="p-3 bg-gray-800 border border-gray-700 rounded-lg text-xs font-mono break-all text-gray-200">
            {{ manualAccountStatus?.auth_url }}
          </div>
        </div>

        <div class="flex flex-wrap gap-3">
          <a
            :href="manualAccountStatus?.auth_url"
            target="_blank"
            rel="noopener noreferrer"
            class="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition"
          >
            打开 OAuth 链接
          </a>
        </div>

        <div
          v-if="manualAccountStatus?.callback_received"
          class="text-xs text-emerald-300"
        >
          已收到{{ manualAccountStatus?.callback_source === 'auto' ? '自动' : '手动' }}回调，刷新轮询中…
        </div>

        <div class="space-y-3">
          <input
            v-model.trim="manualCallbackUrl"
            aria-label="OAuth 回调 URL"
            type="text"
            placeholder="粘贴回调 URL，例如 http://localhost:1455/auth/callback?code=...&state=..."
            :disabled="manualSubmitting"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <button
            @click="submitManualCallback"
            :disabled="manualSubmitting || !manualCallbackUrl"
            class="px-4 py-2 bg-emerald-700 hover:bg-emerald-600 text-white text-sm rounded-lg transition disabled:opacity-50"
          >
            {{ manualSubmitting ? '提交中...' : '提交回调 URL' }}
          </button>
        </div>

        <div v-if="manualSubmitting && manualSubmittingHint" class="text-xs text-emerald-300">
          {{ manualSubmittingHint }}
        </div>

        <div class="flex justify-end">
          <button
            @click="cancelManualAccount"
            :disabled="manualSubmitting"
            class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
          >
            取消 OAuth 登录
          </button>
        </div>
      </div>
    </div>
        </WorkflowStage>
      </template>
      <template #progress>
        <WorkflowStage name="progress" title="完成授权" description="在浏览器中完成登录，自动回调或手动回调均可。" :state="manualAccountBusy ? 'active' : 'idle'">
          <UiStatusBadge :label="manualAccountBusy ? '等待浏览器授权' : '等待授权'" :tone="manualAccountBusy ? 'info' : 'neutral'" />
        </WorkflowStage>
      </template>
      <template #result>
        <WorkflowStage name="result" title="提交回调" description="提交最终回调 URL 后交换 token 并保存账号。" :state="manualAccountStatus?.status === 'completed' ? 'complete' : (manualAccountStatus?.status === 'error' ? 'error' : 'idle')">
          <UiStatePanel v-if="manualAccountStatus?.status === 'completed'" state="empty" title="OAuth 已完成" :message="manualAccountStatus.message || '账号已添加。'" />
          <UiStatePanel v-else-if="manualAccountStatus?.status === 'error'" state="error" title="OAuth 失败" :message="manualAccountStatus.error || '请检查回调并重试。'" />
          <UiStatePanel v-else state="empty" title="等待回调" message="完成浏览器授权后，在配置区提交回调 URL。" />
        </WorkflowStage>
      </template>
      <template #resources>
        <WorkflowStage name="resources" title="授权资源" description="当前链接和回调状态" state="idle"><UiStatusBadge label="状态由服务端同步" tone="info" /></WorkflowStage>
      </template>
    </WorkflowWorkspace>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { api } from '../api.js'
import WorkflowStage from './workflow/WorkflowStage.vue'
import WorkflowWorkspace from './workflow/WorkflowWorkspace.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'

const props = defineProps({
  manualAccountStatus: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['refresh', 'progress'])

const manualCallbackUrl = ref('')
const manualEmail = ref('')
const manualSubmitting = ref(false)
const manualSubmittingHint = ref('')
const message = ref('')
const messageClass = ref('')

const manualAccountBusy = computed(() => !!props.manualAccountStatus?.in_progress)

watch(
  () => props.manualAccountStatus,
  (next) => {
    if (!next?.in_progress) {
      manualCallbackUrl.value = ''
      manualSubmittingHint.value = ''
    } else if (next?.email) {
      manualEmail.value = next.email
    }
  },
  { immediate: true },
)

function setMessage(text, type = 'success') {
  message.value = text
  messageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 8000)
}

async function startManualAccount() {
  manualSubmitting.value = true
  manualSubmittingHint.value = '正在生成 OAuth 链接...'
  try {
    const result = await api.startManualAccount(manualEmail.value)
    setMessage(result.auth_url ? 'OAuth 链接已生成，请完成登录后粘贴回调 URL' : '已开始 OAuth 登录流程')
    emit('progress')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    manualSubmitting.value = false
    manualSubmittingHint.value = ''
  }
}

async function submitManualCallback() {
  manualSubmitting.value = true
  manualSubmittingHint.value = '正在提交回调 URL 并交换 token...'
  try {
    const result = await api.submitManualAccountCallback(manualCallbackUrl.value)
    setMessage(result.status === 'completed' ? (result.message || '账号已添加') : '回调 URL 已提交')
    emit('progress')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    manualSubmitting.value = false
    manualSubmittingHint.value = ''
  }
}

async function cancelManualAccount() {
  manualSubmitting.value = true
  try {
    await api.cancelManualAccount()
    manualCallbackUrl.value = ''
    setMessage('OAuth 登录流程已取消')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    manualSubmitting.value = false
  }
}
</script>
