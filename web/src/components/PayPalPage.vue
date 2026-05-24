<template>
  <div class="space-y-6 xl:h-[calc(100vh-3rem)] xl:min-h-0">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6 xl:flex xl:h-full xl:min-h-0 xl:flex-col xl:overflow-hidden">
      <div class="grid shrink-0 grid-cols-1 gap-4 xl:grid-cols-[420px_minmax(0,1fr)] xl:items-stretch">
        <div class="flex flex-col justify-center">
          <h2 class="text-xl font-bold text-white">PayPal</h2>
          <p class="mt-1 text-sm text-gray-400">
            批量流程对齐 GoPay：从号池选择账号并执行 PayPal 绑定。
          </p>
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="card in boardCards"
            :key="card.label"
            class="rounded-xl border border-gray-800 bg-gray-900/80 px-4 py-3"
          >
            <div class="text-xs font-medium text-gray-400">{{ card.label }}</div>
            <div class="mt-2 text-xl font-semibold" :class="card.color">{{ card.value }}</div>
            <div v-if="card.meta" class="mt-1 text-xs text-gray-500">{{ card.meta }}</div>
          </div>
        </div>
      </div>

      <div v-if="message" class="mt-4 shrink-0 rounded-lg border px-4 py-3 text-sm" :class="messageClass">
        {{ message }}
      </div>

      <div class="mt-5 grid grid-cols-1 xl:min-h-0 xl:flex-1 xl:grid-cols-[480px_minmax(0,1fr)] gap-4 xl:overflow-hidden">
        <div class="flex flex-col gap-4 xl:min-h-0">
          <div class="shrink-0 rounded-xl border border-gray-800 bg-gray-900/80 p-4">
            <div class="flex flex-col gap-3 sm:flex-row">
              <button
                @click="startTask"
                :disabled="busy || running"
                class="w-full px-4 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50"
              >
                {{ busy ? '提交中...' : running ? '任务运行中...' : '开始 PayPal 绑定' }}
              </button>
              <button
                v-if="running"
                @click="stopTask"
                :disabled="busy"
                class="w-full px-4 py-2 rounded-lg text-sm border bg-red-600/15 hover:bg-red-600/25 text-red-300 border-red-500/30 transition disabled:opacity-50"
              >
                {{ busy ? '取消中...' : '取消任务' }}
              </button>
            </div>
          </div>

          <div class="space-y-4 xl:min-h-0 xl:overflow-y-auto xl:pr-2 xl:pb-2">
          <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
            <div class="flex items-center justify-between gap-3 mb-2">
              <label class="block text-sm text-gray-400">号池账号</label>
              <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                <input
                  v-model="form.batchMode"
                  type="checkbox"
                  :disabled="busy || running"
                  class="accent-blue-500"
                />
                批量绑定
              </label>
            </div>

            <template v-if="!form.batchMode">
              <input
                v-model.trim="accountSearchKeyword"
                type="text"
                class="mb-2 w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                placeholder="搜索邮箱"
                :disabled="busy || loadingAccounts"
              />
              <select
                v-model="selectedAccountEmail"
                class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                :disabled="busy || loadingAccounts"
              >
                <option value="">{{ loadingAccounts ? '加载账号中...' : (filteredAccountOptions.length ? `共 ${filteredAccountOptions.length} 个匹配账号` : '没有匹配账号') }}</option>
                <option v-for="account in filteredAccountOptions" :key="account.email" :value="account.email">
                  {{ account.email }}
                </option>
              </select>
            </template>

            <div v-else class="rounded-lg border border-gray-700 bg-gray-800/60 p-3">
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-xs text-gray-500">当前选择</div>
                  <div class="mt-1 text-sm text-gray-200 font-mono truncate">{{ accountSelectionLabel }}</div>
                </div>
                <button
                  type="button"
                  @click="accountPickerOpen = true"
                  :disabled="busy || running || loadingAccounts"
                  class="shrink-0 px-4 py-2 rounded-lg text-sm border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition disabled:opacity-50"
                >
                  {{ loadingAccounts ? '加载中...' : '选择账号' }}
                </button>
              </div>
              <div v-if="selectedBatchEmails.length" class="mt-2 flex flex-wrap gap-2">
                <span
                  v-for="email in batchPreviewEmails"
                  :key="`paypal-selected-${email}`"
                  class="max-w-full truncate rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-300 font-mono"
                >
                  {{ email }}
                </span>
                <span
                  v-if="selectedBatchEmails.length > batchPreviewEmails.length"
                  class="rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-500"
                >
                  +{{ selectedBatchEmails.length - batchPreviewEmails.length }}
                </span>
              </div>
            </div>

          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
            <div class="text-sm font-semibold text-white mb-3">PayPal绑定配置</div>
            <div class="space-y-3">
              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <label class="flex items-center justify-between gap-3 text-sm text-gray-300">
                  <span class="font-medium text-gray-200">手动确认模式</span>
                  <input v-model="form.manualConfirm" type="checkbox" class="accent-blue-500" :disabled="busy || running" />
                </label>
                <div class="mt-2 text-xs text-gray-500">
                  {{ form.manualConfirm ? '只打开页面并停在支付流程中。' : '自动继续处理 PayPal 登录 / 注册 / OTP / 授权。' }}
                </div>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <label class="flex items-center justify-between gap-3 text-sm text-gray-300">
                  <span class="font-medium text-gray-200">执行模式</span>
                  <select v-model="form.paypalBrowser" class="rounded-lg border border-gray-700 bg-gray-950 px-3 py-1.5 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running">
                    <option value="chromium">Chromium</option>
                    <option value="camoufox">Camoufox</option>
                    <option value="protocol">协议模式</option>
                  </select>
                </label>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <div class="flex items-center justify-between gap-3">
                  <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                    <input v-model="form.autofillEnabled" type="checkbox" class="accent-blue-500" :disabled="busy || running" />
                    <span class="font-medium text-gray-200">自动生成账单信息</span>
                  </label>
                  <button
                    type="button"
                    class="rounded-lg border border-blue-500/30 bg-blue-600/10 px-3 py-1.5 text-xs text-blue-300 transition hover:bg-blue-600/20 disabled:opacity-50"
                    :disabled="busy || running"
                    @click="billingConfigOpen = true"
                  >
                    配置
                  </button>
                </div>
                <div class="mt-2 text-xs text-gray-500">
                  {{ billingSummaryText }}
                </div>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <label class="flex items-center justify-between gap-3 text-sm text-gray-300">
                  <span>
                    <span class="block font-medium text-gray-200">绑定成功后自动 OAuth 补登录</span>
                    <span class="mt-1 block text-xs text-gray-500">未勾选时，绑定成功后直接用当前 auth_session 生成 CPA 认证 JSON。</span>
                  </span>
                  <input v-model="form.autoOauthAfterSuccess" type="checkbox" class="accent-blue-500" :disabled="busy || running" />
                </label>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="text-sm font-medium text-gray-200">PaPal账号配置</div>
                  <div class="grid grid-cols-2 gap-2">
                    <button
                      class="rounded-lg border px-3 py-1.5 text-xs transition"
                      :class="form.paypalMode === 'create_account'
                        ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                        : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                      :disabled="busy || running || form.manualConfirm"
                      @click="form.paypalMode = 'create_account'"
                    >
                      自动注册
                    </button>
                    <button
                      class="rounded-lg border px-3 py-1.5 text-xs transition"
                      :class="form.paypalMode === 'existing_account'
                        ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                        : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                      :disabled="busy || running || form.manualConfirm"
                      @click="form.paypalMode = 'existing_account'"
                    >
                      已有账号
                    </button>
                  </div>
                </div>

                <div v-if="form.paypalMode === 'existing_account'" class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">PayPal 邮箱</label>
                    <input v-model.trim="form.paypalEmail" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running || form.manualConfirm" />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">PayPal 密码</label>
                    <input v-model="form.paypalPassword" type="password" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running || form.manualConfirm" />
                  </div>
                </div>

                <div v-else class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div v-if="!form.phonePoolEnabled" class="md:col-span-2">
                    <label class="block text-xs text-gray-400 mb-1">PayPal 注册手机号</label>
                    <input v-model.trim="form.billingPhone" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" placeholder="+18352880840" :disabled="busy || running || form.manualConfirm || form.phonePoolEnabled" />
                  </div>
                  <div v-if="!form.phonePoolEnabled" class="md:col-span-2">
                    <label class="block text-xs text-gray-400 mb-1">接码 API</label>
                    <input v-model.trim="form.smsUrl" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" placeholder="https://example.com/api/record?token=..." :disabled="busy || running || form.manualConfirm || form.phonePoolEnabled" />
                  </div>
                  <div class="md:col-span-2">
                    <div class="rounded-lg border border-gray-800 bg-gray-900/70 p-3">
                      <div class="flex items-center justify-between gap-3">
                        <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                          <input v-model="form.phonePoolEnabled" type="checkbox" class="accent-blue-500" :disabled="busy || running || form.manualConfirm" />
                          <span class="font-medium text-gray-200">启用手机号池</span>
                        </label>
                        <button
                          type="button"
                          class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50"
                          :disabled="busy || running || form.manualConfirm || !form.phonePoolEnabled"
                          @click="openPoolEdit('phone')"
                        >
                          编辑
                        </button>
                      </div>
                      <div class="mt-2 text-xs text-gray-500">
                        已配置 {{ phonePoolEntries.length }} 个手机号；编辑弹窗内可导入、修改和删除。
                      </div>
                      <div v-if="form.phonePoolEnabled" class="mt-3 max-h-32 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950/70">
                        <div v-if="!phonePoolEntries.length" class="px-3 py-3 text-xs text-gray-500">尚未导入手机号。</div>
                        <div
                          v-for="entry in phonePoolEntries"
                          :key="`${entry.phone_number}|${entry.sms_url}`"
                          class="flex items-center justify-between gap-3 border-b border-gray-900 px-3 py-2 last:border-b-0"
                        >
                          <div class="flex min-w-0 items-center gap-2">
                            <span
                              class="h-2.5 w-2.5 shrink-0 rounded-full"
                              :class="phonePoolStatusClass(entry.phone_number)"
                              :title="phonePoolStatusText(entry.phone_number)"
                            ></span>
                            <span class="font-mono text-xs text-gray-200">{{ entry.phone_number }}</span>
                          </div>
                          <span class="min-w-0 truncate text-xs text-gray-500">{{ entry.sms_url }}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <div class="mb-3 text-sm font-medium text-gray-200">代理设置</div>
                <div v-if="!form.proxyPoolEnabled && !form.proxyApiEnabled" class="mb-3">
                  <label class="block text-xs text-gray-400 mb-1">代理标签</label>
                  <input v-model.trim="form.proxyLabel" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
                </div>
                <div v-if="!form.proxyPoolEnabled && !form.proxyApiEnabled" class="mb-3">
                  <label class="block text-xs text-gray-400 mb-1">代理 URL</label>
                  <input v-model.trim="form.proxyUrl" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" placeholder="socks5://user:pass@host:port" :disabled="busy || running || form.proxyPoolEnabled" />
                  <div class="mt-1 text-xs text-gray-500">未启用轮换时使用这条固定代理。</div>
                </div>
                <div v-if="!form.proxyApiEnabled" class="mb-3 flex items-center justify-between gap-3">
                  <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                    <input v-model="form.proxyPoolEnabled" type="checkbox" class="accent-blue-500" :disabled="busy || running || form.proxyApiEnabled" />
                    <span class="font-medium text-gray-200">启用动态代理池</span>
                  </label>
                  <button
                    v-if="form.proxyPoolEnabled"
                    type="button"
                    class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-700 disabled:opacity-50"
                    :disabled="busy || running || form.proxyApiEnabled"
                    @click="openPoolEdit('proxy')"
                  >
                    编辑
                  </button>
                </div>
                <div v-if="!form.proxyPoolEnabled" class="mb-3">
                  <div class="flex items-center justify-between gap-3">
                    <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                      <input v-model="form.proxyApiEnabled" type="checkbox" class="accent-blue-500" :disabled="busy || running || form.proxyPoolEnabled" />
                      <span class="font-medium text-gray-200">启用代理 API 轮换</span>
                    </label>
                  </div>
                  <div v-if="form.proxyApiEnabled" class="mt-3 space-y-3">
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">供应商</label>
                      <select v-model="form.proxyApiProvider" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running">
                        <option value="1024proxy">1024proxy</option>
                        <option value="cliproxy">Cliproxy</option>
                      </select>
                    </div>
                    <div class="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs text-blue-100">
                      {{ proxyApiProviderHelp }}
                    </div>
                  </div>
                </div>
                <div class="mt-2 text-xs text-gray-500">
                  {{ proxySettingSummary }}
                </div>
                <div v-if="form.proxyPoolEnabled && !form.proxyApiEnabled" class="mt-3 max-h-32 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950/70">
                  <div v-if="!proxyPoolEntries.length" class="px-3 py-3 text-xs text-gray-500">尚未导入代理。</div>
                  <div
                    v-for="(proxy, index) in proxyPoolEntries"
                    :key="proxy"
                    class="flex items-center justify-between gap-3 border-b border-gray-900 px-3 py-2 last:border-b-0"
                  >
                    <span class="shrink-0 text-xs text-gray-500">代理 {{ index + 1 }}</span>
                    <span class="min-w-0 truncate font-mono text-xs text-gray-200">{{ proxy }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>

        </div>
        </div>

        <div class="space-y-4 min-w-0 xl:min-h-0">
          <div class="rounded-xl border border-gray-800 bg-gray-950/80 h-[520px] xl:h-full min-h-0 flex flex-col overflow-hidden">
            <div class="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-800">
              <div class="text-sm font-semibold text-white">实时日志</div>
              <button class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-800" @click="refreshTask">刷新</button>
            </div>
            <div ref="logsScrollRef" class="min-h-0 flex-1 overflow-y-auto p-3 space-y-2">
              <div v-if="!selectedTask" class="text-sm text-gray-500">暂无任务</div>
              <div v-for="line in visibleLogs" :key="line.seq || line.ts || line.line" class="rounded-lg border border-gray-800/80 bg-gray-900/70 px-3 py-2 transition hover:bg-gray-900">
                <div class="grid grid-cols-[52px_minmax(0,1fr)_auto] items-center gap-2">
                  <div class="font-mono text-[11px] text-gray-500">{{ formatTs(line.ts) || '-' }}</div>
                  <div class="min-w-0 truncate text-sm text-gray-100" :title="line.line">{{ line.line }}</div>
                  <span class="shrink-0 rounded-full border border-gray-700 bg-gray-950/80 px-2 py-0.5 font-mono text-[11px]" :class="line.statusClass">
                    {{ line.level }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <div
      v-if="accountPickerOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="accountPickerOpen = false"
    >
      <div class="w-full max-w-3xl max-h-[82vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">批量选择账号</h4>
          </div>
          <button type="button" @click="accountPickerOpen = false" class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">关闭</button>
        </div>

        <div class="px-5 py-4 border-b border-gray-800 space-y-3">
          <input
            v-model.trim="accountSearchKeyword"
            type="text"
            :disabled="loadingAccounts"
            placeholder="搜索邮箱，例如 openaibus.com"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="text-xs text-gray-400">
              {{ loadingAccounts ? '加载账号中...' : filteredAccountOptions.length ? `当前筛选 ${filteredAccountOptions.length} 个账号` : '没有匹配账号' }}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button type="button" @click="selectAllAccounts" :disabled="loadingAccounts || !accountOptions.length || allAccountsSelected" class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">全选</button>
              <button type="button" @click="form.accountEmails = []" :disabled="!selectedBatchEmails.length" class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">清空</button>
            </div>
          </div>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-1">
          <label
            v-for="account in filteredAccountOptions"
            :key="`picker-${account.email}`"
            class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-200 hover:bg-gray-800 cursor-pointer"
          >
            <input v-model="form.accountEmails" type="checkbox" :value="account.email" class="accent-blue-500" />
            <span class="font-mono text-xs break-all">{{ account.email }}</span>
          </label>
          <div v-if="!filteredAccountOptions.length" class="px-3 py-10 text-sm text-gray-500">暂无匹配账号。</div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button type="button" @click="accountPickerOpen = false" class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition">完成</button>
        </div>
      </div>
    </div>

    <div
      v-if="poolEditOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="closePoolEdit"
    >
      <div class="w-full max-w-5xl max-h-[84vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">{{ poolEditTitle }}</h4>
            <div class="text-xs text-gray-500 mt-1">{{ poolEditHelp }}</div>
          </div>
          <button type="button" @click="closePoolEdit" class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">关闭</button>
        </div>
        <div class="flex items-center justify-between gap-3 px-5 py-3 border-b border-gray-800">
          <div class="text-xs text-gray-500">
            共 {{ poolEditRows.length }} 行，已选 {{ poolEditSelectedIds.length }} 行；保存时会自动去重。
          </div>
          <div class="flex items-center gap-2">
            <button type="button" @click="poolEditImportOpen = !poolEditImportOpen" class="px-3 py-1.5 rounded-lg text-xs border border-blue-500/30 bg-blue-600/10 hover:bg-blue-600/20 text-blue-300 transition">导入</button>
            <button type="button" @click="addPoolEditRow" class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">新增一行</button>
            <button
              type="button"
              @click="deleteSelectedPoolEditRows"
              :disabled="!poolEditSelectedIds.length"
              class="px-3 py-1.5 rounded-lg text-xs border bg-red-600/15 hover:bg-red-600/25 text-red-300 border-red-500/30 transition disabled:opacity-50"
            >
              删除选中
            </button>
          </div>
        </div>
        <div v-if="poolEditImportOpen" class="border-b border-gray-800 px-5 py-4">
          <textarea
            v-model="poolEditImportText"
            rows="5"
            spellcheck="false"
            class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
            :placeholder="poolEditImportPlaceholder"
          ></textarea>
          <div class="mt-3 flex items-center justify-between gap-3">
            <div class="text-xs text-gray-500">导入会追加到当前表格，并立即按完整行去重。</div>
            <div class="flex items-center gap-2">
              <button type="button" @click="closePoolEditImport" class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">取消</button>
              <button type="button" @click="confirmPoolEditImport" class="px-3 py-1.5 rounded-lg text-xs bg-blue-600 hover:bg-blue-500 text-white transition">追加导入</button>
            </div>
          </div>
        </div>
        <div class="flex-1 min-h-0 overflow-auto px-5 py-4">
          <table v-if="poolEditTarget === 'phone'" class="min-w-full overflow-hidden rounded-lg border border-gray-800 text-sm">
            <thead class="bg-gray-950/80 text-xs text-gray-400">
              <tr>
                <th class="w-11 px-3 py-2 text-left">
                  <input type="checkbox" class="accent-blue-500" :checked="poolEditAllSelected" :disabled="!poolEditRows.length" @change="togglePoolEditAll" />
                </th>
                <th class="w-16 px-3 py-2 text-left font-medium">状态</th>
                <th class="w-52 px-3 py-2 text-left font-medium">手机号</th>
                <th class="px-3 py-2 text-left font-medium">接码 API</th>
                <th class="w-24 px-3 py-2 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800 bg-gray-950/40">
              <tr v-if="!poolEditRows.length">
                <td colspan="5" class="px-3 py-8 text-center text-sm text-gray-500">暂无手机号，点击“新增一行”添加。</td>
              </tr>
              <tr v-for="row in poolEditRows" :key="row.id" class="transition hover:bg-gray-900/70">
                <td class="px-3 py-2 align-middle">
                  <input v-model="poolEditSelectedIds" type="checkbox" class="accent-blue-500" :value="row.id" />
                </td>
                <td class="px-3 py-2 align-middle">
                  <div class="flex items-center gap-2">
                    <span class="h-2.5 w-2.5 rounded-full" :class="phonePoolStatusClass(row.phone_number)"></span>
                    <span class="text-xs text-gray-400">{{ phonePoolStatusText(row.phone_number) }}</span>
                  </div>
                </td>
                <td class="px-3 py-2 align-middle">
                  <input
                    v-model.trim="row.phone_number"
                    type="text"
                    placeholder="+18352623053"
                    class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-3 py-2 align-middle">
                  <input
                    v-model.trim="row.sms_url"
                    type="text"
                    placeholder="https://ithte.tgflare.com/api/record?token=..."
                    class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-3 py-2 text-right align-middle">
                  <button type="button" @click="deletePoolEditRow(row.id)" class="rounded-lg border border-red-500/30 bg-red-600/10 px-3 py-1.5 text-xs text-red-300 transition hover:bg-red-600/20">删除</button>
                </td>
              </tr>
            </tbody>
          </table>

          <table v-else class="min-w-full overflow-hidden rounded-lg border border-gray-800 text-sm">
            <thead class="bg-gray-950/80 text-xs text-gray-400">
              <tr>
                <th class="w-11 px-3 py-2 text-left">
                  <input type="checkbox" class="accent-blue-500" :checked="poolEditAllSelected" :disabled="!poolEditRows.length" @change="togglePoolEditAll" />
                </th>
                <th class="px-3 py-2 text-left font-medium">代理</th>
                <th class="w-24 px-3 py-2 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-800 bg-gray-950/40">
              <tr v-if="!poolEditRows.length">
                <td colspan="3" class="px-3 py-8 text-center text-sm text-gray-500">暂无代理，点击“新增一行”添加。</td>
              </tr>
              <tr v-for="row in poolEditRows" :key="row.id" class="transition hover:bg-gray-900/70">
                <td class="px-3 py-2 align-middle">
                  <input v-model="poolEditSelectedIds" type="checkbox" class="accent-blue-500" :value="row.id" />
                </td>
                <td class="px-3 py-2 align-middle">
                  <input
                    v-model.trim="row.proxy"
                    type="text"
                    :placeholder="poolEditPlaceholder"
                    class="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 font-mono text-xs text-white focus:border-blue-500 focus:outline-none"
                  />
                </td>
                <td class="px-3 py-2 text-right align-middle">
                  <button type="button" @click="deletePoolEditRow(row.id)" class="rounded-lg border border-red-500/30 bg-red-600/10 px-3 py-1.5 text-xs text-red-300 transition hover:bg-red-600/20">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button type="button" @click="closePoolEdit" class="px-5 py-2 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">取消</button>
          <button type="button" @click="confirmPoolEdit" class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition">保存</button>
        </div>
      </div>
    </div>

    <div
      v-if="billingConfigOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="billingConfigOpen = false"
    >
      <div class="w-full max-w-3xl max-h-[86vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">账单信息配置</h4>
            <div class="text-xs text-gray-500 mt-1">所有字段仍会自动填入 PayPal 表单；这里只控制信息来源。</div>
          </div>
          <button type="button" @click="billingConfigOpen = false" class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">关闭</button>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
          <label class="flex items-center justify-between gap-3 rounded-lg border border-gray-800 bg-gray-950/60 p-3 text-sm text-gray-300">
            <span>
              <span class="block font-medium text-gray-200">自动生成账单信息</span>
              <span class="mt-1 block text-xs text-gray-500">开启后账单姓名 / 地址 / 卡信息从地址生成器获取。</span>
            </span>
            <input v-model="form.autofillEnabled" type="checkbox" class="accent-blue-500" :disabled="busy || running" />
          </label>

          <div v-if="!isCreateAccountMode" class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label class="block text-xs text-gray-400 mb-1">账单电话</label>
              <input v-model.trim="form.billingPhone" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
          </div>

          <div v-if="form.autofillEnabled" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
            当前会自动生成账单姓名、美国地址和卡片信息；页面上的手动账单字段不会参与本次任务。
          </div>

          <div v-else class="grid grid-cols-1 gap-3 md:grid-cols-2">
            <div>
              <label class="block text-xs text-gray-400 mb-1">账单姓名</label>
              <input v-model.trim="form.billingName" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">国家</label>
              <input v-model.trim="form.billingCountry" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
            <div class="md:col-span-2">
              <label class="block text-xs text-gray-400 mb-1">地址 1</label>
              <input v-model.trim="form.billingAddress1" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
            <div class="md:col-span-2">
              <label class="block text-xs text-gray-400 mb-1">地址 2</label>
              <input v-model.trim="form.billingAddress2" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">城市</label>
              <input v-model.trim="form.billingCity" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">州/省</label>
              <input v-model.trim="form.billingState" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>
            <div>
              <label class="block text-xs text-gray-400 mb-1">邮编</label>
              <input v-model.trim="form.billingZip" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
            </div>

            <template v-if="form.paypalMode === 'create_account'">
              <div class="md:col-span-2 border-t border-gray-800 pt-3 text-xs font-semibold uppercase tracking-wide text-gray-500">卡片信息</div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">卡号</label>
                <input v-model.trim="form.paypalCardNumber" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">有效期</label>
                <input v-model.trim="form.paypalCardExpiry" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" placeholder="03/30" :disabled="busy || running" />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">CVV</label>
                <input v-model.trim="form.paypalCardCvv" type="text" class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none" :disabled="busy || running" />
              </div>
            </template>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button type="button" @click="billingConfigOpen = false" class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition">完成</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { computeGoPayBoardView } from '../gopayBoard.js'

const busy = ref(false)
const loadingAccounts = ref(false)
const loadingAccountToken = ref(false)
const accounts = ref([])
const selectedAccountEmail = ref('')
const accountSearchKeyword = ref('')
const accountPickerOpen = ref(false)
const billingConfigOpen = ref(false)
const poolEditOpen = ref(false)
const poolEditTarget = ref('phone')
const poolEditRows = ref([])
const poolEditSelectedIds = ref([])
const poolEditRowSeq = ref(0)
const poolEditImportOpen = ref(false)
const poolEditImportText = ref('')
const message = ref('')
const messageClass = ref('bg-green-500/10 text-green-400 border-green-500/20')
const lastTask = ref(null)
const selectedTask = ref(null)
const pollTimer = ref(null)
const currentLink = ref('')
const restoredFormState = ref(false)
const logsScrollRef = ref(null)
const PAYPAL_FORM_STATE_KEY = 'autoteam_paypal_form_state_v2'
const phonePoolStatusMap = ref({})

const form = ref({
  batchMode: false,
  accountEmails: [],
  proxyLabel: '',
  proxyUrl: '',
  proxyApiEnabled: false,
  proxyApiProvider: '1024proxy',
  proxyPoolEnabled: false,
  proxyPoolText: '',
  manualConfirm: false,
  paypalMode: 'create_account',
  paypalEmail: '',
  paypalPassword: '',
  smsUrl: '',
  phonePoolEnabled: false,
  phonePoolText: '',
  paypalCardNumber: '',
  paypalCardExpiry: '',
  paypalCardCvv: '',
  autofillEnabled: true,
  autoOauthAfterSuccess: false,
  paypalBrowser: 'chromium',
  billingName: '',
  billingPhone: '',
  billingCountry: 'US',
  billingState: '',
  billingCity: '',
  billingZip: '',
  billingAddress1: '',
  billingAddress2: '',
})

const bindForm = ref({
  accessToken: '',
  planType: 'plus',
  promoId: 'plus-1-month-free',
  country: 'US',
  currency: 'USD',
  checkoutUiMode: 'hosted',
  teamWorkspaceName: '我的团队',
  teamSeatQuantity: 2,
  teamPriceInterval: 'month',
  teamPromoCode: 'STRIPEPERKSGPT4BIZ',
  teamCancelUrl: 'https://chatgpt.com/?promoCode=STRIPEPERKSGPT4BIZ',
})

const promoOptions = [
  { id: 'plus-1-month-free', name: 'Plus 1个月免费试用', plan: 'plus' },
]

const countryCurrencyMap = {
  US: 'USD',
  GB: 'GBP',
  HK: 'HKD',
  JP: 'JPY',
  SG: 'SGD',
}

const accountOptions = computed(() => {
  const rows = Array.isArray(accounts.value) ? accounts.value : []
  return rows.filter(isUsableFreeAccount)
})

const filteredAccountOptions = computed(() => {
  const keyword = accountSearchKeyword.value.trim().toLowerCase()
  if (!keyword) return accountOptions.value
  return accountOptions.value.filter(account => String(account?.email || '').toLowerCase().includes(keyword))
})

const selectedBatchEmails = computed(() => {
  const seen = new Set()
  return (Array.isArray(form.value.accountEmails) ? form.value.accountEmails : [])
    .map(email => String(email || '').trim().toLowerCase())
    .filter(email => {
      if (!email || seen.has(email)) return false
      seen.add(email)
      return true
    })
})

const batchActive = computed(() => Boolean(form.value.batchMode && selectedBatchEmails.value.length > 0))
const batchPreviewEmails = computed(() => selectedBatchEmails.value.slice(0, 4))
const allAccountsSelected = computed(() => accountOptions.value.length > 0 && accountOptions.value.every(account => selectedBatchEmails.value.includes(String(account.email || '').toLowerCase())))
const accountSelectionLabel = computed(() => selectedBatchEmails.value.length ? `${selectedBatchEmails.value.length} 个账号` : '未选择')
const filteredPromoOptions = computed(() => promoOptions.filter(item => item.plan === bindForm.value.planType))
const running = computed(() => ['pending', 'running'].includes(String(lastTask.value?.status || '')))
const isCreateAccountMode = computed(() => form.value.paypalMode === 'create_account')
const singleSelectedEmail = computed(() => String(selectedAccountEmail.value || '').trim().toLowerCase())
const phonePoolEntries = computed(() => parsePayPalPhonePool(form.value.phonePoolText, { strict: false }))
const availablePhonePoolEntries = computed(() => phonePoolEntries.value.filter(entry => phonePoolEntryAvailable(entry)))
const proxyPoolEntries = computed(() => parseProxyPoolLines(form.value.proxyPoolText))
const proxyApiProviderHelp = computed(() => {
  if (form.value.proxyApiProvider === 'cliproxy') {
    return '运行时每个账号都会重新提取并使用 Cliproxy 返回的代理。'
  }
  return '运行时每个账号都会重新提取并使用 1024proxy 返回的代理。'
})
const proxySettingSummary = computed(() => {
  if (form.value.proxyApiEnabled) {
    return '已启用代理 API 轮换；每个账号流程开始前调用一次供应商 API。'
  }
  return `已配置 ${proxyPoolEntries.value.length} 条代理；每个账号流程开始时随机选一条，编辑弹窗内可导入、修改和删除。`
})
const poolEditTitle = computed(() => poolEditTarget.value === 'phone' ? '编辑手机号池' : '编辑动态代理池')
const poolEditHelp = computed(() => poolEditTarget.value === 'phone'
  ? '逐行编辑手机号和接码 API；空行保存时会被忽略。'
  : '逐行编辑代理；空行保存时会被忽略。'
)
const poolEditPlaceholder = computed(() => poolEditTarget.value === 'phone'
  ? ''
  : 'socks5://user:pass@host:port'
)
const poolEditImportPlaceholder = computed(() => poolEditTarget.value === 'phone'
  ? '+18352623053----https://ithte.tgflare.com/api/record?token=...\n+18352880840----https://ithte.tgflare.com/api/record?token=...'
  : 'socks5://user:pass@host:port\nhttp://user:pass@host:port\nhost:port:user:pass'
)
const poolEditAllSelected = computed(() => (
  poolEditRows.value.length > 0
  && poolEditRows.value.every(row => poolEditSelectedIds.value.includes(row.id))
))
const billingSummaryText = computed(() => {
  if (form.value.autofillEnabled) {
    return '账单姓名 / 地址 / 卡信息从地址生成器获取；运行时仍会自动填表。'
  }
  const parts = []
  if (form.value.billingName) parts.push(form.value.billingName)
  if (form.value.billingCity || form.value.billingState) {
    parts.push([form.value.billingCity, form.value.billingState].filter(Boolean).join(', '))
  }
  if (form.value.paypalMode === 'create_account' && form.value.paypalCardNumber) {
    const digits = String(form.value.paypalCardNumber || '').replace(/\D/g, '')
    parts.push(digits ? `卡尾号 ${digits.slice(-4)}` : '已配置卡片')
  }
  return parts.length ? `手动账单：${parts.join(' / ')}` : '手动账单信息未配置，点击“配置”填写。'
})
const stageText = computed(() => {
  const progress = selectedTask.value?.progress || lastTask.value?.progress || {}
  return progress.message || progress.stage || '-'
})
const taskTargetLabel = computed(() => {
  const progressEmail = String(selectedTask.value?.progress?.email || '').trim()
  if (progressEmail) return progressEmail
  const params = selectedTask.value?.params || lastTask.value?.params || {}
  const emails = Array.isArray(params.account_emails) ? params.account_emails : []
  if (emails.length > 1) return `${emails.length} 个账号`
  return selectedTask.value?.result?.email || params.email || '-'
})

const visibleLogs = computed(() => {
  const task = selectedTask.value
  if (!task) return []
  const events = Array.isArray(task.progress_events) ? task.progress_events : []
  return events.slice(-200).map(item => ({
    ...item,
    line: item.message || item.line || item.stage || '',
    level: item.level || item.stage || 'INFO',
    statusClass:
      item.level === 'error'
        ? 'border-rose-500/30 text-rose-300'
        : item.level === 'warn'
          ? 'border-amber-500/30 text-amber-300'
          : item.level === 'success'
            ? 'border-emerald-500/30 text-emerald-300'
            : 'border-gray-700 text-gray-300',
  }))
})

const boardView = computed(() => computeGoPayBoardView({
  task: selectedTask.value || lastTask.value,
  form: { email: singleSelectedEmail.value },
  batchActive: batchActive.value,
  selectedBatchEmails: selectedBatchEmails.value,
}))

const boardCards = computed(() => (boardView.value.cards || []).filter(card => card.label !== '当前账号'))

function normalizeBindDefaults() {
  bindForm.value.planType = 'plus'
  bindForm.value.promoId = 'plus-1-month-free'
  bindForm.value.country = 'US'
  bindForm.value.currency = 'USD'
  bindForm.value.checkoutUiMode = 'hosted'
}

function normalizePhoneKey(phone) {
  const digits = String(phone || '').replace(/\D/g, '')
  return digits || String(phone || '').trim().toLowerCase()
}

function phonePoolStatusValue(phone) {
  const key = normalizePhoneKey(phone)
  if (!key) return 'available'
  return phonePoolStatusMap.value[key] === 'invalid' ? 'invalid' : 'available'
}

function phonePoolEntryAvailable(entry) {
  return phonePoolStatusValue(entry?.phone_number) !== 'invalid'
}

function phonePoolStatusClass(phone) {
  return phonePoolStatusValue(phone) === 'invalid' ? 'bg-rose-500' : 'bg-emerald-500'
}

function phonePoolStatusText(phone) {
  return phonePoolStatusValue(phone) === 'invalid' ? '失效' : '可用'
}

function markPhonePoolStatus(phone, status = 'invalid') {
  const key = normalizePhoneKey(phone)
  if (!key) return
  phonePoolStatusMap.value = {
    ...phonePoolStatusMap.value,
    [key]: status === 'invalid' ? 'invalid' : 'available',
  }
}

function prunePhonePoolStatuses(entries = phonePoolEntries.value) {
  const validKeys = new Set((Array.isArray(entries) ? entries : []).map(entry => normalizePhoneKey(entry?.phone_number)).filter(Boolean))
  const nextMap = {}
  Object.entries(phonePoolStatusMap.value || {}).forEach(([key, value]) => {
    if (validKeys.has(key)) nextMap[key] = value
  })
  phonePoolStatusMap.value = nextMap
}

function applyPhonePoolStatusFromTask(task) {
  const events = Array.isArray(task?.progress_events) ? [...task.progress_events] : []
  if (task?.progress && typeof task.progress === 'object') {
    events.push(task.progress)
  }
  if (task?.result && typeof task.result === 'object') {
    events.push(task.result)
  }
  events.forEach((event) => {
    const stage = String(event?.stage || '').trim()
    const failureStage = String(event?.failure_stage || '').trim()
    const rejectedPhone = String(event?.rejected_phone || '').trim()
    if (
      rejectedPhone
      && (
        stage === 'paypal_phone_rejected_waiting_dismiss'
        || stage === 'paypal_phone_rejected_rotate'
        || stage === 'paypal_phone_rejected_final'
        || failureStage === 'paypal_phone_rejected'
      )
    ) {
      markPhonePoolStatus(rejectedPhone, 'invalid')
    }
    const invalidPhones = Array.isArray(event?.invalid_phone_numbers) ? event.invalid_phone_numbers : []
    invalidPhones.forEach((phone) => markPhonePoolStatus(phone, 'invalid'))
  })
}

function parseProxyPoolLines(text) {
  const seen = new Set()
  return String(text || '')
    .split(/\r?\n|,/)
    .map((line) => {
      const clean = String(line || '').split('#')[0].trim()
      return clean
    })
    .filter((line) => {
      if (!line) return false
      const key = line.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function mergeProxyPoolText(...texts) {
  return parseProxyPoolLines(texts.join('\n')).join('\n')
}

function formatPhonePoolEntries(entries) {
  return entries.map(entry => `${entry.phone_number}----${entry.sms_url}`).join('\n')
}

function nextPoolEditRowId() {
  poolEditRowSeq.value += 1
  return `pool-edit-${Date.now()}-${poolEditRowSeq.value}`
}

function makePhonePoolEditRow(entry = {}) {
  return {
    id: nextPoolEditRowId(),
    phone_number: String(entry.phone_number || '').trim(),
    sms_url: String(entry.sms_url || '').trim(),
  }
}

function makeProxyPoolEditRow(proxy = '') {
  return {
    id: nextPoolEditRowId(),
    proxy: String(proxy || '').trim(),
  }
}

function openPoolEdit(target) {
  const normalizedTarget = target === 'proxy' ? 'proxy' : 'phone'
  poolEditTarget.value = normalizedTarget
  poolEditSelectedIds.value = []
  closePoolEditImport()
  poolEditRows.value = normalizedTarget === 'phone'
    ? phonePoolEntries.value.map(entry => makePhonePoolEditRow(entry))
    : proxyPoolEntries.value.map(proxy => makeProxyPoolEditRow(proxy))
  poolEditOpen.value = true
}

function closePoolEdit() {
  poolEditOpen.value = false
  poolEditRows.value = []
  poolEditSelectedIds.value = []
  closePoolEditImport()
}

function addPoolEditRow() {
  poolEditRows.value.push(
    poolEditTarget.value === 'phone'
      ? makePhonePoolEditRow()
      : makeProxyPoolEditRow()
  )
}

function deletePoolEditRow(rowId) {
  poolEditRows.value = poolEditRows.value.filter(row => row.id !== rowId)
  poolEditSelectedIds.value = poolEditSelectedIds.value.filter(id => id !== rowId)
}

function deleteSelectedPoolEditRows() {
  const selected = new Set(poolEditSelectedIds.value)
  poolEditRows.value = poolEditRows.value.filter(row => !selected.has(row.id))
  poolEditSelectedIds.value = []
}

function togglePoolEditAll(event) {
  poolEditSelectedIds.value = event?.target?.checked
    ? poolEditRows.value.map(row => row.id)
    : []
}

function closePoolEditImport() {
  poolEditImportOpen.value = false
  poolEditImportText.value = ''
}

function dedupePoolEditRows(rows, target = poolEditTarget.value) {
  const seen = new Set()
  return rows.filter((row) => {
    const key = target === 'phone'
      ? `${String(row.phone_number || '').trim()}|${String(row.sms_url || '').trim()}`.toLowerCase()
      : String(row.proxy || '').trim().toLowerCase()
    if (!key || key === '|' || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function phonePoolEntriesFromEditRows(rows) {
  return rows
    .map((row, index) => {
      const phone = String(row.phone_number || '').trim()
      const smsUrl = String(row.sms_url || '').trim()
      if (!phone && !smsUrl) return null
      if (!phone || !smsUrl) {
        throw new Error(`手机号池第 ${index + 1} 行未填写完整`)
      }
      return { phone_number: phone, sms_url: smsUrl, otp_channel: 'sms' }
    })
    .filter(Boolean)
}

function confirmPoolEditImport() {
  try {
    if (poolEditTarget.value === 'phone') {
      const imported = parsePayPalPhonePool(poolEditImportText.value, { strict: true })
      poolEditRows.value = dedupePoolEditRows([
        ...poolEditRows.value,
        ...imported.map(entry => makePhonePoolEditRow(entry)),
      ], 'phone')
    } else {
      const imported = parseProxyPoolLines(poolEditImportText.value)
      poolEditRows.value = dedupePoolEditRows([
        ...poolEditRows.value,
        ...imported.map(proxy => makeProxyPoolEditRow(proxy)),
      ], 'proxy')
    }
    poolEditSelectedIds.value = poolEditSelectedIds.value.filter(id => poolEditRows.value.some(row => row.id === id))
    closePoolEditImport()
  } catch (error) {
    setMessage(`导入失败: ${error.message}`, false)
  }
}

function confirmPoolEdit() {
  try {
    if (poolEditTarget.value === 'phone') {
      const deduped = dedupePhonePoolEntries(phonePoolEntriesFromEditRows(poolEditRows.value))
      form.value.phonePoolText = formatPhonePoolEntries(deduped)
      form.value.phonePoolEnabled = true
      prunePhonePoolStatuses(deduped)
      setMessage(`手机号池已保存并去重：${deduped.length} 个`)
    } else {
      const rawText = poolEditRows.value
        .map(row => String(row.proxy || '').trim())
        .filter(Boolean)
        .join('\n')
      const deduped = mergeProxyPoolText(rawText)
      form.value.proxyPoolText = deduped
      form.value.proxyPoolEnabled = true
      setMessage(`动态代理池已保存并去重：${parseProxyPoolLines(deduped).length} 条`)
    }
    closePoolEdit()
  } catch (error) {
    setMessage(`保存失败: ${error.message}`, false)
  }
}

function setMessage(text, ok = true) {
  message.value = text
  messageClass.value = ok
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
}

function isUsableFreeAccount(account) {
  if (!account?.email || account?.is_main_account) return false
  if (String(account?.account_type || '').toLowerCase() !== 'free') return false
  if (!account?.auth_session_file) return false
  const status = String(account?.status || '').toLowerCase()
  return !['fail', 'auth_invalid', 'orphan', 'standby', 'pending'].includes(status)
}

function rememberedPayPalState() {
  return {
    selectedAccountEmail: selectedAccountEmail.value,
    accountSearchKeyword: accountSearchKeyword.value,
    currentLink: currentLink.value,
    phonePoolStatusMap: phonePoolStatusMap.value,
    form: {
      ...form.value,
      accountEmails: selectedBatchEmails.value,
    },
    bindForm: {
      ...bindForm.value,
      accessToken: '',
    },
  }
}

function restorePayPalState() {
  try {
    const raw = localStorage.getItem(PAYPAL_FORM_STATE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return
    if (saved.phonePoolStatusMap && typeof saved.phonePoolStatusMap === 'object') {
      phonePoolStatusMap.value = { ...saved.phonePoolStatusMap }
    }
    if (saved.form && typeof saved.form === 'object') {
      Object.assign(form.value, saved.form)
      form.value.paypalPassword = ''
      form.value.accountEmails = Array.isArray(saved.form.accountEmails) ? saved.form.accountEmails : []
      if (saved.form.phonePoolEnabled === undefined && String(saved.form.phonePoolText || '').trim()) {
        form.value.phonePoolEnabled = true
      }
      if (saved.form.proxyPoolEnabled === undefined && String(saved.form.proxyPoolText || '').trim()) {
        form.value.proxyPoolEnabled = true
      }
      if (saved.form.proxyApiEnabled === undefined) {
        form.value.proxyApiEnabled = false
      }
      if (!['1024proxy', 'cliproxy'].includes(String(form.value.proxyApiProvider || ''))) {
        form.value.proxyApiProvider = '1024proxy'
      }
      if (String(form.value.paypalBrowser || '').toLowerCase() === 'chrome') {
        form.value.paypalBrowser = 'chromium'
      }
      if (!['chromium', 'camoufox', 'protocol'].includes(String(form.value.paypalBrowser || '').toLowerCase())) {
        form.value.paypalBrowser = 'chromium'
      }
      if (form.value.proxyApiEnabled) {
        form.value.proxyPoolEnabled = false
      }
    }
    if (saved.bindForm && typeof saved.bindForm === 'object') {
      Object.assign(bindForm.value, saved.bindForm)
      bindForm.value.accessToken = ''
    }
    normalizeBindDefaults()
    selectedAccountEmail.value = String(saved.selectedAccountEmail || '').trim().toLowerCase()
    accountSearchKeyword.value = String(saved.accountSearchKeyword || '')
    currentLink.value = String(saved.currentLink || '')
    prunePhonePoolStatuses()
  } catch (error) {
    console.warn('PayPal 表单缓存读取失败:', error)
  }
}

function savePayPalState() {
  if (!restoredFormState.value) return
  try {
    localStorage.setItem(PAYPAL_FORM_STATE_KEY, JSON.stringify(rememberedPayPalState()))
  } catch (error) {
    console.warn('PayPal 表单缓存保存失败:', error)
  }
}

function formatTs(ts) {
  if (!ts) return ''
  const d = new Date(Number(ts) * 1000)
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleTimeString('zh-CN', {
        hour12: false,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      })
}

function scrollLogsToBottom() {
  nextTick(() => {
    const el = logsScrollRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function buildBindLinkBody() {
  normalizeBindDefaults()
  return {
    promo_campaign: {
      promo_campaign_id: bindForm.value.promoId,
      is_coupon_from_query_param: false,
    },
    plan_name: 'chatgptplusplan',
    billing_details: {
      country: bindForm.value.country,
      currency: bindForm.value.currency,
    },
    checkout_ui_mode: bindForm.value.checkoutUiMode,
  }
}

function buildBindLinkRequest(accessToken) {
  return {
    access_token: accessToken,
    ...buildBindLinkBody(),
  }
}

function resolveGeneratedLink(result) {
  if (result?.url) {
    return {
      link: result.url,
      sessionId: result.checkout_session_id || '',
      rawGeneratedUrl: result.url,
    }
  }
  if (result?.checkout_session_id) {
    const sessionId = result.checkout_session_id
    const processorEntity = String(result?.processor_entity || 'openai_llc').trim() || 'openai_llc'
    return {
      link: `https://chatgpt.com/checkout/${processorEntity}/${sessionId}`,
      sessionId,
      rawGeneratedUrl: '',
    }
  }
  return null
}

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const result = await api.getAccounts({ includeSessionStubs: true })
    accounts.value = Array.isArray(result) ? result : (result?.accounts || [])
    if (selectedAccountEmail.value && !accountOptions.value.some(account => account.email === selectedAccountEmail.value)) {
      selectedAccountEmail.value = ''
      bindForm.value.accessToken = ''
    }
    form.value.accountEmails = selectedBatchEmails.value.filter(email => accountOptions.value.some(account => account.email === email))
  } catch (error) {
    console.warn('PayPal 账号加载失败:', error)
  } finally {
    loadingAccounts.value = false
  }
}

async function ensureAccessToken() {
  if (bindForm.value.accessToken) return bindForm.value.accessToken
  if (!singleSelectedEmail.value) {
    throw new Error('请先选择单个账号再提取 access_token')
  }
  const result = await api.getCodexAuth(singleSelectedEmail.value)
  const token = result?.codex_auth?.tokens?.access_token || ''
  if (!token) throw new Error('对应 auth_session 文件中没有 accessToken')
  bindForm.value.accessToken = token
  return token
}

async function useAccountToken() {
  if (!singleSelectedEmail.value) {
    setMessage('请先选择单个号池账号', false)
    return
  }
  loadingAccountToken.value = true
  try {
    await ensureAccessToken()
    setMessage(`已提取 ${singleSelectedEmail.value} 的 access_token`)
  } catch (error) {
    setMessage(`提取 access_token 失败: ${error.message}`, false)
  } finally {
    loadingAccountToken.value = false
  }
}

async function generateLink() {
  busy.value = true
  try {
    const token = await ensureAccessToken()
    const result = await api.generateBindLink(buildBindLinkRequest(token))
    const resolved = resolveGeneratedLink(result)
    const link = resolved?.link || ''
    if (!link) throw new Error(result?.detail || '未返回可用支付链接')
    currentLink.value = link
    setMessage('支付链接已生成')
  } catch (error) {
    const text = String(error?.message || '').trim()
    const friendly = text.includes('<html')
      ? '生成链接失败：上游返回了 HTML 风控页，通常是 access_token 失效、Cloudflare 未通过，或当前 IP/环境被风控'
      : text
    setMessage(`生成链接失败: ${friendly}`, false)
  } finally {
    busy.value = false
  }
}

async function refreshTask() {
  try {
    const tasks = await api.getTasks()
    const paypalTasks = (Array.isArray(tasks) ? tasks.filter(task => task?.command === 'paypal') : [])
      .sort((a, b) => Number(b?.started_at || b?.created_at || 0) - Number(a?.started_at || a?.created_at || 0))
    const active = paypalTasks
      .filter(task => ['running', 'pending'].includes(String(task?.status || '')))
      [0] || null
    const target = active || paypalTasks[0] || null
    if (!target?.task_id) {
      selectedTask.value = null
      lastTask.value = null
      scrollLogsToBottom()
      return
    }
    let detail = target
    try {
      detail = await api.getTask(target.task_id)
    } catch (error) {
      console.warn(`PayPal 任务详情刷新失败: ${target.task_id}`, error)
    }
    applyPhonePoolStatusFromTask(detail)
    selectedTask.value = detail
    lastTask.value = detail
    if (detail?.result?.checkout_url) {
      currentLink.value = detail.result.checkout_url
    }
    scrollLogsToBottom()
  } catch (error) {
    console.warn('PayPal 任务刷新失败:', error)
  }
}

function selectAllAccounts() {
  form.value.accountEmails = accountOptions.value.map(account => String(account.email || '').trim().toLowerCase())
}

function dedupePhonePoolEntries(entries) {
  const seen = new Set()
  return (Array.isArray(entries) ? entries : [])
    .filter(Boolean)
    .filter((entry) => {
      const phone = String(entry.phone_number || '').trim()
      const smsUrl = String(entry.sms_url || '').trim()
      const key = `${phone}|${smsUrl}`.toLowerCase()
      if (!phone || !smsUrl || seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function parsePayPalPhonePool(text, options = {}) {
  const strict = options.strict !== false
  const entries = []
  String(text || '')
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const parts = line.split('----')
      if (parts.length < 2) {
        if (strict) throw new Error(`手机号池格式错误: ${line}`)
        return
      }
      const phone = String(parts.shift() || '').trim()
      const smsUrl = parts.join('----').trim()
      if (!phone || !smsUrl) {
        if (strict) throw new Error(`手机号池格式错误: ${line}`)
        return
      }
      entries.push({ phone_number: phone, sms_url: smsUrl, otp_channel: 'sms' })
    })
  return dedupePhonePoolEntries(entries)
}

function validateBeforeStart() {
  if (!form.value.batchMode && !singleSelectedEmail.value) {
    throw new Error('请先选择号池账号')
  }
  if (form.value.batchMode && !selectedBatchEmails.value.length) {
    throw new Error('请先选择批量账号')
  }
  if (form.value.proxyApiEnabled) {
    const provider = String(form.value.proxyApiProvider || '').trim()
    if (!['1024proxy', 'cliproxy'].includes(provider)) {
      throw new Error('代理 API 供应商暂只支持 1024proxy 或 Cliproxy')
    }
  }
  if (!form.value.proxyApiEnabled && form.value.proxyPoolEnabled && !proxyPoolEntries.value.length) {
    throw new Error('启用动态代理池后需要先导入代理')
  }
  if (!form.value.manualConfirm) {
    if (isCreateAccountMode.value) {
      const phoneAccounts = form.value.phonePoolEnabled ? availablePhonePoolEntries.value : []
      if (form.value.phonePoolEnabled) {
        if (!phonePoolEntries.value.length) throw new Error('启用手机号池后需要先导入手机号')
        if (!phoneAccounts.length) throw new Error('手机号池中没有可用号码，请先更换或编辑已失效号码')
      } else {
        if (!String(form.value.billingPhone || '').trim()) throw new Error('自动注册模式需要填写 PayPal 注册手机号')
        if (!String(form.value.smsUrl || '').trim()) throw new Error('自动注册模式需要填写接码 API')
      }
      if (!form.value.autofillEnabled) {
        if (!String(form.value.billingName || '').trim()) throw new Error('手动账单信息模式需要填写账单姓名')
        if (!String(form.value.billingAddress1 || '').trim()) throw new Error('手动账单信息模式需要填写地址 1')
        if (!String(form.value.billingCity || '').trim()) throw new Error('手动账单信息模式需要填写城市')
        if (!String(form.value.billingState || '').trim()) throw new Error('手动账单信息模式需要填写州/省')
        if (!String(form.value.billingZip || '').trim()) throw new Error('手动账单信息模式需要填写邮编')
        if (!String(form.value.billingCountry || '').trim()) throw new Error('手动账单信息模式需要填写国家')
        if (!String(form.value.paypalCardNumber || '').trim()) throw new Error('自动注册模式需要填写卡号')
        if (!String(form.value.paypalCardExpiry || '').trim()) throw new Error('自动注册模式需要填写卡有效期')
        if (!String(form.value.paypalCardCvv || '').trim()) throw new Error('自动注册模式需要填写 CVV')
      }
    } else {
      if (!String(form.value.paypalEmail || '').trim()) throw new Error('已有账号模式需要填写 PayPal 邮箱')
      if (!String(form.value.paypalPassword || '').trim()) throw new Error('已有账号模式需要填写 PayPal 密码')
    }
  }
}

async function startTask() {
  busy.value = true
  try {
    validateBeforeStart()
    currentLink.value = ''
    const effectiveEmail = form.value.batchMode ? selectedBatchEmails.value[0] : singleSelectedEmail.value
    const phoneAccounts = isCreateAccountMode.value && form.value.phonePoolEnabled ? availablePhonePoolEntries.value : []
    const firstPhoneAccount = phoneAccounts[0] || null
    const task = await api.startPayPal({
      runner_mode: 'manual_checkout',
      email: effectiveEmail,
      account_emails: form.value.batchMode ? selectedBatchEmails.value : [],
      checkout_url: '',
      bind_link_payload: buildBindLinkBody(),
      proxy_url: form.value.proxyUrl || null,
      proxy_pool_text: !form.value.proxyApiEnabled && form.value.proxyPoolEnabled ? (form.value.proxyPoolText || '') : '',
      proxy_api_provider: form.value.proxyApiEnabled ? form.value.proxyApiProvider : '',
      proxy_label: form.value.proxyLabel,
      manual_confirm: Boolean(form.value.manualConfirm),
      paypal_browser: form.value.paypalBrowser,
      paypal_mode: form.value.paypalMode,
      paypal_email: isCreateAccountMode.value ? '' : form.value.paypalEmail,
      paypal_password: isCreateAccountMode.value ? '' : form.value.paypalPassword,
      phone_accounts: phoneAccounts,
      sms_url: firstPhoneAccount?.sms_url || form.value.smsUrl,
      otp_channel: 'sms',
      paypal_card_number: form.value.paypalCardNumber,
      paypal_card_expiry: form.value.paypalCardExpiry,
      paypal_card_cvv: form.value.paypalCardCvv,
      autofill_enabled: Boolean(form.value.autofillEnabled),
      auto_oauth_after_success: Boolean(form.value.autoOauthAfterSuccess),
      billing_name: form.value.billingName,
      billing_email: effectiveEmail,
      billing_phone: firstPhoneAccount?.phone_number || form.value.billingPhone,
      billing_country: form.value.billingCountry,
      billing_state: form.value.billingState,
      billing_city: form.value.billingCity,
      billing_zip: form.value.billingZip,
      billing_address1: form.value.billingAddress1,
      billing_address2: form.value.billingAddress2,
    })
    lastTask.value = task
    selectedTask.value = task
    setMessage('')
    await refreshTask()
  } catch (error) {
    setMessage(`提交 PayPal 任务失败: ${error.message}`, false)
  } finally {
    busy.value = false
  }
}

async function stopTask() {
  if (!running.value) return
  busy.value = true
  try {
    const taskId = selectedTask.value?.task_id || lastTask.value?.task_id || ''
    await api.cancelTask(taskId ? { task_id: taskId } : null)
    setMessage('已请求停止当前 PayPal 任务')
    await refreshTask()
  } catch (error) {
    setMessage(`停止 PayPal 任务失败: ${error.message}`, false)
  } finally {
    busy.value = false
  }
}

function copyCurrentLink() {
  if (!currentLink.value) return
  navigator.clipboard.writeText(currentLink.value)
  setMessage('链接已复制到剪贴板')
}

function openLink() {
  if (!currentLink.value) return
  window.open(currentLink.value, '_blank')
}

watch(
  () => bindForm.value.country,
  (country) => {
    bindForm.value.currency = countryCurrencyMap[country] || 'USD'
  },
  { immediate: true }
)

watch(
  () => visibleLogs.value.length,
  () => {
    scrollLogsToBottom()
  }
)

watch(
  () => form.value.phonePoolText,
  () => {
    prunePhonePoolStatuses()
  }
)

watch(
  () => form.value.proxyApiEnabled,
  (enabled) => {
    if (enabled) {
      form.value.proxyPoolEnabled = false
    }
  }
)

watch(
  [form, bindForm, selectedAccountEmail, accountSearchKeyword, currentLink, phonePoolStatusMap],
  savePayPalState,
  { deep: true }
)

onMounted(async () => {
  restorePayPalState()
  normalizeBindDefaults()
  restoredFormState.value = true
  savePayPalState()
  await loadAccounts()
  await refreshTask()
  pollTimer.value = setInterval(refreshTask, 3000)
})

onBeforeUnmount(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>
