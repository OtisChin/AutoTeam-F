<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-2">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div class="inline-flex w-fit rounded-xl border border-gray-800 bg-gray-900/80 p-1">
          <button
            @click="activePixTab = 'extract'"
            class="rounded-lg px-4 py-2 text-sm font-bold transition"
            :class="activePixTab === 'extract' ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'"
          >提链页</button>
          <button
            @click="activePixTab = 'payment'"
            class="rounded-lg px-4 py-2 text-sm font-bold transition"
            :class="activePixTab === 'payment' ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'"
          >支付页</button>
        </div>
        <p class="px-2 text-xs text-gray-500">提链和支付分开管理，切换不会清空当前输入。</p>
      </div>
    </section>

    <section v-if="activePixTab === 'payment'" class="overflow-hidden rounded-2xl border border-cyan-500/20 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.13),transparent_34%),linear-gradient(135deg,rgba(15,23,42,0.96),rgba(2,6,23,0.98))] p-5 shadow-2xl shadow-black/30 md:p-6">
      <div class="flex flex-col gap-4 border-b border-white/10 pb-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.28em] text-cyan-300">Batch Payment Workspace</p>
          <h2 class="mt-2 text-2xl font-black text-white md:text-3xl">支付页：链接与 CDK 分开管理</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-400">按输入顺序自动配对 Stripe PIX 链接与 CDK，最多同时运行 20 项；每一行会实时显示提交、轮询、成功或待处理状态。</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="importExtractedLinksToPayment" :disabled="paymentBusy" class="rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-500/20 disabled:opacity-50">导入已提取链接</button>
          <button @click="runAllPayments" :disabled="paymentBusy || !paymentRunnableCount" class="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">▶ 全部运行</button>
          <button @click="clearFinishedPayments" :disabled="paymentBusy" class="rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:bg-slate-800 disabled:opacity-50">清理已结束</button>
        </div>
      </div>

      <div class="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-5">
        <div v-for="card in paymentSummaryCards" :key="card.label" class="relative overflow-hidden rounded-2xl border bg-slate-950/70 p-4" :class="card.class">
          <div class="absolute -right-8 -top-8 h-24 w-24 rounded-full bg-white/5"></div>
          <p class="text-xs font-bold text-slate-400">{{ card.label }}</p>
          <strong class="mt-2 block text-3xl font-black text-white">{{ card.value }}</strong>
        </div>
      </div>

      <div class="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(360px,0.75fr)]">
        <section class="rounded-2xl border border-slate-800 bg-slate-950/70">
          <div class="flex items-center justify-between border-b border-slate-800 px-5 py-4">
            <div class="flex items-center gap-3">
              <span class="rounded-xl bg-blue-500/10 px-3 py-2 text-xs font-black text-blue-300">01</span>
              <div>
                <h3 class="text-lg font-black text-white">链接队列</h3>
                <p class="text-xs text-slate-500">每行一个 Stripe PIX 链接</p>
              </div>
            </div>
            <span class="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold text-slate-300">{{ paymentLinks.length }} 行</span>
          </div>
          <div class="space-y-4 p-5">
            <label class="block rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
              <span class="mb-2 block text-sm font-bold text-slate-300">粘贴链接</span>
              <textarea v-model="paymentLinkInput" rows="5" spellcheck="false" placeholder="https://payments.stripe.com/qr/instructions/..." class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"></textarea>
              <div class="mt-3 flex items-center justify-between gap-3">
                <span class="text-xs text-slate-500">自动忽略空行并标记重复项</span>
                <button @click="addPaymentLinks" class="rounded-xl border border-blue-500/40 bg-blue-500/10 px-4 py-2 text-sm font-bold text-blue-100 hover:bg-blue-500/20">加入链接</button>
              </div>
            </label>
            <div class="max-h-72 overflow-y-auto rounded-xl border border-slate-800">
              <table class="w-full min-w-[760px] text-left text-sm">
                <thead class="sticky top-0 bg-slate-900 text-xs uppercase tracking-wide text-slate-500">
                  <tr><th class="px-3 py-2">链接 / 运行情况</th><th class="px-3 py-2">状态</th><th class="px-3 py-2">CDK</th><th class="px-3 py-2 text-right">操作</th></tr>
                </thead>
                <tbody class="divide-y divide-slate-900">
                  <tr v-if="!paymentLinks.length"><td colspan="4" class="px-3 py-8 text-center text-slate-500">暂无链接</td></tr>
                  <tr v-for="(item, index) in paymentLinks" :key="item.id" class="hover:bg-slate-900/50">
                    <td class="px-3 py-3">
                      <div class="flex items-center gap-2 text-xs text-slate-500"><span>#{{ String(index + 1).padStart(2, '0') }}</span><span v-if="item.jobId" class="font-mono">job {{ item.jobId }}</span></div>
                      <div class="mt-1 max-w-[460px] truncate font-mono text-xs text-slate-300">{{ item.value }}</div>
                      <div v-if="item.message" class="mt-1 text-xs text-slate-500">{{ item.message }}</div>
                    </td>
                    <td class="px-3 py-3"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="paymentLinkStatusClass(item.status)">{{ paymentLinkStatusText(item.status) }}</span></td>
                    <td class="px-3 py-3 font-mono text-xs text-slate-500">{{ maskCdk(item.cdk || '') }}</td>
                    <td class="px-3 py-3 text-right"><button @click="copy(item.value)" class="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800">复制</button><button @click="removePaymentLink(item.id)" :disabled="paymentBusy" class="ml-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-800 bg-slate-950/70">
          <div class="flex items-center justify-between border-b border-slate-800 px-5 py-4">
            <div class="flex items-center gap-3">
              <span class="rounded-xl bg-violet-500/10 px-3 py-2 text-xs font-black text-violet-300">02</span>
              <div>
                <h3 class="text-lg font-black text-white">CDK 池</h3>
                <p class="text-xs text-slate-500">按顺序自动取用</p>
              </div>
            </div>
            <button @click="showCdks = !showCdks" class="text-xs font-bold text-blue-300 hover:text-blue-200">{{ showCdks ? '隐藏 CDK' : '显示 CDK' }}</button>
          </div>
          <div class="space-y-4 p-5">
            <label class="block rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
              <span class="mb-2 block text-sm font-bold text-slate-300">粘贴 CDK</span>
              <textarea v-model="paymentCdkInput" rows="5" spellcheck="false" placeholder="PIX-XXXXX-XXXXX-XXXXX-XXXXX" class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"></textarea>
              <div class="mt-3 flex items-center justify-between gap-3">
                <span class="text-xs text-slate-500">{{ paymentAvailableCdks }} 枚可用</span>
                <button @click="addPaymentCdks" class="rounded-xl border border-blue-500/40 bg-blue-500/10 px-4 py-2 text-sm font-bold text-blue-100 hover:bg-blue-500/20">加入 CDK</button>
              </div>
            </label>
            <div class="max-h-72 overflow-y-auto rounded-xl border border-slate-800">
              <table class="w-full text-left text-sm">
                <thead class="sticky top-0 bg-slate-900 text-xs uppercase tracking-wide text-slate-500"><tr><th class="px-3 py-2">CDK / 使用情况</th><th class="px-3 py-2 text-right">操作</th></tr></thead>
                <tbody class="divide-y divide-slate-900">
                  <tr v-if="!paymentCdks.length"><td colspan="2" class="px-3 py-8 text-center text-slate-500">暂无 CDK</td></tr>
                  <tr v-for="(item, index) in paymentCdks" :key="item.id" class="hover:bg-slate-900/50">
                    <td class="px-3 py-3">
                      <div class="flex items-center gap-2 text-xs text-slate-500"><span>#{{ String(index + 1).padStart(2, '0') }}</span><span class="inline-flex rounded-full border px-2 py-0.5 font-bold" :class="paymentCdkStatusClass(item.status)">{{ paymentCdkStatusText(item.status) }}</span></div>
                      <div class="mt-1 font-mono text-xs text-slate-300">{{ showCdks ? item.value : maskCdk(item.value) }}</div>
                      <div v-if="item.message" class="mt-1 text-xs text-slate-500">{{ item.message }}</div>
                    </td>
                    <td class="px-3 py-3 text-right"><button @click="copy(item.value)" class="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800">复制</button><button @click="removePaymentCdk(item.id)" :disabled="paymentBusy" class="ml-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">{{ paymentStatusText }}</div>
          </div>
        </section>
      </div>
    </section>

    <template v-else>
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
        <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">独立 PIX 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">巴西PIX 提链</h2>
          <p class="mt-2 text-sm text-gray-400">在账号池中勾选一个或多个账号执行提链，结果会进入下方链接管理表。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ busy ? progressText : '本地服务在线' }}
        </span>
      </div>
    </section>

    <div class="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">BR 代理</h3>
        </div>

        <div class="mt-5 space-y-5">
          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">BR 代理列表</span>
            <textarea
              v-model.trim="form.proxies"
              rows="8"
              spellcheck="false"
              placeholder="每行一个代理；支持 host:port:user:pass 或 socks5h://user:pass@host:port"
              class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              :disabled="busy"
            ></textarea>
            <span class="mt-1 block text-xs text-gray-500">ArxLabs 的 host:port:user:pass 会自动按 socks5h 使用。</span>
          </label>

          <label class="block">
            <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
            <input
              v-model.number="form.concurrency"
              type="number"
              min="1"
              max="10"
              class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none"
              :disabled="busy"
            />
            <span class="mt-1 block text-xs text-gray-500">默认 1，最高 10；并发越高越依赖代理质量。</span>
          </label>

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

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="busy" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:opacity-50">
              {{ busy ? '提取中...' : `开始提链 (${selectedEmails.length})` }}
            </button>
            <button v-if="busy" @click="cancelJob" :disabled="canceling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
              {{ canceling ? '取消中...' : '取消提链' }}
            </button>
            <button @click="reloadAll" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号/链接</button>
            <button @click="saveProxy" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
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
          <div class="flex flex-wrap gap-2">
            <button @click="selectAllFiltered" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
            <button @click="clearSelectedAccounts" :disabled="busy" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
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
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-900">
              <tr v-if="!filteredAccounts.length">
                <td colspan="4" class="px-3 py-10 text-center text-gray-500">暂无账号</td>
              </tr>
              <tr v-for="account in filteredAccounts" :key="account.email" class="hover:bg-gray-900/50">
                <td class="px-3 py-2">
                  <input :checked="selectedAccounts.has(account.email)" type="checkbox" class="accent-emerald-500" :disabled="busy" @change="toggleAccount(account.email)" />
                </td>
                <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ account.email }}</td>
                <td class="px-3 py-2 text-xs text-gray-500">{{ ttlText(account.ttl_seconds) }}</td>
                <td class="px-3 py-2 text-xs">
                  <span class="inline-flex rounded-full border px-2 py-1 font-semibold" :class="accountStatusClass(account)" :title="accountStatusError(account)">
                    {{ accountStatusText(account) }}
                  </span>
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

          <div v-else-if="currentResult.batch" class="mt-5 space-y-3 text-sm">
            <div class="rounded-xl border border-gray-800 bg-gray-950 p-4 text-gray-300">
              本次完成：成功 <span class="font-semibold text-emerald-300">{{ currentResult.successes?.length || 0 }}</span>，失败 <span class="font-semibold text-rose-300">{{ currentResult.errors?.length || 0 }}</span>，跳过 <span class="font-semibold text-gray-300">{{ currentResult.skipped?.length || 0 }}</span>
            </div>
            <div v-for="item in currentResult.successes || []" :key="item.email" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
              <div class="font-mono text-emerald-200">{{ item.email }}</div>
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="item.link?.hosted_instructions_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!item.link?.hosted_instructions_url ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(item.link?.pix_copy_paste)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制码</button>
                <button @click="copy(item.link?.hosted_instructions_url)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100">复制链</button>
              </div>
            </div>
            <div v-for="item in currentResult.errors || []" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {{ item.email }}：{{ item.error }}
            </div>
            <div v-for="item in currentResult.skipped || []" :key="item.email" class="rounded-lg border border-gray-700 bg-gray-900/60 px-3 py-2 text-xs text-gray-300">
              {{ item.email }}：{{ item.reason || '已跳过' }}
            </div>
          </div>

          <div v-else class="mt-5 space-y-4">
            <div class="flex flex-col items-center gap-4">
              <div class="flex h-44 w-44 items-center justify-center rounded-xl border border-gray-700 bg-white p-2">
                <img v-if="fields.image_url_png || fields.image_url_svg" :src="fields.image_url_png || fields.image_url_svg" alt="PIX QR" class="h-full w-full object-contain" />
                <span v-else class="text-sm text-gray-500">无二维码图片</span>
              </div>
              <div class="flex flex-wrap justify-center gap-2">
                <a :href="fields.hosted_instructions_url || '#'" target="_blank" rel="noopener" class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-blue-500" :class="!fields.hosted_instructions_url ? 'pointer-events-none opacity-50' : ''">打开 PIX 链接</a>
                <button @click="copy(fields.pix_copy_paste)" :disabled="!fields.pix_copy_paste" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">复制 PIX 码</button>
              </div>
            </div>
            <ResultDetails :result="currentResult" />
          </div>
        </section>
      </div>
    </div>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
      <div class="flex flex-col gap-3 border-b border-gray-800 pb-4 md:flex-row md:items-end md:justify-between">
        <div>
          <p class="text-xs font-semibold text-gray-500">链接管理</p>
          <h3 class="mt-1 text-xl font-bold text-white">已提取 PIX 链接</h3>
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
              <th class="px-3 py-2">PIX 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!links.length">
              <td colspan="7" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ link.created_at }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || '-' }}</td>
              <td class="px-3 py-2 text-xs text-gray-400">{{ link.amount || '-' }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-400">{{ link.cs_id || '-' }}</td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-2">
                  <a :href="link.hosted_instructions_url || '#'" target="_blank" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!link.hosted_instructions_url ? 'pointer-events-none opacity-50' : ''">打开</a>
                  <button @click="copy(link.pix_copy_paste)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200">复制码</button>
                  <button @click="copy(link.hosted_instructions_url)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200">复制链</button>
                </div>
              </td>
              <td class="max-w-[360px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ link.hosted_instructions_url || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, defineComponent, h, nextTick, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const PROXY_STORAGE_KEY = 'autotoken_brazil_pix_proxies'
const PIX_TAB_STORAGE_KEY = 'autotoken_brazil_pix_active_tab'
const PAYMENT_STATE_STORAGE_KEY = 'autotoken_brazil_pix_payment_state'
const activePixTab = ref('extract')

const ResultRow = defineComponent({
  props: { label: String, value: String },
  setup(props) {
    return () => h('div', { class: 'grid gap-1 md:grid-cols-[120px_minmax(0,1fr)]' }, [
      h('span', { class: 'text-gray-500' }, props.label || ''),
      h('code', { class: 'break-all rounded bg-gray-900 px-2 py-1 text-xs text-gray-300' }, props.value || '-'),
    ])
  },
})

const ResultDetails = defineComponent({
  props: { result: Object },
  setup(props) {
    return () => {
      const result = props.result || {}
      const fields = result.fields || {}
      return h('div', { class: 'space-y-3 rounded-xl border border-gray-800 bg-gray-950 p-4 text-sm' }, [
        h(ResultRow, { label: '账号', value: result.account_email || '-' }),
        h(ResultRow, { label: '金额', value: String(fields.amount || result.amount || '-') }),
        h(ResultRow, { label: 'CS ID', value: fields.cs_id || '-' }),
        h(ResultRow, { label: 'PIX 链接', value: fields.hosted_instructions_url || '-' }),
        h(ResultRow, { label: 'PNG', value: fields.image_url_png || '-' }),
        h(ResultRow, { label: 'Checkout', value: fields.chatgpt_checkout_url || '-' }),
        h('label', { class: 'block' }, [
          h('span', { class: 'mb-1 block text-gray-500' }, 'PIX 复制码'),
          h('textarea', { readonly: true, rows: 4, value: fields.pix_copy_paste || '', class: 'w-full rounded-lg border border-gray-800 bg-gray-900 px-3 py-2 font-mono text-xs text-gray-300' }),
        ]),
      ])
    }
  },
})

const form = ref({
  proxies: '',
  concurrency: 1,
  localProxy: '',
  kookeeyUser: '',
  kookeeyPass: '',
  kookeeyEndpoint: 'gate.kookeey.info:1000',
})
const accounts = ref([])
const links = ref([])
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const accountFilter = ref('')
const busy = ref(false)
const canceling = ref(false)
const currentJob = ref(null)
const statusText = ref('等待提交任务。')
const statusError = ref(false)
const logs = ref([])
const currentResult = ref(null)
const logRef = ref(null)

const PAYMENT_MAX_CONCURRENCY = 20
const PAYMENT_TERMINAL_STATUSES = new Set(['succeeded', 'failed', 'rejected_amount'])
const paymentLinkInput = ref('')
const paymentCdkInput = ref('')
const paymentLinks = ref([])
const paymentCdks = ref([])
const paymentBusy = ref(false)
const paymentRunningCount = ref(0)
const paymentStatusText = ref('等待加入链接和 CDK。')
const showCdks = ref(false)

const fields = computed(() => currentResult.value?.fields || {})
const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const filteredAccounts = computed(() => {
  const needle = accountFilter.value.toLowerCase()
  if (!needle) return accounts.value
  return accounts.value.filter(account => String(account.email || '').toLowerCase().includes(needle))
})
const progressText = computed(() => {
  const total = currentJob.value?.total || 0
  const completed = currentJob.value?.completed || 0
  const concurrency = currentJob.value?.concurrency || 1
  const running = currentJob.value?.running_count || 0
  const status = currentJob.value?.status || ''
  if (status === 'cancelling') return total ? `取消中 ${completed}/${total} · 活跃 ${running}` : '取消中'
  return total ? `运行中 ${completed}/${total} · 活跃 ${running}${concurrency > 1 ? ` · 并发 ${concurrency}` : ''}` : '任务运行中'
})
const badgeText = computed(() => {
  if (busy.value) return progressText.value
  if (currentJob.value?.status === 'cancelled') return '已取消'
  return statusError.value ? '失败' : '待命'
})
const badgeClass = computed(() => {
  if (busy.value) return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (currentJob.value?.status === 'cancelled') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  if (statusError.value) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
})

const paymentAvailableCdks = computed(() => paymentCdks.value.filter(item => item.status === 'available').length)
const paymentPendingLinks = computed(() => paymentLinks.value.filter(item => item.status === 'pending').length)
const paymentRunnableCount = computed(() => Math.min(paymentPendingLinks.value, paymentAvailableCdks.value))
const paymentSummaryCards = computed(() => [
  { label: '待处理链接', value: paymentPendingLinks.value, class: 'border-blue-500/30' },
  { label: '正在运行', value: paymentRunningCount.value, class: 'border-sky-500/30' },
  { label: '支付成功', value: paymentLinks.value.filter(item => item.status === 'success').length, class: 'border-emerald-500/30' },
  { label: '需处理', value: paymentLinks.value.filter(item => ['failed', 'needs_action'].includes(item.status)).length + paymentCdks.value.filter(item => item.status === 'failed').length, class: 'border-rose-500/30' },
  { label: '可用 CDK', value: paymentAvailableCdks.value, class: 'border-violet-500/30' },
])


function makePaymentId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function parseLines(value) {
  return String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean)
}

