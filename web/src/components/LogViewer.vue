<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-xl font-bold text-white">日志</h2>
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-2 text-sm text-gray-400">
          <input type="checkbox" v-model="autoScroll" class="rounded bg-gray-800 border-gray-700" />
          自动滚动
        </label>
        <button @click="fetchLogs" :disabled="loading"
          class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm rounded-lg border border-gray-700 transition disabled:opacity-50">
          刷新
        </button>
        <button @click="clearLogs"
          class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm rounded-lg border border-gray-700 transition text-gray-400 hover:text-white">
          清空
        </button>
      </div>
    </div>

    <div ref="logContainer"
      class="bg-gray-950 border border-gray-800 rounded-xl p-3 md:p-4 font-mono text-xs leading-relaxed h-[calc(100vh-200px)] md:h-[600px] overflow-y-auto">
      <div v-if="logs.length === 0" class="text-gray-600 text-center py-8">暂无日志</div>
      <div v-for="log in logs" :key="log._key"
        class="py-0.5 flex gap-3 hover:bg-gray-900/50">
        <span class="text-gray-600 shrink-0">{{ formatTime(log.time) }}</span>
        <span class="shrink-0 w-16"
          :class="{
            'text-red-400': log.level === 'ERROR',
            'text-yellow-400': log.level === 'WARNING',
            'text-blue-400': log.level === 'INFO',
            'text-gray-500': log.level === 'DEBUG',
          }">{{ log.level }}</span>
        <span class="text-gray-300 break-all">{{ log.message }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api.js'

const logs = ref([])
const loading = ref(false)
const autoScroll = ref(true)
const logContainer = ref(null)
const LOG_FETCH_LIMIT = 1000
const LOG_KEEP_LIMIT = 1000
const POLL_INTERVAL_MS = 3000

let pollTimer = null
let requestInFlight = false
let componentActive = false
let requestGeneration = 0
let lastTime = 0
let lastLogId = 0
let lastBootId = ''

function formatTime(ts) {
  const d = new Date(ts * 1000)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

// BEGIN LOG MERGE HELPERS
function getLogKey(log, bootId = '') {
  const epoch = String(bootId || log?._bootId || 'legacy')
  if (log.id !== undefined && log.id !== null && String(log.id) !== '') {
    return `${epoch}:id:${String(log.id)}`
  }
  return `${epoch}:entry:${JSON.stringify([log.time, log.level, log.message])}`
}

function mergeLogEntries(currentLogs, entries, bootId, keepLimit) {
  const nextLogs = Array.isArray(currentLogs) ? currentLogs.slice() : []
  const nextKeys = new Set(nextLogs.map(log => log._key || getLogKey(log, log?._bootId)))

  for (const entry of entries) {
    if (!entry || typeof entry !== 'object') continue
    const key = getLogKey(entry, bootId)
    if (nextKeys.has(key)) continue
    nextKeys.add(key)
    nextLogs.push({ ...entry, _bootId: bootId, _key: key })
  }

  return nextLogs.slice(-keepLimit)
}
// END LOG MERGE HELPERS

function mergeLogs(entries, replace, bootId) {
  logs.value = mergeLogEntries(replace ? [] : logs.value, entries, bootId, LOG_KEEP_LIMIT)
}

function scrollToLatest() {
  if (!autoScroll.value) return
  nextTick(() => {
    if (componentActive && logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight
    }
  })
}

async function fetchLogs() {
  if (requestInFlight || !componentActive || document.hidden) return

  requestInFlight = true
  loading.value = true
  const generation = requestGeneration
  const since = lastTime

  try {
    const result = await api.getLogs(LOG_FETCH_LIMIT, since, lastLogId, lastBootId)
    if (!componentActive || document.hidden || generation !== requestGeneration) return

    const responseBootId = String(result?.boot_id || '')
    const bootChanged = Boolean(responseBootId && lastBootId && responseBootId !== lastBootId)
    if (bootChanged) {
      lastLogId = 0
      lastTime = 0
    }
    if (responseBootId) lastBootId = responseBootId

    const entries = Array.isArray(result?.logs) ? result.logs : []
    if (entries.length === 0) return

    mergeLogs(entries, since === 0 && !bootChanged, lastBootId)
    for (const entry of entries) {
      const id = Number(entry?.id)
      if (Number.isFinite(id)) lastLogId = Math.max(lastLogId, id)
    }
    lastTime = entries.reduce((latest, entry) => {
      const timestamp = Number(entry?.time)
      return Number.isFinite(timestamp) ? Math.max(latest, timestamp) : latest
    }, lastTime)
    scrollToLatest()
  } catch (e) {
    console.error('获取日志失败:', e)
  } finally {
    requestInFlight = false
    if (componentActive) loading.value = false
  }
}

function clearPollTimer() {
  if (pollTimer === null) return
  clearTimeout(pollTimer)
  pollTimer = null
}

function scheduleNextPoll() {
  clearPollTimer()
  if (!componentActive || document.hidden) return

  pollTimer = setTimeout(() => {
    pollTimer = null
    void runPoll()
  }, POLL_INTERVAL_MS)
}

async function runPoll() {
  if (!componentActive || document.hidden) return
  await fetchLogs()
  scheduleNextPoll()
}

function handleVisibilityChange() {
  clearPollTimer()
  if (document.hidden) {
    requestGeneration += 1
    loading.value = false
    return
  }
  void runPoll()
}

function clearLogs() {
  requestGeneration += 1
  logs.value = []
  lastTime = 0
  lastLogId = 0
  lastBootId = ''
}

onMounted(() => {
  componentActive = true
  document.addEventListener('visibilitychange', handleVisibilityChange)
  if (!document.hidden) void runPoll()
})

onUnmounted(() => {
  componentActive = false
  requestGeneration += 1
  loading.value = false
  clearPollTimer()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>
