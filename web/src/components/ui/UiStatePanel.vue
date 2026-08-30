<template>
  <section class="ui-state-panel" :class="`ui-state-panel-${state}`" :role="state === 'error' ? 'alert' : 'status'" aria-live="polite">
    <h2 v-if="title">{{ title }}</h2><p v-if="message">{{ message }}</p>
    <button v-if="actionLabel" type="button" class="ui-state-panel-action" @click="$emit('action')">{{ actionLabel }}</button>
    <slot />
  </section>
</template>

<script setup>
defineProps({
  state: { type: String, default: 'loading', validator: value => ['loading', 'empty', 'error', 'partial'].includes(value) },
  title: { type: String, default: '' }, message: { type: String, default: '' }, actionLabel: { type: String, default: '' },
})
defineEmits(['action'])
</script>
