<template>
  <Teleport to="body">
    <Transition name="ui-sheet" @after-leave="handleAfterLeave">
      <div v-if="open" ref="layerRef" class="ui-sheet-layer" @click.self="requestClose">
        <section ref="sheetRef" class="ui-sheet" :class="'ui-sheet-' + side" role="dialog" aria-modal="true" :aria-label="labelledby ? undefined : label" :aria-labelledby="labelledby || undefined" tabindex="-1" @keydown.esc.stop="requestClose" @keydown.tab="trapFocus">
          <header v-if="$slots.header" class="ui-sheet-header"><slot name="header" /></header>
          <div class="ui-sheet-body"><slot /></div>
          <footer v-if="$slots.footer" class="ui-sheet-footer"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { focusTarget, getFocusableElements } from './sheetBehavior.js'
const props = defineProps({
  open: { type: Boolean, default: false }, label: { type: String, default: '' }, labelledby: { type: String, default: '' },
  side: { type: String, default: 'bottom', validator: value => ['bottom', 'right'].includes(value) },
  initialFocusSelector: { type: String, default: '' },
})
const emit = defineEmits(['close', 'after-close'])
const layerRef = ref(null); const sheetRef = ref(null)
let opener = null; let inertState = []; let previousOverflow = null
let wasOpen = false
function focusableElements() { return getFocusableElements(sheetRef.value) }
function restoreBackground() { for (const { element, inert } of inertState) if (element?.isConnected) element.inert = inert; inertState = []; if (previousOverflow !== null && typeof document !== 'undefined') { document.body.style.overflow = previousOverflow; previousOverflow = null } }
function setBackgroundInert() { restoreBackground(); const layer = layerRef.value; if (!layer || typeof document === 'undefined') return; inertState = [...document.body.children].filter(element => element !== layer && !element.contains(layer)).map(element => ({ element, inert: Boolean(element.inert) })); for (const { element } of inertState) element.inert = true; previousOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden' }
function focusInitial() { const explicit = props.initialFocusSelector ? sheetRef.value?.querySelector(props.initialFocusSelector) : null; (explicit || focusableElements()[0] || sheetRef.value)?.focus() }
function trapFocus(event) { const focusable = focusableElements(); if (!focusable.length) { event.preventDefault(); sheetRef.value?.focus(); return }; const target = focusTarget(focusable, document.activeElement, sheetRef.value, event.shiftKey); if (target) { event.preventDefault(); target.focus() } }
function requestClose() { emit('close') }
function handleAfterLeave() { emit('after-close') }
watch(() => props.open, async open => {
  if (open) { wasOpen = true; opener = typeof document === 'undefined' ? null : document.activeElement; await nextTick(); setBackgroundInert(); focusInitial(); return }
  if (!wasOpen) return
  wasOpen = false
  restoreBackground()
  await nextTick()
  if (opener?.isConnected && typeof opener.focus === 'function') opener.focus()
  opener = null
})
onBeforeUnmount(() => { restoreBackground(); if (props.open && opener?.isConnected && typeof opener.focus === 'function') opener.focus() })
</script>
