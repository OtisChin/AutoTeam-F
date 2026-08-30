<template>
  <div class="space-y-5">
    <WorkflowWorkspace title="PayPal 工作流" eyebrow="支付 / PayPal" description="按配置、启动、进度和结果组织业务操作" :status-label="workflowStatusPresentation(anyBusy ? 'running' : 'success').label" :status-tone="workflowStatusPresentation(anyBusy ? 'running' : 'success').tone">
    <UiSegmentedControl v-model="activeTab" :options="[{ value: 'links', label: '提链' },{ value: 'protocol', label: '协议' },{ value: 'pay153', label: '153支付' }]" aria-label="PayPal 工作流模式" />
      <template #configuration>
        <WorkflowStage name="configuration" title="配置" description="确认账号、代理和运行参数" state="idle">
          <WorkflowStage name="launch" title="启动" description="提交后会保留当前任务状态" state="idle"><UiButton variant="primary">开始任务</UiButton></WorkflowStage>
        </WorkflowStage>
      </template>
      <template #progress><WorkflowStage name="progress" title="进度" description="实时状态与可恢复任务" state="idle"><UiStatusBadge label="等待操作" tone="neutral" /></WorkflowStage></template>
      <template #result><WorkflowStage name="result" title="结果" description="完成后查看链接、订单或错误" state="idle"><UiStatePanel state="empty" title="暂无结果" message="启动任务后结果会显示在这里。" /></WorkflowStage></template>
      <template #resources><WorkflowStage name="resources" title="资源" description="账号池、链接和日志" state="idle"><UiStatusBadge label="资源列表由当前页面管理" tone="info" /></WorkflowStage></template>
    </WorkflowWorkspace>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-2">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div class="inline-flex w-fit rounded-xl border border-gray-800 bg-gray-900/80 p-1">
          <button type="button" @click="activeTab = 'links'" class="rounded-lg px-4 py-2 text-sm font-bold transition" :class="activeTab === 'links' ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">
            PayPal 提链
          </button>
          <button type="button" @click="activeTab = 'protocol'" class="rounded-lg px-4 py-2 text-sm font-bold transition" :class="activeTab === 'protocol' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">
            协议支付
          </button>
          <button type="button" @click="activeTab = 'pay153'" class="rounded-lg px-4 py-2 text-sm font-bold transition" :class="activeTab === 'pay153' ? 'bg-cyan-600 text-white shadow-lg shadow-cyan-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">
            153支付
          </button>
        </div>
        <p class="px-2 text-xs text-gray-500">提链、协议支付和 153支付分开管理，切换不会清空当前输入。</p>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">独立 PayPal 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">PayPal 任务</h2>
          <p class="mt-2 text-sm text-gray-400">先提取 BA 链接，再在独立协议支付页使用本地引擎完成 PayPal approval。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="anyBusy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ anyBusy ? activeStatusText : '本地服务在线' }}
        </span>
      </div>
      <div v-if="activeTab === 'pay153'" class="mt-5">
        <section class="rounded-2xl border border-cyan-500/20 bg-gray-950 p-4">
          <div class="flex items-center justify-between border-b border-gray-800 pb-3">
            <div>
              <p class="text-xs font-semibold text-gray-500">当前支付数据</p>
              <h3 class="mt-1 text-lg font-bold text-white">153支付看板</h3>
            </div>
            <span class="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2.5 py-1 text-xs font-semibold text-cyan-200">153支付</span>
          </div>
          <div class="mt-3 grid grid-cols-6 gap-2">
            <div v-for="item in pay153PaymentStats" :key="item.label" class="rounded-xl border border-gray-800 bg-gray-900/60 p-3">
              <div class="text-[11px] text-gray-500">{{ item.label }}</div>
              <div class="mt-1 text-xl font-bold" :class="item.class">{{ item.value }}</div>
            </div>
          </div>
        </section>
      </div>
      <div v-if="activeTab === 'protocol'" class="mt-5">
        <section class="rounded-2xl border border-indigo-500/20 bg-gray-950 p-4">
          <div class="flex items-center justify-between border-b border-gray-800 pb-3">
            <div>
              <p class="text-xs font-semibold text-gray-500">当前支付数据</p>
              <h3 class="mt-1 text-lg font-bold text-white">协议支付看板</h3>
            </div>
            <span class="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-xs font-semibold text-indigo-200">协议支付</span>
          </div>
          <div class="mt-3 grid grid-cols-6 gap-2">
            <div v-for="item in protocolPaymentStats" :key="item.label" class="rounded-xl border border-gray-800 bg-gray-900/60 p-3">
              <div class="text-[11px] text-gray-500">{{ item.label }}</div>
              <div class="mt-1 text-xl font-bold" :class="item.class">{{ item.value }}</div>
            </div>
          </div>
        </section>
      </div>
    </section>

    <template v-if="activeTab === 'links'">
    <div class="grid grid-cols-1 items-start gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">PayPal 代理</h3>
        </div>

        <div class="mt-5 space-y-5">
          <div class="grid gap-4 md:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">目标 PayPal 国家</span>
              <select v-model="form.region" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
                <option v-for="country in paypalCountryOptions" :key="country.value" :value="country.value">{{ country.label }}</option>
              </select>
              <span class="mt-1 block text-xs text-gray-500">checkout、Stripe init、Express BA 阶段使用该国家代理。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">优惠区</span>
              <select v-model="form.promoRegion" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy">
                <option v-for="country in promoRegionOptions" :key="country.value" :value="country.value">{{ country.label }}</option>
              </select>
              <span class="mt-1 block text-xs text-gray-500">保留优惠区参数；当前 PayPal 提链会复用目标国家同一条粘性代理。</span>
            </label>
          </div>

          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">代理</span>
            <textarea v-model.trim="form.proxies" rows="3" spellcheck="false" placeholder="global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-xxxx-sessTime-180-sessAuto-1:pass" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" :disabled="busy"></textarea>
            <span class="mt-1 block text-xs text-gray-500">填一条代理即可；后端会按目标国家自动切换 region 和 sid，并在创建/优惠/Stripe/approve 复用同一粘性代理。兼容 711、ArxLabs 等 host:port:user:pass 或 URL 格式。</span>
          </label>

          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">Access Token 池（优先于账号池）</span>
            <textarea v-model.trim="form.accessTokens" rows="4" spellcheck="false" placeholder="每行一个 ChatGPT access token；也支持 Bearer xxx。先导入到池，再选择运行。" class="w-full rounded-xl border border-emerald-500/30 bg-emerald-950/10 px-4 py-3 font-mono text-xs text-emerald-50 placeholder:text-emerald-900/60 focus:border-emerald-400 focus:outline-none" :disabled="busy"></textarea>
            <span class="mt-1 block text-xs" :class="directAccessTokens.length ? 'text-emerald-300' : 'text-gray-500'">
              待导入 {{ directAccessTokens.length }} 个；池内 {{ accessTokenPool.length }} 个，已选 {{ selectedAccessTokenItems.length }} 个。只要选中 token，运行会忽略账号池。
            </span>
          </label>

          <section class="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
            <div class="flex flex-wrap items-center gap-2">
              <button @click="importAccessTokensToPool" :disabled="busy || !directAccessTokens.length" class="rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs font-semibold text-emerald-100 hover:bg-emerald-500/20 disabled:opacity-50">导入/追加到池</button>
              <button @click="selectAllAccessTokenPool" :disabled="busy || !filteredAccessTokenPool.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
              <button @click="clearSelectedAccessTokens" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
              <button @click="retryFailedAccessTokens" :disabled="busy || !failedAccessTokenItems.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50">重试失败{{ failedAccessTokenItems.length ? ` (${failedAccessTokenItems.length})` : '' }}</button>
              <button @click="removeSelectedAccessTokens" :disabled="busy || !selectedAccessTokenItems.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
              <button @click="resetSelectedAccessTokenStatus" :disabled="busy || !selectedAccessTokenItems.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">重置状态</button>
              <select v-model="accessTokenStatusFilter" class="ml-auto rounded-lg border border-gray-700 bg-gray-950 px-2 py-2 text-xs text-white focus:border-blue-500 focus:outline-none">
                <option value="all">全部状态</option>
                <option value="pending">未提链</option>
                <option value="running">提链中</option>
                <option value="success">成功</option>
                <option value="failed">失败</option>
                <option value="paid">已支付</option>
                <option value="no_promo">无优惠</option>
                <option value="non_oaics">非Oaics</option>
              </select>
            </div>
            <div class="mt-3 grid grid-cols-5 gap-2 text-xs">
              <div v-for="item in accessTokenPoolStats" :key="item.label" class="rounded-lg border border-gray-800 bg-gray-950/70 p-2">
                <div class="text-gray-500">{{ item.label }}</div>
                <div class="mt-1 font-bold" :class="item.class">{{ item.value }}</div>
              </div>
            </div>
            <div class="mt-3 max-h-52 overflow-y-auto rounded-lg border border-gray-800">
              <table class="w-full text-left text-xs">
                <thead class="sticky top-0 bg-gray-900 text-gray-500">
                  <tr>
                    <th class="w-8 px-2 py-2"></th>
                    <th class="px-2 py-2">账号/标签</th>
                    <th class="px-2 py-2">Token</th>
                    <th class="px-2 py-2">状态</th>
                    <th class="px-2 py-2">失败原因</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-gray-900">
                  <tr v-if="!filteredAccessTokenPool.length">
                    <td colspan="5" class="px-2 py-6 text-center text-gray-500">暂无 token，先粘贴并导入</td>
                  </tr>
                  <tr v-for="item in visibleAccessTokenPool" :key="item.id" class="hover:bg-gray-900/50">
                    <td class="px-2 py-2">
                      <input :checked="selectedAccessTokenIds.has(item.id)" type="checkbox" class="accent-emerald-500" :disabled="busy || item.status === 'paid'" @change="toggleAccessToken(item.id)" />
                    </td>
                    <td class="px-2 py-2 font-mono text-emerald-100">{{ item.label }}</td>
                    <td class="px-2 py-2 font-mono text-gray-500">{{ item.masked }}</td>
                    <td class="px-2 py-2">
                      <span class="rounded-full border px-2 py-1 font-semibold" :class="accessTokenStatusClass(item.status)">{{ accessTokenStatusText(item.status) }}</span>
                    </td>
                    <td class="max-w-[180px] truncate px-2 py-2 text-gray-500" :title="item.error">{{ item.error || '-' }}</td>
                  </tr>
                </tbody>
              </table>
              <div v-if="hiddenAccessTokenCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                <span>已显示 {{ visibleAccessTokenPool.length }} / {{ filteredAccessTokenPool.length }}，剩余 {{ hiddenAccessTokenCount }} 项</span>
                <button @click="showMoreAccessTokens" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
              </div>
            </div>
          </section>

          <div class="grid gap-4 md:grid-cols-3">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="form.concurrency" type="number" min="1" max="30" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 1，最高 30；并发越高越依赖代理质量。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">重试次数</span>
              <input v-model.number="form.maxAttempts" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">单账号最多尝试次数，含首次；默认 5。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">代理预检次数</span>
              <input v-model.number="form.proxyPreflightAttempts" type="number" min="1" max="100" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">代理出口/认证接口预检失败时的最大尝试次数，默认 5。</span>
            </label>
          </div>

          <label class="flex items-start gap-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-3">
            <input v-model="form.onlyOaics" type="checkbox" class="mt-1 h-4 w-4 rounded border-gray-600 bg-gray-950 text-emerald-500 focus:ring-emerald-500" :disabled="busy" />
            <span>
              <span class="block text-sm font-semibold text-emerald-200">仅 OAICS</span>
              <span class="mt-1 block text-xs text-gray-500">开启后返回 cs_* 的账号会直接跳过，只继续 oaics_* native PayPal 提链。</span>
            </span>
          </label>

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="busy" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50">
              {{ busy ? '提取中...' : `开始提链 (${linkInputCount})` }}
            </button>
            <button v-if="busy" @click="cancelJob" :disabled="canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
              {{ canceling ? '取消中...' : '取消提链' }}
            </button>
            <button @click="reloadAll" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号/链接</button>
            <button @click="saveProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
            <button @click="retryFailedAccounts" :disabled="busy || !retryFailedEmails.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50" title="一键重试上一轮提链失败且仍在账号池中的账号">
              失败重试{{ retryFailedEmails.length ? ` (${retryFailedEmails.length})` : '' }}
            </button>
            <NotificationSoundControl v-model="form.notificationSoundEnabled" :disabled="busy" />
          </div>

          <div class="text-sm" :class="statusError ? 'text-rose-300' : 'text-gray-400'">{{ statusText }}</div>
        </div>
      </section>

      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p class="text-xs font-semibold text-gray-500">账号管理</p>
            <h3 class="mt-1 text-xl font-bold text-white">账号池选择</h3>
          </div>
          <div class="text-sm text-gray-400">已选 <span class="font-semibold text-emerald-300">{{ selectedEmails.length }}</span> / {{ filteredAccounts.length }}</div>
        </div>

        <div class="mt-4 flex flex-col gap-3 md:flex-row md:items-center">
          <input v-model.trim="accountFilter" placeholder="搜索账号邮箱" class="min-w-0 flex-1 rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" />
          <select v-model="accountStatusFilter" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
            <option value="all">全部状态</option>
            <option value="pending">未提链</option>
            <option value="failed">提链失败</option>
            <option value="no_promo">无优惠</option>
            <option value="non_oaics">非Oaics</option>
            <option value="success">已提链</option>
            <option value="paid">已支付</option>
          </select>
          <select v-model="accountCountryFilter" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none">
            <option value="all">全部国家</option>
            <option v-for="country in accountCountryOptions" :key="country" :value="country">{{ country }}</option>
          </select>
          <div class="flex flex-wrap gap-2">
            <button @click="selectAllFiltered" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
            <label class="inline-flex items-center gap-2 rounded-lg border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-400">
              <span>前N</span>
              <input v-model.number="accountQuickSelectCount" type="number" min="1" class="w-20 rounded border border-gray-800 bg-gray-900 px-2 py-1 text-xs text-white focus:border-blue-500 focus:outline-none" placeholder="N" />
            </label>
            <button @click="selectFirstFilteredAccounts" :disabled="busy || !filteredAccounts.length" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-200 hover:bg-blue-500/20 disabled:opacity-50">快速勾选前N个</button>
            <button @click="clearSelectedAccounts" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
            <button @click="deleteSelectedPaypalAccounts" :disabled="busy || deletingPaypalAccounts.size > 0 || !selectedEmails.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">
              删除选中{{ selectedEmails.length ? ` (${selectedEmails.length})` : '' }}
            </button>
          </div>
        </div>

        <div class="mt-4 max-h-[520px] overflow-y-auto rounded-xl border border-gray-800">
          <table class="w-full text-left text-sm">
            <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th class="w-10 px-3 py-2"></th>
                <th class="px-3 py-2">邮箱</th>
                <th class="px-3 py-2">国家</th>
                <th class="px-3 py-2">有效期</th>
                <th class="px-3 py-2">提链状态</th>
                <th class="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-900">
              <tr v-if="!filteredAccounts.length">
                <td colspan="6" class="px-3 py-10 text-center text-gray-500">暂无账号</td>
              </tr>
              <tr v-for="account in visibleAccounts" :key="account.email" class="hover:bg-gray-900/50">
                <td class="px-3 py-2">
                  <input :checked="selectedAccounts.has(account.email)" type="checkbox" class="accent-emerald-500" :disabled="busy || !accountSelectable(account)" @change="toggleAccount(account.email)" />
                </td>
                <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ account.email }}</td>
                <td class="px-3 py-2 text-xs text-gray-400">{{ accountPaypalCountry(account) }}</td>
                <td class="px-3 py-2 text-xs text-gray-500">{{ ttlText(account.ttl_seconds) }}</td>
                <td class="px-3 py-2 text-xs">
                  <span class="inline-flex rounded-full border px-2 py-1 font-semibold" :class="accountStatusClass(account)" :title="accountStatusError(account)">
                    {{ accountStatusText(account) }}
                  </span>
                </td>
                <td class="px-3 py-2 text-right">
                  <button @click="deletePaypalAccount(account.email)" :disabled="busy || deletingPaypalAccounts.has(account.email)" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50" title="从 PayPal 账号池和仪表盘账号池中删除该账号">
                    {{ deletingPaypalAccounts.has(account.email) ? '删除中' : '删除' }}
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="hiddenAccountCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
            <span>已显示 {{ visibleAccounts.length }} / {{ filteredAccounts.length }} 个账号</span>
            <button @click="showMoreAccounts" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
          </div>
        </div>
      </section>

      <div class="space-y-5">
        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4">
            <div>
              <p class="text-xs font-semibold text-gray-500">实时状态</p>
              <h3 class="mt-1 text-xl font-bold text-white">执行日志</h3>
            </div>
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="badgeClass">{{ badgeText }}</span>
          </div>
          <div ref="logRef" class="mt-4 h-72 overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-3 font-mono text-xs text-gray-400">
            <div v-if="!logs.length" class="flex h-full items-center justify-center font-sans text-sm text-gray-500">暂无执行日志</div>
            <div v-for="(line, index) in logs" :key="index" class="border-b border-gray-900 py-1 last:border-b-0">{{ line }}</div>
          </div>
        </section>

        <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
          <div class="flex items-center justify-between border-b border-gray-800 pb-4">
            <div>
              <p class="text-xs font-semibold text-gray-500">当前结果</p>
              <h3 class="mt-1 text-xl font-bold text-white">最近一次任务</h3>
            </div>
            <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="currentResult ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-gray-700 bg-gray-900 text-gray-400'">{{ currentResult ? '有结果' : '等待提取' }}</span>
          </div>

          <div v-if="!currentResult" class="flex min-h-48 flex-col items-center justify-center text-center text-gray-500">
            <strong class="text-gray-300">尚未生成结果</strong>
            <span class="mt-1 text-sm">从账号池勾选账号后开始提链</span>
          </div>

          <div v-else class="mt-5 max-h-72 space-y-3 overflow-y-auto pr-1 text-sm">
            <div class="flex flex-col gap-3 rounded-xl border border-gray-800 bg-gray-950 p-4 text-gray-300 sm:flex-row sm:items-center sm:justify-between">
              <div>
                本次完成：成功 <span class="font-semibold text-emerald-300">{{ currentResult.successes?.length || 0 }}</span>，失败 <span class="font-semibold text-rose-300">{{ currentResult.errors?.length || 0 }}</span>，跳过 <span class="font-semibold text-gray-300">{{ currentResult.skipped?.length || 0 }}</span>
              </div>
              <select v-model="recentResultFilter" class="w-fit rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 text-xs font-semibold text-gray-200 focus:border-blue-500 focus:outline-none">
                <option value="all">全部</option>
                <option value="success">已提链</option>
                <option value="failed">提链失败</option>
              </select>
            </div>
            <div v-if="recentResultFilter !== 'failed'" v-for="item in visibleRecentResultSuccesses" :key="item.email" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
              <div class="font-mono text-emerald-200">{{ item.email }}</div>
              <div class="mt-1 text-[11px] text-emerald-300/80">国家：{{ linkCountry(item.link) }}</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!(item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url) ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制链</button>
              </div>
            </div>
            <div v-if="recentResultFilter !== 'success'" v-for="item in visibleRecentResultErrors" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {{ item.email }}：{{ item.error }}
            </div>
            <div v-if="recentResultFilter === 'all'" v-for="item in visibleRecentResultSkipped" :key="item.email" class="rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-2 text-xs text-gray-300">
              {{ item.email }}：{{ item.reason || '已跳过' }}
            </div>
            <div v-if="!filteredRecentResultCount" class="rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-8 text-center text-xs text-gray-500">当前筛选下暂无结果</div>
            <div v-if="hiddenRecentResultCount > 0" class="sticky bottom-0 flex items-center justify-between rounded-lg border border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
              <span>已显示 {{ visibleRecentResultCount }} / {{ filteredRecentResultCount }}，剩余 {{ hiddenRecentResultCount }} 项</span>
              <button @click="showMoreRecentResults" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
            </div>
          </div>
        </section>
      </div>
    </div>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="text-xs font-semibold text-gray-500">链接管理</p>
          <h3 class="mt-1 text-xl font-bold text-white">已提取 PayPal 链接</h3>
        </div>
        <div class="flex flex-wrap gap-2">
          <select v-model="linkCountryFilter" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-xs font-semibold text-gray-200 focus:border-blue-500 focus:outline-none">
            <option value="all">全部国家</option>
            <option v-for="country in linkCountryOptions" :key="country" :value="country">{{ country }}</option>
          </select>
          <button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button>
          <button @click="exportLinks" :disabled="!filteredLinks.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button>
          <button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
          <button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空</button>
        </div>
      </div>

      <div class="mt-4 max-h-[520px] overflow-auto rounded-xl border border-gray-800">
        <table class="min-w-[1260px] w-full text-left text-sm">
          <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="w-10 px-3 py-2"></th>
              <th class="px-3 py-2">时间</th>
              <th class="px-3 py-2">链接有效期</th>
              <th class="px-3 py-2">账号</th>
              <th class="px-3 py-2">国家</th>
              <th class="px-3 py-2">金额</th>
              <th class="px-3 py-2">CS ID</th>
              <th class="px-3 py-2">操作</th>
              <th class="px-3 py-2">PayPal 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!filteredLinks.length">
              <td colspan="9" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in visibleLinks" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ linkCreatedAtText(link) }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-xs" :class="paypalLinkIsActive(link) ? 'text-emerald-300' : 'text-rose-300'">{{ linkValidityText(link) }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || link.accountEmail || '-' }}</td>
              <td class="px-3 py-2 text-xs"><span class="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2 py-1 font-semibold text-cyan-200">{{ linkCountry(link) }}</span></td>
              <td class="px-3 py-2 text-xs text-gray-400">{{ link.amount || '-' }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-400">{{ link.cs_id || '-' }}</td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-2">
                  <a :href="link.paypal_link || link.provider_redirect_url || link.stripe_redirect_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!(link.paypal_link || link.provider_redirect_url || link.stripe_redirect_url) ? 'pointer-events-none opacity-50' : ''">打开</a>
                  <button @click="copy(link.paypal_link || link.provider_redirect_url || link.stripe_redirect_url)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200">复制链</button>
                </div>
              </td>
              <td class="max-w-[360px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ link.paypal_link || link.provider_redirect_url || link.stripe_redirect_url || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="hiddenLinkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
          <span>已显示 {{ visibleLinks.length }} / {{ filteredLinks.length }}，剩余 {{ hiddenLinkCount }} 项</span>
          <button @click="showMoreLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
        </div>
      </div>
    </section>
    </template>

    <section v-else-if="activeTab === 'protocol'" class="rounded-2xl border border-indigo-500/20 bg-gray-950/70 p-5 md:p-6">
      <div class="grid gap-5 xl:grid-cols-[minmax(360px,0.9fr)_minmax(460px,1.1fr)]">
        <div class="space-y-5">
          <div class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <h3 class="text-lg font-bold text-white">协议支付输入</h3>
            <div class="mt-5 space-y-4">
              <div class="rounded-xl border border-indigo-500/20 bg-indigo-500/10 p-4">
                <div class="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p class="text-sm font-semibold text-indigo-100">选择已成功提链账号</p>
                    <p class="mt-1 text-xs text-indigo-200/75">从已保存的真 BA 链接中选择，自动填入 BA 链、国家和关联账号邮箱。</p>
                  </div>
                  <span class="text-xs font-semibold text-indigo-200/80">可选 {{ protocolLinkAccountOptions.length }} 个</span>
                </div>
                <div class="grid gap-3 md:grid-cols-[150px_150px_150px_minmax(0,1fr)]">
                  <label class="block">
                    <span class="mb-1.5 block text-xs font-semibold text-indigo-200">国家筛选</span>
                    <select v-model="protocolLinkCountryFilter" class="w-full rounded-lg border border-indigo-500/30 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-400 focus:outline-none" :disabled="protocolBusy">
                      <option value="all">全部国家</option>
                      <option v-for="country in protocolLinkCountryOptions" :key="country" :value="country">{{ country }}</option>
                    </select>
                  </label>
                  <label class="block">
                    <span class="mb-1.5 block text-xs font-semibold text-indigo-200">提取时间</span>
                    <select v-model="protocolLinkTimeFilter" class="w-full rounded-lg border border-indigo-500/30 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-400 focus:outline-none" :disabled="protocolBusy">
                      <option v-for="option in linkTimeFilterOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                    </select>
                  </label>
                  <label class="block">
                    <span class="mb-1.5 block text-xs font-semibold text-indigo-200">状态筛选</span>
                    <select v-model="protocolLinkStatusFilter" class="w-full rounded-lg border border-indigo-500/30 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-400 focus:outline-none" :disabled="protocolBusy">
                      <option v-for="option in paymentAccountStatusFilterOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                    </select>
                  </label>
                  <label class="block">
                    <span class="mb-1.5 block text-xs font-semibold text-indigo-200">已成功提链账号</span>
                    <select v-model="selectedProtocolAccountEmail" @change="applySelectedProtocolAccount" class="w-full rounded-lg border border-indigo-500/30 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-400 focus:outline-none" :disabled="protocolBusy || !protocolLinkAccountOptions.length">
                      <option value="">{{ protocolLinkAccountOptions.length ? '选择账号并填入 BA 链' : '暂无符合条件的成功提链账号' }}</option>
                      <option v-for="item in visibleProtocolLinkAccountOptions" :key="item.email" :value="item.email" :disabled="protocolBusy || !paymentLinkAccountSelectable(item, protocolPaymentAccountStatus)">
                        {{ item.country }} · {{ linkCreatedAtText(item.link) }} · {{ item.email }}
                      </option>
                    </select>
                  </label>
                </div>
                <div class="mt-3 flex flex-wrap items-center gap-2">
                  <button @click="toggleProtocolLinkSortOrder" :disabled="protocolBusy" class="rounded-lg border border-indigo-500/30 bg-gray-950 px-3 py-2 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/10 disabled:opacity-50">
                    {{ protocolLinkSortOrder === 'desc' ? '倒序：新→旧' : '顺序：旧→新' }}
                  </button>
                  <button @click="selectAllProtocolAccounts" :disabled="protocolBusy || !protocolLinkSelectableEmails.size" class="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/20 disabled:opacity-50">全选当前</button>
                  <label class="inline-flex items-center gap-2 rounded-lg border border-indigo-500/20 bg-gray-950 px-2 py-1 text-xs text-indigo-200/80">
                    <span>前N</span>
                    <input v-model.number="protocolQuickSelectCount" type="number" min="1" class="w-20 rounded border border-indigo-500/20 bg-gray-900 px-2 py-1 text-xs text-white focus:border-indigo-400 focus:outline-none" placeholder="N" :disabled="protocolBusy" />
                  </label>
                  <button @click="selectFirstProtocolAccounts" :disabled="protocolBusy || !protocolLinkSelectableEmails.size" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-200 hover:bg-blue-500/20 disabled:opacity-50">快速勾选前N条</button>
                  <button @click="clearSelectedProtocolAccounts" :disabled="protocolBusy || !selectedProtocolAccountEmails.size" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空协议多选</button>
                  <button @click="refreshPaymentLinks" :disabled="protocolBusy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">刷新链接列表</button>
                  <span class="text-xs font-semibold text-indigo-200/80">已选支付账号 {{ protocolSelectedEmails.length }}</span>
                </div>
                <div class="mt-3 max-h-44 overflow-y-auto rounded-xl border border-indigo-500/20">
                  <table class="w-full text-left text-xs">
                    <thead class="sticky top-0 bg-gray-900 text-indigo-200/70">
                      <tr>
                        <th class="w-10 px-3 py-2"></th>
                        <th class="px-3 py-2">账号</th>
                        <th class="px-3 py-2">国家</th>
                        <th class="px-3 py-2">提取时间</th>
                        <th class="px-3 py-2">链接有效期</th>
                        <th class="px-3 py-2">状态</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-900">
                      <tr v-if="!protocolLinkAccountOptions.length">
                        <td colspan="6" class="px-3 py-6 text-center text-gray-500">暂无符合条件的成功提链账号</td>
                      </tr>
                      <tr v-for="item in visibleProtocolLinkAccountOptions" :key="item.email" class="hover:bg-gray-900/60">
                        <td class="px-3 py-2"><input :checked="selectedProtocolAccountEmails.has(item.email)" type="checkbox" class="accent-indigo-500" :disabled="protocolBusy || !paymentLinkAccountSelectable(item, protocolPaymentAccountStatus)" @change="toggleProtocolAccount(item.email)" /></td>
                        <td class="px-3 py-2 font-mono text-gray-300">{{ item.email }}</td>
                        <td class="px-3 py-2 text-gray-400">{{ item.country }}</td>
                        <td class="whitespace-nowrap px-3 py-2 text-gray-500">{{ linkCreatedAtText(item.link) }}</td>
                        <td class="whitespace-nowrap px-3 py-2 text-emerald-300">{{ linkValidityText(item.link) }}</td>
                        <td class="px-3 py-2">
                          <span class="rounded-full border px-2 py-0.5 font-semibold" :class="protocolPaymentAccountStatusClass(item)">
                            {{ protocolPaymentAccountStatusText(item) }}
                          </span>
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-if="hiddenProtocolLinkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-indigo-500/20 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                    <span>已显示 {{ visibleProtocolLinkAccountOptions.length }} / {{ protocolLinkAccountOptions.length }}，剩余 {{ hiddenProtocolLinkCount }} 项</span>
                    <button @click="showMoreProtocolLinks" class="rounded-lg border border-indigo-500/30 bg-gray-900 px-3 py-1.5 font-semibold text-indigo-100 hover:bg-indigo-500/10">加载更多</button>
                  </div>
                </div>
              </div>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">BA 链接 / BA token</span>
                <textarea v-model.trim="protocolForm.paypalLink" rows="3" spellcheck="false" placeholder="https://www.paypal.com/agreements/approve?ba_token=BA-...&#10;https://www.paypal.com/agreements/approve?ba_token=BA-..." class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
                <span class="mt-1 block text-xs" :class="directProtocolBaLinks.length ? 'text-indigo-300' : 'text-gray-500'">每行一条，可粘贴多条 BA 链接。待导入 {{ directProtocolBaLinks.length }} 条；池内 {{ protocolBaPool.length }} 条，已选 {{ selectedProtocolBaItems.length }} 条。未勾选已提链账号时优先使用 BA 链池。</span>
              </label>

              <section class="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3">
                <div class="flex flex-wrap items-center gap-2">
                  <button @click="importBaLinksToPool('protocol')" :disabled="protocolBusy || !directProtocolBaLinks.length" class="rounded-lg border border-indigo-500/40 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/20 disabled:opacity-50">导入/追加到 BA 池</button>
                  <button @click="selectAllBaPool('protocol')" :disabled="protocolBusy || !filteredProtocolBaPool.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
                  <button @click="clearSelectedBaPool('protocol')" :disabled="protocolBusy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
                  <button @click="retryFailedBaPool('protocol')" :disabled="protocolBusy || !failedProtocolBaItems.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50">重试失败{{ failedProtocolBaItems.length ? ` (${failedProtocolBaItems.length})` : '' }}</button>
                  <button @click="removeSelectedBaPool('protocol')" :disabled="protocolBusy || !selectedProtocolBaItems.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
                  <button @click="resetSelectedBaPoolStatus('protocol')" :disabled="protocolBusy || !selectedProtocolBaItems.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">重置状态</button>
                  <select v-model="protocolBaStatusFilter" class="ml-auto rounded-lg border border-gray-700 bg-gray-950 px-2 py-2 text-xs text-white focus:border-indigo-500 focus:outline-none">
                    <option value="all">全部状态</option>
                    <option value="pending">未支付</option>
                    <option value="running">支付中</option>
                    <option value="unknown_outcome">结果待核对</option>
                    <option value="paid">已支付</option>
                    <option value="failed">失败</option>
                    <option value="cancelled">已取消</option>
                  </select>
                </div>
                <div class="mt-3 grid grid-cols-4 gap-2 text-xs">
                  <div v-for="item in protocolBaPoolStats" :key="item.label" class="rounded-lg border border-gray-800 bg-gray-950/70 p-2">
                    <div class="text-gray-500">{{ item.label }}</div>
                    <div class="mt-1 font-bold" :class="item.class">{{ item.value }}</div>
                  </div>
                </div>
                <div class="mt-3 max-h-44 overflow-y-auto rounded-lg border border-gray-800">
                  <table class="w-full text-left text-xs">
                    <thead class="sticky top-0 bg-gray-900 text-gray-500">
                      <tr><th class="w-8 px-2 py-2"></th><th class="px-2 py-2">BA</th><th class="px-2 py-2">国家</th><th class="px-2 py-2">状态</th><th class="px-2 py-2">失败原因</th></tr>
                    </thead>
                    <tbody class="divide-y divide-gray-900">
                      <tr v-if="!filteredProtocolBaPool.length"><td colspan="5" class="px-2 py-6 text-center text-gray-500">暂无 BA 链，先粘贴并导入</td></tr>
                      <tr v-for="item in visibleProtocolBaPool" :key="item.id" class="hover:bg-gray-900/50">
                        <td class="px-2 py-2"><input :checked="selectedProtocolBaIds.has(item.id)" type="checkbox" class="accent-indigo-500" :disabled="protocolBusy || !baPoolItemSelectable(item)" @change="toggleBaPoolItem('protocol', item.id)" /></td>
                        <td class="px-2 py-2 font-mono text-indigo-100">{{ item.baToken }}</td>
                        <td class="px-2 py-2 text-gray-400">{{ item.country }}</td>
                        <td class="px-2 py-2"><span class="rounded-full border px-2 py-1 font-semibold" :class="baPoolStatusClass(item.status)">{{ baPoolStatusText(item.status) }}</span></td>
                        <td class="max-w-[180px] truncate px-2 py-2 text-gray-500" :title="item.error">{{ item.error || '-' }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-if="hiddenProtocolBaCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-indigo-500/20 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                    <span>已显示 {{ visibleProtocolBaPool.length }} / {{ filteredProtocolBaPool.length }}，剩余 {{ hiddenProtocolBaCount }} 项</span>
                    <button @click="showMoreProtocolBaPool" class="rounded-lg border border-indigo-500/30 bg-gray-900 px-3 py-1.5 font-semibold text-indigo-100 hover:bg-indigo-500/10">加载更多</button>
                  </div>
                </div>
              </section>

              <div class="grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">国家</span>
                  <select v-model="protocolForm.country" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy">
                    <option value="AU">AU · 澳大利亚</option>
                    <option value="BR">BR · 巴西</option>
                    <option value="CA">CA · 加拿大</option>
                    <option value="GB">GB · 英国</option>
                    <option value="ID">ID · 印度尼西亚</option>
                    <option value="JP">JP · 日本</option>
                    <option value="MX">MX · 墨西哥</option>
                    <option value="PH">PH · 菲律宾</option>
                    <option value="TH">TH · 泰国</option>
                    <option value="NL">NL · 荷兰</option>
                    <option value="US">US · 美国</option>
                  </select>
                  <span class="mt-1 block text-xs text-gray-500">US 使用 no-FI；其它国家使用本地化账单/地址 signup-card/auto 兼容路径。</span>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">手机号接码</span>
                  <select v-model="protocolForm.smsProvider" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy">
                    <option value="sms_record">固定手机号 + SMS record URL</option>
                    <option value="hero_sms">HeroSMS 自动取号</option>
                    <option value="hero_sms_rent">HeroSMS 长效号（已购买）</option>
                    <option value="smsbower">SMSBower 自动取号</option>
                  </select>
                  <span class="mt-1 block text-xs text-gray-500">自动取号走服务商库存；HeroSMS 长效号会复用你已购买的号码并由后端轮询验证码。</span>
                </label>
              </div>

              <section v-if="protocolForm.smsProvider === 'sms_record'" class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">手机号池</span>
                <div class="space-y-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <button type="button" @click="protocolPhonePoolImportOpen = !protocolPhonePoolImportOpen" :disabled="protocolBusy" class="rounded-lg border border-yellow-500/50 bg-yellow-500/10 px-3 py-2 text-xs font-semibold text-yellow-200 hover:bg-yellow-500/20 disabled:opacity-50">加入手机号池</button>
                    <button type="button" @click="resetPhonePoolStatusesForText(protocolForm.phonePool, 'protocol')" :disabled="protocolBusy || !phonePoolEntriesFor(protocolForm.phonePool, 'protocol').length" class="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">重置状态</button>
                    <button type="button" @click="purgeUsedPhonePoolEntries('protocol')" :disabled="protocolBusy || !phonePoolEntriesFor(protocolForm.phonePool, 'protocol').length" class="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清理已使用</button>
                    <button type="button" @click="clearPhonePoolEntries('protocol')" :disabled="protocolBusy || !protocolForm.phonePool" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空手机号</button>
                  </div>
                  <textarea v-if="protocolPhonePoolImportOpen || !phonePoolEntriesFor(protocolForm.phonePool, 'protocol').length" v-model.trim="protocolForm.phonePool" rows="4" placeholder="+447383370667----https://api.sms8.net/api/record?token=bx56haoxaoqs07vj0cls2fxeokuf2gywyxy8p&#10;+447383370668----https://api.sms8.net/api/record?token=..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
                  <div class="max-h-56 overflow-y-auto rounded-2xl border border-gray-700 bg-gray-950">
                    <table class="w-full text-left text-xs">
                      <thead class="sticky top-0 bg-gray-900 text-gray-500">
                        <tr>
                          <th class="px-3 py-2">手机号</th>
                          <th class="px-3 py-2">状态</th>
                          <th class="px-3 py-2">SMS record URL</th>
                          <th class="px-3 py-2 text-right">操作</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-gray-900">
                        <tr v-if="!protocolPhonePoolEntries.length">
                          <td colspan="4" class="px-3 py-6 text-center text-gray-500">暂无手机号；点击“加入手机号池”批量导入。</td>
                        </tr>
                        <tr v-for="item in visibleProtocolPhonePoolEntries" :key="item.key" class="hover:bg-gray-900/60">
                          <td class="px-3 py-2 font-mono text-gray-300">{{ item.phone }}</td>
                          <td class="px-3 py-2">
                            <span class="rounded-full border px-2 py-0.5 font-semibold" :class="phonePoolStatusClass(item.status)">{{ phonePoolStatusText(item.status) }}</span>
                            <div class="mt-1 text-[11px] text-gray-500">{{ phonePoolEntryQuotaText(item.status) }}</div>
                          </td>
                          <td class="max-w-[360px] truncate px-3 py-2 font-mono text-gray-500">{{ item.url || '-' }}</td>
                          <td class="px-3 py-2 text-right"><button type="button" @click="removePhonePoolEntry('protocol', item.key)" :disabled="protocolBusy" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button></td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-if="hiddenProtocolPhoneCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-indigo-500/20 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                      <span>已显示 {{ visibleProtocolPhonePoolEntries.length }} / {{ protocolPhonePoolEntries.length }}，剩余 {{ hiddenProtocolPhoneCount }} 项</span>
                      <button @click="showMoreProtocolPhones" class="rounded-lg border border-indigo-500/30 bg-gray-900 px-3 py-1.5 font-semibold text-indigo-100 hover:bg-indigo-500/10">加载更多</button>
                    </div>
                  </div>
                </div>
                <span class="mt-1 block text-xs text-gray-500">每行一个“手机号----SMS record URL”；并发批量支付时后端会自动领取未使用号码。</span>
              </section>

              <template v-else-if="protocolForm.smsProvider === 'hero_sms_rent'">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">HeroSMS 长效号码</span>
                  <textarea v-model.trim="protocolForm.phone" rows="3" placeholder="+316..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
                  <span class="mt-1 block text-xs text-gray-500">填写 HeroSMS 已购买的长效号码；批量支付时每行一个长效号码，后端按账号顺序分配并轮询 PayPal OTP。</span>
                </label>
              </template>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">协议支付代理（可选）</span>
                <textarea v-model.trim="protocolForm.proxies" rows="3" spellcheck="false" placeholder="proxy.example.com:10000:USER-zone-custom-region-US-session-xxxx-sessTime-120-sessAuto-1:pass" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
                <span class="mt-1 block text-xs text-gray-500">每行一个代理；批量支付时按账号顺序分配，代理少于账号时循环复用。</span>
              </label>

              <div class="grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发支付数</span>
                  <input v-model.number="protocolForm.concurrency" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                  <span class="mt-1 block text-xs text-gray-500">多选账号时生效，默认 1，最高 20。</span>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">代理预检次数</span>
                  <input v-model.number="protocolForm.proxyPreflightAttempts" type="number" min="1" max="100" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                  <span class="mt-1 block text-xs text-gray-500">代理出口/认证接口预检失败时的最大尝试次数，默认 5。</span>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">OTP 等待秒数</span>
                  <input v-model.number="protocolForm.smsRecordWaitSeconds" type="number" min="60" max="900" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                  <span class="mt-1 block text-xs text-gray-500">默认 300；PayPal 短信慢时可调到 600。</span>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">OTP 轮询间隔</span>
                  <input v-model.number="protocolForm.smsRecordPollSeconds" type="number" min="1" max="30" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                  <span class="mt-1 block text-xs text-gray-500">默认 3 秒。</span>
                </label>
              </div>

              <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
                <button @click="startProtocolPayment" :disabled="protocolBusy" class="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-indigo-500 disabled:opacity-50">
                  {{ protocolBusy ? '支付中...' : `开始协议支付${protocolSelectedEmails.length ? ` (${protocolSelectedEmails.length})` : ''}` }}
                </button>
                <button type="button" @click="toggleProtocolAutoPay" class="rounded-lg border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50" :class="protocolAutoPayActive ? 'border-rose-500/40 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20' : 'border-indigo-500/40 bg-indigo-500/10 text-indigo-100 hover:bg-indigo-500/20'">
                  {{ protocolAutoPayActive ? `停止自动支付 (${protocolAutoPayQueue.length})` : '自动支付' }}
                </button>
                <button v-if="protocolRecoveryPaused && protocolRecoveryCheckpoint?.submitPayload" type="button" @click="resumeProtocolRecovery" class="rounded-lg border border-blue-500/40 bg-blue-500/10 px-4 py-2.5 text-sm font-semibold text-blue-100 transition hover:bg-blue-500/20">继续确认未知提交</button>
                <button v-if="protocolRecoveryPaused" type="button" @click="discardProtocolRecovery" :disabled="protocolBusy" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-100 transition hover:bg-amber-500/20 disabled:opacity-50">确认远端无任务并解除占用</button>
                <button v-if="protocolLegacyUnresolvedAutoPayCount" type="button" @click="clearLegacyUnresolvedAutoPayJobs('protocol')" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-100 transition hover:bg-amber-500/20">
                  解除旧未知任务 ({{ protocolLegacyUnresolvedAutoPayCount }})
                </button>
                <button v-if="protocolBusy" @click="cancelProtocolJob" :disabled="protocolCanceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
                  {{ protocolCanceling ? '取消中...' : '取消支付' }}
                </button>
                <button @click="saveProtocolForm" :disabled="protocolBusy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存输入</button>
                <button type="button" @click="togglePhonePoolReuse" :disabled="protocolBusy" class="rounded-lg border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50" :class="phonePoolReuseEnabled ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20' : 'border-gray-700 bg-gray-900 text-gray-200 hover:bg-gray-800'">{{ phonePoolReuseEnabled ? '关闭手机号复用' : '开启手机号复用' }}</button>
              </div>
              <div v-if="protocolAutoPayStatusText" class="text-xs text-indigo-200/80">{{ protocolAutoPayStatusText }}</div>
              <div class="text-sm" :class="protocolStatusError ? 'text-rose-300' : 'text-gray-400'">{{ protocolStatusText }}</div>
            </div>
          </div>
        </div>

        <div class="space-y-5">
          <section class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <div class="flex items-center justify-between border-b border-gray-800 pb-4">
              <div>
                <p class="text-xs font-semibold text-gray-500">实时状态</p>
                <h3 class="mt-1 text-xl font-bold text-white">协议支付日志</h3>
              </div>
              <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="protocolBadgeClass">{{ protocolBadgeText }}</span>
            </div>
            <div ref="protocolLogRef" class="mt-4 h-96 overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-3 font-mono text-xs text-gray-400">
              <div v-if="!protocolLogs.length" class="flex h-full items-center justify-center font-sans text-sm text-gray-500">暂无协议支付日志</div>
              <div v-for="(line, index) in protocolLogs" :key="index" class="border-b border-gray-900 py-1 last:border-b-0">{{ line }}</div>
            </div>
          </section>

          <section class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <div class="flex items-center justify-between border-b border-gray-800 pb-4">
              <div>
                <p class="text-xs font-semibold text-gray-500">当前结果</p>
                <h3 class="mt-1 text-xl font-bold text-white">协议支付结果</h3>
              </div>
              <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="protocolResult ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-gray-700 bg-gray-900 text-gray-400'">{{ protocolResult ? '有结果' : '等待支付' }}</span>
            </div>
            <pre v-if="protocolResult" class="mt-4 max-h-72 overflow-auto rounded-xl border border-gray-800 bg-gray-950 p-4 text-xs text-gray-300">{{ JSON.stringify(protocolResult, null, 2) }}</pre>
            <div v-else class="flex min-h-36 flex-col items-center justify-center text-center text-gray-500">
              <strong class="text-gray-300">尚未提交协议支付</strong>
              <span class="mt-1 text-sm">选择 AU/BR/CA/GB/ID/JP/MX/PH/TH/NL/US，填入 BA，并选择固定 SMS URL / HeroSMS / SMSBower 后开始。</span>
            </div>
          </section>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'pay153'" class="rounded-2xl border border-cyan-500/20 bg-gray-950/70 p-5 md:p-6">
      <div class="grid gap-5 xl:grid-cols-[minmax(420px,1fr)_minmax(420px,0.9fr)]">
        <div class="space-y-5">
          <div class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
              <div>
                <p class="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300/70">PAY.153 REMOTE CORE</p>
                <h3 class="mt-1 text-xl font-bold text-white">153支付输入</h3>
                <p class="mt-1 text-xs text-gray-500">多选已提链账号后，本地后端批量提交到 153 协议支付接口；账号支付失败自动重试最多 3 次。</p>
              </div>
              <span class="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-xs font-semibold text-cyan-200">已选 {{ pay153SelectedEmails.length }}</span>
            </div>

            <div class="mt-5 space-y-4">
              <div class="rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-4">
                <div class="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
                  <div>
                    <p class="text-sm font-semibold text-cyan-100">选择已成功提链账号</p>
                    <p class="mt-1 text-xs text-cyan-200/75">按账号保存的 BA 链和国家提交到 153；支持多选批量。</p>
                  </div>
                  <span class="text-xs font-semibold text-cyan-200/80">可选 {{ pay153LinkAccountOptions.length }} 个</span>
                </div>
                <div class="mb-3 flex flex-col gap-3 md:flex-row md:flex-wrap md:items-center">
                  <select v-model="pay153LinkCountryFilter" class="rounded-lg border border-cyan-500/30 bg-gray-950 px-3 py-2 text-sm text-white focus:border-cyan-400 focus:outline-none" :disabled="pay153Busy">
                    <option value="all">全部国家</option>
                    <option v-for="country in protocolLinkCountryOptions" :key="country" :value="country">{{ country }}</option>
                  </select>
                  <select v-model="pay153LinkTimeFilter" class="rounded-lg border border-cyan-500/30 bg-gray-950 px-3 py-2 text-sm text-white focus:border-cyan-400 focus:outline-none" :disabled="pay153Busy">
                    <option v-for="option in linkTimeFilterOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <select v-model="pay153LinkStatusFilter" class="rounded-lg border border-cyan-500/30 bg-gray-950 px-3 py-2 text-sm text-white focus:border-cyan-400 focus:outline-none" :disabled="pay153Busy">
                    <option v-for="option in paymentAccountStatusFilterOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <button @click="togglePay153LinkSortOrder" :disabled="pay153Busy" class="rounded-lg border border-cyan-500/30 bg-gray-950 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/10 disabled:opacity-50">
                    {{ pay153LinkSortOrder === 'desc' ? '倒序：新→旧' : '顺序：旧→新' }}
                  </button>
                  <button @click="selectAllPay153Accounts" :disabled="pay153Busy || !pay153LinkSelectableEmails.size" class="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">全选当前</button>
                  <label class="inline-flex items-center gap-2 rounded-lg border border-cyan-500/20 bg-gray-950 px-2 py-1 text-xs text-cyan-200/80">
                    <span>前N</span>
                    <input v-model.number="pay153QuickSelectCount" type="number" min="1" class="w-20 rounded border border-cyan-500/20 bg-gray-900 px-2 py-1 text-xs text-white focus:border-cyan-400 focus:outline-none" placeholder="N" :disabled="pay153Busy" />
                  </label>
                  <button @click="selectFirstPay153Accounts" :disabled="pay153Busy || !pay153LinkSelectableEmails.size" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 text-xs font-semibold text-blue-200 hover:bg-blue-500/20 disabled:opacity-50">快速勾选前N条</button>
                  <button @click="clearSelectedPay153Accounts" :disabled="pay153Busy || !selectedPay153AccountEmails.size" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
                  <button @click="refreshPaymentLinks" :disabled="pay153Busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">刷新链接列表</button>
                </div>
                <div class="max-h-56 overflow-y-auto rounded-xl border border-cyan-500/20">
                  <table class="w-full text-left text-xs">
                    <thead class="sticky top-0 bg-gray-900 text-cyan-200/70">
                      <tr>
                        <th class="w-10 px-3 py-2"></th>
                        <th class="px-3 py-2">账号</th>
                        <th class="px-3 py-2">国家</th>
                        <th class="px-3 py-2">提取时间</th>
                        <th class="px-3 py-2">链接有效期</th>
                        <th class="px-3 py-2">状态</th>
                        <th class="px-3 py-2">BA</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-gray-900">
                      <tr v-if="!pay153LinkAccountOptions.length">
                        <td colspan="7" class="px-3 py-8 text-center text-gray-500">暂无符合条件的成功提链账号</td>
                      </tr>
                      <tr v-for="item in visiblePay153LinkAccountOptions" :key="item.email" class="hover:bg-gray-900/60">
                        <td class="px-3 py-2"><input :checked="selectedPay153AccountEmails.has(item.email)" type="checkbox" class="accent-cyan-500" :disabled="pay153Busy || !paymentLinkAccountSelectable(item, pay153PaymentAccountStatus)" @change="togglePay153Account(item.email)" /></td>
                        <td class="px-3 py-2 font-mono text-gray-300">{{ item.email }}</td>
                        <td class="px-3 py-2 text-gray-400">{{ item.country }}</td>
                        <td class="whitespace-nowrap px-3 py-2 text-gray-500">{{ linkCreatedAtText(item.link) }}</td>
                        <td class="whitespace-nowrap px-3 py-2 text-emerald-300">{{ linkValidityText(item.link) }}</td>
                        <td class="px-3 py-2">
                          <span class="rounded-full border px-2 py-0.5 font-semibold" :class="pay153PaymentAccountStatusClass(item)">
                            {{ pay153PaymentAccountStatusText(item) }}
                          </span>
                        </td>
                        <td class="max-w-[180px] truncate px-3 py-2 font-mono text-gray-500">{{ displayBaToken(item.baToken || item.paypalLink) }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-if="hiddenPay153LinkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-cyan-500/20 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                    <span>已显示 {{ visiblePay153LinkAccountOptions.length }} / {{ pay153LinkAccountOptions.length }}，剩余 {{ hiddenPay153LinkCount }} 项</span>
                    <button @click="showMorePay153Links" class="rounded-lg border border-cyan-500/30 bg-gray-900 px-3 py-1.5 font-semibold text-cyan-100 hover:bg-cyan-500/10">加载更多</button>
                  </div>
                </div>
              </div>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">BA 链接 / BA token</span>
                <textarea v-model.trim="pay153Form.paypalLink" rows="3" spellcheck="false" placeholder="https://www.paypal.com/agreements/approve?ba_token=BA-...&#10;https://www.paypal.com/agreements/approve?ba_token=BA-..." class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy"></textarea>
                <span class="mt-1 block text-xs" :class="directPay153BaLinks.length ? 'text-cyan-300' : 'text-gray-500'">每行一条，可粘贴多条 BA 链接。待导入 {{ directPay153BaLinks.length }} 条；池内 {{ pay153BaPool.length }} 条，已选 {{ selectedPay153BaItems.length }} 条。未选择已提链账号时优先使用 BA 链池。</span>
              </label>

              <section class="rounded-xl border border-cyan-500/20 bg-cyan-500/5 p-3">
                <div class="flex flex-wrap items-center gap-2">
                  <button @click="importBaLinksToPool('pay153')" :disabled="pay153Busy || !directPay153BaLinks.length" class="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">导入/追加到 BA 池</button>
                  <button @click="selectAllBaPool('pay153')" :disabled="pay153Busy || !filteredPay153BaPool.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
                  <button @click="clearSelectedBaPool('pay153')" :disabled="pay153Busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
                  <button @click="retryFailedBaPool('pay153')" :disabled="pay153Busy || !failedPay153BaItems.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 disabled:opacity-50">重试失败{{ failedPay153BaItems.length ? ` (${failedPay153BaItems.length})` : '' }}</button>
                  <button @click="removeSelectedBaPool('pay153')" :disabled="pay153Busy || !selectedPay153BaItems.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
                  <button @click="resetSelectedBaPoolStatus('pay153')" :disabled="pay153Busy || !selectedPay153BaItems.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">重置状态</button>
                  <select v-model="pay153BaStatusFilter" class="ml-auto rounded-lg border border-gray-700 bg-gray-950 px-2 py-2 text-xs text-white focus:border-cyan-500 focus:outline-none">
                    <option value="all">全部状态</option>
                    <option value="pending">未支付</option>
                    <option value="running">支付中</option>
                    <option value="unknown_outcome">结果待核对</option>
                    <option value="paid">已支付</option>
                    <option value="failed">失败</option>
                    <option value="cancelled">已取消</option>
                  </select>
                </div>
                <div class="mt-3 grid grid-cols-4 gap-2 text-xs">
                  <div v-for="item in pay153BaPoolStats" :key="item.label" class="rounded-lg border border-gray-800 bg-gray-950/70 p-2">
                    <div class="text-gray-500">{{ item.label }}</div>
                    <div class="mt-1 font-bold" :class="item.class">{{ item.value }}</div>
                  </div>
                </div>
                <div class="mt-3 max-h-44 overflow-y-auto rounded-lg border border-gray-800">
                  <table class="w-full text-left text-xs">
                    <thead class="sticky top-0 bg-gray-900 text-gray-500">
                      <tr><th class="w-8 px-2 py-2"></th><th class="px-2 py-2">BA</th><th class="px-2 py-2">国家</th><th class="px-2 py-2">状态</th><th class="px-2 py-2">失败原因</th></tr>
                    </thead>
                    <tbody class="divide-y divide-gray-900">
                      <tr v-if="!filteredPay153BaPool.length"><td colspan="5" class="px-2 py-6 text-center text-gray-500">暂无 BA 链，先粘贴并导入</td></tr>
                      <tr v-for="item in visiblePay153BaPool" :key="item.id" class="hover:bg-gray-900/50">
                        <td class="px-2 py-2"><input :checked="selectedPay153BaIds.has(item.id)" type="checkbox" class="accent-cyan-500" :disabled="pay153Busy || !baPoolItemSelectable(item)" @change="toggleBaPoolItem('pay153', item.id)" /></td>
                        <td class="px-2 py-2 font-mono text-cyan-100">{{ item.baToken }}</td>
                        <td class="px-2 py-2 text-gray-400">{{ item.country }}</td>
                        <td class="px-2 py-2"><span class="rounded-full border px-2 py-1 font-semibold" :class="baPoolStatusClass(item.status)">{{ baPoolStatusText(item.status) }}</span></td>
                        <td class="max-w-[180px] truncate px-2 py-2 text-gray-500" :title="item.error">{{ item.error || '-' }}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div v-if="hiddenPay153BaCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-cyan-500/20 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                    <span>已显示 {{ visiblePay153BaPool.length }} / {{ filteredPay153BaPool.length }}，剩余 {{ hiddenPay153BaCount }} 项</span>
                    <button @click="showMorePay153BaPool" class="rounded-lg border border-cyan-500/30 bg-gray-900 px-3 py-1.5 font-semibold text-cyan-100 hover:bg-cyan-500/10">加载更多</button>
                  </div>
                </div>
              </section>

              <div class="grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">国家</span>
                  <select v-model="pay153Form.country" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy">
                    <option value="AUTO">按账号提链国家</option>
                    <option v-for="country in paypalCountryOptions" :key="country.value" :value="country.value">{{ country.label }}</option>
                  </select>
                  <span class="mt-1 block text-xs text-gray-500">选择具体国家会覆盖账号保存的国家并提交给 153。</span>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">手机号供应商</span>
                  <select v-model="pay153Form.smsProvider" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy">
                    <option value="sms_record">号池（手机号 + SMS record URL）</option>
                    <option value="hero_sms">HeroSMS 自动取号</option>
                    <option value="hero_sms_rent">HeroSMS 长效号（已购买）</option>
                    <option value="smsbower">SMSBower 自动取号</option>
                  </select>
                  <span class="mt-1 block text-xs text-gray-500">153 原站只收手机号；HeroSMS/SMSBower 60 秒未收到验证码自动换号，最多 3 次。</span>
                </label>
              </div>

              <section v-if="pay153Form.smsProvider === 'sms_record'" class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">手机号池</span>
                <div class="space-y-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <button type="button" @click="pay153PhonePoolImportOpen = !pay153PhonePoolImportOpen" :disabled="pay153Busy" class="rounded-lg border border-yellow-500/50 bg-yellow-500/10 px-3 py-2 text-xs font-semibold text-yellow-200 hover:bg-yellow-500/20 disabled:opacity-50">加入手机号池</button>
                    <button type="button" @click="resetPhonePoolStatusesForText(pay153Form.phonePool, 'pay153')" :disabled="pay153Busy || !phonePoolEntriesFor(pay153Form.phonePool, 'pay153').length" class="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">重置状态</button>
                    <button type="button" @click="purgeUsedPhonePoolEntries('pay153')" :disabled="pay153Busy || !phonePoolEntriesFor(pay153Form.phonePool, 'pay153').length" class="rounded-lg border border-gray-600 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清理已使用</button>
                    <button type="button" @click="clearPhonePoolEntries('pay153')" :disabled="pay153Busy || !pay153Form.phonePool" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空手机号</button>
                  </div>
                  <textarea v-if="pay153PhonePoolImportOpen || !phonePoolEntriesFor(pay153Form.phonePool, 'pay153').length" v-model.trim="pay153Form.phonePool" rows="4" placeholder="+447383370667----https://api.sms8.net/api/record?token=bx56haoxaoqs07vj0cls2fxeokuf2gywyxy8p&#10;+447383370668----https://api.sms8.net/api/record?token=..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy"></textarea>
                  <div class="max-h-56 overflow-y-auto rounded-2xl border border-gray-700 bg-gray-950">
                    <table class="w-full text-left text-xs">
                      <thead class="sticky top-0 bg-gray-900 text-gray-500">
                        <tr>
                          <th class="px-3 py-2">手机号</th>
                          <th class="px-3 py-2">状态</th>
                          <th class="px-3 py-2">SMS record URL</th>
                          <th class="px-3 py-2 text-right">操作</th>
                        </tr>
                      </thead>
                      <tbody class="divide-y divide-gray-900">
                        <tr v-if="!pay153PhonePoolEntries.length">
                          <td colspan="4" class="px-3 py-6 text-center text-gray-500">暂无手机号；点击“加入手机号池”批量导入。</td>
                        </tr>
                        <tr v-for="item in visiblePay153PhonePoolEntries" :key="item.key" class="hover:bg-gray-900/60">
                          <td class="px-3 py-2 font-mono text-gray-300">{{ item.phone }}</td>
                          <td class="px-3 py-2">
                            <span class="rounded-full border px-2 py-0.5 font-semibold" :class="phonePoolStatusClass(item.status)">{{ phonePoolStatusText(item.status) }}</span>
                            <div class="mt-1 text-[11px] text-gray-500">{{ phonePoolEntryQuotaText(item.status) }}</div>
                          </td>
                          <td class="max-w-[360px] truncate px-3 py-2 font-mono text-gray-500">{{ item.url || '-' }}</td>
                          <td class="px-3 py-2 text-right"><button type="button" @click="removePhonePoolEntry('pay153', item.key)" :disabled="pay153Busy" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button></td>
                        </tr>
                      </tbody>
                    </table>
                    <div v-if="hiddenPay153PhoneCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-cyan-500/20 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                      <span>已显示 {{ visiblePay153PhonePoolEntries.length }} / {{ pay153PhonePoolEntries.length }}，剩余 {{ hiddenPay153PhoneCount }} 项</span>
                      <button @click="showMorePay153Phones" class="rounded-lg border border-cyan-500/30 bg-gray-900 px-3 py-1.5 font-semibold text-cyan-100 hover:bg-cyan-500/10">加载更多</button>
                    </div>
                  </div>
                </div>
                <span class="mt-1 block text-xs text-gray-500">每行一个“手机号----SMS record URL”；并发启动时后端会自动领取未使用号码。</span>
              </section>

              <label v-if="pay153Form.smsProvider === 'hero_sms_rent'" class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">HeroSMS 长效手机号</span>
                <textarea v-model.trim="pay153Form.phone" rows="4" placeholder="+447700900001&#10;+6281234567890" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy"></textarea>
                <span class="mt-1 block text-xs text-gray-500">每行一个已购买长效号，按选中的账号顺序分配。</span>
              </label>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">153支付代理池</span>
                <textarea v-model.trim="pay153Form.proxies" rows="4" spellcheck="false" placeholder="host:port:username:password&#10;http://username:password@host:port" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy"></textarea>
                <span class="mt-1 block text-xs text-gray-500">提交给 153 远端任务；代理池最多 500 条。</span>
              </label>

              <div class="grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">Buyer 身份模式</span>
                  <select v-model="pay153Form.buyerMode" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy">
                    <option value="identity_elevation">身份提升流程</option>
                    <option value="original">原版流程</option>
                  </select>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发提交数</span>
                  <input v-model.number="pay153Form.concurrency" type="number" min="1" max="10" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy" />
                </label>
              </div>

              <div class="grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">验证码等待秒数</span>
                  <input v-model.number="pay153Form.smsRecordWaitSeconds" type="number" min="30" max="900" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy" />
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">轮询间隔秒数</span>
                  <input v-model.number="pay153Form.smsRecordPollSeconds" type="number" min="1" max="30" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-cyan-500 focus:outline-none" :disabled="pay153Busy" />
                </label>
              </div>

              <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
                <button @click="startPay153Payment" :disabled="pay153Busy || pay153Canceling" class="rounded-lg bg-cyan-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50">
                  {{ pay153Busy ? '153支付中...' : `开始153支付 (${pay153SelectedEmails.length})` }}
                </button>
                <button type="button" @click="togglePay153AutoPay" :disabled="pay153Canceling && !pay153AutoPayActive" class="rounded-lg border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50" :class="pay153AutoPayActive ? 'border-rose-500/40 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20' : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100 hover:bg-cyan-500/20'">
                  {{ pay153AutoPayActive ? `停止自动支付 (${pay153AutoPayQueue.length})` : '自动支付' }}
                </button>
                <button v-if="pay153RecoveryPaused && pay153RecoveryCheckpoint?.submitPayload" type="button" @click="resumePay153Recovery" class="rounded-lg border border-blue-500/40 bg-blue-500/10 px-4 py-2.5 text-sm font-semibold text-blue-100 transition hover:bg-blue-500/20">继续确认未知提交</button>
                <button v-if="pay153RecoveryPaused" type="button" @click="discardPay153Recovery" :disabled="pay153Busy" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-100 transition hover:bg-amber-500/20 disabled:opacity-50">确认远端无任务并解除占用</button>
                <button v-if="pay153LegacyUnresolvedAutoPayCount" type="button" @click="clearLegacyUnresolvedAutoPayJobs('pay153')" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-100 transition hover:bg-amber-500/20">
                  解除旧未知任务 ({{ pay153LegacyUnresolvedAutoPayCount }})
                </button>
                <button @click="retryFailedPay153Payment" :disabled="pay153Busy || pay153Canceling || !pay153FailedEmails.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50">
                  失败重试{{ pay153FailedEmails.length ? ` (${pay153FailedEmails.length})` : '' }}
                </button>
                <button v-if="pay153Busy" @click="cancelPay153Job" :disabled="pay153Canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
                  {{ pay153Canceling ? '取消中...' : '取消153支付' }}
                </button>
                <button type="button" @click="cancelPay153RemoteByCurrentBa" :disabled="pay153Canceling || pay153Busy || pay153AutoPayActive || !!pay153AutoPayActiveJobs.length" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
                  清理153卡住任务
                </button>
                <button @click="savePay153Form" :disabled="pay153Busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存输入</button>
                <button type="button" @click="togglePhonePoolReuse" :disabled="pay153Busy" class="rounded-lg border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50" :class="phonePoolReuseEnabled ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200 hover:bg-emerald-500/20' : 'border-gray-700 bg-gray-900 text-gray-200 hover:bg-gray-800'">{{ phonePoolReuseEnabled ? '关闭手机号复用' : '开启手机号复用' }}</button>
              </div>
              <div v-if="pay153AutoPayStatusText" class="text-xs text-cyan-200/80">{{ pay153AutoPayStatusText }}</div>
              <div class="text-sm" :class="pay153StatusError ? 'text-rose-300' : 'text-gray-400'">{{ pay153StatusText }}</div>
            </div>
          </div>
        </div>

        <div class="space-y-5">
          <section class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <div class="flex items-center justify-between border-b border-gray-800 pb-4">
              <div>
                <p class="text-xs font-semibold text-gray-500">实时状态</p>
                <h3 class="mt-1 text-xl font-bold text-white">153支付日志</h3>
              </div>
              <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="pay153BadgeClass">{{ pay153BadgeText }}</span>
            </div>
            <div ref="pay153LogRef" class="mt-4 h-96 overflow-y-auto rounded-xl border border-gray-800 bg-gray-950 p-3 font-mono text-xs text-gray-400">
              <div v-if="!pay153Logs.length" class="flex h-full items-center justify-center font-sans text-sm text-gray-500">暂无153支付日志</div>
              <div v-for="(line, index) in pay153Logs" :key="index" class="border-b border-gray-900 py-1 last:border-b-0">{{ line }}</div>
            </div>
          </section>

          <section class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <div class="flex items-center justify-between border-b border-gray-800 pb-4">
              <div>
                <p class="text-xs font-semibold text-gray-500">当前结果</p>
                <h3 class="mt-1 text-xl font-bold text-white">153支付结果</h3>
              </div>
              <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="pay153Result ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300' : 'border-gray-700 bg-gray-900 text-gray-400'">{{ pay153Result ? '有结果' : '等待支付' }}</span>
            </div>
            <pre v-if="pay153Result" class="mt-4 max-h-72 overflow-auto rounded-xl border border-gray-800 bg-gray-950 p-4 text-xs text-gray-300">{{ JSON.stringify(pay153Result, null, 2) }}</pre>
            <div v-else class="flex min-h-36 flex-col items-center justify-center text-center text-gray-500">
              <strong class="text-gray-300">尚未提交153支付</strong>
              <span class="mt-1 text-sm">选择已提链账号，填写手机号和代理池后开始。</span>
            </div>
          </section>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { paypalStatusPresentation as workflowStatusPresentation } from '../operationsPresentation.js'

import WorkflowWorkspace from './workflow/WorkflowWorkspace.vue'
import WorkflowStage from './workflow/WorkflowStage.vue'
import UiButton from './ui/UiButton.vue'
import UiSegmentedControl from './ui/UiSegmentedControl.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'

import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { createDeferredStorageWriter } from '../deferredStorage.js'
import { compactPaymentJobSnapshot, createSnapshotWriteGate } from '../jobSnapshot.js'
import {
  createSubmissionGenerationGuard,
  isAmbiguousPaymentFailure,
  PAYMENT_RECOVERY_MAX_ATTEMPTS,
  paymentRecoveryDelayMs,
} from '../paymentRequestState.js'
import { createSharedPollingGate } from '../pollingLifecycle.js'
import { readPollingSnapshot } from '../pollingRecovery.js'
import { createSessionStorageFacade } from '../sessionStorageScope.js'
import NotificationSoundControl from './NotificationSoundControl.vue'
import {
  paypalAccountCountryOptions,
  paypalLinkCreatedAtMs,
  paypalLinkExpiresAtMs,
  paypalLinkIsActive,
  resolveSelectedPayPalLinkAccount,
  successfulPayPalLinkAccounts,
} from '../paypalAccountOptions.js'
import { PAYPAL_LINK_SUCCESS_SOUND_URL, playNotificationSound } from '../notificationSounds.js'

const FORM_STORAGE_KEY = 'autotoken_us_paypal_form'
const JOB_STORAGE_KEY = 'autotoken_us_paypal_job'
const ACTIVE_TAB_STORAGE_KEY = 'autotoken_us_paypal_active_tab'
const ACCESS_TOKEN_POOL_STORAGE_KEY = 'autotoken_us_paypal_access_token_pool'
const PROTOCOL_BA_POOL_STORAGE_KEY = 'autotoken_us_paypal_protocol_ba_pool'
const PAY153_BA_POOL_STORAGE_KEY = 'autotoken_us_paypal_153_ba_pool'
const PROTOCOL_FORM_STORAGE_KEY = 'autotoken_us_paypal_protocol_form'
const PROTOCOL_JOB_STORAGE_KEY = 'autotoken_us_paypal_protocol_job'
const PAY153_FORM_STORAGE_KEY = 'autotoken_us_paypal_153_form'
const PAY153_JOB_STORAGE_KEY = 'autotoken_us_paypal_153_job'
const PHONE_POOL_MANAGEMENT_STORAGE_KEY = 'autotoken_us_paypal_phone_pool_management'
const PAYPAL_AUTO_PAY_STATE_STORAGE_KEY = 'autotoken_us_paypal_auto_pay_state'
const sessionStorageFacade = createSessionStorageFacade()
const storageWriter = createDeferredStorageWriter()
const jobSnapshotWriteGate = createSnapshotWriteGate()
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented', 'unknown_outcome'])
const AUTO_PAYMENT_POLL_MS = 60 * 1000
const AUTO_PAYMENT_IDLE_LIMIT_MS = 30 * 60 * 1000
const ACCOUNT_STATUS_TEXT = { pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', no_promo: '无优惠', non_oaics: '非Oaics', paid: '已支付', unknown_outcome: '支付结果待核对' }
const PROTOCOL_COUNTRIES = new Set(['AU', 'BR', 'CA', 'GB', 'ID', 'JP', 'MX', 'PH', 'TH', 'NL', 'US'])
const linkTimeFilterOptions = [
  { value: 'all', label: '全部时间' },
  { value: '15m', label: '最近15分钟' },
  { value: '60m', label: '最近1小时' },
  { value: '180m', label: '最近3小时' },
]
const paymentAccountStatusFilterOptions = [
  { value: 'all', label: '全部状态' },
  { value: 'success', label: '已提链/待支付' },
  { value: 'running', label: '支付中' },
  { value: 'unknown_outcome', label: '结果待核对' },
  { value: 'failed', label: '支付失败' },
  { value: 'pending', label: '未提链' },
  { value: 'no_promo', label: '无优惠' },
  { value: 'non_oaics', label: '非Oaics' },
]
const paypalCountryOptions = [
  { value: 'BA', label: 'BA · 波黑' },
  { value: 'US', label: 'US · 美国' },
  { value: 'GB', label: 'GB · 英国' },
  { value: 'CA', label: 'CA · 加拿大' },
  { value: 'AU', label: 'AU · 澳大利亚' },
  { value: 'JP', label: 'JP · 日本' },
  { value: 'BR', label: 'BR · 巴西' },
  { value: 'ID', label: 'ID · 印度尼西亚' },
  { value: 'VN', label: 'VN · 越南' },
  { value: 'TH', label: 'TH · 泰国' },
  { value: 'TR', label: 'TR · 土耳其' },
  { value: 'DE', label: 'DE · 德国' },
  { value: 'FR', label: 'FR · 法国' },
  { value: 'IT', label: 'IT · 意大利' },
  { value: 'ES', label: 'ES · 西班牙' },
  { value: 'NL', label: 'NL · 荷兰' },
  { value: 'SG', label: 'SG · 新加坡' },
  { value: 'HK', label: 'HK · 香港' },
  { value: 'TW', label: 'TW · 台湾' },
  { value: 'KR', label: 'KR · 韩国' },
  { value: 'MX', label: 'MX · 墨西哥' },
  { value: 'NZ', label: 'NZ · 新西兰' },
]
const promoRegionOptions = [
  { value: 'JP', label: 'JP · 日本' },
  { value: 'GB', label: 'GB · 英国' },
  { value: 'US', label: 'US · 美国' },
  { value: 'BR', label: 'BR · 巴西' },
  { value: 'ID', label: 'ID · 印度尼西亚' },
  { value: 'VN', label: 'VN · 越南' },
  { value: 'TH', label: 'TH · 泰国' },
  { value: 'PH', label: 'PH · 菲律宾' },
  { value: 'TR', label: 'TR · 土耳其' },
]

const form = ref({
  proxies: '',
  accessTokens: '',
  concurrency: 1,
  maxAttempts: 5,
  proxyPreflightAttempts: 5,
  region: 'US',
  promoRegion: 'JP',
  onlyOaics: false,
  notificationSoundEnabled: true,
})
const accounts = ref([])
const links = ref([])
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const accessTokenPool = ref([])
const selectedAccessTokenIds = ref(new Set())
const accessTokenStatusFilter = ref('all')
const accessTokenVisibleCount = ref(100)
const busy = ref(false)
const canceling = ref(false)
const currentJob = ref(null)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const currentResult = ref(null)
const accountFilter = ref('')
const accountStatusFilter = ref('all')
const accountCountryFilter = ref('all')
const accountQuickSelectCount = ref(10)
const accountVisibleCount = ref(100)
const linkCountryFilter = ref('all')
const linkVisibleCount = ref(100)
const protocolLinkCountryFilter = ref('all')
const protocolLinkTimeFilter = ref('all')
const protocolLinkStatusFilter = ref('all')
const protocolLinkVisibleCount = ref(100)
const protocolLinkSortOrder = ref('desc')
const protocolQuickSelectCount = ref(10)
const recentResultFilter = ref('all')
const recentResultVisibleCount = ref(100)
const selectedProtocolAccountEmail = ref('')
const selectedProtocolAccountEmails = ref(new Set())
const selectedPay153AccountEmails = ref(new Set())
const protocolBaPool = ref([])
const pay153BaPool = ref([])
const selectedProtocolBaIds = ref(new Set())
const selectedPay153BaIds = ref(new Set())
const protocolBaStatusFilter = ref('all')
const pay153BaStatusFilter = ref('all')
const protocolBaVisibleCount = ref(100)
const pay153BaVisibleCount = ref(100)
const PHONE_POOL_REUSE_STORAGE_KEY = 'autotoken-us-paypal-phone-pool-reuse'
const phonePoolReuseEnabled = ref(false)
const phonePoolStatusMap = ref({})
const protocolPhonePoolImportOpen = ref(false)
const pay153PhonePoolImportOpen = ref(false)
const protocolPhoneVisibleCount = ref(100)
const pay153PhoneVisibleCount = ref(100)
const retryFailedEmailSet = ref(new Set())
const deletingPaypalAccounts = ref(new Set())
const logRef = ref(null)
const activeTab = ref('links')
const protocolForm = ref({
  paypalLink: '',
  phone: '',
  phonePool: '',
  smsRecordUrl: '',
  smsProvider: 'sms_record',
  proxies: '',
  country: 'US',
  accountEmail: '',
  concurrency: 1,
  smsRecordWaitSeconds: 300,
  smsRecordPollSeconds: 3,
  proxyPreflightAttempts: 5,
})
const protocolBusy = ref(false)
const protocolCanceling = ref(false)
const protocolJob = ref(null)
const protocolLogs = ref([])
const protocolResult = ref(null)
const protocolStatusText = ref('等待提交协议支付。')
const protocolStatusError = ref(false)
const protocolRecoveryPaused = ref(false)
const protocolRecoveryCheckpoint = ref(null)
const protocolLogRef = ref(null)
const protocolAutoPayActive = ref(false)
const protocolAutoPayQueue = ref([])
const protocolAutoPayActiveJobs = ref([])
const protocolAutoPaySeenKeys = ref(new Set())
const protocolAutoPayLastNewAt = ref(0)
const protocolAutoPayStatusText = ref('')
const pay153Form = ref({
  paypalLink: '',
  country: 'AUTO',
  smsProvider: 'sms_record',
  phone: '',
  phonePool: '',
  smsRecordUrl: '',
  proxies: '',
  buyerMode: 'identity_elevation',
  concurrency: 1,
  smsRecordWaitSeconds: 300,
  smsRecordPollSeconds: 3,
})
const pay153Busy = ref(false)
const pay153Canceling = ref(false)
const pay153Job = ref(null)
const pay153Logs = ref([])
const pay153Result = ref(null)
const pay153StatusText = ref('等待提交153支付。')
const pay153StatusError = ref(false)
const pay153RecoveryPaused = ref(false)
const pay153RecoveryCheckpoint = ref(null)
const pay153LogRef = ref(null)
const pay153AutoPayActive = ref(false)
const pay153AutoPayQueue = ref([])
const pay153AutoPayActiveJobs = ref([])
const pay153AutoPaySeenKeys = ref(new Set())
const pay153AutoPayLastNewAt = ref(0)
const pay153AutoPayStatusText = ref('')
const pay153LinkCountryFilter = ref('all')
const pay153LinkTimeFilter = ref('all')
const pay153LinkStatusFilter = ref('all')
const pay153LinkSortOrder = ref('desc')
const pay153QuickSelectCount = ref(10)
const pay153LinkVisibleCount = ref(100)
const pay153ActionInputs = ref({})
let componentUnmounted = false
let protocolSubmissionCancelRequested = false
let pay153SubmissionCancelRequested = false
const protocolSubmissionGuard = createSubmissionGenerationGuard()
const pay153SubmissionGuard = createSubmissionGenerationGuard()
const paypalPolling = createSharedPollingGate()
let protocolAutoPayScheduleGeneration = 0
let pay153AutoPayScheduleGeneration = 0
let protocolAutoPayDraining = false
let pay153AutoPayDraining = false
const protocolAutoPayLogOffsets = new Map()
const pay153AutoPayLogOffsets = new Map()
const protocolAutoPayStartReconciliations = new Set()
const pay153AutoPayStartReconciliations = new Set()
const protocolClaimedPhonePoolKeysByJob = new Map()
const pay153ClaimedPhonePoolKeysByJob = new Map()

const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const directAccessTokens = computed(() => parseAccessTokens(form.value.accessTokens))
const selectedAccessTokenItems = computed(() => accessTokenPool.value.filter(item => selectedAccessTokenIds.value.has(item.id) && item.status !== 'paid'))
const failedAccessTokenItems = computed(() => accessTokenPool.value.filter(item => item.status === 'failed'))
const filteredAccessTokenPool = computed(() => {
  const target = String(accessTokenStatusFilter.value || 'all').trim().toLowerCase()
  if (!target || target === 'all') return accessTokenPool.value
  return accessTokenPool.value.filter(item => String(item.status || 'pending').toLowerCase() === target)
})
const visibleAccessTokenPool = computed(() => filteredAccessTokenPool.value.slice(0, accessTokenVisibleCount.value))
const hiddenAccessTokenCount = computed(() => Math.max(0, filteredAccessTokenPool.value.length - visibleAccessTokenPool.value.length))
const accessTokenPoolStats = computed(() => [
  { label: '池内', value: accessTokenPool.value.length, class: 'text-gray-200' },
  { label: '已选', value: selectedAccessTokenItems.value.length, class: 'text-white' },
  { label: '成功', value: accessTokenPool.value.filter(item => item.status === 'success').length, class: 'text-emerald-300' },
  { label: '失败', value: accessTokenPool.value.filter(item => item.status === 'failed').length, class: 'text-rose-300' },
  { label: '已支付', value: accessTokenPool.value.filter(item => item.status === 'paid').length, class: 'text-amber-300' },
])
const linkInputCount = computed(() => selectedAccessTokenItems.value.length || directAccessTokens.value.length || selectedEmails.value.length)
const protocolSelectedEmails = computed(() => Array.from(selectedProtocolAccountEmails.value))
const pay153SelectedEmails = computed(() => Array.from(selectedPay153AccountEmails.value))
const directProtocolBaLinks = computed(() => parseManualPaypalLinks(protocolForm.value.paypalLink))
const directPay153BaLinks = computed(() => parseManualPaypalLinks(pay153Form.value.paypalLink))
const selectedProtocolBaItems = computed(() => protocolBaPool.value.filter(item => selectedProtocolBaIds.value.has(item.id) && baPoolItemSelectable(item)))
const selectedPay153BaItems = computed(() => pay153BaPool.value.filter(item => selectedPay153BaIds.value.has(item.id) && baPoolItemSelectable(item)))
const failedProtocolBaItems = computed(() => protocolBaPool.value.filter(item => item.status === 'failed'))
const failedPay153BaItems = computed(() => pay153BaPool.value.filter(item => item.status === 'failed'))
const filteredProtocolBaPool = computed(() => filterBaPool(protocolBaPool.value, protocolBaStatusFilter.value))
const filteredPay153BaPool = computed(() => filterBaPool(pay153BaPool.value, pay153BaStatusFilter.value))
const visibleProtocolBaPool = computed(() => filteredProtocolBaPool.value.slice(0, protocolBaVisibleCount.value))
const hiddenProtocolBaCount = computed(() => Math.max(0, filteredProtocolBaPool.value.length - visibleProtocolBaPool.value.length))
const visiblePay153BaPool = computed(() => filteredPay153BaPool.value.slice(0, pay153BaVisibleCount.value))
const hiddenPay153BaCount = computed(() => Math.max(0, filteredPay153BaPool.value.length - visiblePay153BaPool.value.length))
const protocolBaPoolStats = computed(() => baPoolStats(protocolBaPool.value, selectedProtocolBaItems.value.length))
const pay153BaPoolStats = computed(() => baPoolStats(pay153BaPool.value, selectedPay153BaItems.value.length))
const retryFailedEmails = computed(() => Array.from(retryFailedEmailSet.value).filter(email => accounts.value.some(account => account.email === email && accountSelectable(account))))
function linkCountry(link) {
  const billing = link?.billing && typeof link.billing === 'object' ? link.billing : {}
  return String(link?.target_country || link?.targetCountry || link?.paypal_country || link?.paypalCountry || link?.country || link?.region || billing.country || '-').trim().toUpperCase() || '-'
}

function accountPaypalCountry(account) {
  const status = accountStatus(account)
  const country = String(account?.paypal_country || account?.paypalCountry || '').trim().toUpperCase()
  return status === 'success' && country ? country : '-'
}

function countryMatchesFilter(country, filter) {
  const normalized = String(country || '-').trim().toUpperCase() || '-'
  const target = String(filter || 'all').trim().toUpperCase()
  return target === 'ALL' || normalized === target
}

const filteredAccounts = computed(() => accounts.value.filter((account) => {
  const status = accountStatus(account)
  return (
    (!accountFilter.value || String(account.email || '').toLowerCase().includes(accountFilter.value.toLowerCase()))
    && (accountStatusFilter.value === 'all' || status === accountStatusFilter.value)
    && countryMatchesFilter(accountPaypalCountry(account), accountCountryFilter.value)
  )
}))
const visibleAccounts = computed(() => filteredAccounts.value.slice(0, accountVisibleCount.value))
const hiddenAccountCount = computed(() => Math.max(0, filteredAccounts.value.length - visibleAccounts.value.length))
const filteredLinks = computed(() => links.value.filter(link => countryMatchesFilter(linkCountry(link), linkCountryFilter.value)))
const visibleLinks = computed(() => filteredLinks.value.slice(0, linkVisibleCount.value))
const hiddenLinkCount = computed(() => Math.max(0, filteredLinks.value.length - visibleLinks.value.length))
const accountCountryOptions = computed(() => Array.from(new Set(accounts.value.map(accountPaypalCountry).filter(country => country && country !== '-'))).sort())
const linkCountryOptions = computed(() => Array.from(new Set(links.value.map(linkCountry).filter(country => country && country !== '-'))).sort())
const protocolLinkCountryOptions = computed(() => paypalAccountCountryOptions(accounts.value, links.value))
const protocolLinkAccountOptions = computed(() => filterPaymentLinkAccountsByStatus(
  successfulPayPalLinkAccounts(accounts.value, links.value, protocolLinkCountryFilter.value, { timeFilter: protocolLinkTimeFilter.value, sortOrder: protocolLinkSortOrder.value }),
  protocolLinkStatusFilter.value,
  protocolPaymentAccountStatus,
))
const visibleProtocolLinkAccountOptions = computed(() => protocolLinkAccountOptions.value.slice(0, protocolLinkVisibleCount.value))
const hiddenProtocolLinkCount = computed(() => Math.max(0, protocolLinkAccountOptions.value.length - visibleProtocolLinkAccountOptions.value.length))
const pay153LinkAccountOptions = computed(() => filterPaymentLinkAccountsByStatus(
  successfulPayPalLinkAccounts(accounts.value, links.value, pay153LinkCountryFilter.value, { timeFilter: pay153LinkTimeFilter.value, sortOrder: pay153LinkSortOrder.value }),
  pay153LinkStatusFilter.value,
  pay153PaymentAccountStatus,
))
const visiblePay153LinkAccountOptions = computed(() => pay153LinkAccountOptions.value.slice(0, pay153LinkVisibleCount.value))
const hiddenPay153LinkCount = computed(() => Math.max(0, pay153LinkAccountOptions.value.length - visiblePay153LinkAccountOptions.value.length))
const protocolPhonePoolEntries = computed(() => phonePoolEntriesFor(protocolForm.value.phonePool, 'protocol'))
const visibleProtocolPhonePoolEntries = computed(() => protocolPhonePoolEntries.value.slice(0, protocolPhoneVisibleCount.value))
const hiddenProtocolPhoneCount = computed(() => Math.max(0, protocolPhonePoolEntries.value.length - visibleProtocolPhonePoolEntries.value.length))
const pay153PhonePoolEntries = computed(() => phonePoolEntriesFor(pay153Form.value.phonePool, 'pay153'))
const visiblePay153PhonePoolEntries = computed(() => pay153PhonePoolEntries.value.slice(0, pay153PhoneVisibleCount.value))
const hiddenPay153PhoneCount = computed(() => Math.max(0, pay153PhonePoolEntries.value.length - visiblePay153PhonePoolEntries.value.length))
const currentResultSuccesses = computed(() => Array.isArray(currentResult.value?.successes) ? [...currentResult.value.successes].reverse() : [])
const currentResultErrors = computed(() => Array.isArray(currentResult.value?.errors) ? [...currentResult.value.errors].reverse() : [])
const currentResultSkipped = computed(() => Array.isArray(currentResult.value?.skipped) ? [...currentResult.value.skipped].reverse() : [])
const pay153FailedEmails = computed(() => Array.from(new Set((pay153Result.value?.errors || []).filter(paymentResultErrorRetryable).map(item => String(item.email || '').trim()).filter(Boolean))))
const protocolLinkSelectableEmails = computed(() => new Set(protocolLinkAccountOptions.value.filter(item => paymentLinkAccountSelectable(item, protocolPaymentAccountStatus)).map(item => item.email)))
const pay153LinkSelectableEmails = computed(() => new Set(pay153LinkAccountOptions.value.filter(item => paymentLinkAccountSelectable(item, pay153PaymentAccountStatus)).map(item => item.email)))
const protocolPaymentStats = computed(() => [
  { label: '可支付链接', value: protocolLinkAccountOptions.value.length, class: 'text-indigo-200' },
  { label: '已选择', value: protocolSelectedEmails.value.length, class: 'text-white' },
  { label: '进行中', value: Math.max(Number(protocolJob.value?.running_count || 0), protocolAutoPayActiveJobs.value.length), class: 'text-blue-300' },
  { label: '成功', value: protocolResult.value?.successes?.length || 0, class: 'text-emerald-300' },
  { label: '失败', value: protocolResult.value?.errors?.length || 0, class: 'text-rose-300' },
  { label: '跳过', value: protocolResult.value?.skipped?.length || 0, class: 'text-gray-300' },
])
const pay153PaymentStats = computed(() => [
  { label: '可支付链接', value: pay153LinkAccountOptions.value.length, class: 'text-cyan-200' },
  { label: '已选择', value: pay153SelectedEmails.value.length, class: 'text-white' },
  { label: '进行中', value: Math.max(Number(pay153Job.value?.running_count || 0), pay153AutoPayActiveJobs.value.length), class: 'text-blue-300' },
  { label: '成功', value: pay153Result.value?.successes?.length || 0, class: 'text-emerald-300' },
  { label: '失败', value: pay153Result.value?.errors?.length || 0, class: 'text-rose-300' },
  { label: '等待', value: pay153WaitingActions.value.length, class: 'text-amber-300' },
])
const filteredRecentResultCount = computed(() => {
  if (recentResultFilter.value === 'success') return currentResultSuccesses.value.length
  if (recentResultFilter.value === 'failed') return currentResultErrors.value.length
  return currentResultSuccesses.value.length + currentResultErrors.value.length + currentResultSkipped.value.length
})
const progressText = computed(() => {
  const job = currentJob.value || {}
  const completed = Number(job.completed || 0)
  const total = Number(job.total || 0)
  return total ? `提链中 ${completed}/${total}` : '任务执行中'
})
const badgeText = computed(() => {
  const status = String(currentJob.value?.status || '')
  if (status === 'queued') return '排队中'
  if (status === 'running') return progressText.value
  if (status === 'cancelling') return '取消中'
  if (status === 'success') return '已完成'
  if (status === 'cancelled') return '已取消'
  if (status === 'error' || status === 'failed') return '失败'
  return '待开始'
})
const badgeClass = computed(() => {
  const status = String(currentJob.value?.status || '')
  if (status === 'running' || status === 'queued') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'cancelling') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'cancelled') return 'border-gray-700 bg-gray-900 text-gray-300'
  if (status === 'error' || status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
})
const protocolBadgeText = computed(() => {
  const status = String(protocolJob.value?.status || '')
  if (status === 'queued') return '排队中'
  if (status === 'running') return '协议支付中'
  if (status === 'cancelling') return '取消中'
  if (status === 'success') return '支付成功'
  if (status === 'cancelled') return '已取消'
  if (status === 'error' || status === 'failed') return '支付失败'
  return '待开始'
})
const protocolBadgeClass = computed(() => {
  const status = String(protocolJob.value?.status || '')
  if (status === 'running' || status === 'queued') return 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300'
  if (status === 'cancelling') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'cancelled') return 'border-gray-700 bg-gray-900 text-gray-300'
  if (status === 'error' || status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
})
const pay153WaitingActions = computed(() => {
  const children = pay153Job.value?.children || {}
  return Object.values(children).filter(child => child && (child.awaiting_otp || child.awaiting_captcha))
})
const pay153BadgeText = computed(() => {
  const status = String(pay153Job.value?.status || '')
  if (status === 'queued') return '排队中'
  if (status === 'running') return pay153ProgressText.value
  if (status === 'cancelling') return '取消中'
  if (status === 'success') return '153支付完成'
  if (status === 'cancelled') return '已取消'
  if (status === 'error' || status === 'failed') return '153支付失败'
  return '待开始'
})
const pay153BadgeClass = computed(() => {
  const status = String(pay153Job.value?.status || '')
  if (status === 'running' || status === 'queued') return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300'
  if (status === 'cancelling') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'cancelled') return 'border-gray-700 bg-gray-900 text-gray-300'
  if (status === 'error' || status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
})
const pay153ProgressText = computed(() => {
  const job = pay153Job.value || {}
  const completed = Number(job.completed || 0)
  const total = Number(job.total || 0)
  const waiting = pay153WaitingActions.value.length
  if (waiting) return `等待操作 ${waiting}`
  return total ? `153支付 ${completed}/${total}` : '153任务执行中'
})
const anyBusy = computed(() => busy.value || protocolBusy.value || pay153Busy.value || protocolAutoPayActiveJobs.value.length > 0 || pay153AutoPayActiveJobs.value.length > 0)
const isUnresolvedAutoPayItem = item => (
  (!item.jobId && !(item.clientRequestId && item.submitPayload))
  || ['recovery_paused', 'unknown_outcome', 'unknown'].includes(String(item.status || ''))
)
const protocolLegacyUnresolvedAutoPayCount = computed(() => protocolAutoPayActiveJobs.value.filter(isUnresolvedAutoPayItem).length)
const pay153LegacyUnresolvedAutoPayCount = computed(() => pay153AutoPayActiveJobs.value.filter(isUnresolvedAutoPayItem).length)
const activeStatusText = computed(() => {
  if (activeTab.value === 'protocol' && protocolBusy.value) return protocolBadgeText.value
  if (activeTab.value === 'pay153' && pay153Busy.value) return pay153BadgeText.value
  return progressText.value
})

function setStatus(message, error = false) { statusText.value = message; statusError.value = error }
function cleanText(value) { return String(value || '未知错误').replace(/\s+/g, ' ').trim() }
function cleanError(error) { return cleanText(error?.message || error) }
function persistLinkJobState(fallback = {}, options = {}) {
  const payload = paymentJobSnapshot(currentJob.value?.id || fallback.jobId, currentJob.value, logs.value, currentResult.value, statusText.value, statusError.value, fallback)
  if (payload.jobId || payload.logs.length || payload.result) queuePaymentJobSnapshot(JOB_STORAGE_KEY, payload, options)
}
function restoreLinkJobState(saved = {}) {
  if (!saved || typeof saved !== 'object' || !(saved.jobId || saved.job || saved.logs || saved.result)) return false
  currentJob.value = saved.job || { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 0), completed: 0, concurrency: Number(saved.concurrency || 1), running_count: 0 }
  logs.value = Array.isArray(saved.logs) ? saved.logs : []
  currentResult.value = saved.result || null
  if (saved.statusText) setStatus(saved.statusText, Boolean(saved.statusError))
  return true
}
function resumeLinkJobStateFromStorage(options = {}) {
  if (busy.value) return false
  const hasMemoryState = Boolean(currentJob.value?.id || logs.value.length || currentResult.value)
  let saved = {}
  if (!hasMemoryState || options.force) {
    try {
      saved = JSON.parse(sessionStorageFacade.getItem(JOB_STORAGE_KEY) || '{}')
    } catch {
      saved = {}
    }
    if (!restoreLinkJobState(saved)) return false
  }
  const status = String(currentJob.value?.status || '')
  const jobId = currentJob.value?.id || saved.jobId
  if (options.preferredActiveTab === 'links' || !TERMINAL_STATUSES.has(status)) activeTab.value = 'links'
  if (!TERMINAL_STATUSES.has(status) && jobId) {
    busy.value = true
    canceling.value = false
    setStatus('已恢复提链任务，正在重新同步后端进度。')
    persistLinkJobState(saved)
    void pollJob(jobId).catch((error) => {
      setStatus(`恢复提链任务失败：${cleanError(error)}`, true)
      persistLinkJobState()
    }).finally(() => {
      if (!componentUnmounted) {
        busy.value = false
        canceling.value = false
      }
    })
  }
  return true
}
function displayBaToken(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  const match = text.match(/BA-[A-Za-z0-9_-]+/i)
  return match ? match[0] : text
}
function autoPayLinkKey(item) {
  return `${String(item?.email || '').trim().toLowerCase()}::${displayBaToken(item?.paypalLink || item?.link?.ba_token || item?.link?.paypal_link || '')}`
}
function phonePoolEntryKey(scope, phone, url = '') {
  return `${String(scope || 'shared').trim()}::${String(phone || '').trim()}|${String(url || '').trim()}`
}
function parsePhonePoolEntries(value, scope = 'shared') {
  const items = []
  for (const line of String(value || '').replace(/,/g, '\n').split(/\r?\n/)) {
    const text = String(line || '').trim()
    if (!text) continue
    const [phone = '', ...rest] = text.split('----')
    const url = rest.join('----').trim()
    const normalizedPhone = String(phone || '').trim()
    if (!normalizedPhone) continue
    items.push({
      phone: normalizedPhone,
      url,
      key: phonePoolEntryKey(scope, normalizedPhone, url),
    })
  }
  return items
}
function setPhonePoolStatus(entries, status) {
  const next = { ...phonePoolStatusMap.value }
  for (const entry of entries) {
    if (entry?.key) next[entry.key] = status
  }
  phonePoolStatusMap.value = next
}
function phonePoolStatusText(status) {
  return ({ available: '可用', claimed: '已领取', success: '成功', failed: '失败' })[status] || '可用'
}
function phonePoolStatusClass(status) {
  return ({
    available: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    claimed: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    success: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  })[status] || 'border-gray-700 bg-gray-900 text-gray-400'
}
function phonePoolEntryQuotaText(status) {
  if (status === 'claimed') return '额度：总 1，已用 1，处理中 0，剩余 0'
  if (status === 'success') return '额度：总 1，已用 1，处理中 0，剩余 0'
  if (status === 'failed') return '额度：总 1，已用 1，处理中 0，剩余 0'
  return '额度：总 1，已用 0，处理中 0，剩余 1'
}
function phonePoolEntriesFor(value, scope = 'shared') {
  return parsePhonePoolEntries(value, scope).map((item) => ({
    ...item,
    status: phonePoolStatusMap.value[item.key] || 'available',
  }))
}
function phonePoolStatsFor(value, scope = 'shared') {
  const entries = phonePoolEntriesFor(value, scope)
  const counts = { total: entries.length, available: 0, claimed: 0, success: 0, failed: 0 }
  for (const item of entries) {
    if (counts[item.status] !== undefined) counts[item.status] += 1
  }
  return counts
}
function usablePhonePoolEntriesFromText(value, scope = 'shared') {
  const entries = parsePhonePoolEntries(value, scope)
  if (phonePoolReuseEnabled.value) return entries
  return entries.filter(item => {
    const status = phonePoolStatusMap.value[item.key] || 'available'
    return status === 'available' || status === 'failed'
  })
}
function phonePoolPayloadForSubmission(value, scope = 'shared') {
  const entries = usablePhonePoolEntriesFromText(value, scope)
  return formatPhonePoolEntries(entries)
}
function formatPhonePoolEntries(entries) {
  return (entries || []).map(item => `${item.phone}----${item.url}`).join('\n')
}
function claimPhonePoolEntriesForSubmission(value, count, scope = 'shared') {
  if (phonePoolReuseEnabled.value) return []
  const entries = usablePhonePoolEntriesFromText(value, scope).slice(0, Math.max(0, Number(count || 0)))
  setPhonePoolStatus(entries, 'claimed')
  return entries
}
function markPhonePoolClaimedForSubmission(value, count, scope = 'shared') {
  const entries = claimPhonePoolEntriesForSubmission(value, count, scope)
  return entries.map(item => item.key).filter(Boolean)
}
function resetPhonePoolStatusesForText(value, scope = 'shared') {
  const entries = parsePhonePoolEntries(value, scope)
  const next = { ...phonePoolStatusMap.value }
  for (const item of entries) next[item.key] = 'available'
  phonePoolStatusMap.value = next
}
function clearPhonePoolEntries(scope) {
  if (scope === 'protocol') protocolForm.value.phonePool = ''
  if (scope === 'pay153') pay153Form.value.phonePool = ''
}
function purgeUsedPhonePoolEntries(scope) {
  if (scope === 'protocol') {
    const entries = phonePoolEntriesFor(protocolForm.value.phonePool, 'protocol').filter(item => item.status === 'available')
    protocolForm.value.phonePool = entries.map(item => `${item.phone}----${item.url}`).join('\n')
  }
  if (scope === 'pay153') {
    const entries = phonePoolEntriesFor(pay153Form.value.phonePool, 'pay153').filter(item => item.status === 'available')
    pay153Form.value.phonePool = entries.map(item => `${item.phone}----${item.url}`).join('\n')
  }
}
function removePhonePoolEntry(scope, key) {
  const formRef = scope === 'protocol' ? protocolForm : scope === 'pay153' ? pay153Form : null
  if (!formRef) return
  const entries = phonePoolEntriesFor(formRef.value.phonePool, scope).filter(item => item.key !== key)
  formRef.value.phonePool = entries.map(item => `${item.phone}----${item.url}`).join('\n')
}
function syncPhonePoolStatusFromJobResult(result, scope = 'shared') {
  const successes = Array.isArray(result?.successes) ? result.successes : []
  const errors = Array.isArray(result?.errors) ? result.errors : []
  const updates = new Map()
  for (const item of successes) {
    const key = phonePoolEntryKey(scope, item?.phone, item?.phone_url || item?.sms_record_url || item?.record_url || '')
    if (!String(item?.phone || '').trim()) continue
    updates.set(key, 'success')
  }
  for (const item of errors) {
    const key = phonePoolEntryKey(scope, item?.phone, item?.phone_url || item?.sms_record_url || item?.record_url || '')
    if (!String(item?.phone || '').trim()) continue
    updates.set(key, 'failed')
  }
  if (!updates.size) return
  const next = { ...phonePoolStatusMap.value }
  for (const [key, status] of updates) {
    next[key] = status
  }
  phonePoolStatusMap.value = next
}
function releaseClaimedPhonePoolEntriesAfterJob(result, scope = 'shared', claimedKeys = [], sourceText = '') {
  if (phonePoolReuseEnabled.value) return
  const successKeys = new Set()
  const successes = Array.isArray(result?.successes) ? result.successes : []
  for (const item of successes) {
    if (!String(item?.phone || '').trim()) continue
    successKeys.add(phonePoolEntryKey(scope, item?.phone, item?.phone_url || item?.sms_record_url || item?.record_url || ''))
  }
  const providedKeys = (claimedKeys || []).filter(Boolean)
  const fallbackKeys = sourceText && !providedKeys.length
    ? parsePhonePoolEntries(sourceText, scope).filter(item => (phonePoolStatusMap.value[item.key] || 'available') === 'claimed').map(item => item.key)
    : []
  const keys = Array.from(new Set([...providedKeys, ...fallbackKeys]))
  if (!keys.length) return
  const next = { ...phonePoolStatusMap.value }
  let changed = false
  for (const key of keys) {
    if (successKeys.has(key)) continue
    if ((next[key] || 'available') === 'claimed') {
      next[key] = 'failed'
      changed = true
    }
  }
  if (changed) phonePoolStatusMap.value = next
}
function paymentTargetSelectable(status) {
  return !['queued', 'running', 'cancelling', 'unknown', 'unknown_outcome', 'paid'].includes(String(status || '').trim().toLowerCase())
}
function paymentLinkAccountSelectable(item, statusResolver) {
  if (item?.account?.paypal_selectable === false) return false
  return paymentTargetSelectable(statusResolver(item))
}
function paymentResultErrorRetryable(item) {
  return Boolean(item) && item.unknown_outcome !== true && String(item.status || '').trim().toLowerCase() !== 'unknown_outcome'
}
function accountJobStatus(account) { const statuses = currentJob.value?.account_statuses || {}; return statuses[account.email] || statuses[String(account.email || '').toLowerCase()] || null }
function accountStatus(account) { return accountJobStatus(account)?.status || account?.paypal_status || 'pending' }
function ttlText(seconds) { const value = Number(seconds); if (!Number.isFinite(value) || value < 0) return '-'; if (value < 60) return `${Math.floor(value)}s`; if (value < 3600) return `${Math.ceil(value / 60)}m`; return `${Math.ceil(value / 3600)}h` }
function shortDateTime(ms) {
  const value = Number(ms || 0)
  if (!Number.isFinite(value) || value <= 0) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const pad = n => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function linkCreatedAtText(link) { return shortDateTime(paypalLinkCreatedAtMs(link)) }
function linkValidityText(link) {
  const expiresAt = paypalLinkExpiresAtMs(link)
  if (!expiresAt) return '-'
  const remaining = expiresAt - Date.now()
  if (remaining <= 0) return `已过期 · ${shortDateTime(expiresAt)}`
  return `${ttlText(Math.floor(remaining / 1000))} · ${shortDateTime(expiresAt)}`
}
function accountStatusText(account) { const jobStatus = accountJobStatus(account); if (jobStatus) return jobStatus.status_text || ACCOUNT_STATUS_TEXT[jobStatus.status] || '未提链'; return account.paypal_status_text || ACCOUNT_STATUS_TEXT[account.paypal_status] || '未提链' }
function accountStatusClass(account) { const status = accountStatus(account); return ({ running: 'border-blue-500/30 bg-blue-500/10 text-blue-300', unknown_outcome: 'border-amber-500/30 bg-amber-500/10 text-amber-200', success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300', failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300', no_promo: 'border-amber-500/30 bg-amber-500/10 text-amber-200', non_oaics: 'border-slate-500/30 bg-slate-500/10 text-slate-300', paid: 'border-violet-500/30 bg-violet-500/10 text-violet-300' })[status] || 'border-gray-700 bg-gray-900 text-gray-400' }
function accountStatusError(account) { return accountJobStatus(account)?.error || account.paypal_error || '' }
function accountSelectable(account) { return account.paypal_selectable !== false && paymentTargetSelectable(accountStatus(account)) }
function paymentAccountJobStatus(job, email) {
  const statuses = job?.account_statuses || {}
  const item = statuses[email] || statuses[String(email || '').toLowerCase()] || null
  return String(item?.status || '').trim().toLowerCase()
}
function paymentAccountJobStatusFromActive(activeJobs, email) {
  const target = String(email || '').trim().toLowerCase()
  const active = (activeJobs || []).find(item => String(item?.email || '').trim().toLowerCase() === target)
  if (!active) return ''
  const status = paymentAccountJobStatus(active.job, email)
  return status || (TERMINAL_STATUSES.has(String(active.status || '')) ? String(active.status || '') : 'running')
}
function paymentAccountStatusText(status, fromPaymentJob = false) {
  if (status === 'running') return '支付中'
  if (status === 'unknown_outcome' || status === 'unknown') return '结果待核对'
  if (status === 'paid') return '已支付'
  if (status === 'failed' || status === 'error') return '支付失败'
  if (status === 'pending') return '未提链'
  return '已提链'
}
function paymentAccountStatusClass(status) {
  if (status === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'unknown_outcome' || status === 'unknown') return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  if (status === 'paid') return 'border-violet-500/30 bg-violet-500/10 text-violet-300'
  if (status === 'failed' || status === 'error') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
}
function paymentAccountStatusMatchesFilter(status, filter) {
  const cleanStatus = String(status || '').trim().toLowerCase()
  const target = String(filter || 'all').trim().toLowerCase()
  if (!target || target === 'all') return true
  if (target === 'failed') return cleanStatus === 'failed' || cleanStatus === 'error'
  return cleanStatus === target
}
function filterPaymentLinkAccountsByStatus(items, statusFilter, statusResolver) {
  return (Array.isArray(items) ? items : []).filter((item) => {
    const status = statusResolver(item)
    return status !== 'paid' && paymentAccountStatusMatchesFilter(status, statusFilter)
  })
}
function protocolPaymentAccountJobStatus(item) { return paymentAccountJobStatus(protocolJob.value, item.email) || paymentAccountJobStatusFromActive(protocolAutoPayActiveJobs.value, item.email) }
function protocolPaymentAccountStatus(item) { return protocolPaymentAccountJobStatus(item) || item.paypalStatus }
function protocolPaymentAccountStatusText(item) { return paymentAccountStatusText(protocolPaymentAccountStatus(item), Boolean(protocolPaymentAccountJobStatus(item))) }
function protocolPaymentAccountStatusClass(item) { return paymentAccountStatusClass(protocolPaymentAccountStatus(item)) }
function pay153PaymentAccountJobStatus(item) { return paymentAccountJobStatus(pay153Job.value, item.email) || paymentAccountJobStatusFromActive(pay153AutoPayActiveJobs.value, item.email) }
function pay153PaymentAccountStatus(item) { return pay153PaymentAccountJobStatus(item) || item.paypalStatus }
function pay153PaymentAccountStatusText(item) { return paymentAccountStatusText(pay153PaymentAccountStatus(item), Boolean(pay153PaymentAccountJobStatus(item))) }
function pay153PaymentAccountStatusClass(item) { return paymentAccountStatusClass(pay153PaymentAccountStatus(item)) }
function toggleAccount(email) { const account = accounts.value.find(item => item.email === email); if (!account || !accountSelectable(account)) return; const next = new Set(selectedAccounts.value); next.has(email) ? next.delete(email) : next.add(email); selectedAccounts.value = next }
function selectAllFiltered() { selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).map(account => account.email)) }
function selectFirstFilteredAccounts() {
  const limit = Math.max(1, Math.floor(Number(accountQuickSelectCount.value || 0)))
  selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).slice(0, limit).map(account => account.email))
}
function clearSelectedAccounts() { selectedAccounts.value = new Set() }
function showMoreAccounts() { accountVisibleCount.value = Math.min(filteredAccounts.value.length, accountVisibleCount.value + 100) }
function showMoreAccessTokens() {
  accessTokenVisibleCount.value = Math.min(filteredAccessTokenPool.value.length, accessTokenVisibleCount.value + 100)
}
function showMoreLinks() {
  linkVisibleCount.value = Math.min(filteredLinks.value.length, linkVisibleCount.value + 100)
}
function showMoreProtocolLinks() {
  protocolLinkVisibleCount.value = Math.min(protocolLinkAccountOptions.value.length, protocolLinkVisibleCount.value + 100)
}
function showMorePay153Links() {
  pay153LinkVisibleCount.value = Math.min(pay153LinkAccountOptions.value.length, pay153LinkVisibleCount.value + 100)
}
function showMoreProtocolBaPool() {
  protocolBaVisibleCount.value = Math.min(filteredProtocolBaPool.value.length, protocolBaVisibleCount.value + 100)
}
function showMorePay153BaPool() {
  pay153BaVisibleCount.value = Math.min(filteredPay153BaPool.value.length, pay153BaVisibleCount.value + 100)
}
function showMoreProtocolPhones() {
  protocolPhoneVisibleCount.value = Math.min(protocolPhonePoolEntries.value.length, protocolPhoneVisibleCount.value + 100)
}
function showMorePay153Phones() {
  pay153PhoneVisibleCount.value = Math.min(pay153PhonePoolEntries.value.length, pay153PhoneVisibleCount.value + 100)
}
function showMoreRecentResults() {
  recentResultVisibleCount.value = Math.min(filteredRecentResultCount.value, recentResultVisibleCount.value + 100)
}
function toggleLink(id) { const next = new Set(selectedLinkIds.value); next.has(id) ? next.delete(id) : next.add(id); selectedLinkIds.value = next }
function rememberFailedEmails(result) { retryFailedEmailSet.value = new Set((result?.errors || []).map(item => String(item.email || '').trim()).filter(Boolean)) }

