<template>
  <div class="space-y-6 xl:h-[calc(100vh-3rem)] xl:min-h-0">
    <div class="grid shrink-0 grid-cols-1 gap-4 xl:grid-cols-[380px_minmax(0,1fr)] xl:items-stretch">
      <div class="flex flex-col justify-center">
        <h2 class="text-xl font-bold text-white">PayPal ICE</h2>
        <p class="mt-1 text-sm text-gray-400">通过 ICE API 检测试用资格并激活 ChatGPT Plus。</p>
      </div>
      <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div v-for="card in boardCards" :key="card.label" class="rounded-xl border border-gray-800 bg-gray-900/80 px-4 py-3">
          <div class="text-xs font-medium text-gray-400">{{ card.label }}</div>
          <div class="mt-2 text-xl font-semibold" :class="card.color">{{ card.value }}</div>
          <div class="mt-1 text-xs text-gray-500">{{ card.meta }}</div>
        </div>
      </div>
    </div>

    <div v-if="message" class="rounded-lg border px-4 py-3 text-sm" :class="messageOk ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border-rose-500/20 bg-rose-500/10 text-rose-300'">
      {{ message }}
    </div>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4 xl:h-[calc(100vh-150px)] xl:min-h-0 xl:flex xl:flex-col xl:overflow-hidden">
      <div class="grid grid-cols-1 gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[460px_minmax(0,1fr)] xl:overflow-hidden">
        <div class="space-y-4 xl:min-h-0 xl:overflow-y-auto xl:pr-2 xl:pb-2">
          <div class="grid grid-cols-1 gap-3" :class="activationBusy ? 'sm:grid-cols-3' : 'sm:grid-cols-2'">
            <button @click="checkTrials" :disabled="busy || activationLocked || !selectedItems.length || !config.configured" class="rounded-lg border border-emerald-500/30 bg-emerald-600/15 px-4 py-2.5 text-sm text-emerald-200 transition hover:bg-emerald-600/25 disabled:opacity-50">
              {{ trialBusy ? `检测中... (${selectedItems.length})` : `检测 Plus 试用资格 (${selectedItems.length})` }}
            </button>
            <button v-if="activationBusy || activeJobCount || currentActivationOpen" @click="cancelActivationRun" :disabled="activationCancelRequested" class="rounded-lg border border-amber-500/30 bg-amber-600/15 px-4 py-2.5 text-sm text-amber-200 transition hover:bg-amber-600/25 disabled:opacity-50">
              {{ activationCancelRequested ? '取消中...' : '取消任务' }}
            </button>
            <button @click="activatePlus" :disabled="busy || activationLocked || !selectedItems.length || !config.configured" class="rounded-lg bg-blue-600 px-4 py-2.5 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50">
              {{ activationLocked ? '运行中...' : `激活 Plus (${selectedItems.length})` }}
            </button>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-white">ICE API 配置</h3>
                <p class="mt-1 text-xs text-gray-500">{{ configStatusText }}</p>
              </div>
              <button @click="loadIceAccount" :disabled="busy || !config.configured" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50">
                刷新额度
              </button>
            </div>
            <div class="space-y-3">
              <div>
                <label class="mb-1 block text-xs text-gray-400">接口地址</label>
                <input v-model.trim="configDraft.base_url" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">API Key</label>
                <input v-model="configDraft.api_key" type="password" :placeholder="config.api_key_masked || '输入 ICE API Key'" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <button @click="saveConfig" :disabled="busy || !configDraft.base_url" class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50">
                {{ configSaving ? '保存中...' : '保存 ICE 配置' }}
              </button>
            </div>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="mb-3 flex items-center justify-between gap-3">
              <div>
                <h3 class="text-sm font-semibold text-white">激活账号</h3>
                <p class="mt-1 text-xs text-gray-500">{{ inputSource === 'token' ? '直接粘贴 Access Token 提交 ICE 激活。' : '选择一个账号或批量提交，Token 从本地 auth 文件读取。' }}</p>
              </div>
              <div class="grid grid-cols-2 gap-1 rounded-lg border border-gray-700 bg-gray-900 p-1 text-xs">
                <button @click="inputSource = 'account'" :disabled="activationLocked" class="rounded-md px-3 py-1.5 transition disabled:opacity-50" :class="inputSource === 'account' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'">号池</button>
                <button @click="inputSource = 'token'" :disabled="activationLocked" class="rounded-md px-3 py-1.5 transition disabled:opacity-50" :class="inputSource === 'token' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'">Token</button>
              </div>
            </div>

            <template v-if="inputSource === 'account'">
              <div class="mb-2 flex items-center justify-between gap-3">
                <label class="block text-sm text-gray-400">号池账号</label>
                <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                  <input
                    v-model="batchMode"
                    type="checkbox"
                    :disabled="loadingAccounts || activationLocked"
                    class="accent-blue-500"
                  />
                  批量激活
                </label>
              </div>

              <template v-if="!batchMode">
                <input
                  v-model.trim="accountKeyword"
                  type="text"
                  class="mb-2 w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500"
                  placeholder="搜索邮箱"
                  :disabled="loadingAccounts"
                />
                <select
                  v-model="singleEmail"
                  class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500"
                  :disabled="loadingAccounts"
                >
                  <option value="">{{ loadingAccounts ? '加载账号中...' : (filteredAccounts.length ? `共 ${filteredAccounts.length} 个匹配账号` : '没有匹配账号') }}</option>
                  <option v-for="account in filteredAccounts" :key="account.email" :value="account.email">
                    {{ account.email }}
                  </option>
                </select>
              </template>

              <div v-else class="rounded-lg border border-gray-700 bg-gray-900/70 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="min-w-0">
                    <div class="text-xs text-gray-500">当前选择</div>
                    <div class="mt-1 truncate font-mono text-sm text-gray-200">{{ accountSelectionLabel }}</div>
                  </div>
                  <button
                    type="button"
                    @click="pickerOpen = true"
                    :disabled="loadingAccounts"
                    class="shrink-0 rounded-lg border border-blue-500/30 bg-blue-600/20 px-4 py-2 text-sm text-blue-300 transition hover:bg-blue-600/30 disabled:opacity-50"
                  >
                    {{ loadingAccounts ? '加载中...' : '选择账号' }}
                  </button>
                </div>
                <div v-if="selectedBatchEmails.length" class="mt-2 flex flex-wrap gap-2">
                  <span v-for="email in batchPreview" :key="email" class="max-w-full truncate rounded-md border border-gray-700 bg-gray-950 px-2 py-1 font-mono text-xs text-gray-300">{{ email }}</span>
                  <span v-if="selectedBatchEmails.length > batchPreview.length" class="rounded-md border border-gray-700 bg-gray-950 px-2 py-1 text-xs text-gray-500">+{{ selectedBatchEmails.length - batchPreview.length }}</span>
                </div>
              </div>
            </template>

            <div v-else class="space-y-2">
              <textarea
                v-model="accessTokenText"
                rows="7"
                wrap="off"
                spellcheck="false"
                class="w-full overflow-x-auto rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-white outline-none focus:border-blue-500"
                placeholder="一行一个 Access Token，或：备注----access_token"
              ></textarea>
              <div class="flex items-center justify-between gap-3 text-xs text-gray-500">
                <span>已解析 {{ directTokenEntries.length }} 个 token</span>
                <button @click="accessTokenText = ''" :disabled="!accessTokenText.trim()" class="rounded-md border border-gray-700 bg-gray-800 px-2 py-1 text-gray-300 transition hover:bg-gray-700 disabled:opacity-50">清空</button>
              </div>
            </div>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <h3 class="text-sm font-semibold text-white">任务选项</h3>
            <div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label class="mb-1 block text-xs text-gray-400">US 代理</label>
                <input v-model.trim="options.proxy" type="text" placeholder="留空使用内置代理" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">JP 代理</label>
                <input v-model.trim="options.proxy_jp" type="text" placeholder="留空使用内置代理" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div class="sm:col-span-2">
                <div class="mb-2 flex items-center justify-between gap-3">
                  <label class="block text-xs text-gray-400">接码来源</label>
                  <button type="button" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700" @click="phonePoolOpen = true">
                    管理手机号池
                  </button>
                </div>
                <div class="grid grid-cols-2 gap-1 rounded-lg border border-gray-700 bg-gray-900 p-1 text-sm">
                  <button type="button" class="rounded-md px-3 py-2 transition" :class="options.use_pool ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'" @click="options.use_pool = true">
                    手机号池
                  </button>
                  <button type="button" class="rounded-md px-3 py-2 transition" :class="!options.use_pool ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-gray-200'" @click="options.use_pool = false">
                    手动接码
                  </button>
                </div>
              </div>
              <div v-if="options.use_pool" class="flex items-center justify-between rounded-lg border border-gray-800 bg-gray-900/70 px-3 py-3 sm:col-span-2">
                <div>
                  <div class="text-sm text-gray-200">可用 {{ phonePoolStats.available || 0 }} / 总数 {{ phonePoolStats.total || 0 }}</div>
                  <div class="mt-1 text-xs text-gray-500">运行中的任务独占号码；任务结束释放后，下一账号可继续复用。</div>
                </div>
                <button type="button" :disabled="phonePoolLoading" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50" @click="loadPhonePoolStats">
                  {{ phonePoolLoading ? '刷新中...' : '刷新' }}
                </button>
              </div>
              <template v-else>
                <div>
                  <label class="mb-1 block text-xs text-gray-400">接码手机号</label>
                  <input v-model.trim="options.phone" type="text" placeholder="必须与接码 API 同时填写" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                </div>
                <div>
                  <label class="mb-1 block text-xs text-gray-400">接码 API</label>
                  <input v-model.trim="options.sms_api" type="text" placeholder="https://.../getphonecode?order_no=..." class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                </div>
              </template>
              <div>
                <label class="mb-1 block text-xs text-gray-400">提链重试</label>
                <input v-model.number="options.pplink_retry" type="number" min="0" max="10" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">OTP 超时（秒）</label>
                <input v-model.number="options.otp_timeout" type="number" min="30" max="900" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">前端并发数</label>
                <input v-model.number="options.concurrency" type="number" min="1" max="99" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                <div class="mt-1 text-xs text-gray-500">实际并发还会受 ICE 额度和可用手机号限制。</div>
              </div>
              <div>
                <label class="mb-1 block text-xs text-gray-400">任务失败重试</label>
                <input v-model.number="options.job_retry" type="number" min="0" max="5" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
                <div class="mt-1 text-xs text-gray-500">本轮全部结束后，将失败账号整轮重新提交；手机号池模式会先等待号码释放。</div>
              </div>
              <label class="flex items-start gap-3 rounded-lg border border-gray-800 bg-gray-900/70 px-3 py-3 sm:col-span-2" :class="inputSource === 'token' ? 'cursor-not-allowed opacity-50' : 'cursor-pointer'">
                <input v-model="options.auto_oauth_login" type="checkbox" :disabled="inputSource === 'token'" class="mt-0.5 h-4 w-4 accent-blue-500" />
                <span>
                  <span class="block text-sm text-gray-200">Plus 激活成功后自动协议补登录并绑定邮箱</span>
                  <span class="mt-1 block text-xs text-gray-500">默认关闭。仅号池账号可用，使用仪表盘 OAuth 配置；失败不会影响 ICE 激活结果。</span>
                </span>
              </label>
              <div v-if="inputSource === 'account' && options.auto_oauth_login" class="space-y-3 rounded-lg border border-blue-500/20 bg-blue-600/10 px-3 py-3 sm:col-span-2">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <div class="text-sm font-semibold text-blue-100">邮箱绑定配置</div>
                    <div class="mt-1 text-xs text-gray-500">用于 ICE 激活成功后的协议补登录和邮箱绑定。</div>
                  </div>
                  <button type="button" :disabled="oauthEmailLoading" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50" @click="loadOauthEmailConfig(true)">
                    {{ oauthEmailLoading ? '读取中...' : '刷新配置' }}
                  </button>
                </div>

                <div class="grid gap-3 sm:grid-cols-2">
                  <div>
                    <label class="mb-1 block text-xs text-gray-400">邮件供应商</label>
                    <select v-model="oauthEmailMailProvider" :disabled="oauthEmailLoading" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500">
                      <option value="">请选择邮件供应商</option>
                      <option v-for="opt in oauthEmailMailProviderOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                    </select>
                  </div>

                  <template v-if="oauthEmailMailProvider === 'luckmail'">
                    <div>
                      <label class="mb-1 block text-xs text-gray-400">LuckMail 邮箱类型</label>
                      <select v-model="oauthEmailLuckmailEmailType" :disabled="oauthEmailLoading" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500">
                        <option v-for="opt in luckmailEmailTypeOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </select>
                    </div>
                    <div>
                      <label class="mb-1 block text-xs text-gray-400">LuckMail 首选域名</label>
                      <select v-model="oauthEmailLuckmailDomain" :disabled="oauthEmailLoading" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500">
                        <option v-for="opt in luckmailDomainOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                      </select>
                    </div>
                  </template>

                  <div v-if="oauthEmailMailProvider && oauthEmailMailProvider !== 'luckmail' && oauthEmailMailProvider !== 'outlook'">
                    <label class="mb-1 block text-xs text-gray-400">注册域名</label>
                    <select v-model="oauthEmailDomain" :disabled="oauthEmailLoading" class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white outline-none focus:border-blue-500">
                      <option value="">请选择域名</option>
                      <option v-for="domain in oauthEmailDomainOptions" :key="domain" :value="domain">@{{ domain }}</option>
                    </select>
                  </div>

                </div>

                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div class="text-xs text-gray-500">{{ oauthEmailSummary }}</div>
                  <button type="button" :disabled="oauthEmailSaving || oauthEmailLoading" class="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50" @click="saveOauthEmailConfig">
                    {{ oauthEmailSaving ? '保存中...' : '保存邮箱配置' }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <section class="flex min-h-[520px] flex-col rounded-xl border border-gray-800 bg-gray-950/60 p-4 xl:min-h-0">
          <div class="flex shrink-0 flex-col gap-3 border-b border-gray-800 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h3 class="font-semibold text-white">ICE 激活任务</h3>
              <p class="mt-1 text-xs text-gray-500">{{ displayedResultRows.length ? `共 ${displayedResultRows.length} 条记录，运行中任务实时刷新。` : '尚未提交检测或激活任务。' }}</p>
            </div>
            <div class="flex gap-2">
              <button @click="refreshActiveJobs({ manual: true })" :disabled="manualRefreshingJobs || !activeJobCount" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 transition hover:bg-gray-700 disabled:opacity-50">{{ manualRefreshingJobs ? '刷新中...' : '刷新任务' }}</button>
              <button @click="clearResults" :disabled="busy || !resultRows.length" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-400 transition hover:bg-gray-700 disabled:opacity-50">清空</button>
            </div>
          </div>

          <div class="mt-4 rounded-lg border border-gray-800 bg-gray-900/70 px-4 py-3">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div class="text-xs font-medium text-gray-400">整体任务进度</div>
                <div class="mt-1 text-sm text-gray-200">{{ overallProgress.summary }}</div>
              </div>
              <div class="font-mono text-2xl font-semibold" :class="overallProgress.color">{{ overallProgress.percent }}%</div>
            </div>
            <div class="mt-3 h-2 overflow-hidden rounded-full bg-gray-800">
              <div class="h-full rounded-full transition-all duration-500" :class="overallProgress.barClass" :style="{ width: `${overallProgress.percent}%` }"></div>
            </div>
            <div class="mt-2 grid grid-cols-2 gap-2 text-xs text-gray-500 sm:grid-cols-4">
              <span>总任务 {{ overallProgress.total }}</span>
              <span class="text-emerald-300">成功 {{ overallProgress.success }}</span>
              <span class="text-amber-300">运行 {{ overallProgress.running }}</span>
              <span class="text-rose-300">失败 {{ overallProgress.failed }}</span>
            </div>
            <div v-if="failureReasonStats.length" class="mt-3 border-t border-gray-800 pt-3">
              <div class="mb-2 flex items-center justify-between gap-3">
                <span class="text-xs font-medium text-gray-400">失败原因统计</span>
                <span class="text-xs text-gray-500">{{ failureReasonStats.length }} 类原因</span>
              </div>
              <div class="max-h-32 space-y-1 overflow-auto pr-1">
                <div v-for="item in failureReasonStats" :key="item.reason" class="grid grid-cols-[4.5rem_3.5rem_minmax(0,1fr)] items-start gap-2 text-xs">
                  <span class="font-mono text-rose-300">{{ item.count }} 个</span>
                  <span class="font-mono text-gray-500">{{ item.percent }}%</span>
                  <span class="break-words text-gray-300" :title="item.reason">{{ item.reason }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="mt-4 min-h-0 flex-1 overflow-auto">
            <table class="w-full min-w-[1180px] table-fixed text-left text-sm">
              <thead class="sticky top-0 bg-gray-950 text-xs text-gray-500">
                <tr>
                  <th class="w-[18%] px-3 py-2 font-medium">账号</th>
                  <th class="w-[9%] px-3 py-2 font-medium">试用资格</th>
                  <th class="w-[23%] px-3 py-2 font-medium">任务进度</th>
                  <th class="w-[16%] px-3 py-2 font-medium">补登录</th>
                  <th class="w-[13%] px-3 py-2 font-medium">绑定时间</th>
                  <th class="w-[8%] px-3 py-2 font-medium">计费</th>
                  <th class="w-[13%] px-3 py-2 font-medium">结果</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-800">
                <tr v-for="row in displayedResultRows" :key="rowKey(row)" class="text-gray-300">
                  <td class="truncate px-3 py-2.5 font-mono text-xs text-gray-200" :title="row.email">{{ row.email }}</td>
                  <td class="px-3 py-2.5"><span class="rounded-md border px-2 py-1 text-xs" :class="trialClass(row.trialStatus)">{{ trialLabel(row.trialStatus) }}</span></td>
                  <td class="px-3 py-2.5">
                    <div class="space-y-2">
                      <div class="flex items-center justify-between gap-3">
                        <span class="rounded-md border px-2 py-1 text-xs" :class="jobClass(row.status)">{{ jobLabel(row.status) }}</span>
                        <span class="font-mono text-xs text-gray-500">{{ jobProgressPercent(row) }}%</span>
                      </div>
                      <div class="h-1.5 overflow-hidden rounded-full bg-gray-800">
                        <div class="h-full rounded-full transition-all duration-500" :class="jobProgressClass(row)" :style="{ width: `${jobProgressPercent(row)}%` }"></div>
                      </div>
                      <div class="truncate text-[11px] text-sky-300" :title="iceRealtimeProgressText(row)">{{ iceRealtimeProgressText(row) }}</div>
                      <div class="truncate text-[11px] text-gray-500" :title="jobProgressText(row)">{{ jobProgressText(row) }}</div>
                    </div>
                  </td>
                  <td class="px-3 py-2.5">
                    <div v-if="row.autoOauthLogin" class="space-y-1">
                      <span class="rounded-md border px-2 py-1 text-xs" :class="oauthLoginClass(row.oauthLoginStatus)">{{ oauthLoginLabel(row.oauthLoginStatus) }}</span>
                      <div v-if="oauthLoginStageSummary(row).visible" class="space-y-1">
                        <span
                          class="inline-flex rounded border px-1.5 py-0.5 text-[10px] leading-4 transition-colors"
                          :class="oauthLoginStageClass(oauthLoginStageSummary(row).current)"
                        >
                          {{ oauthLoginStageSummary(row).current.label }}
                        </span>
                        <div
                          class="truncate text-[11px]"
                          :class="oauthLoginStageSummary(row).failed ? 'text-rose-300' : 'text-sky-300'"
                          :title="oauthLoginStageSummary(row).message"
                        >
                          {{ oauthLoginStageSummary(row).message }}
                        </div>
                      </div>
                      <div v-if="row.oauthLoginResultEmail" class="truncate font-mono text-[11px] text-emerald-300" :title="row.oauthLoginResultEmail">{{ row.oauthLoginResultEmail }}</div>
                      <div v-else-if="row.oauthLoginError" class="truncate text-[11px] text-rose-300" :title="row.oauthLoginError">{{ row.oauthLoginError }}</div>
                    </div>
                    <span v-else class="text-xs text-gray-600">未开启</span>
                  </td>
                  <td class="truncate px-3 py-2.5 font-mono text-xs text-gray-400" :title="formatBindTime(row)">{{ formatBindTime(row) }}</td>
                  <td class="truncate px-3 py-2.5 text-xs text-gray-400" :title="row.billingStatus || '-'">{{ row.billingStatus || '-' }}</td>
                  <td class="truncate px-3 py-2.5 text-xs" :class="row.error ? 'text-rose-300' : 'text-gray-400'" :title="row.error || row.resultCode || row.resourceMode || '-'">{{ row.error || row.resultCode || row.resourceMode || '-' }}</td>
                </tr>
                <tr v-if="!displayedResultRows.length">
                  <td colspan="7" class="px-3 py-16 text-center text-sm text-gray-500">没有 ICE 激活记录</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </section>

    <Teleport to="body">
      <div v-if="pickerOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" @click.self="pickerOpen = false">
        <div class="flex max-h-[82vh] w-full max-w-3xl flex-col rounded-xl border border-gray-800 bg-gray-900 shadow-2xl">
          <div class="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-4">
            <div>
              <h4 class="text-lg font-semibold text-white">批量选择账号</h4>
            </div>
            <button @click="pickerOpen = false" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:bg-gray-700">关闭</button>
          </div>
          <div class="space-y-3 border-b border-gray-800 px-5 py-4">
            <input
              v-model.trim="accountKeyword"
              type="text"
              :disabled="loadingAccounts"
              placeholder="搜索邮箱，例如 openaibus.com"
              class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white outline-none focus:border-blue-500"
            />
            <div class="flex flex-wrap items-end gap-2">
              <label class="min-w-[132px] flex-1">
                <span class="mb-1 block text-xs text-gray-400">选择数量</span>
                <input
                  v-model.number="batchSelectCount"
                  type="number"
                  min="1"
                  :max="Math.max(1, filteredAccounts.length)"
                  :disabled="loadingAccounts || !filteredAccounts.length"
                  class="w-full rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-white outline-none focus:border-blue-500 disabled:opacity-50"
                  @keydown.enter.prevent="selectAccountsByCount"
                />
              </label>
              <button
                type="button"
                @click="selectAccountsByCount"
                :disabled="loadingAccounts || !filteredAccounts.length"
                class="h-[38px] rounded-lg border border-blue-500/30 bg-blue-600/20 px-4 text-sm text-blue-300 transition hover:bg-blue-600/30 disabled:opacity-50"
              >
                按数量选择
              </button>
            </div>
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="text-xs text-gray-400">
                {{ loadingAccounts ? '加载账号中...' : filteredAccounts.length ? `当前筛选 ${filteredAccounts.length} 个账号` : '没有匹配账号' }}
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <button type="button" @click="selectAllAccounts" :disabled="loadingAccounts || !accountOptions.length || allAccountsSelected" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50">全选</button>
                <button type="button" @click="batchEmails = []" :disabled="!selectedBatchEmails.length" class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50">清空</button>
              </div>
            </div>
          </div>
          <div class="min-h-0 flex-1 space-y-1 overflow-y-auto px-5 py-4">
            <label v-for="account in filteredAccounts" :key="`picker-${account.email}`" class="flex cursor-pointer items-center gap-3 rounded-lg px-3 py-2 text-sm text-gray-200 hover:bg-gray-800">
              <input v-model="batchEmails" type="checkbox" :value="account.email" class="accent-blue-500" />
              <span class="break-all font-mono text-xs">{{ account.email }}</span>
            </label>
            <div v-if="!filteredAccounts.length" class="px-3 py-10 text-sm text-gray-500">暂无匹配账号。</div>
          </div>
          <div class="flex items-center justify-end gap-3 border-t border-gray-800 px-5 py-4">
            <button type="button" @click="pickerOpen = false" class="rounded-lg bg-blue-600 px-5 py-2 text-sm text-white transition hover:bg-blue-500">完成</button>
          </div>
        </div>
      </div>
    </Teleport>
    <PayPalIcePhonePoolDialog
      :open="phonePoolOpen"
      @close="phonePoolOpen = false"
      @stats="applyPhonePoolStats"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import PayPalIcePhonePoolDialog from './PayPalIcePhonePoolDialog.vue'

const emit = defineEmits(['refresh'])
const PAYPAL_ICE_FORM_STATE_KEY = 'autotoken.paypalIce.formState.v1'
const PAYPAL_ICE_ROWS_STATE_KEY = 'autotoken.paypalIce.resultRows.v1'
const PAYPAL_ICE_RUN_STATE_KEY = 'autotoken.paypalIce.activationRun.v1'
const OAUTH_EMAIL_STORAGE_KEY = 'autotoken.dashboard.oauthEmailCfg'
const PAYPAL_ICE_POLL_INTERVAL_MS = 1500
const PAYPAL_ICE_ACCOUNT_REFRESH_INTERVAL_MS = 5000
const PAYPAL_ICE_SCHEDULER_INTERVAL_MS = 500
const PAYPAL_ICE_EARLY_RETRY_REMAINING = 10
const PAYPAL_ICE_ROWS_LIMIT = 500
const rememberedFormState = loadPayPalIceFormState()
const rememberedActivationRun = loadStoredActivationRunState()

const config = ref({ configured: false, api_key_masked: '', base_url: 'https://plus.iceaix.com' })
const configDraft = ref({ api_key: '', base_url: 'https://plus.iceaix.com' })
const iceAccount = ref(null)
const accounts = ref([])
const inputSource = ref(rememberedFormState.inputSource)
const mode = ref(rememberedFormState.mode)
const singleEmail = ref(rememberedFormState.singleEmail)
const batchEmails = ref(rememberedFormState.batchEmails)
const accessTokenText = ref('')
const accountKeyword = ref('')
const batchSelectCount = ref(rememberedFormState.batchSelectCount)
const pickerOpen = ref(false)
const phonePoolOpen = ref(false)
const phonePoolLoading = ref(false)
const phonePoolStats = ref({ total: 0, available: 0, in_use: 0, disabled: 0, error: 0 })
const loadingAccounts = ref(false)
const oauthEmailMailProvider = ref('')
const oauthEmailLuckmailEmailType = ref('ms_imap')
const oauthEmailLuckmailDomain = ref('')
const oauthEmailMailProviderOptions = ref([])
const oauthEmailDomain = ref('')
const oauthEmailDomainOptions = ref([])
const oauthEmailLoading = ref(false)
const oauthEmailSaving = ref(false)
const oauthEmailLoaded = ref(false)
const configSaving = ref(false)
const trialBusy = ref(false)
const activationBusy = ref(false)
const activationCancelRequested = ref(false)
const refreshingJobs = ref(false)
const manualRefreshingJobs = ref(false)
const message = ref('')
const messageOk = ref(true)
const resultRows = ref(loadStoredResultRows())
const options = ref(rememberedFormState.options)
const currentActivationRunId = ref(rememberedActivationRun.runId)
const currentActivationTotal = ref(rememberedActivationRun.total)
const currentActivationRetryRound = ref(rememberedActivationRun.retryRound)
const currentActivationInputSource = ref(rememberedActivationRun.inputSource)
const restoredActivationItems = ref(rememberedActivationRun.items.length ? rememberedActivationRun.items : null)
const cancelledActivationRunIds = new Set()
let pollTimer = null
let iceAccountRefreshPromise = null
let lastIceAccountRefreshAt = 0

const busy = computed(() => configSaving.value || trialBusy.value || activationBusy.value)
const batchMode = computed({
  get: () => mode.value === 'batch',
  set: value => {
    mode.value = value ? 'batch' : 'single'
  },
})
const accountOptions = computed(() => {
  const rows = Array.isArray(accounts.value) ? accounts.value : []
  return rows.filter(isUsableFreeAccount)
})
const filteredAccounts = computed(() => filterAccounts(accountOptions.value, accountKeyword.value))
const selectedBatchEmails = computed(() => {
  const seen = new Set()
  return batchEmails.value
    .map(email => String(email || '').trim().toLowerCase())
    .filter(email => {
      if (!email || seen.has(email)) return false
      seen.add(email)
      return true
    })
})
const selectedEmails = computed(() => batchMode.value ? selectedBatchEmails.value : (singleEmail.value ? [singleEmail.value] : []))
const directTokenEntries = computed(() => parseAccessTokenEntries(accessTokenText.value))
const selectedItems = computed(() => {
  if (inputSource.value === 'token') return directTokenEntries.value
  return selectedEmails.value.map(email => ({ key: email, label: email, clientRef: email, email }))
})
const batchPreview = computed(() => selectedBatchEmails.value.slice(0, 4))
const allAccountsSelected = computed(() => accountOptions.value.length > 0 && accountOptions.value.every(account => selectedBatchEmails.value.includes(String(account.email || '').toLowerCase())))
const accountSelectionLabel = computed(() => selectedBatchEmails.value.length ? `${selectedBatchEmails.value.length} 个账号` : '未选择')
const displayedResultRows = computed(() => normalizeResultRows(resultRows.value))
const activeJobCount = computed(() => resultRows.value.filter(rowNeedsRefresh).length)
const currentActivationRows = computed(() => {
  const runId = currentActivationRunId.value
  if (!runId) return []
  const latestByAccount = new Map()
  for (const row of resultRows.value) {
    if (row.activationRunId !== runId) continue
    const key = String(row.activationItemKey || row.email || '').trim().toLowerCase()
    if (!key) continue
    const existing = latestByAccount.get(key)
    const rowTimestamp = normalizeRowTimestamp(row.updatedAt || row.createdAt || row.sortAt)
    const existingTimestamp = normalizeRowTimestamp(existing?.updatedAt || existing?.createdAt || existing?.sortAt)
    if (!existing || preferActivationProgressRow(row, existing, rowTimestamp, existingTimestamp)) {
      latestByAccount.set(key, row)
    }
  }
  return [...latestByAccount.values()]
})
const currentActivationOpen = computed(() => currentActivationRows.value.some(row => !isTerminalActivationStatus(row.status)))
const activationLocked = computed(() => activationBusy.value || currentActivationOpen.value)
const successCount = computed(() => currentActivationRows.value.filter(activationRowSucceeded).length)
const jobRows = computed(() => currentActivationRows.value.filter(row => row.activationRunId))
const overallProgress = computed(() => {
  const rows = jobRows.value
  const total = Math.max(currentActivationTotal.value, rows.length)
  if (!total) {
    return {
      total: 0,
      success: 0,
      failed: 0,
      running: 0,
      percent: 0,
      summary: '等待本轮 ICE 激活任务',
      color: 'text-gray-400',
      barClass: 'bg-gray-600',
    }
  }
  const success = rows.filter(activationRowSucceeded).length
  const failed = rows.filter(row => String(row.status || '').toLowerCase() === 'failed').length
  const skipped = rows.filter(row => String(row.status || '').toLowerCase() === 'skipped').length
  const running = rows.filter(row => {
    const status = String(row.status || '').toLowerCase()
    return status && !['success', 'failed', 'skipped', 'cancelled'].includes(status)
  }).length
  const percent = Math.max(0, Math.min(100, Math.round(rows.reduce((sum, row) => sum + jobProgressPercent(row), 0) / total)))
  const done = success + failed + skipped
  const waiting = Math.max(0, total - done - running)
  const hasFailures = failed > 0
  return {
    total,
    success,
    failed,
    skipped,
    running,
    waiting,
    percent,
    summary: `成功 ${success}/${total} · 失败 ${failed} · 运行中 ${running}${waiting ? ` · 等待 ${waiting}` : ''}${skipped ? ` · 已跳过 ${skipped}` : ''}`,
    color: hasFailures ? 'text-rose-300' : (done === total ? 'text-emerald-300' : 'text-blue-300'),
    barClass: hasFailures ? 'bg-rose-400' : (done === total ? 'bg-emerald-400' : 'bg-blue-400'),
  }
})
const failureReasonStats = computed(() => {
  const counts = new Map()
  for (const row of currentActivationRows.value) {
    if (String(row.status || '').toLowerCase() !== 'failed') continue
    const reason = failureReasonText(row)
    counts.set(reason, (counts.get(reason) || 0) + 1)
  }
  const total = [...counts.values()].reduce((sum, count) => sum + count, 0)
  return [...counts.entries()]
    .map(([reason, count]) => ({
      reason,
      count,
      percent: total ? Math.round((count / total) * 100) : 0,
    }))
    .sort((left, right) => right.count - left.count || left.reason.localeCompare(right.reason, 'zh-CN'))
})
const configStatusText = computed(() => config.value.configured ? `已配置 · ${config.value.api_key_masked || 'API Key 已保存'}` : '尚未配置 API Key')
const configuredConcurrency = computed(() => clampNumber(options.value?.concurrency, 1, 99, defaultPayPalIceOptions().concurrency))
const iceConcurrencyLimit = computed(() => {
  const limit = Number(iceAccount.value?.concurrency_limit)
  return Number.isFinite(limit) && limit > 0 ? limit : null
})
const effectiveConcurrencyText = computed(() => {
  const base = Math.min(configuredConcurrency.value, iceConcurrencyLimit.value || configuredConcurrency.value)
  const phoneLimit = options.value.use_pool ? Number(phonePoolStats.value.available || 0) : null
  const effective = phoneLimit !== null ? Math.min(base, Math.max(0, phoneLimit)) : base
  const parts = [`前端 ${configuredConcurrency.value}`]
  if (iceConcurrencyLimit.value) parts.push(`ICE ${iceConcurrencyLimit.value}`)
  if (phoneLimit !== null) parts.push(`手机号 ${phoneLimit}`)
  parts.push(`实际 ${effective}`)
  return parts.join(' / ')
})
const oauthEmailSummary = computed(() => {
  const provider = oauthEmailMailProvider.value || '未选择邮件供应商'
  if (oauthEmailMailProvider.value === 'luckmail') {
    return `${provider} / ${oauthEmailLuckmailEmailType.value || 'ms_imap'} / ${oauthEmailLuckmailDomain.value ? `@${oauthEmailLuckmailDomain.value}` : '自动分配'}`
  }
  const domain = oauthEmailMailProvider.value && oauthEmailMailProvider.value !== 'outlook'
    ? (oauthEmailDomain.value ? `@${oauthEmailDomain.value}` : '未选域名')
    : '供应商默认邮箱'
  return `${provider} / ${domain}`
})
const boardCards = computed(() => [
  { label: 'ICE 剩余额度', value: iceAccount.value?.quota_remaining ?? '-', meta: iceAccount.value ? `总额 ${iceAccount.value.quota_total ?? '-'} / 已用 ${iceAccount.value.quota_used ?? '-'}` : '保存配置后读取', color: 'text-blue-400' },
  { label: '激活成功数', value: successCount.value, meta: `本轮 ${overallProgress.value.total} 个任务`, color: 'text-emerald-400' },
  { label: '运行中任务', value: activeJobCount.value, meta: effectiveConcurrencyText.value, color: 'text-amber-300' },
  { label: '整体进度', value: `${overallProgress.value.percent}%`, meta: `本轮 ${successCount.value} 成功 / ${overallProgress.value.total} 任务`, color: overallProgress.value.color },
])

const luckmailEmailTypeOptions = [
  { value: 'ms_imap', label: '微软 IMAP 邮箱' },
  { value: 'ms_graph', label: '微软 Graph 邮箱' },
  { value: 'microsoft', label: '微软邮箱' },
  { value: 'self_built', label: '自建邮箱' },
]

const luckmailDomainOptions = [
  { value: '', label: '自动分配' },
  { value: 'outlook.com', label: 'outlook.com' },
  { value: 'outlook.de', label: 'outlook.de' },
  { value: 'outlook.fr', label: 'outlook.fr' },
  { value: 'outlook.jp', label: 'outlook.jp' },
  { value: 'outlook.my', label: 'outlook.my' },
  { value: 'hotmail.com', label: 'hotmail.com' },
  { value: 'hotmail.de', label: 'hotmail.de' },
  { value: 'live.com', label: 'live.com' },
]

function filterAccounts(rows, keyword) {
  const query = String(keyword || '').trim().toLowerCase()
  return query ? rows.filter(item => String(item.email || '').toLowerCase().includes(query)) : rows
}

function isUsableFreeAccount(account) {
  if (!account?.email || account?.is_main_account) return false
  if (String(account?.account_type || '').toLowerCase() !== 'free') return false
  if (!hasUsableAccountAuth(account)) return false
  const status = String(account?.status || '').toLowerCase()
  if (['fail', 'auth_invalid', 'orphan', 'pending'].includes(status)) return false
  if (status === 'standby' && !hasUsableCodexAuth(account)) return false
  return true
}

function hasUsableAccountAuth(account) {
  if (account?.auth_session_file) return true
  return hasUsableCodexAuth(account)
}

function hasUsableCodexAuth(account) {
  if (account?.has_codex_auth_file !== undefined) return Boolean(account.has_codex_auth_file)
  return Boolean(account?.codex_auth_file || account?.auth_file)
}

function setMessage(text, ok = true) {
  message.value = text
  messageOk.value = ok
}

function defaultPayPalIceOptions() {
  return {
    proxy: '',
    proxy_jp: '',
    phone: '',
    sms_api: '',
    use_pool: true,
    pplink_retry: 3,
    job_retry: 1,
    concurrency: 5,
    otp_timeout: 180,
    auto_oauth_login: false,
  }
}

function normalizePayPalIceOptions(value) {
  const defaults = defaultPayPalIceOptions()
  const source = value && typeof value === 'object' ? value : {}
  return {
    proxy: String(source.proxy || ''),
    proxy_jp: String(source.proxy_jp || ''),
    phone: String(source.phone || ''),
    sms_api: String(source.sms_api || ''),
    use_pool: source.use_pool === undefined ? defaults.use_pool : Boolean(source.use_pool),
    pplink_retry: clampNumber(source.pplink_retry, 0, 10, defaults.pplink_retry),
    job_retry: clampNumber(source.job_retry, 0, 5, defaults.job_retry),
    concurrency: clampNumber(source.concurrency, 1, 99, defaults.concurrency),
    otp_timeout: clampNumber(source.otp_timeout, 30, 900, defaults.otp_timeout),
    auto_oauth_login: Boolean(source.auto_oauth_login),
  }
}

function clampNumber(value, min, max, fallback) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.max(min, Math.min(max, parsed))
}

function normalizeStoredEmails(value) {
  const seen = new Set()
  return (Array.isArray(value) ? value : [])
    .map(email => String(email || '').trim().toLowerCase())
    .filter(email => {
      if (!email || seen.has(email)) return false
      seen.add(email)
      return true
    })
}

function normalizeOauthLoginProgressEvents(value) {
  return (Array.isArray(value) ? value : [])
    .map(event => ({
      stage: String(event?.stage || ''),
      message: String(event?.message || ''),
      email: String(event?.email || ''),
      level: String(event?.level || ''),
      current: event?.current ?? null,
      total: event?.total ?? null,
      updated_at: event?.updated_at ?? null,
    }))
    .filter(event => event.stage || event.message)
    .slice(-12)
}

function normalizeRowTimestamp(value) {
  if (value === null || value === undefined || value === '') return 0
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return parsed > 1_000_000_000_000 ? Math.floor(parsed / 1000) : parsed
}

function formatTimestamp(value) {
  const timestamp = normalizeRowTimestamp(value)
  if (!timestamp) return '-'
  const date = new Date(timestamp * 1000)
  if (Number.isNaN(date.getTime())) return '-'
  const pad = part => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function formatBindTime(row) {
  const status = String(row?.status || '').toLowerCase()
  const resultCode = String(row?.resultCode || '').toUpperCase()
  if (status !== 'success' && resultCode !== 'SUCCESS') return '-'
  return formatTimestamp(row?.finishedAt || row?.finished_at)
}

function resultRowSortTimestamp(row) {
  return normalizeRowTimestamp(row?.sortAt || row?.sort_at)
    || normalizeRowTimestamp(row?.createdAt || row?.created_at)
    || normalizeRowTimestamp(row?.updatedAt || row?.updated_at)
    || 0
}

function activationRowSucceeded(row) {
  return String(row?.status || '').toLowerCase() === 'success'
    || String(row?.resultCode || '').toUpperCase() === 'SUCCESS'
}

function preferActivationProgressRow(candidate, existing, candidateTimestamp, existingTimestamp) {
  const candidateSuccess = activationRowSucceeded(candidate)
  const existingSuccess = activationRowSucceeded(existing)
  if (candidateSuccess !== existingSuccess) return candidateSuccess
  if (Boolean(candidate?.jobId) !== Boolean(existing?.jobId)) return Boolean(candidate?.jobId)
  return candidateTimestamp >= existingTimestamp
}

function normalizeResultRows(rows) {
  return (Array.isArray(rows) ? rows : [])
    .map(normalizeResultRow)
    .filter(Boolean)
    .sort((a, b) => resultRowSortTimestamp(b) - resultRowSortTimestamp(a))
    .slice(0, PAYPAL_ICE_ROWS_LIMIT)
}

function trimResultRows() {
  resultRows.value = normalizeResultRows(resultRows.value)
}

function loadPayPalIceFormState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PAYPAL_ICE_FORM_STATE_KEY) || '{}')
    const input = parsed?.inputSource === 'token' ? 'token' : 'account'
    const nextMode = parsed?.mode === 'batch' ? 'batch' : 'single'
    return {
      inputSource: input,
      mode: nextMode,
      singleEmail: String(parsed?.singleEmail || '').trim().toLowerCase(),
      batchEmails: normalizeStoredEmails(parsed?.batchEmails),
      batchSelectCount: clampNumber(parsed?.batchSelectCount, 1, 10000, 10),
      options: normalizePayPalIceOptions(parsed?.options),
    }
  } catch (_) {
    return {
      inputSource: 'account',
      mode: 'single',
      singleEmail: '',
      batchEmails: [],
      batchSelectCount: 10,
      options: defaultPayPalIceOptions(),
    }
  }
}

