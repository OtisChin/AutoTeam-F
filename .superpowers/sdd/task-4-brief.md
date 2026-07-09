### Task 4: 注册账户页 mail.com 邮箱池 UI

**Files:**
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/api.js`
- Modify: `D:/code/OpenSource/AutoTeam-F/web/src/components/RegisterAccountPage.vue`

**Interfaces:**
- Consumes: `api.importMailAccounts(text)`
- Consumes: `api.getMailAccountsPoolStatus()`
- Consumes: `api.syncMailAccountsToAccountPool(emails)`
- Consumes: `api.loginAccountsBatch(emails, { mail_provider: "mail.com", protocol_only: true, bind_email: false })`
- Produces UI functions:
  - `isMailComProvider`
  - `loadMailComPoolStatus`
  - `importMailComAccounts`
  - `loginSelectedMailComAccounts`
  - `deleteSelectedMailComPoolEmails`

- [ ] **Step 1: Add API methods**

In `D:/code/OpenSource/AutoTeam-F/web/src/api.js`, after existing mail account methods:

```js
  getMailAccountsPoolStatus: () => request('GET', '/mail-accounts/pool-status'),
  syncMailAccountsToAccountPool: (emails = []) => request('POST', '/mail-accounts/sync-account-pool', { emails }),
```

- [ ] **Step 2: Add provider computeds**

In `D:/code/OpenSource/AutoTeam-F/web/src/components/RegisterAccountPage.vue`, add:

```js
const isMailComProvider = computed(() => String(registerForm.value.mailProvider || '').trim().toLowerCase() === 'mail.com')
```

Update:

```js
const registerProviderUsesPool = computed(() => isOutlookProvider.value || isMailComProvider.value)
const registerProviderPoolMessage = computed(() => {
  if (isOutlookProvider.value) return 'Outlook 邮箱池中选择'
  if (isMailComProvider.value) return 'mail.com 邮箱池中选择'
  return ''
})
const registerProviderUsesDomains = computed(() => !registerProviderUsesPool.value && !isPhoneCpaFlow.value)
```

Update `registerPreviewEmail`:

```js
if (isMailComProvider.value) return 'mail.com邮箱池中选择'
```

- [ ] **Step 3: Add mail.com UI state**

Near Outlook state variables, add:

```js
const mailComPoolStatus = ref(null)
const mailComPoolLoading = ref(false)
const mailComPoolError = ref('')
const mailComImportDialogOpen = ref(false)
const mailComImportContent = ref('')
const mailComImportResult = ref('')
const mailComImportResultOk = ref(true)
const mailComPoolDialogOpen = ref(false)
const mailComPoolSelectedEmails = ref([])
const mailComPoolDeleting = ref(false)
const mailComPoolLoginBusy = ref(false)

const mailComPoolItems = computed(() => Array.isArray(mailComPoolStatus.value?.items) ? mailComPoolStatus.value.items : [])
const mailComPoolVisibleEmails = computed(() => mailComPoolItems.value.map(item => item.email).filter(Boolean))
const mailComPoolSelectedCount = computed(() => mailComPoolSelectedEmails.value.length)
const mailComPoolAllVisibleSelected = computed(() => {
  const visible = mailComPoolVisibleEmails.value
  return visible.length > 0 && visible.every(email => mailComPoolSelectedEmails.value.includes(email))
})
const mailComLoginCandidateEmails = computed(() => {
  const selected = mailComPoolSelectedEmails.value.length ? mailComPoolSelectedEmails.value : mailComPoolVisibleEmails.value
  const ready = new Set(mailComPoolItems.value.filter(item => item.auth_session_status === 'ready').map(item => item.email))
  return selected.filter(email => email && !ready.has(email))
})
```

- [ ] **Step 4: Add mail.com UI methods**

Near Outlook methods, add:

```js
function openMailComImportDialog() {
  mailComImportDialogOpen.value = true
  mailComImportResult.value = ''
}

function closeMailComImportDialog() {
  if (mailComPoolLoading.value) return
  mailComImportDialogOpen.value = false
}

async function loadMailComPoolStatus() {
  if (!isMailComProvider.value || mailComPoolLoading.value) return
  mailComPoolLoading.value = true
  mailComPoolError.value = ''
  try {
    mailComPoolStatus.value = await api.getMailAccountsPoolStatus()
    const visible = new Set(mailComPoolVisibleEmails.value)
    mailComPoolSelectedEmails.value = mailComPoolSelectedEmails.value.filter(email => visible.has(email))
  } catch (e) {
    mailComPoolStatus.value = null
    mailComPoolError.value = `读取 mail.com 邮箱池失败: ${e.message}`
  } finally {
    mailComPoolLoading.value = false
  }
}