async function refreshAccounts() {
  try {
    const data = await api.getUsPaypalAccounts()
    accounts.value = Array.isArray(data.accounts) ? data.accounts : []
    const available = new Set(accounts.value.filter(accountSelectable).map(account => account.email))
    selectedAccounts.value = new Set(selectedEmails.value.filter(email => available.has(email)))
  } catch (error) {
    setStatus(`账号池读取失败：${cleanError(error)}`, true)
  }
}

async function refreshLinks() {
  try {
    const data = await api.getUsPaypalLinks()
    links.value = Array.isArray(data.links) ? data.links : []
    const available = new Set(links.value.map(link => link.id))
    selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => available.has(id)))
  } catch (error) {
    setStatus(`链接读取失败：${cleanError(error)}`, true)
  }
}

async function refreshPaymentLinks() {
  await Promise.all([refreshAccounts(), refreshLinks()])
}

async function reloadAll() {
  await refreshAccounts()
  await refreshLinks()
  if (!busy.value) setStatus('账号和链接已刷新。')
}

function cleanAccessToken(value) {
  const token = String(value || '').trim().replace(/^Bearer\s+/i, '').replace(/^[\\"']+|[\\"',;\s]+$/g, '').trim()
  return token
}
function parseAccessTokens(value) {
  const seen = new Set()
  const tokens = []
  for (const rawLine of String(value || '').split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    const candidates = /^Bearer\s+/i.test(line) || line.startsWith('{')
      ? [line]
      : line.split(/[\s,;]+/).filter(Boolean)
    for (const candidate of candidates) {
      let token = cleanAccessToken(candidate)
      if (token.startsWith('{') && token.includes('accessToken')) {
        try {
          const parsed = JSON.parse(token)
          token = cleanAccessToken(parsed?.accessToken || parsed?.access_token || '')
        } catch { /* keep raw token fallback */ }
      }
      if (token && !seen.has(token)) {
        seen.add(token)
        tokens.push(token)
      }
    }
  }
  return tokens
}

function accessTokenFingerprint(token) {
  const text = String(token || '')
  let hash = 0
  for (let index = 0; index < text.length; index += 1) hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0
  return `${Math.abs(hash).toString(36)}-${text.slice(-8)}`
}
function maskAccessToken(token) {
  const text = String(token || '')
  if (text.length <= 16) return text ? `${text.slice(0, 4)}…` : ''
  return `${text.slice(0, 8)}…${text.slice(-6)}`
}
function decodeAccessTokenEmail(token) {
  try {
    const part = String(token || '').split('.')[1] || ''
    if (!part) return ''
    const json = JSON.parse(decodeURIComponent(Array.from(atob(part.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - part.length % 4) % 4))).map(char => `%${char.charCodeAt(0).toString(16).padStart(2, '0')}`).join('')))
    const profile = json?.['https://api.openai.com/profile']
    return String(profile?.email || '').trim()
  } catch {
    return ''
  }
}
function makeAccessTokenPoolItem(token, index = 1) {
  const clean = cleanAccessToken(token)
  const id = accessTokenFingerprint(clean)
  return {
    id,
    token: clean,
    label: decodeAccessTokenEmail(clean) || `access-token-${String(index).padStart(3, '0')}`,
    masked: maskAccessToken(clean),
    status: 'pending',
    error: '',
    updatedAt: '',
  }
}
function saveAccessTokenPool() {
  storageWriter.queueJson(ACCESS_TOKEN_POOL_STORAGE_KEY, () => accessTokenPool.value)
}
function importAccessTokensToPool(options = {}) {
  const tokens = directAccessTokens.value
  if (!tokens.length) {
    if (!options.silent) setStatus('没有可导入的 access token。', true)
    return []
  }
  const existingIds = new Set(accessTokenPool.value.map(item => item.id))
  const imported = []
  const next = [...accessTokenPool.value]
  tokens.forEach((token, index) => {
    const item = makeAccessTokenPoolItem(token, accessTokenPool.value.length + index + 1)
    if (existingIds.has(item.id)) return
    existingIds.add(item.id)
    imported.push(item)
    next.push(item)
  })
  accessTokenPool.value = next
  if (options.select !== false && imported.length) selectedAccessTokenIds.value = new Set([...selectedAccessTokenIds.value, ...imported.map(item => item.id)])
  if (imported.length) form.value.accessTokens = ''
  saveAccessTokenPool()
  if (!options.silent) setStatus(imported.length ? `已导入 ${imported.length} 个 access token。` : '这些 access token 已在池中。')
  return imported
}
function accessTokenStatusText(status) { return ACCOUNT_STATUS_TEXT[String(status || 'pending').toLowerCase()] || '未提链' }
function accessTokenStatusClass(status) {
  return ({
    pending: 'border-gray-700 bg-gray-900 text-gray-400',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    no_promo: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    non_oaics: 'border-gray-600 bg-gray-800 text-gray-300',
    paid: 'border-purple-500/30 bg-purple-500/10 text-purple-300',
  })[String(status || 'pending').toLowerCase()] || 'border-gray-700 bg-gray-900 text-gray-400'
}
function toggleAccessToken(id) {
  const item = accessTokenPool.value.find(entry => entry.id === id)
  if (!item || item.status === 'paid') return
  const next = new Set(selectedAccessTokenIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedAccessTokenIds.value = next
}
function selectAllAccessTokenPool() {
  selectedAccessTokenIds.value = new Set(filteredAccessTokenPool.value.filter(item => item.status !== 'paid').map(item => item.id))
}
function clearSelectedAccessTokens() { selectedAccessTokenIds.value = new Set() }
function removeSelectedAccessTokens() {
  const selected = selectedAccessTokenIds.value
  accessTokenPool.value = accessTokenPool.value.filter(item => !selected.has(item.id))
  selectedAccessTokenIds.value = new Set()
  saveAccessTokenPool()
}
function resetSelectedAccessTokenStatus() {
  const selected = selectedAccessTokenIds.value
  accessTokenPool.value = accessTokenPool.value.map(item => selected.has(item.id) ? { ...item, status: 'pending', error: '', updatedAt: '' } : item)
  saveAccessTokenPool()
}
function setAccessTokenPoolStatus(ids, status, error = '') {
  const targets = new Set(ids)
  const updatedAt = new Date().toLocaleString()
  accessTokenPool.value = accessTokenPool.value.map(item => targets.has(item.id) ? { ...item, status, error: String(error || ''), updatedAt } : item)
  saveAccessTokenPool()
}
function syncAccessTokenPoolFromJob(job) {
  if (!job || !accessTokenPool.value.length) return
  const byLabel = new Map(accessTokenPool.value.map(item => [String(item.label || '').toLowerCase(), item]))
  const updates = new Map()
  const statuses = job.account_statuses && typeof job.account_statuses === 'object' ? job.account_statuses : {}
  for (const [label, statusItem] of Object.entries(statuses)) {
    const item = byLabel.get(String(label || '').toLowerCase())
    if (item && statusItem) updates.set(item.id, { status: String(statusItem.status || 'pending'), error: String(statusItem.error || '') })
  }
  for (const item of job.result?.successes || []) {
    const row = byLabel.get(String(item.email || '').toLowerCase())
    if (row) updates.set(row.id, { status: 'success', error: '' })
  }
  for (const item of job.result?.errors || []) {
    const row = byLabel.get(String(item.email || '').toLowerCase())
    if (row) updates.set(row.id, { status: 'failed', error: String(item.error || '') })
  }
  for (const item of job.result?.skipped || []) {
    const row = byLabel.get(String(item.email || '').toLowerCase())
    if (row && !updates.has(row.id)) updates.set(row.id, { status: 'failed', error: String(item.reason || '已跳过') })
  }
  if (!updates.size) return
  const updatedAt = new Date().toLocaleString()
  accessTokenPool.value = accessTokenPool.value.map(item => updates.has(item.id) ? { ...item, ...updates.get(item.id), updatedAt } : item)
  saveAccessTokenPool()
}
async function retryFailedAccessTokens() {
  const ids = failedAccessTokenItems.value.map(item => item.id)
  if (!ids.length) {
    setStatus('没有失败的 access token 可重试。', true)
    return
  }
  selectedAccessTokenIds.value = new Set(ids)
  await startWithEmails([], '重试提取')
}

function validateStart(emails = selectedEmails.value, accessTokenItems = selectedAccessTokenItems.value) {
  if (!accessTokenItems.length && !emails.length) {
    setStatus('请在账号池中选择至少一个账号，或粘贴 access token。', true)
    return false
  }
  form.value.concurrency = Math.max(1, Math.min(30, Number(form.value.concurrency || 1)))
  form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
  form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  form.value.region = String(form.value.region || 'US').trim().toUpperCase()
  form.value.promoRegion = String(form.value.promoRegion || 'JP').trim().toUpperCase()
  if (!form.value.proxies.trim()) {
    setStatus('请填写代理。', true)
    return false
  }
  return true
}

async function startWithEmails(emails, actionText = '提取') {
  if (!selectedAccessTokenItems.value.length && directAccessTokens.value.length) {
    importAccessTokensToPool({ silent: true, select: true })
  }
  const accessTokenItems = selectedAccessTokenItems.value
  const accountEmails = accessTokenItems.length ? [] : Array.from(new Set((emails || []).map(email => String(email || '').trim()).filter(Boolean)))
  if (!validateStart(accountEmails, accessTokenItems)) return
  const inputCount = accessTokenItems.length || accountEmails.length
  const inputSource = accessTokenItems.length ? 'access token' : '账号'
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  currentJob.value = null
  if (accessTokenItems.length) setAccessTokenPoolStatus(accessTokenItems.map(item => item.id), 'running')
  setStatus(`任务已提交，正在为 ${inputCount} 个${inputSource}${actionText} PayPal，目标国家 ${form.value.region}，优惠区 ${form.value.promoRegion}，并发 ${form.value.concurrency}，重试 ${form.value.maxAttempts}${form.value.onlyOaics ? '，仅 OAICS' : ''}。`)
  try {
    saveProxy({ silent: true })
    const payload = {
      proxies: form.value.proxies,
      accessTokenItems: accessTokenItems.map(item => ({ label: item.label, accessToken: item.token })),
      concurrency: form.value.concurrency,
      maxAttempts: form.value.maxAttempts,
      proxyPreflightAttempts: form.value.proxyPreflightAttempts,
      region: form.value.region,
      promoRegion: form.value.promoRegion,
      onlyOaics: form.value.onlyOaics,
      phonePoolReuseEnabled: phonePoolReuseEnabled.value,
    }
    const data = await api.startUsPaypalBatch({ ...payload, accountEmails })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    currentJob.value = { id: data.job_id, status: 'queued', total: inputCount, completed: 0, concurrency: form.value.concurrency, running_count: 0 }
    persistLinkJobState({ jobId: data.job_id, accountCount: inputCount, concurrency: form.value.concurrency, startedAt: Date.now() })
    await pollJob(data.job_id)
  } catch (error) {
    if (accessTokenItems.length) setAccessTokenPoolStatus(accessTokenItems.map(item => item.id), 'failed', cleanError(error))
    setStatus(cleanError(error), true)
    persistLinkJobState()
  } finally {
    busy.value = false
    canceling.value = false
  }
}

async function start() {
  await startWithEmails(selectedEmails.value, '提取')
}

async function retryFailedAccounts() {
  await refreshAccounts()
  const emails = retryFailedEmails.value
  if (!emails.length) {
    setStatus('上一轮没有可重试的失败账号。', true)
    return
  }
  selectedAccounts.value = new Set(emails)
  await startWithEmails(emails, '重试提取')
}

async function pollJob(jobId) {
  let lastSyncedCompleted = 0
  for (;;) {
    if (componentUnmounted) return
    if (!await paypalPolling.waitUntilAvailable()) return
    if (componentUnmounted) return
    const job = await api.getUsPaypalJob(jobId)
    if (componentUnmounted) return
    const completed = Number(job.completed || 0)
    const total = Number(job.total || 0)
    const shouldSyncIncremental = job.result && completed > lastSyncedCompleted && ['running', 'cancelling'].includes(job.status)
    currentJob.value = job
    logs.value = Array.isArray(job.logs) ? job.logs.slice(-200) : []
    currentResult.value = job.result || null
    syncAccessTokenPoolFromJob(job)
    persistLinkJobState({ jobId, accountCount: total, concurrency: job.concurrency || form.value.concurrency })
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (shouldSyncIncremental) {
      lastSyncedCompleted = completed
      await refreshLinks()
    }
    if (job.status === 'success') {
      rememberFailedEmails(job.result || {})
      setStatus('提链任务已完成，链接已写入管理表。')
      if ((job.result?.successes || []).length) playNotificationSound(PAYPAL_LINK_SUCCESS_SOUND_URL, form.value.notificationSoundEnabled)
      persistLinkJobState({ jobId })
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (job.status === 'cancelled') {
      currentResult.value = job.result || { batch: true, successes: [], errors: [], skipped: job.skipped || [] }
      rememberFailedEmails(currentResult.value)
      setStatus('提链任务已取消；已完成的链接已写入管理表。')
      persistLinkJobState({ jobId })
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (job.status === 'error' || job.status === 'failed') {
      rememberFailedEmails(job.result || {})
      persistLinkJobState({ jobId })
      await Promise.all([refreshAccounts(), refreshLinks()])
      throw new Error(job.error || '生成失败')
    }
    setStatus(total ? `任务执行中，已完成 ${completed}/${total}，已记录 ${logs.value.length} 条日志。` : `任务执行中，已记录 ${logs.value.length} 条日志。`)
    persistLinkJobState({ jobId, accountCount: total, concurrency: job.concurrency || form.value.concurrency })
    if (!await paypalPolling.wait(1000)) return
  }
}

async function cancelJob() {
  const jobId = currentJob.value?.id
  if (!jobId || canceling.value) return
  canceling.value = true
  try {
    await api.cancelUsPaypalJob(jobId)
    setStatus('已发送取消请求，正在停止未开始的账号。')
  } catch (error) {
    setStatus(`取消失败：${cleanError(error)}`, true)
    canceling.value = false
  }
}

function saveProxy(options = {}) {
  storageWriter.queueJson(FORM_STORAGE_KEY, () => form.value)
  if (!options.silent && !busy.value) setStatus('代理已保存。')
}

async function deletePaypalAccount(email) {
  const target = String(email || '').trim()
  if (!target || deletingPaypalAccounts.value.has(target)) return
  if (!window.confirm(`确认从 PayPal 账号池和仪表盘账号池中删除 ${target}？`)) return
  deletingPaypalAccounts.value = new Set([...deletingPaypalAccounts.value, target])
  try {
    const data = await api.deleteUsPaypalAccount(target)
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(item => item !== target))
    await Promise.all([refreshAccounts(), refreshLinks()])
    const paypal = data.paypal || {}
    setStatus(`已删除账号 ${target}：仪表盘账号 ${data.dashboard_account_deleted ? '已删除' : '未找到'}，认证 ${data.auth_session_deleted ? '已删除' : '未找到'}，PayPal 链接 ${paypal.links_deleted || 0} 条。`)
  } catch (error) {
    setStatus(`删除账号失败：${cleanError(error)}`, true)
  } finally {
    const next = new Set(deletingPaypalAccounts.value)
    next.delete(target)
    deletingPaypalAccounts.value = next
  }
}

async function deleteSelectedPaypalAccounts() {
  const emails = selectedEmails.value.map(email => String(email || '').trim()).filter(Boolean)
  if (!emails.length || deletingPaypalAccounts.value.size) return
  if (!window.confirm(`确认批量删除选中的 ${emails.length} 个账号？这些账号会同时从 PayPal 账号池和仪表盘账号池删除。`)) return
  deletingPaypalAccounts.value = new Set(emails)
  try {
    const data = await api.deleteUsPaypalAccounts(emails)
    const deleted = new Set((data.results || []).map(item => String(item.email || '').trim()).filter(Boolean))
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => !deleted.has(email)))
    await Promise.all([refreshAccounts(), refreshLinks()])
    const linkCount = (data.results || []).reduce((sum, item) => sum + Number(item.paypal?.links_deleted || 0), 0)
    setStatus(`已批量删除 ${data.deleted || deleted.size} 个账号，清理 PayPal 链接 ${linkCount} 条。`)
  } catch (error) {
    setStatus(`批量删除账号失败：${cleanError(error)}`, true)
  } finally {
    deletingPaypalAccounts.value = new Set()
  }
}

