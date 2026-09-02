<template>
  <div v-if="status">
    <div v-if="accountsError" class="dashboard-stale-warning" role="status">
      <div>
        <strong>账号数据暂时无法刷新</strong>
        <span>保留上次成功数据<span v-if="lastSuccessfulLabel">（{{ lastSuccessfulLabel }}）</span>，可继续查看和操作。</span>
      </div>
      <button type="button" :disabled="loading" @click="retryAccounts">
        {{ loading ? '正在重试…' : '立即重试' }}
      </button>
    </div>
    <div class="dashboard-tabs">
      <button
        v-for="tab in dashboardTabs"
        :key="tab.value"
        @click="activeDashboardTab = tab.value"
        class="dashboard-tab"
        :class="activeDashboardTab === tab.value
          ? 'dashboard-tab-active'
          : 'dashboard-tab-idle'">
        {{ tab.label }}
      </button>
    </div>

    <template v-if="activeDashboardTab === 'chatgpt'">
    <div class="dashboard-summary-grid">
      <div v-for="card in cards" :key="card.label" class="dashboard-summary-card">
        <div class="dashboard-summary-label">{{ card.label }}</div>
        <div class="dashboard-summary-value" :class="card.color">{{ card.value }}</div>
      </div>
    </div>

    <!-- 账号表格 -->
    <div class="dashboard-table-shell">
      <div class="dashboard-table-header">
        <div>
          <h2 class="text-lg font-semibold text-white">账号列表</h2>
          <p class="mt-1 text-xs text-gray-500">批量导出、OAuth授权、补登录、刷新额度和清理无效凭证。</p>
        </div>
        <div class="dashboard-actions">
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
            v-if="selectedEmails.length"
            @click="exportSelectedAccessTokens"
            :disabled="accessTokenExporting"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="accessTokenExporting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-cyan-600/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/20'">
            {{ accessTokenExporting ? '导出中...' : `导出ac (${selectedEmails.length})` }}
          </button>
          <button
            @click="openExternalAccountImport"
            :disabled="externalAccountImporting"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="externalAccountImporting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/20'">
            {{ externalAccountImporting ? '导入中...' : '导入账号' }}
          </button>
          <button
            @click="openCpaImport"
            :disabled="cpaImporting"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="cpaImporting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-purple-600/10 text-purple-300 border-purple-500/30 hover:bg-purple-600/20'">
            {{ cpaImporting ? '导入中...' : '导入CPA认证' }}
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
            @click="exportSubAuths"
            :disabled="!cpaExportableAccounts.length || subExporting"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="!cpaExportableAccounts.length || subExporting
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-indigo-600/10 text-indigo-300 border-indigo-500/30 hover:bg-indigo-600/20'">
            {{ subExporting ? '导出中...' : `导出Sub2API认证 (${cpaExportableAccounts.length})` }}
          </button>
          <button
            @click="batchOauthAuthorizeAccounts"
            :disabled="loginDisabled || batchOauthAuthorizing || !oauthBatchActionAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="loginDisabled || batchOauthAuthorizing || !oauthBatchActionAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-blue-600/10 text-blue-400 border-blue-500/30 hover:bg-blue-600/20'">
            {{ oauthBatchButtonLabel }}
          </button>
          <button
            @click="batchSetupAccountTwoFactor"
            :disabled="twoFactorSubmitting || twoFactorTaskRunning || !twoFactorSetupAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="twoFactorSubmitting || twoFactorTaskRunning
              ? 'bg-yellow-500/10 text-yellow-300 border-yellow-500/30 cursor-wait'
              : !twoFactorSetupAccounts.length
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-yellow-600/10 text-yellow-300 border-yellow-500/30 hover:bg-yellow-600/20'">
            {{ twoFactorSubmitting || twoFactorTaskRunning
                ? '设置中...'
                : `批量设置2FA (${twoFactorSetupAccounts.length})` }}
          </button>
          <button
            @click="batchReloginAccounts"
            :disabled="loginDisabled || batchReloggingIn || reloginBatchRunning || !reloginableAccounts.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="loginDisabled || batchReloggingIn || reloginBatchRunning || !reloginableAccounts.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-cyan-600/10 text-cyan-300 border-cyan-500/30 hover:bg-cyan-600/20'">
            {{ batchReloginButtonLabel }}
          </button>
          <button
            @click="oauthConfigOpen = true"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="oauthProxyEnabled
              ? 'bg-emerald-600/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/20'
              : 'bg-gray-800 text-gray-400 border-gray-700 hover:bg-gray-700 hover:text-white'">
            OAuth配置
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
            v-if="selectedEmails.length"
            @click="openBatchAccountEditor"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="'bg-slate-600/10 text-slate-200 border-slate-500/30 hover:bg-slate-600/20'">
            批量修改账号 ({{ selectedEmails.length }})
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
            @click="batchUpdateExportStatus(true)"
            :disabled="exportStatusUpdating"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="exportStatusUpdating
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/10 text-emerald-300 border-emerald-500/30 hover:bg-emerald-600/20'">
            标记已导出 ({{ selectedEmails.length }})
          </button>
          <button
            v-if="selectedEmails.length"
            @click="batchUpdateExportStatus(false)"
            :disabled="exportStatusUpdating"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="exportStatusUpdating
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-gray-700/70 text-gray-300 border-gray-600 hover:bg-gray-700'">
            标记未导出 ({{ selectedEmails.length }})
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
          <button @click="syncToAccountHub" :disabled="hubSyncing || !selectedEmails.length"
            class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
            :class="hubSyncing || !selectedEmails.length
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-violet-600/10 text-violet-300 border-violet-500/30 hover:bg-violet-600/20'">
            {{ hubSyncing ? '上传中...' : `同步到账号Hub (${selectedEmails.length})` }}
          </button>
        </div>
      </div>
      <!-- OAuth 配置弹窗 -->
      <AccessibleModal v-if="oauthConfigOpen" label="OAuth 配置" @close="oauthConfigOpen = false">
        <div class="flex max-h-[85vh] w-full max-w-3xl flex-col rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
          <!-- Header -->
          <div class="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-4">
            <div>
              <h3 class="text-lg font-semibold text-white">OAuth 配置</h3>
              <p class="mt-1 text-xs text-gray-500">配置 OAuth授权/补登录代理和绑定方式；绑定邮箱/绑定手机号二选一。</p>
            </div>
            <button @click="oauthConfigOpen = false" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700">关闭</button>
          </div>
          <!-- Tabs -->
          <div class="flex border-b border-gray-800 px-5 pt-3">
            <button
              @click="oauthConfigTab = 'proxy'"
              class="px-4 py-2 text-sm font-medium border-b-2 transition"
              :class="oauthConfigTab === 'proxy' ? 'text-cyan-300 border-cyan-500' : 'text-gray-500 border-transparent hover:text-gray-300'">
              OAuth授权/补登录代理
            </button>
            <button
              @click="oauthConfigTab = 'email'"
              class="px-4 py-2 text-sm font-medium border-b-2 transition"
              :class="oauthConfigTab === 'email' ? 'text-cyan-300 border-cyan-500' : 'text-gray-500 border-transparent hover:text-gray-300'">
              邮箱绑定
            </button>
            <button
              @click="oauthConfigTab = 'phone'"
              class="px-4 py-2 text-sm font-medium border-b-2 transition"
              :class="oauthConfigTab === 'phone' ? 'text-cyan-300 border-cyan-500' : 'text-gray-500 border-transparent hover:text-gray-300'">
              手机号绑定
            </button>
            <button
              @click="oauthConfigTab = 'phone_sms'"
              class="px-4 py-2 text-sm font-medium border-b-2 transition"
              :class="oauthConfigTab === 'phone_sms' ? 'text-cyan-300 border-cyan-500' : 'text-gray-500 border-transparent hover:text-gray-300'">
              手机号接码
            </button>
          </div>
          <!-- Body -->
          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <!-- Proxy Tab -->
            <div v-if="oauthConfigTab === 'proxy'">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="text-sm font-semibold text-cyan-100">OAuth授权/补登录代理</div>
                  <div class="mt-1 text-xs text-gray-500">用于仪表盘单个/批量 OAuth授权和补登录；不开启时保持直连。</div>
                </div>
                <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                  <input v-model="oauthProxyEnabled" type="checkbox" class="h-4 w-4 rounded border-gray-700 bg-gray-950 text-cyan-500 focus:ring-cyan-500/30" />
                  启用代理
                </label>
              </div>
              <div class="mt-4 grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)]">
                <div>
                  <label class="text-xs text-gray-500">登录模式</label>
                  <select v-model="oauthBrowserMode" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                    <option value="protocol">协议模式</option>
                    <option value="roxy">RoxyBrowser 模式</option>
                  </select>
                </div>
                <div class="rounded-lg border border-gray-800 bg-gray-950/60 px-3 py-2 text-xs text-gray-400">
                  {{ oauthBrowserMode === 'roxy' ? 'OAuth授权/补登录将使用设置页的 RoxyBrowser 配置打开浏览器，适合协议风控较强时手动使用。' : '默认协议模式，速度快；遇到风控时可手动切换 RoxyBrowser。' }}
                </div>
              </div>
              <div v-if="oauthProxyEnabled" class="mt-4 grid gap-3 lg:grid-cols-[180px_minmax(0,1fr)]">
                <div>
                  <label class="text-xs text-gray-500">代理模式</label>
                  <select v-model="oauthProxyMode" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                    <option value="single">单条代理</option>
                    <option value="pool">动态代理池</option>
                    <option value="api">代理 API 轮换</option>
                  </select>
                </div>
                <div v-if="oauthProxyMode === 'single'">
                  <label class="text-xs text-gray-500">代理地址</label>
                  <input v-model.trim="oauthProxyUrl" type="text" placeholder="hostname:port:username:password / socks5://user:pass@host:port" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60" />
                </div>
                <div v-else-if="oauthProxyMode === 'pool'">
                  <label class="text-xs text-gray-500">代理池，一行一个</label>
                  <textarea v-model.trim="oauthProxyPoolText" rows="3" placeholder="hostname:port:username:password&#10;socks5://user:pass@host:port" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60"></textarea>
                </div>
                <div v-else class="grid gap-3 sm:grid-cols-[180px_120px_minmax(0,1fr)]">
                  <div>
                    <label class="text-xs text-gray-500">供应商</label>
                    <select v-model="oauthProxyApiProvider" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                      <option value="cliproxy">cliproxy</option>
                      <option value="1024proxy">1024proxy</option>
                    </select>
                  </div>
                  <div>
                    <label class="text-xs text-gray-500">国家</label>
                    <input v-model.trim="oauthProxyApiCountry" type="text" placeholder="US / JP / GB" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60" />
                  </div>
                  <div>
                    <label class="text-xs text-gray-500">连接入口代理，可选</label>
                    <input v-model.trim="oauthProxyUrl" type="text" placeholder="API 未返回可直接连接地址时，用这里的代理入口" class="mt-1 w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60" />
                  </div>
                </div>
                <div class="lg:col-span-2 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
                  <span>{{ oauthProxySummary }}</span>
                  <button @click="resetOauthProxyConfig" class="px-2.5 py-1 rounded-md border border-gray-700 bg-gray-900 text-gray-400 hover:text-white hover:bg-gray-800 transition">清空代理配置</button>
                </div>
              </div>
            </div>
            <!-- Email Binding Tab -->
            <div v-if="oauthConfigTab === 'email'">
              <div class="text-sm font-semibold text-amber-100">邮箱绑定配置</div>
              <div class="mt-1 text-xs text-gray-500">选择邮箱绑定时使用这些邮件供应商和域名参数；如果启用手机号绑定，OAuth授权/补登录请求不会同时绑定邮箱。</div>
              <div class="mt-4 space-y-4">
                <div>
                  <label class="block text-xs text-gray-500 mb-1">邮件供应商</label>
                  <select v-model="oauthEmailMailProvider" :disabled="oauthEmailLoading" class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/60">
                    <option v-for="opt in oauthEmailMailProviderOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                  </select>
                  <div class="mt-1 text-xs text-gray-500">选择注册后用于绑定邮箱的邮件供应商；具体 API Key / token 在"设置 → 邮件 Provider"里配置。</div>
                </div>
                <template v-if="oauthEmailMailProvider === 'luckmail'">
                  <div class="grid grid-cols-2 gap-3">
                    <div>
                      <label class="block text-xs text-gray-500 mb-1">LuckMail 邮箱类型</label>
                      <select v-model="oauthEmailLuckmailEmailType" :disabled="oauthEmailLoading" class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/60">
                        <option v-for="opt in luckmailEmailTypeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </select>
                    </div>
                    <div>
                      <label class="block text-xs text-gray-500 mb-1">LuckMail 首选域名</label>
                      <select v-model="oauthEmailLuckmailDomain" :disabled="oauthEmailLoading" class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/60">
                        <option v-for="opt in luckmailDomainOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </select>
                    </div>
                  </div>
                  <div class="text-xs text-gray-500">选择 LuckMail 的邮箱类型和首选域名；账号池为空时按这里的配置自动购买。</div>
                </template>
                <div v-if="oauthEmailMailProvider && oauthEmailMailProvider !== 'luckmail' && oauthEmailMailProvider !== 'outlook'">
                  <label class="block text-xs text-gray-500 mb-1">注册域名</label>
                  <select v-model="oauthEmailDomain" class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-amber-500/30 focus:border-amber-500/60">
                    <option v-for="domain in oauthEmailDomainOptions" :key="domain" :value="domain">@{{ domain }}</option>
                  </select>
                  <div class="mt-1 text-xs text-gray-500">注册临时邮箱使用的域名。</div>
                </div>
              </div>
            </div>
            <!-- Phone Binding Tab -->
            <div v-if="oauthConfigTab === 'phone'">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="text-sm font-semibold text-emerald-100">手机号绑定</div>
                  <div class="mt-1 text-xs text-gray-500">开启后，仪表盘单个/批量 OAuth授权和补登录遇到 add-phone 会自动绑定手机号。</div>
                </div>
                <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                  <input v-model="oauthBindPhone" type="checkbox" class="h-4 w-4 rounded border-gray-700 bg-gray-950 text-emerald-500 focus:ring-emerald-500/30" />
                  启用手机号绑定（关闭则绑定邮箱）
                </label>
              </div>
              <div class="mt-4 rounded-lg border border-gray-800 bg-gray-950/70 p-3 text-xs text-gray-400">
                <div>当前模式：<span :class="oauthBindPhone ? 'text-emerald-300' : 'text-amber-300'">{{ oauthBindPhone ? '绑定手机号' : '绑定邮箱' }}</span></div>
                <div class="mt-1">二选一：启用手机号绑定时，会发送 bind_phone=true、bind_email=false；关闭时发送 bind_email=true、bind_phone=false。</div>
                <div class="mt-1">接码来源使用“手机号接码”页签保存的配置，例如手机号池、hero-sms、smsbower、SMSCloud、Oasis 或 TuJie。</div>
              </div>
            </div>
            <!-- Phone SMS Tab -->
            <div v-if="oauthConfigTab === 'phone_sms'" class="space-y-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div class="text-sm font-semibold text-emerald-100">OAuth 手机号接码配置</div>
                  <div class="mt-1 text-xs text-gray-500">用于 OAuth授权/补登录需要 add-phone 时取号和收验证码；保存后写入后端 OAuth 接码配置。</div>
                </div>
                <span
                  class="min-w-[72px] rounded-full border px-3 py-1.5 text-center text-xs whitespace-nowrap"
                  :class="oauthPhoneSmsConfigured
                    ? 'bg-green-500/10 text-green-400 border-green-500/20'
                    : 'bg-gray-800 text-gray-400 border-gray-700'">
                  {{ oauthPhoneSmsConfigured ? '已配置' : '未配置' }}
                </span>
              </div>

              <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <label class="block text-xs text-gray-500 mb-1">手机号来源</label>
                  <select
                    v-model="oauthPhoneSmsForm.provider"
                    :disabled="oauthPhoneSmsLoading || oauthPhoneSmsSaving"
                    class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60">
                    <option value="phone_pool">OAuth 手机号池</option>
                    <option value="hero_sms">hero-sms</option>
                    <option value="smsbower">smsbower</option>
                    <option value="smscloud">SMSCloud</option>
                    <option value="oasis">Oasis CDK</option>
                    <option value="tujie">TuJie CDK</option>
                  </select>
                  <div class="mt-1 text-xs text-gray-500">手机号池适合固定号码；hero-sms / smsbower / SMSCloud 按国家买号；Oasis / TuJie 使用 CDK 池兑换号码。</div>
                </div>
                <div>
                  <label class="block text-xs text-gray-500 mb-1">固定参数</label>
                  <div class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-300">
                    服务：OpenAI（service: dr）
                  </div>
                  <div class="mt-1 text-xs text-gray-500">国家会随 OAuth授权/补登录请求传给后端；列表来自所选接码供应商。</div>
                </div>
                <div v-if="['hero_sms', 'smsbower', 'smscloud'].includes(oauthPhoneSmsForm.provider)">
                  <label class="block text-xs text-gray-500 mb-1">手机号国家</label>
                  <div class="relative">
                    <input
                      v-model="oauthPhoneSmsCountrySearch"
                      :disabled="oauthPhoneSmsLoading || oauthPhoneSmsSaving || oauthPhoneSmsCountriesLoading"
                      type="search"
                      autocomplete="off"
                      :placeholder="oauthPhoneSmsCountriesLoading ? '国家列表加载中...' : '搜索国家名称或 ID'"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 pr-9 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60 disabled:opacity-60"
                      @focus="openOauthPhoneSmsCountryDropdown"
                      @input="handleOauthPhoneSmsCountryInput"
                      @blur="closeOauthPhoneSmsCountryDropdownSoon"
                    />
                    <button
                      type="button"
                      :disabled="oauthPhoneSmsLoading || oauthPhoneSmsSaving || oauthPhoneSmsCountriesLoading"
                      class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded px-1.5 py-1 text-xs text-gray-400 transition hover:bg-gray-800 hover:text-white disabled:pointer-events-none disabled:opacity-40"
                      @mousedown.prevent
                      @click="toggleOauthPhoneSmsCountryDropdown">
                      ▾
                    </button>
                    <div
                      v-if="oauthPhoneSmsCountryDropdownOpen"
                      class="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-gray-800 bg-gray-950 shadow-xl shadow-black/40">
                      <button
                        v-for="option in oauthPhoneSmsCountryOptionsForSelect"
                        :key="option.value"
                        type="button"
                        class="block w-full px-3 py-2 text-left text-sm transition hover:bg-gray-900"
                        :class="option.value === currentOauthPhoneSmsCountry ? 'bg-emerald-600/15 text-emerald-200' : 'text-gray-200'"
                        @mousedown.prevent="selectOauthPhoneSmsCountry(option)">
                        <span class="block truncate">{{ option.label }}</span>
                      </button>
                      <div v-if="!oauthPhoneSmsCountryOptionsForSelect.length" class="px-3 py-2 text-sm text-gray-500">
                        没有匹配的国家
                      </div>
                    </div>
                  </div>
                  <div class="mt-1 text-xs text-gray-500">支持按国家名称或供应商国家 ID 搜索，例如“英国”或“16”。</div>
                  <div v-if="oauthPhoneSmsCountryError" class="mt-1 text-xs text-amber-300">{{ oauthPhoneSmsCountryError }}</div>
                </div>

                <template v-if="oauthPhoneSmsForm.provider === 'hero_sms'">
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">
                      hero-sms API Key
                      <span v-if="oauthPhoneSmsStatus.hero_sms_api_key_present" class="ml-1 text-xs text-green-400">已保存</span>
                    </label>
                    <input
                      v-model="oauthPhoneSmsForm.hero_sms_api_key"
                      type="password"
                      autocomplete="off"
                      :placeholder="oauthPhoneSmsStatus.hero_sms_api_key_masked || '留空则保留现有配置'"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">hero-sms 价格模式</label>
                    <select
                      v-model="oauthPhoneSmsForm.hero_sms_price_mode"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60">
                      <option value="lowest">优先最低价格</option>
                      <option value="ceiling">仅限制最高价格</option>
                    </select>
                    <div class="mt-1 text-xs text-gray-500">会在价格区间内，从最低可用档位开始取号。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">hero-sms 最低价格</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.hero_sms_min_price"
                      type="text"
                      inputmode="decimal"
                      autocomplete="off"
                      placeholder="例如 0.1，留空不限下限"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    <div class="mt-1 text-xs text-gray-500">填 0.1 时，0.1 以下的号码不会取。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">hero-sms 最高价格</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.hero_sms_max_price"
                      type="text"
                      inputmode="decimal"
                      autocomplete="off"
                      placeholder="例如 0.045，留空不限价"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    <div class="mt-1 text-xs text-gray-500">作为价格上限；留空则不限上限。</div>
                  </div>
                </template>

                <template v-if="oauthPhoneSmsForm.provider === 'smscloud'">
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">
                      SMSCloud API Key
                      <span v-if="oauthPhoneSmsStatus.smscloud_api_key_present" class="ml-1 text-xs text-green-400">已保存</span>
                    </label>
                    <input
                      v-model="oauthPhoneSmsForm.smscloud_api_key"
                      type="password"
                      autocomplete="off"
                      :placeholder="oauthPhoneSmsStatus.smscloud_api_key_masked || '留空则保留现有配置'"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">SMSCloud 最低价格</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.smscloud_min_price"
                      type="text"
                      inputmode="decimal"
                      autocomplete="off"
                      placeholder="例如 0.05，留空不限下限"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    <div class="mt-1 text-xs text-gray-500">实际扣费低于该价格会取消订单，不继续使用。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">SMSCloud 最高价格</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.smscloud_max_price"
                      type="text"
                      inputmode="decimal"
                      autocomplete="off"
                      placeholder="例如 0.08，留空按默认价格"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    <div class="mt-1 text-xs text-gray-500">作为 SMSCloud flexible 的 maxPrice。</div>
                  </div>
                </template>

                <template v-if="oauthPhoneSmsForm.provider === 'smsbower'">
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">
                      smsbower API Key
                      <span v-if="oauthPhoneSmsStatus.smsbower_api_key_present" class="ml-1 text-xs text-green-400">已保存</span>
                    </label>
                    <input
                      v-model="oauthPhoneSmsForm.smsbower_api_key"
                      type="password"
                      autocomplete="off"
                      :placeholder="oauthPhoneSmsStatus.smsbower_api_key_masked || '留空则保留现有配置'"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">smsbower 价格模式</label>
                    <select
                      v-model="oauthPhoneSmsForm.smsbower_price_mode"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60">
                      <option value="lowest">优先最低价格</option>
                      <option value="ceiling">仅限制最高价格</option>
                    </select>
                    <div class="mt-1 text-xs text-gray-500">会查询 provider 价格列表，并在价格区间内优先使用最低价 provider。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">smsbower 最低价格</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.smsbower_min_price"
                      type="text"
                      inputmode="decimal"
                      autocomplete="off"
                      placeholder="例如 0.1，留空不限下限"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    <div class="mt-1 text-xs text-gray-500">填 0.1 时，0.1 以下的 provider 不会取。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">smsbower 最高价格</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.smsbower_max_price"
                      type="text"
                      inputmode="decimal"
                      autocomplete="off"
                      placeholder="例如 0.045，留空不限价"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    <div class="mt-1 text-xs text-gray-500">作为价格上限；留空则不限上限。</div>
                  </div>
                </template>

                <template v-if="oauthPhoneSmsForm.provider === 'oasis'">
                  <div class="md:col-span-2">
                    <label class="block text-xs text-gray-500 mb-1">
                      Oasis CDK 池
                      <span v-if="oauthPhoneSmsStatus.oasis_sms_cdk_count" class="ml-1 text-xs text-green-400">已保存 {{ oauthPhoneSmsStatus.oasis_sms_cdk_count }} 个</span>
                    </label>
                    <textarea
                      v-model.trim="oauthPhoneSmsForm.oasis_sms_cdks"
                      rows="5"
                      spellcheck="false"
                      autocomplete="off"
                      placeholder="一行一个或粘贴多个 CDK，例如 SMS-6L2A-6TAH-Q7BA"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 font-mono text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60"></textarea>
                    <div class="mt-1 text-xs text-gray-500">每个 CDK 只对应一个号码和验证码，注册成功后会保存 CDK 与账号的映射。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">
                      CDK 文件
                      <span v-if="oauthPhoneSmsStatus.oasis_sms_cdk_file_present" class="ml-1 text-xs text-green-400">已配置</span>
                    </label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.oasis_sms_cdk_file"
                      type="text"
                      autocomplete="off"
                      placeholder="例如 data/oasis_cdks.txt"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">Oasis API 地址</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.oasis_sms_base_url"
                      type="text"
                      autocomplete="off"
                      placeholder="https://sms.oapi.vip"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">账号映射文件</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.oasis_sms_account_map_file"
                      type="text"
                      autocomplete="off"
                      placeholder="oasis-cdk-accounts.jsonl"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div class="grid grid-cols-2 gap-3">
                    <div>
                      <label class="block text-xs text-gray-500 mb-1">轮询次数</label>
                      <input
                        v-model.trim="oauthPhoneSmsForm.oasis_sms_poll_attempts"
                        type="number"
                        min="1"
                        autocomplete="off"
                        placeholder="24"
                        class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-500 mb-1">轮询间隔 ms</label>
                      <input
                        v-model.trim="oauthPhoneSmsForm.oasis_sms_poll_interval_ms"
                        type="number"
                        min="500"
                        autocomplete="off"
                        placeholder="5000"
                        class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    </div>
                  </div>
                </template>
                <template v-if="oauthPhoneSmsForm.provider === 'tujie'">
                  <div class="md:col-span-2">
                    <label class="block text-xs text-gray-500 mb-1">
                      TuJie CDK 池
                      <span v-if="oauthPhoneSmsStatus.tujie_sms_cdk_count" class="ml-1 text-xs text-green-400">已保存 {{ oauthPhoneSmsStatus.tujie_sms_cdk_count }} 个</span>
                    </label>
                    <textarea
                      v-model.trim="oauthPhoneSmsForm.tujie_sms_cdks"
                      rows="5"
                      spellcheck="false"
                      autocomplete="off"
                      placeholder="一行一个或粘贴多个 CDK，例如 SMS-AE4H6TLEZV5H69SJGQ"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 font-mono text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60"></textarea>
                    <div class="mt-1 text-xs text-gray-500">每个 CDK 只对应一个号码和验证码，OAuth 成功后会保存 CDK 与账号的映射。</div>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">
                      CDK 文件
                      <span v-if="oauthPhoneSmsStatus.tujie_sms_cdk_file_present" class="ml-1 text-xs text-green-400">已配置</span>
                    </label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.tujie_sms_cdk_file"
                      type="text"
                      autocomplete="off"
                      placeholder="例如 data/tujie_cdks.txt"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">TuJie 取码页面地址</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.tujie_sms_base_url"
                      type="text"
                      autocomplete="off"
                      placeholder="填写 TuJie 页面地址；支持 {cdk} 占位符"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-500 mb-1">账号映射文件</label>
                    <input
                      v-model.trim="oauthPhoneSmsForm.tujie_sms_account_map_file"
                      type="text"
                      autocomplete="off"
                      placeholder="tujie-cdk-accounts.jsonl"
                      class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                  </div>
                  <div class="grid grid-cols-2 gap-3">
                    <div>
                      <label class="block text-xs text-gray-500 mb-1">轮询次数</label>
                      <input
                        v-model.trim="oauthPhoneSmsForm.tujie_sms_poll_attempts"
                        type="number"
                        min="1"
                        autocomplete="off"
                        placeholder="24"
                        class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-500 mb-1">轮询间隔 ms</label>
                      <input
                        v-model.trim="oauthPhoneSmsForm.tujie_sms_poll_interval_ms"
                        type="number"
                        min="500"
                        autocomplete="off"
                        placeholder="5000"
                        class="w-full rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60" />
                    </div>
                  </div>
                </template>
              </div>

              <div class="flex justify-end gap-3">
                <button
                  @click="loadOauthPhoneSmsConfig"
                  :disabled="oauthPhoneSmsLoading || oauthPhoneSmsSaving"
                  class="rounded-lg border border-gray-700 bg-gray-800 px-4 py-2 text-sm text-gray-200 transition hover:bg-gray-700 disabled:opacity-50">
                  {{ oauthPhoneSmsLoading ? '刷新中...' : '刷新接码配置' }}
                </button>
                <button
                  @click="saveOauthPhoneSmsConfig"
                  :disabled="oauthPhoneSmsSaving"
                  class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white transition hover:bg-emerald-500 disabled:opacity-50">
                  {{ oauthPhoneSmsSaving ? '保存中...' : '保存接码配置' }}
                </button>
              </div>
            </div>
          </div>
          <!-- Footer -->
          <div class="flex justify-end gap-3 border-t border-gray-800 px-5 py-4">
            <button @click="oauthConfigOpen = false" class="px-4 py-2 text-sm rounded-lg border border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700 transition">关闭</button>
            <button @click="saveOauthConfig" :disabled="oauthEmailSaving || oauthPhoneSmsSaving" class="px-4 py-2 text-sm rounded-lg bg-cyan-600 text-white hover:bg-cyan-500 disabled:opacity-50 transition">{{ oauthEmailSaving || oauthPhoneSmsSaving ? '保存中...' : '保存配置' }}</button>
          </div>
        </div>
      </AccessibleModal>
      <div class="dashboard-filter-bar">
        <div class="dashboard-filters">
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
            v-model="twoFactorFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部2FA状态</option>
            <option value="enabled">已设置 ({{ twoFactorCounts.enabled }})</option>
            <option value="disabled">未设置 ({{ twoFactorCounts.disabled }})</option>
          </select>
          <select
            v-model="trialFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60">
            <option value="">全部试用资格</option>
            <option value="eligible">可试用 ({{ trialEligibleCount }})</option>
            <option value="not_eligible">不可试用</option>
          </select>
          <select
            v-model="bindProviderFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部绑定渠道</option>
            <option v-for="option in accountBindProviderFilterOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.count }})
            </option>
          </select>
          <select
            v-model="registerDateFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部注册日期</option>
            <option v-for="option in registerDateOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="registerStartTimeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">注册开始</option>
            <option v-for="option in bindTimeOptions" :key="`register-start-${option.value}`" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="registerEndTimeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">注册结束</option>
            <option v-for="option in bindTimeOptions" :key="`register-end-${option.value}`" :value="option.value">
              {{ option.label }}
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
            v-model="exportDateFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部导出日期</option>
            <option v-for="option in exportDateOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="exportStartTimeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">导出开始</option>
            <option v-for="option in bindTimeOptions" :key="`export-start-${option.value}`" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="exportEndTimeFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">导出结束</option>
            <option v-for="option in bindTimeOptions" :key="`export-end-${option.value}`" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <select
            v-model="accountHubSyncFilter"
            class="bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
            <option value="">全部同步状态</option>
            <option v-for="option in accountHubSyncOptions" :key="option.value" :value="option.value">
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
          <button
            v-if="emailFilter || statusFilter || accountTypeFilter || twoFactorFilter || trialFilter || bindProviderFilter || registerDateFilter || registerStartTimeFilter || registerEndTimeFilter || credentialExportFilter || exportDateFilter || exportStartTimeFilter || exportEndTimeFilter || accountHubSyncFilter || authCredentialFilter || bindDateFilter || bindStartTimeFilter || bindEndTimeFilter"
            @click="clearFilters"
            class="px-3 py-2 bg-gray-800 hover:bg-gray-700 text-xs rounded-lg border border-gray-700 text-gray-400 hover:text-white transition">
            清空筛选
          </button>
        </div>
        <div class="text-xs text-gray-500">
          显示
          <span class="text-gray-300 font-mono">{{ accountPageStartDisplay }}-{{ accountPageEndDisplay }}</span>
          / <span class="text-gray-300 font-mono">{{ accountFilteredTotal }}</span>
          / <span class="font-mono">{{ accountPoolTotal }}</span>
          <span v-if="selectedEmails.length">，已选 <span class="text-blue-400 font-mono">{{ selectedEmails.length }}</span></span>
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
              <th class="px-4 py-3 font-medium min-w-56">邮箱</th>
              <th class="px-4 py-3 font-medium">账号类型</th>
              <th class="px-4 py-3 font-medium">状态</th>
              <th class="px-4 py-3 font-medium whitespace-nowrap">2FA</th>
              <th class="px-4 py-3 font-medium">绑定渠道</th>
              <th class="px-4 py-3 font-medium">账密导出</th>
              <th class="px-4 py-3 font-medium">Hub同步</th>
              <th class="px-4 py-3 font-medium text-right">5h 剩余</th>
              <th class="px-4 py-3 font-medium text-right">周 剩余</th>
              <th class="px-4 py-3 font-medium">注册时间</th>
              <th class="px-4 py-3 font-medium">激活时间</th>
              <th class="px-4 py-3 font-medium text-right">
                <div class="inline-flex items-center justify-end gap-2">
                  <span>操作</span>
                  <button
                    type="button"
                    @click="toggleAccountDisplayOrder"
                    class="inline-flex h-6 min-w-6 items-center justify-center rounded-md border px-1.5 text-[11px] font-semibold transition"
                    :class="accountDisplayOrder === 'desc'
                      ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'
                      : 'border-gray-700 bg-gray-800/70 text-gray-400 hover:border-gray-600 hover:text-gray-200'"
                    :title="accountDisplayOrder === 'desc' ? '当前倒序显示，点击切换正序' : '当前正序显示，点击切换倒序'"
                    :aria-label="accountDisplayOrder === 'desc' ? '切换为账号正序显示' : '切换为账号倒序显示'">
                    ↑↓
                  </button>
                </div>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="!filteredAccounts.length">
              <td class="px-4 py-8 text-center text-gray-500" colspan="14">没有匹配的账号</td>
            </tr>
            <tr v-for="(acc, i) in paginatedAccounts" :key="acc.email"
              v-memo="[acc, accountPageStartIndex, isSelected(acc.email), accountActionBusy && actionEmail === acc.email, twoFactorSubmitting || twoFactorTaskRunning, accountTwoFactorEnabled(acc), accountTwoFactorSetupInProgress(acc), hasCodexAuthFile(acc)]"
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
              <td class="px-4 py-3 text-gray-500">{{ accountPageStartIndex + i + 1 }}</td>
              <td class="px-4 py-3 max-w-56">
                <div class="flex w-56 max-w-full items-center gap-1.5">
                  <div
                    class="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-mono text-xs text-gray-200"
                    :title="displayEmail(acc)">
                    {{ displayEmailPreview(acc) }}
                  </div>
                  <span
                    v-if="hasCodexAuthFile(acc)"
                    title="该账号已有 OAuth 凭证"
                    aria-label="该账号已有 OAuth 凭证"
                    class="shrink-0 inline-flex items-center rounded-full border border-cyan-500/25 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-cyan-300">
                    OAuth
                  </span>
                </div>
                <div v-if="acc.hub_source_name" class="mt-1 text-[11px] text-violet-300">
                  Hub: {{ acc.hub_source_name }}
                </div>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="accountTypeClass(acc.account_type)">
                  {{ accountTypeLabel(acc.account_type) }}
                </span>
                <span
                  v-if="acc.trial_eligible"
                  class="ml-1.5 inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20"
                  title="注册时检测到该账号可 0 元试用（available_plans 非空）">
                  可试用
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
                <button
                  v-if="accountTwoFactorEnabled(acc)"
                  type="button"
                  @click="openTwoFactorTotpDialog(acc)"
                  class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 transition hover:bg-emerald-500/20">
                  已设置
                </button>
                <button
                  v-else
                  type="button"
                  @click="setupAccountTwoFactor(acc)"
                  :disabled="accountTwoFactorSetupInProgress(acc)"
                  class="inline-flex items-center px-2 py-0.5 rounded-md border text-xs font-medium whitespace-nowrap transition"
                  :class="accountTwoFactorSetupInProgress(acc)
                    ? 'border-yellow-500/20 bg-yellow-500/5 text-yellow-300/70 cursor-wait'
                    : 'border-yellow-500/30 bg-yellow-500/10 text-yellow-300 hover:bg-yellow-500/20'">
                  {{ twoFactorButtonLabel(acc) }}
                </button>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="bindProviderClass(effectiveBindProvider(acc))">
                  {{ bindProviderLabel(effectiveBindProvider(acc)) }}
                </span>
              </td>
              <td class="px-4 py-3">
                <div class="inline-flex flex-col items-start gap-1">
                  <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                    :class="credentialExportClass(acc)">
                    {{ credentialExportLabel(acc) }}
                  </span>
                  <span
                    v-if="acc?.credentials_exported && accountExportTs(acc)"
                    class="pl-0.5 text-[11px] font-mono leading-tight text-gray-500">
                    {{ exportTimeLabel(acc) }}
                  </span>
                </div>
              </td>
              <td class="px-4 py-3">
                <span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium"
                  :class="accountHubSyncClass(acc)">
                  {{ accountHubSyncLabel(acc) }}
                </span>
              </td>
              <td
                class="px-4 py-3 text-right font-mono"
                :class="pctColor(quota(acc, 'primary'))"
                :title="quotaWindow(acc, 'primary') ? 'OpenAI 返回的 5h 限额窗口' : 'OpenAI 未返回 5h 限额窗口'">
                {{ quotaPct(acc, 'primary') }}
              </td>
              <td
                class="px-4 py-3 text-right font-mono"
                :class="pctColor(quota(acc, 'weekly'))"
                :title="quotaWindow(acc, 'weekly') ? 'OpenAI 返回的周限额窗口' : 'OpenAI 未返回周限额窗口'">
                {{ quotaPct(acc, 'weekly') }}
              </td>
              <td class="px-4 py-3 text-gray-400 text-xs font-mono">{{ registerTimeLabel(acc) }}</td>
              <td class="px-4 py-3 text-gray-400 text-xs font-mono">{{ activationTimeLabel(acc) }}</td>
              <td class="px-4 py-3 text-right">
                <button
                  type="button"
                  @click="openAccountActionMenu(acc, $event)"
                  :disabled="accountActionBusy && actionEmail === acc.email"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border transition"
                  :class="accountActionBusy && actionEmail === acc.email
                    ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-wait'
                    : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700 hover:text-white'">
                  {{ accountActionBusy && actionEmail === acc.email ? '处理中…' : '操作' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div
        v-if="accountFilteredTotal > 0"
        class="flex flex-col gap-3 border-t border-gray-800 px-4 py-3 text-xs text-gray-500 sm:flex-row sm:items-center sm:justify-between">
        <div class="flex flex-wrap items-center gap-2">
          <span>账号分页：每页</span>
          <select
            v-model.number="accountPageSize"
            class="rounded-lg border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-200 focus:border-cyan-500/60 focus:outline-none focus:ring-2 focus:ring-cyan-500/30">
            <option v-for="option in ACCOUNT_PAGE_SIZE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
          <span>条，第</span>
          <span class="font-mono text-gray-300">{{ accountCurrentPage }}</span>
          <span>/</span>
          <span class="font-mono text-gray-300">{{ accountTotalPages }}</span>
          <span>页</span>
        </div>
        <div class="flex items-center gap-2">
          <button
            type="button"
            @click="setAccountPage(1)"
            :disabled="accountCurrentPage <= 1"
            class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40">
            首页
          </button>
          <button
            type="button"
            @click="setAccountPage(accountCurrentPage - 1)"
            :disabled="accountCurrentPage <= 1"
            class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40">
            上一页
          </button>
          <button
            type="button"
            @click="setAccountPage(accountCurrentPage + 1)"
            :disabled="accountCurrentPage >= accountTotalPages"
            class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40">
            下一页
          </button>
          <button
            type="button"
            @click="setAccountPage(accountTotalPages)"
            :disabled="accountCurrentPage >= accountTotalPages"
            class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-gray-300 transition hover:bg-gray-700 disabled:cursor-not-allowed disabled:opacity-40">
            末页
          </button>
        </div>
      </div>

      <Teleport to="body">
        <div
          v-if="accountActionMenuAccount"
          ref="accountActionDialogRef"
          role="dialog"
          aria-modal="true"
          aria-labelledby="account-action-dialog-title"
          tabindex="-1"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          @click.self="closeAccountActionMenu"
          @keydown.esc.stop="closeAccountActionMenu"
          @keydown.tab="trapAccountActionDialogFocus"
        >
          <section class="w-full max-w-lg overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl">
            <header class="flex items-start justify-between gap-4 border-b border-gray-800 px-5 py-4">
              <div class="min-w-0">
                <h3 id="account-action-dialog-title" class="font-semibold text-white">账号操作</h3>
                <p class="mt-1 truncate font-mono text-xs text-gray-500">{{ displayEmail(accountActionMenuAccount) }}</p>
              </div>
              <button ref="accountActionDialogInitialFocusRef" type="button" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700" @click="closeAccountActionMenu">关闭</button>
            </header>
            <div class="grid grid-cols-2 gap-2 p-5 sm:grid-cols-3">
              <button type="button" :disabled="accountActionMenuBusy" class="account-action-choice text-emerald-300" @click="copyAccountAccessToken(accountActionMenuAccount.email)">
                {{ actionEmail === accountActionMenuAccount.email && actionType === 'access-token' ? '复制中…' : '获取 Access Token' }}
              </button>
              <button type="button" :disabled="accountActionMenuBusy" class="account-action-choice text-teal-300" @click="queryAccountSubscription(accountActionMenuAccount.email)">
                {{ actionEmail === accountActionMenuAccount.email && actionType === 'subscription' ? '查询中…' : '查询订阅' }}
              </button>
              <button type="button" :disabled="accountActionMenuBusy" class="account-action-choice text-sky-300" @click="queryAccountLatestMail(accountActionMenuAccount.email)">
                {{ actionEmail === accountActionMenuAccount.email && actionType === 'latest-mail' ? '取件中…' : '获取邮件' }}
              </button>
              <button v-if="canOauthAuthorize(accountActionMenuAccount)" type="button" :disabled="loginDisabled || accountActionMenuBusy" class="account-action-choice text-amber-300" @click="oauthAuthorizeAccount(accountActionMenuAccount.email)">
                {{ actionEmail === accountActionMenuAccount.email && actionType === 'oauth-authorize' ? '授权中…' : oauthAuthorizeLabel(accountActionMenuAccount) }}
              </button>
              <button v-if="canRelogin(accountActionMenuAccount)" type="button" :disabled="loginDisabled || accountActionMenuBusy" class="account-action-choice text-cyan-300" @click="reloginAccount(accountActionMenuAccount.email)">
                {{ actionEmail === accountActionMenuAccount.email && actionType === 'relogin' ? '补登录中…' : reloginLabel(accountActionMenuAccount) }}
              </button>
              <button v-if="!accountActionMenuAccount.is_main_account" type="button" :disabled="accountActionMenuBusy" class="account-action-choice text-gray-200" @click="editAccountFromActionMenu">修改账号</button>
              <button v-if="!accountActionMenuAccount.is_main_account" type="button" :disabled="deleteDisabled || accountActionMenuBusy" class="account-action-choice text-rose-300" @click="removeAccountFromActionMenu">
                {{ actionEmail === accountActionMenuAccount.email && actionType === 'delete' ? '删除中…' : '删除账号' }}
              </button>
            </div>
          </section>
        </div>
      </Teleport>

      <AccessibleModal
        v-if="twoFactorTotpDialog.open"
        label="查看2FA验证码"
        initial-focus-selector="[data-two-factor-refresh]"
        @close="closeTwoFactorTotpDialog">
        <div class="w-full max-w-md overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl">
          <div class="flex items-start justify-between gap-4 border-b border-gray-800 px-5 py-4">
            <div class="min-w-0">
              <div class="flex flex-wrap items-center gap-2">
                <h3 class="text-base font-semibold text-white">2FA 验证码</h3>
                <span class="inline-flex items-center rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300">
                  已启用
                </span>
              </div>
              <p class="mt-1 truncate font-mono text-xs text-gray-500">{{ twoFactorTotpDialog.email }}</p>
            </div>
            <button type="button" aria-label="关闭2FA验证码" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700" @click="closeTwoFactorTotpDialog">关闭</button>
          </div>
          <div class="space-y-4 p-5">
            <div v-if="twoFactorTotpDialog.loading" class="rounded-xl border border-cyan-500/20 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-200">
              正在获取密钥和验证码...
            </div>
            <div v-else-if="twoFactorTotpDialog.error" class="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-300">
              {{ twoFactorTotpDialog.error }}
            </div>
            <template v-else>
              <div class="rounded-xl border border-gray-800 bg-gray-950/70 p-4">
                <div class="mb-2 flex items-center justify-between gap-3">
                  <span class="text-xs font-medium text-gray-500">密钥</span>
                  <button
                    type="button"
                    class="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/20"
                    @click="copyTwoFactorSecret">
                    复制密钥
                  </button>
                </div>
                <div class="break-all font-mono text-sm text-gray-200">{{ twoFactorTotpDialog.secret || '-' }}</div>
              </div>
              <div class="flex items-center justify-between gap-3">
                <div>
                  <div class="text-xs font-medium text-gray-500">当前验证码</div>
                  <div class="mt-1 text-[11px] text-gray-500">剩余 {{ twoFactorTotpDialog.remaining || 0 }} 秒</div>
                </div>
                <div class="inline-flex items-center gap-3">
                  <span class="rounded-full border border-blue-500/25 bg-blue-500/10 px-4 py-2 font-mono text-lg font-bold tracking-[0.18em] text-blue-200">
                    {{ formatTwoFactorCode(twoFactorTotpDialog.code) }}
                  </span>
                  <button
                    type="button"
                    data-two-factor-refresh
                    :disabled="twoFactorTotpDialog.refreshing"
                    class="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-300 transition hover:bg-emerald-500/20 disabled:cursor-wait disabled:opacity-60"
                    @click="refreshTwoFactorTotpDialog">
                    {{ twoFactorTotpDialog.refreshing ? '刷新中...' : '刷新' }}
                  </button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </AccessibleModal>

      <!-- 外部账号导入弹窗 -->
      <AccessibleModal v-if="externalAccountImportOpen" label="导入账号" @close="closeExternalAccountImport">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-2xl max-h-[86vh] flex flex-col">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">导入账号</h3>
              <div class="text-xs text-gray-500 mt-0.5">支持一行一个：邮箱----取件URL，或 邮箱----密码----2FA密钥；带 2FA 密钥的账号导入后直接显示“已设置”。</div>
            </div>
            <button type="button" aria-label="关闭导入账号" @click="closeExternalAccountImport" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-4 overflow-y-auto flex-1">
            <div>
              <label for="external-account-import-content" class="block text-xs text-gray-500 mb-2">账号内容</label>
              <textarea
                id="external-account-import-content"
                v-model="externalAccountImportText"
                rows="10"
                placeholder="user@example.com----https://example.com/api/mail?token=...
Pro2x-0906@nbclas.com----EaD5zylT23wAJv----MSRVASZAW32OYTLQOUXK625IXPCMKPAW"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs font-mono text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500/60"></textarea>
              <div class="mt-1 text-xs text-gray-500">重复邮箱只导入第一条；取件URL格式会更新取件URL，2FA格式会更新密码并保存密钥，不覆盖账号类型/状态。</div>
            </div>

            <div v-if="externalAccountImportResult" class="rounded-xl border border-gray-800 bg-gray-950/60 p-3 text-xs">
              <div class="text-gray-200">
                新增 {{ externalAccountImportResult.imported || 0 }}，更新 {{ externalAccountImportResult.updated || 0 }}，2FA {{ externalAccountImportResult.totp_imported || 0 }}，重复 {{ externalAccountImportResult.duplicates || 0 }}，无效 {{ externalAccountImportResult.invalid?.length || 0 }}
              </div>
              <div v-if="externalAccountImportResult.invalid?.length" class="mt-2 text-amber-300">
                跳过 {{ externalAccountImportResult.invalid.length }} 条无效；前 5 条：
                <div v-for="item in externalAccountImportResult.invalid.slice(0, 5)" :key="String(item.line || '') + String(item.error || '')" class="mt-1 text-amber-200/80 font-mono break-all">
                  第 {{ item.line }} 行：{{ item.error }}<span v-if="item.content"> / {{ item.content }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button
              @click="closeExternalAccountImport"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              关闭
            </button>
            <button
              @click="submitExternalAccountImport"
              :disabled="externalAccountImporting || !externalAccountImportText.trim()"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="externalAccountImporting || !externalAccountImportText.trim()
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500'">
              {{ externalAccountImporting ? '导入中...' : '开始导入' }}
            </button>
          </div>
        </div>
      </AccessibleModal>

      <!-- CPA 认证导入弹窗 -->
      <AccessibleModal v-if="cpaImportOpen" label="导入 CPA 认证" @close="closeCpaImport">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-3xl max-h-[86vh] flex flex-col">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">导入 CPA 认证</h3>
              <div class="text-xs text-gray-500 mt-0.5">支持粘贴 JSON、选择多个 JSON/ZIP 文件，或选择文件夹批量导入。</div>
            </div>
            <button type="button" aria-label="关闭 CPA 认证导入" @click="closeCpaImport" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-4 overflow-y-auto flex-1">
            <div>
              <label for="cpa-import-content" class="block text-xs text-gray-500 mb-2">直接粘贴 CPA JSON</label>
              <textarea
                id="cpa-import-content"
                v-model="cpaImportText"
                rows="8"
                placeholder='{"type":"codex","email":"...","access_token":"...","id_token":"...","refresh_token":"..."}'
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-xs font-mono text-gray-200 placeholder:text-gray-600 focus:outline-none focus:ring-2 focus:ring-purple-500/30 focus:border-purple-500/60"></textarea>
            </div>

            <div class="grid gap-3 md:grid-cols-2">
              <label class="rounded-xl border border-gray-800 bg-gray-950/60 p-4 cursor-pointer hover:border-purple-500/40 transition">
                <input type="file" multiple accept=".json,.zip,application/json,application/zip" class="hidden" @change="handleCpaImportFiles" />
                <div class="text-sm font-semibold text-gray-100">选择文件</div>
                <div class="mt-1 text-xs text-gray-500">可一次选择多个 .json 或 .zip。</div>
              </label>
              <label class="rounded-xl border border-gray-800 bg-gray-950/60 p-4 cursor-pointer hover:border-purple-500/40 transition">
                <input type="file" multiple webkitdirectory directory class="hidden" @change="handleCpaImportFiles" />
                <div class="text-sm font-semibold text-gray-100">选择文件夹</div>
                <div class="mt-1 text-xs text-gray-500">会递归读取文件夹中的 .json/.zip。</div>
              </label>
            </div>

            <div v-if="cpaImportFiles.length" class="rounded-xl border border-gray-800 bg-gray-950/60 overflow-hidden">
              <div class="px-3 py-2 border-b border-gray-800 flex items-center justify-between">
                <div class="text-xs text-gray-400">待导入文件：{{ cpaImportFiles.length }}</div>
                <button @click="cpaImportFiles = []" class="text-xs text-gray-500 hover:text-gray-200">清空</button>
              </div>
              <div class="max-h-36 overflow-y-auto divide-y divide-gray-800/60">
                <div v-for="file in cpaImportFiles" :key="file.name + file.size + file.lastModified" class="px-3 py-2 text-xs text-gray-300 font-mono truncate">
                  {{ file.webkitRelativePath || file.name }}
                </div>
              </div>
            </div>

            <div v-if="cpaImportResult" class="rounded-xl border border-gray-800 bg-gray-950/60 p-3 text-xs">
              <div class="text-gray-200">
                导入 {{ cpaImportResult.imported || 0 }}，更新 {{ cpaImportResult.updated || 0 }}，新增账号 {{ cpaImportResult.accounts_added || 0 }}，更新账号 {{ cpaImportResult.accounts_updated || 0 }}，重复 {{ cpaImportResult.duplicates || 0 }}
              </div>
              <div v-if="cpaImportResult.invalid?.length" class="mt-2 text-amber-300">
                跳过 {{ cpaImportResult.invalid.length }} 条无效来源；前 3 条：
                <div v-for="item in cpaImportResult.invalid.slice(0, 3)" :key="item.filename + item.error" class="mt-1 text-amber-200/80 font-mono break-all">
                  {{ item.filename }}: {{ item.error }}
                </div>
              </div>
            </div>
          </div>
          <div class="px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button
              @click="closeCpaImport"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              关闭
            </button>
            <button
              @click="submitCpaImport"
              :disabled="cpaImporting || (!cpaImportText.trim() && !cpaImportFiles.length)"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="cpaImporting || (!cpaImportText.trim() && !cpaImportFiles.length)
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-purple-600 hover:bg-purple-500 text-white border-purple-500'">
              {{ cpaImporting ? '导入中...' : '开始导入' }}
            </button>
          </div>
        </div>
      </AccessibleModal>

      <!-- 订阅状态弹窗 -->
      <Teleport to="body">
        <div
          v-if="subscriptionDialog.open"
          ref="subscriptionDialogRef"
          role="dialog"
          aria-modal="true"
          aria-label="ChatGPT 订阅状态"
          tabindex="-1"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          @click.self="closeSubscriptionDialog"
          @keydown.esc.stop="closeSubscriptionDialog"
          @keydown.tab="trapAccountSecondaryDialogFocus($event, subscriptionDialogRef)"
        >
        <div class="w-full max-w-6xl overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
          <div class="max-h-[88vh] overflow-y-auto p-6">
            <div v-if="subscriptionDialog.loading" class="rounded-xl border border-teal-500/20 bg-teal-500/10 px-4 py-10 text-center text-sm text-teal-200">
              正在查询 ChatGPT 实时订阅状态...
            </div>
            <div v-else-if="subscriptionDialog.error" class="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-5 text-sm text-red-300">
              {{ subscriptionDialog.error }}
            </div>
            <div v-else-if="subscriptionDialog.data" class="space-y-7">
              <div class="flex flex-col gap-4 border-b border-slate-800 pb-6 md:flex-row md:items-start md:justify-between">
                <div>
                  <h3 class="text-3xl font-black text-violet-400">{{ subscriptionPlanLabel }}</h3>
                  <div class="mt-3 break-all font-mono text-sm text-slate-400">
                    {{ subscriptionDialog.email }} · {{ subscriptionAccountId }}
                  </div>
                </div>
                <div class="flex flex-wrap items-center gap-2">
                  <span
                    class="rounded-full border px-3 py-1.5 text-xs font-bold"
                    :class="subscriptionActive(activeSubscription)
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : 'border-amber-500/40 bg-amber-500/15 text-amber-300'">
                    {{ subscriptionActive(activeSubscription) ? '✓ 订阅生效中' : '订阅未生效' }}
                  </span>
                  <span class="rounded-full border px-3 py-1.5 text-xs font-bold"
                    :class="activeSubscription.renewing
                      ? 'border-emerald-500/40 bg-emerald-500/15 text-emerald-300'
                      : 'border-slate-700 bg-slate-900 text-slate-300'">
                    {{ activeSubscription.renewing ? '自动续费' : '未自动续费' }}
                  </span>
                  <span class="rounded-full border border-indigo-500/20 bg-indigo-500/10 px-3 py-1.5 text-xs font-bold text-indigo-200">JWT={{ activeSubscription.jwt_plan_type || '-' }}</span>
                  <button @click="closeSubscriptionDialog" class="rounded-full border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-800 hover:text-white">关闭</button>
                </div>
              </div>

              <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
                <div v-for="item in subscriptionSummaryItems" :key="item.label" class="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
                  <div class="text-xs text-slate-400">{{ item.label }}</div>
                  <div class="mt-3 whitespace-pre-line text-xl font-black text-white" :class="item.accent ? 'text-emerald-300 text-3xl' : ''">{{ item.value }}</div>
                  <div v-if="item.meta" class="mt-2 text-sm text-blue-300">{{ item.meta }}</div>
                </div>
              </div>

              <div>
                <div class="mb-3 text-base font-bold text-blue-100">
                  订阅时间线
                </div>
                <div class="grid gap-4 md:grid-cols-3">
                  <div v-for="item in subscriptionTimelineItems" :key="item.label" class="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
                    <div class="text-xs text-slate-400">{{ item.label }}</div>
                    <div class="mt-3 break-all font-mono text-lg font-bold text-white">{{ item.value }}</div>
                  </div>
                </div>
              </div>

              <div>
                <div class="mb-3 text-base font-bold text-blue-100">已应用优惠</div>
                <div v-if="subscriptionDiscountItems.length" class="space-y-3">
                  <div v-for="discount in subscriptionDiscountItems" :key="discount.id || discount.label" class="rounded-xl border border-sky-500/30 bg-sky-500/10 p-4">
                    <div class="font-mono text-sm font-bold text-sky-300">{{ discount.id || '-' }}</div>
                    <div class="mt-2 text-sm text-blue-200">{{ discount.label }}</div>
                  </div>
                </div>
                <div v-else class="rounded-xl border border-slate-800 bg-slate-900/70 p-4 text-sm text-slate-500">暂无优惠</div>
              </div>

              <div>
                <div class="mb-3 border-b border-slate-800 pb-3 text-base font-bold text-blue-100">该账号可购买的套餐</div>
                <div class="flex flex-wrap gap-2">
                  <span
                    v-for="plan in subscriptionAvailablePlanItems"
                    :key="plan"
                    class="rounded-lg border px-3 py-2 font-mono text-sm"
                    :class="plan === subscriptionPlanKey
                      ? 'border-violet-500 bg-violet-500/15 text-cyan-200'
                      : 'border-slate-800 bg-slate-900 text-slate-100'">
                    {{ plan }}<span v-if="plan === subscriptionPlanKey"> ★</span>
                  </span>
                </div>
              </div>

              <details class="group">
                <summary class="cursor-pointer select-none text-sm text-slate-400 transition hover:text-slate-200">查看原始 JSON</summary>
                <pre class="mt-3 max-h-72 overflow-auto rounded-xl border border-slate-800 bg-slate-950/80 p-4 text-xs text-slate-300">{{ subscriptionRawJson }}</pre>
              </details>
            </div>
            <div class="mt-6 flex justify-end">
              <button ref="subscriptionDialogInitialFocusRef" type="button" @click="closeSubscriptionDialog" class="rounded-lg border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-semibold text-slate-300 transition hover:bg-slate-800 hover:text-white">关闭</button>
              </div>
            </div>
          </div>
        </div>
      </Teleport>

      <!-- 最近邮件弹窗 -->
      <Teleport to="body">
        <div
          v-if="latestMailDialog.open"
          ref="latestMailDialogRef"
          role="dialog"
          aria-modal="true"
          aria-label="最近一封邮件"
          tabindex="-1"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
          @click.self="closeLatestMailDialog"
          @keydown.esc.stop="closeLatestMailDialog"
          @keydown.tab="trapAccountSecondaryDialogFocus($event, latestMailDialogRef)"
        >
        <div class="w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-700 bg-slate-950 shadow-2xl">
          <div class="flex flex-wrap items-start justify-between gap-3 border-b border-slate-800 px-6 py-4">
            <div class="min-w-0">
              <h3 class="text-xl font-bold text-sky-300">最近一封邮件</h3>
              <div class="mt-1 break-all font-mono text-xs text-slate-400">{{ latestMailDialog.email }}</div>
            </div>
            <button ref="latestMailDialogInitialFocusRef" type="button" @click="closeLatestMailDialog" class="rounded-full border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-slate-300 transition hover:bg-slate-800 hover:text-white">关闭</button>
          </div>
          <div class="max-h-[82vh] overflow-y-auto p-6">
            <div v-if="latestMailDialog.loading" class="rounded-xl border border-sky-500/20 bg-sky-500/10 px-4 py-10 text-center text-sm text-sky-200">
              正在获取最新邮件...
            </div>
            <div v-else-if="latestMailDialog.error" class="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-5 text-sm text-red-300">
              {{ latestMailDialog.error }}
            </div>
            <div v-else-if="!activeLatestMail" class="rounded-xl border border-slate-800 bg-slate-900/70 px-4 py-10 text-center text-sm text-slate-500">
              收件箱暂无邮件
              <div v-if="latestMailDialog.data?.provider || latestMailDialog.data?.mail_email" class="mt-2 font-mono text-xs text-slate-600">
                {{ latestMailDialog.data?.provider || '-' }} · {{ latestMailDialog.data?.mail_email || '-' }}
              </div>
            </div>
            <div v-else class="space-y-4">
              <div class="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
                <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div class="min-w-0">
                    <div class="text-xs text-slate-500">
                      {{ latestMailDialog.data?.provider || '-' }} · {{ latestMailDialog.data?.mail_email || '-' }}
                    </div>
                    <h4 class="mt-2 break-words text-lg font-bold text-white">{{ activeLatestMail.subject || '(无主题)' }}</h4>
                    <div class="mt-2 space-y-1 text-xs text-slate-400">
                      <div>发件人：<span class="font-mono text-slate-200">{{ activeLatestMail.sendEmail || '-' }}</span></div>
                      <div>收件人：<span class="font-mono text-slate-200">{{ activeLatestMail.toEmail || latestMailDialog.data?.mail_email || '-' }}</span></div>
                    </div>
                  </div>
                  <div class="shrink-0 rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 font-mono text-xs text-slate-400">
                    {{ formatLatestMailDate(activeLatestMail.createTime || activeLatestMail.createdAt) }}
                  </div>
                </div>
              </div>
              <iframe
                v-if="activeLatestMail.html"
                :srcdoc="latestMailSrcdoc"
                sandbox=""
                class="h-[48vh] w-full rounded-xl border border-slate-800 bg-white"
              ></iframe>
              <pre v-else class="max-h-[48vh] overflow-auto whitespace-pre-wrap rounded-xl border border-slate-800 bg-slate-950 p-4 text-xs leading-5 text-slate-200">{{ activeLatestMail.text || activeLatestMail.content || '无正文' }}</pre>
            </div>
          </div>
          </div>
        </div>
      </Teleport>

      <!-- 账号操作编辑弹窗 -->
      <AccessibleModal v-if="accountTypeEditAccount" label="编辑账号操作" @close="closeAccountTypeEditor">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-md">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">编辑账号操作</h3>
              <div class="text-xs text-gray-500 font-mono mt-0.5">{{ accountTypeEditAccount.email }}</div>
            </div>
            <button type="button" aria-label="关闭账号编辑" @click="closeAccountTypeEditor" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label for="account-type-edit" class="block text-xs text-gray-500 mb-2">账号类型</label>
              <select
                id="account-type-edit"
                v-model="accountTypeEditValue"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option v-for="option in editableAccountTypeOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label for="account-status-edit" class="block text-xs text-gray-500 mb-2">账号状态</label>
              <select
                id="account-status-edit"
                v-model="accountStatusEditValue"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option v-for="option in editableAccountStatusOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label for="account-provider-edit" class="block text-xs text-gray-500 mb-2">绑定渠道</label>
              <select
                id="account-provider-edit"
                v-model="accountBindProviderEditValue"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option v-for="option in editableBindProviderOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="text-xs text-gray-500 leading-relaxed">
              这里只修改本地账号池记录，不会自动移出 Team、同步 CPA 或刷新 auth 文件。
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
              :disabled="accountTypeSaving || accountMetadataEditUnchanged"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="accountTypeSaving || accountMetadataEditUnchanged
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-cyan-600 hover:bg-cyan-500 text-white border-cyan-500'">
              {{ accountTypeSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </AccessibleModal>

      <!-- 批量修改账号弹窗 -->
      <AccessibleModal v-if="batchAccountEditOpen" label="批量修改账号" @close="closeBatchAccountEditor">
        <div class="bg-gray-900 border border-gray-800 rounded-xl w-full max-w-md">
          <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">批量修改账号</h3>
              <div class="text-xs text-gray-500 font-mono mt-0.5">{{ batchAccountEditEmails.length }} 个账号</div>
            </div>
            <button type="button" aria-label="关闭批量账号编辑" @click="closeBatchAccountEditor" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="p-4 space-y-4">
            <div>
              <label for="batch-account-type-edit" class="block text-xs text-gray-500 mb-2">账号类型</label>
              <select
                id="batch-account-type-edit"
                v-model="batchAccountEditType"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option :value="BATCH_METADATA_SKIP">不修改</option>
                <option v-for="option in editableAccountTypeOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label for="batch-account-status-edit" class="block text-xs text-gray-500 mb-2">账号状态</label>
              <select
                id="batch-account-status-edit"
                v-model="batchAccountEditStatus"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option :value="BATCH_METADATA_SKIP">不修改</option>
                <option v-for="option in editableAccountStatusOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label for="batch-account-provider-edit" class="block text-xs text-gray-500 mb-2">绑定渠道</label>
              <select
                id="batch-account-provider-edit"
                v-model="batchAccountEditProvider"
                class="w-full bg-gray-950 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 focus:border-cyan-500/60">
                <option :value="BATCH_METADATA_SKIP">不修改</option>
                <option v-for="option in editableBindProviderOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="text-xs text-gray-500 leading-relaxed">
              只会修改选中的本地账号池记录；未选择的字段保持不变。
            </div>
          </div>
          <div class="px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button
              @click="closeBatchAccountEditor"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              取消
            </button>
            <button
              @click="saveBatchAccountMetadata"
              :disabled="batchAccountSaving || !batchAccountMetadataHasChanges"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="batchAccountSaving || !batchAccountMetadataHasChanges
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-cyan-600 hover:bg-cyan-500 text-white border-cyan-500'">
              {{ batchAccountSaving ? '保存中...' : '保存' }}
            </button>
          </div>
        </div>
      </AccessibleModal>

      <!-- 账密导出弹窗 -->
      <AccessibleModal v-if="credentialExportOpen" label="导出账密 TXT" @close="closeCredentialExport">
        <div class="credential-export-panel bg-gray-900 border border-gray-800 rounded-xl w-full max-w-lg max-h-[calc(100dvh-2rem)] flex flex-col overflow-hidden">
          <div class="shrink-0 px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <div>
              <h3 class="text-white font-semibold">导出账密 TXT</h3>
              <div class="text-xs text-gray-500 mt-0.5">
                {{ selectedEmails.length ? `将导出 ${selectedEmails.length} 个选中账号` : `将导出 ${filteredAccounts.length} 个筛选账号` }}
              </div>
              <div class="text-xs text-gray-600 mt-1">已导出的账号也会按当前选择重复导出。</div>
            </div>
            <button type="button" aria-label="关闭账密导出" @click="closeCredentialExport" class="text-gray-400 hover:text-white text-lg">&times;</button>
          </div>
          <div class="credential-export-body p-4 space-y-4 min-h-0 flex-1 overflow-y-auto">
            <div class="grid gap-3 text-xs text-gray-300">
              <div class="rounded-lg border border-gray-800 bg-gray-950/70 p-3">
                <div class="font-semibold text-gray-100 mb-1">域名邮箱</div>
                <div class="font-mono break-all">邮箱-----密码-----https://gptcode.external.cc.cd/</div>
              </div>
              <div class="rounded-lg border border-gray-800 bg-gray-950/70 p-3">
                <div class="font-semibold text-gray-100 mb-1">LuckMail</div>
                <div class="font-mono break-all">邮箱-----token-----https://mail.cpacc.us.ci/</div>
              </div>
              <div class="rounded-lg border border-gray-800 bg-gray-950/70 p-3">
                <div class="font-semibold text-gray-100 mb-1">Outlook OAuth 邮箱</div>
                <div class="font-mono break-all">邮箱----密码----client-id----refresh-token</div>
                <div class="mt-1 text-gray-500">邮箱大小写按 Outlook 账号池原始记录导出。</div>
              </div>
              <div class="rounded-lg border border-gray-800 bg-gray-950/70 p-3">
                <div class="font-semibold text-gray-100 mb-1">Outlook mailapi 邮箱</div>
                <div class="font-mono break-all">邮箱-----密码-----https://mailapi.icu/key?type=html&orderNo=...</div>
                <div class="mt-1 text-gray-500">mailapi 类型保持原来的三段式导出。</div>
              </div>
            </div>
          </div>
          <div class="shrink-0 px-4 py-3 border-t border-gray-800 flex justify-end gap-3">
            <button
              @click="closeCredentialExport"
              class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 rounded-lg border border-gray-700 transition">
              取消
            </button>
            <button
              @click="downloadCredentials"
              :disabled="credentialExporting || !exportableAccounts.length"
              class="px-4 py-2 text-sm rounded-lg border transition"
              :class="credentialExporting || !exportableAccounts.length
                ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
                : 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500'">
              {{ credentialExporting ? '导出中...' : '导出 txt' }}
            </button>
          </div>
        </div>
      </AccessibleModal>
    </div>
    </template>

    <div v-else class="space-y-6">
      <div class="flex items-center justify-between gap-3 mb-3">
        <h2 class="text-lg font-semibold text-white">Kiro 统计面板</h2>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div v-for="card in kiroCards" :key="card.label"
          class="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <div class="text-sm text-gray-400">{{ card.label }}</div>
          <div class="text-3xl font-bold mt-1" :class="card.color">{{ card.value }}</div>
        </div>
      </div>

      <div class="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <div class="px-4 py-3 border-b border-gray-800 flex items-center justify-between gap-3 flex-wrap">
          <h2 class="text-lg font-semibold text-white">Kiro 账号列表</h2>
        </div>
        <div class="px-4 py-10 text-sm text-gray-500">
          暂无 Kiro 数据。
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
  <div v-else-if="accountsError" role="alert" class="dashboard-load-error">
    <div class="dashboard-load-error-icon" aria-hidden="true">!</div>
    <div>
      <h2>账号数据加载失败</h2>
      <p>{{ accountsError }}</p>
      <p class="dashboard-load-error-hint">网络恢复后重试；页面不会停在无反馈的空白状态。</p>
    </div>
    <button type="button" @click="retryAccounts">重新加载账号</button>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { normalizeStoredPageSize } from '../accountData.js'
import {
  buildAccountSelectionIndex,
  buildScopedAccountActions,
  selectAccountsFromIndex,
} from '../accountActionScope.js'
import { buildAccountFacets } from '../accountFacets.js'
import { buildAccountSearchIndex, filterAccountSearchIndex } from '../accountSearchIndex.js'
import { confirmExportStatusBatches } from '../exportCommit.js'
import { createMessageClearScheduler } from '../messageLifecycle.js'
import { createSessionStorageFacade } from '../sessionStorageScope.js'
import AccessibleModal from './AccessibleModal.vue'

const sessionStorage = createSessionStorageFacade()

const props = defineProps({
  status: Object,
  loading: Boolean,
  accountsError: {
    type: String,
    default: '',
  },
  lastSuccessfulAt: {
    type: [Number, String, Date],
    default: null,
  },
  runningTask: Object,
  tasks: {
    type: Array,
    default: () => [],
  },
  refreshQuotaResultTask: {
    type: Object,
    default: null,
  },
  adminStatus: {
    type: Object,
    default: null,
  },
})
const emit = defineEmits(['refresh', 'task-started', 'retry-accounts'])

const lastSuccessfulLabel = computed(() => {
  if (!props.lastSuccessfulAt) return ''
  const timestamp = Number(props.lastSuccessfulAt)
  const date = new Date(Number.isFinite(timestamp) ? timestamp : props.lastSuccessfulAt)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString('zh-CN', { hour12: false })
})

function retryAccounts() {
  emit('retry-accounts')
}

const dashboardTabs = [
  { value: 'chatgpt', label: 'ChatGPT' },
  { value: 'kiro', label: 'Kiro' },
]
const ACCOUNT_HUB_SYNC_MAX_EMAILS = 1000
const ACCOUNT_DELETE_BATCH_MAX_EMAILS = 1000
const DEFAULT_ACCOUNT_PAGE_SIZE = 50
const ACCOUNT_PAGE_SIZE_OPTIONS = [
  { value: 50, label: '50' },
  { value: 100, label: '100' },
  { value: 200, label: '200' },
]
const ACCOUNT_PAGE_SIZE_VALUES = ACCOUNT_PAGE_SIZE_OPTIONS.map(option => option.value)
const ACCOUNT_PAGE_SIZE_STORAGE_KEY = 'autotoken.dashboard.accountPageSize'
const activeDashboardTab = ref('chatgpt')
const accountDisplayOrder = ref('asc')
const accountPage = ref(1)
const accountPageSize = ref(loadAccountPageSize())
const actionEmail = ref('')
const actionType = ref('')
const accountActionBusy = ref(false)
const accountActionRequestId = ref(0)
const accountActionMenuAccount = ref(null)
const accountActionDialogRef = ref(null)
const accountActionDialogInitialFocusRef = ref(null)
const ACCOUNT_ACTION_FOCUSABLE_SELECTOR = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
let accountActionMenuTrigger = null
let accountActionBackgroundInertState = []
const accountActionMenuBusy = computed(() => Boolean(
  accountActionBusy.value
  || (accountActionMenuAccount.value && actionEmail.value === accountActionMenuAccount.value.email)
))
const hubSyncing = ref(false)
const message = ref('')
const messageClearScheduler = createMessageClearScheduler()

function scheduleMessageClear(delayMs, when = () => true) {
  messageClearScheduler.schedule(delayMs, {
    read: () => message.value,
    clear: () => { message.value = '' },
    when,
  })
}

watch(message, nextMessage => {
  if (nextMessage) messageClearScheduler.cancel()
}, { flush: 'sync' })

const subscriptionDialog = ref({
  open: false,
  email: '',
  loading: false,
  error: '',
  data: null,
})
const subscriptionDialogRef = ref(null)
const subscriptionDialogInitialFocusRef = ref(null)
const latestMailDialog = ref({
  open: false,
  email: '',
  loading: false,
  error: '',
  data: null,
})
const latestMailDialogRef = ref(null)
const latestMailDialogInitialFocusRef = ref(null)
const messageClass = ref('')
const emailFilter = ref('')
const deferredEmailFilter = ref('')
const statusFilter = ref('')
const accountTypeFilter = ref('')
const twoFactorFilter = ref('')
const trialFilter = ref('')
const bindProviderFilter = ref('')
const registerDateFilter = ref('')
const registerStartTimeFilter = ref('')
const registerEndTimeFilter = ref('')
const credentialExportFilter = ref('')
const exportDateFilter = ref('')
const exportStartTimeFilter = ref('')
const exportEndTimeFilter = ref('')
const accountHubSyncFilter = ref('')
const authCredentialFilter = ref('')
const bindDateFilter = ref('')
const bindStartTimeFilter = ref('')
const bindEndTimeFilter = ref('')
const accountTypeEditAccount = ref(null)
const accountTypeEditValue = ref('')
const accountStatusEditValue = ref('')
const accountBindProviderEditValue = ref('')
const accountTypeSaving = ref(false)
const BATCH_METADATA_SKIP = '__skip__'
const batchAccountEditOpen = ref(false)
const batchAccountEditEmails = ref([])
const batchAccountEditType = ref(BATCH_METADATA_SKIP)
const batchAccountEditStatus = ref(BATCH_METADATA_SKIP)
const batchAccountEditProvider = ref(BATCH_METADATA_SKIP)
const batchAccountSaving = ref(false)
const credentialExportOpen = ref(false)
const credentialExporting = ref(false)
const externalAccountImportOpen = ref(false)
const externalAccountImportText = ref('')
const externalAccountImporting = ref(false)
const externalAccountImportResult = ref(null)
const cpaImportOpen = ref(false)
const cpaImportText = ref('')
const cpaImportFiles = ref([])
const cpaImporting = ref(false)
const cpaImportResult = ref(null)
const cpaExporting = ref(false)
const subExporting = ref(false)
const accessTokenExporting = ref(false)
const exportStatusUpdating = ref(false)
const batchOauthAuthorizing = ref(false)
const twoFactorSubmitting = ref(false)
const twoFactorSubmittingEmails = ref(new Set())
const twoFactorPendingTaskIds = ref(new Set())
const twoFactorPendingTaskEmails = ref(new Set())
const twoFactorCompletedEmails = ref(new Set())
const twoFactorFailedEmails = ref(new Set())
const oauthCredentialCompletedEmails = ref(new Set())
const twoFactorTotpDialog = ref({
  open: false,
  email: '',
  loading: false,
  refreshing: false,
  error: '',
  secret: '',
  code: '',
  remaining: 0,
  period: 30,
})
const twoFactorTotpRequestId = ref(0)
let twoFactorPendingClearTimer = null
const batchReloggingIn = ref(false)
const quotaRefreshing = ref(false)
const invalidDeleting = ref(false)
const oauthConfigOpen = ref(false)
const oauthConfigTab = ref('proxy')
const luckmailEmailTypeOptions = [
  { value: 'ms_imap', label: '微软 IMAP 邮箱' },
  { value: 'ms_graph', label: '微软 Graph 邮箱' },
  { value: 'microsoft', label: '微软邮箱' },
  { value: 'self_built', label: '自建邮箱' },
]

const luckmailDomainOptions = [
  { value: '', label: '自动分配' },
  { value: 'outlook.com', label: 'outlook.com' },
  { value: 'outlook.cl', label: 'outlook.cl' },
  { value: 'outlook.de', label: 'outlook.de' },
  { value: 'outlook.fr', label: 'outlook.fr' },
  { value: 'outlook.jp', label: 'outlook.jp' },
  { value: 'outlook.my', label: 'outlook.my' },
  { value: 'outlook.ph', label: 'outlook.ph' },
  { value: 'hotmail.com', label: 'hotmail.com' },
  { value: 'hotmail.de', label: 'hotmail.de' },
  { value: 'live.com', label: 'live.com' },
]
const oauthEmailMailProvider = ref('')
const oauthEmailLuckmailEmailType = ref('ms_imap')
const oauthEmailLuckmailDomain = ref('')
const oauthEmailMailProviderOptions = ref([])
const oauthEmailDomain = ref('')
const oauthEmailDomainOptions = ref([])
const oauthEmailLoading = ref(false)
const oauthEmailSaving = ref(false)
const oauthEmailLoaded = ref(false)
const oauthPhoneSmsLoading = ref(false)
const oauthPhoneSmsSaving = ref(false)
const oauthPhoneSmsCountriesLoading = ref(false)
const oauthPhoneSmsCountryError = ref('')
const oauthPhoneSmsCountrySearch = ref('')
const oauthPhoneSmsCountryDropdownOpen = ref(false)
const oauthPhoneSmsStatus = ref({})
const oauthPhoneSmsForm = ref({
  provider: 'phone_pool',
  hero_sms_api_key: '',
  hero_sms_country: '187',
  hero_sms_min_price: '',
  hero_sms_max_price: '',
  hero_sms_price_mode: 'lowest',
  smsbower_api_key: '',
  smsbower_country: '187',
  smsbower_min_price: '',
  smsbower_max_price: '',
  smsbower_price_mode: 'lowest',
  smscloud_api_key: '',
  smscloud_country: '187',
  smscloud_min_price: '',
  smscloud_max_price: '',
  smscloud_price_mode: 'ceiling',
  oasis_sms_cdks: '',
  oasis_sms_cdk_file: 'oasis-cdk-accounts.jsonl',
  oasis_sms_base_url: 'https://sms.oapi.vip',
  oasis_sms_poll_attempts: '24',
  oasis_sms_poll_interval_ms: '5000',
  oasis_sms_account_map_file: 'oasis-cdk-accounts.jsonl',
  tujie_sms_cdks: '',
  tujie_sms_cdk_file: '',
  tujie_sms_base_url: 'https://tujie.xyz/api',
  tujie_sms_poll_attempts: '24',
  tujie_sms_poll_interval_ms: '5000',
  tujie_sms_account_map_file: 'tujie-cdk-accounts.jsonl',
})
const oauthPhoneSmsCountryFallbackOptions = {
  phone_pool: [],
  hero_sms: [
    { value: 'all', label: '全部国家 / 不限制' },
    { value: '187', label: '美国 / 187' },
    { value: '6', label: '印度尼西亚 / 6' },
    { value: '33', label: '哥伦比亚 / 33' },
  ],
  smsbower: [
    { value: 'all', label: '全部国家 / 不限制' },
    { value: '187', label: '美国 / 187' },
    { value: '6', label: '印度尼西亚 / 6' },
    { value: '33', label: '哥伦比亚 / 33' },
  ],
  smscloud: [
    { value: 'all', label: '全部国家 / 不限制' },
    { value: '187', label: '美国 / 187' },
    { value: '44', label: '英国 / 44' },
    { value: '6', label: '印度尼西亚 / 6' },
    { value: '33', label: '哥伦比亚 / 33' },
  ],
  oasis: [],
  tujie: [],
}
const oauthPhoneSmsCountryOptions = ref(oauthPhoneSmsCountryFallbackOptions.hero_sms)
let oauthPhoneSmsCountryRequestId = 0
const oauthProxyEnabled = ref(false)
const oauthProxyMode = ref('single')
const oauthBrowserMode = ref('protocol')
const oauthProxyUrl = ref('')
const oauthProxyPoolText = ref('')
const oauthProxyApiProvider = ref('cliproxy')
const oauthProxyApiCountry = ref('US')
const oauthBindPhone = ref(false)

// 批量删除选中态:按邮箱(小写)保存,便于跨刷新复用
const selectedSet = ref(new Set())
const batchDeleting = ref(false)
const batchProgress = ref('')

const OAUTH_PROXY_STORAGE_KEY = 'autotoken.dashboard.oauthProxy'
const OAUTH_EMAIL_STORAGE_KEY = 'autotoken.dashboard.oauthEmailCfg'
const OAUTH_PHONE_STORAGE_KEY = 'autotoken.dashboard.oauthPhoneCfg'
const BRAZIL_PIX_PAYMENT_STATE_STORAGE_KEY = 'autotoken_brazil_pix_payment_state'
const OAUTH_PHONE_PROVIDER_VALUES = ['phone_pool', 'hero_sms', 'smsbower', 'smscloud', 'oasis', 'tujie']
const OAUTH_PHONE_CDK_PROVIDERS = ['oasis', 'tujie']

function isCdkOauthPhoneProvider(provider) {
  return OAUTH_PHONE_CDK_PROVIDERS.includes(String(provider || ''))
}

function loadOauthEmailConfig() {
  if (oauthEmailLoaded.value) return
  oauthEmailLoading.value = true
  Promise.all([
    api.getMailProviderConfig().catch(() => ({ provider_options: [] })),
    api.getRegisterDomain().catch(() => ({ domain: '', domains: [] })),
  ]).then(([mailCfg, domainCfg]) => {
    let saved = {}
    try {
      saved = JSON.parse(sessionStorage.getItem(OAUTH_EMAIL_STORAGE_KEY) || '{}')
    } catch (_) {
      saved = {}
    }
    oauthEmailMailProviderOptions.value = (mailCfg.provider_options || []).map(p => ({ value: p.value, label: p.label || p.value }))
    oauthEmailMailProvider.value = saved.mail_provider || mailCfg.provider || mailCfg.provider_options?.[0]?.value || ''
    oauthEmailLuckmailEmailType.value = saved.luckmail_email_type || oauthEmailLuckmailEmailType.value
    oauthEmailLuckmailDomain.value = saved.luckmail_preferred_domain || oauthEmailLuckmailDomain.value
    const domains = domainCfg.domains?.length ? domainCfg.domains : (domainCfg.domain ? [domainCfg.domain] : [])
    oauthEmailDomainOptions.value = domains
    oauthEmailDomain.value = saved.email_domain || saved.domain || oauthEmailDomainOptions.value[0] || ''
    oauthEmailLoaded.value = true
  }).finally(() => { oauthEmailLoading.value = false })
}
async function saveOauthEmailConfig() {
  oauthEmailSaving.value = true
  try {
    sessionStorage.setItem(OAUTH_EMAIL_STORAGE_KEY, JSON.stringify({
      mail_provider: oauthEmailMailProvider.value,
      luckmail_email_type: oauthEmailLuckmailEmailType.value,
      luckmail_preferred_domain: oauthEmailLuckmailDomain.value,
      email_domain: oauthEmailDomain.value,
    }))
    message.value = 'OAuth 邮箱绑定配置已保存'
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    scheduleMessageClear(5000)
  } catch (e) { console.error(e) }
  oauthEmailSaving.value = false
}

async function loadOauthPhoneSmsConfig({ silent = false } = {}) {
  oauthPhoneSmsLoading.value = true
  try {
    const cfg = await api.getOAuthPhoneSmsConfig()
    oauthPhoneSmsStatus.value = cfg || {}
    oauthPhoneSmsForm.value = {
      provider: OAUTH_PHONE_PROVIDER_VALUES.includes(cfg?.provider) ? cfg.provider : 'phone_pool',
      hero_sms_api_key: '',
      hero_sms_country: cfg?.hero_sms_country || '187',
      hero_sms_min_price: cfg?.hero_sms_min_price || '',
      hero_sms_max_price: cfg?.hero_sms_max_price || '',
      hero_sms_price_mode: cfg?.hero_sms_price_mode || 'lowest',
      smsbower_api_key: '',
      smsbower_country: cfg?.smsbower_country || '187',
      smsbower_min_price: cfg?.smsbower_min_price || '',
      smsbower_max_price: cfg?.smsbower_max_price || '',
      smsbower_price_mode: cfg?.smsbower_price_mode || 'lowest',
      smscloud_api_key: '',
      smscloud_country: cfg?.smscloud_country || '187',
      smscloud_min_price: cfg?.smscloud_min_price || '',
      smscloud_max_price: cfg?.smscloud_max_price || '',
      smscloud_price_mode: cfg?.smscloud_price_mode || 'ceiling',
      oasis_sms_cdks: '',
      oasis_sms_cdk_file: cfg?.oasis_sms_cdk_file || 'oasis-cdk-accounts.jsonl',
      oasis_sms_base_url: cfg?.oasis_sms_base_url || 'https://sms.oapi.vip',
      oasis_sms_poll_attempts: cfg?.oasis_sms_poll_attempts || '24',
      oasis_sms_poll_interval_ms: cfg?.oasis_sms_poll_interval_ms || '5000',
      oasis_sms_account_map_file: cfg?.oasis_sms_account_map_file || 'oasis-cdk-accounts.jsonl',
      tujie_sms_cdks: '',
      tujie_sms_cdk_file: cfg?.tujie_sms_cdk_file || '',
      tujie_sms_base_url: cfg?.tujie_sms_base_url || 'https://tujie.xyz/api',
      tujie_sms_poll_attempts: cfg?.tujie_sms_poll_attempts || '24',
      tujie_sms_poll_interval_ms: cfg?.tujie_sms_poll_interval_ms || '5000',
      tujie_sms_account_map_file: cfg?.tujie_sms_account_map_file || 'tujie-cdk-accounts.jsonl',
    }
    await loadOauthPhoneSmsCountries(oauthPhoneSmsForm.value.provider)
  } catch (e) {
    if (!silent) {
      setMessage(e.message || '加载 OAuth 接码配置失败', 'error')
    }
  } finally {
    oauthPhoneSmsLoading.value = false
  }
}

function normalizeOauthPhoneSmsCountryOptions(options) {
  return (Array.isArray(options) ? options : [])
    .map(option => ({
      value: String(option?.value || '').trim(),
      label: String(option?.label || option?.value || '').trim(),
    }))
    .filter(option => option.value)
}

async function loadOauthPhoneSmsCountries(provider = oauthPhoneSmsForm.value.provider) {
  const normalizedProvider = String(provider || 'phone_pool').trim()
  const requestId = ++oauthPhoneSmsCountryRequestId
  const isCurrentRequest = () => requestId === oauthPhoneSmsCountryRequestId
    && String(oauthPhoneSmsForm.value.provider || 'phone_pool').trim() === normalizedProvider
  oauthPhoneSmsCountryError.value = ''
  oauthPhoneSmsCountryDropdownOpen.value = false
  if (normalizedProvider === 'phone_pool' || isCdkOauthPhoneProvider(normalizedProvider)) {
    oauthPhoneSmsCountryOptions.value = []
    oauthPhoneSmsCountrySearch.value = ''
    oauthPhoneSmsCountriesLoading.value = false
    return { provider: normalizedProvider, options: [], committed: isCurrentRequest() }
  }
  oauthPhoneSmsCountriesLoading.value = true
  try {
    const result = await api.getOAuthPhoneSmsCountries(normalizedProvider)
    const options = Array.isArray(result.options) && result.options.length
      ? result.options
      : (oauthPhoneSmsCountryFallbackOptions[normalizedProvider] || [])
    const normalizedOptions = normalizeOauthPhoneSmsCountryOptions(options)
    if (!isCurrentRequest()) return { provider: normalizedProvider, options: normalizedOptions, committed: false }
    oauthPhoneSmsCountryOptions.value = normalizedOptions
    oauthPhoneSmsCountryError.value = result.fallback && result.error ? result.error : ''
    return { provider: normalizedProvider, options: normalizedOptions, committed: true }
  } catch (e) {
    const fallbackOptions = normalizeOauthPhoneSmsCountryOptions(oauthPhoneSmsCountryFallbackOptions[normalizedProvider] || [])
    if (!isCurrentRequest()) return { provider: normalizedProvider, options: fallbackOptions, committed: false }
    oauthPhoneSmsCountryOptions.value = fallbackOptions
    oauthPhoneSmsCountryError.value = e.message || '国家列表加载失败，已使用兜底列表'
    return { provider: normalizedProvider, options: fallbackOptions, committed: true }
  } finally {
    if (isCurrentRequest()) {
      oauthPhoneSmsCountriesLoading.value = false
      oauthPhoneSmsCountrySearch.value = currentOauthPhoneSmsCountryLabel.value
    }
  }
}

function applyLoadedOauthPhoneSmsDefault(provider, loadResult) {
  const normalizedProvider = String(provider || 'phone_pool').trim()
  const currentProvider = String(oauthPhoneSmsForm.value.provider || 'phone_pool').trim()
  if (!loadResult?.committed || loadResult.provider !== normalizedProvider || currentProvider !== normalizedProvider) return false

  const defaultCountry = loadResult.options?.[0]?.value || '187'
  if (normalizedProvider === 'hero_sms' && !oauthPhoneSmsForm.value.hero_sms_country) {
    oauthPhoneSmsForm.value.hero_sms_country = defaultCountry
  } else if (normalizedProvider === 'smsbower' && !oauthPhoneSmsForm.value.smsbower_country) {
    oauthPhoneSmsForm.value.smsbower_country = defaultCountry
  } else if (normalizedProvider === 'smscloud' && !oauthPhoneSmsForm.value.smscloud_country) {
    oauthPhoneSmsForm.value.smscloud_country = defaultCountry
  }
  return true
}

function selectOauthPhoneSmsCountry(value) {
  const country = String((value && typeof value === 'object' ? value.value : value) || '').trim()
  if (oauthPhoneSmsForm.value.provider === 'hero_sms') {
    oauthPhoneSmsForm.value.hero_sms_country = country
  } else if (oauthPhoneSmsForm.value.provider === 'smsbower') {
    oauthPhoneSmsForm.value.smsbower_country = country
  } else if (oauthPhoneSmsForm.value.provider === 'smscloud') {
    oauthPhoneSmsForm.value.smscloud_country = country
  }
  const option = oauthPhoneSmsCountryOptions.value.find(item => item.value === country)
  oauthPhoneSmsCountrySearch.value = String(
    (value && typeof value === 'object' ? value.label : '') || option?.label || country
  ).trim()
  oauthPhoneSmsCountryDropdownOpen.value = false
}

function openOauthPhoneSmsCountryDropdown() {
  if (oauthPhoneSmsLoading.value || oauthPhoneSmsSaving.value || oauthPhoneSmsCountriesLoading.value) return
  oauthPhoneSmsCountryDropdownOpen.value = true
}

function handleOauthPhoneSmsCountryInput() {
  if (oauthPhoneSmsLoading.value || oauthPhoneSmsSaving.value || oauthPhoneSmsCountriesLoading.value) return
  oauthPhoneSmsCountryDropdownOpen.value = true
}

function toggleOauthPhoneSmsCountryDropdown() {
  if (oauthPhoneSmsLoading.value || oauthPhoneSmsSaving.value || oauthPhoneSmsCountriesLoading.value) return
  oauthPhoneSmsCountryDropdownOpen.value = !oauthPhoneSmsCountryDropdownOpen.value
}

function closeOauthPhoneSmsCountryDropdownSoon() {
  window.setTimeout(() => {
    oauthPhoneSmsCountryDropdownOpen.value = false
    if (!String(oauthPhoneSmsCountrySearch.value || '').trim()) {
      oauthPhoneSmsCountrySearch.value = currentOauthPhoneSmsCountryLabel.value
    }
  }, 120)
}

async function saveOauthPhoneSmsConfig() {
  oauthPhoneSmsSaving.value = true
  try {
    const result = await api.saveOAuthPhoneSmsConfig(oauthPhoneSmsForm.value)
    oauthPhoneSmsStatus.value = result || {}
    oauthPhoneSmsForm.value.hero_sms_api_key = ''
    oauthPhoneSmsForm.value.smsbower_api_key = ''
    oauthPhoneSmsForm.value.smscloud_api_key = ''
    oauthPhoneSmsForm.value.oasis_sms_cdks = ''
    oauthPhoneSmsForm.value.tujie_sms_cdks = ''
    setMessage(result.message || 'OAuth 接码配置已保存')
    await loadOauthPhoneSmsConfig()
  } catch (e) {
    setMessage(e.message || '保存 OAuth 接码配置失败', 'error')
  } finally {
    oauthPhoneSmsSaving.value = false
  }
}

async function saveOauthConfig() {
  if (oauthConfigTab.value === 'phone_sms') {
    await saveOauthPhoneSmsConfig()
    return
  }
  if (oauthConfigTab.value === 'phone') {
    saveOauthPhoneConfig()
    setMessage(oauthBindPhone.value ? 'OAuth 手机号绑定已启用' : 'OAuth 已切换为邮箱绑定')
    return
  }
  if (oauthConfigTab.value === 'proxy') {
    saveOauthProxyConfig()
    setMessage('OAuth 代理配置已保存')
    return
  }
  await saveOauthEmailConfig()
}

function loadOauthProxyConfig() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(OAUTH_PROXY_STORAGE_KEY) || '{}')
    oauthProxyEnabled.value = Boolean(saved.enabled)
    oauthProxyMode.value = ['single', 'pool', 'api'].includes(saved.mode) ? saved.mode : 'single'
    oauthBrowserMode.value = ['protocol', 'roxy'].includes(saved.browserMode) ? saved.browserMode : 'protocol'
    oauthProxyUrl.value = saved.proxyUrl || ''
    oauthProxyPoolText.value = saved.proxyPoolText || ''
    oauthProxyApiProvider.value = saved.proxyApiProvider === '1024proxy' ? '1024proxy' : 'cliproxy'
    oauthProxyApiCountry.value = String(saved.proxyApiCountry || 'US').trim().toUpperCase() || 'US'
  } catch (_) {
    // ignore broken local storage
  }
}

function loadOauthPhoneConfig() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(OAUTH_PHONE_STORAGE_KEY) || '{}')
    oauthBindPhone.value = Boolean(saved.bind_phone)
  } catch (_) {
    // ignore broken local storage
  }
}

