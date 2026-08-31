<template>
  <UiStatePanel
    title="页面加载失败"
    :message="error?.message || '请刷新后重试'"
    state="error"
    @action="emit('retry')"
  >
    <button type="button" class="page-load-retry" @click="emit('retry')">重新加载</button>
  </UiStatePanel>
</template>

<script setup>
import UiStatePanel from './ui/UiStatePanel.vue'

defineProps({ error: { type: Error, default: null } })
const emit = defineEmits(['retry'])
</script>