function savePayPalIceFormState() {
  try {
    localStorage.setItem(
      PAYPAL_ICE_FORM_STATE_KEY,
      JSON.stringify({
        inputSource: inputSource.value === 'token' ? 'token' : 'account',
        mode: mode.value === 'batch' ? 'batch' : 'single',
        singleEmail: String(singleEmail.value || '').trim().toLowerCase(),
        batchEmails: normalizeStoredEmails(batchEmails.value),
        batchSelectCount: clampNumber(batchSelectCount.value, 1, 10000, 10),
        options: normalizePayPalIceOptions(options.value),
      }),
    )
  } catch (_) {
    // localStorage can be unavailable in private or restricted browser contexts.
  }
}

function normalizeResultRow(row) {
  const source = row && typeof row === 'object' ? row : {}
  const email = String(source.email || '').trim()
  if (!email) return null
  return {
    email,
    sortAt: normalizeRowTimestamp(source.sortAt || source.sort_at)
      || normalizeRowTimestamp(source.createdAt || source.created_at)
      || normalizeRowTimestamp(source.updatedAt || source.updated_at),
    createdAt: normalizeRowTimestamp(source.createdAt || source.created_at),
    updatedAt: normalizeRowTimestamp(source.updatedAt || source.updated_at),
    finishedAt: normalizeRowTimestamp(source.finishedAt || source.finished_at),
    activationRunId: String(source.activationRunId || ''),
    activationItemKey: String(source.activationItemKey || ''),
    activationRetryCount: clampNumber(source.activationRetryCount, 0, 5, 0),
    trialStatus: String(source.trialStatus || ''),
    status: String(source.status || ''),
    billingStatus: String(source.billingStatus || ''),
    resultCode: String(source.resultCode || ''),
    resourceMode: String(source.resourceMode || ''),
    progressPercent: normalizeProgressPercent(source.progressPercent),
    progressStage: String(source.progressStage || ''),
    progressMessage: String(source.progressMessage || ''),
    progressAvailable: Boolean(source.progressAvailable),
    otpPending: Boolean(source.otpPending),
    error: String(source.error || ''),
    jobId: String(source.jobId || ''),
    localCancelled: Boolean(source.localCancelled || source.local_cancelled),
    autoOauthLogin: Boolean(source.autoOauthLogin),
    oauthLoginTaskId: String(source.oauthLoginTaskId || ''),
    oauthLoginStatus: String(source.oauthLoginStatus || ''),
    oauthLoginError: String(source.oauthLoginError || ''),
    oauthLoginResultEmail: String(source.oauthLoginResultEmail || ''),
    oauthLoginProgressStage: String(source.oauthLoginProgressStage || ''),
    oauthLoginProgressMessage: String(source.oauthLoginProgressMessage || ''),
    oauthLoginProgressEmail: String(source.oauthLoginProgressEmail || ''),
    oauthLoginProgressEvents: normalizeOauthLoginProgressEvents(source.oauthLoginProgressEvents),
  }
}

