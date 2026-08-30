# Apple Light Theme and Full UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变后端 API 与业务状态机的前提下，把整个 Vue 前端重构为流畅、可访问、Apple 风格的全路由界面，并提供首屏无闪烁的 `system | light | dark` 三态主题。

**Architecture:** 先从已验证提交恢复 43 个既有前端回归，再以根节点数据属性、纯 JavaScript 主题控制器和语义 CSS Token 建立主题基础。页面按应用框架、数据工作台、业务工作流、管理设置四种视觉原型逐阶段迁移；共享 UI 组件只接收状态和发出意图，业务页继续拥有请求、轮询、取消、恢复、持久化和大列表窗口化。

**Tech Stack:** Vue 3.5、Vite 6、Tailwind CSS 3.4、原生 JavaScript/Node assertions、CSS custom properties、Playwright Core 1.55、axe-core/playwright 4.10。

## Global Constraints

- 实施分支固定为 `codex/apple-light-theme-ui`；隔离工作树固定为 `D:\code\OpenSource\AutoTeam-F\.worktrees\apple-light-theme-ui`。
- 修改基线固定为 `f0a222fcddee752784230040e58dc938b68e8517`，基线树固定为 `92957da9ac905f15cd1cee50f9d86e01d35c1503`。
- 既有 7 个运行时文件的已验证恢复来源固定为 `e2a77c0f77d90bed4cc3a4ab5d6f29cc3ad02b1f`。
- Task 1 仅恢复已验证的 `App.vue`、`api.js`、`request.js`、`runtimePerformance.js`、`Sidebar.vue`、`PageLoadError.vue`、`style.css`；后续任务不改变后端 API 或请求 payload。
- 不改变登录隔离、任务持久化、start acknowledgement、single-flight、轮询、取消、恢复、unknown-outcome、超时和大列表窗口化语义。
- 主题偏好仅允许 `system | light | dark`，存储键固定为 `autotoken_theme`。
- 主题状态只写入 `document.documentElement`、`color-scheme` 和 `meta[name="theme-color"]`；不得遍历业务 DOM，不得发起网络请求。
- 不使用 `transition: all` 或 `transition-all`；主题变化不得全局动画颜色。
- 明亮主题画布固定为 `#f5f5f7`，窗口/面板固定为 `#ffffff`，正文固定为 `#1d1d1f`，主强调固定为 `#0071e3`。
- `text-on-accent` 在明暗主题均保持白色，不能映射成普通正文色。
- 正文对比度至少 `4.5:1`；控件边界与焦点指示至少 `3:1`；触控目标至少 `44px`。
- 必须支持键盘、焦点返回、`forced-colors` 与 `prefers-reduced-motion`。
- Phase 1 首先把现有前端脚本从 `32/43` 恢复到 `43/43`，之后新增回归脚本继续全部通过。
- 生产入口不超过 `250 KiB`，异步 JavaScript chunk 不少于 `8`。
- 全部页面必须覆盖明亮、深色、跟随系统、桌面、移动端和短视口。
- 不新增 Support 页面或后端接口；支持与维护功能进入 Settings，并链接现有 LogViewer。
- 新回归文件使用非忽略名称 `*-regression.mjs`；`run-frontend-tests.mjs` 同时发现已跟踪的 `test-*.mjs` 与新 `*-regression.mjs`。
- 每个实现任务严格执行 RED → 验证 RED → 最小实现 → GREEN → commit；纯验收/工件任务执行其列出的 preflight、验证、重开和记录步骤，失败时先定位根因，不跳过门禁。

---

## Locked File and Interface Map

### Theme and shell

- Create `web/src/themePreference.js` and `web/src/components/ThemeSwitcher.vue` (`mode="compact" | "group"`).
- Create `web/src/components/ui/UiPageHeader.vue`, `UiSurface.vue`, `UiButton.vue`, `UiStatusBadge.vue`, `UiFormField.vue`, `UiSegmentedControl.vue`, `UiStatePanel.vue`, `UiSheet.vue`.
- Modify `web/index.html`, `web/src/main.js`, `web/src/style.css`, `web/tailwind.config.js`, `web/src/App.vue`, `Sidebar.vue`, `SetupPage.vue`, `AccessibleModal.vue`, `TaskPanel.vue`, `PageLoading.vue`, `PageLoadError.vue`, `Settings.vue`.

### Operations workspace

- Create `web/src/useMediaQuery.js`, `web/src/operationsPresentation.js`, `web/src/taskHistoryData.js`.
- Create `UiMetricSummary.vue`, `UiDataToolbar.vue`, `UiBatchBar.vue`, `UiPagination.vue`, `UiTableFrame.vue`.
- Modify Dashboard, MailAccountsPage, TaskHistory, TaskHistoryPage, LogViewer, TeamMembers, navigation and NavIcon.
- Delete the duplicate unreachable `web/src/components/TasksPage.vue` only after confirming it has no live import.

### Workflow workspace

- Create `web/src/components/workflow/WorkflowWorkspace.vue` and `WorkflowStage.vue`.
- Modify RegisterAccountPage, BindCardPool, BindCard, UsPaypalPage, IdealLinkPage, MomoPage, GCashPhPage, BrazilPixPage, IndiaUpiPage and KakaoPayPage.

### Management, settings and QA

- Create `web/src/components/settings/SettingsWorkspace.vue` and `SettingsGroup.vue`.
- Modify OAuthPage, OAuthPhonePoolPage, OAuthPhoneRecordsPage, PoolPage, SyncPage, TradeManagerPage, CpaToSub2ApiPage, Settings and LogViewer.
- Create repeatable browser fixture/QA scripts and `cleanup-artifacts/apple-light-theme-ui/` transaction artifacts.

### Locked theme controller API

```js
export const THEME_STORAGE_KEY = 'autotoken_theme'
export const THEME_PREFERENCES = Object.freeze(['system', 'light', 'dark'])
export const THEME_CONTROLLER_KEY = Symbol('autotoken-theme-controller')

normalizeThemePreference(value)
// => 'system' | 'light' | 'dark'

resolveThemePreference(preference, systemDark)
// => 'light' | 'dark'

createThemeController({
  root,
  storage,
  mediaQueryList,
  eventTarget,
  themeColorMeta,
  initialPreference,
})
// => {
//   getSnapshot(): { preference, resolvedTheme },
//   setPreference(next): { preference, resolvedTheme },
//   subscribe(listener): unsubscribe,
//   dispose(): void,
// }
```

### Locked shared primitive APIs

| Component | Props | Emits / Slots |
|---|---|---|
| `UiPageHeader` | `title` required, `eyebrow`, `description`, `status` | `actions`, default |
| `UiSurface` | `as`, `variant=panel|strong|inset`, `padding=none|sm|md|lg`, `labelledby` | `header`, default, `footer` |
| `UiButton` | `type`, `variant=primary|secondary|quiet|danger`, `size=sm|md`, `disabled`, `loading` | `click`; `icon`, default |
| `UiStatusBadge` | `tone=neutral|info|success|warning|danger`, `label`, `dot` | none |
| `UiFormField` | `id`, `label`, `help`, `error`, `required`, `disabled` | scoped default `{ inputId, describedBy, invalid, disabled }` |
| `UiSegmentedControl` | `modelValue`, `options[{value,label,description?}]`, `ariaLabel` | `update:modelValue`; exposes `focusSelected()` |
| `UiStatePanel` | `state=loading|empty|error|partial`, `title`, `message`, `actionLabel` | `action` |
| `UiSheet` | `open`, `label`, `labelledby`, `side=bottom|right`, `initialFocusSelector` | `close`, `after-close`; header/default/footer |
| `ThemeSwitcher` | `mode=compact|group` | no business events |

### Locked operations workspace primitive APIs

| Component | Props | Emits / Slots |
|---|---|---|
| `UiMetricSummary` | `items: Array<{key, label, value, tone?, detail?}> = []`, `label='关键指标'`, `compact=false` | `empty` |
| `UiDataToolbar` | `resultLabel=''`, `activeFilterCount=0`, `filtersLabel='筛选'`, `clearable=false` | `clear-filters`; `primary`, `filters`, `actions` |
| `UiBatchBar` | required `count`, `label='已选择'`, `itemLabel='项'`, `busy=false` | `clear`; default |
| `UiPagination` | required `page`, `pageSize`, `totalItems`; `pageSizes=[]`, `itemLabel='条记录'` | `update:page`, `update:pageSize` |
| `UiTableFrame` | required `label`; `busy=false`, `empty=false`, `minWidth='0'` | `header`, default, `empty`, `footer` |

### Locked operations APIs

```js
export function useMediaQuery(query) // => Readonly<Ref<boolean>>

export function accountStatusPresentation(value) // => { label, tone }
export function accountTypePresentation(value)
export function bindProviderPresentation(value)
export function mailAccountStatusPresentation(value)
export function mailCheckStatusPresentation(value)
export function taskStatusPresentation(value)
export function teamRolePresentation(value)
export function teamMemberTypePresentation(value)
export function oauthPhoneStatusPresentation(value)
export function oauthPhoneRecordStatusPresentation(value)

export const TASK_HISTORY_PAGE_SIZE = 50
export function filterTaskHistory(tasks, {
  query = '',
  status = '',
  command = '',
} = {})
export function pageTaskHistory(tasks, page, pageSize = TASK_HISTORY_PAGE_SIZE)
// => { page, pageSize, totalItems, totalPages, rows }
export function summarizeTaskHistory(tasks)
// => { total, active, completed, failed }
```

---

## Phase 1：主题基础与应用框架

**目标：** 恢复全部既有前端运行时保障，并实现无首屏闪烁的 system / light / dark 三态主题、语义 Token、共享 UI 原语及登录、Setup、应用框架、导航、弹窗和任务面板重设计。

**架构：** 先从已验证提交 e2a77c0f77d90bed4cc3a4ab5d6f29cc3ad02b1f 恢复被 ac298d7 回退的七个文件，使 43 个既有脚本全部转绿；随后用纯 JavaScript controller 管理主题，并由 main.js 注入同一实例。主题变化只更新根节点、color-scheme 和 theme-color；Tailwind RGB 变量负责旧页面即时兼容，共享 Vue 原语不读取业务 API。

**技术栈：** Vue 3.5、Vite 6、Tailwind CSS 3.4、原生 JavaScript/Node assertions、CSS custom properties。

### 全局约束

- 分支：codex/apple-light-theme-ui。
- 工作树：D:\code\OpenSource\AutoTeam-F\.worktrees\apple-light-theme-ui。
- 不改变后端 API、业务状态机、轮询、取消、恢复、持久化及大列表保护逻辑。
- 偏好仅允许 system / light / dark，键固定为 autotoken_theme。
- light 画布固定 #f5f5f7；主题切换不遍历 DOM、不发请求、不使用全局颜色 transition。
- 正文对比度 >= 4.5:1；控件边界/焦点环 >= 3:1；触控目标 >= 44px。
- 支持键盘、焦点返回、forced-colors、prefers-reduced-motion。
- Task 1 先恢复既有 43/43；theme-regression 纳入 runner 后 Phase 1 全套为 44/44。
- entry <= 250 KiB；异步 JavaScript chunks >= 8；不新增运行时或业务依赖。Task 27 may add only the explicitly listed dev-only Playwright Core and axe-core/playwright packages for browser QA.

### 精确文件与接口

**Create**

- web/src/themePreference.js
- web/scripts/theme-regression.mjs
- web/src/components/ThemeSwitcher.vue
- web/src/components/ui/UiPageHeader.vue
- web/src/components/ui/UiSurface.vue
- web/src/components/ui/UiButton.vue
- web/src/components/ui/UiStatusBadge.vue
- web/src/components/ui/UiFormField.vue
- web/src/components/ui/UiSegmentedControl.vue
- web/src/components/ui/UiStatePanel.vue
- web/src/components/ui/UiSheet.vue

**Modify**

- web/index.html
- web/package.json
- web/tailwind.config.js
- web/scripts/run-frontend-tests.mjs
- web/src/main.js
- web/src/style.css
- web/src/App.vue
- web/src/api.js
- web/src/request.js
- web/src/runtimePerformance.js
- web/src/components/Sidebar.vue
- web/src/components/SetupPage.vue
- web/src/components/AccessibleModal.vue
- web/src/components/TaskPanel.vue
- web/src/components/PageLoading.vue
- web/src/components/PageLoadError.vue
- web/src/components/Settings.vue
- web/src/components/BrazilPixPage.vue
- web/src/components/IndiaUpiPage.vue
- web/src/components/KakaoPayPage.vue

**Controller contract**

~~~js
normalizeThemePreference(value) // 'system' | 'light' | 'dark'
resolveThemePreference(preference, systemDark) // 'light' | 'dark'
createThemeController({
  root,
  storage,
  mediaQueryList,
  eventTarget,
  themeColorMeta,
  initialPreference,
}) // {
   // getSnapshot(): { preference, resolvedTheme }
   // setPreference(next): snapshot
   // subscribe(listener): unsubscribe
   // dispose(): void
   // }
~~~

**Shared component contract**

- UiPageHeader: title required；eyebrow/description/status optional；slots actions/default。
- UiSurface: as；variant panel|strong|inset；padding none|sm|md|lg；labelledby；slots header/default/footer。
- UiButton: type；variant primary|secondary|quiet|danger；size sm|md；disabled/loading；emit click；slots icon/default。
- UiStatusBadge: tone neutral|info|success|warning|danger；label/dot。
- UiFormField: id/label/help/error/required/disabled；scoped slot { inputId, describedBy, invalid, disabled }。
- UiSegmentedControl: modelValue；options [{ value, label, description? }]；ariaLabel；emit update:modelValue；expose focusSelected()。
- UiStatePanel: state loading|empty|error|partial；title/message/actionLabel；emit action。
- UiSheet: open/label/labelledby；side bottom|right；initialFocusSelector；emit close/after-close；slots header/default/footer。
- ThemeSwitcher: mode compact|group，default compact。

### 11 个既有失败与修复路径

| Script | Observed failure / root cause | Fix |
|---|---|---|
| test-account-loading-lifecycle.mjs | missing shouldLoadDashboardAccounts/current-page lifecycle | App.vue |
| test-account-loading-performance.mjs | immutable snapshots no longer shallowRef | App.vue |
| test-auth-session-isolation.mjs | 22 failures: auth epoch, owner rotation, stale-response fencing, keyed single-flight | App.vue, api.js, runtimePerformance.js |
| test-export-commit-order.mjs | exportAccountSubAuths lost timeoutMs: 0 | api.js |
| test-frontend-runtime.mjs | timeout disarmed before response body consume; App/API guards regressed | request.js, App.vue, api.js |
| test-frontend-shell.mjs | sheet Teleport/inert/focus/breakpoint/retry and CSS protections regressed | Sidebar.vue, App.vue, PageLoadError.vue, style.css |
| test-log-viewer.mjs | getLogs lost sinceBootId/since_boot_id | api.js |
| test-long-running-api-timeouts.mjs | serialOperationTimeoutMs export and endpoint deadlines removed | api.js |
| test-payment-unknown-outcome.mjs | payment submit/cancel/reconcile deadlines removed | api.js |
| test-storage-session-isolation.mjs | logout ordering and owner/session fencing removed | App.vue, api.js |
| test-storage-unavailable.mjs | saved page read unguarded; memory key/cross-tab invalidation regressed | App.vue, api.js |

---

### Task 1：恢复 43/43 运行时基线

**Files**

- Modify: web/src/App.vue
- Modify: web/src/api.js
- Modify: web/src/request.js
- Modify: web/src/runtimePerformance.js
- Modify: web/src/components/Sidebar.vue
- Modify: web/src/components/PageLoadError.vue
- Modify: web/src/style.css

**Produces**

- createSingleFlight(run, { key })
- fetchWithTimeout(input, init, { timeoutMs, fetchImpl, consume })
- auth epoch/session-owner fencing
- retryable async page and accessible navigation behavior

- [ ] **Step 1: RED — prove all 11 known regressions**

~~~powershell
$tests = @(
  'test-account-loading-lifecycle.mjs',
  'test-account-loading-performance.mjs',
  'test-auth-session-isolation.mjs',
  'test-export-commit-order.mjs',
  'test-frontend-runtime.mjs',
  'test-frontend-shell.mjs',
  'test-log-viewer.mjs',
  'test-long-running-api-timeouts.mjs',
  'test-payment-unknown-outcome.mjs',
  'test-storage-session-isolation.mjs',
  'test-storage-unavailable.mjs'
)
$failed = @()
foreach ($test in $tests) {
  & node "web/scripts/$test"
  if ($LASTEXITCODE -ne 0) { $failed += $test }
}
"KNOWN_RED=$($failed.Count)/$($tests.Count)"
if ($failed.Count -ne 11) { exit 2 }
exit 1
~~~

Expected literal result:

~~~text
KNOWN_RED=11/11
exit status 1
~~~

- [ ] **Step 2: Restore the exact verified implementations**

No commit after ac298d7 and before f0a222f changed these paths.

~~~powershell
git restore --source=e2a77c0f77d90bed4cc3a4ab5d6f29cc3ad02b1f -- web/src/App.vue web/src/api.js web/src/request.js web/src/runtimePerformance.js web/src/components/Sidebar.vue web/src/components/PageLoadError.vue web/src/style.css
~~~

- [ ] **Step 3: GREEN — run the 11 focused scripts**

~~~powershell
$tests = @(
  'test-account-loading-lifecycle.mjs',
  'test-account-loading-performance.mjs',
  'test-auth-session-isolation.mjs',
  'test-export-commit-order.mjs',
  'test-frontend-runtime.mjs',
  'test-frontend-shell.mjs',
  'test-log-viewer.mjs',
  'test-long-running-api-timeouts.mjs',
  'test-payment-unknown-outcome.mjs',
  'test-storage-session-isolation.mjs',
  'test-storage-unavailable.mjs'
)
foreach ($test in $tests) {
  & node "web/scripts/$test"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
~~~

Expected: all eleven commands exit 0。

- [ ] **Step 4: GREEN — full existing suite**

~~~powershell
npm.cmd --prefix web run test:frontend-regressions
~~~

Expected:

~~~text
all frontend scripts passed: 43/43
exit status 0
~~~

- [ ] **Step 5: Build**

~~~powershell
npm.cmd --prefix web run build
~~~

Expected: Vite exits 0。

- [ ] **Step 6: Commit**

~~~powershell
git add web/src/App.vue web/src/api.js web/src/request.js web/src/runtimePerformance.js web/src/components/Sidebar.vue web/src/components/PageLoadError.vue web/src/style.css
git commit -m "fix(frontend): restore runtime regression guarantees"
~~~

---

### Task 2：Theme Controller TDD and expanded regression discovery

**Files**

- Create: web/src/themePreference.js
- Create: web/scripts/theme-regression.mjs
- Modify: web/scripts/run-frontend-tests.mjs
- Modify: web/package.json

**Produces**

- THEME_STORAGE_KEY
- THEME_PREFERENCES
- THEME_CONTROLLER_KEY
- normalizeThemePreference()
- resolveThemePreference()
- createThemeController()

- [ ] **Step 1: RED — create web/scripts/theme-regression.mjs**

~~~js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  THEME_CONTROLLER_KEY,
  THEME_STORAGE_KEY,
  createThemeController,
  normalizeThemePreference,
  resolveThemePreference,
} from '../src/themePreference.js'

class FakeEventTarget {
  constructor() { this.listeners = new Map() }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || new Set()
    listeners.add(listener)
    this.listeners.set(type, listeners)
  }
  removeEventListener(type, listener) {
    this.listeners.get(type)?.delete(listener)
  }
  dispatch(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event)
  }
  listenerCount(type) {
    return this.listeners.get(type)?.size || 0
  }
}

function createStorage(seed = {}, blocked = false) {
  const values = new Map(Object.entries(seed))
  return {
    getItem(key) {
      if (blocked) throw new DOMException('blocked', 'SecurityError')
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      if (blocked) throw new DOMException('blocked', 'SecurityError')
      values.set(key, String(value))
    },
    removeItem(key) {
      if (blocked) throw new DOMException('blocked', 'SecurityError')
      values.delete(key)
    },
    value(key) { return values.get(key) },
  }
}

const createRoot = () => ({ dataset: {}, style: {} })

