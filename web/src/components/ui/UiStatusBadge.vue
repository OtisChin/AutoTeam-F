<template>
  <span class="ui-status-badge" :class="`ui-status-badge-${tone}`">
    <span v-if="dot" class="ui-status-badge-dot" aria-hidden="true" />
    <span>{{ label }}</span>
  </span>
</template>

<script setup>
defineProps({
  tone: { type: String, default: 'neutral', validator: value => ['neutral', 'info', 'success', 'warning', 'danger'].includes(value) },
  label: { type: String, required: true },
  dot: { type: Boolean, default: true },
})
</script>
