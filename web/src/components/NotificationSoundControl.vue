<template>
  <div class="inline-flex flex-wrap items-center gap-2">
    <button
      type="button"
      role="switch"
      :aria-checked="String(enabled)"
      :disabled="disabled || unlocking"
      class="inline-flex items-center gap-2 rounded-lg border px-3 py-2.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-50"
      :class="enabled ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200' : 'border-gray-700 bg-gray-900 text-gray-200 hover:bg-gray-800'"
      @click="toggleSound"
    >
      <span class="relative inline-flex h-4 w-7 items-center rounded-full transition" :class="enabled ? 'bg-emerald-500/80' : 'bg-gray-700'">
        <span class="inline-block h-3 w-3 rounded-full bg-white transition" :class="enabled ? 'translate-x-3.5' : 'translate-x-0.5'"></span>
      </span>
      <span>启用提示音</span>
      <span v-if="unlocking" class="text-[11px] text-gray-400">启用中...</span>
    </button>
    <span v-if="message" class="max-w-[220px] text-[11px]" :class="error ? 'text-rose-300' : 'text-gray-400'">{{ message }}</span>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { isNotificationSoundUnlocked, unlockNotificationSounds } from '../notificationSounds.js'

const props = defineProps({
  modelValue: { type: Boolean, default: true },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['update:modelValue'])

const unlocked = ref(isNotificationSoundUnlocked())
const unlocking = ref(false)
const message = ref('')
const error = ref(false)

const enabled = computed(() => Boolean(props.modelValue && unlocked.value))

async function toggleSound() {
  if (enabled.value) {
    emit('update:modelValue', false)
    error.value = false
    message.value = '已关闭'
    return
  }
  unlocking.value = true
  error.value = false
  message.value = ''
  try {
    await unlockNotificationSounds()
    unlocked.value = true
    emit('update:modelValue', true)
  } catch (err) {
    error.value = true
    emit('update:modelValue', false)
    message.value = err?.message || '启用失败'
  } finally {
    unlocking.value = false
  }
}
</script>
