<template>
  <div class="ui-segmented" role="radiogroup" :aria-label="ariaLabel" @keydown="handleKeydown">
    <button
      v-for="(option, index) in options"
      :key="option.value"
      :ref="element => setOptionRef(element, index)"
      type="button"
      class="ui-segmented-option"
      :class="{ 'ui-segmented-option-selected': option.value === modelValue }"
      role="radio"
      :aria-checked="option.value === modelValue"
      :tabindex="option.value === modelValue ? 0 : -1"
      @click="select(index)"
    >
      <span class="ui-segmented-copy"><strong>{{ option.label }}</strong><small v-if="option.description">{{ option.description }}</small></span>
      <span class="ui-segmented-check" :aria-hidden="option.value !== modelValue">✓</span>
    </button>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUpdate } from 'vue'
const props = defineProps({
  modelValue: { type: String, required: true },
  options: { type: Array, required: true, validator: value => value.every(option => typeof option?.value === 'string' && typeof option?.label === 'string') },
  ariaLabel: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
let optionRefs = []
onBeforeUpdate(() => { optionRefs = [] })
function setOptionRef(element, index) { if (element) optionRefs[index] = element }
function selectedIndex() { const index = props.options.findIndex(option => option.value === props.modelValue); return index >= 0 ? index : 0 }
async function select(index) { const option = props.options[index]; if (!option) return; emit('update:modelValue', option.value); await nextTick(); optionRefs[index]?.focus() }
function handleKeydown(event) { const last = props.options.length - 1; let next = selectedIndex(); if (event.key === 'ArrowDown' || event.key === 'ArrowRight') next = next >= last ? 0 : next + 1; else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') next = next <= 0 ? last : next - 1; else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = last; else return; event.preventDefault(); void select(next) }
function focusSelected() { optionRefs[selectedIndex()]?.focus() }
defineExpose({ focusSelected })
</script>
