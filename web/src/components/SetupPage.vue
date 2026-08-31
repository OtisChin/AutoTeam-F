<template>
  <div class="setup-shell">
    <div class="setup-theme-control"><ThemeSwitcher /></div>
    <div class="setup-card bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-lg">
      <h1 class="text-xl font-bold text-white text-center mb-2">AutoPro 初始配置</h1>
      <p class="text-sm text-gray-400 text-center mb-6">首次使用请填写以下配置项</p>

      <div v-if="message" class="mb-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass" :role="messageRole" aria-live="polite">
        {{ message }}
      </div>

      <div class="space-y-6">
        <div>
          <label for="setup-mail-provider" class="block text-sm text-gray-400 mb-1">
            Mail Provider
            <span class="text-red-400">*</span>
          </label>
          <select
            id="setup-mail-provider"
            v-model="provider"
            required
            aria-required="true"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option v-for="option in providerOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.description }})
            </option>
          </select>
        </div>

        <div v-if="providerFieldTitle" class="space-y-4">
          <div class="text-xs font-semibold uppercase tracking-wide text-gray-500">
            {{ providerFieldTitle }}
          </div>
          <div v-for="field in providerFields" :key="field.key">
            <label :for="fieldInputId(field)" class="block text-sm text-gray-400 mb-1">
              {{ field.prompt }}
              <span v-if="!field.optional" class="text-red-400">*</span>
            </label>
            <input
              :id="fieldInputId(field)"
              v-model="form[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              :required="!field.optional"
              :aria-required="!field.optional"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        <div class="space-y-4">
          <div class="text-xs font-semibold uppercase tracking-wide text-gray-500">
            通用配置
          </div>
          <div v-for="field in commonFields" :key="field.key">
            <label :for="fieldInputId(field)" class="block text-sm text-gray-400 mb-1">
              {{ field.prompt }}
              <span v-if="!field.optional" class="text-red-400">*</span>
              <span v-if="field.key === 'API_KEY'" class="text-gray-500 text-xs ml-1">（留空自动生成）</span>
            </label>
            <input
              :id="fieldInputId(field)"
              v-model="form[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              :required="!field.optional"
              :aria-required="!field.optional"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <button @click="save" :disabled="saving || configured"
        class="w-full mt-6 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition disabled:opacity-50">
        {{ saving ? '验证并保存中...' : configured ? '配置已保存' : '保存配置' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, reactive, watch } from 'vue'
import { api, setApiKey } from '../api.js'
import ThemeSwitcher from './ThemeSwitcher.vue'

const emit = defineEmits(['configured'])

const fields = ref([])
const provider = ref('cloudflare_temp_email')
const providerOptions = ref([])
const providerFieldGroups = ref({})
const form = reactive({})
const saving = ref(false)
const configured = ref(false)
const message = ref('')
const messageClass = ref('')
const messageRole = computed(() => messageClass.value.includes('bg-red') ? 'alert' : 'status')

const providerFields = computed(() => providerFieldGroups.value[provider.value] || [])

const providerFieldKeys = computed(() => new Set(
  Object.values(providerFieldGroups.value)
    .flatMap(group => Array.isArray(group) ? group : [])
    .map(field => field.key),
))

const commonFields = computed(() =>
  fields.value.filter((field) =>
    !providerFieldKeys.value.has(field.key) &&
    field.key !== 'MAIL_PROVIDER'
  )
)

const providerFieldTitle = computed(() => {
  if (!providerFields.value.length) return ''
  const option = providerOptions.value.find(option => option.value === provider.value)
  return `${option?.label || provider.value} 配置`
})

onMounted(async () => {
  try {
    const result = await api.getSetupStatus()
    fields.value = result.fields
    provider.value = result.provider || 'cloudflare_temp_email'
    providerOptions.value = result.provider_options || []
    providerFieldGroups.value = result.provider_fields || {}
    for (const f of result.fields) {
      form[f.key] = f.default || ''
    }
    form.MAIL_PROVIDER = provider.value
  } catch (e) {
    message.value = '获取配置状态失败: ' + e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  }
})

watch(provider, (value) => {
  form.MAIL_PROVIDER = value
})

function isSecretField(key) {
  return key.includes('PASSWORD') || key.includes('KEY') || key.includes('TOKEN')
}

function fieldInputId(field) {
  return `setup-${String(field?.key || 'field').toLowerCase().replace(/[^a-z0-9_-]+/g, '-')}`
}

async function save() {
  if (configured.value || saving.value) return
  saving.value = true
  message.value = ''
  try {
    const result = await api.saveSetup({ ...form, MAIL_PROVIDER: provider.value })
    if (result.api_key) {
      setApiKey(result.api_key)
    }
    message.value = result.message
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    configured.value = true
    emit('configured', result.api_key)
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    saving.value = false
  }
}
</script>