async function deleteSelectedLinks() {
  const ids = Array.from(selectedLinkIds.value)
  if (!ids.length) return
  try {
    const data = await api.deleteUsPaypalLinks(ids)
    links.value = Array.isArray(data.links) ? data.links : []
    selectedLinkIds.value = new Set()
    setStatus(`已删除 ${data.deleted || ids.length} 条链接。`)
  } catch (error) {
    setStatus(`删除失败：${cleanError(error)}`, true)
  }
}

async function clearLinks() {
  if (!links.value.length) return
  try {
    const data = await api.clearUsPaypalLinks()
    links.value = Array.isArray(data.links) ? data.links : []
    selectedLinkIds.value = new Set()
    setStatus(`已清空 ${data.deleted || 0} 条链接。`)
  } catch (error) {
    setStatus(`清空失败：${cleanError(error)}`, true)
  }
}

function exportLinks() {
  const blob = new Blob([JSON.stringify(filteredLinks.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `paypal-links-${Date.now()}.json`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
  setStatus('链接 JSON 已导出。')
}

async function copy(value) {
  const text = String(value || '')
  if (!text) return
  if (!navigator.clipboard?.writeText) { setStatus('当前环境不支持复制。', true); return }
  try {
    await navigator.clipboard.writeText(text)
    setStatus('已复制。')
  } catch (error) {
    setStatus(`复制失败：${cleanError(error)}`, true)
  }
}

function setProtocolStatus(message, error = false) { protocolStatusText.value = message; protocolStatusError.value = error }
function paymentJobSnapshot(jobId, job, logs, result, statusText, statusError, fallback = {}) {
  return compactPaymentJobSnapshot({ jobId, job, logs, result, statusText, statusError, fallback })
}
function queuePaymentJobSnapshot(storageKey, payload, { force = false } = {}) {
  if (componentUnmounted) {
    storageWriter.writeJsonNow(storageKey, payload)
    return true
  }
  force = force || TERMINAL_STATUSES.has(String(payload.job?.status || ''))
  if (!jobSnapshotWriteGate.shouldWrite(storageKey, { force })) return false
  if (force) storageWriter.writeJsonNow(storageKey, payload)
  else storageWriter.queueJson(storageKey, payload)
  return true
}
function persistProtocolJobState(fallback = {}, options = {}) {
  const jobId = protocolJob.value?.id || fallback.jobId
  const claimedPhonePoolKeys = fallback.claimedPhonePoolKeys || protocolClaimedPhonePoolKeysByJob.get(jobId) || []
  const payload = paymentJobSnapshot(jobId, protocolJob.value, protocolLogs.value, protocolResult.value, protocolStatusText.value, protocolStatusError.value, { ...fallback, claimedPhonePoolKeys })
  if (payload.jobId || payload.clientRequestId || payload.logs.length || payload.result) queuePaymentJobSnapshot(PROTOCOL_JOB_STORAGE_KEY, payload, options)
}
function restoreProtocolJobState(saved = {}) {
  if (!saved || typeof saved !== 'object' || !(saved.jobId || saved.clientRequestId || saved.job || saved.logs || saved.result)) return false
  protocolJob.value = saved.job || (saved.jobId ? { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 1), completed: 0, concurrency: Number(saved.concurrency || 1) } : null)
  protocolLogs.value = Array.isArray(saved.logs) ? saved.logs : []
  protocolResult.value = saved.result || null
  protocolRecoveryPaused.value = Boolean(saved.recoveryPaused)
  protocolRecoveryCheckpoint.value = saved.recoveryPaused || (saved.clientRequestId && saved.submitPayload) ? saved : null
  if (saved.jobId && Array.isArray(saved.claimedPhonePoolKeys)) protocolClaimedPhonePoolKeysByJob.set(saved.jobId, saved.claimedPhonePoolKeys)
  if (saved.statusText) setProtocolStatus(saved.statusText, Boolean(saved.statusError))
  return true
}
function resumeProtocolJobStateFromStorage(options = {}) {
  if (protocolBusy.value) return false
  const hasMemoryState = Boolean(protocolJob.value?.id || protocolLogs.value.length || protocolResult.value)
  let saved = {}
  if (!hasMemoryState || options.force) {
    try {
      saved = JSON.parse(sessionStorageFacade.getItem(PROTOCOL_JOB_STORAGE_KEY) || '{}')
    } catch {
      saved = {}
    }
    const savedJobId = String(saved.jobId || saved.job?.id || '').trim()
    if (savedJobId && protocolAutoPayActiveJobs.value.some(item => item.jobId === savedJobId)) {
      storageWriter.remove(PROTOCOL_JOB_STORAGE_KEY)
      return false
    }
    if (!restoreProtocolJobState(saved)) return false
  }
  const status = String(protocolJob.value?.status || '')
  const jobId = protocolJob.value?.id || saved.jobId
  if (options.preferredActiveTab === 'protocol' || !TERMINAL_STATUSES.has(status)) activeTab.value = 'protocol'
  if (!jobId && saved.clientRequestId && saved.submitPayload) {
    protocolRecoveryCheckpoint.value = saved
    if (saved.recoveryPaused) {
      protocolRecoveryPaused.value = true
      setProtocolStatus('协议支付提交确认已暂停；任务和手机号占用继续保留，可继续确认或在核对远端后人工解除。', true)
      return true
    }
    protocolBusy.value = true
    protocolCanceling.value = false
    protocolSubmissionCancelRequested = false
    setProtocolStatus('已恢复结果未知的协议支付提交，正在使用原幂等键确认后端任务。')
    void resumeUnknownProtocolPaymentStart(saved).catch((error) => {
      setProtocolStatus(`恢复协议支付提交失败：${cleanError(error)}`, true)
      persistProtocolJobState(saved, { force: true })
    }).finally(() => {
      if (!componentUnmounted) {
        protocolBusy.value = false
        protocolCanceling.value = false
      }
    })
    return true
  }
  if (!TERMINAL_STATUSES.has(status) && jobId) {
    protocolBusy.value = true
    protocolCanceling.value = false
    setProtocolStatus('已恢复协议支付任务，正在重新同步后端进度。')
    persistProtocolJobState(saved)
    void pollProtocolJob(jobId).catch((error) => {
      setProtocolStatus(`恢复协议支付失败：${cleanError(error)}`, true)
      persistProtocolJobState()
    }).finally(() => {
      if (!componentUnmounted) {
        protocolBusy.value = false
        protocolCanceling.value = false
      }
    })
  }
  return true
}
async function submitProtocolManualJob(submitPayload, checkpoint) {
  const submissionGeneration = protocolSubmissionGuard.start()
  const submissionActive = () => protocolSubmissionGuard.isActive(submissionGeneration)
  let attempt = Number(checkpoint?.retryAttempts || 0)
  for (;;) {
    if (!submissionActive() || protocolSubmissionCancelRequested || componentUnmounted) return null
    if (!await paypalPolling.waitUntilAvailable()) return null
    if (!submissionActive() || protocolSubmissionCancelRequested || componentUnmounted) return null
    try {
      const data = await api.startUsPaypalProtocolBatch(submitPayload)
      if (!data?.job_id) throw missingPaymentJobIdError('后端没有返回协议支付任务 ID')
      protocolRecoveryPaused.value = false
      return data
    } catch (error) {
      if (!isAmbiguousPaymentFailure(error)) throw error
      attempt += 1
      const paused = !submissionActive() || protocolSubmissionCancelRequested || attempt >= PAYMENT_RECOVERY_MAX_ATTEMPTS
      const nextCheckpoint = { ...checkpoint, unknownOutcome: true, recoveryPaused: paused, retryAttempts: attempt }
      protocolRecoveryCheckpoint.value = nextCheckpoint
      protocolRecoveryPaused.value = paused
      if (paused) {
        setProtocolStatus(`协议支付提交结果仍未知；已在 ${attempt} 次确认后暂停，任务和手机号占用保持不变。`, true)
        persistProtocolJobState(nextCheckpoint, { force: true })
        return null
      }
      const retryDelayMs = paymentRecoveryDelayMs(attempt)
      setProtocolStatus(`协议支付提交结果未知：${cleanError(error)}；任务和手机号占用已保留，约 ${Math.ceil(retryDelayMs / 1000)} 秒后使用原幂等键恢复。`, true)
      persistProtocolJobState(nextCheckpoint, { force: true })
      if (!await paypalPolling.wait(retryDelayMs)) return null
    }
  }
}
async function resumeUnknownProtocolPaymentStart(saved) {
  protocolRecoveryCheckpoint.value = saved
  const data = await submitProtocolManualJob(saved.submitPayload, saved)
  if (!data || componentUnmounted) return
  if (!data.job_id) throw missingPaymentJobIdError('后端没有返回协议支付任务 ID')
  const claimedPhonePoolKeys = Array.isArray(saved.claimedPhonePoolKeys) ? saved.claimedPhonePoolKeys : []
  if (claimedPhonePoolKeys.length) protocolClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
  protocolJob.value = { id: data.job_id, status: 'queued', total: Number(saved.accountCount || 1), completed: 0, concurrency: Number(saved.concurrency || 1) }
  protocolRecoveryCheckpoint.value = null
  protocolRecoveryPaused.value = false
  persistProtocolJobState({ ...saved, jobId: data.job_id, clientRequestId: '', submitPayload: null, unknownOutcome: false, recoveryPaused: false, retryAttempts: 0 }, { force: true })
  if (protocolSubmissionCancelRequested) {
    await cancelProtocolJob()
    await pollProtocolJob(data.job_id)
    return
  }
  await pollProtocolJob(data.job_id)
}
async function resumeProtocolRecovery() {
  const saved = protocolRecoveryCheckpoint.value
  if (!saved?.clientRequestId || !saved?.submitPayload || protocolBusy.value) return
  protocolSubmissionCancelRequested = false
  protocolRecoveryPaused.value = false
  protocolBusy.value = true
  protocolCanceling.value = false
  setProtocolStatus('正在继续确认未知的协议支付提交。')
  try {
    await resumeUnknownProtocolPaymentStart({ ...saved, recoveryPaused: false, retryAttempts: 0 })
  } catch (error) {
    setProtocolStatus(`继续确认协议支付失败：${cleanError(error)}`, true)
  } finally {
    protocolBusy.value = false
    protocolCanceling.value = false
  }
}
async function releaseUnknownPaymentOccupancy(kind, saved = {}, accountEmails = []) {
  const payloadEmails = Array.isArray(saved?.submitPayload?.accountEmails)
    ? saved.submitPayload.accountEmails
    : (Array.isArray(saved?.accountEmails) ? saved.accountEmails : accountEmails)
  return api.releaseUsPaypalPaymentOccupancy({
    kind,
    jobId: String(saved?.jobId || saved?.job?.id || '').trim(),
    clientRequestId: String(saved?.clientRequestId || '').trim(),
    accountEmails: Array.from(new Set((payloadEmails || []).map(item => String(item || '').trim()).filter(Boolean))),
  })
}
function resetReconciledBaPoolTargets(kind, result = {}, saved = {}) {
  const targetTokens = new Set((result.target_ba_tokens || result.targetBaTokens || []).map(item => displayBaToken(item).toUpperCase()).filter(Boolean))
  for (const link of saved?.submitPayload?.paypalLinks || []) {
    const token = displayBaToken(link).toUpperCase()
    if (token) targetTokens.add(token)
  }
  if (!targetTokens.size) return
  const poolRef = kind === 'paypal_153_payment' ? pay153BaPool : protocolBaPool
  poolRef.value = poolRef.value.map((item) => (
    targetTokens.has(displayBaToken(item.baToken || item.paypalLink).toUpperCase())
      ? { ...item, status: 'pending', error: '', updatedAt: new Date().toLocaleString() }
      : item
  ))
  saveBaPool(kind === 'paypal_153_payment' ? 'pay153' : 'protocol')
}
async function discardProtocolRecovery() {
  if (protocolBusy.value) {
    setProtocolStatus('提交确认仍在停止中，请稍候再解除占用。', true)
    return
  }
  const saved = protocolRecoveryCheckpoint.value
  if (!saved || !window.confirm('仅当你已核对远端且确认没有运行中的协议支付任务时解除手机号占用，是否继续？')) return
  let released
  try {
    released = await releaseUnknownPaymentOccupancy('paypal_protocol_payment', saved)
  } catch (error) {
    setProtocolStatus(`后端解除未知协议支付占用失败：${cleanError(error)}`, true)
    return
  }
  releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', saved.claimedPhonePoolKeys || [], protocolForm.value.phonePool)
  resetReconciledBaPoolTargets('paypal_protocol_payment', released, saved)
  protocolRecoveryCheckpoint.value = null
  protocolRecoveryPaused.value = false
  protocolSubmissionCancelRequested = false
  protocolJob.value = null
  storageWriter.remove(PROTOCOL_JOB_STORAGE_KEY)
  await refreshAccounts()
  setProtocolStatus('已解除经人工确认的未知协议支付占用。')
}
function saveProtocolForm(options = {}) {
  storageWriter.queueJson(PROTOCOL_FORM_STORAGE_KEY, () => protocolForm.value)
  if (!options.silent && !protocolBusy.value) setProtocolStatus('协议支付输入已保存。')
}
function applySelectedProtocolAccount() {
  const selected = resolveSelectedPayPalLinkAccount(accounts.value, links.value, selectedProtocolAccountEmail.value, { timeFilter: protocolLinkTimeFilter.value })
  if (!selected) return
  if (!protocolLinkSelectableEmails.value.has(selected.email)) {
    setProtocolStatus('该账号已支付，不能重复提交。', true)
    selectedProtocolAccountEmail.value = ''
    return
  }
  protocolForm.value.paypalLink = selected.paypalLink
  protocolForm.value.accountEmail = selected.email
  if (PROTOCOL_COUNTRIES.has(selected.country)) protocolForm.value.country = selected.country
  setProtocolStatus(`已填入 ${selected.country || '-'} · ${selected.email} 的 BA 链。`)
}
function toggleProtocolAccount(email) {
  const target = String(email || '').trim()
  if (!target) return
  if (!protocolLinkSelectableEmails.value.has(target)) return
  const next = new Set(selectedProtocolAccountEmails.value)
  next.has(target) ? next.delete(target) : next.add(target)
  selectedProtocolAccountEmails.value = next
  if (next.size === 1) {
    selectedProtocolAccountEmail.value = Array.from(next)[0]
    applySelectedProtocolAccount()
  }
}
function selectAllProtocolAccounts() {
  selectedProtocolAccountEmails.value = new Set(protocolLinkAccountOptions.value.filter(item => paymentLinkAccountSelectable(item, protocolPaymentAccountStatus)).map(item => item.email))
  if (selectedProtocolAccountEmails.value.size === 1) {
    selectedProtocolAccountEmail.value = protocolSelectedEmails.value[0]
    applySelectedProtocolAccount()
  }
}
function selectFirstProtocolAccounts() {
  const limit = Math.max(1, Math.floor(Number(protocolQuickSelectCount.value || 0)))
  selectedProtocolAccountEmails.value = new Set(protocolLinkAccountOptions.value.filter(item => paymentLinkAccountSelectable(item, protocolPaymentAccountStatus)).slice(0, limit).map(item => item.email))
  if (selectedProtocolAccountEmails.value.size === 1) {
    selectedProtocolAccountEmail.value = protocolSelectedEmails.value[0]
    applySelectedProtocolAccount()
  }
}
function toggleProtocolLinkSortOrder() {
  protocolLinkSortOrder.value = protocolLinkSortOrder.value === 'desc' ? 'asc' : 'desc'
}
function clearSelectedProtocolAccounts() {
  selectedProtocolAccountEmails.value = new Set()
}
function togglePhonePoolReuse() {
  phonePoolReuseEnabled.value = !phonePoolReuseEnabled.value
}

function normalizePaypalAutoPayJob(raw) {
  if (!raw || typeof raw !== 'object') return null
  const email = String(raw.email || '').trim()
  if (!email) return null
  const jobId = String(raw.jobId || raw.job_id || '').trim()
  return {
    email,
    key: String(raw.key || '').trim(),
    jobId,
    clientRequestId: String(raw.clientRequestId || raw.client_request_id || '').trim(),
    submitPayload: raw.submitPayload && typeof raw.submitPayload === 'object' ? { ...raw.submitPayload } : null,
    status: String(raw.status || (jobId ? 'running' : 'unknown')).trim().toLowerCase(),
    claimedPhonePoolKeys: Array.from(new Set((Array.isArray(raw.claimedPhonePoolKeys) ? raw.claimedPhonePoolKeys : []).map(item => String(item || '').trim()).filter(Boolean))),
    error: String(raw.error || '').trim(),
  }
}

function createPaypalClientRequestId(kind, email) {
  const nonce = globalThis.crypto?.randomUUID?.() || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
  const account = String(email || '').trim().toLowerCase().replace(/[^a-z0-9._-]+/g, '-').slice(0, 48)
  return `${String(kind || 'paypal')}:${account}:${nonce}`.slice(0, 128)
}

function paypalAutoPayJobsForStorage(activeRef) {
  return activeRef.value.map(normalizePaypalAutoPayJob).filter(Boolean)
}

function persistPaypalAutoPayState({ force = false } = {}) {
  const payload = {
    protocol: paypalAutoPayJobsForStorage(protocolAutoPayActiveJobs),
    pay153: paypalAutoPayJobsForStorage(pay153AutoPayActiveJobs),
    savedAt: Date.now(),
  }
  if (force || componentUnmounted) storageWriter.writeJsonNow(PAYPAL_AUTO_PAY_STATE_STORAGE_KEY, payload)
  else storageWriter.queueJson(PAYPAL_AUTO_PAY_STATE_STORAGE_KEY, payload)
}

function autoPayCandidateStillRunnable(items, activeJobs, email, { statusResolver = item => item?.paypalStatus, manualEmails = [] } = {}) {
  const target = String(email || '').trim().toLowerCase()
  if (!target) return false
  if ((activeJobs || []).some(item => String(item?.email || '').trim().toLowerCase() === target)) return false
  if ((manualEmails || []).some(item => String(item || '').trim().toLowerCase() === target)) return false
  return (items || []).some(item => String(item?.email || '').trim().toLowerCase() === target && item.paypalStatus === 'success' && statusResolver(item) === 'success')
}

function claimedPhonePoolKeysForAutoJob(activeRef, jobId, email) {
  const targetJobId = String(jobId || '').trim()
  const targetEmail = String(email || '').trim().toLowerCase()
  const active = activeRef.value.find(item => (
    (targetJobId && String(item?.jobId || '').trim() === targetJobId)
    || (targetEmail && String(item?.email || '').trim().toLowerCase() === targetEmail)
  ))
  return Array.isArray(active?.claimedPhonePoolKeys) ? active.claimedPhonePoolKeys : []
}

function restorePaypalAutoPayState() {
  let saved = {}
  try {
    saved = JSON.parse(sessionStorageFacade.getItem(PAYPAL_AUTO_PAY_STATE_STORAGE_KEY) || '{}')
  } catch {
    saved = {}
  }
  protocolAutoPayActiveJobs.value = (Array.isArray(saved.protocol) ? saved.protocol : []).map(normalizePaypalAutoPayJob).filter(Boolean)
  pay153AutoPayActiveJobs.value = (Array.isArray(saved.pay153) ? saved.pay153 : []).map(normalizePaypalAutoPayJob).filter(Boolean)

  const claimedStatuses = { ...phonePoolStatusMap.value }
  for (const item of protocolAutoPayActiveJobs.value) {
    for (const key of item.claimedPhonePoolKeys) claimedStatuses[key] = 'claimed'
    if (!item.jobId) {
      if (item.status !== 'recovery_paused' && item.clientRequestId && item.submitPayload) void reconcileProtocolAutoPayStart(item.email, item.clientRequestId, { delay: false })
      continue
    }
    protocolClaimedPhonePoolKeysByJob.set(item.jobId, item.claimedPhonePoolKeys)
    if (item.status !== 'unknown_outcome') void pollProtocolAutoPayJob(item.jobId, item.email)
  }
  for (const item of pay153AutoPayActiveJobs.value) {
    for (const key of item.claimedPhonePoolKeys) claimedStatuses[key] = 'claimed'
    if (!item.jobId) {
      if (item.status !== 'recovery_paused' && item.clientRequestId && item.submitPayload) void reconcilePay153AutoPayStart(item.email, item.clientRequestId, { delay: false })
      continue
    }
    pay153ClaimedPhonePoolKeysByJob.set(item.jobId, item.claimedPhonePoolKeys)
    if (item.status !== 'unknown_outcome') void pollPay153AutoPayJob(item.jobId, item.email)
  }
  phonePoolStatusMap.value = claimedStatuses

  const protocolCount = protocolAutoPayActiveJobs.value.length
  const pay153Count = pay153AutoPayActiveJobs.value.length
  if (protocolCount) protocolAutoPayStatusText.value = `已恢复 ${protocolCount} 个协议自动支付任务，正在继续查询远端状态。`
  if (pay153Count) pay153AutoPayStatusText.value = `已恢复 ${pay153Count} 个153自动支付任务，正在继续查询远端状态。`
  if (protocolCount || pay153Count) persistPaypalAutoPayState()
}

async function clearLegacyUnresolvedAutoPayJobs(kind) {
  const isPay153 = kind === 'pay153'
  const activeRef = isPay153 ? pay153AutoPayActiveJobs : protocolAutoPayActiveJobs
  const formRef = isPay153 ? pay153Form : protocolForm
  const unresolved = activeRef.value.filter(isUnresolvedAutoPayItem)
  if (!unresolved.length) return
  if (!window.confirm(`仅当你已确认远端没有运行这些旧任务时解除 ${unresolved.length} 个占用，是否继续？`)) return
  const paymentKind = isPay153 ? 'paypal_153_payment' : 'paypal_protocol_payment'
  try {
    for (const item of unresolved) {
      await releaseUnknownPaymentOccupancy(paymentKind, item, [item.email])
    }
  } catch (error) {
    const message = `后端解除旧未知任务占用失败：${cleanError(error)}`
    if (isPay153) pay153AutoPayStatusText.value = message
    else protocolAutoPayStatusText.value = message
    return
  }
  for (const item of unresolved) {
    releaseClaimedPhonePoolEntriesAfterJob({}, kind, item.claimedPhonePoolKeys || [], formRef.value.phonePool)
  }
  const unresolvedEmails = new Set(unresolved.map(item => item.email))
  activeRef.value = activeRef.value.filter(item => !unresolvedEmails.has(item.email))
  persistPaypalAutoPayState({ force: true })
  if (isPay153) pay153AutoPayStatusText.value = `已解除 ${unresolved.length} 个经人工确认的旧未知任务占用。`
  else protocolAutoPayStatusText.value = `已解除 ${unresolved.length} 个经人工确认的旧未知任务占用。`
}

function stopProtocolAutoPay(message = '协议自动支付已停止。') {
  protocolAutoPayActive.value = false
  protocolAutoPayScheduleGeneration += 1
  protocolAutoPayActiveJobs.value = protocolAutoPayActiveJobs.value.map(item => (
    !item.jobId && item.clientRequestId && item.submitPayload ? { ...item, status: 'recovery_paused' } : item
  ))
  persistPaypalAutoPayState({ force: true })
  protocolAutoPayStatusText.value = message
}
function stopPay153AutoPay(message = '153自动支付已停止。') {
  pay153AutoPayActive.value = false
  pay153AutoPayScheduleGeneration += 1
  pay153AutoPayActiveJobs.value = pay153AutoPayActiveJobs.value.map(item => (
    !item.jobId && item.clientRequestId && item.submitPayload ? { ...item, status: 'recovery_paused' } : item
  ))
  persistPaypalAutoPayState({ force: true })
  pay153AutoPayStatusText.value = message
}
async function scheduleProtocolAutoPayScan(generation = protocolAutoPayScheduleGeneration) {
  if (!protocolAutoPayActive.value || componentUnmounted || generation !== protocolAutoPayScheduleGeneration) return
  if (!await paypalPolling.wait(AUTO_PAYMENT_POLL_MS)) return
  if (!protocolAutoPayActive.value || componentUnmounted || generation !== protocolAutoPayScheduleGeneration) return
  if (!await paypalPolling.waitUntilAvailable()) return
  if (!protocolAutoPayActive.value || componentUnmounted || generation !== protocolAutoPayScheduleGeneration) return
  try {
    await scanProtocolAutoPayLinks(generation)
  } catch (error) {
    protocolAutoPayStatusText.value = `协议自动支付扫描失败：${cleanError(error)}；稍后自动重试。`
  }
  if (protocolAutoPayActive.value && !componentUnmounted && generation === protocolAutoPayScheduleGeneration) {
    void scheduleProtocolAutoPayScan(generation)
  }
}
async function schedulePay153AutoPayScan(generation = pay153AutoPayScheduleGeneration) {
  if (!pay153AutoPayActive.value || componentUnmounted || generation !== pay153AutoPayScheduleGeneration) return
  if (!await paypalPolling.wait(AUTO_PAYMENT_POLL_MS)) return
  if (!pay153AutoPayActive.value || componentUnmounted || generation !== pay153AutoPayScheduleGeneration) return
  if (!await paypalPolling.waitUntilAvailable()) return
  if (!pay153AutoPayActive.value || componentUnmounted || generation !== pay153AutoPayScheduleGeneration) return
  try {
    await scanPay153AutoPayLinks(generation)
  } catch (error) {
    pay153AutoPayStatusText.value = `153自动支付扫描失败：${cleanError(error)}；稍后自动重试。`
  }
  if (pay153AutoPayActive.value && !componentUnmounted && generation === pay153AutoPayScheduleGeneration) {
    void schedulePay153AutoPayScan(generation)
  }
}
async function toggleProtocolAutoPay() {
  if (protocolAutoPayActive.value) {
    stopProtocolAutoPay('协议自动支付已手动停止。')
    return
  }
  protocolAutoPayActive.value = true
  protocolAutoPayQueue.value = []
  protocolAutoPaySeenKeys.value = new Set()
  protocolAutoPayLastNewAt.value = Date.now()
  protocolAutoPayStatusText.value = '协议自动支付已开启：每1分钟拉取新链接，30分钟无新链接后结束。'
  const generation = ++protocolAutoPayScheduleGeneration
  try {
    await scanProtocolAutoPayLinks(generation)
  } catch (error) {
    protocolAutoPayStatusText.value = `协议自动支付扫描失败：${cleanError(error)}；稍后自动重试。`
  }
  if (protocolAutoPayActive.value && !componentUnmounted && generation === protocolAutoPayScheduleGeneration) {
    void scheduleProtocolAutoPayScan(generation)
  }
}
async function togglePay153AutoPay() {
  if (pay153AutoPayActive.value) {
    stopPay153AutoPay('153自动支付已手动停止。')
    return
  }
  if (pay153Canceling.value) {
    setPay153Status('153取消或清理仍在进行，暂不能启动自动支付。', true)
    return
  }
  if (pay153RecoveryPaused.value) {
    setPay153Status('已有结果未知的153任务；请继续确认或人工核对后解除占用。', true)
    return
  }
  pay153AutoPayActive.value = true
  pay153AutoPayQueue.value = []
  pay153AutoPaySeenKeys.value = new Set()
  pay153AutoPayLastNewAt.value = Date.now()
  pay153AutoPayStatusText.value = '153自动支付已开启：每1分钟拉取新链接，30分钟无新链接后结束。'
  const generation = ++pay153AutoPayScheduleGeneration
  try {
    await scanPay153AutoPayLinks(generation)
  } catch (error) {
    pay153AutoPayStatusText.value = `153自动支付扫描失败：${cleanError(error)}；稍后自动重试。`
  }
  if (pay153AutoPayActive.value && !componentUnmounted && generation === pay153AutoPayScheduleGeneration) {
    void schedulePay153AutoPayScan(generation)
  }
}
async function scanProtocolAutoPayLinks(generation = protocolAutoPayScheduleGeneration) {
  if (!protocolAutoPayActive.value || componentUnmounted || generation !== protocolAutoPayScheduleGeneration) return
  await refreshPaymentLinks()
  if (!protocolAutoPayActive.value || componentUnmounted || generation !== protocolAutoPayScheduleGeneration) return
  const seen = new Set(protocolAutoPaySeenKeys.value)
  const queued = new Set(protocolAutoPayQueue.value.map(item => item.email))
  const manualEmails = protocolBusy.value ? [...protocolSelectedEmails.value, protocolForm.value.accountEmail].filter(Boolean) : []
  const activeEmails = new Set([...protocolAutoPayActiveJobs.value.map(item => item.email), ...manualEmails])
  const activeKeys = new Set(protocolAutoPayActiveJobs.value.map(item => item.key).filter(Boolean))
  const additions = []
  for (const item of protocolLinkAccountOptions.value) {
    if (!item?.email || item.paypalStatus !== 'success' || activeEmails.has(item.email) || protocolPaymentAccountStatus(item) !== 'success') continue
    const key = autoPayLinkKey(item)
    if (!key || seen.has(key) || activeKeys.has(key) || queued.has(item.email)) continue
    seen.add(key)
    queued.add(item.email)
    additions.push({ email: item.email, key })
  }
  protocolAutoPaySeenKeys.value = seen
  if (additions.length) {
    protocolAutoPayQueue.value = [...protocolAutoPayQueue.value, ...additions]
    protocolAutoPayLastNewAt.value = Date.now()
    protocolAutoPayStatusText.value = `协议自动支付发现 ${additions.length} 个新链接，队列 ${protocolAutoPayQueue.value.length} 个。`
    void drainProtocolAutoPayQueue()
    return
  }
  void drainProtocolAutoPayQueue()
  const idleMs = Date.now() - Number(protocolAutoPayLastNewAt.value || Date.now())
  protocolAutoPayStatusText.value = `协议自动支付等待新链接中，队列 ${protocolAutoPayQueue.value.length} 个，已空闲 ${Math.floor(idleMs / 60000)} 分钟。`
  if (idleMs >= AUTO_PAYMENT_IDLE_LIMIT_MS && !protocolAutoPayQueue.value.length && !protocolAutoPayActiveJobs.value.length) stopProtocolAutoPay('协议自动支付已结束：30分钟没有新链接。')
}
async function scanPay153AutoPayLinks(generation = pay153AutoPayScheduleGeneration) {
  if (!pay153AutoPayActive.value || componentUnmounted || generation !== pay153AutoPayScheduleGeneration) return
  await refreshPaymentLinks()
  if (!pay153AutoPayActive.value || componentUnmounted || generation !== pay153AutoPayScheduleGeneration) return
  const seen = new Set(pay153AutoPaySeenKeys.value)
  const queued = new Set(pay153AutoPayQueue.value.map(item => item.email))
  const manualEmails = pay153Busy.value ? pay153SelectedEmails.value : []
  const activeEmails = new Set([...pay153AutoPayActiveJobs.value.map(item => item.email), ...manualEmails])
  const activeKeys = new Set(pay153AutoPayActiveJobs.value.map(item => item.key).filter(Boolean))
  const additions = []
  for (const item of pay153LinkAccountOptions.value) {
    if (!item?.email || item.paypalStatus !== 'success' || activeEmails.has(item.email) || pay153PaymentAccountStatus(item) !== 'success') continue
    const key = autoPayLinkKey(item)
    if (!key || seen.has(key) || activeKeys.has(key) || queued.has(item.email)) continue
    seen.add(key)
    queued.add(item.email)
    additions.push({ email: item.email, key })
  }
  pay153AutoPaySeenKeys.value = seen
  if (additions.length) {
    pay153AutoPayQueue.value = [...pay153AutoPayQueue.value, ...additions]
    pay153AutoPayLastNewAt.value = Date.now()
    pay153AutoPayStatusText.value = `153自动支付发现 ${additions.length} 个新链接，队列 ${pay153AutoPayQueue.value.length} 个。`
    void drainPay153AutoPayQueue()
    return
  }
  void drainPay153AutoPayQueue()
  const idleMs = Date.now() - Number(pay153AutoPayLastNewAt.value || Date.now())
  pay153AutoPayStatusText.value = `153自动支付等待新链接中，队列 ${pay153AutoPayQueue.value.length} 个，已空闲 ${Math.floor(idleMs / 60000)} 分钟。`
  if (idleMs >= AUTO_PAYMENT_IDLE_LIMIT_MS && !pay153AutoPayQueue.value.length && !pay153AutoPayActiveJobs.value.length) stopPay153AutoPay('153自动支付已结束：30分钟没有新链接。')
}
function mergePaymentResult(current, next) {
  const base = current && typeof current === 'object' ? current : { batch: true, successes: [], errors: [], skipped: [] }
  const incoming = next && typeof next === 'object' ? next : {}
  return {
    batch: true,
    successes: [...(base.successes || []), ...(incoming.successes || [])],
    errors: [...(base.errors || []), ...(incoming.errors || [])],
    skipped: [...(base.skipped || []), ...(incoming.skipped || [])],
  }
}
function appendAutoPayLogs(logsRef, offsets, jobId, email, logsList) {
  const rows = Array.isArray(logsList) ? logsList : []
  const offset = Number(offsets.get(jobId) || 0)
  const additions = rows.slice(offset).map(line => `[自动 ${email}] ${line}`)
  if (additions.length) logsRef.value = [...logsRef.value, ...additions].slice(-200)
  offsets.set(jobId, rows.length)
}
function updateAutoPayActiveJob(activeRef, email, patch) {
  activeRef.value = activeRef.value.map(item => item.email === email ? { ...item, ...patch } : item)
}
function removeAutoPayActiveJob(activeRef, email) {
  activeRef.value = activeRef.value.filter(item => item.email !== email)
}
function updateAutoPayActiveSubmission(activeRef, clientRequestId, patch) {
  activeRef.value = activeRef.value.map(item => item.clientRequestId === clientRequestId ? { ...item, ...patch } : item)
}
function removeAutoPayActiveSubmission(activeRef, clientRequestId) {
  activeRef.value = activeRef.value.filter(item => item.clientRequestId !== clientRequestId)
}
function missingPaymentJobIdError(message) {
  const error = new Error(message)
  error.code = 'payment_job_acknowledgement_missing'
  return error
}
async function reconcileProtocolAutoPayStart(email, clientRequestId, { delay = true } = {}) {
  if (!clientRequestId || protocolAutoPayStartReconciliations.has(clientRequestId)) return
  protocolAutoPayStartReconciliations.add(clientRequestId)
  let attempt = delay ? 1 : 0
  try {
    if (delay) {
      if (!await paypalPolling.waitUntilAvailable() || componentUnmounted) return
      if (!await paypalPolling.wait(paymentRecoveryDelayMs(attempt)) || componentUnmounted) return
    }
    for (;;) {
      if (componentUnmounted) return
      const active = protocolAutoPayActiveJobs.value.find(item => item.clientRequestId === clientRequestId)
      if (!active || active.jobId || !active.submitPayload) return
      if (active.status === 'recovery_paused') return
      if (!await paypalPolling.waitUntilAvailable() || componentUnmounted) return
      try {
        const data = await api.startUsPaypalProtocolBatch(active.submitPayload)
        if (!data.job_id) throw missingPaymentJobIdError('后端没有返回协议支付任务 ID')
        const current = protocolAutoPayActiveJobs.value.find(item => item.clientRequestId === clientRequestId)
        if (!current || current.jobId) return
        protocolClaimedPhonePoolKeysByJob.set(data.job_id, current.claimedPhonePoolKeys || [])
        updateAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId, { jobId: data.job_id, status: 'running', error: '', submitPayload: null })
        persistPaypalAutoPayState({ force: true })
        void pollProtocolAutoPayJob(data.job_id, email)
        return
      } catch (error) {
        const current = protocolAutoPayActiveJobs.value.find(item => item.clientRequestId === clientRequestId)
        if (!current) return
        if (!isAmbiguousPaymentFailure(error)) {
          if (Number(error?.status || 0) === 409) {
            updateAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId, { status: 'unknown', error: cleanError(error) })
            protocolAutoPayStatusText.value = `协议自动支付幂等键冲突：${email}；任务占用已保留，请核对后端状态。`
            persistPaypalAutoPayState({ force: true })
            return
          }
          releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', current.claimedPhonePoolKeys || [], protocolForm.value.phonePool)
          removeAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId)
          protocolResult.value = mergePaymentResult(protocolResult.value, { errors: [{ email, error: cleanError(error) }] })
          protocolAutoPayStatusText.value = `协议自动支付启动失败：${email} ${cleanError(error)}`
          persistPaypalAutoPayState({ force: true })
          void drainProtocolAutoPayQueue()
          return
        }
        attempt += 1
        if (attempt >= PAYMENT_RECOVERY_MAX_ATTEMPTS) {
          updateAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId, { status: 'recovery_paused', error: cleanError(error), retryAttempts: attempt })
          protocolAutoPayStatusText.value = `协议自动支付提交结果仍未知：${email}；已在 ${attempt} 次确认后暂停并保留占用。`
          persistPaypalAutoPayState({ force: true })
          return
        }
        const retryDelayMs = paymentRecoveryDelayMs(attempt)
        updateAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId, { status: 'unknown', error: cleanError(error) })
        protocolAutoPayStatusText.value = `协议自动支付提交结果仍未知：${email}；任务和手机号占用已保留，约 ${Math.ceil(retryDelayMs / 1000)} 秒后继续幂等恢复。`
        persistPaypalAutoPayState({ force: true })
        if (!await paypalPolling.wait(retryDelayMs)) return
      }
    }
  } finally {
    protocolAutoPayStartReconciliations.delete(clientRequestId)
  }
}
async function reconcilePay153AutoPayStart(email, clientRequestId, { delay = true } = {}) {
  if (!clientRequestId || pay153AutoPayStartReconciliations.has(clientRequestId)) return
  pay153AutoPayStartReconciliations.add(clientRequestId)
  let attempt = delay ? 1 : 0
  try {
    if (delay) {
      if (!await paypalPolling.waitUntilAvailable() || componentUnmounted) return
      if (!await paypalPolling.wait(paymentRecoveryDelayMs(attempt)) || componentUnmounted) return
    }
    for (;;) {
      if (componentUnmounted) return
      const active = pay153AutoPayActiveJobs.value.find(item => item.clientRequestId === clientRequestId)
      if (!active || active.jobId || !active.submitPayload) return
      if (active.status === 'recovery_paused') return
      if (!await paypalPolling.waitUntilAvailable() || componentUnmounted) return
      try {
        const data = await api.startUsPaypal153Batch(active.submitPayload)
        if (!data.job_id) throw missingPaymentJobIdError('后端没有返回153支付任务 ID')
        const current = pay153AutoPayActiveJobs.value.find(item => item.clientRequestId === clientRequestId)
        if (!current || current.jobId) return
        pay153ClaimedPhonePoolKeysByJob.set(data.job_id, current.claimedPhonePoolKeys || [])
        updateAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId, { jobId: data.job_id, status: 'running', error: '', submitPayload: null })
        persistPaypalAutoPayState({ force: true })
        void pollPay153AutoPayJob(data.job_id, email)
        return
      } catch (error) {
        const current = pay153AutoPayActiveJobs.value.find(item => item.clientRequestId === clientRequestId)
        if (!current) return
        if (!isAmbiguousPaymentFailure(error)) {
          if (Number(error?.status || 0) === 409) {
            updateAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId, { status: 'unknown', error: cleanError(error) })
            pay153AutoPayStatusText.value = `153自动支付幂等键冲突：${email}；任务占用已保留，请核对后端状态。`
            persistPaypalAutoPayState({ force: true })
            return
          }
          releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', current.claimedPhonePoolKeys || [], pay153Form.value.phonePool)
          removeAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId)
          pay153Result.value = mergePaymentResult(pay153Result.value, { errors: [{ email, error: cleanError(error) }] })
          pay153AutoPayStatusText.value = `153自动支付启动失败：${email} ${cleanError(error)}`
          persistPaypalAutoPayState({ force: true })
          void drainPay153AutoPayQueue()
          return
        }
        attempt += 1
        if (attempt >= PAYMENT_RECOVERY_MAX_ATTEMPTS) {
          updateAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId, { status: 'recovery_paused', error: cleanError(error), retryAttempts: attempt })
          pay153AutoPayStatusText.value = `153自动支付提交结果仍未知：${email}；已在 ${attempt} 次确认后暂停并保留占用。`
          persistPaypalAutoPayState({ force: true })
          return
        }
        const retryDelayMs = paymentRecoveryDelayMs(attempt)
        updateAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId, { status: 'unknown', error: cleanError(error) })
        pay153AutoPayStatusText.value = `153自动支付提交结果仍未知：${email}；任务和手机号占用已保留，约 ${Math.ceil(retryDelayMs / 1000)} 秒后继续幂等恢复。`
        persistPaypalAutoPayState({ force: true })
        if (!await paypalPolling.wait(retryDelayMs)) return
      }
    }
  } finally {
    pay153AutoPayStartReconciliations.delete(clientRequestId)
  }
}
function protocolManualOccupiedSlots() {
  if (!protocolBusy.value) return 0
  return Math.max(1, Number(protocolJob.value?.running_count || 1))
}
function pay153ManualOccupiedSlots() {
  if (!pay153Busy.value) return 0
  return Math.max(1, Number(pay153Job.value?.running_count || 1))
}
async function launchProtocolAutoPayItem(item) {
  const email = String(item?.email || '').trim()
  if (!email || !protocolAutoPayActive.value) return
  if (!autoPayCandidateStillRunnable(protocolLinkAccountOptions.value, protocolAutoPayActiveJobs.value, email, {
    statusResolver: protocolPaymentAccountStatus,
    manualEmails: protocolBusy.value ? [...protocolSelectedEmails.value, protocolForm.value.accountEmail].filter(Boolean) : [],
  })) return
  if (!validateProtocolPayment([email])) return
  const claimedPhonePoolEntries = protocolForm.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(protocolForm.value.phonePool, 1, 'protocol') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(entry => entry.key).filter(Boolean)
  const clientRequestId = createPaypalClientRequestId('protocol', email)
  saveProtocolForm({ silent: true })
  const submitPayload = {
    paypalLink: protocolForm.value.paypalLink,
    phone: protocolForm.value.phone,
    phonePool: protocolForm.value.smsProvider === 'sms_record' ? (phonePoolReuseEnabled.value ? phonePoolPayloadForSubmission(protocolForm.value.phonePool, 'protocol') : formatPhonePoolEntries(claimedPhonePoolEntries)) : protocolForm.value.phonePool,
    smsRecordUrl: protocolForm.value.smsRecordUrl,
    smsProvider: protocolForm.value.smsProvider,
    proxies: protocolForm.value.proxies,
    country: protocolForm.value.country,
    accountEmail: protocolForm.value.accountEmail,
    concurrency: 1,
    proxyPreflightAttempts: protocolForm.value.proxyPreflightAttempts,
    smsRecordWaitSeconds: protocolForm.value.smsRecordWaitSeconds,
    smsRecordPollSeconds: protocolForm.value.smsRecordPollSeconds,
    accountEmails: [email],
    clientRequestId,
  }
  protocolAutoPayActiveJobs.value = [...protocolAutoPayActiveJobs.value, { email, key: item.key, status: 'queued', jobId: '', clientRequestId, submitPayload, claimedPhonePoolKeys }]
  persistPaypalAutoPayState({ force: true })
  try {
    const data = await api.startUsPaypalProtocolBatch(submitPayload)
    if (!data.job_id) throw missingPaymentJobIdError('后端没有返回协议支付任务 ID')
    protocolClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    updateAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId, { jobId: data.job_id, status: 'running', submitPayload: null })
    persistPaypalAutoPayState({ force: true })
    void pollProtocolAutoPayJob(data.job_id, email)
  } catch (error) {
    if (isAmbiguousPaymentFailure(error)) {
      updateAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId, { status: 'unknown', error: cleanError(error) })
      protocolAutoPayStatusText.value = `协议自动支付提交结果未知：${email}；已保留占用，5 秒后使用同一幂等键恢复。`
      persistPaypalAutoPayState({ force: true })
      void reconcileProtocolAutoPayStart(email, clientRequestId)
      return
    }
    releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', claimedPhonePoolKeys, protocolForm.value.phonePool)
    removeAutoPayActiveSubmission(protocolAutoPayActiveJobs, clientRequestId)
    persistPaypalAutoPayState({ force: true })
    if (componentUnmounted) storageWriter.writeJsonNow(PHONE_POOL_MANAGEMENT_STORAGE_KEY, { statuses: phonePoolStatusMap.value })
    protocolResult.value = mergePaymentResult(protocolResult.value, { errors: [{ email, error: cleanError(error) }] })
    protocolAutoPayStatusText.value = `协议自动支付启动失败：${email} ${cleanError(error)}`
    void drainProtocolAutoPayQueue()
  }
}
async function launchPay153AutoPayItem(item) {
  const email = String(item?.email || '').trim()
  if (!email || !pay153AutoPayActive.value || pay153Canceling.value || pay153RecoveryPaused.value) return
  if (!autoPayCandidateStillRunnable(pay153LinkAccountOptions.value, pay153AutoPayActiveJobs.value, email, {
    statusResolver: pay153PaymentAccountStatus,
    manualEmails: pay153Busy.value ? pay153SelectedEmails.value : [],
  })) return
  if (!validatePay153Payment([email])) return
  const claimedPhonePoolEntries = pay153Form.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(pay153Form.value.phonePool, 1, 'pay153') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(entry => entry.key).filter(Boolean)
  const clientRequestId = createPaypalClientRequestId('pay153', email)
  savePay153Form({ silent: true })
  const submitPayload = {
    accountEmails: [email],
    country: pay153Form.value.country,
    smsProvider: pay153Form.value.smsProvider,
    phone: pay153Form.value.phone,
    phonePool: pay153Form.value.smsProvider === 'sms_record' ? (phonePoolReuseEnabled.value ? phonePoolPayloadForSubmission(pay153Form.value.phonePool, 'pay153') : formatPhonePoolEntries(claimedPhonePoolEntries)) : pay153Form.value.phonePool,
    smsRecordUrl: pay153Form.value.smsRecordUrl,
    proxies: pay153Form.value.proxies,
    buyerMode: pay153Form.value.buyerMode,
    concurrency: 1,
    smsRecordWaitSeconds: pay153Form.value.smsRecordWaitSeconds,
    smsRecordPollSeconds: pay153Form.value.smsRecordPollSeconds,
    phonePoolReuseEnabled: phonePoolReuseEnabled.value,
    clientRequestId,
  }
  pay153AutoPayActiveJobs.value = [...pay153AutoPayActiveJobs.value, { email, key: item.key, status: 'queued', jobId: '', clientRequestId, submitPayload, claimedPhonePoolKeys }]
  persistPaypalAutoPayState({ force: true })
  try {
    const data = await api.startUsPaypal153Batch(submitPayload)
    if (!data.job_id) throw missingPaymentJobIdError('后端没有返回153支付任务 ID')
    pay153ClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    updateAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId, { jobId: data.job_id, status: 'running', submitPayload: null })
    persistPaypalAutoPayState({ force: true })
    void pollPay153AutoPayJob(data.job_id, email)
  } catch (error) {
    if (isAmbiguousPaymentFailure(error)) {
      updateAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId, { status: 'unknown', error: cleanError(error) })
      pay153AutoPayStatusText.value = `153自动支付提交结果未知：${email}；已保留占用，5 秒后使用同一幂等键恢复。`
      persistPaypalAutoPayState({ force: true })
      void reconcilePay153AutoPayStart(email, clientRequestId)
      return
    }
    releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', claimedPhonePoolKeys, pay153Form.value.phonePool)
    removeAutoPayActiveSubmission(pay153AutoPayActiveJobs, clientRequestId)
    persistPaypalAutoPayState({ force: true })
    if (componentUnmounted) storageWriter.writeJsonNow(PHONE_POOL_MANAGEMENT_STORAGE_KEY, { statuses: phonePoolStatusMap.value })
    pay153Result.value = mergePaymentResult(pay153Result.value, { errors: [{ email, error: cleanError(error) }] })
    pay153AutoPayStatusText.value = `153自动支付启动失败：${email} ${cleanError(error)}`
    void drainPay153AutoPayQueue()
  }
}
async function pollProtocolAutoPayJob(jobId, email) {
  let pollingFailureCount = 0
  for (;;) {
    if (componentUnmounted) return
    if (!await paypalPolling.waitUntilAvailable()) return
    if (componentUnmounted) return
    const recovery = await readPollingSnapshot({
      request: () => api.getUsPaypalProtocolJob(jobId),
      wait: delayMs => paypalPolling.wait(delayMs),
      attempt: pollingFailureCount,
      onTransientError: (error, delayMs, nextAttempt) => {
        if (componentUnmounted) return
        updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId, status: 'poll_error', error: cleanError(error), retryAttempts: nextAttempt })
        protocolAutoPayStatusText.value = `协议自动支付状态查询失败：${email} ${cleanError(error)}；任务和手机号占用已保留，${Math.ceil(delayMs / 1000)} 秒后重试。`
        persistPaypalAutoPayState({ force: true })
      },
    })
    if (componentUnmounted) return
    if (recovery.kind === 'retry') {
      pollingFailureCount = recovery.attempt
      continue
    }
    if (recovery.kind === 'missing') {
      updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId, status: 'unknown_outcome', error: cleanError(recovery.error) })
      protocolAutoPayStatusText.value = `协议自动支付任务已无法从后端定位：${email}；账号和手机号占用保持隔离，请人工核对。`
      persistPaypalAutoPayState({ force: true })
      return
    }
    if (['permanent', 'paused'].includes(recovery.kind)) {
      updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId, status: 'recovery_paused', error: cleanError(recovery.error), retryAttempts: recovery.attempt })
      protocolAutoPayStatusText.value = `协议自动支付状态无法继续确认：${email} ${cleanError(recovery.error)}；任务、账号和手机号占用已暂停隔离。`
      persistPaypalAutoPayState({ force: true })
      return
    }
    if (recovery.kind !== 'snapshot' || componentUnmounted) return
    pollingFailureCount = 0
    const job = recovery.value
    updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId, status: job.status, job, retryAttempts: 0 })
    appendAutoPayLogs(protocolLogs, protocolAutoPayLogOffsets, jobId, email, job.logs)
    if (job.status === 'unknown_outcome') {
      updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId, status: 'unknown_outcome', error: job.error || '服务重启后支付结果未知' })
      protocolAutoPayStatusText.value = `协议自动支付结果未知：${email}；手机号占用保持隔离，请核对远端后人工解除。`
      persistPaypalAutoPayState({ force: true })
      return
    }
    if (TERMINAL_STATUSES.has(String(job.status || ''))) {
      protocolResult.value = mergePaymentResult(protocolResult.value, job.result || {})
      syncPhonePoolStatusFromJobResult(job.result || {}, 'protocol')
      const claimedKeys = protocolClaimedPhonePoolKeysByJob.get(jobId) || claimedPhonePoolKeysForAutoJob(protocolAutoPayActiveJobs, jobId, email)
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'protocol', claimedKeys, protocolForm.value.phonePool)
      protocolClaimedPhonePoolKeysByJob.delete(jobId)
      protocolAutoPayLogOffsets.delete(jobId)
      removeAutoPayActiveJob(protocolAutoPayActiveJobs, email)
      persistPaypalAutoPayState({ force: true })
      await refreshAccounts()
      void drainProtocolAutoPayQueue()
      return
    }
    protocolAutoPayStatusText.value = `协议自动支付运行中：进行中 ${protocolAutoPayActiveJobs.value.length}，队列 ${protocolAutoPayQueue.value.length}。`
    if (!await paypalPolling.wait(1000)) return
  }
}
async function pollPay153AutoPayJob(jobId, email) {
  let pollingFailureCount = 0
  for (;;) {
    if (componentUnmounted) return
    if (!await paypalPolling.waitUntilAvailable()) return
    if (componentUnmounted) return
    const recovery = await readPollingSnapshot({
      request: () => api.getUsPaypal153Job(jobId),
      wait: delayMs => paypalPolling.wait(delayMs),
      attempt: pollingFailureCount,
      onTransientError: (error, delayMs, nextAttempt) => {
        if (componentUnmounted) return
        updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId, status: 'poll_error', error: cleanError(error), retryAttempts: nextAttempt })
        pay153AutoPayStatusText.value = `153自动支付状态查询失败：${email} ${cleanError(error)}；任务和手机号占用已保留，${Math.ceil(delayMs / 1000)} 秒后重试。`
        persistPaypalAutoPayState({ force: true })
      },
    })
    if (componentUnmounted) return
    if (recovery.kind === 'retry') {
      pollingFailureCount = recovery.attempt
      continue
    }
    if (recovery.kind === 'missing') {
      updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId, status: 'unknown_outcome', error: cleanError(recovery.error) })
      pay153AutoPayStatusText.value = `153自动支付任务已无法从后端定位：${email}；账号和手机号占用保持隔离，请人工核对。`
      persistPaypalAutoPayState({ force: true })
      return
    }
    if (['permanent', 'paused'].includes(recovery.kind)) {
      updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId, status: 'recovery_paused', error: cleanError(recovery.error), retryAttempts: recovery.attempt })
      pay153AutoPayStatusText.value = `153自动支付状态无法继续确认：${email} ${cleanError(recovery.error)}；任务、账号和手机号占用已暂停隔离。`
      persistPaypalAutoPayState({ force: true })
      return
    }
    if (recovery.kind !== 'snapshot' || componentUnmounted) return
    pollingFailureCount = 0
    const job = recovery.value
    updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId, status: job.status, job, retryAttempts: 0 })
    appendAutoPayLogs(pay153Logs, pay153AutoPayLogOffsets, jobId, email, job.logs)
    if (job.status === 'unknown_outcome') {
      updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId, status: 'unknown_outcome', error: job.error || '服务重启后支付结果未知' })
      pay153AutoPayStatusText.value = `153自动支付结果未知：${email}；手机号占用保持隔离，请核对远端后人工解除。`
      persistPaypalAutoPayState({ force: true })
      return
    }
    if (TERMINAL_STATUSES.has(String(job.status || ''))) {
      pay153Result.value = mergePaymentResult(pay153Result.value, job.result || {})
      syncPhonePoolStatusFromJobResult(job.result || {}, 'pay153')
      const claimedKeys = pay153ClaimedPhonePoolKeysByJob.get(jobId) || claimedPhonePoolKeysForAutoJob(pay153AutoPayActiveJobs, jobId, email)
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'pay153', claimedKeys, pay153Form.value.phonePool)
      pay153ClaimedPhonePoolKeysByJob.delete(jobId)
      pay153AutoPayLogOffsets.delete(jobId)
      removeAutoPayActiveJob(pay153AutoPayActiveJobs, email)
      persistPaypalAutoPayState({ force: true })
      await refreshAccounts()
      void drainPay153AutoPayQueue()
      return
    }
    pay153AutoPayStatusText.value = `153自动支付运行中：进行中 ${pay153AutoPayActiveJobs.value.length}，队列 ${pay153AutoPayQueue.value.length}。`
    if (!await paypalPolling.wait(1000)) return
  }
}
async function drainProtocolAutoPayQueue() {
  if (protocolAutoPayDraining) return
  protocolAutoPayDraining = true
  try {
    while (protocolAutoPayActive.value && protocolAutoPayQueue.value.length) {
      const limit = Math.max(1, Number(protocolForm.value.concurrency || 1))
      const availableSlots = Math.max(0, limit - protocolManualOccupiedSlots() - protocolAutoPayActiveJobs.value.length)
      if (!availableSlots) break
      const batch = protocolAutoPayQueue.value.splice(0, availableSlots)
      protocolAutoPayQueue.value = [...protocolAutoPayQueue.value]
      protocolAutoPayStatusText.value = `协议自动支付正在提交 ${batch.length} 个账号，进行中 ${protocolAutoPayActiveJobs.value.length}，队列剩余 ${protocolAutoPayQueue.value.length} 个。`
      for (const item of batch) void launchProtocolAutoPayItem(item)
    }
  } finally {
    protocolAutoPayDraining = false
  }
}
async function drainPay153AutoPayQueue() {
  if (pay153AutoPayDraining || pay153Canceling.value || pay153RecoveryPaused.value) return
  pay153AutoPayDraining = true
  try {
    while (pay153AutoPayActive.value && !pay153Canceling.value && !pay153RecoveryPaused.value && pay153AutoPayQueue.value.length) {
      const limit = Math.max(1, Number(pay153Form.value.concurrency || 1))
      const availableSlots = Math.max(0, limit - pay153ManualOccupiedSlots() - pay153AutoPayActiveJobs.value.length)
      if (!availableSlots) break
      const batch = pay153AutoPayQueue.value.splice(0, availableSlots)
      pay153AutoPayQueue.value = [...pay153AutoPayQueue.value]
      pay153AutoPayStatusText.value = `153自动支付正在提交 ${batch.length} 个账号，进行中 ${pay153AutoPayActiveJobs.value.length}，队列剩余 ${pay153AutoPayQueue.value.length} 个。`
      for (const item of batch) void launchPay153AutoPayItem(item)
    }
  } finally {
    pay153AutoPayDraining = false
  }
}
function splitProtocolLines(value) {
  return String(value || '').replace(/,/g, '\n').split(/\r?\n/).map(item => item.trim()).filter(Boolean)
}
function parseManualPaypalLinks(value) {
  const seen = new Set()
  const links = []
  for (const line of splitProtocolLines(value)) {
    const token = displayBaToken(line)
    if (!/^BA-[A-Za-z0-9_-]+$/i.test(token)) continue
    const key = token.toUpperCase()
    if (seen.has(key)) continue
    seen.add(key)
    links.push(line)
  }
  return links
}
function baPoolId(value) {
  const token = displayBaToken(value).toUpperCase()
  return token || String(value || '').trim()
}
function baPoolLink(value) {
  const text = String(value || '').trim()
  const token = displayBaToken(text)
  if (!token) return ''
  return /^https?:\/\//i.test(text) ? text : `https://www.paypal.com/agreements/approve?ba_token=${token}`
}
function makeBaPoolItem(value, country = 'US') {
  const token = displayBaToken(value)
  const link = baPoolLink(value)
  if (!token || !link) return null
  return {
    id: baPoolId(token),
    label: token,
    baToken: token,
    paypalLink: link,
    country: String(country || 'US').trim().toUpperCase() || 'US',
    status: 'pending',
    error: '',
    updatedAt: '',
  }
}
function baPoolStatusText(status) {
  return ({
    pending: '未支付',
    running: '支付中',
    unknown_outcome: '结果待核对',
    success: '支付成功',
    paid: '已支付',
    failed: '支付失败',
    cancelled: '已取消',
  })[String(status || 'pending').toLowerCase()] || '未支付'
}
function baPoolStatusClass(status) {
  return ({
    pending: 'border-gray-700 bg-gray-900 text-gray-400',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    unknown_outcome: 'border-amber-500/30 bg-amber-500/10 text-amber-200',
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    paid: 'border-purple-500/30 bg-purple-500/10 text-purple-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    cancelled: 'border-gray-600 bg-gray-800 text-gray-300',
  })[String(status || 'pending').toLowerCase()] || 'border-gray-700 bg-gray-900 text-gray-400'
}
function baPoolItemSelectable(item) {
  const status = String(item?.status || '').trim().toLowerCase()
  return Boolean(item) && !['paid', 'success'].includes(status) && paymentTargetSelectable(status)
}
function filterBaPool(pool, statusFilter) {
  const target = String(statusFilter || 'all').trim().toLowerCase()
  if (!target || target === 'all') return pool
  return pool.filter(item => String(item.status || 'pending').toLowerCase() === target)
}
function baPoolStats(pool, selectedCount) {
  return [
    { label: '池内', value: pool.length, class: 'text-gray-200' },
    { label: '已选', value: selectedCount, class: 'text-white' },
    { label: '已支付', value: pool.filter(item => ['paid', 'success'].includes(item.status)).length, class: 'text-emerald-300' },
    { label: '失败', value: pool.filter(item => item.status === 'failed').length, class: 'text-rose-300' },
  ]
}
function saveBaPool(kind) {
  const key = kind === 'pay153' ? PAY153_BA_POOL_STORAGE_KEY : PROTOCOL_BA_POOL_STORAGE_KEY
  storageWriter.queueJson(key, () => kind === 'pay153' ? pay153BaPool.value : protocolBaPool.value)
}
function importBaLinksToPool(kind, options = {}) {
  const isPay153 = kind === 'pay153'
  const sourceLinks = isPay153 ? directPay153BaLinks.value : directProtocolBaLinks.value
  const poolRef = isPay153 ? pay153BaPool : protocolBaPool
  const selectedRef = isPay153 ? selectedPay153BaIds : selectedProtocolBaIds
  const formRef = isPay153 ? pay153Form : protocolForm
  const country = isPay153 && formRef.value.country === 'AUTO' ? 'US' : formRef.value.country
  const setStatusFn = isPay153 ? setPay153Status : setProtocolStatus
  if (!sourceLinks.length) {
    if (!options.silent) setStatusFn('没有可导入的 BA 链接。', true)
    return []
  }
  const existingIds = new Set(poolRef.value.map(item => item.id))
  const imported = []
  const next = [...poolRef.value]
  for (const link of sourceLinks) {
    const item = makeBaPoolItem(link, country)
    if (!item || existingIds.has(item.id)) continue
    existingIds.add(item.id)
    imported.push(item)
    next.push(item)
  }
  poolRef.value = next
  if (options.select !== false && imported.length) selectedRef.value = new Set([...selectedRef.value, ...imported.map(item => item.id)])
  if (imported.length) formRef.value.paypalLink = ''
  saveBaPool(kind)
  if (!options.silent) setStatusFn(imported.length ? `已导入 ${imported.length} 条 BA 链到池。` : '这些 BA 链已在池中。')
  return imported
}
function toggleBaPoolItem(kind, id) {
  const pool = kind === 'pay153' ? pay153BaPool.value : protocolBaPool.value
  const selectedRef = kind === 'pay153' ? selectedPay153BaIds : selectedProtocolBaIds
  const item = pool.find(entry => entry.id === id)
  if (!baPoolItemSelectable(item)) return
  const next = new Set(selectedRef.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedRef.value = next
}
function selectAllBaPool(kind) {
  const pool = kind === 'pay153' ? filteredPay153BaPool.value : filteredProtocolBaPool.value
  const selectedRef = kind === 'pay153' ? selectedPay153BaIds : selectedProtocolBaIds
  selectedRef.value = new Set(pool.filter(baPoolItemSelectable).map(item => item.id))
}
function clearSelectedBaPool(kind) {
  const selectedRef = kind === 'pay153' ? selectedPay153BaIds : selectedProtocolBaIds
  selectedRef.value = new Set()
}
function removeSelectedBaPool(kind) {
  const selectedRef = kind === 'pay153' ? selectedPay153BaIds : selectedProtocolBaIds
  const selected = selectedRef.value
  if (kind === 'pay153') pay153BaPool.value = pay153BaPool.value.filter(item => !selected.has(item.id))
  else protocolBaPool.value = protocolBaPool.value.filter(item => !selected.has(item.id))
  selectedRef.value = new Set()
  saveBaPool(kind)
}
function resetSelectedBaPoolStatus(kind) {
  const selected = kind === 'pay153' ? selectedPay153BaIds.value : selectedProtocolBaIds.value
  const reset = item => selected.has(item.id) ? { ...item, status: 'pending', error: '', updatedAt: '' } : item
  if (kind === 'pay153') pay153BaPool.value = pay153BaPool.value.map(reset)
  else protocolBaPool.value = protocolBaPool.value.map(reset)
  saveBaPool(kind)
}
function setBaPoolStatus(kind, ids, status, error = '') {
  const targets = new Set(ids)
  const updatedAt = new Date().toLocaleString()
  const update = item => targets.has(item.id) ? { ...item, status, error: String(error || ''), updatedAt } : item
  if (kind === 'pay153') pay153BaPool.value = pay153BaPool.value.map(update)
  else protocolBaPool.value = protocolBaPool.value.map(update)
  saveBaPool(kind)
}
function syncBaPoolFromJob(kind, job) {
  if (!job) return
  const poolRef = kind === 'pay153' ? pay153BaPool : protocolBaPool
  if (!poolRef.value.length) return
  const byToken = new Map(poolRef.value.map(item => [String(item.baToken || item.label || '').toUpperCase(), item]))
  const updates = new Map()
  const jobUnknown = String(job.status || '').toLowerCase() === 'unknown_outcome'
  if (jobUnknown) {
    for (const target of job.target_ba_tokens || job.targetBaTokens || []) {
      const row = byToken.get(displayBaToken(target).toUpperCase())
      if (row) updates.set(row.id, { status: 'unknown_outcome', error: String(job.error || '远端支付结果待核对') })
    }
  }
  const statuses = job.account_statuses && typeof job.account_statuses === 'object' ? job.account_statuses : {}
  for (const [label, statusItem] of Object.entries(statuses)) {
    const row = byToken.get(displayBaToken(label).toUpperCase() || String(label || '').toUpperCase())
    if (row && statusItem) updates.set(row.id, { status: String(statusItem.status || 'pending'), error: String(statusItem.error || '') })
  }
  for (const item of job.result?.successes || []) {
    const row = byToken.get(displayBaToken(item.email || item.ba_token || item.baToken || '').toUpperCase())
    if (row) updates.set(row.id, { status: 'paid', error: '' })
  }
  for (const item of job.result?.errors || []) {
    const row = byToken.get(displayBaToken(item.email || item.ba_token || item.baToken || '').toUpperCase())
    if (row) updates.set(row.id, {
      status: jobUnknown || item.unknown_outcome === true ? 'unknown_outcome' : 'failed',
      error: String(item.error || item.message || ''),
    })
  }
  for (const item of job.result?.skipped || []) {
    const row = byToken.get(displayBaToken(item.email || item.ba_token || item.baToken || '').toUpperCase())
    if (row) updates.set(row.id, { status: 'cancelled', error: String(item.reason || '已跳过') })
  }
  for (const child of Object.values(job.children || {})) {
    const row = byToken.get(displayBaToken(child?.ba_token || child?.baToken || child?.email || '').toUpperCase())
    if (!row) continue
    const childStatus = String(child?.status || '').toLowerCase()
    if (childStatus === 'completed') updates.set(row.id, { status: 'paid', error: '' })
    else if (childStatus === 'failed') updates.set(row.id, { status: 'failed', error: String(child?.error || child?.stage || '') })
    else if (childStatus === 'cancelled') updates.set(row.id, { status: 'cancelled', error: String(child?.error || '已取消') })
    else if (childStatus) updates.set(row.id, { status: jobUnknown ? 'unknown_outcome' : 'running', error: String(child?.stage || job.error || '') })
  }
  if (!updates.size) return
  const updatedAt = new Date().toLocaleString()
  poolRef.value = poolRef.value.map(item => updates.has(item.id) ? { ...item, ...updates.get(item.id), updatedAt } : item)
  saveBaPool(kind)
}
async function retryFailedBaPool(kind) {
  const isPay153 = kind === 'pay153'
  const failed = isPay153 ? failedPay153BaItems.value : failedProtocolBaItems.value
  const selectedRef = isPay153 ? selectedPay153BaIds : selectedProtocolBaIds
  const selectedAccountRef = isPay153 ? selectedPay153AccountEmails : selectedProtocolAccountEmails
  const startFn = isPay153 ? startPay153Payment : startProtocolPayment
  const setStatusFn = isPay153 ? setPay153Status : setProtocolStatus
  if (!failed.length) {
    setStatusFn('没有失败的 BA 链可重试。', true)
    return
  }
  selectedAccountRef.value = new Set()
  selectedRef.value = new Set(failed.map(item => item.id))
  await startFn()
}
function parseSmsRecordPhonePoolLines(value) {
  return String(value || '').split(/\r?\n/).map(item => item.trim()).filter(line => /^\S+\s*-{4,}\s*https?:\/\//i.test(line))
}
function parsePay153PhonePoolLines(value) {
  return parseSmsRecordPhonePoolLines(value)
}
function validateProtocolPayment(targetEmails = protocolSelectedEmails.value) {
  protocolForm.value.country = String(protocolForm.value.country || 'US').trim().toUpperCase()
  protocolForm.value.smsProvider = String(protocolForm.value.smsProvider || 'sms_record').trim().toLowerCase().replace(/-/g, '_')
  if (!['sms_record', 'hero_sms', 'hero_sms_rent', 'smsbower'].includes(protocolForm.value.smsProvider)) protocolForm.value.smsProvider = 'sms_record'
  const batchCount = Array.isArray(targetEmails) ? targetEmails.length : 0
  const activeAutoPayEmails = new Set(protocolAutoPayActiveJobs.value.map(item => String(item.email || '').trim().toLowerCase()))
  const duplicateEmail = (targetEmails || []).find(email => activeAutoPayEmails.has(String(email || '').trim().toLowerCase()))
  if (duplicateEmail) { setProtocolStatus(`账号 ${duplicateEmail} 已有自动支付任务，不能重复提交。`, true); return false }
  if (!batchCount && !selectedProtocolBaItems.value.length && directProtocolBaLinks.value.length) {
    importBaLinksToPool('protocol', { silent: true, select: true })
  }
  const manualPaypalLinks = batchCount ? [] : selectedProtocolBaItems.value.map(item => item.paypalLink)
  const manualLinkCount = manualPaypalLinks.length
  if (!batchCount && !manualLinkCount) { setProtocolStatus('请填写有效 BA 链接或 BA token，或多选已成功提链账号。', true); return false }
  if (!PROTOCOL_COUNTRIES.has(protocolForm.value.country)) { setProtocolStatus('当前协议支付支持 AU/BR/CA/GB/ID/JP/MX/PH/TH/NL/US。', true); return false }
  const phoneCount = splitProtocolLines(protocolForm.value.phone).length
  const phonePoolCount = phonePoolReuseEnabled.value ? parseSmsRecordPhonePoolLines(protocolForm.value.phonePool).length : usablePhonePoolEntriesFromText(protocolForm.value.phonePool, 'protocol').length
  const requiredPaymentCount = batchCount || manualLinkCount || 1
  if (protocolForm.value.smsProvider === 'sms_record') {
    const requiredCount = requiredPaymentCount
    if (phonePoolCount < requiredCount) { setProtocolStatus('协议支付号池数量不足；请按“手机号----SMS record URL”每行导入一个号码。', true); return false }
  } else if (protocolForm.value.smsProvider === 'hero_sms_rent') {
    if (!String(protocolForm.value.phone || '').trim()) { setProtocolStatus('请填写 HeroSMS 长效号码。', true); return false }
    if (requiredPaymentCount > 1 && phoneCount < requiredPaymentCount) { setProtocolStatus('HeroSMS 长效号批量支付时，每个账号或 BA 链接都需要一行长效号码。', true); return false }
  }
  protocolForm.value.concurrency = Math.max(1, Math.min(20, Number(protocolForm.value.concurrency || 1)))
  protocolForm.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(protocolForm.value.proxyPreflightAttempts || 5)))
  protocolForm.value.smsRecordWaitSeconds = Math.max(60, Math.min(900, Number(protocolForm.value.smsRecordWaitSeconds || 300)))
  protocolForm.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(protocolForm.value.smsRecordPollSeconds || 3)))
  return true
}