function maskCdk(value) {
  const text = String(value || '')
  if (!text) return '-'
  if (text.length <= 10) return text.replace(/.(?=.{3})/g, '•')
  return `${text.slice(0, 4)}••••••••${text.slice(-4)}`
}

function paymentLinkStatusText(status) {
  if (status === 'running') return '正在运行'
  if (status === 'success') return '成功'
  if (status === 'failed') return '失败'
  if (status === 'needs_action') return '需处理'
  return '待处理'
}

function paymentLinkStatusClass(status) {
  if (status === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (status === 'needs_action') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-slate-700 bg-slate-900 text-slate-400'
}

function paymentCdkStatusText(status) {
  if (status === 'reserved') return '已分配'
  if (status === 'used') return '已核销'
  if (status === 'failed') return '需处理'
  return '可用'
}

function paymentCdkStatusClass(status) {
  if (status === 'reserved') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'used') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-violet-500/30 bg-violet-500/10 text-violet-300'
}

function addPaymentLinks() {
  const existing = new Set(paymentLinks.value.map(item => normalizePaymentUrl(item.value)))
  const items = []
  for (const line of parseLines(paymentLinkInput.value)) {
    const normalized = normalizePaymentUrl(line)
    if (existing.has(normalized)) continue
    existing.add(normalized)
    items.push({ id: makePaymentId('link'), value: line, status: 'pending', message: '', cdk: '', cdkId: '', jobId: '', statusToken: '' })
  }
  if (items.length) paymentLinks.value = [...paymentLinks.value, ...items]
  paymentLinkInput.value = ''
  paymentStatusText.value = items.length ? `已加入 ${items.length} 条链接。` : '没有新增链接，可能为空或重复。'
}

function normalizePaymentUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

function normalizePaymentItem(item, kind) {
  const raw = item && typeof item === 'object' ? item : {}
  const value = String(raw.value || '').trim()
  if (!value) return null
  if (kind === 'cdk') {
    const status = ['available', 'reserved', 'used', 'failed'].includes(raw.status) ? raw.status : 'available'
    return {
      id: String(raw.id || makePaymentId('cdk')),
      value,
      status: status === 'reserved' ? 'available' : status,
      message: status === 'reserved' ? '刷新后已释放，可重新配对。' : String(raw.message || ''),
      linkId: '',
      jobId: String(raw.jobId || ''),
    }
  }
  const status = ['pending', 'running', 'success', 'failed', 'needs_action'].includes(raw.status) ? raw.status : 'pending'
  return {
    id: String(raw.id || makePaymentId('link')),
    value,
    status: status === 'running' ? 'pending' : status,
    message: status === 'running' ? '刷新后已恢复为待处理，请查询服务端或重新运行。' : String(raw.message || ''),
    cdk: status === 'running' ? '' : String(raw.cdk || ''),
    cdkId: status === 'running' ? '' : String(raw.cdkId || ''),
    jobId: String(raw.jobId || ''),
    statusToken: String(raw.statusToken || ''),
    accountEmail: String(raw.accountEmail || ''),
  }
}

