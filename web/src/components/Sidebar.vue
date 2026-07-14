<template>
  <!-- 桌面端侧边栏 -->
  <nav class="nav-shell hidden shrink-0 flex-col md:flex">
    <div class="mb-7 flex items-center gap-3">
      <div class="nav-mark">AT</div>
      <div class="min-w-0">
        <h1 class="truncate text-lg font-semibold text-white">AutoToken</h1>
        <p class="mt-0.5 truncate text-xs text-gray-500">Token operations console</p>
      </div>
    </div>

    <div class="flex-1 overflow-y-auto pr-1">
      <div v-for="group in groupedItems" :key="group.label">
        <div class="section-label">{{ group.label }}</div>
        <div class="space-y-1">
          <button
            v-for="item in group.items"
            :key="item.key"
            @click="$emit('navigate', item.key)"
            class="nav-item text-left text-sm"
            :class="active === item.key ? 'nav-item-active' : ''">
            <span class="nav-glyph">{{ item.glyph }}</span>
            <span class="min-w-0 flex-1 truncate">{{ item.label }}</span>
          </button>
        </div>
      </div>
    </div>

    <div class="mt-4 space-y-1 border-t border-gray-800 pt-4">
      <button @click="$emit('refresh')" :disabled="loading"
        class="nav-item text-left text-sm disabled:opacity-50">
        <span class="nav-glyph">{{ loading ? '...' : 'R' }}</span>
        {{ loading ? '刷新中...' : '刷新数据' }}
      </button>
      <button v-if="authRequired" @click="$emit('logout')"
        class="nav-item text-left text-sm hover:text-red-300">
        <span class="nav-glyph">Q</span>
        登出
      </button>
    </div>
  </nav>

  <!-- 移动端底部 tab 栏 -->
  <nav class="mobile-nav md:hidden">
    <button v-for="item in items" :key="item.key"
      @click="$emit('navigate', item.key)"
      class="flex min-w-20 shrink-0 flex-col items-center px-2 py-2 text-xs transition"
      :class="active === item.key
        ? 'text-blue-400'
        : 'text-gray-500 hover:text-gray-300'">
      <span class="nav-glyph mb-1">{{ item.glyph }}</span>
      <span class="mt-0.5">{{ item.mobileLabel || item.label }}</span>
    </button>
  </nav>
</template>

<script setup>
defineProps({
  active: String,
  loading: Boolean,
  authRequired: Boolean,
})
defineEmits(['navigate', 'refresh', 'logout'])

const items = [
  { key: 'dashboard', group: 'Command', glyph: 'DB', label: '仪表盘', mobileLabel: '仪表盘' },
  { key: 'register', group: 'Accounts', glyph: 'RG', label: '注册账号', mobileLabel: '注册' },
  { key: 'cardpool', group: 'Payments', glyph: 'CP', label: '卡池', mobileLabel: '卡池' },
  { key: 'bindcard', group: 'Payments', glyph: 'BC', label: '自动绑卡服务', mobileLabel: '绑卡' },
  { key: 'gopay', group: 'Payments', glyph: 'GP', label: 'GoPay', mobileLabel: 'GoPay' },
  { key: 'ideal', group: 'Payments', glyph: 'ID', label: '荷兰iDEAL', mobileLabel: 'iDEAL' },
  { key: 'paypal', group: 'Payments', glyph: 'PP', label: 'PayPal', mobileLabel: 'PayPal' },
  { key: 'paypalIce', group: 'Payments', glyph: 'PI', label: 'PayPal ICE', mobileLabel: 'ICE' },
  { key: 'oauthPhones', group: 'OAuth', glyph: 'PH', label: 'OAuth 手机号', mobileLabel: '手机号' },
  { key: 'oauthPhoneRecords', group: 'OAuth', glyph: 'OR', label: 'OAuth 取号记录', mobileLabel: '取号' },
  { key: 'oauth', group: 'OAuth', glyph: 'OA', label: 'OAuth 登录', mobileLabel: 'OAuth' },
  { key: 'mailAccounts', group: 'Accounts', glyph: 'ML', label: 'mail邮箱管理', mobileLabel: 'mail' },
  { key: 'trade', group: 'Commerce', glyph: 'CD', label: '交易管理', mobileLabel: '交易' },
  { key: 'cpa2sub', group: 'Tools', glyph: 'CS', label: 'CPA_2_Sub2API', mobileLabel: 'CPA2Sub' },
  { key: 'tasks', group: 'System', glyph: 'TS', label: '任务历史', mobileLabel: '任务' },
  { key: 'logs', group: 'System', glyph: 'LG', label: '日志', mobileLabel: '日志' },
  { key: 'settings', group: 'System', glyph: 'ST', label: '设置', mobileLabel: '设置' },
]

const groupOrder = ['Command', 'Accounts', 'Payments', 'OAuth', 'Commerce', 'Tools', 'System']
const groupedItems = groupOrder
  .map(label => ({ label, items: items.filter(item => item.group === label) }))
  .filter(group => group.items.length)
</script>