function saveOauthPhoneConfig() {
  try {
    sessionStorage.setItem(OAUTH_PHONE_STORAGE_KEY, JSON.stringify({
      bind_phone: oauthBindPhone.value,
    }))
  } catch (_) {
    // ignore local storage write errors
  }
}

function saveOauthProxyConfig() {
  try {
    sessionStorage.setItem(OAUTH_PROXY_STORAGE_KEY, JSON.stringify({
      enabled: oauthProxyEnabled.value,
      mode: oauthProxyMode.value,
      browserMode: oauthBrowserMode.value,
      proxyUrl: oauthProxyUrl.value,
      proxyPoolText: oauthProxyPoolText.value,
      proxyApiProvider: oauthProxyApiProvider.value,
      proxyApiCountry: String(oauthProxyApiCountry.value || 'US').trim().toUpperCase() || 'US',
    }))
  } catch (_) {
    // ignore local storage write errors
  }
}

function resetOauthProxyConfig() {
  oauthProxyEnabled.value = false
  oauthProxyMode.value = 'single'
  oauthBrowserMode.value = 'protocol'
  oauthProxyUrl.value = ''
  oauthProxyPoolText.value = ''
  oauthProxyApiProvider.value = 'cliproxy'
  oauthProxyApiCountry.value = 'US'
}