function loadPaymentState() {
  try {
    const raw = JSON.parse(localStorage.getItem(PAYMENT_STATE_STORAGE_KEY) || '{}')
    paymentLinks.value = Array.isArray(raw.links) ? raw.links.map(item => normalizePaymentItem(item, 'link')).filter(Boolean) : []
    paymentCdks.value = Array.isArray(raw.cdks) ? raw.cdks.map(item => normalizePaymentItem(item, 'cdk')).filter(Boolean) : []
    paymentStatusText.value = paymentLinks.value.length || paymentCdks.value.length ? '已恢复上次支付页数据。' : '等待加入链接和 CDK。'
  } catch {
    paymentLinks.value = []
    paymentCdks.value = []
    paymentStatusText.value = '支付页缓存读取失败，已重置为空。'
  }
}

function savePaymentState() {
  const snapshot = {
    links: paymentLinks.value,
    cdks: paymentCdks.value,
    savedAt: Date.now(),
  }
  localStorage.setItem(PAYMENT_STATE_STORAGE_KEY, JSON.stringify(snapshot))
}

function dedupeExtractedLinks(items) {
  const seenAccounts = new Set()
  const seenUrls = new Set()
  const result = []
  for (const item of Array.isArray(items) ? items : []) {
    const account = String(item?.account_email || '').trim().toLowerCase()
    const url = normalizePaymentUrl(item?.hosted_instructions_url)
    if (account) {
      if (seenAccounts.has(account)) continue
      seenAccounts.add(account)
    } else if (url) {
      if (seenUrls.has(url)) continue
    }
    if (url) seenUrls.add(url)
    result.push(item)
  }
  return result
}

