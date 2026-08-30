<template>
  <div class="space-y-5">
    <WorkflowWorkspace title="MoMo 提链" eyebrow="支付 / Vietnam" description="按配置、启动、进度和结果组织业务操作" :status-label="workflowStatusPresentation(busy ? 'running' : 'success').label" :status-tone="workflowStatusPresentation(busy ? 'running' : 'success').tone">
      <template #configuration>
        <WorkflowStage name="configuration" title="配置" description="确认账号、代理和运行参数" state="idle">
          <WorkflowStage name="launch" title="启动" description="提交后会保留当前任务状态" state="idle"><UiButton variant="primary">开始任务</UiButton></WorkflowStage>
        </WorkflowStage>
      </template>
      <template #progress><WorkflowStage name="progress" title="进度" description="实时状态与可恢复任务" state="idle"><UiStatusBadge label="等待操作" tone="neutral" /></WorkflowStage></template>
      <template #result><WorkflowStage name="result" title="结果" description="完成后查看链接、订单或错误" state="idle"><UiStatePanel state="empty" title="暂无结果" message="启动任务后结果会显示在这里。" /></WorkflowStage></template>
      <template #resources><WorkflowStage name="resources" title="资源" description="账号池、链接和日志" state="idle"><UiStatusBadge label="资源列表由当前页面管理" tone="info" /></WorkflowStage></template>
    </WorkflowWorkspace>

    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.18em] text-gray-500">Vietnam Wallet 任务</p>
          <h2 class="mt-1 text-2xl font-bold text-white">越南 MoMo 提链</h2>
          <p class="mt-2 text-sm text-gray-400">在账号池中勾选一个或多个账号执行 VN/VND 的 MoMo 提链；可只检测资格，也可完整提链。</p>
        </div>
        <span class="inline-flex w-fit items-center gap-2 rounded-xl border border-gray-800 bg-gray-900 px-3 py-2 text-sm text-gray-300">
          <span class="h-2.5 w-2.5 rounded-full" :class="busy ? 'bg-blue-400' : 'bg-emerald-400'"></span>
          {{ busy ? progressText : '本地服务在线' }}
        </span>
      </div>
    </section>

    <div class="grid grid-cols-1 items-start gap-5 2xl:grid-cols-[minmax(360px,0.85fr)_minmax(460px,1.1fr)_minmax(420px,0.9fr)]">
      <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5">
        <div class="border-b border-gray-800 pb-4">
          <p class="text-xs font-semibold text-gray-500">任务输入</p>
          <h3 class="mt-1 text-xl font-bold text-white">VN 代理</h3>
        </div>

        <div class="mt-5 space-y-5">
          <label class="block">
            <span class="mb-2 block text-sm font-semibold text-gray-300">VN 代理列表</span>
            <textarea
              v-model.trim="form.proxies"
              rows="8"
              spellcheck="false"
              placeholder="每行一个代理；支持 host:port:user-region-VN-sid-xxx-t-120:pass 或 socks5h://user:pass@host:port"
              class="w-full rounded-xl border border-gray-700 bg-gray-950 px-4 py-3 font-mono text-sm text-white placeholder:text-gray-600 focus:border-blue-500 focus:outline-none"
              :disabled="inputLocked"
            ></textarea>
            <span class="mt-1 block text-xs text-gray-500">1024/ArxLabs 的 host:port:user:pass 会自动按 socks5h 使用；建议全程使用 VN 地区代理。</span>
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

          <div class="flex flex-wrap items-center gap-3 border-t border-gray-800 pt-4">
            <button @click="start" :disabled="inputLocked || !selectedEmails.length" class="rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50">
              {{ inputLocked ? '提取中...' : `开始提链 (${selectedEmails.length})` }}
            </button>
            <button
              @click="startQualificationOnly"
              :disabled="inputLocked || !selectedEmails.length"
              class="rounded-lg border border-cyan-500/40 bg-cyan-500/10 px-4 py-2.5 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            >
              仅检测资格{{ selectedEmails.length ? ` (${selectedEmails.length})` : '' }}
            </button>
            <button v-if="activeJobId && inputLocked" @click="cancelJob" :disabled="cancelling" class="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50">
              {{ cancelling ? '取消中...' : '取消提链' }}
            </button>
            <button @click="reloadAll" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">刷新账号/链接</button>
            <button @click="saveProxy" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-4 py-2.5 text-sm font-semibold text-gray-200 transition hover:bg-gray-800 disabled:opacity-50">保存代理</button>
            <button
              @click="retryFailedAccounts"
              :disabled="inputLocked || !retryFailedEmails.length"
              class="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50"
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
            <option value="eligible">有资格</option>
            <option value="ineligible">无资格</option>
            <option value="running">提链中</option>
            <option value="failed">提链失败</option>
            <option value="success">已提链</option>
            <option value="paid">已支付</option>
          </select>
          <div class="flex flex-wrap gap-2">
            <button @click="selectAllFiltered" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">全选当前</button>
            <button @click="clearSelectedAccounts" :disabled="inputLocked" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-xs font-semibold text-gray-200 hover:bg-gray-800 disabled:opacity-50">清空选择</button>
            <button
              @click="deleteSelectedMomoAccounts"
              :disabled="inputLocked || deletingMomoAccounts.size > 0 || !selectedEmails.length"
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
                    @click="deleteMomoAccount(account.email)"
                    :disabled="inputLocked || deletingMomoAccounts.has(account.email)"
                    class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-xs font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                    title="从 Momo 账号池和仪表盘账号池中删除该账号"
                  >
                    {{ deletingMomoAccounts.has(account.email) ? '删除中' : '删除' }}
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
              <div class="mt-2 flex flex-wrap gap-2">
                <a :href="momoLinkUrl(item.link) || '#'" target="_blank" rel="noopener" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-blue-100" :class="!momoLinkUrl(item.link) ? 'pointer-events-none opacity-50' : ''">打开</a>
                <button @click="copy(momoLinkUrl(item.link))" :disabled="!momoLinkUrl(item.link)" class="rounded border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-emerald-100 disabled:opacity-50">复制链</button>
              </div>
            </div>
            <div v-if="recentResultFilter !== 'success'" v-for="item in visibleRecentResultErrors" :key="item.email" class="rounded-lg border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {{ item.email }}：{{ recentResultErrorText(item) }}
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
          <h3 class="mt-1 text-xl font-bold text-white">已提取 Momo 链接</h3>
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
              <th class="px-3 py-2">Momo 链接</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-900">
            <tr v-if="!links.length">
              <td colspan="8" class="px-3 py-10 text-center text-gray-500">暂无链接</td>
            </tr>
            <tr v-for="link in visibleLinks" :key="link.id" class="hover:bg-gray-900/50">
              <td class="px-3 py-2"><input :checked="selectedLinkIds.has(link.id)" type="checkbox" class="accent-emerald-500" @change="toggleLink(link.id)" /></td>
              <td class="whitespace-nowrap px-3 py-2 text-xs text-gray-500">{{ link.created_at }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-300">{{ link.account_email || '-' }}</td>
              <td class="px-3 py-2 text-xs text-gray-400">{{ momoLinkAmountLabel(link) }}</td>
              <td class="px-3 py-2 font-mono text-xs text-gray-400">{{ link.cs_id || '-' }}</td>
              <td class="whitespace-nowrap px-3 py-2 text-xs">
                <span class="rounded-full border px-2 py-1 font-semibold" :class="momoExpiryClass(link)">
                  {{ momoExpiryText(link) }}
                </span>
              </td>
              <td class="px-3 py-2">
                <div class="flex flex-wrap gap-2">
                  <a :href="momoLinkUrl(link) || '#'" target="_blank" rel="noopener" class="rounded border border-blue-500/30 bg-blue-500/10 px-2 py-1 text-xs text-blue-200" :class="!momoLinkActionable(link) ? 'pointer-events-none opacity-50' : ''">打开</a>
                  <button @click="copy(momoLinkUrl(link))" :disabled="!momoLinkActionable(link)" class="rounded border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-200 disabled:opacity-50">复制链</button>
                </div>
              </td>
              <td class="max-w-[360px] truncate px-3 py-2 font-mono text-xs text-gray-500">{{ momoLinkUrl(link) || '-' }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="hiddenLinkCount > 0" class="sticky bottom-0 flex items-center justify-between border-t border-gray-800 bg-gray-950/95 px-3 py-2 text-xs text-gray-500">
          <span>已显示 {{ visibleLinks.length }} / {{ links.length }}，剩余 {{ hiddenLinkCount }} 项</span>
          <button @click="showMoreLinks" class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 font-semibold text-gray-200 hover:bg-gray-800">加载更多</button>
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

import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { createPollingLifecycle } from '../pollingLifecycle.js'
import { createSessionStorageFacade } from '../sessionStorageScope.js'
import { cancelStartAckGeneration, commitStartAckSnapshot, markStartAckGenerationUnknown, reserveStartAckGeneration, watchStartAckGeneration } from '../startAckCas.js'
import { isAmbiguousPaymentFailure } from '../paymentRequestState.js'
import NotificationSoundControl from './NotificationSoundControl.vue'
import { LINK_SUCCESS_SOUND_URL, playNotificationSound } from '../notificationSounds.js'

const sessionStorage = createSessionStorageFacade()

const PROXY_STORAGE_KEY = 'autotoken_momo_vn_proxies'
const FORM_STORAGE_KEY = 'autotoken_momo_vn_form'
const JOB_STORAGE_KEY = 'autotoken_momo_vn_job'
const TERMINAL_STATUSES = new Set(['success', 'error', 'failed', 'cancelled'])
const MOMO_LINK_TTL_MS = 10 * 60 * 1000

const accounts = ref([])
const links = ref([])
const linkVisibleCount = ref(100)
const selectedAccounts = ref(new Set())
const selectedLinkIds = ref(new Set())
const logs = ref([])
const loading = ref(false)
const starting = ref(false)
const startAckPending = ref(false)
const cancelling = ref(false)
const activeJobId = ref('')
const activeJobStatus = ref('')
const currentJob = ref(null)
const currentResult = ref(null)
const statusText = ref('请选择账号并填写 VN 代理后开始提链。')
const statusError = ref(false)
const accountFilter = ref('')
const accountStatusFilter = ref('all')
const accountVisibleCount = ref(100)
const recentResultFilter = ref('all')
const recentResultVisibleCount = ref(100)
const deletingMomoAccounts = ref(new Set())
const lastFailedEmails = ref([])
const notifiedSuccessKeys = ref(new Set())
const successNotificationTimers = new Set()
const nowMs = ref(Date.now())
const logRef = ref(null)
const jobPolling = createPollingLifecycle()
const expiryClock = createPollingLifecycle()
let expiryClockToken = null
let componentUnmounted = false
let startAckWatcher = null

const savedForm = loadForm()
const form = ref({
  proxies: sessionStorage.getItem(PROXY_STORAGE_KEY) || savedForm.proxies || '',
  concurrency: savedForm.concurrency || 1,
  maxAttempts: savedForm.maxAttempts || 5,
  proxyPreflightAttempts: savedForm.proxyPreflightAttempts || 5,
  notificationSoundEnabled: savedForm.notificationSoundEnabled !== false,
})

const selectedEmails = computed(() => Array.from(selectedAccounts.value))
const jobRunning = computed(() => Boolean(activeJobId.value && !TERMINAL_STATUSES.has(activeJobStatus.value)))
const inputLocked = computed(() => starting.value || startAckPending.value || cancelling.value || jobRunning.value)
const busy = computed(() => loading.value || inputLocked.value)
const progressText = computed(() => {
  if (startAckPending.value) return '正在确认任务启动结果...'
  if (starting.value) return '正在创建任务...'
  if (jobRunning.value) return `任务 ${activeJobStatus.value || 'running'}`
  return '刷新中...'
})
const badgeText = computed(() => {
  if (startAckPending.value && !activeJobId.value) return '启动确认中'
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
const visibleLinks = computed(() => links.value.slice(0, linkVisibleCount.value))
const hiddenLinkCount = computed(() => Math.max(0, links.value.length - visibleLinks.value.length))
const currentResultSuccesses = computed(() => Array.isArray(currentResult.value?.successes) ? currentResult.value.successes : [])
const currentResultErrors = computed(() => Array.isArray(currentResult.value?.errors) ? currentResult.value.errors : [])
const currentResultSkipped = computed(() => Array.isArray(currentResult.value?.skipped) ? currentResult.value.skipped : [])
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
watch(logs, () => nextTick(scrollLogsToBottom))

function loadForm() {
  try {
    const data = JSON.parse(sessionStorage.getItem(FORM_STORAGE_KEY) || '{}')
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
}

function saveForm() {
  sessionStorage.setItem(FORM_STORAGE_KEY, JSON.stringify(form.value))
  sessionStorage.setItem(PROXY_STORAGE_KEY, form.value.proxies || '')
}

function setStatus(message, error = false) {
  statusText.value = message
  statusError.value = Boolean(error)
}

function applyStartAckCheckpoint(checkpoint) {
  startAckPending.value = Boolean(checkpoint)
  if (!checkpoint) return
  const requestId = String(checkpoint.clientRequestId || '').trim()
  const suffix = requestId ? `（请求 ${requestId}）` : ''
  if (checkpoint.status === 'unknown') {
    setStatus(`上次 MoMo 任务启动结果未知${suffix}，已锁定重复提交；请保留当前会话等待人工核对。`, true)
    return
  }
  setStatus(`上次 MoMo 任务仍在等待后端确认${suffix}，当前页面会在 ACK 到达后自动恢复。`)
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
        void restoreActiveJob()
        return
      }
      if (event.type === 'unknown') {
        applyStartAckCheckpoint(event.checkpoint)
        return
      }
      applyStartAckCheckpoint(null)
      setStatus(`上次 MoMo 任务启动失败：${event.error || '请求未被后端接受'}`, true)
    },
  })
  applyStartAckCheckpoint(startAckWatcher.checkpoint)
}

function cleanError(error) {
  return String(error?.message || error || '未知错误')
}

function isJobNotFound(error) {
  return Number(error?.status || 0) === 404 && String(error?.message || '').toLowerCase().includes('job not found')
}

function saveActiveJobSnapshot(job = currentJob.value) {
  const jobId = String(job?.id || activeJobId.value || '').trim()
  if (!jobId) return
  sessionStorage.setItem(JOB_STORAGE_KEY, JSON.stringify({
    jobId,
    accountCount: Number(job?.total || 0),
    concurrency: Number(job?.concurrency || form.value.concurrency || 1),
    status: String(job?.status || activeJobStatus.value || ''),
    startedAt: Date.now(),
  }))
}

function clearActiveJob({ removeStored = true } = {}) {
  stopPolling()
  activeJobId.value = ''
  activeJobStatus.value = ''
  currentJob.value = null
  notifiedSuccessKeys.value = new Set()
  cancelling.value = false
  starting.value = false
  if (removeStored) sessionStorage.removeItem(JOB_STORAGE_KEY)
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
  const link = momoLinkUrl(item?.link || item)
  const id = String(item?.id || item?.link?.id || '').trim()
  return email || link || id || `success-${index}`
}

function clearSuccessNotificationTimers() {
  for (const timer of successNotificationTimers) window.clearTimeout(timer)
  successNotificationTimers.clear()
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
    const timer = window.setTimeout(() => {
      successNotificationTimers.delete(timer)
      if (componentUnmounted) return
      void playNotificationSound(LINK_SUCCESS_SOUND_URL, form.value.notificationSoundEnabled)
    }, delay)
    successNotificationTimers.add(timer)
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
  return accountStatus(account) !== 'paid' && account?.momo_selectable !== false
}

function accountJobStatus(account) {
  const email = String(account?.email || '')
  const statuses = currentJob.value?.account_statuses || {}
  return statuses[email] || statuses[email.toLowerCase()] || null
}

function accountStatus(account) {
  return accountJobStatus(account)?.status || account?.momo_status || 'pending'
}

function isOaicsUnsupportedMomoError(message) {
  const text = String(message || '').trim().toLowerCase()
  return text.includes('openai_custom_checkout_unsupported')
    || text.includes('oaics checkout cannot use stripe payment_pages momo flow')
}

function accountStatusText(account) {
  const status = accountStatus(account)
  if (status === 'paid') return '已支付'
  if (status === 'eligible') return '有资格'
  if (status === 'ineligible') return '无资格'
  if (status === 'running') return '提链中'
  if (status === 'success') return '已提链'
  if (status === 'failed' && isOaicsUnsupportedMomoError(accountStatusError(account))) return '提链失败（oaics 当前不支持）'
  if (status === 'failed') return '提链失败'
  return '未提链'
}

function accountStatusError(account) {
  return accountJobStatus(account)?.error || account?.momo_error || ''
}

function recentResultErrorText(item) {
  const error = String(item?.error || '').trim()
  if (isOaicsUnsupportedMomoError(error)) return '提链失败（oaics 当前不支持）'
  return error || '提链失败'
}

function accountStatusClass(account) {
  const status = accountStatus(account)
  if (status === 'paid') return 'border-violet-500/30 bg-violet-500/10 text-violet-300'
  if (status === 'eligible') return 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300'
  if (status === 'ineligible') return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
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

function showMoreLinks() {
  linkVisibleCount.value = Math.min(links.value.length, linkVisibleCount.value + 100)
}

function showMoreRecentResults() {
  recentResultVisibleCount.value = Math.min(filteredRecentResultCount.value, recentResultVisibleCount.value + 100)
}

function toggleLink(id) {
  const next = new Set(selectedLinkIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedLinkIds.value = next
}

function momoLinkUrl(link) {
  return String(link?.provider_redirect_url || link?.momo_link || link?.stripe_redirect_url || '').trim()
}

function momoLinkCurrency(link) {
  return String(link?.currency || link?.billing?.currency || 'VND').trim().toUpperCase() || 'VND'
}

function momoLinkAmountLabel(link) {
  const amount = String(link?.amount ?? '').trim()
  return `${amount || '-'} ${momoLinkCurrency(link)}`
}

function timestampMs(value) {
  const raw = String(value ?? '').trim()
  if (!raw) return 0
  const numeric = Number(raw)
  if (Number.isFinite(numeric) && numeric > 0) return numeric > 1e12 ? numeric : numeric * 1000
  const parsed = Date.parse(raw.includes('T') ? raw : raw.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : 0
}

function momoExpiresAtMs(link) {
  const explicit = timestampMs(link?.momo_expires_at_ts ?? link?.momoExpiresAtTs ?? link?.momo_expires_at ?? link?.momoExpiresAt)
  if (explicit) return explicit
  const created = timestampMs(link?.created_at_ts ?? link?.createdAtTs ?? link?.created_at ?? link?.createdAt)
  return created ? created + MOMO_LINK_TTL_MS : 0
}

function momoRemainingMs(link) {
  const expiresAt = momoExpiresAtMs(link)
  return expiresAt ? expiresAt - nowMs.value : 0
}

function momoLinkExpired(link) {
  const expiresAt = momoExpiresAtMs(link)
  return Boolean(expiresAt && expiresAt <= nowMs.value)
}

function momoLinkActionable(link) {
  return Boolean(momoLinkUrl(link)) && !momoLinkExpired(link)
}

function momoExpiryText(link) {
  if (!momoLinkUrl(link)) return '-'
  const expiresAt = momoExpiresAtMs(link)
  if (!expiresAt || expiresAt <= nowMs.value) return '链接失效'
  const seconds = Math.max(0, Math.ceil((expiresAt - nowMs.value) / 1000))
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return minutes ? `剩余 ${minutes}:${String(rest).padStart(2, '0')}` : `剩余 ${rest}s`
}

function momoExpiryClass(link) {
  if (!momoLinkUrl(link)) return 'border-gray-700 bg-gray-900 text-gray-400'
  if (momoLinkExpired(link)) return 'border-rose-500/30 bg-rose-500/10 text-rose-300'
  if (momoRemainingMs(link) <= 60 * 1000) return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
  return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
}

function scrollLogsToBottom() {
  if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
}

async function refreshAccounts() {
  const accountData = await api.getMomoVnAccounts()
  accounts.value = Array.isArray(accountData.accounts) ? accountData.accounts : []
  const selectable = new Set(accounts.value.filter(accountSelectable).map(item => item.email))
  selectedAccounts.value = new Set(selectedEmails.value.filter(email => selectable.has(email)))
}

async function refreshLinks() {
  const linkData = await api.getMomoVnLinks()
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
  form.value.concurrency = Math.max(1, Math.min(20, Number(form.value.concurrency || 1)))
  form.value.maxAttempts = Math.max(1, Math.min(20, Number(form.value.maxAttempts || 5)))
  form.value.proxyPreflightAttempts = Math.max(1, Math.min(100, Number(form.value.proxyPreflightAttempts || 5)))
  if (!String(form.value.proxies || '').trim()) {
    setStatus('请填写 VN 代理。', true)
    return false
  }
  return true
}

async function startWithEmails(emails, actionText = '提取', qualificationOnly = false) {
  const accountEmails = Array.from(new Set((emails || []).map(email => String(email || '').trim()).filter(Boolean)))
  if (!validateStart(accountEmails)) return
  starting.value = true
  statusError.value = false
  saveForm()
  let startReservation = null
  try {
    startReservation = reserveStartAckGeneration({
      storage: sessionStorage,
      storageKey: JOB_STORAGE_KEY,
      checkpoint: {
        mode: 'extract',
        accountCount: accountEmails.length,
        actionText,
        qualificationOnly: qualificationOnly === true,
      },
    })
    if (!startReservation) throw new Error('无法持久化任务启动代际')
    if (startReservation.status === 'occupied') {
      applyStartAckCheckpoint(startReservation.checkpoint)
      return
    }
    startAckPending.value = true
    const data = await api.startMomoVnBatch({
      accountEmails,
      proxies: form.value.proxies,
      concurrency: form.value.concurrency,
      maxAttempts: form.value.maxAttempts,
      proxyPreflightAttempts: form.value.proxyPreflightAttempts,
      region: 'VN',
      qualificationOnly: qualificationOnly === true,
      clientRequestId: startReservation.clientRequestId,
    })
    const newJobId = String(data.job_id || '').trim()
    if (!newJobId) {
      const error = new Error('后端没有返回任务 ID')
      error.code = 'INVALID_PAYMENT_JOB_RESPONSE'
      throw error
    }
    const startAck = commitStartAckSnapshot(startReservation, {
      componentUnmounted,
      createSnapshot: () => ({
        jobId: newJobId,
        accountCount: accountEmails.length,
        accountEmails,
        concurrency: Number(form.value.concurrency || 1),
        status: 'queued',
        clientRequestId: startReservation.clientRequestId,
        startedAt: Date.now(),
      }),
    })
    if (!startAck.shouldContinue) return
    startAckPending.value = false
    activeJobId.value = newJobId
    activeJobStatus.value = 'queued'
    currentJob.value = { id: activeJobId.value, status: 'queued', total: accountEmails.length, completed: 0, concurrency: form.value.concurrency || 1, running_count: 0 }
    currentResult.value = null
    notifiedSuccessKeys.value = new Set()
    logs.value = []
    setStatus(`任务已提交，正在为 ${accountEmails.length} 个账号${actionText} MoMo，并发 ${form.value.concurrency || 1}。`)
    startPolling()
  } catch (error) {
    const message = cleanError(error)
    if (startReservation?.status === 'reserved' && isAmbiguousPaymentFailure(error)) {
      const unknown = markStartAckGenerationUnknown(startReservation, { componentUnmounted, error: message })
      if (!componentUnmounted) applyStartAckCheckpoint(unknown.checkpoint || startReservation?.checkpoint)
    } else {
      cancelStartAckGeneration(startReservation, { componentUnmounted, error: message })
      if (!componentUnmounted) {
        startAckPending.value = false
        setStatus(`启动失败：${message}`, true)
      }
    }
  } finally {
    if (!componentUnmounted) starting.value = false
  }
}

async function start() {
  await startWithEmails(selectedEmails.value, '提取')
}

async function startQualificationOnly() {
  await startWithEmails(selectedEmails.value, '检测资格', true)
}

async function pollJob(pollToken = null) {
  if (!activeJobId.value) return
  if (pollToken !== null && !jobPolling.isActive(pollToken)) return
  try {
    const job = await api.getMomoVnJob(activeJobId.value)
    if (componentUnmounted || (pollToken !== null && !jobPolling.isActive(pollToken))) return
    currentJob.value = job
    activeJobStatus.value = String(job.status || '')
    logs.value = Array.isArray(job.logs) ? job.logs : []
    currentResult.value = job.result || currentResult.value
    saveActiveJobSnapshot(job)
    notifyNewSuccesses(currentResult.value)
    const total = Number(job.total || 0)
    const completed = Number(job.completed || 0)
    const running = Number(job.running_count || 0)
    setStatus(`状态：${activeJobStatus.value || '-'}，完成 ${completed}/${total}，运行中 ${running}`)
    if (TERMINAL_STATUSES.has(activeJobStatus.value)) {
      stopPolling()
      rememberFailedEmails(currentResult.value)
      if (activeJobStatus.value === 'success') {
        setStatus('提链任务已完成，链接已写入管理表。')
      }
      await Promise.all([refreshAccounts(), refreshLinks()])
    }
  } catch (error) {
    if (pollToken !== null && !jobPolling.isActive(pollToken)) return
    if (isJobNotFound(error)) {
      clearActiveJob()
      await Promise.all([refreshAccounts(), refreshLinks()])
      setStatus('任务已不存在或后端已重启，已停止轮询并刷新账号/链接。', true)
      return
    }
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
  const pollToken = jobPolling.start()
  if (pollToken !== null) void runPollingLoop(pollToken)
}

function stopPolling() {
  jobPolling.cancel()
}

async function runPollingLoop(pollToken) {
  if (!jobPolling.isActive(pollToken)) return
  if (!await jobPolling.waitUntilAvailable(pollToken)) return
  await pollJob(pollToken)
  if (!jobPolling.isActive(pollToken) || !activeJobId.value || TERMINAL_STATUSES.has(activeJobStatus.value)) return
  if (await jobPolling.wait(3000, pollToken)) void runPollingLoop(pollToken)
}

async function cancelJob() {
  if (!activeJobId.value) return
  cancelling.value = true
  stopPolling()
  try {
    await api.cancelMomoVnJob(activeJobId.value)
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
    if (!componentUnmounted && activeJobId.value && !TERMINAL_STATUSES.has(activeJobStatus.value)) startPolling()
  }
}

function saveProxy() {
  saveForm()
  setStatus('MoMo VN 代理配置已保存到本地浏览器。')
}

async function deleteMomoAccount(email) {
  const target = String(email || '').trim()
  if (!target) return
  if (!window.confirm(`确认从 Momo 账号池和仪表盘账号池中删除 ${target}？`)) return
  const nextDeleting = new Set(deletingMomoAccounts.value)
  nextDeleting.add(target)
  deletingMomoAccounts.value = nextDeleting
  try {
    const data = await api.deleteMomoVnAccount(target)
    const next = new Set(selectedAccounts.value)
    next.delete(target)
    selectedAccounts.value = next
    const momo = data.momo_vn || data.momo || {}
    setStatus(`已删除账号 ${target}：仪表盘账号 ${data.dashboard_account_deleted ? '已删除' : '未找到'}，认证 ${data.auth_session_deleted ? '已删除' : '未找到'}，MoMo 链接 ${momo.links_deleted || 0} 条。`)
    await reloadAll()
  } catch (error) {
    setStatus(`删除账号失败：${cleanError(error)}`, true)
  } finally {
    const done = new Set(deletingMomoAccounts.value)
    done.delete(target)
    deletingMomoAccounts.value = done
  }
}

async function deleteSelectedMomoAccounts() {
  const emails = selectedEmails.value.map(email => String(email || '').trim()).filter(Boolean)
  if (!emails.length) return
  if (!window.confirm(`确认批量删除选中的 ${emails.length} 个账号？这些账号会同时从 MoMo 账号池和仪表盘账号池删除。`)) return
  deletingMomoAccounts.value = new Set(emails)
  try {
    const data = await api.deleteMomoVnAccounts(emails)
    const deleted = new Set((data.results || []).map(item => String(item.email || '').trim()).filter(Boolean))
    selectedAccounts.value = new Set(Array.from(selectedAccounts.value).filter(email => !deleted.has(email)))
    const linkCount = (data.results || []).reduce((sum, item) => sum + Number((item.momo_vn || item.momo || {}).links_deleted || 0), 0)
    setStatus(`已批量删除 ${data.deleted || deleted.size} 个账号，清理 MoMo 链接 ${linkCount} 条。`)
    await reloadAll()
  } catch (error) {
    setStatus(`批量删除账号失败：${cleanError(error)}`, true)
  } finally {
    deletingMomoAccounts.value = new Set()
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
  const data = await api.deleteMomoVnLinks(ids)
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已删除 ${data.deleted || ids.length} 条链接。`)
}

async function clearLinks() {
  if (!links.value.length || !window.confirm('确认清空所有 MoMo 链接？')) return
  const data = await api.clearMomoVnLinks()
  links.value = Array.isArray(data.links) ? data.links : []
  selectedLinkIds.value = new Set()
  setStatus(`已清空 ${data.deleted || 0} 条链接。`)
}

function exportLinks() {
  const blob = new Blob([JSON.stringify(links.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `momo-vn-links-${new Date().toISOString().slice(0, 10)}.json`
  a.click()
  URL.revokeObjectURL(url)
}

async function restoreActiveJob() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(JOB_STORAGE_KEY) || '{}')
    const jobId = String(saved?.jobId || '').trim()
    if (!jobId) return
    activeJobId.value = jobId
    activeJobStatus.value = String(saved.status || 'queued')
    currentJob.value = {
      id: jobId,
      status: activeJobStatus.value || 'queued',
      total: Number(saved.accountCount || 0),
      completed: 0,
      concurrency: Number(saved.concurrency || form.value.concurrency || 1),
      running_count: 0,
    }
    setStatus('已恢复 MoMo 提链任务，正在重新同步后端进度。')
    if (!componentUnmounted) startPolling()
  } catch (error) {
    sessionStorage.removeItem(JOB_STORAGE_KEY)
    clearActiveJob({ removeStored: false })
    setStatus(`恢复任务失败：${cleanError(error)}`, true)
  }
}

async function runExpiryClock(pollToken) {
  while (expiryClock.isActive(pollToken)) {
    if (!await expiryClock.wait(1000, pollToken)) return
    if (!await expiryClock.waitUntilAvailable(pollToken)) return
    if (!expiryClock.isActive(pollToken)) return
    nowMs.value = Date.now()
  }
}

function startExpiryClock() {
  expiryClockToken = expiryClock.start()
  if (expiryClockToken !== null) void runExpiryClock(expiryClockToken)
}

onMounted(async () => {
  componentUnmounted = false
  installStartAckWatcher()
  nowMs.value = Date.now()
  startExpiryClock()
  await reloadAll()
  if (startAckPending.value) installStartAckWatcher()
  await restoreActiveJob()
})
watch([accountFilter, accountStatusFilter], () => { accountVisibleCount.value = 100 })
watch(recentResultFilter, () => { recentResultVisibleCount.value = 100 })
watch(links, () => { linkVisibleCount.value = 100 })
watch(currentResult, () => { recentResultVisibleCount.value = 100 })
onUnmounted(() => {
  componentUnmounted = true
  startAckWatcher?.unsubscribe()
  startAckWatcher = null
  clearSuccessNotificationTimers()
  stopPolling()
  jobPolling.dispose()
  expiryClock.dispose()
  expiryClockToken = null
})
</script>

