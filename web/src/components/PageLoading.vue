<template>
  <UiStatePanel
    state="loading"
    title="正在打开工作区"
    message="首次打开时按需加载，不阻塞其他操作。"
  />
</template>
<script setup>
import UiStatePanel from './ui/UiStatePanel.vue'
</script>
