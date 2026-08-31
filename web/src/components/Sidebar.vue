<template>
  <aside class="nav-shell hidden shrink-0 flex-col md:flex" aria-label="主导航">
    <header class="nav-brand">
      <div class="nav-mark" aria-hidden="true"><span>A</span></div>
      <div class="min-w-0">
        <h1 class="truncate text-[15px] font-semibold text-white">AutoToken</h1>
        <p class="mt-0.5 truncate text-[11px] text-gray-500">Operations Console</p>
      </div>
    </header>

    <nav class="nav-scroll" aria-label="工作区">
      <section v-for="group in groupedItems" :key="group.label" class="nav-group">
        <h2 class="section-label">{{ group.label }}</h2>
        <div class="space-y-0.5">
          <button
            v-for="item in group.items"
            :key="item.key"
            type="button"
            class="nav-item text-left text-sm"
            :data-nav-key="item.key"
            :class="active === item.key ? 'nav-item-active' : ''"
            :aria-current="active === item.key ? 'page' : undefined"
            :title="item.description"
            @click="navigate(item.key)"
            @pointerenter="emit('prefetch', item.key)"
            @focus="emit('prefetch', item.key)"
          >
            <span class="nav-glyph"><NavIcon :name="item.icon" /></span>
            <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
            <span v-if="active === item.key" class="nav-active-dot" aria-hidden="true"></span>
          </button>
        </div>
      </section>
    </nav>

    <footer class="nav-footer">
      <div class="nav-health" aria-live="polite">
        <span class="nav-health-dot" :class="loading ? 'nav-health-busy' : ''"></span>
        <span>{{ loading ? '正在同步数据' : '服务连接正常' }}</span>
      </div>
      <div class="mt-2 grid grid-cols-2 gap-1.5">
        <button type="button" class="nav-utility" :disabled="loading" @click="emit('refresh')">
          <NavIcon name="refresh" :class="loading ? 'is-spinning' : ''" />
          <span>刷新</span>
        </button>
        <button v-if="authRequired" type="button" class="nav-utility nav-utility-danger" @click="emit('logout')">
          <NavIcon name="logout" />
          <span>登出</span>
        </button>
      </div>
    </footer>
  </aside>

  <nav class="mobile-nav md:hidden" aria-label="移动端主导航">
    <button
      v-for="item in mobilePrimaryItems"
      :key="item.key"
      type="button"
      class="mobile-nav-item"
      :data-nav-key="item.key"
      :class="active === item.key ? 'mobile-nav-item-active' : ''"
      :aria-current="active === item.key ? 'page' : undefined"
      @click="navigate(item.key)"
      @pointerenter="emit('prefetch', item.key)"
    >
      <NavIcon :name="item.icon" />
      <span>{{ item.label }}</span>
    </button>
    <button
      ref="moreButtonRef"
      type="button"
      class="mobile-nav-item"
      data-nav-key="more"
      :class="mobileSecondaryKeys.has(active) ? 'mobile-nav-item-active' : ''"
      :aria-expanded="mobileMenuOpen"
      aria-controls="mobile-navigation-sheet"
      @click="openMobileMenu"
    >
      <NavIcon name="more" />
      <span>更多</span>
    </button>
  </nav>

  <Teleport to="body">
    <Transition name="mobile-sheet">
      <div ref="sheetLayerRef" v-if="mobileMenuOpen" class="mobile-nav-layer md:hidden" @click.self="closeMobileMenu">
        <section
          id="mobile-navigation-sheet"
          ref="sheetRef"
          class="mobile-nav-sheet"
          role="dialog"
          aria-modal="true"
          aria-label="全部工作区"
          tabindex="-1"
          @keydown.esc="closeMobileMenu"
          @keydown.tab="trapMobileMenuFocus"
        >
          <header class="mobile-sheet-header">
            <div>
              <span class="workspace-eyebrow">导航</span>
              <h2>全部工作区</h2>
            </div>
            <button type="button" class="mobile-sheet-close" aria-label="关闭导航" @click="closeMobileMenu">完成</button>
          </header>
          <div class="mobile-sheet-scroll">
            <section v-for="group in groupedItems" :key="group.label" class="mobile-sheet-group">
              <h3 class="section-label">{{ group.label }}</h3>
              <div class="mobile-sheet-grid">
                <button
                  v-for="item in group.items"
                  :key="item.key"
                  type="button"
                  class="mobile-sheet-item"
                  :data-nav-key="item.key"
                  :class="active === item.key ? 'mobile-sheet-item-active' : ''"
                  :aria-current="active === item.key ? 'page' : undefined"
                  @click="navigate(item.key)"
                  @focus="emit('prefetch', item.key)"
                >
                  <span class="nav-glyph"><NavIcon :name="item.icon" /></span>
                  <span class="min-w-0 text-left">
                    <strong>{{ item.label }}</strong>
                    <small>{{ item.description }}</small>
                  </span>
                </button>
              </div>
            </section>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { NAV_GROUPS, NAV_ITEMS } from '../navigation.js'