async function startProtocolPayment(options = {}) {
  if (protocolRecoveryPaused.value) {
    setProtocolStatus('已有结果未知的协议支付提交；请先继续确认，或核对远端后解除占用。', true)
    return false
  }
  protocolSubmissionCancelRequested = false
  const selectedEmails = (Array.isArray(options.autoBatchEmails) ? options.autoBatchEmails : protocolSelectedEmails.value).filter(email => protocolLinkSelectableEmails.value.has(email))
  if (Array.isArray(options.autoBatchEmails)) selectedProtocolAccountEmails.value = new Set(selectedEmails)
  if (!validateProtocolPayment(selectedEmails)) return false
  const protocolBaItems = selectedEmails.length ? [] : selectedProtocolBaItems.value
  const manualPaypalLinks = protocolBaItems.map(item => item.paypalLink)
  const paymentCount = manualPaypalLinks.length || selectedEmails.length || 1
  protocolBusy.value = true
  protocolCanceling.value = false
  protocolLogs.value = []
  protocolResult.value = null
  protocolJob.value = null
  activeTab.value = 'protocol'
  if (protocolBaItems.length) setBaPoolStatus('protocol', protocolBaItems.map(item => item.id), 'running')
  setProtocolStatus('协议支付任务已提交，正在启动本地 PayPal 引擎。')
  const claimedPhonePoolEntries = protocolForm.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(protocolForm.value.phonePool, paymentCount, 'protocol') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(item => item.key).filter(Boolean)
  const clientRequestId = createPaypalClientRequestId('protocol-manual', selectedEmails[0] || manualPaypalLinks[0] || 'manual')
  saveProtocolForm({ silent: true })
  const submitPayload = {
    paypalLink: manualPaypalLinks[0] || protocolForm.value.paypalLink,
    paypalLinks: manualPaypalLinks,
    phone: protocolForm.value.phone,
    phonePool: protocolForm.value.smsProvider === 'sms_record' ? (phonePoolReuseEnabled.value ? phonePoolPayloadForSubmission(protocolForm.value.phonePool, 'protocol') : formatPhonePoolEntries(claimedPhonePoolEntries)) : protocolForm.value.phonePool,
    smsRecordUrl: protocolForm.value.smsRecordUrl,
    smsProvider: protocolForm.value.smsProvider,
    proxies: protocolForm.value.proxies,
    country: protocolForm.value.country,
    accountEmail: protocolForm.value.accountEmail,
    concurrency: protocolForm.value.concurrency,
    proxyPreflightAttempts: protocolForm.value.proxyPreflightAttempts,
    smsRecordWaitSeconds: protocolForm.value.smsRecordWaitSeconds,
    smsRecordPollSeconds: protocolForm.value.smsRecordPollSeconds,
    accountEmails: selectedEmails,
    clientRequestId,
  }
  const checkpoint = { clientRequestId, submitPayload, accountCount: paymentCount, concurrency: protocolForm.value.concurrency, startedAt: Date.now(), claimedPhonePoolKeys }
  protocolRecoveryCheckpoint.value = checkpoint
  persistProtocolJobState(checkpoint, { force: true })
  try {
    const data = await submitProtocolManualJob(submitPayload, checkpoint)
    if (!data) return false
    if (!data.job_id) throw missingPaymentJobIdError('后端没有返回协议支付任务 ID')
    if (claimedPhonePoolKeys.length) protocolClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    protocolJob.value = { id: data.job_id, status: 'queued', total: paymentCount, completed: 0, concurrency: protocolForm.value.concurrency }
    protocolRecoveryCheckpoint.value = null
    protocolRecoveryPaused.value = false
    persistProtocolJobState({ ...checkpoint, jobId: data.job_id, clientRequestId: '', submitPayload: null, unknownOutcome: false, recoveryPaused: false, retryAttempts: 0 }, { force: true })
    if (protocolSubmissionCancelRequested) {
      await cancelProtocolJob()
      await pollProtocolJob(data.job_id)
      return false
    }
    await pollProtocolJob(data.job_id)
    return true
  } catch (error) {
    if (protocolBaItems.length) setBaPoolStatus('protocol', protocolBaItems.map(item => item.id), 'failed', cleanError(error))
    releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', claimedPhonePoolKeys, protocolForm.value.phonePool)
    setProtocolStatus(cleanError(error), true)
    if (protocolJob.value?.id) persistProtocolJobState()
    else {
      protocolRecoveryCheckpoint.value = null
      protocolRecoveryPaused.value = false
      storageWriter.remove(PROTOCOL_JOB_STORAGE_KEY)
    }
    return false
  } finally {
    protocolBusy.value = false
    protocolCanceling.value = false
    void drainProtocolAutoPayQueue()
  }
}