assert.equal(typeof THEME_CONTROLLER_KEY, 'symbol')
assert.equal(THEME_STORAGE_KEY, 'autotoken_theme')
assert.equal(normalizeThemePreference('system'), 'system')
assert.equal(normalizeThemePreference('light'), 'light')
assert.equal(normalizeThemePreference('dark'), 'dark')
assert.equal(normalizeThemePreference('sepia'), 'system')
assert.equal(resolveThemePreference('system', false), 'light')
assert.equal(resolveThemePreference('system', true), 'dark')
assert.equal(resolveThemePreference('light', true), 'light')
assert.equal(resolveThemePreference('dark', false), 'dark')

const storage = createStorage({ [THEME_STORAGE_KEY]: 'invalid' })
const media = new FakeEventTarget()
media.matches = true
const events = new FakeEventTarget()
const root = createRoot()
const meta = { content: '' }
const controller = createThemeController({
  root,
  storage,
  mediaQueryList: media,
  eventTarget: events,
  themeColorMeta: meta,
})

assert.deepEqual(controller.getSnapshot(), {
  preference: 'system',
  resolvedTheme: 'dark',
})
assert.equal(root.dataset.themePreference, 'system')
assert.equal(root.dataset.theme, 'dark')
assert.equal(root.style.colorScheme, 'dark')
assert.equal(meta.content, '#151517')
assert.equal(media.listenerCount('change'), 1)
assert.equal(events.listenerCount('storage'), 1)

const snapshots = []
const unsubscribe = controller.subscribe(snapshot => snapshots.push(snapshot))
controller.setPreference('light')
assert.deepEqual(controller.getSnapshot(), {
  preference: 'light',
  resolvedTheme: 'light',
})
assert.equal(storage.value(THEME_STORAGE_KEY), 'light')
assert.equal(meta.content, '#f5f5f7')

media.matches = false
media.dispatch('change', { matches: false })
assert.equal(controller.getSnapshot().resolvedTheme, 'light')

controller.setPreference('system')
media.matches = true
media.dispatch('change', { matches: true })
assert.equal(controller.getSnapshot().resolvedTheme, 'dark')

events.dispatch('storage', {
  key: THEME_STORAGE_KEY,
  newValue: 'light',
})
assert.deepEqual(controller.getSnapshot(), {
  preference: 'light',
  resolvedTheme: 'light',
})
assert.ok(snapshots.length >= 3)

unsubscribe()
controller.dispose()
assert.equal(media.listenerCount('change'), 0)
assert.equal(events.listenerCount('storage'), 0)

const blockedController = createThemeController({
  root: createRoot(),
  storage: createStorage({}, true),
  mediaQueryList: Object.assign(new FakeEventTarget(), { matches: false }),
  eventTarget: new FakeEventTarget(),
  themeColorMeta: { content: '' },
})
assert.doesNotThrow(() => blockedController.setPreference('dark'))
assert.deepEqual(blockedController.getSnapshot(), {
  preference: 'dark',
  resolvedTheme: 'dark',
})
blockedController.dispose()

const controllerSource = readFileSync(
  new URL('../src/themePreference.js', import.meta.url),
  'utf8',
)
assert.doesNotMatch(
  controllerSource,
  /querySelectorAll|getElementsByClassName|getElementsByTagName|TreeWalker/,
  'theme changes must not traverse the page DOM',
)

console.log('theme controller regression tests passed')
~~~

- [ ] **Step 2: Expand web/scripts/run-frontend-tests.mjs discovery**

Replace its test filter with:

~~~js
const tests = readdirSync(scriptsDirectory)
  .filter(name =>
    name.endsWith('.mjs') &&
    (name.startsWith('test-') || name.endsWith('-regression.mjs'))
  )
  .sort((left, right) => left.localeCompare(right))
~~~

This keeps the 43 tracked test-* scripts and includes non-ignored theme-regression.mjs plus later operations/workflow/management regression scripts.

- [ ] **Step 3: Add package scripts**

~~~json
"test:theme": "node scripts/theme-regression.mjs",
"test:frontend": "npm run build && npm run test:frontend-regressions"
~~~

Preserve every other script.

- [ ] **Step 4: Run RED**

~~~powershell
npm.cmd --prefix web run test:theme
~~~

Expected: ERR_MODULE_NOT_FOUND for web/src/themePreference.js，exit 1。

- [ ] **Step 5: Implement web/src/themePreference.js**

~~~js
export const THEME_STORAGE_KEY = 'autotoken_theme'
export const THEME_PREFERENCES = Object.freeze(['system', 'light', 'dark'])
export const THEME_CONTROLLER_KEY = Symbol('autotoken-theme-controller')

const DARK_MEDIA_QUERY = '(prefers-color-scheme: dark)'
const THEME_COLORS = Object.freeze({
  light: '#f5f5f7',
  dark: '#151517',
})

export function normalizeThemePreference(value) {
  return THEME_PREFERENCES.includes(value) ? value : 'system'
}

export function resolveThemePreference(preference, systemDark = false) {
  const normalized = normalizeThemePreference(preference)
  if (normalized === 'system') return systemDark ? 'dark' : 'light'
  return normalized
}

function readGlobal(name) {
  try { return globalThis[name] || null } catch { return null }
}

function safeRead(storage) {
  try { return storage?.getItem?.(THEME_STORAGE_KEY) ?? null } catch { return null }
}

function safeWrite(storage, preference) {
  try { storage?.setItem?.(THEME_STORAGE_KEY, preference) } catch {}
}

function defaultMediaQueryList() {
  const browserWindow = readGlobal('window')
  try {
    return browserWindow?.matchMedia?.(DARK_MEDIA_QUERY) || null
  } catch {
    return null
  }
}

function defaultThemeColorMeta() {
  const browserDocument = readGlobal('document')
  try {
    return browserDocument?.querySelector?.('meta[name="theme-color"]') || null
  } catch {
    return null
  }
}

function addMediaListener(mediaQueryList, listener) {
  if (typeof mediaQueryList?.addEventListener === 'function') {
    mediaQueryList.addEventListener('change', listener)
    return () => mediaQueryList.removeEventListener('change', listener)
  }
  if (typeof mediaQueryList?.addListener === 'function') {
    mediaQueryList.addListener(listener)
    return () => mediaQueryList.removeListener(listener)
  }
  return () => {}
}

function applyThemeState(root, themeColorMeta, preference, resolvedTheme) {
  if (root) {
    root.dataset.themePreference = preference
    root.dataset.theme = resolvedTheme
    if (root.style) root.style.colorScheme = resolvedTheme
  }
  if (themeColorMeta) {
    const color = THEME_COLORS[resolvedTheme]
    if ('content' in themeColorMeta) themeColorMeta.content = color
    else themeColorMeta.setAttribute?.('content', color)
  }
}

export function createThemeController(options = {}) {
  const browserDocument = readGlobal('document')
  const browserWindow = readGlobal('window')
  const root = options.root ?? browserDocument?.documentElement ?? null
  const storage = Object.prototype.hasOwnProperty.call(options, 'storage')
    ? options.storage
    : readGlobal('localStorage')
  const mediaQueryList = Object.prototype.hasOwnProperty.call(options, 'mediaQueryList')
    ? options.mediaQueryList
    : defaultMediaQueryList()
  const eventTarget = Object.prototype.hasOwnProperty.call(options, 'eventTarget')
    ? options.eventTarget
    : browserWindow
  const themeColorMeta = Object.prototype.hasOwnProperty.call(options, 'themeColorMeta')
    ? options.themeColorMeta
    : defaultThemeColorMeta()
  const seed = options.initialPreference
    ?? root?.dataset?.themePreference
    ?? safeRead(storage)

  let preference = normalizeThemePreference(seed)
  let resolvedTheme = resolveThemePreference(
    preference,
    Boolean(mediaQueryList?.matches),
  )
  let disposed = false
  const subscribers = new Set()
  const getSnapshot = () => ({ preference, resolvedTheme })

  function notify() {
    const snapshot = getSnapshot()
    for (const subscriber of subscribers) subscriber(snapshot)
  }

  function commit(nextPreference, shouldPersist) {
    if (disposed) return getSnapshot()
    const normalized = normalizeThemePreference(nextPreference)
    const nextResolved = resolveThemePreference(
      normalized,
      Boolean(mediaQueryList?.matches),
    )
    const changed = normalized !== preference || nextResolved !== resolvedTheme
    preference = normalized
    resolvedTheme = nextResolved
    if (shouldPersist) safeWrite(storage, preference)
    applyThemeState(root, themeColorMeta, preference, resolvedTheme)
    if (changed) notify()
    return getSnapshot()
  }

  function handleSystemChange() {
    if (preference === 'system') commit(preference, false)
  }

  function handleStorageChange(event) {
    if (event?.key !== THEME_STORAGE_KEY) return
    commit(event.newValue, false)
  }

  const removeMediaListener = addMediaListener(
    mediaQueryList,
    handleSystemChange,
  )
  eventTarget?.addEventListener?.('storage', handleStorageChange)
  applyThemeState(root, themeColorMeta, preference, resolvedTheme)

  return {
    getSnapshot,
    setPreference(next) { return commit(next, true) },
    subscribe(listener) {
      if (typeof listener !== 'function' || disposed) return () => {}
      subscribers.add(listener)
      return () => subscribers.delete(listener)
    },
    dispose() {
      if (disposed) return
      disposed = true
      removeMediaListener()
      eventTarget?.removeEventListener?.('storage', handleStorageChange)
      subscribers.clear()
    },
  }
}
~~~

- [ ] **Step 6: Run GREEN**

~~~powershell
npm.cmd --prefix web run test:theme
npm.cmd --prefix web run test:frontend-regressions
~~~

Expected:

~~~text
theme controller regression tests passed
all frontend scripts passed: 44/44
exit status 0
~~~

- [ ] **Step 7: Commit**

~~~powershell
git add web/src/themePreference.js web/scripts/theme-regression.mjs web/scripts/run-frontend-tests.mjs web/package.json
git commit -m "feat(frontend): add resilient theme controller"
~~~


---

### Task 3：First-Paint Bootstrap and Application Injection

**Files**

- Modify: web/scripts/theme-regression.mjs
- Modify: web/index.html
- Modify: web/src/main.js

**Consumes:** createThemeController and THEME_CONTROLLER_KEY。

**Produces:** synchronous first paint state and one injected controller instance。

- [ ] **Step 1: Append bootstrap RED assertions to theme-regression.mjs**

~~~js
import vm from 'node:vm'

const htmlSource = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
const bootstrapSource = htmlSource.match(
  /<script data-theme-bootstrap>([\s\S]*?)<\/script>/,
)?.[1]
assert.ok(bootstrapSource, 'index.html must contain the synchronous theme bootstrap')

function runBootstrap({ stored = null, systemDark = false, blocked = false } = {}) {
  const root = { dataset: {}, style: {} }
  const meta = { content: '' }
  vm.runInNewContext(bootstrapSource, {
    document: {
      documentElement: root,
      querySelector(selector) {
        return selector === 'meta[name="theme-color"]' ? meta : null
      },
    },
    localStorage: {
      getItem(key) {
        assert.equal(key, THEME_STORAGE_KEY)
        if (blocked) throw new DOMException('blocked', 'SecurityError')
        return stored
      },
    },
    matchMedia(query) {
      assert.equal(query, '(prefers-color-scheme: dark)')
      return { matches: systemDark }
    },
  })
  return { root, meta }
}

assert.equal(runBootstrap().root.dataset.theme, 'light')
assert.equal(runBootstrap({ systemDark: true }).root.dataset.theme, 'dark')
assert.equal(runBootstrap({ stored: 'light', systemDark: true }).root.dataset.theme, 'light')
assert.equal(runBootstrap({ stored: 'dark' }).root.dataset.theme, 'dark')
assert.equal(runBootstrap({ stored: 'invalid' }).root.dataset.themePreference, 'system')
assert.doesNotThrow(() => runBootstrap({ blocked: true }))

const mainSource = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8')
assert.match(mainSource, /createThemeController\(\)/)
assert.match(mainSource, /provide\(THEME_CONTROLLER_KEY,\s*themeController\)/)
assert.match(mainSource, /themeController\.dispose\(\)/)
~~~

- [ ] **Step 2: Run RED**

~~~powershell
npm.cmd --prefix web run test:theme
~~~

Expected: index.html must contain the synchronous theme bootstrap，exit 1。

- [ ] **Step 3: Replace web/index.html**

~~~html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#f5f5f7" />
  <title>AutoToken</title>
  <script data-theme-bootstrap>
    (() => {
      const storageKey = 'autotoken_theme'
      const allowed = new Set(['system', 'light', 'dark'])
      let preference = 'system'
      try {
        const stored = localStorage.getItem(storageKey)
        if (allowed.has(stored)) preference = stored
      } catch {}

      let resolvedTheme = preference
      if (preference === 'system') {
        try {
          resolvedTheme = matchMedia('(prefers-color-scheme: dark)').matches
            ? 'dark'
            : 'light'
        } catch {
          resolvedTheme = 'light'
        }
      }

      const root = document.documentElement
      root.dataset.themePreference = preference
      root.dataset.theme = resolvedTheme
      root.style.colorScheme = resolvedTheme
      const themeColor = document.querySelector('meta[name="theme-color"]')
      if (themeColor) {
        themeColor.content = resolvedTheme === 'dark' ? '#151517' : '#f5f5f7'
      }
    })()
  </script>
</head>
<body class="min-h-screen">
  <div id="app"></div>
  <script type="module" src="/src/main.js"></script>
</body>
</html>
~~~

- [ ] **Step 4: Replace web/src/main.js**

~~~js
import { createApp } from 'vue'
import App from './App.vue'
import {
  THEME_CONTROLLER_KEY,
  createThemeController,
} from './themePreference.js'
import './style.css'

const themeController = createThemeController()
const app = createApp(App)
app.provide(THEME_CONTROLLER_KEY, themeController)
app.mount('#app')

if (import.meta.hot) {
  import.meta.hot.dispose(() => themeController.dispose())
}
~~~

- [ ] **Step 5: Run GREEN and build**

~~~powershell
npm.cmd --prefix web run test:theme
npm.cmd --prefix web run build
~~~

Expected: both exit 0。

- [ ] **Step 6: Commit**

~~~powershell
git add web/index.html web/src/main.js web/scripts/theme-regression.mjs
git commit -m "feat(frontend): resolve appearance before first paint"
~~~

---

### Task 4：Semantic Tokens and Tailwind RGB Compatibility

**Files**

- Modify: web/tailwind.config.js
- Modify: web/src/style.css
- Modify: web/src/components/BrazilPixPage.vue
- Modify: web/src/components/IndiaUpiPage.vue
- Modify: web/src/components/KakaoPayPage.vue
- Modify: web/scripts/theme-regression.mjs

**Produces:** semantic surfaces/text/accent/status/depth/environment tokens；alpha-safe Tailwind palette；workflow-hero-surface compatibility。

- [ ] **Step 1: Append RED assertions**

~~~js
const styleSource = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
const tailwindSource = readFileSync(new URL('../tailwind.config.js', import.meta.url), 'utf8')
const componentSources = [
  'BrazilPixPage.vue',
  'IndiaUpiPage.vue',
  'KakaoPayPage.vue',
].map(name => readFileSync(
  new URL('../src/components/' + name, import.meta.url),
  'utf8',
)).join('\n')

