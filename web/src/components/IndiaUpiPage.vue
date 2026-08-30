<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-2">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div class="inline-flex w-fit rounded-xl border border-gray-800 bg-gray-900/80 p-1">
          <button
            type="button"
            @click="activeUpiTab = 'extract'"
            class="rounded-lg px-4 py-2 text-sm font-bold transition"
            :class="activeUpiTab === 'extract' ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'"
          >提链页</button>
          <button
            type="button"
            @click="activeUpiTab = 'tempExtract'"
            class="rounded-lg px-4 py-2 text-sm font-bold transition"
            :class="activeUpiTab === 'tempExtract' ? 'bg-amber-600 text-white shadow-lg shadow-amber-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'"
          >临时提链页</button>
          <button
            type="button"
            @click="activeUpiTab = 'payment'"
            class="rounded-lg px-4 py-2 text-sm font-bold transition"
            :class="activeUpiTab === 'payment' ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'"
          >支付页</button>
        </div>
        <p class="px-2 text-xs text-gray-500">
          印度 UPI 正式提链、临时提链和支付分开管理，切换不会清空当前输入。
          <span class="ml-2 inline-flex items-center gap-1 text-gray-400">
            <span class="h-2 w-2 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
            {{ busy ? progressText : '本地服务在线' }}
          </span>
        </p>
      </div>
    </section>

    <section v-if="activeUpiTab === 'payment'" class="overflow-hidden rounded-2xl border border-cyan-500/20 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.13),transparent_34%),linear-gradient(135deg,rgba(15,23,42,0.96),rgba(2,6,23,0.98))] p-5 shadow-2xl shadow-black/30 md:p-6">
      <div class="flex flex-col gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-start md:justify-between">
        <div>
          <p class="text-xs font-black uppercase tracking-[0.22em] text-cyan-300/80">UPI Payment Desk</p>
          <h2 class="mt-2 text-2xl font-black text-white md:text-3xl">支付页：提交 UPI-SCAN 任务</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-400">自动同步已提取的有效 UPI 链接，并按顺序配对 UPI-SCAN CDK，提交到支付扫描接口后轮询 status_token 查询任务状态。</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="importExtractedLinksToPayment" :disabled="paymentBusy" class="rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-500/20 disabled:opacity-50">同步已提取链接</button>
          <button @click="runAllPayments" :disabled="paymentBusy || !paymentStartable" class="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">▶ 提交全部</button>
          <button @click="clearExpiredPaymentLinks" :disabled="paymentBusy || !expiredPaymentLinkCount" class="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-bold text-amber-100 transition hover:bg-amber-500/20 disabled:opacity-50">清理失效</button>
          <button @click="clearFinishedPayments" :disabled="paymentBusy || !paymentLinks.length" class="rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:bg-slate-800 disabled:opacity-50">清理已结束</button>
        </div>
      </div>

      <div class="mt-5 grid gap-3 md:grid-cols-5">
        <div v-for="card in paymentSummaryCards" :key="card.label" class="rounded-2xl border bg-slate-950/70 p-4" :class="card.class">
          <div class="text-xs font-bold uppercase tracking-wide text-slate-500">{{ card.label }}</div>
          <div class="mt-2 text-3xl font-black text-white">{{ card.value }}</div>
        </div>
      </div>

      <div class="mt-5 grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
        <section class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-bold text-white">UPI-SCAN 输入池</h3>
            <span class="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold text-slate-300">{{ paymentLinks.length }} 链接 / {{ paymentCdks.length }} CDK</span>
          </div>
          <p class="mt-4 rounded-xl border border-cyan-500/20 bg-cyan-500/10 p-3 text-xs leading-5 text-cyan-100">
            支付链接来源固定为“已提取链接”：点击“同步已提取链接”或“提交全部”时会自动同步，且只导入未失效链接。
          </p>
          <label class="mt-4 block">
            <span class="mb-2 block text-xs font-bold uppercase tracking-wide text-slate-500">UPI-SCAN CDK 池</span>
            <textarea v-model="paymentCdkInput" rows="5" spellcheck="false" placeholder="一行一个 UPI-SCAN-XXXXXX-XXXXXX" class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none" :disabled="paymentBusy"></textarea>
          </label>
          <div class="mt-3 flex flex-wrap gap-2">
            <button @click="addPaymentCdks" :disabled="paymentBusy" class="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50">加入 CDK 池</button>
            <button @click="clearPaymentLinks" :disabled="paymentBusy || !paymentLinks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空队列</button>
            <button @click="clearPaymentCdks" :disabled="paymentBusy || !paymentCdks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空 CDK</button>
          </div>
          <div class="mt-4 rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">{{ paymentStatusText }}</div>
          <div class="mt-4 max-h-56 overflow-auto rounded-xl border border-slate-800">
            <table class="w-full text-left text-sm">
              <thead class="sticky top-0 bg-slate-900 text-xs uppercase tracking-wide text-slate-500"><tr><th class="px-3 py-2">CDK</th><th class="px-3 py-2">状态</th></tr></thead>
              <tbody class="divide-y divide-slate-900">
                <tr v-if="!paymentCdks.length"><td colspan="2" class="px-3 py-6 text-center text-slate-500">暂无 UPI-SCAN CDK</td></tr>
                <tr v-for="cdk in visiblePaymentCdks" :key="cdk.id" class="hover:bg-slate-900/50">
                  <td class="px-3 py-2 font-mono text-xs text-slate-400">{{ maskPaymentSecret(cdk.value) }}</td>
                  <td class="px-3 py-2"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="paymentCdkStatusClass(cdk.status)">{{ paymentCdkStatusText(cdk.status) }}</span><div v-if="cdk.message" class="mt-1 text-xs text-slate-500">{{ cdk.message }}</div></td>
                </tr>
              </tbody>
            </table>
            <div v-if="hiddenPaymentCdkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-slate-800 bg-slate-950/95 px-3 py-2 text-xs text-slate-500">
              <span>已显示 {{ visiblePaymentCdks.length }} / {{ paymentCdks.length }}，剩余 {{ hiddenPaymentCdkCount }} 项</span>
              <button @click="showMorePaymentCdks" class="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 font-semibold text-slate-200 hover:bg-slate-800">加载更多</button>
            </div>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <div class="overflow-auto rounded-xl border border-slate-800">
            <table class="min-w-[980px] w-full text-left text-sm">
              <thead class="bg-slate-900 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th class="px-3 py-2">状态</th>
                  <th class="px-3 py-2">Job ID</th>
                  <th class="px-3 py-2">CDK</th>
                  <th class="px-3 py-2">剩余时间</th>
                  <th class="px-3 py-2">账号/消息</th>
                  <th class="px-3 py-2">链接</th>
                  <th class="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-900">
                <tr v-if="!paymentLinks.length"><td colspan="7" class="px-3 py-10 text-center text-slate-500">暂无任务队列</td></tr>
                <tr v-for="item in visiblePaymentLinks" :key="item.id" class="hover:bg-slate-900/50">
                  <td class="px-3 py-3"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="paymentLinkStatusClass(item.status)">{{ paymentLinkStatusText(item.status) }}</span><div v-if="item.message" class="mt-1 max-w-[180px] truncate text-xs text-slate-500" :title="item.message">{{ item.message }}</div></td>
                  <td class="max-w-[160px] truncate px-3 py-3 font-mono text-xs text-slate-500">{{ item.jobId || '-' }}</td>
                  <td class="max-w-[180px] truncate px-3 py-3 font-mono text-xs text-slate-500">{{ maskPaymentSecret(item.cdk || '') }}</td>
                  <td class="px-3 py-3 text-xs"><span class="rounded-full border px-2 py-1 font-semibold" :class="paymentExpiryClass(item)">{{ paymentExpiryText(item) }}</span></td>
                  <td class="max-w-[260px] px-3 py-3 text-xs text-slate-500"><div class="truncate font-mono text-slate-400">{{ item.accountEmail || '-' }}</div><div v-if="item.message" class="mt-1 truncate" :title="item.message">{{ item.message }}</div></td>
                  <td class="max-w-[320px] truncate px-3 py-3 font-mono text-xs text-slate-500">{{ item.value }}</td>
                  <td class="px-3 py-3 text-right">
                    <button @click="runPaymentTask(item)" :disabled="paymentBusy || !paymentTaskRunnable(item)" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200 disabled:cursor-not-allowed disabled:opacity-50">提交/查询</button>
                    <a :href="item.value || '#'" target="_blank" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!item.value ? 'pointer-events-none opacity-50' : ''">打开</a>
                    <button @click="copy(item.paymentUri || item.value)" class="ml-2 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800">复制</button>
                    <button @click="removePaymentLink(item.id)" :disabled="paymentBusy" class="ml-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="hiddenPaymentLinkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-slate-800 bg-slate-950/95 px-3 py-2 text-xs text-slate-500">
              <span>已显示 {{ visiblePaymentLinks.length }} / {{ paymentLinks.length }}，剩余 {{ hiddenPaymentLinkCount }} 项</span>
              <button @click="showMorePaymentLinks" class="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 font-semibold text-slate-200 hover:bg-slate-800">加载更多</button>
            </div>
          </div>
        </section>
      </div>
    </section>

    <template v-else>
    <div class="grid grid-cols-1 items-start gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">{{ isTempExtract ? '临时 Generate CDK' : 'IN 代理' }}</h3>
        </div>

        <div class="mt-5 space-y-5">
          <template v-if="isTempExtract">
            <label class="block">
              <span class="mb-2 block text-sm font-semibold text-gray-300">临时提链 CDK 池</span>
              <textarea v-model.trim="tempCdkInput" rows="5" spellcheck="false" placeholder="一行一个 UPI-GEN 临时提链 CDK" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-amber-500 focus:outline-none" :disabled="busy"></textarea>
              <span class="mt-1 block text-xs text-gray-500">一行一个 CDK；可用 {{ availableTempCdkCount }} / 冷却 {{ coolingTempCdkCount }} / 总计 {{ tempCdks.length }}。提交时会按账号顺序分配，成功后自动标记为已使用。</span>
            </label>
            <div class="flex flex-wrap gap-2">
              <button @click="addTempCdks" :disabled="busy" class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs font-bold text-amber-100 hover:bg-amber-500/20 disabled:opacity-50">加入 CDK 池</button>
              <button @click="clearUsedTempCdks" :disabled="busy || !usedTempCdkCount" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-bold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清理已使用</button>
              <button @click="clearTempCdks" :disabled="busy || !tempCdks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空 CDK</button>
            </div>
            <div class="max-h-56 overflow-auto rounded-xl border border-gray-800">
              <table class="w-full text-left text-sm">
                <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500"><tr><th class="px-3 py-2">CDK</th><th class="px-3 py-2">状态</th><th class="px-3 py-2">账号</th><th class="px-3 py-2 text-right">操作</th></tr></thead>
                <tbody class="divide-y divide-gray-900">
                  <tr v-if="!tempCdks.length"><td colspan="4" class="px-3 py-8 text-center text-gray-500">暂无临时提链 CDK</td></tr>
                  <tr v-for="item in visibleTempCdks" :key="item.id" class="hover:bg-gray-900/50">
                    <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ maskPaymentSecret(item.value) }}</td>
                    <td class="px-3 py-2"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="tempCdkStatusClass(item.status)">{{ tempCdkStatusText(item.status) }}</span><div v-if="tempCdkInfoText(item)" class="mt-1 max-w-[220px] truncate text-xs text-gray-500" :title="tempCdkInfoText(item)">{{ tempCdkInfoText(item) }}</div></td>
                    <td class="max-w-[180px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ item.accountEmail || '-' }}</td>
                    <td class="px-3 py-2 text-right"><button @click="removeTempCdk(item.id)" :disabled="busy" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button></td>
                  </tr>
                </tbody>
              </table>
              <div v-if="hiddenTempCdkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
                <span>已显示 {{ visibleTempCdks.length }} / {{ tempCdks.length }}，剩余 {{ hiddenTempCdkCount }} 项</span>
                <button @click="showMoreTempCdks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
              </div>
            </div>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="tempForm.concurrency" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-amber-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 5，最高 20。</span>
            </label>
          </template>

          <template v-else>
          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">IN 代理列表</span>
            <textarea v-model.trim="form.proxies" rows="8" spellcheck="false" placeholder="每行一个代理；支持 host:port:user:pass 或 socks5h://user:pass@host:port" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none" :disabled="busy"></textarea>
            <span class="mt-1 block text-xs text-gray-500">711/ArxLabs 的 host:port:user:pass 会自动按 socks5h 使用。</span>
          </label>

          <div class="grid gap-4 md:grid-cols-3">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="form.concurrency" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 1，最高 20。</span>
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

          <details class="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
            <summary class="cursor-pointer text-sm font-semibold text-gray-200">高级设置</summary>
            <div class="mt-4 grid gap-4 md:grid-cols-2">
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">本地代理链</span>
                <input v-model.trim="form.localProxy" placeholder="留空；仅需链式 HTTP 代理时填写" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Kookeey 入口</span>
                <input v-model.trim="form.kookeeyEndpoint" placeholder="gate.kookeey.info:1000" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Kookeey 用户名</span>
                <input v-model.trim="form.kookeeyUser" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
              <label class="block">
                <span class="mb-1.5 block text-xs text-gray-400">Kookeey 密码</span>
                <input v-model="form.kookeeyPass" type="password" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              </label>
            </div>
          </details>
          </template>

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="busy" class="rounded-lg px-5 py-2.5 text-sm font-semibold text-white transition disabled:opacity-50" :class="isTempExtract ? 'bg-amber-600 hover:bg-amber-500' : 'bg-emerald-600 hover:bg-emerald-500'">
              {{ busy ? '提取中...' : `${isTempExtract ? '开始临时提链' : '开始提链'} (${selectedEmails.length})` }}
            </button>
            <button v-if="busy && currentJob?.id" @click="cancelJob" :disabled="canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
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
            <option value="success">已提链</option>
            <option value="paid">已支付</option>
          </select>
          <div class="flex flex-wrap gap-2">
            <button @click="selectAllFiltered" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
            <button @click="clearSelectedAccounts" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
            <button @click="deleteSelectedUpiAccounts" :disabled="busy || deletingUpiAccounts.size > 0 || !selectedEmails.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50">
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
              <tr v-for="account in visibleAccounts" :key="account.email" class="hover:bg-gray-900/50">
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
                  <button @click="deleteUpiAccount(account.email)" :disabled="busy || deletingUpiAccounts.has(account.email)" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50" title="从 UPI 账号池和仪表盘账号池中删除该账号">
                    {{ deletingUpiAccounts.has(account.email) ? '删除中' : '删除' }}
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
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-mono text-emerald-200">{{ item.email }}</span>
                <span class="rounded-full border px-2 py-0.5 font-semibold" :class="upiExpiryClass(item.link)">
                  {{ upiExpiryText(item.link) }}
                </span>
              </div>
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="upiLinkUrl(item.link) || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!upiLinkActionable(item.link) ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(upiLinkUrl(item.link))" :disabled="!upiLinkActionable(item.link)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100 disabled:cursor-not-allowed disabled:opacity-50">复制链</button>
              </div>
            </div>
            <div v-if="recentResultFilter !== 'success'" v-for="item in visibleRecentResultErrors" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-mono">{{ item.email }}</span>
                <span v-if="failureLabel(item)" class="rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-0.5 font-semibold text-rose-100">{{ failureLabel(item) }}</span>
              </div>
              <div class="mt-1 break-words">{{ item.error }}</div>
              <div v-if="retryHint(item)" class="mt-1 text-amber-200">建议：{{ retryHint(item) }}</div>
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
          <h3 class="mt-1 text-xl font-bold text-white">已提取 UPI 链接</h3>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button>
          <button @click="exportLinks" :disabled="!links.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button>
          <button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
          <button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空</button>
          <button @click="importExtractedLinksToPayment" :disabled="!importablePaymentLinks.length" class="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50">同步支付页</button>
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
              <th class="px-3 py-2">剩余时间</th>
              <th class="px-3 py-2">操作</th>
              <th class="px-3 py-2">付款载荷</th>
              <th class="px-3 py-2">UPI 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!links.length">
              <td colspan="9" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in visibleLinks" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ link.created_at || link.createdAt || '-' }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || link.accountEmail || '-' }}</td>
              <td class="px-3 py-2 text-xs text-gray-400">{{ link.amount || '-' }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-400">{{ link.cs_id || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-xs">
                <span class="rounded-full border px-2 py-1 font-semibold" :class="upiExpiryClass(link)">
                  {{ upiExpiryText(link) }}
                </span>
              </td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-2">
                  <a :href="upiLinkUrl(link) || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!upiLinkActionable(link) ? 'pointer-events-none opacity-50' : ''">打开</a>
                  <button @click="copy(upiLinkUrl(link))" :disabled="!upiLinkActionable(link)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200 disabled:cursor-not-allowed disabled:opacity-50">复制链</button>
                </div>
              </td>
              <td class="max-w-[260px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ upiPaymentUri(link) || '-' }}</td>
              <td class="max-w-[360px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ upiLinkUrl(link) || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="hiddenLinkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
          <span>已显示 {{ visibleLinks.length }} / {{ links.length }}，剩余 {{ hiddenLinkCount }} 项</span>
          <button @click="showMoreLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
        </div>
      </div>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { createDeferredStorageWriter } from '../deferredStorage.js'
import { createPollingLifecycle, createSharedPollingGate } from '../pollingLifecycle.js'
import { readPollingSnapshot } from '../pollingRecovery.js'
import { createSessionStorageFacade } from '../sessionStorageScope.js'
import { cancelStartAckGeneration, commitStartAckSnapshot, markStartAckGenerationUnknown, reserveStartAckGeneration, watchStartAckGeneration } from '../startAckCas.js'
import { LOCAL_PAYMENT_POLL_PAUSED, isAmbiguousPaymentFailure } from '../paymentRequestState.js'
import NotificationSoundControl from './NotificationSoundControl.vue'
import { PAYMENT_RETRYABLE_LINK_STATUSES, extractedLinkPaymentSeed, indiaUpiCdkStatusClass, isTempCdkCoolingError, paymentPairUnavailableMessage, tempCdkCooldownUntil, tempCdkRemainingText } from '../indiaUpiPaymentQueue.js'
import { LINK_SUCCESS_SOUND_URL, playNotificationSound } from '../notificationSounds.js'

const FORM_STORAGE_KEY = 'autotoken_india_upi_form'
const TEMP_FORM_STORAGE_KEY = 'autotoken_india_upi_temp_form'
const TEMP_CDK_STATE_STORAGE_KEY = 'autotoken_india_upi_temp_cdks'
const JOB_STORAGE_KEY = 'autotoken_india_upi_job'
const ACTIVE_TAB_STORAGE_KEY = 'autotoken_india_upi_active_tab'
const PAYMENT_STATE_STORAGE_KEY = 'autotoken_india_upi_payment_state'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented'])
const PAYMENT_TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'stopped', 'cancelled', 'canceled', 'error'])
const PAYMENT_MAX_CONCURRENCY = 5
const ACCOUNT_STATUS_TEXT = { pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', paid: '已支付' }
const UPI_LINK_TTL_MS = 5 * 60 * 1000

const storageWriter = createDeferredStorageWriter()
const sessionStorage = createSessionStorageFacade()
const form = ref({ proxies: '', concurrency: 1, maxAttempts: 5, proxyPreflightAttempts: 5, localProxy: '', kookeeyEndpoint: 'gate.kookeey.info:1000', kookeeyUser: '', kookeeyPass: '', notificationSoundEnabled: true })
const tempForm = ref({ cdk: '', concurrency: 5 })
const tempCdkInput = ref('')
const tempCdks = ref([])
const tempCdkVisibleCount = ref(100)
const accounts = ref([])
const links = ref([])
const linkVisibleCount = ref(100)
const nowMs = ref(Date.now())
const savedTab = sessionStorage.getItem(ACTIVE_TAB_STORAGE_KEY)
const activeUpiTab = ref(['extract', 'tempExtract', 'payment'].includes(savedTab) ? savedTab : 'extract')
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const busy = ref(false)
const startAckPending = ref(false)
const canceling = ref(false)
const currentJob = ref(null)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const currentResult = ref(null)
const accountFilter = ref('')
const accountStatusFilter = ref('all')
const accountVisibleCount = ref(100)
const recentResultFilter = ref('all')
const recentResultVisibleCount = ref(100)
const retryFailedEmailSet = ref(new Set())
const deletingUpiAccounts = ref(new Set())
const paymentCdkInput = ref('')
const paymentLinks = ref([])
const paymentCdks = ref([])
const paymentLinkVisibleCount = ref(100)
const paymentCdkVisibleCount = ref(100)
const paymentBusy = ref(false)
const paymentRunningCount = ref(0)
const paymentStatusText = ref('等待同步已提取 UPI 链接并加入 UPI-SCAN CDK。')
const logRef = ref(null)
let componentUnmounted = false
const networkPollingGate = createSharedPollingGate()
const expiryClock = createPollingLifecycle()
let expiryClockToken = null
let startAckWatcher = null
let restoreActiveJobPromise = null

function persistJsonState(storageKey, value) {
  if (componentUnmounted) {
    storageWriter.writeJsonNow(storageKey, value)
    return
  }
  storageWriter.queueJson(storageKey, value)
}

const isTempExtract = computed(() => activeUpiTab.value === 'tempExtract')
const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const retryFailedEmails = computed(() => Array.from(retryFailedEmailSet.value).filter(email => accounts.value.some(account => account.email === email && accountSelectable(account))))
const availableTempCdkCount = computed(() => tempCdks.value.filter(item => item.status === 'available').length)
const coolingTempCdkCount = computed(() => tempCdks.value.filter(item => item.status === 'cooling').length)
const usedTempCdkCount = computed(() => tempCdks.value.filter(item => item.status === 'used').length)
const currentResultSuccesses = computed(() => Array.isArray(currentResult.value?.successes) ? [...currentResult.value.successes].reverse() : [])
const currentResultErrors = computed(() => Array.isArray(currentResult.value?.errors) ? [...currentResult.value.errors].reverse() : [])
const currentResultSkipped = computed(() => Array.isArray(currentResult.value?.skipped) ? [...currentResult.value.skipped].reverse() : [])
const filteredRecentResultCount = computed(() => {
  if (recentResultFilter.value === 'success') return currentResultSuccesses.value.length
  if (recentResultFilter.value === 'failed') return currentResultErrors.value.length
  return currentResultSuccesses.value.length + currentResultErrors.value.length + currentResultSkipped.value.length
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
const filteredAccounts = computed(() => accounts.value.filter((account) => {
  const status = accountStatus(account)
  return (!accountFilter.value || String(account.email || '').toLowerCase().includes(accountFilter.value.toLowerCase())) && (accountStatusFilter.value === 'all' || status === accountStatusFilter.value)
}))
const visibleAccounts = computed(() => filteredAccounts.value.slice(0, accountVisibleCount.value))
const hiddenAccountCount = computed(() => Math.max(0, filteredAccounts.value.length - visibleAccounts.value.length))
const visibleTempCdks = computed(() => tempCdks.value.slice(0, tempCdkVisibleCount.value))
const hiddenTempCdkCount = computed(() => Math.max(0, tempCdks.value.length - visibleTempCdks.value.length))
const visibleLinks = computed(() => links.value.slice(0, linkVisibleCount.value))
const hiddenLinkCount = computed(() => Math.max(0, links.value.length - visibleLinks.value.length))
const visiblePaymentLinks = computed(() => paymentLinks.value.slice(0, paymentLinkVisibleCount.value))
const hiddenPaymentLinkCount = computed(() => Math.max(0, paymentLinks.value.length - visiblePaymentLinks.value.length))
const visiblePaymentCdks = computed(() => paymentCdks.value.slice(0, paymentCdkVisibleCount.value))
const hiddenPaymentCdkCount = computed(() => Math.max(0, paymentCdks.value.length - visiblePaymentCdks.value.length))
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
const paymentSummaryCards = computed(() => [
  { label: '待提交', value: paymentLinks.value.filter(item => paymentTaskRunnable(item)).length, class: 'border-blue-500/30' },
  { label: '正在运行', value: paymentRunningCount.value, class: 'border-sky-500/30' },
  { label: '已成功', value: paymentLinks.value.filter(item => item.status === 'success').length, class: 'border-emerald-500/30' },
  { label: '失效/需处理', value: paymentLinks.value.filter(item => paymentLinkInvalid(item) || ['failed', 'stopped', 'needs_action'].includes(item.status)).length, class: 'border-rose-500/30' },
  { label: '可用 CDK', value: paymentCdks.value.filter(paymentCdkReusable).length, class: 'border-cyan-500/30' },
])
const paymentRunnableCount = computed(() => paymentLinks.value.filter(item => paymentTaskRunnable(item)).length)
const expiredPaymentLinkCount = computed(() => paymentLinks.value.filter(paymentLinkInvalid).length)
const importablePaymentLinks = computed(() => links.value.filter(upiLinkImportable))
const paymentStartable = computed(() => paymentRunnableCount.value || (importablePaymentLinks.value.length && paymentCdks.value.some(paymentCdkReusable)))

function setStatus(message, error = false) { statusText.value = message; statusError.value = error }
function cleanText(value) { return String(value || '未知错误').replace(/\s+/g, ' ').trim() }
function cleanError(error) { return cleanText(error?.message || error) }

function isBlockingUpiExtractionJob(job = currentJob.value) {
  const jobId = String(job?.id || '').trim()
  if (!jobId) return false
  const status = String(job?.status || '').trim().toLowerCase()
  return !TERMINAL_STATUSES.has(status)
}

function syncUpiExtractionBusy() {
  const locked = startAckPending.value || isBlockingUpiExtractionJob()
  busy.value = locked
  return locked
}

function applyStartAckCheckpoint(checkpoint) {
  startAckPending.value = Boolean(checkpoint)
  syncUpiExtractionBusy()
  if (!checkpoint) return
  canceling.value = false
  if (['extract', 'tempExtract'].includes(checkpoint.mode)) activeUpiTab.value = checkpoint.mode
  const requestId = String(checkpoint.clientRequestId || '').trim()
  const suffix = requestId ? `（请求 ${requestId}）` : ''
  if (checkpoint.status === 'unknown') {
    setStatus(`上次 UPI 任务启动结果未知${suffix}，已锁定重复提交；请保留当前会话等待人工核对。`, true)
    return
  }
  setStatus(`上次 UPI 任务仍在等待后端确认${suffix}，当前页面会在 ACK 到达后自动恢复。`)
}

function installStartAckWatcher() {
  startAckWatcher?.unsubscribe()
  startAckWatcher = watchStartAckGeneration({
    storage: sessionStorage,
    storageKey: JOB_STORAGE_KEY,
    onChange: (event) => {
      if (componentUnmounted) return
      if (event.type === 'acknowledged') {
        applyStartAckCheckpoint(null)
        void restoreActiveJob().then((restored) => {
          if (!restored && !componentUnmounted) void restoreActiveJob()
        })
        return
      }
      if (event.type === 'unknown') {
        applyStartAckCheckpoint(event.checkpoint)
        return
      }
      applyStartAckCheckpoint(null)
      setStatus(`上次 UPI 任务启动失败：${event.error || '请求未被后端接受'}`, true)
    },
  })
  applyStartAckCheckpoint(startAckWatcher.checkpoint)
}

function parseLines(value) { return String(value || '').split(/\r?\n|,/).map(item => item.trim()).filter(Boolean) }
function tempCdkLines() { return tempCdks.value.filter(item => item.status === 'available').map(item => item.value) }
function tempCdkStatusText(status) {
  return ({ available: '可用', reserved: '运行中', cooling: '冷却中', used: '已使用', failed: '失败' })[String(status || '')] || '可用'
}
function tempCdkStatusClass(status) {
  return indiaUpiCdkStatusClass(status)
}
function tempCdkInfoText(item) {
  const coolingText = item?.status === 'cooling' ? tempCdkRemainingText(item.cooldownUntilMs, nowMs.value) : ''
  return [coolingText, item?.message || ''].filter(Boolean).join(' · ')
}
function makeTempCdkId() { return `temp-cdk-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}` }
function normalizeTempCdkItem(raw) {
  const value = String(typeof raw === 'string' ? raw : raw?.value || raw?.cdk || '').trim()
  if (!value) return null
  const rawStatus = String(typeof raw === 'object' ? raw.status || 'available' : 'available').toLowerCase()
  const rawCooldownUntilMs = Number(typeof raw === 'object' ? raw.cooldownUntilMs || raw.cooldown_until_ms || 0 : 0)
  const status = rawStatus === 'cooling' && rawCooldownUntilMs <= Date.now()
    ? 'available'
    : (['available', 'reserved', 'cooling', 'used', 'failed'].includes(rawStatus) ? rawStatus : 'available')
  return {
    id: String((typeof raw === 'object' && raw.id) || makeTempCdkId()),
    value,
    status,
    accountEmail: String((typeof raw === 'object' && (raw.accountEmail || raw.account_email)) || '').trim(),
    jobId: String((typeof raw === 'object' && (raw.jobId || raw.job_id)) || '').trim(),
    message: String((typeof raw === 'object' && (raw.message || raw.error)) || '').trim(),
    cooldownUntilMs: rawStatus === 'cooling' && rawCooldownUntilMs > Date.now() ? rawCooldownUntilMs : 0,
  }
}
function addTempCdks(options = {}) {
  const existing = new Set(tempCdks.value.map(item => item.value.toLowerCase()))
  const items = []
  for (const line of parseLines(tempCdkInput.value)) {
    const key = line.toLowerCase()
    if (existing.has(key)) continue
    existing.add(key)
    items.push({ id: makeTempCdkId(), value: line, status: 'available', accountEmail: '', jobId: '', message: '', cooldownUntilMs: 0 })
  }
  if (items.length) tempCdks.value = [...tempCdks.value, ...items]
  tempCdkInput.value = ''
  if (!options.silent) setStatus(items.length ? `已加入 ${items.length} 枚临时提链 CDK。` : '没有新增 CDK，可能为空或重复。')
  saveTempCdkState()
  return items.length
}
function removeTempCdk(id) {
  tempCdks.value = tempCdks.value.filter(item => item.id !== id)
  saveTempCdkState()
}
function clearUsedTempCdks() {
  const before = tempCdks.value.length
  tempCdks.value = tempCdks.value.filter(item => item.status !== 'used')
  setStatus(`已清理 ${before - tempCdks.value.length} 枚已使用 CDK。`)
  saveTempCdkState()
}
function clearTempCdks() {
  tempCdks.value = []
  tempCdkInput.value = ''
  setStatus('已清空临时提链 CDK 池。')
  saveTempCdkState()
}
function saveTempCdkState() {
  persistJsonState(TEMP_CDK_STATE_STORAGE_KEY, () => ({ cdks: tempCdks.value }))
}
function loadTempCdkState(legacyText = '') {
  try {
    const raw = JSON.parse(sessionStorage.getItem(TEMP_CDK_STATE_STORAGE_KEY) || '{}')
    tempCdks.value = Array.isArray(raw.cdks) ? raw.cdks.map(normalizeTempCdkItem).filter(Boolean) : []
  } catch {
    tempCdks.value = []
  }
  if (!tempCdks.value.length && legacyText) {
    tempCdks.value = tempCdkItemsFromLines(parseLines(legacyText))
    saveTempCdkState()
  }
}
function tempCdkItemsFromLines(lines) {
  const seen = new Set()
  const items = []
  for (const line of lines) {
    const key = String(line || '').trim().toLowerCase()
    if (!key || seen.has(key)) continue
    seen.add(key)
    items.push({ id: makeTempCdkId(), value: String(line).trim(), status: 'available', accountEmail: '', jobId: '', message: '', cooldownUntilMs: 0 })
  }
  return items
}
function reserveTempCdksForAccounts(emails, jobId = '') {
  const targets = Array.from(emails || [])
  const available = tempCdks.value.filter(item => item.status === 'available').slice(0, targets.length)
  for (let index = 0; index < available.length; index += 1) {
    available[index].status = 'reserved'
    available[index].accountEmail = targets[index] || ''
    available[index].jobId = jobId
    available[index].message = '已分配，等待临时提链结果。'
  }
  saveTempCdkState()
  return available.map(item => item.value)
}
function releaseReservedTempCdks(jobId = '', message = '任务未完成，CDK 已释放。') {
  for (const item of tempCdks.value) {
    if (item.status === 'reserved' && (!jobId || item.jobId === jobId)) {
      item.status = 'available'
      item.jobId = ''
      item.accountEmail = ''
      item.cooldownUntilMs = 0
      item.message = message
    }
  }
  saveTempCdkState()
}
function findTempCdkByValue(value) {
  const key = String(value || '').trim().toLowerCase()
  if (!key) return null
  return tempCdks.value.find(item => item.value.toLowerCase() === key) || null
}
function tempCdkAlreadyUsedError(error) {
  const text = cleanText(error?.error || error?.message || error).toLowerCase()
  return Boolean(error?.cdk_used)
    || text.includes('cdk has already been used')
    || text.includes('cdk already used')
    || text.includes('cdk 已使用')
    || text.includes('cdk已使用')
}
function applyTempCdkResult(result, jobId = '') {
  const successes = Array.isArray(result?.successes) ? result.successes : []
  const errors = Array.isArray(result?.errors) ? result.errors : []
  const touched = new Set()
  for (const success of successes) {
    const item = findTempCdkByValue(success?.cdk)
    if (!item) continue
    touched.add(item.id)
    item.status = 'used'
    item.jobId = jobId || item.jobId
    item.accountEmail = String(success?.email || item.accountEmail || '').trim()
    item.message = '提链成功，CDK 已使用。'
  }
  for (const error of errors) {
    const item = findTempCdkByValue(error?.cdk)
    if (!item || touched.has(item.id)) continue
    if (tempCdkAlreadyUsedError(error)) {
      item.status = 'used'
      item.jobId = jobId || item.jobId
      item.accountEmail = String(error?.email || item.accountEmail || '').trim()
      item.message = '临时 UPI 服务返回 CDK 已使用，已标记为已使用。'
      touched.add(item.id)
      continue
    }
    if (isTempCdkCoolingError(error)) {
      if (item.status === 'cooling' && Number(item.cooldownUntilMs || 0) > nowMs.value) {
        touched.add(item.id)
        continue
      }
      item.status = 'cooling'
      item.jobId = ''
      item.accountEmail = ''
      item.cooldownUntilMs = tempCdkCooldownUntil(nowMs.value, error)
      item.message = '临时 UPI 服务提示该 CDK 正在其他任务中运行，冷却 3 分钟后自动可用。'
      touched.add(item.id)
      continue
    }
    if (item.status === 'used') continue
    item.status = 'available'
    item.jobId = ''
    item.accountEmail = ''
    item.cooldownUntilMs = 0
    item.message = `提链失败，CDK 已释放：${cleanText(error?.error || '未知错误')}`
  }
  saveTempCdkState()
}
function releaseExpiredTempCdkCooldowns() {
  let changed = false
  for (const item of tempCdks.value) {
    if (item.status === 'cooling' && Number(item.cooldownUntilMs || 0) <= nowMs.value) {
      item.status = 'available'
      item.cooldownUntilMs = 0
      item.message = '冷却结束，CDK 已恢复可用。'
      changed = true
    }
  }
  if (changed) saveTempCdkState()
}
function accountJobStatus(account) { const statuses = currentJob.value?.account_statuses || {}; return statuses[account.email] || statuses[String(account.email || '').toLowerCase()] || null }
function accountStatus(account) { return accountJobStatus(account)?.status || account?.upi_status || 'pending' }
function ttlText(seconds) { const value = Number(seconds); if (!Number.isFinite(value) || value < 0) return '-'; if (value < 60) return `${Math.floor(value)}s`; if (value < 3600) return `${Math.ceil(value / 60)}m`; return `${Math.ceil(value / 3600)}h` }
function accountStatusText(account) { const jobStatus = accountJobStatus(account); if (jobStatus) return jobStatus.status_text || ACCOUNT_STATUS_TEXT[jobStatus.status] || '未提链'; return account.upi_status_text || ACCOUNT_STATUS_TEXT[account.upi_status] || '未提链' }
function accountStatusClass(account) { const status = accountStatus(account); return ({ running: 'border-blue-500/30 bg-blue-500/10 text-blue-300', success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300', failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300', paid: 'border-violet-500/30 bg-violet-500/10 text-violet-300' })[status] || 'border-gray-700 bg-gray-900 text-gray-400' }
function failureLabel(item) { return String(item?.failure_label || item?.failureLabel || item?.upi_failure_label || '').trim() }
function retryHint(item) { return String(item?.retry_hint || item?.retryHint || item?.upi_retry_hint || '').trim() }
function accountStatusError(account) {
  const status = accountJobStatus(account) || account || {}
  return [status.error || account.upi_error || '', failureLabel(status), retryHint(status)].filter(Boolean).join('\n')
}
function accountSelectable(account) { return account.upi_selectable !== false && accountStatus(account) !== 'paid' }
function toggleAccount(email) { const account = accounts.value.find(item => item.email === email); if (!account || !accountSelectable(account)) return; const next = new Set(selectedAccounts.value); next.has(email) ? next.delete(email) : next.add(email); selectedAccounts.value = next }
function selectAllFiltered() { selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).map(account => account.email)) }
function clearSelectedAccounts() { selectedAccounts.value = new Set() }
function showMoreAccounts() { accountVisibleCount.value = Math.min(filteredAccounts.value.length, accountVisibleCount.value + 100) }
function showMoreTempCdks() { tempCdkVisibleCount.value = Math.min(tempCdks.value.length, tempCdkVisibleCount.value + 100) }
function showMoreLinks() { linkVisibleCount.value = Math.min(links.value.length, linkVisibleCount.value + 100) }
function showMorePaymentLinks() { paymentLinkVisibleCount.value = Math.min(paymentLinks.value.length, paymentLinkVisibleCount.value + 100) }
function showMorePaymentCdks() { paymentCdkVisibleCount.value = Math.min(paymentCdks.value.length, paymentCdkVisibleCount.value + 100) }
function showMoreRecentResults() { recentResultVisibleCount.value = Math.min(filteredRecentResultCount.value, recentResultVisibleCount.value + 100) }
function toggleLink(id) { const next = new Set(selectedLinkIds.value); next.has(id) ? next.delete(id) : next.add(id); selectedLinkIds.value = next }
function rememberFailedEmails(result) { retryFailedEmailSet.value = new Set((result?.errors || []).map(item => String(item.email || '').trim()).filter(Boolean)) }
function upiLinkUrl(link) { return String(link?.hosted_instructions_url || link?.upi_link || '').trim() }
function upiPaymentUri(link) { return String(link?.upi_payment_uri || link?.upiPaymentUri || link?.qr_image_url_svg || link?.qr_image_url_png || '').trim() }
function timestampMs(value) {
  const raw = String(value ?? '').trim()
  if (!raw) return 0
  const numeric = Number(raw)
  if (Number.isFinite(numeric) && numeric > 0) return numeric > 1e12 ? numeric : numeric * 1000
  const parsed = Date.parse(raw.includes('T') ? raw : raw.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : 0
}
function upiExpiresAtMs(link) {
  const explicit = timestampMs(link?.upi_expires_at_ts ?? link?.upiExpiresAtTs)
  if (explicit) return explicit
  const created = timestampMs(link?.created_at_ts ?? link?.createdAtTs ?? link?.created_at ?? link?.createdAt)
  return created ? created + UPI_LINK_TTL_MS : 0
}
function upiRemainingMs(link) {
  const expiresAt = upiExpiresAtMs(link)
  return expiresAt ? expiresAt - nowMs.value : 0
}
function upiLinkExpired(link) {
  const expiresAt = upiExpiresAtMs(link)
  return Boolean(expiresAt && expiresAt <= nowMs.value)
}
function upiLinkActionable(link) { return Boolean(upiLinkUrl(link)) && !upiLinkExpired(link) }
function upiLinkImportable(link) { return Boolean(upiLinkUrl(link)) && Boolean(upiExpiresAtMs(link)) && !upiLinkExpired(link) }
function paymentLinkInvalid(item) { return !upiLinkUrl(item) || !upiExpiresAtMs(item) || upiLinkExpired(item) }
function upiExpiryText(link) {
  if (!upiLinkUrl(link)) return '-'
  const expiresAt = upiExpiresAtMs(link)
  if (!expiresAt || expiresAt <= nowMs.value) return '链接失效'
  const seconds = Math.max(0, Math.ceil((expiresAt - nowMs.value) / 1000))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return minutes ? `剩余 ${minutes}:${String(rest).padStart(2, '0')}` : `剩余 ${rest}s`
}
function upiExpiryClass(link) {
  if (!upiLinkUrl(link)) return 'border-gray-700 bg-gray-900 text-gray-400'
  if (upiLinkExpired(link)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (upiRemainingMs(link) <= 60 * 1000) return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
}
function paymentExpired(item) { return upiLinkExpired(item) }
function paymentExpiryText(item) { return upiExpiryText(item) }
function paymentExpiryClass(item) { return upiExpiryClass(item) }
function paymentQrImage(item) {
  const value = String(item?.paymentUri || '').trim()
  return value.startsWith('http') ? value : ''
}
function paymentLinkStatusText(status) {
  return ({ pending: '待提交', imported: '待提交', running: '运行中', success: '成功', failed: '失败', stopped: '已停止', needs_action: '需处理', unknown: '结果未知' })[String(status || '')] || '待提交'
}
function paymentLinkStatusClass(status) {
  const text = String(status || 'pending')
  if (text === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (text === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (['failed', 'stopped', 'needs_action'].includes(text)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (text === 'unknown') return 'border-orange-500/30 bg-orange-500/10 text-orange-200'
  return 'border-slate-700 bg-slate-900 text-slate-300'
}
function paymentCdkStatusText(status) {
  return ({ available: '可用', reserved: '已分配', used: '已核销', failed: '失效' })[String(status || '')] || '可用'
}
function paymentCdkStatusClass(status) {
  return indiaUpiCdkStatusClass(status)
}
function maskPaymentSecret(value) {
  const text = String(value || '').trim()
  if (!text) return '-'
  if (text.length <= 14) return text
  return `${text.slice(0, 7)}...${text.slice(-5)}`
}
function makePaymentId(prefix = 'upi-pay') { return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}` }
function normalizePaymentUrl(value) { return String(value || '').trim().replace(/\/+$/, '') }
function normalizePaymentItem(raw) {
  if (!raw || typeof raw !== 'object') return null
  const value = normalizePaymentUrl(raw.value || raw.upi_link || raw.hosted_instructions_url || raw.link || raw.url || '')
  const paymentUri = String(raw.paymentUri || raw.upi_payment_uri || raw.qr_image_url_svg || raw.qr_image_url_png || '').trim()
  const jobId = String(raw.jobId || raw.job_id || '').trim()
  const statusToken = String(raw.statusToken || raw.status_token || raw.jobToken || raw.job_token || raw.token || '').trim()
  if (!value && !jobId) return null
  const rawStatus = String(raw.status || (value ? 'pending' : 'failed')).toLowerCase()
  const remoteTerminal = raw.remoteTerminal === true || rawStatus === 'success'
  const liveRemoteJob = Boolean(jobId && statusToken && !remoteTerminal)
  const status = rawStatus === 'running' ? (liveRemoteJob ? 'needs_action' : 'unknown') : rawStatus
  return {
    id: String(raw.id || makePaymentId('link')),
    value,
    upi_link: value,
    hosted_instructions_url: value.startsWith('http') ? value : '',
    paymentUri,
    cdk: String(raw.cdk || '').trim(),
    cdkId: String(raw.cdkId || raw.cdk_id || '').trim(),
    jobId,
    statusToken,
    jobToken: statusToken,
    remoteTerminal,
    status,
    message: rawStatus === 'running'
      ? (liveRemoteJob ? '页面已恢复，可继续查询远端支付任务。' : '上次提交结果未知，关联 CDK 保持锁定。')
      : String(raw.message || raw.error || '').trim(),
    accountEmail: String(raw.accountEmail || raw.account_email || raw.account || '').trim(),
    created_at: raw.created_at || raw.createdAt || '',
    created_at_ts: raw.created_at_ts || raw.createdAtTs || 0,
    upi_expires_at_ts: raw.upi_expires_at_ts || raw.upiExpiresAtTs || raw.upiExpiresAt || 0,
  }
}
function normalizePaymentCdk(raw) {
  const value = String(typeof raw === 'string' ? raw : raw?.value || raw?.cdk || '').trim()
  if (!value) return null
  const status = String(typeof raw === 'object' ? raw.status || 'available' : 'available').toLowerCase()
  return {
    id: String((typeof raw === 'object' && raw.id) || makePaymentId('cdk')),
    value,
    status: ['available', 'reserved', 'used', 'failed'].includes(status) ? status : 'available',
    message: String((typeof raw === 'object' && (raw.message || raw.error)) || '').trim(),
    linkId: String((typeof raw === 'object' && (raw.linkId || raw.link_id)) || '').trim(),
    jobId: String((typeof raw === 'object' && (raw.jobId || raw.job_id)) || '').trim(),
  }
}
function savePaymentState() {
  persistJsonState(PAYMENT_STATE_STORAGE_KEY, () => ({ links: paymentLinks.value, cdks: paymentCdks.value }))
}
function loadPaymentState() {
  try {
    const raw = JSON.parse(sessionStorage.getItem(PAYMENT_STATE_STORAGE_KEY) || '{}')
    paymentLinks.value = Array.isArray(raw.links) ? raw.links.map(normalizePaymentItem).filter(Boolean) : []
    paymentCdks.value = Array.isArray(raw.cdks) ? raw.cdks.map(normalizePaymentCdk).filter(Boolean) : []
    paymentStatusText.value = paymentLinks.value.length || paymentCdks.value.length ? '已恢复上次 UPI-SCAN 支付页数据。' : '等待同步已提取 UPI 链接并加入 UPI-SCAN CDK。'
  } catch {
    paymentLinks.value = []
    paymentCdks.value = []
    paymentStatusText.value = '支付页缓存读取失败，已重置为空。'
  }
}
function addOrUpdatePaymentLink(raw) {
  const item = normalizePaymentItem(raw)
  if (!item?.value) return false
  const key = normalizePaymentUrl(item.value)
  const existing = paymentLinks.value.find(row => normalizePaymentUrl(row.value) === key)
  if (existing) {
    if (!['running', 'success'].includes(existing.status)) Object.assign(existing, item, { id: existing.id, cdk: existing.cdk, cdkId: existing.cdkId, jobId: existing.jobId, statusToken: existing.statusToken, jobToken: existing.jobToken, remoteTerminal: existing.remoteTerminal })
    return false
  }
  paymentLinks.value = [...paymentLinks.value, item]
  return true
}
function addPaymentCdks() {
  const existing = new Set(paymentCdks.value.map(item => item.value.toLowerCase()))
  const items = []
  for (const line of parseLines(paymentCdkInput.value)) {
    const key = line.toLowerCase()
    if (existing.has(key)) continue
    existing.add(key)
    items.push({ id: makePaymentId('cdk'), value: line, status: 'available', message: '', linkId: '', jobId: '' })
  }
  if (items.length) paymentCdks.value = [...paymentCdks.value, ...items]
  paymentCdkInput.value = ''
  paymentStatusText.value = items.length ? `已加入 ${items.length} 枚 UPI-SCAN CDK。` : '没有新增 CDK，可能为空或重复。'
  savePaymentState()
}
function syncExtractedLinksToPayment(options = {}) {
  let added = 0
  let updated = 0
  let skipped = 0
  for (const link of links.value) {
    const seed = extractedLinkPaymentSeed(link, { nowMs: nowMs.value, ttlMs: UPI_LINK_TTL_MS, makeId: makePaymentId })
    if (!seed) {
      skipped += 1
      continue
    }
    const before = paymentLinks.value.length
    const created = addOrUpdatePaymentLink(seed)
    if (created) added += 1
    else if (paymentLinks.value.length === before) updated += 1
  }
  if (!options.silent) {
    paymentStatusText.value = added || updated
      ? `已同步已提取有效链接：新增 ${added}，更新 ${updated}，跳过失效 ${skipped}。`
      : `没有可同步的有效 UPI 链接${skipped ? `，已跳过失效 ${skipped} 条` : ''}。`
  }
  savePaymentState()
  return { added, updated, skipped }
}
async function importExtractedLinksToPayment(options = {}) {
  await refreshLinks({ syncPayment: false })
  return syncExtractedLinksToPayment(options)
}
function releaseReservedCdkForLink(id, message = '') {
  for (const cdk of paymentCdks.value) {
    if (cdk.linkId === id && cdk.status === 'reserved') {
      cdk.status = 'available'
      cdk.linkId = ''
      cdk.message = message
    }
  }
}
function paymentTaskHasLiveRemoteJob(item) {
  return Boolean(item?.jobId && (item?.statusToken || item?.jobToken) && item.remoteTerminal !== true)
}
function paymentCdkSupportsLiveRemoteJob(cdk) {
  const cdkId = String(cdk?.id || '')
  const value = String(cdk?.value || '')
  const linkId = String(cdk?.linkId || '')
  const jobId = String(cdk?.jobId || '')
  return paymentLinks.value.some(item => paymentTaskHasLiveRemoteJob(item) && (
    (item.cdkId && String(item.cdkId) === cdkId)
    || (item.cdk && String(item.cdk) === value)
    || (item.id && String(item.id) === linkId)
    || (item.jobId && String(item.jobId) === jobId)
  ))
}
function paymentCdkReusable(cdk) {
  return cdk?.status === 'available' && !paymentCdkSupportsLiveRemoteJob(cdk)
}
function removePaymentLink(id) {
  const item = paymentLinks.value.find(row => row.id === id)
  if (paymentTaskHasLiveRemoteJob(item)) {
    paymentStatusText.value = '远端支付任务尚未结束，已保留支付记录和关联 CDK。'
    return
  }
  releaseReservedCdkForLink(id, '关联链接已移除，CDK 已释放。')
  paymentLinks.value = paymentLinks.value.filter(item => item.id !== id)
  paymentStatusText.value = '已移除支付记录。'
  savePaymentState()
}
function clearPaymentLinks() {
  const retained = paymentLinks.value.filter(paymentTaskHasLiveRemoteJob)
  const removable = paymentLinks.value.filter(item => !paymentTaskHasLiveRemoteJob(item))
  for (const item of removable) releaseReservedCdkForLink(item.id, '链接队列已清空，CDK 已释放。')
  paymentLinks.value = retained
  paymentStatusText.value = retained.length
    ? `已移除 ${removable.length} 条支付记录；保留 ${retained.length} 个尚未结束的远端任务及其 CDK。`
    : '已清空支付队列。'
  savePaymentState()
}
function clearPaymentCdks() {
  for (const link of paymentLinks.value) {
    if (paymentTaskHasLiveRemoteJob(link)) continue
    if (link.cdkId) {
      link.cdk = ''
      link.cdkId = ''
      if (link.status === 'running') link.status = 'pending'
    }
  }
  const before = paymentCdks.value.length
  paymentCdks.value = paymentCdks.value.filter(paymentCdkSupportsLiveRemoteJob)
  paymentStatusText.value = paymentCdks.value.length
    ? `已清理 ${before - paymentCdks.value.length} 枚 CDK；保留 ${paymentCdks.value.length} 枚仍关联远端任务的 CDK。`
    : '已清空 UPI-SCAN CDK 池。'
  savePaymentState()
}
function clearExpiredPaymentLinks() {
  const before = paymentLinks.value.length
  const expiredIds = new Set(paymentLinks.value.filter(item => paymentLinkInvalid(item) && !paymentTaskHasLiveRemoteJob(item)).map(item => String(item.id || '')).filter(Boolean))
  if (!expiredIds.size) {
    paymentStatusText.value = '没有可清理的失效链接。'
    return
  }
  for (const id of expiredIds) releaseReservedCdkForLink(id, '关联链接已失效并清理，CDK 已释放。')
  paymentLinks.value = paymentLinks.value.filter(item => !expiredIds.has(String(item.id || '')))
  paymentStatusText.value = `已清理 ${before - paymentLinks.value.length} 条失效链接。`
  savePaymentState()
}
function paymentTaskClearable(item) {
  const status = String(item?.status || 'pending')
  const restorable = paymentTaskHasLiveRemoteJob(item)
  if (restorable && ['running', 'needs_action'].includes(status)) return false
  if (restorable) return false
  return paymentLinkInvalid(item) || ['success', 'failed', 'stopped', 'needs_action'].includes(status)
}

function clearFinishedPayments() {
  const beforeLinks = paymentLinks.value.length
  const beforeCdks = paymentCdks.value.length
  const removableIds = new Set(paymentLinks.value.filter(paymentTaskClearable).map(item => String(item.id || '')).filter(Boolean))
  for (const id of removableIds) releaseReservedCdkForLink(id, '关联链接已结束或失效，CDK 已释放。')
  paymentLinks.value = paymentLinks.value.filter(item => !paymentTaskClearable(item))
  paymentCdks.value = paymentCdks.value.filter(item => paymentCdkSupportsLiveRemoteJob(item) || !['used', 'failed'].includes(item.status))
  paymentStatusText.value = `已清理 ${beforeLinks - paymentLinks.value.length} 条链接、${beforeCdks - paymentCdks.value.length} 枚 CDK。`
  savePaymentState()
}

function paymentTaskRunnable(item) {
  if (!item) return false
  if (paymentTaskHasLiveRemoteJob(item)) return !['success', 'running'].includes(String(item.status || 'pending'))
  if (!item.value || paymentLinkInvalid(item)) return false
  if (item.jobId && (item.statusToken || item.jobToken)) return !['success', 'running'].includes(String(item.status || 'pending'))
  return PAYMENT_RETRYABLE_LINK_STATUSES.has(String(item.status || 'pending')) && paymentCdks.value.some(paymentCdkReusable)
}
function paymentUnavailableMessage() {
  return paymentPairUnavailableMessage({
    hasUsableLink: paymentLinks.value.some(item => Boolean(upiLinkUrl(item)) && !paymentLinkInvalid(item)),
    hasAvailableCdk: paymentCdks.value.some(paymentCdkReusable),
  })
}
function nextPaymentPair(preferredLink = null) {
  const link = preferredLink && paymentTaskRunnable(preferredLink)
    ? preferredLink
    : paymentLinks.value.find(item => paymentTaskRunnable(item) && !item.jobId)
  const cdk = paymentCdks.value.find(paymentCdkReusable)
  if (!link || !cdk) return null
  link.jobId = ''
  link.statusToken = ''
  link.jobToken = ''
  link.remoteTerminal = false
  link.cdk = cdk.value
  link.cdkId = cdk.id
  cdk.linkId = link.id
  cdk.status = 'reserved'
  cdk.message = '已分配，等待 UPI-SCAN 结果。'
  return { link, cdk }
}
function paymentErrorCode(error) {
  if (error?.code) return String(error.code)
  const message = String(error?.message || '')
  const match = message.match(/"code"\s*:\s*"([^"]+)"/) || message.match(/code['"]?\s*[:=]\s*['"]?([a-z0-9_]+)/i)
  return match?.[1] || ''
}
function isCdkBusyPaymentError(code, message) {
  const normalizedCode = String(code || '').trim().toLowerCase()
  const text = String(message || '').toLowerCase()
  return ['cdk_processing', 'cdk_busy', 'cdk_locked', 'cdk_in_use', 'cdk_processing_other_link'].includes(normalizedCode)
    || text.includes('cdk 正在处理其他链接')
    || text.includes('正在处理其他链接')
    || text.includes('processing other link')
    || text.includes('already processing')
    || text.includes('cdk is processing')
}
function isCdkUnavailablePaymentError(code, message) {
  const normalizedCode = String(code || '').trim().toLowerCase()
  const text = String(message || '').toLowerCase()
  return ['cdk_invalid', 'cdk_disabled', 'cdk_used'].includes(normalizedCode)
    || text.includes('cdk 无效')
    || text.includes('cdk 已被禁用')
    || text.includes('cdk 已使用')
    || text.includes('cdk不存在')
    || text.includes('cdk 不存在')
}
function setPaymentFailure(link, cdk, message, { cdkFailed = false, retryLink = false, linkNeedsAction = true } = {}) {
  if (paymentTaskHasLiveRemoteJob(link)) {
    link.status = 'needs_action'
    link.message = message
    if (cdk) {
      cdk.status = 'reserved'
      cdk.linkId = link.id
      cdk.jobId = link.jobId
      cdk.message = '远端任务尚未返回终态，已禁止自动复用。'
    }
    return
  }
  link.status = retryLink ? 'pending' : (linkNeedsAction ? 'needs_action' : 'failed')
  link.message = retryLink ? `${message}；该 CDK 已标记失效，链接已退回待提交，将换用下一枚 UPI-SCAN CDK。` : message
  if (retryLink) {
    link.jobId = ''
    link.statusToken = ''
    link.jobToken = ''
    link.remoteTerminal = false
    link.cdk = ''
    link.cdkId = ''
  }
  if (cdk) {
    if (cdkFailed) {
      cdk.status = 'failed'
      cdk.message = message
    } else {
      cdk.status = 'available'
      cdk.message = '支付未成功，CDK 已释放，可重新配对。'
    }
    cdk.linkId = ''
  }
}
async function waitPaymentJob(link) {
  for (;;) {
    if (componentUnmounted) return { status: LOCAL_PAYMENT_POLL_PAUSED, message: '页面已关闭，远端支付任务仍在运行。' }
    if (!await networkPollingGate.waitUntilAvailable() || componentUnmounted) return { status: LOCAL_PAYMENT_POLL_PAUSED, message: '页面已关闭，远端支付任务仍在运行。' }
    const data = await api.getIndiaUpiPaymentJob(link.jobId, link.statusToken || link.jobToken)
    const job = data.job || data
    const status = String(job.status || data.status || '').toLowerCase()
    link.message = cleanText(job.message || job.error || data.message || status || '处理中')
    if (PAYMENT_TERMINAL_STATUSES.has(status)) return { ...job, status, remoteTerminal: true }
    if (!await networkPollingGate.wait(2000)) return { status: LOCAL_PAYMENT_POLL_PAUSED, message: '页面已关闭，远端支付任务仍在运行。' }
  }
}

async function runPaymentTask(item) {
  if (!item || !paymentTaskRunnable(item)) return
  let hasExistingJob = Boolean(item.jobId && (item.statusToken || item.jobToken))
  let pair = null
  let cdk = paymentCdks.value.find(row => row.id === item.cdkId) || null
  if (!hasExistingJob) {
    pair = nextPaymentPair(item)
    if (!pair) {
      const message = paymentUnavailableMessage()
      item.status = 'pending'
      item.message = message
      paymentStatusText.value = `任务失败：${message}`
      savePaymentState()
      return
    }
    cdk = pair.cdk
  }
  paymentRunningCount.value += 1
  item.status = 'running'
  item.message = hasExistingJob ? '查询 UPI-SCAN 状态中...' : '提交 UPI-SCAN 任务中...'
  try {
    if (!hasExistingJob) {
      const payload = { cdk: cleanText(cdk.value), link: normalizePaymentUrl(item.value) }
      const submitted = await api.submitIndiaUpiPayment(payload)
      if (submitted?.ok === false) {
        const err = new Error(submitted.message || submitted.error || 'UPI-SCAN 支付服务拒绝提交')
        err.code = submitted.code || ''
        err.data = submitted
        throw err
      }
      item.jobId = String(submitted.job_id || submitted.jobId || submitted.id || '').trim()
      item.statusToken = String(submitted.status_token || submitted.jobToken || submitted.job_token || submitted.token || '').trim()
      item.jobToken = item.statusToken
      cdk.jobId = item.jobId
      if (!item.jobId || !item.statusToken) throw new Error('UPI-SCAN 支付服务未返回 job_id/status_token')
      item.remoteTerminal = false
      hasExistingJob = true
    }
    const job = await waitPaymentJob(item)
    if (job.remoteTerminal === true) item.remoteTerminal = true
    if (job.status === LOCAL_PAYMENT_POLL_PAUSED) {
      item.status = 'needs_action'
      item.message = job.message
      if (cdk) {
        cdk.status = 'reserved'
        cdk.linkId = item.id
        cdk.jobId = item.jobId
        cdk.message = '远端任务仍在运行，重新进入页面后可继续查询。'
      }
      return
    }
    if (job.status === 'succeeded') {
      item.status = 'success'
      const accountMark = job.account_email ? `账号 ${job.account_email} 已标记 Plus / UPI。` : ''
      item.message = [job.message || '支付成功，CDK 已核销。', accountMark].filter(Boolean).join(' ')
      if (cdk) {
        cdk.status = 'used'
        cdk.message = '支付成功，已核销。'
        cdk.linkId = item.id
      }
      removeAccountFromUpiPool(job.account_email || item.accountEmail)
      refreshAccounts()
    } else {
      const message = job.message || job.error_code || `任务结束：${job.status}`
      const cdkBusy = isCdkBusyPaymentError(job.error_code, message)
      const cdkUnavailable = isCdkUnavailablePaymentError(job.error_code, message)
      setPaymentFailure(item, cdk, message, { cdkFailed: cdkBusy || cdkUnavailable, retryLink: cdkBusy || cdkUnavailable })
    }
    paymentStatusText.value = item.status === 'success' ? `任务 ${item.jobId} 已成功。` : `任务 ${item.jobId || '-'} 状态：${paymentLinkStatusText(item.status)}。`
  } catch (error) {
    const message = cleanError(error)
    const code = paymentErrorCode(error)
    const cdkBusy = isCdkBusyPaymentError(code, message)
    const cdkUnavailable = isCdkUnavailablePaymentError(code, message)
    if (isAmbiguousPaymentFailure(error)) {
      item.status = hasExistingJob ? 'needs_action' : 'unknown'
      item.message = `${message}；远端结果未知，已锁定关联 CDK，避免重复支付。`
      if (cdk) {
        cdk.status = 'reserved'
        cdk.linkId = item.id
        cdk.jobId = item.jobId || cdk.jobId
        cdk.message = '远端提交或查询结果未知，已禁止自动复用。'
      }
    } else {
      setPaymentFailure(item, cdk, message, { cdkFailed: cdkBusy || cdkUnavailable, retryLink: cdkBusy || cdkUnavailable, linkNeedsAction: !cdkBusy && !cdkUnavailable })
    }
    paymentStatusText.value = `任务失败：${message}`
  } finally {
    paymentRunningCount.value = Math.max(0, paymentRunningCount.value - 1)
    savePaymentState()
  }
}
function removeAccountFromUpiPool(email) {
  const target = String(email || '').trim().toLowerCase()
  if (!target) return
  accounts.value = accounts.value.filter(account => String(account.email || '').trim().toLowerCase() !== target)
  selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(item => String(item || '').trim().toLowerCase() !== target))
}

async function runAllPayments() {
  await importExtractedLinksToPayment({ silent: true })
  if (!paymentRunnableCount.value || paymentBusy.value) {
    if (!paymentBusy.value) paymentStatusText.value = paymentUnavailableMessage()
    return
  }
  paymentBusy.value = true
  paymentStatusText.value = `开始提交 UPI-SCAN 队列，最多并发 ${PAYMENT_MAX_CONCURRENCY} 项。`
  const queriedJobIds = new Set()
  const workers = Array.from({ length: Math.min(PAYMENT_MAX_CONCURRENCY, paymentRunnableCount.value) }, async () => {
    for (;;) {
      const item = paymentLinks.value.find(candidate => paymentTaskRunnable(candidate) && !(candidate.jobId && queriedJobIds.has(candidate.jobId)))
      if (!item) return
      await runPaymentTask(item)
      if (item.jobId) queriedJobIds.add(item.jobId)
    }
  })
  await Promise.all(workers)
  paymentBusy.value = false
  paymentStatusText.value = `支付队列已结束：成功 ${paymentLinks.value.filter(item => item.status === 'success').length}，需处理 ${paymentLinks.value.filter(item => ['failed', 'stopped', 'needs_action'].includes(item.status)).length}。`
}

async function refreshAccounts() {
  try {
    const data = await api.getIndiaUpiAccounts()
    accounts.value = Array.isArray(data.accounts) ? data.accounts : []
    const available = new Set(accounts.value.filter(accountSelectable).map(account => account.email))
    selectedAccounts.value = new Set(selectedEmails.value.filter(email => available.has(email)))
  } catch (error) {
    setStatus(`账号池读取失败：${cleanError(error)}`, true)
  }
}

async function refreshLinks(options = {}) {
  try {
    const data = await api.getIndiaUpiLinks()
    links.value = Array.isArray(data.links) ? data.links : []
    const available = new Set(links.value.map(link => link.id))
    selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => available.has(id)))
    if (options.syncPayment !== false && activeUpiTab.value === 'payment') syncExtractedLinksToPayment({ silent: true })
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
  if (isTempExtract.value) {
    if (tempCdkInput.value.trim()) addTempCdks({ silent: true })
    tempForm.value.concurrency = Math.max(1, Math.min(20, Number(tempForm.value.concurrency || 5)))
    if (!tempCdkLines().length) {
      setStatus('请填写临时 UPI 提链 CDK。', true)
      return false
    }
    if (tempCdkLines().length < emails.length) {
      setStatus(`可用临时提链 CDK 不足：已选 ${emails.length} 个账号，但只有 ${tempCdkLines().length} 枚可用 CDK。`, true)
      return false
    }
    return true
  }
  form.value.concurrency = Math.max(1, Math.min(20, Number(form.value.concurrency || 1)))
  form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
  form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  if (!form.value.proxies.trim() && (!form.value.kookeeyUser || !form.value.kookeeyPass)) {
    setStatus('请填写 IN 代理列表，或在高级设置填写 Kookeey 用户名/密码。', true)
    return false
  }
  return true
}

async function startWithEmails(emails, actionText = '提取') {
  const accountEmails = Array.from(new Set((emails || []).map(email => String(email || '').trim()).filter(Boolean)))
  if (syncUpiExtractionBusy()) {
    setStatus('已有 UPI 提链任务正在运行或等待状态恢复；请先取消任务或等待任务结束。', true)
    return false
  }
  if (!validateStart(accountEmails)) return false
  const tempMode = isTempExtract.value
  const concurrency = tempMode ? tempForm.value.concurrency : form.value.concurrency
  const tempCdksForRun = tempMode ? tempCdkLines().slice(0, accountEmails.length) : []
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  currentJob.value = null
  let startReservation = null
  let startAcknowledged = false
  setStatus(`任务已提交，正在为 ${accountEmails.length} 个账号${actionText} UPI，并发 ${concurrency}。`)
  try {
    saveProxy({ silent: true })
    saveTempForm()
    const payload = tempMode
      ? { cdk: tempCdksForRun.join('\n'), cdks: tempCdksForRun, concurrency: tempForm.value.concurrency }
      : {
          proxies: form.value.proxies,
          concurrency: form.value.concurrency,
          maxAttempts: form.value.maxAttempts,
          proxyPreflightAttempts: form.value.proxyPreflightAttempts,
          localProxy: form.value.localProxy,
          kookeeyEndpoint: form.value.kookeeyEndpoint,
          kookeeyUser: form.value.kookeeyUser,
          kookeeyPass: form.value.kookeeyPass,
        }
    storageWriter.flush()
    startReservation = reserveStartAckGeneration({
      storage: sessionStorage,
      storageKey: JOB_STORAGE_KEY,
      checkpoint: {
        mode: tempMode ? 'tempExtract' : 'extract',
        accountCount: accountEmails.length,
        actionText,
      },
    })
    if (!startReservation) throw new Error('无法持久化任务启动代际')
    if (startReservation.status === 'occupied') {
      applyStartAckCheckpoint(startReservation.checkpoint)
      return
    }
    startAckPending.value = true
    const data = tempMode
      ? await api.startIndiaUpiTempBatch({ ...payload, accountEmails, clientRequestId: startReservation.clientRequestId })
      : await api.startIndiaUpiBatch({ ...payload, accountEmails, clientRequestId: startReservation.clientRequestId })
    const newJobId = String(data.job_id || '').trim()
    if (!newJobId) {
      const error = new Error('后端没有返回任务 ID')
      error.code = 'INVALID_PAYMENT_JOB_RESPONSE'
      throw error
    }
    storageWriter.flush()
    const startAck = commitStartAckSnapshot(startReservation, {
      componentUnmounted,
      createSnapshot: () => ({
        jobId: newJobId,
        accountCount: accountEmails.length,
        accountEmails,
        concurrency,
        mode: tempMode ? 'tempExtract' : 'extract',
        clientRequestId: startReservation.clientRequestId,
        startedAt: Date.now(),
      }),
    })
    if (!startAck.shouldContinue) return
    startAcknowledged = true
    startAckPending.value = false
    if (tempMode) reserveTempCdksForAccounts(accountEmails, newJobId)
    currentJob.value = { id: newJobId, status: 'queued', total: accountEmails.length, completed: 0, concurrency, running_count: 0 }
    await pollJob(newJobId)
  } catch (error) {
    storageWriter.flush()
    const message = cleanError(error)
    if (startAcknowledged) {
      startAckPending.value = false
      if (!componentUnmounted) setStatus(message, true)
    } else if (startReservation?.status === 'reserved' && isAmbiguousPaymentFailure(error)) {
      const unknown = markStartAckGenerationUnknown(startReservation, { componentUnmounted, error: message })
      if (!componentUnmounted) applyStartAckCheckpoint(unknown.checkpoint || startReservation?.checkpoint)
    } else {
      cancelStartAckGeneration(startReservation, { componentUnmounted, error: message })
      if (!componentUnmounted) {
        startAckPending.value = false
        setStatus(message, true)
      }
    }
  } finally {
    if (!componentUnmounted) {
      syncUpiExtractionBusy()
      canceling.value = false
    }
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
  let pollingFailureCount = 0
  for (;;) {
    if (componentUnmounted) return
    if (!await networkPollingGate.waitUntilAvailable() || componentUnmounted) return
    const recovery = await readPollingSnapshot({
      request: () => api.getIndiaUpiJob(jobId),
      wait: delayMs => networkPollingGate.wait(delayMs),
      attempt: pollingFailureCount,
      onTransientError: (error, delayMs) => {
        if (componentUnmounted) return
        setStatus(`任务状态查询暂时失败：${cleanError(error)}；任务与账号占用已保留，${Math.ceil(delayMs / 1000)} 秒后重试。`, true)
      },
    })
    if (componentUnmounted) return
    if (recovery.kind === 'retry') {
      pollingFailureCount = recovery.attempt
      continue
    }
    if (recovery.kind === 'missing') {
      storageWriter.remove(JOB_STORAGE_KEY)
      currentJob.value = null
      setStatus('任务已不存在或后端已重启，已停止轮询并保留现有结果。', true)
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (['permanent', 'paused'].includes(recovery.kind)) {
      currentJob.value = { ...(currentJob.value || {}), id: jobId, status: 'recovery_paused' }
      const reason = recovery.kind === 'permanent'
        ? `任务状态查询被服务端拒绝：${cleanError(recovery.error)}`
        : `任务状态连续查询失败 ${recovery.attempt} 次`
      setStatus(`${reason}；已暂停本轮查询并保留任务与账号占用，重新进入页面后可恢复。`, true)
      return
    }
    if (recovery.kind !== 'snapshot' || componentUnmounted) return
    pollingFailureCount = 0
    const job = recovery.value
    if (componentUnmounted) return
    const completed = Number(job.completed || 0)
    const total = Number(job.total || 0)
    const shouldSyncIncremental = job.result && completed > lastSyncedCompleted && ['running', 'cancelling'].includes(job.status)
    currentJob.value = job
    logs.value = Array.isArray(job.logs) ? job.logs : []
    currentResult.value = job.result || null
    if (job.temp && job.result) applyTempCdkResult(job.result, jobId)
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (shouldSyncIncremental) {
      lastSyncedCompleted = completed
      await refreshLinks()
    }
    if (job.status === 'success') {
      rememberFailedEmails(job.result || {})
      if (job.temp) releaseReservedTempCdks(jobId, '任务已结束，未使用 CDK 已释放。')
      setStatus('提链任务已完成，链接已写入管理表。')
      if ((job.result?.successes || []).length) playNotificationSound(LINK_SUCCESS_SOUND_URL, form.value.notificationSoundEnabled)
      storageWriter.remove(JOB_STORAGE_KEY)
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (job.status === 'cancelled') {
      currentResult.value = job.result || { batch: true, successes: [], errors: [], skipped: job.skipped || [] }
      rememberFailedEmails(currentResult.value)
      if (job.temp) releaseReservedTempCdks(jobId, '任务已取消，未使用 CDK 已释放。')
      setStatus('提链任务已取消；已完成的链接已写入管理表。')
      storageWriter.remove(JOB_STORAGE_KEY)
      await Promise.all([refreshAccounts(), refreshLinks()])
      return
    }
    if (job.status === 'error' || job.status === 'failed') {
      rememberFailedEmails(job.result || {})
      if (job.temp) releaseReservedTempCdks(jobId, '任务失败，未使用 CDK 已释放。')
      storageWriter.remove(JOB_STORAGE_KEY)
      await Promise.all([refreshAccounts(), refreshLinks()])
      throw new Error(job.error || '生成失败')
    }
    setStatus(total ? `任务执行中，已完成 ${completed}/${total}，已记录 ${logs.value.length} 条日志。` : `任务执行中，已记录 ${logs.value.length} 条日志。`)
    persistJsonState(JOB_STORAGE_KEY, { jobId, accountCount: total, concurrency: job.concurrency || (isTempExtract.value ? tempForm.value.concurrency : form.value.concurrency), mode: activeUpiTab.value, startedAt: Date.now() })
    if (!await networkPollingGate.wait(1000)) return
  }
}

async function cancelJob() {
  const jobId = currentJob.value?.id
  if (!jobId || canceling.value) return
  canceling.value = true
  try {
    await api.cancelIndiaUpiJob(jobId)
    setStatus('已发送取消请求，正在停止未开始的账号。')
  } catch (error) {
    setStatus(`取消失败：${cleanError(error)}`, true)
    canceling.value = false
  }
}

function saveProxy(options = {}) {
  persistJsonState(FORM_STORAGE_KEY, () => form.value)
  if (!options.silent && !busy.value) setStatus('代理列表已保存。')
}

function saveTempForm(options = {}) {
  persistJsonState(TEMP_FORM_STORAGE_KEY, () => ({ ...tempForm.value, cdk: tempCdks.value.map(item => item.value).join('\n') }))
  saveTempCdkState()
  if (!options.silent && !busy.value) setStatus('临时提链 CDK 已保存。')
}

async function deleteUpiAccount(email) {
  const target = String(email || '').trim()
  if (!target || deletingUpiAccounts.value.has(target)) return
  if (!window.confirm(`确认从 UPI 账号池和仪表盘账号池中删除 ${target}？`)) return
  deletingUpiAccounts.value = new Set([...deletingUpiAccounts.value, target])
  try {
    const data = await api.deleteIndiaUpiAccount(target)
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(item => item !== target))
    await Promise.all([refreshAccounts(), refreshLinks()])
    const upi = data.upi || {}
    setStatus(`已删除账号 ${target}：仪表盘账号 ${data.dashboard_account_deleted ? '已删除' : '未找到'}，认证 ${data.auth_session_deleted ? '已删除' : '未找到'}，UPI 链接 ${upi.links_deleted || 0} 条。`)
  } catch (error) {
    setStatus(`删除账号失败：${cleanError(error)}`, true)
  } finally {
    const next = new Set(deletingUpiAccounts.value)
    next.delete(target)
    deletingUpiAccounts.value = next
  }
}

async function deleteSelectedUpiAccounts() {
  const emails = selectedEmails.value.map(email => String(email || '').trim()).filter(Boolean)
  if (!emails.length || deletingUpiAccounts.value.size) return
  if (!window.confirm(`确认批量删除选中的 ${emails.length} 个账号？这些账号会同时从 UPI 账号池和仪表盘账号池删除。`)) return
  deletingUpiAccounts.value = new Set(emails)
  try {
    const data = await api.deleteIndiaUpiAccounts(emails)
    const deleted = new Set((data.results || []).map(item => String(item.email || '').trim()).filter(Boolean))
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => !deleted.has(email)))
    await Promise.all([refreshAccounts(), refreshLinks()])
    const linkCount = (data.results || []).reduce((sum, item) => sum + Number(item.upi?.links_deleted || 0), 0)
    setStatus(`已批量删除 ${data.deleted || deleted.size} 个账号，清理 UPI 链接 ${linkCount} 条。`)
  } catch (error) {
    setStatus(`批量删除账号失败：${cleanError(error)}`, true)
  } finally {
    deletingUpiAccounts.value = new Set()
  }
}

async function deleteSelectedLinks() {
  const ids = Array.from(selectedLinkIds.value)
  if (!ids.length) return
  try {
    const data = await api.deleteIndiaUpiLinks(ids)
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
    const data = await api.clearIndiaUpiLinks()
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
  anchor.download = `india-upi-links-${Date.now()}.json`
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

async function runExpiryClock(pollToken) {
  while (expiryClock.isActive(pollToken)) {
    if (!await expiryClock.wait(1000, pollToken)) return
    if (!await expiryClock.waitUntilAvailable(pollToken)) return
    if (!expiryClock.isActive(pollToken)) return
    nowMs.value = Date.now()
    releaseExpiredTempCdkCooldowns()
  }
}

function startExpiryClock() {
  expiryClockToken = expiryClock.start()
  if (expiryClockToken !== null) void runExpiryClock(expiryClockToken)
}

function restoreActiveJob() {
  if (restoreActiveJobPromise) return restoreActiveJobPromise
  restoreActiveJobPromise = (async () => {
    try {
      const saved = JSON.parse(sessionStorage.getItem(JOB_STORAGE_KEY) || '{}')
      if (!saved.jobId) return false
      if (['extract', 'tempExtract'].includes(saved.mode)) activeUpiTab.value = saved.mode
      startAckPending.value = false
      busy.value = true
      canceling.value = false
      currentJob.value = { id: saved.jobId, status: 'queued', total: Number(saved.accountCount || 0), completed: 0, concurrency: Number(saved.concurrency || 1), running_count: 0 }
      setStatus('已恢复提链任务，正在重新同步后端进度。')
      await pollJob(saved.jobId)
      return true
    } catch (error) {
      storageWriter.remove(JOB_STORAGE_KEY)
      currentJob.value = null
      setStatus(`恢复任务失败：${cleanError(error)}`, true)
      return false
    } finally {
      if (!componentUnmounted) {
        syncUpiExtractionBusy()
        canceling.value = false
      }
    }
  })().finally(() => { restoreActiveJobPromise = null })
  return restoreActiveJobPromise
}

onMounted(async () => {
  componentUnmounted = false
  installStartAckWatcher()
  nowMs.value = Date.now()
  startExpiryClock()
  try {
    const savedForm = JSON.parse(sessionStorage.getItem(FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(form.value)) {
      if (savedForm[key] !== undefined) form.value[key] = savedForm[key]
    }
    form.value.concurrency = Math.max(1, Math.min(20, Number(form.value.concurrency || 1)))
    form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
    form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  } catch { /* ignore malformed local state */ }
  try {
    const savedTempForm = JSON.parse(sessionStorage.getItem(TEMP_FORM_STORAGE_KEY) || '{}')
    if (savedTempForm.cdk !== undefined) tempForm.value.cdk = String(savedTempForm.cdk || '')
    if (savedTempForm.concurrency !== undefined) tempForm.value.concurrency = Math.max(1, Math.min(20, Number(savedTempForm.concurrency || 5)))
  } catch { /* ignore malformed local state */ }
  loadTempCdkState(tempForm.value.cdk)
  releaseExpiredTempCdkCooldowns()
  loadPaymentState()
  await reloadAll()
  if (startAckPending.value) installStartAckWatcher()
  await restoreActiveJob()
})

watch(form, () => saveProxy({ silent: true }), { deep: true })
watch(tempForm, () => saveTempForm({ silent: true }), { deep: true })
watch([accountFilter, accountStatusFilter], () => { accountVisibleCount.value = 100 })
watch(recentResultFilter, () => { recentResultVisibleCount.value = 100 })
watch(links, () => { linkVisibleCount.value = 100 })
watch(paymentLinks, () => { paymentLinkVisibleCount.value = 100 })
watch(paymentCdks, () => { paymentCdkVisibleCount.value = 100 })
watch(tempCdks, () => { tempCdkVisibleCount.value = 100 })
watch(currentResult, () => { recentResultVisibleCount.value = 100 })
watch(tempCdks, saveTempCdkState, { deep: true })
watch(activeUpiTab, (value) => {
  sessionStorage.setItem(ACTIVE_TAB_STORAGE_KEY, value)
  if (value === 'payment') refreshLinks()
})
watch(paymentLinks, savePaymentState, { deep: true })
watch(paymentCdks, savePaymentState, { deep: true })

onBeforeUnmount(() => {
  componentUnmounted = true
  startAckWatcher?.unsubscribe()
  startAckWatcher = null
  networkPollingGate.dispose()
  expiryClock.dispose()
  expiryClockToken = null
  storageWriter.dispose()
})
</script>