async function pollProtocolJob(jobId) {
  let pollingFailureCount = 0
  for (;;) {
    if (componentUnmounted) return
    if (!await paypalPolling.waitUntilAvailable()) return
    if (componentUnmounted) return
    const recovery = await readPollingSnapshot({
      request: () => api.getUsPaypalProtocolJob(jobId),
      wait: delayMs => paypalPolling.wait(delayMs),
      attempt: pollingFailureCount,
      onTransientError: (error, delayMs) => {
        if (componentUnmounted) return
        persistProtocolJobState({ jobId })
        setProtocolStatus(`协议支付状态查询失败：${cleanError(error)}；任务和手机号占用已保留，${Math.ceil(delayMs / 1000)} 秒后重试。`, true)
      },
    })
    if (componentUnmounted) return
    if (recovery.kind === 'retry') {
      pollingFailureCount = recovery.attempt
      continue
    }
    if (recovery.kind === 'missing') {
      protocolJob.value = { ...(protocolJob.value || {}), id: jobId, status: 'unknown_outcome', error: cleanError(recovery.error) }
      protocolRecoveryPaused.value = true
      protocolRecoveryCheckpoint.value = { jobId, recoveryPaused: true, unknownOutcome: true, accountEmails: [...protocolSelectedEmails.value], claimedPhonePoolKeys: protocolClaimedPhonePoolKeysByJob.get(jobId) || [] }
      setProtocolStatus('协议支付任务已无法从后端定位；结果未知，账号与手机号占用保持隔离，请人工核对。', true)
      persistProtocolJobState(protocolRecoveryCheckpoint.value, { force: true })
      return
    }
    if (['permanent', 'paused'].includes(recovery.kind)) {
      protocolJob.value = { ...(protocolJob.value || {}), id: jobId, status: 'recovery_paused' }
      protocolRecoveryPaused.value = true
      protocolRecoveryCheckpoint.value = { jobId, recoveryPaused: true, unknownOutcome: true, accountEmails: [...protocolSelectedEmails.value], claimedPhonePoolKeys: protocolClaimedPhonePoolKeysByJob.get(jobId) || [] }
      const reason = recovery.kind === 'permanent' ? `服务端拒绝状态查询：${cleanError(recovery.error)}` : `连续查询失败 ${recovery.attempt} 次`
      setProtocolStatus(`协议支付${reason}；已暂停查询并保留任务、账号与手机号占用。`, true)
      persistProtocolJobState(protocolRecoveryCheckpoint.value, { force: true })
      return
    }
    if (recovery.kind !== 'snapshot') return
    if (componentUnmounted) return
    pollingFailureCount = 0
    const job = recovery.value
    protocolJob.value = job
    if (protocolRecoveryPaused.value) {
      protocolRecoveryPaused.value = false
      protocolRecoveryCheckpoint.value = null
      persistProtocolJobState({ jobId, recoveryPaused: false, unknownOutcome: false }, { force: true })
    }
    protocolLogs.value = Array.isArray(job.logs) ? job.logs.slice(-200) : []
    protocolResult.value = job.result || null
    syncBaPoolFromJob('protocol', job)
    await nextTick()
    if (protocolLogRef.value) protocolLogRef.value.scrollTop = protocolLogRef.value.scrollHeight
    if (job.status === 'unknown_outcome') {
      protocolRecoveryPaused.value = true
      protocolRecoveryCheckpoint.value = { jobId, recoveryPaused: true, unknownOutcome: true, claimedPhonePoolKeys: protocolClaimedPhonePoolKeysByJob.get(jobId) || [] }
      setProtocolStatus(job.error || '服务重启后协议支付结果未知；手机号占用保持隔离，请核对远端状态。', true)
      persistProtocolJobState(protocolRecoveryCheckpoint.value, { force: true })
      return
    }
    if (job.status === 'success') {
      syncPhonePoolStatusFromJobResult(job.result || {}, 'protocol')
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'protocol', protocolClaimedPhonePoolKeysByJob.get(jobId) || [], protocolForm.value.phonePool)
      setProtocolStatus(Number(job.total || 0) > 1 ? `协议批量支付完成，已完成 ${job.completed || 0}/${job.total || 0}。` : '协议支付成功。')
      persistProtocolJobState({ jobId })
      await refreshAccounts()
      void drainProtocolAutoPayQueue()
      return
    }
    if (job.status === 'cancelled') {
      syncPhonePoolStatusFromJobResult(job.result || {}, 'protocol')
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'protocol', protocolClaimedPhonePoolKeysByJob.get(jobId) || [], protocolForm.value.phonePool)
      setProtocolStatus('协议支付任务已取消。')
      persistProtocolJobState({ jobId })
      void drainProtocolAutoPayQueue()
      return
    }
    if (job.status === 'error' || job.status === 'failed') {
      syncPhonePoolStatusFromJobResult(job.result || {}, 'protocol')
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'protocol', protocolClaimedPhonePoolKeysByJob.get(jobId) || [], protocolForm.value.phonePool)
      setProtocolStatus(job.error || '协议支付失败', true)
      persistProtocolJobState({ jobId })
      void drainProtocolAutoPayQueue()
      throw new Error(job.error || '协议支付失败')
    }
    const total = Number(job.total || 0)
    const completed = Number(job.completed || 0)
    setProtocolStatus(total > 1 ? `协议批量支付执行中，已完成 ${completed}/${total}，已记录 ${protocolLogs.value.length} 条日志。` : `协议支付执行中，已记录 ${protocolLogs.value.length} 条日志。`)
    persistProtocolJobState({ jobId, accountCount: total || 1, concurrency: job.concurrency || protocolForm.value.concurrency })
    if (!await paypalPolling.wait(1000)) return
  }
}

