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
          <h2 class="mt-2 text-2xl font-black text-white md:text-3xl">支付页：UPI 链接与二维码载荷</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-400">从提链页导入已生成的 UPI 链接；若接口返回 Stripe QR 图片则直接预览，若返回 upi:// 则可复制后使用收款 App 扫码/打开。</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="importExtractedLinksToPayment" class="rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-500/20">导入已提取链接</button>
          <button @click="clearFinishedPayments" :disabled="!paymentLinks.length" class="rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:bg-slate-800 disabled:opacity-50">清理失效项</button>
        </div>
      </div>

      <div class="mt-5 grid gap-3 md:grid-cols-4">
        <div v-for="card in paymentSummaryCards" :key="card.label" class="rounded-2xl border bg-slate-950/70 p-4" :class="card.class">
          <div class="text-xs font-bold uppercase tracking-wide text-slate-500">{{ card.label }}</div>
          <div class="mt-2 text-3xl font-black text-white">{{ card.value }}</div>
        </div>
      </div>

      <div class="mt-5 grid gap-5 lg:grid-cols-[0.65fr_1.35fr]">
        <section class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-bold text-white">手动加入</h3>
            <span class="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold text-slate-300">{{ paymentLinks.length }} 行</span>
          </div>
          <textarea v-model="paymentLinkInput" rows="8" spellcheck="false" placeholder="每行一个 UPI 链接或 upi:// 支付载荷" class="mt-4 w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"></textarea>
          <div class="mt-3 flex flex-wrap gap-2">
            <button @click="addPaymentLinksFromInput" class="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white hover:bg-blue-500">加入队列</button>
            <button @click="clearPaymentLinks" :disabled="!paymentLinks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空队列</button>
          </div>
          <div class="mt-4 rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">{{ paymentStatusText }}</div>
        </section>

        <section class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <div class="overflow-auto rounded-xl border border-slate-800">
            <table class="min-w-[980px] w-full text-left text-sm">
              <thead class="bg-slate-900 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th class="px-3 py-2">账号</th>
                  <th class="px-3 py-2">剩余时间</th>
                  <th class="px-3 py-2">二维码/载荷</th>
                  <th class="px-3 py-2">链接</th>
                  <th class="px-3 py-2 text-right">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-900">
                <tr v-if="!paymentLinks.length"><td colspan="5" class="px-3 py-10 text-center text-slate-500">暂无支付队列</td></tr>
                <tr v-for="item in paymentLinks" :key="item.id" class="hover:bg-slate-900/50">
                  <td class="px-3 py-3 font-mono text-xs text-slate-300">{{ item.account || '-' }}</td>
                  <td class="px-3 py-3 text-xs"><span class="rounded-full border px-2 py-1 font-semibold" :class="paymentExpiryClass(item)">{{ paymentExpiryText(item) }}</span></td>
                  <td class="px-3 py-3">
                    <div class="flex items-center gap-3">
                      <img v-if="paymentQrImage(item)" :src="paymentQrImage(item)" alt="UPI QR" class="h-16 w-16 rounded-lg bg-white object-contain p-1" />
                      <span v-else class="inline-flex h-16 w-16 items-center justify-center rounded-lg border border-dashed border-slate-700 text-xs text-slate-500">无图</span>
                      <code class="max-w-[260px] truncate text-xs text-slate-500">{{ item.paymentUri || '-' }}</code>
                    </div>
                  </td>
                  <td class="max-w-[320px] truncate px-3 py-3 font-mono text-xs text-slate-500">{{ item.value }}</td>
                  <td class="px-3 py-3 text-right">
                    <a :href="item.value || '#'" target="_blank" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!item.value ? 'pointer-events-none opacity-50' : ''">打开</a>
                    <button @click="copy(item.paymentUri || item.value)" class="ml-2 rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800">复制</button>
                    <button @click="removePaymentLink(item.id)" class="ml-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20">移除</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>

    <template v-else>
    <div class="grid grid-cols-1 gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">{{ isTempExtract ? '临时 Generate CDK' : 'IN 代理' }}</h3>
        </div>

        <div class="mt-5 space-y-5">
          <template v-if="isTempExtract">
            <label class="block">
              <span class="mb-2 block text-sm font-semibold text-gray-300">临时提链 CDK 池</span>
              <textarea v-model.trim="tempForm.cdk" rows="8" spellcheck="false" placeholder="一行一个 UPI-GEN 临时提链 CDK" class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-amber-500 focus:outline-none" :disabled="busy"></textarea>
              <span class="mt-1 block text-xs text-gray-500">一行一个 CDK；当前 {{ tempCdkLines().length }} 个。提交到 Public UPI Generate API 时会按账号顺序分配。</span>
            </label>
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

          <div class="grid gap-4 md:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="form.concurrency" type="number" min="1" max="10" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">默认 1，最高 10。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">重试次数</span>
              <input v-model.number="form.maxAttempts" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy" />
              <span class="mt-1 block text-xs text-gray-500">单账号最多尝试次数，含首次；默认 5。</span>
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
                  <button @click="deleteUpiAccount(account.email)" :disabled="busy || deletingUpiAccounts.has(account.email)" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50" title="从 UPI 账号池和仪表盘账号池中删除该账号">
                    {{ deletingUpiAccounts.has(account.email) ? '删除中' : '删除' }}
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
            <div v-for="item in currentResult.errors || []" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              <div class="flex flex-wrap items-center gap-2">
                <span class="font-mono">{{ item.email }}</span>
                <span v-if="failureLabel(item)" class="rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-0.5 font-semibold text-rose-100">{{ failureLabel(item) }}</span>
              </div>
              <div class="mt-1 break-words">{{ item.error }}</div>
              <div v-if="retryHint(item)" class="mt-1 text-amber-200">建议：{{ retryHint(item) }}</div>
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
          <h3 class="mt-1 text-xl font-bold text-white">已提取 UPI 链接</h3>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button>
          <button @click="exportLinks" :disabled="!links.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button>
          <button @click="deleteSelectedLinks" :disabled="!selectedLinkIds.size" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">删除选中</button>
          <button @click="clearLinks" :disabled="!links.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空</button>
          <button @click="importExtractedLinksToPayment" :disabled="!links.length" class="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-2 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/20 disabled:opacity-50">导入支付页</button>
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
            <tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50">
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
      </div>
    </section>
    </template>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const FORM_STORAGE_KEY = 'autotoken_india_upi_form'