function buildOauthProxyPayload() {
  const browserPayload = oauthBrowserMode.value === 'roxy' ? { oauth_browser_mode: 'roxy' } : {}
  if (!oauthProxyEnabled.value) return browserPayload
  if (oauthProxyMode.value === 'single') {
    return oauthProxyUrl.value ? { ...browserPayload, proxy_url: oauthProxyUrl.value } : browserPayload
  }
  if (oauthProxyMode.value === 'pool') {
    return oauthProxyPoolText.value ? { ...browserPayload, proxy_pool_text: oauthProxyPoolText.value } : browserPayload
  }
  return {
    ...browserPayload,
    proxy_api_provider: oauthProxyApiProvider.value || 'cliproxy',
    proxy_api_country: String(oauthProxyApiCountry.value || 'US').trim().toUpperCase() || 'US',
    ...(oauthProxyUrl.value ? { proxy_url: oauthProxyUrl.value } : {}),
  }
}

function buildOauthEmailPayload() {
  const bindPhone = Boolean(oauthBindPhone.value)
  const useRoxyBrowser = oauthBrowserMode.value === 'roxy'
  return {
    protocol_only: !useRoxyBrowser,
    bind_email: !bindPhone,
    bind_phone: bindPhone,
    ...buildOauthMailProviderPayload(),
  }
}

