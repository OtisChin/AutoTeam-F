<template>
  <div class="space-y-5">
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
              <span class="mt-1 block text-xs text-gray-500">promo 后注入阶段使用优惠区代理，默认 JP。</span>
            </label>
          </div>

          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">代理</span>
            <textarea v-model.trim="form.proxies" rows="3" spellcheck="false" placeholder="global.rotgb.711proxy.com:10000:USER-zone-custom-region-US-session-xxxx-sessTime-180-sessAuto-1:pass" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" :disabled="busy"></textarea>
            <span class="mt-1 block text-xs text-gray-500">填一条代理即可；后端会按目标国家/优惠区自动切换 region 和 sid。兼容 711、ArxLabs 等 host:port:user:pass 或 URL 格式。</span>
          </label>

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
              {{ busy ? '提取中...' : `开始提链 (${selectedEmails.length})` }}
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
            <div v-if="recentResultFilter !== 'failed'" v-for="item in currentResultSuccesses" :key="item.email" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
              <div class="font-mono text-emerald-200">{{ item.email }}</div>
              <div class="mt-1 text-[11px] text-emerald-300/80">国家：{{ linkCountry(item.link) }}</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!(item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url) ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制链</button>
              </div>
            </div>
            <div v-if="recentResultFilter !== 'success'" v-for="item in currentResultErrors" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {{ item.email }}：{{ item.error }}
            </div>
            <div v-if="recentResultFilter === 'all'" v-for="item in currentResultSkipped" :key="item.email" class="rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-2 text-xs text-gray-300">
              {{ item.email }}：{{ item.reason || '已跳过' }}
            </div>
            <div v-if="!filteredRecentResultCount" class="rounded-lg border border-gray-800 bg-gray-900/60 px-3 py-8 text-center text-xs text-gray-500">当前筛选下暂无结果</div>
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
            <tr v-for="link in filteredLinks" :key="link.id" class="hover:bg-gray-900/50">
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
                <div class="grid gap-3 md:grid-cols-[160px_160px_minmax(0,1fr)]">
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
                    <span class="mb-1.5 block text-xs font-semibold text-indigo-200">已成功提链账号</span>
                    <select v-model="selectedProtocolAccountEmail" @change="applySelectedProtocolAccount" class="w-full rounded-lg border border-indigo-500/30 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-400 focus:outline-none" :disabled="protocolBusy || !protocolLinkAccountOptions.length">
                      <option value="">{{ protocolLinkAccountOptions.length ? '选择账号并填入 BA 链' : '暂无符合条件的成功提链账号' }}</option>
                      <option v-for="item in protocolLinkAccountOptions" :key="item.email" :value="item.email" :disabled="item.paypalStatus === 'paid'">
                        {{ item.country }} · {{ linkCreatedAtText(item.link) }} · {{ item.email }}
                      </option>
                    </select>
                  </label>
                </div>
                <div class="mt-3 flex flex-wrap items-center gap-2">
                  <button @click="selectAllProtocolAccounts" :disabled="protocolBusy || !protocolLinkSelectableEmails.size" class="rounded-lg border border-indigo-500/30 bg-indigo-500/10 px-3 py-2 text-xs font-semibold text-indigo-100 hover:bg-indigo-500/20 disabled:opacity-50">全选当前</button>
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
                      <tr v-for="item in protocolLinkAccountOptions" :key="item.email" class="hover:bg-gray-900/60">
                        <td class="px-3 py-2"><input :checked="selectedProtocolAccountEmails.has(item.email)" type="checkbox" class="accent-indigo-500" :disabled="protocolBusy || protocolPaymentAccountStatus(item) === 'paid'" @change="toggleProtocolAccount(item.email)" /></td>
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
                </div>
              </div>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">BA 链接 / BA token</span>
                <textarea v-model.trim="protocolForm.paypalLink" rows="3" spellcheck="false" placeholder="https://www.paypal.com/agreements/approve?ba_token=BA-..." class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
              </label>

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
                        <tr v-if="!phonePoolEntriesFor(protocolForm.phonePool, 'protocol').length">
                          <td colspan="4" class="px-3 py-6 text-center text-gray-500">暂无手机号；点击“加入手机号池”批量导入。</td>
                        </tr>
                        <tr v-for="item in phonePoolEntriesFor(protocolForm.phonePool, 'protocol')" :key="item.key" class="hover:bg-gray-900/60">
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
                  <input v-model.number="protocolForm.concurrency" type="number" min="1" max="10" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                  <span class="mt-1 block text-xs text-gray-500">多选账号时生效，默认 1，最高 10。</span>
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
                <div class="mb-3 flex flex-col gap-3 md:flex-row md:items-center">
                  <select v-model="pay153LinkCountryFilter" class="rounded-lg border border-cyan-500/30 bg-gray-950 px-3 py-2 text-sm text-white focus:border-cyan-400 focus:outline-none" :disabled="pay153Busy">
                    <option value="all">全部国家</option>
                    <option v-for="country in protocolLinkCountryOptions" :key="country" :value="country">{{ country }}</option>
                  </select>
                  <select v-model="pay153LinkTimeFilter" class="rounded-lg border border-cyan-500/30 bg-gray-950 px-3 py-2 text-sm text-white focus:border-cyan-400 focus:outline-none" :disabled="pay153Busy">
                    <option v-for="option in linkTimeFilterOptions" :key="option.value" :value="option.value">{{ option.label }}</option>
                  </select>
                  <button @click="selectAllPay153Accounts" :disabled="pay153Busy || !pay153LinkSelectableEmails.size" class="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">全选当前</button>
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
                      <tr v-for="item in pay153LinkAccountOptions" :key="item.email" class="hover:bg-gray-900/60">
                        <td class="px-3 py-2"><input :checked="selectedPay153AccountEmails.has(item.email)" type="checkbox" class="accent-cyan-500" :disabled="pay153Busy || pay153PaymentAccountStatus(item) === 'paid'" @change="togglePay153Account(item.email)" /></td>
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
                </div>
              </div>

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
                        <tr v-if="!phonePoolEntriesFor(pay153Form.phonePool, 'pay153').length">
                          <td colspan="4" class="px-3 py-6 text-center text-gray-500">暂无手机号；点击“加入手机号池”批量导入。</td>
                        </tr>
                        <tr v-for="item in phonePoolEntriesFor(pay153Form.phonePool, 'pay153')" :key="item.key" class="hover:bg-gray-900/60">
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
                <button @click="startPay153Payment" :disabled="pay153Busy" class="rounded-lg bg-cyan-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-cyan-500 disabled:opacity-50">
                  {{ pay153Busy ? '153支付中...' : `开始153支付 (${pay153SelectedEmails.length})` }}
                </button>
                <button type="button" @click="togglePay153AutoPay" class="rounded-lg border px-4 py-2.5 text-sm font-semibold transition disabled:opacity-50" :class="pay153AutoPayActive ? 'border-rose-500/40 bg-rose-500/10 text-rose-200 hover:bg-rose-500/20' : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-100 hover:bg-cyan-500/20'">
                  {{ pay153AutoPayActive ? `停止自动支付 (${pay153AutoPayQueue.length})` : '自动支付' }}
                </button>
                <button @click="retryFailedPay153Payment" :disabled="pay153Busy || !pay153FailedEmails.length" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50">
                  失败重试{{ pay153FailedEmails.length ? ` (${pay153FailedEmails.length})` : '' }}
                </button>
                <button v-if="pay153Busy" @click="cancelPay153Job" :disabled="pay153Canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
                  {{ pay153Canceling ? '取消中...' : '取消153支付' }}
                </button>
                <button type="button" @click="cancelPay153RemoteByCurrentBa" :disabled="pay153Canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
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
const PROTOCOL_FORM_STORAGE_KEY = 'autotoken_us_paypal_protocol_form'
const PROTOCOL_JOB_STORAGE_KEY = 'autotoken_us_paypal_protocol_job'
const PAY153_FORM_STORAGE_KEY = 'autotoken_us_paypal_153_form'
const PAY153_JOB_STORAGE_KEY = 'autotoken_us_paypal_153_job'
const PHONE_POOL_MANAGEMENT_STORAGE_KEY = 'autotoken_us_paypal_phone_pool_management'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented'])
const AUTO_PAYMENT_POLL_MS = 60 * 1000
const AUTO_PAYMENT_IDLE_LIMIT_MS = 30 * 60 * 1000
const ACCOUNT_STATUS_TEXT = { pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', no_promo: '无优惠', non_oaics: '非Oaics', paid: '已支付' }
const PROTOCOL_COUNTRIES = new Set(['AU', 'BR', 'CA', 'GB', 'ID', 'JP', 'MX', 'PH', 'TH', 'NL', 'US'])
const linkTimeFilterOptions = [
  { value: 'all', label: '全部时间' },
  { value: '15m', label: '最近15分钟' },
  { value: '60m', label: '最近1小时' },
  { value: '180m', label: '最近3小时' },
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
  { value: 'BR', label: 'BR · 巴西' },
  { value: 'ID', label: 'ID · 印度尼西亚' },
  { value: 'VN', label: 'VN · 越南' },
  { value: 'TH', label: 'TH · 泰国' },
  { value: 'PH', label: 'PH · 菲律宾' },
  { value: 'TR', label: 'TR · 土耳其' },
]

const form = ref({
  proxies: '',
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
const protocolLinkCountryFilter = ref('all')
const protocolLinkTimeFilter = ref('all')
const recentResultFilter = ref('all')
const selectedProtocolAccountEmail = ref('')
const selectedProtocolAccountEmails = ref(new Set())
const selectedPay153AccountEmails = ref(new Set())
const PHONE_POOL_REUSE_STORAGE_KEY = 'autotoken-us-paypal-phone-pool-reuse'
const phonePoolReuseEnabled = ref(false)
const phonePoolStatusMap = ref({})
const protocolPhonePoolImportOpen = ref(false)
const pay153PhonePoolImportOpen = ref(false)
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
const protocolLogRef = ref(null)
const protocolAutoPayActive = ref(false)
const protocolAutoPayQueue = ref([])
const protocolAutoPayActiveJobs = ref([])
const protocolAutoPaySeenKeys = ref(new Set())
const protocolAutoPayLastNewAt = ref(0)
const protocolAutoPayStatusText = ref('')
const pay153Form = ref({
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
const pay153LogRef = ref(null)
const pay153AutoPayActive = ref(false)
const pay153AutoPayQueue = ref([])
const pay153AutoPayActiveJobs = ref([])
const pay153AutoPaySeenKeys = ref(new Set())
const pay153AutoPayLastNewAt = ref(0)
const pay153AutoPayStatusText = ref('')
const pay153LinkCountryFilter = ref('all')
const pay153LinkTimeFilter = ref('all')
const pay153ActionInputs = ref({})
let componentUnmounted = false
let protocolAutoPayTimer = null
let pay153AutoPayTimer = null
let protocolAutoPayDraining = false
let pay153AutoPayDraining = false
const protocolAutoPayLogOffsets = new Map()
const pay153AutoPayLogOffsets = new Map()
const protocolClaimedPhonePoolKeysByJob = new Map()
const pay153ClaimedPhonePoolKeysByJob = new Map()

const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const protocolSelectedEmails = computed(() => Array.from(selectedProtocolAccountEmails.value))
const pay153SelectedEmails = computed(() => Array.from(selectedPay153AccountEmails.value))
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
const accountCountryOptions = computed(() => Array.from(new Set(accounts.value.map(accountPaypalCountry).filter(country => country && country !== '-'))).sort())
const linkCountryOptions = computed(() => Array.from(new Set(links.value.map(linkCountry).filter(country => country && country !== '-'))).sort())
const protocolLinkCountryOptions = computed(() => paypalAccountCountryOptions(accounts.value, links.value))
const protocolLinkAccountOptions = computed(() => successfulPayPalLinkAccounts(accounts.value, links.value, protocolLinkCountryFilter.value, { timeFilter: protocolLinkTimeFilter.value }))
const pay153LinkAccountOptions = computed(() => successfulPayPalLinkAccounts(accounts.value, links.value, pay153LinkCountryFilter.value, { timeFilter: pay153LinkTimeFilter.value }))
const currentResultSuccesses = computed(() => Array.isArray(currentResult.value?.successes) ? [...currentResult.value.successes].reverse() : [])
const currentResultErrors = computed(() => Array.isArray(currentResult.value?.errors) ? [...currentResult.value.errors].reverse() : [])
const currentResultSkipped = computed(() => Array.isArray(currentResult.value?.skipped) ? [...currentResult.value.skipped].reverse() : [])
const pay153FailedEmails = computed(() => Array.from(new Set((pay153Result.value?.errors || []).map(item => String(item.email || '').trim()).filter(Boolean))))
const protocolLinkSelectableEmails = computed(() => new Set(protocolLinkAccountOptions.value.filter(item => item.paypalStatus !== 'paid').map(item => item.email)))
const pay153LinkSelectableEmails = computed(() => new Set(pay153LinkAccountOptions.value.filter(item => item.paypalStatus !== 'paid').map(item => item.email)))
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
const activeStatusText = computed(() => {
  if (activeTab.value === 'protocol' && protocolBusy.value) return protocolBadgeText.value
  if (activeTab.value === 'pay153' && pay153Busy.value) return pay153BadgeText.value
  return progressText.value
})

function setStatus(message, error = false) { statusText.value = message; statusError.value = error }
function cleanText(value) { return String(value || '未知错误').replace(/\s+/g, ' ').trim() }
function cleanError(error) { return cleanText(error?.message || error) }
function persistLinkJobState(fallback = {}) {
  const payload = paymentJobSnapshot(currentJob.value?.id || fallback.jobId, currentJob.value, logs.value, currentResult.value, statusText.value, statusError.value, fallback)
  if (payload.jobId || payload.logs.length || payload.result) localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify(payload))
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
      saved = JSON.parse(localStorage.getItem(JOB_STORAGE_KEY) || '{}')
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
function accountStatusClass(account) { const status = accountStatus(account); return ({ running: 'border-blue-500/30 bg-blue-500/10 text-blue-300', success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300', failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300', no_promo: 'border-amber-500/30 bg-amber-500/10 text-amber-200', non_oaics: 'border-slate-500/30 bg-slate-500/10 text-slate-300', paid: 'border-violet-500/30 bg-violet-500/10 text-violet-300' })[status] || 'border-gray-700 bg-gray-900 text-gray-400' }
function accountStatusError(account) { return accountJobStatus(account)?.error || account.paypal_error || '' }
function accountSelectable(account) { return account.paypal_selectable !== false && accountStatus(account) !== 'paid' }
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
  if (status === 'paid') return '已支付'
  if (status === 'failed' || status === 'error') return '支付失败'
  if (status === 'pending') return '未提链'
  return '已提链'
}
function paymentAccountStatusClass(status) {
  if (status === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'paid') return 'border-violet-500/30 bg-violet-500/10 text-violet-300'
  if (status === 'failed' || status === 'error') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
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

function validateStart(emails = selectedEmails.value) {
  if (!emails.length) {
    setStatus('请在账号池中选择至少一个账号。', true)
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
  const accountEmails = Array.from(new Set((emails || []).map(email => String(email || '').trim()).filter(Boolean)))
  if (!validateStart(accountEmails)) return
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  currentJob.value = null
  setStatus(`任务已提交，正在为 ${accountEmails.length} 个账号${actionText} PayPal，目标国家 ${form.value.region}，优惠区 ${form.value.promoRegion}，并发 ${form.value.concurrency}，重试 ${form.value.maxAttempts}${form.value.onlyOaics ? '，仅 OAICS' : ''}。`)
  try {
    saveProxy({ silent: true })
    const payload = {
      proxies: form.value.proxies,
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
    currentJob.value = { id: data.job_id, status: 'queued', total: accountEmails.length, completed: 0, concurrency: form.value.concurrency, running_count: 0 }
    persistLinkJobState({ jobId: data.job_id, accountCount: accountEmails.length, concurrency: form.value.concurrency, startedAt: Date.now() })
    await pollJob(data.job_id)
  } catch (error) {
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
    const job = await api.getUsPaypalJob(jobId)
    if (componentUnmounted) return
    const completed = Number(job.completed || 0)
    const total = Number(job.total || 0)
    const shouldSyncIncremental = job.result && completed > lastSyncedCompleted && ['running', 'cancelling'].includes(job.status)
    currentJob.value = job
    logs.value = Array.isArray(job.logs) ? job.logs : []
    currentResult.value = job.result || null
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
    await new Promise(resolve => window.setTimeout(resolve, 1000))
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
  localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value))
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
  return {
    ...fallback,
    jobId: jobId || job?.id || fallback.jobId || '',
    accountCount: Number(job?.total || fallback.accountCount || 1),
    concurrency: Number(job?.concurrency || fallback.concurrency || 1),
    startedAt: fallback.startedAt || Date.now(),
    updatedAt: Date.now(),
    job: job || null,
    logs: Array.isArray(logs) ? logs : [],
    result: result || null,
    statusText: String(statusText || ''),
    statusError: Boolean(statusError),
  }
}
function persistProtocolJobState(fallback = {}) {
  const jobId = protocolJob.value?.id || fallback.jobId
  const claimedPhonePoolKeys = fallback.claimedPhonePoolKeys || protocolClaimedPhonePoolKeysByJob.get(jobId) || []
  const payload = paymentJobSnapshot(jobId, protocolJob.value, protocolLogs.value, protocolResult.value, protocolStatusText.value, protocolStatusError.value, { ...fallback, claimedPhonePoolKeys })
  if (payload.jobId || payload.logs.length || payload.result) localStorage.setItem(PROTOCOL_JOB_STORAGE_KEY, JSON.stringify(payload))
}
function restoreProtocolJobState(saved = {}) {
  if (!saved || typeof saved !== 'object' || !(saved.jobId || saved.job || saved.logs || saved.result)) return false
  protocolJob.value = saved.job || { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 1), completed: 0, concurrency: Number(saved.concurrency || 1) }
  protocolLogs.value = Array.isArray(saved.logs) ? saved.logs : []
  protocolResult.value = saved.result || null
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
      saved = JSON.parse(localStorage.getItem(PROTOCOL_JOB_STORAGE_KEY) || '{}')
    } catch {
      saved = {}
    }
    if (!restoreProtocolJobState(saved)) return false
  }
  const status = String(protocolJob.value?.status || '')
  const jobId = protocolJob.value?.id || saved.jobId
  if (options.preferredActiveTab === 'protocol' || !TERMINAL_STATUSES.has(status)) activeTab.value = 'protocol'
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
function saveProtocolForm(options = {}) {
  localStorage.setItem(PROTOCOL_FORM_STORAGE_KEY, JSON.stringify(protocolForm.value))
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
  selectedProtocolAccountEmails.value = new Set(protocolLinkAccountOptions.value.filter(item => item.paypalStatus !== 'paid').map(item => item.email))
  if (selectedProtocolAccountEmails.value.size === 1) {
    selectedProtocolAccountEmail.value = protocolSelectedEmails.value[0]
    applySelectedProtocolAccount()
  }
}
function clearSelectedProtocolAccounts() {
  selectedProtocolAccountEmails.value = new Set()
}
function togglePhonePoolReuse() {
  phonePoolReuseEnabled.value = !phonePoolReuseEnabled.value
}
function stopProtocolAutoPay(message = '协议自动支付已停止。') {
  protocolAutoPayActive.value = false
  if (protocolAutoPayTimer) window.clearInterval(protocolAutoPayTimer)
  protocolAutoPayTimer = null
  protocolAutoPayStatusText.value = message
}
function stopPay153AutoPay(message = '153自动支付已停止。') {
  pay153AutoPayActive.value = false
  if (pay153AutoPayTimer) window.clearInterval(pay153AutoPayTimer)
  pay153AutoPayTimer = null
  pay153AutoPayStatusText.value = message
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
  await scanProtocolAutoPayLinks()
  protocolAutoPayTimer = window.setInterval(() => { void scanProtocolAutoPayLinks() }, AUTO_PAYMENT_POLL_MS)
}
async function togglePay153AutoPay() {
  if (pay153AutoPayActive.value) {
    stopPay153AutoPay('153自动支付已手动停止。')
    return
  }
  pay153AutoPayActive.value = true
  pay153AutoPayQueue.value = []
  pay153AutoPaySeenKeys.value = new Set()
  pay153AutoPayLastNewAt.value = Date.now()
  pay153AutoPayStatusText.value = '153自动支付已开启：每1分钟拉取新链接，30分钟无新链接后结束。'
  await scanPay153AutoPayLinks()
  pay153AutoPayTimer = window.setInterval(() => { void scanPay153AutoPayLinks() }, AUTO_PAYMENT_POLL_MS)
}
async function scanProtocolAutoPayLinks() {
  if (!protocolAutoPayActive.value) return
  await refreshPaymentLinks()
  const seen = new Set(protocolAutoPaySeenKeys.value)
  const queued = new Set(protocolAutoPayQueue.value.map(item => item.email))
  const additions = []
  for (const item of protocolLinkAccountOptions.value) {
    if (!item?.email || item.paypalStatus === 'paid') continue
    const key = autoPayLinkKey(item)
    if (!key || seen.has(key) || queued.has(item.email)) continue
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
async function scanPay153AutoPayLinks() {
  if (!pay153AutoPayActive.value) return
  await refreshPaymentLinks()
  const seen = new Set(pay153AutoPaySeenKeys.value)
  const queued = new Set(pay153AutoPayQueue.value.map(item => item.email))
  const additions = []
  for (const item of pay153LinkAccountOptions.value) {
    if (!item?.email || item.paypalStatus === 'paid') continue
    const key = autoPayLinkKey(item)
    if (!key || seen.has(key) || queued.has(item.email)) continue
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
  if (additions.length) logsRef.value = [...logsRef.value, ...additions]
  offsets.set(jobId, rows.length)
}
function updateAutoPayActiveJob(activeRef, email, patch) {
  activeRef.value = activeRef.value.map(item => item.email === email ? { ...item, ...patch } : item)
}
function removeAutoPayActiveJob(activeRef, email) {
  activeRef.value = activeRef.value.filter(item => item.email !== email)
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
  if (!validateProtocolPayment([email])) return
  const claimedPhonePoolEntries = protocolForm.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(protocolForm.value.phonePool, 1, 'protocol') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(entry => entry.key).filter(Boolean)
  protocolAutoPayActiveJobs.value = [...protocolAutoPayActiveJobs.value, { email, key: item.key, status: 'queued', jobId: '' }]
  try {
    saveProtocolForm({ silent: true })
    const payload = {
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
    }
    const data = await api.startUsPaypalProtocolBatch(payload)
    if (!data.job_id) throw new Error('后端没有返回协议支付任务 ID')
    protocolClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId: data.job_id, status: 'running' })
    void pollProtocolAutoPayJob(data.job_id, email)
  } catch (error) {
    releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', claimedPhonePoolKeys, protocolForm.value.phonePool)
    removeAutoPayActiveJob(protocolAutoPayActiveJobs, email)
    protocolResult.value = mergePaymentResult(protocolResult.value, { errors: [{ email, error: cleanError(error) }] })
    protocolAutoPayStatusText.value = `协议自动支付启动失败：${email} ${cleanError(error)}`
    void drainProtocolAutoPayQueue()
  }
}
async function launchPay153AutoPayItem(item) {
  const email = String(item?.email || '').trim()
  if (!email || !pay153AutoPayActive.value) return
  if (!validatePay153Payment([email])) return
  const claimedPhonePoolEntries = pay153Form.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(pay153Form.value.phonePool, 1, 'pay153') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(entry => entry.key).filter(Boolean)
  pay153AutoPayActiveJobs.value = [...pay153AutoPayActiveJobs.value, { email, key: item.key, status: 'queued', jobId: '' }]
  try {
    savePay153Form({ silent: true })
    const data = await api.startUsPaypal153Batch({
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
    })
    if (!data.job_id) throw new Error('后端没有返回153支付任务 ID')
    pay153ClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId: data.job_id, status: 'running' })
    void pollPay153AutoPayJob(data.job_id, email)
  } catch (error) {
    releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', claimedPhonePoolKeys, pay153Form.value.phonePool)
    removeAutoPayActiveJob(pay153AutoPayActiveJobs, email)
    pay153Result.value = mergePaymentResult(pay153Result.value, { errors: [{ email, error: cleanError(error) }] })
    pay153AutoPayStatusText.value = `153自动支付启动失败：${email} ${cleanError(error)}`
    void drainPay153AutoPayQueue()
  }
}
async function pollProtocolAutoPayJob(jobId, email) {
  try {
    for (;;) {
      if (componentUnmounted) return
      const job = await api.getUsPaypalProtocolJob(jobId)
      if (componentUnmounted) return
      protocolJob.value = job
      updateAutoPayActiveJob(protocolAutoPayActiveJobs, email, { jobId, status: job.status, job })
      appendAutoPayLogs(protocolLogs, protocolAutoPayLogOffsets, jobId, email, job.logs)
      if (TERMINAL_STATUSES.has(String(job.status || ''))) {
        protocolResult.value = mergePaymentResult(protocolResult.value, job.result || {})
        syncPhonePoolStatusFromJobResult(job.result || {}, 'protocol')
        releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'protocol', protocolClaimedPhonePoolKeysByJob.get(jobId) || [], protocolForm.value.phonePool)
        removeAutoPayActiveJob(protocolAutoPayActiveJobs, email)
        await refreshAccounts()
        void drainProtocolAutoPayQueue()
        return
      }
      protocolAutoPayStatusText.value = `协议自动支付运行中：进行中 ${protocolAutoPayActiveJobs.value.length}，队列 ${protocolAutoPayQueue.value.length}。`
      await new Promise(resolve => window.setTimeout(resolve, 1000))
    }
  } catch (error) {
    releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', protocolClaimedPhonePoolKeysByJob.get(jobId) || [], protocolForm.value.phonePool)
    removeAutoPayActiveJob(protocolAutoPayActiveJobs, email)
    protocolResult.value = mergePaymentResult(protocolResult.value, { errors: [{ email, error: cleanError(error) }] })
    void drainProtocolAutoPayQueue()
  }
}
async function pollPay153AutoPayJob(jobId, email) {
  try {
    for (;;) {
      if (componentUnmounted) return
      const job = await api.getUsPaypal153Job(jobId)
      if (componentUnmounted) return
      pay153Job.value = job
      updateAutoPayActiveJob(pay153AutoPayActiveJobs, email, { jobId, status: job.status, job })
      appendAutoPayLogs(pay153Logs, pay153AutoPayLogOffsets, jobId, email, job.logs)
      if (TERMINAL_STATUSES.has(String(job.status || ''))) {
        pay153Result.value = mergePaymentResult(pay153Result.value, job.result || {})
        syncPhonePoolStatusFromJobResult(job.result || {}, 'pay153')
        releaseClaimedPhonePoolEntriesAfterJob(job.result || {}, 'pay153', pay153ClaimedPhonePoolKeysByJob.get(jobId) || [], pay153Form.value.phonePool)
        removeAutoPayActiveJob(pay153AutoPayActiveJobs, email)
        await refreshAccounts()
        void drainPay153AutoPayQueue()
        return
      }
      pay153AutoPayStatusText.value = `153自动支付运行中：进行中 ${pay153AutoPayActiveJobs.value.length}，队列 ${pay153AutoPayQueue.value.length}。`
      await new Promise(resolve => window.setTimeout(resolve, 1000))
    }
  } catch (error) {
    releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', pay153ClaimedPhonePoolKeysByJob.get(jobId) || [], pay153Form.value.phonePool)
    removeAutoPayActiveJob(pay153AutoPayActiveJobs, email)
    pay153Result.value = mergePaymentResult(pay153Result.value, { errors: [{ email, error: cleanError(error) }] })
    void drainPay153AutoPayQueue()
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
  if (pay153AutoPayDraining) return
  pay153AutoPayDraining = true
  try {
    while (pay153AutoPayActive.value && pay153AutoPayQueue.value.length) {
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
  if (!batchCount && !String(protocolForm.value.paypalLink || '').trim()) { setProtocolStatus('请填写 BA 链接或 BA token，或多选已成功提链账号。', true); return false }
  if (!PROTOCOL_COUNTRIES.has(protocolForm.value.country)) { setProtocolStatus('当前协议支付支持 AU/BR/CA/GB/ID/JP/MX/PH/TH/NL/US。', true); return false }
  const phoneCount = splitProtocolLines(protocolForm.value.phone).length
  const phonePoolCount = phonePoolReuseEnabled.value ? parseSmsRecordPhonePoolLines(protocolForm.value.phonePool).length : usablePhonePoolEntriesFromText(protocolForm.value.phonePool, 'protocol').length
  if (protocolForm.value.smsProvider === 'sms_record') {
    const requiredCount = batchCount || 1
    if (phonePoolCount < requiredCount) { setProtocolStatus('协议支付号池数量不足；请按“手机号----SMS record URL”每行导入一个号码。', true); return false }
  } else if (protocolForm.value.smsProvider === 'hero_sms_rent') {
    if (!String(protocolForm.value.phone || '').trim()) { setProtocolStatus('请填写 HeroSMS 长效号码。', true); return false }
    if (batchCount > 1 && phoneCount < batchCount) { setProtocolStatus('HeroSMS 长效号批量支付时，每个账号都需要一行长效号码。', true); return false }
  }
  protocolForm.value.concurrency = Math.max(1, Math.min(10, Number(protocolForm.value.concurrency || 1)))
  protocolForm.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(protocolForm.value.proxyPreflightAttempts || 5)))
  protocolForm.value.smsRecordWaitSeconds = Math.max(60, Math.min(900, Number(protocolForm.value.smsRecordWaitSeconds || 300)))
  protocolForm.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(protocolForm.value.smsRecordPollSeconds || 3)))
  return true
}

async function startProtocolPayment(options = {}) {
  const selectedEmails = Array.isArray(options.autoBatchEmails) ? options.autoBatchEmails : protocolSelectedEmails.value
  if (Array.isArray(options.autoBatchEmails)) selectedProtocolAccountEmails.value = new Set(options.autoBatchEmails)
  if (!validateProtocolPayment(selectedEmails)) return false
  protocolBusy.value = true
  protocolCanceling.value = false
  protocolLogs.value = []
  protocolResult.value = null
  protocolJob.value = null
  activeTab.value = 'protocol'
  setProtocolStatus('协议支付任务已提交，正在启动本地 PayPal 引擎。')
  const claimedPhonePoolEntries = protocolForm.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(protocolForm.value.phonePool, selectedEmails.length || 1, 'protocol') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(item => item.key).filter(Boolean)
  try {
    saveProtocolForm({ silent: true })
    const payload = {
      paypalLink: protocolForm.value.paypalLink,
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
    }
    const data = selectedEmails.length
      ? await api.startUsPaypalProtocolBatch({ ...payload, accountEmails: selectedEmails })
      : await api.startUsPaypalProtocol(payload)
    if (!data.job_id) throw new Error('后端没有返回协议支付任务 ID')
    if (claimedPhonePoolKeys.length) protocolClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    protocolJob.value = { id: data.job_id, status: 'queued', total: selectedEmails.length || 1, completed: 0, concurrency: protocolForm.value.concurrency }
    persistProtocolJobState({ jobId: data.job_id, accountCount: selectedEmails.length || 1, concurrency: protocolForm.value.concurrency, startedAt: Date.now(), claimedPhonePoolKeys })
    await pollProtocolJob(data.job_id)
    return true
  } catch (error) {
    releaseClaimedPhonePoolEntriesAfterJob({}, 'protocol', claimedPhonePoolKeys, protocolForm.value.phonePool)
    setProtocolStatus(cleanError(error), true)
    persistProtocolJobState()
    return false
  } finally {
    protocolBusy.value = false
    protocolCanceling.value = false
    void drainProtocolAutoPayQueue()
  }
}

async function pollProtocolJob(jobId) {
  for (;;) {
    if (componentUnmounted) return
    const job = await api.getUsPaypalProtocolJob(jobId)
    if (componentUnmounted) return
    protocolJob.value = job
    protocolLogs.value = Array.isArray(job.logs) ? job.logs : []
    protocolResult.value = job.result || null
    await nextTick()
    if (protocolLogRef.value) protocolLogRef.value.scrollTop = protocolLogRef.value.scrollHeight
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
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
}

async function cancelProtocolJob() {
  const jobId = protocolJob.value?.id
  if (!jobId || protocolCanceling.value) return
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
function persistPay153JobState(fallback = {}) {
  const jobId = pay153Job.value?.id || fallback.jobId
  const claimedPhonePoolKeys = fallback.claimedPhonePoolKeys || pay153ClaimedPhonePoolKeysByJob.get(jobId) || []
  const payload = paymentJobSnapshot(jobId, pay153Job.value, pay153Logs.value, pay153Result.value, pay153StatusText.value, pay153StatusError.value, { ...fallback, claimedPhonePoolKeys })
  if (payload.jobId || payload.logs.length || payload.result) localStorage.setItem(PAY153_JOB_STORAGE_KEY, JSON.stringify(payload))
}
function restorePay153JobState(saved = {}) {
  if (!saved || typeof saved !== 'object' || !(saved.jobId || saved.job || saved.logs || saved.result)) return false
  pay153Job.value = saved.job || { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 1), completed: 0, concurrency: Number(saved.concurrency || 1), children: {} }
  pay153Logs.value = Array.isArray(saved.logs) ? saved.logs : []
  pay153Result.value = saved.result || null
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
      saved = JSON.parse(localStorage.getItem(PAY153_JOB_STORAGE_KEY) || '{}')
    } catch {
      saved = {}
    }
    if (!restorePay153JobState(saved)) return false
  }
  const status = String(pay153Job.value?.status || '')
  const jobId = pay153Job.value?.id || saved.jobId
  if (options.preferredActiveTab === 'pay153' || !TERMINAL_STATUSES.has(status)) activeTab.value = 'pay153'
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
function savePay153Form(options = {}) {
  localStorage.setItem(PAY153_FORM_STORAGE_KEY, JSON.stringify(pay153Form.value))
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
  selectedPay153AccountEmails.value = new Set(pay153LinkAccountOptions.value.filter(item => item.paypalStatus !== 'paid').map(item => item.email))
}
function clearSelectedPay153Accounts() {
  selectedPay153AccountEmails.value = new Set()
}
function currentPay153BaPayload() {
  const selectedEmail = pay153SelectedEmails.value[0] || ''
  const selected = selectedEmail ? pay153LinkAccountOptions.value.find(item => item.email === selectedEmail) : null
  return {
    paypalLink: selected?.paypalLink || '',
    baToken: displayBaToken(selected?.paypalLink || ''),
  }
}
function validatePay153Payment(targetEmails = pay153SelectedEmails.value) {
  const batchCount = Array.isArray(targetEmails) ? targetEmails.length : 0
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
  if (!batchCount) { setPay153Status('请选择要使用 153支付 的已成功提链账号。', true); return false }
  if (pay153Form.value.smsProvider === 'sms_record') {
    if (phonePoolCount < batchCount) { setPay153Status('153支付号池数量不足；请按“手机号----SMS record URL”每行导入一个号码。', true); return false }
  } else if (pay153Form.value.smsProvider === 'hero_sms_rent' && phoneCount < batchCount) {
    setPay153Status('HeroSMS 长效号 153支付批量提交时，每个账号都需要一行长效号码。', true); return false
  }
  if (!proxyCount) { setPay153Status('请填写153支付代理池。', true); return false }
  if (proxyCount > 500) { setPay153Status('153支付代理池最多支持 500 条。', true); return false }
  return true
}
async function startPay153Payment(options = {}) {
  const selectedEmails = Array.isArray(options.autoBatchEmails) ? options.autoBatchEmails : pay153SelectedEmails.value
  if (Array.isArray(options.autoBatchEmails)) selectedPay153AccountEmails.value = new Set(options.autoBatchEmails)
  if (!validatePay153Payment(selectedEmails)) return false
  pay153Busy.value = true
  pay153Canceling.value = false
  pay153Logs.value = []
  pay153Result.value = null
  pay153Job.value = null
  activeTab.value = 'pay153'
  setPay153Status('153支付任务已提交，正在创建远端任务。')
  const claimedPhonePoolEntries = pay153Form.value.smsProvider === 'sms_record' ? claimPhonePoolEntriesForSubmission(pay153Form.value.phonePool, selectedEmails.length, 'pay153') : []
  const claimedPhonePoolKeys = claimedPhonePoolEntries.map(item => item.key).filter(Boolean)
  try {
    savePay153Form({ silent: true })
    const data = await api.startUsPaypal153Batch({
      accountEmails: selectedEmails,
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
    })
    if (!data.job_id) throw new Error('后端没有返回153支付任务 ID')
    if (claimedPhonePoolKeys.length) pay153ClaimedPhonePoolKeysByJob.set(data.job_id, claimedPhonePoolKeys)
    pay153Job.value = { id: data.job_id, status: 'queued', total: selectedEmails.length, completed: 0, concurrency: pay153Form.value.concurrency, children: {} }
    persistPay153JobState({ jobId: data.job_id, accountCount: selectedEmails.length, concurrency: pay153Form.value.concurrency, startedAt: Date.now(), claimedPhonePoolKeys })
    await pollPay153Job(data.job_id)
    return true
  } catch (error) {
    releaseClaimedPhonePoolEntriesAfterJob({}, 'pay153', claimedPhonePoolKeys, pay153Form.value.phonePool)
    setPay153Status(cleanError(error), true)
    persistPay153JobState()
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
  const retryable = new Set(successfulPayPalLinkAccounts(accounts.value, links.value, 'all').filter(item => item.paypalStatus !== 'paid').map(item => item.email))
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
  const payload = currentPay153BaPayload()
  if (!payload.paypalLink && !payload.baToken) {
    setPay153Status('请先在153支付链接列表选择一个要清理的 BA。', true)
    return
  }
  pay153Canceling.value = true
  try {
    const data = await api.cancelUsPaypal153RemoteByBa(payload)
    const cancelled = Array.isArray(data.remote_cancelled) ? data.remote_cancelled : []
    setPay153Status(cancelled.length ? `已清理153卡住任务：${cancelled.join(', ')}` : `没有找到可清理的153远端任务：${data.ba_token || payload.baToken}`)
  } catch (error) {
    setPay153Status(`清理153卡住任务失败：${cleanError(error)}`, true)
  } finally {
    pay153Canceling.value = false
  }
}
async function pollPay153Job(jobId) {
  for (;;) {
    if (componentUnmounted) return
    const job = await api.getUsPaypal153Job(jobId)
    if (componentUnmounted) return
    pay153Job.value = job
    pay153Logs.value = Array.isArray(job.logs) ? job.logs : []
    pay153Result.value = job.result || null
    await nextTick()
    if (pay153LogRef.value) pay153LogRef.value.scrollTop = pay153LogRef.value.scrollHeight
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
    await new Promise(resolve => window.setTimeout(resolve, 1000))
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
  if (!jobId || pay153Canceling.value) return
  pay153Canceling.value = true
  try {
    await api.cancelUsPaypal153Job(jobId)
    setPay153Status('已发送取消请求，正在终止153远端任务。')
  } catch (error) {
    setPay153Status(`取消失败：${cleanError(error)}`, true)
    pay153Canceling.value = false
  }
}

onMounted(async () => {
  componentUnmounted = false
  let preferredActiveTab = activeTab.value
  try {
    const savedForm = JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(form.value)) {
      if (savedForm[key] !== undefined) form.value[key] = savedForm[key]
    }
    form.value.concurrency = Math.max(1, Math.min(30, Number(form.value.concurrency || 1)))
    form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
    form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  } catch { /* ignore malformed local state */ }
  try {
    const savedReuse = localStorage.getItem(PHONE_POOL_REUSE_STORAGE_KEY)
    if (savedReuse !== null) phonePoolReuseEnabled.value = savedReuse === '1' || savedReuse === 'true'
  } catch { /* ignore malformed reuse state */ }
  try {
    const savedTab = String(localStorage.getItem(ACTIVE_TAB_STORAGE_KEY) || '').trim()
    if (['links', 'protocol', 'pay153'].includes(savedTab)) {
      activeTab.value = savedTab
      preferredActiveTab = savedTab
    }
  } catch { /* ignore malformed active tab */ }
  try {
    const savedProtocolForm = JSON.parse(localStorage.getItem(PROTOCOL_FORM_STORAGE_KEY) || '{}')
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
    protocolForm.value.concurrency = Math.max(1, Math.min(10, Number(protocolForm.value.concurrency || 1)))
    protocolForm.value.smsRecordWaitSeconds = Math.max(60, Math.min(900, Number(protocolForm.value.smsRecordWaitSeconds || 300)))
    protocolForm.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(protocolForm.value.smsRecordPollSeconds || 3)))
    protocolForm.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(protocolForm.value.proxyPreflightAttempts || 5)))
  } catch { /* ignore malformed protocol state */ }
  try {
    const savedPay153Form = JSON.parse(localStorage.getItem(PAY153_FORM_STORAGE_KEY) || '{}')
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
    const savedPhonePool = JSON.parse(localStorage.getItem(PHONE_POOL_MANAGEMENT_STORAGE_KEY) || '{}')
    phonePoolStatusMap.value = savedPhonePool.statuses && typeof savedPhonePool.statuses === 'object' ? savedPhonePool.statuses : {}
  } catch { /* ignore malformed phone pool state */ }
  await reloadAll()
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