async function cancelProtocolJob() {
  const jobId = protocolJob.value?.id
  if (protocolCanceling.value) return
  protocolSubmissionGuard.cancel()
  if (!jobId) {
    protocolSubmissionCancelRequested = true
    protocolRecoveryPaused.value = true
    const checkpoint = protocolRecoveryCheckpoint.value
    if (checkpoint) {
      protocolRecoveryCheckpoint.value = { ...checkpoint, recoveryPaused: true }
      persistProtocolJobState(protocolRecoveryCheckpoint.value, { force: true })
    }
    setProtocolStatus('已暂停提交确认；任务和手机号占用继续保留。', true)
    return
  }
  protocolCanceling.value = true
  try {
    await api.cancelUsPaypalProtocolJob(jobId)
    setProtocolStatus('已发送取消请求，正在终止协议子进程。')
  } catch (error) {
    setProtocolStatus(`取消失败：${cleanError(error)}`, true)
    protocolCanceling.value = false
  }
}

function setPay153Status(message, error = false) { pay153StatusText.value = message; pay153StatusError.value = error }
function persistPay153JobState(fallback = {}, options = {}) {
  const cleanupOnly = fallback.cleanupByBa === true
  const currentJob = cleanupOnly ? null : pay153Job.value
  const jobId = currentJob?.id || fallback.jobId
  const claimedPhonePoolKeys = fallback.claimedPhonePoolKeys || pay153ClaimedPhonePoolKeysByJob.get(jobId) || []
  const payload = paymentJobSnapshot(jobId, currentJob, cleanupOnly ? [] : pay153Logs.value, cleanupOnly ? null : pay153Result.value, pay153StatusText.value, pay153StatusError.value, { ...fallback, claimedPhonePoolKeys })
  if (payload.jobId || payload.clientRequestId || payload.cleanupByBa || payload.logs.length || payload.result) queuePaymentJobSnapshot(PAY153_JOB_STORAGE_KEY, payload, options)
}
function restorePay153JobState(saved = {}) {
  if (!saved || typeof saved !== 'object' || !(saved.jobId || saved.clientRequestId || saved.cleanupByBa || saved.job || saved.logs || saved.result)) return false
  pay153Job.value = saved.job || (saved.jobId ? { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 1), completed: 0, concurrency: Number(saved.concurrency || 1), children: {} } : null)
  pay153Logs.value = Array.isArray(saved.logs) ? saved.logs : []
  pay153Result.value = saved.result || null
  pay153RecoveryPaused.value = Boolean(saved.recoveryPaused)
  pay153RecoveryCheckpoint.value = saved.recoveryPaused || (saved.clientRequestId && saved.submitPayload) ? saved : null
  if (saved.jobId && Array.isArray(saved.claimedPhonePoolKeys)) pay153ClaimedPhonePoolKeysByJob.set(saved.jobId, saved.claimedPhonePoolKeys)
  if (saved.statusText) setPay153Status(saved.statusText, Boolean(saved.statusError))
  return true
}
function resumePay153JobStateFromStorage(options = {}) {
  if (pay153Busy.value) return false
  const hasMemoryState = Boolean(pay153Job.value?.id || pay153Logs.value.length || pay153Result.value)
  let saved = {}
  if (!hasMemoryState || options.force) {
    try {
      saved = JSON.parse(sessionStorageFacade.getItem(PAY153_JOB_STORAGE_KEY) || '{}')
    } catch {
      saved = {}
    }
    const savedJobId = String(saved.jobId || saved.job?.id || '').trim()
    if (savedJobId && pay153AutoPayActiveJobs.value.some(item => item.jobId === savedJobId)) {
      storageWriter.remove(PAY153_JOB_STORAGE_KEY)
      return false
    }
    if (!restorePay153JobState(saved)) return false
  }
  const status = String(pay153Job.value?.status || '')
  const jobId = pay153Job.value?.id || saved.jobId
  if (options.preferredActiveTab === 'pay153' || !TERMINAL_STATUSES.has(status)) activeTab.value = 'pay153'
  if (!jobId && saved.clientRequestId && saved.submitPayload) {
    pay153RecoveryCheckpoint.value = saved
    if (saved.recoveryPaused) {
      pay153RecoveryPaused.value = true
      setPay153Status('153支付提交确认已暂停；任务和手机号占用继续保留，可继续确认或在核对远端后人工解除。', true)
      return true
    }
    pay153Busy.value = true
    pay153Canceling.value = false
    pay153SubmissionCancelRequested = false
    setPay153Status('已恢复结果未知的153支付提交，正在使用原幂等键确认后端任务。')
    void resumeUnknownPay153PaymentStart(saved).catch((error) => {
      setPay153Status(`恢复153支付提交失败：${cleanError(error)}`, true)
      persistPay153JobState(saved, { force: true })
    }).finally(() => {
      if (!componentUnmounted) {
        pay153Busy.value = false
        pay153Canceling.value = false
      }
    })
    return true
  }
  if (!TERMINAL_STATUSES.has(status) && jobId) {
    pay153Busy.value = true
    pay153Canceling.value = false
    setPay153Status('已恢复153支付任务，正在重新同步后端进度。')
    persistPay153JobState(saved)
    void pollPay153Job(jobId).catch((error) => {
      setPay153Status(`恢复153支付失败：${cleanError(error)}`, true)
      persistPay153JobState()
    }).finally(() => {
      if (!componentUnmounted) {
        pay153Busy.value = false
        pay153Canceling.value = false
      }
    })
  }
  return true
}
async function submitPay153ManualJob(submitPayload, checkpoint) {
  const submissionGeneration = pay153SubmissionGuard.start()
  const submissionActive = () => pay153SubmissionGuard.isActive(submissionGeneration)
  let attempt = Number(checkpoint?.retryAttempts || 0)
  for (;;) {
    if (!submissionActive() || pay153SubmissionCancelRequested || componentUnmounted) return null
    if (!await paypalPolling.waitUntilAvailable()) return null
    if (!submissionActive() || pay153SubmissionCancelRequested || componentUnmounted) return null
    try {
      const data = await api.startUsPaypal153Batch(submitPayload)
      if (!data?.job_id) throw missingPaymentJobIdError('后端没有返回153支付任务 ID')
      pay153RecoveryPaused.value = false
      return data
    } catch (error) {
      if (!isAmbiguousPaymentFailure(error)) throw error
      attempt += 1
      const paused = !submissionActive() || pay153SubmissionCancelRequested || attempt >= PAYMENT_RECOVERY_MAX_ATTEMPTS
      const nextCheckpoint = { ...checkpoint, unknownOutcome: true, recoveryPaused: paused, retryAttempts: attempt }
      pay153RecoveryCheckpoint.value = nextCheckpoint
      pay153RecoveryPaused.value = paused
      if (paused) {
        setPay153Status(`153支付提交结果仍未知；已在 ${attempt} 次确认后暂停，任务和手机号占用保持不变。`, true)
        persistPay153JobState(nextCheckpoint, { force: true })
        return null
      }
      const retryDelayMs = paymentRecoveryDelayMs(attempt)
      setPay153Status(`153支付提交结果未知：${cleanError(error)}；任务和手机号占用已保留，约 ${Math.ceil(retryDelayMs / 1000)} 秒后使用原幂等键恢复。`, true)
      persistPay153JobState(nextCheckpoint, { force: true })
      if (!await paypalPolling.wait(retryDelayMs)) return null
    }
  }
}
async function resumeUnknownPay153PaymentStart(saved) {
  pay153RecoveryCheckpoint.value = saved
  const data = await submitPay153ManualJob(saved.submitPayload, saved)
  if (!data || componentUnmounted) return
  if (!data.job_id) throw missingPaymentJobIdError('后端没有返回153支付任务 ID')
  const claimedPhonePoolKeys = Array.isArray(saved.claimedPhonePoolKeys) ? saved.claimedPhonePoolKeys : []
  if (claimedPhonePoolKeys.length) pay153ClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
  pay153Job.value = { id: data.job_id, status: 'queued', total: Number(saved.accountCount || 1), completed: 0, concurrency: Number(saved.concurrency || 1), children: {} }
  pay153RecoveryCheckpoint.value = null
  pay153RecoveryPaused.value = false
  persistPay153JobState({ ...saved, jobId: data.job_id, clientRequestId: '', submitPayload: null, unknownOutcome: false, recoveryPaused: false, retryAttempts: 0 }, { force: true })
  if (pay153SubmissionCancelRequested) {
    await cancelPay153Job()
    await pollPay153Job(data.job_id)
    return
  }
  await pollPay153Job(data.job_id)
}
async function resumePay153Recovery() {
  const saved = pay153RecoveryCheckpoint.value
  if (!saved?.clientRequestId || !saved?.submitPayload || pay153Busy.value) return
  pay153SubmissionCancelRequested = false
  pay153RecoveryPaused.value = false
  pay153Busy.value = true
  pay153Canceling.value = false
  setPay153Status('正在继续确认未知的153支付提交。')
  try {
    await resumeUnknownPay153PaymentStart({ ...saved, recoveryPaused: false, retryAttempts: 0 })
  } catch (error) {
    setPay153Status(`继续确认153支付失败：${cleanError(error)}`, true)
  } finally {
    pay153Busy.value = false
    pay153Canceling.value = false
  }
}
async function discardPay153Recovery() {
  if (pay153Busy.value) {
    setPay153Status('提交确认仍在停止中，请稍候再解除占用。', true)
    return
  }
  const saved = pay153RecoveryCheckpoint.value
  if (!saved || !window.confirm('仅当你已核对远端且确认没有运行中的153支付任务时解除手机号占用，是否继续？')) return
  let released
  try {
    released = saved.cleanupByBa
      ? { ok: true, target_ba_tokens: [saved.baToken].filter(Boolean), account_emails: [] }
      : await releaseUnknownPaymentOccupancy('paypal_153_payment', saved)
  } catch (error) {
    setPay153Status(`后端解除未知153支付占用失败：${cleanError(error)}`, true)
    return
  }
  releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', saved.claimedPhonePoolKeys || [], pay153Form.value.phonePool)
  resetReconciledBaPoolTargets('paypal_153_payment', released, saved)
  pay153RecoveryCheckpoint.value = null
  pay153RecoveryPaused.value = false
  pay153SubmissionCancelRequested = false
  pay153Job.value = null
  storageWriter.remove(PAY153_JOB_STORAGE_KEY)
  await refreshAccounts()
  setPay153Status('已解除经人工确认的未知153支付占用。')
}
function savePay153Form(options = {}) {
  storageWriter.queueJson(PAY153_FORM_STORAGE_KEY, () => pay153Form.value)
  if (!options.silent && !pay153Busy.value) setPay153Status('153支付输入已保存。')
}
function togglePay153Account(email) {
  const target = String(email || '').trim()
  if (!target) return
  if (!pay153LinkSelectableEmails.value.has(target)) return
  const next = new Set(selectedPay153AccountEmails.value)
  next.has(target) ? next.delete(target) : next.add(target)
  selectedPay153AccountEmails.value = next
}
function selectAllPay153Accounts() {
  selectedPay153AccountEmails.value = new Set(pay153LinkAccountOptions.value.filter(item => paymentLinkAccountSelectable(item, pay153PaymentAccountStatus)).map(item => item.email))
}
function selectFirstPay153Accounts() {
  const limit = Math.max(1, Math.floor(Number(pay153QuickSelectCount.value || 0)))
  selectedPay153AccountEmails.value = new Set(pay153LinkAccountOptions.value.filter(item => paymentLinkAccountSelectable(item, pay153PaymentAccountStatus)).slice(0, limit).map(item => item.email))
}
function togglePay153LinkSortOrder() {
  pay153LinkSortOrder.value = pay153LinkSortOrder.value === 'desc' ? 'asc' : 'desc'
}
function clearSelectedPay153Accounts() {
  selectedPay153AccountEmails.value = new Set()
}
function currentPay153BaPayload() {
  const selectedEmail = pay153SelectedEmails.value[0] || ''
  const selected = selectedEmail ? pay153LinkAccountOptions.value.find(item => item.email === selectedEmail) : null
  const manualPaypalLinks = selectedPay153BaItems.value.length ? selectedPay153BaItems.value.map(item => item.paypalLink) : parseManualPaypalLinks(pay153Form.value.paypalLink)
  return {
    paypalLink: selected?.paypalLink || manualPaypalLinks[0] || '',
    baToken: displayBaToken(selected?.paypalLink || manualPaypalLinks[0] || ''),
  }
}
function validatePay153Payment(targetEmails = pay153SelectedEmails.value) {
  const batchCount = Array.isArray(targetEmails) ? targetEmails.length : 0
  const activeAutoPayEmails = new Set(pay153AutoPayActiveJobs.value.map(item => String(item.email || '').trim().toLowerCase()))
  const duplicateEmail = (targetEmails || []).find(email => activeAutoPayEmails.has(String(email || '').trim().toLowerCase()))
  if (duplicateEmail) { setPay153Status(`账号 ${duplicateEmail} 已有153自动支付任务，不能重复提交。`, true); return false }
  if (!batchCount && !selectedPay153BaItems.value.length && directPay153BaLinks.value.length) {
    importBaLinksToPool('pay153', { silent: true, select: true })
  }
  const manualPaypalLinks = batchCount ? [] : selectedPay153BaItems.value.map(item => item.paypalLink)
  const manualLinkCount = manualPaypalLinks.length
  const phoneCount = splitProtocolLines(pay153Form.value.phone).length
  const phonePoolCount = phonePoolReuseEnabled.value ? parsePay153PhonePoolLines(pay153Form.value.phonePool).length : usablePhonePoolEntriesFromText(pay153Form.value.phonePool, 'pay153').length
  const proxyCount = splitProtocolLines(pay153Form.value.proxies).length
  pay153Form.value.country = String(pay153Form.value.country || 'AUTO').trim().toUpperCase()
  if (pay153Form.value.country !== 'AUTO' && !/^[A-Z]{2}$/.test(pay153Form.value.country)) pay153Form.value.country = 'AUTO'
  pay153Form.value.smsProvider = String(pay153Form.value.smsProvider || 'sms_record').trim().toLowerCase().replace(/-/g, '_')
  if (!['sms_record', 'hero_sms', 'hero_sms_rent', 'smsbower'].includes(pay153Form.value.smsProvider)) pay153Form.value.smsProvider = 'sms_record'
  pay153Form.value.buyerMode = ['identity_elevation', 'original'].includes(pay153Form.value.buyerMode) ? pay153Form.value.buyerMode : 'identity_elevation'
  pay153Form.value.concurrency = Math.max(1, Math.min(10, Number(pay153Form.value.concurrency || 1)))
  pay153Form.value.smsRecordWaitSeconds = Math.max(30, Math.min(900, Number(pay153Form.value.smsRecordWaitSeconds || 300)))
  pay153Form.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(pay153Form.value.smsRecordPollSeconds || 3)))
  const requiredPaymentCount = batchCount || manualLinkCount
  if (!requiredPaymentCount) { setPay153Status('请选择要使用 153支付 的已成功提链账号，或填写有效 BA 链接。', true); return false }
  if (pay153Form.value.smsProvider === 'sms_record') {
    if (phonePoolCount < requiredPaymentCount) { setPay153Status('153支付号池数量不足；请按“手机号----SMS record URL”每行导入一个号码。', true); return false }
  } else if (pay153Form.value.smsProvider === 'hero_sms_rent' && phoneCount < requiredPaymentCount) {
    setPay153Status('HeroSMS 长效号 153支付批量提交时，每个账号或 BA 链接都需要一行长效号码。', true); return false
  }
  if (!proxyCount) { setPay153Status('请填写153支付代理池。', true); return false }
  if (proxyCount > 500) { setPay153Status('153支付代理池最多支持 500 条。', true); return false }
  return true
}
async function startPay153Payment(options = {}) {
  if (pay153Canceling.value) {
    setPay153Status('153取消或清理仍在进行，暂不能启动新支付。', true)
    return false
  }
  if (pay153RecoveryPaused.value) {
    setPay153Status('已有结果未知的153支付提交；请先继续确认，或核对远端后解除占用。', true)
    return false
  }
  pay153SubmissionCancelRequested = false
  const selectedEmails = (Array.isArray(options.autoBatchEmails) ? options.autoBatchEmails : pay153SelectedEmails.value).filter(email => pay153LinkSelectableEmails.value.has(email))
  if (Array.isArray(options.autoBatchEmails)) selectedPay153AccountEmails.value = new Set(selectedEmails)
  if (!validatePay153Payment(selectedEmails)) return false
  const pay153BaItems = selectedEmails.length ? [] : selectedPay153BaItems.value
  const manualPaypalLinks = pay153BaItems.map(item => item.paypalLink)
  const paymentCount = manualPaypalLinks.length || selectedEmails.length
  pay153Busy.value = true
  pay153Canceling.value = false
  pay153Logs.value = []
  pay153Result.value = null
  pay153Job.value = null
  activeTab.value = 'pay153'
  if (pay153BaItems.length) setBaPoolStatus('pay153', pay153BaItems.map(item => item.id), 'running')
  setPay153Status('153支付任务已提交，正在创建远端任务。')
  const claimedPhonePoolEntries = pay153Form.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(pay153Form.value.phonePool, paymentCount, 'pay153') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(item => item.key).filter(Boolean)
  const clientRequestId = createPaypalClientRequestId('pay153-manual', selectedEmails[0] || manualPaypalLinks[0] || 'manual')
  savePay153Form({ silent: true })
  const submitPayload = {
    accountEmails: selectedEmails,
    paypalLinks: manualPaypalLinks,
    country: pay153Form.value.country,
    smsProvider: pay153Form.value.smsProvider,
    phone: pay153Form.value.phone,
    phonePool: pay153Form.value.smsProvider === 'sms_record' ? (phonePoolReuseEnabled.value ? phonePoolPayloadForSubmission(pay153Form.value.phonePool, 'pay153') : formatPhonePoolEntries(claimedPhonePoolEntries)) : pay153Form.value.phonePool,
    smsRecordUrl: pay153Form.value.smsRecordUrl,
    proxies: pay153Form.value.proxies,
    buyerMode: pay153Form.value.buyerMode,
    concurrency: pay153Form.value.concurrency,
    smsRecordWaitSeconds: pay153Form.value.smsRecordWaitSeconds,
    smsRecordPollSeconds: pay153Form.value.smsRecordPollSeconds,
    phonePoolReuseEnabled: phonePoolReuseEnabled.value,
    clientRequestId,
  }
  const checkpoint = { clientRequestId, submitPayload, accountCount: paymentCount, concurrency: pay153Form.value.concurrency, startedAt: Date.now(), claimedPhonePoolKeys }
  pay153RecoveryCheckpoint.value = checkpoint
  persistPay153JobState(checkpoint, { force: true })
  try {
    const data = await submitPay153ManualJob(submitPayload, checkpoint)
    if (!data) return false
    if (!data.job_id) throw missingPaymentJobIdError('后端没有返回153支付任务 ID')
    if (claimedPhonePoolKeys.length) pay153ClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    pay153Job.value = { id: data.job_id, status: 'queued', total: paymentCount, completed: 0, concurrency: pay153Form.value.concurrency, children: {} }
    pay153RecoveryCheckpoint.value = null
    pay153RecoveryPaused.value = false
    persistPay153JobState({ ...checkpoint, jobId: data.job_id, clientRequestId: '', submitPayload: null, unknownOutcome: false, recoveryPaused: false, retryAttempts: 0 }, { force: true })
    if (pay153SubmissionCancelRequested) {
      await cancelPay153Job()
      await pollPay153Job(data.job_id)
      return false
    }
    await pollPay153Job(data.job_id)
    return true
  } catch (error) {
    if (pay153BaItems.length) setBaPoolStatus('pay153', pay153BaItems.map(item => item.id), 'failed', cleanError(error))
    releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', claimedPhonePoolKeys, pay153Form.value.phonePool)
    setPay153Status(cleanError(error), true)
    if (pay153Job.value?.id) persistPay153JobState()
    else {
      pay153RecoveryCheckpoint.value = null
      pay153RecoveryPaused.value = false
      storageWriter.remove(PAY153_JOB_STORAGE_KEY)
    }
    return false
  } finally {
    pay153Busy.value = false
    pay153Canceling.value = false
    void drainPay153AutoPayQueue()
  }
}
async function retryFailedPay153Payment() {
  const failedEmails = pay153FailedEmails.value
  if (!failedEmails.length) {
    setPay153Status('上一轮153支付没有失败账号。', true)
    return
  }
  await refreshAccounts()
  await refreshLinks()
  const retryable = new Set(successfulPayPalLinkAccounts(accounts.value, links.value, 'all').filter(item => paymentLinkAccountSelectable(item, pay153PaymentAccountStatus)).map(item => item.email))
  const retryEmails = failedEmails.filter(email => retryable.has(email))
  if (!retryEmails.length) {
    setPay153Status('上一轮失败账号已支付或无 BA 链，无法重试。', true)
    return
  }
  selectedPay153AccountEmails.value = new Set(retryEmails)
  setPay153Status(`已选择上一轮失败账号 ${retryEmails.length} 个，正在重试153支付。`)
  await startPay153Payment()
}
async function cancelPay153RemoteByCurrentBa() {
  if (pay153Canceling.value) return
  if (pay153Busy.value || pay153AutoPayActive.value || pay153AutoPayActiveJobs.value.length) {
    setPay153Status('请先停止正在运行的153手动或自动支付，再清理远端 BA 任务。', true)
    return
  }
  const payload = currentPay153BaPayload()
  if (!payload.paypalLink && !payload.baToken) {
    setPay153Status('请先在153支付链接列表选择一个要清理的 BA。', true)
    return
  }
  const targetBaToken = String(payload.baToken || displayBaToken(payload.paypalLink)).trim()
  const targetBaIds = pay153BaPool.value
    .filter(item => displayBaToken(item.baToken || item.paypalLink).toUpperCase() === targetBaToken.toUpperCase())
    .map(item => item.id)
  pay153Canceling.value = true
  try {
    const data = await api.cancelUsPaypal153RemoteByBa(payload)
    const cancelled = Array.isArray(data.remote_cancelled) ? data.remote_cancelled : []
    setPay153Status(cancelled.length ? `已清理153卡住任务：${cancelled.join(', ')}` : `没有找到可清理的153远端任务：${data.ba_token || payload.baToken}`)
  } catch (error) {
    if (isAmbiguousPaymentFailure(error)) {
      const checkpoint = {
        cleanupByBa: true,
        baToken: targetBaToken,
        paypalLink: payload.paypalLink,
        submitPayload: { paypalLinks: [payload.paypalLink].filter(Boolean), accountEmails: [] },
        recoveryPaused: true,
        unknownOutcome: true,
        claimedPhonePoolKeys: [],
      }
      pay153RecoveryPaused.value = true
      pay153RecoveryCheckpoint.value = checkpoint
      if (targetBaIds.length) setBaPoolStatus('pay153', targetBaIds, 'unknown_outcome', cleanError(error))
      setPay153Status(`清理153卡住任务结果未知：${cleanError(error)}；BA 已保持隔离，请核对远端后人工解除。`, true)
      persistPay153JobState(checkpoint, { force: true })
    } else {
      setPay153Status(`清理153卡住任务失败：${cleanError(error)}`, true)
    }
  } finally {
    pay153Canceling.value = false
  }
}
async function pollPay153Job(jobId) {
  let pollingFailureCount = 0
  for (;;) {
    if (componentUnmounted) return
    if (!await paypalPolling.waitUntilAvailable()) return
    if (componentUnmounted) return
    const recovery = await readPollingSnapshot({
      request: () => api.getUsPaypal153Job(jobId),
      wait: delayMs => paypalPolling.wait(delayMs),
      attempt: pollingFailureCount,
      onTransientError: (error, delayMs) => {
        if (componentUnmounted) return
        persistPay153JobState({ jobId })
        setPay153Status(`153支付状态查询失败：${cleanError(error)}；任务和手机号占用已保留，${Math.ceil(delayMs / 1000)} 秒后重试。`, true)
      },
    })
    if (componentUnmounted) return
    if (recovery.kind === 'retry') {
      pollingFailureCount = recovery.attempt
      continue
    }
    if (recovery.kind === 'missing') {
      pay153Job.value = { ...(pay153Job.value || {}), id: jobId, status: 'unknown_outcome', error: cleanError(recovery.error) }
      pay153RecoveryPaused.value = true
      pay153RecoveryCheckpoint.value = { jobId, recoveryPaused: true, unknownOutcome: true, accountEmails: [...pay153SelectedEmails.value], claimedPhonePoolKeys: pay153ClaimedPhonePoolKeysByJob.get(jobId) || [] }
      setPay153Status('153支付任务已无法从后端定位；结果未知，账号与手机号占用保持隔离，请人工核对。', true)
      persistPay153JobState(pay153RecoveryCheckpoint.value, { force: true })
      return
    }
    if (['permanent', 'paused'].includes(recovery.kind)) {
      pay153Job.value = { ...(pay153Job.value || {}), id: jobId, status: 'recovery_paused' }
      pay153RecoveryPaused.value = true
      pay153RecoveryCheckpoint.value = { jobId, recoveryPaused: true, unknownOutcome: true, accountEmails: [...pay153SelectedEmails.value], claimedPhonePoolKeys: pay153ClaimedPhonePoolKeysByJob.get(jobId) || [] }
      const reason = recovery.kind === 'permanent' ? `服务端拒绝状态查询：${cleanError(recovery.error)}` : `连续查询失败 ${recovery.attempt} 次`
      setPay153Status(`153支付${reason}；已暂停查询并保留任务、账号与手机号占用。`, true)
      persistPay153JobState(pay153RecoveryCheckpoint.value, { force: true })
      return
    }
    if (recovery.kind !== 'snapshot') return
    if (componentUnmounted) return
    pollingFailureCount = 0
    const job = recovery.value
    pay153Job.value = job
    if (pay153RecoveryPaused.value) {
      pay153RecoveryPaused.value = false
      pay153RecoveryCheckpoint.value = null
      persistPay153JobState({ jobId, recoveryPaused: false, unknownOutcome: false }, { force: true })
    }
    pay153Logs.value = Array.isArray(job.logs) ? job.logs.slice(-200) : []
    pay153Result.value = job.result || null
    syncBaPoolFromJob('pay153', job)
    await nextTick()
    if (pay153LogRef.value) pay153LogRef.value.scrollTop = pay153LogRef.value.scrollHeight
    if (job.status === 'unknown_outcome') {
      pay153RecoveryPaused.value = true
      pay153RecoveryCheckpoint.value = { jobId, recoveryPaused: true, unknownOutcome: true, claimedPhonePoolKeys: pay153ClaimedPhonePoolKeysByJob.get(jobId) || [] }
      setPay153Status(job.error || '服务重启后153支付结果未知；手机号占用保持隔离，请核对远端状态。', true)
      persistPay153JobState(pay153RecoveryCheckpoint.value, { force: true })
      return
    }
    if (job.status === 'success') {
      syncPhonePoolStatusFromJobResult(job.result || {}, 'pay153')
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'pay153', pay153ClaimedPhonePoolKeysByJob.get(jobId) || [], pay153Form.value.phonePool)
      setPay153Status(`153支付完成，已完成 ${job.completed || 0}/${job.total || 0}。`)
      persistPay153JobState({ jobId })
      await refreshAccounts()
      void drainPay153AutoPayQueue()
      return
    }
    if (job.status === 'cancelled') {
      syncPhonePoolStatusFromJobResult(job.result || {}, 'pay153')
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'pay153', pay153ClaimedPhonePoolKeysByJob.get(jobId) || [], pay153Form.value.phonePool)
      setPay153Status('153支付任务已取消。')
      persistPay153JobState({ jobId })
      void drainPay153AutoPayQueue()
      return
    }
    if (job.status === 'error' || job.status === 'failed') {
      syncPhonePoolStatusFromJobResult(job.result || {}, 'pay153')
      releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'pay153', pay153ClaimedPhonePoolKeysByJob.get(jobId) || [], pay153Form.value.phonePool)
      setPay153Status(job.error || '153支付失败', true)
      persistPay153JobState({ jobId })
      void drainPay153AutoPayQueue()
      throw new Error(job.error || '153支付失败')
    }
    const total = Number(job.total || 0)
    const completed = Number(job.completed || 0)
    const waiting = pay153WaitingActions.value.length
    setPay153Status(waiting ? `153支付等待操作 ${waiting} 个账号，已完成 ${completed}/${total}。` : `153支付执行中，已完成 ${completed}/${total}，已记录 ${pay153Logs.value.length} 条日志。`)
    persistPay153JobState({ jobId, accountCount: total || 1, concurrency: job.concurrency || pay153Form.value.concurrency })
    if (!await paypalPolling.wait(1000)) return
  }
}
async function submitPay153Otp(child) {
  const remoteJobId = child?.remote_job_id
  const value = String(pay153ActionInputs.value[remoteJobId] || '').trim()
  if (!pay153Job.value?.id || !remoteJobId || !value) return
  try {
    const data = await api.submitUsPaypal153Otp(pay153Job.value.id, { remoteJobId, value })
    if (data.job) pay153Job.value = data.job
    pay153ActionInputs.value = { ...pay153ActionInputs.value, [remoteJobId]: '' }
    setPay153Status(`已提交 ${child.email || remoteJobId} 的验证码。`)
  } catch (error) {
    setPay153Status(`提交验证码失败：${cleanError(error)}`, true)
  }
}
async function submitPay153Captcha(child) {
  const remoteJobId = child?.remote_job_id
  const value = String(pay153ActionInputs.value[remoteJobId] || '').trim()
  if (!pay153Job.value?.id || !remoteJobId || !value) return
  try {
    const data = await api.submitUsPaypal153Captcha(pay153Job.value.id, { remoteJobId, value })
    if (data.job) pay153Job.value = data.job
    pay153ActionInputs.value = { ...pay153ActionInputs.value, [remoteJobId]: '' }
    setPay153Status(`已提交 ${child.email || remoteJobId} 的验证结果。`)
  } catch (error) {
    setPay153Status(`提交验证结果失败：${cleanError(error)}`, true)
  }
}
async function cancelPay153Job() {
  const jobId = pay153Job.value?.id
  if (pay153Canceling.value) return
  pay153SubmissionGuard.cancel()
  if (!jobId) {
    pay153SubmissionCancelRequested = true
    pay153RecoveryPaused.value = true
    const checkpoint = pay153RecoveryCheckpoint.value
    if (checkpoint) {
      pay153RecoveryCheckpoint.value = { ...checkpoint, recoveryPaused: true }
      persistPay153JobState(pay153RecoveryCheckpoint.value, { force: true })
    }
    setPay153Status('已暂停提交确认；任务和手机号占用继续保留。', true)
    return
  }
  pay153Canceling.value = true
  try {
    await api.cancelUsPaypal153Job(jobId)
    setPay153Status('已发送取消请求，正在终止153远端任务。')
  } catch (error) {
    if (isAmbiguousPaymentFailure(error)) {
      const checkpoint = { jobId, recoveryPaused: true, unknownOutcome: true, accountEmails: [...pay153SelectedEmails.value], claimedPhonePoolKeys: pay153ClaimedPhonePoolKeysByJob.get(jobId) || [] }
      pay153RecoveryPaused.value = true
      pay153RecoveryCheckpoint.value = checkpoint
      setPay153Status(`取消请求结果未知：${cleanError(error)}；任务、账号与手机号占用继续保留并等待状态核对。`, true)
      persistPay153JobState(checkpoint, { force: true })
    } else {
      setPay153Status(`取消失败：${cleanError(error)}`, true)
      pay153Canceling.value = false
    }
  }
}