function releasePaymentLinkCdk(link) {
  if (!link?.cdkId) return
  const cdk = paymentCdks.value.find(item => item.id === link.cdkId)
  if (cdk && cdk.status === 'reserved') {
    cdk.status = 'available'
    cdk.linkId = ''
    cdk.message = '链接已被新提链结果覆盖，CDK 已释放。'
  }
  link.cdk = ''
  link.cdkId = ''
}

function upsertExtractedPaymentLink(record, existingByAccount, existingUrls) {
  const url = String(record.hosted_instructions_url || '').trim()
  const normalized = normalizePaymentUrl(url)
  if (!url || existingUrls.has(normalized)) return 'skipped'
  const account = String(record.account_email || '').trim()
  const accountKey = account.toLowerCase()
  const existing = accountKey ? existingByAccount.get(accountKey) : null
  if (existing) {
    if (existing.status === 'running') return 'running'
    releasePaymentLinkCdk(existing)
    existing.value = url
    existing.status = 'pending'
    existing.message = `来自提链账号 ${account}，已用最新链接覆盖旧链接`
    existing.jobId = ''
    existing.statusToken = ''
    existing.accountEmail = account
    existingUrls.add(normalized)
    return 'updated'
  }
  const item = {
    id: makePaymentId('link'),
    value: url,
    status: 'pending',
    message: account ? `来自提链账号 ${account}` : '来自已提取 PIX 链接',
    cdk: '',
    cdkId: '',
    jobId: '',
    statusToken: '',
    accountEmail: account,
  }
  paymentLinks.value = [...paymentLinks.value, item]
  if (accountKey) existingByAccount.set(accountKey, item)
  existingUrls.add(normalized)
  return 'added'
}

