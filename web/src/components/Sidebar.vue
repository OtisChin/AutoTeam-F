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
      :class="mobileSecondaryKeys.has(active) ? 'mobile-nav-item-active' : ''"
      :aria-expanded="mobileMenuOpen"
      aria-controls="mobile-navigation-sheet"
      @click="openMobileMenu"
    >
      <NavIcon name="more" />
      <span>更多</span>
    </button>
  </nav>

  <Transition name="mobile-sheet">
    <div v-if="mobileMenuOpen" class="mobile-nav-layer md:hidden" @click.self="closeMobileMenu">
      <section
        id="mobile-navigation-sheet"
        ref="sheetRef"
        class="mobile-nav-sheet"
        role="dialog"
        aria-modal="true"
        aria-label="全部工作区"
        tabindex="-1"
        @keydown.esc="closeMobileMenu"
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
</template>

<script setup>
import { computed, nextTick, ref } from 'vue'
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
const moreButtonRef = ref(null)
const mobilePrimaryItems = NAV_ITEMS.filter(item => item.mobilePrimary)
const mobileSecondaryKeys = new Set(NAV_ITEMS.filter(item => !item.mobilePrimary).map(item => item.key))
const groupedItems = computed(() => NAV_GROUPS
  .map(label => ({ label, items: NAV_ITEMS.filter(item => item.group === label) }))
  .filter(group => group.items.length))

function navigate(key) {
  emit('navigate', key)
  mobileMenuOpen.value = false
}

async function openMobileMenu() {
  mobileMenuOpen.value = true
  await nextTick()
  sheetRef.value?.focus()
}

async function closeMobileMenu() {
  mobileMenuOpen.value = false
  await nextTick()
  moreButtonRef.value?.focus()
}
</script>