const TEMP_FORM_STORAGE_KEY = 'autotoken_india_upi_temp_form'
const JOB_STORAGE_KEY = 'autotoken_india_upi_job'
const ACTIVE_TAB_STORAGE_KEY = 'autotoken_india_upi_active_tab'
const PAYMENT_STATE_STORAGE_KEY = 'autotoken_india_upi_payment_state'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled', 'not_implemented'])
const ACCOUNT_STATUS_TEXT = { pending: '未提链', running: '提链中', success: '已提链', failed: '提链失败', paid: '已支付' }
const UPI_LINK_TTL_MS = 5 * 60 * 1000

const form = ref({ proxies: '', concurrency: 1, maxAttempts: 5, localProxy: '', kookeeyEndpoint: 'gate.kookeey.info:1000', kookeeyUser: '', kookeeyPass: '' })
const tempForm = ref({ cdk: '', concurrency: 5 })
const accounts = ref([])
const links = ref([])
const nowMs = ref(Date.now())
const savedTab = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY)
const activeUpiTab = ref(['extract', 'tempExtract', 'payment'].includes(savedTab) ? savedTab : 'extract')
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
const deletingUpiAccounts = ref(new Set())
const paymentLinkInput = ref('')
const paymentLinks = ref([])
const paymentStatusText = ref('等待导入 UPI 链接。')
const logRef = ref(null)
let componentUnmounted = false
let expiryTimer = null

const isTempExtract = computed(() => activeUpiTab.value === 'tempExtract')
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
const paymentSummaryCards = computed(() => [
  { label: '队列链接', value: paymentLinks.value.length, class: 'border-blue-500/30' },
  { label: '可付款', value: paymentLinks.value.filter(item => !paymentExpired(item)).length, class: 'border-emerald-500/30' },
  { label: '已失效', value: paymentLinks.value.filter(paymentExpired).length, class: 'border-rose-500/30' },
  { label: '带二维码', value: paymentLinks.value.filter(item => Boolean(paymentQrImage(item))).length, class: 'border-cyan-500/30' },
])

