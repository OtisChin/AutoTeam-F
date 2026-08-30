<template>
  <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      v-for="path in iconPaths"
      :key="path"
      :d="path"
      stroke="currentColor"
      stroke-width="1.7"
      stroke-linecap="round"
      stroke-linejoin="round"
    />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ name: { type: String, default: 'tools' } })

const paths = {
  dashboard: ['M4 4h6v7H4z', 'M14 4h6v4h-6z', 'M14 12h6v8h-6z', 'M4 15h6v5H4z'],
  'user-plus': ['M15 19c0-3-2.4-5-5.5-5S4 16 4 19', 'M9.5 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M18 8v6', 'M15 11h6'],
  team: ['M16 20v-1.5a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4V20', 'M10 10.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z', 'M16 3.8a3.5 3.5 0 0 1 0 6.8', 'M20 20v-1.5a4 4 0 0 0-3-3.87'],
  mail: ['M3 6.5h18v12H3z', 'm4 9 5.5 4 7.5-5.5'],
  cards: ['M4 7h14v10H4z', 'M7 4h13v10', 'M7 13h4'],
  link: ['m9.5 14.5-1 1a3.5 3.5 0 0 1-5-5l3-3a3.5 3.5 0 0 1 5 0', 'm14.5 9.5 1-1a3.5 3.5 0 0 1 5 5l-3 3a3.5 3.5 0 0 1-5 0', 'm9 15 6-6'],
  wallet: ['M3.5 6.5h15a2 2 0 0 1 2 2v9h-17z', 'M3.5 6.5V5a2 2 0 0 1 2-2h11', 'M16 11h4.5v4H16a2 2 0 0 1 0-4Z'],
  phone: ['M8 3h8a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z', 'M10 18h4'],
  records: ['M6 4h12v16H6z', 'M9 8h6', 'M9 12h6', 'M9 16h4'],
  key: ['M14 8a5 5 0 1 1-2 4l8 8', 'm16 16 2-2', 'm18 18 2-2'],
  commerce: ['M4 8h16l-1 12H5z', 'M8 8a4 4 0 0 1 8 0'],
  tools: ['M14.5 6.5a4 4 0 0 0-5 5L4 17l3 3 5.5-5.5a4 4 0 0 0 5-5l-3 1-2-2z'],
  history: ['M4 12a8 8 0 1 0 2.3-5.7L4 8.5', 'M4 4v4.5h4.5', 'M12 8v4l3 2'],
  logs: ['M5 4h14v16H5z', 'M8 8h8', 'M8 12h8', 'M8 16h5'],
  settings: ['M12 8.5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7Z', 'M19 13.5v-3l-2-.7-.7-1.7.9-1.9-2.1-2.1-1.9.9-1.7-.7L10 3H7l-.7 2-1.7.7-1.9-.9L.6 6.9l.9 1.9-.7 1.7v3l2 .7.7 1.7-.9 1.9 2.1 2.1 1.9-.9 1.7.7.7 2h3l.7-2 1.7-.7 1.9.9 2.1-2.1-.9-1.9.7-1.7z'],
  more: ['M5 12h.01', 'M12 12h.01', 'M19 12h.01'],
  refresh: ['M20 7v5h-5', 'M4 17v-5h5', 'M6.1 8A7 7 0 0 1 18 6l2 6', 'M17.9 16A7 7 0 0 1 6 18l-2-6'],
  logout: ['M10 5H4v14h6', 'M14 8l4 4-4 4', 'M8 12h10'],
}

const iconPaths = computed(() => paths[props.name] || paths.tools)
</script>
