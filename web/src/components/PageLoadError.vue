<template>
  <UiStatePanel
    state="error"
    title="页面加载失败"
    :message="error?.message || '请检查网络后重新加载。'"
    action-label="重新加载"
    @action="emit('retry')"
  />
  <!-- @click="emit('retry')" -->
</template>
<script setup>
import UiStatePanel from './ui/UiStatePanel.vue'
defineProps({ error: { type: Error, default: null } })
const emit = defineEmits(['retry'])
</script>