onMounted(async () => {
  componentUnmounted = false
  let preferredActiveTab = activeTab.value
  try {
    const savedForm = JSON.parse(sessionStorageFacade.getItem(FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(form.value)) {
      if (savedForm[key] !== undefined) form.value[key] = savedForm[key]
    }
    form.value.concurrency = Math.max(1, Math.min(30, Number(form.value.concurrency || 1)))
    form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
    form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  } catch { /* ignore malformed local state */ }
  try {
    const savedPool = JSON.parse(sessionStorageFacade.getItem(ACCESS_TOKEN_POOL_STORAGE_KEY) || '[]')
    accessTokenPool.value = Array.isArray(savedPool)
      ? savedPool.map((item, index) => {
        const token = cleanAccessToken(item?.token || '')
        if (!token) return null
        return {
          id: String(item?.id || accessTokenFingerprint(token)),
          token,
          label: String(item?.label || decodeAccessTokenEmail(token) || `access-token-${String(index + 1).padStart(3, '0')}`).trim(),
          masked: String(item?.masked || maskAccessToken(token)),
          status: String(item?.status || 'pending').trim().toLowerCase(),
          error: String(item?.error || ''),
          updatedAt: String(item?.updatedAt || ''),
        }
      }).filter(Boolean)
      : []
  } catch { /* ignore malformed token pool */ }
  try {
    const loadBaPool = (storageKey, fallbackCountry) => {
      const saved = JSON.parse(sessionStorageFacade.getItem(storageKey) || '[]')
      if (!Array.isArray(saved)) return []
      return saved.map((item) => {
        const token = displayBaToken(item?.baToken || item?.label || item?.paypalLink || '')
        const link = baPoolLink(item?.paypalLink || token)
        if (!token || !link) return null
        return {
          id: String(item?.id || baPoolId(token)),
          label: token,
          baToken: token,
          paypalLink: link,
          country: String(item?.country || fallbackCountry || 'US').trim().toUpperCase(),
          status: String(item?.status || 'pending').trim().toLowerCase(),
          error: String(item?.error || ''),
          updatedAt: String(item?.updatedAt || ''),
        }
      }).filter(Boolean)
    }
    protocolBaPool.value = loadBaPool(PROTOCOL_BA_POOL_STORAGE_KEY, protocolForm.value.country)
    pay153BaPool.value = loadBaPool(PAY153_BA_POOL_STORAGE_KEY, pay153Form.value.country === 'AUTO' ? 'US' : pay153Form.value.country)
  } catch { /* ignore malformed BA pool */ }
  try {
    const savedReuse = sessionStorageFacade.getItem(PHONE_POOL_REUSE_STORAGE_KEY)
    if (savedReuse !== null) phonePoolReuseEnabled.value = savedReuse === '1' || savedReuse === 'true'
  } catch { /* ignore malformed reuse state */ }
  try {
    const savedTab = String(sessionStorageFacade.getItem(ACTIVE_TAB_STORAGE_KEY) || '').trim()
    if (['links', 'protocol', 'pay153'].includes(savedTab)) {
      activeTab.value = savedTab
      preferredActiveTab = savedTab
    }
  } catch { /* ignore malformed active tab */ }
  try {
    const savedProtocolForm = JSON.parse(sessionStorageFacade.getItem(PROTOCOL_FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(protocolForm.value)) {
      if (savedProtocolForm[key] !== undefined) protocolForm.value[key] = savedProtocolForm[key]
    }
    protocolForm.value.smsProvider = String(protocolForm.value.smsProvider || 'sms_record').trim().toLowerCase().replace(/-/g, '_')
    if (!['sms_record', 'hero_sms', 'hero_sms_rent', 'smsbower'].includes(protocolForm.value.smsProvider)) protocolForm.value.smsProvider = 'sms_record'
    if (!String(protocolForm.value.phonePool || '').trim() && String(protocolForm.value.phone || '').trim() && String(protocolForm.value.smsRecordUrl || '').trim()) {
      const phones = splitProtocolLines(protocolForm.value.phone)
      const urls = splitProtocolLines(protocolForm.value.smsRecordUrl)
      protocolForm.value.phonePool = phones.map((phone, index) => urls[index] ? `${phone}----${urls[index]}` : '').filter(Boolean).join('\n')
    }
    protocolForm.value.concurrency = Math.max(1, Math.min(20, Number(protocolForm.value.concurrency || 1)))
    protocolForm.value.smsRecordWaitSeconds = Math.max(60, Math.min(900, Number(protocolForm.value.smsRecordWaitSeconds || 300)))
    protocolForm.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(protocolForm.value.smsRecordPollSeconds || 3)))
    protocolForm.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(protocolForm.value.proxyPreflightAttempts || 5)))
  } catch { /* ignore malformed protocol state */ }
  try {
    const savedPay153Form = JSON.parse(sessionStorageFacade.getItem(PAY153_FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(pay153Form.value)) {
      if (savedPay153Form[key] !== undefined) pay153Form.value[key] = savedPay153Form[key]
    }
    pay153Form.value.country = String(pay153Form.value.country || 'AUTO').trim().toUpperCase()
    if (pay153Form.value.country !== 'AUTO' && !/^[A-Z]{2}$/.test(pay153Form.value.country)) pay153Form.value.country = 'AUTO'
    pay153Form.value.smsProvider = String(pay153Form.value.smsProvider || 'sms_record').trim().toLowerCase().replace(/-/g, '_')
    if (!['sms_record', 'hero_sms', 'hero_sms_rent', 'smsbower'].includes(pay153Form.value.smsProvider)) pay153Form.value.smsProvider = 'sms_record'
    if (!String(pay153Form.value.phonePool || '').trim() && String(pay153Form.value.phone || '').trim() && String(pay153Form.value.smsRecordUrl || '').trim()) {
      const phones = splitProtocolLines(pay153Form.value.phone)
      const urls = splitProtocolLines(pay153Form.value.smsRecordUrl)
      pay153Form.value.phonePool = phones.map((phone, index) => urls[index] ? `${phone}----${urls[index]}` : '').filter(Boolean).join('\n')
    }
    pay153Form.value.buyerMode = ['identity_elevation', 'original'].includes(pay153Form.value.buyerMode) ? pay153Form.value.buyerMode : 'identity_elevation'
    pay153Form.value.concurrency = Math.max(1, Math.min(10, Number(pay153Form.value.concurrency || 1)))
    pay153Form.value.smsRecordWaitSeconds = Math.max(30, Math.min(900, Number(pay153Form.value.smsRecordWaitSeconds || 300)))
    pay153Form.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(pay153Form.value.smsRecordPollSeconds || 3)))
  } catch { /* ignore malformed 153 state */ }
  try {
    const savedPhonePool = JSON.parse(sessionStorageFacade.getItem(PHONE_POOL_MANAGEMENT_STORAGE_KEY) || '{}')
    phonePoolStatusMap.value = savedPhonePool.statuses && typeof savedPhonePool.statuses === 'object' ? savedPhonePool.statuses : {}
  } catch { /* ignore malformed phone pool state */ }
  await reloadAll()
  restorePaypalAutoPayState()
  try {
    resumeLinkJobStateFromStorage({ force: true, preferredActiveTab })
  } catch (error) {
    busy.value = false
    setStatus(`恢复提链任务失败：${cleanError(error)}`, true)
    persistLinkJobState()
  }
  try {
    resumeProtocolJobStateFromStorage({ force: true, preferredActiveTab })
  } catch (error) {
    protocolBusy.value = false
    setProtocolStatus(`恢复协议支付失败：${cleanError(error)}`, true)
    persistProtocolJobState()
  }
  try {
    resumePay153JobStateFromStorage({ force: true, preferredActiveTab })
  } catch (error) {
    pay153Busy.value = false
    setPay153Status(`恢复153支付失败：${cleanError(error)}`, true)
    persistPay153JobState()
  }
})