function loadStoredResultRows() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PAYPAL_ICE_ROWS_STATE_KEY) || '[]')
    if (!Array.isArray(parsed)) return []
    return normalizeResultRows(parsed)
  } catch (_) {
    return []
  }
}

function saveResultRowsState() {
  try {
    localStorage.setItem(
      PAYPAL_ICE_ROWS_STATE_KEY,
      JSON.stringify(normalizeResultRows(resultRows.value)),
    )
  } catch (_) {
    // localStorage can be unavailable in private or restricted browser contexts.
  }
}

function normalizeActivationRunItem(item) {
  const source = item && typeof item === 'object' ? item : {}
  const key = activationItemKey(source)
  if (!key) return null
  const email = String(source.email || key).trim().toLowerCase()
  return {
    key,
    label: String(source.label || email || key).trim(),
    clientRef: String(source.clientRef || email || key).trim(),
    email,
  }
}

function normalizeActivationRunItems(items) {
  const seen = new Set()
  return (Array.isArray(items) ? items : [])
    .map(normalizeActivationRunItem)
    .filter(item => {
      if (!item || seen.has(item.key)) return false
      seen.add(item.key)
      return true
    })
}

function loadStoredActivationRunState() {
  try {
    const parsed = JSON.parse(localStorage.getItem(PAYPAL_ICE_RUN_STATE_KEY) || '{}')
    const runId = String(parsed?.runId || '').trim()
    if (!runId) return inferStoredActivationRunState()
    return {
      runId,
      total: Math.max(0, Number(parsed?.total || 0)),
      retryRound: Math.max(0, Number(parsed?.retryRound || 0)),
      inputSource: parsed?.inputSource === 'account' ? 'account' : '',
      items: parsed?.inputSource === 'account' ? normalizeActivationRunItems(parsed?.items) : [],
    }
  } catch (_) {
    return inferStoredActivationRunState()
  }
}

