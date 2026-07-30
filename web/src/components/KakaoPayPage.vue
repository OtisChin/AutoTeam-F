<template>
  <div class="space-y-5">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-2">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div class="inline-flex w-fit rounded-xl border border-gray-800 bg-gray-900/80 p-1">
          <button type="button" @click="activeKakaoTab = 'extract'" class="rounded-lg px-4 py-2 text-sm font-bold transition" :class="activeKakaoTab === 'extract' ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">提链页</button>
          <button type="button" @click="activeKakaoTab = 'tempExtract'" class="rounded-lg px-4 py-2 text-sm font-black transition" :class="activeKakaoTab === 'tempExtract' ? 'bg-yellow-400 text-slate-950 shadow-lg shadow-yellow-400/30' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">临时提链页</button>
          <button type="button" @click="activeKakaoTab = 'payment'" class="rounded-lg px-4 py-2 text-sm font-bold transition" :class="activeKakaoTab === 'payment' ? 'bg-blue-600 text-white shadow-lg shadow-blue-950/40' : 'text-gray-400 hover:bg-gray-800 hover:text-gray-100'">支付页</button>
        </div>
        <p class="px-2 text-xs text-gray-500">
          韩国 Kakao 正式提链、KSCAN 临时提链和 KK 客户支付分开管理，切换不会清空输入。
          <span class="ml-2 inline-flex items-center gap-1 text-gray-400">
            <span class="h-2 w-2 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
            {{ busy ? progressText : '本地服务在线' }}
          </span>
        </p>
      </div>
    </section>

    <template v-if="activeKakaoTab !== 'payment'">
    <div class="grid grid-cols-1 items-start gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">{{ isTempExtract ? '临时提链 CDK 池' : 'KR 代理' }}</h3>
        </div>

        <div class="mt-5 space-y-5">
          <template v-if="isTempExtract">
            <label class="block">
              <span class="mb-2 block text-sm font-semibold text-gray-300">临时提链 CDK 池</span>
              <textarea
                v-model.trim="tempCdkInput"
                rows="5"
                spellcheck="false"
                placeholder="一行一个 KSCAN 临时提链 CDK"
                class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-yellow-300 focus:outline-none"
                :disabled="inputLocked"
              ></textarea>
              <span class="mt-1 block text-xs text-gray-500">一行一个 CDK；可用 {{ availableTempCdkCount }} 枚 / 可提交 {{ availableTempCdkCapacity }} 个账号 / 冷却 {{ coolingTempCdkCount }} / 已使用 {{ usedTempCdkCount }} / 总计 {{ tempCdks.length }}。临时提链 CDK 会按额度重复分配。</span>
            </label>
            <div class="flex flex-wrap gap-2">
              <button @click="addTempCdks" :disabled="inputLocked" class="rounded-lg border border-yellow-400/40 bg-yellow-400/10 px-3 py-2 text-xs font-bold text-yellow-100 hover:bg-yellow-400/20 disabled:opacity-50">加入 CDK 池</button>
              <button @click="queryTempCdkQuota" :disabled="inputLocked || tempCdkQuotaBusy || (!tempCdks.length && !tempCdkInput.trim())" class="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-bold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">{{ tempCdkQuotaBusy ? '查询中...' : '查询额度' }}</button>
              <button @click="clearUsedTempCdks" :disabled="inputLocked || !usedTempCdkCount" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-bold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清理已使用</button>
              <button @click="clearTempCdks" :disabled="inputLocked || !tempCdks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空 CDK</button>
            </div>
            <div class="max-h-56 overflow-auto rounded-xl border border-gray-800">
              <table class="w-full text-left text-sm">
                <thead class="sticky top-0 bg-gray-900 text-xs uppercase tracking-wide text-gray-500"><tr><th class="px-3 py-2">CDK</th><th class="px-3 py-2">状态</th><th class="px-3 py-2">账号</th><th class="px-3 py-2 text-right">操作</th></tr></thead>
                <tbody class="divide-y divide-gray-900">
                  <tr v-if="!tempCdks.length"><td colspan="4" class="px-3 py-8 text-center text-gray-500">暂无临时提链 CDK</td></tr>
                  <tr v-for="item in visibleTempCdks" :key="item.id" class="hover:bg-gray-900/50">
                    <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ maskExternalSecret(item.value) }}</td>
                    <td class="px-3 py-2"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="tempCdkStatusClass(tempCdkDisplayStatus(item))">{{ tempCdkStatusText(tempCdkDisplayStatus(item)) }}</span><div v-if="tempCdkInfoText(item)" class="mt-1 max-w-[220px] truncate text-xs text-gray-500" :title="tempCdkInfoText(item)">{{ tempCdkInfoText(item) }}</div></td>
                    <td class="max-w-[180px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ item.accountEmail || '-' }}</td>
                    <td class="px-3 py-2 text-right"><button @click="removeTempCdk(item.id)" :disabled="inputLocked" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input v-model.number="tempForm.concurrency" type="number" min="1" max="20" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-yellow-300 focus:outline-none" :disabled="inputLocked" />
              <span class="mt-1 block text-xs text-gray-500">默认 5，最高 20。</span>
            </label>
          </template>

          <template v-else>
          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">KR 代理列表</span>
            <textarea
              v-model.trim="form.proxies"
              rows="8"
              spellcheck="false"
              placeholder="每行一个代理；支持 host:port:user-region-KR-sid-xxx-t-120:pass 或 socks5h://user:pass@host:port"
              class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              :disabled="inputLocked"
            ></textarea>
            <span class="mt-1 block text-xs text-gray-500">1024/ArxLabs 的 host:port:user:pass 会自动按 socks5h 使用；建议使用 KR 地区代理。</span>
          </label>

          <div class="grid gap-4 md:grid-cols-3">
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">并发数</span>
              <input
                v-model.number="form.concurrency"
                type="number"
                min="1"
                max="100"
                class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none"
                :disabled="inputLocked"
              />
              <span class="mt-1 block text-xs text-gray-500">默认 1，最高 20。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">重试次数</span>
              <input
                v-model.number="form.maxAttempts"
                type="number"
                min="1"
                max="20"
                class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none"
                :disabled="inputLocked"
              />
              <span class="mt-1 block text-xs text-gray-500">单账号最多尝试次数，含首次；默认 5。</span>
            </label>
            <label class="block">
              <span class="mb-1.5 block text-sm font-semibold text-gray-300">代理预检次数</span>
              <input
                v-model.number="form.proxyPreflightAttempts"
                type="number"
                min="1"
                max="100"
                class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none"
                :disabled="inputLocked"
              />
              <span class="mt-1 block text-xs text-gray-500">代理出口/认证接口预检失败时的最大尝试次数，默认 5。</span>
            </label>
          </div>
          </template>

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="starting || cancelling || !selectedEmails.length" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50">
              {{ starting ? '提交中...' : `${jobRunning ? '追加' : '开始'}${isTempExtract ? '临时' : ''}提链 (${selectedEmails.length})` }}
            </button>
            <button v-if="activeJobIds.length || (activeJobId && jobRunning)" @click="cancelJob" :disabled="cancelling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
              {{ cancelling ? '取消中...' : `取消提链${activeJobIds.length > 1 ? ` (${activeJobIds.length})` : ''}` }}
            </button>
            <button @click="reloadAll" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号/链接</button>
            <button v-if="!isTempExtract" @click="saveProxy" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
            <button v-else @click="saveTempForm" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存 CDK</button>
            <button
              @click="retryFailedAccounts"
              :disabled="inputLocked || !retryFailedEmails.length"
              class="rounded-lg border border-yellow-400/40 bg-yellow-400/10 px-4 py-2.5 text-sm font-semibold text-yellow-200 transition hover:bg-yellow-400/20 disabled:opacity-50"
              title="一键重试上一轮提链失败且仍在账号池中的账号"
            >
              失败重试{{ retryFailedEmails.length ? ` (${retryFailedEmails.length})` : '' }}
            </button>
            <NotificationSoundControl v-model="form.notificationSoundEnabled" :disabled="inputLocked" />
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
            <button @click="selectAllFiltered" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
            <button @click="clearSelectedAccounts" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
            <button
              @click="deleteSelectedKakaoAccounts"
              :disabled="inputLocked || deletingKakaoAccounts.size > 0 || !selectedEmails.length"
              class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
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
                  <input :checked="selectedAccounts.has(account.email)" type="checkbox" class="accent-emerald-500" :disabled="inputLocked || !accountSelectable(account)" @change="toggleAccount(account.email)" />
                </td>
                <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ account.email }}</td>
                <td class="px-3 py-2 text-xs text-gray-500">{{ ttlText(account.ttl_seconds) }}</td>
                <td class="px-3 py-2 text-xs">
                  <span class="inline-flex rounded-full border px-2 py-1 font-semibold" :class="accountStatusClass(account)" :title="accountStatusError(account)">
                    {{ accountStatusText(account) }}
                  </span>
                </td>
                <td class="px-3 py-2 text-right">
                  <button
                    @click="deleteKakaoAccount(account.email)"
                    :disabled="inputLocked || deletingKakaoAccounts.has(account.email)"
                    class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                    title="从 Kakao 账号池和仪表盘账号池中删除该账号"
                  >
                    {{ deletingKakaoAccounts.has(account.email) ? '删除中' : '删除' }}
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
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="kakaoLinkUrl(item.link) || '#'" target="_blank" rel="noopener" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!kakaoLinkUrl(item.link) ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(kakaoLinkUrl(item.link))" :disabled="!kakaoLinkUrl(item.link)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100 disabled:opacity-50">复制链</button>
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
          <h3 class="mt-1 text-xl font-bold text-white">已提取 Kakao 链接</h3>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="refreshLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800">刷新</button>
          <button @click="exportLinks" :disabled="!links.length" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">导出 JSON</button>
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
              <th class="px-3 py-2">账号</th>
              <th class="px-3 py-2">金额</th>
              <th class="px-3 py-2">CS ID</th>
              <th class="px-3 py-2">剩余时间</th>
              <th class="px-3 py-2">操作</th>
              <th class="px-3 py-2">Kakao 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!links.length">
              <td colspan="8" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in links" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ link.created_at }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || '-' }}</td>
              <td class="px-3 py-2 text-xs text-gray-400">{{ link.amount || '-' }} KRW</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-400">{{ link.cs_id || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-xs">
                <span class="rounded-full border px-2 py-1 font-semibold" :class="kakaoExpiryClass(link)">
                  {{ kakaoExpiryText(link) }}
                </span>
              </td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-2">
                  <a :href="kakaoLinkUrl(link) || '#'" target="_blank" rel="noopener" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!kakaoLinkActionable(link) ? 'pointer-events-none opacity-50' : ''">打开</a>
                  <button @click="copy(kakaoLinkUrl(link))" :disabled="!kakaoLinkActionable(link)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200 disabled:opacity-50">复制链</button>
                </div>
              </td>
              <td class="max-w-[360px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ kakaoLinkUrl(link) || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
    </template>

    <section v-else class="overflow-hidden rounded-2xl border border-blue-500/20 bg-[radial-gradient(circle_at_top_left,rgba(59,130,246,0.13),transparent_34%),linear-gradient(135deg,rgba(15,23,42,0.96),rgba(2,6,23,0.98))] p-5 shadow-2xl shadow-black/30 md:p-6">
      <div class="flex flex-col gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-start md:justify-between">
        <div>
          <p class="text-xs font-black uppercase tracking-[0.22em] text-blue-300/80">KK Customer Payment API</p>
          <h2 class="mt-2 text-2xl font-black text-white md:text-3xl">支付页：已提链账号 + KK CDK 支付</h2>
          <p class="mt-2 max-w-3xl text-sm text-slate-400">只同步已提取 Kakao/NicePay 链接的账号；提交时后端按账号加载 access token，并和链接、KK CDK 一起提交。支付 CDK 按额度重复分配。</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button @click="importKkPaymentLinks" :disabled="kkPaymentCdkQuotaBusy" class="rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-2.5 text-sm font-bold text-cyan-100 transition hover:bg-cyan-500/20 disabled:opacity-50">同步已提取链接</button>
          <button @click="runAllKkPayments" :disabled="!kkPaymentStartable" class="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-bold text-white shadow-lg shadow-blue-950/40 transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50">▶ {{ kkPaymentBusy ? '追加提交' : '提交全部' }}</button>
          <button @click="clearInvalidKkPaymentLinks" :disabled="kkPaymentBusy || !kkPaymentInvalidCount" class="rounded-xl border border-yellow-400/40 bg-yellow-400/10 px-4 py-2.5 text-sm font-bold text-yellow-100 transition hover:bg-yellow-400/20 disabled:opacity-50">清理失效</button>
          <button @click="clearFinishedKkPayments" :disabled="kkPaymentBusy || !kkPaymentLinks.length" class="rounded-xl border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-bold text-slate-200 transition hover:bg-slate-800 disabled:opacity-50">清理已结束</button>
        </div>
      </div>

      <div class="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <div v-for="card in kkPaymentSummaryCards" :key="card.label" class="rounded-2xl border bg-slate-950/70 p-4" :class="card.class">
          <div class="text-xs font-bold uppercase tracking-wide text-slate-500">{{ card.label }}</div>
          <div class="mt-2 text-3xl font-black text-white">{{ card.value }}</div>
        </div>
      </div>

      <div class="mt-5 grid gap-5 lg:grid-cols-[0.62fr_1.38fr]">
        <section class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <div class="flex items-center justify-between">
            <h3 class="text-lg font-bold text-white">KK CDK 管理池</h3>
            <span class="rounded-full bg-slate-800 px-3 py-1 text-xs font-bold text-slate-300">{{ kkPaymentLinks.length }} 账号 / {{ kkPaymentCdks.length }} CDK</span>
          </div>
          <p class="mt-4 rounded-xl border border-blue-500/20 bg-blue-500/10 p-3 text-xs leading-5 text-blue-100">
            支付任务固定来自“已提取 Kakao 链接”的账号。支付 CDK 会按额度可重复分配；提交后本地扣减一次容量，可用额度以查询结果为准。
          </p>
          <label class="mt-4 block">
            <span class="mb-2 block text-xs font-bold uppercase tracking-wide text-slate-500">KK CDK / X-CDK-Key 池</span>
            <textarea v-model="kkPaymentCdkInput" rows="5" spellcheck="false" placeholder="一行一个 KK 支付 CDK" class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 font-mono text-sm text-white placeholder:text-slate-600 focus:border-blue-500 focus:outline-none" :disabled="kkPaymentCdkQuotaBusy"></textarea>
          </label>
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <label class="block">
              <span class="mb-1.5 block text-xs font-bold uppercase tracking-wide text-slate-500">并发数</span>
              <input v-model.number="kkPaymentConcurrency" type="number" min="1" max="20" class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="kkPaymentBusy" />
            </label>
            <label class="block">
              <span class="mb-1.5 block text-xs font-bold uppercase tracking-wide text-slate-500">支付方式</span>
              <select v-model="kkPaymentMethod" class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="kkPaymentBusy"><option value="kakao_pay">kakao_pay</option><option value="naver_pay">naver_pay</option></select>
            </label>
          </div>
          <div class="mt-3 flex flex-wrap gap-2">
            <button @click="addKkPaymentCdks" :disabled="kkPaymentCdkQuotaBusy" class="rounded-lg bg-blue-600 px-3 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-50">加入 CDK 池</button>
            <button @click="queryKkPaymentCdkQuota" :disabled="kkPaymentCdkQuotaBusy || (!kkPaymentCdks.length && !kkPaymentCdkInput.trim())" class="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-3 py-2 text-xs font-bold text-cyan-100 hover:bg-cyan-500/20 disabled:opacity-50">{{ kkPaymentCdkQuotaBusy ? '查询中...' : '查询额度' }}</button>
            <button @click="clearKkPaymentLinks" :disabled="kkPaymentBusy || !kkPaymentLinks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空账号池</button>
            <button @click="clearKkPaymentCdks" :disabled="kkPaymentBusy || !kkPaymentCdks.length" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">清空 CDK</button>
          </div>
          <div class="mt-4 rounded-xl border border-slate-800 bg-slate-950 p-3 text-xs text-slate-400">{{ kkPaymentStatusText }}</div>
          <div class="mt-4 max-h-56 overflow-auto rounded-xl border border-slate-800">
            <table class="w-full text-left text-sm">
              <thead class="sticky top-0 bg-slate-900 text-xs uppercase tracking-wide text-slate-500"><tr><th class="px-3 py-2">CDK</th><th class="px-3 py-2">状态</th><th class="px-3 py-2">账号</th></tr></thead>
              <tbody class="divide-y divide-slate-900">
                <tr v-if="!kkPaymentCdks.length"><td colspan="3" class="px-3 py-6 text-center text-slate-500">暂无 KK 支付 CDK</td></tr>
                <tr v-for="cdk in visibleKkPaymentCdks" :key="cdk.id" class="hover:bg-slate-900/50">
                  <td class="px-3 py-2 font-mono text-xs text-slate-400">{{ maskExternalSecret(cdk.value) }}</td>
                  <td class="px-3 py-2"><span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="kkPaymentCdkStatusClass(kkPaymentCdkDisplayStatus(cdk))">{{ kkPaymentCdkStatusText(kkPaymentCdkDisplayStatus(cdk)) }}</span><div v-if="cdk.message" class="mt-1 text-xs text-slate-500">{{ cdk.message }}</div></td>
                  <td class="max-w-[180px] truncate px-3 py-2 font-mono text-xs text-slate-500">{{ cdk.accountEmail || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section class="rounded-2xl border border-slate-800 bg-slate-950/60 p-4">
          <div class="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
            <div>
              <h3 class="text-lg font-bold text-white">账号管理池（已提取链接）</h3>
              <span class="text-xs text-slate-500">显示 {{ visibleKkPaymentLinks.length }} / 总 {{ kkPaymentLinks.length }}，可提交 {{ kkPaymentRunnableCount }} / 可用额度 {{ kkPaymentAvailableCdkCapacity }}</span>
            </div>
            <select v-model="kkPaymentStatusFilter" class="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-bold text-slate-200 focus:border-blue-500 focus:outline-none">
              <option value="all">全部状态</option>
              <option value="runnable">可提交</option>
              <option value="pending">待提交</option>
              <option value="running">运行中</option>
              <option value="success">成功</option>
              <option value="needs_action">需处理</option>
              <option value="failed">失败</option>
              <option value="stopped">已停止</option>
            </select>
          </div>
          <div class="max-h-[640px] overflow-auto rounded-xl border border-slate-800 bg-slate-950/70 p-3">
            <div v-if="!kkPaymentLinks.length" class="rounded-xl border border-dashed border-slate-800 px-4 py-12 text-center text-sm text-slate-500">
              暂无账号；点击“同步已提取链接”导入已提链账号
            </div>
            <div v-else-if="!visibleKkPaymentLinks.length" class="rounded-xl border border-dashed border-slate-800 px-4 py-12 text-center text-sm text-slate-500">
              当前筛选下没有账号
            </div>
            <div v-else class="space-y-3">
              <article v-for="item in visibleKkPaymentLinks" :key="item.id" class="rounded-xl border border-slate-800 bg-slate-900/35 p-4 transition hover:border-slate-700 hover:bg-slate-900/55">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-2">
                      <span class="inline-flex rounded-full border px-2 py-1 text-xs font-bold" :class="kkPaymentStatusClass(item.status)">{{ kkPaymentLinkStatusText(item.status) }}</span>
                      <span class="truncate font-mono text-sm font-semibold text-slate-200">{{ item.accountEmail || '-' }}</span>
                      <span class="rounded-full border px-2 py-1 text-xs font-semibold" :class="kakaoExpiryClass(item)">{{ kakaoExpiryText(item) }}</span>
                    </div>
                    <div v-if="item.message" class="mt-2 max-w-3xl truncate text-xs text-slate-500" :title="item.message">{{ item.message }}</div>
                  </div>
                  <div class="flex shrink-0 flex-wrap justify-end gap-2">
                    <button @click="runKkPaymentTask(item)" :disabled="!kkPaymentTaskRunnable(item)" class="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs font-bold text-blue-200 hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-50">提交/查询</button>
                    <button v-if="kkPaymentCanCancel(item)" @click="cancelKkPaymentOrder(item)" class="rounded-lg border border-orange-400/40 bg-orange-400/10 px-3 py-1.5 text-xs font-bold text-orange-100 hover:bg-orange-400/20">取消订单</button>
                    <button v-if="kkPaymentCanResubmit(item)" @click="resubmitKkPaymentOrder(item)" class="rounded-lg border border-cyan-400/40 bg-cyan-400/10 px-3 py-1.5 text-xs font-bold text-cyan-100 hover:bg-cyan-400/20">重投订单</button>
                    <button v-if="kkPaymentNeedsRelink(item)" @click="reExtractKkPaymentLink(item)" :disabled="starting || cancelling" class="rounded-lg border border-yellow-400/40 bg-yellow-400/10 px-3 py-1.5 text-xs font-bold text-yellow-100 hover:bg-yellow-400/20 disabled:opacity-50">重新提链</button>
                    <a :href="item.paymentUrl || '#'" target="_blank" class="rounded-lg border border-sky-500/30 bg-sky-500/10 px-3 py-1.5 text-xs font-bold text-sky-200 hover:bg-sky-500/20" :class="!item.paymentUrl ? 'pointer-events-none opacity-50' : ''">打开</a>
                    <button @click="copy(item.paymentUrl || item.orderId)" class="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-bold text-slate-200 hover:bg-slate-800">复制</button>
                    <button @click="removeKkPaymentLink(item.id)" :disabled="kkPaymentBusy" class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-bold text-rose-200 hover:bg-rose-500/20 disabled:opacity-50">移除</button>
                  </div>
                </div>
                <div class="mt-4 grid gap-3 xl:grid-cols-[1fr_0.9fr_auto]">
                  <div class="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
                    <div class="text-[10px] font-bold uppercase tracking-wide text-slate-600">Order</div>
                    <div class="mt-1 truncate font-mono text-xs text-slate-400" :title="item.orderId || '-'">{{ item.orderId || '-' }}</div>
                  </div>
                  <div class="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
                    <div class="text-[10px] font-bold uppercase tracking-wide text-slate-600">CDK</div>
                    <div class="mt-1 truncate font-mono text-xs text-slate-400" :title="item.cdk || '-'">{{ maskExternalSecret(item.cdk || '') || '-' }}</div>
                  </div>
                  <div class="rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
                    <div class="text-[10px] font-bold uppercase tracking-wide text-slate-600">链接</div>
                    <div class="mt-1 text-xs font-semibold" :class="kakaoLinkActionable(item) ? 'text-sky-300' : 'text-rose-300'">{{ kakaoPaymentLinkSummary(item) }}</div>
                  </div>
                </div>
              </article>
            </div>
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'
import NotificationSoundControl from './NotificationSoundControl.vue'
import { LINK_SUCCESS_SOUND_URL, playNotificationSound } from '../notificationSounds.js'

const PROXY_STORAGE_KEY = 'autotoken_kakao_pay_proxies'
const FORM_STORAGE_KEY = 'autotoken_kakao_pay_form'
const TEMP_FORM_STORAGE_KEY = 'autotoken_kakao_pay_temp_form'
const TEMP_CDK_STATE_STORAGE_KEY = 'autotoken_kakao_pay_temp_cdks'
const KK_PAYMENT_STATE_STORAGE_KEY = 'autotoken_kakao_pay_kk_payment_state'
const JOB_STORAGE_KEY = 'autotoken_kakao_pay_job'
const ACTIVE_TAB_STORAGE_KEY = 'autotoken_kakao_pay_active_tab'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled'])
const KK_PAYMENT_TERMINAL_STATUSES = new Set(['success', 'succeeded', 'paid', 'completed', 'failed', 'stopped', 'cancelled', 'canceled', 'error', 'rejected', 'expired', 'timeout', 'qr_timeout', 'paused'])
const KK_PAYMENT_RETRYABLE_STATUSES = new Set(['pending', 'imported', 'failed', 'needs_action', 'stopped'])
const KAKAO_LINK_TTL_MS = 15 * 60 * 1000

const savedKakaoTab = localStorage.getItem(ACTIVE_TAB_STORAGE_KEY)
const activeKakaoTab = ref(['extract', 'tempExtract', 'payment'].includes(savedKakaoTab) ? savedKakaoTab : 'extract')
const accounts = ref([])
const links = ref([])
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const logs = ref([])
const loading = ref(false)
const starting = ref(false)
const cancelling = ref(false)
const activeJobId = ref('')
const activeJobIds = ref([])
const activeJobStatus = ref('')
const currentJob = ref(null)
const currentResult = ref(null)
const statusText = ref('请选择账号并填写 KR 代理后开始提链。')
const statusError = ref(false)
const accountFilter = ref('')
const accountStatusFilter = ref('all')
const accountVisibleCount = ref(100)
const recentResultFilter = ref('all')
const deletingKakaoAccounts = ref(new Set())
const lastFailedEmails = ref([])
const notifiedSuccessKeys = ref(new Set())
const nowMs = ref(Date.now())
const logRef = ref(null)
const tempForm = ref({ concurrency: 5 })
const tempCdkInput = ref('')
const tempCdks = ref([])
const tempCdkQuotaBusy = ref(false)
const kkForm = ref({ cdk: '', accessTokens: '', paymentUrl: '', paymentMethod: 'kakao_pay', mode: 'READY_LINK' })
const kkOrders = ref([])
const kkBusy = ref(false)
const kkStatusText = ref('填写 KK CDK、AT 和 NicePay 链接后提交支付订单。')
const kkPaymentCdkInput = ref('')
const kkPaymentCdks = ref([])
const kkPaymentLinks = ref([])
const kkPaymentBusy = ref(false)
const kkPaymentActiveRuns = ref(0)
const kkPaymentCdkQuotaBusy = ref(false)
const kkPaymentRunningCount = ref(0)
const kkPaymentConcurrency = ref(5)
const kkPaymentMethod = ref('kakao_pay')
const kkPaymentStatusText = ref('等待同步已提取 Kakao 链接并加入 KK 支付 CDK。')
const kkPaymentStatusFilter = ref('all')
let timer = null
let expiryTimer = null
let componentUnmounted = false

const savedForm = loadForm()
const form = ref({
  proxies: localStorage.getItem(PROXY_STORAGE_KEY) || savedForm.proxies || '',
  concurrency: savedForm.concurrency || 1,
  maxAttempts: savedForm.maxAttempts || 5,
  proxyPreflightAttempts: savedForm.proxyPreflightAttempts || 5,
  notificationSoundEnabled: savedForm.notificationSoundEnabled !== false,
})

const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const isTempExtract = computed(() => activeKakaoTab.value === 'tempExtract')
const jobRunning = computed(() => Boolean((activeJobIds.value.length || activeJobId.value) && !TERMINAL_STATUSES.has(activeJobStatus.value)))
const inputLocked = computed(() => starting.value || cancelling.value)
const busy = computed(() => loading.value || inputLocked.value)
const progressText = computed(() => {
  if (starting.value) return '正在创建任务...'
  if (jobRunning.value) return `任务 ${activeJobStatus.value || 'running'}`
  return '刷新中...'
})
const badgeText = computed(() => {
  if (!activeJobId.value) return '等待任务'
  if (activeJobStatus.value === 'success') return '已完成'
  if (['error', 'failed'].includes(activeJobStatus.value)) return '失败'
  if (activeJobStatus.value === 'cancelled') return '已取消'
  return activeJobStatus.value || '运行中'
})
const badgeClass = computed(() => {
  if (activeJobStatus.value === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (['error', 'failed', 'cancelled'].includes(activeJobStatus.value)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (activeJobId.value) return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
})
const filteredAccounts = computed(() => {
  const query = accountFilter.value.trim().toLowerCase()
  const status = accountStatusFilter.value
  return accounts.value.filter((account) => {
    const email = String(account.email || '').toLowerCase()
    const accountStatusValue = accountStatus(account)
    return (!query || email.includes(query)) && (status === 'all' || accountStatusValue === status)
  })
})
const visibleAccounts = computed(() => filteredAccounts.value.slice(0, accountVisibleCount.value))
const hiddenAccountCount = computed(() => Math.max(0, filteredAccounts.value.length - visibleAccounts.value.length))
const currentResultSuccesses = computed(() => Array.isArray(currentResult.value?.successes) ? currentResult.value.successes : [])
const currentResultErrors = computed(() => Array.isArray(currentResult.value?.errors) ? currentResult.value.errors : [])
const currentResultSkipped = computed(() => Array.isArray(currentResult.value?.skipped) ? currentResult.value.skipped : [])
const filteredRecentResultCount = computed(() => {
  if (recentResultFilter.value === 'success') return currentResultSuccesses.value.length
  if (recentResultFilter.value === 'failed') return currentResultErrors.value.length
  return currentResultSuccesses.value.length + currentResultErrors.value.length + currentResultSkipped.value.length
})
const availableTempCdkCount = computed(() => tempCdks.value.filter(tempCdkUsable).length)
const coolingTempCdkCount = computed(() => tempCdks.value.filter(item => item.status === 'cooling').length)
const usedTempCdkCount = computed(() => tempCdks.value.filter(item => item.status === 'used' && !tempCdkUsable(item)).length)
const availableTempCdkCapacity = computed(() => tempCdks.value.filter(tempCdkUsable).reduce((sum, item) => sum + tempCdkCapacity(item), 0))
const kkPaymentAvailableCdkCount = computed(() => kkPaymentCdks.value.filter(kkPaymentCdkUsable).length)
const kkPaymentAvailableCdkCapacity = computed(() => kkPaymentCdks.value.reduce((sum, item) => sum + kkPaymentCdkCapacity(item), 0))
const kkPaymentRunnableCount = computed(() => kkPaymentLinks.value.filter(kkPaymentTaskRunnable).length)
const kkPaymentInvalidCount = computed(() => kkPaymentLinks.value.filter(kkPaymentLinkInvalid).length)
const kkPaymentStartable = computed(() => kkPaymentRunnableCount.value || (kakaoImportablePaymentLinks.value.length && kkPaymentAvailableCdkCount.value))
const kakaoImportablePaymentLinks = computed(() => links.value.filter(kakaoLinkImportable))
const visibleTempCdks = computed(() => [...tempCdks.value].reverse())
const visibleKkPaymentCdks = computed(() => [...kkPaymentCdks.value].reverse())
const sortedKkPaymentLinks = computed(() => [...kkPaymentLinks.value].reverse())
const visibleKkPaymentLinks = computed(() => {
  const filter = String(kkPaymentStatusFilter.value || 'all')
  return sortedKkPaymentLinks.value.filter(item => {
    if (filter === 'all') return true
    if (filter === 'runnable') return kkPaymentTaskRunnable(item)
    return kkPaymentTaskFilterStatus(item) === filter
  })
})
const kkPaymentSummaryCards = computed(() => [
  { label: '待提交', value: kkPaymentLinks.value.filter(kkPaymentTaskRunnable).length, class: 'border-blue-500/30' },
  { label: '正在运行', value: kkPaymentRunningCount.value, class: 'border-sky-500/30' },
  { label: '已成功', value: kkPaymentLinks.value.filter(item => item.status === 'success').length, class: 'border-emerald-500/30' },
  { label: '失效/需处理', value: kkPaymentLinks.value.filter(item => kkPaymentLinkInvalid(item) || ['failed', 'stopped', 'needs_action'].includes(item.status)).length, class: 'border-rose-500/30' },
  { label: '可用 CDK', value: kkPaymentAvailableCdkCount.value, class: 'border-cyan-500/30' },
  { label: '可用次数', value: kkPaymentAvailableCdkCapacity.value, class: 'border-cyan-400/30' },
])
const accountEmailByLower = computed(() => {
  const map = new Map()
  for (const account of accounts.value) {
    const email = String(account.email || '').trim()
    if (email) map.set(email.toLowerCase(), email)
  }
  return map
})
const retryFailedEmails = computed(() => {
  const available = accountEmailByLower.value
  const seen = new Set()
  const emails = []
  for (const email of lastFailedEmails.value) {
    const accountEmail = available.get(String(email || '').trim().toLowerCase())
    if (!accountEmail) continue
    const key = accountEmail.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    emails.push(accountEmail)
  }
  return emails
})

watch(form, () => saveForm(), { deep: true })
watch(tempForm, () => saveTempForm({ silent: true }), { deep: true })
watch(tempCdks, saveTempCdkState, { deep: true })
watch(kkPaymentLinks, saveKkPaymentState, { deep: true })
watch(kkPaymentCdks, saveKkPaymentState, { deep: true })
watch([kkPaymentConcurrency, kkPaymentMethod], saveKkPaymentState)
watch(activeKakaoTab, value => localStorage.setItem(ACTIVE_TAB_STORAGE_KEY, value))
watch([accountFilter, accountStatusFilter], () => { accountVisibleCount.value = 100 })
watch(logs, () => nextTick(scrollLogsToBottom))

function loadForm() {
  try {
    const data = JSON.parse(localStorage.getItem(FORM_STORAGE_KEY) || '{}')
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
}

function saveForm() {
  localStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value))
  localStorage.setItem(PROXY_STORAGE_KEY, form.value.proxies || '')
}

function setStatus(message, error = false) {
  statusText.value = message
  statusError.value = Boolean(error)
}

function cleanError(error) {
  const detail = error?.detail || error?.data?.detail || error?.data
  const nested = detail?.error || error?.error
  const code = nested?.code || detail?.code || error?.code
  const message = nested?.message || detail?.message || error?.message || error
  const text = String(message || '未知错误')
  return code ? `${text} (${code})` : text
}

function makeTempCdkId() {
  return `kakao-temp-cdk-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function tempCdkHasKnownQuota(item) {
  const total = Number(item?.totalUses ?? item?.total_uses ?? 0)
  const used = Number(item?.usedUses ?? item?.used_uses ?? 0)
  const reserved = Number(item?.reservedUses ?? item?.reserved_uses ?? item?.pending_uses ?? 0)
  const message = String(item?.message || '')
  return (Number.isFinite(total) && total > 0)
    || (Number.isFinite(used) && used > 0)
    || (Number.isFinite(reserved) && reserved > 0)
    || message.includes('额度')
}

function tempCdkUsable(item) {
  if (!item) return false
  const status = String(item.status || 'available')
  if (status === 'failed' || status === 'used') return false
  if (status === 'cooling' && Number(item.cooldownUntilMs || 0) > Date.now()) return false
  const remaining = Number(item.remainingUses)
  const reserved = Number(item.reservedUses || 0)
  if (status === 'available' || status === 'reserved') return !Number.isFinite(remaining) || Math.max(0, remaining - reserved) > 0
  return tempCdkHasKnownQuota(item) && Number.isFinite(remaining) && remaining > 0
}

function reconcileTempCdkQuotaState(item) {
  if (!item) return item
  const remaining = Number(item.remainingUses)
  if (item.status === 'reserved') return item
  if (item.status === 'cooling' && Number(item.cooldownUntilMs || 0) > Date.now()) return item
  if (Number.isFinite(remaining) && remaining <= 0 && tempCdkHasKnownQuota(item)) {
    item.status = 'used'
    return item
  }
  if (tempCdkUsable(item)) {
    item.status = 'available'
    item.cooldownUntilMs = 0
  }
  return item
}

function tempCdkDisplayStatus(item) {
  if (tempCdkUsable(item)) return Number(item?.reservedUses || 0) > 0 ? 'reserved' : 'available'
  return String(item?.status || 'available')
}

function tempCdkStatusText(status) {
  return ({ available: '可用', reserved: '运行中', cooling: '冷却中', used: '已使用', failed: '失败' })[String(status || '')] || '可用'
}

function tempCdkStatusClass(status) {
  const key = String(status || 'available')
  if (key === 'available') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (key === 'reserved') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (key === 'cooling') return 'border-yellow-400/30 bg-yellow-400/10 text-yellow-200'
  if (key === 'used') return 'border-gray-700 bg-gray-900 text-gray-400'
  return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
}

function tempCdkRemainingText(untilMs, baseMs = nowMs.value) {
  const remain = Number(untilMs || 0) - Number(baseMs || Date.now())
  if (remain <= 0) return ''
  const seconds = Math.ceil(remain / 1000)
  const minutes = Math.floor(seconds / 60)
  return minutes ? `剩余 ${minutes}:${String(seconds % 60).padStart(2, '0')}` : `剩余 ${seconds}s`
}

function tempCdkInfoText(item) {
  const coolingText = item?.status === 'cooling' ? tempCdkRemainingText(item.cooldownUntilMs) : ''
  return [coolingText, item?.message || ''].filter(Boolean).join(' · ')
}

function normalizeTempCdkItem(raw) {
  const value = String(typeof raw === 'string' ? raw : raw?.value || raw?.cdk || '').trim()
  if (!value) return null
  const rawStatus = String(typeof raw === 'object' ? raw.status || 'available' : 'available').toLowerCase()
  const rawCooldownUntilMs = Number(typeof raw === 'object' ? raw.cooldownUntilMs || raw.cooldown_until_ms || 0 : 0)
  const status = rawStatus === 'cooling' && rawCooldownUntilMs <= Date.now()
    ? 'available'
    : (['available', 'reserved', 'cooling', 'used', 'failed'].includes(rawStatus) ? rawStatus : 'available')
  const item = {
    id: String((typeof raw === 'object' && raw.id) || makeTempCdkId()),
    value,
    status,
    accountEmail: String((typeof raw === 'object' && (raw.accountEmail || raw.account_email)) || '').trim(),
    jobId: String((typeof raw === 'object' && (raw.jobId || raw.job_id)) || '').trim(),
    message: String((typeof raw === 'object' && (raw.message || raw.error)) || '').trim(),
    cooldownUntilMs: status === 'cooling' && rawCooldownUntilMs > Date.now() ? rawCooldownUntilMs : 0,
    remainingUses: Number(typeof raw === 'object' ? raw.remainingUses ?? raw.remaining_uses ?? 1 : 1),
    totalUses: Number(typeof raw === 'object' ? raw.totalUses ?? raw.total_uses ?? 0 : 0),
    usedUses: Number(typeof raw === 'object' ? raw.usedUses ?? raw.used_uses ?? 0 : 0),
    reservedUses: Number(typeof raw === 'object' ? raw.reservedUses ?? raw.reserved_uses ?? raw.pending_uses ?? 0 : 0),
    reservations: (typeof raw === 'object' && raw.reservations && typeof raw.reservations === 'object') ? raw.reservations : {},
  }
  return reconcileTempCdkQuotaState(item)
}

function tempCdkCapacity(item) {
  if (!tempCdkUsable(item)) return 0
  const remaining = Number(item.remainingUses)
  const reserved = Number(item.reservedUses || 0)
  return Number.isFinite(remaining) && remaining > 0 ? Math.max(0, Math.floor(remaining - reserved)) : 1
}

function tempCdkLines() {
  const lines = []
  for (const item of tempCdks.value.filter(tempCdkUsable)) {
    for (let index = 0; index < tempCdkCapacity(item); index += 1) lines.push(item.value)
  }
  return lines
}

function addTempCdks(options = {}) {
  const existing = new Set(tempCdks.value.map(item => item.value.toLowerCase()))
  const items = []
  for (const line of textLines(tempCdkInput.value).flatMap(item => item.split(',')).map(item => item.trim()).filter(Boolean)) {
    const key = line.toLowerCase()
    if (existing.has(key)) continue
    existing.add(key)
    items.push({ id: makeTempCdkId(), value: line, status: 'available', accountEmail: '', jobId: '', message: '', cooldownUntilMs: 0, remainingUses: 1, totalUses: 0, usedUses: 0, reservedUses: 0 })
  }
  if (items.length) tempCdks.value = [...tempCdks.value, ...items]
  tempCdkInput.value = ''
  if (!options.silent) setStatus(items.length ? `已加入 ${items.length} 枚 KSCAN 临时提链 CDK。` : '没有新增 CDK，可能为空或重复。')
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

function tempCdkQuotaPayload(data) {
  const payload = data?.data || data || {}
  const ticket = payload.ticket || payload.cdk || payload
  return ticket && typeof ticket === 'object' ? ticket : {}
}

function tempCdkQuotaValues(ticket) {
  const rawTotal = ticket.total_uses ?? ticket.totalUses ?? ticket.total
  const rawReserved = ticket.reserved_uses ?? ticket.reservedUses ?? ticket.pending_uses ?? ticket.pendingUses
  const rawRemaining = ticket.available_uses ?? ticket.availableUses ?? ticket.remaining_uses ?? ticket.remainingUses ?? ticket.remaining
  const totalNumber = Number(rawTotal)
  const reservedNumber = Number(rawReserved ?? 0)
  const remainingNumber = Number(rawRemaining)
  let rawUsed = ticket.used_uses ?? ticket.usedUses ?? ticket.used
  if (rawUsed === undefined && Number.isFinite(totalNumber)) {
    if (Number.isFinite(Number(ticket.remaining_uses ?? ticket.remainingUses))) {
      rawUsed = Math.max(0, totalNumber - Number(ticket.remaining_uses ?? ticket.remainingUses))
    } else if (Number.isFinite(remainingNumber)) {
      rawUsed = Math.max(0, totalNumber - remainingNumber - (Number.isFinite(reservedNumber) ? reservedNumber : 0))
    }
  }
  let remaining = rawRemaining
  if (remaining === undefined) {
    const usedNumber = Number(rawUsed)
    remaining = Number.isFinite(totalNumber) && Number.isFinite(usedNumber)
      ? Math.max(0, totalNumber - usedNumber - (Number.isFinite(reservedNumber) ? reservedNumber : 0))
      : '-'
  }
  return {
    total: rawTotal ?? '-',
    used: rawUsed ?? '-',
    reserved: rawReserved ?? 0,
    remaining,
  }
}

function tempCdkQuotaMessage(ticket) {
  const { total, used, reserved, remaining } = tempCdkQuotaValues(ticket)
  return `额度：总 ${total}，已用 ${used}，处理中 ${reserved}，剩余 ${remaining}`
}

async function queryTempCdkQuota() {
  if (tempCdkInput.value.trim()) addTempCdks({ silent: true })
  const targets = tempCdks.value.filter(item => String(item.value || '').trim())
  if (!targets.length) {
    setStatus('请先加入要查询额度的 KSCAN CDK。', true)
    return
  }
  tempCdkQuotaBusy.value = true
  let ok = 0
  let failed = 0
  try {
    for (const item of targets) {
      try {
        item.message = '正在查询额度...'
        const data = await api.getKakaoPayTempTicketStatus(item.value)
        const ticket = tempCdkQuotaPayload(data)
        const quota = tempCdkQuotaValues(ticket)
        item.totalUses = Number(quota.total === '-' ? 0 : quota.total)
        item.usedUses = Number(quota.used === '-' ? 0 : quota.used)
        item.reservedUses = Number(quota.reserved === '-' ? 0 : quota.reserved)
        item.remainingUses = Number(quota.remaining === '-' ? Math.max(0, item.totalUses - item.usedUses - item.reservedUses) : quota.remaining)
        item.message = tempCdkQuotaMessage(ticket)
        const remaining = Number(item.remainingUses)
        if (Number.isFinite(remaining) && remaining <= 0) {
          item.status = 'used'
        } else if (item.status !== 'reserved') {
          item.status = 'available'
          item.cooldownUntilMs = 0
        }
        ok += 1
      } catch (error) {
        item.status = item.status === 'reserved' ? item.status : 'failed'
        item.message = `额度查询失败：${cleanError(error)}`
        failed += 1
      }
    }
    saveTempCdkState()
    setStatus(`KSCAN CDK 额度查询完成：成功 ${ok}，失败 ${failed}。`, failed > 0)
  } finally {
    tempCdkQuotaBusy.value = false
  }
}

function saveTempCdkState() {
  localStorage.setItem(TEMP_CDK_STATE_STORAGE_KEY, JSON.stringify({ cdks: tempCdks.value }))
}

function loadTempCdkState(legacyText = '') {
  try {
    const raw = JSON.parse(localStorage.getItem(TEMP_CDK_STATE_STORAGE_KEY) || '{}')
    tempCdks.value = Array.isArray(raw.cdks) ? raw.cdks.map(normalizeTempCdkItem).filter(Boolean) : []
  } catch {
    tempCdks.value = []
  }
  if (!tempCdks.value.length && legacyText) {
    tempCdkInput.value = legacyText
    addTempCdks({ silent: true })
  }
}

function saveTempForm(options = {}) {
  localStorage.setItem(TEMP_FORM_STORAGE_KEY, JSON.stringify({
    ...tempForm.value,
    cdk: tempCdks.value.map(item => item.value).join('\n'),
  }))
  saveTempCdkState()
  if (!options.silent && !inputLocked.value) setStatus('临时提链 CDK 已保存。')
}

function loadTempForm() {
  try {
    const data = JSON.parse(localStorage.getItem(TEMP_FORM_STORAGE_KEY) || '{}')
    if (data.concurrency !== undefined) tempForm.value.concurrency = Math.max(1, Math.min(20, Number(data.concurrency || 5)))
    loadTempCdkState(String(data.cdk || ''))
  } catch {
    loadTempCdkState('')
  }
}

function reserveTempCdksForAccounts(emails, jobId = '') {
  const targets = Array.from(emails || [])
  let assigned = 0
  const usedCdks = []
  for (const item of tempCdks.value.filter(tempCdkUsable)) {
    if (assigned >= targets.length) break
    const capacity = Math.min(tempCdkCapacity(item), targets.length - assigned)
    const accounts = targets.slice(assigned, assigned + capacity)
    assigned += capacity
    item.reservations = item.reservations && typeof item.reservations === 'object' ? item.reservations : {}
    item.reservations[jobId] = Number(item.reservations[jobId] || 0) + capacity
    item.reservedUses = Number(item.reservedUses || 0) + capacity
    item.status = tempCdkCapacity(item) > 0 ? 'available' : 'reserved'
    item.accountEmail = `${item.reservedUses} 个账号`
    item.jobId = jobId
    item.message = `已分配 ${capacity} 个账号，剩余可追加 ${tempCdkCapacity(item)} 个。`
    for (let index = 0; index < capacity; index += 1) usedCdks.push(item.value)
  }
  saveTempCdkState()
  return usedCdks
}

function releaseReservedTempCdks(jobId = '', message = '任务未完成，CDK 已释放。') {
  for (const item of tempCdks.value) {
    const reservations = item.reservations && typeof item.reservations === 'object' ? item.reservations : {}
    const releaseCount = jobId ? Number(reservations[jobId] || 0) : Number(item.reservedUses || 0)
    if (releaseCount > 0 || (item.status === 'reserved' && (!jobId || item.jobId === jobId))) {
      if (jobId) delete reservations[jobId]
      else {
        item.reservations = {}
        for (const key of Object.keys(reservations)) delete reservations[key]
      }
      item.reservedUses = Math.max(0, Number(item.reservedUses || 0) - releaseCount)
      item.status = tempCdkCapacity(item) > 0 ? 'available' : (item.reservedUses > 0 ? 'reserved' : 'available')
      item.jobId = Object.keys(reservations)[0] || ''
      item.accountEmail = item.reservedUses > 0 ? `${item.reservedUses} 个账号` : ''
      item.cooldownUntilMs = 0
      item.message = message
    }
  }
  saveTempCdkState()
}

function findTempCdkByValue(value) {
  const key = String(value || '').trim().toLowerCase()
  return key ? (tempCdks.value.find(item => item.value.toLowerCase() === key) || null) : null
}

function tempCdkAlreadyUsedError(error) {
  const text = String(error?.error || error?.message || error || '').toLowerCase()
  return Boolean(error?.cdk_used) || text.includes('cdk') && (text.includes('used') || text.includes('已使用'))
}

function applyTempCdkResult(result, jobId = '') {
  const successes = Array.isArray(result?.successes) ? result.successes : []
  const errors = Array.isArray(result?.errors) ? result.errors : []
  const successCountByCdk = new Map()
  const errorCountByCdk = new Map()
  for (const success of successes) {
    const key = String(success?.cdk || '').trim().toLowerCase()
    if (key) successCountByCdk.set(key, (successCountByCdk.get(key) || 0) + 1)
  }
  for (const error of errors) {
    const key = String(error?.cdk || '').trim().toLowerCase()
    if (key) errorCountByCdk.set(key, (errorCountByCdk.get(key) || 0) + 1)
  }
  for (const [key, count] of successCountByCdk.entries()) {
    const item = findTempCdkByValue(key)
    if (!item) continue
    const remaining = Number(item.remainingUses)
    item.remainingUses = Number.isFinite(remaining) ? Math.max(0, remaining - count) : 0
    item.usedUses = Number(item.usedUses || 0) + count
    item.reservations = item.reservations && typeof item.reservations === 'object' ? item.reservations : {}
    const reservedForJob = Number(item.reservations[jobId] || 0)
    if (reservedForJob > 0) {
      item.reservations[jobId] = Math.max(0, reservedForJob - count)
      if (item.reservations[jobId] <= 0) delete item.reservations[jobId]
    }
    item.reservedUses = Math.max(0, Number(item.reservedUses || 0) - count)
    item.status = item.remainingUses > 0 ? (tempCdkCapacity(item) > 0 ? 'available' : 'reserved') : 'used'
    item.jobId = jobId || item.jobId
    item.message = item.status === 'used' ? '临时提链成功，CDK 额度已用完。' : `临时提链成功 ${count} 个，剩余额度 ${item.remainingUses}。`
  }
  for (const error of errors) {
    const item = findTempCdkByValue(error?.cdk)
    if (!item) continue
    if (tempCdkAlreadyUsedError(error)) {
      item.status = 'used'
      item.message = '临时服务返回 CDK 已使用，已标记为已使用。'
      continue
    }
    if (item.status === 'used') continue
    item.reservations = item.reservations && typeof item.reservations === 'object' ? item.reservations : {}
    const key = String(error?.cdk || '').trim().toLowerCase()
    const failedCount = errorCountByCdk.get(key) || 1
    const reservedForJob = Number(item.reservations[jobId] || 0)
    if (reservedForJob > 0) delete item.reservations[jobId]
    item.reservedUses = Math.max(0, Number(item.reservedUses || 0) - (reservedForJob || failedCount))
    item.status = tempCdkCapacity(item) > 0 ? 'available' : (item.reservedUses > 0 ? 'reserved' : 'available')
    item.jobId = Object.keys(item.reservations)[0] || ''
    item.accountEmail = item.reservedUses > 0 ? `${item.reservedUses} 个账号` : ''
    item.cooldownUntilMs = 0
    item.message = `提链失败 ${failedCount} 个，CDK 剩余额度已释放：${cleanError(error?.error || error)}`
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

function isJobNotFound(error) {
  return Number(error?.status || 0) === 404 && String(error?.message || '').toLowerCase().includes('job not found')
}

function saveActiveJobSnapshot(job = currentJob.value) {
  const ids = activeJobIds.value.length ? activeJobIds.value : [String(job?.id || activeJobId.value || '').trim()].filter(Boolean)
  if (!ids.length) return
  const mode = job?.temp ? 'tempExtract' : 'extract'
  localStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({
    jobId: ids[0],
    jobIds: ids,
    accountCount: Number(job?.total || 0),
    concurrency: Number(job?.concurrency || (mode === 'tempExtract' ? tempForm.value.concurrency : form.value.concurrency) || 1),
    status: String(job?.status || activeJobStatus.value || ''),
    mode,
    startedAt: Date.now(),
  }))
}

function clearActiveJob({ removeStored = true } = {}) {
  stopPolling()
  activeJobId.value = ''
  activeJobIds.value = []
  activeJobStatus.value = ''
  currentJob.value = null
  notifiedSuccessKeys.value = new Set()
  cancelling.value = false
  starting.value = false
  if (removeStored) localStorage.removeItem(JOB_STORAGE_KEY)
}

function rememberFailedEmails(result) {
  const errors = Array.isArray(result?.errors) ? result.errors : []
  const seen = new Set()
  const emails = []
  for (const item of errors) {
    const email = String(item?.email || '').trim()
    if (!email) continue
    if (item?.cleanup) continue
    const key = email.toLowerCase()
    if (seen.has(key)) continue
    seen.add(key)
    emails.push(email)
  }
  lastFailedEmails.value = emails
}

function successNotificationKey(item, index) {
  const email = String(item?.email || item?.account_email || '').trim().toLowerCase()
  const link = kakaoLinkUrl(item?.link || item)
  const id = String(item?.id || item?.link?.id || '').trim()
  return email || link || id || `success-${index}`
}

function notifyNewSuccesses(result) {
  const successes = Array.isArray(result?.successes) ? result.successes : []
  if (!successes.length) return
  const seen = new Set(notifiedSuccessKeys.value)
  let delay = 0
  let changed = false
  successes.forEach((item, index) => {
    const key = successNotificationKey(item, index)
    if (seen.has(key)) return
    seen.add(key)
    changed = true
    window.setTimeout(() => {
      playNotificationSound(LINK_SUCCESS_SOUND_URL, form.value.notificationSoundEnabled)
    }, delay)
    delay += 450
  })
  if (changed) notifiedSuccessKeys.value = seen
}

function ttlText(value) {
  const seconds = Number(value || 0)
  if (!Number.isFinite(seconds) || seconds <= 0) return '-'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return hours > 0 ? `${hours}h ${minutes}m` : `${minutes}m`
}

function accountSelectable(account) {
  return accountStatus(account) !== 'paid' && account?.kakao_selectable !== false
}

function accountJobStatus(account) {
  const email = String(account?.email || '')
  const statuses = currentJob.value?.account_statuses || {}
  return statuses[email] || statuses[email.toLowerCase()] || null
}

function accountStatus(account) {
  return accountJobStatus(account)?.status || account?.kakao_status || 'pending'
}

function accountStatusText(account) {
  const status = accountStatus(account)
  if (status === 'paid') return '已支付'
  if (status === 'running') {
    const jobStatus = accountJobStatus(account) || {}
    const code = String(jobStatus.external_code || jobStatus.external_status || '').trim()
    return code ? `提链中 · ${code}` : '提链中'
  }
  if (status === 'success') return '已提链'
  if (status === 'failed') return '提链失败'
  return '未提链'
}

function accountStatusError(account) {
  const jobStatus = accountJobStatus(account) || {}
  return [jobStatus.external_step, jobStatus.external_message, jobStatus.error, account?.kakao_error].filter(Boolean).join(' · ')
}

function accountStatusClass(account) {
  const status = accountStatus(account)
  if (status === 'paid') return 'border-violet-500/30 bg-violet-500/10 text-violet-300'
  if (status === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (status === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (status === 'failed') return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-gray-700 bg-gray-900 text-gray-400'
}

function toggleAccount(email) {
  const account = accounts.value.find(item => item.email === email)
  if (!account || !accountSelectable(account)) return
  const next = new Set(selectedAccounts.value)
  next.has(email) ? next.delete(email) : next.add(email)
  selectedAccounts.value = next
}

function selectAllFiltered() {
  selectedAccounts.value = new Set(filteredAccounts.value.filter(accountSelectable).map(item => item.email))
}

function clearSelectedAccounts() {
  selectedAccounts.value = new Set()
}

function showMoreAccounts() {
  accountVisibleCount.value = Math.min(filteredAccounts.value.length, accountVisibleCount.value + 100)
}

function toggleLink(id) {
  const next = new Set(selectedLinkIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedLinkIds.value = next
}

function kakaoLinkUrl(link) {
  return String(link?.provider_redirect_url || link?.kakao_link || link?.stripe_redirect_url || link?.paymentUrl || link?.payment_url || link?.value || '').trim()
}

function timestampMs(value) {
  const raw = String(value ?? '').trim()
  if (!raw) return 0
  const numeric = Number(raw)
  if (Number.isFinite(numeric) && numeric > 0) return numeric > 1e12 ? numeric : numeric * 1000
  const parsed = Date.parse(raw.includes('T') ? raw : raw.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : 0
}

function kakaoExpiresAtMs(link) {
  const explicit = timestampMs(link?.kakao_expires_at_ts ?? link?.kakaoExpiresAtTs ?? link?.kakao_expires_at ?? link?.kakaoExpiresAt)
  if (explicit) return explicit
  const created = timestampMs(link?.created_at_ts ?? link?.createdAtTs ?? link?.created_at ?? link?.createdAt)
  return created ? created + KAKAO_LINK_TTL_MS : 0
}

function kakaoRemainingMs(link) {
  const expiresAt = kakaoExpiresAtMs(link)
  return expiresAt ? expiresAt - nowMs.value : 0
}

function kakaoLinkExpired(link) {
  const expiresAt = kakaoExpiresAtMs(link)
  return Boolean(expiresAt && expiresAt <= nowMs.value)
}

function kakaoLinkActionable(link) {
  return Boolean(kakaoLinkUrl(link)) && !kakaoLinkExpired(link)
}

function kakaoExpiryText(link) {
  if (!kakaoLinkUrl(link)) return '-'
  const expiresAt = kakaoExpiresAtMs(link)
  if (!expiresAt || expiresAt <= nowMs.value) return '链接失效'
  const seconds = Math.max(0, Math.ceil((expiresAt - nowMs.value) / 1000))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return minutes ? `剩余 ${minutes}:${String(rest).padStart(2, '0')}` : `剩余 ${rest}s`
}

function kakaoExpiryClass(link) {
  if (!kakaoLinkUrl(link)) return 'border-gray-700 bg-gray-900 text-gray-400'
  if (kakaoLinkExpired(link)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (kakaoRemainingMs(link) <= 60 * 1000) return 'border-yellow-400/30 bg-yellow-400/10 text-yellow-200'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
}

function scrollLogsToBottom() {
  if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
}

async function refreshAccounts() {
  const accountData = await api.getKakaoPayAccounts()
  accounts.value = Array.isArray(accountData.accounts) ? accountData.accounts : []
  const selectable = new Set(accounts.value.filter(accountSelectable).map(item => item.email))
  selectedAccounts.value = new Set(selectedEmails.value.filter(email => selectable.has(email)))
}

async function refreshLinks() {
  const linkData = await api.getKakaoPayLinks()
  links.value = Array.isArray(linkData.links) ? linkData.links : []
  const existing = new Set(links.value.map(item => item.id))
  selectedLinkIds.value = new Set(Array.from(selectedLinkIds.value).filter(id => existing.has(id)))
}

async function reloadAll() {
  loading.value = true
  try {
    await Promise.all([refreshAccounts(), refreshLinks()])
    setStatus('账号和链接已刷新。')
  } catch (error) {
    setStatus(`刷新失败：${cleanError(error)}`, true)
  } finally {
    loading.value = false
  }
}

function validateStart(emails = selectedEmails.value) {
  if (!emails.length) {
    setStatus('请在账号池中选择至少一个账号。', true)
    return false
  }
  if (isTempExtract.value) {
    if (tempCdkInput.value.trim()) addTempCdks({ silent: true })
    tempForm.value.concurrency = Math.max(1, Math.min(20, Number(tempForm.value.concurrency || 5)))
    const availableCdks = tempCdkLines()
    if (!availableCdks.length) {
      setStatus('请填写 KSCAN 临时提链 CDK。', true)
      return false
    }
    if (availableCdks.length < emails.length) {
      setStatus(`可用 KSCAN CDK 额度不足：已选 ${emails.length} 个账号，但当前额度只能提交 ${availableCdks.length} 个账号。`, true)
      return false
    }
    return true
  }
  form.value.concurrency = Math.max(1, Math.min(20, Number(form.value.concurrency || 1)))
  form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
  form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  if (!String(form.value.proxies || '').trim()) {
    setStatus('请填写 KR 代理。', true)
    return false
  }
  return true
}

async function startWithEmails(emails, actionText = '提取') {
  const accountEmails = Array.from(new Set((emails || []).map(email => String(email || '').trim()).filter(Boolean)))
  if (!validateStart(accountEmails)) return
  const tempMode = isTempExtract.value
  const appendMode = jobRunning.value
  const concurrency = tempMode ? tempForm.value.concurrency : form.value.concurrency
  const tempCdksForRun = tempMode ? tempCdkLines().slice(0, accountEmails.length) : []
  starting.value = true
  statusError.value = false
  saveForm()
  saveTempForm({ silent: true })
  try {
    const data = tempMode
      ? await api.startKakaoPayTempBatch({
          accountEmails,
          cdk: tempCdksForRun.join('\n'),
          cdks: tempCdksForRun,
          concurrency,
        })
      : await api.startKakaoPayBatch({
          accountEmails,
          proxies: form.value.proxies,
          concurrency,
          maxAttempts: form.value.maxAttempts,
          proxyPreflightAttempts: form.value.proxyPreflightAttempts,
          region: 'KR',
        })
    const newJobId = data.job_id || ''
    if (!newJobId) throw new Error('后端没有返回任务 ID')
    const nextIds = activeJobIds.value.length ? [...activeJobIds.value] : [activeJobId.value].filter(Boolean)
    if (!nextIds.includes(newJobId)) nextIds.push(newJobId)
    activeJobIds.value = nextIds
    activeJobId.value = nextIds[0] || newJobId
    if (tempMode) reserveTempCdksForAccounts(accountEmails, newJobId)
    activeJobStatus.value = 'queued'
    if (!appendMode) {
      currentResult.value = null
      notifiedSuccessKeys.value = new Set()
      logs.value = []
    }
    currentJob.value = { id: activeJobIds.value.join(','), status: 'queued', total: (Number(currentJob.value?.total || 0) + accountEmails.length), completed: Number(currentJob.value?.completed || 0), concurrency, running_count: Number(currentJob.value?.running_count || 0), temp: tempMode }
    saveActiveJobSnapshot(currentJob.value)
    setStatus(`${appendMode ? '追加任务' : '任务'}已提交，正在为 ${accountEmails.length} 个账号${actionText} Kakao${tempMode ? ' 临时' : ''}，并发 ${concurrency || 1}。`)
    startPolling()
  } catch (error) {
    if (tempMode) releaseReservedTempCdks('', '任务启动失败，CDK 已释放。')
    setStatus(`启动失败：${cleanError(error)}`, true)
  } finally {
    starting.value = false
  }
}

async function start() {
  await startWithEmails(selectedEmails.value, '提取')
}

async function pollJob() {
  const ids = activeJobIds.value.length ? [...activeJobIds.value] : [activeJobId.value].filter(Boolean)
  if (!ids.length) return
  try {
    const jobs = []
    const missingIds = new Set()
    for (const id of ids) {
      try {
        jobs.push(await api.getKakaoPayJob(id))
      } catch (error) {
        if (isJobNotFound(error)) missingIds.add(id)
        else throw error
      }
    }
    if (componentUnmounted) return
    if (!jobs.length && missingIds.size) {
      clearActiveJob()
      await Promise.all([refreshAccounts(), refreshLinks()])
      setStatus('任务已不存在或后端已重启，已停止轮询并刷新账号/链接。', true)
      return
    }
    const activeJobs = jobs.filter(job => !TERMINAL_STATUSES.has(String(job.status || '')))
    activeJobIds.value = activeJobs.map(job => String(job.id || '')).filter(Boolean)
    activeJobId.value = activeJobIds.value[0] || ''
    const successes = []
    const errors = []
    const skipped = []
    const accountStatuses = {}
    const mergedLogs = []
    for (const job of jobs) {
      const jid = String(job.id || '').trim()
      const result = job.result || {}
      if (job.temp && result && TERMINAL_STATUSES.has(String(job.status || ''))) applyTempCdkResult(result, jid)
      for (const item of Array.isArray(result.successes) ? result.successes : []) successes.push(item)
      for (const item of Array.isArray(result.errors) ? result.errors : []) errors.push(item)
      for (const item of Array.isArray(result.skipped) ? result.skipped : []) skipped.push(item)
      Object.assign(accountStatuses, job.account_statuses || {})
      for (const line of Array.isArray(job.logs) ? job.logs : []) mergedLogs.push(ids.length > 1 ? `[${jid.slice(0, 8)}] ${line}` : line)
    }
    const total = jobs.reduce((sum, job) => sum + Number(job.total || 0), 0)
    const completed = jobs.reduce((sum, job) => sum + Number(job.completed || 0), 0)
    const running = jobs.reduce((sum, job) => sum + Number(job.running_count || 0), 0)
    const aggregateStatus = activeJobs.length ? 'running' : (jobs.some(job => String(job.status || '') === 'error') ? 'error' : (jobs.some(job => String(job.status || '') === 'cancelled') ? 'cancelled' : 'success'))
    currentResult.value = { batch: true, successes, errors, skipped }
    currentJob.value = { id: ids.join(','), status: aggregateStatus, total, completed, running_count: running, concurrency: jobs.reduce((sum, job) => sum + Number(job.concurrency || 0), 0), account_statuses: accountStatuses, temp: jobs.some(job => job.temp) }
    activeJobStatus.value = aggregateStatus
    logs.value = mergedLogs.slice(-500)
    saveActiveJobSnapshot(currentJob.value)
    notifyNewSuccesses(currentResult.value)
    setStatus(`状态：${activeJobStatus.value || '-'}，任务 ${activeJobs.length}/${jobs.length} 运行中，完成 ${completed}/${total}，运行中 ${running}`)
    if (!activeJobs.length) {
      stopPolling()
      rememberFailedEmails(currentResult.value)
      for (const job of jobs) {
        if (job.temp) releaseReservedTempCdks(String(job.id || ''), '任务已结束，未使用 CDK 已释放。')
      }
      activeJobIds.value = []
      activeJobId.value = ''
      localStorage.removeItem(JOB_STORAGE_KEY)
      if (activeJobStatus.value === 'success') {
        setStatus('提链任务已完成，链接已写入管理表。')
      }
      await Promise.all([refreshAccounts(), refreshLinks()])
    }
  } catch (error) {
    setStatus(`轮询失败：${cleanError(error)}`, true)
  }
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

function startPolling() {
  stopPolling()
  pollJob()
  timer = window.setInterval(pollJob, 3000)
}

function stopPolling() {
  if (timer) window.clearInterval(timer)
  timer = null
}

async function cancelJob() {
  const ids = activeJobIds.value.length ? [...activeJobIds.value] : [activeJobId.value].filter(Boolean)
  if (!ids.length) return
  cancelling.value = true
  try {
    await Promise.all(ids.map(id => api.cancelKakaoPayJob(id).catch(error => {
      if (!isJobNotFound(error)) throw error
      return null
    })))
    await pollJob()
  } catch (error) {
    if (isJobNotFound(error)) {
      clearActiveJob()
      await Promise.all([refreshAccounts(), refreshLinks()])
      setStatus('任务已不存在或后端已重启，已清理当前任务状态。', true)
      return
    }
    setStatus(`取消失败：${cleanError(error)}`, true)
  } finally {
    cancelling.value = false
  }
}

function saveProxy() {
  saveForm()
  setStatus('Kakao 代理配置已保存到本地浏览器。')
}

async function deleteKakaoAccount(email) {
  const target = String(email || '').trim()
  if (!target) return
  if (!window.confirm(`确认从 Kakao 账号池和仪表盘账号池中删除 ${target}？`)) return
  const nextDeleting = new Set(deletingKakaoAccounts.value)
  nextDeleting.add(target)
  deletingKakaoAccounts.value = nextDeleting
  try {
    const data = await api.deleteKakaoPayAccount(target)
    const next = new Set(selectedAccounts.value)
    next.delete(target)
    selectedAccounts.value = next
    const kakao = data.kakao_pay || data.kakao || {}
    setStatus(`已删除账号 ${target}：仪表盘账号 ${data.dashboard_account_deleted ? '已删除' : '未找到'}，认证 ${data.auth_session_deleted ? '已删除' : '未找到'}，Kakao 链接 ${kakao.links_deleted || 0} 条。`)
    await reloadAll()
  } catch (error) {
    setStatus(`删除账号失败：${cleanError(error)}`, true)
  } finally {
    const done = new Set(deletingKakaoAccounts.value)
    done.delete(target)
    deletingKakaoAccounts.value = done
  }
}

async function deleteSelectedKakaoAccounts() {
  const emails = selectedEmails.value.map(email => String(email || '').trim()).filter(Boolean)
  if (!emails.length) return
  if (!window.confirm(`确认批量删除选中的 ${emails.length} 个账号？这些账号会同时从 Kakao 账号池和仪表盘账号池删除。`)) return
  deletingKakaoAccounts.value = new Set(emails)
  try {
    const data = await api.deleteKakaoPayAccounts(emails)
    const deleted = new Set((data.results || []).map(item => String(item.email || '').trim()).filter(Boolean))
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => !deleted.has(email)))
    const linkCount = (data.results || []).reduce((sum, item) => sum + Number((item.kakao_pay || item.kakao || {}).links_deleted || 0), 0)
    setStatus(`已批量删除 ${data.deleted || deleted.size} 个账号，清理 Kakao 链接 ${linkCount} 条。`)
    await reloadAll()
  } catch (error) {
    setStatus(`批量删除账号失败：${cleanError(error)}`, true)
  } finally {
    deletingKakaoAccounts.value = new Set()
  }
}

async function copy(value) {
  const text = String(value || '').trim()
  if (!text) return
  await navigator.clipboard.writeText(text)
  setStatus('已复制到剪贴板。')
}

async function deleteSelectedLinks() {
  const ids = Array.from(selectedLinkIds.value)
  if (!ids.length) return
  const data = await api.deleteKakaoPayLinks(ids)
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已删除 ${data.deleted || ids.length} 条链接。`)
}

async function clearLinks() {
  if (!links.value.length || !window.confirm('确认清空所有 Kakao 链接？')) return
  const data = await api.clearKakaoPayLinks()
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已清空 ${data.deleted || 0} 条链接。`)
}

function exportLinks() {
  const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `kakao-pay-links-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

function textLines(value) {
  return String(value || '').split(/\r?\n/).map(item => item.trim()).filter(Boolean)
}

function maskExternalSecret(value) {
  const text = String(value || '').trim()
  if (text.length <= 12) return text ? `${text.slice(0, 2)}***` : ''
  return `${text.slice(0, 6)}…${text.slice(-4)}`
}

function orderStatusPayload(data) {
  const payload = data?.data || data || {}
  return payload.order || payload
}

function externalOrderStatusText(status) {
  const key = String(status || '').toLowerCase()
  return {
    pending: '等待分配',
    queued: '排队中',
    waiting: '等待中',
    awaiting_scanner: '等待扫码',
    waiting_scanner: '等待扫码',
    extracting: '提链中',
    awaiting_worker: '等待扫码',
    claimed: '已领取',
    assigned: '已分配',
    scanner_assigned: '扫码员已接单',
    checking: '校验中',
    completed: '已完成',
    failed: '失败',
    error: '异常',
    rejected: '已拒绝',
    expired: '已过期',
    timeout: '已超时',
    qr_timeout: '二维码超时',
    processing: '处理中',
    success: '成功',
    succeeded: '成功',
    paid: '已支付',
    cancelled: '已取消',
    canceled: '已取消',
    resubmitted: '已重投',
  }[key] || status || '未知'
}

function externalOrderStatusClass(status) {
  const key = String(status || '').toLowerCase()
  if (['completed', 'success', 'succeeded', 'paid'].includes(key)) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (['failed', 'error', 'rejected', 'cancelled', 'canceled'].includes(key)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (['expired', 'timeout', 'qr_timeout'].includes(key)) return 'border-yellow-400/30 bg-yellow-400/10 text-yellow-200'
  if (['claimed', 'assigned', 'scanner_assigned', 'processing', 'checking', 'extracting', 'pending', 'queued', 'waiting', 'awaiting_scanner', 'waiting_scanner', 'awaiting_worker', 'resubmitted'].includes(key)) return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  return 'border-yellow-400/30 bg-yellow-400/10 text-yellow-200'
}

function externalExpiryText(value) {
  const ms = timestampMs(value)
  if (!ms) return '-'
  if (ms <= nowMs.value) return '已过期'
  const seconds = Math.ceil((ms - nowMs.value) / 1000)
  const minutes = Math.floor(seconds / 60)
  return minutes ? `${minutes}:${String(seconds % 60).padStart(2, '0')}` : `${seconds}s`
}

function compactJson(value) {
  if (!value || typeof value !== 'object') return '-'
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function makeKkPaymentId(prefix = 'kk-pay') {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function normalizeKkPaymentUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

function kakaoLinkImportable(link) {
  return Boolean(kakaoLinkUrl(link)) && !kakaoLinkExpired(link)
}

function kkPaymentLinkInvalid(item) {
  return !normalizeKkPaymentUrl(item?.paymentUrl || item?.value) || kakaoLinkExpired(item)
}

function kkPaymentTaskFilterStatus(item) {
  const status = String(item?.status || 'pending').toLowerCase()
  if (['running', 'success', 'failed', 'stopped', 'needs_action'].includes(status)) return status
  return 'pending'
}

function kakaoPaymentLinkSummary(item) {
  if (!normalizeKkPaymentUrl(item?.paymentUrl || item?.value)) return '无链接'
  return kakaoLinkExpired(item) ? '链接已失效' : 'NicePay 链接已保存'
}

function kkPaymentLinkStatusText(status) {
  return ({ pending: '待提交', imported: '待提交', running: '运行中', success: '成功', failed: '失败', stopped: '已停止', needs_action: '需处理' })[String(status || '')] || '待提交'
}

function kkPaymentStatusClass(status) {
  const text = String(status || 'pending')
  if (text === 'running') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (text === 'success') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (['failed', 'stopped', 'needs_action'].includes(text)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  return 'border-slate-700 bg-slate-900 text-slate-300'
}

function kkPaymentCdkStatusText(status) {
  return ({ available: '可用', reserved: '已分配', used: '已使用', failed: '失效' })[String(status || '')] || '可用'
}

function kkPaymentNeedsRelink(item) {
  const status = String(item?.status || '').toLowerCase()
  return kkPaymentLinkInvalid(item) || ['failed', 'stopped', 'needs_action'].includes(status)
}

function kkPaymentCanCancel(item) {
  const status = String(item?.status || '').toLowerCase()
  return Boolean(item?.orderId) && ['running', 'pending', 'imported'].includes(status)
}

function kkPaymentCanResubmit(item) {
  const status = String(item?.status || '').toLowerCase()
  const message = String(item?.message || '').toLowerCase()
  return Boolean(item?.orderId) && ['failed', 'stopped', 'needs_action'].includes(status) && (
    message.includes('timeout')
    || message.includes('超时')
    || message.includes('过期')
    || message.includes('qr')
    || message.includes('二维码')
  )
}

function kkPaymentCdkStatusClass(status) {
  const text = String(status || 'available')
  if (text === 'available') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (text === 'reserved') return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  if (text === 'used') return 'border-gray-700 bg-gray-900 text-gray-400'
  return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
}

function kkPaymentCdkQuotaPayload(data) {
  const payload = data?.data || data?.cdk || data?.ticket || data || {}
  return payload && typeof payload === 'object' ? payload : {}
}

function kkPaymentCdkQuotaValues(payload) {
  const total = payload.totalCount ?? payload.total_count ?? payload.totalUses ?? payload.total_uses ?? payload.total ?? '-'
  const used = payload.usedCount ?? payload.used_count ?? payload.usedUses ?? payload.used_uses ?? payload.used ?? 0
  const frozen = payload.frozenCount ?? payload.frozen_count ?? payload.pendingCount ?? payload.pending_count ?? payload.pending_uses ?? payload.reservedUses ?? payload.reserved_uses ?? 0
  const available = payload.availableCount ?? payload.available_count ?? payload.availableUses ?? payload.available_uses ?? payload.remainingUses ?? payload.remaining_uses ?? payload.remaining
  const totalNumber = Number(total)
  const usedNumber = Number(used)
  const frozenNumber = Number(frozen)
  return {
    total,
    used,
    frozen,
    available: available ?? (Number.isFinite(totalNumber) && Number.isFinite(usedNumber) ? Math.max(0, totalNumber - usedNumber - (Number.isFinite(frozenNumber) ? frozenNumber : 0)) : '-'),
    productType: String(payload.productType || payload.product_type || '').trim(),
    status: String(payload.status || '').trim(),
  }
}

function kkPaymentCdkQuotaMessage(payload) {
  const quota = kkPaymentCdkQuotaValues(payload)
  return `额度：总 ${quota.total}，已用 ${quota.used}，冻结 ${quota.frozen}，剩余 ${quota.available}`
}

function kkPaymentCdkUsable(cdk) {
  if (!cdk || ['failed'].includes(String(cdk.status || 'available'))) return false
  const remaining = Number(cdk.remainingUses)
  const reserved = Number(cdk.reservedUses || 0)
  return !Number.isFinite(remaining) ? String(cdk.status || 'available') === 'available' : Math.max(0, remaining - reserved) > 0
}

function kkPaymentCdkCapacity(cdk) {
  if (!kkPaymentCdkUsable(cdk)) return 0
  const remaining = Number(cdk.remainingUses)
  const reserved = Number(cdk.reservedUses || 0)
  return Number.isFinite(remaining) ? Math.max(0, Math.floor(remaining - reserved)) : 1
}

function kkPaymentCdkDisplayStatus(cdk) {
  if (kkPaymentCdkUsable(cdk)) return Number(cdk?.reservedUses || 0) > 0 ? 'reserved' : 'available'
  return String(cdk?.status || 'available')
}

function normalizeKkPaymentItem(raw) {
  if (!raw || typeof raw !== 'object') return null
  const paymentUrl = normalizeKkPaymentUrl(raw.paymentUrl || raw.payment_url || raw.value || raw.link || raw.url || kakaoLinkUrl(raw))
  const linkId = String(raw.linkId || raw.link_id || raw.id || '').trim()
  const accountEmail = String(raw.accountEmail || raw.account_email || raw.account || '').trim()
  if (!paymentUrl && !raw.orderId && !raw.order_id) return null
  const orderId = String(raw.orderId || raw.order_id || raw.id || '').trim()
  const customerToken = String(raw.customerToken || raw.customer_token || raw.token || '').trim()
  const rawStatus = String(raw.status || (paymentUrl ? 'pending' : 'failed')).toLowerCase()
  const pausedByReload = rawStatus === 'running' && orderId && customerToken
  return {
    id: String(raw.queueId || raw.queue_id || raw.id || makeKkPaymentId('link')),
    linkId,
    accountEmail,
    paymentUrl,
    value: paymentUrl,
    cdk: String(raw.cdk || '').trim(),
    cdkId: String(raw.cdkId || raw.cdk_id || '').trim(),
    orderId,
    orderNo: String(raw.orderNo || raw.order_no || '').trim(),
    customerToken,
    status: pausedByReload ? 'needs_action' : rawStatus,
    message: pausedByReload ? '页面刷新导致轮询暂停，可点击“提交/查询”继续查询。' : String(raw.message || raw.error || raw.problemReason || raw.problem_reason || '').trim(),
    created_at: raw.created_at || raw.createdAt || '',
    created_at_ts: raw.created_at_ts || raw.createdAtTs || 0,
    kakao_expires_at_ts: raw.kakao_expires_at_ts || raw.kakaoExpiresAtTs || raw.kakaoExpiresAt || 0,
  }
}

function normalizeKkPaymentCdk(raw) {
  const value = String(typeof raw === 'string' ? raw : raw?.value || raw?.cdk || '').trim()
  if (!value) return null
  const status = String(typeof raw === 'object' ? raw.status || 'available' : 'available').toLowerCase()
  return {
    id: String((typeof raw === 'object' && raw.id) || makeKkPaymentId('cdk')),
    value,
    status: ['available', 'reserved', 'used', 'failed'].includes(status) ? status : 'available',
    message: String((typeof raw === 'object' && (raw.message || raw.error)) || '').trim(),
    linkId: String((typeof raw === 'object' && (raw.linkId || raw.link_id)) || '').trim(),
    accountEmail: String((typeof raw === 'object' && (raw.accountEmail || raw.account_email)) || '').trim(),
    orderId: String((typeof raw === 'object' && (raw.orderId || raw.order_id)) || '').trim(),
    linkIds: Array.isArray(raw?.linkIds) ? raw.linkIds.map(item => String(item || '').trim()).filter(Boolean) : [],
    accountEmails: Array.isArray(raw?.accountEmails) ? raw.accountEmails.map(item => String(item || '').trim()).filter(Boolean) : [],
    totalUses: Number(typeof raw === 'object' ? raw.totalUses ?? raw.total_uses ?? raw.totalCount ?? raw.total_count ?? 0 : 0),
    usedUses: Number(typeof raw === 'object' ? raw.usedUses ?? raw.used_uses ?? raw.usedCount ?? raw.used_count ?? 0 : 0),
    frozenUses: Number(typeof raw === 'object' ? raw.frozenUses ?? raw.frozen_uses ?? raw.frozenCount ?? raw.frozen_count ?? 0 : 0),
    remainingUses: Number(typeof raw === 'object' ? raw.remainingUses ?? raw.remaining_uses ?? raw.availableCount ?? raw.available_count ?? 1 : 1),
    reservedUses: Number(typeof raw === 'object' ? raw.reservedUses ?? raw.reserved_uses ?? 0 : 0),
  }
}

function saveKkPaymentState() {
  localStorage.setItem(KK_PAYMENT_STATE_STORAGE_KEY, JSON.stringify({
    links: kkPaymentLinks.value,
    cdks: kkPaymentCdks.value,
    concurrency: kkPaymentConcurrency.value,
    paymentMethod: kkPaymentMethod.value,
  }))
}

function loadKkPaymentState() {
  try {
    const raw = JSON.parse(localStorage.getItem(KK_PAYMENT_STATE_STORAGE_KEY) || '{}')
    kkPaymentLinks.value = Array.isArray(raw.links) ? raw.links.map(normalizeKkPaymentItem).filter(Boolean) : []
    kkPaymentCdks.value = Array.isArray(raw.cdks) ? raw.cdks.map(normalizeKkPaymentCdk).filter(Boolean) : []
    kkPaymentConcurrency.value = Math.max(1, Math.min(20, Number(raw.concurrency || 5)))
    kkPaymentMethod.value = ['kakao_pay', 'naver_pay'].includes(raw.paymentMethod) ? raw.paymentMethod : 'kakao_pay'
    kkPaymentStatusText.value = kkPaymentLinks.value.length || kkPaymentCdks.value.length ? '已恢复上次 KK 支付页数据。' : '等待同步已提取 Kakao 链接并加入 KK 支付 CDK。'
  } catch {
    kkPaymentLinks.value = []
    kkPaymentCdks.value = []
    kkPaymentStatusText.value = '支付页缓存读取失败，已重置为空。'
  }
}

function addOrUpdateKkPaymentLink(raw) {
  const item = normalizeKkPaymentItem(raw)
  if (!item?.paymentUrl) return false
  const key = `${String(item.accountEmail || '').toLowerCase()}|${normalizeKkPaymentUrl(item.paymentUrl)}`
  const existing = kkPaymentLinks.value.find(row => `${String(row.accountEmail || '').toLowerCase()}|${normalizeKkPaymentUrl(row.paymentUrl)}` === key)
  if (existing) {
    if (!['running', 'success'].includes(existing.status)) Object.assign(existing, item, { id: existing.id, cdk: existing.cdk, cdkId: existing.cdkId, orderId: existing.orderId, customerToken: existing.customerToken, status: existing.status })
    return false
  }
  kkPaymentLinks.value = [...kkPaymentLinks.value, item]
  return true
}

function addKkPaymentCdks() {
  const existing = new Set(kkPaymentCdks.value.map(item => item.value.toLowerCase()))
  const items = []
  for (const line of textLines(kkPaymentCdkInput.value).flatMap(item => item.split(',')).map(item => item.trim()).filter(Boolean)) {
    const key = line.toLowerCase()
    if (existing.has(key)) continue
    existing.add(key)
    items.push({ id: makeKkPaymentId('cdk'), value: line, status: 'available', message: '', linkId: '', accountEmail: '', orderId: '', totalUses: 0, usedUses: 0, frozenUses: 0, remainingUses: 1, reservedUses: 0 })
  }
  if (items.length) kkPaymentCdks.value = [...kkPaymentCdks.value, ...items]
  kkPaymentCdkInput.value = ''
  kkPaymentStatusText.value = items.length ? `已加入 ${items.length} 枚 KK 支付 CDK。` : '没有新增 CDK，可能为空或重复。'
  saveKkPaymentState()
}

async function queryKkPaymentCdkQuota() {
  if (kkPaymentCdkInput.value.trim()) addKkPaymentCdks()
  const targets = kkPaymentCdks.value.filter(item => String(item.value || '').trim())
  if (!targets.length) {
    kkPaymentStatusText.value = '请先加入要查询额度的 KK 支付 CDK。'
    return
  }
  kkPaymentCdkQuotaBusy.value = true
  let ok = 0
  let failed = 0
  try {
    for (const cdk of targets) {
      try {
        cdk.message = '正在查询额度...'
        const data = await api.getKakaoPayKkPaymentCdkStatus(cdk.value)
        const payload = kkPaymentCdkQuotaPayload(data)
        const quota = kkPaymentCdkQuotaValues(payload)
        cdk.totalUses = Number(quota.total === '-' ? 0 : quota.total)
        cdk.usedUses = Number(quota.used === '-' ? 0 : quota.used)
        cdk.frozenUses = Number(quota.frozen === '-' ? 0 : quota.frozen)
        cdk.remainingUses = Number(quota.available === '-' ? Math.max(0, cdk.totalUses - cdk.usedUses - cdk.frozenUses) : quota.available)
        cdk.reservedUses = 0
        cdk.status = Number(cdk.remainingUses) > 0 ? 'available' : 'used'
        cdk.message = kkPaymentCdkQuotaMessage(payload)
        ok += 1
      } catch (error) {
        cdk.status = 'failed'
        cdk.message = `额度查询失败：${cleanError(error)}`
        failed += 1
      }
    }
    kkPaymentStatusText.value = `KK 支付 CDK 额度查询完成：成功 ${ok}，失败 ${failed}。`
    saveKkPaymentState()
  } finally {
    kkPaymentCdkQuotaBusy.value = false
  }
}

function syncKkPaymentLinks(options = {}) {
  let added = 0
  let updated = 0
  let skipped = 0
  for (const link of links.value) {
    if (!kakaoLinkImportable(link)) {
      skipped += 1
      continue
    }
    const seed = {
      queueId: makeKkPaymentId('link'),
      linkId: link.id,
      accountEmail: link.account_email || link.accountEmail || '',
      paymentUrl: kakaoLinkUrl(link),
      status: 'pending',
      created_at: link.created_at,
      created_at_ts: link.created_at_ts,
      kakao_expires_at_ts: kakaoExpiresAtMs(link),
    }
    const before = kkPaymentLinks.value.length
    const created = addOrUpdateKkPaymentLink(seed)
    if (created) added += 1
    else if (kkPaymentLinks.value.length === before) updated += 1
  }
  if (!options.silent) {
    kkPaymentStatusText.value = added || updated
      ? `已同步已提取有效 Kakao 链接：新增 ${added}，更新 ${updated}，跳过失效 ${skipped}。`
      : `没有可同步的有效 Kakao 链接${skipped ? `，已跳过失效 ${skipped} 条` : ''}。`
  }
  saveKkPaymentState()
  return { added, updated, skipped }
}

async function importKkPaymentLinks(options = {}) {
  await refreshLinks()
  return syncKkPaymentLinks(options)
}

function releaseKkPaymentCdkForLink(id, message = '') {
  for (const cdk of kkPaymentCdks.value) {
    if (cdk.linkId === id || (Array.isArray(cdk.linkIds) && cdk.linkIds.includes(id))) {
      cdk.reservedUses = Math.max(0, Number(cdk.reservedUses || 0) - 1)
      cdk.linkIds = Array.isArray(cdk.linkIds) ? cdk.linkIds.filter(item => item !== id) : []
      cdk.accountEmails = Array.isArray(cdk.accountEmails) ? cdk.accountEmails : []
      cdk.linkId = cdk.linkIds[0] || ''
      cdk.accountEmail = cdk.accountEmails.length ? `${cdk.accountEmails.length} 个账号` : ''
      if (kkPaymentCdkUsable(cdk)) cdk.status = 'available'
      cdk.message = message
    }
  }
}

function removeKkPaymentLink(id) {
  releaseKkPaymentCdkForLink(id, '关联账号已移除，CDK 已释放。')
  kkPaymentLinks.value = kkPaymentLinks.value.filter(item => item.id !== id)
  kkPaymentStatusText.value = '已移除支付账号。'
  saveKkPaymentState()
}

function clearKkPaymentLinks() {
  for (const item of kkPaymentLinks.value) releaseKkPaymentCdkForLink(item.id, '账号池已清空，CDK 已释放。')
  kkPaymentLinks.value = []
  kkPaymentStatusText.value = '已清空支付账号池。'
  saveKkPaymentState()
}

function clearKkPaymentCdks() {
  for (const link of kkPaymentLinks.value) {
    if (link.cdkId && link.status !== 'success') {
      link.cdk = ''
      link.cdkId = ''
      if (link.status === 'running') link.status = 'pending'
    }
  }
  kkPaymentCdks.value = []
  kkPaymentStatusText.value = '已清空 KK 支付 CDK 池。'
  saveKkPaymentState()
}

function clearInvalidKkPaymentLinks() {
  const before = kkPaymentLinks.value.length
  const invalidIds = new Set(kkPaymentLinks.value.filter(kkPaymentLinkInvalid).map(item => item.id))
  for (const id of invalidIds) releaseKkPaymentCdkForLink(id, '关联链接已失效并清理，CDK 已释放。')
  kkPaymentLinks.value = kkPaymentLinks.value.filter(item => !invalidIds.has(item.id))
  kkPaymentStatusText.value = invalidIds.size ? `已清理 ${before - kkPaymentLinks.value.length} 条失效账号链接。` : '没有可清理的失效链接。'
  saveKkPaymentState()
}

function clearFinishedKkPayments() {
  const beforeLinks = kkPaymentLinks.value.length
  const beforeCdks = kkPaymentCdks.value.length
  const removableStatuses = ['success', 'failed', 'stopped', 'needs_action']
  const removableIds = new Set(kkPaymentLinks.value.filter(item => kkPaymentLinkInvalid(item) || removableStatuses.includes(item.status)).map(item => item.id))
  for (const id of removableIds) releaseKkPaymentCdkForLink(id, '关联任务已结束或失效，CDK 已释放。')
  kkPaymentLinks.value = kkPaymentLinks.value.filter(item => !removableIds.has(item.id))
  kkPaymentCdks.value = kkPaymentCdks.value.filter(item => !['used', 'failed'].includes(item.status))
  kkPaymentStatusText.value = `已清理 ${beforeLinks - kkPaymentLinks.value.length} 个账号、${beforeCdks - kkPaymentCdks.value.length} 枚 CDK。`
  saveKkPaymentState()
}

function kkPaymentTaskRunnable(item) {
  if (!item?.paymentUrl || kkPaymentLinkInvalid(item)) return false
  if (item.orderId && (item.customerToken || item.cdk)) return !['success', 'running'].includes(String(item.status || 'pending'))
  return KK_PAYMENT_RETRYABLE_STATUSES.has(String(item.status || 'pending')) && kkPaymentCdks.value.some(kkPaymentCdkUsable)
}

function kkPaymentUnavailableMessage() {
  if (!kkPaymentLinks.value.some(item => Boolean(item.paymentUrl) && !kkPaymentLinkInvalid(item))) return '没有可提交的已提取 Kakao 链接。'
  if (!kkPaymentCdks.value.some(kkPaymentCdkUsable)) return '没有可用 KK 支付 CDK。'
  return '没有可提交的支付任务。'
}

function nextKkPaymentPair(preferredLink = null) {
  const link = preferredLink && kkPaymentTaskRunnable(preferredLink) && !preferredLink.orderId
    ? preferredLink
    : kkPaymentLinks.value.find(item => kkPaymentTaskRunnable(item) && !item.orderId)
  const cdk = kkPaymentCdks.value.find(kkPaymentCdkUsable)
  if (!link || !cdk) return null
  link.orderId = ''
  link.customerToken = ''
  link.cdk = cdk.value
  link.cdkId = cdk.id
  cdk.reservedUses = Number(cdk.reservedUses || 0) + 1
  cdk.linkIds = [...(Array.isArray(cdk.linkIds) ? cdk.linkIds : []), link.id]
  cdk.accountEmails = [...(Array.isArray(cdk.accountEmails) ? cdk.accountEmails : []), link.accountEmail]
  cdk.linkId = cdk.linkIds[0] || link.id
  cdk.accountEmail = `${cdk.accountEmails.length} 个账号`
  cdk.status = kkPaymentCdkCapacity(cdk) > 0 ? 'available' : 'reserved'
  cdk.message = `已分配 ${cdk.reservedUses} 个账号，剩余可提交 ${kkPaymentCdkCapacity(cdk)} 个。`
  return { link, cdk }
}

function markKkPaymentCdkSubmitted(cdk, link) {
  if (!cdk) return
  cdk.reservedUses = Math.max(0, Number(cdk.reservedUses || 0) - 1)
  const remaining = Number(cdk.remainingUses)
  if (Number.isFinite(remaining)) cdk.remainingUses = Math.max(0, remaining - 1)
  cdk.usedUses = Number(cdk.usedUses || 0) + 1
  cdk.linkIds = Array.isArray(cdk.linkIds) ? cdk.linkIds.filter(id => id !== link.id) : []
  cdk.accountEmails = Array.isArray(cdk.accountEmails) ? cdk.accountEmails.filter(email => email !== link.accountEmail) : []
  cdk.linkId = cdk.linkIds[0] || ''
  cdk.accountEmail = cdk.accountEmails.length ? `${cdk.accountEmails.length} 个账号` : ''
  cdk.orderId = link.orderId
  cdk.status = kkPaymentCdkCapacity(cdk) > 0 ? 'available' : 'used'
  cdk.message = `已提交 1 个账号，本地剩余可提交 ${kkPaymentCdkCapacity(cdk)} 个；可点“查询额度”刷新真实余额。`
}

function kkCustomerOrderPayload(data) {
  const payload = data?.data || data || {}
  const order = payload.order || payload
  return { payload, order }
}

function kkOrderProblemReason(data, fallback = '') {
  const { payload, order } = kkCustomerOrderPayload(data)
  const error = payload.error || data?.error || {}
  const code = String(order.problemCode || order.problem_code || error.code || data?.code || '').trim()
  const rawReason = String(order.problemReason || order.problem_reason || order.reason || order.message || error.message || data?.message || fallback || '').trim()
  const details = error.details || payload.details || order.details || null
  const codeText = {
    account_not_eligible: '账号暂不符合支付条件',
    payment_link_invalid: '支付二维码无法打开或无法完成',
    payment_link_expired: '支付链接已过期',
    payment_link_non_zero: '支付链接金额不是 0 KRW',
    payment_link_rejected: '支付链接被上游拒绝',
    multiple: '存在多个失败原因',
    customer_cancelled: '客户已取消订单',
    scanner_timeout: '扫码员处理超时',
    qr_timeout: '二维码超时，可尝试重投订单',
  }[code]
  const parts = []
  if (codeText) parts.push(`${codeText}${code ? `（${code}）` : ''}`)
  else if (rawReason) parts.push(rawReason)
  else if (code) parts.push(code)
  if (rawReason && codeText && rawReason !== code) parts.push(rawReason)
  if (details) parts.push(compactJson(details))
  return parts.filter(Boolean).join('：') || fallback || '处理中'
}

function kkPaymentStatusFromOrderStatus(status) {
  const key = String(status || '').toLowerCase()
  if (['success', 'succeeded', 'paid', 'completed'].includes(key)) return 'success'
  if (['cancelled', 'canceled', 'stopped'].includes(key)) return 'stopped'
  if (['failed', 'error', 'rejected'].includes(key)) return 'failed'
  if (['expired', 'timeout', 'qr_timeout'].includes(key)) return 'needs_action'
  if (['pending', 'queued', 'waiting', 'awaiting_scanner', 'waiting_scanner', 'awaiting_worker', 'claimed', 'assigned', 'scanner_assigned', 'checking', 'processing', 'extracting', 'resubmitted'].includes(key)) return 'running'
  return key ? 'needs_action' : 'pending'
}

function kkOrderCdkSnapshot(data) {
  const { payload, order } = kkCustomerOrderPayload(data)
  return order?.cdk || payload?.cdk || data?.cdk || null
}

function applyKkPaymentCdkSnapshot(cdk, data, prefix = '已同步订单额度') {
  const snapshot = kkOrderCdkSnapshot(data)
  if (!cdk || !snapshot || typeof snapshot !== 'object') return false
  const quota = kkPaymentCdkQuotaValues(snapshot)
  cdk.totalUses = Number(quota.total === '-' ? cdk.totalUses || 0 : quota.total)
  cdk.usedUses = Number(quota.used === '-' ? cdk.usedUses || 0 : quota.used)
  cdk.frozenUses = Number(quota.frozen === '-' ? cdk.frozenUses || 0 : quota.frozen)
  cdk.remainingUses = Number(quota.available === '-' ? cdk.remainingUses || 0 : quota.available)
  cdk.status = Number(cdk.remainingUses) > 0 ? 'available' : 'used'
  cdk.message = `${prefix}：${kkPaymentCdkQuotaMessage(snapshot)}`
  return true
}

async function waitKkPaymentOrder(link) {
  for (;;) {
    if (componentUnmounted) return { status: 'paused', message: '页面刷新或切换导致轮询暂停，可重新进入后继续查询。' }
    const data = await api.getKakaoPayKkPaymentOrder(link.orderId, link.customerToken, link.cdk, link.accountEmail)
    const { payload, order } = kkCustomerOrderPayload(data)
    const status = String(order.status || payload.status || data.status || '').toLowerCase()
    link.message = kkOrderProblemReason(data, externalOrderStatusText(status))
    if (KK_PAYMENT_TERMINAL_STATUSES.has(status)) return { ...order, status, account_email: order.account_email || data.account_email || link.accountEmail }
    await new Promise(resolve => window.setTimeout(resolve, 2000))
  }
}

async function runKkPaymentTask(item) {
  if (!item || !kkPaymentTaskRunnable(item)) return
  const hasExistingOrder = Boolean(item.orderId && (item.customerToken || item.cdk))
  let pair = null
  let cdk = kkPaymentCdks.value.find(row => row.id === item.cdkId) || null
  if (!hasExistingOrder) {
    pair = nextKkPaymentPair(item)
    if (!pair) {
      const message = kkPaymentUnavailableMessage()
      item.status = 'pending'
      item.message = message
      kkPaymentStatusText.value = `任务失败：${message}`
      saveKkPaymentState()
      return
    }
    cdk = pair.cdk
  }
  kkPaymentRunningCount.value += 1
  item.status = 'running'
  item.message = hasExistingOrder ? '查询 KK 支付状态中...' : '提交 session_cookie/AT + Kakao 链接 + CDK 中...'
  try {
    if (!hasExistingOrder) {
      const submitted = await api.submitKakaoPayKkPayment({
        cdk: cdk.value,
        accountEmail: item.accountEmail,
        linkId: item.linkId,
        paymentUrl: item.paymentUrl,
        paymentMethod: kkPaymentMethod.value,
      })
      const { payload, order } = kkCustomerOrderPayload(submitted)
      item.orderId = String(order.id || order.order_id || order.orderId || '').trim()
      item.orderNo = String(order.orderNo || order.order_no || '').trim()
      item.customerToken = String(payload.customerToken || payload.customer_token || payload.token || '').trim()
      if (!item.orderId) throw new Error('KK 客户支付 API 未返回 order id')
      if (!applyKkPaymentCdkSnapshot(cdk, submitted, '订单创建后额度')) markKkPaymentCdkSubmitted(cdk, item)
    }
    const job = await waitKkPaymentOrder(item)
    if (['success', 'succeeded', 'paid', 'completed'].includes(job.status)) {
      item.status = 'success'
      item.message = kkOrderProblemReason(job, '支付成功，账号已标记 Plus / Kakao。')
      removeAccountFromKakaoPool(job.account_email || item.accountEmail)
      await Promise.all([refreshAccounts(), refreshLinks()])
    } else if (job.status === 'paused') {
      item.status = 'needs_action'
      item.message = job.message || '页面刷新或切换导致轮询暂停，可点击“提交/查询”继续查询。'
    } else {
      item.status = kkPaymentStatusFromOrderStatus(job.status)
      item.message = kkOrderProblemReason(job, `任务结束：${externalOrderStatusText(job.status)}`)
    }
    kkPaymentStatusText.value = item.status === 'success' ? `任务 ${item.orderId} 已成功。` : `任务 ${item.orderId || '-'} 状态：${kkPaymentLinkStatusText(item.status)}。`
  } catch (error) {
    const message = cleanError(error)
    item.status = 'needs_action'
    item.message = message
    if (cdk && (cdk.linkId === item.id || (Array.isArray(cdk.linkIds) && cdk.linkIds.includes(item.id)))) {
      releaseKkPaymentCdkForLink(item.id, `提交失败，已释放本地预留：${message}`)
    }
    kkPaymentStatusText.value = `任务失败：${message}`
  } finally {
    kkPaymentRunningCount.value = Math.max(0, kkPaymentRunningCount.value - 1)
    saveKkPaymentState()
  }
}

function removeAccountFromKakaoPool(email) {
  const target = String(email || '').trim().toLowerCase()
  if (!target) return
  accounts.value = accounts.value.filter(account => String(account.email || '').trim().toLowerCase() !== target)
  selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(item => String(item || '').trim().toLowerCase() !== target))
  kkPaymentLinks.value = kkPaymentLinks.value.filter(item => String(item.accountEmail || '').trim().toLowerCase() !== target || item.status === 'success')
}

async function reExtractKkPaymentLink(item) {
  const email = String(item?.accountEmail || '').trim()
  if (!email) {
    kkPaymentStatusText.value = '该支付账号缺少邮箱，无法重新提链。'
    return
  }
  activeKakaoTab.value = 'tempExtract'
  await refreshAccounts()
  selectedAccounts.value = new Set([email])
  item.status = 'needs_action'
  item.message = '已切换到临时提链页并选中账号，正在尝试重新提链。'
  setStatus(`已为 ${email} 切到临时提链页，默认使用 KSCAN 临时提链重新提链。`)
  await startWithEmails([email], '重新提链')
}

async function cancelKkPaymentOrder(item) {
  if (!item?.orderId) return
  item.message = '正在取消 KK 支付订单...'
  try {
    const data = await api.cancelKakaoPayKkPaymentOrder(item.orderId, item.customerToken, item.cdk)
    const { payload, order } = kkCustomerOrderPayload(data)
    const status = String(order.status || payload.status || 'cancelled').toLowerCase()
    item.status = kkPaymentStatusFromOrderStatus(status)
    item.message = kkOrderProblemReason(data, `订单${externalOrderStatusText(status)}。`)
    const cdk = kkPaymentCdks.value.find(row => row.id === item.cdkId || row.value === item.cdk)
    if (!applyKkPaymentCdkSnapshot(cdk, data, '取消后额度')) releaseKkPaymentCdkForLink(item.id, '订单已取消，本地预留已释放。')
    kkPaymentStatusText.value = `订单 ${item.orderId} 已取消/更新：${item.message}`
  } catch (error) {
    item.status = 'needs_action'
    item.message = `取消失败：${cleanError(error)}`
    kkPaymentStatusText.value = item.message
  } finally {
    saveKkPaymentState()
  }
}

async function resubmitKkPaymentOrder(item) {
  if (!item?.orderId) return
  item.message = '正在重投 KK 支付订单...'
  try {
    const data = await api.resubmitKakaoPayKkPaymentOrder(item.orderId, item.customerToken, item.cdk)
    const { payload, order } = kkCustomerOrderPayload(data)
    const status = String(order.status || payload.status || 'resubmitted').toLowerCase()
    item.status = kkPaymentStatusFromOrderStatus(status)
    item.message = kkOrderProblemReason(data, `订单${externalOrderStatusText(status)}，正在继续查询。`)
    const cdk = kkPaymentCdks.value.find(row => row.id === item.cdkId || row.value === item.cdk)
    applyKkPaymentCdkSnapshot(cdk, data, '重投后额度')
    kkPaymentStatusText.value = `订单 ${item.orderId} 已重投，继续查询。`
    item.status = 'needs_action'
    await runKkPaymentTask(item)
  } catch (error) {
    item.status = 'needs_action'
    item.message = `重投失败：${cleanError(error)}`
    kkPaymentStatusText.value = item.message
  } finally {
    saveKkPaymentState()
  }
}

async function runAllKkPayments() {
  await importKkPaymentLinks({ silent: true })
  if (!kkPaymentRunnableCount.value) {
    kkPaymentStatusText.value = kkPaymentUnavailableMessage()
    return
  }
  kkPaymentActiveRuns.value += 1
  kkPaymentBusy.value = true
  const concurrency = Math.max(1, Math.min(20, Number(kkPaymentConcurrency.value || 5), kkPaymentRunnableCount.value))
  kkPaymentStatusText.value = `${kkPaymentActiveRuns.value > 1 ? '追加' : '开始'}提交 KK 支付队列，新增 worker ${concurrency} 个。`
  const workers = Array.from({ length: concurrency }, async () => {
    for (;;) {
      const item = kkPaymentLinks.value.find(kkPaymentTaskRunnable)
      if (!item) return
      await runKkPaymentTask(item)
    }
  })
  await Promise.all(workers)
  kkPaymentActiveRuns.value = Math.max(0, kkPaymentActiveRuns.value - 1)
  kkPaymentBusy.value = kkPaymentActiveRuns.value > 0 || kkPaymentRunningCount.value > 0
  if (!kkPaymentBusy.value) {
    kkPaymentStatusText.value = `支付队列已结束：成功 ${kkPaymentLinks.value.filter(item => item.status === 'success').length}，需处理 ${kkPaymentLinks.value.filter(item => ['failed', 'stopped', 'needs_action'].includes(item.status)).length}。`
  }
}

function applyKkOrder(item, data) {
  const payload = data?.data || data || {}
  const order = payload.order || payload
  item.orderId = String(order.id || order.order_id || item.orderId || '').trim()
  item.orderNo = String(order.orderNo || order.order_no || item.orderNo || '').trim()
  item.status = String(order.status || item.status || '').trim()
  item.customerToken = String(payload.customerToken || payload.customer_token || item.customerToken || '').trim()
  item.pollUrl = String(payload.pollUrl || payload.poll_url || item.pollUrl || '').trim()
  item.mode = String(order.mode || item.mode || kkForm.value.mode)
  item.qualification = order.qualification || item.qualification || null
  item.payment = order.payment || item.payment || null
  item.subscription = order.subscription || item.subscription || null
  item.problemReason = kkOrderProblemReason(data, item.problemReason || '')
}

async function submitKkOrders() {
  const cdk = kkForm.value.cdk.trim()
  const tokens = textLines(kkForm.value.accessTokens)
  if (!cdk || !tokens.length) {
    kkStatusText.value = '请填写 KK CDK 和至少一个 AT。'
    return
  }
  if (kkForm.value.mode === 'READY_LINK' && !kkForm.value.paymentUrl.trim()) {
    kkStatusText.value = 'READY_LINK 模式需要填写 NicePay 链接。'
    return
  }
  kkBusy.value = true
  try {
    for (const token of tokens) {
      const item = { id: `kk-${Date.now()}-${Math.random()}`, status: 'PENDING', mode: kkForm.value.mode, orderId: '', orderNo: '', customerToken: '', problemReason: '' }
      kkOrders.value.unshift(item)
      try {
        const data = await api.createKakaoPayKkPaymentOrder({
          cdk,
          accessToken: token,
          paymentUrl: kkForm.value.mode === 'READY_LINK' ? kkForm.value.paymentUrl.trim() : '',
          paymentMethod: kkForm.value.paymentMethod,
          mode: kkForm.value.mode,
        })
        applyKkOrder(item, data)
      } catch (error) {
        item.status = 'failed'
        item.problemReason = cleanError(error)
      }
    }
    kkStatusText.value = `KK 客户支付 API 订单已提交：${tokens.length} 个。`
  } finally {
    kkBusy.value = false
  }
}

async function pollKkOrder(item) {
  if (!item?.orderId) return
  kkBusy.value = true
  try {
    const data = await api.getKakaoPayKkPaymentOrder(item.orderId, item.customerToken, kkForm.value.cdk.trim())
    applyKkOrder(item, data)
    kkStatusText.value = `订单 ${item.orderNo || item.orderId} 状态：${externalOrderStatusText(item.status)}。`
  } catch (error) {
    item.status = 'failed'
    item.problemReason = cleanError(error)
    kkStatusText.value = `查询失败：${item.problemReason}`
  } finally {
    kkBusy.value = false
  }
}

async function pollAllKkOrders() {
  for (const item of kkOrders.value.filter(item => item.orderId)) {
    await pollKkOrder(item)
  }
}

function clearKkOrders() {
  kkOrders.value = []
  kkStatusText.value = 'KK 支付订单已清空。'
}

async function restoreActiveJob() {
  try {
    const saved = JSON.parse(localStorage.getItem(JOB_STORAGE_KEY) || '{}')
    const jobIds = Array.isArray(saved?.jobIds)
      ? saved.jobIds.map(item => String(item || '').trim()).filter(Boolean)
      : [String(saved?.jobId || '').trim()].filter(Boolean)
    if (!jobIds.length) return
    activeJobIds.value = jobIds
    activeJobId.value = jobIds[0] || ''
    activeJobStatus.value = String(saved.status || 'queued')
    currentJob.value = {
      id: jobIds.join(','),
      status: activeJobStatus.value || 'queued',
      total: Number(saved.accountCount || 0),
      completed: 0,
      concurrency: Number(saved.concurrency || (saved.mode === 'tempExtract' ? tempForm.value.concurrency : form.value.concurrency) || 1),
      running_count: 0,
      temp: saved.mode === 'tempExtract',
    }
    setStatus('已恢复 Kakao 提链任务，正在重新同步后端进度。')
    await pollJob()
    if (!componentUnmounted && activeJobIds.value.length && !TERMINAL_STATUSES.has(activeJobStatus.value)) startPolling()
  } catch (error) {
    localStorage.removeItem(JOB_STORAGE_KEY)
    clearActiveJob({ removeStored: false })
    setStatus(`恢复任务失败：${cleanError(error)}`, true)
  }
}

onMounted(async () => {
  componentUnmounted = false
  nowMs.value = Date.now()
  expiryTimer = window.setInterval(() => {
    nowMs.value = Date.now()
    releaseExpiredTempCdkCooldowns()
  }, 1000)
  loadTempForm()
  loadKkPaymentState()
  releaseExpiredTempCdkCooldowns()
  await reloadAll()
  await restoreActiveJob()
})
onUnmounted(() => {
  componentUnmounted = true
  stopPolling()
  if (expiryTimer) window.clearInterval(expiryTimer)
  expiryTimer = null
})
</script>
