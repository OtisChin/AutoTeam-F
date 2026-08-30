<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-2">账号池操作</h2>
    <p class="text-sm text-gray-400 mb-6">
      这里集中放轮转、检查、补满、添加、清理等会直接影响账号池状态的操作。
    </p>
    <TaskPanel
      mode="pool"
      :running-task="runningTask"
      :admin-status="adminStatus"
      @task-started="$emit('task-started')"
      @refresh="$emit('refresh')"
    />
  </div>
</template>

<script setup>
import TaskPanel from './TaskPanel.vue'

defineProps({
  runningTask: Object,
  adminStatus: Object,
})

defineEmits(['task-started', 'refresh'])
</script>