function inferStoredActivationRunState() {
  try {
    const rows = normalizeResultRows(JSON.parse(localStorage.getItem(PAYPAL_ICE_ROWS_STATE_KEY) || '[]'))
    const byRun = new Map()
    for (const row of rows) {
      const runId = String(row.activationRunId || '').trim()
      if (!runId) continue
      const current = byRun.get(runId) || { runId, total: 0, latest: 0, items: [] }
      current.total += 1
      current.latest = Math.max(current.latest, Number(row.sortAt || row.updatedAt || row.createdAt || 0))
      current.items.push({ key: row.activationItemKey || row.email, label: row.email, clientRef: row.email, email: row.activationItemKey || row.email })
      if (!row.localCancelled && String(row.status || '').toLowerCase() !== 'cancelled') {
        current.displayable = true
      }
      byRun.set(runId, current)
    }
    const latest = [...byRun.values()]
      .filter(run => run.displayable)
      .sort((a, b) => b.latest - a.latest)[0]
    if (!latest) return { runId: '', total: 0, retryRound: 0, inputSource: '', items: [] }
    const formState = loadPayPalIceFormState()
    return {
      runId: latest.runId,
      total: latest.total,
      retryRound: 0,
      inputSource: formState.inputSource === 'account' ? 'account' : '',
      items: formState.inputSource === 'account' ? normalizeActivationRunItems(latest.items) : [],
    }
  } catch (_) {
    return { runId: '', total: 0, retryRound: 0, inputSource: '', items: [] }
  }
}

function saveActivationRunState(items = null) {
  const runId = String(currentActivationRunId.value || '').trim()
  if (!runId) return
  const runInputSource = currentActivationInputSource.value === 'account' ? 'account' : 'token'
  const sourceItems = items || restoredActivationItems.value || (runInputSource === 'account' ? selectedItems.value : [])
  try {
    localStorage.setItem(
      PAYPAL_ICE_RUN_STATE_KEY,
      JSON.stringify({
        runId,
        total: Number(currentActivationTotal.value || 0),
        retryRound: Number(currentActivationRetryRound.value || 0),
        inputSource: runInputSource,
        items: runInputSource === 'account' ? normalizeActivationRunItems(sourceItems) : [],
        updatedAt: Date.now(),
      }),
    )
  } catch (_) {
    // localStorage can be unavailable in private or restricted browser contexts.
  }
}

function discardActivationRunState() {
  currentActivationRunId.value = ''
  currentActivationTotal.value = 0
  currentActivationRetryRound.value = 0
  currentActivationInputSource.value = ''
  restoredActivationItems.value = null
  try {
    localStorage.removeItem(PAYPAL_ICE_RUN_STATE_KEY)
  } catch (_) {
    // localStorage can be unavailable in private or restricted browser contexts.
  }
}

function readStoredOauthEmailConfig() {
  try {
    return JSON.parse(localStorage.getItem(OAUTH_EMAIL_STORAGE_KEY) || '{}')
  } catch (_) {
    return {}
  }
}

async function loadOauthEmailConfig(force = false) {
  if (oauthEmailLoaded.value && !force) return
  oauthEmailLoading.value = true
  try {
    const [mailCfg, domainCfg] = await Promise.all([
      api.getMailProviderConfig().catch(() => ({ provider_options: [] })),
      api.getRegisterDomain().catch(() => ({ domain: '', domains: [] })),
    ])
    const saved = readStoredOauthEmailConfig()
    const mailOptions = Array.isArray(mailCfg.provider_options) ? mailCfg.provider_options : []
    oauthEmailMailProviderOptions.value = mailOptions
      .map(item => ({
        value: String(item?.value || '').trim(),
        label: String(item?.label || item?.value || '').trim(),
      }))
      .filter(item => item.value)
    oauthEmailMailProvider.value = saved.mail_provider || mailCfg.provider || oauthEmailMailProviderOptions.value[0]?.value || ''
    oauthEmailLuckmailEmailType.value = saved.luckmail_email_type || oauthEmailLuckmailEmailType.value
    oauthEmailLuckmailDomain.value = saved.luckmail_preferred_domain || oauthEmailLuckmailDomain.value

    const domains = Array.isArray(domainCfg.domains) && domainCfg.domains.length
      ? domainCfg.domains
      : (domainCfg.domain ? [domainCfg.domain] : [])
    oauthEmailDomainOptions.value = domains.map(item => String(item || '').trim()).filter(Boolean)
    oauthEmailDomain.value = saved.email_domain || saved.domain || oauthEmailDomainOptions.value[0] || ''
    oauthEmailLoaded.value = true
  } finally {
    oauthEmailLoading.value = false
  }
}

function saveOauthEmailConfig() {
  oauthEmailSaving.value = true
  try {
    localStorage.setItem(OAUTH_EMAIL_STORAGE_KEY, JSON.stringify(currentOauthEmailConfig()))
    setMessage('ICE 自动补登录邮箱配置已保存')
  } catch (error) {
    setMessage(`保存邮箱配置失败: ${error.message}`, false)
  } finally {
    oauthEmailSaving.value = false
  }
}

function ensureRow(email) {
  let row = resultRows.value.find(item => item.email === email)
  const now = Math.floor(Date.now() / 1000)
  if (!row) {
    row = {
      email,
      sortAt: now,
      createdAt: now,
      updatedAt: now,
      finishedAt: 0,
      activationRunId: '',
      activationItemKey: '',
      trialStatus: '',
      status: '',
      billingStatus: '',
      resultCode: '',
      resourceMode: '',
      progressPercent: null,
      progressStage: '',
      progressMessage: '',
      progressAvailable: false,
      otpPending: false,
      error: '',
      jobId: '',
      localCancelled: false,
      autoOauthLogin: false,
      oauthLoginTaskId: '',
      oauthLoginStatus: '',
      oauthLoginError: '',
      oauthLoginResultEmail: '',
      oauthLoginProgressStage: '',
      oauthLoginProgressMessage: '',
      oauthLoginProgressEmail: '',
      oauthLoginProgressEvents: [],
    }
    resultRows.value.unshift(row)
    trimResultRows()
  } else if (!row.createdAt) {
    row.createdAt = now
    row.sortAt = row.sortAt || now
  }
  return row
}

function rowKey(row) {
  return row.jobId || row.email
}

function rowFromJob(item) {
  const label = item.client_ref || item.job_id || 'ICE job'
  return {
    email: label,
    sortAt: normalizeRowTimestamp(item.created_at || item.updated_at),
    createdAt: normalizeRowTimestamp(item.created_at),
    updatedAt: normalizeRowTimestamp(item.updated_at || item.created_at),
    finishedAt: normalizeRowTimestamp(item.finished_at),
    activationRunId: '',
    activationItemKey: '',
    trialStatus: '',
    status: item.status || '',
    billingStatus: item.billing_status || '',
    resultCode: item.result_code || '',
    resourceMode: item.resource_mode || '',
    progressPercent: normalizeProgressPercent(item.progress_percent),
    progressStage: item.progress_stage || '',
    progressMessage: item.progress_message || '',
    progressAvailable: Boolean(item.progress_available),
    otpPending: Boolean(item.otp_pending),
    error: item.error_message || '',
    jobId: item.job_id || '',
    localCancelled: Boolean(item.local_cancelled),
    autoOauthLogin: Boolean(item.auto_oauth_login),
    oauthLoginTaskId: item.oauth_login_task_id || '',
    oauthLoginStatus: item.oauth_login_status || '',
    oauthLoginError: item.oauth_login_error || '',
    oauthLoginResultEmail: item.oauth_login_result_email || '',
    oauthLoginProgressStage: item.oauth_login_progress_stage || '',
    oauthLoginProgressMessage: item.oauth_login_progress_message || '',
    oauthLoginProgressEmail: item.oauth_login_progress_email || '',
    oauthLoginProgressEvents: normalizeOauthLoginProgressEvents(item.oauth_login_progress_events),
  }
}

function isTerminalActivationStatus(status) {
  return ['success', 'failed', 'skipped', 'cancelled'].includes(String(status || '').toLowerCase())
}

function rowNeedsRefresh(row) {
  if (!row?.jobId) return false
  if (row.localCancelled) return false
  if (!isTerminalActivationStatus(row.status)) return true
  return row.autoOauthLogin && ['pending', 'queued', 'submitted', 'running', 'waiting', 'retrying'].includes(row.oauthLoginStatus)
}

function currentOauthEmailConfig() {
  const saved = readStoredOauthEmailConfig()
  if (oauthEmailLoaded.value) {
    return {
      mail_provider: oauthEmailMailProvider.value,
      luckmail_email_type: oauthEmailLuckmailEmailType.value,
      luckmail_preferred_domain: oauthEmailLuckmailDomain.value,
      email_domain: oauthEmailDomain.value,
    }
  }
  return {
    mail_provider: oauthEmailMailProvider.value || saved.mail_provider || '',
    luckmail_email_type: oauthEmailLuckmailEmailType.value || saved.luckmail_email_type || '',
    luckmail_preferred_domain: oauthEmailLuckmailDomain.value || saved.luckmail_preferred_domain || '',
    email_domain: oauthEmailDomain.value || saved.email_domain || saved.domain || '',
  }
}

