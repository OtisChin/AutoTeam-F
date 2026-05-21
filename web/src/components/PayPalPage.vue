<template>
  <div class="space-y-6">
    <section class="rounded-2xl border border-gray-800 bg-gray-950/70 p-5 md:p-6">
      <div class="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h2 class="text-xl font-bold text-white">PayPal</h2>
          <p class="mt-1 text-sm text-gray-400">
            自动打开 checkout、注入选中账号的 auth_session、填写账单、切到 PayPal，并可继续自动登录已有账号或自动创建新 PayPal 账号。保留手动确认兜底模式。
          </p>
        </div>
        <div class="flex items-center gap-2">
          <button
            class="px-3 py-2 rounded-lg text-sm border transition border-gray-700 bg-gray-900 text-gray-300 hover:bg-gray-800"
            :disabled="busy"
            @click="refreshTask"
          >
            刷新状态
          </button>
          <button
            class="px-3 py-2 rounded-lg text-sm border transition"
            :class="running ? 'border-red-500/40 bg-red-500/10 text-red-300 hover:bg-red-500/20' : 'border-blue-500/30 bg-blue-500/10 text-blue-300 hover:bg-blue-500/20'"
            :disabled="busy"
            @click="running ? stopTask() : startTask()"
          >
            {{ running ? '停止任务' : (busy ? '提交中...' : '开始运行') }}
          </button>
        </div>
      </div>

      <div v-if="message" class="mt-4 rounded-lg border px-4 py-3 text-sm" :class="messageClass">
        {{ message }}
      </div>

      <div class="mt-5 grid grid-cols-1 xl:grid-cols-[420px_minmax(0,1fr)] gap-4">
        <div class="space-y-4">
          <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
            <div class="text-sm font-semibold text-white mb-3">账号与链接</div>
            <div class="space-y-3">
              <div>
                <label class="block text-xs text-gray-400 mb-1">号池账号</label>
                <input
                  v-model.trim="accountSearchKeyword"
                  type="text"
                  class="mb-2 w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  placeholder="搜索邮箱"
                  :disabled="busy"
                />
                <div class="flex gap-2">
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
                  <button
                    class="shrink-0 rounded-lg border border-blue-500/30 bg-blue-600/20 px-4 py-2 text-sm text-blue-300 transition hover:bg-blue-600/30 disabled:opacity-50"
                    :disabled="busy || loadingAccountToken || !selectedAccountEmail"
                    @click="useAccountToken"
                  >
                    {{ loadingAccountToken ? '提取中...' : '提取 Token' }}
                  </button>
                </div>
              </div>

              <div>
                <label class="block text-xs text-gray-400 mb-2">Checkout 链接模式</label>
                <div class="grid grid-cols-2 gap-2">
                  <button
                    class="rounded-lg border px-4 py-2 text-sm transition"
                    :class="form.checkoutMode === 'auto'
                      ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                      : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                    :disabled="busy"
                    @click="form.checkoutMode = 'auto'"
                  >
                    自动生成
                  </button>
                  <button
                    class="rounded-lg border px-4 py-2 text-sm transition"
                    :class="form.checkoutMode === 'manual'
                      ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                      : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                    :disabled="busy"
                    @click="form.checkoutMode = 'manual'"
                  >
                    手动输入
                  </button>
                </div>
              </div>

              <div v-if="form.checkoutMode === 'auto'" class="space-y-3 rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">套餐类型</label>
                  <div class="grid grid-cols-2 gap-2">
                    <button
                      class="rounded-lg border px-4 py-2 text-sm transition"
                      :class="bindForm.planType === 'plus'
                        ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                        : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                      :disabled="busy"
                      @click="bindForm.planType = 'plus'"
                    >
                      Plus
                    </button>
                    <button
                      class="rounded-lg border px-4 py-2 text-sm transition"
                      :class="bindForm.planType === 'team'
                        ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                        : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                      :disabled="busy"
                      @click="bindForm.planType = 'team'"
                    >
                      Team
                    </button>
                  </div>
                </div>

                <div v-if="bindForm.planType === 'plus'">
                  <label class="block text-xs text-gray-400 mb-1">优惠活动</label>
                  <select
                    v-model="bindForm.promoId"
                    class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    :disabled="busy"
                  >
                    <option v-for="promo in filteredPromoOptions" :key="promo.id" :value="promo.id">
                      {{ promo.name }}
                    </option>
                  </select>
                </div>

                <div v-else class="grid grid-cols-1 gap-3">
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">优惠码</label>
                    <input
                      v-model.trim="bindForm.teamPromoCode"
                      type="text"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      placeholder="例如 STRIPEPERKSGPT4BIZ"
                      :disabled="busy"
                    />
                  </div>
                  <div class="grid grid-cols-2 gap-3">
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">工作区名称</label>
                      <input
                        v-model.trim="bindForm.teamWorkspaceName"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">席位数</label>
                      <input
                        v-model.number="bindForm.teamSeatQuantity"
                        type="number"
                        min="1"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                  </div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">国家</label>
                    <select
                      v-model="bindForm.country"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      :disabled="busy"
                    >
                      <option value="US">US</option>
                      <option value="SG">SG</option>
                      <option value="GB">GB</option>
                      <option value="HK">HK</option>
                      <option value="JP">JP</option>
                    </select>
                  </div>
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">链接类型</label>
                    <select
                      v-model="bindForm.checkoutUiMode"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      :disabled="busy || bindForm.planType === 'team'"
                    >
                      <option value="hosted">长链接</option>
                      <option value="custom">短链接</option>
                    </select>
                  </div>
                </div>
              </div>

              <div v-else>
                <label class="block text-xs text-gray-400 mb-1">手动 Checkout 链接</label>
                <textarea
                  v-model.trim="form.checkoutUrl"
                  rows="4"
                  class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  placeholder="粘贴 pay.openai.com / chatgpt.com/checkout 链接"
                  :disabled="busy"
                />
              </div>

              <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
                <div>
                  <label class="block text-xs text-gray-400 mb-1">代理标签</label>
                  <input
                    v-model.trim="form.proxyLabel"
                    type="text"
                    class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    placeholder="例如 res-us-01"
                    :disabled="busy"
                  />
                </div>
                <div>
                  <label class="block text-xs text-gray-400 mb-1">超时（秒）</label>
                  <input
                    v-model.number="form.timeoutSeconds"
                    type="number"
                    min="60"
                    class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                    :disabled="busy"
                  />
                </div>
              </div>

              <div>
                <label class="block text-xs text-gray-400 mb-1">代理 URL</label>
                <input
                  v-model.trim="form.proxyUrl"
                  type="text"
                  class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                  placeholder="socks5://user:pass@host:port"
                  :disabled="busy"
                />
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <label class="flex items-center justify-between gap-3 text-sm text-gray-300">
                  <span class="font-medium text-gray-200">手动确认模式</span>
                  <input v-model="form.manualConfirm" type="checkbox" class="accent-blue-500" :disabled="busy" />
                </label>
                <div class="mt-2 text-xs text-gray-500">
                  {{ form.manualConfirm ? '开启后只自动打开页面与填写账单，不会继续处理 PayPal 登录、注册或授权。' : '关闭后会继续处理 PayPal 登录/注册、短信验证码与最终授权。' }}
                </div>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="text-sm font-medium text-gray-200">PayPal 自动模式</div>
                  <div class="grid grid-cols-2 gap-2">
                    <button
                      class="rounded-lg border px-3 py-1.5 text-xs transition"
                      :class="form.paypalMode === 'create_account'
                        ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                        : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                      :disabled="busy || form.manualConfirm"
                      @click="form.paypalMode = 'create_account'"
                    >
                      自动注册
                    </button>
                    <button
                      class="rounded-lg border px-3 py-1.5 text-xs transition"
                      :class="form.paypalMode === 'existing_account'
                        ? 'border-blue-500/40 bg-blue-600/20 text-blue-400'
                        : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
                      :disabled="busy || form.manualConfirm"
                      @click="form.paypalMode = 'existing_account'"
                    >
                      已有账号
                    </button>
                  </div>
                </div>
                <div class="mt-2 text-xs text-gray-500">
                  {{ form.paypalMode === 'create_account'
                    ? '自动注册PayPal账号。'
                    : '使用现成 PayPal 账号登录并授权。' }}
                </div>
                <div v-if="form.paypalMode === 'existing_account'" class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">PayPal 邮箱</label>
                    <input
                      v-model.trim="form.paypalEmail"
                      type="text"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      :disabled="busy || form.manualConfirm"
                    />
                  </div>
                  <div>
                    <label class="block text-xs text-gray-400 mb-1">PayPal 密码</label>
                    <input
                      v-model="form.paypalPassword"
                      type="password"
                      autocomplete="off"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      :disabled="busy || form.manualConfirm"
                    />
                  </div>
                </div>
                <div v-else class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div class="md:col-span-2">
                    <label class="block text-xs text-gray-400 mb-1">PayPal 注册手机号</label>
                    <input
                      v-model.trim="form.billingPhone"
                      type="text"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      placeholder="+18352880840"
                      :disabled="busy || form.manualConfirm"
                    />
                  </div>
                  <div class="md:col-span-2">
                    <label class="block text-xs text-gray-400 mb-1">接码 API</label>
                    <input
                      v-model.trim="form.smsUrl"
                      type="text"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      placeholder="https://example.com/api/record?token=..."
                      :disabled="busy || form.manualConfirm"
                    />
                  </div>
                </div>
              </div>

              <div class="rounded-lg border border-gray-800 bg-gray-800/30 p-3">
                <label class="flex items-center justify-between gap-3 text-sm text-gray-300">
                  <span class="font-medium text-gray-200">自动填写表单</span>
                  <input v-model="form.autofillEnabled" type="checkbox" class="accent-blue-500" :disabled="busy" />
                </label>
                <div class="mt-2 text-xs text-gray-500">
                  {{ form.autofillEnabled ? '开启后从美国地址生成器获取地址/卡片字段并自动填写；卡片信息区域会隐藏。' : '关闭后显示地址和卡片信息，按你填写的内容提交。' }}
                </div>
                <div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <div v-if="!isCreateAccountMode">
                    <label class="block text-xs text-gray-400 mb-1">账单电话</label>
                    <input
                      v-model.trim="form.billingPhone"
                      type="text"
                      class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                      :disabled="busy"
                    />
                  </div>
                  <template v-if="!form.autofillEnabled">
                    <div class="md:col-span-2">
                      <label class="block text-xs text-gray-400 mb-1">地址 1</label>
                      <input
                        v-model.trim="form.billingAddress1"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div class="md:col-span-2">
                      <label class="block text-xs text-gray-400 mb-1">地址 2</label>
                      <input
                        v-model.trim="form.billingAddress2"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">城市</label>
                      <input
                        v-model.trim="form.billingCity"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">州/省</label>
                      <input
                        v-model.trim="form.billingState"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">邮编</label>
                      <input
                        v-model.trim="form.billingZip"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">国家</label>
                      <input
                        v-model.trim="form.billingCountry"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                  </template>
                  <template v-if="form.paypalMode === 'create_account' && !form.autofillEnabled">
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">卡号</label>
                      <input
                        v-model.trim="form.paypalCardNumber"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">有效期</label>
                      <input
                        v-model.trim="form.paypalCardExpiry"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        placeholder="03/30"
                        :disabled="busy"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-gray-400 mb-1">CVV</label>
                      <input
                        v-model.trim="form.paypalCardCvv"
                        type="text"
                        class="w-full rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                        :disabled="busy"
                      />
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="space-y-4 min-w-0">
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <div class="text-xs text-gray-400">任务状态</div>
              <div class="mt-2 text-lg font-semibold text-white">{{ running ? '执行中' : (lastTask?.status || '空闲') }}</div>
            </div>
            <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <div class="text-xs text-gray-400">当前阶段</div>
              <div class="mt-2 text-sm font-semibold text-blue-300">{{ stageText }}</div>
            </div>
            <div class="rounded-xl border border-gray-800 bg-gray-900/80 p-4">
              <div class="text-xs text-gray-400">目标账号</div>
              <div class="mt-2 text-sm font-semibold text-emerald-300 truncate">{{ lastTask?.result?.email || lastTask?.params?.email || '-' }}</div>
            </div>
          </div>

          <div class="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-4">
            <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4 flex min-h-[260px] flex-col">
              <div class="mb-3 flex items-start justify-between gap-3">
                <div>
                  <div class="text-sm font-semibold text-white">Access Token</div>
                  <div class="text-xs text-gray-500 mt-0.5">自动生成链接时使用</div>
                </div>
                <button
                  class="shrink-0 rounded-lg border border-emerald-500/30 bg-emerald-600/10 px-3 py-1.5 text-xs text-emerald-300 transition hover:bg-emerald-600/20 disabled:opacity-50"
                  :disabled="busy || form.checkoutMode !== 'auto' || !bindForm.accessToken"
                  @click="generateLink"
                >
                  生成链接
                </button>
              </div>
              <textarea
                v-model.trim="bindForm.accessToken"
                class="min-h-0 flex-1 resize-none rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"
                placeholder="输入 access_token，或从账号提取"
                :disabled="busy || form.checkoutMode !== 'auto'"
              />
            </div>

            <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4 flex min-h-[260px] flex-col">
              <div class="mb-3 flex items-start justify-between gap-3">
                <div>
                  <div class="text-sm font-semibold text-white">Checkout 链接</div>
                  <div class="text-xs text-gray-500 mt-0.5">任务会用这个链接直接打开页面</div>
                </div>
                <div class="flex items-center gap-2">
                  <button
                    class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-800 disabled:opacity-50"
                    :disabled="!currentLink"
                    @click="copyCurrentLink"
                  >
                    复制
                  </button>
                  <button
                    class="rounded-lg border border-blue-500/30 bg-blue-600/10 px-3 py-1.5 text-xs text-blue-300 transition hover:bg-blue-600/20 disabled:opacity-50"
                    :disabled="!currentLink"
                    @click="openLink"
                  >
                    打开
                  </button>
                </div>
              </div>
              <div class="min-h-0 flex-1 overflow-y-auto rounded-lg border border-gray-800 bg-gray-900 p-3">
                <div v-if="!currentLink" class="text-sm text-gray-500">尚未准备好 checkout 链接</div>
                <div v-else class="break-all text-sm font-mono text-blue-400">
                  {{ currentLink }}
                </div>
              </div>
            </div>
          </div>

          <div class="rounded-xl border border-gray-800 bg-gray-950/80 h-[520px] min-h-0 flex flex-col overflow-hidden">
            <div class="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-800">
              <div>
                <div class="text-sm font-semibold text-white">实时日志</div>
                <div class="text-xs text-gray-400">展示当前任务与最近执行记录</div>
              </div>
              <button
                class="rounded-lg border border-gray-700 bg-gray-900 px-3 py-1.5 text-xs text-gray-300 transition hover:bg-gray-800"
                @click="refreshTask"
              >
                刷新
              </button>
            </div>
            <div class="min-h-0 flex-1 overflow-y-auto p-4 space-y-2">
              <div v-if="!selectedTask" class="text-sm text-gray-500">暂无任务</div>
              <div v-for="line in visibleLogs" :key="line.seq || line.ts || line.line" class="rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2">
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="text-[11px] text-gray-500">{{ formatTs(line.ts) }}</div>
                    <div class="mt-1 whitespace-pre-wrap break-words text-sm text-gray-100">{{ line.line }}</div>
                  </div>
                  <span class="shrink-0 rounded-full border px-2 py-0.5 text-[11px]" :class="line.statusClass">
                    {{ line.level }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'

const busy = ref(false)
const loadingAccounts = ref(false)
const loadingAccountToken = ref(false)
const accounts = ref([])
const selectedAccountEmail = ref('')
const accountSearchKeyword = ref('')
const message = ref('')
const messageClass = ref('bg-green-500/10 text-green-400 border-green-500/20')
const lastTask = ref(null)
const selectedTask = ref(null)
const pollTimer = ref(null)
const currentLink = ref('')
const restoredFormState = ref(false)
const PAYPAL_FORM_STATE_KEY = 'autoteam_paypal_form_state_v1'

const form = ref({
  checkoutMode: 'auto',
  checkoutUrl: '',
  proxyLabel: '',
  proxyUrl: '',
  manualConfirm: false,
  paypalMode: 'create_account',
  paypalEmail: '',
  paypalPassword: '',
  smsUrl: '',
  paypalCardNumber: '',
  paypalCardExpiry: '',
  paypalCardCvv: '',
  autofillEnabled: true,
  billingPhone: '',
  billingCountry: 'US',
  billingState: '',
  billingCity: '',
  billingZip: '',
  billingAddress1: '',
  billingAddress2: '',
  timeoutSeconds: 900,
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

const filteredAccountOptions = computed(() => {
  const keyword = accountSearchKeyword.value.trim().toLowerCase()
  const rows = Array.isArray(accounts.value) ? accounts.value : []
  const freeRows = rows.filter(isUsableFreeAccount)
  if (!keyword) return freeRows
  return freeRows.filter(account => String(account?.email || '').toLowerCase().includes(keyword))
})

const filteredPromoOptions = computed(() => promoOptions.filter(item => item.plan === bindForm.value.planType))
const running = computed(() => ['pending', 'running'].includes(String(lastTask.value?.status || '')))
const isCreateAccountMode = computed(() => form.value.paypalMode === 'create_account')
const stageText = computed(() => {
  const progress = lastTask.value?.progress || {}
  return progress.message || progress.stage || '-'
})

const visibleLogs = computed(() => {
  const task = selectedTask.value
  if (!task) return []
  const events = Array.isArray(task.progress_events) ? task.progress_events : []
  return events.slice(-200).map((item) => ({
    ...item,
    line: item.message || item.line || item.stage || '',
    level: item.level || item.stage || 'INFO',
    statusClass:
      item.level === 'error'
        ? 'border-rose-500/30 text-rose-300'
        : item.level === 'warn'
          ? 'border-amber-500/30 text-amber-300'
          : 'border-gray-700 text-gray-300',
  }))
})

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
    form: {
      checkoutMode: form.value.checkoutMode,
      checkoutUrl: form.value.checkoutUrl,
      proxyLabel: form.value.proxyLabel,
      proxyUrl: form.value.proxyUrl,
      manualConfirm: form.value.manualConfirm,
      paypalMode: form.value.paypalMode,
      paypalEmail: form.value.paypalEmail,
      smsUrl: form.value.smsUrl,
      paypalCardNumber: form.value.paypalCardNumber,
      paypalCardExpiry: form.value.paypalCardExpiry,
      paypalCardCvv: form.value.paypalCardCvv,
      autofillEnabled: form.value.autofillEnabled,
      billingPhone: form.value.billingPhone,
      billingCountry: form.value.billingCountry,
      billingState: form.value.billingState,
      billingCity: form.value.billingCity,
      billingZip: form.value.billingZip,
      billingAddress1: form.value.billingAddress1,
      billingAddress2: form.value.billingAddress2,
      timeoutSeconds: form.value.timeoutSeconds,
    },
    bindForm: {
      planType: bindForm.value.planType,
      promoId: bindForm.value.promoId,
      country: bindForm.value.country,
      currency: bindForm.value.currency,
      checkoutUiMode: bindForm.value.checkoutUiMode,
      teamWorkspaceName: bindForm.value.teamWorkspaceName,
      teamSeatQuantity: bindForm.value.teamSeatQuantity,
      teamPriceInterval: bindForm.value.teamPriceInterval,
      teamPromoCode: bindForm.value.teamPromoCode,
      teamCancelUrl: bindForm.value.teamCancelUrl,
    },
  }
}

function restorePayPalState() {
  try {
    const raw = localStorage.getItem(PAYPAL_FORM_STATE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return
    if (saved.form && typeof saved.form === 'object') {
      Object.assign(form.value, saved.form)
      form.value.paypalPassword = ''
    }
    if (saved.bindForm && typeof saved.bindForm === 'object') {
      Object.assign(bindForm.value, saved.bindForm)
      bindForm.value.accessToken = ''
    }
    selectedAccountEmail.value = String(saved.selectedAccountEmail || '').trim()
    accountSearchKeyword.value = String(saved.accountSearchKeyword || '')
    currentLink.value = String(saved.currentLink || form.value.checkoutUrl || '')
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
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString()
}

function buildBindLinkPayload(accessToken) {
  const planName = bindForm.value.planType === 'plus' ? 'chatgptplusplan' : 'chatgptteamplan'
  if (bindForm.value.planType === 'team') {
    return {
      access_token: accessToken,
      entry_point: 'team_workspace_purchase_modal',
      plan_name: planName,
      team_plan_data: {
        workspace_name: bindForm.value.teamWorkspaceName || '我的团队',
        price_interval: bindForm.value.teamPriceInterval || 'month',
        seat_quantity: Number(bindForm.value.teamSeatQuantity) || 2,
      },
      billing_details: {
        country: bindForm.value.country,
        currency: bindForm.value.currency,
      },
      cancel_url: bindForm.value.teamCancelUrl || undefined,
      promo_code: bindForm.value.teamPromoCode || undefined,
      checkout_ui_mode: 'hosted',
    }
  }

  return {
    access_token: accessToken,
    promo_campaign: {
      promo_campaign_id: bindForm.value.promoId,
      is_coupon_from_query_param: false,
    },
    plan_name: planName,
    billing_details: {
      country: bindForm.value.country,
      currency: bindForm.value.currency,
    },
    checkout_ui_mode: bindForm.value.checkoutUiMode,
  }
}

function resolveGeneratedLink(result) {
  if (result?.url) {
    return result.url
  }
  if (bindForm.value.planType === 'plus' && bindForm.value.checkoutUiMode === 'hosted') {
    return ''
  }
  if (result?.checkout_session_id) {
    const sessionId = result.checkout_session_id
    return bindForm.value.planType === 'team'
      ? `https://chatgpt.com/checkout/openai_ie/${sessionId}`
      : `https://chatgpt.com/checkout/openai_llc/${sessionId}`
  }
  return ''
}

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const result = await api.getAccounts({ includeSessionStubs: true })
    accounts.value = Array.isArray(result) ? result : (result?.accounts || [])
    if (selectedAccountEmail.value && !filteredAccountOptions.value.some(account => account.email === selectedAccountEmail.value)) {
      selectedAccountEmail.value = ''
      bindForm.value.accessToken = ''
    }
  } catch (error) {
    console.warn('PayPal 账号加载失败:', error)
  } finally {
    loadingAccounts.value = false
  }
}

async function useAccountToken() {
  if (!selectedAccountEmail.value) {
    setMessage('请先选择号池账号', false)
    return
  }
  loadingAccountToken.value = true
  try {
    const result = await api.getCodexAuth(selectedAccountEmail.value)
    const token = result?.codex_auth?.tokens?.access_token || ''
    if (!token) {
      throw new Error('对应 auth_session 文件中没有 accessToken')
    }
    bindForm.value.accessToken = token
    setMessage(`已提取 ${selectedAccountEmail.value} 的 access_token`)
  } catch (error) {
    setMessage(`提取 access_token 失败: ${error.message}`, false)
  } finally {
    loadingAccountToken.value = false
  }
}

async function generateLink() {
  if (!bindForm.value.accessToken) {
    setMessage('请先提供 access_token', false)
    return
  }
  busy.value = true
  try {
    const result = await api.generateBindLink(buildBindLinkPayload(bindForm.value.accessToken))
    const link = resolveGeneratedLink(result)
    if (!link) {
      throw new Error(result?.detail || '未返回可用支付链接')
    }
    currentLink.value = link
    form.value.checkoutUrl = link
    setMessage('支付链接已生成')
  } catch (error) {
    setMessage(`生成链接失败: ${error.message}`, false)
  } finally {
    busy.value = false
  }
}

async function ensureCheckoutUrl() {
  if (form.value.checkoutMode === 'manual') {
    const manualLink = String(form.value.checkoutUrl || '').trim()
    if (!manualLink) {
      throw new Error('请先输入 checkout 链接')
    }
    currentLink.value = manualLink
    return manualLink
  }

  const existing = String(form.value.checkoutUrl || '').trim()
  if (existing) {
    currentLink.value = existing
    return existing
  }

  if (!bindForm.value.accessToken) {
    if (!selectedAccountEmail.value) {
      throw new Error('请先选择账号，或手动提供 access_token')
    }
    const result = await api.getCodexAuth(selectedAccountEmail.value)
    const token = result?.codex_auth?.tokens?.access_token || ''
    if (!token) {
      throw new Error('对应 auth_session 文件中没有 accessToken')
    }
    bindForm.value.accessToken = token
  }

  const result = await api.generateBindLink(buildBindLinkPayload(bindForm.value.accessToken))
  const link = resolveGeneratedLink(result)
  if (!link) {
    throw new Error(result?.detail || '自动生成支付链接失败')
  }
  currentLink.value = link
  form.value.checkoutUrl = link
  return link
}

async function refreshTask() {
  try {
    const tasks = await api.getTasks(true)
    const paypalTasks = Array.isArray(tasks) ? tasks.filter(task => task?.command === 'paypal') : []
    const active = paypalTasks.find(task => ['running', 'pending'].includes(String(task?.status || '')))
    selectedTask.value = active || paypalTasks[0] || null
    lastTask.value = selectedTask.value
  } catch (error) {
    console.warn('PayPal 任务刷新失败:', error)
  }
}

async function startTask() {
  if (!selectedAccountEmail.value) {
    setMessage('请先选择号池账号', false)
    return
  }
  if (!form.value.manualConfirm) {
    if (isCreateAccountMode.value) {
      if (!String(form.value.billingPhone || '').trim()) {
        setMessage('自动注册模式需要填写 PayPal 注册手机号', false)
        return
      }
      if (!String(form.value.smsUrl || '').trim()) {
        setMessage('自动注册模式需要填写接码 API', false)
        return
      }
      if (!form.value.autofillEnabled) {
        if (!String(form.value.paypalCardNumber || '').trim()) {
          setMessage('自动注册模式需要填写卡号', false)
          return
        }
        if (!String(form.value.paypalCardExpiry || '').trim()) {
          setMessage('自动注册模式需要填写卡有效期', false)
          return
        }
        if (!String(form.value.paypalCardCvv || '').trim()) {
          setMessage('自动注册模式需要填写 CVV', false)
          return
        }
      }
    } else {
      if (!String(form.value.paypalEmail || '').trim()) {
        setMessage('已有账号模式需要填写 PayPal 邮箱', false)
        return
      }
      if (!String(form.value.paypalPassword || '').trim()) {
        setMessage('已有账号模式需要填写 PayPal 密码', false)
        return
      }
    }
  }

  busy.value = true
  try {
    const checkoutUrl = await ensureCheckoutUrl()
    const task = await api.startPayPal({
      runner_mode: 'manual_checkout',
      email: selectedAccountEmail.value,
      checkout_url: checkoutUrl,
      proxy_url: form.value.proxyUrl || null,
      proxy_label: form.value.proxyLabel,
      manual_confirm: Boolean(form.value.manualConfirm),
      paypal_mode: form.value.paypalMode,
      paypal_email: isCreateAccountMode.value ? '' : form.value.paypalEmail,
      paypal_password: isCreateAccountMode.value ? '' : form.value.paypalPassword,
      sms_url: form.value.smsUrl,
      otp_channel: 'sms',
      paypal_card_number: form.value.paypalCardNumber,
      paypal_card_expiry: form.value.paypalCardExpiry,
      paypal_card_cvv: form.value.paypalCardCvv,
      autofill_enabled: Boolean(form.value.autofillEnabled),
      billing_name: '',
      billing_email: selectedAccountEmail.value,
      billing_phone: form.value.billingPhone,
      billing_country: form.value.billingCountry,
      billing_state: form.value.billingState,
      billing_city: form.value.billingCity,
      billing_zip: form.value.billingZip,
      billing_address1: form.value.billingAddress1,
      billing_address2: form.value.billingAddress2,
      timeout_seconds: Number(form.value.timeoutSeconds || 900),
    })
    lastTask.value = task
    selectedTask.value = task
    setMessage(`PayPal 任务已提交: ${task.task_id}`)
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
  () => bindForm.value.planType,
  (planType) => {
    if (planType === 'team') {
      bindForm.value.country = 'US'
      bindForm.value.currency = 'USD'
      bindForm.value.checkoutUiMode = 'hosted'
    } else {
      if (!filteredPromoOptions.value.find(item => item.id === bindForm.value.promoId)) {
        bindForm.value.promoId = filteredPromoOptions.value[0]?.id || ''
      }
    }
  },
  { immediate: true }
)

watch(
  () => bindForm.value.country,
  (country) => {
    bindForm.value.currency = countryCurrencyMap[country] || 'USD'
  },
  { immediate: true }
)

watch(
  [form, bindForm, selectedAccountEmail, accountSearchKeyword, currentLink],
  savePayPalState,
  { deep: true }
)

onMounted(async () => {
  restorePayPalState()
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
