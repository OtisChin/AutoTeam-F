<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-2">任务历史</h2>
    <p class="text-sm text-gray-400 mb-6">
      查看后台任务的执行状态、耗时、参数和结果，便于排查失败原因。
    </p>
    <TaskHistory :tasks="tasks" />
  </div>
</template>

<script setup>
import TaskHistory from './TaskHistory.vue'

defineProps({
  tasks: Array,
})
</script>
