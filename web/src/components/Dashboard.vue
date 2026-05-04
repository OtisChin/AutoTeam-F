<template>
  <div v-if="status">
    <!-- 统计卡片 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
      <div v-for="card in cards" :key="card.label"
        class="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div class="text-sm text-gray-400">{{ card.label }}</div>
        <div class="text-3xl font-bold mt-1" :class="card.color">{{ card.value }}</div>
      </div>
    </div>

    <!-- 账号表格 -->
    <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between gap-3 flex-wrap">
        <h2 class="text-lg font-semibold text-white">账号列表</h2>
        <div class="flex items-center gap-2">
          <button
            @click="exportAccounts"
            :disabled="!exportableAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="!exportableAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-cyan-600/10 text-cyan-400 border-cyan-500/30 hover:bg-cyan-600/20'">
            {{ selectedEmails.length ? `导出选中 (${selectedEmails.length})` : `导出筛选 (${filteredAccounts.length})` }}
          </button>
          <button
            @click="openCredentialExport"
            :disabled="!exportableAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="!exportableAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/10 text-emerald-400 border-emerald-500/30 hover:bg-emerald-600/20'">
            {{ selectedEmails.length ? `导出账密 (${selectedEmails.length})` : `导出账密 (${filteredAccounts.length})` }}
          </button>
          <button
            @click="exportCpaAuths"
            :disabled="!cpaExportableAccounts.length || cpaExporting"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="!cpaExportableAccounts.length || cpaExporting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-sky-600/10 text-sky-400 border-sky-500/30 hover:bg-sky-600/20'">
            {{ cpaExporting ? '导出中...' : `导出CPA认证 (${cpaExportableAccounts.length})` }}
          </button>
          <button
            @click="batchLoginAccounts"
            :disabled="loginDisabled || batchLoggingIn || !batchLoginableAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="loginDisabled || batchLoggingIn || !batchLoginableAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-blue-600/10 text-blue-400 border-blue-500/30 hover:bg-blue-600/20'">
            {{ batchLoggingIn ? '提交中...' : `批量补登录 (${batchLoginableAccounts.length})` }}
          </button>
          <button
            @click="refreshAllQuota"
            :disabled="quotaRefreshing || refreshQuotaRunning || !refreshableQuotaAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="quotaRefreshing || refreshQuotaRunning || !refreshableQuotaAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-amber-600/10 text-amber-300 border-amber-500/30 hover:bg-amber-600/20'">
            {{ refreshQuotaButtonLabel }}
          </button>
          <button
            @click="deleteInvalidCredentials"
            :disabled="deleteDisabled || invalidDeleting || !invalidCredentialAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="deleteDisabled || invalidDeleting || !invalidCredentialAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-red-600/10 text-red-300 border-red-500/30 hover:bg-red-600/20'">
            {{ invalidDeleting ? '删除中...' : `删除无效凭证 (${invalidCredentialAccounts.length})` }}
          </button>
          <button
            v-if="selectedEmails.length"
            @click="batchDelete"
            :disabled="deleteDisabled || batchDeleting"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="deleteDisabled || batchDeleting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-rose-600/10 text-rose-400 border-rose-500/30 hover:bg-rose-600/20'">
            {{ batchDeleting ? `批量删除中 ${batchProgress}` : `批量删除 (${selectedEmails.length})` }}
          </button>
          <button
            v-if="selectedEmails.length"
            @click="clearSelection"
            class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 text-gray-400 hover:text-white transition">
            取消选择
          </button>
          <button @click="syncAccounts" :disabled="syncDisabled || syncing"
            class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 transition disabled:opacity-50 text-gray-400 hover:text-white">
            {{ syncing ? '同步中...' : '同步账号' }}
          </button>
        </div>
      </div>
      <div class="px-4 py-3 border-b border-gray-800 bg-gray-950/30 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label class="relative block">
            <input
              v-model.trim="emailFilter"
              type="search"
              placeholder="按邮箱搜索"
              class="w-full sm:w-72 bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60" />
          </label>
          <select
            v-model="statusFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部状态</option>
            <option v-for="option in accountStatusOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.count }})
            </option>
          </select>
          <select
            v-model="accountTypeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部类型</option>
            <option v-for="option in accountTypeOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.count }})
            </option>
          </select>
          <select
            v-model="credentialExportFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部导出状态</option>
            <option v-for="option in credentialExportOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.count }})
            </option>
          </select>
          <select
            v-model="authCredentialFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部凭证</option>
            <option v-for="option in authCredentialOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.count }})
            </option>
          </select>
          <select
            v-model="bindDateFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部绑定日期</option>
            <option v-for="option in bindDateOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="bindStartTimeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">开始时间</option>
            <option v-for="option in bindTimeOptions" :key="`start-${option.value}`" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="bindEndTimeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">结束时间</option>
            <option v-for="option in bindTimeOptions" :key="`end-${option.value}`" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <input
            v-model.trim="bindTaskFilter"
            type="search"
            placeholder="GoPay 任务ID"
            class="w-full sm:w-40 bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60" />
          <button
            v-if="emailFilter || statusFilter || accountTypeFilter || credentialExportFilter || authCredentialFilter || bindDateFilter || bindStartTimeFilter || bindEndTimeFilter || bindTaskFilter"
            @click="clearFilters"
            class="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 text-gray-400 hover:text-white transition">
            清空筛选
          </button>
        </div>
        <div class="text-xs text-gray-500">
          显示 <span class="text-gray-300 font-mono">{{ filteredAccounts.length }}</span> / <span class="font-mono">{{ allAccounts.length }}</span>
          <span v-if="selectedEmails.length">，已选 <span class="text-cyan-300 font-mono">{{ selectedEmails.length }}</span></span>
        </div>
      </div>
      <div v-if="message" class="mx-4 mt-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="text-gray-400 text-left border-b border-gray-800">
              <th class="px-3 py-3 font-medium w-8">
                <input
                  type="checkbox"
                  :checked="allSelectableChecked"
                  :indeterminate.prop="someSelectableChecked"
                  @change="toggleSelectAll"
                  :disabled="!selectableEmails.length"
                  class="accent-rose-500 cursor-pointer"
                  title="全选/取消全选(主号除外)" />
              </th>
              <th class="px-4 py-3 font-medium">#</th>
              <th class="px-4 py-3 font-medium">邮箱</th>
              <th class="px-4 py-3 font-medium">账号类型</th>
              <th class="px-4 py-3 font-medium">状态</th>
              <th class="px-4 py-3 font-medium">账密导出</th>
              <th class="px-4 py-3 font-medium text-right">5h 剩余</th>
              <th class="px-4 py-3 font-medium text-right">周 剩余</th>
              <th class="px-4 py-3 font-medium">5h 重置</th>
              <th class="px-4 py-3 font-medium">周 重置</th>
              <th class="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!filteredAccounts.length">
              <td class="px-4 py-8 text-center text-gray-500" colspan="11">没有匹配的账号</td>
            </tr>
            <tr v-for="(acc, i) in filteredAccounts" :key="acc.email"
              class="border-b border-gray-800/50 hover:bg-gray-800/30 transition"
              :class="isSelected(acc.email) ? 'bg-rose-500/5' : ''">
              <td class="px-3 py-3">
                <input
                  v-if="!acc.is_main_account"
                  type="checkbox"
                  :checked="isSelected(acc.email)"
                  @change="toggleSelect(acc.email)"
                  class="accent-rose-500 cursor-pointer" />
              </td>
              <td class="px-4 py-3 text-gray-500">{{ i + 1 }}</td>
              <td class="px-4 py-3 font-mono text-xs">{{ acc.email }}</td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="accountTypeClass(acc.account_type)">
                  {{ accountTypeLabel(acc.account_type) }}
                </span>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="statusClass(acc.status)">
                  <span class="w-1.5 h-1.5 rounded-full" :class="dotClass(acc.status)"></span>
                  {{ statusLabel(acc.status) }}
                </span>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="credentialExportClass(acc)">
                  {{ credentialExportLabel(acc) }}
                </span>
              </td>
              <td class="px-4 py-3 text-right font-mono" :class="pctColor(quota(acc, 'primary'))">
                {{ quotaPct(acc, 'primary') }}
              </td>
              <td class="px-4 py-3 text-right font-mono" :class="pctColor(quota(acc, 'weekly'))">
                {{ quotaPct(acc, 'weekly') }}
              </td>
              <td class="px-4 py-3 text-gray-400 text-xs">{{ quotaReset(acc, 'primary') }}</td>
              <td class="px-4 py-3 text-gray-400 text-xs">{{ quotaReset(acc, 'weekly') }}</td>
              <td class="px-4 py-3 text-right space-x-2">
                <!-- 缺认证标识：账号没有 data/auths 下的 Codex auth_file → 在补登录按钮旁提示 -->
                <span
                  v-if="needsCodexLogin(acc)"
                  class="inline-block px-2 py-0.5 mr-1 rounded text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/30"
                  title="未拿到 data/auths 下的 Codex auth 文件，请点击补登录">
                  缺认证
                </span>
                <button
                  v-if="canLogin(acc)"
                  @click="loginAccount(acc.email)"
                  :disabled="loginDisabled || actionEmail === acc.email"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                  :class="loginDisabled || actionEmail === acc.email
                    ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                    : 'bg-blue-600/10 text-blue-400 border-blue-500/30 hover:bg-blue-600/20'">
                  {{ actionEmail === acc.email && actionType === 'login' ? '登录中...' : loginLabel(acc) }}
                </button>
                <button
                  v-if="!acc.is_main_account"
                  @click="openAccountTypeEditor(acc)"
                  :disabled="actionEmail === acc.email"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border transition bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 disabled:opacity-50">
                  类型
                </button>
                <button
                  v-if="acc.status === 'active' || acc.is_main_account"
                  @click="exportCodexAuth(acc.email)"
                  :disabled="actionEmail === acc.email"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border transition bg-cyan-600/10 text-cyan-400 border-cyan-500/30 hover:bg-cyan-600/20">
                  导出
                </button>
                <button
                  v-if="!acc.is_main_account"
                  @click="removeAccount(acc.email)"
                  :disabled="deleteDisabled || actionEmail === acc.email"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                  :class="deleteDisabled || actionEmail === acc.email
                    ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                    : 'bg-rose-600/10 text-rose-400 border-rose-500/30 hover:bg-rose-600/20'">
                  {{ actionEmail === acc.email && actionType === 'delete' ? '删除中...' : '删除' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 注册失败明细 -->
      <div class="mt-6 bg-gray-900 border border-gray-800 rounded-xl p-4">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h2 class="text-lg font-semibold text-white">注册失败明细</h2>
            <div class="text-xs text-gray-500 mt-0.5">未能入池的注册尝试会写在这里（add-phone / duplicate / OAuth 失败等）</div>
          </div>
          <button @click="loadFailures" :disabled="failuresLoading"
            class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            {{ failuresLoading ? '加载中...' : '刷新' }}
          </button>
        </div>
        <div v-if="failuresCounts && Object.keys(failuresCounts).length" class="flex flex-wrap gap-2 mb-3 text-xs">
          <span v-for="(cnt, cat) in failuresCounts" :key="cat"
            class="px-2 py-1 rounded border bg-gray-800 border-gray-700 text-gray-300">
            {{ cat }}: <span class="text-rose-400 font-mono">{{ cnt }}</span>
          </span>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="text-xs text-gray-500 border-b border-gray-800">
              <tr>
                <th class="text-left px-3 py-2">时间</th>
                <th class="text-left px-3 py-2">邮箱</th>
                <th class="text-left px-3 py-2">类别</th>
                <th class="text-left px-3 py-2">原因</th>
                <th class="text-left px-3 py-2">附加</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800/60 text-xs">
              <tr v-if="!failuresItems.length">
                <td class="px-3 py-4 text-gray-500" colspan="5">暂无失败记录</td>
              </tr>
              <tr v-for="(f, idx) in failuresItems" :key="idx">
                <td class="px-3 py-2 text-gray-400 font-mono">{{ fmtTs(f.timestamp) }}</td>
                <td class="px-3 py-2 text-gray-300 font-mono">{{ f.email || '-' }}</td>
                <td class="px-3 py-2">
                  <span class="px-2 py-0.5 rounded border text-[11px]"
                    :class="failureCategoryClass(f.category)">{{ f.category }}</span>
                </td>
                <td class="px-3 py-2 text-gray-400">{{ f.reason }}</td>
                <td class="px-3 py-2 text-gray-500 font-mono text-[11px]">{{ fmtFailureExtra(f) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Codex 认证导出弹窗 -->
      <div v-if="exportData" class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" @click.self="exportData = null">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-2xl max-h-[80vh] flex flex-col">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <h3 class="text-white font-semibold">Codex CLI 认证文件</h3>
            <button @click="exportData = null" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-3 overflow-y-auto flex-1">
            <div class="px-3 py-2 bg-amber-500/10 border border-amber-500/20 rounded-lg text-sm text-amber-300 space-y-2">
              <div class="font-medium">使用步骤：</div>
              <ol class="list-decimal list-inside space-y-1 text-xs text-amber-400/90">
                <li>退出当前 Codex CLI 会话</li>
                <li>删除旧文件：<code class="bg-gray-800 px-1 rounded">rm ~/.codex/auth.json</code></li>
                <li>将下方内容保存到 <code class="bg-gray-800 px-1 rounded">~/.codex/auth.json</code>（Windows: <code class="bg-gray-800 px-1 rounded">%APPDATA%\codex\auth.json</code>）</li>
                <li>重新启动 Codex CLI</li>
              </ol>
              <div class="text-xs text-amber-400/60">导出后 Codex CLI 直连 OpenAI，不走 CPA 代理，响应更快。</div>
            </div>
            <div class="relative">
              <pre class="bg-gray-950 border border-gray-800 rounded-lg p-4 text-xs font-mono text-gray-300 overflow-x-auto whitespace-pre">{{ exportJson }}</pre>
              <button @click="copyExport"
                class="absolute top-2 right-2 px-2 py-1 rounded border text-xs transition"
                :class="copied
                  ? 'bg-green-600/20 text-green-400 border-green-500/30'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white border-gray-700'">
                {{ copied ? '复制成功' : '复制' }}
              </button>
            </div>
          </div>
          <div class="px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button @click="downloadExport"
              class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition">
              下载 auth.json
            </button>
            <button @click="exportData = null"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              关闭
            </button>
          </div>
        </div>
      </div>

      <!-- 账号类型编辑弹窗 -->
      <div v-if="accountTypeEditAccount" class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" @click.self="closeAccountTypeEditor">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-md">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">编辑账号类型</h3>
              <div class="text-xs text-gray-500 font-mono mt-0.5">{{ accountTypeEditAccount.email }}</div>
            </div>
            <button @click="closeAccountTypeEditor" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label class="block text-xs text-gray-500 mb-2">账号类型</label>
              <select
                v-model="accountTypeEditValue"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option v-for="option in editableAccountTypeOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="text-xs text-gray-500 leading-relaxed">
              这里只修改本地账号类型，不会自动移出 Team、同步 CPA 或刷新 auth 文件。
            </div>
          </div>
          <div class="px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button
              @click="closeAccountTypeEditor"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              取消
            </button>
            <button
              @click="saveAccountType"
              :disabled="accountTypeSaving || !accountTypeEditValue || accountTypeEditValue === accountTypeEditAccount.account_type"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="accountTypeSaving || !accountTypeEditValue || accountTypeEditValue === accountTypeEditAccount.account_type
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-cyan-600 hover:bg-cyan-500 text-white border-cyan-500'">
              {{ accountTypeSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </div>

      <!-- 账密导出弹窗 -->
      <div v-if="credentialExportOpen" class="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-4" @click.self="closeCredentialExport">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-lg">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">导出账密 TXT</h3>
              <div class="text-xs text-gray-500 mt-0.5">
                {{ selectedEmails.length ? `将导出 ${selectedEmails.length} 个选中账号` : `将导出 ${filteredAccounts.length} 个筛选账号` }}
              </div>
              <div class="text-xs text-gray-600 mt-1">已导出的账号也会按当前选择重复导出。</div>
            </div>
            <button @click="closeCredentialExport" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label class="block text-xs text-gray-500 mb-2">每行格式</label>
              <input
                v-model="credentialLineFormat"
                type="text"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm font-mono text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
              <div class="text-xs text-gray-500 mt-2">
                可用占位符：<code class="text-gray-300">{email}</code> <code class="text-gray-300">{password}</code>
              </div>
            </div>
            <div class="bg-gray-950 border border-gray-800 rounded-lg p-3">
              <div class="text-xs text-gray-500 mb-2">预览</div>
              <pre class="text-xs text-gray-300 font-mono whitespace-pre-wrap break-all">{{ credentialPreview }}</pre>
            </div>
          </div>
          <div class="px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button
              @click="closeCredentialExport"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              取消
            </button>
            <button
              @click="downloadCredentials"
              :disabled="credentialExporting || !credentialLineFormat.trim()"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="credentialExporting || !credentialLineFormat.trim()
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500'">
              {{ credentialExporting ? '导出中...' : '导出 txt' }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Loading skeleton -->
  <div v-else-if="loading" class="space-y-4">
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
      <div v-for="i in 4" :key="i" class="bg-gray-900 border border-gray-800 rounded-xl p-4 h-20 animate-pulse"></div>
    </div>
    <div class="bg-gray-900 border border-gray-800 rounded-xl h-64 animate-pulse"></div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const props = defineProps({
  status: Object,
  loading: Boolean,
  runningTask: Object,
  adminStatus: {
    type: Object,
    default: null,
  },
})
const emit = defineEmits(['refresh', 'task-started'])

const actionEmail = ref('')
const actionType = ref('')
const syncing = ref(false)
const message = ref('')
const exportData = ref(null)
const copied = ref(false)
const messageClass = ref('')
const emailFilter = ref('')
const statusFilter = ref('')
const accountTypeFilter = ref('')
const credentialExportFilter = ref('')
const authCredentialFilter = ref('')
const bindDateFilter = ref(dateKey(new Date()))
const bindStartTimeFilter = ref('')
const bindEndTimeFilter = ref('')
const bindTaskFilter = ref('')
const accountTypeEditAccount = ref(null)
const accountTypeEditValue = ref('')
const accountTypeSaving = ref(false)
const credentialExportOpen = ref(false)
const credentialExporting = ref(false)
const cpaExporting = ref(false)
const batchLoggingIn = ref(false)
const quotaRefreshing = ref(false)
const invalidDeleting = ref(false)
const credentialLineFormat = ref('{email}-----{password}')

// 批量删除选中态:按邮箱(小写)保存,便于跨刷新复用
const selectedSet = ref(new Set())
const batchDeleting = ref(false)
const batchProgress = ref('')

// 失败日志面板状态
const failuresItems = ref([])
const failuresCounts = ref({})
const failuresLoading = ref(false)

async function loadFailures() {
  failuresLoading.value = true
  try {
    const r = await api.getRegisterFailures(50)
    failuresItems.value = r.items || []
    failuresCounts.value = r.counts || {}
  } catch (e) {
    console.error('loadFailures', e)
  } finally {
    failuresLoading.value = false
  }
}

function fmtTs(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function failureCategoryClass(cat) {
  const map = {
    phone_blocked: 'bg-rose-500/10 text-rose-400 border-rose-500/30',
    duplicate_exhausted: 'bg-orange-500/10 text-orange-400 border-orange-500/30',
    register_failed: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
    oauth_failed: 'bg-purple-500/10 text-purple-400 border-purple-500/30',
    kick_failed: 'bg-yellow-500/10 text-yellow-400 border-yellow-500/30',
    exception: 'bg-red-500/10 text-red-400 border-red-500/30',
  }
  return map[cat] || 'bg-gray-500/10 text-gray-400 border-gray-500/30'
}

function fmtFailureExtra(f) {
  const keys = ['step', 'register_attempts', 'duplicate_swaps', 'stage']
  const parts = []
  for (const k of keys) {
    if (f[k] !== undefined && f[k] !== null && f[k] !== '') parts.push(`${k}=${f[k]}`)
  }
  return parts.join(' ') || '-'
}

onMounted(loadFailures)
watch(() => props.runningTask, (cur, prev) => {
  // 有任务完成（从有到无）时自动刷新一次失败日志
  if (prev && !cur) loadFailures()
})
const adminReady = computed(() => !!props.adminStatus?.configured)
const syncDisabled = computed(() => false)
const loginDisabled = computed(() => false)
const kickDisabled = computed(() => !adminReady.value)
const deleteDisabled = computed(() => false)
const editableAccountTypeOptions = [
  { value: 'free', label: 'Free' },
  { value: 'team', label: 'Team' },
  { value: 'plus', label: 'Plus' },
  { value: 'pro', label: 'Pro' },
]

const allAccounts = computed(() => props.status?.accounts || [])

function accountBindTs(acc) {
  return Number(acc?.plus_bound_at || acc?.last_bind_at || 0) || 0
}

function isPlusAccount(acc) {
  return String(acc?.account_type || '').toLowerCase() === 'plus'
}

function dateKey(date) {
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function dateLabel(value) {
  if (!value) return ''
  const d = new Date(`${value}T00:00:00`)
  if (Number.isNaN(d.getTime())) return value
  const today = dateKey(new Date())
  const yesterdayDate = new Date()
  yesterdayDate.setDate(yesterdayDate.getDate() - 1)
  const yesterday = dateKey(yesterdayDate)
  const pad = n => String(n).padStart(2, '0')
  const label = `${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  if (value === today) return `今天 ${label}`
  if (value === yesterday) return `昨天 ${label}`
  return label
}

const bindDateOptions = computed(() => {
  const values = new Set([dateKey(new Date())])
  for (const acc of allAccounts.value) {
    const ts = accountBindTs(acc)
    if (!ts) continue
    values.add(dateKey(ts * 1000))
  }
  return Array.from(values)
    .filter(Boolean)
    .sort((a, b) => b.localeCompare(a))
    .map(value => ({ value, label: dateLabel(value) }))
})

const bindTimeOptions = computed(() => {
  const items = []
  for (let hour = 0; hour < 24; hour += 1) {
    const value = `${String(hour).padStart(2, '0')}:00`
    items.push({ value, label: value })
  }
  return items
})

function dateTimeFilterTimestamp(dateValue, timeValue, fallbackTime, seconds = 0) {
  if (!dateValue) return 0
  const timePart = timeValue || fallbackTime
  const secondPart = String(seconds).padStart(2, '0')
  const ts = new Date(`${dateValue}T${timePart}:${secondPart}`).getTime()
  return Number.isFinite(ts) ? Math.floor(ts / 1000) : 0
}

const bindTimeRange = computed(() => {
  if (!bindDateFilter.value) return { start: 0, end: 0 }
  const start = dateTimeFilterTimestamp(bindDateFilter.value, bindStartTimeFilter.value, '00:00')
  const end = bindEndTimeFilter.value
    ? dateTimeFilterTimestamp(bindDateFilter.value, bindEndTimeFilter.value, '23:59') + 3599
    : dateTimeFilterTimestamp(bindDateFilter.value, '', '23:59', 59)
  return {
    start,
    end,
  }
})

const filteredAccounts = computed(() => {
  const emailNeedle = emailFilter.value.trim().toLowerCase()
  const statusNeedle = statusFilter.value
  const typeNeedle = accountTypeFilter.value
  const exportNeedle = credentialExportFilter.value
  const authNeedle = authCredentialFilter.value
  const bindRange = bindTimeRange.value
  const bindTaskNeedle = bindTaskFilter.value.trim().toLowerCase()
  return allAccounts.value
    .map((acc, index) => ({ acc, index }))
    .filter(({ acc }) => {
    const email = String(acc?.email || '').toLowerCase()
    const status = String(acc?.status || '')
    const accountType = String(acc?.account_type || 'unknown')
    const exportStatus = acc?.credentials_exported ? 'exported' : 'unexported'
    const authStatus = hasCodexAuthFile(acc) ? 'has_auth' : 'missing_auth'
    const bindTaskId = String(acc?.last_bind_task_id || '').toLowerCase()
    if (emailNeedle && !email.includes(emailNeedle)) return false
    if (statusNeedle && status !== statusNeedle) return false
    if (typeNeedle && accountType !== typeNeedle) return false
    if (exportNeedle && exportStatus !== exportNeedle) return false
    if (authNeedle && authStatus !== authNeedle) return false
    if (bindRange.start || bindRange.end) {
      const bindTs = accountBindTs(acc)
      if (!bindTs) return false
      if (bindRange.start && bindTs < bindRange.start) return false
      if (bindRange.end && bindTs > bindRange.end) return false
    }
    if (bindTaskNeedle && !bindTaskId.includes(bindTaskNeedle)) return false
    return true
  })
    .sort((a, b) => {
      const aPlus = isPlusAccount(a.acc)
      const bPlus = isPlusAccount(b.acc)
      if (aPlus && bPlus) {
        const diff = accountBindTs(b.acc) - accountBindTs(a.acc)
        if (diff) return diff
      }
      if (aPlus !== bPlus) return aPlus ? -1 : 1
      return a.index - b.index
    })
    .map(({ acc }) => acc)
})
const accountStatusOptions = computed(() => {
  const counts = new Map()
  for (const acc of allAccounts.value) {
    const status = String(acc?.status || '')
    if (!status) continue
    counts.set(status, (counts.get(status) || 0) + 1)
  }
  return Array.from(counts.entries())
    .sort((a, b) => statusLabel(a[0]).localeCompare(statusLabel(b[0]), 'zh-Hans-CN'))
    .map(([value, count]) => ({ value, label: statusLabel(value), count }))
})
const accountTypeOptions = computed(() => {
  const counts = new Map()
  for (const acc of allAccounts.value) {
    const accountType = String(acc?.account_type || 'unknown')
    counts.set(accountType, (counts.get(accountType) || 0) + 1)
  }
  return Array.from(counts.entries())
    .sort((a, b) => accountTypeLabel(a[0]).localeCompare(accountTypeLabel(b[0]), 'zh-Hans-CN'))
    .map(([value, count]) => ({ value, label: accountTypeLabel(value), count }))
})
const credentialExportOptions = computed(() => {
  let exported = 0
  let unexported = 0
  for (const acc of allAccounts.value) {
    if (acc?.credentials_exported) exported += 1
    else unexported += 1
  }
  return [
    { value: 'unexported', label: '未导出', count: unexported },
    { value: 'exported', label: '已导出', count: exported },
  ]
})
const authCredentialOptions = computed(() => {
  let hasAuth = 0
  let missingAuth = 0
  for (const acc of allAccounts.value) {
    if (acc?.is_main_account) continue
    if (hasCodexAuthFile(acc)) hasAuth += 1
    else missingAuth += 1
  }
  return [
    { value: 'missing_auth', label: '无凭证', count: missingAuth },
    { value: 'has_auth', label: '有凭证', count: hasAuth },
  ]
})
const selectableEmails = computed(() =>
  filteredAccounts.value.filter(a => !a.is_main_account).map(a => a.email)
)
const selectedEmails = computed(() =>
  selectableEmails.value.filter(e => selectedSet.value.has(e.toLowerCase()))
)
const exportableAccounts = computed(() => {
  const selected = new Set(selectedEmails.value.map(email => email.toLowerCase()))
  if (selected.size) {
    return filteredAccounts.value.filter(acc => selected.has(String(acc.email || '').toLowerCase()))
  }
  return filteredAccounts.value
})
const batchLoginableAccounts = computed(() => {
  const selected = new Set(selectedEmails.value.map(email => email.toLowerCase()))
  const rows = selected.size
    ? filteredAccounts.value.filter(acc => selected.has(String(acc.email || '').toLowerCase()))
    : filteredAccounts.value
  return rows.filter(acc => !acc.is_main_account && needsCodexLogin(acc))
})
const cpaExportableAccounts = computed(() => {
  const selected = new Set(selectedEmails.value.map(email => email.toLowerCase()))
  const rows = selected.size
    ? filteredAccounts.value.filter(acc => selected.has(String(acc.email || '').toLowerCase()))
    : filteredAccounts.value
  return rows.filter(acc => !acc.is_main_account && hasCodexAuthFile(acc))
})
const refreshableQuotaAccounts = computed(() =>
  allAccounts.value.filter(acc =>
    !acc.is_main_account && String(acc.status || '').toLowerCase() !== 'fail'
  )
)
const invalidCredentialAccounts = computed(() =>
  allAccounts.value.filter(acc =>
    !acc.is_main_account && ['fail', 'auth_invalid'].includes(String(acc.status || '').toLowerCase())
  )
)
const refreshQuotaTask = computed(() => {
  const task = props.runningTask
  if (!task || task.command !== 'refresh-quota') return null
  if (!['running', 'pending'].includes(String(task.status || ''))) return null
  return task
})
const refreshQuotaRunning = computed(() => !!refreshQuotaTask.value)
const refreshQuotaProgress = computed(() => {
  const progress = refreshQuotaTask.value?.progress || {}
  const current = Number(progress.current || 0)
  const total = Number(progress.total || refreshQuotaTask.value?.result?.total || refreshableQuotaAccounts.value.length || 0)
  return {
    current: Number.isFinite(current) ? current : 0,
    total: Number.isFinite(total) ? total : 0,
  }
})
const refreshQuotaButtonLabel = computed(() => {
  if (refreshQuotaRunning.value) {
    const { current, total } = refreshQuotaProgress.value
    return total > 0 ? `刷新中 (${current}/${total})` : '刷新中...'
  }
  if (quotaRefreshing.value) return '提交中...'
  return `刷新凭证 (${refreshableQuotaAccounts.value.length})`
})
const credentialPreview = computed(() => {
  const sample = exportableAccounts.value[0] || { email: 'xxx@email.com', status: 'active', seat_type: 'unknown' }
  return renderCredentialPreview(credentialLineFormat.value, sample, 'password')
})
const allSelectableChecked = computed(() =>
  selectableEmails.value.length > 0 && selectedEmails.value.length === selectableEmails.value.length
)
const someSelectableChecked = computed(() =>
  selectedEmails.value.length > 0 && selectedEmails.value.length < selectableEmails.value.length
)

function isSelected(email) {
  return selectedSet.value.has((email || '').toLowerCase())
}

function toggleSelect(email) {
  const key = (email || '').toLowerCase()
  const next = new Set(selectedSet.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  selectedSet.value = next
}

function toggleSelectAll() {
  if (allSelectableChecked.value) {
    selectedSet.value = new Set()
  } else {
    selectedSet.value = new Set(selectableEmails.value.map(e => e.toLowerCase()))
  }
}

function clearSelection() {
  selectedSet.value = new Set()
}

function clearFilters() {
  emailFilter.value = ''
  statusFilter.value = ''
  accountTypeFilter.value = ''
  credentialExportFilter.value = ''
  authCredentialFilter.value = ''
  bindDateFilter.value = dateKey(new Date())
  bindStartTimeFilter.value = ''
  bindEndTimeFilter.value = ''
  bindTaskFilter.value = ''
}

function openAccountTypeEditor(acc) {
  accountTypeEditAccount.value = acc
  accountTypeEditValue.value = acc?.account_type || 'free'
}

function closeAccountTypeEditor() {
  if (accountTypeSaving.value) return
  accountTypeEditAccount.value = null
  accountTypeEditValue.value = ''
}

function openCredentialExport() {
  if (!exportableAccounts.value.length) return
  credentialExportOpen.value = true
}

function closeCredentialExport() {
  if (credentialExporting.value) return
  credentialExportOpen.value = false
}

function renderCredentialPreview(format, account, passwordValue = 'password') {
  const values = {
    email: String(account?.email || 'xxx@email.com'),
    password: passwordValue,
  }
  let line = String(format || '')
  for (const [key, value] of Object.entries(values)) {
    line = line.replaceAll(`{${key}}`, value)
  }
  return line || '-'
}

const cards = computed(() => {
  if (!props.status) return []
  const s = props.status.summary
  return [
    { label: '活跃', value: s.active, color: 'text-green-400' },
    { label: '待命', value: s.standby, color: 'text-yellow-400' },
    { label: '废弃', value: s.fail || 0, color: 'text-orange-400' },
    { label: 'Free', value: s.free || 0, color: 'text-fuchsia-400' },
    { label: 'Team', value: s.team || 0, color: 'text-violet-400' },
    { label: 'Plus', value: s.plus || 0, color: 'text-sky-400' },
    { label: 'Pro', value: s.pro || 0, color: 'text-cyan-400' },
    { label: '总计', value: s.total, color: 'text-white' },
  ]
})

function statusClass(s) {
  return {
    active: 'bg-green-500/10 text-green-400',
    exhausted: 'bg-red-500/10 text-red-400',
    standby: 'bg-yellow-500/10 text-yellow-400',
    pending: 'bg-gray-500/10 text-gray-400',
    auth_invalid: 'bg-orange-500/10 text-orange-400',
    orphan: 'bg-amber-500/10 text-amber-300',
    fail: 'bg-red-500/10 text-red-300',
  }[s] || 'bg-gray-500/10 text-gray-400'
}

function dotClass(s) {
  return {
    active: 'bg-green-400',
    exhausted: 'bg-red-400',
    standby: 'bg-yellow-400',
    pending: 'bg-gray-400',
    auth_invalid: 'bg-orange-400',
    orphan: 'bg-amber-300',
    fail: 'bg-red-300',
  }[s] || 'bg-gray-400'
}

function statusLabel(s) {
  return {
    active: 'Active',
    exhausted: 'Used up',
    standby: 'Standby',
    pending: 'Pending',
    auth_invalid: '认证失效',
    orphan: '孤立',
    fail: 'Fail/废弃',
  }[s] || s
}

function accountTypeClass(type) {
  return {
    free: 'bg-fuchsia-500/10 text-fuchsia-400',
    team: 'bg-violet-500/10 text-violet-300',
    plus: 'bg-sky-500/10 text-sky-400',
    pro: 'bg-cyan-500/10 text-cyan-300',
  }[type] || 'bg-gray-500/10 text-gray-400'
}

function accountTypeLabel(type) {
  return {
    free: 'Free',
    team: 'Team',
    plus: 'Plus',
    pro: 'Pro',
    unknown: '未知',
  }[type] || type || '未知'
}

function credentialExportLabel(acc) {
  return acc?.credentials_exported ? '已导出' : '未导出'
}

function credentialExportClass(acc) {
  return acc?.credentials_exported
    ? 'bg-emerald-500/10 text-emerald-400'
    : 'bg-gray-500/10 text-gray-400'
}

function quota(acc, type) {
  const qi = props.status?.quota_cache?.[acc.email] || acc.last_quota
  if (!qi) return null
  const pct = type === 'primary' ? qi.primary_pct : qi.weekly_pct
  return 100 - (pct || 0)
}

function quotaPct(acc, type) {
  const val = quota(acc, type)
  return val !== null ? `${val}%` : '-'
}

function quotaReset(acc, type) {
  const qi = props.status?.quota_cache?.[acc.email] || acc.last_quota
  if (!qi) return '-'
  const ts = type === 'primary' ? qi.primary_resets_at : qi.weekly_resets_at
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function pctColor(val) {
  if (val === null) return 'text-gray-500'
  if (val > 30) return 'text-green-400'
  if (val > 0) return 'text-yellow-400'
  return 'text-red-400'
}

const exportJson = computed(() => {
  if (!exportData.value) return ''
  return JSON.stringify(exportData.value.codex_auth, null, 2)
})

async function exportCodexAuth(email) {
  try {
    exportData.value = await api.getCodexAuth(email)
    copied.value = false
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function copyExport() {
  try {
    await navigator.clipboard.writeText(exportJson.value)
  } catch {
    // HTTP 下 clipboard API 不可用，用 textarea fallback
    const ta = document.createElement('textarea')
    ta.value = exportJson.value
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => { copied.value = false }, 3000)
}

function downloadExport() {
  const blob = new Blob([exportJson.value], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'auth.json'
  a.click()
  URL.revokeObjectURL(url)
}

function exportAccounts() {
  const rows = exportableAccounts.value
  if (!rows.length) return
  const payload = {
    exported_at: new Date().toISOString(),
    total: rows.length,
    filters: {
      email: emailFilter.value || '',
      status: statusFilter.value || '',
      account_type: accountTypeFilter.value || '',
      credentials_exported: credentialExportFilter.value || '',
      auth_credential: authCredentialFilter.value || '',
      bind_date: bindDateFilter.value || '',
      bind_start_time: bindStartTimeFilter.value || '',
      bind_end_time: bindEndTimeFilter.value || '',
      bind_time_start: bindTimeRange.value.start || null,
      bind_time_end: bindTimeRange.value.end || null,
      gopay_task_id: bindTaskFilter.value || '',
      selected_only: selectedEmails.value.length > 0,
    },
    accounts: rows.map(acc => ({
      email: acc.email || '',
      status: acc.status || '',
      seat_type: acc.seat_type || '',
      auth_file: acc.auth_file || '',
      auth_session_file: acc.auth_session_file || '',
      quota_exhausted_at: acc.quota_exhausted_at || null,
      quota_resets_at: acc.quota_resets_at || null,
      last_quota_check_at: acc.last_quota_check_at || null,
      last_bind_status: acc.last_bind_status || '',
      last_bind_at: acc.last_bind_at || null,
      last_checkout_url: acc.last_checkout_url || '',
      last_proxy_label: acc.last_proxy_label || '',
      last_bind_task_id: acc.last_bind_task_id || '',
      last_bind_message: acc.last_bind_message || '',
      last_bind_failure_stage: acc.last_bind_failure_stage || '',
      credentials_exported: !!acc.credentials_exported,
      credentials_exported_at: acc.credentials_exported_at || null,
      is_main_account: !!acc.is_main_account,
    })),
  }
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const scope = selectedEmails.value.length ? 'selected' : 'filtered'
  a.href = url
  a.download = `accounts-${scope}-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
  message.value = `已导出 ${rows.length} 个账号`
  messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
  setTimeout(() => { message.value = '' }, 5000)
}

async function downloadCredentials() {
  const emails = exportableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length || !credentialLineFormat.value.trim()) return

  credentialExporting.value = true
  message.value = ''
  try {
    const result = await api.exportAccountCredentials(emails, credentialLineFormat.value)
    const blob = new Blob([result.content || ''], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename || `accounts-credentials-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
    credentialExportOpen.value = false
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个无账密记录账号` : ''
    message.value = `已导出 ${result.count || 0} 条账密${missing}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    credentialExporting.value = false
    setTimeout(() => { message.value = '' }, 8000)
  }
}

function downloadBase64File(contentBase64, filename, contentType) {
  const binary = atob(contentBase64 || '')
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  const blob = new Blob([bytes], { type: contentType || 'application/octet-stream' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename || 'cpa-auths.zip'
  a.click()
  URL.revokeObjectURL(url)
}

async function exportCpaAuths() {
  const emails = cpaExportableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  cpaExporting.value = true
  message.value = ''
  try {
    const result = await api.exportAccountCpaAuths(emails)
    downloadBase64File(result.content_base64, result.filename, result.content_type)
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个无认证文件账号` : ''
    message.value = `已导出 ${result.count || 0} 个 CPA 认证文件${missing}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    cpaExporting.value = false
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function batchLoginAccounts() {
  if (loginDisabled.value || batchLoggingIn.value) return
  const emails = batchLoginableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  batchLoggingIn.value = true
  message.value = ''
  try {
    const result = await api.loginAccountsBatch(emails)
    message.value = `已提交批量补登录任务: ${result.task_id}，账号 ${emails.length} 个`
    messageClass.value = 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    batchLoggingIn.value = false
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function refreshAllQuota() {
  const emails = refreshableQuotaAccounts.value.map(acc => acc.email).filter(Boolean)
  if (quotaRefreshing.value || !emails.length) return

  quotaRefreshing.value = true
  message.value = ''
  try {
    const result = await api.refreshAccountsQuota([])
    message.value = `已提交刷新凭证任务: ${result.task_id}，默认刷新全部账号 ${emails.length} 个；401/403 会标记 Fail/废弃`
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    quotaRefreshing.value = false
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function deleteInvalidCredentials() {
  if (deleteDisabled.value || invalidDeleting.value) return
  const emails = invalidCredentialAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  const preview = emails.slice(0, 8).join('\n')
  const more = emails.length > 8 ? `\n...还有 ${emails.length - 8} 个` : ''
  const ok = window.confirm(
    `确认删除以下 ${emails.length} 个无效凭证账号？这会清理本地记录、本地/CPA认证文件，并尽量移出 Team/Invite；不会删除邮箱服务中的邮箱账号。\n\n${preview}${more}`
  )
  if (!ok) return

  invalidDeleting.value = true
  message.value = ''
  try {
    const r = await api.deleteAccountsBatch(emails, true)
    const s = r?.summary || {}
    const failed = (r?.results || []).filter(x => !x.ok)
    if (failed.length === 0) {
      message.value = `无效凭证删除完成:成功 ${s.ok}/${s.total}`
      messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    } else {
      const head = failed.slice(0, 3).map(x => `${x.email}: ${x.error}`).join('; ')
      message.value = `无效凭证删除部分失败(成功 ${s.ok}/${s.total}):${head}${failed.length > 3 ? ' …' : ''}`
      messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    }
    clearSelection()
    emit('refresh')
  } catch (e) {
    message.value = `无效凭证删除失败: ${e.message}`
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    invalidDeleting.value = false
    setTimeout(() => { message.value = '' }, 12000)
  }
}

async function syncAccounts() {
  if (syncDisabled.value) return
  syncing.value = true
  message.value = ''
  try {
    const result = await api.postSyncAccounts()
    message.value = result.message || '同步完成'
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    syncing.value = false
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function saveAccountType() {
  const account = accountTypeEditAccount.value
  const nextType = accountTypeEditValue.value
  if (!account?.email || !nextType || nextType === account.account_type) return

  accountTypeSaving.value = true
  message.value = ''
  try {
    const result = await api.updateAccountType(account.email, nextType)
    message.value = result.message || `已更新 ${account.email} 账号类型`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    accountTypeEditAccount.value = null
    accountTypeEditValue.value = ''
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    accountTypeSaving.value = false
    setTimeout(() => { message.value = '' }, 8000)
  }
}

function canLogin(acc) {
  if (acc.is_main_account) return false
  if (acc.needs_codex_login !== undefined) return !!acc.needs_codex_login
  // 兼容旧后端：只有 data/auths 下的 Codex auth 文件才算已补登录。
  if (hasCodexAuthFile(acc)) return false
  if (acc.auth_session_file) return true
  if (!acc.auth_file) return true
  return true
}

function loginLabel(acc) {
  if (needsCodexLogin(acc) || acc.status === 'auth_invalid' || acc.status === 'orphan') return '补登录'
  return '登录'
}

function hasCodexAuthFile(acc) {
  if (acc.has_codex_auth_file !== undefined) return !!acc.has_codex_auth_file
  const file = String(acc.codex_auth_file || acc.auth_file || '').replace(/\\/g, '/').toLowerCase()
  return file.includes('/data/auths/') || file.includes('/auths/codex-') || file.includes('data/auths/')
}

function needsCodexLogin(acc) {
  if (acc.is_main_account) return false
  if (acc.needs_codex_login !== undefined) return !!acc.needs_codex_login
  return !hasCodexAuthFile(acc)
}

async function loginAccount(email) {
  if (loginDisabled.value) return

  actionEmail.value = email
  actionType.value = 'login'
  message.value = ''
  try {
    const result = await api.loginAccount(email)
    message.value = `已提交 ${email} 的登录任务: ${result.task_id}`
    messageClass.value = 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    actionEmail.value = ''
    actionType.value = ''
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function kickAccount(email) {
  if (kickDisabled.value) {
    message.value = '移出 Team 需要先完成管理员登录'
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    setTimeout(() => { message.value = '' }, 8000)
    return
  }

  const ok = window.confirm(`确认将 ${email} 移出 Team？\n账号会变为 standby 状态，额度恢复后可重新复用。`)
  if (!ok) return

  actionEmail.value = email
  actionType.value = 'kick'
  message.value = ''
  try {
    const result = await api.kickAccount(email)
    message.value = result.message || `已将 ${email} 移出 Team`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    actionEmail.value = ''
    actionType.value = ''
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function removeAccount(email) {
  if (deleteDisabled.value) return

  const ok = window.confirm(`确认删除账号 ${email}？\n这会清理本地记录、本地/CPA认证文件，并尽量移出 Team/Invite；不会删除邮箱服务中的邮箱账号。`)
  if (!ok) return

  actionEmail.value = email
  actionType.value = 'delete'
  message.value = ''
  try {
    const result = await api.deleteAccount(email)
    message.value = result.message || `已删除 ${email}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    actionEmail.value = ''
    actionType.value = ''
    setTimeout(() => { message.value = '' }, 8000)
  }
}

async function batchDelete() {
  if (deleteDisabled.value) return
  if (batchDeleting.value) return
  const emails = selectedEmails.value
  if (!emails.length) return

  const preview = emails.slice(0, 8).join('\n')
  const more = emails.length > 8 ? `\n...还有 ${emails.length - 8} 个` : ''
  const ok = window.confirm(
    `确认批量删除以下 ${emails.length} 个账号？这会清理本地记录、本地/CPA认证文件，并尽量移出 Team/Invite；不会删除邮箱服务中的邮箱账号。\n\n${preview}${more}`
  )
  if (!ok) return

  batchDeleting.value = true
  batchProgress.value = `0/${emails.length}`
  message.value = ''
  try {
    const r = await api.deleteAccountsBatch(emails, true)
    const s = r?.summary || {}
    const failed = (r?.results || []).filter(x => !x.ok)
    if (failed.length === 0) {
      message.value = `批量删除完成:成功 ${s.ok}/${s.total}`
      messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    } else {
      const head = failed.slice(0, 3).map(x => `${x.email}: ${x.error}`).join('; ')
      message.value = `批量删除部分失败(成功 ${s.ok}/${s.total}):${head}${failed.length > 3 ? ' …' : ''}`
      messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    }
    clearSelection()
    emit('refresh')
  } catch (e) {
    message.value = `批量删除失败: ${e.message}`
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    batchDeleting.value = false
    batchProgress.value = ''
    setTimeout(() => { message.value = '' }, 12000)
  }
}
</script>