async function importExtractedLinksToPayment() {
  try {
    const data = await api.getBrazilPixLinks()
    links.value = dedupeExtractedLinks(data.links)
    const existingUrls = new Set(paymentLinks.value.map(item => normalizePaymentUrl(item.value)))
    const existingByAccount = new Map(
      paymentLinks.value
        .filter(item => String(item.accountEmail || '').trim())
        .map(item => [String(item.accountEmail || '').trim().toLowerCase(), item]),
    )
    let added = 0
    let updated = 0
    let running = 0
    for (const record of links.value) {
      const result = upsertExtractedPaymentLink(record, existingByAccount, existingUrls)
      if (result === 'added') added += 1
      if (result === 'updated') updated += 1
      if (result === 'running') running += 1
    }
    const summary = [`新增 ${added}`, `覆盖 ${updated}`]
    if (running) summary.push(`运行中未覆盖 ${running}`)
    paymentStatusText.value = added || updated || running ? `已从提链页导入：${summary.join('，')}。` : '没有可导入的新链接；可能为空或已在队列中。'
  } catch (error) {
    paymentStatusText.value = `导入失败：${cleanText(error.message || error)}`
  }
}

function addPaymentCdks() {
  const existing = new Set(paymentCdks.value.map(item => item.value))
  const items = []
  for (const line of parseLines(paymentCdkInput.value)) {
    if (existing.has(line)) continue
    existing.add(line)
    items.push({ id: makePaymentId('cdk'), value: line, status: 'available', message: '', linkId: '', jobId: '' })
  }
  if (items.length) paymentCdks.value = [...paymentCdks.value, ...items]
  paymentCdkInput.value = ''
  paymentStatusText.value = items.length ? `已加入 ${items.length} 枚 CDK。` : '没有新增 CDK，可能为空或重复。'
}

function removePaymentLink(id) {
  paymentLinks.value = paymentLinks.value.filter(item => item.id !== id)
  for (const cdk of paymentCdks.value) {
    if (cdk.linkId === id && cdk.status === 'reserved') {
      cdk.status = 'available'
      cdk.linkId = ''
      cdk.message = ''
    }
  }
}

function removePaymentCdk(id) {
  paymentCdks.value = paymentCdks.value.filter(item => item.id !== id)
  for (const link of paymentLinks.value) {
    if (link.cdkId === id && link.status === 'pending') {
      link.cdk = ''
      link.cdkId = ''
    }
  }
}

function clearFinishedPayments() {
  paymentLinks.value = paymentLinks.value.filter(item => !['success', 'failed', 'needs_action'].includes(item.status))
  paymentCdks.value = paymentCdks.value.filter(item => !['used', 'failed'].includes(item.status))
  paymentStatusText.value = '已清理结束项。'
}

function nextPaymentPair() {
  const link = paymentLinks.value.find(item => item.status === 'pending')
  const cdk = paymentCdks.value.find(item => item.status === 'available')
  if (!link || !cdk) return null
  link.cdk = cdk.value
  link.cdkId = cdk.id
  cdk.linkId = link.id
  cdk.status = 'reserved'
  return { link, cdk }
}

function setPaymentFailure(link, cdk, message, { cdkFailed = false, linkNeedsAction = true } = {}) {
  link.status = linkNeedsAction ? 'needs_action' : 'failed'
  link.message = message
  if (cdkFailed) {
    cdk.status = 'failed'
    cdk.message = message
  } else {
    cdk.status = 'available'
    cdk.linkId = ''
    cdk.message = '支付未成功，CDK 已释放，可重新配对。'
  }
}

function paymentErrorCode(error) {
  if (error?.code) return String(error.code)
  const message = String(error?.message || '')
  const match = message.match(/"code"\s*:\s*"([^"]+)"/) || message.match(/code['"]?\s*[:=]\s*['"]?([a-z0-9_]+)/i)
  return match?.[1] || ''
}

async function waitPaymentJob(link) {
  for (;;) {
    const data = await api.getBrazilPixPaymentJob(link.jobId, link.statusToken)
    const job = data.job || {}
    const status = String(job.status || '')
    link.message = job.message || status || '处理中'
    if (PAYMENT_TERMINAL_STATUSES.has(status)) return job
    await new Promise(resolve => window.setTimeout(resolve, 2000))
  }
}

