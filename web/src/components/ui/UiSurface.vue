<template>
  <component :is="as" class="ui-surface" :class="[`ui-surface-${variant}`, `ui-surface-padding-${padding}`]" :aria-labelledby="labelledby || undefined">
    <header v-if="$slots.header" class="ui-surface-header"><slot name="header" /></header>
    <div class="ui-surface-content"><slot /></div>
    <footer v-if="$slots.footer" class="ui-surface-footer"><slot name="footer" /></footer>
  </component>
</template>

<script setup>
defineProps({
  as: { type: String, default: 'section', validator: value => ['section', 'div', 'article', 'aside'].includes(value) },
  variant: { type: String, default: 'panel', validator: value => ['panel', 'strong', 'inset'].includes(value) },
  padding: { type: String, default: 'md', validator: value => ['none', 'sm', 'md', 'lg'].includes(value) },
  labelledby: { type: String, default: '' },
})
</script>
