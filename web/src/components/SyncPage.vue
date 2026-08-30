<template>
  <div>
    <UiPageHeader title="同步中心" eyebrow="系统 / Sync" description="本地、CPA 与账号凭据对账。" />
    <UiSurface variant="panel" class="mt-6">
    <TaskPanel
      mode="sync"
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
