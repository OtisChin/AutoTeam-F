<template>
  <div class="ui-batch-bar">
    <div v-if="!isMobile" class="ui-batch-bar-desktop"><span class="ui-batch-bar-count">{{ count }} {{ label }}{{ itemLabel }}</span><slot /><UiButton variant="quiet" size="sm" :loading="busy" :disabled="busy" @click="$emit('clear')">清除选择</UiButton></div>
    <template v-else>
      <div class="ui-batch-bar-mobile-trigger"><UiButton variant="secondary" size="sm" @click="sheetOpen = true">{{ count }} {{ label }}{{ itemLabel }}</UiButton></div>
      <UiSheet :open="sheetOpen" label="批量操作" side="bottom" @close="sheetOpen = false"><div class="ui-batch-bar-sheet"><slot /><UiButton variant="quiet" :loading="busy" :disabled="busy" @click="$emit('clear')">清除选择</UiButton></div></UiSheet>
    </template>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'; import UiButton from './UiButton.vue'; import UiSheet from './UiSheet.vue'; import { useMediaQuery } from '../../useMediaQuery.js'
defineProps({ count: { type: Number, required: true, validator: value => Number.isFinite(value) && value >= 0 }, label: { type: String, default: '已选择' }, itemLabel: { type: String, default: '项' }, busy: { type: Boolean, default: false } })
defineEmits(['clear'])
const isMobile = useMediaQuery('(max-width: 767px)'); const sheetOpen = ref(false)
watch(isMobile, value => { if (!value) sheetOpen.value = false })
</script>
