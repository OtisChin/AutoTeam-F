<template>
  <div class="settings-workspace" :aria-label="ariaLabel">
    <nav class="settings-workspace-nav" role="tablist" aria-label="设置分组" @keydown="handleKeydown">
      <button
        v-for="(section, index) in sections"
        :key="section.id"
        :ref="element => setButtonRef(element, index)"
        :id="tabId(section.id)"
        type="button"
        class="settings-workspace-nav-item"
        :class="{ 'settings-workspace-nav-item-active': section.id === modelValue }"
        role="tab"
        :aria-selected="section.id === modelValue"
        aria-controls="settings-workspace-panel"
        :tabindex="section.id === modelValue ? 0 : -1"
        @click="select(section.id, index, true)"
      >
        <span class="settings-workspace-nav-label">{{ section.label }}</span>
        <span v-if="section.description" class="settings-workspace-nav-description">{{ section.description }}</span>
      </button>
    </nav>
    <label class="settings-workspace-select-label">
      <span>设置分组</span>
      <select :value="modelValue" :aria-label="ariaLabel" @change="select($event.target.value)">
        <option v-for="section in sections" :key="section.id" :value="section.id">{{ section.label }}</option>
      </select>
    </label>
    <div id="settings-workspace-panel" class="settings-workspace-content" role="tabpanel" :aria-labelledby="activeTabId" tabindex="0">
      <slot />
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick } from 'vue'

const props = defineProps({
  sections: {
    type: Array,
    default: () => [],
    validator: value => value.every(section => typeof section?.id === 'string' && typeof section?.label === 'string'),
  },
  modelValue: { type: String, required: true },
  ariaLabel: { type: String, default: '设置分组' },
})
const emit = defineEmits(['update:modelValue'])
let buttonRefs = []

const activeTabId = computed(() => tabId(props.modelValue))

function tabId(id) {
  return `settings-tab-${String(id || '').replace(/[^a-zA-Z0-9_-]/g, '-')}`
}

function setButtonRef(element, index) {
  if (element) buttonRefs[index] = element
}

function select(id, index = props.sections.findIndex(section => section.id === id), shouldFocus = false) {
  if (!props.sections.some(section => section.id === id)) return
  emit('update:modelValue', id)
  if (shouldFocus && Number.isInteger(index) && index >= 0) {
    void nextTick(() => buttonRefs[index]?.focus())
  }
}

function handleKeydown(event) {
  if (!props.sections.length) return
  const current = Math.max(0, props.sections.findIndex(section => section.id === props.modelValue))
  let next = null
  if (event.key === 'ArrowDown') next = (current + 1) % props.sections.length
  if (event.key === 'ArrowUp') next = (current - 1 + props.sections.length) % props.sections.length
  if (event.key === 'Home') next = 0
  if (event.key === 'End') next = props.sections.length - 1
  if (next === null) return
  event.preventDefault()
  select(props.sections[next].id, next, true)
}
</script>
