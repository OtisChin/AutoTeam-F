<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">独立 PayPal 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">PayPal 任务</h2>
          <p class="mt-2 text-sm text-gray-400">先提取 BA 链接，再在独立协议支付页使用本地引擎完成 PayPal approval。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ anyBusy ? activeStatusText : '本地服务在线' }}
        </span>
      </div>
    </section>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-2">
      <div class="flex flex-wrap gap-2">
        <button type="button" @click="activeTab = 'links'" class="rounded-xl px-4 py-2 text-sm font-bold transition" :class="activeTab === 'links' ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">
          PayPal 提链
        </button>
        <button type="button" @click="activeTab = 'protocol'" class="rounded-xl px-4 py-2 text-sm font-bold transition" :class="activeTab === 'protocol' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">
          协议支付
        </button>
      </div>
    </section>

    <template v-if="activeTab === 'links'">
    <div class="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
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

          <div class="grid gap-4 md:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="form.concurrency" type="number" min="1" max="10" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 1，最高 10；并发越高越依赖代理质量。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">重试次数</span>
              <input v-model.number="form.maxAttempts" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">单账号最多尝试次数，含首次；默认 5。</span>
            </label>
          </div>

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
            <option value="success">已提链</option>
            <option value="paid">已支付</option>
          </select>
          <div class="flex flex-wrap gap-2">
            <button @click="selectAllFiltered" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
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
                <th class="px-3 py-2">有效期</th>
                <th class="px-3 py-2">提链状态</th>
                <th class="px-3 py-2 text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-900">
              <tr v-if="!filteredAccounts.length">
                <td colspan="5" class="px-3 py-10 text-center text-gray-500">暂无账号</td>
              </tr>
              <tr v-for="account in filteredAccounts" :key="account.email" class="hover:bg-gray-900/50">
                <td class="px-3 py-2">
                  <input :checked="selectedAccounts.has(account.email)" type="checkbox" class="accent-emerald-500" :disabled="busy || !accountSelectable(account)" @change="toggleAccount(account.email)" />
                </td>
                <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ account.email }}</td>
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

          <div v-else class="mt-5 space-y-3 text-sm">
            <div class="rounded-xl border border-gray-800 bg-gray-950 p-4 text-gray-300">
              本次完成：成功 <span class="font-semibold text-emerald-300">{{ currentResult.successes?.length || 0 }}</span>，失败 <span class="font-semibold text-rose-300">{{ currentResult.errors?.length || 0 }}</span>，跳过 <span class="font-semibold text-gray-300">{{ currentResult.skipped?.length || 0 }}</span>
            </div>
            <div v-for="item in currentResult.successes || []" :key="item.email" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
              <div class="font-mono text-emerald-200">{{ item.email }}</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!(item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url) ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(item.link?.paypal_link || item.link?.provider_redirect_url || item.link?.stripe_redirect_url)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制链</button>
              </div>
            </div>
            <div v-for="item in currentResult.errors || []" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {{ item.email }}：{{ item.error }}
            </div>
            <div v-for="item in currentResult.skipped || []" :key="item.email" class="rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-2 text-xs text-gray-300">
              {{ item.email }}：{{ item.reason || '已跳过' }}
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
          <button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button>
          <button @click="exportLinks" :disabled="!links.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button>
          <button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
          <button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空</button>
        </div>
      </div>

      <div class="mt-4 max-h-[520px] overflow-auto rounded-xl border border-gray-800">
        <table class="min-w-[1180px] w-full text-left text-sm">
          <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500">
            <tr>
              <th class="w-10 px-3 py-2"></th>
              <th class="px-3 py-2">时间</th>
              <th class="px-3 py-2">账号</th>
              <th class="px-3 py-2">金额</th>
              <th class="px-3 py-2">CS ID</th>
              <th class="px-3 py-2">操作</th>
              <th class="px-3 py-2">PayPal 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!links.length">
              <td colspan="7" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ link.created_at || link.createdAt || '-' }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || link.accountEmail || '-' }}</td>
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

    <section v-else class="rounded-2xl border border-indigo-500/20 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 border-b border-indigo-500/20 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-300/70">PayPal Protocol Payment</p>
          <h2 class="mt-1 text-2xl font-bold text-white">本地协议支付页</h2>
          <p class="mt-2 text-sm text-gray-400">使用 AutoTeam-F 内置的 PayPal 协议引擎执行 BA approval；不调用任何第三方远程兼容网站。</p>
        </div>
        <span class="rounded-full border px-3 py-1 text-xs font-semibold" :class="protocolBadgeClass">{{ protocolBadgeText }}</span>
      </div>

      <div class="mt-6 grid gap-5 xl:grid-cols-[minmax(360px,0.9fr)_minmax(460px,1.1fr)]">
        <div class="space-y-5">
          <div class="rounded-2xl border border-gray-800 bg-gray-950 p-5">
            <h3 class="text-lg font-bold text-white">协议支付输入</h3>
            <div class="mt-5 space-y-4">
              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">BA 链接 / BA token</span>
                <textarea v-model.trim="protocolForm.paypalLink" rows="3" spellcheck="false" placeholder="https://www.paypal.com/agreements/approve?ba_token=BA-..." class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
              </label>

              <div class="grid gap-4 md:grid-cols-2">
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">国家</span>
                  <select v-model="protocolForm.country" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy">
                    <option value="US">US · 美国</option>
                  </select>
                  <span class="mt-1 block text-xs text-gray-500">当前仅开放已验证的 US no-FI 链路。</span>
                </label>
                <label class="block">
                  <span class="mb-1.5 block text-sm font-semibold text-gray-300">手机号</span>
                  <input v-model.trim="protocolForm.phone" placeholder="+1835..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                </label>
              </div>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">SMS record URL</span>
                <input v-model.trim="protocolForm.smsRecordUrl" placeholder="https://sms.example/api/record?token=..." class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
                <span class="mt-1 block text-xs text-gray-500">后端会轮询该 URL，并只使用本次请求后的新 OTP。</span>
              </label>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">US 代理（可选）</span>
                <textarea v-model.trim="protocolForm.proxies" rows="3" spellcheck="false" placeholder="proxy.example.com:10000:USER-zone-custom-region-US-session-xxxx-sessTime-120-sessAuto-1:pass" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy"></textarea>
                <span class="mt-1 block text-xs text-gray-500">默认不走代理，复现已验证成功的 no-proxy 组合；填写时后端取第一条并在本地子进程中执行。</span>
              </label>

              <label class="block">
                <span class="mb-1.5 block text-sm font-semibold text-gray-300">关联账号邮箱（可选）</span>
                <input v-model.trim="protocolForm.accountEmail" placeholder="支付成功后标记为 Plus/paid" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 font-mono text-sm text-white placeholder:text-gray-600 focus:border-indigo-500 focus:outline-none" :disabled="protocolBusy" />
              </label>

              <div class="grid gap-4 md:grid-cols-2">
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
                  {{ protocolBusy ? '支付中...' : '开始协议支付' }}
                </button>
                <button v-if="protocolBusy" @click="cancelProtocolJob" :disabled="protocolCanceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
                  {{ protocolCanceling ? '取消中...' : '取消支付' }}
                </button>
                <button @click="saveProtocolForm" :disabled="protocolBusy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存输入</button>
              </div>
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
              <span class="mt-1 text-sm">填入 BA、手机号、SMS URL 和代理后开始。</span>
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