function storedOauthLoginConfig() {
  const emailCfg = currentOauthEmailConfig()
  const mailProvider = String(emailCfg.mail_provider || '').trim()
  let proxyCfg = {}
  try {
    proxyCfg = JSON.parse(localStorage.getItem('autotoken.dashboard.oauthProxy') || '{}')
  } catch (_) {
    proxyCfg = {}
  }
  const payload = {
    protocol_only: true,
    bind_email: true,
  }
  if (mailProvider) payload.mail_provider = mailProvider
  if (mailProvider === 'luckmail') {
    if (emailCfg.luckmail_email_type) payload.luckmail_email_type = emailCfg.luckmail_email_type
    if (emailCfg.luckmail_preferred_domain) payload.luckmail_preferred_domain = emailCfg.luckmail_preferred_domain
  } else if (mailProvider && mailProvider !== 'outlook' && (emailCfg.email_domain || emailCfg.domain)) {
    payload.email_domain = emailCfg.email_domain || emailCfg.domain
  }
  if (proxyCfg.enabled) {
    if (proxyCfg.mode === 'pool') payload.proxy_pool_text = proxyCfg.proxyPoolText || ''
    else if (proxyCfg.mode === 'api') {
      payload.proxy_api_provider = proxyCfg.proxyApiProvider || 'cliproxy'
      payload.proxy_url = proxyCfg.proxyUrl || ''
    } else {
      payload.proxy_url = proxyCfg.proxyUrl || ''
    }
  }
  return payload
}

async function loadJobHistory() {
  try {
    const result = await api.listPayPalIceJobs()
    const existingByJobId = new Map()
    const existingByEmail = new Map()
    for (const row of resultRows.value) {
      if (row.jobId) existingByJobId.set(row.jobId, row)
      if (row.email) existingByEmail.set(String(row.email || '').trim().toLowerCase(), row)
    }
    const rows = Array.isArray(result?.items)
      ? result.items.map(rowFromJob).map(row => mergeJobHistoryRow(row, existingByJobId, existingByEmail))
      : []
    const jobIds = new Set(rows.map(row => row.jobId).filter(Boolean))
    const labels = new Set(rows.map(row => row.email).filter(Boolean))
    const existingRows = resultRows.value.filter(row => {
      if (row.jobId) return !jobIds.has(row.jobId)
      return !labels.has(row.email)
    })
    resultRows.value = normalizeResultRows([...rows, ...existingRows])
    reconcileCurrentActivationState()
  } catch (error) {
    setMessage(`读取 ICE 任务历史失败: ${error.message}`, false)
  }
}

function mergeJobHistoryRow(row, existingByJobId, existingByEmail) {
  const existingByExactJob = row.jobId ? existingByJobId.get(row.jobId) : null
  const existingByLabel = existingByEmail.get(String(row.email || '').trim().toLowerCase())
  const existing = existingByExactJob || (!existingByLabel?.jobId ? existingByLabel : null)
  if (!existing) return row
  return {
    ...existing,
    ...row,
    sortAt: existing.sortAt || row.sortAt,
    createdAt: existing.createdAt || row.createdAt,
    finishedAt: existing.finishedAt || row.finishedAt,
    activationRunId: existing.activationRunId || row.activationRunId,
    activationItemKey: existing.activationItemKey || row.activationItemKey,
    activationRetryCount: Math.max(
      Number(existing.activationRetryCount || 0),
      Number(row.activationRetryCount || 0),
    ),
    trialStatus: existing.trialStatus || row.trialStatus,
  }
}

function shortTokenLabel(token, index) {
  const value = String(token || '').trim()
  if (!value) return `Token ${index + 1}`
  if (value.length <= 18) return `Token ${index + 1} · ${value}`
  return `Token ${index + 1} · ${value.slice(0, 8)}...${value.slice(-6)}`
}

function parseAccessTokenEntries(text) {
  const seen = new Set()
  return String(text || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      let label = ''
      let token = line
      if (line.includes('----')) {
        const parts = line.split('----')
        label = parts.shift().trim()
        token = parts.join('----').trim()
      } else if (line.includes('|')) {
        const parts = line.split('|')
        label = parts.shift().trim()
        token = parts.join('|').trim()
      }
      token = token.replace(/^Bearer\s+/i, '').trim()
      const key = token.toLowerCase()
      if (!token || seen.has(key)) return null
      seen.add(key)
      return {
        key: `token:${key}`,
        label: label || shortTokenLabel(token, index),
        clientRef: label || `manual-token-${index + 1}`,
        token,
      }
    })
    .filter(Boolean)
}

function extractAccessToken(payload) {
  return String(
    payload?.codex_auth?.tokens?.access_token
    || payload?.codex_auth?.access_token
    || payload?.tokens?.access_token
    || payload?.access_token
    || ''
  ).trim()
}

async function tokenForEmail(email) {
  const payload = await api.getCodexAuth(email)
  const token = extractAccessToken(payload)
  if (!token) throw new Error('本地 auth 文件没有 access_token')
  return token
}

async function tokenForItem(item) {
  if (item.token) return item.token
  return tokenForEmail(item.email)
}

function sleep(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

async function runPool(items, worker, concurrencyOverride = null) {
  const pending = [...items]
  const requestedConcurrency = clampNumber(concurrencyOverride ?? configuredConcurrency.value, 1, 99, configuredConcurrency.value)
  const concurrency = Math.min(requestedConcurrency, iceConcurrencyLimit.value || requestedConcurrency)
  await Promise.all(Array.from({ length: Math.min(concurrency, pending.length) }, async () => {
    while (pending.length) {
      const item = pending.shift()
      await worker(item)
    }
  }))
}

async function loadConfig() {
  try {
    config.value = await api.getPayPalIceConfig()
    configDraft.value.base_url = config.value.base_url || 'https://plus.iceaix.com'
  } catch (error) {
    setMessage(`读取 ICE 配置失败: ${error.message}`, false)
  }
}

async function saveConfig() {
  configSaving.value = true
  try {
    config.value = await api.savePayPalIceConfig(configDraft.value)
    configDraft.value.api_key = ''
    setMessage(config.value.message || 'PayPal ICE 配置已保存')
    await loadIceAccount()
  } catch (error) {
    setMessage(`保存 ICE 配置失败: ${error.message}`, false)
  } finally {
    configSaving.value = false
  }
}

async function loadIceAccount() {
  await refreshIceAccount({ force: true })
}

async function refreshIceAccount(options = {}) {
  const force = Boolean(options?.force)
  const silent = Boolean(options?.silent)
  if (!config.value.configured) return
  const now = Date.now()
  if (!force && now - lastIceAccountRefreshAt < PAYPAL_ICE_ACCOUNT_REFRESH_INTERVAL_MS) return
  if (iceAccountRefreshPromise) return iceAccountRefreshPromise
  lastIceAccountRefreshAt = now
  iceAccountRefreshPromise = (async () => {
    try {
      iceAccount.value = await api.getPayPalIceAccount()
    } catch (error) {
      if (!silent) {
        iceAccount.value = null
        setMessage(`读取 ICE 额度失败: ${error.message}`, false)
      }
    } finally {
      iceAccountRefreshPromise = null
    }
  })()
  return iceAccountRefreshPromise
}

async function refreshIceAccountSilently(options = {}) {
  try {
    await refreshIceAccount({ ...options, silent: true })
  } catch (_) {
    // Silent background quota refresh should not interrupt running tasks.
  }
}

function activationRunStartedAt(runId) {
  const match = /^ice-(\d+)/.exec(String(runId || '').trim())
  return match ? Math.floor(Number(match[1]) / 1000) : 0
}

function reconcileCurrentActivationState() {
  const runId = String(currentActivationRunId.value || '').trim()
  if (!runId) return
  const runItems = activationSchedulerItems()
  const itemKeys = new Set(runItems.map(activationItemKey).filter(Boolean))
  const runStartedAt = activationRunStartedAt(runId)
  const activatedByEmail = paypalIceActivatedAccountMap(runId)
  const activatedByJobId = new Map()
  for (const account of activatedByEmail.values()) {
    const jobId = String(account?.last_bind_task_id || '').trim()
    if (jobId) activatedByJobId.set(jobId, account)
  }

  for (const item of runItems) {
    const key = activationItemKey(item)
    const account = activatedByEmail.get(key)
    if (!account) continue
    const existing = resultRows.value.find(row => (
      row.activationRunId === runId
      && String(row.activationItemKey || row.email || '').trim().toLowerCase() === key
    ))
    if (existing) continue
    const row = ensureRow(item.label)
    row.activationRunId = runId
    row.activationItemKey = key
    row.createdAt = row.createdAt || runStartedAt || Math.floor(Date.now() / 1000)
    row.sortAt = row.sortAt || row.createdAt
  }

  for (const row of resultRows.value) {
    const key = String(row.activationItemKey || row.email || '').trim().toLowerCase()
    const rowAt = normalizeRowTimestamp(row.createdAt || row.updatedAt || row.sortAt)
    const matchesRunItem = itemKeys.has(key)
    const matchesRunTime = !runStartedAt || !rowAt || rowAt >= runStartedAt - 60
    const accountByJob = row.jobId ? activatedByJobId.get(row.jobId) : null
    const belongsToRun = row.activationRunId === runId
      || (Boolean(row.jobId) && matchesRunItem && matchesRunTime)
      || Boolean(accountByJob && matchesRunItem)
    if (!belongsToRun) continue

    row.activationRunId = runId
    row.activationItemKey = key
    const account = accountByJob || activatedByEmail.get(key)
    if (!account) continue
    const bindAt = normalizeRowTimestamp(account.plus_bound_at || account.last_bind_at)
    row.status = 'success'
    row.resultCode = 'SUCCESS'
    row.progressPercent = 100
    row.progressStage = 'account_reconciled'
    row.progressMessage = '账号池已确认 PayPal ICE 激活成功'
    row.progressAvailable = true
    row.otpPending = false
    row.error = ''
    row.finishedAt = bindAt || row.finishedAt || Math.floor(Date.now() / 1000)
    row.updatedAt = Math.max(row.updatedAt || 0, bindAt || 0)
  }
}

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const result = await api.getAccounts({ includeSessionStubs: true })
    accounts.value = Array.isArray(result) ? result : (result?.accounts || [])
    reconcileCurrentActivationState()
    const availableEmails = new Set(accountOptions.value.map(account => String(account.email || '').trim().toLowerCase()))
    if (singleEmail.value && !availableEmails.has(String(singleEmail.value || '').trim().toLowerCase())) {
      singleEmail.value = ''
    }
    batchEmails.value = selectedBatchEmails.value.filter(email => availableEmails.has(email))
  } catch (error) {
    setMessage(`读取号池失败: ${error.message}`, false)
  } finally {
    loadingAccounts.value = false
  }
}

function validateSelection(requireSms = false) {
  if (!selectedItems.value.length) {
    throw new Error(inputSource.value === 'token' ? '请先输入 Access Token' : '请先选择账号')
  }
  if (!requireSms) return
  if (options.value.use_pool) {
    if (Number(phonePoolStats.value.available || 0) < 1) {
      throw new Error('手机号池没有可用号码')
    }
    return
  }
  if ((options.value.phone && !options.value.sms_api) || (!options.value.phone && options.value.sms_api)) {
    throw new Error('自定义接码必须同时填写手机号和接码 API')
  }
  if (!options.value.phone || !options.value.sms_api) {
    throw new Error('手动接码必须填写手机号和接码 API')
  }
}

async function checkTrials() {
  trialBusy.value = true
  try {
    validateSelection(false)
    const items = [...selectedItems.value]
    await runPool(items, async (item) => {
      const row = ensureRow(item.label)
      row.trialStatus = 'checking'
      row.error = ''
      try {
        const token = await tokenForItem(item)
        const result = await api.checkPayPalIceTrial({ token, proxy_jp: options.value.proxy_jp || '' })
        const eligible = applyTrialCheckResult(row, result)
        if (!eligible) await handleIneligibleTrial(item, row, token)
      } catch (error) {
        row.trialStatus = 'error'
        row.error = error.message
      }
    })
    setMessage(`Plus 试用资格检测完成：${items.length} 个账号`)
  } catch (error) {
    setMessage(error.message, false)
  } finally {
    trialBusy.value = false
  }
}

function activationConcurrencyLimit() {
  const requested = configuredConcurrency.value
  let limit = Math.min(requested, iceConcurrencyLimit.value || requested)
  if (options.value.use_pool) {
    limit = Math.min(limit, Number(phonePoolStats.value.available || 0))
  }
  return Math.max(0, limit)
}

function activationItemKey(item) {
  return String(item?.key || item?.clientRef || item?.email || item?.label || '').trim().toLowerCase()
}

async function removeAccountFromIcePool(item, row = null) {
  if (inputSource.value !== 'account') return
  const email = activationItemKey(item)
  if (!email) return
  accounts.value = accounts.value.filter(account => String(account.email || '').trim().toLowerCase() !== email)
  batchEmails.value = batchEmails.value.filter(value => String(value || '').trim().toLowerCase() !== email)
  if (String(singleEmail.value || '').trim().toLowerCase() === email) {
    singleEmail.value = ''
  }
  try {
    await api.deleteAccount(email)
    emit('refresh')
  } catch (error) {
    if (error.status === 404) {
      emit('refresh')
      return
    }
    const deleteError = `号池删除失败: ${error.message}`
    if (row) {
      row.error = row.error ? `${row.error}；${deleteError}` : deleteError
    } else {
      setMessage(deleteError, false)
    }
  }
}

function activationRunCancelled(runId = currentActivationRunId.value) {
  const id = String(runId || '').trim()
  if (id && cancelledActivationRunIds.has(id)) return true
  return Boolean(activationCancelRequested.value && (!id || currentActivationRunId.value === id))
}

function activationRowsToCancel() {
  const runId = String(currentActivationRunId.value || '').trim()
  const runRows = runId ? resultRows.value.filter(row => row.activationRunId === runId) : []
  if (runRows.length) return runRows
  return resultRows.value.filter(row => {
    if (row.localCancelled) return false
    if (rowNeedsRefresh(row)) return true
    return row.autoOauthLogin && ['pending', 'queued', 'submitted', 'running', 'waiting', 'retrying'].includes(row.oauthLoginStatus)
  })
}