function setStatus(message, error = false) { statusText.value = message; statusError.value = error }
function cleanText(value) { return String(value || '未知错误').replace(/\s+/g, ' ').trim() }
function cleanError(error) { return cleanText(error?.message || error) }
function parseLines(value) { return String(value || '').split(/\r?\n|,/).map(item => item.trim()).filter(Boolean) }
function tempCdkLines() { return Array.from(new Set(parseLines(tempForm.value.cdk))) }
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
function makePaymentId() { return `upi-pay-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}` }
function normalizePaymentUrl(value) { return String(value || '').trim().replace(/\/+$/, '') }
function normalizePaymentItem(raw) {
  if (!raw || typeof raw !== 'object') return null
  const value = String(raw.value || raw.upi_link || raw.hosted_instructions_url || '').trim()
  const paymentUri = String(raw.paymentUri || raw.upi_payment_uri || raw.qr_image_url_svg || raw.qr_image_url_png || '').trim()
  if (!value && !paymentUri) return null
  return {
    id: String(raw.id || makePaymentId()),
    value,
    upi_link: value,
    hosted_instructions_url: value.startsWith('http') ? value : '',
    paymentUri,
    account: String(raw.account || raw.account_email || raw.accountEmail || '').trim(),
    created_at: raw.created_at || raw.createdAt || '',
    created_at_ts: raw.created_at_ts || raw.createdAtTs || 0,
    upi_expires_at_ts: raw.upi_expires_at_ts || raw.upiExpiresAtTs || 0,
  }
}
function savePaymentState() {
  localStorage.setItem(PAYMENT_STATE_STORAGE_KEY, JSON.stringify({ links: paymentLinks.value }))
}
function loadPaymentState() {
  try {
    const raw = JSON.parse(localStorage.getItem(PAYMENT_STATE_STORAGE_KEY) || '{}')
    paymentLinks.value = Array.isArray(raw.links) ? raw.links.map(normalizePaymentItem).filter(Boolean) : []
    paymentStatusText.value = paymentLinks.value.length ? '已恢复上次支付页数据。' : '等待导入 UPI 链接。'
  } catch {
    paymentLinks.value = []
    paymentStatusText.value = '支付页缓存读取失败，已重置为空。'
  }
}
function addOrUpdatePaymentLink(raw) {
  const item = normalizePaymentItem(raw)
  if (!item) return false
  const key = normalizePaymentUrl(item.value || item.paymentUri)
  const existing = paymentLinks.value.find(row => normalizePaymentUrl(row.value || row.paymentUri) === key)
  if (existing) {
    Object.assign(existing, item, { id: existing.id })
    return false
  }
  paymentLinks.value = [...paymentLinks.value, item]
  return true
}
function addPaymentLinksFromInput() {
  let added = 0
  for (const line of parseLines(paymentLinkInput.value)) {
    if (addOrUpdatePaymentLink({ value: line, paymentUri: line.startsWith('upi://') ? line : '' })) added += 1
  }
  paymentLinkInput.value = ''
  paymentStatusText.value = added ? `已加入 ${added} 条支付记录。` : '没有新增记录，可能为空或重复。'
  savePaymentState()
}
async function importExtractedLinksToPayment() {
  await refreshLinks()
  let added = 0
  let updated = 0
  for (const link of links.value) {
    const before = paymentLinks.value.length
    const created = addOrUpdatePaymentLink({
      id: `link-${link.id || makePaymentId()}`,
      value: upiLinkUrl(link),
      paymentUri: upiPaymentUri(link),
      account: link.account_email || link.accountEmail || '',
      created_at: link.created_at || link.createdAt || '',
      created_at_ts: link.created_at_ts || link.createdAtTs || 0,
      upi_expires_at_ts: link.upi_expires_at_ts || link.upiExpiresAtTs || 0,
    })
    if (created) added += 1
    else if (paymentLinks.value.length === before) updated += 1
  }
  paymentStatusText.value = added || updated ? `已从链接管理导入：新增 ${added}，更新 ${updated}。` : '没有可导入的 UPI 链接。'
  savePaymentState()
}
function removePaymentLink(id) {
  paymentLinks.value = paymentLinks.value.filter(item => item.id !== id)
  paymentStatusText.value = '已移除支付记录。'
  savePaymentState()
}
function clearPaymentLinks() {
  paymentLinks.value = []
  paymentStatusText.value = '已清空支付队列。'
  savePaymentState()
}
function clearFinishedPayments() {
  const before = paymentLinks.value.length
  paymentLinks.value = paymentLinks.value.filter(item => !paymentExpired(item))
  paymentStatusText.value = `已清理 ${before - paymentLinks.value.length} 条失效记录。`
  savePaymentState()
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

async function refreshLinks() {
  try {
    const data = await api.getIndiaUpiLinks()
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
  if (isTempExtract.value) {
    tempForm.value.concurrency = Math.max(1, Math.min(20, Number(tempForm.value.concurrency || 5)))
    if (!tempCdkLines().length) {
      setStatus('请填写临时 UPI 提链 CDK。', true)
      return false
    }
    return true
  }
  form.value.concurrency = Math.max(1, Math.min(10, Number(form.value.concurrency || 1)))
  form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
  if (!form.value.proxies.trim() && (!form.value.kookeeyUser || !form.value.kookeeyPass)) {
    setStatus('请填写 IN 代理列表，或在高级设置填写 Kookeey 用户名/密码。', true)
    return false
  }
  return true
}

async function startWithEmails(emails, actionText = '提取') {
  const accountEmails = Array.from(new Set((emails || []).map(email => String(email || '').trim()).filter(Boolean)))
  if (!validateStart(accountEmails)) return
  const tempMode = isTempExtract.value
  const concurrency = tempMode ? tempForm.value.concurrency : form.value.concurrency
  busy.value = true
  canceling.value = false
  logs.value = []
  currentResult.value = null
  currentJob.value = null
  setStatus(`任务已提交，正在为 ${accountEmails.length} 个账号${actionText} UPI，并发 ${concurrency}。`)
  try {
    saveProxy({ silent: true })
    saveTempForm()
    const payload = tempMode
      ? { cdk: tempForm.value.cdk, concurrency: tempForm.value.concurrency }
      : {
          proxies: form.value.proxies,
          concurrency: form.value.concurrency,
          maxAttempts: form.value.maxAttempts,
          localProxy: form.value.localProxy,
          kookeeyEndpoint: form.value.kookeeyEndpoint,
          kookeeyUser: form.value.kookeeyUser,
          kookeeyPass: form.value.kookeeyPass,
        }
    const data = tempMode
      ? await api.startIndiaUpiTempBatch({ ...payload, accountEmails })
      : await api.startIndiaUpiBatch({ ...payload, accountEmails })
    if (!data.job_id) throw new Error('后端没有返回任务 ID')
    currentJob.value = { id: data.job_id, status: 'queued', total: accountEmails.length, completed: 0, concurrency, running_count: 0 }
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({ jobId: data.job_id, accountCount: accountEmails.length, concurrency, mode: tempMode ? 'tempExtract' : 'extract', startedAt: Date.now() }))
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
    const job = await api.getIndiaUpiJob(jobId)
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
    localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({ jobId, accountCount: total, concurrency: job.concurrency || (isTempExtract.value ? tempForm.value.concurrency : form.value.concurrency), mode: activeUpiTab.value, startedAt: Date.now() }))
    await new Promise(resolve => window.setTimeout(resolve, 1000))
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
  localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value))
  if (!options.silent && !busy.value) setStatus('代理列表已保存。')
}