function buildOauthMailProviderPayload() {
  return {
    ...(oauthEmailMailProvider.value ? { mail_provider: oauthEmailMailProvider.value } : {}),
    ...(oauthEmailMailProvider.value === 'luckmail' && oauthEmailLuckmailEmailType.value
      ? { luckmail_email_type: oauthEmailLuckmailEmailType.value }
      : {}),
    ...(oauthEmailMailProvider.value === 'luckmail' && oauthEmailLuckmailDomain.value
      ? { luckmail_preferred_domain: oauthEmailLuckmailDomain.value }
      : {}),
    ...(oauthEmailMailProvider.value && oauthEmailMailProvider.value !== 'luckmail' && oauthEmailMailProvider.value !== 'outlook' && oauthEmailDomain.value
      ? { email_domain: oauthEmailDomain.value }
      : {}),
  }
}

function buildOauthPhoneSmsPayload() {
  if (!oauthBindPhone.value) return {}
  const provider = oauthPhoneSmsForm.value.provider || 'phone_pool'
  const country = provider === 'hero_sms'
    ? oauthPhoneSmsForm.value.hero_sms_country
    : provider === 'smsbower'
      ? oauthPhoneSmsForm.value.smsbower_country
      : provider === 'smscloud'
        ? oauthPhoneSmsForm.value.smscloud_country
        : ''
  return {
    ...(provider !== 'phone_pool' ? { oauth_phone_sms_provider: provider } : {}),
    ...(country ? { oauth_phone_sms_country: country } : {}),
    ...(provider === 'hero_sms' && oauthPhoneSmsForm.value.hero_sms_max_price
      ? { oauth_phone_sms_max_price: oauthPhoneSmsForm.value.hero_sms_max_price }
      : {}),
    ...(provider === 'smsbower' && oauthPhoneSmsForm.value.smsbower_max_price
      ? { oauth_phone_sms_max_price: oauthPhoneSmsForm.value.smsbower_max_price }
      : {}),
    ...(provider === 'smscloud' && oauthPhoneSmsForm.value.smscloud_max_price
      ? { oauth_phone_sms_max_price: oauthPhoneSmsForm.value.smscloud_max_price }
      : {}),
    ...(isCdkOauthPhoneProvider(provider) && (
      provider === 'tujie'
        ? oauthPhoneSmsForm.value.tujie_sms_cdks
        : oauthPhoneSmsForm.value.oasis_sms_cdks
    )
      ? {
          oauth_oasis_sms_cdks: provider === 'tujie'
            ? oauthPhoneSmsForm.value.tujie_sms_cdks
            : oauthPhoneSmsForm.value.oasis_sms_cdks,
        }
      : {}),
  }
}