function markActivationRowsCancelled(rows) {
  for (const row of resultRows.value) {
    if (!rows.includes(row)) continue
    const submitted = Boolean(row.jobId)
    const iceTerminal = isTerminalActivationStatus(row.status) || activationRowSucceeded(row)
    if (!submitted || !iceTerminal) {
      row.localCancelled = submitted
      row.status = 'cancelled'
      row.progressPercent = 100
      row.progressStage = 'cancelled'
      row.progressMessage = submitted ? '已本地取消 PayPal ICE 任务' : '已取消，未提交到 ICE'
      row.progressAvailable = true
      row.error = submitted ? '已本地取消 PayPal ICE 任务' : '已取消，未提交到 ICE'
    }
    if (row.autoOauthLogin && !['completed', 'failed', 'cancelled'].includes(String(row.oauthLoginStatus || '').toLowerCase())) {
      row.oauthLoginStatus = 'cancelled'
      row.oauthLoginError = iceTerminal ? '已本地取消协议补登录' : '已本地取消 PayPal ICE 任务'
    }
  }
  saveResultRowsState()
}

function markPendingActivationRowsCancelled(runId) {
  const rows = resultRows.value.filter(row => {
    if (row.activationRunId !== runId || row.jobId) return false
    return ['pending', 'checking_trial', 'submitting', ''].includes(String(row.status || '').toLowerCase())
  })
  markActivationRowsCancelled(rows)
}

async function cancelActivationRun() {
  if (activationCancelRequested.value) return
  const rows = activationRowsToCancel()
  if (!rows.length && !activationBusy.value) return
  activationCancelRequested.value = true
  const runId = String(currentActivationRunId.value || '').trim()
  if (runId) cancelledActivationRunIds.add(runId)
  markActivationRowsCancelled(rows)
  discardActivationRunState()

  const jobIds = [...new Set(rows.map(row => String(row.jobId || '').trim()).filter(Boolean))]
  const oauthTaskIds = [...new Set(rows.map(row => String(row.oauthLoginTaskId || '').trim()).filter(Boolean))]
  const cancellations = []
  if (jobIds.length) cancellations.push(api.cancelPayPalIceJobs(jobIds))
  cancellations.push(...oauthTaskIds.map(taskId => api.cancelTask({ task_id: taskId })))
  const results = await Promise.allSettled(cancellations)
  const failed = results.filter(result => result.status === 'rejected')
  if (failed.length) {
    activationCancelRequested.value = false
    setMessage(`已停止本地 PayPal ICE 任务，但有 ${failed.length} 个取消请求失败，请刷新确认状态`, false)
    return
  }
  activationCancelRequested.value = false
  setMessage(jobIds.length ? `已停止本地 PayPal ICE 任务：${jobIds.length} 个已提交 job 不再刷新/补登录` : '已取消本次 PayPal ICE 任务')
}

function prepareActivationRunRow(item, runId, sortAt = null) {
  const key = activationItemKey(item)
  const row = ensureRow(item.label)
  const now = Math.floor(Date.now() / 1000)
  row.createdAt = row.createdAt || now
  row.sortAt = normalizeRowTimestamp(sortAt) || row.sortAt || now
  row.updatedAt = now
  row.activationRunId = runId
  row.activationItemKey = key
  row.activationRetryCount = 0
  row.trialStatus = row.trialStatus || ''
  row.status = 'pending'
  row.billingStatus = ''
  row.resultCode = ''
  row.resourceMode = ''
  row.progressPercent = null
  row.progressStage = ''
  row.progressMessage = ''
  row.progressAvailable = false
  row.otpPending = false
  row.error = ''
  row.jobId = ''
  row.autoOauthLogin = currentActivationInputSource.value === 'account' && Boolean(options.value.auto_oauth_login)
  row.oauthLoginTaskId = ''
  row.oauthLoginStatus = ''
  row.oauthLoginError = ''
  row.oauthLoginResultEmail = ''
  row.oauthLoginProgressStage = ''
  row.oauthLoginProgressMessage = ''
  row.oauthLoginProgressEmail = ''
  row.oauthLoginProgressEvents = []
  return row
}

function syncActivationRunRows(items, runId, preparedKeys, submittedKeys) {
  const currentKeys = new Set(items.map(activationItemKey).filter(Boolean))
  currentActivationTotal.value = Math.max(currentActivationTotal.value, currentKeys.size, submittedKeys.size)
  for (const item of items) {
    const key = activationItemKey(item)
    if (!key || preparedKeys.has(key)) continue
    prepareActivationRunRow(item, runId, Date.now() / 1000 - preparedKeys.size / 1000)
    preparedKeys.add(key)
  }
  currentActivationTotal.value = Math.max(currentActivationTotal.value, preparedKeys.size, submittedKeys.size)
  for (const row of resultRows.value) {
    if (row.activationRunId !== runId) continue
    const key = String(row.activationItemKey || row.email || '').trim().toLowerCase()
    if (currentKeys.has(key) || submittedKeys.has(key)) continue
    if (!row.jobId && ['pending', 'submitting', ''].includes(String(row.status || '').toLowerCase())) {
      row.activationRunId = ''
      row.activationItemKey = ''
      row.status = ''
      row.error = ''
    }
  }
  saveActivationRunState(items)
}

function existingActivationPreparedKeys(runId) {
  return new Set(resultRows.value
    .filter(row => row.activationRunId === runId)
    .map(row => String(row.activationItemKey || row.email || '').trim().toLowerCase())
    .filter(Boolean))
}

function paypalIceActivatedAccountMap(runId = currentActivationRunId.value) {
  const runStartedAt = activationRunStartedAt(runId)
  const activated = new Map()
  for (const account of accounts.value) {
    const email = String(account?.email || '').trim().toLowerCase()
    const accountType = String(account?.account_type || '').trim().toLowerCase()
    const bindProvider = String(account?.last_bind_provider || '').trim().toLowerCase()
    if (!email || accountType !== 'plus' || bindProvider !== 'paypal_ice') continue
    const bindAt = normalizeRowTimestamp(account.plus_bound_at || account.last_bind_at)
    if (runStartedAt && bindAt && bindAt < runStartedAt - 60) continue
    activated.set(email, account)
  }
  return activated
}

function activationRowSubmittedOrInFlight(row) {
  if (!row) return false
  if (row.jobId || isTerminalActivationStatus(row.status)) return true
  return ['checking_trial', 'submitting'].includes(String(row.status || '').toLowerCase())
}

function existingActivationSubmittedKeys(runId) {
  const submitted = new Set(resultRows.value
    .filter(row => row.activationRunId === runId && activationRowSubmittedOrInFlight(row))
    .map(row => String(row.activationItemKey || row.email || '').trim().toLowerCase())
    .filter(Boolean))
  const activated = paypalIceActivatedAccountMap(runId)
  for (const item of activationSchedulerItems()) {
    const key = activationItemKey(item)
    if (key && activated.has(key)) submitted.add(key)
  }
  return submitted
}

function activationSchedulerItems() {
  return restoredActivationItems.value?.length ? restoredActivationItems.value : selectedItems.value
}

function activationRetryLimit() {
  return clampNumber(options.value.job_retry, 0, 5, defaultPayPalIceOptions().job_retry)
}

function activationRetryCountForItem(runId, item) {
  const key = activationItemKey(item)
  const row = resultRows.value.find(candidate => (
    candidate.activationRunId === runId
    && String(candidate.activationItemKey || candidate.email || '').trim().toLowerCase() === key
  ))
  return clampNumber(row?.activationRetryCount, 0, 5, 0)
}

function inFlightActivationRowsCount(runId) {
  return resultRows.value.filter(row => {
    if (row.activationRunId !== runId || isTerminalActivationStatus(row.status)) return false
    const status = String(row.status || '').toLowerCase()
    return Boolean(row.jobId) || ['checking_trial', 'submitting'].includes(status)
  }).length
}

function resetStaleLocalSubmissionRows(runId) {
  for (const row of resultRows.value) {
    if (row.activationRunId !== runId || row.jobId) continue
    if (!['checking_trial', 'submitting'].includes(String(row.status || '').toLowerCase())) continue
    row.status = 'pending'
    row.progressPercent = 0
    row.progressStage = 'resume_pending'
    row.progressMessage = '页面刷新后等待重新提交'
    row.progressAvailable = true
    row.error = ''
  }
}

function pauseUnsubmittedActivationRows(runId) {
  for (const row of resultRows.value) {
    if (row.activationRunId !== runId || row.jobId || isTerminalActivationStatus(row.status)) continue
    row.status = 'cancelled'
    row.localCancelled = true
    row.progressPercent = 100
    row.progressStage = 'refresh_paused'
    row.progressMessage = '页面刷新后已暂停本地提交，未重新发起 ICE 任务'
    row.progressAvailable = true
    row.error = '页面刷新后已暂停本地提交，未重新发起 ICE 任务'
  }
}

function retryableFailedActivationItems(runId, items) {
  const retryLimit = activationRetryLimit()
  const retryableKeys = new Set(resultRows.value
    .filter(row => (
      row.activationRunId === runId
      && String(row.status || '').toLowerCase() === 'failed'
      && (row.jobId || row.trialStatus === 'eligible')
      && clampNumber(row.activationRetryCount, 0, 5, 0) < retryLimit
    ))
    .map(row => String(row.activationItemKey || row.email || '').trim().toLowerCase())
    .filter(Boolean))
  return items.filter(item => retryableKeys.has(activationItemKey(item)))
}

function pendingActivationItems(runId, items) {
  const pendingKeys = new Set(resultRows.value
    .filter(row => (
      row.activationRunId === runId
      && !row.jobId
      && !isTerminalActivationStatus(row.status)
    ))
    .map(row => String(row.activationItemKey || row.email || '').trim().toLowerCase())
    .filter(Boolean))
  return items.filter(item => pendingKeys.has(activationItemKey(item)))
}

function unsubmittedActivationItems(runId, items) {
  const submitted = existingActivationSubmittedKeys(runId)
  return items.filter(item => {
    const key = activationItemKey(item)
    return key && !submitted.has(key)
  })
}

function prepareActivationRetryRows(items, runId, retryLimit) {
  for (const item of items) {
    const row = ensureRow(item.label)
    const retryCount = Math.min(retryLimit, activationRetryCountForItem(runId, item) + 1)
    row.activationRunId = runId
    row.activationItemKey = activationItemKey(item)
    row.activationRetryCount = retryCount
    row.updatedAt = Math.floor(Date.now() / 1000)
    row.status = 'pending'
    row.billingStatus = ''
    row.resultCode = ''
    row.progressPercent = 0
    row.progressStage = 'retry_wait'
    row.progressMessage = `任务重试 ${retryCount}/${retryLimit}，等待重新提交`
    row.progressAvailable = true
    row.otpPending = false
    row.error = ''
    row.jobId = ''
    row.finishedAt = 0
    row.autoOauthLogin = currentActivationInputSource.value === 'account' && Boolean(options.value.auto_oauth_login)
    row.oauthLoginTaskId = ''
    row.oauthLoginStatus = ''
    row.oauthLoginError = ''
    row.oauthLoginResultEmail = ''
    row.oauthLoginProgressStage = ''
    row.oauthLoginProgressMessage = ''
    row.oauthLoginProgressEmail = ''
    row.oauthLoginProgressEvents = []
  }
}

async function runActivationItem(item, runId) {
  const row = ensureRow(item.label)
  row.activationRunId = runId
  row.activationItemKey = activationItemKey(item)
  row.error = ''
  if (activationRunCancelled(runId)) {
    markPendingActivationRowsCancelled(runId)
    return
  }
  try {
    await submitIceJobWithRetry(item, row)
  } catch (error) {
    if (activationRunCancelled(runId)) {
      if (!row.jobId) {
        row.status = 'cancelled'
        row.error = '已取消，未提交到 ICE'
      }
      return
    }
    row.status = 'failed'
    row.error = error.message
  }
}

async function runActivationRound(runId, roundItems, useExistingSubmitted = true, roundOptions = {}) {
  const submitted = useExistingSubmitted ? existingActivationSubmittedKeys(runId) : new Set()
  const active = new Set()
  const prepared = existingActivationPreparedKeys(runId)
  const earlyRetryRemaining = Math.max(0, Number(roundOptions.earlyRetryRemaining || 0))
  while (true) {
    const currentItems = roundItems || activationSchedulerItems()
    syncActivationRunRows(currentItems, runId, prepared, submitted)
    if (activationRunCancelled(runId)) {
      markPendingActivationRowsCancelled(runId)
      if (!active.size) break
      await Promise.race([...active, sleep(PAYPAL_ICE_SCHEDULER_INTERVAL_MS)])
      continue
    }
    const nextItems = currentItems.filter(item => {
      const key = activationItemKey(item)
      return key && !submitted.has(key)
    })
    let limit = activationConcurrencyLimit()
    if (limit < 1) {
      if (options.value.use_pool) await loadPhonePoolStats()
      limit = activationConcurrencyLimit()
      if (limit < 1) {
        setMessage('手机号池暂无可用号码，等待运行中的 ICE 任务释放号码')
        await sleep(PAYPAL_ICE_SCHEDULER_INTERVAL_MS)
        continue
      }
    }
    const detachedActive = Math.max(0, inFlightActivationRowsCount(runId) - active.size)
    const availableLimit = Math.max(0, limit - detachedActive)
    while (active.size < availableLimit && nextItems.length) {
      const item = nextItems.shift()
      const key = activationItemKey(item)
      if (!key || submitted.has(key)) continue
      submitted.add(key)
      const promise = runActivationItem(item, runId).finally(() => {
        active.delete(promise)
      })
      active.add(promise)
    }
    if (!nextItems.length && earlyRetryRemaining > 0 && active.size > 0 && active.size < earlyRetryRemaining) {
      return { earlyRetry: true }
    }
    if (!active.size && !currentItems.some(item => !submitted.has(activationItemKey(item)))) {
      break
    }
    if (active.size) {
      await Promise.race([...active, sleep(PAYPAL_ICE_SCHEDULER_INTERVAL_MS)])
    } else {
      await sleep(PAYPAL_ICE_SCHEDULER_INTERVAL_MS)
    }
  }
  return { earlyRetry: false }
}

