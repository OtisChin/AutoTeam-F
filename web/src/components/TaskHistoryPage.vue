<template>
  <div class="task-history-page">
    <UiPageHeader title="任务历史" eyebrow="系统 / Tasks" description="查看后台任务的执行状态、耗时、参数和结果。" />
    <TaskHistory :tasks="tasks" />
  </div>
</template>

<script setup>
import TaskHistory from './TaskHistory.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
defineProps({ tasks: { type: Array, default: () => [] } })
</script>