function buildDashboardOauthPayload() {
  return {
    ...buildOauthProxyPayload(),
    ...buildOauthEmailPayload(),
    ...buildOauthPhoneSmsPayload(),
  }
}

function buildDashboardReloginPayload() {
  const proxyPayload = { ...buildOauthProxyPayload() }
  delete proxyPayload.oauth_browser_mode
  return {
    ...proxyPayload,
    ...buildOauthMailProviderPayload(),
    refresh_auth_session: true,
  }
}

const oauthProxySummary = computed(() => {
  if (oauthBrowserMode.value === 'roxy' && !oauthProxyEnabled.value) return 'OAuth授权/补登录将使用 RoxyBrowser 模式直连。'
  if (oauthBrowserMode.value === 'roxy' && oauthProxyEnabled.value) return 'OAuth授权/补登录将使用 RoxyBrowser 模式，并应用下方代理配置。'
  if (!oauthProxyEnabled.value) return 'OAuth授权/补登录当前直连。'
  if (oauthProxyMode.value === 'single') return oauthProxyUrl.value ? '单个/批量 OAuth授权和补登录会使用这条代理。' : '请填写单条代理地址。'
  if (oauthProxyMode.value === 'pool') {
    const count = oauthProxyPoolText.value.split(/\r?\n/).map(v => v.trim()).filter(Boolean).length
    return count ? `批量 OAuth授权和补登录会从 ${count} 条代理中按账号随机选择。` : '请导入或粘贴代理池。'
  }
  return `OAuth授权/补登录会通过 ${oauthProxyApiProvider.value} API 每个账号取一次 ${String(oauthProxyApiCountry.value || 'US').trim().toUpperCase() || 'US'} 代理。`
})

const oauthPhoneSmsConfigured = computed(() => {
  const provider = oauthPhoneSmsForm.value.provider
  if (provider === 'phone_pool') return true
  if (provider === 'smsbower') return Boolean(oauthPhoneSmsStatus.value.smsbower_api_key_present)
  if (provider === 'smscloud') return Boolean(oauthPhoneSmsStatus.value.smscloud_api_key_present)
  if (provider === 'oasis') return Number(oauthPhoneSmsStatus.value.oasis_sms_cdk_count || 0) > 0
  if (provider === 'tujie') {
    return Number(oauthPhoneSmsStatus.value.tujie_sms_cdk_count || 0) > 0 && Boolean(oauthPhoneSmsStatus.value.tujie_sms_base_url)
  }
  return Boolean(oauthPhoneSmsStatus.value.hero_sms_api_key_present)
})

const currentOauthPhoneSmsCountry = computed(() => {
  if (oauthPhoneSmsForm.value.provider === 'smsbower') return String(oauthPhoneSmsForm.value.smsbower_country || '').trim()
  if (oauthPhoneSmsForm.value.provider === 'smscloud') return String(oauthPhoneSmsForm.value.smscloud_country || '').trim()
  if (oauthPhoneSmsForm.value.provider === 'hero_sms') return String(oauthPhoneSmsForm.value.hero_sms_country || '').trim()
  return ''
})

const currentOauthPhoneSmsCountryLabel = computed(() => {
  const selected = currentOauthPhoneSmsCountry.value
  if (!selected) return ''
  const option = (oauthPhoneSmsCountryOptions.value || []).find(item => item.value === selected)
  return option?.label || `当前配置 / ${selected}`
})

const oauthPhoneSmsCountryOptionsForSelect = computed(() => {
  const selected = currentOauthPhoneSmsCountry.value
  const sourceOptions = oauthPhoneSmsCountryOptions.value || []
  const query = String(oauthPhoneSmsCountrySearch.value || '').trim().toLowerCase()
  const selectedOption = sourceOptions.find(option => option.value === selected)
  const selectedLabel = String(selectedOption?.label || '').trim().toLowerCase()
  let options = sourceOptions
  if (query && query !== selectedLabel) {
    options = sourceOptions.filter(option => {
      const text = `${option.value} ${option.label}`.toLowerCase()
      return text.includes(query)
    })
  }
  const selectedSearchText = `${selected} ${selectedOption?.label || ''}`.toLowerCase()
  if (selected && !options.some(option => option.value === selected) && (!query || selectedSearchText.includes(query))) {
    const known = sourceOptions.find(option => option.value === selected)
    return [{ value: selected, label: known?.label || `当前配置 / ${selected}` }, ...options]
  }
  return options
})

const accountMetadataEditUnchanged = computed(() => {
  const account = accountTypeEditAccount.value
  if (!account) return true
  return String(accountTypeEditValue.value || '').toLowerCase() === String(account.account_type || 'free').toLowerCase()
    && String(accountStatusEditValue.value || '').toLowerCase() === String(account.status || 'pending').toLowerCase()
    && String(accountBindProviderEditValue.value || '').toLowerCase() === String(account.last_bind_provider || '').toLowerCase()
})

const batchAccountMetadataHasChanges = computed(() =>
  Boolean(
    batchAccountEditType.value !== BATCH_METADATA_SKIP
    || batchAccountEditStatus.value !== BATCH_METADATA_SKIP
    || batchAccountEditProvider.value !== BATCH_METADATA_SKIP,
  ),
)

function setMessage(text, type = 'success') {
  message.value = text
  messageClass.value = type === 'error'
    ? 'bg-red-500/10 text-red-400 border-red-500/20'
    : 'bg-green-500/10 text-green-400 border-green-500/20'
  scheduleMessageClear(8000)
}

function fmtTs(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

onMounted(() => {
  loadOauthProxyConfig()
  loadOauthPhoneConfig()
  watch(oauthConfigOpen, (open) => {
    if (open) {
      loadOauthEmailConfig()
      loadOauthPhoneSmsConfig()
    }
  })
})
watch(
  [oauthProxyEnabled, oauthProxyMode, oauthBrowserMode, oauthProxyUrl, oauthProxyPoolText, oauthProxyApiProvider, oauthProxyApiCountry],
  saveOauthProxyConfig,
)
watch(oauthBindPhone, saveOauthPhoneConfig)
watch(
  () => oauthPhoneSmsForm.value.provider,
  async (provider) => {
    const loadResult = await loadOauthPhoneSmsCountries(provider)
    applyLoadedOauthPhoneSmsDefault(provider, loadResult)
  },
)
const adminReady = computed(() => !!props.adminStatus?.configured)
const loginDisabled = computed(() => false)
const kickDisabled = computed(() => !adminReady.value)
const deleteDisabled = computed(() => false)
const editableAccountTypeOptions = [
  { value: 'free', label: 'Free' },
  { value: 'team', label: 'Team' },
  { value: 'plus', label: 'Plus' },
  { value: 'pro', label: 'Pro' },
]
const editableAccountStatusOptions = [
  { value: 'active', label: 'Active' },
  { value: 'exhausted', label: 'Used up' },
  { value: 'standby', label: 'Standby' },
  { value: 'stashed', label: '暂存' },
  { value: 'pending', label: 'Pending' },
  { value: 'personal', label: 'Personal' },
  { value: 'plus', label: 'Plus' },
  { value: 'session_only', label: 'Session Only/Active' },
  { value: 'auth_invalid', label: 'token失效' },
  { value: 'auth_revoked', label: '掉授权' },
  { value: 'orphan', label: '孤立' },
  { value: 'fail', label: 'Fail/废弃' },
]
const editableBindProviderOptions = [
  { value: '', label: '未绑定' },
  { value: 'pix', label: 'Pix' },
  { value: 'paypal', label: 'PayPal' },
  { value: 'upi', label: 'UPI' },
  { value: 'ideal', label: 'iDEAL' },
  { value: 'kakao_pay', label: 'Kakao Pay' },
  { value: 'momo_vn', label: 'MoMo' },
  { value: 'gcash_ph', label: 'GCash' },
  { value: 'gopay', label: 'GoPay' },
  { value: 'card', label: 'Card' },
  { value: 'external_import', label: '外部导入' },
]

const allAccounts = computed(() => props.status?.accounts || [])
const accountFacets = computed(() => buildAccountFacets(allAccounts.value))
const accountSearchIndex = computed(() => buildAccountSearchIndex(allAccounts.value))
const twoFactorCounts = computed(() => allAccounts.value.reduce((counts, account) => {
  counts[accountTwoFactorEnabled(account) ? 'enabled' : 'disabled'] += 1
  return counts
}, { enabled: 0, disabled: 0 }))

function accountBindProviderFilterLabel(value) {
  const normalized = String(value || '').trim().toLowerCase()
  if (normalized === '__none__' || normalized === '') return '未绑定'
  return editableBindProviderOptions.find(option => option.value === normalized)?.label || normalized
}

function accountRegisterTs(acc) {
  return Number(acc?.created_at || acc?.registered_at || acc?.register_at || 0) || 0
}

function accountExportTs(acc) {
  return Number(acc?.credentials_exported_at || 0) || 0
}

function accountKakaoLinkExtracted(acc) {
  const lastQuota = acc?.last_quota && typeof acc.last_quota === 'object' ? acc.last_quota : {}
  const provider = String(acc?.last_bind_provider || '').trim().toLowerCase()
  const bindStatus = String(acc?.last_bind_status || '').trim().toLowerCase()
  return Boolean(acc?.kakao_link_extracted)
    || Boolean(acc?.kakao_link_extracted_at)
    || Boolean(lastQuota.kakao_link_extracted)
    || (provider === 'kakao_pay' && bindStatus === 'link_extracted')
}

function displayEmail(acc) {
  return acc?.display_email || acc?.original_email || acc?.email || ''
}

function displayEmailPreview(acc) {
  const email = displayEmail(acc)
  if (!email) return ''
  const maxVisible = 34
  if (email.length <= maxVisible) return email
  return `${email.slice(0, maxVisible)}…`
}

function dateKey(date) {
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return ''
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function normalizeAccountPageSize(value) {
  return normalizeStoredPageSize(value, DEFAULT_ACCOUNT_PAGE_SIZE, ACCOUNT_PAGE_SIZE_VALUES)
}

function loadAccountPageSize() {
  try {
    return normalizeAccountPageSize(sessionStorage.getItem(ACCOUNT_PAGE_SIZE_STORAGE_KEY))
  } catch {
    return DEFAULT_ACCOUNT_PAGE_SIZE
  }
}

function saveAccountPageSize() {
  try {
    sessionStorage.setItem(ACCOUNT_PAGE_SIZE_STORAGE_KEY, String(accountPageSize.value))
  } catch {}
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
  const values = new Set([dateKey(new Date()), ...accountFacets.value.bindDateKeys])
  return Array.from(values)
    .filter(Boolean)
    .sort((a, b) => b.localeCompare(a))
    .map(value => ({ value, label: dateLabel(value) }))
})

const registerDateOptions = computed(() => {
  return accountFacets.value.registerDateKeys
    .map(value => ({ value, label: dateLabel(value) }))
})

const exportDateOptions = computed(() => {
  return accountFacets.value.exportDateKeys
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

const registerTimeRange = computed(() => {
  if (!registerDateFilter.value) return { start: 0, end: 0 }
  const start = dateTimeFilterTimestamp(registerDateFilter.value, registerStartTimeFilter.value, '00:00')
  const end = registerEndTimeFilter.value
    ? dateTimeFilterTimestamp(registerDateFilter.value, registerEndTimeFilter.value, '23:59') + 3599
    : dateTimeFilterTimestamp(registerDateFilter.value, '', '23:59', 59)
  return {
    start,
    end,
  }
})

const exportTimeRange = computed(() => {
  if (!exportDateFilter.value) return { start: 0, end: 0 }
  const start = dateTimeFilterTimestamp(exportDateFilter.value, exportStartTimeFilter.value, '00:00')
  const end = exportEndTimeFilter.value
    ? dateTimeFilterTimestamp(exportDateFilter.value, exportEndTimeFilter.value, '23:59') + 3599
    : dateTimeFilterTimestamp(exportDateFilter.value, '', '23:59', 59)
  return {
    start,
    end,
  }
})

function resetAccountPageAndEmit() {
  accountPageSize.value = normalizeAccountPageSize(accountPageSize.value)
  saveAccountPageSize()
  accountPage.value = 1
}

watch(
  [
    emailFilter,
    statusFilter,
    accountTypeFilter,
    twoFactorFilter,
    trialFilter,
    bindProviderFilter,
    registerDateFilter,
    registerStartTimeFilter,
    registerEndTimeFilter,
    credentialExportFilter,
    exportDateFilter,
    exportStartTimeFilter,
    exportEndTimeFilter,
    accountHubSyncFilter,
    authCredentialFilter,
    bindDateFilter,
    bindStartTimeFilter,
    bindEndTimeFilter,
    accountDisplayOrder,
    accountPageSize,
  ],
  resetAccountPageAndEmit,
)

let emailFilterTimer = null
watch(emailFilter, value => {
  if (emailFilterTimer !== null) clearTimeout(emailFilterTimer)
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) {
    deferredEmailFilter.value = ''
    emailFilterTimer = null
    return
  }
  emailFilterTimer = setTimeout(() => {
    deferredEmailFilter.value = normalized
    emailFilterTimer = null
  }, 120)
})

onBeforeUnmount(() => {
  if (emailFilterTimer !== null) clearTimeout(emailFilterTimer)
  if (twoFactorPendingClearTimer !== null) clearTimeout(twoFactorPendingClearTimer)
  messageClearScheduler.dispose()
  restoreAccountActionBackgroundInert()
})

const filteredAccounts = computed(() => {
  return filterAccountSearchIndex(accountSearchIndex.value, {
    email: deferredEmailFilter.value,
    status: statusFilter.value,
    accountType: accountTypeFilter.value,
    twoFactor: twoFactorFilter.value,
    trial: trialFilter.value,
    bindProvider: bindProviderFilter.value,
    registerRange: registerTimeRange.value,
    credentialExport: credentialExportFilter.value,
    exportRange: exportTimeRange.value,
    hubSync: accountHubSyncFilter.value,
    authCredential: authCredentialFilter.value,
    bindRange: bindTimeRange.value,
  }, accountDisplayOrder.value)
})
const accountFilteredTotal = computed(() => filteredAccounts.value.length)
const accountPoolTotal = computed(() => allAccounts.value.length)
const effectiveAccountPageSize = computed(() => normalizeAccountPageSize(accountPageSize.value))
const accountTotalPages = computed(() => {
  return Math.max(1, Math.ceil(accountFilteredTotal.value / effectiveAccountPageSize.value) || 1)
})
const accountCurrentPage = computed(() => Math.max(1, Math.min(Number(accountPage.value || 1), accountTotalPages.value)))
const accountPageStartIndex = computed(() => (accountCurrentPage.value - 1) * effectiveAccountPageSize.value)
const paginatedAccounts = computed(() => {
  return filteredAccounts.value.slice(accountPageStartIndex.value, accountPageStartIndex.value + effectiveAccountPageSize.value)
})
const accountPageStartDisplay = computed(() => accountFilteredTotal.value && paginatedAccounts.value.length ? accountPageStartIndex.value + 1 : 0)
const accountPageEndDisplay = computed(() =>
  accountFilteredTotal.value && paginatedAccounts.value.length ? Math.min(accountFilteredTotal.value, accountPageStartIndex.value + paginatedAccounts.value.length) : 0
)
const accountStatusOptions = computed(() => {
  return Array.from(accountFacets.value.statusCounts.entries())
    .sort((a, b) => statusLabel(a[0]).localeCompare(statusLabel(b[0]), 'zh-Hans-CN'))
    .map(([value, count]) => ({ value, label: statusLabel(value), count }))
})
const accountTypeOptions = computed(() => {
  return Array.from(accountFacets.value.accountTypeCounts.entries())
    .sort((a, b) => accountTypeLabel(a[0]).localeCompare(accountTypeLabel(b[0]), 'zh-Hans-CN'))
    .map(([value, count]) => ({ value, label: accountTypeLabel(value), count }))
})
const trialEligibleCount = computed(() => accountFacets.value.trialEligibleCount)
const accountBindProviderFilterOptions = computed(() => {
  const counts = accountFacets.value.bindProviderCounts
  const knownOrder = ['__none__', ...editableBindProviderOptions.map(option => option.value).filter(Boolean)]
  const known = knownOrder
    .filter((value, index, arr) => arr.indexOf(value) === index)
    .filter(value => counts.has(value))
    .map(value => ({ value, label: accountBindProviderFilterLabel(value), count: counts.get(value) || 0 }))
  const extra = Array.from(counts.entries())
    .filter(([value]) => !knownOrder.includes(value))
    .sort((a, b) => accountBindProviderFilterLabel(a[0]).localeCompare(accountBindProviderFilterLabel(b[0]), 'zh-Hans-CN'))
    .map(([value, count]) => ({ value, label: accountBindProviderFilterLabel(value), count }))
  return [...known, ...extra]
})
const credentialExportOptions = computed(() => {
  const { exported, unexported } = accountFacets.value.credentialCounts
  return [
    { value: 'unexported', label: '未导出', count: unexported },
    { value: 'exported', label: '已导出', count: exported },
  ]
})
const accountHubSyncOptions = computed(() => {
  const { synced, unsynced } = accountFacets.value.hubSyncCounts
  return [
    { value: 'unsynced', label: '未同步', count: unsynced },
    { value: 'synced', label: '已同步', count: synced },
  ]
})
const authCredentialOptions = computed(() => {
  const { hasAuth, missingAuth } = accountFacets.value.authCredentialCounts
  return [
    { value: 'missing_auth', label: '无凭证', count: missingAuth },
    { value: 'has_auth', label: '有凭证', count: hasAuth },
  ]
})
const accountSelectionIndex = computed(() => buildAccountSelectionIndex(filteredAccounts.value))
const selectedAccounts = computed(() => selectAccountsFromIndex(accountSelectionIndex.value, selectedSet.value))
const selectableEmails = computed(() => accountSelectionIndex.value.selectableEmails)
const selectedEmails = computed(() => selectedAccounts.value.map(account => account.email))
const scopedAccounts = computed(() => selectedAccounts.value.length ? selectedAccounts.value : filteredAccounts.value)
const exportableAccounts = computed(() => scopedAccounts.value)
const twoFactorSetupAccounts = computed(() => scopedAccounts.value.filter(account => !accountTwoFactorEnabled(account)))
const accountActions = computed(() => buildScopedAccountActions(scopedAccounts.value, {
  canOauthAuthorize,
  canRelogin,
  hasCodexAuthFile,
}))
const oauthAuthorizableAccounts = computed(() => accountActions.value.oauthAuthorizableAccounts)
const reloginableAccounts = computed(() => accountActions.value.reloginableAccounts)
const batchLoginableAccounts = computed(() => {
  return oauthAuthorizableAccounts.value
})
const oauthBatchTask = computed(() => {
  const task = props.runningTask
  if (!task || task.command !== 'login-batch') return null
  if (!['running', 'pending'].includes(String(task.status || ''))) return null
  if (Boolean(task.params?.refresh_auth_session)) return null
  return task
})
const reloginBatchRunning = computed(() => {
  const task = props.runningTask
  return Boolean(
    task
      && task.command === 'login-batch'
      && ['running', 'pending'].includes(String(task.status || ''))
      && Boolean(task.params?.refresh_auth_session),
  )
})
const oauthBatchRunning = computed(() => !!oauthBatchTask.value)
const oauthBatchQueuedEmails = computed(() => {
  const params = oauthBatchTask.value?.params || {}
  const emails = Array.isArray(params.emails) ? params.emails : []
  return new Set(emails.map(email => String(email || '').trim().toLowerCase()).filter(Boolean))
})
const oauthBatchAppendableAccounts = computed(() => {
  const queued = oauthBatchQueuedEmails.value
  return batchLoginableAccounts.value.filter(acc => {
    const email = String(acc.email || '').trim().toLowerCase()
    return email && !queued.has(email)
  })
})
const oauthBatchActionAccounts = computed(() =>
  oauthBatchRunning.value ? oauthBatchAppendableAccounts.value : batchLoginableAccounts.value
)
const oauthBatchButtonLabel = computed(() => {
  if (batchOauthAuthorizing.value) return oauthBatchRunning.value ? '追加中...' : '提交中...'
  const count = oauthBatchActionAccounts.value.length
  return oauthBatchRunning.value ? `追加OAuth授权 (${count})` : `批量OAuth授权 (${count})`
})
const oauthCredentialProgressTasks = computed(() => {
  const allTasks = Array.isArray(props.tasks) ? props.tasks : []
  const tasks = allTasks.filter(isOAuthCredentialTask)
  if (isOAuthCredentialTask(props.runningTask)) {
    const runningTaskId = String(props.runningTask.task_id || '')
    if (!runningTaskId || !tasks.some(task => String(task.task_id || '') === runningTaskId)) {
      tasks.unshift(props.runningTask)
    }
  }
  return tasks
})
const batchReloginButtonLabel = computed(() => {
  if (batchReloggingIn.value) return '提交中...'
  if (reloginBatchRunning.value) return '补登录运行中...'
  return `批量补登录 (${reloginableAccounts.value.length})`
})
const cpaExportableAccounts = computed(() => accountActions.value.cpaExportableAccounts)
const bindableFreeAccounts = computed(() => accountFacets.value.bindableFreeAccounts)
const refreshableQuotaAccounts = computed(() => accountActions.value.refreshableQuotaAccounts)
const invalidCredentialAccounts = computed(() => accountFacets.value.invalidCredentialAccounts)
const refreshQuotaTask = computed(() => {
  const task = props.runningTask
  if (!task || task.command !== 'refresh-quota') return null
  if (!['running', 'pending'].includes(String(task.status || ''))) return null
  return task
})
const refreshQuotaRunning = computed(() => !!refreshQuotaTask.value)
function isActiveTwoFactorTask(task) {
  return task?.command === 'setup-2fa'
    && ['running', 'pending'].includes(String(task.status || ''))
}

const twoFactorTasks = computed(() => {
  const activeTasks = Array.isArray(props.tasks) ? props.tasks : []
  const tasks = activeTasks.filter(isActiveTwoFactorTask)
  if (isActiveTwoFactorTask(props.runningTask)) {
    const runningTaskId = String(props.runningTask.task_id || '')
    if (!runningTaskId || !tasks.some(task => String(task.task_id || '') === runningTaskId)) {
      tasks.unshift(props.runningTask)
    }
  }
  return tasks
})
const twoFactorProgressTasks = computed(() => {
  const allTasks = Array.isArray(props.tasks) ? props.tasks : []
  const tasks = allTasks.filter(task => task?.command === 'setup-2fa')
  if (props.runningTask?.command === 'setup-2fa') {
    const runningTaskId = String(props.runningTask.task_id || '')
    if (!runningTaskId || !tasks.some(task => String(task.task_id || '') === runningTaskId)) {
      tasks.unshift(props.runningTask)
    }
  }
  return tasks
})
const twoFactorTask = computed(() => twoFactorTasks.value[0] || null)
const twoFactorTaskRunning = computed(() => twoFactorTasks.value.length > 0)
const twoFactorTaskEmails = computed(() => {
  const emails = new Set()
  const completed = twoFactorCompletedEmails.value
  const failed = twoFactorFailedEmails.value
  for (const task of twoFactorTasks.value) {
    for (const email of task?.params?.emails || []) {
      const normalized = String(email || '').trim().toLowerCase()
      if (normalized && !completed.has(normalized) && !failed.has(normalized)) emails.add(normalized)
    }
  }
  return emails
})

function applyTwoFactorTaskProgressEvents(tasks) {
  const pending = new Set(twoFactorPendingTaskEmails.value)
  const completed = new Set(twoFactorCompletedEmails.value)
  const failed = new Set(twoFactorFailedEmails.value)
  for (const task of tasks || []) {
    for (const event of task?.progress_events || []) {
      if (event?.stage !== 'account_2fa_progress') continue
      const email = String(event.email || '').trim().toLowerCase()
      const status = String(event.status || '').trim().toLowerCase()
      if (!email) continue
      if (status === 'enabled' || (status === 'skipped' && String(event.reason || '').trim() === 'already_enabled')) {
        completed.add(email)
        failed.delete(email)
        pending.delete(email)
      } else if (status === 'failed') {
        failed.add(email)
        completed.delete(email)
        pending.delete(email)
      } else if (status === 'skipped') {
        pending.delete(email)
      }
    }
  }
  twoFactorPendingTaskEmails.value = pending
  twoFactorCompletedEmails.value = completed
  twoFactorFailedEmails.value = failed
}

function clearTwoFactorPendingTask() {
  if (twoFactorPendingClearTimer !== null) {
    clearTimeout(twoFactorPendingClearTimer)
    twoFactorPendingClearTimer = null
  }
  twoFactorPendingTaskIds.value = new Set()
  twoFactorPendingTaskEmails.value = new Set()
}

function scheduleTwoFactorPendingTaskClear() {
  if (twoFactorPendingClearTimer !== null || !twoFactorPendingTaskEmails.value.size) return
  twoFactorPendingClearTimer = setTimeout(() => {
    twoFactorPendingClearTimer = null
    clearTwoFactorPendingTask()
  }, 3000)
}

watch(twoFactorProgressTasks, tasks => {
  applyTwoFactorTaskProgressEvents(tasks)
}, { deep: true, immediate: true })

function isOAuthCredentialTask(task) {
  const command = String(task?.command || '')
  if (Boolean(task?.params?.refresh_auth_session)) return false
  return command === 'login-batch' || command.startsWith('login:')
}

function oauthCredentialEmailFromTask(task) {
  const resultEmail = String(task?.result?.email || '').trim().toLowerCase()
  if (resultEmail) return resultEmail
  const paramEmail = String(task?.params?.email || '').trim().toLowerCase()
  if (paramEmail) return paramEmail
  const command = String(task?.command || '')
  return command.startsWith('login:') ? command.slice('login:'.length).trim().toLowerCase() : ''
}

function applyOAuthCredentialTaskProgressEvents(tasks) {
  const completed = new Set(oauthCredentialCompletedEmails.value)
  for (const task of tasks || []) {
    if (!isOAuthCredentialTask(task)) continue
    for (const event of task?.progress_events || []) {
      const stage = String(event?.stage || '')
      if (stage === 'account_login_done') {
        const email = String(event.email || '').trim().toLowerCase()
        if (email) completed.add(email)
      }
    }
    if (String(task?.status || '') === 'completed' && String(task?.result?.auth_file || '').trim()) {
      const email = oauthCredentialEmailFromTask(task)
      if (email) completed.add(email)
    }
  }
  oauthCredentialCompletedEmails.value = completed
}

watch(oauthCredentialProgressTasks, tasks => {
  applyOAuthCredentialTaskProgressEvents(tasks)
}, { deep: true, immediate: true })

watch(twoFactorTasks, tasks => {
  if (!twoFactorPendingTaskEmails.value.size) return
  const activeTaskIds = new Set(tasks.map(task => String(task?.task_id || '')).filter(Boolean))
  const hasActivePendingTask = [...twoFactorPendingTaskIds.value].some(taskId => activeTaskIds.has(taskId))
  if (hasActivePendingTask) {
    if (twoFactorPendingClearTimer !== null) {
      clearTimeout(twoFactorPendingClearTimer)
      twoFactorPendingClearTimer = null
    }
    if (twoFactorTaskEmails.value.size) {
      twoFactorPendingTaskEmails.value = new Set([
        ...twoFactorPendingTaskEmails.value,
        ...twoFactorTaskEmails.value,
      ])
    }
    return
  }
  if (!tasks.length) scheduleTwoFactorPendingTaskClear()
}, { deep: true, immediate: true })

watch(allAccounts, accounts => {
  const completed = new Set(twoFactorCompletedEmails.value)
  const failed = new Set(twoFactorFailedEmails.value)
  for (const account of accounts) {
    const email = accountTwoFactorEmailKey(account)
    if (!email) continue
    if (account?.two_factor_enabled === true || String(account?.totp_status || '').trim().toLowerCase() === 'enabled') {
      completed.delete(email)
      failed.delete(email)
    }
  }
  twoFactorCompletedEmails.value = completed
  twoFactorFailedEmails.value = failed

  if (!twoFactorPendingTaskEmails.value.size) return
  const pending = new Set(twoFactorPendingTaskEmails.value)
  const allFinished = [...pending].every(email => {
    const account = accounts.find(item => String(item?.email || '').trim().toLowerCase() === email)
    return !account || accountTwoFactorEnabled(account)
  })
  if (allFinished) clearTwoFactorPendingTask()
})

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
  return selectedEmails.value.length
    ? `刷新选中额度 (${refreshableQuotaAccounts.value.length})`
    : `刷新筛选额度 (${refreshableQuotaAccounts.value.length})`
})
const lastRefreshQuotaTaskId = ref('')
const pendingRefreshQuotaTaskId = ref('')

