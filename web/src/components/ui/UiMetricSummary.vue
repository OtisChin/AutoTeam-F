<template>
  <UiSurface class="ui-metric-summary" :class="{ 'ui-metric-summary-compact': compact }" :aria-label="label">
    <template #header><h2 class="ui-metric-summary-label">{{ label }}</h2></template>
    <div v-if="items.length" class="ui-metric-summary-grid">
      <article v-for="item in items" :key="item.key" class="ui-metric-card">
        <div class="ui-metric-card-label">{{ item.label }}</div>
        <div class="ui-metric-card-value" :class="`ui-metric-card-value-${item.tone || 'neutral'}`">{{ item.value }}</div>
        <div v-if="item.detail" class="ui-metric-card-detail">{{ item.detail }}</div>
      </article>
    </div>
    <div v-else class="ui-metric-summary-empty"><slot name="empty">暂无数据</slot></div>
  </UiSurface>
</template>
<script setup>
import UiSurface from './UiSurface.vue'
defineProps({
  items: { type: Array, default: () => [], validator: value => value.every(item => item && typeof item.key === 'string' && typeof item.label === 'string' && (typeof item.value === 'string' || typeof item.value === 'number') && ['neutral','info','success','warning','danger'].includes(item.tone || 'neutral')) },
  label: { type: String, default: '关键指标' }, compact: { type: Boolean, default: false },
})
</script>
