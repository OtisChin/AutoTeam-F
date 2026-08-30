<template>
  <div class="cpa-workspace">
    <UiPageHeader title="OpenAI 账号 JSON 批量转换" eyebrow="维护 / CPA" description="批量载入源文件，筛选需要的账号，统一导出成一个目标 JSON。">
      <template #actions><UiStatusBadge :label="busy ? '处理中' : (hasConverted ? '已完成' : '待处理')" :tone="busy ? 'info' : (hasConverted ? 'success' : 'neutral')" /></template>
    </UiPageHeader>
    <UiMetricSummary label="转换指标" :items="metricItems" />

    <input
      ref="fileInput"
      type="file"
      accept=".json,application/json"
      multiple
      class="hidden"
      @change="handleFiles"
    />
    <input
      ref="folderInput"
      type="file"
      accept=".json,application/json"
      multiple
      webkitdirectory
      directory
      class="hidden"
      @change="handleFiles"
    />

    <UiStatePanel v-if="busy && !sources.length" state="loading" title="正在读取文件" message="解析并校验 JSON 内容…" />
    <UiStatePanel v-else-if="!busy && !sources.length" state="empty" title="尚未载入文件" message="选择 JSON 文件或文件夹后，会在列表中预览校验结果。" />

    <section class="panel" data-cpa-stage="configuration">
      <h3 class="panel-title">文件区</h3>
      <div class="flex flex-wrap items-center gap-3">
        <button class="btn" :disabled="busy" @click="pickFiles">添加文件</button>
        <button class="btn" :disabled="busy" @click="pickFolder">添加文件夹</button>
        <button class="btn" :disabled="busy || !sources.length" @click="clearFiles">清空</button>
        <div class="text-sm font-semibold text-blue-300">
          共 {{ totalCount }} 个文件，已识别 {{ validCount }} 个，已勾选 {{ selectedCount }} 个，无效 {{ invalidCount }} 个。
        </div>
      </div>
    </section>

    <section v-if="sources.length" class="panel">
      <h3 class="panel-title">文件列表</h3>
      <div class="overflow-x-auto rounded-xl border border-gray-800 min-h-[310px] bg-gray-950/40">
        <table class="w-full text-sm">
          <thead class="bg-gray-800/80 text-blue-100">
            <tr>
              <th class="table-head w-20">选择</th>
              <th class="table-head">文件名</th>
              <th class="table-head">邮箱</th>
              <th class="table-head">目标名称</th>
              <th class="table-head">套餐</th>
              <th class="table-head">源格式</th>
              <th class="table-head">校验结果</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-800">
            <tr v-for="source in sources" :key="source.key" class="hover:bg-gray-800/40">
              <td class="px-4 py-3">
                <input
                  type="checkbox"
                  :aria-label="`选择文件 ${source.file_name}`"
                  :checked="source.selected"
                  :disabled="!source.is_valid || busy"
                  class="rounded bg-gray-900 border-gray-700 text-blue-500 focus:ring-blue-500"
                  @change="toggleSource(source.key)"
                />
              </td>
              <td class="px-4 py-3 max-w-[320px] truncate font-mono text-xs text-gray-200" :title="source.file_name">
                {{ source.file_name }}
              </td>
              <td class="px-4 py-3 font-mono text-xs text-gray-300">{{ source.email || '-' }}</td>
              <td class="px-4 py-3 text-gray-300">{{ source.target_name || '-' }}</td>
              <td class="px-4 py-3 text-gray-300">{{ source.plan_type || '-' }}</td>
              <td class="px-4 py-3 text-gray-400">{{ source.variant || '-' }}</td>
              <td class="px-4 py-3">
                <span :class="source.is_valid ? 'text-green-400' : 'text-red-400'">
                  {{ source.status_text || '-' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="grid grid-cols-1 xl:grid-cols-[minmax(0,0.78fr)_minmax(0,1fr)] gap-4">
      <section class="panel">
        <h3 class="panel-title">导出操作</h3>
        <div class="space-y-3">
          <div class="summary-row">
            <span class="summary-label">输出目录</span>
            <span class="summary-value" :title="settings.output_dir">{{ settings.output_dir }}</span>
            <button class="btn btn-compact" :disabled="busy || directoryChooserBusy" @click="chooseOutputDir('settings')">选择目录</button>
          </div>
          <div class="summary-row">
            <span class="summary-label">输出文件</span>
            <span class="summary-value" :title="settings.output_filename">{{ settings.output_filename }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">代理</span>
            <span class="summary-value">{{ proxySummary }}</span>
          </div>
          <div class="summary-row">
            <span class="summary-label">导出参数</span>
            <span class="summary-value">{{ policySummary }}</span>
          </div>
        </div>

        <p class="mt-4 text-sm text-gray-400">完整配置已移到独立窗口编辑，主界面只保留摘要，避免挤压。</p>

        <div class="mt-5 flex flex-wrap items-center gap-3">
          <button class="btn" :disabled="busy" @click="openSettingsDialog">编辑导出设置</button>
          <button class="btn-primary" :disabled="busy || selectedCount === 0" @click="convertSelected">
            {{ busy ? '转换中...' : '开始转换' }}
          </button>
          <button class="btn" :disabled="busy || !canOpenOutputDir" @click="openOutputDir">打开输出目录</button>
        </div>
      </section>

      <section class="panel" data-cpa-stage="result" aria-live="polite">
        <h3 class="panel-title">执行结果</h3>
        <div class="text-sm font-semibold text-blue-300 mb-3">
          成功 {{ resultSuccess }} 个，失败 {{ resultFailed }} 个。
        </div>
        <input readonly aria-label="导出结果路径" class="result-path" :value="resultPath" />
        <div class="result-log">
          <template v-if="resultLines.length">
            <div v-for="(line, index) in resultLines" :key="index" :class="line.type === 'error' ? 'text-red-400' : 'text-gray-300'">
              {{ line.text }}
            </div>
          </template>
          <div v-else class="text-gray-500">这里会显示导出结果、无效文件和错误原因。</div>
        </div>
      </section>
    </div>

    <AccessibleModal v-if="settingsDialogOpen" label="导出设置" @close="settingsDialogOpen = false">
      <div class="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-xl border border-gray-800 bg-gray-900 p-5 shadow-2xl">
        <div class="mb-4">
          <h3 class="text-lg font-bold text-white">导出设置</h3>
          <p class="text-sm text-gray-400 mt-1">完整导出配置放在这里编辑。保存后，主界面只保留摘要。</p>
        </div>

        <div class="space-y-5">
          <section class="settings-box">
            <h4 class="settings-title">基础设置</h4>
            <div class="grid grid-cols-1 gap-3">
              <label class="field">
                <span>输出目录</span>
                <div class="flex gap-2">
                  <input v-model.trim="draftSettings.output_dir" type="text" class="input" />
                  <button class="btn shrink-0" :disabled="directoryChooserBusy" @click="chooseOutputDir('draft')">选择目录</button>
                </div>
              </label>
              <label class="field">
                <span>输出文件名</span>
                <input v-model.trim="draftSettings.output_filename" type="text" class="input" />
              </label>
              <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
                <label class="field">
                  <span>并发数</span>
                  <input v-model.number="draftSettings.concurrency" type="number" min="0" class="input" />
                </label>
                <label class="field">
                  <span>优先级</span>
                  <input v-model.number="draftSettings.priority" type="number" min="0" class="input" />
                </label>
                <label class="field">
                  <span>倍率</span>
                  <input v-model.number="draftSettings.rate_multiplier" type="number" min="0" step="0.01" class="input" />
                </label>
              </div>
              <label class="flex items-center gap-2 text-sm text-gray-300">
                <input
                  v-model="draftSettings.auto_pause_on_expired"
                  type="checkbox"
                  aria-label="到期后自动暂停"
                  class="rounded bg-gray-950 border-gray-700 text-blue-500 focus:ring-blue-500"
                />
                到期后自动暂停
              </label>
            </div>
          </section>

          <section class="settings-box">
            <h4 class="settings-title">代理设置</h4>
            <label class="mb-3 flex items-center gap-2 text-sm text-gray-300">
              <input
                v-model="draftSettings.proxy.enabled"
                type="checkbox"
                aria-label="启用代理"
                class="rounded bg-gray-950 border-gray-700 text-blue-500 focus:ring-blue-500"
              />
              启用代理
            </label>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3" :class="draftSettings.proxy.enabled ? '' : 'opacity-50 pointer-events-none'">
              <label class="field">
                <span>名称</span>
                <input v-model.trim="draftSettings.proxy.name" type="text" class="input" />
              </label>
              <label class="field">
                <span>协议</span>
                <select v-model="draftSettings.proxy.protocol" class="input">
                  <option value="http">http</option>
                  <option value="https">https</option>
                  <option value="socks5">socks5</option>
                  <option value="socks5h">socks5h</option>
                </select>
              </label>
              <label class="field">
                <span>地址</span>
                <input v-model.trim="draftSettings.proxy.host" type="text" class="input" />
              </label>
              <label class="field">
                <span>端口</span>
                <input v-model.number="draftSettings.proxy.port" type="number" min="1" max="65535" class="input" />
              </label>
              <label class="field">
                <span>用户名</span>
                <input v-model.trim="draftSettings.proxy.username" type="text" class="input" />
              </label>
              <label class="field">
                <span>密码</span>
                <input v-model="draftSettings.proxy.password" type="password" class="input" />
              </label>
              <label class="field">
                <span>状态</span>
                <select v-model="draftSettings.proxy.status" class="input">
                  <option value="active">active</option>
                  <option value="inactive">inactive</option>
                </select>
              </label>
            </div>
          </section>
        </div>

        <div class="mt-5 flex justify-end gap-3">
          <button class="btn" @click="settingsDialogOpen = false">取消</button>
          <button class="btn-primary" @click="saveSettings">保存设置</button>
        </div>
      </div>
    </AccessibleModal>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { api } from '../api.js'
import { validateCpaFileSelection } from '../cpaFileLimits.js'
import AccessibleModal from './AccessibleModal.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'

const fileInput = ref(null)
const folderInput = ref(null)
const sourceFiles = ref([])
const sources = ref([])
const busy = ref(false)
const directoryChooserBusy = ref(false)
const settingsDialogOpen = ref(false)
const resultPath = ref('')
const resultLines = ref([])
const lastResultSuccess = ref(0)
const lastResultFailed = ref(0)
const hasConverted = ref(false)

const settings = reactive(defaultSettings())
const draftSettings = reactive(defaultSettings())

const totalCount = computed(() => sources.value.length)
const validCount = computed(() => sources.value.filter((item) => item.is_valid).length)
const invalidCount = computed(() => sources.value.filter((item) => !item.is_valid).length)
const selectedCount = computed(() => sources.value.filter((item) => item.is_valid && item.selected).length)
const resultSuccess = computed(() => (hasConverted.value ? lastResultSuccess.value : selectedCount.value))
const resultFailed = computed(() => (hasConverted.value ? lastResultFailed.value : invalidCount.value))
const metricItems = computed(() => [{ key: 'files', label: '文件', value: totalCount.value, tone: 'neutral' }, { key: 'valid', label: '有效', value: validCount.value, tone: 'success' }, { key: 'selected', label: '已选择', value: selectedCount.value, tone: 'info' }, { key: 'invalid', label: '无效', value: invalidCount.value, tone: 'danger' }, { key: 'converted', label: '已转换', value: resultSuccess.value, tone: 'success' }])
const canOpenOutputDir = computed(() => Boolean(settings.output_dir && resultPath.value))
const proxySummary = computed(() => {
  const proxy = settings.proxy
  if (!proxy.enabled) return '未启用'
  return `${proxy.protocol}://${proxy.host}:${proxy.port}`
})
const policySummary = computed(
  () => `并发 ${settings.concurrency} / 优先级 ${settings.priority} / 倍率 ${Number(settings.rate_multiplier || 0).toFixed(2)}`,
)

function defaultSettings() {
  return {
    output_dir: '',
    output_filename: defaultFilename(),
    concurrency: 10,
    priority: 1,
    rate_multiplier: 1.0,
    auto_pause_on_expired: true,
    proxy: {
      enabled: false,
      name: '批量导入代理',
      protocol: 'http',
      host: '',
      port: 7890,
      username: '',
      password: '',
      status: 'active',
    },
  }
}

onMounted(async () => {
  await loadDefaultOutputDir()
})

async function loadDefaultOutputDir() {
  try {
    const result = await api.getCpaToSub2ApiDefaultOutputDir()
    if (!result.output_dir) return
    if (!settings.output_dir) settings.output_dir = result.output_dir
    if (!draftSettings.output_dir) draftSettings.output_dir = result.output_dir
  } catch (error) {
    appendResult(error.message || '读取默认输出目录失败', 'error')
  }
}

function defaultFilename() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `sub2api-account-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.json`
}

function pickFiles() {
  fileInput.value?.click()
}

function pickFolder() {
  folderInput.value?.click()
}

async function handleFiles(event) {
  const files = Array.from(event.target.files || []).filter((file) => file.name.toLowerCase().endsWith('.json'))
  event.target.value = ''
  if (!files.length) {
    appendResult('选择的文件中没有找到 JSON 文件。', 'error')
    return
  }
  const selection = validateCpaFileSelection(sourceFiles.value, files)
  if (!selection.ok) {
    appendResult(selection.message, 'error')
    return
  }
  busy.value = true
  try {
    const loaded = []
    const loadedAt = Date.now()
    for (const [index, file] of selection.incomingFiles.entries()) {
      loaded.push({
        key: `${Date.now()}-${index}-${file.webkitRelativePath || file.name}`,
        filename: file.webkitRelativePath || file.name,
        content: await file.text(),
        byteSize: Number(file.size || 0),
        loadedAt,
      })
    }
    sourceFiles.value = mergeFiles(sourceFiles.value, loaded)
    await inspectFiles()
    appendResult(`已载入 ${loaded.length} 个文件，当前总数 ${sourceFiles.value.length}。`)
  } catch (error) {
    appendResult(error.message || '读取文件失败', 'error')
  } finally {
    busy.value = false
  }
}

function mergeFiles(existing, incoming) {
  const next = [...existing]
  for (const item of incoming) {
    const oldIndex = next.findIndex((existingItem) => existingItem.filename === item.filename)
    if (oldIndex >= 0) next.splice(oldIndex, 1, item)
    else next.push(item)
  }
  return next
}

async function inspectFiles() {
  if (!sourceFiles.value.length) {
    sources.value = []
    return
  }
  const previousSelected = new Map(sources.value.map((item) => [item.file_name, item.selected]))
  const result = await api.inspectCpaToSub2Api(toApiFiles())
  sources.value = result.records.map((record, index) => ({
    ...record,
    key: `${index}-${record.file_name}`,
    selected: record.is_valid && (previousSelected.get(record.file_name) ?? record.selected),
  }))
  hasConverted.value = false
}

function toApiFiles() {
  return sourceFiles.value.map((item) => ({
    filename: item.filename,
    content: item.content,
  }))
}

function toggleSource(key) {
  const item = sources.value.find((source) => source.key === key)
  if (item && item.is_valid) {
    item.selected = !item.selected
    hasConverted.value = false
  }
}

function clearFiles() {
  sourceFiles.value = []
  sources.value = []
  resultPath.value = ''
  resultLines.value = []
  lastResultSuccess.value = 0
  lastResultFailed.value = 0
  hasConverted.value = false
}

function openSettingsDialog() {
  Object.assign(draftSettings, cloneSettings(settings))
  settingsDialogOpen.value = true
}

function saveSettings() {
  Object.assign(settings, cloneSettings(draftSettings))
  settings.output_dir = String(settings.output_dir || '').trim()
  settings.output_filename = normalizeFilename(settings.output_filename)
  settingsDialogOpen.value = false
}

async function convertSelected() {
  busy.value = true
  resultLines.value = []
  try {
    const selectedNames = sources.value
      .filter((source) => source.is_valid && source.selected)
      .map((source) => source.file_name)
    const result = await api.convertCpaToSub2Api({
      files: toApiFiles(),
      selected_filenames: selectedNames,
      settings,
    })
    resultPath.value = result.output_path || result.filename
    lastResultSuccess.value = result.converted || 0
    lastResultFailed.value = result.invalid || 0
    hasConverted.value = true
    sources.value = result.records.map((record, index) => ({
      ...record,
      key: `${index}-${record.file_name}`,
      selected: record.is_valid && selectedNames.includes(record.file_name),
    }))
    appendResult(`导出完成：${resultPath.value}`)
    appendInvalidRecords()
    settings.output_filename = defaultFilename()
  } catch (error) {
    appendResult(`转换失败：${error.message || error}`, 'error')
  } finally {
    busy.value = false
  }
}

async function openOutputDir() {
  try {
    await api.openCpaToSub2ApiOutputDir(settings.output_dir)
    appendResult(`已打开输出目录：${settings.output_dir}`)
  } catch (error) {
    appendResult(error.message || '打开输出目录失败', 'error')
  }
}

async function chooseOutputDir(target) {
  if (directoryChooserBusy.value) return
  directoryChooserBusy.value = true
  try {
    const currentDir = target === 'draft' ? draftSettings.output_dir : settings.output_dir
    const result = await api.selectCpaToSub2ApiOutputDir(currentDir)
    if (!result.output_dir) return
    if (target === 'draft') {
      draftSettings.output_dir = result.output_dir
    } else {
      settings.output_dir = result.output_dir
    }
  } catch (error) {
    appendResult(error.message || '选择输出目录失败', 'error')
  } finally {
    directoryChooserBusy.value = false
  }
}

function appendInvalidRecords() {
  for (const source of sources.value) {
    if (!source.is_valid) {
      appendResult(`${source.file_name}: ${source.error_message || source.status_text || '无效文件'}`, 'error')
    }
  }
}

function appendResult(text, type = 'info') {
  resultLines.value.push({ text, type })
}

function cloneSettings(value) {
  return JSON.parse(JSON.stringify(value))
}

function normalizeFilename(value) {
  const name = String(value || '').trim() || defaultFilename()
  return name.toLowerCase().endsWith('.json') ? name : `${name}.json`
}
</script>

<style scoped>
.panel {
  @apply bg-gray-900 border border-gray-800 rounded-xl p-5;
}

.panel-title {
  @apply text-base font-bold text-white mb-4;
}

.btn {
  @apply px-4 py-2 bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-100 text-sm font-medium rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed;
}

.btn-primary {
  @apply px-4 py-2 bg-blue-600 hover:bg-blue-500 border border-blue-500 text-white text-sm font-semibold rounded-lg transition disabled:opacity-50 disabled:cursor-not-allowed;
}

.btn-compact {
  @apply px-3;
}

.table-head {
  @apply px-4 py-3 text-left font-semibold;
}

.summary-row {
  @apply grid grid-cols-[82px_minmax(0,1fr)_auto] items-center gap-3;
}

.summary-label {
  @apply text-sm text-gray-300;
}

.summary-value {
  @apply truncate rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm font-semibold text-blue-200;
}

.result-path {
  @apply mb-3 w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-300 outline-none;
}

.result-log {
  @apply min-h-[180px] rounded-lg border border-gray-800 bg-gray-950 p-3 text-sm leading-6;
}

.settings-box {
  @apply rounded-xl border border-gray-800 bg-gray-950/60 p-4;
}

.settings-title {
  @apply mb-3 text-sm font-semibold text-white;
}

.field {
  @apply block;
}

.field span {
  @apply mb-1 block text-xs text-gray-400;
}

.input {
  @apply w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-white outline-none focus:border-blue-500;
}
</style>