async function waitForActivationJobs(runId, items) {
  const itemKeys = new Set(items.map(activationItemKey).filter(Boolean))
  const activeRows = resultRows.value.filter(row => {
    const key = String(row.activationItemKey || row.email || '').trim().toLowerCase()
    return row.activationRunId === runId
      && itemKeys.has(key)
      && row.jobId
      && !isTerminalActivationStatus(row.status)
  })
  await Promise.all(activeRows.map(row => waitForIceTerminal(
    row,
    () => activationRunCancelled(runId),
  )))
}

async function runActivationScheduler() {
  const runId = currentActivationRunId.value
  const allItems = activationSchedulerItems()
  const savedRetryRound = Math.max(0, Number(currentActivationRetryRound.value || 0))
  let roundItems = savedRetryRound > 0 ? pendingActivationItems(runId, allItems) : null
  if (savedRetryRound > 0 && !roundItems.length) roundItems = allItems

  await runActivationRound(runId, roundItems, true, {
    earlyRetryRemaining: PAYPAL_ICE_EARLY_RETRY_REMAINING,
  })

  while (!activationRunCancelled(runId)) {
    const currentItems = activationSchedulerItems()
    if (unsubmittedActivationItems(runId, currentItems).length) {
      await runActivationRound(runId, null, true, {
        earlyRetryRemaining: PAYPAL_ICE_EARLY_RETRY_REMAINING,
      })
      continue
    }
    const retryLimit = activationRetryLimit()
    const failedItems = retryableFailedActivationItems(runId, currentItems)
    if (failedItems.length && retryLimit > 0) {
      const retryRound = Math.max(...failedItems.map(item => activationRetryCountForItem(runId, item) + 1))
      currentActivationRetryRound.value = Math.max(currentActivationRetryRound.value, retryRound)
      prepareActivationRetryRows(failedItems, runId, retryLimit)
      saveActivationRunState(currentItems)
      setMessage(`ICE 失败账号提前重试：${failedItems.length} 个账号，本轮剩余任务少于 ${PAYPAL_ICE_EARLY_RETRY_REMAINING}`)
      await runActivationRound(runId, failedItems, false, {
        earlyRetryRemaining: PAYPAL_ICE_EARLY_RETRY_REMAINING,
      })
      continue
    }
    if (inFlightActivationRowsCount(runId) > 0) {
      await sleep(PAYPAL_ICE_SCHEDULER_INTERVAL_MS)
      continue
    }
    break
  }
  await waitForActivationJobs(runId, activationSchedulerItems())
}

async function resumeActivationRunIfNeeded() {
  const runId = String(currentActivationRunId.value || '').trim()
  if (!runId) return
  const storedRows = resultRows.value.filter(row => row.activationRunId === runId)
  if (storedRows.length && storedRows.every(row => row.localCancelled || String(row.status || '').toLowerCase() === 'cancelled')) {
    discardActivationRunState()
    return
  }
  if (storedRows.length && storedRows.every(row => row.localCancelled || isTerminalActivationStatus(row.status))) {
    return
  }
  resetStaleLocalSubmissionRows(runId)
  currentActivationTotal.value = Math.max(
    currentActivationTotal.value,
    currentActivationRows.value.length,
    restoredActivationItems.value?.length || 0,
  )
  saveActivationRunState()
  const hasPendingSubmission = currentActivationRows.value.some(row => !row.jobId && !isTerminalActivationStatus(row.status))
  const hasActiveJobs = currentActivationRows.value.some(row => row.jobId && !isTerminalActivationStatus(row.status))
  const hasRetryableFailures = retryableFailedActivationItems(
    currentActivationRunId.value,
    activationSchedulerItems(),
  ).length > 0
  if (!hasPendingSubmission && !hasActiveJobs && !hasRetryableFailures) return
  if (hasPendingSubmission) {
    pauseUnsubmittedActivationRows(runId)
    saveResultRowsState()
  }
  if (hasActiveJobs) {
    setMessage(
      hasPendingSubmission || hasRetryableFailures
        ? '已恢复已提交 ICE job 的状态刷新；未提交账号已暂停，避免刷新后重复发起任务'
        : '已恢复已提交 ICE job 的状态刷新',
      true,
    )
    await refreshActiveJobs()
    await refreshIceAccountSilently({ force: true })
    return
  }
  setMessage('检测到上次未提交完成的 ICE 任务，已暂停自动提交，避免刷新后重复发起任务', false)
}

async function activatePlus() {
  activationBusy.value = true
  activationCancelRequested.value = false
  try {
    if (options.value.use_pool) await loadPhonePoolStats()
    if (inputSource.value === 'account' && options.value.auto_oauth_login) await loadOauthEmailConfig()
    validateSelection(true)
    currentActivationRunId.value = `ice-${Date.now()}-${Math.random().toString(16).slice(2)}`
    currentActivationInputSource.value = inputSource.value === 'account' ? 'account' : 'token'
    const initialItems = [...selectedItems.value]
    restoredActivationItems.value = initialItems
    currentActivationTotal.value = initialItems.length
    currentActivationRetryRound.value = 0
    saveActivationRunState(initialItems)
    for (const [index, item] of initialItems.entries()) {
      prepareActivationRunRow(item, currentActivationRunId.value, Date.now() / 1000 - index / 1000)
    }
    await runActivationScheduler()
    const progress = overallProgress.value
    setMessage(
      activationCancelRequested.value
        ? 'PayPal ICE 激活任务已取消，已提交的 job 会继续刷新状态'
        : `PayPal ICE 激活任务已完成：成功 ${progress.success} / ${progress.total}，失败 ${progress.failed}`,
      !activationCancelRequested.value && progress.failed < 1,
    )
    await refreshActiveJobs()
    await refreshIceAccountSilently({ force: true })
  } catch (error) {
    setMessage(error.message, false)
  } finally {
    activationBusy.value = false
    activationCancelRequested.value = false
  }
}

async function submitIceJobWithRetry(item, row) {
  if (activationRunCancelled(row.activationRunId)) {
    row.status = 'cancelled'
    row.error = '已取消，未提交到 ICE'
    return
  }
  const token = await checkTrialEligibilityBeforeIce(item, row)
  if (!token) return
  if (activationRunCancelled(row.activationRunId)) {
    row.status = 'cancelled'
    row.error = '已取消，未提交到 ICE'
    return
  }
  const retryRound = clampNumber(row.activationRetryCount, 0, 5, 0)
  const retryLimit = Math.max(activationRetryLimit(), retryRound)
  row.status = 'submitting'
  row.error = retryRound ? `整轮重试 ${retryRound}/${retryLimit}` : ''
  let result = null
  try {
    result = await api.createPayPalIceJob({
      input: token,
      client_ref: item.clientRef,
      proxy: options.value.proxy || '',
      proxy_jp: options.value.proxy_jp || '',
      phone: options.value.use_pool ? '' : (options.value.phone || ''),
      sms_api: options.value.use_pool ? '' : (options.value.sms_api || ''),
      use_pool: Boolean(options.value.use_pool),
      pplink_retry: Number(options.value.pplink_retry || 3),
      otp_timeout: Number(options.value.otp_timeout || 180),
      idempotency_key: `autotoken-${item.clientRef}-${Date.now()}-round-${retryRound}`,
      auto_oauth_login: currentActivationInputSource.value === 'account' && Boolean(options.value.auto_oauth_login),
      oauth_login_config: storedOauthLoginConfig(),
    })
  } catch (error) {
    if (isPhonePoolExhaustedError(error)) {
      const available = await waitForPhonePoolSlot(row)
      if (!available) return
      return submitIceJobWithRetry(item, row)
    }
    throw error
  }
  applyJobResult(row, result)
  row.jobId = result.job_id || row.jobId
  row.resourceMode = result.resource_mode || row.resourceMode
  await refreshIceAccountSilently()

  if (row.jobId) {
    await waitForIceTerminal(row, () => activationRunCancelled(row.activationRunId))
  }
  if (options.value.use_pool) await loadPhonePoolStats()
}

function isPhonePoolExhaustedError(error) {
  if (!options.value.use_pool) return false
  const message = String(error?.message || '').trim()
  return error?.status === 429 || message.includes('手机号池') || message.toLowerCase().includes('phone pool')
}

async function waitForPhonePoolSlot(row) {
  row.status = 'pending'
  row.progressPercent = 0
  row.progressStage = 'phone_pool_wait'
  row.progressMessage = '手机号池暂无可用号码，等待释放后继续提交'
  row.error = ''
  while (!activationRunCancelled(row.activationRunId)) {
    await loadPhonePoolStats()
    if (Number(phonePoolStats.value.available || 0) > 0) {
      row.progressMessage = '手机号已释放，继续提交 ICE 任务'
      return true
    }
    await sleep(PAYPAL_ICE_SCHEDULER_INTERVAL_MS)
  }
  row.status = 'cancelled'
  row.progressPercent = 100
  row.progressStage = 'cancelled'
  row.progressMessage = '已取消，未提交到 ICE'
  row.error = '已取消，未提交到 ICE'
  return false
}

async function refreshActiveJobs(options = {}) {
  const manual = Boolean(options?.manual)
  if (refreshingJobs.value) {
    if (manual) {
      manualRefreshingJobs.value = true
      window.setTimeout(() => {
        manualRefreshingJobs.value = false
      }, 350)
    }
    return
  }
  const active = resultRows.value.filter(rowNeedsRefresh)
  if (!active.length) return
  refreshingJobs.value = true
  if (manual) manualRefreshingJobs.value = true
  try {
    await runPool(active, async (row) => {
      try {
        const result = await api.getPayPalIceJob(row.jobId)
        applyJobResult(row, result)
      } catch (error) {
        row.error = error.message
      }
    })
    await refreshIceAccountSilently()
  } finally {
    refreshingJobs.value = false
    if (manual) manualRefreshingJobs.value = false
  }
}

function clearResults() {
  resultRows.value = []
  cancelledActivationRunIds.clear()
  discardActivationRunState()
  try {
    localStorage.removeItem(PAYPAL_ICE_ROWS_STATE_KEY)
  } catch (_) {
    // localStorage can be unavailable in private or restricted browser contexts.
  }
}

function trialCheckFailureMessage(result) {
  const message = String(result?.status || result?.message || result?.reason || '').trim()
  if (message) return message
  if (result?.token_ok === false) return 'access token 无效'
  return '无 Plus 试用资格'
}

function applyTrialCheckResult(row, result) {
  const eligible = Boolean(result?.eligible)
  row.trialStatus = eligible ? 'eligible' : (result?.blocked ? 'blocked' : 'ineligible')
  row.resourceMode = result?.resource_mode || row.resourceMode || ''
  row.error = eligible ? '' : trialCheckFailureMessage(result)
  return eligible
}

function subscriptionPlan(result) {
  return String(
    result?.plan_type
    || result?.subscription_plan
    || result?.plan
    || result?.data?.plan_type
    || result?.data?.subscription_plan
    || result?.data?.plan
    || ''
  ).trim().toLowerCase()
}

function subscriptionIsPlus(result) {
  const plan = subscriptionPlan(result)
  return plan === 'plus'
    || plan === 'chatgpt_plus'
    || plan.includes('chatgptplus')
    || plan.includes('chatgpt plus')
}

async function markAccountAlreadyPlus(item, row, subscription) {
  const email = String(item?.email || '').trim().toLowerCase()
  if (inputSource.value === 'account' && email) {
    await api.updateAccountType(email, 'plus')
    accounts.value = accounts.value.map(account => (
      String(account?.email || '').trim().toLowerCase() === email
        ? { ...account, account_type: 'plus', status: 'active' }
        : account
    ))
    batchEmails.value = batchEmails.value.filter(value => String(value || '').trim().toLowerCase() !== email)
    if (String(singleEmail.value || '').trim().toLowerCase() === email) singleEmail.value = ''
    emit('refresh')
  }
  row.trialStatus = 'subscribed'
  row.status = 'skipped'
  row.progressPercent = 100
  row.progressStage = 'already_plus'
  row.progressMessage = '账号当前已是 Plus，已更新账号类型并跳过 ICE'
  row.progressAvailable = true
  row.resourceMode = subscriptionPlan(subscription) || row.resourceMode
  row.error = ''
}

async function handleIneligibleTrial(item, row, token) {
  row.progressStage = 'subscription_check'
  row.progressMessage = '无试用资格，正在查询当前订阅'
  const subscription = await api.checkPayPalIceSubscription({ token })
  if (subscriptionIsPlus(subscription)) {
    await markAccountAlreadyPlus(item, row, subscription)
    return 'already_plus'
  }
  await removeAccountFromIcePool(item, row)
  return 'removed'
}

async function checkTrialEligibilityBeforeIce(item, row) {
  row.status = 'checking_trial'
  row.trialStatus = 'checking'
  row.progressPercent = 4
  row.progressStage = 'trial_check'
  row.progressMessage = '正在检测 Plus 试用资格'
  row.progressAvailable = true
  row.error = ''

  let token = ''
  try {
    token = await tokenForItem(item)
  } catch (error) {
    row.trialStatus = 'error'
    row.status = 'failed'
    row.progressPercent = 100
    row.progressMessage = '读取 access token 失败，已跳过 ICE'
    row.error = error.message
    return ''
  }

  if (activationRunCancelled(row.activationRunId)) {
    row.status = 'cancelled'
    row.progressPercent = 100
    row.progressMessage = '已取消，未提交到 ICE'
    row.error = '已取消，未提交到 ICE'
    return ''
  }

  try {
    const result = await api.checkPayPalIceTrial({ token, proxy_jp: options.value.proxy_jp || '' })
    const eligible = applyTrialCheckResult(row, result)
    if (activationRunCancelled(row.activationRunId)) {
      row.status = 'cancelled'
      row.progressPercent = 100
      row.progressMessage = '已取消，未提交到 ICE'
      row.error = '已取消，未提交到 ICE'
      return ''
    }
    if (!eligible) {
      const outcome = await handleIneligibleTrial(item, row, token)
      if (outcome === 'already_plus') return ''
      row.status = 'failed'
      row.progressPercent = 100
      row.progressStage = 'trial_check'
      row.progressMessage = '无 Plus 试用资格，已跳过 ICE'
      row.error = row.error || '无 Plus 试用资格'
      return ''
    }
    row.status = 'submitting'
    row.progressPercent = 8
    row.progressStage = 'submit_ice'
    row.progressMessage = '试用资格可用，正在提交 ICE 任务'
    row.error = ''
    return token
  } catch (error) {
    row.trialStatus = 'error'
    row.status = 'failed'
    row.progressPercent = 100
    row.progressStage = 'trial_check'
    row.progressMessage = '试用资格检测失败，已跳过 ICE'
    row.error = error.message
    return ''
  }
}

