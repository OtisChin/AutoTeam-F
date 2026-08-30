<template>
  <section class="settings-group" :class="`settings-group-${tone}`" :data-settings-group="id" :aria-labelledby="headingId">
    <header class="settings-group-header">
      <div class="settings-group-copy">
        <h2 :id="headingId" class="settings-group-title">{{ title }}</h2>
        <p v-if="description" class="settings-group-description">{{ description }}</p>
      </div>
      <div class="settings-group-actions">
        <slot name="actions" />
        <button
          v-if="disclosure"
          type="button"
          class="settings-group-disclosure"
          :aria-expanded="open ? 'true' : 'false'"
          :aria-controls="contentId"
          @click="$emit('update:open', !open)"
        >
          {{ open ? '收起' : '展开' }}
        </button>
      </div>
    </header>
    <div :id="contentId" class="settings-group-content" :hidden="disclosure && !open">
      <slot />
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  id: { type: String, required: true },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  tone: { type: String, default: 'neutral', validator: value => ['neutral', 'warning', 'danger'].includes(value) },
  disclosure: { type: Boolean, default: false },
  open: { type: Boolean, default: true },
})
defineEmits(['update:open'])
const headingId = computed(() => `settings-group-${props.id}-heading`)
const contentId = computed(() => `settings-group-${props.id}-content`)
</script>