async function importMailComAccounts() {
  if (mailComPoolLoading.value) return
  const content = mailComImportContent.value.trim()
  if (!content) {
    mailComImportResult.value = '请先粘贴 mail.com 账号'
    mailComImportResultOk.value = false
    return
  }
  mailComPoolLoading.value = true
  try {
    const result = await api.importMailAccounts(content)
    mailComPoolStatus.value = result.pool_status || await api.getMailAccountsPoolStatus()
    const emails = Array.isArray(result.synced_account_pool?.emails) ? result.synced_account_pool.emails : []
    mailComImportResult.value = `导入完成：成功 ${result.imported || 0}，跳过 ${result.skipped || 0}，同步账号池 ${emails.length} 个，正在启动登录入池`
    mailComImportResultOk.value = true
    if (emails.length) {
      await api.loginAccountsBatch(emails, {
        mail_provider: 'mail.com',
        protocol_only: true,
        bind_email: false,
      })
      emit('task-started')
    }
    await loadMailComPoolStatus()
  } catch (e) {
    mailComImportResult.value = `导入失败: ${e.message}`
    mailComImportResultOk.value = false
  } finally {
    mailComPoolLoading.value = false
  }
}

function openMailComPoolDialog() {
  mailComPoolDialogOpen.value = true
  loadMailComPoolStatus()
}

function closeMailComPoolDialog() {
  if (mailComPoolDeleting.value || mailComPoolLoginBusy.value) return
  mailComPoolDialogOpen.value = false
}

function toggleMailComPoolEmail(email, checked) {
  const value = String(email || '').trim()
  if (!value) return
  const selected = new Set(mailComPoolSelectedEmails.value)
  checked ? selected.add(value) : selected.delete(value)
  mailComPoolSelectedEmails.value = Array.from(selected)
}

function toggleMailComPoolVisible(checked) {
  const selected = new Set(mailComPoolSelectedEmails.value)
  for (const email of mailComPoolVisibleEmails.value) {
    checked ? selected.add(email) : selected.delete(email)
  }
  mailComPoolSelectedEmails.value = Array.from(selected)
}

async function loginSelectedMailComAccounts() {
  if (mailComPoolLoginBusy.value) return
  const emails = mailComLoginCandidateEmails.value
  if (!emails.length) {
    setMessage('没有需要登录入池的 mail.com 账号', false)
    return
  }
  mailComPoolLoginBusy.value = true
  try {
    await api.syncMailAccountsToAccountPool(emails)
    await api.loginAccountsBatch(emails, {
      mail_provider: 'mail.com',
      protocol_only: true,
      bind_email: false,
    })
    emit('task-started')
    setMessage(`已启动 ${emails.length} 个 mail.com 账号登录入池`, true)
  } catch (e) {
    setMessage(`启动 mail.com 登录入池失败: ${e.message}`, false)
  } finally {
    mailComPoolLoginBusy.value = false
  }
}