function applyPhonePoolStats(stats) {
  phonePoolStats.value = {
    total: Number(stats?.total || 0),
    available: Number(stats?.available || 0),
    in_use: Number(stats?.in_use || 0),
    disabled: Number(stats?.disabled || 0),
    error: Number(stats?.error || 0),
  }
}

function applyJobResult(row, result) {
  const resultCode = String(result.result_code || '').trim().toUpperCase()
  const status = String(result.status || '').trim().toLowerCase()
  row.createdAt = normalizeRowTimestamp(result.created_at) || row.createdAt || Math.floor(Date.now() / 1000)
  row.updatedAt = normalizeRowTimestamp(result.updated_at) || Math.floor(Date.now() / 1000)
  row.finishedAt = normalizeRowTimestamp(result.finished_at) || row.finishedAt || 0
  row.status = resultCode === 'SUCCESS' ? 'success' : (status || row.status)
  row.billingStatus = result.billing_status || ''
  row.resultCode = resultCode || ''
  row.resourceMode = result.resource_mode || row.resourceMode
  row.progressPercent = normalizeProgressPercent(result.progress_percent)
  row.progressStage = result.progress_stage || ''
  row.progressMessage = result.progress_message || ''
  row.progressAvailable = Boolean(result.progress_available)
  row.otpPending = Boolean(result.otp_pending)
  row.error = result.error_message || ''
  row.localCancelled = Boolean(result.local_cancelled)
  row.autoOauthLogin = Boolean(result.auto_oauth_login)
  row.oauthLoginTaskId = result.oauth_login_task_id || ''
  row.oauthLoginStatus = result.oauth_login_status || ''
  row.oauthLoginError = result.oauth_login_error || ''
  row.oauthLoginResultEmail = result.oauth_login_result_email || ''
  row.oauthLoginProgressStage = result.oauth_login_progress_stage || ''
  row.oauthLoginProgressMessage = result.oauth_login_progress_message || ''
  row.oauthLoginProgressEmail = result.oauth_login_progress_email || ''
  row.oauthLoginProgressEvents = normalizeOauthLoginProgressEvents(result.oauth_login_progress_events)
}

function normalizeProgressPercent(value) {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(String(value).trim().replace(/%$/, ''))
  if (!Number.isFinite(parsed)) return null
  const percent = parsed <= 1 ? parsed * 100 : parsed
  return Math.max(0, Math.min(100, Math.round(percent)))
}

function jobProgressPercent(row) {
  if (row?.progressPercent !== null && row?.progressPercent !== undefined) {
    return normalizeProgressPercent(row.progressPercent) ?? 0
  }
  const status = String(row?.status || '').toLowerCase()
  if (status === 'success') return 100
  if (status === 'failed') return 100
  if (status === 'skipped' || status === 'cancelled') return 100
  if (status === 'pending' && !row?.jobId) return 0
  if (row?.otpPending) return 72
  if (['running', 'processing', 'activating'].includes(status)) return 58
  if (['waiting', 'otp_pending'].includes(status)) return 72
  if (['queued', 'pending'].includes(status)) return 22
  if (status === 'submitting') return 8
  return 0
}

function jobProgressText(row) {
  if (row?.progressMessage) return row.progressMessage
  if (row?.progressStage) return row.progressStage
  if (row?.error) return row.error
  if (row?.resultCode) return row.resultCode
  if (row?.resourceMode) return row.resourceMode
  return {
    checking_trial: '正在检测 Plus 试用资格',
    submitting: '正在提交 ICE 任务',
    pending: row?.jobId ? '等待 ICE 执行' : '等待提交 ICE 任务',
    queued: '任务已提交，等待 ICE 执行',
    running: 'ICE 正在激活 Plus',
    processing: 'ICE 正在处理',
    waiting: '等待验证码或外部资源',
    cancelled: '已取消，未提交到 ICE',
    skipped: '账号当前已是 Plus，已跳过 ICE',
    success: 'Plus 激活完成',
    failed: '任务失败',
  }[String(row?.status || '').toLowerCase()] || '等待任务状态'
}

function failureReasonText(row) {
  const candidates = [
    row?.error,
    row?.progressMessage,
    row?.resultCode,
    row?.progressStage,
  ]
  for (const value of candidates) {
    const text = String(value || '').replace(/\s+/g, ' ').trim()
    if (text && text !== '任务失败') return text
  }
  return 'ICE 未返回失败原因'
}

function iceRealtimeProgressText(row) {
  const parts = []
  if (row?.progressPercent !== null && row?.progressPercent !== undefined && row?.progressAvailable) {
    parts.push(`${normalizeProgressPercent(row.progressPercent)}%`)
  }
  if (row?.progressStage) parts.push(row.progressStage)
  if (row?.progressMessage && row.progressMessage !== row.progressStage) parts.push(row.progressMessage)
  if (!parts.length && row?.error) parts.push(row.error)
  if (!parts.length) return '未返回细分进度'
  return parts.join(' · ')
}

function jobProgressClass(row) {
  const status = String(row?.status || '').toLowerCase()
  if (status === 'success') return 'bg-emerald-400'
  if (status === 'failed') return 'bg-rose-400'
  if (status === 'cancelled') return 'bg-amber-400'
  if (status === 'skipped') return 'bg-sky-400'
  if (['waiting', 'otp_pending'].includes(status) || row?.otpPending) return 'bg-amber-400'
  return 'bg-blue-400'
}

async function waitForIceTerminal(row, shouldStop = null) {
  while (row.jobId && !['success', 'failed', 'skipped', 'cancelled'].includes(String(row.status || '').toLowerCase())) {
    if (typeof shouldStop === 'function' && shouldStop()) {
      row.progressMessage = '已取消本地等待，ICE job 会继续刷新状态'
      return false
    }
    await new Promise(resolve => window.setTimeout(resolve, 3000))
    try {
      applyJobResult(row, await api.getPayPalIceJob(row.jobId))
      await refreshIceAccountSilently()
    } catch (error) {
      row.error = error.message
    }
  }
  await refreshIceAccountSilently()
  return true
}

async function loadPhonePoolStats() {
  phonePoolLoading.value = true
  try {
    const result = await api.getPayPalIcePhonePool()
    applyPhonePoolStats(result?.stats)
  } catch (error) {
    setMessage(`读取手机号池失败: ${error.message}`, false)
  } finally {
    phonePoolLoading.value = false
  }
}

function selectAllAccounts() {
  batchEmails.value = accountOptions.value.map(account => String(account.email || '').trim().toLowerCase())
}

function selectAccountsByCount() {
  const available = filteredAccounts.value
  if (!available.length) return
  const count = Math.max(1, Math.min(available.length, Math.trunc(Number(batchSelectCount.value) || 1)))
  batchSelectCount.value = count
  batchEmails.value = available
    .slice(0, count)
    .map(account => String(account.email || '').trim().toLowerCase())
    .filter(Boolean)
}

function trialLabel(status) {
  return { checking: '检测中', eligible: '可试用', subscribed: '已是 Plus', ineligible: '不可试用', blocked: '已阻断', error: '检测失败' }[status] || '未检测'
}

function trialClass(status) {
  return {
    checking: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    eligible: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    subscribed: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
    blocked: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    error: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  }[status] || 'border-gray-700 bg-gray-900 text-gray-400'
}

function jobLabel(status) {
  return { checking_trial: '检测资格', submitting: '提交中', queued: '排队中', running: '运行中', otp_pending: '等待验证码', success: '成功', failed: '失败', skipped: '已跳过', cancelled: '已取消' }[status] || '未提交'
}

function jobClass(status) {
  return {
    checking_trial: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    submitting: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    queued: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    otp_pending: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    success: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    skipped: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
    cancelled: 'border-gray-600 bg-gray-800 text-gray-400',
  }[status] || 'border-gray-700 bg-gray-900 text-gray-400'
}

function oauthLoginLabel(status) {
  return {
    pending: '待启动',
    queued: '排队中',
    submitted: '已提交',
    running: '补登录中',
    waiting: '等待任务位',
    retrying: '重试中',
    completed: 'OAuth完成',
    failed: '失败',
    cancelled: '已取消',
    skipped: '已跳过',
  }[status] || '等待激活'
}

function oauthLoginClass(status) {
  return {
    pending: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    queued: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    submitted: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    running: 'border-blue-500/30 bg-blue-500/10 text-blue-300',
    waiting: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    retrying: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
    completed: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
    failed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
    cancelled: 'border-gray-600 bg-gray-800 text-gray-400',
    skipped: 'border-gray-600 bg-gray-800 text-gray-400',
  }[status] || 'border-gray-700 bg-gray-900 text-gray-400'
}

const OAUTH_LOGIN_STAGE_STEPS = [
  { key: 'email', label: '获取邮箱' },
  { key: 'bind', label: '绑定邮箱' },
  { key: 'otp', label: '获取验证码' },
  { key: 'submit', label: '输入验证码' },
  { key: 'done', label: '完成' },
]

function oauthLoginProgressEvents(row) {
  const events = normalizeOauthLoginProgressEvents(row?.oauthLoginProgressEvents)
  const stage = String(row?.oauthLoginProgressStage || '')
  const message = String(row?.oauthLoginProgressMessage || '')
  if ((stage || message) && !events.some(event => event.stage === stage && event.message === message)) {
    events.push({
      stage,
      message,
      email: String(row?.oauthLoginProgressEmail || ''),
      level: '',
      current: null,
      total: null,
      updated_at: null,
    })
  }
  return events.slice(-12)
}

function oauthLoginStageIndex(stage, message, status) {
  const text = `${stage || ''} ${message || ''}`.toLowerCase()
  const terminalStatus = String(status || '').toLowerCase()
  if (terminalStatus === 'completed' || text.includes('login_done') || text.includes('finished') || text.includes('补登录成功') || text.includes('oauth 已完成')) return 4
  if (text.includes('after_otp') || text.includes('otp_verified') || text.includes('verify_otp') || text.includes('输入验证码') || text.includes('提交邮箱验证码') || text.includes('邮箱验证码校验')) return 3
  if (text.includes('otp') || text.includes('code') || text.includes('验证码')) return 2
  if (text.includes('add_email') || text.includes('bind_email') || text.includes('绑定邮箱') || text.includes('提交注册邮箱')) return 1
  if (text.includes('mail') || text.includes('email_created') || text.includes('email_creating') || text.includes('获取邮箱') || text.includes('创建绑定邮箱')) return 0
  if (text.includes('account_login') || text.includes('oauth')) return 0
  return -1
}

function oauthLoginStageSummary(row) {
  const status = String(row?.oauthLoginStatus || '').toLowerCase()
  const events = oauthLoginProgressEvents(row)
  const latest = events[events.length - 1] || {}
  const message = String(row?.oauthLoginProgressMessage || latest.message || '').trim()
  const visible = Boolean(row?.autoOauthLogin && status !== 'completed' && (events.length || message || status === 'running'))
  let index = oauthLoginStageIndex(latest.stage || row?.oauthLoginProgressStage, message, status)
  if (index < 0 && status === 'running') index = 0
  const failed = ['failed', 'cancelled'].includes(status) || String(latest.level || '').toLowerCase() === 'warn'
  return {
    visible,
    failed,
    message: message || oauthLoginLabel(status),
    current: {
      ...OAUTH_LOGIN_STAGE_STEPS[Math.max(0, Math.min(index, OAUTH_LOGIN_STAGE_STEPS.length - 1))],
      state: status === 'completed' ? 'done' : 'current',
      failed,
    },
    steps: OAUTH_LOGIN_STAGE_STEPS.map((step, stepIndex) => ({
      ...step,
      state: stepIndex < index || status === 'completed' ? 'done' : stepIndex === index ? 'current' : 'pending',
      failed: failed && stepIndex === Math.max(index, 0),
    })),
  }
}

function oauthLoginStageClass(stage) {
  if (stage.failed) return 'border-rose-500/40 bg-rose-500/10 text-rose-300'
  if (stage.state === 'done') return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
  if (stage.state === 'current') return 'border-sky-500/30 bg-sky-500/10 text-sky-300'
  return 'border-gray-700 bg-gray-900 text-gray-500'
}

watch(
  () => ({
    inputSource: inputSource.value,
    mode: mode.value,
    singleEmail: singleEmail.value,
    batchEmails: batchEmails.value,
    batchSelectCount: batchSelectCount.value,
    options: options.value,
  }),
  savePayPalIceFormState,
  { deep: true },
)

watch(
  resultRows,
  saveResultRowsState,
  { deep: true },
)

watch(
  () => options.value.auto_oauth_login,
  (enabled) => {
    if (enabled && inputSource.value === 'account') {
      loadOauthEmailConfig()
    }
  },
)

onMounted(async () => {
  await Promise.all([
    loadConfig(),
    loadAccounts(),
    loadJobHistory(),
    loadPhonePoolStats(),
    options.value.auto_oauth_login ? loadOauthEmailConfig() : Promise.resolve(),
  ])
  if (config.value.configured) await loadIceAccount()
  pollTimer = setInterval(refreshActiveJobs, PAYPAL_ICE_POLL_INTERVAL_MS)
  void resumeActivationRunIfNeeded()
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>