import NavIcon from './NavIcon.vue'

defineProps({
  active: String,
  loading: Boolean,
  authRequired: Boolean,
})
const emit = defineEmits(['navigate', 'prefetch', 'refresh', 'logout'])

const mobileMenuOpen = ref(false)
const sheetRef = ref(null)
const sheetLayerRef = ref(null)
const moreButtonRef = ref(null)
let mobileMenuBackgroundInertState = []
let mobileMenuBodyOverflow = null
let desktopMediaQuery = null
const mobilePrimaryItems = NAV_ITEMS.filter(item => item.mobilePrimary)
const mobileSecondaryKeys = new Set(NAV_ITEMS.filter(item => !item.mobilePrimary).map(item => item.key))
const FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
const groupedItems = computed(() => NAV_GROUPS
  .map(label => ({ label, items: NAV_ITEMS.filter(item => item.group === label) }))
  .filter(group => group.items.length))

function navigate(key) {
  emit('navigate', key)
  if (mobileMenuOpen.value) void closeMobileMenu()
}

async function openMobileMenu() {
  mobileMenuOpen.value = true
  await nextTick()
  setMobileMenuBackgroundInert(sheetLayerRef.value)
  sheetRef.value?.focus()
}

async function closeMobileMenu(restoreFocus = true) {
  mobileMenuOpen.value = false
  restoreMobileMenuBackgroundInert()
  await nextTick()
  if (restoreFocus !== false) moreButtonRef.value?.focus()
}

function setMobileMenuBackgroundInert(layer) {
  restoreMobileMenuBackgroundInert()
  if (!layer || typeof document === 'undefined') return
  mobileMenuBackgroundInertState = [...document.body.children]
    .filter(element => element !== layer && !element.contains(layer))
    .map(element => ({ element, inert: Boolean(element.inert) }))
  for (const { element } of mobileMenuBackgroundInertState) element.inert = true
  mobileMenuBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
}

function restoreMobileMenuBackgroundInert() {
  for (const { element, inert } of mobileMenuBackgroundInertState) {
    if (element?.isConnected) element.inert = inert
  }
  mobileMenuBackgroundInertState = []
  if (mobileMenuBodyOverflow !== null && typeof document !== 'undefined') {
    document.body.style.overflow = mobileMenuBodyOverflow
    mobileMenuBodyOverflow = null
  }
}

function trapMobileMenuFocus(event) {
  const sheet = sheetRef.value
  if (!sheet) return
  const focusable = [...sheet.querySelectorAll(FOCUSABLE_SELECTOR)]
    .filter(element => element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true')
  if (!focusable.length) {
    event.preventDefault()
    sheet.focus()
    return
  }
  const first = focusable[0]
  const last = focusable.at(-1)
  const current = document.activeElement
  const focusOutsideCycle = current === sheet || !sheet.contains(current)
  if (event.shiftKey && (focusOutsideCycle || current === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (focusOutsideCycle || current === last)) {
    event.preventDefault()
    first.focus()
  }
}

async function handleDesktopBreakpointChange(event) {
  if (!event.matches || !mobileMenuOpen.value) return
  await closeMobileMenu(false)
  if (typeof document === 'undefined') return
  const visibleActiveItem = document.querySelector('.nav-shell .nav-item[aria-current="page"]')
    || document.querySelector('.nav-shell .nav-item')
  visibleActiveItem?.focus()
}

onMounted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  desktopMediaQuery = window.matchMedia('(min-width: 768px)')
  desktopMediaQuery.addEventListener('change', handleDesktopBreakpointChange)
  if (desktopMediaQuery.matches) void handleDesktopBreakpointChange(desktopMediaQuery)
})

onBeforeUnmount(() => {
  desktopMediaQuery?.removeEventListener('change', handleDesktopBreakpointChange)
  desktopMediaQuery = null
  restoreMobileMenuBackgroundInert()
})
</script>
