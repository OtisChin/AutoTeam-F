<template>
  <div class="theme-switcher" :class="{ 'theme-switcher-group': mode === 'group' }">
    <template v-if="mode === 'group'">
      <UiSegmentedControl
        :model-value="preference"
        :options="options"
        aria-label="外观主题"
        @update:model-value="updatePreference"
      />
    </template>

    <template v-else>
      <button
        ref="triggerRef"
        type="button"
        class="theme-switcher-trigger"
        aria-haspopup="dialog"
        :aria-expanded="open"
        :aria-label="triggerAriaLabel"
        @click="toggleSelector"
        @keydown.enter.prevent="openSelector"
        @keydown.space.prevent="openSelector"
        @keydown.down.prevent="openSelector"
      >
        <span class="theme-switcher-icon" aria-hidden="true">{{ resolvedOption.icon }}</span>
        <span class="theme-switcher-trigger-label">{{ preferenceOption.label }}</span>
        <span class="theme-switcher-current" aria-hidden="true">{{ resolvedOption.label }}</span>
      </button>

      <Teleport to="body">
        <div
          v-if="open && !isMobile"
          ref="popoverRef"
          class="theme-switcher-popover"
          role="dialog"
          aria-label="选择外观"
          @keydown.esc.stop="closeSelector"
          @keydown="handlePopoverKeydown"
        >
          <div class="theme-switcher-options" role="radiogroup" aria-label="外观主题">
            <button
              v-for="(option, index) in options"
              :key="option.value"
              :ref="element => setOptionRef(element, index)"
              type="button"
              class="theme-switcher-option"
              :class="{ 'theme-switcher-option-selected': option.value === preference }"
              role="radio"
              :aria-checked="option.value === preference"
              :tabindex="option.value === preference ? 0 : -1"
              @click="updatePreference(option.value)"
            >
              <span class="theme-switcher-option-icon" aria-hidden="true">{{ option.icon }}</span>
              <span class="theme-switcher-option-copy"><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span>
              <span class="theme-switcher-option-check" :aria-hidden="option.value !== preference">✓</span>
            </button>
          </div>
        </div>
      </Teleport>

      <UiSheet
        :open="open && isMobile"
        label="选择外观"
        side="bottom"
        initial-focus-selector="[role='radio'][tabindex='0']"
        @close="closeSelector"
      >
        <div class="theme-switcher-sheet-options" role="radiogroup" aria-label="外观主题">
          <button
            v-for="(option, index) in options"
            :key="option.value"
            :ref="element => setOptionRef(element, index)"
            type="button"
            class="theme-switcher-option"
            :class="{ 'theme-switcher-option-selected': option.value === preference }"
            role="radio"
            :aria-checked="option.value === preference"
            :tabindex="option.value === preference ? 0 : -1"
            @click="updatePreference(option.value)"
            @keydown="handleOptionKeydown($event, index)"
          >
            <span class="theme-switcher-option-icon" aria-hidden="true">{{ option.icon }}</span>
            <span class="theme-switcher-option-copy"><strong>{{ option.label }}</strong><small>{{ option.description }}</small></span>
            <span class="theme-switcher-option-check" :aria-hidden="option.value !== preference">✓</span>
          </button>
        </div>
      </UiSheet>
    </template>
  </div>
</template>

<script setup>
import { computed, inject, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import UiSegmentedControl from './ui/UiSegmentedControl.vue'
import UiSheet from './ui/UiSheet.vue'
import { createThemeController, THEME_CONTROLLER_KEY } from '../themePreference.js'

const props = defineProps({
  mode: { type: String, default: 'compact', validator: value => ['compact', 'group'].includes(value) },
})

const options = Object.freeze([
  { value: 'system', label: '跟随系统', description: '自动匹配设备外观', icon: '◐' },
  { value: 'light', label: '明亮', description: '浅色画布与白色内容层', icon: '☀' },
  { value: 'dark', label: '深色', description: '低亮度深色工作区', icon: '☾' },
])

const providedController = inject(THEME_CONTROLLER_KEY, null)
const ownsController = !providedController
const controller = providedController || createThemeController()
const preference = ref(controller.getSnapshot().preference)
const resolvedTheme = ref(controller.getSnapshot().resolvedTheme)
const open = ref(false)
const isMobile = ref(false)
const triggerRef = ref(null)
const popoverRef = ref(null)
const optionRefs = []
let unsubscribe = () => {}
let mediaQuery = null
let removeMediaListener = () => {}

const preferenceOption = computed(() => options.find(option => option.value === preference.value) || options[0])
const resolvedOption = computed(() => options.find(option => option.value === resolvedTheme.value) || options[1])
const triggerAriaLabel = computed(() => `外观：${preferenceOption.value.label}，当前${resolvedOption.value.label}`)

function setOptionRef(element, index) { if (element) optionRefs[index] = element }
function updateMediaMode(event) { isMobile.value = Boolean(event?.matches ?? mediaQuery?.matches) }
function openSelector() { open.value = true; void nextTick(() => optionRefs[options.findIndex(option => option.value === preference.value)]?.focus()) }
function closeSelector() {
  if (!open.value) return
  open.value = false
  void nextTick(() => triggerRef.value?.focus())
}
function toggleSelector() { if (open.value) closeSelector(); else openSelector() }
function updatePreference(value, { close = true } = {}) {
  controller.setPreference(value)
  if (props.mode === 'compact' && close) closeSelector()
}
function handleOptionKeydown(event, index) {
  if (event.key === 'Escape') { event.preventDefault(); closeSelector(); return }
  const delta = event.key === 'ArrowDown' || event.key === 'ArrowRight' ? 1 : event.key === 'ArrowUp' || event.key === 'ArrowLeft' ? -1 : 0
  if (delta) {
    event.preventDefault()
    const nextIndex = (index + delta + options.length) % options.length
    updatePreference(options[nextIndex].value, { close: false })
    void nextTick(() => optionRefs[nextIndex]?.focus())
  }
  if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); updatePreference(options[index].value) }
}
function handlePopoverKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); closeSelector(); return }
  const index = optionRefs.indexOf(event.target)
  if (index >= 0) handleOptionKeydown(event, index)
}
function handlePointerdown(event) {
  if (!popoverRef.value?.contains(event.target) && !triggerRef.value?.contains(event.target)) closeSelector()
}

onMounted(() => {
  unsubscribe = controller.subscribe(snapshot => { preference.value = snapshot.preference; resolvedTheme.value = snapshot.resolvedTheme })
  mediaQuery = typeof window !== 'undefined' ? window.matchMedia?.('(max-width: 639px)') : null
  updateMediaMode()
  if (mediaQuery) {
    const listener = event => updateMediaMode(event)
    if (typeof mediaQuery.addEventListener === 'function') { mediaQuery.addEventListener('change', listener); removeMediaListener = () => mediaQuery.removeEventListener('change', listener) }
    else if (typeof mediaQuery.addListener === 'function') { mediaQuery.addListener(listener); removeMediaListener = () => mediaQuery.removeListener(listener) }
  }
})

onBeforeUnmount(() => {
  unsubscribe()
  removeMediaListener()
  if (ownsController) controller.dispose()
  if (typeof document !== 'undefined') document.removeEventListener('pointerdown', handlePointerdown)
})

import { watch } from 'vue'
watch([open, isMobile, () => props.mode], ([isOpen, mobile, mode]) => {
  if (typeof document === 'undefined') return
  if (isOpen && !mobile && mode === 'compact') document.addEventListener('pointerdown', handlePointerdown)
  else document.removeEventListener('pointerdown', handlePointerdown)
})
</script>
