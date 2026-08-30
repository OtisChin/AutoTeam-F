<template>
  <section class="task-history-workspace">
    <UiMetricSummary :items="metricItems" label="任务指标" />
    <UiDataToolbar :result-label="`${filteredTasks.length} / ${tasks.length} 条任务`" :active-filter-count="activeFilterCount" clearable @clear-filters="clearFilters">
      <template #filters>
        <label class="ui-inline-field"><span>搜索</span><input v-model.trim="query" type="search" placeholder="任务 ID、参数或结果" /></label>
        <label class="ui-inline-field"><span>状态</span><select v-model="status"><option value="">全部</option><option value="pending">待执行</option><option value="running">执行中</option><option value="completed">已完成</option><option value="failed">失败</option></select></label>
        <label class="ui-inline-field"><span>命令</span><input v-model.trim="command" type="search" placeholder="筛选命令" /></label>
      </template>
    </UiDataToolbar>
    <UiStatePanel v-if="!tasks.length" state="empty" title="暂无任务记录" message="后台任务完成后会显示在这里。" />
    <UiTableFrame v-else label="任务历史" :empty="!pagedTasks.length">
      <table class="ui-data-table">
        <thead><tr><th>任务 ID</th><th>命令</th><th>状态</th><th>创建时间</th><th>耗时</th><th>结果</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="task in pagedTasks" :key="task.task_id || task.id">
            <td><code>{{ task.task_id || task.id || '-' }}</code></td>
            <td>{{ task.command || '-' }}</td>
            <td><UiStatusBadge :label="taskStatusPresentation(task.status).label" :tone="taskStatusPresentation(task.status).tone" /></td>
            <td>{{ formatTime(task.created_at) }}</td><td>{{ duration(task) }}</td>
            <td class="ui-table-truncate">{{ task.error || formatResult(task.result) }}</td>
            <td><UiButton variant="quiet" size="sm" @click="openDetail(task)">详情</UiButton></td>
          </tr>
        </tbody>
      </table>
      <template #footer><UiPagination v-model:page="page" :page-size="pageSize" :total-items="filteredTasks.length" :page-sizes="[25, 50, 100]" @update:page-size="setPageSize" /></template>
    </UiTableFrame>
    <AccessibleModal v-if="detailTask" label="任务详情" @close="detailTask = null">
      <section class="ui-modal-card"><header class="ui-modal-header"><h2>任务详情</h2><UiButton variant="quiet" size="sm" @click="detailTask = null">关闭</UiButton></header><div class="ui-modal-body ui-detail-grid"><dl><dt>任务 ID</dt><dd>{{ detailTask.task_id || detailTask.id || '-' }}</dd><dt>命令</dt><dd>{{ detailTask.command || '-' }}</dd><dt>状态</dt><dd><UiStatusBadge :label="taskStatusPresentation(detailTask.status).label" :tone="taskStatusPresentation(detailTask.status).tone" /></dd></dl><pre>{{ JSON.stringify({ params: detailTask.params, result: detailTask.result, error: detailTask.error }, null, 2) }}</pre></div></section>
    </AccessibleModal>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { filterTaskHistory, pageTaskHistory, summarizeTaskHistory, TASK_HISTORY_PAGE_SIZE } from '../taskHistoryData.js'
import { taskStatusPresentation } from '../operationsPresentation.js'
import AccessibleModal from './AccessibleModal.vue'
import UiButton from './ui/UiButton.vue'
import UiDataToolbar from './ui/UiDataToolbar.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPagination from './ui/UiPagination.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'
import UiTableFrame from './ui/UiTableFrame.vue'

const props = defineProps({ tasks: { type: Array, default: () => [] } })
const query = ref(''); const status = ref(''); const command = ref(''); const page = ref(1); const pageSize = ref(TASK_HISTORY_PAGE_SIZE); const detailTask = ref(null)
const filteredTasks = computed(() => filterTaskHistory(props.tasks, { query: query.value, status: status.value, command: command.value }))
const paged = computed(() => pageTaskHistory(filteredTasks.value, page.value, pageSize.value))
const pagedTasks = computed(() => paged.value.rows)
const summary = computed(() => summarizeTaskHistory(props.tasks))
const metricItems = computed(() => [{ key: 'total', label: '总数', value: summary.value.total }, { key: 'active', label: '进行中', value: summary.value.active, tone: 'warning' }, { key: 'completed', label: '已完成', value: summary.value.completed, tone: 'success' }, { key: 'failed', label: '失败', value: summary.value.failed, tone: 'danger' }])
const activeFilterCount = computed(() => [query.value, status.value, command.value].filter(Boolean).length)
watch(filteredTasks, () => { page.value = 1 })
function setPageSize(value) { pageSize.value = Number(value) || TASK_HISTORY_PAGE_SIZE; page.value = 1 }
function clearFilters() { query.value = ''; status.value = ''; command.value = '' }
function openDetail(task) { detailTask.value = task }
function formatTime(ts) { if (!ts) return '-'; const d = new Date(Number(ts) * 1000); return Number.isNaN(d.getTime()) ? '-' : d.toLocaleString() }
function duration(task) { const start = Number(task?.started_at || task?.created_at); const end = Number(task?.finished_at || (task?.status === 'running' ? Date.now() / 1000 : 0)); if (!start || !end) return '-'; const sec = Math.max(0, Math.round(end - start)); return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${sec % 60}s` }
function formatResult(result) { if (result == null) return '-'; if (typeof result === 'string') return result; if (result.message) return result.message; try { return JSON.stringify(result) } catch { return String(result) } }
</script>
