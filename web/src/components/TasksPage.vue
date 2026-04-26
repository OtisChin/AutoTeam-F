<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-6">操作 & 任务</h2>
    <TaskPanel :running-task="runningTask" :admin-status="adminStatus" @task-started="$emit('task-started')" @refresh="$emit('refresh')" />
    <TaskHistory :tasks="tasks" />
  </div>
</template>

<script setup>
import TaskPanel from './TaskPanel.vue'
import TaskHistory from './TaskHistory.vue'

defineProps({
  runningTask: Object,
  adminStatus: Object,
  tasks: Array,
})
defineEmits(['task-started', 'refresh'])
</script>