function saveTempForm(options = {}) {
  localStorage.setItem(TEMP_FORM_STORAGE_KEY, JSON.stringify(tempForm.value))
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

onMounted(async () => {
  componentUnmounted = false
  nowMs.value = Date.now()
  expiryTimer = window.setInterval(() => { nowMs.value = Date.now() }, 1000)
  try {
    const savedForm = JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) || '{}')
    for (const key of Object.keys(form.value)) {
      if (savedForm[key] !== undefined) form.value[key] = savedForm[key]
    }
  } catch { /* ignore malformed local state */ }
  try {
    const savedTempForm = JSON.parse(localStorage.getItem(TEMP_FORM_STORAGE_KEY) || '{}')
    if (savedTempForm.cdk !== undefined) tempForm.value.cdk = String(savedTempForm.cdk || '')
    if (savedTempForm.concurrency !== undefined) tempForm.value.concurrency = Math.max(1, Math.min(20, Number(savedTempForm.concurrency || 5)))
  } catch { /* ignore malformed local state */ }
  loadPaymentState()
  await reloadAll()
  try {
    const saved = JSON.parse(localStorage.getItem(JOB_STORAGE_KEY) || '{}')
    if (saved.jobId) {
      if (['extract', 'tempExtract'].includes(saved.mode)) activeUpiTab.value = saved.mode
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
})

watch(form, () => localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value)), { deep: true })
watch(tempForm, () => localStorage.setItem(TEMP_FORM_STORAGE_KEY, JSON.stringify(tempForm.value)), { deep: true })
watch(activeUpiTab, (value) => localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, value))
watch(paymentLinks, savePaymentState, { deep: true })

onBeforeUnmount(() => {
  componentUnmounted = true
  if (expiryTimer) window.clearInterval(expiryTimer)
  expiryTimer = null
})
</script>
