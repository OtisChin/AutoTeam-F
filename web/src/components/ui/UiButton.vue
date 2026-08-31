<template>
  <button :type="type" class="ui-button" :class="[`ui-button-${variant}`, `ui-button-${size}`]" :disabled="disabled || loading" :aria-busy="loading ? 'true' : undefined" @click="$emit('click', $event)">
    <span v-if="$slots.icon" class="ui-button-icon"><slot name="icon" /></span>
    <span class="ui-button-label"><slot /></span>
    <span v-if="loading" class="ui-button-spinner" aria-hidden="true" />
  </button>
</template>

<script setup>
defineProps({
  type: { type: String, default: 'button', validator: value => ['button', 'submit', 'reset'].includes(value) },
  variant: { type: String, default: 'primary', validator: value => ['primary', 'secondary', 'quiet', 'danger'].includes(value) },
  size: { type: String, default: 'md', validator: value => ['sm', 'md'].includes(value) },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
})
defineEmits(['click'])
</script>
