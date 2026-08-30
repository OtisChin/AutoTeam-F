<template>
  <nav class="ui-pagination" aria-label="分页">
    <div class="ui-pagination-summary">共 {{ totalItems }} {{ itemLabel }}</div>
    <label v-if="pageSizes.length" class="ui-pagination-size">每页 <select :value="pageSize" @change="changePageSize"><option v-for="size in pageSizes" :key="size" :value="size">{{ size }}</option></select></label>
    <div class="ui-pagination-controls"><UiButton variant="quiet" size="sm" :disabled="currentPage <= 1" @click="changePage(currentPage - 1)">上一页</UiButton><span class="ui-pagination-current">{{ currentPage }} / {{ pageCount }}</span><UiButton variant="quiet" size="sm" :disabled="currentPage >= pageCount" @click="changePage(currentPage + 1)">下一页</UiButton></div>
  </nav>
</template>
<script setup>
import { computed } from 'vue'; import UiButton from './UiButton.vue'
const props = defineProps({ page: { type: Number, required: true, validator: value => Number.isFinite(value) }, pageSize: { type: Number, required: true, validator: value => Number.isFinite(value) && value > 0 }, pageSizes: { type: Array, default: () => [], validator: value => value.every(size => Number.isFinite(size) && size > 0) }, totalItems: { type: Number, required: true, validator: value => Number.isFinite(value) && value >= 0 }, itemLabel: { type: String, default: '条记录' } })
const emit = defineEmits(['update:page','update:pageSize'])
const pageCount = computed(() => Math.max(1, Math.ceil(Math.max(0, props.totalItems) / Math.max(1, props.pageSize))))
const currentPage = computed(() => Math.min(pageCount.value, Math.max(1, Number(props.page) || 1)))
function changePage(value) { emit('update:page', Math.min(pageCount.value, Math.max(1, Math.floor(Number(value) || 1)))) }
function changePageSize(event) { const size = Math.max(1, Number(event.target.value) || 1); emit('update:pageSize', size); const max = Math.max(1, Math.ceil(Math.max(0, props.totalItems) / size)); emit('update:page', Math.min(max, Math.max(1, Number(props.page) || 1))) }
</script>
