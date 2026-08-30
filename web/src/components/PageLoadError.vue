<template>
  <section class="page-load-error" role="alert">
    <strong>页面加载失败</strong>
    <span>{{ error?.message || '请刷新后重试' }}</span>
    <button
      type="button"
      class="rounded-lg border border-blue-400/40 bg-blue-500/10 px-4 py-2 text-sm font-semibold text-blue-300 transition hover:bg-blue-500/20 focus:outline-none focus:ring-2 focus:ring-blue-400/60"
      @click="emit('retry')"
    >
      重新加载
    </button>
  </section>
</template>

<script setup>
defineProps({ error: { type: Error, default: null } })
const emit = defineEmits(['retry'])
</script>
