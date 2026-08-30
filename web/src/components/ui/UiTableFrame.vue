<template>
  <section class="ui-table-frame" role="region" :aria-label="label" :aria-busy="busy ? 'true' : 'false'">
    <header v-if="$slots.header || label" class="ui-table-frame-header"><h2>{{ label }}</h2><slot name="header" /></header>
    <div class="ui-table-frame-scroll" :style="{ minWidth: minWidth !== '0' ? minWidth : undefined }">
      <div v-if="empty" class="ui-table-frame-empty"><slot name="empty">暂无数据</slot></div>
      <slot v-else />
    </div>
    <footer v-if="$slots.footer" class="ui-table-frame-footer"><slot name="footer" /></footer>
  </section>
</template>
<script setup>
defineProps({ label: { type: String, required: true }, busy: { type: Boolean, default: false }, empty: { type: Boolean, default: false }, minWidth: { type: String, default: '0' } })
</script>
