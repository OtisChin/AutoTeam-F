<template>
  <section class="log-workspace">
    <UiPageHeader title="日志" eyebrow="系统 / Diagnostics" description="实时查看运行日志并保留最近 1,000 条记录">
      <template #actions><div class="ui-toolbar-actions"><label class="ui-check-label"><input type="checkbox" v-model="autoScroll" /> 自动滚动</label><UiButton variant="quiet" size="sm" :loading="loading" @click="fetchLogs">刷新</UiButton><UiButton variant="quiet" size="sm" @click="clearLogs">清空视图</UiButton></div></template>
    </UiPageHeader>
    <UiSurface variant="strong" padding="none" class="log-console-surface" aria-label="运行日志">
      <div ref="logContainer" class="log-console" aria-live="polite">
        <UiStatePanel v-if="logs.length === 0" state="empty" title="暂无日志" message="新的运行事件会自动出现在这里。" />
        <div v-for="log in logs" :key="log._key" class="log-entry"><time>{{ formatTime(log.time) }}</time><strong :data-level="log.level">{{ log.level }}</strong><span>{{ log.message }}</span></div>
      </div>
    </UiSurface>
  </section>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { api } from '../api.js'
import UiButton from './ui/UiButton.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiSurface from './ui/UiSurface.vue'

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
