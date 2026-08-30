<template>
  <div class="ui-data-toolbar">
    <div v-if="!isMobile" class="ui-data-toolbar-desktop">
      <div class="ui-data-toolbar-primary"><slot name="primary" /></div>
      <div class="ui-data-toolbar-filters"><slot name="filters" /></div>
      <div class="ui-data-toolbar-actions"><span v-if="resultLabel" class="ui-data-toolbar-result">{{ resultLabel }}</span><UiButton v-if="clearable && activeFilterCount > 0" variant="quiet" size="sm" @click="$emit('clear-filters')">清除筛选</UiButton><slot name="actions" /></div>
    </div>
    <template v-else>
      <div class="ui-data-toolbar-mobile-trigger"><UiButton variant="secondary" size="sm" @click="sheetOpen = true">{{ filtersLabel }}<span v-if="activeFilterCount">（{{ activeFilterCount }}）</span></UiButton><span v-if="resultLabel" class="ui-data-toolbar-result">{{ resultLabel }}</span><slot name="primary" /></div>
      <UiSheet :open="sheetOpen" :label="filtersLabel" side="bottom" @close="sheetOpen = false">
        <div class="ui-data-toolbar-sheet"><div class="ui-data-toolbar-sheet-filters"><slot name="filters" /></div><div class="ui-data-toolbar-sheet-actions"><UiButton v-if="clearable && activeFilterCount > 0" variant="quiet" @click="$emit('clear-filters')">清除筛选</UiButton><slot name="actions" /></div></div>
      </UiSheet>
    </template>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import UiButton from './UiButton.vue'; import UiSheet from './UiSheet.vue'; import { useMediaQuery } from '../../useMediaQuery.js'
defineProps({ resultLabel: { type: String, default: '' }, activeFilterCount: { type: Number, default: 0, validator: value => Number.isFinite(value) && value >= 0 }, filtersLabel: { type: String, default: '筛选' }, clearable: { type: Boolean, default: false } })
defineEmits(['clear-filters'])
const isMobile = useMediaQuery('(max-width: 767px)'); const sheetOpen = ref(false)
watch(isMobile, value => { if (!value) sheetOpen.value = false })
</script>
