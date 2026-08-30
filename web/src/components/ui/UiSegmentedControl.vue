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
      :tabindex="rovingTabindex(options, modelValue)[index]"
      @click="select(index)"
    >
      <span class="ui-segmented-copy"><strong>{{ option.label }}</strong><small v-if="option.description">{{ option.description }}</small></span>
      <span class="ui-segmented-check" :aria-hidden="option.value !== modelValue">✓</span>
    </button>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUpdate } from 'vue'
import { keyboardIndex, rovingTabindex, selectedIndex, selectionIntent } from './segmentedBehavior.js'
const props = defineProps({
  modelValue: { type: String, required: true },
  options: { type: Array, required: true, validator: value => value.every(option => typeof option?.value === 'string' && typeof option?.label === 'string') },
  ariaLabel: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
let optionRefs = []
onBeforeUpdate(() => { optionRefs = [] })
function setOptionRef(element, index) { if (element) optionRefs[index] = element }
async function select(index) { const value = selectionIntent(props.options, index); if (value === null) return; emit('update:modelValue', value); await nextTick(); optionRefs[index]?.focus() }
// ArrowDown/ArrowUp and horizontal arrows use the shared keyboard transition.
function handleKeydown(event) { const next = keyboardIndex(props.options, selectedIndex(props.options, props.modelValue), event.key); if (next === null) return; event.preventDefault(); void select(next) }
function focusSelected() { optionRefs[selectedIndex(props.options, props.modelValue)]?.focus() }
defineExpose({ focusSelected })
</script>




