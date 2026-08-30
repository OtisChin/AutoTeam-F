<template>
  <div class="ui-form-field">
    <label v-if="label" class="ui-form-field-label" :for="id">{{ label }}<span v-if="required" aria-hidden="true"> *</span></label>
    <slot :input-id="id" :described-by="describedBy || undefined" :invalid="Boolean(error)" :disabled="disabled" />
    <p v-if="help && !error" :id="helpId" class="ui-form-field-help">{{ help }}</p>
    <p v-if="error" :id="errorId" class="ui-form-field-error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  id: { type: String, required: true },
  label: { type: String, default: '' },
  help: { type: String, default: '' },
  error: { type: String, default: '' },
  required: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})
const helpId = computed(() => `${props.id}-help`)
const errorId = computed(() => `${props.id}-error`)
const describedBy = computed(() => props.error ? errorId.value : (props.help ? helpId.value : ''))
</script>
