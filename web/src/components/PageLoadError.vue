<template>
  <section class="page-load-error" role="alert">
    <strong>页面加载失败</strong>
    <span>{{ error?.message || '请刷新后重试' }}</span>
  </section>
</template>

<script setup>
defineProps({ error: { type: Error, default: null } })
</script>
