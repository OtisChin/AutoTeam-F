<template>
  <header class="ui-page-header">
    <div class="ui-page-header-copy">
      <p v-if="eyebrow" class="ui-page-header-eyebrow">{{ eyebrow }}</p>
      <h1 class="ui-page-header-title">{{ title }}</h1>
      <p v-if="description" class="ui-page-header-description">{{ description }}</p>
      <span v-if="status" class="ui-page-header-status">{{ status }}</span>
      <slot />
    </div>
    <div v-if="$slots.actions" class="ui-page-header-actions"><slot name="actions" /></div>
  </header>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  eyebrow: { type: String, default: '' },
  description: { type: String, default: '' },
  status: { type: String, default: '' },
})
</script>