function refreshQuotaResultCount(result, key) {
  const value = result?.[key]
  if (Array.isArray(value)) return value.length
  if (value && typeof value === 'object' && Number.isFinite(Number(value.count))) return Number(value.count)
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function formatRefreshQuotaResultSummary(task) {
  const result = task?.result || {}
  const progress = task?.progress || {}
  const total = Number(result.total ?? progress.total ?? 0)
  const ok = refreshQuotaResultCount(result, 'ok') || Number(progress.ok || 0)
  const exhausted = refreshQuotaResultCount(result, 'exhausted') || Number(progress.exhausted || 0)
  const failed = refreshQuotaResultCount(result, 'failed') || Number(progress.failed || 0)
  const skipped = refreshQuotaResultCount(result, 'skipped') || Number(progress.skipped || 0)
  const networkError = refreshQuotaResultCount(result, 'network_error') || Number(progress.network_error || 0)
  const missing = refreshQuotaResultCount(result, 'missing')
  const parts = [
    `成功 ${Number.isFinite(ok) ? ok : 0}`,
    `额度用尽 ${Number.isFinite(exhausted) ? exhausted : 0}`,
    `认证失败 ${Number.isFinite(failed) ? failed : 0}`,
    `跳过 ${Number.isFinite(skipped) ? skipped : 0}`,
    `临时错误 ${Number.isFinite(networkError) ? networkError : 0}`,
  ]
  if (missing) parts.push(`不存在 ${missing}`)
  const totalText = Number.isFinite(total) && total > 0 ? `，共 ${total} 个` : ''
  return `刷新额度完成${totalText}: ${parts.join('，')}`
}

watch(
  () => props.runningTask,
  (task) => {
    if (!task || task.command !== 'refresh-quota') return
    const progress = task.progress || {}
    const current = Number(progress.current || 0)
    const total = Number(progress.total || task.result?.total || 0)
    const ok = Number(progress.ok || 0)
    const exhausted = Number(progress.exhausted || 0)
    const failed = Number(progress.failed || 0)
    const skipped = Number(progress.skipped || 0)
    const networkError = Number(progress.network_error || 0)
    const progressText = Number.isFinite(total) && total > 0
      ? `${Number.isFinite(current) ? current : 0}/${total}`
      : '进行中'
    message.value = `刷新额度中 (${progressText}): 成功 ${Number.isFinite(ok) ? ok : 0}，额度用尽 ${Number.isFinite(exhausted) ? exhausted : 0}，认证失败 ${Number.isFinite(failed) ? failed : 0}，跳过 ${Number.isFinite(skipped) ? skipped : 0}，临时错误 ${Number.isFinite(networkError) ? networkError : 0}`
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
  }
)

watch(
  () => props.refreshQuotaResultTask,
  (task) => {
    if (!task || task.command !== 'refresh-quota') return
    const taskId = String(task.task_id || '')
    if (!pendingRefreshQuotaTaskId.value) {
      if (taskId) lastRefreshQuotaTaskId.value = taskId
      return
    }
    if (pendingRefreshQuotaTaskId.value && taskId !== pendingRefreshQuotaTaskId.value) return
    if (taskId && taskId === lastRefreshQuotaTaskId.value) return
    lastRefreshQuotaTaskId.value = taskId
    if (String(task.status || '') === 'failed') {
      message.value = `刷新额度失败: ${task.error || task.result?.message || taskId || '后台任务失败'}`
      messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
    } else {
      message.value = formatRefreshQuotaResultSummary(task)
      messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    }
    pendingRefreshQuotaTaskId.value = ''
    scheduleMessageClear(
      15000,
      () => !refreshQuotaRunning.value && taskId === lastRefreshQuotaTaskId.value,
    )
  }
)
const allSelectableChecked = computed(() =>
  selectableEmails.value.length > 0 && selectedEmails.value.length === selectableEmails.value.length
)
const someSelectableChecked = computed(() =>
  selectedEmails.value.length > 0 && selectedEmails.value.length < selectableEmails.value.length
)
const activeSubscription = computed(() => subscriptionDialog.value.data?.subscription || {})
const subscriptionPlanLabel = computed(() =>
  activeSubscription.value.plan_label || accountTypeLabel(activeSubscription.value.plan_type) || 'Unknown'
)
const subscriptionPlanKey = computed(() =>
  activeSubscription.value.plan_key || activeSubscription.value.plan_type || '-'
)
const subscriptionSummaryItems = computed(() => {
  const sub = activeSubscription.value
  const seats = sub.seats || {}
  return [
    {
      label: '剩余时间',
      value: sub.remaining_days === null || sub.remaining_days === undefined ? '-' : `${sub.remaining_days} 天`,
      meta: sub.ends_at ? `至 ${formatSubscriptionDate(sub.ends_at, { dateOnly: true })}` : '',
      accent: true,
    },
    { label: '套餐 ID', value: subscriptionPlanKey.value, meta: [sub.billing_period, sub.currency].filter(Boolean).join(' · ') },
    { label: '渠道', value: sub.channel_label || subscriptionChannelLabel(sub.purchase_origin), meta: sub.payment_processor || '' },
    {
      label: '席位',
      value: seats.used !== null && seats.used !== undefined && seats.total !== null && seats.total !== undefined
        ? `${seats.used} / ${seats.total}`
        : '-',
    },
    { label: '是否曾付费', value: yesNo(sub.paid) },
  ]
})
const subscriptionTimelineItems = computed(() => {
  const sub = activeSubscription.value
  return [
    { label: '订阅开始', value: formatSubscriptionDate(sub.starts_at) },
    { label: '订阅结束', value: formatSubscriptionDate(sub.ends_at) },
    { label: '下次续费', value: formatSubscriptionDate(sub.renews_at) },
  ]
})
const subscriptionAvailablePlanItems = computed(() => {
  const plans = activeSubscription.value.available_plans
  return Array.isArray(plans) && plans.length ? plans : []
})
const subscriptionDiscountItems = computed(() => {
  const discounts = activeSubscription.value.applied_discounts
  if (!Array.isArray(discounts)) return []
  return discounts.map(discount => ({
    id: discount?.id || '',
    label: `${discount?.percent_off ?? '-'}% off · ${discount?.duration_in_months ?? '-'} 期 · 至 ${formatSubscriptionDate(discount?.ends_at)}${discount?.end_behavior ? ` · ${discount.end_behavior}` : ''}`,
  }))
})
const subscriptionRawJson = computed(() => {
  if (!subscriptionDialog.value.data?.raw) return '{}'
  return JSON.stringify(subscriptionDialog.value.data.raw, null, 2)
})
const subscriptionAccountId = computed(() => subscriptionDialog.value.data?.account_id || '-')
const activeLatestMail = computed(() => latestMailDialog.value.data?.message || null)
const latestMailSrcdoc = computed(() => {
  const mail = activeLatestMail.value
  if (!mail) return ''
  const html = String(mail.html || mail.content || '').trim()
  if (String(mail.html || '').trim()) return html
  const text = String(mail.text || '').replace(/[&<>"']/g, char => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[char])
  return `<pre style="white-space:pre-wrap;font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;color:#111827;padding:16px;">${text || '无正文'}</pre>`
})
const subscriptionChannelLiteral = '网页 (Web)'

function subscriptionChannelLabel(origin) {
  return String(origin || '').trim().toLowerCase() === 'chatgpt_web' ? subscriptionChannelLiteral : (origin || '-')
}

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

function toggleAccountDisplayOrder() {
  accountDisplayOrder.value = accountDisplayOrder.value === 'desc' ? 'asc' : 'desc'
}

function setAccountPage(page) {
  const next = Math.max(1, Math.min(Number(page) || 1, accountTotalPages.value))
  accountPage.value = next
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

function chunkItems(items, size) {
  const chunks = []
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size))
  }
  return chunks
}

function emptyDeleteBatchResult() {
  return {
    results: [],
    summary: {
      total: 0,
      ok: 0,
      failed: 0,
      skipped: 0,
      remote_cleanup: false,
      batches: 0,
    },
  }
}

function mergeDeleteBatchResult(target, batch) {
  const summary = batch?.summary || {}
  target.results.push(...(batch?.results || []))
  target.summary.total += Number(summary.total || 0)
  target.summary.ok += Number(summary.ok || 0)
  target.summary.failed += Number(summary.failed || 0)
  target.summary.skipped += Number(summary.skipped || 0)
  target.summary.remote_cleanup = target.summary.remote_cleanup || Boolean(summary.remote_cleanup)
  return target
}

async function deleteAccountsInChunks(emails, onProgress = null) {
  const chunks = chunkItems(emails, ACCOUNT_DELETE_BATCH_MAX_EMAILS)
  const combined = emptyDeleteBatchResult()
  combined.summary.batches = chunks.length

  for (let index = 0; index < chunks.length; index += 1) {
    const batch = await api.deleteAccountsBatch(chunks[index], true)
    mergeDeleteBatchResult(combined, batch)
    if (onProgress) onProgress(combined, index + 1, chunks.length)
  }

  return combined
}

function cleanupBrazilPixPaymentStateForEmails(emails) {
  const targets = new Set(
    (Array.isArray(emails) ? emails : [emails])
      .map(email => String(email || '').trim().toLowerCase())
      .filter(Boolean)
  )
  if (!targets.size) return { linksRemoved: 0, cdksReleased: 0 }

  try {
    const state = JSON.parse(sessionStorage.getItem(BRAZIL_PIX_PAYMENT_STATE_STORAGE_KEY) || '{}')
    const links = Array.isArray(state.links) ? state.links : []
    const cdks = Array.isArray(state.cdks) ? state.cdks : []
    const removedLinkIds = new Set()
    const keptLinks = []

    for (const link of links) {
      const accountEmail = String(link?.accountEmail || '').trim().toLowerCase()
      if (accountEmail && targets.has(accountEmail)) {
        if (link?.id) removedLinkIds.add(String(link.id))
        continue
      }
      keptLinks.push(link)
    }

    if (!removedLinkIds.size && keptLinks.length === links.length) {
      return { linksRemoved: 0, cdksReleased: 0 }
    }

    let cdksReleased = 0
    const nextCdks = cdks.map(cdk => {
      if (cdk?.linkId && removedLinkIds.has(String(cdk.linkId)) && cdk.status === 'reserved') {
        cdksReleased += 1
        return { ...cdk, status: 'available', linkId: '', message: '关联账号已从仪表盘删除，CDK 已释放。' }
      }
      return cdk
    })

    sessionStorage.setItem(
      BRAZIL_PIX_PAYMENT_STATE_STORAGE_KEY,
      JSON.stringify({ ...state, links: keptLinks, cdks: nextCdks, savedAt: Date.now() })
    )
    return { linksRemoved: links.length - keptLinks.length, cdksReleased }
  } catch (error) {
    console.warn('cleanupBrazilPixPaymentStateForEmails failed', error)
    return { linksRemoved: 0, cdksReleased: 0, error: String(error?.message || error) }
  }
}

function clearFilters() {
  emailFilter.value = ''
  statusFilter.value = ''
  accountTypeFilter.value = ''
  twoFactorFilter.value = ''
  trialFilter.value = ''
  bindProviderFilter.value = ''
  registerDateFilter.value = ''
  registerStartTimeFilter.value = ''
  registerEndTimeFilter.value = ''
  credentialExportFilter.value = ''
  exportDateFilter.value = ''
  exportStartTimeFilter.value = ''
  exportEndTimeFilter.value = ''
  accountHubSyncFilter.value = ''
  authCredentialFilter.value = ''
  bindDateFilter.value = ''
  bindStartTimeFilter.value = ''
  bindEndTimeFilter.value = ''
}

async function openAccountActionMenu(account, event) {
  accountActionMenuTrigger = event?.currentTarget || document.activeElement
  accountActionMenuAccount.value = account || null
  if (!accountActionMenuAccount.value) return
  await nextTick()
  setAccountActionBackgroundInert(accountActionDialogRef.value)
  accountActionDialogInitialFocusRef.value?.focus()
}

async function closeAccountActionMenu() {
  const trigger = accountActionMenuTrigger
  accountActionMenuAccount.value = null
  restoreAccountActionBackgroundInert()
  await nextTick()
  if (accountActionMenuAccount.value || accountActionMenuTrigger !== trigger) return
  accountActionMenuTrigger = null
  if (trigger?.isConnected && typeof trigger.focus === 'function') trigger.focus()
}

function setAccountActionBackgroundInert(dialog) {
  restoreAccountActionBackgroundInert()
  if (!dialog || typeof document === 'undefined') return
  accountActionBackgroundInertState = [...document.body.children]
    .filter(element => element !== dialog && !element.contains(dialog))
    .map(element => ({ element, inert: Boolean(element.inert) }))
  for (const { element } of accountActionBackgroundInertState) element.inert = true
}

function restoreAccountActionBackgroundInert() {
  for (const { element, inert } of accountActionBackgroundInertState) {
    if (element?.isConnected) element.inert = inert
  }
  accountActionBackgroundInertState = []
}

function trapDialogFocus(event, dialog) {
  if (!dialog) return
  const focusable = [...dialog.querySelectorAll(ACCOUNT_ACTION_FOCUSABLE_SELECTOR)]
    .filter(element => element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true')
  if (!focusable.length) {
    event.preventDefault()
    dialog.focus()
    return
  }
  const first = focusable[0]
  const last = focusable.at(-1)
  const current = document.activeElement
  const focusOutsideCycle = current === dialog || !dialog.contains(current)
  if (event.shiftKey && (focusOutsideCycle || current === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (focusOutsideCycle || current === last)) {
    event.preventDefault()
    first.focus()
  }
}

function trapAccountActionDialogFocus(event) {
  trapDialogFocus(event, accountActionDialogRef.value)
}

function trapAccountSecondaryDialogFocus(event, dialogRef) {
  trapDialogFocus(event, dialogRef?.value || dialogRef)
}

async function transitionAccountActionToSecondaryDialog(dialogRef, initialFocusRef, openDialog) {
  accountActionMenuAccount.value = null
  restoreAccountActionBackgroundInert()
  openDialog()
  await nextTick()
  if (!dialogRef.value) return
  setAccountActionBackgroundInert(dialogRef.value)
  initialFocusRef.value?.focus()
}

async function finishAccountSecondaryDialogClose() {
  const trigger = accountActionMenuTrigger
  restoreAccountActionBackgroundInert()
  await nextTick()
  if (subscriptionDialog.value.open || latestMailDialog.value.open || accountActionMenuAccount.value) return
  if (accountActionMenuTrigger !== trigger) return
  accountActionMenuTrigger = null
  if (trigger?.isConnected && typeof trigger.focus === 'function') trigger.focus()
}

async function editAccountFromActionMenu() {
  const account = accountActionMenuAccount.value
  if (!account || accountActionMenuBusy.value) return
  await closeAccountActionMenu()
  openAccountTypeEditor(account)
}

async function removeAccountFromActionMenu() {
  const email = accountActionMenuAccount.value?.email
  if (!email || accountActionMenuBusy.value) return
  await removeAccount(email)
  await closeAccountActionMenu()
}

function openAccountTypeEditor(acc) {
  accountTypeEditAccount.value = acc
  accountTypeEditValue.value = acc?.account_type || 'free'
  accountStatusEditValue.value = acc?.status || 'pending'
  accountBindProviderEditValue.value = acc?.last_bind_provider || ''
}

function openBatchAccountEditor() {
  if (!selectedEmails.value.length) return
  batchAccountEditEmails.value = [...selectedEmails.value]
  batchAccountEditType.value = BATCH_METADATA_SKIP
  batchAccountEditStatus.value = BATCH_METADATA_SKIP
  batchAccountEditProvider.value = BATCH_METADATA_SKIP
  batchAccountEditOpen.value = true
}

function closeAccountTypeEditor() {
  if (accountTypeSaving.value) return
  accountTypeEditAccount.value = null
  accountTypeEditValue.value = ''
  accountStatusEditValue.value = ''
  accountBindProviderEditValue.value = ''
}

function closeBatchAccountEditor() {
  if (batchAccountSaving.value) return
  batchAccountEditOpen.value = false
  batchAccountEditEmails.value = []
  batchAccountEditType.value = BATCH_METADATA_SKIP
  batchAccountEditStatus.value = BATCH_METADATA_SKIP
  batchAccountEditProvider.value = BATCH_METADATA_SKIP
}

function openCredentialExport() {
  if (!exportableAccounts.value.length) return
  credentialExportOpen.value = true
}

function closeCredentialExport() {
  if (credentialExporting.value) return
  credentialExportOpen.value = false
}

function openExternalAccountImport() {
  externalAccountImportOpen.value = true
  externalAccountImportResult.value = null
}

function closeExternalAccountImport() {
  if (externalAccountImporting.value) return
  externalAccountImportOpen.value = false
}

async function submitExternalAccountImport() {
  const text = externalAccountImportText.value.trim()
  if (externalAccountImporting.value || !text) return
  externalAccountImporting.value = true
  externalAccountImportResult.value = null
  message.value = ''
  try {
    const result = await api.importExternalAccounts(text)
    externalAccountImportResult.value = result
    const completed = new Set(twoFactorCompletedEmails.value)
    for (const account of result.accounts || []) {
      if (accountTwoFactorEnabled(account)) {
        const email = accountTwoFactorEmailKey(account)
        if (email) completed.add(email)
      }
    }
    twoFactorCompletedEmails.value = completed
    const invalid = Array.isArray(result.invalid) && result.invalid.length ? `，跳过 ${result.invalid.length} 条无效` : ''
    const skippedMain = Array.isArray(result.skipped_main) && result.skipped_main.length ? `，跳过主号 ${result.skipped_main.length} 个` : ''
    const totp = result.totp_imported ? `，2FA ${result.totp_imported}` : ''
    message.value = `账号导入完成：新增 ${result.imported || 0}，更新 ${result.updated || 0}${totp}，重复 ${result.duplicates || 0}${invalid}${skippedMain}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    externalAccountImportText.value = ''
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    externalAccountImporting.value = false
    scheduleMessageClear(10000)
  }
}

function openCpaImport() {
  cpaImportOpen.value = true
  cpaImportResult.value = null
}

function closeCpaImport() {
  if (cpaImporting.value) return
  cpaImportOpen.value = false
}

function handleCpaImportFiles(event) {
  const files = Array.from(event.target.files || [])
    .filter(file => /\.(json|zip)$/i.test(file.name || file.webkitRelativePath || ''))
  const seen = new Set(cpaImportFiles.value.map(file => `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`))
  const next = [...cpaImportFiles.value]
  for (const file of files) {
    const key = `${file.webkitRelativePath || file.name}:${file.size}:${file.lastModified}`
    if (seen.has(key)) continue
    seen.add(key)
    next.push(file)
  }
  cpaImportFiles.value = next
  event.target.value = ''
}

function readFileBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const value = String(reader.result || '')
      resolve(value.includes(',') ? value.split(',', 2)[1] : value)
    }
    reader.onerror = () => reject(reader.error || new Error('读取文件失败'))
    reader.readAsDataURL(file)
  })
}

async function submitCpaImport() {
  if (cpaImporting.value || (!cpaImportText.value.trim() && !cpaImportFiles.value.length)) return
  cpaImporting.value = true
  cpaImportResult.value = null
  message.value = ''
  try {
    const files = []
    for (const file of cpaImportFiles.value) {
      files.push({
        filename: file.webkitRelativePath || file.name,
        content_base64: await readFileBase64(file),
      })
    }
    const result = await api.importAccountCpaAuths({
      pasted_text: cpaImportText.value,
      files,
    })
    cpaImportResult.value = result
    const invalid = Array.isArray(result.invalid) && result.invalid.length ? `，跳过 ${result.invalid.length} 条无效` : ''
    message.value = `CPA 认证导入完成：导入 ${result.imported || 0}，更新 ${result.updated || 0}，新增账号 ${result.accounts_added || 0}，更新账号 ${result.accounts_updated || 0}${invalid}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    cpaImportText.value = ''
    cpaImportFiles.value = []
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    cpaImporting.value = false
    scheduleMessageClear(10000)
  }
}

const cards = computed(() => {
  if (!props.status) return []
  const s = props.status.summary
  return [
    { label: '活跃', value: s.active, color: 'text-green-400' },
    { label: '暂存', value: s.stashed || 0, color: 'text-slate-300' },
    { label: '废弃', value: s.fail || 0, color: 'text-orange-400' },
    { label: 'Free', value: s.free || 0, color: 'text-fuchsia-400' },
    { label: 'Team', value: s.team || 0, color: 'text-violet-400' },
    { label: 'Plus', value: s.plus || 0, color: 'text-sky-400' },
    { label: 'Pro', value: s.pro || 0, color: 'text-blue-400' },
    { label: '总计', value: s.total, color: 'text-white' },
  ]
})

const kiroCards = [
  { label: '活跃', value: 0, color: 'text-green-400' },
  { label: '废弃', value: 0, color: 'text-orange-400' },
  { label: '总计', value: 0, color: 'text-white' },
]

function statusClass(s) {
  s = normalizedStatus(s)
  return {
    active: 'bg-green-500/10 text-green-400',
    exhausted: 'bg-red-500/10 text-red-400',
    standby: 'bg-yellow-500/10 text-yellow-400',
    stashed: 'bg-slate-500/10 text-slate-300',
    pending: 'bg-gray-500/10 text-gray-400',
    session_only: 'bg-green-500/10 text-green-400',
    auth_invalid: 'bg-orange-500/10 text-orange-400',
    auth_revoked: 'bg-orange-500/10 text-orange-300',
    orphan: 'bg-amber-500/10 text-amber-300',
    fail: 'bg-red-500/10 text-red-300',
  }[s] || 'bg-gray-500/10 text-gray-400'
}

function dotClass(s) {
  s = normalizedStatus(s)
  return {
    active: 'bg-green-400',
    exhausted: 'bg-red-400',
    standby: 'bg-yellow-400',
    stashed: 'bg-slate-300',
    pending: 'bg-gray-400',
    session_only: 'bg-green-400',
    auth_invalid: 'bg-orange-400',
    auth_revoked: 'bg-orange-300',
    orphan: 'bg-amber-300',
    fail: 'bg-red-300',
  }[s] || 'bg-gray-400'
}

function statusLabel(s) {
  s = normalizedStatus(s)
  return {
    active: 'Active',
    exhausted: 'Used up',
    standby: 'Standby',
    stashed: '暂存',
    pending: 'Pending',
    session_only: 'Active',
    auth_invalid: 'token失效',
    auth_revoked: '掉授权',
    orphan: '孤立',
    fail: 'Fail/废弃',
  }[s] || s
}

function normalizedStatus(status) {
  const normalized = String(status || '').trim().toLowerCase()
  return ['personal', 'plus'].includes(normalized) ? 'active' : normalized
}

function accountTwoFactorEnabled(account) {
  return account?.two_factor_enabled === true
    || String(account?.totp_status || '').trim().toLowerCase() === 'enabled'
    || twoFactorCompletedEmails.value.has(accountTwoFactorEmailKey(account))
}

function accountTwoFactorEmailKey(account) {
  return String(account?.email || '').trim().toLowerCase()
}

function accountTwoFactorSetupInProgress(account) {
  const email = accountTwoFactorEmailKey(account)
  if (!email || twoFactorCompletedEmails.value.has(email) || twoFactorFailedEmails.value.has(email)) return false
  return twoFactorSubmittingEmails.value.has(email)
    || twoFactorPendingTaskEmails.value.has(email)
    || twoFactorTaskEmails.value.has(email)
}

function twoFactorButtonLabel(account) {
  return accountTwoFactorSetupInProgress(account) ? '设置中...' : '设置'
}

function formatTwoFactorCode(code) {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : '-'
}

function applyTwoFactorTotpPayload(payload) {
  twoFactorTotpDialog.value = {
    ...twoFactorTotpDialog.value,
    loading: false,
    refreshing: false,
    error: '',
    email: String(payload?.email || twoFactorTotpDialog.value.email || '').trim(),
    secret: String(payload?.secret || ''),
    code: String(payload?.code || ''),
    remaining: Number(payload?.remaining || 0),
    period: Number(payload?.period || 30),
  }
}

async function fetchTwoFactorTotp(email, { refreshing = false } = {}) {
  const target = String(email || '').trim()
  if (!target) return
  const requestId = twoFactorTotpRequestId.value + 1
  twoFactorTotpRequestId.value = requestId
  twoFactorTotpDialog.value = {
    ...twoFactorTotpDialog.value,
    email: target,
    loading: !refreshing,
    refreshing,
    error: '',
  }
  try {
    const result = await api.getAccountTwoFactorTotp(target)
    if (requestId !== twoFactorTotpRequestId.value || !twoFactorTotpDialog.value.open) return
    applyTwoFactorTotpPayload(result)
  } catch (error) {
    if (requestId !== twoFactorTotpRequestId.value || !twoFactorTotpDialog.value.open) return
    twoFactorTotpDialog.value = {
      ...twoFactorTotpDialog.value,
      loading: false,
      refreshing: false,
      error: error?.message || '获取 2FA 验证码失败',
    }
  }
}

function openTwoFactorTotpDialog(account) {
  const email = String(account?.email || '').trim()
  if (!email) return
  twoFactorTotpDialog.value = {
    open: true,
    email,
    loading: true,
    refreshing: false,
    error: '',
    secret: '',
    code: '',
    remaining: 0,
    period: 30,
  }
  void fetchTwoFactorTotp(email)
}

function closeTwoFactorTotpDialog() {
  twoFactorTotpRequestId.value += 1
  twoFactorTotpDialog.value = {
    open: false,
    email: '',
    loading: false,
    refreshing: false,
    error: '',
    secret: '',
    code: '',
    remaining: 0,
    period: 30,
  }
}

function refreshTwoFactorTotpDialog() {
  if (twoFactorTotpDialog.value.refreshing) return
  return fetchTwoFactorTotp(twoFactorTotpDialog.value.email, { refreshing: true })
}

async function copyTwoFactorSecret() {
  const secret = String(twoFactorTotpDialog.value.secret || '').trim()
  if (!secret) return
  await writeClipboard(secret)
  message.value = `已复制 ${twoFactorTotpDialog.value.email} 的 2FA 密钥`
  messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
  scheduleMessageClear(6000)
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

function bindProviderLabel(provider) {
  return {
    pix: 'Pix',
    paypal: 'PayPal',
    upi: 'UPI',
    ideal: 'iDEAL',
    kakao_pay: 'Kakao Pay',
    momo_vn: 'MoMo',
    gcash_ph: 'GCash',
    gopay: 'GoPay',
    card: 'Card',
    external_import: '外部导入',
  }[String(provider || '').toLowerCase()] || '-'
}

function effectiveBindProvider(acc) {
  const provider = String(acc?.last_bind_provider || '').trim().toLowerCase()
  if (provider) return provider
  const accountType = String(acc?.account_type || '').toLowerCase()
  if (!['plus', 'pro', 'team'].includes(accountType)) return ''
  const rawStatus = String(acc?.raw_status || acc?.status || '').trim().toLowerCase()
  return ''
}

function bindProviderClass(provider) {
  return {
    pix: 'bg-cyan-500/10 text-cyan-300',
    paypal: 'bg-indigo-500/10 text-indigo-300',
    upi: 'bg-orange-500/10 text-orange-300',
    ideal: 'bg-blue-500/10 text-blue-300',
    kakao_pay: 'bg-yellow-500/10 text-yellow-300',
    momo_vn: 'bg-pink-500/10 text-pink-300',
    gcash_ph: 'bg-cyan-500/10 text-cyan-300',
    gopay: 'bg-emerald-500/10 text-emerald-300',
    card: 'bg-amber-500/10 text-amber-300',
    external_import: 'bg-teal-500/10 text-teal-300',
  }[String(provider || '').toLowerCase()] || 'bg-gray-500/10 text-gray-500'
}

function credentialExportLabel(acc) {
  return acc?.credentials_exported ? '已导出' : '未导出'
}

function credentialExportClass(acc) {
  return acc?.credentials_exported
    ? 'bg-emerald-500/10 text-emerald-400'
    : 'bg-gray-500/10 text-gray-400'
}

function exportTimeLabel(acc) {
  return accountExportTs(acc) ? fmtTs(accountExportTs(acc)) : '-'
}

function registerTimeLabel(acc) {
  return accountRegisterTs(acc) ? fmtTs(accountRegisterTs(acc)) : '-'
}

function accountActivationTs(acc) {
  return Number(acc?.plus_bound_at || acc?.activated_at || acc?.activation_at || acc?.upgraded_at || acc?.last_bind_at || 0) || 0
}

function activationTimeLabel(acc) {
  return accountActivationTs(acc) ? fmtTs(accountActivationTs(acc)) : '-'
}

function accountHubSyncLabel(acc) {
  return acc?.account_hub_synced ? '已同步' : '未同步'
}

function accountHubSyncClass(acc) {
  return acc?.account_hub_synced
    ? 'bg-violet-500/10 text-violet-300'
    : 'bg-gray-500/10 text-gray-400'
}

const QUOTA_WINDOW_SECONDS = {
  primary: 18000,
  weekly: 604800,
}

function quotaInfo(acc) {
  return props.status?.quota_cache?.[acc.email] || acc.last_quota || null
}

function numericOrNull(value) {
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function quotaWindow(acc, type) {
  const qi = quotaInfo(acc)
  if (!qi) return null
  const expectedWindowSeconds = QUOTA_WINDOW_SECONDS[type]
  const direct = qi.windows?.[type]
  const directWindowSeconds = numericOrNull(direct?.limit_window_seconds)
  if (direct && (!expectedWindowSeconds || directWindowSeconds === expectedWindowSeconds)) {
    return direct
  }

  const windowSeconds = numericOrNull(qi[`${type}_window_seconds`])
  const usedPercent = numericOrNull(qi[`${type}_pct`])
  const resetAt = numericOrNull(qi[`${type}_resets_at`])
  const resetAfterSeconds = numericOrNull(qi[`${type}_reset_after_seconds`])
  if (usedPercent === null) return null
  if (expectedWindowSeconds && windowSeconds && windowSeconds !== expectedWindowSeconds) return null

  const hasClassifiedWindowSeconds = ['primary_window_seconds', 'weekly_window_seconds', 'monthly_window_seconds']
    .some(key => numericOrNull(qi[key]) !== null)
  if (expectedWindowSeconds && !windowSeconds && hasClassifiedWindowSeconds) return null

  return {
    used_percent: usedPercent,
    reset_at: resetAt,
    reset_after_seconds: resetAfterSeconds,
    limit_window_seconds: windowSeconds || expectedWindowSeconds || null,
  }
}

function quota(acc, type) {
  const slot = quotaWindow(acc, type)
  const pct = numericOrNull(slot?.used_percent)
  return pct !== null ? 100 - pct : null
}

function quotaPct(acc, type) {
  const val = quota(acc, type)
  return val !== null ? `${val}%` : '-'
}

function quotaReset(acc, type) {
  const qi = quotaInfo(acc)
  const slot = quotaWindow(acc, type)
  if (!qi || !slot) return '-'
  let ts = numericOrNull(slot.reset_at)
  const resetAfterSeconds = numericOrNull(slot.reset_after_seconds)
  const usedPercent = numericOrNull(slot.used_percent)
  const windowSeconds = numericOrNull(slot.limit_window_seconds)
  const checkedAt = numericOrNull(qi.checked_at)
  let suppressFullUnusedWindowReset = false
  if (usedPercent !== null && usedPercent <= 0 && windowSeconds && resetAfterSeconds !== null && resetAfterSeconds >= windowSeconds) {
    ts = null
    suppressFullUnusedWindowReset = true
  }
  if (usedPercent !== null && usedPercent <= 0 && windowSeconds && ts && checkedAt && ts - checkedAt >= windowSeconds - 60) {
    ts = null
    suppressFullUnusedWindowReset = true
  }
  if (ts && checkedAt && resetAfterSeconds !== null && resetAfterSeconds <= 0 && ts <= checkedAt) {
    ts = null
  }
  if (!ts && !suppressFullUnusedWindowReset && resetAfterSeconds !== null && resetAfterSeconds > 0 && checkedAt) {
    ts = checkedAt + resetAfterSeconds
  }
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function pctColor(val) {
  if (val === null) return 'text-gray-500'
  if (val > 30) return 'text-green-400'
  if (val > 0) return 'text-yellow-400'
  return 'text-red-400'
}

function yesNo(value) {
  return value ? '是' : '否'
}

function formatSubscriptionDate(value, options = {}) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = number => String(number).padStart(2, '0')
  const text = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
  if (options.dateOnly) return text
  return `${text} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatLatestMailDate(value) {
  if (!value) return '-'
  let dateValue = value
  if (typeof value === 'number' || /^\d+$/.test(String(value))) {
    const numeric = Number(value)
    dateValue = numeric > 10000000000 ? numeric : numeric * 1000
  }
  const date = new Date(dateValue)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = number => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function subscriptionActive(subscription) {
  return Boolean(subscription?.active)
}

async function writeClipboard(value) {
  try {
    await navigator.clipboard.writeText(value)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = value
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

async function copyAccountAccessToken(email) {
  if (accountActionBusy.value) return
  const requestId = accountActionRequestId.value + 1
  accountActionRequestId.value = requestId
  accountActionBusy.value = true
  actionEmail.value = email
  actionType.value = 'access-token'
  message.value = ''
  try {
    const result = await api.getAccountAccessToken(email)
    const token = String(result?.access_token || '')
    if (!token) throw new Error('该账号没有可复制的 access_token')
    if (requestId !== accountActionRequestId.value) return
    await writeClipboard(token)
    if (requestId !== accountActionRequestId.value) return
    message.value = `已复制 ${email} 的 access token`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
  } catch (e) {
    if (requestId !== accountActionRequestId.value) return
    message.value = `获取 access token 失败: ${e.message}`
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    if (requestId === accountActionRequestId.value) {
      accountActionBusy.value = false
      actionEmail.value = ''
      actionType.value = ''
      scheduleMessageClear(8000)
    }
  }
}

async function queryAccountSubscription(email) {
  if (accountActionBusy.value) return
  const requestId = accountActionRequestId.value + 1
  accountActionRequestId.value = requestId
  accountActionBusy.value = true
  actionEmail.value = email
  actionType.value = 'subscription'
  await transitionAccountActionToSecondaryDialog(
    subscriptionDialogRef,
    subscriptionDialogInitialFocusRef,
    () => {
      subscriptionDialog.value = {
        open: true,
        email,
        loading: true,
        error: '',
        data: null,
      }
    },
  )
  try {
    const result = await api.getAccountSubscription(email)
    if (requestId !== accountActionRequestId.value || !subscriptionDialog.value.open) return
    subscriptionDialog.value = {
      open: true,
      email,
      loading: false,
      error: '',
      data: result,
    }
  } catch (e) {
    if (requestId !== accountActionRequestId.value || !subscriptionDialog.value.open) return
    subscriptionDialog.value = {
      open: true,
      email,
      loading: false,
      error: e.message || '订阅查询失败',
      data: null,
    }
  } finally {
    if (requestId === accountActionRequestId.value) {
      accountActionBusy.value = false
      actionEmail.value = ''
      actionType.value = ''
    }
  }
}

async function queryAccountLatestMail(email) {
  if (accountActionBusy.value) return
  const requestId = accountActionRequestId.value + 1
  accountActionRequestId.value = requestId
  accountActionBusy.value = true
  actionEmail.value = email
  actionType.value = 'latest-mail'
  await transitionAccountActionToSecondaryDialog(
    latestMailDialogRef,
    latestMailDialogInitialFocusRef,
    () => {
      latestMailDialog.value = {
        open: true,
        email,
        loading: true,
        error: '',
        data: null,
      }
    },
  )
  try {
    const result = await api.getAccountLatestMail(email)
    if (requestId !== accountActionRequestId.value || !latestMailDialog.value.open) return
    latestMailDialog.value = {
      open: true,
      email,
      loading: false,
      error: '',
      data: result,
    }
  } catch (e) {
    if (requestId !== accountActionRequestId.value || !latestMailDialog.value.open) return
    latestMailDialog.value = {
      open: true,
      email,
      loading: false,
      error: e.message || '获取邮件失败',
      data: null,
    }
  } finally {
    if (requestId === accountActionRequestId.value) {
      accountActionBusy.value = false
      actionEmail.value = ''
      actionType.value = ''
    }
  }
}

async function closeSubscriptionDialog() {
  if (actionType.value === 'subscription') {
    accountActionRequestId.value += 1
    accountActionBusy.value = false
    actionEmail.value = ''
    actionType.value = ''
  }
  subscriptionDialog.value = {
    open: false,
    email: '',
    loading: false,
    error: '',
    data: null,
  }
  await finishAccountSecondaryDialogClose()
}

async function closeLatestMailDialog() {
  if (actionType.value === 'latest-mail') {
    accountActionRequestId.value += 1
    accountActionBusy.value = false
    actionEmail.value = ''
    actionType.value = ''
  }
  latestMailDialog.value = {
    open: false,
    email: '',
    loading: false,
    error: '',
    data: null,
  }
  await finishAccountSecondaryDialogClose()
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
      trial_eligible: trialFilter.value || '',
      register_date: registerDateFilter.value || '',
      register_start_time: registerStartTimeFilter.value || '',
      register_end_time: registerEndTimeFilter.value || '',
      register_time_start: registerTimeRange.value.start || null,
      register_time_end: registerTimeRange.value.end || null,
      credentials_exported: credentialExportFilter.value || '',
      account_hub_synced: accountHubSyncFilter.value || '',
      auth_credential: authCredentialFilter.value || '',
      bind_date: bindDateFilter.value || '',
      bind_start_time: bindStartTimeFilter.value || '',
      bind_end_time: bindEndTimeFilter.value || '',
      bind_time_start: bindTimeRange.value.start || null,
      bind_time_end: bindTimeRange.value.end || null,
      selected_only: selectedEmails.value.length > 0,
    },
    accounts: rows.map(acc => ({
      email: acc.email || '',
      display_email: displayEmail(acc),
      original_email: acc.original_email || '',
      status: acc.status || '',
      created_at: acc.created_at || null,
      seat_type: acc.seat_type || '',
      auth_file: acc.auth_file || '',
      auth_session_file: acc.auth_session_file || '',
      quota_exhausted_at: acc.quota_exhausted_at || null,
      quota_resets_at: acc.quota_resets_at || null,
      last_quota_check_at: acc.last_quota_check_at || null,
      last_bind_status: acc.last_bind_status || '',
      last_bind_at: acc.last_bind_at || null,
      last_bind_provider: acc.last_bind_provider || '',
      last_checkout_url: acc.last_checkout_url || '',
      last_proxy_label: acc.last_proxy_label || '',
      last_bind_task_id: acc.last_bind_task_id || '',
      last_bind_message: acc.last_bind_message || '',
      last_bind_failure_stage: acc.last_bind_failure_stage || '',
      kakao_link_extracted: accountKakaoLinkExtracted(acc),
      kakao_link_extracted_at: acc.kakao_link_extracted_at || null,
      kakao_link_expires_at: acc.kakao_link_expires_at || null,
      kakao_link_cs_id: acc.kakao_link_cs_id || '',
      kakao_link_job_id: acc.kakao_link_job_id || '',
      credentials_exported: !!acc.credentials_exported,
      credentials_exported_at: acc.credentials_exported_at || null,
      account_hub_synced: !!acc.account_hub_synced,
      account_hub_synced_at: acc.account_hub_synced_at || null,
      hub_source_name: acc.hub_source_name || '',
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
  scheduleMessageClear(5000)
}

async function downloadCredentials() {
  const emails = exportableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  credentialExporting.value = true
  message.value = ''
  try {
    const result = await api.exportAccountCredentials(emails)
    const blob = new Blob([result.content || ''], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename || `accounts-credentials-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
    await confirmDownloadedExport(result)
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
    scheduleMessageClear(8000)
  }
}

async function exportSelectedAccessTokens() {
  const emails = selectedEmails.value
  if (!emails.length || accessTokenExporting.value) return

  accessTokenExporting.value = true
  message.value = ''
  try {
    const result = await api.exportAccountAccessTokens(emails)
    const blob = new Blob([result.content || ''], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = result.filename || `access-tokens-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个无可用 access_token 账号` : ''
    message.value = `已导出 ${result.count || 0} 个账号的 access_token${missing}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    accessTokenExporting.value = false
    scheduleMessageClear(8000)
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

async function confirmDownloadedExport(result) {
  try {
    await confirmExportStatusBatches(
      result,
      emails => api.updateAccountsExportStatus(emails, true),
    )
  } catch (error) {
    const detail = String(error?.message || error || '未知错误')
    const confirmedCount = Number(error?.confirmedCount || 0)
    if (confirmedCount > 0) emit('refresh')
    const progress = confirmedCount > 0
      ? `已确认前 ${confirmedCount} 个，剩余 ${error.remainingCount} 个保持未导出；`
      : ''
    const wrapped = new Error(`文件已开始下载，但导出状态确认失败：${progress}${detail}`)
    wrapped.confirmedCount = confirmedCount
    wrapped.remainingCount = Number(error?.remainingCount || 0)
    throw wrapped
  }
}

async function exportCpaAuths() {
  const emails = cpaExportableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  cpaExporting.value = true
  message.value = ''
  try {
    const result = await api.exportAccountCpaAuths(emails)
    downloadBase64File(result.content_base64, result.filename, result.content_type)
    await confirmDownloadedExport(result)
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个无认证文件账号` : ''
    message.value = `已导出 ${result.count || 0} 个 CPA 认证文件${missing}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    cpaExporting.value = false
    scheduleMessageClear(8000)
  }
}

async function exportSubAuths() {
  const emails = cpaExportableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  subExporting.value = true
  message.value = ''
  try {
    const result = await api.exportAccountSubAuths(emails)
    downloadBase64File(result.content_base64, result.filename, result.content_type)
    await confirmDownloadedExport(result)
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个无认证文件账号` : ''
    const invalid = Array.isArray(result.invalid) && result.invalid.length ? `，${result.invalid.length} 个认证文件无法转换` : ''
    message.value = `已导出 ${result.count || 0} 个 Sub2API 认证账号${missing}${invalid}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    subExporting.value = false
    scheduleMessageClear(8000)
  }
}

async function batchUpdateExportStatus(exported) {
  const emails = selectedEmails.value
  if (exportStatusUpdating.value || !emails.length) return

  exportStatusUpdating.value = true
  message.value = ''
  try {
    const result = await api.updateAccountsExportStatus(emails, exported)
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个不存在或不可修改账号` : ''
    message.value = `${exported ? '已标记为已导出' : '已标记为未导出'} ${result.updated || 0} 个账号${missing}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    exportStatusUpdating.value = false
    scheduleMessageClear(8000)
  }
}

async function submitAccountTwoFactorSetup(accounts, scopeLabel) {
  const emails = (accounts || [])
    .filter(account => !accountTwoFactorEnabled(account) && !accountTwoFactorSetupInProgress(account))
    .map(account => String(account?.email || '').trim())
    .filter(Boolean)
  if (!emails.length) return

  twoFactorSubmitting.value = true
  const completed = new Set(twoFactorCompletedEmails.value)
  const failed = new Set(twoFactorFailedEmails.value)
  for (const email of emails) {
    const normalized = email.toLowerCase()
    completed.delete(normalized)
    failed.delete(normalized)
  }
  twoFactorCompletedEmails.value = completed
  twoFactorFailedEmails.value = failed
  twoFactorSubmittingEmails.value = new Set([
    ...twoFactorSubmittingEmails.value,
    ...emails.map(email => email.toLowerCase()),
  ])
  message.value = ''
  try {
    const result = await api.setupAccountsTwoFactor(emails)
    const taskId = String(result.task_id || '')
    if (taskId) {
      twoFactorPendingTaskIds.value = new Set([
        ...twoFactorPendingTaskIds.value,
        taskId,
      ])
    }
    twoFactorPendingTaskEmails.value = new Set([
      ...twoFactorPendingTaskEmails.value,
      ...emails.map(email => email.toLowerCase()),
    ])
    if (twoFactorPendingClearTimer !== null) {
      clearTimeout(twoFactorPendingClearTimer)
      twoFactorPendingClearTimer = null
    }
    message.value = `已提交${scopeLabel}2FA设置任务: ${result.task_id}，账号 ${emails.length} 个`
    messageClass.value = 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
    emit('task-started')
    emit('refresh')
  } catch (error) {
    clearTwoFactorPendingTask()
    message.value = error.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    const submitting = new Set(twoFactorSubmittingEmails.value)
    for (const email of emails) submitting.delete(email.toLowerCase())
    twoFactorSubmittingEmails.value = submitting
    twoFactorSubmitting.value = submitting.size > 0
    scheduleMessageClear(8000)
  }
}

function setupAccountTwoFactor(account) {
  return submitAccountTwoFactorSetup([account], `${String(account?.email || '').trim()} 的`)
}

function batchSetupAccountTwoFactor() {
  const scope = selectedEmails.value.length ? '选中账号' : '筛选账号'
  return submitAccountTwoFactorSetup(twoFactorSetupAccounts.value, `${scope}批量`)
}

async function batchOauthAuthorizeAccounts() {
  if (loginDisabled.value || batchOauthAuthorizing.value) return
  const appendMode = oauthBatchRunning.value
  const emails = oauthBatchActionAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  batchOauthAuthorizing.value = true
  message.value = ''
  try {
    if (appendMode) {
      const result = await api.appendLoginAccountsBatch(emails, oauthBatchTask.value?.task_id || '')
      const skipped = Array.isArray(result.missing) && result.missing.length ? `，跳过不存在账号 ${result.missing.length} 个` : ''
      const duplicates = Array.isArray(result.duplicates) && result.duplicates.length ? `，已在队列 ${result.duplicates.length} 个` : ''
      message.value = `已追加到当前 OAuth授权任务: ${result.task_id}，新增 ${result.added_emails?.length || 0} 个${skipped}${duplicates}`
    } else {
      await loadOauthPhoneSmsConfig({ silent: true })
      const oauthPayload = buildDashboardOauthPayload()
      const result = await api.loginAccountsBatch(emails, oauthPayload)
      const proxyText = Object.keys(buildOauthProxyPayload()).length ? '，OAuth代理已启用' : ''
      const browserText = oauthBrowserMode.value === 'roxy' ? '，RoxyBrowser模式' : ''
      const bindText = oauthAuthorizableAccounts.value.some(isPhoneOnlyAccount) ? '，手机号账号会协议绑邮箱' : ''
      const phoneText = oauthBindPhone.value ? '，已启用手机号绑定' : ''
      message.value = `已提交批量 OAuth授权任务: ${result.task_id}，账号 ${emails.length} 个${proxyText}${browserText}${bindText}${phoneText}`
    }
    messageClass.value = 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    batchOauthAuthorizing.value = false
    scheduleMessageClear(8000)
  }
}

async function batchReloginAccounts() {
  if (loginDisabled.value || batchReloggingIn.value || reloginBatchRunning.value) return
  const emails = reloginableAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  batchReloggingIn.value = true
  message.value = ''
  try {
    const reloginPayload = buildDashboardReloginPayload()
    const result = await api.loginAccountsBatch(emails, reloginPayload)
    const proxyText = Object.keys(buildOauthProxyPayload()).length ? '，OAuth代理已启用' : ''
    message.value = `已提交批量补登录任务: ${result.task_id}，账号 ${emails.length} 个${proxyText}`
    messageClass.value = 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    batchReloggingIn.value = false
    scheduleMessageClear(8000)
  }
}

async function refreshAllQuota() {
  const emails = refreshableQuotaAccounts.value.map(acc => acc.email).filter(Boolean)
  if (quotaRefreshing.value || !emails.length) return

  quotaRefreshing.value = true
  message.value = ''
  try {
    const result = await api.refreshAccountsQuota(emails)
    const scope = selectedEmails.value.length ? '选中' : '筛选'
    pendingRefreshQuotaTaskId.value = String(result.task_id || '')
    message.value = `已提交刷新${scope}额度任务: ${result.task_id}，账号 ${emails.length} 个`
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    quotaRefreshing.value = false
    scheduleMessageClear(
      8000,
      () => !pendingRefreshQuotaTaskId.value && !refreshQuotaRunning.value,
    )
  }
}

async function deleteInvalidCredentials() {
  if (deleteDisabled.value || invalidDeleting.value) return
  const emails = invalidCredentialAccounts.value.map(acc => acc.email).filter(Boolean)
  if (!emails.length) return

  const preview = emails.slice(0, 8).join('\n')
  const more = emails.length > 8 ? `\n...还有 ${emails.length - 8} 个` : ''
  const ok = window.confirm(
    `确认删除以下 ${emails.length} 个无效凭证账号？这会清理本地记录和本地认证文件，并尽量移出 Team/Invite；不会删除 CPA 或邮箱服务中的账号/文件。\n\n${preview}${more}`
  )
  if (!ok) return

  invalidDeleting.value = true
  message.value = ''
  try {
    const r = await deleteAccountsInChunks(emails, (progress, done, total) => {
      message.value = `无效凭证删除中 ${progress.summary.ok}/${emails.length}，批次 ${done}/${total}`
      messageClass.value = 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    })
    const s = r?.summary || {}
    const failed = (r?.results || []).filter(x => !x.ok)
    if (failed.length === 0) {
      message.value = `无效凭证删除完成:成功 ${s.ok}/${s.total}${s.batches > 1 ? `，分 ${s.batches} 批` : ''}`
      messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    } else {
      const head = failed.slice(0, 3).map(x => `${x.email}: ${x.error}`).join('; ')
      message.value = `无效凭证删除部分失败(成功 ${s.ok}/${s.total}${s.batches > 1 ? `，分 ${s.batches} 批` : ''}):${head}${failed.length > 3 ? ' …' : ''}`
      messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    }
    clearSelection()
    emit('refresh')
  } catch (e) {
    message.value = `无效凭证删除失败: ${e.message}`
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    invalidDeleting.value = false
    scheduleMessageClear(12000)
  }
}

async function syncToAccountHub() {
  const emails = selectedEmails.value
  if (!emails.length) {
    message.value = '请先勾选要同步到账号 Hub 的账号'
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    scheduleMessageClear(5000)
    return
  }
  if (emails.length > ACCOUNT_HUB_SYNC_MAX_EMAILS) {
    message.value = `账号 Hub 单次最多同步 ${ACCOUNT_HUB_SYNC_MAX_EMAILS} 个账号，请缩小筛选或分批选择`
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    scheduleMessageClear(8000)
    return
  }
  hubSyncing.value = true
  message.value = ''
  try {
    const result = await api.syncAccountHub(emails)
    message.value = result.message || `已上传 ${result.uploaded_accounts || result.received_accounts || 0} 个勾选账号到账号 Hub`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    hubSyncing.value = false
    scheduleMessageClear(8000)
  }
}

async function saveAccountType() {
  const account = accountTypeEditAccount.value
  const nextType = String(accountTypeEditValue.value || '').trim().toLowerCase()
  const nextStatus = String(accountStatusEditValue.value || '').trim().toLowerCase()
  const nextProvider = String(accountBindProviderEditValue.value || '').trim().toLowerCase()
  if (!account?.email || !nextType || !nextStatus || accountMetadataEditUnchanged.value) return

  accountTypeSaving.value = true
  message.value = ''
  try {
    const result = await api.updateAccountMetadata(account.email, {
      account_type: nextType,
      status: nextStatus,
      last_bind_provider: nextProvider,
    })
    message.value = result.message || `已更新 ${account.email} 账号信息`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    accountTypeEditAccount.value = null
    accountTypeEditValue.value = ''
    accountStatusEditValue.value = ''
    accountBindProviderEditValue.value = ''
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    accountTypeSaving.value = false
    scheduleMessageClear(8000)
  }
}

async function saveBatchAccountMetadata() {
  if (!batchAccountEditEmails.value.length || batchAccountSaving.value) return
  const selectedType = String(batchAccountEditType.value || '').trim()
  const selectedStatus = String(batchAccountEditStatus.value || '').trim()
  const selectedProvider = String(batchAccountEditProvider.value ?? '').trim()
  const payload = {
    emails: [...batchAccountEditEmails.value],
    ...(selectedType !== BATCH_METADATA_SKIP ? { account_type: selectedType.toLowerCase() } : {}),
    ...(selectedStatus !== BATCH_METADATA_SKIP ? { status: selectedStatus.toLowerCase() } : {}),
    ...(selectedProvider !== BATCH_METADATA_SKIP ? { last_bind_provider: selectedProvider.toLowerCase() } : {}),
  }
  if (Object.keys(payload).length <= 1) return

  batchAccountSaving.value = true
  message.value = ''
  let saved = false
  try {
    const result = await api.updateAccountsMetadataBatch(payload)
    const missing = Array.isArray(result.missing) && result.missing.length ? `，跳过 ${result.missing.length} 个不存在账号` : ''
    const skippedMain = Array.isArray(result.skipped_main) && result.skipped_main.length ? `，跳过主号 ${result.skipped_main.length} 个` : ''
    message.value = `${result.message || '已批量更新账号信息'}${missing}${skippedMain}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    saved = true
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    batchAccountSaving.value = false
    if (saved) {
      closeBatchAccountEditor()
    }
    scheduleMessageClear(8000)
  }
}

function canOauthAuthorize(acc) {
  if (!acc?.email || acc.is_main_account) return false
  if (['auth_invalid', 'auth_revoked', 'orphan'].includes(String(acc.status || '').toLowerCase())) return true
  if (Boolean(acc.codex_auth_synthetic)) return true
  return needsCodexLogin(acc)
}

function canRelogin(acc) {
  return Boolean(acc?.email) && !acc.is_main_account && !isPhoneOnlyAccount(acc)
}

function isPhoneOnlyAccount(acc) {
  const email = String(acc?.email || '').trim()
  return Boolean(email) && !email.includes('@')
}

function oauthAuthorizeLabel(acc) {
  if (isPhoneOnlyAccount(acc)) return 'OAuth授权/绑邮箱'
  if (Boolean(acc.codex_auth_synthetic)) return '重新OAuth授权'
  return 'OAuth授权'
}

function reloginLabel(acc) {
  return '补登录'
}

function hasCodexAuthFile(acc) {
  const email = String(acc?.email || '').trim().toLowerCase()
  if (email && oauthCredentialCompletedEmails.value.has(email)) return true
  return accountHasPersistedCodexAuthFile(acc)
}

function accountHasPersistedCodexAuthFile(acc) {
  if (acc.has_codex_auth_file !== undefined) return !!acc.has_codex_auth_file
  const file = String(acc.codex_auth_file || acc.auth_file || '').replace(/\\/g, '/').toLowerCase()
  return file.includes('/data/auths/') || file.includes('/auths/codex-') || file.includes('data/auths/')
}

function needsCodexLogin(acc) {
  if (acc.is_main_account) return false
  if (acc.needs_codex_login !== undefined) return !!acc.needs_codex_login
  return !hasCodexAuthFile(acc)
}

async function oauthAuthorizeAccount(email) {
  if (loginDisabled.value) return

  actionEmail.value = email
  actionType.value = 'oauth-authorize'
  message.value = ''
  try {
    await loadOauthPhoneSmsConfig({ silent: true })
    const oauthPayload = buildDashboardOauthPayload()
    const result = await api.loginAccount(email, oauthPayload)
    const proxyText = Object.keys(buildOauthProxyPayload()).length ? '，OAuth代理已启用' : ''
    const browserText = oauthBrowserMode.value === 'roxy' ? '，RoxyBrowser模式' : ''
    const bindText = email.includes('@') ? '' : '，成功后会绑定邮箱并迁移账号'
    const phoneText = oauthBindPhone.value ? '，已启用手机号绑定' : ''
    message.value = `已提交 ${email} 的 OAuth授权任务: ${result.task_id}${proxyText}${browserText}${bindText}${phoneText}`
    messageClass.value = 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    actionEmail.value = ''
    actionType.value = ''
    scheduleMessageClear(8000)
  }
}

async function reloginAccount(email) {
  if (loginDisabled.value) return

  actionEmail.value = email
  actionType.value = 'relogin'
  message.value = ''
  try {
    const reloginPayload = buildDashboardReloginPayload()
    const result = await api.loginAccount(email, reloginPayload)
    const proxyText = Object.keys(buildOauthProxyPayload()).length ? '，OAuth代理已启用' : ''
    message.value = `已提交 ${email} 的补登录任务: ${result.task_id}${proxyText}`
    messageClass.value = 'bg-cyan-500/10 text-cyan-300 border-cyan-500/20'
    emit('task-started')
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    actionEmail.value = ''
    actionType.value = ''
    scheduleMessageClear(8000)
  }
}

async function kickAccount(email) {
  if (kickDisabled.value) {
    message.value = '移出 Team 需要先完成管理员登录'
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    scheduleMessageClear(8000)
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
    scheduleMessageClear(8000)
  }
}

async function removeAccount(email) {
  if (deleteDisabled.value) return

  const ok = window.confirm(`确认删除账号 ${email}？\n这会清理本地记录和本地认证文件，并尽量移出 Team/Invite；不会删除 CPA 或邮箱服务中的账号/文件。`)
  if (!ok) return

  actionEmail.value = email
  actionType.value = 'delete'
  message.value = ''
  try {
    const result = await api.deleteAccount(email)
    const pixCleanup = cleanupBrazilPixPaymentStateForEmails([email])
    const pixText = pixCleanup.linksRemoved ? `，已同步删除 PIX 支付页链接 ${pixCleanup.linksRemoved} 条` : ''
    message.value = `${result.message || `已删除 ${email}`}${pixText}`
    messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    emit('refresh')
  } catch (e) {
    message.value = e.message
    messageClass.value = 'bg-red-500/10 text-red-400 border-red-500/20'
  } finally {
    actionEmail.value = ''
    actionType.value = ''
    scheduleMessageClear(8000)
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
    `确认批量删除以下 ${emails.length} 个账号？这会清理本地记录和本地认证文件，并尽量移出 Team/Invite；不会删除 CPA 或邮箱服务中的账号/文件。\n\n${preview}${more}`
  )
  if (!ok) return

  batchDeleting.value = true
  batchProgress.value = `0/${emails.length}`
  message.value = ''
  try {
    const r = await deleteAccountsInChunks(emails, (progress, done, total) => {
      batchProgress.value = `${progress.summary.ok}/${emails.length}`
      message.value = `批量删除中 ${progress.summary.ok}/${emails.length}，批次 ${done}/${total}`
      messageClass.value = 'bg-blue-500/10 text-blue-400 border-blue-500/20'
    })
    const s = r?.summary || {}
    const failed = (r?.results || []).filter(x => !x.ok)
    const succeededEmails = (r?.results || []).filter(x => x.ok).map(x => x.email)
    const pixCleanup = cleanupBrazilPixPaymentStateForEmails(succeededEmails)
    const pixText = pixCleanup.linksRemoved ? `，已同步删除 PIX 支付页链接 ${pixCleanup.linksRemoved} 条` : ''
    if (failed.length === 0) {
      message.value = `批量删除完成:成功 ${s.ok}/${s.total}${s.batches > 1 ? `，分 ${s.batches} 批` : ''}${pixText}`
      messageClass.value = 'bg-green-500/10 text-green-400 border-green-500/20'
    } else {
      const head = failed.slice(0, 3).map(x => `${x.email}: ${x.error}`).join('; ')
      message.value = `批量删除部分失败(成功 ${s.ok}/${s.total}${s.batches > 1 ? `，分 ${s.batches} 批` : ''}${pixText}):${head}${failed.length > 3 ? ' …' : ''}`
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
    scheduleMessageClear(12000)
  }
}
</script>