async function deleteSelectedMailComPoolEmails() {
  if (mailComPoolDeleting.value || mailComPoolSelectedCount.value === 0) return
  const emails = [...mailComPoolSelectedEmails.value]
  const ok = window.confirm(`确认从 mail.com 邮箱池删除 ${emails.length} 个邮箱?\\n\\n只会删除 mail邮箱管理中的记录，不会删除本地账号池记录。`)
  if (!ok) return
  mailComPoolDeleting.value = true
  try {
    const result = await api.deleteMailAccounts(emails)
    mailComPoolSelectedEmails.value = []
    await loadMailComPoolStatus()
    setMessage(`已从 mail.com 邮箱池删除 ${result.deleted || 0} 个邮箱`, true)
  } catch (e) {
    setMessage(`删除 mail.com 邮箱失败: ${e.message}`, false)
  } finally {
    mailComPoolDeleting.value = false
  }
}
```

- [ ] **Step 5: Add mail.com card and dialogs**

Copy the Outlook 邮箱池 card in `RegisterAccountPage.vue` and change text/state/function names:

```vue
<div v-if="isMailComProvider" class="rounded-xl border border-gray-800 bg-gray-950/60 p-3 space-y-3">
  <div class="flex items-start justify-between gap-3">
    <div>
      <div class="text-sm font-medium text-white">mail.com 邮箱池</div>
      <div class="mt-1 text-xs text-gray-500">导入后会同步账号池，并自动启动 ChatGPT 登录获取 auth_session。</div>
    </div>
    <div class="flex flex-wrap justify-end gap-2">
      <button type="button" @click="loadMailComPoolStatus" :disabled="mailComPoolLoading" class="px-3 py-1.5 rounded-lg text-xs border bg-gray-900 hover:bg-gray-800 text-gray-300 border-gray-700 transition disabled:opacity-50">
        {{ mailComPoolLoading ? '刷新中...' : '刷新状态' }}
      </button>
      <button type="button" @click="openMailComImportDialog" class="px-3 py-1.5 rounded-lg text-xs border bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border-emerald-500/30 transition">
        导入邮箱
      </button>
      <button type="button" @click="openMailComPoolDialog" class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition">
        管理邮箱池
      </button>
    </div>
  </div>
  <div v-if="mailComPoolStatus" class="border-y border-gray-800 py-3">
    <div class="grid grid-cols-2 gap-3 sm:grid-cols-5">
      <div><div class="text-[11px] text-gray-500">邮箱池</div><div class="mt-0.5 text-sm font-medium text-white">{{ mailComPoolStatus.total }}</div></div>
      <div><div class="text-[11px] text-gray-500">可用</div><div class="mt-0.5 text-sm font-medium text-emerald-300">{{ mailComPoolStatus.available }}</div></div>
      <div><div class="text-[11px] text-gray-500">auth_session</div><div class="mt-0.5 text-sm font-medium text-blue-300">{{ mailComPoolStatus.auth_session_ready }}</div></div>
      <div><div class="text-[11px] text-gray-500">未登录</div><div class="mt-0.5 text-sm font-medium text-amber-300">{{ mailComPoolStatus.not_logged_in }}</div></div>
      <div><div class="text-[11px] text-gray-500">失败</div><div class="mt-0.5 text-sm font-medium text-red-300">{{ mailComPoolStatus.login_failed }}</div></div>
    </div>
    <div class="mt-2 text-xs text-gray-500">
      下一个可用邮箱：
      <span class="font-mono text-gray-300">{{ mailComPoolStatus.next_available_email || '无' }}</span>
    </div>
  </div>
  <div v-else-if="mailComPoolError" class="text-xs text-red-300">{{ mailComPoolError }}</div>
</div>
```

Add import and pool dialogs near the Outlook dialogs with fields:

```vue
<div v-if="mailComImportDialogOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
  <div class="w-full max-w-3xl rounded-2xl border border-gray-800 bg-gray-950 p-5 shadow-2xl">
    <div class="flex items-center justify-between">
      <h3 class="text-lg font-semibold text-white">导入 mail.com 邮箱</h3>
      <button type="button" class="text-gray-400 hover:text-white" @click="closeMailComImportDialog">×</button>
    </div>
    <p class="mt-2 text-xs text-gray-500">格式：邮箱----GPT密码----邮箱密码----refreshToken，每行一个。</p>
    <textarea v-model="mailComImportContent" rows="10" spellcheck="false" class="mt-3 w-full rounded-lg border border-gray-700 bg-gray-900 p-3 font-mono text-xs text-gray-100 focus:border-blue-500 focus:outline-none"></textarea>
    <div v-if="mailComImportResult" class="mt-3 rounded-lg px-3 py-2 text-xs" :class="mailComImportResultOk ? 'border border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border border-red-500/20 bg-red-500/10 text-red-300'">
      {{ mailComImportResult }}
    </div>
    <div class="mt-4 flex justify-end gap-2">
      <button type="button" @click="closeMailComImportDialog" class="rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">取消</button>
      <button type="button" @click="importMailComAccounts" :disabled="mailComPoolLoading" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50">
        {{ mailComPoolLoading ? '导入中...' : '导入并登录入池' }}
      </button>
    </div>
  </div>
</div>
```

The management dialog should list `mailComPoolItems` with columns: checkbox, email, status, auth_session, account_pool_status, actions. Use `loginSelectedMailComAccounts()` for the “登录并入池/重试” button and `deleteSelectedMailComPoolEmails()` for deletion.

- [ ] **Step 6: Add watchers and lifecycle**

Update Escape handler:

```js
  } else if (mailComImportDialogOpen.value) {
    closeMailComImportDialog()
  } else if (mailComPoolDialogOpen.value) {
    closeMailComPoolDialog()
  }
```

Add watcher:

```js
watch(
  isMailComProvider,
  enabled => {
    if (enabled) loadMailComPoolStatus()
  }
)
```

Update mounted hooks and task-finished refresh paths:

```js
if (isMailComProvider.value) loadMailComPoolStatus()
```

- [ ] **Step 7: Run frontend build**

Run:

```powershell
npm --prefix web run build
```

Expected: build exits with code 0.

- [ ] **Step 8: Commit Task 4**

```powershell
git add web/src/api.js web/src/components/RegisterAccountPage.vue
git commit -m "feat: add mailcom pool UI"
```