async function runPaymentPair(link, cdk) {
  paymentRunningCount.value += 1
  link.status = 'running'
  link.message = '提交支付任务中...'
  cdk.status = 'reserved'
  cdk.message = '已分配，等待支付结果。'
  try {
    const submitted = await api.submitBrazilPixPayment({ cdk: cdk.value, link: link.value })
    link.jobId = submitted.job_id || ''
    link.statusToken = submitted.status_token || ''
    cdk.jobId = link.jobId
    link.message = submitted.message || '已进入支付队列。'
    if (!link.jobId || !link.statusToken) throw new Error('支付服务未返回 job_id/status_token')
    const job = await waitPaymentJob(link)
    if (job.status === 'succeeded') {
      link.status = 'success'
      const accountMark = job.account_email ? `账号 ${job.account_email} 已标记 Plus / Pix。` : ''
      link.message = [job.message || '支付成功，CDK 已核销。', accountMark].filter(Boolean).join(' ')
      cdk.status = 'used'
      cdk.message = '支付成功，已核销。'
      removeAccountFromPixPool(job.account_email || link.accountEmail)
      reloadAccounts()
    } else {
      setPaymentFailure(link, cdk, job.message || job.error_code || `任务结束：${job.status}`)
    }
  } catch (error) {
    const message = cleanText(error.message || error)
    const code = paymentErrorCode(error)
    const cdkFailed = ['cdk_invalid', 'cdk_disabled', 'cdk_used'].includes(code)
    setPaymentFailure(link, cdk, message, { cdkFailed })
  } finally {
    paymentRunningCount.value = Math.max(0, paymentRunningCount.value - 1)
  }
}

function removeAccountFromPixPool(email) {
  const target = String(email || '').trim().toLowerCase()
  if (!target) return
  accounts.value = accounts.value.filter(account => String(account.email || '').trim().toLowerCase() !== target)
  selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(item => String(item || '').trim().toLowerCase() !== target))
}

async function runAllPayments() {
  if (!paymentRunnableCount.value || paymentBusy.value) return
  paymentBusy.value = true
  paymentStatusText.value = `开始支付，最多并发 ${PAYMENT_MAX_CONCURRENCY} 项。`
  const workers = Array.from({ length: Math.min(PAYMENT_MAX_CONCURRENCY, paymentRunnableCount.value) }, async () => {
    for (;;) {
      const pair = nextPaymentPair()
      if (!pair) return
      await runPaymentPair(pair.link, pair.cdk)
    }
  })
  await Promise.all(workers)
  paymentBusy.value = false
  paymentStatusText.value = `支付队列已结束：成功 ${paymentLinks.value.filter(item => item.status === 'success').length}，需处理 ${paymentLinks.value.filter(item => ['failed', 'needs_action'].includes(item.status)).length}。`
}

function cleanText(value) {
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function setStatus(text, isError = false) {
  statusText.value = text
  statusError.value = isError
}

function ttlText(seconds) {
  const value = Number(seconds || 0)
  if (!value) return '-'
  if (value < 3600) return `${Math.round(value / 60)}m`
  return `${Math.round(value / 3600)}h`
}

function accountJobStatus(account) {
  const email = String(account?.email || '')
  const statuses = currentJob.value?.account_statuses || {}
  return statuses[email] || statuses[email.toLowerCase()] || null
}

function accountStatus(account) {
  return accountJobStatus(account)?.status || account?.pix_status || 'pending'
}

function accountStatusText(account) {
  const status = accountStatus(account)
  if (status === 'running') return '提链中'
  if (status === 'success') return '已提链'
  if (status === 'failed') return '提链失败'
  return '未提链'
}

function accountStatusError(account) {
  return accountJobStatus(account)?.error || account?.pix_error || ''
}

function accountStatusClass(account) {
  const status = accountStatus(account)
  if (status === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
}

function toggleAccount(email) {
  const next = new Set(selectedAccounts.value)
  if (next.has(email)) next.delete(email)
  else next.add(email)
  selectedAccounts.value = next
}

function selectAllFiltered() {
  selectedAccounts.value = new Set(filteredAccounts.value.map(account => account.email))
}

function clearSelectedAccounts() {
  selectedAccounts.value = new Set()
}

function toggleLink(id) {
  const next = new Set(selectedLinkIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedLinkIds.value = next
}

async function reloadAccounts() {
  try {
    const data = await api.getBrazilPixAccounts()
    accounts.value = Array.isArray(data.accounts) ? data.accounts : []
    const available = new Set(accounts.value.map(account => account.email))
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => available.has(email)))
  } catch (error) {
    setStatus(`账号池读取失败：${cleanText(error.message || error)}`, true)
  }
}

async function refreshLinks() {
  try {
    const data = await api.getBrazilPixLinks()
    links.value = dedupeExtractedLinks(data.links)
    const available = new Set(links.value.map(link => link.id))
    selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => available.has(id)))
  } catch (error) {
    setStatus(`链接读取失败：${cleanText(error.message || error)}`, true)
  }
}