watch(form, () => storageWriter.queueJson(FORM_STORAGE_KEY, () => form.value), { deep: true })
watch(accessTokenPool, () => saveAccessTokenPool(), { deep: true })
watch(protocolBaPool, () => saveBaPool('protocol'), { deep: true })
watch(pay153BaPool, () => saveBaPool('pay153'), { deep: true })
watch(activeTab, value => sessionStorageFacade.setItem(ACTIVE_TAB_STORAGE_KEY, value))
watch(phonePoolReuseEnabled, value => sessionStorageFacade.setItem(PHONE_POOL_REUSE_STORAGE_KEY, value ? '1' : '0'))
watch(protocolForm, () => storageWriter.queueJson(PROTOCOL_FORM_STORAGE_KEY, () => protocolForm.value), { deep: true })
watch(pay153Form, () => storageWriter.queueJson(PAY153_FORM_STORAGE_KEY, () => pay153Form.value), { deep: true })
watch([accountFilter, accountStatusFilter, accountCountryFilter], () => { accountVisibleCount.value = 100 })
watch(accessTokenPool, () => { accessTokenVisibleCount.value = 100 })
watch(links, () => { linkVisibleCount.value = 100 })
watch(protocolBaPool, () => { protocolBaVisibleCount.value = 100 })
watch(pay153BaPool, () => { pay153BaVisibleCount.value = 100 })
watch(currentResult, () => { recentResultVisibleCount.value = 100 })
watch(accessTokenStatusFilter, () => { accessTokenVisibleCount.value = 100 })
watch(linkCountryFilter, () => { linkVisibleCount.value = 100 })
watch(protocolBaStatusFilter, () => { protocolBaVisibleCount.value = 100 })
watch(pay153BaStatusFilter, () => { pay153BaVisibleCount.value = 100 })
watch(recentResultFilter, () => { recentResultVisibleCount.value = 100 })
watch(() => protocolForm.value.phonePool, () => { protocolPhoneVisibleCount.value = 100 })
watch(() => pay153Form.value.phonePool, () => { pay153PhoneVisibleCount.value = 100 })
watch(activeTab, (tab) => {
  if (tab === 'links') resumeLinkJobStateFromStorage()
  if (tab === 'protocol' || tab === 'pay153') refreshPaymentLinks()
  if (tab === 'protocol') resumeProtocolJobStateFromStorage()
  if (tab === 'pay153') resumePay153JobStateFromStorage()
})
watch(protocolLinkCountryFilter, () => {
  protocolLinkVisibleCount.value = 100
  if (selectedProtocolAccountEmail.value && !protocolLinkSelectableEmails.value.has(selectedProtocolAccountEmail.value)) {
    selectedProtocolAccountEmail.value = ''
  }
  const available = protocolLinkSelectableEmails.value
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => available.has(email)))
})
watch(protocolLinkTimeFilter, () => {
  protocolLinkVisibleCount.value = 100
  const available = protocolLinkSelectableEmails.value
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => available.has(email)))
})
watch(protocolLinkStatusFilter, () => {
  protocolLinkVisibleCount.value = 100
  const available = protocolLinkSelectableEmails.value
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => available.has(email)))
})
watch(pay153LinkCountryFilter, () => {
  pay153LinkVisibleCount.value = 100
  const available = pay153LinkSelectableEmails.value
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => available.has(email)))
})
watch(pay153LinkTimeFilter, () => {
  pay153LinkVisibleCount.value = 100
  const available = pay153LinkSelectableEmails.value
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => available.has(email)))
})
watch(pay153LinkStatusFilter, () => {
  pay153LinkVisibleCount.value = 100
  const available = pay153LinkSelectableEmails.value
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => available.has(email)))
})
watch(protocolLinkSortOrder, () => { protocolLinkVisibleCount.value = 100 })
watch(pay153LinkSortOrder, () => { pay153LinkVisibleCount.value = 100 })
watch([accounts, links], () => {
  protocolLinkVisibleCount.value = 100
  pay153LinkVisibleCount.value = 100
})
watch([accounts, links], () => {
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => protocolLinkSelectableEmails.value.has(email)))
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => pay153LinkSelectableEmails.value.has(email)))
}, { deep: true })
watch(phonePoolStatusMap, () => {
  storageWriter.queueJson(PHONE_POOL_MANAGEMENT_STORAGE_KEY, () => ({
    statuses: phonePoolStatusMap.value,
  }))
}, { deep: true })

onBeforeUnmount(() => {
  componentUnmounted = true
  paypalPolling.dispose()
  stopProtocolAutoPay('协议自动支付已随页面关闭停止。')
  stopPay153AutoPay('153自动支付已随页面关闭停止。')
  persistPaypalAutoPayState({ force: true })
  persistLinkJobState({}, { force: true })
  persistProtocolJobState({}, { force: true })
  persistPay153JobState({}, { force: true })
  storageWriter.dispose()
})
const visibleRecentResultSuccesses = computed(() => {
  if (recentResultFilter.value === 'failed') return []
  return currentResultSuccesses.value.slice(0, recentResultVisibleCount.value)
})
const visibleRecentResultErrors = computed(() => {
  if (recentResultFilter.value === 'success') return []
  const remaining = recentResultFilter.value === 'failed'
    ? recentResultVisibleCount.value
    : Math.max(0, recentResultVisibleCount.value - visibleRecentResultSuccesses.value.length)
  return currentResultErrors.value.slice(0, remaining)
})
const visibleRecentResultSkipped = computed(() => {
  if (recentResultFilter.value !== 'all') return []
  const remaining = Math.max(0, recentResultVisibleCount.value - visibleRecentResultSuccesses.value.length - visibleRecentResultErrors.value.length)
  return currentResultSkipped.value.slice(0, remaining)
})
const visibleRecentResultCount = computed(() => visibleRecentResultSuccesses.value.length + visibleRecentResultErrors.value.length + visibleRecentResultSkipped.value.length)
const hiddenRecentResultCount = computed(() => Math.max(0, filteredRecentResultCount.value - visibleRecentResultCount.value))
</script>
