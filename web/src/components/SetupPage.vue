<template>
  <div class="min-h-screen flex items-center justify-center p-4">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-6 w-full max-w-lg">
      <h1 class="text-xl font-bold text-white text-center mb-2">AutoTeam 初始配置</h1>
      <p class="text-sm text-gray-400 text-center mb-6">首次使用请填写以下配置项</p>

      <div v-if="message" class="mb-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div class="space-y-6">
        <div>
          <label class="block text-sm text-gray-400 mb-1">
            Mail Provider
            <span class="text-red-400">*</span>
          </label>
          <select
            v-model="provider"
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
            <label class="block text-sm text-gray-400 mb-1">
              {{ field.prompt }}
              <span v-if="!field.optional" class="text-red-400">*</span>
            </label>
            <input
              v-model="form[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        <div class="space-y-4">
          <div class="text-xs font-semibold uppercase tracking-wide text-gray-500">
            通用配置
          </div>
          <div v-for="field in commonFields" :key="field.key">
            <label class="block text-sm text-gray-400 mb-1">
              {{ field.prompt }}
              <span v-if="!field.optional" class="text-red-400">*</span>
              <span v-if="field.key === 'API_KEY'" class="text-gray-500 text-xs ml-1">（留空自动生成）</span>
            </label>
            <input
              v-model="form[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <button @click="save" :disabled="saving"
        class="w-full mt-6 px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition disabled:opacity-50">
        {{ saving ? '验证并保存中...' : '保存配置' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, reactive, watch } from 'vue'
import { api, setApiKey } from '../api.js'

const emit = defineEmits(['configured'])

const fields = ref([])
const provider = ref('cloudflare_temp_email')
const providerOptions = ref([])
const providerFieldGroups = ref({})
const form = reactive({})
const saving = ref(false)
const message = ref('')
const messageClass = ref('')

const providerFields = computed(() => providerFieldGroups.value[provider.value] || [])

const commonFields = computed(() =>
  fields.value.filter((field) =>
    !field.key.startsWith('CLOUDFLARE_TEMP_EMAIL_') &&
    !field.key.startsWith('CLOUD_MAIL_') &&
    !field.key.startsWith('OUTLOOK_') &&
    !field.key.startsWith('LUCKMAIL_') &&
    field.key !== 'MAIL_PROVIDER'
  )
)

const providerFieldTitle = computed(() =>
  provider.value === 'cloud-mail'
    ? 'cloud-mail 配置'
    : provider.value === 'outlook'
      ? 'Outlook 配置'
      : provider.value === 'luckmail'
        ? 'LuckMail 配置'
        : 'cloudflare_temp_email 配置'
)

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

async function save() {
  saving.value = true
  message.value = ''
  try {
    const result = await api.saveSetup({ ...form, MAIL_PROVIDER: provider.value })
    if (result.api_key) {
      setApiKey(result.api_key)
    }
    message.value = result.message
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    setTimeout(() => emit('configured'), 1000)
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    saving.value = false
  }
}
</script>
