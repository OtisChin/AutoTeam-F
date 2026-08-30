<template>
  <div class="setup-shell">
    <div class="setup-theme-control"><ThemeSwitcher /></div>
    <section class="setup-card" aria-labelledby="setup-title">
      <header class="setup-heading">
        <span class="workspace-eyebrow">首次运行</span>
        <h1 id="setup-title">配置 AutoToken</h1>
        <p>连接邮箱服务并创建控制台访问凭证。</p>
      </header>
      <div v-if="message" class="setup-message" :class="messageClass" :role="messageRole" aria-live="polite">{{ message }}</div>
      <div class="setup-form">
        <label class="sr-only" for="setup-mail-provider">Mail Provider</label>
        <UiFormField id="setup-mail-provider" label="Mail Provider" help="选择注册流程使用的邮箱供应商。" required>
          <template #default="{ inputId, describedBy }">
            <select :id="inputId" v-model="provider" :aria-describedby="describedBy" required>
              <option v-for="option in providerOptions" :key="option.value" :value="option.value">{{ option.label }}（{{ option.description }}）</option>
            </select>
          </template>
        </UiFormField>
        <section v-if="providerFieldTitle" class="setup-field-group">
          <h2>{{ providerFieldTitle }}</h2>
          <UiFormField v-for="field in providerFields" :id="fieldInputId(field)" :key="field.key" :label="field.prompt" :required="!field.optional">
            <template #default="{ inputId, describedBy }">
              <label class="sr-only" :for="fieldInputId(field)">{{ field.prompt }}</label>
              <input :id="inputId" v-model="form[field.key]" :type="isSecretField(field.key) ? 'password' : 'text'" :placeholder="field.default || ''" :required="!field.optional" :aria-required="!field.optional" :aria-describedby="describedBy" />
            </template>
          </UiFormField>
        </section>
        <section class="setup-field-group">
          <h2>通用配置</h2>
          <UiFormField v-for="field in commonFields" :id="fieldInputId(field)" :key="field.key" :label="field.prompt" :help="field.key === 'API_KEY' ? '留空时自动生成。' : ''" :required="!field.optional">
            <template #default="{ inputId, describedBy }">
              <label class="sr-only" :for="fieldInputId(field)">{{ field.prompt }}</label>
              <input :id="inputId" v-model="form[field.key]" :type="isSecretField(field.key) ? 'password' : 'text'" :placeholder="field.default || ''" :required="!field.optional" :aria-required="!field.optional" :aria-describedby="describedBy" />
            </template>
          </UiFormField>
        </section>
      </div>
      <UiButton class="setup-submit" variant="primary" :disabled="saving || configured" :loading="saving" @click="save">{{ configured ? '配置已保存' : '保存配置' }}</UiButton>
    </section>
  </div>
</template>
<script setup>
import ThemeSwitcher from './ThemeSwitcher.vue'
import UiButton from './ui/UiButton.vue'
import UiFormField from './ui/UiFormField.vue'

import { computed, ref, onMounted, reactive, watch } from 'vue'
import { api, setApiKey } from '../api.js'

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

