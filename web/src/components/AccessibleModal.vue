<template>
  <Teleport to="body">
    <div
      ref="dialogRef"
      role="dialog"
      aria-modal="true"
      :aria-label="labelledby ? undefined : label"
      :aria-labelledby="labelledby || undefined"
      tabindex="-1"
      class="accessible-modal-layer fixed inset-0 z-50 flex justify-center bg-black/60 p-4"
      @click.self="requestClose"
      @keydown.esc.stop="requestClose"
      @keydown.tab="trapFocus"
    >
      <slot />
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'

const props = defineProps({
  label: { type: String, default: '' },
  labelledby: { type: String, default: '' },
  initialFocusSelector: { type: String, default: '' },
})
const emit = defineEmits(['close'])

const dialogRef = ref(null)
const opener = typeof document === 'undefined' ? null : document.activeElement
const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
let backgroundInertState = []
let bodyOverflow = null

function focusableElements() {
  const dialog = dialogRef.value
  if (!dialog) return []
  return [...dialog.querySelectorAll(FOCUSABLE_SELECTOR)]
    .filter(element => element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true')
}

function setBackgroundInert(dialog) {
  restoreBackgroundInert()
  if (!dialog || typeof document === 'undefined') return
  backgroundInertState = [...document.body.children]
    .filter(element => element !== dialog && !element.contains(dialog))
    .map(element => ({ element, inert: Boolean(element.inert) }))
  for (const { element } of backgroundInertState) element.inert = true
  bodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
}

function restoreBackgroundInert() {
  for (const { element, inert } of backgroundInertState) {
    if (element?.isConnected) element.inert = inert
  }
  backgroundInertState = []
  if (bodyOverflow !== null && typeof document !== 'undefined') {
    document.body.style.overflow = bodyOverflow
    bodyOverflow = null
  }
}

function focusInitialTarget() {
  const dialog = dialogRef.value
  if (!dialog) return
  const explicit = props.initialFocusSelector
    ? dialog.querySelector(props.initialFocusSelector)
    : dialog.querySelector('[autofocus]')
  const target = explicit || focusableElements()[0] || dialog
  target?.focus()
}

function requestClose() {
  emit('close')
}

function trapFocus(event) {
  const dialog = dialogRef.value
  if (!dialog) return
  const focusable = focusableElements()
  if (!focusable.length) {
    event.preventDefault()
    dialog.focus()
    return
  }
  const first = focusable[0]
  const last = focusable.at(-1)
  const current = document.activeElement
  const outsideCycle = current === dialog || !dialog.contains(current)
  if (event.shiftKey && (outsideCycle || current === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (outsideCycle || current === last)) {
    event.preventDefault()
    first.focus()
  }
}

onMounted(async () => {
  await nextTick()
  setBackgroundInert(dialogRef.value)
  focusInitialTarget()
})

onBeforeUnmount(() => {
  restoreBackgroundInert()
  void nextTick(() => {
    if (opener?.isConnected && typeof opener.focus === 'function') opener.focus()
  })
})
</script>

<style scoped>
.accessible-modal-layer {
  overflow-y: auto;
  align-items: safe center;
  overscroll-behavior: contain;
  -webkit-overflow-scrolling: touch;
}
</style>