async function reloadAll() {
  await Promise.all([reloadAccounts(), refreshLinks()])
}

async function poll(jobId) {
  let lastSyncedCompleted = 0
  for (;;) {
    const data = await api.getBrazilPixJob(jobId)
    const completed = Number(data.completed || 0)
    const total = Number(data.total || 0)
    const shouldSyncIncremental = data.result && completed > lastSyncedCompleted && ['running', 'cancelling'].includes(data.status)
    currentJob.value = data
    if (data.result) currentResult.value = data.result
    logs.value = Array.isArray(data.logs) ? data.logs : []
    await nextTick()
    if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    if (shouldSyncIncremental) {
      lastSyncedCompleted = completed
      await refreshLinks()
    }
    if (data.status === 'success') {
      currentResult.value = data.result || {}
      setStatus('提链任务已完成，链接已写入管理表。')
      await Promise.all([refreshLinks(), reloadAccounts()])
      return
    }
    if (data.status === 'cancelled') {
      currentResult.value = data.result || { batch: true, successes: [], errors: [], skipped: data.skipped || [] }
      setStatus('提链任务已取消；已完成的链接已写入管理表。')
      await Promise.all([refreshLinks(), reloadAccounts()])
      return
    }
    if (data.status === 'error') {
      currentResult.value = data.result || null
      await Promise.all([refreshLinks(), reloadAccounts()])
      throw new Error(data.error || '生成失败')
    }
    setStatus(total ? `任务执行中，已完成 ${completed}/${total}，已记录 ${logs.value.length} 条日志。` : `任务执行中，已记录 ${logs.value.length} 条日志。`)
    await new Promise(resolve => window.setTimeout(resolve, 1000))
  }
}

function validateStart() {
  if (!selectedEmails.value.length) {
    setStatus('请在账号池中选择至少一个账号。', true)
    return false
  }
  form.value.concurrency = Math.max(1, Math.min(10, Number(form.value.concurrency || 1)))
  if (!form.value.proxies.trim() && (!form.value.kookeeyUser || !form.value.kookeeyPass)) {
    setStatus('请填写 BR 代理列表，或在高级设置填写 Kookeey 用户名/密码。', true)
    return false
  }
  return true
}

async function start() {
  if (!validateStart()) return
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  currentJob.value = null
  setStatus(`任务已提交，正在为 ${selectedEmails.value.length} 个账号提取 PIX，并发 ${form.value.concurrency}。`)
  try {
    saveProxy()
    const payload = { ...form.value }
    const data = await api.startBrazilPixBatch({ ...payload, accountEmails: selectedEmails.value })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    currentJob.value = { id: data.job_id, status: 'queued', total: selectedEmails.value.length, completed: 0, concurrency: form.value.concurrency, running_count: 0 }
    await poll(data.job_id)
  } catch (error) {
    setStatus(cleanText(error.message || error), true)
  } finally {
    busy.value = false
    canceling.value = false
  }
}

async function cancelJob() {
  const jobId = currentJob.value?.id
  if (!jobId || canceling.value) return
  canceling.value = true
  try {
    await api.cancelBrazilPixJob(jobId)
    setStatus('已发送取消请求，正在停止未开始的账号。')
  } catch (error) {
    setStatus(`取消失败：${cleanText(error.message || error)}`, true)
    canceling.value = false
  }
}

function saveProxy() {
  localStorage.setItem(PROXY_STORAGE_KEY, form.value.proxies || '')
  if (!busy.value) setStatus('代理列表已保存。')
}

async function copy(value) {
  const text = String(value || '')
  if (!text) return
  await navigator.clipboard?.writeText(text)
  setStatus('已复制。')
}

async function deleteSelectedLinks() {
  const ids = Array.from(selectedLinkIds.value)
  if (!ids.length) return
  const data = await api.deleteBrazilPixLinks(ids)
  links.value = dedupeExtractedLinks(data.links)
  selectedLinkIds.value = new Set()
  setStatus(`已删除 ${data.deleted || ids.length} 条链接。`)
}

async function clearLinks() {
  const data = await api.clearBrazilPixLinks()
  links.value = dedupeExtractedLinks(data.links)
  selectedLinkIds.value = new Set()
  setStatus(`已清空 ${data.deleted || 0} 条链接。`)
}

function exportLinks() {
  const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `brazil-pix-links-${Date.now()}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
  setStatus('链接 JSON 已导出。')
}

onMounted(() => {
  form.value.proxies = localStorage.getItem(PROXY_STORAGE_KEY) || ''
  const savedTab = localStorage.getItem(PIX_TAB_STORAGE_KEY)
  if (savedTab === 'payment' || savedTab === 'extract') activePixTab.value = savedTab
  loadPaymentState()
  reloadAll()
})

watch(activePixTab, (tab) => {
  localStorage.setItem(PIX_TAB_STORAGE_KEY, tab)
  if (tab === 'extract') reloadAll()
})

watch(paymentLinks, savePaymentState, { deep: true })
watch(paymentCdks, savePaymentState, { deep: true })
</script>