const FORM_STORAGE_KEY = 'autotoken_us_paypal_form'
const JOB_STORAGE_KEY = 'autotoken_us_paypal_job'
const PROTOCOL_FORM_STORAGE_KEY = 'autotoken_us_paypal_protocol_form'
const PROTOCOL_JOB_STORAGE_KEY = 'autotoken_us_paypal_protocol_job'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented'])
const ACCOUNT_STATUS_TEXT = { pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', paid: '已支付' }
const paypalCountryOptions = [
  { value: 'US', label: 'US · 美国' },
  { value: 'GB', label: 'GB · 英国' },
  { value: 'CA', label: 'CA · 加拿大' },
  { value: 'AU', label: 'AU · 澳大利亚' },
  { value: 'JP', label: 'JP · 日本' },
  { value: 'BR', label: 'BR · 巴西' },
  { value: 'VN', label: 'VN · 越南' },
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
  { value: 'VN', label: 'VN · 越南' },
]

const form = ref({
  proxies: '',
  concurrency: 1,
  maxAttempts: 5,
  region: 'US',
  promoRegion: 'JP',
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
const retryFailedEmailSet = ref(new Set())
const deletingPaypalAccounts = ref(new Set())
const logRef = ref(null)
const activeTab = ref('links')
const protocolForm = ref({ paypalLink: '', phone: '', smsRecordUrl: '', proxies: '', country: 'US', accountEmail: '', smsRecordWaitSeconds: 300, smsRecordPollSeconds: 3 })
const protocolBusy = ref(false)
const protocolCanceling = ref(false)
const protocolJob = ref(null)
const protocolLogs = ref([])
const protocolResult = ref(null)
const protocolStatusText = ref('等待提交协议支付。')
const protocolStatusError = ref(false)
const protocolLogRef = ref(null)
let componentUnmounted = false

const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const retryFailedEmails = computed(() => Array.from(retryFailedEmailSet.value).filter(email => accounts.value.some(account => account.email === email && accountSelectable(account))))
const filteredAccounts = computed(() => accounts.value.filter((account) => {
  const status = accountStatus(account)
  return (!accountFilter.value || String(account.email || '').toLowerCase().includes(accountFilter.value.toLowerCase())) && (accountStatusFilter.value === 'all' || status === accountStatusFilter.value)
}))
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
const anyBusy = computed(() => busy.value || protocolBusy.value)
const activeStatusText = computed(() => activeTab.value === 'protocol' && protocolBusy.value ? protocolBadgeText.value : progressText.value)

function setStatus(message, error = false) { statusText.value = message; statusError.value = error }
function cleanText(value) { return String(value || '未知错误').replace(/\s+/g, ' ').trim() }
function cleanError(error) { return cleanText(error?.message || error) }
function accountJobStatus(account) { const statuses = currentJob.value?.account_statuses || {}; return statuses[account.email] || statuses[String(account.email || '').toLowerCase()] || null }
function accountStatus(account) { return accountJobStatus(account)?.status || account?.paypal_status || 'pending' }
function ttlText(seconds) { const value = Number(seconds); if (!Number.isFinite(value) || value < 0) return '-'; if (value < 60) return `${Math.floor(value)}s`; if (value < 3600) return `${Math.ceil(value / 60)}m`; return `${Math.ceil(value / 3600)}h` }
function accountStatusText(account) { const jobStatus = accountJobStatus(account); if (jobStatus) return jobStatus.status_text || ACCOUNT_STATUS_TEXT[jobStatus.status] || '未提链'; return account.paypal_status_text || ACCOUNT_STATUS_TEXT[account.paypal_status] || '未提链' }
function accountStatusClass(account) { const status = accountStatus(account); return ({ running: 'border-blue-500/30 bg-blue-500/10 text-blue-300', success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300', failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300', paid: 'border-violet-500/30 bg-violet-500/10 text-violet-300' })[status] || 'border-gray-700 bg-gray-900 text-gray-400' }
function accountStatusError(account) { return accountJobStatus(account)?.error || account.paypal_error || '' }
function accountSelectable(account) { return account.paypal_selectable !== false && accountStatus(account) !== 'paid' }
function toggleAccount(email) { const account = accounts.value.find(item => item.email === email); if (!account || !accountSelectable(account)) return; const next = new Set(selectedAccounts.value); next.has(email) ? next.delete(email) : next.add(email); selectedAccounts.value = next }
function selectAllFiltered() { selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).map(account => account.email)) }
function clearSelectedAccounts() { selectedAccounts.value = new Set() }
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
  form.value.concurrency = Math.max(1, Math.min(10, Number(form.value.concurrency || 1)))
  form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
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
  setStatus(`任务已提交，正在为 ${accountEmails.length} 个账号${actionText} PayPal，目标国家 ${form.value.region}，优惠区 ${form.value.promoRegion}，并发 ${form.value.concurrency}，重试 ${form.value.maxAttempts}。`)
  try {
    saveProxy({ silent: true })
    const payload = {
      proxies: form.value.proxies,
      concurrency: form.value.concurrency,
      maxAttempts: form.value.maxAttempts,
      region: form.value.region,
      promoRegion: form.value.promoRegion,
    }
    const data = await api.startUsPaypalBatch({ ...payload, accountEmails })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    currentJob.value = { id: data.job_id, status: 'queued', total: accountEmails.length, completed: 0, concurrency: form.value.concurrency, running_count: 0 }
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({ jobId: data.job_id, accountCount: accountEmails.length, concurrency: form.value.concurrency, startedAt: Date.now() }))
    await pollJob(data.job_id)
  } catch (error) {
    setStatus(cleanError(error), true)
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
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (shouldSyncIncremental) {
      lastSyncedCompleted = completed
      await refreshLinks()
    }
    if (job.status === 'success') {
      rememberFailedEmails(job.result || {})
      setStatus('提链任务已完成，链接已写入管理表。')
      localStorage.removeItem(JOB_STORAGE_KEY)
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (job.status === 'cancelled') {
      currentResult.value = job.result || { batch: true, successes: [], errors: [], skipped: job.skipped || [] }
      rememberFailedEmails(currentResult.value)
      setStatus('提链任务已取消；已完成的链接已写入管理表。')
      localStorage.removeItem(JOB_STORAGE_KEY)
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (job.status === 'error' || job.status === 'failed') {
      rememberFailedEmails(job.result || {})
      localStorage.removeItem(JOB_STORAGE_KEY)
      await Promise.all([refreshAccounts(), refreshLinks()])
      throw new Error(job.error || '生成失败')
    }
    setStatus(total ? `任务执行中，已完成 ${completed}/${total}，已记录 ${logs.value.length} 条日志。` : `任务执行中，已记录 ${logs.value.length} 条日志。`)
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({ jobId, accountCount: total, concurrency: job.concurrency || form.value.concurrency, startedAt: Date.now() }))
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
  const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' })
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
function saveProtocolForm(options = {}) {
  localStorage.setItem(PROTOCOL_FORM_STORAGE_KEY, JSON.stringify(protocolForm.value))
  if (!options.silent && !protocolBusy.value) setProtocolStatus('协议支付输入已保存。')
}
function validateProtocolPayment() {
  protocolForm.value.country = String(protocolForm.value.country || 'US').trim().toUpperCase()
  if (!String(protocolForm.value.paypalLink || '').trim()) { setProtocolStatus('请填写 BA 链接或 BA token。', true); return false }
  if (protocolForm.value.country !== 'US') { setProtocolStatus('当前协议支付仅开放 US。', true); return false }
  if (!String(protocolForm.value.phone || '').trim()) { setProtocolStatus('请填写手机号。', true); return false }
  if (!String(protocolForm.value.smsRecordUrl || '').trim()) { setProtocolStatus('请填写 SMS record URL。', true); return false }
  protocolForm.value.smsRecordWaitSeconds = Math.max(60, Math.min(900, Number(protocolForm.value.smsRecordWaitSeconds || 300)))
  protocolForm.value.smsRecordPollSeconds = Math.max(1, Math.min(30, Number(protocolForm.value.smsRecordPollSeconds || 3)))
  return true
}

async function startProtocolPayment() {
  if (!validateProtocolPayment()) return
  protocolBusy.value = true
  protocolCanceling.value = false
  protocolLogs.value = []
  protocolResult.value = null
  protocolJob.value = null
  activeTab.value = 'protocol'
  setProtocolStatus('协议支付任务已提交，正在启动本地 PayPal 引擎。')
  try {
    saveProtocolForm({ silent: true })
    const payload = {
      paypalLink: protocolForm.value.paypalLink,
      phone: protocolForm.value.phone,
      smsRecordUrl: protocolForm.value.smsRecordUrl,
      proxies: protocolForm.value.proxies,
      country: protocolForm.value.country,
      accountEmail: protocolForm.value.accountEmail,
      smsRecordWaitSeconds: protocolForm.value.smsRecordWaitSeconds,
      smsRecordPollSeconds: protocolForm.value.smsRecordPollSeconds,
    }
    const data = await api.startUsPaypalProtocol(payload)
    if (!data.job_id) throw new Error('后端没有返回协议支付任务 ID')
    protocolJob.value = { id: data.job_id, status: 'queued', total: 1, completed: 0 }
    localStorage.setItem(PROTOCOL_JOB_STORAGE_KEY, JSON.stringify({ jobId: data.job_id, startedAt: Date.now() }))
    await pollProtocolJob(data.job_id)
  } catch (error) {
    setProtocolStatus(cleanError(error), true)
  } finally {
    protocolBusy.value = false
    protocolCanceling.value = false
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
      setProtocolStatus('协议支付成功。')
      localStorage.removeItem(PROTOCOL_JOB_STORAGE_KEY)
      await refreshAccounts()
      return
    }
    if (job.status === 'cancelled') {
      setProtocolStatus('协议支付任务已取消。')
      localStorage.removeItem(PROTOCOL_JOB_STORAGE_KEY)
      return
    }
    if (job.status === 'error' || job.status === 'failed') {
      localStorage.removeItem(PROTOCOL_JOB_STORAGE_KEY)
      throw new Error(job.error || '协议支付失败')
    }
    setProtocolStatus(`协议支付执行中，已记录 ${protocolLogs.value.length} 条日志。`)
    localStorage.setItem(PROTOCOL_JOB_STORAGE_KEY, JSON.stringify({ jobId, startedAt: Date.now() }))
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

onMounted(async () => {
  componentUnmounted = false
  try {
    const savedForm = JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(form.value)) {
      if (savedForm[key] !== undefined) form.value[key] = savedForm[key]
    }
  } catch { /* ignore malformed local state */ }
  try {
    const savedProtocolForm = JSON.parse(localStorage.getItem(PROTOCOL_FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(protocolForm.value)) {
      if (savedProtocolForm[key] !== undefined) protocolForm.value[key] = savedProtocolForm[key]
    }
  } catch { /* ignore malformed protocol state */ }
  await reloadAll()
  try {
    const saved = JSON.parse(localStorage.getItem(JOB_STORAGE_KEY) || '{}')
    if (saved.jobId) {
      activeTab.value = 'links'
      busy.value = true
      canceling.value = false
      currentJob.value = { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 0), completed: 0, concurrency: Number(saved.concurrency || 1), running_count: 0 }
      setStatus('已恢复提链任务，正在重新同步后端进度。')
      await pollJob(saved.jobId)
    }
  } catch (error) {
    localStorage.removeItem(JOB_STORAGE_KEY)
    currentJob.value = null
    busy.value = false
    setStatus(`恢复任务失败：${cleanError(error)}`, true)
  } finally {
    if (!componentUnmounted) {
      busy.value = false
      canceling.value = false
    }
  }
  try {
    const savedProtocol = JSON.parse(localStorage.getItem(PROTOCOL_JOB_STORAGE_KEY) || '{}')
    if (savedProtocol.jobId) {
      activeTab.value = 'protocol'
      protocolBusy.value = true
      protocolCanceling.value = false
      protocolJob.value = { id: savedProtocol.jobId, status: 'queued', total: 1, completed: 0 }
      setProtocolStatus('已恢复协议支付任务，正在重新同步后端进度。')
      await pollProtocolJob(savedProtocol.jobId)
    }
  } catch (error) {
    localStorage.removeItem(PROTOCOL_JOB_STORAGE_KEY)
    protocolJob.value = null
    protocolBusy.value = false
    setProtocolStatus(`恢复协议支付失败：${cleanError(error)}`, true)
  } finally {
    if (!componentUnmounted) {
      protocolBusy.value = false
      protocolCanceling.value = false
    }
  }
})

watch(form, () => localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value)), { deep: true })
watch(protocolForm, () => localStorage.setItem(PROTOCOL_FORM_STORAGE_KEY, JSON.stringify(protocolForm.value)), { deep: true })

onBeforeUnmount(() => { componentUnmounted = true })
</script>
