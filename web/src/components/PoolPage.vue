<template>
  <div>
    <UiPageHeader title="账号池操作" eyebrow="账号 / Pool" description="轮转、检查、补位与清理账号池。" />
    <UiSurface variant="panel" class="mt-6">
    <TaskPanel
      mode="pool"
      :running-task="runningTask"
      :admin-status="adminStatus"
      @task-started="$emit('task-started')"
      @refresh="$emit('refresh')"
    />
    </UiSurface>
  </div>
</template>

<script setup>
import TaskPanel from './TaskPanel.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiSurface from './ui/UiSurface.vue'

defineProps({
  runningTask: Object,
  adminStatus: Object,
})

defineEmits(['task-started', 'refresh'])
</script>