watch(form, () => localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value)), { deep: true })
watch(activeTab, value => localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, value))
watch(phonePoolReuseEnabled, value => localStorage.setItem(PHONE_POOL_REUSE_STORAGE_KEY, value ? '1' : '0'))
watch(protocolForm, () => localStorage.setItem(PROTOCOL_FORM_STORAGE_KEY, JSON.stringify(protocolForm.value)), { deep: true })
watch(pay153Form, () => localStorage.setItem(PAY153_FORM_STORAGE_KEY, JSON.stringify(pay153Form.value)), { deep: true })
watch([accountFilter, accountStatusFilter, accountCountryFilter], () => { accountVisibleCount.value = 100 })
watch(activeTab, (tab) => {
  if (tab === 'links') resumeLinkJobStateFromStorage()
  if (tab === 'protocol' || tab === 'pay153') refreshPaymentLinks()
  if (tab === 'protocol') resumeProtocolJobStateFromStorage()
  if (tab === 'pay153') resumePay153JobStateFromStorage()
})
watch(protocolLinkCountryFilter, () => {
  if (selectedProtocolAccountEmail.value && !protocolLinkSelectableEmails.value.has(selectedProtocolAccountEmail.value)) {
    selectedProtocolAccountEmail.value = ''
  }
  const available = protocolLinkSelectableEmails.value
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => available.has(email)))
})
watch(protocolLinkTimeFilter, () => {
  const available = protocolLinkSelectableEmails.value
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => available.has(email)))
})
watch(pay153LinkCountryFilter, () => {
  const available = pay153LinkSelectableEmails.value
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => available.has(email)))
})
watch(pay153LinkTimeFilter, () => {
  const available = pay153LinkSelectableEmails.value
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => available.has(email)))
})
watch([accounts, links], () => {
  selectedProtocolAccountEmails.value = new Set(protocolSelectedEmails.value.filter(email => protocolLinkSelectableEmails.value.has(email)))
  selectedPay153AccountEmails.value = new Set(pay153SelectedEmails.value.filter(email => pay153LinkSelectableEmails.value.has(email)))
}, { deep: true })
watch(phonePoolStatusMap, () => {
  localStorage.setItem(PHONE_POOL_MANAGEMENT_STORAGE_KEY, JSON.stringify({
    statuses: phonePoolStatusMap.value,
  }))
}, { deep: true })

onBeforeUnmount(() => {
  stopProtocolAutoPay('协议自动支付已随页面关闭停止。')
  stopPay153AutoPay('153自动支付已随页面关闭停止。')
  persistLinkJobState()
  persistProtocolJobState()
  persistPay153JobState()
  componentUnmounted = true
})
</script>