assert.match(styleSource, /html\[data-theme=['"]light['"]\]/)
assert.match(styleSource, /--surface-base:\s*#f5f5f7/i)
assert.match(styleSource, /--surface-window:\s*#fff(?:fff)?/i)
assert.match(styleSource, /--text-main:\s*#1d1d1f/i)
assert.match(styleSource, /--accent-fill:\s*#0071e3/i)
assert.match(styleSource, /html\[data-theme=['"]dark['"]\]/)
assert.match(styleSource, /--text-on-accent:\s*#fff(?:fff)?/i)
assert.match(styleSource, /forced-colors:\s*active/)
assert.match(styleSource, /prefers-reduced-motion:\s*reduce/)
assert.doesNotMatch(styleSource, /transition\s*:\s*all/i)
assert.doesNotMatch(styleSource, /\btransition-all\b/)
assert.match(tailwindSource, /<alpha-value>/)
assert.match(tailwindSource, /--tw-neutral-950/)
assert.match(tailwindSource, /--rgb-success-text/)
assert.doesNotMatch(componentSources, /linear-gradient\(135deg,rgba\(15,23,42,0\.96\)/)
assert.match(componentSources, /workflow-hero-surface/)
~~~

Run npm.cmd --prefix web run test:theme。

Expected first failure: semantic light tokens absent，exit 1。

- [ ] **Step 2: Replace web/tailwind.config.js**

~~~js
/** @type {import('tailwindcss').Config} */
const rgb = variable => 'rgb(var(' + variable + ') / <alpha-value>)'
const neutral = Object.fromEntries(
  [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
    .map(shade => [shade, rgb('--tw-neutral-' + shade)]),
)

function tone(text, fill, strong) {
  return {
    50: rgb(text), 100: rgb(text), 200: rgb(text),
    300: rgb(text), 400: rgb(text),
    500: rgb(fill), 600: rgb(strong), 700: rgb(strong),
    800: rgb(strong), 900: rgb(strong), 950: rgb(strong),
  }
}

export default {
  content: ['./index.html', './src/**/*.{vue,js}'],
  theme: {
    extend: {
      colors: {
        white: rgb('--tw-white'),
        black: rgb('--tw-black'),
        gray: neutral,
        slate: neutral,
        blue: tone('--rgb-accent-text', '--rgb-accent-fill', '--rgb-accent-strong'),
        sky: tone('--rgb-accent-text', '--rgb-accent-fill', '--rgb-accent-strong'),
        emerald: tone('--rgb-success-text', '--rgb-success-fill', '--rgb-success-strong'),
        green: tone('--rgb-success-text', '--rgb-success-fill', '--rgb-success-strong'),
        rose: tone('--rgb-danger-text', '--rgb-danger-fill', '--rgb-danger-strong'),
        red: tone('--rgb-danger-text', '--rgb-danger-fill', '--rgb-danger-strong'),
        amber: tone('--rgb-warning-text', '--rgb-warning-fill', '--rgb-warning-strong'),
        yellow: tone('--rgb-warning-text', '--rgb-warning-fill', '--rgb-warning-strong'),
        cyan: tone('--rgb-info-text', '--rgb-info-fill', '--rgb-info-strong'),
        violet: tone('--rgb-violet-text', '--rgb-violet-fill', '--rgb-violet-strong'),
        purple: tone('--rgb-violet-text', '--rgb-violet-fill', '--rgb-violet-strong'),
      },
    },
  },
  plugins: [],
}
~~~

- [ ] **Step 3: Replace root token block in web/src/style.css**

~~~css
:root,
html[data-theme="light"] {
  color-scheme: light;
  --surface-base: #f5f5f7;
  --surface-sidebar: #f2f2f7;
  --surface-window: #ffffff;
  --surface-panel: #ffffff;
  --surface-panel-strong: #f2f2f7;
  --surface-inset: #f5f5f7;
  --surface-muted: #e5e5ea;
  --surface-hover: #ececf0;
  --surface-pressed: #dedee3;
  --surface-line: rgba(60, 60, 67, 0.18);
  --surface-line-strong: rgba(60, 60, 67, 0.28);
  --text-main: #1d1d1f;
  --text-secondary: #424245;
  --text-muted: #6e6e73;
  --text-faint: #7d7d82;
  --text-placeholder: #7d7d82;
  --text-on-accent: #ffffff;
  --accent-fill: #0071e3;
  --accent-hover: #0077ed;
  --accent-strong: #0066cc;
  --accent-text: #0066cc;
  --accent-soft: rgba(0, 113, 227, 0.11);
  --accent-ring: rgba(0, 113, 227, 0.46);
  --success: #197a32;
  --success-soft: rgba(25, 122, 50, 0.11);
  --warning: #8a4b00;
  --warning-soft: rgba(138, 75, 0, 0.11);
  --danger: #d70015;
  --danger-soft: rgba(215, 0, 21, 0.09);
  --info: #00667a;
  --info-soft: rgba(0, 102, 122, 0.1);
  --shadow-window: 0 18px 48px rgba(0, 0, 0, 0.09);
  --shadow-panel: 0 6px 20px rgba(0, 0, 0, 0.07);
  --shadow-popover: 0 18px 48px rgba(0, 0, 0, 0.18);
  --scrim: rgba(0, 0, 0, 0.38);
  --scrollbar-thumb: rgba(60, 60, 67, 0.35);
  --scrollbar-hover: rgba(60, 60, 67, 0.5);
  --page-gradient: radial-gradient(circle at 50% 20%, rgba(0, 113, 227, 0.08), transparent 34rem);
  --workflow-gradient: radial-gradient(circle at top left, rgba(0, 113, 227, 0.1), transparent 36%), linear-gradient(145deg, #ffffff, #f5f5f7);
  --tw-white: 29 29 31;
  --tw-black: 0 0 0;
  --tw-neutral-50: 29 29 31;
  --tw-neutral-100: 29 29 31;
  --tw-neutral-200: 44 44 46;
  --tw-neutral-300: 66 66 69;
  --tw-neutral-400: 66 66 69;
  --tw-neutral-500: 110 110 115;
  --tw-neutral-600: 125 125 130;
  --tw-neutral-700: 209 209 214;
  --tw-neutral-800: 229 229 234;
  --tw-neutral-900: 255 255 255;
  --tw-neutral-950: 245 245 247;
  --rgb-accent-text: 0 102 204;
  --rgb-accent-fill: 0 113 227;
  --rgb-accent-strong: 0 89 179;
  --rgb-success-text: 25 122 50;
  --rgb-success-fill: 29 137 58;
  --rgb-success-strong: 20 101 40;
  --rgb-danger-text: 215 0 21;
  --rgb-danger-fill: 215 0 21;
  --rgb-danger-strong: 174 0 17;
  --rgb-warning-text: 138 75 0;
  --rgb-warning-fill: 173 96 0;
  --rgb-warning-strong: 122 65 0;
  --rgb-info-text: 0 102 122;
  --rgb-info-fill: 0 136 160;
  --rgb-info-strong: 0 85 102;
  --rgb-violet-text: 93 62 168;
  --rgb-violet-fill: 111 76 190;
  --rgb-violet-strong: 78 48 145;
  --radius-window: 20px;
  --radius-panel: 14px;
  --ease-out: cubic-bezier(0.2, 0.8, 0.2, 1);
}

html[data-theme="dark"] {
  color-scheme: dark;
  --surface-base: #0d0d0f;
  --surface-sidebar: #161618;
  --surface-window: #1c1c1e;
  --surface-panel: #232326;
  --surface-panel-strong: #2c2c2e;
  --surface-inset: #141416;
  --surface-muted: #3a3a3c;
  --surface-hover: #303033;
  --surface-pressed: #3a3a3d;
  --surface-line: rgba(255, 255, 255, 0.085);
  --surface-line-strong: rgba(255, 255, 255, 0.15);
  --text-main: #f5f5f7;
  --text-secondary: #d1d1d6;
  --text-muted: #98989d;
  --text-faint: #7d7d84;
  --text-placeholder: #7d7d84;
  --text-on-accent: #ffffff;
  --accent-fill: #0a84ff;
  --accent-hover: #409cff;
  --accent-strong: #0071e3;
  --accent-text: #64b5ff;
  --accent-soft: rgba(10, 132, 255, 0.16);
  --accent-ring: rgba(10, 132, 255, 0.55);
  --success: #30d158;
  --success-soft: rgba(48, 209, 88, 0.13);
  --warning: #ff9f0a;
  --warning-soft: rgba(255, 159, 10, 0.14);
  --danger: #ff453a;
  --danger-soft: rgba(255, 69, 58, 0.13);
  --info: #64d2ff;
  --info-soft: rgba(100, 210, 255, 0.13);
  --shadow-window: 0 20px 58px rgba(0, 0, 0, 0.32);
  --shadow-panel: 0 8px 24px rgba(0, 0, 0, 0.22);
  --shadow-popover: 0 22px 60px rgba(0, 0, 0, 0.48);
  --scrim: rgba(0, 0, 0, 0.64);
  --scrollbar-thumb: rgba(142, 142, 147, 0.58);
  --scrollbar-hover: rgba(174, 174, 178, 0.76);
  --page-gradient: radial-gradient(circle at 50% 20%, rgba(10, 132, 255, 0.09), transparent 34rem);
  --workflow-gradient: radial-gradient(circle at top left, rgba(34, 211, 238, 0.13), transparent 34%), linear-gradient(135deg, #17181c, #0d0e11);
  --tw-white: 255 255 255;
  --tw-neutral-50: 245 245 247;
  --tw-neutral-100: 245 245 247;
  --tw-neutral-200: 229 229 234;
  --tw-neutral-300: 209 209 214;
  --tw-neutral-400: 152 152 157;
  --tw-neutral-500: 125 125 132;
  --tw-neutral-600: 99 99 106;
  --tw-neutral-700: 58 58 62;
  --tw-neutral-800: 36 36 40;
  --tw-neutral-900: 23 23 27;
  --tw-neutral-950: 13 14 17;
  --rgb-accent-text: 100 181 255;
  --rgb-accent-fill: 10 132 255;
  --rgb-accent-strong: 0 113 227;
  --rgb-success-text: 85 220 112;
  --rgb-success-fill: 48 209 88;
  --rgb-success-strong: 36 164 68;
  --rgb-danger-text: 255 105 97;
  --rgb-danger-fill: 255 69 58;
  --rgb-danger-strong: 205 45 39;
  --rgb-warning-text: 255 187 82;
  --rgb-warning-fill: 255 159 10;
  --rgb-warning-strong: 204 122 0;
  --rgb-info-text: 100 210 255;
  --rgb-info-fill: 50 173 230;
  --rgb-info-strong: 30 125 166;
  --rgb-violet-text: 191 143 255;
  --rgb-violet-fill: 175 82 222;
  --rgb-violet-strong: 139 60 180;
}
~~~

Add compatibility and accessibility rules:

~~~css
.workflow-hero-surface { background: var(--workflow-gradient); }

:is(
  .bg-blue-500, .bg-blue-600, .bg-blue-700,
  .bg-sky-500, .bg-sky-600,
  .bg-emerald-500, .bg-emerald-600, .bg-emerald-700,
  .bg-green-600, .bg-green-700,
  .bg-red-600, .bg-red-700,
  .bg-rose-500, .bg-rose-600,
  .bg-amber-500, .bg-amber-600,
  .bg-cyan-500, .bg-cyan-600, .bg-cyan-700,
  .bg-violet-600, .bg-purple-600, .bg-purple-700
).text-white {
  color: var(--text-on-accent) !important;
}

.bg-yellow-400.text-slate-950 { color: #1d1d1f !important; }

@media (forced-colors: active) {
  button, input, select, textarea, [role="radio"], [role="dialog"] {
    border: 1px solid CanvasText;
  }
  :focus-visible {
    outline: 2px solid Highlight !important;
    outline-offset: 2px;
  }
}
~~~

- [ ] **Step 4: Replace the three fixed dark gradients**

In BrazilPixPage.vue、IndiaUpiPage.vue、KakaoPayPage.vue replace only the arbitrary dark radial/linear Tailwind class with workflow-hero-surface。No API/script change。

- [ ] **Step 5: GREEN**

~~~powershell
npm.cmd --prefix web run test:theme
npm.cmd --prefix web run build
node web/scripts/test-payment-unknown-outcome.mjs
~~~

Expected: all exit 0。

- [ ] **Step 6: Commit**

~~~powershell
git add web/tailwind.config.js web/src/style.css web/src/components/BrazilPixPage.vue web/src/components/IndiaUpiPage.vue web/src/components/KakaoPayPage.vue web/scripts/theme-regression.mjs
git commit -m "feat(frontend): add semantic light and dark tokens"
~~~

---

### Task 5：Shared UI Primitives

**Files**

- Create: web/src/components/ui/UiPageHeader.vue
- Create: web/src/components/ui/UiSurface.vue
- Create: web/src/components/ui/UiButton.vue
- Create: web/src/components/ui/UiStatusBadge.vue
- Create: web/src/components/ui/UiFormField.vue
- Create: web/src/components/ui/UiSegmentedControl.vue
- Create: web/src/components/ui/UiStatePanel.vue
- Create: web/src/components/ui/UiSheet.vue
- Modify: web/src/style.css
- Modify: web/scripts/theme-regression.mjs

**Interfaces:** exactly the locked Phase 1 contracts；none imports api.js or owns business state。

- [ ] **Step 1: RED — append primitive contract assertions**

~~~js
const primitiveNames = [
  'UiPageHeader', 'UiSurface', 'UiButton', 'UiStatusBadge',
  'UiFormField', 'UiSegmentedControl', 'UiStatePanel', 'UiSheet',
]
for (const name of primitiveNames) {
  const source = readFileSync(
    new URL('../src/components/ui/' + name + '.vue', import.meta.url),
    'utf8',
  )
  assert.ok(source.length > 0, name + ' must exist')
}

const segmentedSource = readFileSync(
  new URL('../src/components/ui/UiSegmentedControl.vue', import.meta.url),
  'utf8',
)
assert.match(segmentedSource, /role="radiogroup"/)
assert.match(segmentedSource, /role="radio"/)
assert.match(segmentedSource, /aria-checked/)
assert.match(segmentedSource, /ArrowDown/)
assert.match(segmentedSource, /ArrowUp/)
assert.match(segmentedSource, /defineExpose\(\{\s*focusSelected\s*\}\)/)

const sheetSource = readFileSync(
  new URL('../src/components/ui/UiSheet.vue', import.meta.url),
  'utf8',
)
assert.match(sheetSource, /<Teleport to="body">/)
assert.match(sheetSource, /aria-modal="true"/)
assert.match(sheetSource, /trapFocus/)
assert.match(sheetSource, /restoreBackground/)
assert.match(sheetSource, /opener/)
assert.match(sheetSource, /@keydown\.esc/)
~~~

Run npm.cmd --prefix web run test:theme。

Expected: ENOENT for first primitive，exit 1。

- [ ] **Step 2: Implement UiSegmentedControl.vue**

~~~vue
<template>
  <div class="ui-segmented" role="radiogroup" :aria-label="ariaLabel" @keydown="handleKeydown">
    <button
      v-for="(option, index) in options"
      :key="option.value"
      :ref="element => setOptionRef(element, index)"
      type="button"
      class="ui-segmented-option"
      :class="{ 'ui-segmented-option-selected': option.value === modelValue }"
      role="radio"
      :aria-checked="option.value === modelValue"
      :tabindex="option.value === modelValue ? 0 : -1"
      @click="select(index)"
    >
      <span class="ui-segmented-copy">
        <strong>{{ option.label }}</strong>
        <small v-if="option.description">{{ option.description }}</small>
      </span>
      <span class="ui-segmented-check" :aria-hidden="option.value !== modelValue">✓</span>
    </button>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUpdate } from 'vue'

const props = defineProps({
  modelValue: { type: String, required: true },
  options: {
    type: Array,
    required: true,
    validator: value => value.every(option =>
      typeof option?.value === 'string' &&
      typeof option?.label === 'string'
    ),
  },
  ariaLabel: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])
let optionRefs = []

onBeforeUpdate(() => { optionRefs = [] })

function setOptionRef(element, index) {
  if (element) optionRefs[index] = element
}
function selectedIndex() {
  const index = props.options.findIndex(option => option.value === props.modelValue)
  return index >= 0 ? index : 0
}
async function select(index) {
  const option = props.options[index]
  if (!option) return
  emit('update:modelValue', option.value)
  await nextTick()
  optionRefs[index]?.focus()
}
function handleKeydown(event) {
  const last = props.options.length - 1
  let next = selectedIndex()
  if (event.key === 'ArrowDown' || event.key === 'ArrowRight') {
    next = next >= last ? 0 : next + 1
  } else if (event.key === 'ArrowUp' || event.key === 'ArrowLeft') {
    next = next <= 0 ? last : next - 1
  } else if (event.key === 'Home') {
    next = 0
  } else if (event.key === 'End') {
    next = last
  } else {
    return
  }
  event.preventDefault()
  void select(next)
}
function focusSelected() {
  optionRefs[selectedIndex()]?.focus()
}
defineExpose({ focusSelected })
</script>
~~~

- [ ] **Step 3: Implement UiSheet.vue**

~~~vue
<template>
  <Teleport to="body">
    <Transition name="ui-sheet">
      <div v-if="open" ref="layerRef" class="ui-sheet-layer" @click.self="requestClose">
        <section
          ref="sheetRef"
          class="ui-sheet"
          :class="'ui-sheet-' + side"
          role="dialog"
          aria-modal="true"
          :aria-label="labelledby ? undefined : label"
          :aria-labelledby="labelledby || undefined"
          tabindex="-1"
          @keydown.esc.stop="requestClose"
          @keydown.tab="trapFocus"
        >
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

const props = defineProps({
  open: { type: Boolean, default: false },
  label: { type: String, default: '' },
  labelledby: { type: String, default: '' },
  side: {
    type: String,
    default: 'bottom',
    validator: value => ['bottom', 'right'].includes(value),
  },
  initialFocusSelector: { type: String, default: '' },
})
const emit = defineEmits(['close', 'after-close'])
const layerRef = ref(null)
const sheetRef = ref(null)
const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
let opener = null
let inertState = []
let previousOverflow = null

function focusableElements() {
  return [...(sheetRef.value?.querySelectorAll(FOCUSABLE) || [])]
    .filter(element =>
      element.getClientRects().length > 0 &&
      element.getAttribute('aria-hidden') !== 'true'
    )
}
function restoreBackground() {
  for (const { element, inert } of inertState) {
    if (element?.isConnected) element.inert = inert
  }
  inertState = []
  if (previousOverflow !== null && typeof document !== 'undefined') {
    document.body.style.overflow = previousOverflow
    previousOverflow = null
  }
}
function setBackgroundInert() {
  restoreBackground()
  const layer = layerRef.value
  if (!layer || typeof document === 'undefined') return
  inertState = [...document.body.children]
    .filter(element => element !== layer && !element.contains(layer))
    .map(element => ({ element, inert: Boolean(element.inert) }))
  for (const { element } of inertState) element.inert = true
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
}
function focusInitial() {
  const explicit = props.initialFocusSelector
    ? sheetRef.value?.querySelector(props.initialFocusSelector)
    : null
  ;(explicit || focusableElements()[0] || sheetRef.value)?.focus()
}
function trapFocus(event) {
  const focusable = focusableElements()
  if (!focusable.length) {
    event.preventDefault()
    sheetRef.value?.focus()
    return
  }
  const first = focusable[0]
  const last = focusable.at(-1)
  const current = document.activeElement
  const outside = current === sheetRef.value || !sheetRef.value?.contains(current)
  if (event.shiftKey && (outside || current === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (outside || current === last)) {
    event.preventDefault()
    first.focus()
  }
}
function requestClose() { emit('close') }

watch(
  () => props.open,
  async open => {
    if (open) {
      opener = typeof document === 'undefined' ? null : document.activeElement
      await nextTick()
      setBackgroundInert()
      focusInitial()
      return
    }
    restoreBackground()
    await nextTick()
    if (opener?.isConnected && typeof opener.focus === 'function') opener.focus()
    opener = null
    emit('after-close')
  },
  { immediate: true },
)
onBeforeUnmount(restoreBackground)
</script>
~~~

- [ ] **Step 4: Implement remaining six components**

Implement exact locked runtime prop validators, emits, and slots. UiFormField computes stable help/error describedBy IDs and passes them through its scoped slot. UiButton sets disabled when loading and exposes aria-busy. UiStatePanel uses role=alert for error and role=status otherwise. No component imports business modules.

- [ ] **Step 5: Add primitive CSS**

~~~css
.ui-button,
.ui-segmented-option,
.ui-sheet button { min-height: 44px; }

.ui-sheet-layer {
  position: fixed;
  z-index: 80;
  inset: 0;
  display: flex;
  align-items: flex-end;
  background: var(--scrim);
}
.ui-sheet {
  display: grid;
  width: 100%;
  max-height: 92dvh;
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
  border: 1px solid var(--surface-line-strong);
  background: var(--surface-window);
  box-shadow: var(--shadow-popover);
}
.ui-sheet-bottom { border-radius: 22px 22px 0 0; }
.ui-sheet-right {
  width: min(420px, 100%);
  height: 100%;
  max-height: none;
  margin-left: auto;
}
.ui-sheet-body { overflow: auto; overscroll-behavior: contain; }
.ui-sheet-enter-active,
.ui-sheet-leave-active { transition: opacity 180ms ease; }
.ui-sheet-enter-active .ui-sheet,
.ui-sheet-leave-active .ui-sheet {
  transition: transform 220ms var(--ease-out);
}
.ui-sheet-enter-from,
.ui-sheet-leave-to { opacity: 0; }
.ui-sheet-enter-from .ui-sheet-bottom,
.ui-sheet-leave-to .ui-sheet-bottom { transform: translate3d(0, 28px, 0); }
.ui-sheet-enter-from .ui-sheet-right,
.ui-sheet-leave-to .ui-sheet-right { transform: translate3d(28px, 0, 0); }
~~~

- [ ] **Step 6: GREEN**

~~~powershell
npm.cmd --prefix web run test:theme
npm.cmd --prefix web run build
~~~

Expected: both exit 0。

- [ ] **Step 7: Commit**

~~~powershell
git add web/src/components/ui web/src/style.css web/scripts/theme-regression.mjs
git commit -m "feat(frontend): establish semantic UI primitives"
~~~

---

### Task 6：Accessible Theme Switcher

**Files**

- Create: web/src/components/ThemeSwitcher.vue
- Modify: web/src/style.css
- Modify: web/scripts/theme-regression.mjs

**Consumes:** injected controller, UiSegmentedControl, UiSheet。

- [ ] **Step 1: RED — append switcher source contract**

~~~js
const switcherSource = readFileSync(
  new URL('../src/components/ThemeSwitcher.vue', import.meta.url),
  'utf8',
)
assert.match(switcherSource, /inject\(THEME_CONTROLLER_KEY/)
assert.match(switcherSource, /UiSegmentedControl/)
assert.match(switcherSource, /UiSheet/)
assert.match(switcherSource, /aria-haspopup="dialog"/)
assert.match(switcherSource, /aria-expanded/)
assert.match(switcherSource, /@keydown\.down/)
assert.match(switcherSource, /pointerdown/)
assert.match(switcherSource, /Escape/)
assert.match(switcherSource, /triggerRef\.value\?\.focus/)
assert.match(switcherSource, /跟随系统/)
assert.match(switcherSource, /明亮/)
assert.match(switcherSource, /深色/)
assert.match(styleSource, /\.theme-switcher-trigger\s*\{[^}]*min-height:\s*44px/is)
~~~

Run npm.cmd --prefix web run test:theme。

Expected: ENOENT for ThemeSwitcher.vue，exit 1。

- [ ] **Step 2: Implement exact option model and interactions**

~~~js
const options = Object.freeze([
  { value: 'system', label: '跟随系统', description: '自动匹配设备外观', icon: '◐' },
  { value: 'light', label: '明亮', description: '浅色画布与白色内容层', icon: '☀' },
  { value: 'dark', label: '深色', description: '低亮度深色工作区', icon: '☾' },
])
~~~

Requirements:

- inject one provided controller；only create/dispose owned fallback outside provider；
- subscribe once and unsubscribe on unmount；
- matchMedia('(max-width: 639px)') only chooses popover versus sheet；
- attach document pointerdown only while desktop popover is open；
- compact trigger aria-label example: 外观：跟随系统，当前明亮；
- Enter/Space/ArrowDown open；radio arrows stay within selector；
- Escape/outside closes and triggerRef.value?.focus() restores focus；
- icon + label + selected check, not color alone；
- .theme-switcher-trigger min-width/min-height 44px；
- mode=group renders UiSegmentedControl without a second state store；
- no API import and no page DOM traversal。

- [ ] **Step 3: GREEN**

~~~powershell
npm.cmd --prefix web run test:theme
npm.cmd --prefix web run build
~~~

Expected: both exit 0。

- [ ] **Step 4: Commit**

~~~powershell
git add web/src/components/ThemeSwitcher.vue web/src/style.css web/scripts/theme-regression.mjs
git commit -m "feat(frontend): add accessible appearance switcher"
~~~

---

### Task 7：Redesign Shell, Login, Setup, Navigation, Modal and Task States

**Files**

- Modify: web/src/App.vue
- Modify: web/src/components/Sidebar.vue
- Modify: web/src/components/SetupPage.vue
- Modify: web/src/components/AccessibleModal.vue
- Modify: web/src/components/TaskPanel.vue
- Modify: web/src/components/PageLoading.vue
- Modify: web/src/components/PageLoadError.vue
- Modify: web/src/components/Settings.vue
- Modify: web/src/style.css
- Modify: web/scripts/theme-regression.mjs

**Constraints:** no API/event/polling/storage method changes；Settings consumes mode=group；Sidebar Task 1 accessibility remains intact。

- [ ] **Step 1: RED — append shell integration assertions**

~~~js
const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const setupSource = readFileSync(
  new URL('../src/components/SetupPage.vue', import.meta.url),
  'utf8',
)
const settingsSource = readFileSync(
  new URL('../src/components/Settings.vue', import.meta.url),
  'utf8',
)
assert.equal(
  (appSource.match(/<ThemeSwitcher\b/g) || []).length,
  2,
  'login and authenticated title bar each need a switcher',
)
assert.match(setupSource, /<ThemeSwitcher\b/)
assert.match(settingsSource, /<ThemeSwitcher\s+mode="group"/)
assert.match(appSource, /class="auth-theme-control"/)
assert.match(appSource, /class="workspace-toolbar-actions"[\s\S]*?<ThemeSwitcher/)
assert.match(setupSource, /class="setup-theme-control"/)
assert.match(settingsSource, /外观/)
~~~

Run npm.cmd --prefix web run test:theme。

Expected: missing App switchers，exit 1。

- [ ] **Step 2: Integrate App login and title bar**

Add:

~~~js
import ThemeSwitcher from './components/ThemeSwitcher.vue'
~~~

Login opening:

~~~vue
<main v-else-if="!authenticated" class="auth-shell">
  <div class="auth-theme-control">
    <ThemeSwitcher />
  </div>
  <section class="auth-card" aria-labelledby="auth-title">
    <div class="auth-brand">
      <div class="nav-mark" aria-hidden="true"><span>A</span></div>
      <div>
        <p class="workspace-eyebrow">Operations Console</p>
        <h1 id="auth-title" class="auth-title">AutoToken</h1>
        <p class="auth-copy">安全进入你的运营工作区</p>
      </div>
    </div>
~~~

Keep Task 1 authError || startupError alert and reconnect behavior. Insert ThemeSwitcher first in workspace-toolbar-actions。

Do not rename/reorder/rewrite resetSessionState、advanceAuthEpoch、checkAuth、doLogin、doLogout、initializeApp、onSetupDone、handleExternalStorageChange or refresh/polling functions。

- [ ] **Step 3: Redesign Setup while preserving its script**

Add:

~~~js
import ThemeSwitcher from './ThemeSwitcher.vue'
import UiButton from './ui/UiButton.vue'
import UiFormField from './ui/UiFormField.vue'
~~~

Use this composition and preserve existing v-models/save():

~~~vue
<div class="setup-shell">
  <div class="setup-theme-control"><ThemeSwitcher /></div>
  <section class="setup-card" aria-labelledby="setup-title">
    <header class="setup-heading">
      <span class="workspace-eyebrow">首次运行</span>
      <h1 id="setup-title">配置 AutoToken</h1>
      <p>连接邮箱服务并创建控制台访问凭证。</p>
    </header>

    <div
      v-if="message"
      class="setup-message"
      :class="messageClass"
      :role="messageRole"
      aria-live="polite"
    >{{ message }}</div>

    <div class="setup-form">
      <UiFormField
        id="setup-mail-provider"
        label="Mail Provider"
        help="选择注册流程使用的邮箱供应商。"
        required
      >
        <template #default="{ inputId, describedBy }">
          <select
            :id="inputId"
            v-model="provider"
            :aria-describedby="describedBy"
            required
          >
            <option
              v-for="option in providerOptions"
              :key="option.value"
              :value="option.value"
            >{{ option.label }}（{{ option.description }}）</option>
          </select>
        </template>
      </UiFormField>

      <section v-if="providerFieldTitle" class="setup-field-group">
        <h2>{{ providerFieldTitle }}</h2>
        <UiFormField
          v-for="field in providerFields"
          :id="fieldInputId(field)"
          :key="field.key"
          :label="field.prompt"
          :required="!field.optional"
        >
          <template #default="{ inputId, describedBy }">
            <input
              :id="inputId"
              v-model="form[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              :required="!field.optional"
              :aria-describedby="describedBy"
            />
          </template>
        </UiFormField>
      </section>

      <section class="setup-field-group">
        <h2>通用配置</h2>
        <UiFormField
          v-for="field in commonFields"
          :id="fieldInputId(field)"
          :key="field.key"
          :label="field.prompt"
          :help="field.key === 'API_KEY' ? '留空时自动生成。' : ''"
          :required="!field.optional"
        >
          <template #default="{ inputId, describedBy }">
            <input
              :id="inputId"
              v-model="form[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              :required="!field.optional"
              :aria-describedby="describedBy"
            />
          </template>
        </UiFormField>
      </section>
    </div>

    <UiButton
      class="setup-submit"
      variant="primary"
      :disabled="saving || configured"
      :loading="saving"
      @click="save"
    >{{ configured ? '配置已保存' : '保存配置' }}</UiButton>
  </section>
</div>
~~~

- [ ] **Step 4: Preserve and retheme Sidebar**

Keep Teleport to body、trapMobileMenuFocus、background inert restoration、desktop breakpoint listener、focus return、safe close. Only migrate surface/color rules: desktop active nav uses accent-soft/accent-text；mobile dock/sheet use surface-window；scrim uses scrim token。

- [ ] **Step 5: Retheme modal and task panels**

AccessibleModal root class:

~~~vue
class="accessible-modal-layer fixed inset-0 z-50 flex justify-center p-4"
~~~

CSS:

~~~css
.accessible-modal-layer { background: var(--scrim); }
~~~

Keep focus trap、inert、scroll lock、opener restoration unchanged。

App floating task panel keeps pointer-capture drag、saved transform、clamping and task-progress-fill scaleX；only surface/warning/shadow presentation changes。

TaskPanel.vue keeps every watcher/API method；outer wrapper becomes operation-panel ui-surface ui-surface-panel。

- [ ] **Step 6: Convert PageLoading and PageLoadError**

web/src/components/PageLoading.vue:

~~~vue
<template>
  <UiStatePanel
    state="loading"
    title="正在打开工作区"
    message="首次打开时按需加载，不阻塞其他操作。"
  />
</template>
<script setup>
import UiStatePanel from './ui/UiStatePanel.vue'
</script>
~~~

web/src/components/PageLoadError.vue:

~~~vue
<template>
  <UiStatePanel
    state="error"
    title="页面加载失败"
    :message="error?.message || '请检查网络后重新加载。'"
    action-label="重新加载"
    @action="emit('retry')"
  />
</template>
<script setup>
import UiStatePanel from './ui/UiStatePanel.vue'
defineProps({ error: { type: Error, default: null } })
const emit = defineEmits(['retry'])
</script>
~~~

Retain App.vue in-place async component retry wiring。

- [ ] **Step 7: Add Settings appearance group**

At the beginning of Settings.vue content:

~~~vue
<section class="settings-appearance" aria-labelledby="settings-appearance-title">
  <div>
    <span class="workspace-eyebrow">个性化</span>
    <h2 id="settings-appearance-title">外观</h2>
    <p>跟随设备，或为当前浏览器固定明亮/深色模式。</p>
  </div>
  <ThemeSwitcher mode="group" />
</section>
~~~

Add:

~~~js
import ThemeSwitcher from './ThemeSwitcher.vue'
~~~

No API call and no duplicate theme state。

- [ ] **Step 8: GREEN — focused gates**

~~~powershell
npm.cmd --prefix web run test:theme
node web/scripts/test-frontend-shell.mjs
node web/scripts/test-setup-page.mjs
node web/scripts/test-task-panel-single-flight.mjs
node web/scripts/test-auth-session-isolation.mjs
node web/scripts/test-storage-session-isolation.mjs
node web/scripts/test-storage-unavailable.mjs
~~~

Expected: every command exits 0。

- [ ] **Step 9: GREEN — full Phase 1 suite**

~~~powershell
npm.cmd --prefix web run test:frontend
~~~

Expected tail:

~~~text
theme controller regression tests passed
all frontend scripts passed: 44/44
exit status 0
~~~

- [ ] **Step 10: Commit**

~~~powershell
git add web/src/App.vue web/src/components/Sidebar.vue web/src/components/SetupPage.vue web/src/components/AccessibleModal.vue web/src/components/TaskPanel.vue web/src/components/PageLoading.vue web/src/components/PageLoadError.vue web/src/components/Settings.vue web/src/style.css web/scripts/theme-regression.mjs
git commit -m "feat(frontend): redesign the adaptive application shell"
~~~

---

### Task 8：Phase 1 Performance and Browser Checkpoint

**Files:** no tracked source changes expected。

- [ ] **Step 1: Run build, regressions, bundle and account gates**

~~~powershell
npm.cmd --prefix web run test:frontend
npm.cmd --prefix web run test:frontend-bundle
npm.cmd --prefix web run test:account-loading
~~~

Expected:

~~~text
all frontend scripts passed: 44/44
frontend bundle budget passed:
account loading performance tests passed: rows=20000
~~~

The bundle line must match `^frontend bundle budget passed: entry=([0-9]+) bytes chunks=([0-9]+)$`; its parsed entry value is at most 256000 and parsed chunk value is at least 8. The account-loading output starts with the shown literal prefix. All exit statuses are 0。

- [ ] **Step 2: Start 20,000-row fixture**

~~~powershell
node web/scripts/dashboard-browser-fixture-server.mjs 8799 20000
~~~

Expected:

~~~text
fixture_ready url=http://127.0.0.1:8799/ rows=20000 payload_bytes=
~~~

The output starts with the shown literal prefix followed by a decimal payload byte count greater than zero.

- [ ] **Step 3: Run repeated-theme browser measurement**

~~~js
(async () => {
  const root = document.documentElement
  const mutations = []
  const resourcesBefore = performance.getEntriesByType('resource').length
  const observer = new MutationObserver(records => mutations.push(...records))
  observer.observe(document.documentElement, {
    subtree: true,
    attributes: true,
  })

  const samples = []
  for (let index = 0; index < 10; index += 1) {
    const startedAt = performance.now()
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'autotoken_theme',
      newValue: index % 2 === 0 ? 'light' : 'dark',
    }))
    await new Promise(resolve =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))
    )
    samples.push(performance.now() - startedAt)
  }

  observer.disconnect()
  const sorted = [...samples].sort((a, b) => a - b)
  const p95 = sorted[Math.ceil(sorted.length * 0.95) - 1]
  const nonRootMutations = mutations.filter(record =>
    record.target !== root &&
    record.target?.matches?.('meta[name="theme-color"]') !== true
  )

  return {
    p95,
    samples,
    nonRootMutationCount: nonRootMutations.length,
    extraResourceCount:
      performance.getEntriesByType('resource').length - resourcesBefore,
    theme: root.dataset.theme,
  }
})()
~~~

Required:

~~~text
p95 <= 100
nonRootMutationCount = 0
extraResourceCount = 0
~~~

- [ ] **Step 4: Browser smoke matrix**

- 1440×1000：workspace title bar、sidebar、login、Settings group。
- 390×844：mobile dock、navigation sheet、ThemeSwitcher sheet。
- 1024×620：Setup scroll、modal、task panel。
- explicit light、explicit dark、system-light、system-dark。
- Escape、Tab loop、arrow radios、outside-click、focus return。
- no console error、no horizontal overflow。

- [ ] **Step 5: Confirm checkpoint**

~~~powershell
git diff --check
git status --short
~~~

Expected: no diff errors；tracked worktree clean。

### Phase 1 commit boundaries

1. fix(frontend): restore runtime regression guarantees
2. feat(frontend): add resilient theme controller
3. feat(frontend): resolve appearance before first paint
4. feat(frontend): add semantic light and dark tokens
5. feat(frontend): establish semantic UI primitives
6. feat(frontend): add accessible appearance switcher
7. feat(frontend): redesign the adaptive application shell

## Phase 2：运营数据工作台

本阶段在 Phase 1 已交付的三态主题、语义 token、应用壳层和基础 UI 原语之上，重构 Dashboard、邮箱、任务历史、日志和 Team 页面。所有业务 API、轮询、缓存、选择与批处理语义保持不变；大型列表继续执行有界渲染。

### Phase 2 全局约束

- 消费 Phase 1 的 `UiPageHeader.vue`、`UiSurface.vue`、`UiButton.vue`、`UiStatusBadge.vue`、`UiFormField.vue`、`UiSegmentedControl.vue`、`UiStatePanel.vue` 和 `UiSheet.vue`，不复制 modal、sheet、按钮或状态样式。
- 新建回归脚本必须使用 Git 未忽略的 `web/scripts/operations-*-regression.mjs` 命名；Phase 1 扩展后的 `run-frontend-tests.mjs` 必须发现 `*-regression.mjs`。
- 结构 surface、分隔线和正文不得继续直接依赖 `bg-gray-950/900/800`、`border-gray-*`、`text-white`；强调按钮的白字由 `UiButton` 的 on-accent token 提供。
- 页面改造不得删除 Dashboard 20,000 账号索引、50/100/200 分页、`v-memo`、延迟搜索、选择索引、single-flight、request generation、取消或可见性保护。
- MailAccounts 必须保持导入 20,000、auth-session 1,000、批处理 2,000、默认页 100、最大页 500 的现有契约。
- 任务历史默认只挂载 50 行；日志继续硬限制为 1,000 行。
- 桌面、移动和短屏只允许渲染一份筛选或批量操作 slot；不得用 CSS 隐藏两套同时存活的表单 DOM。
- 每个任务先写 RED 回归、观察指定失败，再写最小实现、运行 GREEN 和既有保护测试，最后独立提交。

---

### Task 9：建立数据工作台原语与状态语义

**Files:**

- Create: `web/src/useMediaQuery.js`
- Create: `web/src/operationsPresentation.js`
- Create: `web/src/components/ui/UiMetricSummary.vue`
- Create: `web/src/components/ui/UiDataToolbar.vue`
- Create: `web/src/components/ui/UiBatchBar.vue`
- Create: `web/src/components/ui/UiPagination.vue`
- Create: `web/src/components/ui/UiTableFrame.vue`
- Create: `web/scripts/operations-primitives-regression.mjs`
- Modify: `web/src/style.css`
- Modify: `web/package.json`

**Interfaces:**

- Consumes: `UiSurface`, `UiButton`, `UiSheet` and semantic token classes from Phase 1.
- Produces: `useMediaQuery(query: string): Readonly<Ref<boolean>>`; it registers the `MediaQueryList` change listener on mount and removes it on unmount.
- Produces: `UiMetricSummary` props `items: Array<{key: string, label: string, value: string|number, tone?: 'neutral'|'info'|'success'|'warning'|'danger', detail?: string}> = []`, `label: String = '关键指标'`, `compact: Boolean = false`; slot `empty`.
- Produces: `UiDataToolbar` props `resultLabel: String = ''`, `activeFilterCount: Number = 0`, `filtersLabel: String = '筛选'`, `clearable: Boolean = false`; emit `clear-filters`; slots `primary`, `filters`, `actions`.
- Produces: `UiBatchBar` props `count: Number` required, `label: String = '已选择'`, `itemLabel: String = '项'`, `busy: Boolean = false`; emit `clear`; default slot.
- Produces: `UiPagination` props `page: Number` required, `pageSize: Number` required, `pageSizes: Array<Number> = []`, `totalItems: Number` required, `itemLabel: String = '条记录'`; emits `update:page`, `update:pageSize`.
- Produces: `UiTableFrame` props `label: String` required, `busy: Boolean = false`, `empty: Boolean = false`, `minWidth: String = '0'`; slots `header`, `default`, `empty`, `footer`.
- Produces: the following functions, each returning `{ label: string, tone: 'neutral'|'info'|'success'|'warning'|'danger' }`:

```js
accountStatusPresentation(value)
accountTypePresentation(value)
bindProviderPresentation(value)
mailAccountStatusPresentation(value)
mailCheckStatusPresentation(value)
taskStatusPresentation(value)
teamRolePresentation(value)
teamMemberTypePresentation(value)
oauthPhoneStatusPresentation(value)
oauthPhoneRecordStatusPresentation(value)
```

- [ ] **Step 1: Write the primitive RED contract**

Create `web/scripts/operations-primitives-regression.mjs` with existence checks, pure mapping assertions and source contracts:

```js
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const src = path.resolve(here, '../src')
const ui = path.join(src, 'components/ui')
const required = [
  'UiMetricSummary.vue',
  'UiDataToolbar.vue',
  'UiBatchBar.vue',
  'UiPagination.vue',
  'UiTableFrame.vue',
]
for (const name of required) assert.ok(existsSync(path.join(ui, name)), `${name} should exist`)

const presentationPath = path.join(src, 'operationsPresentation.js')
assert.ok(existsSync(presentationPath), 'operationsPresentation.js should exist')
const presentation = await import(pathToFileURL(presentationPath))
assert.deepEqual(presentation.taskStatusPresentation('running'), { label: '执行中', tone: 'warning' })
assert.deepEqual(presentation.taskStatusPresentation('completed'), { label: '已完成', tone: 'success' })
assert.deepEqual(presentation.mailCheckStatusPresentation('invalid'), { label: '失效', tone: 'danger' })
assert.deepEqual(presentation.oauthPhoneStatusPresentation('available'), { label: '可用', tone: 'success' })
assert.deepEqual(presentation.teamMemberTypePresentation('invite'), { label: '待接受', tone: 'warning' })
assert.equal(presentation.accountStatusPresentation('unknown').tone, 'neutral')

const toolbar = readFileSync(path.join(ui, 'UiDataToolbar.vue'), 'utf8')
const batch = readFileSync(path.join(ui, 'UiBatchBar.vue'), 'utf8')
const pagination = readFileSync(path.join(ui, 'UiPagination.vue'), 'utf8')
const table = readFileSync(path.join(ui, 'UiTableFrame.vue'), 'utf8')
const media = readFileSync(path.join(src, 'useMediaQuery.js'), 'utf8')
const css = readFileSync(path.join(src, 'style.css'), 'utf8')
assert.match(toolbar, /UiSheet/)
assert.match(toolbar, /useMediaQuery/)
assert.match(batch, /UiSheet/)
assert.match(batch, /useMediaQuery/)
assert.match(media, /addEventListener\(['"]change['"]/)
assert.match(media, /removeEventListener\(['"]change['"]/)
assert.match(pagination, /update:page/)
assert.match(pagination, /update:pageSize/)
assert.match(table, /role="region"/)
assert.match(table, /aria-busy/)
assert.doesNotMatch(css, /transition:\s*all/)
console.log('operations primitive contracts passed')
```

- [ ] **Step 2: Run RED and verify the missing-file failure**

Run:

```powershell
node web/scripts/operations-primitives-regression.mjs
```

Expected: exit `1` with `UiMetricSummary.vue should exist` or the first missing primitive.

- [ ] **Step 3: Implement `useMediaQuery` and presentation mappings**

Implement `useMediaQuery` with `ref`, `readonly`, `onMounted`, `onUnmounted`, legacy `addListener/removeListener` fallback, and no module-load access to `window`.

Map states as follows:

```text
task: pending→neutral, running→warning, completed→success, failed→danger, cancelled→neutral
account: active/session_only→success, standby/orphan→warning, exhausted/auth_invalid/auth_revoked/fail→danger, pending/stashed→neutral
mail status: enabled→success, disabled→neutral
mail check: valid→success, invalid/error→danger, unchecked→neutral
OAuth phone: available→success, full→info, cooldown→warning, invalid→danger, disabled→neutral
OAuth record: success*→success, acquired→info, cancelled/released→warning, failed/invalid/cooldown→danger
Team member type: member→success, invite→warning
```

- [ ] **Step 4: Implement the five Vue primitives**

Use runtime `defineProps` validators. `UiDataToolbar` and `UiBatchBar` must conditionally render either their desktop content or their mobile `UiSheet`, based on `useMediaQuery('(max-width: 767px)')`; never mount both copies. When the media query leaves mobile, close the sheet. `UiPagination` clamps every emitted page to `1..Math.max(1, Math.ceil(totalItems / pageSize))`.

- [ ] **Step 5: Add semantic component CSS and the focused npm gate**

Add component classes using only Phase 1 tokens. Add this package script, preserving all existing scripts:

```json
"test:operations-workspaces": "node scripts/operations-primitives-regression.mjs && node scripts/operations-dashboard-regression.mjs && node scripts/operations-mail-regression.mjs && node scripts/operations-history-regression.mjs && node scripts/operations-team-regression.mjs && node scripts/operations-browser-fixture-regression.mjs"
```

Later scripts do not exist yet, so do not run the aggregate gate in this task.

- [ ] **Step 6: Run GREEN and build**

Run:

```powershell
node web/scripts/operations-primitives-regression.mjs
npm.cmd --prefix web run build
```

Expected:

```text
operations primitive contracts passed
```

Both commands exit `0`.

- [ ] **Step 7: Commit the primitives**

```bash
git add web/src/useMediaQuery.js web/src/operationsPresentation.js web/src/components/ui/UiMetricSummary.vue web/src/components/ui/UiDataToolbar.vue web/src/components/ui/UiBatchBar.vue web/src/components/ui/UiPagination.vue web/src/components/ui/UiTableFrame.vue web/src/style.css web/scripts/operations-primitives-regression.mjs web/package.json
git commit -m "feat(frontend): add operations workspace primitives"
```

---

### Task 10：深度重设计 Dashboard 账号运营工作台

**Files:**

- Modify: `web/src/components/Dashboard.vue`
- Modify: `web/src/style.css`
- Create: `web/scripts/operations-dashboard-regression.mjs`
- Modify: `web/package.json`

**Interfaces:**

- Consumes: all Phase 2.1 primitives plus Phase 1 `UiPageHeader`, `UiSegmentedControl`, `UiStatusBadge`, `UiStatePanel`, `UiButton`, `UiSurface`, `AccessibleModal`.
- Preserves: Dashboard props `status`, `loading`, `accountsError`, `lastSuccessfulAt`, `runningTask`, `refreshQuotaResultTask`, `adminStatus`.
- Preserves: emits `refresh`, `task-started`, `retry-accounts`.
- Preserves: `paginatedAccounts`, `accountPage`, `accountPageSize`, `selectedSet`, `deferredEmailFilter`, `accountActionMenuAccount` and all existing API method calls.

- [ ] **Step 1: Write the Dashboard RED contract**

Create `web/scripts/operations-dashboard-regression.mjs`:

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/Dashboard.vue', import.meta.url), 'utf8')
const template = source.split('<script setup>')[0]
for (const tag of [
  'UiPageHeader', 'UiMetricSummary', 'UiDataToolbar', 'UiBatchBar',
  'UiTableFrame', 'UiPagination', 'UiStatusBadge', 'UiStatePanel',
]) assert.match(source, new RegExp(`<${tag}\\b`), `Dashboard should use ${tag}`)

assert.match(source, /<UiSegmentedControl\b/)
assert.match(source, /v-for="\(acc, i\) in paginatedAccounts"/)
assert.match(source, /v-memo=/)
assert.match(source, /buildAccountSearchIndex\(allAccounts\.value\)/)
assert.match(source, /buildAccountSelectionIndex\(filteredAccounts\.value\)/)
assert.match(source, /selectAccountsFromIndex\(accountSelectionIndex\.value, selectedSet\.value\)/)
assert.match(source, /state="partial"/)
assert.match(source, /@action="retryAccounts"|@action="emit\('retry-accounts'\)"/)
assert.doesNotMatch(template, /\b(?:bg|border)-(?:gray|slate)-(?:950|900|800)\b/)
assert.doesNotMatch(template, /transition-all/)

const row = source.match(/<tr v-for="\(acc, i\) in paginatedAccounts"[\s\S]*?<\/tr>/)?.[0] || ''
assert.ok(row, 'the bounded account row should remain discoverable')
assert.ok((row.match(/<button\b/g) || []).length <= 1, 'each account row should retain one action trigger')
console.log('operations dashboard UI contracts passed')
```

- [ ] **Step 2: Run RED and verify semantic components are absent**

```powershell
node web/scripts/operations-dashboard-regression.mjs
```

Expected: exit `1`, first failure `Dashboard should use UiPageHeader`.

- [ ] **Step 3: Recompose the Dashboard header, tabs and metrics**

Use `UiPageHeader` with title `账号运营`, description `筛选账号、批量授权、刷新额度并维护认证状态`, and header actions for the single dominant `导入账号` action plus quiet `刷新`. Replace `dashboardTabs` buttons with `UiSegmentedControl`. Change `cards` entries from `{ color }` to `{ key, label, value, tone }` and render through `UiMetricSummary`.

- [ ] **Step 4: Move filters into the responsive data toolbar**

Keep email, status and account type in slot `primary`. Put trial, bind provider, registration/export/bind time ranges, credential export, Account Hub and auth credential filters in slot `filters`. Pass the existing filtered/pool/selected counts through `resultLabel`; emit `clear-filters` to existing `clearFilters`.

- [ ] **Step 5: Separate scoped actions from selection actions**

Keep import/export/refresh/OAuth configuration as header or toolbar intents. Render selection-only operations in `UiBatchBar` with `:count="selectedEmails.length"` and `@clear="clearSelection"`. Preserve the current rule that an empty selection applies export and supported actions to `filteredAccounts`, while an explicit selection uses `selectedAccounts`.

- [ ] **Step 6: Migrate the table, badges and pagination**

Wrap the existing bounded table in `UiTableFrame`; keep `v-for="(acc, i) in paginatedAccounts"`, stable email keys and `v-memo`. Replace status/type/provider/export/sync pill class maps with `operationsPresentation.js` plus `UiStatusBadge`. Bind `UiPagination` with `v-model:page="accountPage"`, `v-model:page-size="accountPageSize"`, `:page-sizes="[50, 100, 200]"` and `:total-items="accountFilteredTotal"`.

- [ ] **Step 7: Standardize partial, loading, empty and error states**

Render stale data with `UiStatePanel state="partial"`; render first load with `state="loading"`; render first failure with `state="error" action-label="重新加载账号"`; keep the existing snapshot visible on refresh failure. Replace hand-rolled fixed overlays with `AccessibleModal` without moving request state or API calls into shared components.

- [ ] **Step 8: Run focused GREEN and existing performance/lifecycle gates**

```powershell
node web/scripts/operations-dashboard-regression.mjs
node web/scripts/test-dashboard-account-load-state.mjs
node web/scripts/test-dashboard-message-lifecycle.mjs
node web/scripts/test-account-loading-lifecycle.mjs
node web/scripts/test-account-loading-performance.mjs
npm.cmd --prefix web run build
```

Expected focused output:

```text
operations dashboard UI contracts passed
dashboard account load state tests passed
dashboard message lifecycle passed
account loading lifecycle tests passed
```

The performance script must exit `0` and continue reporting a 50-row first page and 20,000-account filter p95 below 100 ms.

- [ ] **Step 9: Commit the Dashboard redesign**

```bash
git add web/src/components/Dashboard.vue web/src/style.css web/scripts/operations-dashboard-regression.mjs web/package.json
git commit -m "refactor(frontend): redesign account operations workspace"
```

---

### Task 11：重构 MailAccounts 数据工作台

**Files:**

- Modify: `web/src/components/MailAccountsPage.vue`
- Modify: `web/src/style.css`
- Create: `web/scripts/operations-mail-regression.mjs`
- Modify: `web/package.json`

**Interfaces:**

- Consumes: `UiPageHeader`, `UiMetricSummary`, `UiDataToolbar`, `UiBatchBar`, `UiTableFrame`, `UiPagination`, `UiStatusBadge`, `UiStatePanel`, `UiButton`, `UiFormField`, `AccessibleModal`.
- Preserves: emit `task-started`.
- Preserves: `MAIL_AUTH_SESSION_BATCH_MAX_ITEMS = 1000`, `MAIL_ACCOUNT_BATCH_MAX_ITEMS = 2000`, `DEFAULT_MAIL_PAGE_SIZE = 100`, `MAIL_PAGE_SIZE_OPTIONS = [50, 100, 200, 500]`.
- Preserves: `planMailAuthSessionLogin`, `mailAccountBatchLimitError`, `formatMailImportOutcome`, `ensureMailAccountBatchWithinLimit`, `pagedRows`, `pagedFetchedRows`, `pagedPasswordResults`.

- [ ] **Step 1: Write the MailAccounts RED contract**

Create `web/scripts/operations-mail-regression.mjs`:

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/MailAccountsPage.vue', import.meta.url), 'utf8')
const template = source.split('<script setup>')[0]
for (const tag of [
  'UiPageHeader', 'UiMetricSummary', 'UiDataToolbar', 'UiBatchBar',
  'UiTableFrame', 'UiPagination', 'UiStatusBadge', 'UiStatePanel', 'AccessibleModal',
]) assert.match(source, new RegExp(`<${tag}\\b`), `MailAccounts should use ${tag}`)

assert.match(source, /createMessageClearScheduler/)
assert.match(source, /onBeforeUnmount\([\s\S]*messageClearScheduler\.dispose/)
assert.match(source, /const hasLoaded = ref\(false\)/)
assert.match(source, /const loadError = ref\(['"]['"]\)/)
assert.match(source, /v-for="\(row, index\) in pagedRows"/)
assert.match(source, /v-for="entry in pagedFetchedRows"/)
assert.match(source, /v-for="item in pagedPasswordResults"/)
assert.doesNotMatch(template, /\b(?:bg|border)-(?:gray|slate)-(?:950|900|800)\b/)

const row = source.match(/<tr v-for="\(row, index\) in pagedRows"[\s\S]*?<\/tr>/)?.[0] || ''
assert.ok(row, 'the bounded mail row should remain discoverable')
assert.ok((row.match(/<button\b/g) || []).length <= 3, 'one row should mount two password reveals and one action trigger at most')
console.log('operations mail UI contracts passed')
```

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/operations-mail-regression.mjs
```

Expected: exit `1` because `UiPageHeader` is absent.

- [ ] **Step 3: Add explicit load and partial-data state**

Add `hasLoaded` and `loadError`. On a successful `loadRows`, update rows/summary, clear `loadError`, set `hasLoaded=true`. On failure, retain old rows, set `loadError`, and set `hasLoaded=true`. Use `UiStatePanel` for initial loading, first-load error, empty and stale-data partial states.

- [ ] **Step 4: Recompose page header, metrics and filters**

Make `导入邮箱` the primary page-header action and `新增` secondary. Render total/enabled/valid/invalid/selected through `UiMetricSummary`. Put check status, enabled status, email search and note search in `UiDataToolbar` and retain the current watchers that reset `accountPage`.

- [ ] **Step 5: Consolidate selection and row actions**

Move batch status, batch note and batch password operations to `UiBatchBar`. Keep full filtered-scope detection and export as quiet toolbar actions. Replace five permanently mounted row operations with one `操作` trigger and one shared `AccessibleModal`; retain the two password reveal buttons, so each row has at most three buttons.

- [ ] **Step 6: Migrate table, statuses, pagination and dialogs**

Use `UiTableFrame`, `UiStatusBadge`, and `UiPagination` while retaining all three bounded arrays. Convert import/edit/password/password-result/status/note/fetched dialogs to `AccessibleModal`, `UiFormField`, `UiButton`, and the shared pagination component. The API calls and `task-started` emit remain in `MailAccountsPage.vue`.

- [ ] **Step 7: Dispose transient message timers**

Replace `setMessage._timer` with `createMessageClearScheduler`; cancel on every replacement message and call `messageClearScheduler.dispose()` from `onBeforeUnmount`.

- [ ] **Step 8: Run GREEN and the existing 20k/2k contracts**

```powershell
node web/scripts/operations-mail-regression.mjs
node web/scripts/test-mail-accounts-render-window.mjs
node web/scripts/test-mail-accounts-batch-contract.mjs
npm.cmd --prefix web run build
```

Expected:

```text
operations mail UI contracts passed
mail account render-window tests passed: accounts=20000 default=100 max=500 fetched=20000 password=2000
mail account batch contract tests passed: import=20000 auth=1000 batch=2000 boundary=2000/2001
```

All commands exit `0`.

- [ ] **Step 9: Commit the mail workspace**

```bash
git add web/src/components/MailAccountsPage.vue web/src/style.css web/scripts/operations-mail-regression.mjs web/package.json
git commit -m "refactor(frontend): redesign mail account workspace"
```

---

### Task 12：重构任务历史和日志工作台

**Files:**

- Create: `web/src/taskHistoryData.js`
- Modify: `web/src/components/TaskHistory.vue`
- Modify: `web/src/components/TaskHistoryPage.vue`
- Modify: `web/src/components/LogViewer.vue`
- Delete: `web/src/components/TasksPage.vue`
- Create: `web/scripts/operations-history-regression.mjs`
- Modify: `web/src/style.css`
- Modify: `web/package.json`

**Interfaces:**

- Produces: `TASK_HISTORY_PAGE_SIZE = 50`.
- Produces: `filterTaskHistory(tasks, { query = '', status = '', command = '' } = {}): Array<object>`.
- Produces: `pageTaskHistory(tasks, page, pageSize = TASK_HISTORY_PAGE_SIZE): { page, pageSize, totalItems, totalPages, rows }`.
- Produces: `summarizeTaskHistory(tasks): { total, active, completed, failed }`.
- Preserves: `TaskHistory` prop `tasks: Array = []`; it does not fetch data.
- Preserves: `LogViewer` request completion scheduling, single-flight guard, visibility lifecycle, generation fencing, stable boot-aware key and 1,000-row cap.

- [ ] **Step 1: Write TaskHistory data and UI RED tests**

Create `web/scripts/operations-history-regression.mjs`:

```js
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

const dataUrl = new URL('../src/taskHistoryData.js', import.meta.url)
assert.ok(existsSync(dataUrl), 'taskHistoryData.js should exist')
const data = await import(dataUrl)
const tasks = Array.from({ length: 125 }, (_, index) => ({
  task_id: `task-${index}`,
  command: index % 2 ? 'register' : 'refresh-quota',
  status: index % 3 ? 'completed' : 'failed',
  params: { index },
}))
assert.equal(data.TASK_HISTORY_PAGE_SIZE, 50)
assert.equal(data.pageTaskHistory(tasks, 1).rows.length, 50)
assert.equal(data.pageTaskHistory(tasks, 99).page, 3)
assert.equal(data.filterTaskHistory(tasks, { query: 'task-124' }).length, 1)
assert.equal(data.filterTaskHistory(tasks, { command: 'register' }).length, 62)

const history = readFileSync(new URL('../src/components/TaskHistory.vue', import.meta.url), 'utf8')
const page = readFileSync(new URL('../src/components/TaskHistoryPage.vue', import.meta.url), 'utf8')
const logs = readFileSync(new URL('../src/components/LogViewer.vue', import.meta.url), 'utf8')
for (const tag of ['UiMetricSummary', 'UiDataToolbar', 'UiTableFrame', 'UiPagination', 'UiStatusBadge', 'AccessibleModal']) {
  assert.match(history, new RegExp(`<${tag}\\b`), `TaskHistory should use ${tag}`)
}
assert.match(page, /<UiPageHeader\b/)
assert.match(history, /v-for="task in pagedTasks"/)
assert.match(logs, /<UiPageHeader\b/)
assert.match(logs, /<UiSurface\b/)
assert.match(logs, /const LOG_KEEP_LIMIT = 1000\b/)
assert.doesNotMatch(logs, /setInterval\s*\(/)
console.log('operations task/history UI contracts passed')
```

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/operations-history-regression.mjs
```

Expected: exit `1` with `taskHistoryData.js should exist`.

- [ ] **Step 3: Implement pure task filtering, summary and pagination**

Normalize query/status/command to lowercase strings. Search task ID, command, params, error and result. Clamp page and page size; never return more than the requested page size. Treat `pending` and `running` as active, `completed` as completed, and `failed` as failed.

- [ ] **Step 4: Recompose TaskHistory and TaskHistoryPage**

Keep `TaskHistoryPage.vue` as the canonical `tasks` route. Add `UiPageHeader`, metric summary, query/status/command filters, a 50-row `UiTableFrame`, semantic badges, `UiPagination`, and one shared detail modal for full params/result/error. Delete unreachable `TasksPage.vue`, which duplicates `TaskHistoryPage` and `TaskPanel`.

- [ ] **Step 5: Recompose LogViewer without changing polling semantics**

Use `UiPageHeader`, `UiSurface`, `UiButton` and semantic log-level labels. Preserve `scheduleNextPoll`, `requestInFlight`, `requestGeneration`, `lastLogId`, `lastBootId`, `mergeLogEntries`, stable `_key`, visibility listeners and `LOG_KEEP_LIMIT=1000`. Continue showing the text `ERROR`, `WARNING`, `INFO` or `DEBUG` so color is not the only status signal.

- [ ] **Step 6: Run GREEN and polling regression**

```powershell
node web/scripts/operations-history-regression.mjs
node web/scripts/test-log-viewer.mjs
npm.cmd --prefix web run build
```

Expected:

```text
operations task/history UI contracts passed
LogViewer polling and rendering regression contract passed
```

All commands exit `0`.

- [ ] **Step 7: Commit task and log workspaces**

```bash
git add web/src/taskHistoryData.js web/src/components/TaskHistory.vue web/src/components/TaskHistoryPage.vue web/src/components/LogViewer.vue web/src/components/TasksPage.vue web/src/style.css web/scripts/operations-history-regression.mjs web/package.json
git commit -m "refactor(frontend): redesign task and log workspaces"
```

---

### Task 13：接入并重设计 Team 成员工作台

**Files:**

- Modify: `web/src/navigation.js`
- Modify: `web/src/App.vue`
- Modify: `web/src/components/NavIcon.vue`
- Modify: `web/src/components/TeamMembers.vue`
- Create: `web/scripts/operations-team-regression.mjs`
- Modify: `web/src/style.css`
- Modify: `web/package.json`

**Interfaces:**

- Produces navigation item `{ key: 'team', group: '账号', icon: 'team', label: 'Team 成员', description: '成员、邀请和本地账号状态' }`.
- Produces lazy loader `team: () => import('./components/TeamMembers.vue')` and `asyncPage('team')`.
- Preserves: `TeamMembers` owner-fenced session cache key `autotoken_team_members`, ten-minute TTL, `api.getTeamMembers()` and `api.removeTeamMember({ email, user_id, type })`.

- [ ] **Step 1: Write the Team RED contract**

Create `web/scripts/operations-team-regression.mjs`:

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const navigation = readFileSync(new URL('../src/navigation.js', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
const icons = readFileSync(new URL('../src/components/NavIcon.vue', import.meta.url), 'utf8')
const team = readFileSync(new URL('../src/components/TeamMembers.vue', import.meta.url), 'utf8')
assert.match(navigation, /key:\s*['"]team['"]/)
assert.match(app, /team:\s*\(\)\s*=>\s*import\(['"]\.\/components\/TeamMembers\.vue['"]\)/)
assert.match(app, /currentPage === ['"]team['"]/)
assert.match(icons, /team:\s*\[/)
for (const tag of ['UiPageHeader', 'UiMetricSummary', 'UiTableFrame', 'UiStatusBadge', 'UiStatePanel', 'AccessibleModal']) {
  assert.match(team, new RegExp(`<${tag}\\b`), `TeamMembers should use ${tag}`)
}
assert.match(team, /createSessionStorageFacade/)
assert.match(team, /state="partial"/)
assert.doesNotMatch(team, /window\.confirm/)
assert.doesNotMatch(team.split('<script setup>')[0], /\b(?:bg|border)-(?:gray|slate)-(?:950|900|800)\b/)
console.log('operations team UI contracts passed')
```

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/operations-team-regression.mjs
```

Expected: exit `1` because navigation has no `team` key.

- [ ] **Step 3: Add Team navigation and lazy route**

Add the exact navigation item above. Add a `team` SVG path set in `NavIcon.vue`. Add the loader, async component constant and `currentPage === 'team'` branch to `App.vue` without eager importing the page.

- [ ] **Step 4: Recompose TeamMembers and its data states**

Use `UiPageHeader`, `UiMetricSummary`, `UiTableFrame`, `UiStatusBadge`, and `UiStatePanel`. Preserve cached data when a refresh fails and show it with `state="partial"`. Continue preventing removal of `account-owner` rows.

- [ ] **Step 5: Replace native confirmation with accessible confirmation**

Store the pending member in a local ref, open one `AccessibleModal`, and invoke the unchanged remove payload only after the user chooses the destructive `UiButton`. Cancel closes the modal and returns focus.

- [ ] **Step 6: Run GREEN, storage and timeout gates**

```powershell
node web/scripts/operations-team-regression.mjs
node web/scripts/test-storage-session-isolation.mjs
node web/scripts/test-long-running-api-timeouts.mjs
npm.cmd --prefix web run build
```

Expected focused output:

```text
operations team UI contracts passed
```

All commands exit `0` and the storage regression continues to include `TeamMembers.vue`.

- [ ] **Step 7: Commit the Team workspace**

```bash
git add web/src/navigation.js web/src/App.vue web/src/components/NavIcon.vue web/src/components/TeamMembers.vue web/src/style.css web/scripts/operations-team-regression.mjs web/package.json
git commit -m "feat(frontend): add redesigned team workspace"
```

---

### Task 14：建立运营工作台浏览器 fixture 和 Phase 2 验收门禁

**Files:**

- Rename: `web/scripts/dashboard-browser-fixture-server.mjs` → `web/scripts/operations-browser-fixture-server.mjs`
- Create: `web/scripts/operations-browser-fixture-regression.mjs`
- Modify: `web/package.json`
- Verify only: `.verification/apple-light-theme-ui/phase-2/`

**Interfaces:**

- `createOperationsFixture({ accountCount = 20_000, mailCount = 20_000, taskCount = 250, phoneCount = 10_000, recordCount = 500 })` returns deterministic payloads for all operations routes.
- Fixture endpoints include `/api/accounts`, `/api/mail-accounts`, `/api/tasks`, `/api/team/members`, `/api/logs`, `/api/oauth-phone-pool`, `/api/oauth-phone-records`, plus setup/auth/admin/main-codex/manual-account boot endpoints.
- The server retains `/__metrics` and reports request paths and account request count.

- [ ] **Step 1: Write the fixture RED contract**

Create `web/scripts/operations-browser-fixture-regression.mjs`:

```js
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'

const serverUrl = new URL('./operations-browser-fixture-server.mjs', import.meta.url)
assert.ok(existsSync(serverUrl), 'operations browser fixture server should exist')
const { createOperationsFixture } = await import(serverUrl)
const fixture = createOperationsFixture({ accountCount: 20_000, mailCount: 20_000, taskCount: 250 })
assert.equal(fixture.accounts.rows.length, 20_000)
assert.equal(fixture.mailAccounts.items.length, 20_000)
assert.equal(fixture.tasks.length, 250)
assert.ok(fixture.teamMembers.members.length > 0)
assert.ok(fixture.logs.logs.length > 0)
assert.equal(createOperationsFixture({ accountCount: 0, mailCount: 0, taskCount: 0 }).accounts.rows.length, 0)
console.log('operations browser fixture contracts passed')
```

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/operations-browser-fixture-regression.mjs
```

Expected: exit `1` with `operations browser fixture server should exist`.

- [ ] **Step 3: Generalize and rename the fixture server**

Export `createOperationsFixture` without starting a listener when imported. Preserve compact Dashboard field ordering. When executed directly, serve the production build and the exact API payloads above. A zero count must produce empty summaries rather than malformed payloads.

- [ ] **Step 4: Run every Phase 2 source and existing frontend gate**

```powershell
node web/scripts/operations-browser-fixture-regression.mjs
npm.cmd --prefix web run test:operations-workspaces
npm.cmd --prefix web run test:frontend
```

Expected:

- the standalone fixture regression ends with `operations browser fixture contracts passed`;
- `test:operations-workspaces` ends with:

```text
operations team UI contracts passed
operations browser fixture contracts passed
```

- `test:frontend` ends with a line matching `^all frontend scripts passed: ([0-9]+)/\1$`.

All commands exit `0`; the production entry remains at or below 250 KiB and produces at least eight JavaScript chunks.

- [ ] **Step 5: Start the 20k browser fixture**

```powershell
node web/scripts/operations-browser-fixture-server.mjs 8799 20000
```

Expected literal prefix:

```text
fixture_ready url=http://127.0.0.1:8799/ rows=20000
```

- [ ] **Step 6: Verify desktop light and dark workspaces**

At `1440×1000`, inspect Dashboard, MailAccounts, Tasks, Logs and Team in explicit light and dark modes. Confirm no console errors, page-root horizontal overflow or unreadable statuses. Dashboard must mount 50 account rows; MailAccounts 100; Tasks 50; only `UiTableFrame` may scroll horizontally.

- [ ] **Step 7: Verify mobile filter and batch sheets**

At `390×844`, open Dashboard and MailAccounts filters and batch actions. Confirm 44 px triggers, Escape close, Tab focus loop, outside close, focus return, readable selected count and no duplicate filter controls in the accessibility tree.

- [ ] **Step 8: Verify the short viewport and state panels**

At `1024×620`, open row actions, task details and Team removal confirmation. Confirm every modal has internal scrolling, visible footer actions and no clipped close control. Restart the fixture with zero rows and verify loading/empty/error/partial panels remain distinguishable in both themes.

- [ ] **Step 9: Capture and reopen Phase 2 screenshots**

Save and reopen:

```text
.verification/apple-light-theme-ui/phase-2/dashboard-light.png
.verification/apple-light-theme-ui/phase-2/dashboard-dark.png
.verification/apple-light-theme-ui/phase-2/mail-light.png
.verification/apple-light-theme-ui/phase-2/mail-dark.png
.verification/apple-light-theme-ui/phase-2/tasks-light.png
.verification/apple-light-theme-ui/phase-2/team-dark.png
.verification/apple-light-theme-ui/phase-2/mobile-filters-light.png
```

- [ ] **Step 10: Commit the fixture and Phase 2 gate**

Do not commit `.verification` images.

```bash
git add web/scripts/operations-browser-fixture-server.mjs web/scripts/operations-browser-fixture-regression.mjs web/scripts/dashboard-browser-fixture-server.mjs web/package.json
git commit -m "test(frontend): verify operations workspaces"
```

---

### Phase 2 完成检查点

- [ ] `Dashboard.vue` retains the 20,000-account performance and stale-snapshot contracts.
- [ ] `MailAccountsPage.vue` retains its 20,000/2,000/1,000 limits and all three bounded render windows.
- [ ] `TaskHistoryPage.vue` is the only task-history route and mounts no more than 50 rows.
- [ ] `TasksPage.vue` is removed as unreachable duplicate code.
- [ ] `TeamMembers.vue` is reachable through a lazy-loaded `team` navigation item.
- [ ] `LogViewer.vue` retains completion-scheduled polling, visibility cancellation, boot-aware merging and a 1,000-row cap.
- [ ] Every migrated page uses semantic surfaces and explicit loading, empty, error and partial states.
- [ ] Desktop, mobile and short-viewport browser checks pass in light and dark modes.
- [ ] `npm.cmd --prefix web run test:frontend` and `npm.cmd --prefix web run build` exit `0`.
- [ ] Phase 2 verification screenshots are reopened and visually inspected.

### Phase 4 消费契约

Phase 4 must consume the exact `UiMetricSummary`, `UiDataToolbar`, `UiBatchBar`, `UiPagination`, and `UiTableFrame` interfaces defined in Task 9 for `OAuthPage.vue`, `OAuthPhonePoolPage.vue`, `OAuthPhoneRecordsPage.vue`, `PoolPage.vue`, `SyncPage.vue`, and `TaskPanel.vue`. It must add reachable `pool` and `sync` lazy routes, retain OAuth phone 100-row pagination and lazy drafts, add bounded pagination to the 500-record OAuth history, preserve TaskPanel single-flight, and dispose its message/domain timers.

## Phase 3: Payment, Registration, and Bind-Card Workflows

### Task 15: Establish the Shared Workflow Page Archetype

**Files:**
- Create: `web/src/components/workflow/WorkflowWorkspace.vue`
- Create: `web/src/components/workflow/WorkflowStage.vue`
- Create: `web/scripts/workflow-archetype-regression.mjs`

**Interfaces:**
- Consumes: `UiPageHeader.vue`, `UiSurface.vue`, `UiStatusBadge.vue`, and `UiStatePanel.vue` from Phase 1.
- Produces: `WorkflowWorkspace` with props `title: string` (required), `eyebrow: string`, `description: string`, `statusLabel: string`, and `statusTone: 'neutral' | 'info' | 'success' | 'warning' | 'danger'`; named slots `actions`, `configuration`, `progress`, `result`, and `resources`.
- Produces: `WorkflowStage` with props `name: 'configuration' | 'launch' | 'progress' | 'result' | 'resources'`, `title: string` (required), `description: string`, and `state: 'idle' | 'active' | 'complete' | 'warning' | 'error'`; named slot `actions` and default slot.
- Neither component imports `api.js`, starts polling, mutates storage, or owns business state.

- [ ] **Step 1: Write the failing workflow-archetype contract**

Create `web/scripts/workflow-archetype-regression.mjs` with assertions that both files exist, `WorkflowWorkspace` renders `data-page-archetype="workflow"`, all five named slots exist, `WorkflowStage` renders `data-workflow-stage`, runtime validators reject unsupported tones/states, and neither source imports `api.js`.

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = name => readFileSync(new URL(`../src/components/workflow/${name}`, import.meta.url), 'utf8')
const workspace = read('WorkflowWorkspace.vue')
const stage = read('WorkflowStage.vue')

assert.match(workspace, /data-page-archetype="workflow"/)
for (const slot of ['actions', 'configuration', 'progress', 'result', 'resources']) {
  assert.match(workspace, new RegExp(`<slot name="${slot}"`))
}
assert.match(stage, /data-workflow-stage/)
assert.match(stage, /configuration.*launch.*progress.*result.*resources/s)
assert.match(stage, /idle.*active.*complete.*warning.*error/s)
assert.doesNotMatch(`${workspace}\n${stage}`, /api\.js/)
console.log('workflow archetype regression passed')
```

- [ ] **Step 2: Run the focused test to verify RED**

Run:

```powershell
node web/scripts/workflow-archetype-regression.mjs
```

Expected: exit `1` with `ENOENT` for `WorkflowWorkspace.vue`.

- [ ] **Step 3: Implement the presentation-only workflow components**

Implement `WorkflowWorkspace.vue` as a `UiPageHeader` followed by a responsive two-column shell. Place `configuration` on the primary column, `progress` and `result` on the secondary column, and `resources` below both columns. At widths below 768 px, render configuration, progress, result, and resources in that exact order. Use component-scoped CSS variables from Phase 1; do not use gray/slate utility colors or `transition: all`.

Implement `WorkflowStage.vue` as a labelled `UiSurface`, expose the state through `data-workflow-state`, and render a `UiStatusBadge` when state is not `idle`. The heading id must be stable for `aria-labelledby`.

- [ ] **Step 4: Run GREEN and the production build**

Run:

```powershell
node web/scripts/workflow-archetype-regression.mjs
npm.cmd --prefix web run build
```

Expected: `workflow archetype regression passed`; both commands exit `0`.

- [ ] **Step 5: Commit the shared workflow archetype**

```powershell
git add web/src/components/workflow/WorkflowWorkspace.vue web/src/components/workflow/WorkflowStage.vue web/scripts/workflow-archetype-regression.mjs
git commit -m "feat(frontend): establish workflow workspace primitives"
```

### Task 16: Redesign the Registration Workspace

**Files:**
- Modify: `web/src/components/RegisterAccountPage.vue`
- Create: `web/scripts/register-workflow-regression.mjs`

**Interfaces:**
- Consumes: `WorkflowWorkspace`, `WorkflowStage`, `UiButton`, `UiFormField`, `UiStatusBadge`, `UiStatePanel`, `UiSegmentedControl`, `AccessibleModal`, and `UiSheet`.
- Preserves props `runningTask: Object` and `adminStatus: Object | null`.
- Preserves emits `task-started` and `refresh`.
- Preserves `submitManualRegister()`, `cancelRegisterTask()`, `startRegisterPolling()`, `stopRegisterPolling()`, `REGISTER_FORM_STORAGE_KEY`, provider-country caching, mail-pool pagination, and the current request payload.

- [ ] **Step 1: Write the failing registration UI contract**

Create `web/scripts/register-workflow-regression.mjs`. Assert that the page imports the workflow components, contains the four stages `configuration`, `launch`, `progress`, and `result`, keeps the two public emits and the polling/start/cancel functions, uses shared modal/sheet primitives for pool/import dialogs, and contains no hand-written `<section role="dialog">`.

```js
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../src/components/RegisterAccountPage.vue', import.meta.url), 'utf8')
assert.match(source, /WorkflowWorkspace/)
for (const stage of ['configuration', 'launch', 'progress', 'result']) {
  assert.match(source, new RegExp(`WorkflowStage[^>]+name="${stage}"`))
}
assert.match(source, /AccessibleModal|UiSheet/)
assert.doesNotMatch(source, /<section[^>]+role="dialog"/)
assert.match(source, /async function submitManualRegister/)
assert.match(source, /async function cancelRegisterTask/)
assert.match(source, /function startRegisterPolling/)
assert.match(source, /defineEmits\(\['task-started', 'refresh'\]\)/)
console.log('registration workflow regression passed')
```

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/register-workflow-regression.mjs
```

Expected: exit `1` because `WorkflowWorkspace` is absent from the page.

- [ ] **Step 3: Recompose the template without changing registration state**

Use `WorkflowWorkspace` for the page. Put registration method, mail source, domain, proxy, SMS-provider, and provider-specific inputs into the `configuration` slot. Put exactly one primary “开始注册” action in `launch`. Put the current task state, cancellation, progress metrics, and registration logs in `progress`. Put recent results and mail-pool status in `result/resources`.

Replace the Outlook/iCloud/generic mail pool, mail.com pool, and import overlays with `AccessibleModal` on desktop and `UiSheet side="bottom"` on mobile. Continue calling the existing open/close/import/delete functions so selection and render-window semantics remain unchanged.

- [ ] **Step 4: Run focused lifecycle, race, render-window, and storage gates**

```powershell
node web/scripts/register-workflow-regression.mjs
node web/scripts/test-register-account-polling-lifecycle.mjs
node web/scripts/test-register-mail-pool-render-window.mjs
node web/scripts/test-provider-response-race.mjs
node web/scripts/test-storage-session-isolation.mjs
npm.cmd --prefix web run build
```

Expected: all commands exit `0`; focused output includes `registration workflow regression passed`.

- [ ] **Step 5: Commit the registration workspace**

```powershell
git add web/src/components/RegisterAccountPage.vue web/scripts/register-workflow-regression.mjs
git commit -m "feat(frontend): redesign account registration workspace"
```

### Task 17: Redesign Card Pool, Bind Card, and GoPay

**Files:**
- Modify: `web/src/components/BindCardPool.vue`
- Modify: `web/src/components/BindCard.vue`
- Create: `web/scripts/bind-card-workflow-regression.mjs`

**Interfaces:**
- `BindCard` continues to accept `initialTab: string` and `standalone: boolean`, and continues to emit `refresh`.
- The `standalone=true` route continues to force the GoPay flow and must not expose unrelated tabs.
- Preserve `generateLink()`, `generateAndOpenWithAuthSession()`, `startBindCard()`, `cancelBindTask()`, `startGoPayBind()`, `cancelGoPayTask()`, `CHATGPT_BIND_FORM_STATE_KEY`, `GOPAY_FORM_STATE_KEY`, and all polling/storage behavior.
- `BindCardPool` preserves filtering, selection, pagination, import, redeem, delete, enable/disable, SMS lookup, and API payloads.

- [ ] **Step 1: Write the failing bind-card UI regression**

The test must assert a `UiSegmentedControl` for `bind | kiro | generate | gopay`, workflow stages for every active flow, the unchanged props/emits, a standalone GoPay branch, shared status badges, shared modal handling in the card pool, and continued presence of the six business functions above.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/bind-card-workflow-regression.mjs
```

Expected: exit `1` because the bind-card page has not adopted the workflow archetype.

- [ ] **Step 3: Implement the card and bind-card redesign**

Replace the existing top tab buttons with `UiSegmentedControl`. Inside each mode render configuration, launch, progress, and result stages. Keep a single visually dominant submit action, move cancellation into the progress stage, and separate destructive history/card-pool actions.

Recompose `BindCardPool` with `UiPageHeader`, Phase 2 metric/table primitives when present, `UiStatusBadge`, `UiStatePanel`, and `AccessibleModal`. Do not change computed filtering, current page calculations, selected id handling, or API calls.

- [ ] **Step 4: Run focused polling and storage gates**

```powershell
node web/scripts/bind-card-workflow-regression.mjs
node web/scripts/test-polling-lifecycle.mjs
node web/scripts/test-storage-session-isolation.mjs
npm.cmd --prefix web run build
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit card and GoPay presentation**

```powershell
git add web/src/components/BindCard.vue web/src/components/BindCardPool.vue web/scripts/bind-card-workflow-regression.mjs
git commit -m "feat(frontend): redesign card and gopay workflows"
```

### Task 18: Redesign the PayPal Extract, Protocol, and 153 Workflows

**Files:**
- Modify: `web/src/components/UsPaypalPage.vue`
- Create: `web/scripts/paypal-workflow-regression.mjs`

**Interfaces:**
- Preserves all request acknowledgement, manual/automatic recovery, retry backoff, BA/phone-pool claims, cancellation, polling, render-window, and session-storage contracts.
- `unknown_outcome` remains a distinct warning state and is never normalized to failed.
- Existing API method names and request payloads remain unchanged.

- [ ] **Step 1: Write the failing PayPal workflow regression**

Assert a labelled segmented control for extract, protocol, and 153 modes; a `WorkflowWorkspace` in each mode; configuration/launch/progress/result stages; one primary action per mode; destructive cancellation separated from launch; and visible warning copy for `unknown_outcome`. Assert presentation helpers return semantic tones rather than Tailwind class strings.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/paypal-workflow-regression.mjs
```

Expected: exit `1` on the missing workflow composition.

- [ ] **Step 3: Recompose all three PayPal modes**

Use one `UiSegmentedControl` for mode selection. Keep each existing form and state machine intact, but place inputs, primary launch, live progress/cancellation, results, account pools, link pools, and BA pools into the corresponding workflow slots. Convert status-class helpers to tone helpers consumed by `UiStatusBadge`; retain the exact `unknown_outcome` text and recovery actions.

- [ ] **Step 4: Run every focused PayPal gate**

```powershell
node web/scripts/paypal-workflow-regression.mjs
node web/scripts/test-deferred-storage.mjs
node web/scripts/test-job-snapshot-performance.mjs
node web/scripts/test-pay153-cancel-mutation-lock.mjs
node web/scripts/test-payment-list-render-window.mjs
node web/scripts/test-payment-unknown-outcome.mjs
node web/scripts/test-paypal-auto-job-recovery.mjs
node web/scripts/test-paypal-late-job-persistence.mjs
node web/scripts/test-paypal-manual-job-recovery.mjs
node web/scripts/test-paypal-missing-job-id-recovery.mjs
node web/scripts/test-paypal-polling-lifecycle.mjs
node web/scripts/test-paypal-pre-ack-cancel.mjs
node web/scripts/test-paypal-retry-backoff.mjs
node web/scripts/test-status-polling-failure-budget.mjs
node web/scripts/test-storage-session-isolation.mjs
npm.cmd --prefix web run build
```

Expected: every command exits `0`.

- [ ] **Step 5: Commit the PayPal redesign**

```powershell
git add web/src/components/UsPaypalPage.vue web/scripts/paypal-workflow-regression.mjs
git commit -m "feat(frontend): redesign paypal workflow workspace"
```

### Task 19: Unify iDEAL, MoMo, and GCash Extraction Workflows

**Files:**
- Modify: `web/src/components/IdealLinkPage.vue`
- Modify: `web/src/components/MomoPage.vue`
- Modify: `web/src/components/GCashPhPage.vue`
- Create: `web/scripts/extraction-workflow-regression.mjs`

**Interfaces:**
- Preserves iDEAL long-link identity, `unknown_outcome` isolation, remote-job reconciliation, polling lifecycle, and QR rendering.
- Preserves MoMo/GCash start-ack CAS, qualification-only mode, cancellation, expiry clocks, job restoration, and 100-row incremental rendering.

- [ ] **Step 1: Write the failing regional extraction contract**

For all three sources, assert `WorkflowWorkspace`, four primary stages, semantic status tones, a bounded resources list, one primary launch action, and preserved restoration/cancellation functions. Assert no fixed dark gradient or gray/slate surface class remains in the template.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/extraction-workflow-regression.mjs
```

Expected: exit `1` because the pages still use dark card stacks.

- [ ] **Step 3: Implement the common extraction composition**

Place proxy and account selection in configuration; start/qualification in launch; current job, cancellation, and logs in progress; recent task output in result; and links in resources. Use text plus `UiStatusBadge` for status. Preserve all current refs, watchers, storage keys, request ordering, and cleanup hooks.

- [ ] **Step 4: Run extraction lifecycle gates**

```powershell
node web/scripts/extraction-workflow-regression.mjs
node web/scripts/test-cancel-polling-recovery.mjs
node web/scripts/test-payment-expiry-clock-lifecycle.mjs
node web/scripts/test-payment-list-render-window.mjs
node web/scripts/test-payment-polling.mjs
node web/scripts/test-polling-lifecycle.mjs
node web/scripts/test-start-ack-remount.mjs
node web/scripts/test-status-polling-failure-budget.mjs
node web/scripts/test-storage-session-isolation.mjs
npm.cmd --prefix web run build
```

Expected: every command exits `0`.

- [ ] **Step 5: Commit the regional extraction redesign**

```powershell
git add web/src/components/IdealLinkPage.vue web/src/components/MomoPage.vue web/src/components/GCashPhPage.vue web/scripts/extraction-workflow-regression.mjs
git commit -m "feat(frontend): unify regional extraction workflows"
```

### Task 20: Redesign PIX, UPI, and Kakao Dual-Mode Payments

**Files:**
- Modify: `web/src/components/BrazilPixPage.vue`
- Modify: `web/src/components/IndiaUpiPage.vue`
- Modify: `web/src/components/KakaoPayPage.vue`
- Create: `web/scripts/dual-mode-payment-workflow-regression.mjs`

**Interfaces:**
- Consumes the Phase 1 `workflow-hero-surface` compatibility class only until the workflow wrapper replaces it.
- Preserves shared polling gates, start-ack watchers, expiry clocks, payment concurrency limits, CDK/link persistence, active remote order recovery, cancellation, and current API payloads.
- Distinguishes `unknown`, `needs_action`, `running`, and terminal results with text and tone.

- [ ] **Step 1: Write the failing dual-mode workflow contract**

Assert segmented extraction/payment modes, workflow stages, separate link/CDK/account resource surfaces, visible unknown/needs-action labels, and absence of arbitrary classes beginning with `bg-[radial-gradient` or fixed dark `linear-gradient` classes.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/dual-mode-payment-workflow-regression.mjs
```

Expected: exit `1` on missing workflow stages.

- [ ] **Step 3: Implement the two-mode layouts**

Keep all script state and functions in their current components. Recompose each template around a labelled segmented control and `WorkflowWorkspace`. Keep extraction configuration/status separate from payment link/CDK queues, make the active remote order conspicuous, and preserve bounded rendering for every collection.

- [ ] **Step 4: Run start-ack, persistence, polling, and render-window gates**

```powershell
node web/scripts/dual-mode-payment-workflow-regression.mjs
node web/scripts/test-deferred-storage.mjs
node web/scripts/test-extraction-polling-recovery.mjs
node web/scripts/test-late-payment-state-persistence.mjs
node web/scripts/test-payment-list-render-window.mjs
node web/scripts/test-payment-unknown-outcome.mjs
node web/scripts/test-shared-payment-polling-gates.mjs
node web/scripts/test-start-ack-remount.mjs
node web/scripts/test-status-polling-failure-budget.mjs
node web/scripts/test-storage-session-isolation.mjs
npm.cmd --prefix web run build
```

Expected: every command exits `0`.

- [ ] **Step 5: Commit the dual-mode payment redesign**

```powershell
git add web/src/components/BrazilPixPage.vue web/src/components/IndiaUpiPage.vue web/src/components/KakaoPayPage.vue web/scripts/dual-mode-payment-workflow-regression.mjs
git commit -m "feat(frontend): redesign pix upi and kakao payment flows"
```

### Task 21: Pass the Phase 3 Checkpoint

**Files:**
- Verify only; no production file changes.

**Interfaces:**
- Confirms all Phase 3 pages retain their business contracts and consume the shared workflow archetype.

- [ ] **Step 1: Run the complete frontend suite and production build**

```powershell
npm.cmd --prefix web run test:frontend
```

Expected: build exits `0`, bundle budget passes, and stdout ends with `all frontend scripts passed:` followed by equal passed/total counts.

- [ ] **Step 2: Verify the checkpoint diff**

```powershell
git diff --check f0a222fcddee752784230040e58dc938b68e8517..HEAD
git status --short
```

Expected: diff check exits `0`; status is clean.

## Phase 4: Management, Settings, Support, and Final Convergence

### Task 22: Expose the Existing Pool and Sync Management Workspaces

**Files:**
- Modify: `web/src/navigation.js`
- Modify: `web/src/App.vue`
- Modify: `web/src/components/NavIcon.vue`
- Modify: `web/src/components/PoolPage.vue`
- Modify: `web/src/components/SyncPage.vue`
- Modify: `web/src/components/TaskPanel.vue`
- Create: `web/scripts/management-routes-regression.mjs`

**Interfaces:**
- `PoolPage` preserves props `runningTask: Object`, `adminStatus: Object`, emits `task-started` and `refresh`, and passes `mode="pool"` to `TaskPanel`.
- `SyncPage` preserves the same props/emits and passes `mode="sync"` to `TaskPanel`.
- `App.vue` supplies `runningTask` and `adminStatus`, forwards `onTaskStarted`, and calls `refresh`.
- Produces navigation keys `pool` and `sync` without introducing backend methods.
- `TaskPanel.vue` retains its `executingAction` single-flight guard and API payloads while owning disposable message and domain-message schedulers.

- [ ] **Step 1: Write the failing route contract**

Create a source-level regression that imports `NAV_ITEMS`, verifies unique keys, requires the following exact metadata, and asserts lazy-loader, component constant, and template branches in `App.vue`:

```js
const expected = {
  pool: { group: '账号', label: '账号池操作', description: '轮转、检查、补位与清理' },
  sync: { group: '系统', label: '同步中心', description: '本地、CPA 与账号凭据对账' },
}
```

Also assert neither wrapper imports `api.js` and both retain their exact `TaskPanel` modes and emits. Require `TaskPanel.vue` to import `createMessageClearScheduler`, create separate `messageClearScheduler` and `domainMessageClearScheduler` instances, dispose both from `onBeforeUnmount`, and contain no raw `setTimeout(` call.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/management-routes-regression.mjs
```

Expected: exit `1` because `pool` and `sync` are absent from `NAV_ITEMS`.

- [ ] **Step 3: Add the routes and semantic wrappers**

Add both navigation records, matching `pool` and `sync` icons, async loaders, constants, and these exact render contracts:

```vue
<PoolPage
  v-else-if="currentPage === 'pool'"
  :running-task="runningTask"
  :admin-status="adminStatus"
  @task-started="onTaskStarted"
  @refresh="refresh"
/>
<SyncPage
  v-else-if="currentPage === 'sync'"
  :running-task="runningTask"
  :admin-status="adminStatus"
  @task-started="onTaskStarted"
  @refresh="refresh"
/>
```

Restyle both wrappers with `UiPageHeader` and `UiSurface`; leave action ownership in `TaskPanel`.

In `TaskPanel.vue`, replace the three raw message/domain timeouts with two `createMessageClearScheduler()` instances. Clear a replaced schedule before setting a new one, and call both schedulers' `dispose()` methods from `onBeforeUnmount`; do not alter the existing single-flight guard, API call names, payloads, or parent emits.

- [ ] **Step 4: Run route, task-panel, shell, and build gates**

```powershell
node web/scripts/management-routes-regression.mjs
node web/scripts/test-task-panel-single-flight.mjs
node web/scripts/test-frontend-shell.mjs
npm.cmd --prefix web run build
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit management routes**

```powershell
git add web/src/navigation.js web/src/App.vue web/src/components/NavIcon.vue web/src/components/PoolPage.vue web/src/components/SyncPage.vue web/src/components/TaskPanel.vue web/scripts/management-routes-regression.mjs
git commit -m "feat(frontend): expose pool and sync management workspaces"
```

### Task 23: Redesign OAuth Login, Phone Pool, and Phone Records

**Files:**
- Modify: `web/src/components/OAuthPage.vue`
- Modify: `web/src/components/OAuthPhonePoolPage.vue`
- Modify: `web/src/components/OAuthPhoneRecordsPage.vue`
- Create: `web/scripts/oauth-management-regression.mjs`

**Interfaces:**
- Consumes Phase 1 UI primitives.
- Consumes `UiMetricSummary` with props `items: Array<{key, label, value, tone?, detail?}> = []`, `label: string = '关键指标'`, and `compact: boolean = false`, plus slot `empty`.
- Consumes `UiDataToolbar` with props `resultLabel: string = ''`, `activeFilterCount: number = 0`, `filtersLabel: string = '筛选'`, and `clearable: boolean = false`; emit `clear-filters`; slots `primary`, `filters`, and `actions`. Its filter slot is mounted once across desktop/mobile.
- Consumes `UiBatchBar` with required prop `count: number`, props `label: string = '已选择'`, `itemLabel: string = '项'`, and `busy: boolean = false`; emit `clear`; default slot. Its action content is mounted once across desktop/mobile.
- Consumes `UiPagination` with required props `page: number`, `pageSize: number`, and `totalItems: number`, plus `pageSizes: number[] = []` and `itemLabel: string = '条记录'`; emits `update:page` and `update:pageSize`.
- Consumes `UiTableFrame` with required prop `label: string`, props `busy: boolean = false`, `empty: boolean = false`, and `minWidth: string = '0'`; slots `header`, default, `empty`, and `footer`; produces a bounded labelled region with `aria-busy`.
- `OAuthPage` preserves prop `manualAccountStatus: Object | null` and emits `refresh` and `progress`.
- `OAuthPhonePoolPage` preserves the 100-row page size, all editable fields, batch import/delete, selection, and save/delete payloads.
- `OAuthPhoneRecordsPage` preserves `api.getOAuthPhoneRecords(500)`, filtering, counts, and all record fields; produces `OAUTH_PHONE_RECORDS_PAGE_SIZE = 100`, renders only `pagedRecords`, clamps the current page after filtering, and binds `UiPagination` with page sizes `[50, 100, 200]`.

- [ ] **Step 1: Write the failing OAuth management regression**

Assert OAuth stages “生成链接”, “完成授权”, “提交回调”, and result; shared status/state components; no inline `h()` stat-card definition; a bounded phone-pool table; pagination; preserved props/emits/API calls; and labelled form controls. Separately assert that `OAuthPhoneRecordsPage` iterates `pagedRecords`, uses `UiPagination`, clamps page changes, and mounts no more than the selected page size from a 500-record fixture; a 250-record fixture at the default size must produce three pages with at most 100 mounted rows.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/oauth-management-regression.mjs
```

Expected: exit `1` on the inline StatCard and missing semantic components.

- [ ] **Step 3: Implement the OAuth management composition**

Render OAuth login as a clear four-step flow while retaining current callback polling and parent events. Recompose the phone pool with metric summary, add/import surfaces, a data toolbar, batch bar, bounded table frame, status badges, and its existing 100-row pagination. Recompose phone records with metric summary, data toolbar, bounded `UiTableFrame`, `UiStatusBadge`, `UiStatePanel`, and the specified 50/100/200 page-size control after filtering.

- [ ] **Step 4: Run focused OAuth performance and storage gates**

```powershell
node web/scripts/oauth-management-regression.mjs
node web/scripts/test-oauth-phone-pool-performance.mjs
node web/scripts/test-storage-session-isolation.mjs
npm.cmd --prefix web run build
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit OAuth management**

```powershell
git add web/src/components/OAuthPage.vue web/src/components/OAuthPhonePoolPage.vue web/src/components/OAuthPhoneRecordsPage.vue web/scripts/oauth-management-regression.mjs
git commit -m "feat(frontend): redesign oauth management workspaces"
```

### Task 24: Build the Grouped Settings Workspace

**Files:**
- Create: `web/src/components/settings/SettingsWorkspace.vue`
- Create: `web/src/components/settings/SettingsGroup.vue`
- Modify: `web/src/components/Settings.vue`
- Modify: `web/src/App.vue`
- Create: `web/scripts/settings-workspace-regression.mjs`

**Interfaces:**
- `SettingsWorkspace` props: `sections: Array<{id: string, label: string, description?: string}>`, `modelValue: string`, and `ariaLabel: string`; emits `update:modelValue`; supports Home, End, ArrowUp, and ArrowDown.
- `SettingsGroup` props: `id: string`, `title: string`, `description: string`, `tone: 'neutral' | 'warning' | 'danger'`, `disclosure: boolean`, and `open: boolean`; emits `update:open`; slots `actions` and default.
- `Settings.vue` emits `navigate` for the maintenance link to `logs`; `App.vue` binds `@navigate="navigateTo"` on the Settings branch.
- Existing configuration API functions and payloads retain their names and ownership in `Settings.vue`.

- [ ] **Step 1: Write the failing settings regression**

Assert the exact section ids `appearance`, `accounts`, `phone`, `payments`, `integrations`, `automation`, and `maintenance`; `<ThemeSwitcher mode="group">`; keyboard navigation in `SettingsWorkspace`; advanced/destructive disclosures; `emit('navigate', 'logs')` in `Settings.vue`; `@navigate="navigateTo"` on the `<Settings>` branch in `App.vue`; and unchanged load/save/test/import/export function names.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/settings-workspace-regression.mjs
```

Expected: exit `1` because grouped settings components do not exist.

- [ ] **Step 3: Implement grouped settings without moving business state**

Create a desktop side-navigation and mobile selector in `SettingsWorkspace`. Keep each group mounted with `v-show` so unsaved form state survives navigation. Put the full appearance control in `appearance`; account hub, domain, and mail provider in `accounts`; OAuth SMS in `phone`; GoPay/Rekberinaja in `payments`; RoxyBrowser in `integrations`; quota refresh and inspections in `automation`; config import/export and support/log navigation in `maintenance`. Hide secrets and destructive import actions behind `SettingsGroup disclosure`.

Mount Settings in `App.vue` with its existing props/events plus the exact navigation listener:

```vue
<Settings
  v-else-if="currentPage === 'settings'"
  :admin-status="adminStatus"
  :codex-status="codexStatus"
  @refresh="refresh"
  @admin-progress="onAdminProgress"
  @navigate="navigateTo"
/>
```

- [ ] **Step 4: Run settings, theme, and build gates**

```powershell
node web/scripts/settings-workspace-regression.mjs
node web/scripts/theme-regression.mjs
npm.cmd --prefix web run build
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit grouped settings**

```powershell
git add web/src/components/settings/SettingsWorkspace.vue web/src/components/settings/SettingsGroup.vue web/src/components/Settings.vue web/src/App.vue web/scripts/settings-workspace-regression.mjs
git commit -m "feat(frontend): reorganize settings and maintenance"
```

### Task 25: Redesign Trade, CPA Conversion, and Log Diagnostics

**Files:**
- Modify: `web/src/components/TradeManagerPage.vue`
- Modify: `web/src/components/CpaToSub2ApiPage.vue`
- Verify only: `web/src/components/LogViewer.vue`
- Create: `web/scripts/utility-routes-regression.mjs`

**Interfaces:**
- Trade retains summary/CDK APIs, create/revoke/download flows, password visibility state, and unique accessible names.
- CPA conversion retains file-count/content-size limits, inspect-before-convert behavior, settings, output-directory actions, and long-request timeout behavior.
- LogViewer retains the semantic layout completed in Task 12 plus single-flight polling, visibility pause, boot-id aware deduplication, 1000-row keep limit, auto-scroll, manual refresh, and clear-local-view behavior; this task verifies it without restructuring its template again.
- Support and maintenance remain in Settings plus LogViewer; no new support route or backend endpoint is introduced.

- [ ] **Step 1: Write the failing utility-routes regression**

Assert shared page headers/surfaces/state panels; `AccessibleModal` for CPA settings; labelled Trade password/revoke controls; the Task 12 bounded diagnostic log region and polling contract; and the existing business function/API names.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/utility-routes-regression.mjs
```

Expected: exit `1` because the pages still use dark card stacks and a custom settings overlay.

- [ ] **Step 3: Implement the three management layouts**

Use a stable header and metric/list hierarchy for Trade and a file/configure/convert/result hierarchy for CPA conversion. Use `UiStatePanel` for loading/empty/error while leaving the current request functions intact. Do not modify LogViewer in this task; its focused regression verifies the semantic diagnostics header/toolbar/bounded console and all Task 12 polling safeguards.

- [ ] **Step 4: Run utility behavior and build gates**

```powershell
node web/scripts/utility-routes-regression.mjs
node web/scripts/test-cpa-file-ingest-limits.mjs
node web/scripts/test-long-running-api-timeouts.mjs
node web/scripts/test-log-viewer.mjs
npm.cmd --prefix web run build
```

Expected: all commands exit `0`.

- [ ] **Step 5: Commit utility and diagnostics presentation**

```powershell
git add web/src/components/TradeManagerPage.vue web/src/components/CpaToSub2ApiPage.vue web/scripts/utility-routes-regression.mjs
git commit -m "feat(frontend): redesign commerce tools and diagnostics"
```

### Task 26: Remove Proven-Unused Dark Compatibility Rules

**Files:**
- Modify: `web/src/style.css`
- Modify: `web/tailwind.config.js` only for mappings proven unused by the scan
- Modify: `web/src/components/NotificationSoundControl.vue`
- Create: `web/scripts/semantic-style-convergence-regression.mjs`

**Interfaces:**
- Preserves all semantic surface, text, accent, status, shadow, scrim, scrollbar, and focus tokens.
- Preserves `text-on-accent` as white in both themes.
- Removes only compatibility selectors with zero Vue consumers.

- [ ] **Step 1: Write the failing semantic convergence scan**

Recursively read `web/src/**/*.vue` and reject these patterns:

```js
const forbidden = [
  /\btext-white\b/,
  /\b(?:bg|border|divide|text|placeholder:text)-(?:gray|slate)-(?:100|200|300|400|500|600|700|800|900|950)\b/,
  /bg-\[(?:radial|linear)-gradient/,
  /\bshadow-black(?:\/\d+)?\b/,
  /\btransition-all\b/,
]
```

Also assert `style.css` has no `transition: all`, retains both light/dark token blocks and forced-colors/reduced-motion rules, and contains no compatibility selector whose source usage count is zero.

- [ ] **Step 2: Run RED**

```powershell
node web/scripts/semantic-style-convergence-regression.mjs
```

Expected: exit `1` and print the remaining file/pattern pairs.

- [ ] **Step 3: Migrate the reported presentation classes and remove only unused rules**

Replace reported utility classes with semantic component variants or local semantic classes, including the controls and preview surface in `NotificationSoundControl.vue`. Convert status-class helper output to tone values. Re-run the scan after each removal so the Tailwind RGB compatibility palette remains available only where a consumer still exists.

- [ ] **Step 4: Run convergence, full frontend, and API-boundary gates**

```powershell
node web/scripts/semantic-style-convergence-regression.mjs
npm.cmd --prefix web run test:frontend
git diff --exit-code e2a77c0f77d90bed4cc3a4ab5d6f29cc3ad02b1f HEAD -- web/src/api.js web/src/request.js web/src/runtimePerformance.js
git diff --exit-code f0a222fcddee752784230040e58dc938b68e8517 HEAD -- src/autotoken
git diff --check f0a222fcddee752784230040e58dc938b68e8517..HEAD
```

Expected: all commands exit `0`; the API-boundary command produces no output.

- [ ] **Step 5: Commit semantic convergence**

```powershell
git add web/src/style.css web/tailwind.config.js web/src/components/NotificationSoundControl.vue web/scripts/semantic-style-convergence-regression.mjs
git commit -m "refactor(frontend): retire dark-only compatibility styles"
```

## Final Browser, Performance, Contrast, and Artifact Verification

### Task 27: Add a Reproducible Chromium All-Route Matrix

**Files:**
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/src/App.vue`
- Modify: `web/src/components/Sidebar.vue`
- Create: `web/scripts/frontend-browser-fixture-server.mjs`
- Create: `web/scripts/frontend-browser-qa.mjs`
- Runtime output: `cleanup-artifacts/apple-light-theme-ui/screenshots/*.png`

**Interfaces:**
- Browser runner consumes the final `NAV_ITEMS` dynamically instead of maintaining a second route list.
- Every desktop/mobile navigation control exposes `:data-nav-key="item.key"`.
- `workspace-main` exposes `:data-page-key="currentPage"`.
- Fixture server exposes `GET /__metrics` and `POST /__fixture/state`, plus valid setup/auth/workspace API responses.
- No test hook participates in production business behavior.

- [ ] **Step 1: Install browser-only test dependencies**

```powershell
npm.cmd --prefix web install --save-dev playwright-core@^1.55.0 @axe-core/playwright@^4.10.0
```

Expected: package files update and command exits `0`. The runner launches `CHROME_PATH` when set, otherwise `C:\Program Files\Google\Chrome\Application\chrome.exe`.

- [ ] **Step 2: Write the fixture server and initially failing browser QA**

The fixture server must return:

- `/api/setup/status`: configurable `{ configured }`.
- `/api/auth/check`: configurable authentication result.
- `/api/accounts`: 20,000 compact rows for the performance case.
- `/api/tasks`, `/api/logs`, all payment account/link endpoints, card pool, OAuth pool/records, Trade, and configuration endpoints: valid empty or deterministic fixture shapes.
- `/__metrics`: request paths, total API requests, account requests.
- `/__fixture/state`: switches setup/login/workspace, active-task, and modal states.

The QA runner must fail until stable navigation/page hooks exist. Add this package script:

```json
"test:browser-qa": "npm run build && node scripts/frontend-browser-qa.mjs"
```

- [ ] **Step 3: Run the browser matrix to verify RED**

```powershell
npm.cmd --prefix web run test:browser-qa
```

Expected: exit `1` identifying missing `data-nav-key` or `data-page-key`.

- [ ] **Step 4: Add stable hooks and implement the complete matrix**

For every final `NAV_ITEMS` destination, run. The dynamic list must contain exactly these 24 keys after Tasks 13 and 22 add the three previously unreachable pages:

```text
dashboard, register, mailAccounts, team, cardpool, bindcard, gopay,
paypal, ideal, brazilPix, indiaUpi, kakaoPay, momoVn, gcashPh,
oauthPhones, oauthPhoneRecords, oauth, trade, cpa2sub, tasks, logs,
settings, pool, sync
```

For each destination, cover:

- Theme: system-light, system-dark, explicit light, explicit dark.
- Viewport: `1440x1000`, `390x844`, `1024x620`.

For every combination assert:

- no `pageerror` or console error;
- horizontal overflow at most 1 px;
- Axe WCAG 2 AA has no violation;
- text contrast at least 4.5:1;
- control boundary and focus indicator contrast at least 3:1;
- keyboard focus enters the page and returns after modal/sheet close;
- title, primary action or intentional empty state, and readable status exist.

Exercise setup and login separately, mobile navigation sheet, registration modal, task panel, Settings disclosure, and ThemeSwitcher keyboard behavior.

- [ ] **Step 5: Add the 20,000-account theme-switch performance measurement**

On Dashboard, switch through the title-bar control ten consecutive times. For each switch, verify the desired `data-theme` by the second animation frame. Record p95 and require `<=100 ms`. Compare `/__metrics` before/after and require request delta `0`. Require cumulative layout shift `0` and confirm the account table remains render-windowed.

- [ ] **Step 6: Produce the required screenshots**

Write explicit light and dark screenshots for each basename below, producing exactly 12 PNG files:

```text
dashboard
settings
paypal
register
mobile-navigation
dense-mobile-form
```

Output directory:

```text
cleanup-artifacts/apple-light-theme-ui/screenshots/
```

- [ ] **Step 7: Run GREEN and reopen every screenshot**

```powershell
npm.cmd --prefix web run test:browser-qa
```

Expected stdout includes:

```text
browser matrix passed
console_errors=0
horizontal_overflow=0
theme performance passed
requests_delta=0
layout_shifts=0
screenshots=12
```

Expected exit `0`. Use `view_image` to reopen all 12 absolute PNG paths and visually inspect both themes, mobile navigation, PayPal, Settings, registration, and dense mobile forms.

- [ ] **Step 8: Commit reproducible browser QA**

```powershell
git add web/package.json web/package-lock.json web/src/App.vue web/src/components/Sidebar.vue web/scripts/frontend-browser-fixture-server.mjs web/scripts/frontend-browser-qa.mjs
git commit -m "test(frontend): add all-route visual and performance matrix"
```

### Task 28: Run the Final Static and Runtime Gates

**Files:**
- Verify only; no production changes.

**Interfaces:**
- Confirms theme, workflow, operations, management, browser, bundle, backend boundary, and diff integrity together.

- [ ] **Step 1: Run all frontend scripts and the browser matrix**

```powershell
npm.cmd --prefix web run test:frontend
npm.cmd --prefix web run test:browser-qa
```

Expected: both commands exit `0`; frontend passed/total counts match; browser matrix reports zero console errors, overflow, network delta, and layout shifts.

- [ ] **Step 2: Verify bundle and API boundaries explicitly**

```powershell
node web/scripts/test-frontend-bundle.mjs
git diff --exit-code e2a77c0f77d90bed4cc3a4ab5d6f29cc3ad02b1f HEAD -- web/src/api.js web/src/request.js web/src/runtimePerformance.js
git diff --exit-code f0a222fcddee752784230040e58dc938b68e8517 HEAD -- src/autotoken
git diff --check f0a222fcddee752784230040e58dc938b68e8517..HEAD
git status --short
```

Expected: bundle reports entry at most 250 KiB and at least eight JavaScript chunks; remaining commands exit `0`; status is clean.

### Task 29: Create and Verify the Four Transaction Artifacts

**Files:**
- Create runtime artifact: `cleanup-artifacts/apple-light-theme-ui/MODIFIED_FILE.zip`
- Create runtime artifact: `cleanup-artifacts/apple-light-theme-ui/DIFF_FILE.patch`
- Create runtime artifact: `cleanup-artifacts/apple-light-theme-ui/VERIFICATION.txt`
- Create runtime artifact: `cleanup-artifacts/apple-light-theme-ui/ROLLBACK.sh`

**Interfaces:**
- Baseline HEAD: `f0a222fcddee752784230040e58dc938b68e8517`.
- Baseline tree: `92957da9ac905f15cd1cee50f9d86e01d35c1503`.
- Branch: `codex/apple-light-theme-ui`.
- Changed field: `theme_preference_and_full_frontend_visual_archetypes`.
- `ROLLBACK.sh` accepts exactly one argument: an absolute transaction-check repository path.
- Current feature worktree remains modified/final; rollback executes only in a detached verification copy.

- [ ] **Step 1: Bind baseline and final identities**

```powershell
$BASE_HEAD='f0a222fcddee752784230040e58dc938b68e8517'
$BASE_TREE='92957da9ac905f15cd1cee50f9d86e01d35c1503'
$MODIFIED_HEAD=(git rev-parse HEAD).Trim()
$MODIFIED_TREE=(git rev-parse 'HEAD^{tree}').Trim()
$ARTIFACT_DIR=(Join-Path (Get-Location) 'cleanup-artifacts\apple-light-theme-ui')
New-Item -ItemType Directory -Force -Path $ARTIFACT_DIR | Out-Null
```

Expected: all four variables are non-empty and baseline constants match `git show -s --format='%H %T' $BASE_HEAD`.

- [ ] **Step 2: Create a detached baseline copy after validating its target**

```powershell
$CHECK='D:\code\OpenSource\AutoTeam-F\.worktrees\apple-light-theme-transaction-check'
$resolvedParent=(Resolve-Path 'D:\code\OpenSource\AutoTeam-F\.worktrees').Path
if (-not ([IO.Path]::GetFullPath($CHECK).StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar))) { throw 'transaction path escaped .worktrees' }
if (Test-Path -LiteralPath $CHECK) { throw "transaction path already exists: $CHECK" }
git worktree add --detach $CHECK $BASE_HEAD
```

Expected: detached worktree created at the exact baseline HEAD, exit `0`.

- [ ] **Step 3: Run and capture BASELINE commands in the detached copy**

```powershell
npm.cmd --prefix "$CHECK\web" ci
npm.cmd --prefix "$CHECK\web" run build
node "$CHECK\web\scripts\test-frontend-bundle.mjs"
```

Expected: install, build, and bundle regression exit `0`. Preserve literal stdout/stderr and exit statuses for `VERIFICATION.txt`.

- [ ] **Step 4: Create the binary diff and modified-file archive**

Generate the patch without PowerShell output redirection so binary data remains intact:

```powershell
$DIFF=(Join-Path $ARTIFACT_DIR 'DIFF_FILE.patch')
git diff --binary --full-index "$BASE_HEAD..$MODIFIED_HEAD" --output=$DIFF
git apply --check $DIFF
git apply --stat $DIFF
```

Create `MODIFIED_FILE.zip` from every added/modified/renamed final path reported by `git diff --name-status -z $BASE_HEAD..$MODIFIED_HEAD`. Include a `MANIFEST.sha256` zip entry containing each archived relative path, size, and SHA-256. Record deleted paths in the manifest without attempting to archive missing bytes.

Use this exact archive command so creation is repeatable and rename/deletion state is represented:

```powershell
$ZIP=(Join-Path $ARTIFACT_DIR 'MODIFIED_FILE.zip')
@'
import hashlib
import subprocess
import sys
import zipfile
from pathlib import Path

base, head, output = sys.argv[1:]
root = Path.cwd()

def names(diff_filter):
    raw = subprocess.check_output([
        'git', '-c', 'core.quotepath=false', 'diff',
        '--name-only', '-z', f'--diff-filter={diff_filter}',
        f'{base}..{head}',
    ])
    return [Path(value.decode('utf-8')) for value in raw.split(b'\0') if value]

changed = names('ACMRT')
deleted = names('D')
manifest = []

with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for relative in changed:
        payload = (root / relative).read_bytes()
        archive.writestr(relative.as_posix(), payload)
        manifest.append(
            f'{hashlib.sha256(payload).hexdigest()}  {len(payload)}  {relative.as_posix()}'
        )
    manifest.extend(f'DELETED  0  {relative.as_posix()}' for relative in deleted)
    archive.writestr('MANIFEST.sha256', '\n'.join(manifest) + '\n')
'@ | python - $BASE_HEAD $MODIFIED_HEAD $ZIP
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

- [ ] **Step 5: Apply the patch to the baseline copy and run MODIFIED gates**

```powershell
git -C $CHECK apply --check --index $DIFF
git -C $CHECK apply --index $DIFF
npm.cmd --prefix "$CHECK\web" ci
npm.cmd --prefix "$CHECK\web" run test:frontend
npm.cmd --prefix "$CHECK\web" run test:browser-qa
git -C $CHECK diff --cached --check
```

Expected: applied index tree equals `$MODIFIED_TREE`; all commands exit `0`; worktree has no unstaged or untracked paths. Capture literal output and statuses.

- [ ] **Step 6: Create executable `ROLLBACK.sh` with strict preflight**

Write `cleanup-artifacts/apple-light-theme-ui/ROLLBACK.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

readonly BASE_HEAD="f0a222fcddee752784230040e58dc938b68e8517"
readonly BASE_TREE="92957da9ac905f15cd1cee50f9d86e01d35c1503"
repo="${1:?usage: ROLLBACK.sh <transaction-check-repo>}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
patch="$script_dir/DIFF_FILE.patch"

fail() {
  printf 'ROLLBACK_RESULT=FAIL\nreason=%s\n' "$1" >&2
  git status --short >&2 || true
  exit 1
}

[[ "$repo" == /* || "$repo" =~ ^[A-Za-z]:/ ]] || fail 'repo path must be absolute'
[[ -f "$patch" ]] || fail "patch missing: $patch"
cd -- "$repo"
[[ "$(git rev-parse HEAD)" == "$BASE_HEAD" ]] || fail 'pre-rollback HEAD mismatch'
tmp_index="$(mktemp)"
rm -f -- "$tmp_index"
trap 'rm -f -- "$tmp_index"' EXIT
GIT_INDEX_FILE="$tmp_index" git read-tree "$BASE_HEAD"
GIT_INDEX_FILE="$tmp_index" git apply --cached "$patch"
expected_modified_tree="$(GIT_INDEX_FILE="$tmp_index" git write-tree)"
[[ "$(git write-tree)" == "$expected_modified_tree" ]] || fail 'pre-rollback staged tree mismatch'
git diff --quiet || fail 'pre-rollback unstaged tracked changes'
[[ -z "$(git ls-files --others --exclude-standard)" ]] || fail 'pre-rollback untracked files present'
git apply --reverse --check --index "$patch" || fail 'reverse patch preflight failed'
git apply --reverse --index "$patch" || fail 'reverse patch apply failed'
[[ "$(git rev-parse HEAD)" == "$BASE_HEAD" ]] || fail 'HEAD changed'
[[ "$(git write-tree)" == "$BASE_TREE" ]] || fail 'baseline tree not restored'
[[ -z "$(git status --porcelain=v1 -uall)" ]] || fail 'worktree status is not clean'
printf 'ROLLBACK_RESULT=PASS\n'
printf 'RESTORED_HEAD=%s\n' "$(git rev-parse HEAD)"
printf 'RESTORED_TREE=%s\n' "$(git write-tree)"
printf 'RESTORED_STATUS=CLEAN\n'
```

Write the script exactly as above, then make executable and syntax-check it:

```powershell
$BASH='D:\Program Files\Git\bin\bash.exe'
$ROLLBACK_POSIX=((Join-Path $ARTIFACT_DIR 'ROLLBACK.sh') -replace '\\','/')
& $BASH --noprofile --norc -c "chmod +x '$ROLLBACK_POSIX' && test -x '$ROLLBACK_POSIX' && bash -n '$ROLLBACK_POSIX'"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

The temporary-index preflight derives the expected modified tree from the baseline plus the adjacent patch, so rollback remains self-verifying without a planning-time hash substitution.

- [ ] **Step 7: Execute rollback on the detached copy and rerun baseline behavior**

```powershell
& $BASH --noprofile --norc ((Join-Path $ARTIFACT_DIR 'ROLLBACK.sh') -replace '\\','/') ($CHECK -replace '\\','/')
npm.cmd --prefix "$CHECK\web" run build
node "$CHECK\web\scripts\test-frontend-bundle.mjs"
```

Expected literal rollback output contains `ROLLBACK_RESULT=PASS`, baseline HEAD/tree, and `RESTORED_STATUS=CLEAN`; post-rollback build and bundle regression exit `0`.

- [ ] **Step 8: Write `VERIFICATION.txt` from observed results**

Record, without paraphrasing runtime output:

- `BRANCH=codex/apple-light-theme-ui`
- `CHANGED_FIELD=theme_preference_and_full_frontend_visual_archetypes`
- all four absolute artifact paths
- baseline/modified HEAD and tree
- recorded SHA-256 values for `MODIFIED_FILE.zip`, `DIFF_FILE.patch`, and `ROLLBACK.sh`; compute and report the `VERIFICATION.txt` SHA-256 only after that file is finalized
- BASELINE, PATCH_APPLY, MODIFIED, ROLLBACK, and POST_ROLLBACK_BASELINE exact command, cwd, input, literal output, result, and exit status
- browser matrix, contrast, screenshot, request delta, layout shift, p95, bundle bytes, and chunk count
- `RESTORED_BEHAVIOR=baseline production build and bundle budget behavior restored`

- [ ] **Step 9: Reopen all four artifacts and all screenshots**

```powershell
$ZIP=(Join-Path $ARTIFACT_DIR 'MODIFIED_FILE.zip')
$DIFF=(Join-Path $ARTIFACT_DIR 'DIFF_FILE.patch')
$VERIFY=(Join-Path $ARTIFACT_DIR 'VERIFICATION.txt')
$ROLLBACK=(Join-Path $ARTIFACT_DIR 'ROLLBACK.sh')
python -c "import zipfile; p=r'$ZIP'; z=zipfile.ZipFile(p); assert z.testzip() is None; print('ZIP_REOPEN=PASS', len(z.infolist()))"
git -C $CHECK apply --check $DIFF
& 'D:\Program Files\Git\bin\bash.exe' -n ($ROLLBACK -replace '\\','/')
Get-Content -Raw $VERIFY
Get-FileHash -Algorithm SHA256 $ZIP,$DIFF,$VERIFY,$ROLLBACK
```

Expected: ZIP CRC passes, patch reopens against the restored baseline, rollback syntax passes, verification text is readable, and the ZIP/patch/rollback hashes match the values recorded inside it. The finalized Verification hash is emitted as external reopen evidence, avoiding a self-referential hash. Use `view_image` to reopen each of the 12 screenshot files by absolute path.

- [ ] **Step 10: Confirm the feature worktree remains final and clean**

```powershell
git rev-parse HEAD
git status --short
```

Expected: HEAD remains `$MODIFIED_HEAD`; tracked worktree status is clean; ignored `cleanup-artifacts/apple-light-theme-ui` retains the four artifacts and screenshots. Do not roll back the feature worktree.

- [ ] **Step 11: Reopen Verification and compose completion evidence**

Reopen `VERIFICATION.txt` after all hashes and observed results are final. The completion response must repeat the exact `BRANCH`, `CHANGED_FIELD`, four absolute artifact paths, and BASELINE/MODIFIED/ROLLBACK command, input, literal output/result, exit status, and restored behavior/status recorded in `VERIFICATION.txt`.
---

## Plan Self-Review

### Spec coverage

- [x] First-paint bootstrap, resilient controller, system/light/dark persistence and all four switcher entry points are covered by Tasks 2–7.
- [x] Semantic light/dark tokens, Tailwind alpha compatibility, shared UI primitives, focus, forced-colors and reduced-motion are covered by Tasks 4–7.
- [x] The 11 known failures are reproduced and the existing suite is restored to 43/43 before theme work in Task 1.
- [x] Dashboard, accounts, mail, tasks, history, logs and Team data workspaces are covered by Tasks 9–14 with their existing performance bounds.
- [x] Registration, bind-card, card pool, GoPay, PayPal, iDEAL, MoMo, GCash, PIX, UPI and Kakao workflows are covered by Tasks 15–21 without changing payload, polling or recovery semantics.
- [x] Pool, sync, OAuth, Settings, maintenance/support, Trade, CPA conversion and remaining diagnostics are covered by Tasks 22–26.
- [x] Every navigation destination, login/setup, modal, sheet and task-panel state is covered by the four-theme/three-viewport browser matrix in Task 27.
- [x] Entry size, chunk count, 20,000-account switching, no-request/no-layout-shift, accessibility and contrast acceptance gates are covered by Tasks 27–28.
- [x] `MODIFIED_FILE.zip`, `DIFF_FILE.patch`, `VERIFICATION.txt` and executable `ROLLBACK.sh`, including detached-copy rollback verification and artifact reopening, are covered by Task 29.

### Placeholder and interface checks

Run after every plan edit:

```powershell
$plan = 'docs/superpowers/plans/2026-08-30-apple-light-theme-full-ui-redesign.md'
$forbidden = @(
  ('T' + 'BD'),
  ('T' + 'ODO'),
  ('implement' + ' later'),
  ('fill in' + ' details'),
  ('Similar to' + ' Task'),
  ('同' + '上'),
  ('类似' + ' Task')
)
$bad = Select-String -LiteralPath $plan -Pattern ($forbidden -join '|')
if ($bad) { $bad | ForEach-Object { $_.Line }; exit 1 }
$content = Get-Content -Raw -LiteralPath $plan
foreach ($required in @(
  'createThemeController',
  'ThemeSwitcher',
  'UiSegmentedControl',
  'UiDataToolbar',
  'WorkflowWorkspace',
  'SettingsWorkspace',
  'theme_preference_and_full_frontend_visual_archetypes',
  'MODIFIED_FILE.zip',
  'DIFF_FILE.patch',
  'VERIFICATION.txt',
  'ROLLBACK.sh'
)) {
  if (-not $content.Contains($required)) { throw "missing plan contract: $required" }
}
'PLAN_SELF_REVIEW=PASS'
```

Expected literal output:

```text
PLAN_SELF_REVIEW=PASS
```

The shared names are consistent across phases: `ThemeSwitcher(mode)`, `UiStatusBadge(tone)`, `UiStatePanel(state)`, `UiSheet(open/close)`, `UiPagination(page/pageSize/totalItems)`, `WorkflowWorkspace` slots and `SettingsWorkspace(modelValue)` are consumed with the signatures defined before their first use.

## Execution Handoff

Execute one task at a time on `codex/apple-light-theme-ui`; review the diff after every commit and stop at each phase checkpoint. Use `superpowers:subagent-driven-development` for fresh implementer plus spec/correctness review per task, or `superpowers:executing-plans` for inline batches with explicit checkpoints.
