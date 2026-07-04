<template>
  <div>
    <div
      v-if="gopaySuccessNoticeVisible"
      class="fixed top-6 left-1/2 z-[60] w-[min(92vw,520px)] -translate-x-1/2 rounded-xl border border-emerald-500/40 bg-gray-950 px-5 py-4 shadow-2xl">
      <div class="text-sm font-semibold text-emerald-300">GoPay 绑定成功</div>
      <div class="mt-1 text-sm text-gray-200">
        请在手机上解绑 OPENAI<span v-if="gopaySuccessNoticeEmail">：{{ gopaySuccessNoticeEmail }}</span>
      </div>
    </div>

    <div
      class="mb-6 grid grid-cols-1 gap-4"
      :class="activeTab === 'gopay' ? 'xl:grid-cols-[420px_minmax(0,1fr)] xl:items-start' : ''">
      <div>
        <h2 class="text-xl font-bold text-white mb-2">{{ standalone ? 'GoPay' : '自动绑卡服务' }}</h2>
        <p class="text-sm text-gray-400" :class="!standalone ? 'mb-4' : ''">
          {{ standalone
            ? '走印尼区 GoPay 支付链路，自动处理 OTP、短信验证码和 PIN 提交。'
            : '支持生成官方支付链接，以及 ChatGPT、Kiro 绑卡流程。' }}
        </p>
        <div v-if="!standalone" class="flex flex-wrap gap-2">
          <button
            @click="activeTab = 'bind'"
            class="px-4 py-2 rounded-lg text-sm border transition"
            :class="activeTab === 'bind'
              ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
              : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
            ChatGPT
          </button>
          <button
            @click="activeTab = 'kiro'"
            class="px-4 py-2 rounded-lg text-sm border transition"
            :class="activeTab === 'kiro'
              ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
              : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
            Kiro
          </button>
          <button
            @click="activeTab = 'generate'"
            class="px-4 py-2 rounded-lg text-sm border transition"
            :class="activeTab === 'generate'
              ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
              : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
            生成支付链接
          </button>
        </div>
      </div>
      <div
        v-if="activeTab === 'gopay'"
        class="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div
          v-for="card in gopayTopCards"
          :key="card.label"
          class="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3 min-w-0">
          <div class="text-xs text-gray-400">{{ card.label }}</div>
          <div class="mt-2 text-xl font-bold truncate" :class="card.color">{{ card.value }}</div>
          <div v-if="card.meta" class="mt-1 text-[11px] text-gray-500 truncate">{{ card.meta }}</div>
        </div>
      </div>
    </div>

    <div v-if="activeTab === 'generate'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
      <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <h3 class="text-lg font-semibold text-white">生成支付链接</h3>
          <p class="text-sm text-gray-400 mt-1">
            选择套餐类型和国家/货币，系统将生成官方绑卡链接。
          </p>
        </div>
      </div>

      <div v-if="message" class="mt-4 px-4 py-3 rounded-lg text-sm border" :class="messageClass">
        {{ message }}
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)] gap-4 items-stretch">
        <div class="min-w-0 space-y-3">
          <div>
            <label class="block text-sm text-gray-400 mb-1">套餐类型</label>
            <select
              v-model="bindForm.planType"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="plan in bindPlanOptions" :key="plan.value" :value="plan.value">
                {{ plan.label }}
              </option>
            </select>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">号池账号</label>
            <input
              v-model.trim="accountSearchKeyword"
              type="text"
              :disabled="generating || loadingAccounts"
              placeholder="搜索邮箱，例如 openaibus.com"
              class="w-full mb-2 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <div class="flex gap-2">
              <select
                v-model="selectedAccountEmail"
                :disabled="generating || loadingAccounts"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option value="">{{ loadingAccounts ? '加载账号中...' : filteredAccountOptions.length ? `共 ${filteredAccountOptions.length} 个匹配账号` : '没有匹配账号' }}</option>
                <option v-for="account in filteredAccountOptions" :key="account.email" :value="account.email">
                  {{ account.email }}
                </option>
              </select>
              <button
                @click="useAccountToken"
                :disabled="generating || loadingAccounts || loadingAccountToken || !selectedAccountEmail"
                class="shrink-0 px-4 py-2 rounded-lg text-sm border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition disabled:opacity-50">
                {{ loadingAccountToken ? '提取中...' : '提取 Token' }}
              </button>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">国家</label>
            <select
              v-model="bindForm.country"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="item in bindCountryOptions" :key="item.country" :value="item.country">
                {{ item.label }}
              </option>
            </select>
          </div>

          <template v-if="bindForm.planType === 'team'">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label class="block text-sm text-gray-400 mb-1">工作区名称</label>
                <input
                  v-model.trim="bindForm.teamWorkspaceName"
                  :disabled="generating"
                  type="text"
                  placeholder="例如 我的团队"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label class="block text-sm text-gray-400 mb-1">席位数</label>
                <input
                  v-model.number="bindForm.teamSeatQuantity"
                  :disabled="generating"
                  type="number"
                  min="1"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label class="block text-sm text-gray-400 mb-1">计费周期</label>
                <select
                  v-model="bindForm.teamPriceInterval"
                  :disabled="generating"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="month">month</option>
                  <option value="year">year</option>
                </select>
              </div>
            </div>
          </template>

            <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
              <div>套餐：<span class="text-gray-200">{{ selectedPlanName }}</span></div>
              <div>国家：<span class="text-gray-200">{{ bindForm.country }}</span> / 货币：<span class="text-gray-200">{{ bindForm.currency }}</span></div>
              <div>链接类型：<span class="text-gray-200">Hosted 长链（pay.openai.com/c/pay）</span></div>
              <template v-if="bindForm.planType === 'team'">
                <div>工作区：<span class="text-gray-200">{{ bindForm.teamWorkspaceName || '-' }}</span></div>
                <div>席位 / 周期：<span class="text-gray-200">{{ bindForm.teamSeatQuantity || 2 }} / {{ bindForm.teamPriceInterval }}</span></div>
              </template>
            </div>

            <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-4 space-y-3">
              <div class="text-xs text-gray-500">
                可先生成链接，也可直接使用所选号池账号的 auth_session 打开支付页。
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button
                  @click="generateLink"
                  :disabled="generating || !bindForm.accessToken"
                  class="px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition disabled:opacity-50">
                  {{ generating ? '生成中...' : '生成绑卡链接' }}
                </button>
                <button
                  @click="generateAndOpenWithAuthSession"
                  :disabled="generating || !selectedAccountEmail"
                  class="px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50">
                  {{ generating ? '打开中...' : '生成并打开' }}
                </button>
              </div>
            </div>

        </div>

        <div class="min-w-0 min-h-0 space-y-4">
          <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 h-[270px] flex flex-col">
            <div class="mb-3 flex items-start justify-between gap-3">
              <div>
                <h3 class="text-white font-semibold">Access Token</h3>
                <div class="text-xs text-gray-500 mt-0.5">输入 ChatGPT access_token</div>
              </div>
            </div>
            <textarea
              v-model.trim="bindForm.accessToken"
              placeholder="输入 ChatGPT access_token"
              :disabled="generating"
              class="flex-1 min-h-0 w-full resize-none px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 h-[170px] flex flex-col">
            <div class="mb-3">
              <h3 class="text-white font-semibold">支付链接</h3>
                <div class="text-xs text-gray-500 mt-0.5">生成后可复制或直接打开</div>
            </div>
            <div class="link-panel flex-1 min-h-0 rounded-lg border border-gray-800 bg-gray-900 p-3 overflow-y-auto" style="scrollbar-width: none; -ms-overflow-style: none;">
              <div v-if="!currentLink" class="text-sm text-gray-500">
                尚未生成链接，请先配置并点击"生成绑卡链接"
              </div>
              <div v-else class="space-y-3">
                <div class="text-sm text-blue-400 whitespace-nowrap font-mono select-all overflow-x-auto" style="scrollbar-width: none; -ms-overflow-style: none;">
                  {{ currentLink }}
                </div>
              </div>
            </div>
            <div class="mt-3 flex items-center gap-3">
              <button
                @click="copyCurrentLink"
                :disabled="!currentLink"
                class="px-3 py-1.5 rounded-lg text-xs border transition disabled:opacity-50"
                :class="currentLink
                  ? 'bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border-emerald-500/30'
                  : 'bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700'">
                复制链接
              </button>
              <button
                @click="openLink"
                :disabled="!currentLink"
                class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition disabled:opacity-50">
                打开链接
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="activeTab === 'bind'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
      <div class="mb-4">
        <h3 class="text-lg font-semibold text-white">ChatGPT</h3>
        <p class="text-sm text-gray-400 mt-1">
          选择号池账号后，可手动输入支付链接；留空时系统会先自动生成支付链接，再提交绑卡任务。
        </p>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)] gap-4">
        <div class="space-y-3">
          <div>
            <label class="block text-sm text-gray-400 mb-1">号池账号</label>
            <input
              v-model.trim="accountSearchKeyword"
              type="text"
              :disabled="bindSubmitting || bindTaskRunning || loadingAccounts"
              placeholder="搜索邮箱，例如 openaibus.com"
              class="w-full mb-2 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <select
              v-model="selectedAccountEmail"
              :disabled="bindSubmitting || bindTaskRunning || loadingAccounts"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="">{{ loadingAccounts ? '加载账号中...' : filteredAccountOptions.length ? `共 ${filteredAccountOptions.length} 个匹配账号` : '没有匹配账号' }}</option>
              <option v-for="account in filteredAccountOptions" :key="account.email" :value="account.email">
                {{ account.email }}
              </option>
            </select>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">虚拟卡</label>
            <select
              v-model="bindTaskForm.cardItemId"
              :disabled="bindSubmitting || bindTaskRunning || loadingCards"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="">{{ loadingCards ? '加载卡池中...' : '请选择未使用卡' }}</option>
              <option v-for="card in availableCards" :key="card.id" :value="card.id">
                {{ formatCardOption(card) }}
              </option>
            </select>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-2">Checkout 链接模式</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="bindTaskForm.checkoutMode = 'auto'"
                :disabled="bindSubmitting || bindTaskRunning"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="bindTaskForm.checkoutMode === 'auto'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                自动生成
              </button>
              <button
                @click="bindTaskForm.checkoutMode = 'manual'"
                :disabled="bindSubmitting || bindTaskRunning"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="bindTaskForm.checkoutMode === 'manual'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                手动添加
              </button>
            </div>
          </div>

          <div v-if="bindTaskForm.checkoutMode === 'auto'" class="rounded-lg border border-gray-800 bg-gray-800/30 p-3 space-y-4">
            <div>
              <label class="block text-sm text-gray-400 mb-1">套餐类型</label>
              <select
                v-model="bindForm.planType"
                :disabled="bindSubmitting || bindTaskRunning"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-for="plan in bindPlanOptions" :key="plan.value" :value="plan.value">
                  {{ plan.label }}
                </option>
              </select>
            </div>

            <div>
              <label class="block text-sm text-gray-400 mb-1">国家</label>
              <select
                v-model="bindForm.country"
                :disabled="bindSubmitting || bindTaskRunning"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-for="item in bindCountryOptions" :key="item.country" :value="item.country">
                  {{ item.label }}
                </option>
              </select>
            </div>

            <template v-if="bindForm.planType === 'team'">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-1">工作区名称</label>
                  <input
                    v-model.trim="bindForm.teamWorkspaceName"
                    :disabled="bindSubmitting || bindTaskRunning"
                    type="text"
                    placeholder="例如 我的团队"
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label class="block text-sm text-gray-400 mb-1">席位数</label>
                  <input
                    v-model.number="bindForm.teamSeatQuantity"
                    :disabled="bindSubmitting || bindTaskRunning"
                    type="number"
                    min="1"
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>

              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-1">计费周期</label>
                  <select
                    v-model="bindForm.teamPriceInterval"
                    :disabled="bindSubmitting || bindTaskRunning"
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                  >
                    <option value="month">month</option>
                    <option value="year">year</option>
                  </select>
                </div>
              </div>
            </template>

          </div>

          <div v-else>
            <label class="block text-sm text-gray-400 mb-1">Checkout 链接</label>
            <input
              v-model.trim="bindTaskForm.checkoutUrl"
              type="text"
              :disabled="bindSubmitting || bindTaskRunning"
              placeholder="手动粘贴支付链接"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <label class="inline-flex items-center gap-2 text-sm text-gray-300">
              <input
                v-model="bindTaskForm.proxyApiEnabled"
                type="checkbox"
                :disabled="bindSubmitting || bindTaskRunning"
                class="accent-blue-500"
              />
              启用 Cliproxy API 轮换
            </label>
            <div v-if="bindTaskForm.proxyApiEnabled" class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label class="block text-sm text-gray-400 mb-1">代理国家</label>
                <select
                  v-model="bindTaskForm.proxyApiCountry"
                  :disabled="bindSubmitting || bindTaskRunning"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option v-for="option in bindCountryOptions" :key="`bind-proxy-${option.country}`" :value="option.country">
                    {{ option.label }}
                  </option>
                </select>
              </div>
              <div>
                <label class="block text-sm text-gray-400 mb-1">Cliproxy API URL（可选）</label>
                <input
                  v-model.trim="bindTaskForm.proxyApiUrl"
                  type="text"
                  :disabled="bindSubmitting || bindTaskRunning"
                  placeholder="留空使用默认 Cliproxy 白名单 API"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
            <div class="mt-2 text-xs" :class="bindTaskForm.proxyApiEnabled ? 'text-blue-300' : 'text-gray-500'">
              {{ bindProxyApiHelp }}
            </div>
          </div>

          <div class="text-xs text-emerald-300/90">
            自动绑卡会在填写完成后自动点击“订阅”，无需人工确认。
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>账号：<span class="text-gray-200">{{ selectedAccountEmail || '-' }}</span></div>
            <div>卡片：<span class="text-gray-200">{{ selectedCardLabel || '-' }}</span></div>
            <div>链接模式：<span class="text-gray-200">{{ bindTaskForm.checkoutMode === 'auto' ? '自动生成' : '手动添加' }}</span></div>
            <div>链接：<span class="text-gray-200 break-all">{{ effectiveCheckoutUrl || '-' }}</span></div>
            <div>代理 API：<span class="text-gray-200">{{ bindTaskForm.proxyApiEnabled ? `Cliproxy / ${bindTaskForm.proxyApiCountry}` : '未启用' }}</span></div>
            <div>模式：<span class="text-gray-200">自动提交</span></div>
          </div>

          <button
            @click="startBindCard"
            :disabled="bindSubmitting || bindTaskRunning || !selectedAccountEmail || !bindTaskForm.cardItemId"
            class="w-full px-4 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50">
            {{ bindSubmitting ? '提交中...' : bindTaskRunning ? '任务运行中...' : '开始绑卡' }}
          </button>
          <button
            v-if="bindTaskRunning"
            @click="cancelBindTask"
            :disabled="bindCancelling"
            class="w-full px-4 py-2 rounded-lg text-sm border bg-red-600/15 hover:bg-red-600/25 text-red-300 border-red-500/30 transition disabled:opacity-50">
            {{ bindCancelling ? '取消中...' : '取消任务' }}
          </button>
        </div>

        <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 min-w-0 flex flex-col">
          <div class="flex items-center justify-between gap-3 mb-3">
            <div class="text-sm text-gray-400">实时绑卡日志</div>
            <div v-if="bindTask" class="text-xs text-gray-500 font-mono">
              {{ bindTask.task_id }}
            </div>
          </div>
          <div class="rounded-lg border border-gray-800 bg-gray-900 p-3 flex-1 min-h-[420px] overflow-y-auto space-y-2">
            <div v-if="!bindLogEntries.length" class="text-sm text-gray-500">
              尚未提交绑卡任务。
            </div>
            <div
              v-for="entry in bindLogEntries"
              :key="entry.id"
              class="rounded-lg border border-gray-800 bg-gray-950/80 px-3 py-2"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="text-xs font-mono text-gray-500">{{ entry.time }}</span>
                <span class="text-[11px] uppercase tracking-wide" :class="entry.levelClass">{{ entry.label }}</span>
              </div>
              <div class="mt-1 text-sm text-gray-200 break-all">{{ entry.message }}</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="activeTab === 'kiro'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
      <div class="mb-4">
        <h3 class="text-lg font-semibold text-white">Kiro</h3>
        <p class="text-sm text-gray-400 mt-1">
          Kiro 绑卡任务。
        </p>
      </div>
      <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-6 text-sm text-gray-400">
        当前没有可提交的 Kiro 绑卡任务。
      </div>
    </div>

    <div v-else-if="activeTab === 'gopay'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6 xl:h-[calc(100vh-150px)] xl:min-h-0 xl:flex xl:flex-col xl:overflow-hidden">
      <div class="grid grid-cols-1 gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[480px_minmax(0,1fr)] xl:overflow-hidden">
        <div class="flex flex-col gap-3 xl:min-h-0">
          <div class="shrink-0 rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="flex flex-col gap-3 sm:flex-row">
              <button
                @click="startGoPayBind"
                :disabled="gopaySubmitting || gopayTaskRunning || !gopayCanSubmit"
                class="w-full px-4 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50">
                {{ gopaySubmitting ? '提交中...' : gopayTaskRunning ? '任务运行中...' : (gopayForm.autoRegister ? '自动注册并 GoPay 绑卡' : gopayBatchActive ? '开始批量 GoPay 绑卡' : '开始 GoPay 绑卡') }}
              </button>
              <button
                v-if="gopayTaskRunning"
                @click="skipGoPayCurrentAccount"
                :disabled="gopaySkipping || !gopaySkipAvailable"
                class="w-full px-4 py-2 rounded-lg text-sm border bg-amber-600/15 hover:bg-amber-600/25 text-amber-200 border-amber-500/30 transition disabled:opacity-50">
                {{ gopaySkipping ? '跳过中...' : '跳过当前账号' }}
              </button>
              <button
                v-if="gopayTaskRunning"
                @click="cancelGoPayTask"
                :disabled="gopayCancelling"
                class="w-full px-4 py-2 rounded-lg text-sm border bg-red-600/15 hover:bg-red-600/25 text-red-300 border-red-500/30 transition disabled:opacity-50">
                {{ gopayCancelling ? '取消中...' : '取消任务' }}
              </button>
            </div>
            <div v-if="gopayTaskRunning" class="mt-3 rounded-lg border border-emerald-500/20 bg-emerald-500/10 p-3">
              <div class="mb-2 text-xs font-medium text-emerald-100">运行中热切换</div>
              <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">并发数</label>
                  <input
                    v-model.number="gopayRuntimeConcurrency"
                    type="number"
                    min="1"
                    max="10"
                    step="1"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">短信服务商</label>
                  <select
                    v-model="gopayRuntimeSmsProvider"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="smscloud">smscloud</option>
                    <option value="hero_sms">hero-sms</option>
                    <option value="smsbower">smsbower</option>
                    <option value="smscode">smscode.gg</option>
                  </select>
                </div>
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">余额查询间隔(s)</label>
                  <input
                    v-model.number="gopayRuntimeBalancePollIntervalSeconds"
                    type="number"
                    min="0"
                    max="300"
                    step="1"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label class="mb-1 block text-xs text-emerald-200/80">转账到账等待(s)</label>
                  <input
                    v-model.number="gopayRuntimeTransferBalanceWaitSeconds"
                    type="number"
                    min="0"
                    max="1800"
                    step="1"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>
              <div class="mt-2 rounded-lg border border-emerald-500/20 bg-gray-900/70 px-3 py-3">
                <div class="flex items-center justify-between gap-3">
                  <div class="min-w-0">
                    <div class="mb-1 text-xs text-emerald-200/80">追加账号</div>
                    <div class="text-sm text-gray-200">已选择 {{ gopayRuntimeAppendEmails.length }} 个待追加账号</div>
                  </div>
                  <button
                    type="button"
                    @click="openGoPayAccountPicker('runtime')"
                    :disabled="loadingAccounts"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-200 border-emerald-500/30 transition disabled:opacity-50"
                  >
                    {{ loadingAccounts ? '加载中...' : '选择账号' }}
                  </button>
                </div>
                <div v-if="gopayRuntimeAppendEmails.length" class="mt-2 flex flex-wrap gap-2">
                  <span
                    v-for="email in gopayRuntimeAppendPreviewEmails"
                    :key="`runtime-append-${email}`"
                    class="max-w-full truncate rounded-md border border-emerald-500/20 bg-gray-950 px-2 py-1 text-xs text-gray-300 font-mono">
                    {{ email }}
                  </span>
                  <span v-if="gopayRuntimeAppendEmails.length > gopayRuntimeAppendPreviewEmails.length" class="rounded-md border border-emerald-500/20 bg-gray-950 px-2 py-1 text-xs text-gray-500">
                    +{{ gopayRuntimeAppendEmails.length - gopayRuntimeAppendPreviewEmails.length }}
                  </span>
                </div>
              </div>
              <button
                type="button"
                @click="applyGoPayRuntimeControl"
                :disabled="gopayRuntimeUpdating"
                class="mt-2 w-full px-4 py-2 rounded-lg text-sm bg-emerald-600 hover:bg-emerald-500 text-white transition disabled:opacity-50"
              >
                {{ gopayRuntimeUpdating ? '应用中...' : '应用热切换' }}
              </button>
            </div>
          </div>

          <div class="space-y-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:pr-2 xl:pb-2">
          <div>
            <div class="flex items-center justify-between gap-3 mb-1">
              <label class="block text-sm text-gray-400">号池账号</label>
              <div class="flex items-center gap-3">
                <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                  <input
                    v-model="gopayForm.autoRegister"
                    type="checkbox"
                    :disabled="gopaySubmitting || gopayTaskRunning || Boolean(gopayForm.checkoutUrl)"
                    @change="handleGoPayAutoRegisterToggle"
                    class="accent-blue-500"
                  />
                  自动注册
                </label>
                <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                  <input
                    v-model="gopayForm.batchMode"
                    type="checkbox"
                    :disabled="gopaySubmitting || gopayTaskRunning || Boolean(gopayForm.checkoutUrl) || gopayForm.autoRegister"
                    class="accent-blue-500"
                  />
                  批量绑定
                </label>
                <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                  <input
                    v-model="gopayForm.gopayAutoSignup"
                    type="checkbox"
                    :disabled="gopaySubmitting || gopayTaskRunning"
                    class="accent-emerald-500"
                  />
                  自动注册 GoPay
                </label>
              </div>
            </div>
            <div v-if="gopayForm.autoRegister && !gopayForm.checkoutUrl" class="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-3">
              <div class="flex items-start justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-sm text-blue-200">运行时自动注册 {{ normalizedGoPayAutoRegisterCount }} 个 Free 账号，保存 auth_session 后逐个执行 GoPay 绑定。</div>
                  <div class="mt-1 text-xs text-gray-400">注册配置：{{ gopayAutoRegisterConfigSummary }}</div>
                </div>
                <button
                  type="button"
                  @click="openGoPayAutoRegisterConfig"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-blue-600/15 hover:bg-blue-600/25 text-blue-200 border-blue-500/30 transition disabled:opacity-50">
                  配置
                </button>
              </div>
              <div class="mt-3">
                <label class="block text-xs text-gray-400 mb-1">自动注册数量</label>
                <input
                  v-model.number="gopayForm.autoRegisterCount"
                  type="number"
                  min="1"
                  max="100"
                  step="1"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="w-36 px-3 py-2 bg-gray-900 border border-blue-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <label class="mt-3 flex items-start gap-2 text-sm text-blue-100">
                <input
                  v-model="gopayForm.autoRegisterProtocol"
                  type="checkbox"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="mt-1 accent-blue-500"
                />
                <span>
                  协议注册
                  <span class="block text-xs text-gray-400">默认使用浏览器注册；勾选后自动注册账号走协议流程。</span>
                </span>
              </label>
            </div>
            <template v-else-if="!gopayForm.batchMode || gopayForm.checkoutUrl">
              <input
                v-model.trim="gopayAccountSearchKeyword"
                type="text"
                :disabled="gopaySubmitting || gopayTaskRunning || loadingAccounts"
                placeholder="搜索邮箱，例如 openaibus.com"
                class="w-full mb-2 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
              <select
                v-model="gopayForm.email"
                :disabled="gopaySubmitting || gopayTaskRunning || loadingAccounts"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option value="">{{ loadingAccounts ? '加载账号中...' : filteredGoPayAccountOptions.length ? `共 ${filteredGoPayAccountOptions.length} 个匹配账号` : '没有匹配账号' }}</option>
                <option v-for="account in filteredGoPayAccountOptions" :key="account.email" :value="account.email">
                  {{ account.email }}
                </option>
              </select>
            </template>
            <div v-else class="rounded-lg border border-gray-700 bg-gray-800/60 p-3">
              <div class="flex items-center justify-between gap-3">
                <div class="min-w-0">
                  <div class="text-xs text-gray-500">当前选择</div>
                  <div class="mt-1 text-sm text-gray-200 font-mono truncate">
                    {{ gopayAccountSelectionLabel }}
                  </div>
                </div>
                <button
                  type="button"
                  @click="openGoPayAccountPicker('batch')"
                  :disabled="gopaySubmitting || gopayTaskRunning || loadingAccounts"
                  class="shrink-0 px-4 py-2 rounded-lg text-sm border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition disabled:opacity-50">
                  {{ loadingAccounts ? '加载中...' : '选择账号' }}
                </button>
              </div>
              <div v-if="gopayBatchActive" class="mt-2 flex flex-wrap gap-2">
                <span
                  v-for="email in gopayBatchPreviewEmails"
                  :key="`selected-${email}`"
                  class="max-w-full truncate rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-300 font-mono">
                  {{ email }}
                </span>
                <span v-if="gopaySelectedBatchEmails.length > gopayBatchPreviewEmails.length" class="rounded-md border border-gray-700 bg-gray-900 px-2 py-1 text-xs text-gray-500">
                  +{{ gopaySelectedBatchEmails.length - gopayBatchPreviewEmails.length }}
                </span>
              </div>
            </div>
            <div v-if="gopayForm.batchMode && !gopayForm.checkoutUrl" class="mt-1 text-xs text-gray-500">
              已选择 {{ gopaySelectedBatchEmails.length }} 个账号；仅在 ChatGPT approve 返回 blocked 时切换下一个。
            </div>
            <div v-if="gopayForm.autoRegister && !gopayForm.checkoutUrl" class="mt-1 text-xs text-gray-500">
              自动注册模式会按数量循环执行：注册一个账号，立即绑定一个账号。
            </div>
            <div v-if="gopayAutoSignupEnabled" class="mt-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-3">
              <div class="text-sm text-emerald-100">绑定前先自动注册 GoPay 钱包，并复用同一个短信服务商会话完成后续绑定 OTP。</div>
              <div class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs text-emerald-200/80 mb-1">注册模式</label>
                  <select
                    v-model="gopayForm.gopayAutoSignupMode"
                    :disabled="gopaySubmitting || gopayTaskRunning"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="http">协议绑定</option>
                    <option value="appium">Appium</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-emerald-200/80 mb-1">短信服务商</label>
                  <select
                    v-model="gopayForm.gopayAutoSignupSmsProvider"
                    :disabled="gopaySubmitting || gopayTaskRunning"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="smscloud">smscloud</option>
                    <option value="hero_sms">hero-sms</option>
                    <option value="smsbower">smsbower</option>
                    <option value="smscode">smscode.gg</option>
                  </select>
                </div>
                <div>
                  <label class="block text-xs text-emerald-200/80 mb-1">自动注册 GoPay PIN</label>
                  <input
                    v-model.trim="gopayForm.gopayPin"
                    type="password"
                    :disabled="gopaySubmitting || gopayTaskRunning"
                    placeholder="自动注册后用于绑定与扣款的 GoPay PIN"
                    class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div v-if="gopayForm.gopayAutoSignupMode === 'appium'">
                  <label class="block text-xs text-emerald-200/80 mb-1">Appium URL</label>
                  <input
                    :value="String(gopayAutoSignupConfig?.appium_url || 'http://127.0.0.1:4723')"
                    type="text"
                    readonly
                    class="w-full px-3 py-2 bg-gray-950 border border-emerald-500/10 rounded-lg text-sm text-gray-300 focus:outline-none"
                  />
                </div>
                <div v-if="gopayForm.gopayAutoSignupMode === 'appium'">
                  <label class="block text-xs text-emerald-200/80 mb-1">ADB Serial</label>
                  <input
                    :value="String(gopayAutoSignupConfig?.appium_adb_serial || '')"
                    type="text"
                    readonly
                    class="w-full px-3 py-2 bg-gray-950 border border-emerald-500/10 rounded-lg text-sm text-gray-300 focus:outline-none"
                  />
                </div>
                <label
                  class="md:col-span-2 inline-flex items-start gap-2 rounded-lg border px-3 py-2 text-xs"
                  :class="rekberinajaTransferEnabled
                    ? 'border-gray-800 bg-gray-950/40 text-gray-500'
                    : 'border-emerald-500/20 bg-gray-950/50 text-emerald-100'"
                >
                  <input
                    v-model="gopayForm.gopayBalanceWaitFallbackTransfer"
                    type="checkbox"
                    class="mt-0.5 accent-blue-500"
                    :disabled="gopaySubmitting || gopayTaskRunning || rekberinajaTransferEnabled"
                  />
                  <span>
                    GoPay 余额等待 120s 仍未到账时回退 Rekberinaja 转账
                    <span class="block mt-1 text-gray-500">
                      {{ rekberinajaTransferEnabled ? '设置中已开启 Rekberinaja 转账，本任务会维持原转账流程。' : '仅在设置中 Rekberinaja 转账关闭时可选；需已保存 Rekberinaja 账号凭证。' }}
                    </span>
                  </span>
                </label>
                <div class="md:col-span-2 rounded-lg border px-3 py-2 text-xs break-words whitespace-normal" :class="gopayAutoSignupProviderConfigured ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100' : 'border-amber-500/30 bg-amber-500/10 text-amber-100'">
                  <div class="font-medium">{{ gopayAutoSignupConfigLoading ? '正在检查短信凭证配置...' : gopayAutoSignupProviderConfigured ? gopayAutoSignupConfiguredMessage : '短信凭证未配置' }}</div>
                  <div v-if="!gopayAutoSignupProviderConfigured" class="mt-1 opacity-80 leading-relaxed">
                    {{ gopayAutoSignupMissingMessage }}
                  </div>
                  <div v-if="gopayForm.gopayAutoSignupMode === 'appium'" class="mt-2 opacity-80 leading-relaxed">
                    当前任务将走 Appium 真实 APP 注册；Appium URL / ADB Serial 请到“设置 → GoPay 自动注册”中修改。
                  </div>
                </div>
                <div v-if="gopayAutoSignupProvider === 'hero_sms'" class="md:col-span-2 rounded-lg border border-emerald-500/20 bg-gray-950/50 px-3 py-3">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <div class="text-sm font-medium text-emerald-100">Hero-SMS 实时价格</div>
                      <div class="mt-1 text-xs text-gray-500">先按最低价/上限过滤，再优先尝试指定档位。</div>
                    </div>
                    <button
                      type="button"
                      @click="queryGoPayHeroSmsPrices"
                      :disabled="gopayHeroSmsPriceQueryLoading || !gopayAutoSignupProviderConfigured"
                      class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-blue-600/15 hover:bg-blue-600/25 text-blue-200 border-blue-500/30 transition disabled:opacity-50">
                      {{ gopayHeroSmsPriceQueryLoading ? '查询中...' : '查询价格' }}
                    </button>
                  </div>
                  <div class="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">最低购买价</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupHeroSmsMinPrice"
                        type="text"
                        placeholder="例如 0.06"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">价格上限</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupHeroSmsMaxPrice"
                        type="text"
                        placeholder="例如 0.12"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">指定档位</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupHeroSmsPreferredPrice"
                        type="text"
                        placeholder="例如 0.09"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                  </div>
                  <div
                    v-if="gopayHeroSmsPriceQueryResult"
                    class="mt-3 rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2 text-xs text-gray-300 space-y-2">
                    <div class="flex gap-2">
                      <span class="shrink-0 text-gray-500">全部档位</span>
                      <div class="flex flex-wrap gap-1.5">
                        <span
                          v-for="tier in gopayHeroSmsAllTierBadges"
                          :key="`all-${tier.key}`"
                          class="rounded-full border border-gray-700 bg-gray-950 px-2 py-0.5 text-gray-300">
                          <span class="font-medium text-gray-100">{{ tier.price }}</span>
                          <span class="ml-1 text-gray-500">x{{ tier.count }}</span>
                        </span>
                        <span v-if="!gopayHeroSmsAllTierBadges.length" class="text-gray-500">无</span>
                      </div>
                    </div>
                    <div class="flex gap-2">
                      <span class="shrink-0 text-emerald-400">区间可用</span>
                      <div class="flex flex-wrap gap-1.5">
                        <span
                          v-for="tier in gopayHeroSmsFilteredTierBadges"
                          :key="`filtered-${tier.key}`"
                          :class="[
                            'rounded-full border px-2 py-0.5',
                            tier.preferred
                              ? 'border-amber-400/40 bg-amber-500/15 text-amber-100'
                              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                          ]">
                          <span class="font-semibold">{{ tier.price }}</span>
                          <span class="ml-1 opacity-70">x{{ tier.count }}</span>
                          <span v-if="tier.preferred" class="ml-1 text-amber-300">指定</span>
                        </span>
                        <span v-if="!gopayHeroSmsFilteredTierBadges.length" class="text-gray-500">无</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="gopayAutoSignupProvider === 'smsbower'" class="md:col-span-2 rounded-lg border border-emerald-500/20 bg-gray-950/50 px-3 py-3">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <div class="text-sm font-medium text-emerald-100">SMSBower 实时价格</div>
                      <div class="mt-1 text-xs text-gray-500">默认国家 ID 6（印尼），服务代码 ni（Gojek）。</div>
                    </div>
                    <button
                      type="button"
                      @click="queryGoPaySmsbowerPrices"
                      :disabled="gopaySmsbowerPriceQueryLoading || !gopayAutoSignupProviderConfigured"
                      class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-blue-600/15 hover:bg-blue-600/25 text-blue-200 border-blue-500/30 transition disabled:opacity-50">
                      {{ gopaySmsbowerPriceQueryLoading ? '查询中...' : '查询价格' }}
                    </button>
                  </div>
                  <div class="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">最低购买价</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupSmsbowerMinPrice"
                        type="text"
                        placeholder="留空不限下限"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">价格上限</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupSmsbowerMaxPrice"
                        type="text"
                        placeholder="留空不限价"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">指定档位</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupSmsbowerPreferredPrice"
                        type="text"
                        placeholder="留空按价格从低到高"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                  </div>
                  <div
                    v-if="gopaySmsbowerPriceQueryResult"
                    class="mt-3 rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2 text-xs text-gray-300 space-y-2">
                    <div
                      v-if="gopaySmsbowerPriceQueryResult.warning"
                      class="rounded-md border border-amber-500/20 bg-amber-500/10 px-2 py-1 text-amber-100">
                      {{ gopaySmsbowerPriceQueryResult.warning }}
                    </div>
                    <div class="flex gap-2">
                      <span class="shrink-0 text-gray-500">全部档位</span>
                      <div class="flex flex-wrap gap-1.5">
                        <span
                          v-for="tier in gopaySmsbowerAllTierBadges"
                          :key="`smsbower-all-${tier.key}`"
                          class="rounded-full border border-gray-700 bg-gray-950 px-2 py-0.5 text-gray-300">
                          <span class="font-medium text-gray-100">{{ tier.price }}</span>
                          <span class="ml-1 text-gray-500">x{{ tier.count }}</span>
                        </span>
                        <span v-if="!gopaySmsbowerAllTierBadges.length" class="text-gray-500">无</span>
                      </div>
                    </div>
                    <div class="flex gap-2">
                      <span class="shrink-0 text-emerald-400">区间可用</span>
                      <div class="flex flex-wrap gap-1.5">
                        <span
                          v-for="tier in gopaySmsbowerFilteredTierBadges"
                          :key="`smsbower-filtered-${tier.key}`"
                          :class="[
                            'rounded-full border px-2 py-0.5',
                            tier.preferred
                              ? 'border-amber-400/40 bg-amber-500/15 text-amber-100'
                              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-100'
                          ]">
                          <span class="font-semibold">{{ tier.price }}</span>
                          <span class="ml-1 opacity-70">x{{ tier.count }}</span>
                          <span v-if="tier.preferred" class="ml-1 text-amber-300">指定</span>
                        </span>
                        <span v-if="!gopaySmsbowerFilteredTierBadges.length" class="text-gray-500">无</span>
                      </div>
                    </div>
                  </div>
                </div>
                <div v-if="gopayAutoSignupProvider === 'smscode'" class="md:col-span-2 rounded-lg border border-emerald-500/20 bg-gray-950/50 px-3 py-3">
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <div class="text-sm font-medium text-emerald-100">SMSCode 实时产品</div>
                      <div class="mt-1 text-xs text-gray-500">默认国家 ID 7（SMSCode 印尼），平台关键词 gojek；也可在设置页固定平台 ID 或产品 ID。</div>
                    </div>
                    <button
                      type="button"
                      @click="queryGoPaySmscodePrices"
                      :disabled="gopaySmscodePriceQueryLoading || !gopayAutoSignupProviderConfigured"
                      class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-blue-600/15 hover:bg-blue-600/25 text-blue-200 border-blue-500/30 transition disabled:opacity-50">
                      {{ gopaySmscodePriceQueryLoading ? '查询中...' : '查询价格' }}
                    </button>
                  </div>
                  <div class="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">最低购买价</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupSmscodeMinPrice"
                        type="text"
                        placeholder="留空不限下限"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                    <div>
                      <label class="block text-xs text-emerald-200/80 mb-1">价格上限</label>
                      <input
                        v-model.trim="gopayForm.gopayAutoSignupSmscodeMaxPrice"
                        type="text"
                        placeholder="留空不限价"
                        :disabled="gopaySubmitting || gopayTaskRunning"
                        class="w-full px-3 py-2 bg-gray-900 border border-emerald-500/20 rounded-lg text-sm text-white focus:outline-none focus:border-emerald-500"
                      />
                    </div>
                  </div>
                  <div
                    v-if="gopaySmscodePriceQueryResult"
                    class="mt-3 rounded-lg border border-gray-800 bg-gray-900/80 px-3 py-2 text-xs text-gray-300 space-y-2">
                    <div class="flex gap-2">
                      <span class="shrink-0 text-gray-500">全部产品</span>
                      <div class="flex flex-wrap gap-1.5">
                        <span
                          v-for="product in gopaySmscodeAllProductBadges"
                          :key="`smscode-all-${product.key}`"
                          class="rounded-full border border-gray-700 bg-gray-950 px-2 py-0.5 text-gray-300">
                          <span class="font-medium text-gray-100">{{ product.price }}</span>
                          <span class="ml-1 text-gray-500">x{{ product.count }}</span>
                        </span>
                        <span v-if="!gopaySmscodeAllProductBadges.length" class="text-gray-500">无</span>
                      </div>
                    </div>
                    <div class="flex gap-2">
                      <span class="shrink-0 text-emerald-400">区间可用</span>
                      <div class="flex flex-wrap gap-1.5">
                        <span
                          v-for="product in gopaySmscodeFilteredProductBadges"
                          :key="`smscode-filtered-${product.key}`"
                          class="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-emerald-100">
                          <span class="font-semibold">{{ product.price }}</span>
                          <span class="ml-1 opacity-70">x{{ product.count }}</span>
                        </span>
                        <span v-if="!gopaySmscodeFilteredProductBadges.length" class="text-gray-500">无</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="gopayForm.checkoutUrl" class="mt-1 text-xs text-gray-500">
              已输入 checkout 链接，任务会固定使用当前账号。
            </div>
            <label class="mt-2 flex items-center gap-2 text-xs text-gray-300">
              <input
                v-model="gopayForm.deleteRejectedAccounts"
                type="checkbox"
                :disabled="gopaySubmitting || gopayTaskRunning"
                class="accent-blue-500"
              />
              付款未获批准 / 金额非 0 / GoPay 授权失败时删除账号
            </label>
            <label class="mt-2 flex items-center gap-2 text-xs text-gray-300">
              <input
                v-model="gopayForm.autoOauthAfterSuccess"
                type="checkbox"
                :disabled="gopaySubmitting || gopayTaskRunning"
                class="accent-blue-500"
              />
              绑定成功后自动 OAuth 补登录
            </label>
            <div class="mt-1 text-xs text-gray-500">
              未勾选时，绑定成功后默认用当前 auth_session 直接生成 CPA 认证 JSON。
            </div>
            <div class="mt-3 grid grid-cols-1 sm:grid-cols-[120px_120px_minmax(0,1fr)] items-center gap-3">
              <div>
                <label class="block text-xs text-gray-400 mb-1">待重试次数</label>
                <input
                  v-model.number="gopayForm.pendingRetryAttempts"
                  type="number"
                  min="0"
                  max="3"
                  step="1"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label class="block text-xs text-gray-400 mb-1">并发数</label>
                <input
                  v-model.number="gopayForm.gopayConcurrency"
                  type="number"
                  min="1"
                  max="10"
                  step="1"
                  :disabled="gopaySubmitting || gopayTaskRunning || gopayForm.autoRegister || Boolean(gopayForm.checkoutUrl)"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
              <div class="text-xs text-gray-500">
                待重试最多 3 轮，退避 60s / 120s；并发最多 10，仅用于批量账号绑定，自动注册 ChatGPT 账号保持顺序。
              </div>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Checkout 链接</label>
            <input
              v-model.trim="gopayForm.checkoutUrl"
              type="text"
              :disabled="gopaySubmitting || gopayTaskRunning || gopayForm.autoRegister"
              placeholder="可留空；也可粘贴 ChatGPT checkout、pay.openai.com/c/pay、pm-redirects 或 Midtrans snap 链接"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">自动生成链接类型</label>
            <select
              v-model="gopayForm.checkoutUiMode"
              :disabled="gopaySubmitting || gopayTaskRunning || Boolean(gopayForm.checkoutUrl)"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="custom">短链（chatgpt.com/checkout）</option>
              <option value="hosted">长链（pay.openai.com/c/pay）</option>
            </select>
            <div class="mt-1 text-xs text-gray-500">
              手动粘贴 checkout 链接时不使用此设置。
            </div>
          </div>

          <div v-if="!gopayAutoSignupEnabled" class="grid grid-cols-1 md:grid-cols-[120px_minmax(0,1fr)_minmax(0,1fr)] gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">国家区号</label>
              <input
                v-model.trim="gopayForm.countryCode"
                type="text"
                :disabled="gopaySubmitting || gopayTaskRunning"
                placeholder="62"
                @blur="normalizeGoPayPhoneFields({ forceLocal: true })"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div v-if="!gopayAutoSignupEnabled">
              <label class="block text-sm text-gray-400 mb-1">GoPay 手机号</label>
              <input
                v-model.trim="gopayForm.phoneNumber"
                type="text"
                :disabled="gopaySubmitting || gopayTaskRunning"
                placeholder="87761973970（不含国家区号）"
                @blur="normalizeGoPayPhoneFields({ forceLocal: true })"
                @paste="scheduleGoPayPhoneNormalize"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">GoPay PIN</label>
              <input
                v-model.trim="gopayForm.gopayPin"
                type="password"
                :disabled="gopaySubmitting || gopayTaskRunning"
                placeholder="用户提供的 GoPay PIN"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div v-if="!gopayAutoSignupEnabled">
            <label class="block text-sm text-gray-400 mb-1">OTP 接收方式</label>
            <div class="grid grid-cols-2 gap-2">
              <label
                class="flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer transition"
                :class="gopayOtpChannel === 'sms' ? 'border-blue-500/50 bg-blue-600/15 text-blue-100' : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
              >
                <input
                  v-model="gopayForm.otpChannel"
                  type="radio"
                  value="sms"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="accent-blue-500"
                />
                短信接口
              </label>
              <label
                class="flex items-center justify-center gap-2 rounded-lg border px-3 py-2 text-sm cursor-pointer transition"
                :class="gopayOtpChannel === 'whatsapp' ? 'border-emerald-500/50 bg-emerald-600/15 text-emerald-100' : 'border-gray-700 bg-gray-800 text-gray-300 hover:bg-gray-700'"
              >
                <input
                  v-model="gopayForm.otpChannel"
                  type="radio"
                  value="whatsapp"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="accent-emerald-500"
                />
                WhatsApp
              </label>
            </div>
            <div v-if="gopayUsingWhatsAppOtp" class="mt-2 rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-100">
              <div class="mb-2">
                <label class="mb-1 block text-[11px] text-emerald-200/80">ADB 模拟器端口</label>
                <select
                  v-model="gopayForm.whatsappAdbPort"
                  :disabled="whatsappOtpStarting || gopaySubmitting || gopayTaskRunning"
                  class="w-full rounded-md border border-emerald-500/20 bg-gray-900 px-2 py-1.5 text-xs text-emerald-50 focus:outline-none focus:border-emerald-400"
                >
                  <option
                    v-for="option in whatsappAdbPortOptions"
                    :key="option.value || 'auto'"
                    :value="option.value"
                  >
                    {{ option.label }}
                  </option>
                </select>
              </div>
              <div class="flex items-center justify-between gap-3">
                <span>
                  {{ whatsappOtpStatus?.running ? 'WhatsApp 监听中' : '提交任务前会自动启动 WhatsApp 监听。请确认本机接收端已准备好。' }}
                </span>
                <button
                  type="button"
                  @click="startWhatsAppOtpListener"
                  :disabled="whatsappOtpStarting || gopaySubmitting || gopayTaskRunning"
                  class="shrink-0 px-2 py-1 rounded-md border border-emerald-500/30 bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-50 disabled:opacity-50"
                >
                  {{ whatsappOtpStarting ? '启动中...' : (whatsappOtpStatus?.running ? '重新检测' : '启动') }}
                </button>
              </div>
              <div class="mt-1 text-emerald-200">
                {{ formatWhatsAppAdbStatus(whatsappOtpStatus) }}
              </div>
              <div v-if="whatsappOtpStatus?.last_error" class="mt-1 text-amber-200">监听异常：{{ whatsappOtpStatus.last_error }}</div>
              <div v-else-if="whatsappOtpStatus?.latest_otp" class="mt-1 text-emerald-200">最近识别到 OTP：{{ whatsappOtpStatus.latest_otp }}</div>
            </div>
          </div>

          <div v-if="!gopayAutoSignupEnabled && !gopayUsingWhatsAppOtp">
            <label class="block text-sm text-gray-400 mb-1">
              短信接口 Token / URL
            </label>
            <input
              v-model.trim="gopayForm.smsUrl"
              type="text"
              :disabled="gopaySubmitting || gopayTaskRunning"
              placeholder="https://it.tgflare.com/api/record?token=..."
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div v-if="!gopayAutoSignupEnabled" class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <div class="flex items-start justify-between gap-3">
              <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                <input
                  v-model="gopayForm.usePhonePool"
                  type="checkbox"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  @change="handleGoPayPhonePoolToggle"
                  class="accent-blue-500"
                />
                使用手机号池
              </label>
              <button
                v-if="gopayForm.usePhonePool"
                type="button"
                @click="openGoPayPhonePoolConfig"
                :disabled="gopaySubmitting || gopayTaskRunning"
                class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-blue-600/15 hover:bg-blue-600/25 text-blue-200 border-blue-500/30 transition disabled:opacity-50">
                配置
              </button>
            </div>
            <div class="mt-2 text-xs" :class="gopayForm.usePhonePool ? 'text-blue-300' : 'text-gray-500'">
              {{ gopayPhonePoolSummary }}
            </div>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-950/40 px-3 py-3">
            <div class="mb-3 text-sm font-medium text-gray-200">GoPay 注册代理</div>
            <template v-if="!gopayForm.proxyPoolEnabled && !gopayForm.proxyApiEnabled">
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label class="block text-sm text-gray-400 mb-1">代理标签</label>
                  <input
                    v-model.trim="gopayForm.proxyLabel"
                    type="text"
                    :disabled="gopaySubmitting || gopayTaskRunning"
                    placeholder="例如 res-id-01"
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
                <div>
                  <label class="block text-sm text-gray-400 mb-1">代理 URL</label>
                  <input
                    v-model.trim="gopayForm.proxyUrl"
                    type="text"
                    :disabled="gopaySubmitting || gopayTaskRunning"
                    placeholder="socks5://user:pass@host:port"
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>
            </template>

            <div v-if="!gopayForm.proxyApiEnabled" class="mt-3 flex items-center justify-between gap-3">
              <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                <input
                  v-model="gopayForm.proxyPoolEnabled"
                  type="checkbox"
                  :disabled="gopaySubmitting || gopayTaskRunning || gopayForm.proxyApiEnabled"
                  class="accent-blue-500"
                />
                启用动态代理池
              </label>
              <button
                v-if="gopayForm.proxyPoolEnabled"
                type="button"
                @click="openGoPayProxyPoolConfig"
                :disabled="gopaySubmitting || gopayTaskRunning"
                class="shrink-0 px-3 py-1.5 rounded-lg text-xs border bg-blue-600/15 hover:bg-blue-600/25 text-blue-200 border-blue-500/30 transition disabled:opacity-50">
                配置
              </button>
            </div>

            <div v-if="!gopayForm.proxyPoolEnabled" class="mt-3">
              <label class="inline-flex items-center gap-2 text-sm text-gray-300">
                <input
                  v-model="gopayForm.proxyApiEnabled"
                  type="checkbox"
                  :disabled="gopaySubmitting || gopayTaskRunning || gopayForm.proxyPoolEnabled"
                  class="accent-blue-500"
                />
                启用代理 API 轮换
              </label>
              <div v-if="gopayForm.proxyApiEnabled" class="mt-3">
                <label class="block text-sm text-gray-400 mb-1">供应商</label>
                <select
                  v-model="gopayForm.proxyApiProvider"
                  :disabled="gopaySubmitting || gopayTaskRunning"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="cliproxy">Cliproxy</option>
                  <option value="1024proxy">1024proxy</option>
                </select>
                <div class="mt-2 rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs text-blue-100">
                  {{ gopayProxyApiHelp }}
                </div>
              </div>
            </div>

            <div class="mt-3 text-xs text-gray-500">{{ gopayProxySummary }}</div>
            <div v-if="gopayForm.proxyPoolEnabled && !gopayForm.proxyApiEnabled" class="mt-3 max-h-32 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950/70">
              <div v-if="!gopayProxyPoolEntries.length" class="px-3 py-3 text-xs text-gray-500">尚未导入代理。</div>
              <div
                v-for="(proxy, index) in gopayProxyPoolEntries"
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

        <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 min-w-0 flex flex-col h-[520px] xl:h-full min-h-0">
          <div class="flex items-center justify-between gap-3 mb-3">
            <div class="text-sm text-gray-400">实时 GoPay 日志</div>
            <div v-if="gopayTask" class="text-xs text-gray-500 font-mono">
              {{ gopayTask.task_id }}
            </div>
          </div>
          <div ref="gopayLogScrollRef" class="rounded-lg border border-gray-800 bg-gray-900 p-3 flex-1 min-h-0 overflow-y-auto space-y-2 pr-1">
            <div v-if="!gopayLogEntries.length" class="text-sm text-gray-500">
              尚未提交 GoPay 任务。
            </div>
            <div
              v-for="entry in gopayLogEntries"
              :key="entry.id"
              class="rounded-lg border border-gray-800 bg-gray-950/80 px-3 py-2"
            >
              <div class="grid grid-cols-[52px_minmax(0,1fr)_auto] items-center gap-2">
                <span class="text-xs font-mono text-gray-500">{{ entry.time || '-' }}</span>
                <span class="min-w-0 truncate text-sm text-gray-200" :title="entry.message">{{ entry.message }}</span>
                <span class="shrink-0 text-[11px] uppercase tracking-wide" :class="entry.levelClass">{{ entry.label }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="activeTab === 'generate'" class="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <h3 class="text-lg font-semibold text-white mb-4">历史记录</h3>
      <div class="space-y-2">
        <div v-if="!history.length" class="text-sm text-gray-500">暂无历史记录</div>
        <div
          v-for="(item, idx) in history"
          :key="idx"
          class="border border-gray-800 rounded-lg px-3 py-3 bg-gray-900/70"
        >
          <div class="flex items-center justify-between gap-3">
            <span class="text-xs font-mono text-gray-500">{{ item.time }}</span>
            <span class="text-xs uppercase tracking-wide" :class="item.success ? 'text-emerald-400' : 'text-red-400'">
              {{ item.success ? '成功' : '失败' }}
            </span>
          </div>
          <div class="mt-2 text-sm text-gray-200">{{ item.plan }} / {{ item.country || '-' }} {{ item.currency ? `(${item.currency})` : '' }}</div>
          <div v-if="item.link" class="mt-2 text-xs text-blue-400 truncate cursor-pointer hover:text-blue-300" @click="openHistoryLink(item.link)">
            {{ item.link }}
          </div>
          <div v-if="item.error" class="mt-2 text-xs text-red-400">
            {{ item.error }}
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="activeTab === 'gopay' && gopayAutoRegisterConfigOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="closeGoPayAutoRegisterConfig"
    >
      <div class="w-full max-w-2xl max-h-[82vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">自动注册配置</h4>
            <div class="text-xs text-gray-500 mt-1">选择 GoPay 自动注册使用的邮箱来源、邮箱前缀和密码。</div>
          </div>
          <button
            type="button"
            @click="closeGoPayAutoRegisterConfig"
            class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            关闭
          </button>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">邮件 Provider</label>
            <select
              v-model="gopayForm.autoRegisterMailProvider"
              :disabled="gopayMailProviderLoading"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="option in gopayMailProviderOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <div class="mt-1 text-xs text-gray-500">
              API Key / token 池仍在“设置 → 邮件 Provider”里维护，这里只决定本次自动注册使用哪个 Provider。
            </div>
          </div>

          <div v-if="gopayAutoRegisterUsesLuckMail" class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">LuckMail 邮箱类型</label>
              <select
                v-model="gopayForm.autoRegisterLuckmailEmailType"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-for="option in luckmailEmailTypeOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">LuckMail 购买域名</label>
              <select
                v-model="gopayForm.autoRegisterLuckmailPreferredDomain"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-for="option in luckmailDomainOptions" :key="option.value || 'auto'" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="col-span-2 rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs text-gray-300">
              LuckMail 模式会从已购邮箱池选择；池子为空时按这里的类型和域名自动购买微软邮箱。选择自动分配时由 LuckMail 按库存自动分配。
            </div>
          </div>

          <div v-if="gopayAutoRegisterUsesOutlook" class="rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-sm text-gray-300">
            Outlook 模式会从已配置的微软邮箱账号池中选择，注册域名选择不参与本次任务。
          </div>

          <div v-if="gopayAutoRegisterUsesDomains">
            <div class="flex items-center justify-between gap-3 mb-2">
              <label class="block text-sm text-gray-400">注册域名</label>
              <div class="flex items-center gap-2">
                <button
                  type="button"
                  @click="selectAllGoPayAutoRegisterDomains"
                  :disabled="gopayRegisterDomainLoading || !gopayRegisterDomainOptions.length || gopayAllAutoRegisterDomainsSelected"
                  class="px-2 py-1 rounded-md text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                  全选
                </button>
                <button
                  type="button"
                  @click="clearGoPayAutoRegisterDomains"
                  :disabled="!gopaySelectedAutoRegisterDomains.length"
                  class="px-2 py-1 rounded-md text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                  清空
                </button>
              </div>
            </div>
            <div class="rounded-lg border border-gray-800 bg-gray-950/50">
              <div class="px-3 py-2 border-b border-gray-800 text-xs text-gray-500">
                {{ gopayRegisterDomainLoading ? '正在加载域名...' : `已选择 ${gopaySelectedAutoRegisterDomains.length} / ${gopayRegisterDomainOptions.length}` }}
              </div>
              <div class="max-h-56 overflow-y-auto px-2 py-2 space-y-1">
                <label
                  v-for="domain in gopayRegisterDomainOptions"
                  :key="`gopay-auto-domain-${domain}`"
                  class="flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-gray-200 hover:bg-gray-800 cursor-pointer"
                >
                  <input
                    v-model="gopayForm.autoRegisterDomains"
                    type="checkbox"
                    :value="domain"
                    class="accent-blue-500"
                  />
                  <span class="font-mono text-xs">@{{ domain }}</span>
                </label>
                <div v-if="!gopayRegisterDomainOptions.length" class="px-2 py-8 text-center text-sm text-gray-500">
                  暂无可用注册域名，请先在设置页维护注册域名。
                </div>
              </div>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">邮箱前缀</label>
            <div class="flex items-center rounded-lg border border-gray-700 bg-gray-800">
              <input
                v-model.trim="gopayForm.autoRegisterPrefix"
                type="text"
                placeholder="例如 gopay"
                class="flex-1 px-3 py-2 bg-transparent text-sm text-white focus:outline-none"
              />
              <div class="px-3 text-xs text-gray-500 border-l border-gray-700">
                +5位随机字母数字 {{ gopayAutoRegisterSuffixLabel }}
              </div>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">密码</label>
            <input
              v-model.trim="gopayForm.autoRegisterPassword"
              type="text"
              placeholder="留空自动生成"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>注册数量：<span class="text-gray-200">{{ normalizedGoPayAutoRegisterCount }}</span></div>
            <div>邮件 Provider：<span class="text-gray-200">{{ gopayAutoRegisterProviderLabel }}</span></div>
            <div v-if="gopayAutoRegisterUsesLuckMail">LuckMail 购买：<span class="text-gray-200">{{ gopayLuckmailPurchaseLabel }}</span></div>
            <div v-else-if="gopayAutoRegisterUsesDomains">域名轮换：<span class="text-gray-200">{{ gopaySelectedAutoRegisterDomainsLabel }}</span></div>
            <div>预览邮箱：<span class="font-mono text-gray-200">{{ gopayAutoRegisterPreviewEmail }}</span></div>
            <div>密码：<span class="text-gray-200">{{ gopayForm.autoRegisterPassword || '自动随机生成' }}</span></div>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button
            type="button"
            @click="closeGoPayAutoRegisterConfig"
            class="px-4 py-2 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            取消
          </button>
          <button
            type="button"
            @click="confirmGoPayAutoRegisterConfig"
            :disabled="gopayAutoRegisterUsesDomains && !gopaySelectedAutoRegisterDomains.length"
            class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50">
            确认
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="activeTab === 'gopay' && gopayPhonePoolConfigOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="closeGoPayPhonePoolConfig"
    >
      <div class="w-full max-w-2xl max-h-[82vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">手机号池配置</h4>
            <div class="text-xs text-gray-500 mt-1">每行一个 GoPay 手机号，任务会按顺序轮换使用。</div>
          </div>
          <button
            type="button"
            @click="closeGoPayPhonePoolConfig"
            class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            关闭
          </button>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">手机号池</label>
            <textarea
              v-model="gopayForm.phonePoolText"
              rows="9"
              :placeholder="gopayPhonePoolPlaceholder"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
            ></textarea>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>有效手机号：<span class="text-gray-200">{{ gopayPhoneAccounts.length }}</span></div>
            <div>OTP 来源：<span class="text-gray-200">{{ gopayUsingWhatsAppOtp ? 'WhatsApp' : '短信接口' }}</span></div>
            <div>轮换方式：<span class="text-gray-200">自动注册按注册序号轮换；批量绑卡按账号候选轮换。</span></div>
            <div>不勾选“使用手机号池”时，会继续使用上方单手机号配置。</div>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button
            type="button"
            @click="closeGoPayPhonePoolConfig"
            class="px-4 py-2 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            取消
          </button>
          <button
            type="button"
            @click="confirmGoPayPhonePoolConfig"
            class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition">
            确认
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="activeTab === 'gopay' && gopayProxyPoolConfigOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="closeGoPayProxyPoolConfig"
    >
      <div class="w-full max-w-2xl max-h-[82vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">动态代理池配置</h4>
            <div class="text-xs text-gray-500 mt-1">每行一个代理，保存时会自动去重；GoPay 钱包注册前随机选择。</div>
          </div>
          <button
            type="button"
            @click="closeGoPayProxyPoolConfig"
            class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            关闭
          </button>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-4">
          <div>
            <label class="block text-sm text-gray-400 mb-1">代理池</label>
            <textarea
              v-model="gopayForm.proxyPoolText"
              rows="9"
              placeholder="每行一条代理，例如：&#10;socks5://user:pass@host:port&#10;host:port:user:pass"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 font-mono"
            ></textarea>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>有效代理：<span class="text-gray-200">{{ gopayProxyPoolEntries.length }}</span></div>
            <div>轮换方式：<span class="text-gray-200">每次注册 GoPay 钱包前随机选择一条。</span></div>
            <div>支持格式与 PayPal 页面一致：协议 URL、host:port:user:pass、user:pass@host:port 等。</div>
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button
            type="button"
            @click="closeGoPayProxyPoolConfig"
            class="px-4 py-2 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            取消
          </button>
          <button
            type="button"
            @click="confirmGoPayProxyPoolConfig"
            class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition">
            确认
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="gopayAccountPickerOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="closeGoPayAccountPicker"
    >
      <div class="w-full max-w-3xl max-h-[82vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">{{ gopayAccountPickerTitle }}</h4>
            <div class="text-xs text-gray-500 mt-1">{{ gopayAccountPickerHelp }}</div>
          </div>
          <button
            type="button"
            @click="closeGoPayAccountPicker"
            class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
            关闭
          </button>
        </div>

        <div class="px-5 py-4 border-b border-gray-800 space-y-3">
          <input
            v-model.trim="gopayAccountSearchKeyword"
            type="text"
            :disabled="loadingAccounts"
            placeholder="搜索邮箱，例如 openaibus.com"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div class="text-xs text-gray-400">
              {{ loadingAccounts ? '加载账号中...' : filteredGoPayAccountOptions.length ? `当前筛选 ${filteredGoPayAccountOptions.length} 个账号` : '没有匹配账号' }}
            </div>
            <div class="flex flex-wrap items-center gap-2">
              <button
                type="button"
                @click="selectAllGoPayAccounts"
                :disabled="loadingAccounts || !accountOptions.length || gopayAllPickerAccountsSelected"
                class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                全选
              </button>
              <button
                type="button"
                @click="clearGoPayPickerAccounts"
                :disabled="!activeGoPayAccountPickerEmails.length"
                class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                清空
              </button>
            </div>
          </div>
        </div>

        <div class="flex-1 min-h-0 overflow-y-auto px-5 py-4 space-y-1">
          <label
            v-for="account in filteredGoPayAccountOptions"
            :key="`picker-${account.email}`"
            class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-200 hover:bg-gray-800 cursor-pointer"
          >
            <input
              v-model="activeGoPayAccountPickerEmails"
              type="checkbox"
              :value="account.email"
              class="accent-blue-500"
            />
            <span class="font-mono text-xs break-all">{{ account.email }}</span>
          </label>
          <div v-if="!filteredGoPayAccountOptions.length" class="px-3 py-10 text-sm text-gray-500">
            暂无匹配账号。
          </div>
        </div>

        <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
          <button
            type="button"
            @click="closeGoPayAccountPicker"
            class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition">
            完成
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { computeGoPayBoardView } from '../gopayBoard.js'
import {
  bindCountryOptions,
  bindPlanLabel,
  bindPlanOptions,
  buildBindLinkPayload as buildCheckoutPayload,
  countryCurrencyMap,
  resolveCheckoutLink,
} from '../bindLinkPayload.js'

const props = defineProps({
  initialTab: {
    type: String,
    default: 'bind',
  },
  standalone: {
    type: Boolean,
    default: false,
  },
})
const emit = defineEmits(['refresh'])

const BIND_HISTORY_KEY = 'autotoken_bind_history_v1'
const CHATGPT_BIND_FORM_STATE_KEY = 'autotoken_chatgpt_bind_form_state_v1'
const GOPAY_FORM_STATE_KEY = 'autotoken_gopay_form_state_v1'
const GOPAY_RECENT_TASK_KEY = 'autotoken_gopay_recent_task_id_v1'
const luckmailEmailTypeOptions = [
  { value: 'ms_imap', label: '微软 IMAP 邮箱' },
  { value: 'ms_graph', label: '微软 Graph 邮箱' },
  { value: 'microsoft', label: '微软邮箱' },
  { value: 'self_built', label: '自建邮箱' },
]
const luckmailDomainOptions = [
  { value: '', label: '自动分配' },
  { value: 'outlook.com', label: 'outlook.com' },
  { value: 'outlook.cl', label: 'outlook.cl' },
  { value: 'outlook.de', label: 'outlook.de' },
  { value: 'outlook.fr', label: 'outlook.fr' },
  { value: 'outlook.jp', label: 'outlook.jp' },
  { value: 'outlook.my', label: 'outlook.my' },
  { value: 'outlook.ph', label: 'outlook.ph' },
  { value: 'hotmail.com', label: 'hotmail.com' },
  { value: 'hotmail.de', label: 'hotmail.de' },
  { value: 'live.com', label: 'live.com' },
]
const luckmailSelectableDomainOptions = luckmailDomainOptions.filter(option => option.value)

const initialTab = ['bind', 'kiro', 'generate', 'gopay'].includes(props.initialTab) ? props.initialTab : 'bind'
const activeTab = ref(props.standalone ? 'gopay' : initialTab)
const message = ref('')
const messageClass = ref('')
const generating = ref(false)
const currentLink = ref('')
const checkoutSessionId = ref('')
const rawGeneratedUrl = ref('')
const history = ref([])
const accountOptions = ref([])
const accountSearchKeyword = ref('')
const loadingAccounts = ref(false)
const loadingAccountToken = ref(false)
const selectedAccountEmail = ref('')
const cardOptions = ref([])
const loadingCards = ref(false)
const bindSubmitting = ref(false)
const bindCancelling = ref(false)
const bindTask = ref(null)
const bindLogEntries = ref([])
const gopayAutoSignupConfig = ref(null)
const gopayAutoSignupConfigLoading = ref(false)
const gopayRekberinajaConfig = ref(null)
const gopayHeroSmsPriceQueryLoading = ref(false)
const gopayHeroSmsPriceQueryResult = ref(null)
const gopaySmsbowerPriceQueryLoading = ref(false)
const gopaySmsbowerPriceQueryResult = ref(null)
const gopaySmscodePriceQueryLoading = ref(false)
const gopaySmscodePriceQueryResult = ref(null)
const gopayRuntimeUpdating = ref(false)
const gopayRuntimeAppendEmails = ref([])
const gopayRuntimeConcurrency = ref(1)
const gopayRuntimeSmsProvider = ref('smscloud')
const gopayRuntimeBalancePollIntervalSeconds = ref(20)
const gopayRuntimeTransferBalanceWaitSeconds = ref(120)
const gopayForm = ref({
  email: '',
  autoRegister: false,
  autoRegisterCount: 1,
  autoRegisterProtocol: false,
  gopayAutoSignup: true,
  gopayAutoSignupSmsProvider: 'smscloud',
  gopayAutoSignupMode: 'http',
  gopayAutoSignupHeroSmsApiKey: '',
  gopayAutoSignupHeroSmsBaseUrl: 'https://hero-sms.com/stubs/handler_api.php',
  gopayAutoSignupHeroSmsCountry: '6',
  gopayAutoSignupHeroSmsService: 'ni',
  gopayAutoSignupHeroSmsTimeout: 120,
  gopayAutoSignupHeroSmsMinPrice: '',
  gopayAutoSignupHeroSmsMaxPrice: '',
  gopayAutoSignupHeroSmsPreferredPrice: '',
  gopayAutoSignupSmsbowerApiKey: '',
  gopayAutoSignupSmsbowerBaseUrl: 'https://smsbower.page/stubs/handler_api.php',
  gopayAutoSignupSmsbowerCountry: '6',
  gopayAutoSignupSmsbowerService: 'ni',
  gopayAutoSignupSmsbowerTimeout: 120,
  gopayAutoSignupSmsbowerMinPrice: '',
  gopayAutoSignupSmsbowerMaxPrice: '',
  gopayAutoSignupSmsbowerPreferredPrice: '',
  gopayAutoSignupSmscloudBaseUrl: 'https://smscloud.sbs/api',
  gopayAutoSignupSmscloudCountry: '6',
  gopayAutoSignupSmscloudService: 'ni',
  gopayAutoSignupSmscloudMaxPrice: '',
  gopayAutoSignupSmscloudTimeout: 120,
  gopayAutoSignupSmscodeApiToken: '',
  gopayAutoSignupSmscodeBaseUrl: 'https://api.smscode.gg/v1',
  gopayAutoSignupSmscodeCountryId: '7',
  gopayAutoSignupSmscodePlatformId: '',
  gopayAutoSignupSmscodePlatformQuery: 'gojek',
  gopayAutoSignupSmscodeProductId: '',
  gopayAutoSignupSmscodeMinPrice: '',
  gopayAutoSignupSmscodeMaxPrice: '',
  gopayAutoSignupSmscodeTimeout: 120,
  gopayBalanceWaitFallbackTransfer: false,
  autoRegisterMailProvider: '',
  autoRegisterLuckmailEmailType: '',
  autoRegisterLuckmailPreferredDomain: '',
  autoRegisterLuckmailPreferredDomains: [],
  autoRegisterDomains: [],
  autoRegisterPrefix: '',
  autoRegisterPassword: '',
  batchMode: false,
  accountEmails: [],
  checkoutUrl: '',
  checkoutUiMode: 'hosted',
  countryCode: '62',
  phoneNumber: '81997420107',
  usePhonePool: false,
  phonePoolText: '',
  otpChannel: 'sms',
  whatsappAdbPort: '',
  smsUrl: '',
  gopayPin: '',
  billingName: '',
  billingCountry: 'US',
  billingState: '',
  billingCity: '',
  billingZip: '',
  billingAddress1: '',
  billingAddress2: '',
  proxyLabel: '',
  proxyUrl: '',
  proxyPoolEnabled: false,
  proxyPoolText: '',
  proxyApiEnabled: false,
  proxyApiProvider: 'cliproxy',
  deleteRejectedAccounts: false,
  autoOauthAfterSuccess: false,
  pendingRetryAttempts: 1,
  gopayConcurrency: 1,
})
const gopayAccountSearchKeyword = ref('')
const gopayAccountPickerOpen = ref(false)
const gopayAccountPickerMode = ref('batch')
const gopayAutoRegisterConfigOpen = ref(false)
const gopayPhonePoolConfigOpen = ref(false)
const gopayProxyPoolConfigOpen = ref(false)
const gopayMailProviderLoading = ref(false)
const gopayMailProviderOptions = ref([])
const gopayRegisterDomainOptions = ref([])
const gopayRegisterDomainLoading = ref(false)
const gopaySubmitting = ref(false)
const gopayCancelling = ref(false)
const gopaySkipping = ref(false)
const gopayTask = ref(null)
const gopayLogEntries = ref([])
const gopayLogScrollRef = ref(null)
const gopayLoggedProgressEventIds = ref(new Set())
const gopayLoggedMessages = ref(new Set())
const gopaySuccessNoticeVisible = ref(false)
const gopaySuccessNoticeEmail = ref('')
const whatsappOtpStatus = ref(null)
const whatsappOtpStarting = ref(false)
const whatsappAdbPortOptions = [
  { value: '', label: '自动检测' },
  { value: '5554', label: 'emulator-5554' },
  { value: '5556', label: 'emulator-5556' },
  { value: '5558', label: 'emulator-5558' },
  { value: '5560', label: 'emulator-5560' },
  { value: '5562', label: 'emulator-5562' },
  { value: '5564', label: 'emulator-5564' },
]
let bindTaskPollTimer = 0
let gopayTaskPollTimer = 0
let gopaySuccessNoticeTimer = 0

const bindForm = ref({
  accessToken: '',
  planType: 'plus',
  country: 'PH',
  currency: 'PHP',
  teamWorkspaceName: 'MyWorkspace',
  teamSeatQuantity: 5,
  teamPriceInterval: 'month',
})

const bindTaskForm = ref({
  checkoutMode: 'auto',
  cardItemId: '',
  checkoutUrl: '',
  proxyApiEnabled: false,
  proxyApiProvider: 'cliproxy',
  proxyApiCountry: 'US',
  proxyApiUrl: '',
  manualConfirm: false,
})

const selectedPlanName = computed(() => bindPlanLabel(bindForm.value.planType))

const filteredAccountOptions = computed(() => {
  const keyword = accountSearchKeyword.value.trim().toLowerCase()
  if (!keyword) return accountOptions.value
  return accountOptions.value.filter(account => String(account?.email || '').toLowerCase().includes(keyword))
})

const filteredGoPayAccountOptions = computed(() => {
  const keyword = gopayAccountSearchKeyword.value.trim().toLowerCase()
  if (!keyword) return accountOptions.value
  return accountOptions.value.filter(account => String(account?.email || '').toLowerCase().includes(keyword))
})

const gopaySelectedBatchEmails = computed(() => {
  const seen = new Set()
  return (gopayForm.value.accountEmails || [])
    .map(email => String(email || '').trim().toLowerCase())
    .filter(email => {
      if (!email || seen.has(email)) return false
      seen.add(email)
      return true
    })
})

const gopayRuntimeAppendPreviewEmails = computed(() => gopayRuntimeAppendEmails.value.slice(0, 4))

const activeGoPayAccountPickerEmails = computed({
  get() {
    return gopayAccountPickerMode.value === 'runtime'
      ? gopayRuntimeAppendEmails.value
      : gopaySelectedBatchEmails.value
  },
  set(emails) {
    setGoPayPickerEmails(emails)
  },
})

const gopayAccountPickerTitle = computed(() => (
  gopayAccountPickerMode.value === 'runtime' ? '选择追加账号' : '批量选择账号'
))

const gopayAccountPickerHelp = computed(() => {
  const selectedCount = activeGoPayAccountPickerEmails.value.length
  const totalCount = accountOptions.value.length
  if (gopayAccountPickerMode.value === 'runtime') {
    return `已选择 ${selectedCount} / ${totalCount} 个待追加账号，应用热切换后加入当前任务队列`
  }
  return `已选择 ${selectedCount} / ${totalCount} 个账号`
})

const normalizedGoPayAutoRegisterCount = computed(() => {
  return normalizeGoPayAutoRegisterCount(gopayForm.value.autoRegisterCount)
})

const normalizedGoPayPendingRetryAttempts = computed(() => {
  return normalizeGoPayPendingRetryAttempts(gopayForm.value.pendingRetryAttempts)
})

const normalizedGoPayConcurrency = computed(() => {
  return normalizeGoPayConcurrency(gopayForm.value.gopayConcurrency)
})

const gopayAutoRegisterUsesLuckMail = computed(() => gopayForm.value.autoRegisterMailProvider === 'luckmail')
const gopayAutoRegisterUsesOutlook = computed(() => gopayForm.value.autoRegisterMailProvider === 'outlook')
const gopayAutoRegisterUsesDomains = computed(() => !gopayAutoRegisterUsesLuckMail.value && !gopayAutoRegisterUsesOutlook.value)

const gopayAutoRegisterProviderLabel = computed(() => {
  const value = gopayForm.value.autoRegisterMailProvider || ''
  return gopayMailProviderOptions.value.find(option => option.value === value)?.label || value || '默认配置'
})

const gopayLuckmailPurchaseLabel = computed(() => {
  const emailType = luckmailEmailTypeOptions.find(option => option.value === gopayForm.value.autoRegisterLuckmailEmailType)?.label
    || gopayForm.value.autoRegisterLuckmailEmailType
    || '微软 IMAP 邮箱'
  const domain = gopayForm.value.autoRegisterLuckmailPreferredDomain || '自动分配'
  const domains = Array.isArray(gopayForm.value.autoRegisterLuckmailPreferredDomains)
    ? gopayForm.value.autoRegisterLuckmailPreferredDomains.filter(Boolean)
    : []
  const domainLabel = domains.length ? domains.map(value => `@${value}`).join(' / ') : domain
  return `${emailType} / ${domainLabel}`
})

const gopaySelectedAutoRegisterDomains = computed(() => {
  const seen = new Set()
  return (Array.isArray(gopayForm.value.autoRegisterDomains) ? gopayForm.value.autoRegisterDomains : [])
    .map(domain => String(domain || '').trim().replace(/^@/, ''))
    .filter(domain => {
      if (!domain || seen.has(domain.toLowerCase())) return false
      if (gopayRegisterDomainOptions.value.length && !gopayRegisterDomainOptions.value.includes(domain)) return false
      seen.add(domain.toLowerCase())
      return true
    })
})

const gopaySelectedAutoRegisterDomainsLabel = computed(() => {
  const domains = gopaySelectedAutoRegisterDomains.value
  if (!domains.length) return '未选择'
  if (domains.length <= 3) return domains.map(domain => `@${domain}`).join(' / ')
  return `${domains.slice(0, 3).map(domain => `@${domain}`).join(' / ')} 等 ${domains.length} 个`
})

const gopayAutoRegisterConfigSummary = computed(() => {
  const prefix = String(gopayForm.value.autoRegisterPrefix || '').trim()
  const password = String(gopayForm.value.autoRegisterPassword || '').trim()
  const mode = gopayForm.value.autoRegisterProtocol ? '协议注册' : '浏览器注册'
  if (gopayAutoRegisterUsesLuckMail.value) {
    return `${mode}，${gopayAutoRegisterProviderLabel.value}，${gopayLuckmailPurchaseLabel.value}，密码 ${password ? '自定义' : '随机'}`
  }
  if (gopayAutoRegisterUsesOutlook.value) {
    return `${mode}，${gopayAutoRegisterProviderLabel.value}，Outlook账号池，密码 ${password ? '自定义' : '随机'}`
  }
  return `${mode}，${gopaySelectedAutoRegisterDomainsLabel.value}，前缀 ${prefix || '随机'}，密码 ${password ? '自定义' : '随机'}`
})

const gopayAutoRegisterPreviewEmail = computed(() => {
  if (gopayAutoRegisterUsesLuckMail.value) return 'LuckMail邮箱池中选择'
  if (gopayAutoRegisterUsesOutlook.value) return 'Outlook邮箱池中选择'
  const prefix = String(gopayForm.value.autoRegisterPrefix || '').trim()
  const domain = gopaySelectedAutoRegisterDomains.value[0] || gopayRegisterDomainOptions.value[0] || 'domain.com'
  return `${prefix ? `${prefix}a8k3p` : '__random__'}@${domain}`
})

const gopayAutoRegisterSuffixLabel = computed(() => {
  if (gopayAutoRegisterUsesOutlook.value) return '@Outlook账号池'
  if (gopayAutoRegisterUsesLuckMail.value) return '@LuckMail'
  return '@随机域名'
})

const gopayAllAutoRegisterDomainsSelected = computed(() => {
  if (!gopayRegisterDomainOptions.value.length) return false
  const selected = new Set(gopaySelectedAutoRegisterDomains.value.map(domain => domain.toLowerCase()))
  return gopayRegisterDomainOptions.value.every(domain => selected.has(String(domain || '').toLowerCase()))
})

const gopayAllPickerAccountsSelected = computed(() => {
  if (!accountOptions.value.length) return false
  const selected = new Set(activeGoPayAccountPickerEmails.value)
  return accountOptions.value.every(account => selected.has(String(account.email || '').toLowerCase()))
})

const gopayBatchPreviewEmails = computed(() => gopaySelectedBatchEmails.value.slice(0, 4))

const gopayAccountSelectionLabel = computed(() => {
  if (gopayBatchActive.value) return `${gopaySelectedBatchEmails.value.length} 个账号`
  return String(gopayForm.value.email || '').trim().toLowerCase() || '未选择'
})

const gopayBatchActive = computed(() => {
  return Boolean(!gopayForm.value.autoRegister && gopayForm.value.batchMode && !gopayForm.value.checkoutUrl && gopaySelectedBatchEmails.value.length > 0)
})

const gopayAutoSignupEnabled = computed(() => Boolean(gopayForm.value.gopayAutoSignup))

const gopayAutoSignupProvider = computed(() => {
  const provider = String(gopayForm.value.gopayAutoSignupSmsProvider || '').trim()
  return provider === 'hero_sms' || provider === 'smsbower' || provider === 'smscode' ? provider : 'smscloud'
})

const gopayAutoSignupProviderConfigured = computed(() => {
  const cfg = gopayAutoSignupConfig.value || {}
  if (gopayAutoSignupProvider.value === 'hero_sms') return Boolean(cfg.hero_sms_api_key_present)
  if (gopayAutoSignupProvider.value === 'smsbower') return Boolean(cfg.smsbower_api_key_present)
  if (gopayAutoSignupProvider.value === 'smscode') return Boolean(cfg.smscode_api_token_present)
  return Boolean(cfg.smscloud_xi_token_present)
})

const gopayAutoSignupConfiguredMessage = computed(() => {
  if (gopayAutoSignupProvider.value === 'hero_sms') return 'Hero-SMS 密钥已配置'
  if (gopayAutoSignupProvider.value === 'smsbower') return 'SMSBower 密钥已配置'
  if (gopayAutoSignupProvider.value === 'smscode') return 'SMSCode 密钥已配置'
  return 'SMSCloud 凭证已配置'
})

const gopayAutoSignupMissingMessage = computed(() => {
  if (gopayAutoSignupProvider.value === 'hero_sms') {
    return '请到设置页配置 hero-sms API Key，或在 .env 中配置 GOPAY_AUTO_SIGNUP_HERO_SMS_API_KEY。'
  }
  if (gopayAutoSignupProvider.value === 'smsbower') {
    return '请到设置页配置 smsbower API Key，或在 .env 中配置 GOPAY_AUTO_SIGNUP_SMSBOWER_API_KEY / OAUTH_SMSBOWER_API_KEY。'
  }
  if (gopayAutoSignupProvider.value === 'smscode') {
    return '请到设置页配置 SMSCode API Token，或在 .env 中配置 GOPAY_AUTO_SIGNUP_SMSCODE_API_TOKEN。'
  }
  return '请到设置页配置 smscloud XI_TOKEN，或在 .env 中配置 GOPAY_AUTO_SIGNUP_SMSCLOUD_XI_TOKEN。'
})

const rekberinajaTransferEnabled = computed(() => Boolean(
  gopayRekberinajaConfig.value?.transfer_enabled
    ?? gopayRekberinajaConfig.value?.enabled
))

function normalizeGoPayHeroSmsTierBadges(tiers, fallbackPrices, preferredPrice) {
  const preferred = Number(String(preferredPrice || '').trim())
  if (Array.isArray(tiers) && tiers.length) {
    return tiers
      .map((tier, index) => {
        const price = Number(tier?.price ?? tier?.cost)
        if (!Number.isFinite(price) || price <= 0) return null
        const count = Number(tier?.count)
        const normalizedPrice = Math.round(price * 10000) / 10000
        return {
          key: `${normalizedPrice}-${index}`,
          price: String(normalizedPrice).replace(/\.?0+$/, ''),
          count: Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0,
          preferred: Number.isFinite(preferred) && Math.abs(normalizedPrice - preferred) < 0.00001,
        }
      })
      .filter(Boolean)
  }
  return (Array.isArray(fallbackPrices) ? fallbackPrices : [])
    .map((price, index) => {
      const normalizedPrice = Number(price)
      if (!Number.isFinite(normalizedPrice) || normalizedPrice <= 0) return null
      return {
        key: `${normalizedPrice}-${index}`,
        price: String(Math.round(normalizedPrice * 10000) / 10000).replace(/\.?0+$/, ''),
        count: 0,
        preferred: Number.isFinite(preferred) && Math.abs(normalizedPrice - preferred) < 0.00001,
      }
    })
    .filter(Boolean)
}

const gopayHeroSmsAllTierBadges = computed(() => {
  const result = gopayHeroSmsPriceQueryResult.value || {}
  return normalizeGoPayHeroSmsTierBadges(
    result.tiers,
    result.prices,
    gopayForm.value.gopayAutoSignupHeroSmsPreferredPrice,
  )
})

const gopayHeroSmsFilteredTierBadges = computed(() => {
  const result = gopayHeroSmsPriceQueryResult.value || {}
  return normalizeGoPayHeroSmsTierBadges(
    result.filtered_tiers,
    result.filtered_prices,
    gopayForm.value.gopayAutoSignupHeroSmsPreferredPrice,
  )
})

const gopaySmsbowerAllTierBadges = computed(() => {
  const result = gopaySmsbowerPriceQueryResult.value || {}
  return normalizeGoPayHeroSmsTierBadges(
    result.tiers,
    result.prices,
    gopayForm.value.gopayAutoSignupSmsbowerPreferredPrice,
  )
})

const gopaySmsbowerFilteredTierBadges = computed(() => {
  const result = gopaySmsbowerPriceQueryResult.value || {}
  return normalizeGoPayHeroSmsTierBadges(
    result.filtered_tiers,
    result.filtered_prices,
    gopayForm.value.gopayAutoSignupSmsbowerPreferredPrice,
  )
})

const gopayHeroSmsPriceQuerySummary = computed(() => {
  const result = gopayHeroSmsPriceQueryResult.value
  if (!result) return ''
  const formatTiers = (tiers, fallbackPrices) => {
    if (Array.isArray(tiers) && tiers.length) {
      return tiers
        .map(tier => {
          const price = tier?.price ?? tier?.cost
          const count = Number(tier?.count)
          return Number.isFinite(count) ? `${price}(x${Math.max(0, Math.floor(count))})` : String(price)
        })
        .join(', ')
    }
    return Array.isArray(fallbackPrices) && fallbackPrices.length ? fallbackPrices.join(', ') : '无'
  }
  const prices = Array.isArray(result.prices) ? result.prices : []
  const filtered = Array.isArray(result.filtered_prices) ? result.filtered_prices : []
  const allText = formatTiers(result.tiers, prices)
  const filteredText = formatTiers(result.filtered_tiers, filtered)
  return `全部档位：${allText}；区间内可用：${filteredText}`
})

function normalizeGoPaySmscodeProductBadges(products) {
  return (Array.isArray(products) ? products : [])
    .map((product, index) => {
      const price = Number(product?.price ?? product?.cost)
      if (!Number.isFinite(price) || price <= 0) return null
      const count = Number(product?.count ?? product?.available ?? product?.stock ?? product?.quantity)
      const id = String(product?.id ?? product?.product_id ?? product?.productId ?? index)
      return {
        key: `${id}-${index}`,
        price: String(Math.round(price * 10000) / 10000).replace(/\.?0+$/, ''),
        count: Number.isFinite(count) ? Math.max(0, Math.floor(count)) : 0,
      }
    })
    .filter(Boolean)
}

const gopaySmscodeAllProductBadges = computed(() => {
  const result = gopaySmscodePriceQueryResult.value || {}
  return normalizeGoPaySmscodeProductBadges(result.products)
})

const gopaySmscodeFilteredProductBadges = computed(() => {
  const result = gopaySmscodePriceQueryResult.value || {}
  return normalizeGoPaySmscodeProductBadges(result.filtered_products)
})

const gopayOtpChannel = computed(() => {
  return gopayForm.value.otpChannel === 'whatsapp' ? 'whatsapp' : 'sms'
})

const gopayUsingWhatsAppOtp = computed(() => {
  return gopayOtpChannel.value === 'whatsapp'
})

const gopayEffectiveEmail = computed(() => {
  if (gopayForm.value.autoRegister) return ''
  if (gopayBatchActive.value) {
    return gopaySelectedBatchEmails.value[0] || ''
  }
  return String(gopayForm.value.email || '').trim().toLowerCase()
})

const gopayPhoneAccounts = computed(() => {
  const fallbackCountryCode = digitsOnly(gopayForm.value.countryCode) || '62'
  const seen = new Set()
  return String(gopayForm.value.phonePoolText || '')
    .split(/\r?\n/)
    .map(line => String(line || '').trim())
    .filter(Boolean)
    .map(line => {
      const separator = line.includes('|') ? '|' : ','
      const parts = line.split(separator).map(part => String(part || '').trim()).filter(Boolean)
      if (gopayUsingWhatsAppOtp.value) {
        if (parts.length < 2) return null
        const countryCode = parts.length >= 3 ? digitsOnly(parts[0]) || fallbackCountryCode : fallbackCountryCode
        const phoneNumber = parts.length >= 3 ? parts[1] : parts[0]
        const gopayPin = parts[parts.length - 1]
        if (!phoneNumber || !gopayPin) return null
        const key = `${countryCode}|${phoneNumber}|whatsapp`
        if (seen.has(key)) return null
        seen.add(key)
        return { country_code: countryCode, phone_number: phoneNumber, sms_url: '', gopay_pin: gopayPin, otp_channel: 'whatsapp' }
      }
      if (parts.length < 3) return null
      const countryCode = parts.length >= 4 ? digitsOnly(parts[0]) || fallbackCountryCode : fallbackCountryCode
      const phoneNumber = parts.length >= 4 ? parts[1] : parts[0]
      const smsUrl = parts.length >= 4 ? parts.slice(2, -1).join(separator) : parts.slice(1, -1).join(separator)
      const gopayPin = parts[parts.length - 1]
      if (!phoneNumber || !smsUrl || !gopayPin) return null
      const key = `${countryCode}|${phoneNumber}|${smsUrl}`
      if (seen.has(key)) return null
      seen.add(key)
      return { country_code: countryCode, phone_number: phoneNumber, sms_url: smsUrl, gopay_pin: gopayPin, otp_channel: 'sms' }
    })
    .filter(Boolean)
})

const gopayActivePhoneAccounts = computed(() => {
  return gopayForm.value.usePhonePool ? gopayPhoneAccounts.value : []
})

const gopayPhonePoolSummary = computed(() => {
  if (gopayAutoSignupEnabled.value) return '已切换为自动注册 GoPay 钱包，当前不使用手动手机号池。'
  if (!gopayForm.value.usePhonePool) return '未启用，当前使用上方单手机号。'
  if (!gopayPhoneAccounts.value.length) return '已启用，但还没有有效手机号，请先配置。'
  return `已启用 ${gopayPhoneAccounts.value.length} 个手机号，提交任务时按顺序轮换。`
})

const gopayPhonePoolPlaceholder = computed(() => {
  if (gopayUsingWhatsAppOtp.value) {
    return '每行：国家区号|手机号|GoPay PIN\n86|15825989172|558023'
  }
  return '每行：国家区号|手机号|短信接口URL|GoPay PIN\n62|81997420107|https://it.tgflare.com/api/record?token=...|558023'
})

const gopayProxyPoolEntries = computed(() => parseGoPayProxyPoolLines(gopayForm.value.proxyPoolText))
const gopayProxyApiHelp = computed(() => {
  if (gopayForm.value.proxyApiProvider === '1024proxy') {
    return '运行时使用 1024proxy 印尼代理 API，每次注册 GoPay 钱包前提取一条。'
  }
  return '运行时使用 Cliproxy 印尼代理 API：region=ID&num=1&time=30&format=n&type=txt。'
})
const gopayProxySummary = computed(() => {
  if (gopayForm.value.proxyApiEnabled) {
    return '已启用代理 API 轮换；每次注册 GoPay 钱包前调用一次供应商 API。'
  }
  if (gopayForm.value.proxyPoolEnabled) {
    return `已配置 ${gopayProxyPoolEntries.value.length} 条代理；每次注册 GoPay 钱包前随机选一条。`
  }
  return gopayForm.value.proxyUrl ? '已配置单条代理；所有 GoPay 钱包注册使用这条代理。' : '未配置代理；GoPay 自动注册会在取号前阻断，避免触发 429。'
})

const gopaySinglePhoneComplete = computed(() => {
  return Boolean(
    gopayForm.value.phoneNumber
    && gopayForm.value.gopayPin
    && (gopayUsingWhatsAppOtp.value || gopayForm.value.smsUrl)
  )
})

const gopayCanSubmit = computed(() => {
  return Boolean(
    (gopayForm.value.autoRegister || gopayEffectiveEmail.value)
    && (!gopayForm.value.autoRegister || !gopayAutoRegisterUsesDomains.value || gopaySelectedAutoRegisterDomains.value.length)
    && gopayForm.value.gopayPin
    && (!gopayAutoSignupEnabled.value || gopayAutoSignupProviderConfigured.value)
    && (
      gopayAutoSignupEnabled.value
      || (gopayForm.value.usePhonePool ? gopayPhoneAccounts.value.length > 0 : gopaySinglePhoneComplete.value)
    )
  )
})

let normalizingGoPayPhone = false

function digitsOnly(value) {
  return String(value || '').replace(/\D/g, '')
}

function parseGoPayProxyPoolLines(text) {
  const seen = new Set()
  return String(text || '')
    .split(/\r?\n|,/)
    .map(line => String(line || '').split('#')[0].trim())
    .filter(line => {
      if (!line) return false
      const key = line.toLowerCase()
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function mergeGoPayProxyPoolText(...texts) {
  return parseGoPayProxyPoolLines(texts.join('\n')).join('\n')
}

function normalizeGoPayAutoRegisterCount(value) {
  const count = Number(value || 1)
  if (!Number.isFinite(count)) return 1
  return Math.max(1, Math.min(100, Math.floor(count)))
}

function normalizeGoPayPendingRetryAttempts(value) {
  const count = Number(value ?? 1)
  if (!Number.isFinite(count)) return 1
  return Math.max(0, Math.min(3, Math.floor(count)))
}

function normalizeGoPayConcurrency(value) {
  const count = Number(value ?? 1)
  if (!Number.isFinite(count)) return 1
  return Math.max(1, Math.min(10, Math.floor(count)))
}

function normalizeGoPayRuntimeSeconds(value, fallback, maxSeconds) {
  const seconds = Number(value ?? fallback)
  if (!Number.isFinite(seconds)) return fallback
  return Math.max(0, Math.min(maxSeconds, Math.floor(seconds)))
}

async function loadGoPayAutoSignupConfig({ applyDefaults = false } = {}) {
  gopayAutoSignupConfigLoading.value = true
  try {
    const cfg = await api.getGoPayAutoSignupConfig()
    gopayAutoSignupConfig.value = cfg
    gopayForm.value.gopayAutoSignupSmscodeBaseUrl = String(cfg.smscode_base_url || 'https://api.smscode.gg/v1').trim()
    gopayForm.value.gopayAutoSignupSmscodeCountryId = String(cfg.smscode_country_id || '7').trim()
    gopayForm.value.gopayAutoSignupSmscodePlatformId = String(cfg.smscode_platform_id || '').trim()
    gopayForm.value.gopayAutoSignupSmscodePlatformQuery = String(cfg.smscode_platform_query || 'gojek').trim()
    gopayForm.value.gopayAutoSignupSmscodeProductId = String(cfg.smscode_product_id || '').trim()
    if (applyDefaults) {
      gopayForm.value.gopayAutoSignupSmsProvider = ['hero_sms', 'smsbower', 'smscode'].includes(cfg.provider) ? cfg.provider : 'smscloud'
      gopayForm.value.gopayAutoSignupMode = 'http'
      gopayForm.value.countryCode = '62'
      gopayForm.value.gopayAutoSignupHeroSmsBaseUrl = String(cfg.hero_sms_base_url || 'https://hero-sms.com/stubs/handler_api.php').trim()
      gopayForm.value.gopayAutoSignupHeroSmsCountry = String(cfg.hero_sms_country || '6').trim()
      gopayForm.value.gopayAutoSignupHeroSmsService = String(cfg.hero_sms_service || 'ni').trim()
      gopayForm.value.gopayAutoSignupHeroSmsMinPrice = String(cfg.hero_sms_min_price || '').trim()
      gopayForm.value.gopayAutoSignupHeroSmsMaxPrice = String(cfg.hero_sms_max_price || '').trim()
      gopayForm.value.gopayAutoSignupHeroSmsPreferredPrice = String(cfg.hero_sms_preferred_price || '').trim()
      gopayForm.value.gopayAutoSignupSmsbowerBaseUrl = String(cfg.smsbower_base_url || 'https://smsbower.page/stubs/handler_api.php').trim()
      gopayForm.value.gopayAutoSignupSmsbowerCountry = String(cfg.smsbower_country || '6').trim()
      gopayForm.value.gopayAutoSignupSmsbowerService = String(cfg.smsbower_service || 'ni').trim()
      gopayForm.value.gopayAutoSignupSmsbowerMinPrice = String(cfg.smsbower_min_price || '').trim()
      gopayForm.value.gopayAutoSignupSmsbowerMaxPrice = String(cfg.smsbower_max_price || '').trim()
      gopayForm.value.gopayAutoSignupSmsbowerPreferredPrice = String(cfg.smsbower_preferred_price || '').trim()
      gopayForm.value.gopayAutoSignupSmscodeBaseUrl = String(cfg.smscode_base_url || 'https://api.smscode.gg/v1').trim()
      gopayForm.value.gopayAutoSignupSmscodeCountryId = String(cfg.smscode_country_id || '7').trim()
      gopayForm.value.gopayAutoSignupSmscodePlatformId = String(cfg.smscode_platform_id || '').trim()
      gopayForm.value.gopayAutoSignupSmscodePlatformQuery = String(cfg.smscode_platform_query || 'gojek').trim()
      gopayForm.value.gopayAutoSignupSmscodeProductId = String(cfg.smscode_product_id || '').trim()
      gopayForm.value.gopayAutoSignupSmscodeMinPrice = String(cfg.smscode_min_price || '').trim()
      gopayForm.value.gopayAutoSignupSmscodeMaxPrice = String(cfg.smscode_max_price || '').trim()
    }
  } catch (e) {
    gopayAutoSignupConfig.value = null
    console.error('加载 GoPay 自动注册配置失败:', e)
  } finally {
    gopayAutoSignupConfigLoading.value = false
  }
}

async function loadGoPayRekberinajaConfig() {
  try {
    const cfg = await api.getRekberinajaConfig()
    gopayRekberinajaConfig.value = cfg || {}
    if (Boolean(cfg?.transfer_enabled ?? cfg?.enabled)) {
      gopayForm.value.gopayBalanceWaitFallbackTransfer = false
    }
  } catch (e) {
    gopayRekberinajaConfig.value = null
    console.error('加载 Rekberinaja 配置失败:', e)
  }
}

async function queryGoPayHeroSmsPrices() {
  gopayHeroSmsPriceQueryLoading.value = true
  gopayHeroSmsPriceQueryResult.value = null
  try {
    const result = await api.queryGoPayHeroSmsPrices({
      hero_sms_base_url: gopayForm.value.gopayAutoSignupHeroSmsBaseUrl,
      hero_sms_country: gopayForm.value.gopayAutoSignupHeroSmsCountry,
      hero_sms_service: gopayForm.value.gopayAutoSignupHeroSmsService,
      hero_sms_min_price: gopayForm.value.gopayAutoSignupHeroSmsMinPrice,
      hero_sms_max_price: gopayForm.value.gopayAutoSignupHeroSmsMaxPrice,
      hero_sms_preferred_price: gopayForm.value.gopayAutoSignupHeroSmsPreferredPrice,
    })
    gopayHeroSmsPriceQueryResult.value = result
  } catch (e) {
    message.value = e?.message || 'hero-sms 查询失败'
    messageClass.value = 'bg-red-500/10 text-red-300 border border-red-500/30'
  } finally {
    gopayHeroSmsPriceQueryLoading.value = false
  }
}

async function queryGoPaySmsbowerPrices() {
  gopaySmsbowerPriceQueryLoading.value = true
  gopaySmsbowerPriceQueryResult.value = null
  try {
    const cfg = gopayAutoSignupConfig.value || {}
    const result = await api.queryGoPaySmsbowerPrices({
      smsbower_base_url: gopayForm.value.gopayAutoSignupSmsbowerBaseUrl || cfg.smsbower_base_url || 'https://smsbower.page/stubs/handler_api.php',
      smsbower_country: gopayForm.value.gopayAutoSignupSmsbowerCountry || cfg.smsbower_country || '6',
      smsbower_service: gopayForm.value.gopayAutoSignupSmsbowerService || cfg.smsbower_service || 'ni',
      smsbower_min_price: gopayForm.value.gopayAutoSignupSmsbowerMinPrice,
      smsbower_max_price: gopayForm.value.gopayAutoSignupSmsbowerMaxPrice,
      smsbower_preferred_price: gopayForm.value.gopayAutoSignupSmsbowerPreferredPrice,
    })
    gopaySmsbowerPriceQueryResult.value = result
  } catch (e) {
    message.value = e?.message || 'smsbower 查询失败'
    messageClass.value = 'bg-red-500/10 text-red-300 border border-red-500/30'
  } finally {
    gopaySmsbowerPriceQueryLoading.value = false
  }
}

async function queryGoPaySmscodePrices() {
  gopaySmscodePriceQueryLoading.value = true
  gopaySmscodePriceQueryResult.value = null
  try {
    const cfg = gopayAutoSignupConfig.value || {}
    const result = await api.queryGoPaySmscodePrices({
      smscode_base_url: gopayForm.value.gopayAutoSignupSmscodeBaseUrl || cfg.smscode_base_url || 'https://api.smscode.gg/v1',
      smscode_country_id: gopayForm.value.gopayAutoSignupSmscodeCountryId || cfg.smscode_country_id || '7',
      smscode_platform_id: gopayForm.value.gopayAutoSignupSmscodePlatformId || cfg.smscode_platform_id || '',
      smscode_platform_query: gopayForm.value.gopayAutoSignupSmscodePlatformQuery || cfg.smscode_platform_query || 'gojek',
      smscode_min_price: gopayForm.value.gopayAutoSignupSmscodeMinPrice,
      smscode_max_price: gopayForm.value.gopayAutoSignupSmscodeMaxPrice,
    })
    gopaySmscodePriceQueryResult.value = result
  } catch (e) {
    message.value = e?.message || 'SMSCode 查询失败'
    messageClass.value = 'bg-red-500/10 text-red-300 border border-red-500/30'
  } finally {
    gopaySmscodePriceQueryLoading.value = false
  }
}

function splitGoPayPhoneInput(phoneValue, countryCodeValue, { forceLocal = false } = {}) {
  const rawPhone = String(phoneValue || '').trim()
  const phoneDigits = digitsOnly(rawPhone)
  const fallbackCountryCode = digitsOnly(countryCodeValue) || '62'
  const hasExplicitCountryCode = Boolean(digitsOnly(countryCodeValue))
  if (!phoneDigits) return null

  const candidateCodes = Array.from(new Set([
    fallbackCountryCode,
    '62',
    '86',
    '1',
    '60',
    '65',
    '852',
    '886',
    '81',
    '82',
    '44',
  ].filter(Boolean)))
  let countryCode = ''

  if (rawPhone.startsWith('+')) {
    countryCode = candidateCodes.find(code => phoneDigits.startsWith(code) && phoneDigits.length >= code.length + 6) || ''
  }
  if (!countryCode && phoneDigits.startsWith(fallbackCountryCode) && phoneDigits.length >= fallbackCountryCode.length + 6) {
    countryCode = fallbackCountryCode
  }
  if (!countryCode && !hasExplicitCountryCode && !rawPhone.startsWith('0')) {
    countryCode = candidateCodes.find(code => phoneDigits.startsWith(code) && phoneDigits.length >= code.length + 7) || ''
  }
  if (!countryCode && (forceLocal || hasExplicitCountryCode)) {
    countryCode = fallbackCountryCode
  }
  if (!countryCode) return null

  let localNumber = countryCode && phoneDigits.startsWith(countryCode)
    ? phoneDigits.slice(countryCode.length)
    : phoneDigits
  if (countryCode === '62' && localNumber.startsWith('0')) {
    localNumber = localNumber.slice(1)
  }
  if (!localNumber) return null
  return { countryCode, phoneNumber: localNumber }
}

function normalizeGoPayPhoneFields(options = {}) {
  if (normalizingGoPayPhone) return
  const cleanedCountryCode = digitsOnly(gopayForm.value.countryCode) || '62'
  const split = splitGoPayPhoneInput(gopayForm.value.phoneNumber, cleanedCountryCode, options)
  const nextCountryCode = split?.countryCode || cleanedCountryCode
  const nextPhoneNumber = split?.phoneNumber || String(gopayForm.value.phoneNumber || '').trim()
  if (nextCountryCode === gopayForm.value.countryCode && nextPhoneNumber === gopayForm.value.phoneNumber) return

  normalizingGoPayPhone = true
  gopayForm.value.countryCode = nextCountryCode
  gopayForm.value.phoneNumber = nextPhoneNumber
  nextTick(() => {
    normalizingGoPayPhone = false
  })
}

function scheduleGoPayPhoneNormalize() {
  nextTick(() => normalizeGoPayPhoneFields())
}

watch(
  () => gopayForm.value.phoneNumber,
  () => normalizeGoPayPhoneFields()
)

watch(
  () => gopayForm.value.countryCode,
  () => {
    if (normalizingGoPayPhone) return
    const cleaned = digitsOnly(gopayForm.value.countryCode)
    if (cleaned && cleaned !== gopayForm.value.countryCode) {
      normalizingGoPayPhone = true
      gopayForm.value.countryCode = cleaned
      nextTick(() => {
        normalizingGoPayPhone = false
      })
    }
  }
)

watch(
  () => gopayForm.value.autoRegister,
  enabled => {
    if (!enabled) return
    gopayForm.value.batchMode = false
    gopayForm.value.accountEmails = []
    gopayForm.value.email = ''
    gopayForm.value.checkoutUrl = ''
  }
)

watch(
  () => gopayForm.value.gopayAutoSignup,
  enabled => {
    if (!enabled) return
    gopayForm.value.usePhonePool = false
    gopayForm.value.otpChannel = 'sms'
    loadGoPayAutoSignupConfig()
  }
)

watch(
  () => gopayForm.value.gopayAutoSignupSmsProvider,
  () => {
    if (gopayAutoSignupEnabled.value) {
      loadGoPayAutoSignupConfig()
    }
  }
)

watch(
  () => rekberinajaTransferEnabled.value,
  enabled => {
    if (enabled) {
      gopayForm.value.gopayBalanceWaitFallbackTransfer = false
    }
  }
)

watch(
  () => gopayForm.value.autoRegisterCount,
  count => {
    const normalized = normalizeGoPayAutoRegisterCount(count)
    if (normalized !== count) {
      gopayForm.value.autoRegisterCount = normalized
    }
  }
)

watch(
  () => gopayForm.value.pendingRetryAttempts,
  count => {
    const normalized = normalizeGoPayPendingRetryAttempts(count)
    if (normalized !== count) {
      gopayForm.value.pendingRetryAttempts = normalized
    }
  }
)

watch(
  () => gopayForm.value.gopayConcurrency,
  count => {
    const normalized = normalizeGoPayConcurrency(count)
    if (normalized !== count) {
      gopayForm.value.gopayConcurrency = normalized
    }
  }
)

watch(
  gopayRuntimeBalancePollIntervalSeconds,
  count => {
    const normalized = normalizeGoPayRuntimeSeconds(count, 20, 300)
    if (normalized !== count) {
      gopayRuntimeBalancePollIntervalSeconds.value = normalized
    }
  }
)

watch(
  gopayRuntimeTransferBalanceWaitSeconds,
  count => {
    const normalized = normalizeGoPayRuntimeSeconds(count, 120, 1800)
    if (normalized !== count) {
      gopayRuntimeTransferBalanceWaitSeconds.value = normalized
    }
  }
)

watch(
  () => gopayForm.value.proxyPoolEnabled,
  enabled => {
    if (enabled) {
      gopayForm.value.proxyApiEnabled = false
    }
  }
)

watch(
  () => gopayForm.value.proxyApiEnabled,
  enabled => {
    if (enabled) {
      gopayForm.value.proxyPoolEnabled = false
      gopayForm.value.proxyApiProvider = ['1024proxy', 'cliproxy'].includes(String(gopayForm.value.proxyApiProvider || ''))
        ? gopayForm.value.proxyApiProvider
        : 'cliproxy'
    }
  }
)

watch(
  () => getRememberedGoPayForm(),
  () => saveGoPayFormState(),
  { deep: true }
)

watch(
  () => getRememberedChatGPTBindForm(),
  () => saveChatGPTBindFormState(),
  { deep: true }
)

const availableCards = computed(() => {
  return (cardOptions.value || []).filter(card => card?.id && card?.status === 'unused')
})

const selectedCard = computed(() => {
  return (cardOptions.value || []).find(card => card.id === bindTaskForm.value.cardItemId) || null
})

const selectedCardLabel = computed(() => {
  return selectedCard.value ? formatCardOption(selectedCard.value) : ''
})

const effectiveCheckoutUrl = computed(() => {
  return bindTaskForm.value.checkoutUrl || currentLink.value || ''
})

const bindProxyApiHelp = computed(() => {
  if (!bindTaskForm.value.proxyApiEnabled) {
    return '未启用时不使用动态代理；启用后每次绑卡任务启动前调用一次 Cliproxy API 获取/轮换代理。'
  }
  const country = String(bindTaskForm.value.proxyApiCountry || 'US').trim().toUpperCase() || 'US'
  return `每次绑卡任务启动前调用 Cliproxy API，region=${country}。`
})

const bindResult = computed(() => bindTask.value?.result || null)

const bindTaskRunning = computed(() => {
  return ['pending', 'running'].includes(bindTask.value?.status)
})

const gopayTaskRunning = computed(() => {
  return ['pending', 'running'].includes(gopayTask.value?.status)
})

const gopayRunningAccountCount = computed(() => {
  const params = gopayTask.value?.params || {}
  if (params.auto_register) {
    return normalizeGoPayAutoRegisterCount(params.auto_register_count)
  }
  const taskAccounts = Array.isArray(params.account_emails) ? params.account_emails : []
  if (taskAccounts.length) return taskAccounts.length
  return gopayBatchActive.value ? gopaySelectedBatchEmails.value.length : 1
})

const gopaySkipAvailable = computed(() => {
  return gopayTaskRunning.value && gopayRunningAccountCount.value > 1
})

const bindTaskStatusLabel = computed(() => {
  const status = bindTask.value?.status || ''
  if (status === 'pending') return '排队中'
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled') return '已取消'
  return status || '-'
})

const gopayStageLabelMap = {
  open_chatgpt: '打开 ChatGPT',
  billing_info_ready: '账单信息已准备',
  billing_address_generated: '已自动生成账单地址',
  billing_address_retry: '账单地址无法识别，已更换地址重试',
  billing_fill_field: '填写账单字段',
  billing_select_field: '选择账单字段',
  billing_field_verified: '校验账单字段',
  gopay_try_account: '尝试当前 auth_session',
  gopay_rotate_account: '切换 auth_session 重试',
  gopay_account_bound: '当前账号绑定成功',
  gopay_auto_register_next: '自动注册绑定进度',
  gopay_auto_register_started: '自动注册账号',
  gopay_auto_register_done: '自动注册完成',
  gopay_auto_register_bind_wait: '注册后等待绑卡',
  gopay_auto_register_bind_failed: '注册成功但绑卡失败',
  gopay_auto_register_failed: '自动注册失败',
  gopay_wallet_auto_signup_started: '自动注册 GoPay 钱包',
  gopay_wallet_auto_signup_detail: 'GoPay 注册详情',
  gopay_wallet_auto_signup_retry: 'GoPay 注册换号重试',
  gopay_wallet_auto_signup_rate_limited: 'GoPay 注册触发限流，任务中止',
  gopay_wallet_auto_signup_provider_error: 'GoPay 短信供应商不可用',
  gopay_wallet_auto_signup_network_error: 'GoPay 注册网络中断，任务中止',
  gopay_wallet_auto_signup_probe_failed: 'GoPay 探测异常',
  gopay_wallet_auto_signup_done: 'GoPay 钱包已就绪',
  gopay_proxy_selected: '已选择 GoPay 代理',
  gopay_proxy_api_selected: '已通过 API 获取 GoPay 代理',
  gopay_wallet_reused: '复用 GoPay 钱包',
  gopay_wallet_reuse_discarded: '丢弃不可用复用钱包',
  gopay_wallet_preserved: '保留 GoPay 钱包',
  gopay_wallet_funding_started: 'GoPay 钱包充值',
  gopay_wallet_funding_skipped: '跳过 GoPay 钱包充值',
  gopay_wallet_funding_done: 'GoPay 钱包充值完成',
  gopay_wallet_funding_failed: 'GoPay 钱包充值失败',
  gopay_wallet_balance_checked: '查询 GoPay 余额',
  gopay_wallet_balance_ready: 'GoPay 余额已到账',
  gopay_wallet_balance_wait: '等待 GoPay 余额',
  gopay_wallet_balance_not_ready: 'GoPay 余额未到账',
  gopay_wallet_balance_fallback_transfer: 'GoPay 余额回退转账',
  gopay_wallet_balance_abandoned: '丢弃 GoPay 钱包',
  gopay_wallet_balance_check_failed: 'GoPay 余额查询失败',
  rekberinaja_login_started: 'Rekberinaja 登录',
  rekberinaja_login_done: 'Rekberinaja 登录成功',
  rekberinaja_balance_checked: 'Rekberinaja 余额检查',
  rekberinaja_order_create_started: '创建 Rekberinaja 订单',
  rekberinaja_order_created: 'Rekberinaja 订单已创建',
  rekberinaja_saldo_pay_started: 'Rekberinaja 站内支付',
  rekberinaja_saldo_pay_done: 'Rekberinaja 支付已提交',
  rekberinaja_order_poll: '轮询 Rekberinaja 订单',
  rekberinaja_order_completed: 'Rekberinaja 订单完成',
  rekberinaja_order_failed: 'Rekberinaja 订单失败',
  register_email_creating: '创建注册邮箱',
  register_email_created: '注册邮箱已创建',
  register_attempt_started: '开始注册账号',
  register_blocked: '注册被阻断',
  register_duplicate_swap: '切换注册邮箱',
  register_retry_wait: '注册重试等待',
  register_chatgpt_success: 'ChatGPT 注册成功',
  register_auth_session_fetch: '保存 auth_session',
  register_auth_session_saved: 'auth_session 已保存',
  register_account_recorded: '账号已写入号池',
  register_finished: '注册完成',
  register_failed: '注册失败',
  gopay_oauth_login_started: '开始 OAuth 补登录',
  gopay_oauth_login_retrying: 'OAuth 补登录重试',
  gopay_oauth_login_done: 'OAuth 补登录成功',
  gopay_oauth_login_failed: 'OAuth 补登录失败',
  gopay_oauth_phone_required_removed: 'OAuth 需要手机验证，已删除账号',
  gopay_oauth_phone_required: 'OAuth 需要手机验证，账号已保留',
  gopay_session_cpa_convert_started: '直接转换 CPA 认证',
  gopay_session_cpa_convert_done: 'CPA 认证转换成功',
  gopay_session_cpa_convert_failed: 'CPA 认证转换失败',
  gopay_batch_completed: '批量绑定完成',
  gopay_account_skipped_cooldown: '跳过冷却中的 auth_session',
  gopay_pending_retry_queued: '加入待重试',
  gopay_pending_retry_wait: '待重试退避等待',
  gopay_parallel_started: 'GoPay 并发开始',
  gopay_parallel_account: 'GoPay 并发账号',
  gopay_concurrency_limited: 'GoPay 并发受限',
  gopay_pending_retry_started: '开始重试待重试账号',
  gopay_pending_retry_account: '重试待重试账号',
  gopay_pending_retry_failed: '待重试账号失败',
  gopay_auth_session_refresh_started: '刷新 auth_session',
  gopay_auth_session_refresh_done: 'auth_session 已刷新',
  gopay_auth_session_refresh_failed: 'auth_session 刷新失败',
  chatgpt_user_paid_skip: '账号已是付费用户，跳过 GoPay',
  gopay_skip_current_requested: '已请求跳过当前账号',
  gopay_account_skipped_by_user: '已跳过当前账号',
  gopay_all_accounts_skipped: '所有账号都已跳过',
  generate_checkout: '生成支付链接',
  checkout_ready: '支付链接已生成',
  open_checkout: '打开支付页',
  checkout_opened: '已进入支付页',
  checkout_context_warmup: '预热 ChatGPT checkout 上下文',
  chatgpt_http_session_ready: 'ChatGPT HTTP 会话已准备',
  gopay_http_flow: '进入 GoPay 协议绑定流程',
  stripe_create_payment_method: '创建 Stripe GoPay 支付方式',
  stripe_init: '初始化 Stripe 支付页',
  stripe_confirm: '确认 Stripe GoPay 支付方式',
  chatgpt_approve: '确认 ChatGPT checkout',
  chatgpt_approve_blocked_rotate: 'ChatGPT approve 被拦截，切换账号',
  chatgpt_approve_blocked_cooldown: 'ChatGPT approve 被拦截，账号进入冷却',
  gopay_all_accounts_blocked: '所有账号 approve 均被拦截',
  checkout_not_approved_rotate: '付款未获批准，切换账号',
  gopay_retryable_failure_rotate: '可重试失败，切换账号',
  gopay_already_linked_retry: 'GoPay 已绑定其他账号，稍后重试',
  gopay_rate_limited_retry: 'GoPay/Midtrans 限流，稍后重试',
  midtrans_linking_retry: 'GoPay 账户绑定限流重试',
  gopay_otp_retry: 'GoPay OTP 未完成，稍后重试',
  gopay_all_accounts_rejected: '所有账号付款均未获批准',
  resolve_midtrans_redirect: '解析 Midtrans 跳转',
  pm_redirect: '跟随 Stripe 跳转',
  midtrans_load_transaction: '读取 Midtrans 交易',
  stripe_zero_due_confirmed: '确认 Stripe 应付金额为 0',
  stripe_nonzero_amount_blocked: 'Stripe 金额非 0，已停止',
  midtrans_nonzero_amount_blocked: 'Midtrans 金额非 0，已停止',
  gopay_nonzero_amount_blocked_rotate: '账单金额非 0，切换账号',
  gopay_all_nonzero_amount_blocked: '所有账号账单金额均非 0',
  midtrans_linking: '发起 GoPay 账户绑定',
  midtrans_already_linked: '手机号已绑定其他账号，等待解绑后重试',
  midtrans_already_linked_failed: '手机号仍绑定其他账号，已停止',
  gopay_wallet_rate_limited: 'GoPay 注册触发限流，任务已中止',
  gopay_wallet_network_error: 'GoPay 注册网络中断，任务已中止',
  gopay_validate_reference: '校验 GoPay 绑定引用',
  gopay_user_consent: '确认 GoPay 授权',
  gopay_rate_limited: 'GoPay 尝试过多，请稍后再试',
  wait_sms_otp_window: '等待 GoPay SMS 可重发',
  trigger_sms_otp: '协议触发 GoPay SMS OTP',
  sms_otp_triggered: '已触发 GoPay SMS OTP',
  sms_otp_resend_due: '2 分钟未收到 OTP，重新发送',
  sms_otp_resend_failed: '重新发送 OTP 失败',
  sms_otp_trigger_failed: '触发 GoPay SMS OTP 失败',
  whatsapp_otp_trigger: '触发 WhatsApp OTP',
  wait_whatsapp_otp: '等待 WhatsApp OTP',
  wait_otp: '等待 GoPay OTP',
  fetch_otp: '拉取 GoPay OTP',
  otp_received: '收到 GoPay OTP',
  otp_invalid: 'OTP 错误，继续等待新验证码',
  gopay_validate_otp: '校验 GoPay OTP',
  gopay_tokenize_pin: '生成 GoPay PIN token',
  gopay_validate_pin: '校验 GoPay 绑定 PIN',
  midtrans_create_charge: '创建 Midtrans GoPay 扣款',
  gopay_payment_validate: '校验 GoPay 扣款引用',
  gopay_payment_confirm: '确认 GoPay 扣款',
  gopay_payment_process: '提交 GoPay 扣款 PIN',
  gopay_payment_process_failed_rotate: 'GoPay 钱包扣款授权失败，切换账号',
  gopay_all_payment_process_failed: '所有账号 GoPay 扣款授权均失败',
  payment_completed: '支付完成，回查状态',
  chatgpt_verify: '回查 ChatGPT 支付结果',
  select_gopay: '选择 GoPay 支付方式',
  gopay_selected: '已选择 GoPay',
  submit_checkout: '提交订阅',
  submit_clicked: '已点击订阅',
  submit_retry: '订阅提交失败，准备重试',
  fill_billing_info: '填写账单信息',
  billing_info_filled: '已填写账单信息',
  wait_phone_step: '等待手机号步骤',
  fill_phone: '填写 GoPay 手机号',
  phone_filled: '已填写手机号',
  confirm_phone: '确认手机号',
  phone_confirmed: '已确认手机号',
  wait_sms_resend: '等待短信重发入口',
  sms_resend_clicked: '已点击短信重发',
  fetch_sms: '获取短信验证码',
  fill_sms: '填写短信验证码',
  sms_filled: '已填写短信验证码',
  pay_now: '点击 Pay now / Bayar',
  pay_now_clicked: '已点击 Pay now / Bayar',
  fill_pin: '填写 GoPay PIN',
  pin_filled: '已填写 GoPay PIN',
  pin_confirm_clicked: '已确认 PIN',
  wait_result: '等待支付结果',
  completed: '流程完成',
  failed: '流程失败',
}

const gopayBoardTaskId = computed(() => {
  const id = String(gopayTask.value?.task_id || '')
  return id ? id.slice(0, 12) : ''
})

const gopayBoardTitle = computed(() => {
  if (!gopayTask.value) return '暂无任务'
  const params = gopayTask.value.params || {}
  if (params.auto_register) {
    const normalizedCount = normalizeGoPayAutoRegisterCount(params.auto_register_count)
    return normalizedCount > 1 ? `自动注册 GoPay · ${normalizedCount} 个账号` : '自动注册 GoPay'
  }
  const accounts = Array.isArray(params.account_emails) ? params.account_emails : []
  const count = accounts.length || 1
  return count > 1 ? `批量 GoPay · ${count} 个账号` : '单账号 GoPay'
})

const gopayBoardStatusLabel = computed(() => {
  if (gopayTask.value?.status === 'running') return '绑定中'
  return bindStatusText(gopayTask.value)
})

const gopayBoardView = computed(() => computeGoPayBoardView({
  task: gopayTask.value,
  form: gopayForm.value,
  batchActive: gopayBatchActive.value,
  selectedBatchEmails: gopaySelectedBatchEmails.value,
}))

const gopayTopCards = computed(() => (gopayBoardView.value.cards || []).filter(card => card.label !== '当前账号'))

const gopayBoardFailureCount = computed(() => {
  return gopayBoardView.value.failureCount
})

const gopayBoardPendingRetryCount = computed(() => {
  return gopayBoardView.value.pendingRetryCount
})

const gopayBoardPendingRetryMeta = computed(() => {
  return gopayBoardView.value.pendingRetryMeta
})

const gopayBoardRegistrationMeta = computed(() => {
  const result = gopayTask.value?.result || {}
  const params = gopayTask.value?.params || {}
  if (!params.auto_register) return ''
  const registeredEmails = new Set()
  if (Array.isArray(result.registered_emails)) {
    for (const email of result.registered_emails) {
      const normalized = String(email || '').trim().toLowerCase()
      if (normalized) registeredEmails.add(normalized)
    }
  }
  const events = Array.isArray(gopayTask.value?.progress_events) ? gopayTask.value.progress_events : []
  for (const event of events) {
    if (String(event?.stage || '') !== 'gopay_auto_register_done') continue
    const normalized = String(event?.email || '').trim().toLowerCase()
    if (normalized) registeredEmails.add(normalized)
  }
  const registered = registeredEmails.size
  return `注册成功 ${registered}`
})

const gopayBoardEmail = computed(() => {
  return gopayBoardView.value.currentAccount
})

const gopayBoardStage = computed(() => {
  const stage = gopayTask.value?.progress?.stage || ''
  if (stage) return gopayStageLabelMap[stage] || stage
  if (gopayTask.value?.status === 'completed') return '任务已完成'
  if (gopayTask.value?.status === 'failed') return '任务失败'
  if (gopayTask.value?.status === 'cancelled') return '任务已取消'
  return '待提交'
})

const gopayBoardProgressStats = computed(() => {
  return gopayBoardView.value.metrics.progressStats
})

const gopayBoardProgress = computed(() => {
  return gopayBoardView.value.progressText
})

const gopayBoardProgressPercent = computed(() => {
  const stats = gopayBoardProgressStats.value
  if (!stats.total) return 0
  const done = Math.max(stats.attempted, stats.successful)
  if (gopayTask.value?.status === 'completed') return 100
  return Math.min(100, Math.max(8, Math.round((done / stats.total) * 100)))
})

function taskStatusBadgeClass(status) {
  return {
    pending: 'bg-gray-500/10 text-gray-300',
    running: 'bg-blue-500/10 text-blue-300',
    completed: 'bg-emerald-500/10 text-emerald-300',
    failed: 'bg-red-500/10 text-red-300',
    cancelled: 'bg-amber-500/10 text-amber-300',
  }[status] || 'bg-gray-500/10 text-gray-400'
}

function taskStatusDotClass(status) {
  return {
    pending: 'bg-gray-400',
    running: 'bg-blue-400 animate-pulse',
    completed: 'bg-emerald-400',
    failed: 'bg-red-400',
    cancelled: 'bg-amber-400',
  }[status] || 'bg-gray-500'
}

function setMessage(text, ok = true) {
  message.value = text
  messageClass.value = ok
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 8000)
}

function showGoPaySuccessNotice(email = '') {
  gopaySuccessNoticeEmail.value = String(email || '').trim()
  gopaySuccessNoticeVisible.value = true
  if (gopaySuccessNoticeTimer) {
    window.clearTimeout(gopaySuccessNoticeTimer)
  }
  gopaySuccessNoticeTimer = window.setTimeout(() => {
    gopaySuccessNoticeVisible.value = false
    gopaySuccessNoticeEmail.value = ''
    gopaySuccessNoticeTimer = 0
  }, 5000)
}

function loadHistory() {
  try {
    const raw = localStorage.getItem(BIND_HISTORY_KEY)
    if (raw) {
      history.value = JSON.parse(raw)
    }
  } catch (e) {
    console.error('loadHistory', e)
  }
}

function normalizeEmailList(value) {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  return value
    .map(email => String(email || '').trim().toLowerCase())
    .filter(email => {
      if (!email || seen.has(email)) return false
      seen.add(email)
      return true
    })
}

function setGoPayPickerEmails(emails) {
  const normalized = normalizeEmailList(emails)
  if (gopayAccountPickerMode.value === 'runtime') {
    gopayRuntimeAppendEmails.value = normalized
  } else {
    gopayForm.value.accountEmails = normalized
  }
}

function mergeGoPayPickerEmails(emails) {
  setGoPayPickerEmails([
    ...activeGoPayAccountPickerEmails.value,
    ...emails,
  ])
}

function selectAllGoPayAccounts() {
  mergeGoPayPickerEmails(accountOptions.value.map(account => account.email))
}

function clearGoPayPickerAccounts() {
  setGoPayPickerEmails([])
}

async function loadGoPayAutoRegisterDomains() {
  if (gopayRegisterDomainLoading.value) return
  gopayRegisterDomainLoading.value = true
  try {
    const result = await api.getRegisterDomain()
    const domains = Array.isArray(result?.domains) && result.domains.length
      ? result.domains
      : (result?.domain ? [result.domain] : [])
    gopayRegisterDomainOptions.value = domains
      .map(domain => String(domain || '').trim().replace(/^@/, ''))
      .filter(Boolean)
    const selected = gopaySelectedAutoRegisterDomains.value.filter(domain => gopayRegisterDomainOptions.value.includes(domain))
    if (selected.length) {
      gopayForm.value.autoRegisterDomains = selected
    } else {
      const defaultDomain = String(result?.domain || gopayRegisterDomainOptions.value[0] || '').trim().replace(/^@/, '')
      gopayForm.value.autoRegisterDomains = defaultDomain ? [defaultDomain] : []
    }
  } catch (e) {
    setMessage(`读取自动注册域名失败: ${e.message}`, false)
  } finally {
    gopayRegisterDomainLoading.value = false
  }
}

async function loadGoPayAutoRegisterMailProviders() {
  if (gopayMailProviderLoading.value) return
  gopayMailProviderLoading.value = true
  try {
    const result = await api.getMailProviderConfig()
    gopayMailProviderOptions.value = result.provider_options || []
    if (!gopayForm.value.autoRegisterMailProvider) {
      gopayForm.value.autoRegisterMailProvider = result.provider || 'cloudflare_temp_email'
    }
    const luckmailFields = result.provider_fields?.luckmail || []
    const emailTypeField = luckmailFields.find(field => field.key === 'LUCKMAIL_EMAIL_TYPE')
    const domainField = luckmailFields.find(field => field.key === 'LUCKMAIL_PREFERRED_DOMAIN')
    const configuredLuckmailEmailType = String(emailTypeField?.value || '').trim()
    if (!gopayForm.value.autoRegisterLuckmailEmailType) {
      gopayForm.value.autoRegisterLuckmailEmailType = configuredLuckmailEmailType || gopayForm.value.autoRegisterLuckmailEmailType || 'ms_imap'
    }
    if (!gopayForm.value.autoRegisterLuckmailPreferredDomain && domainField?.value) {
      gopayForm.value.autoRegisterLuckmailPreferredDomain = domainField.value
      gopayForm.value.autoRegisterLuckmailPreferredDomains = [String(domainField.value).trim().replace(/^@/, '')].filter(Boolean)
    }
  } catch (e) {
    setMessage(`读取邮件 Provider 失败: ${e.message}`, false)
  } finally {
    gopayMailProviderLoading.value = false
  }
}

async function openGoPayAutoRegisterConfig() {
  await Promise.all([loadGoPayAutoRegisterMailProviders(), loadGoPayAutoRegisterDomains()])
  gopayAutoRegisterConfigOpen.value = true
}

function handleGoPayAutoRegisterToggle() {
  if (gopayForm.value.autoRegister) {
    openGoPayAutoRegisterConfig()
  } else {
    closeGoPayAutoRegisterConfig()
  }
}

function closeGoPayAutoRegisterConfig() {
  gopayAutoRegisterConfigOpen.value = false
}

function confirmGoPayAutoRegisterConfig() {
  if (gopayAutoRegisterUsesDomains.value && !gopaySelectedAutoRegisterDomains.value.length) {
    setMessage('请选择至少一个自动注册域名', false)
    return
  }
  gopayForm.value.autoRegisterDomains = gopayAutoRegisterUsesDomains.value ? gopaySelectedAutoRegisterDomains.value : []
  closeGoPayAutoRegisterConfig()
}

function selectAllGoPayAutoRegisterDomains() {
  gopayForm.value.autoRegisterDomains = [...gopayRegisterDomainOptions.value]
}

function clearGoPayAutoRegisterDomains() {
  gopayForm.value.autoRegisterDomains = []
}

function openGoPayPhonePoolConfig() {
  gopayPhonePoolConfigOpen.value = true
}

function handleGoPayPhonePoolToggle() {
  if (gopayForm.value.usePhonePool) {
    openGoPayPhonePoolConfig()
  } else {
    closeGoPayPhonePoolConfig()
  }
}

function closeGoPayPhonePoolConfig() {
  gopayPhonePoolConfigOpen.value = false
}

function confirmGoPayPhonePoolConfig() {
  if (!gopayPhoneAccounts.value.length) {
    setMessage('请至少配置一个有效手机号', false)
    return
  }
  closeGoPayPhonePoolConfig()
}

function openGoPayProxyPoolConfig() {
  gopayProxyPoolConfigOpen.value = true
}

function closeGoPayProxyPoolConfig() {
  gopayProxyPoolConfigOpen.value = false
}

function confirmGoPayProxyPoolConfig() {
  const merged = mergeGoPayProxyPoolText(gopayForm.value.proxyPoolText)
  if (!merged) {
    setMessage('请至少配置一条有效代理', false)
    return
  }
  gopayForm.value.proxyPoolText = merged
  gopayForm.value.proxyPoolEnabled = true
  closeGoPayProxyPoolConfig()
}

async function refreshWhatsAppOtpStatus() {
  try {
    whatsappOtpStatus.value = await api.getWhatsAppOtpStatus()
  } catch (e) {
    whatsappOtpStatus.value = {
      running: false,
      login_required: false,
      latest_otp: '',
      error: e.message,
    }
  }
}

function formatWhatsAppAdbStatus(status) {
  const serial = String(status?.adb_serial || '').trim()
  const adbPath = String(status?.adb_path || '').trim()
  const running = Boolean(status?.running)
  const state = running ? '运行中' : '未运行'
  if (!serial && !adbPath) return `ADB：${state}`
  if (serial && adbPath) return `ADB：${serial} / ${adbPath} / ${state}`
  return `ADB：${serial || adbPath} / ${state}`
}

async function startWhatsAppOtpListener({ silent = false } = {}) {
  if (whatsappOtpStarting.value) return whatsappOtpStatus.value
  whatsappOtpStarting.value = true
  if (!silent) {
    pushGoPayLog('正在启动 WhatsApp OTP 监听', 'info')
  }
  try {
    const adbPort = String(gopayForm.value.whatsappAdbPort || '').replace(/\D/g, '')
    const status = await api.startWhatsAppOtp({ adb_port: adbPort })
    whatsappOtpStatus.value = status
    if (!silent) {
      if (status?.last_error) {
        pushGoPayLog(`WhatsApp 监听异常: ${status.last_error}`, 'warn')
      } else {
        pushGoPayLog(`WhatsApp OTP 监听已启动，${formatWhatsAppAdbStatus(status)}`, 'success')
      }
    }
    return status
  } catch (e) {
    if (!silent) {
      pushGoPayLog(`启动 WhatsApp OTP 监听失败: ${e.message}`, 'error')
      setMessage(`启动 WhatsApp OTP 监听失败: ${e.message}`, false)
    }
    throw e
  } finally {
    whatsappOtpStarting.value = false
  }
}

function openGoPayAccountPicker(mode = 'batch') {
  gopayAccountPickerMode.value = mode === 'runtime' ? 'runtime' : 'batch'
  gopayAccountPickerOpen.value = true
}

function closeGoPayAccountPicker() {
  gopayAccountPickerOpen.value = false
}

function getRememberedChatGPTBindForm() {
  return {
    activeTab: ['bind', 'generate'].includes(activeTab.value) ? activeTab.value : '',
    selectedAccountEmail: String(selectedAccountEmail.value || '').trim().toLowerCase(),
    accountSearchKeyword: String(accountSearchKeyword.value || '').trim(),
    linkForm: {
      planType: ['plus', 'pro5x', 'pro20x', 'team'].includes(String(bindForm.value.planType || ''))
        ? bindForm.value.planType
        : 'plus',
      country: String(bindForm.value.country || 'PH').trim().toUpperCase() || 'PH',
      currency: String(bindForm.value.currency || 'PHP').trim().toUpperCase() || 'PHP',
      teamWorkspaceName: String(bindForm.value.teamWorkspaceName || 'MyWorkspace').trim() || 'MyWorkspace',
      teamSeatQuantity: Math.max(2, Number.parseInt(bindForm.value.teamSeatQuantity || 5, 10) || 5),
      teamPriceInterval: bindForm.value.teamPriceInterval === 'year' ? 'year' : 'month',
    },
    taskForm: {
      checkoutMode: bindTaskForm.value.checkoutMode === 'manual' ? 'manual' : 'auto',
      cardItemId: String(bindTaskForm.value.cardItemId || '').trim(),
      checkoutUrl: String(bindTaskForm.value.checkoutUrl || '').trim(),
      proxyApiEnabled: Boolean(bindTaskForm.value.proxyApiEnabled),
      proxyApiProvider: 'cliproxy',
      proxyApiCountry: String(bindTaskForm.value.proxyApiCountry || 'US').trim().toUpperCase() || 'US',
      proxyApiUrl: String(bindTaskForm.value.proxyApiUrl || '').trim(),
    },
  }
}

function loadChatGPTBindFormState() {
  try {
    if (props.standalone) return false
    const raw = localStorage.getItem(CHATGPT_BIND_FORM_STATE_KEY)
    if (!raw) return false
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return false
    if (!props.standalone && ['bind', 'generate'].includes(saved.activeTab)) {
      activeTab.value = saved.activeTab
    }
    selectedAccountEmail.value = String(saved.selectedAccountEmail || '').trim().toLowerCase()
    accountSearchKeyword.value = String(saved.accountSearchKeyword || '').trim()
    const linkForm = saved.linkForm && typeof saved.linkForm === 'object' ? saved.linkForm : {}
    const savedPlanType = String(linkForm.planType || '')
    bindForm.value = {
      ...bindForm.value,
      planType: ['plus', 'pro5x', 'pro20x', 'team'].includes(savedPlanType) ? savedPlanType : bindForm.value.planType,
      country: String(linkForm.country || bindForm.value.country || 'PH').trim().toUpperCase(),
      currency: String(linkForm.currency || bindForm.value.currency || 'PHP').trim().toUpperCase(),
      teamWorkspaceName: String(linkForm.teamWorkspaceName || bindForm.value.teamWorkspaceName || 'MyWorkspace').trim() || 'MyWorkspace',
      teamSeatQuantity: Math.max(2, Number.parseInt(linkForm.teamSeatQuantity || bindForm.value.teamSeatQuantity || 5, 10) || 5),
      teamPriceInterval: linkForm.teamPriceInterval === 'year' ? 'year' : 'month',
    }
    const taskForm = saved.taskForm && typeof saved.taskForm === 'object' ? saved.taskForm : {}
    bindTaskForm.value = {
      ...bindTaskForm.value,
      checkoutMode: taskForm.checkoutMode === 'manual' ? 'manual' : 'auto',
      cardItemId: String(taskForm.cardItemId || '').trim(),
      checkoutUrl: String(taskForm.checkoutUrl || '').trim(),
      proxyApiEnabled: Boolean(taskForm.proxyApiEnabled),
      proxyApiProvider: 'cliproxy',
      proxyApiCountry: String(taskForm.proxyApiCountry || 'US').trim().toUpperCase() || 'US',
      proxyApiUrl: String(taskForm.proxyApiUrl || '').trim(),
      manualConfirm: false,
    }
    return true
  } catch (e) {
    console.error('loadChatGPTBindFormState', e)
    return false
  }
}

function saveChatGPTBindFormState() {
  try {
    if (props.standalone || !['bind', 'generate'].includes(activeTab.value)) return
    localStorage.setItem(CHATGPT_BIND_FORM_STATE_KEY, JSON.stringify(getRememberedChatGPTBindForm()))
  } catch (e) {
    console.error('saveChatGPTBindFormState', e)
  }
}

function getRememberedGoPayForm() {
  return {
    email: String(gopayForm.value.email || '').trim().toLowerCase(),
    autoRegister: Boolean(gopayForm.value.autoRegister),
    autoRegisterCount: normalizedGoPayAutoRegisterCount.value,
    autoRegisterProtocol: Boolean(gopayForm.value.autoRegisterProtocol),
    gopayAutoSignup: Boolean(gopayForm.value.gopayAutoSignup),
    gopayAutoSignupSmsProvider: gopayAutoSignupProvider.value,
    gopayAutoSignupMode: gopayForm.value.gopayAutoSignupMode === 'appium' ? 'appium' : 'http',
    gopayAutoSignupHeroSmsMinPrice: String(gopayForm.value.gopayAutoSignupHeroSmsMinPrice || '').trim(),
    gopayAutoSignupHeroSmsMaxPrice: String(gopayForm.value.gopayAutoSignupHeroSmsMaxPrice || '').trim(),
    gopayAutoSignupHeroSmsPreferredPrice: String(gopayForm.value.gopayAutoSignupHeroSmsPreferredPrice || '').trim(),
    gopayAutoSignupSmsbowerMinPrice: String(gopayForm.value.gopayAutoSignupSmsbowerMinPrice || '').trim(),
    gopayAutoSignupSmsbowerMaxPrice: String(gopayForm.value.gopayAutoSignupSmsbowerMaxPrice || '').trim(),
    gopayAutoSignupSmsbowerPreferredPrice: String(gopayForm.value.gopayAutoSignupSmsbowerPreferredPrice || '').trim(),
    gopayAutoSignupSmscodeMinPrice: String(gopayForm.value.gopayAutoSignupSmscodeMinPrice || '').trim(),
    gopayAutoSignupSmscodeMaxPrice: String(gopayForm.value.gopayAutoSignupSmscodeMaxPrice || '').trim(),
    gopayBalanceWaitFallbackTransfer: Boolean(gopayForm.value.gopayBalanceWaitFallbackTransfer),
    autoRegisterMailProvider: String(gopayForm.value.autoRegisterMailProvider || ''),
    autoRegisterLuckmailEmailType: String(gopayForm.value.autoRegisterLuckmailEmailType || 'ms_imap'),
    autoRegisterLuckmailPreferredDomain: String(gopayForm.value.autoRegisterLuckmailPreferredDomain || ''),
    autoRegisterLuckmailPreferredDomains: Array.isArray(gopayForm.value.autoRegisterLuckmailPreferredDomains)
      ? gopayForm.value.autoRegisterLuckmailPreferredDomains
      : [],
    autoRegisterDomains: gopaySelectedAutoRegisterDomains.value,
    autoRegisterPrefix: String(gopayForm.value.autoRegisterPrefix || '').trim(),
    batchMode: Boolean(gopayForm.value.batchMode),
    accountEmails: normalizeEmailList(gopayForm.value.accountEmails),
    checkoutUrl: String(gopayForm.value.checkoutUrl || '').trim(),
    gopayPin: String(gopayForm.value.gopayPin || '').trim(),
    countryCode: digitsOnly(gopayForm.value.countryCode) || '62',
    phoneNumber: String(gopayForm.value.phoneNumber || '').trim(),
    usePhonePool: Boolean(gopayForm.value.usePhonePool),
    phonePoolText: String(gopayForm.value.phonePoolText || '').trim(),
    otpChannel: gopayOtpChannel.value,
    whatsappAdbPort: String(gopayForm.value.whatsappAdbPort || '').trim(),
    smsUrl: String(gopayForm.value.smsUrl || '').trim(),
    proxyLabel: String(gopayForm.value.proxyLabel || '').trim(),
    proxyUrl: String(gopayForm.value.proxyUrl || '').trim(),
    proxyPoolEnabled: Boolean(gopayForm.value.proxyPoolEnabled),
    proxyPoolText: String(gopayForm.value.proxyPoolText || '').trim(),
    proxyApiEnabled: Boolean(gopayForm.value.proxyApiEnabled),
    proxyApiProvider: ['1024proxy', 'cliproxy'].includes(String(gopayForm.value.proxyApiProvider || '')) ? gopayForm.value.proxyApiProvider : 'cliproxy',
    checkoutUiMode: gopayForm.value.checkoutUiMode === 'hosted' ? 'hosted' : 'custom',
    deleteRejectedAccounts: Boolean(gopayForm.value.deleteRejectedAccounts),
    autoOauthAfterSuccess: Boolean(gopayForm.value.autoOauthAfterSuccess),
    pendingRetryAttempts: normalizedGoPayPendingRetryAttempts.value,
    gopayConcurrency: normalizedGoPayConcurrency.value,
  }
}

function loadGoPayFormState() {
  try {
    const raw = localStorage.getItem(GOPAY_FORM_STATE_KEY)
    if (!raw) return false
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return false
    gopayForm.value = {
      ...gopayForm.value,
      email: String(saved.email || '').trim().toLowerCase(),
      autoRegister: Boolean(saved.autoRegister),
      autoRegisterCount: normalizeGoPayAutoRegisterCount(saved.autoRegisterCount),
      autoRegisterProtocol: Boolean(saved.autoRegisterProtocol),
      gopayAutoSignup: saved.gopayAutoSignup === undefined ? true : Boolean(saved.gopayAutoSignup),
      gopayAutoSignupSmsProvider: ['hero_sms', 'smsbower', 'smscode'].includes(saved.gopayAutoSignupSmsProvider) ? saved.gopayAutoSignupSmsProvider : 'smscloud',
      gopayAutoSignupMode: saved.gopayAutoSignupMode === 'appium' ? 'appium' : 'http',
      gopayAutoSignupHeroSmsApiKey: '',
      gopayAutoSignupHeroSmsBaseUrl: 'https://hero-sms.com/stubs/handler_api.php',
      gopayAutoSignupHeroSmsCountry: '6',
      gopayAutoSignupHeroSmsService: 'ni',
      gopayAutoSignupHeroSmsTimeout: 120,
      gopayAutoSignupHeroSmsMinPrice: String(saved.gopayAutoSignupHeroSmsMinPrice || '').trim(),
      gopayAutoSignupHeroSmsMaxPrice: String(saved.gopayAutoSignupHeroSmsMaxPrice || '').trim(),
      gopayAutoSignupHeroSmsPreferredPrice: String(saved.gopayAutoSignupHeroSmsPreferredPrice || '').trim(),
      gopayAutoSignupSmsbowerApiKey: '',
      gopayAutoSignupSmsbowerBaseUrl: 'https://smsbower.page/stubs/handler_api.php',
      gopayAutoSignupSmsbowerCountry: '6',
      gopayAutoSignupSmsbowerService: 'ni',
      gopayAutoSignupSmsbowerTimeout: 120,
      gopayAutoSignupSmsbowerMinPrice: String(saved.gopayAutoSignupSmsbowerMinPrice || '').trim(),
      gopayAutoSignupSmsbowerMaxPrice: String(saved.gopayAutoSignupSmsbowerMaxPrice || '').trim(),
      gopayAutoSignupSmsbowerPreferredPrice: String(saved.gopayAutoSignupSmsbowerPreferredPrice || '').trim(),
      gopayAutoSignupSmscloudBaseUrl: 'https://smscloud.sbs/api',
      gopayAutoSignupSmscloudCountry: '6',
      gopayAutoSignupSmscloudService: 'ni',
      gopayAutoSignupSmscloudMaxPrice: '',
      gopayAutoSignupSmscloudTimeout: 120,
      gopayAutoSignupSmscodeApiToken: '',
      gopayAutoSignupSmscodeBaseUrl: 'https://api.smscode.gg/v1',
      gopayAutoSignupSmscodeCountryId: '7',
      gopayAutoSignupSmscodePlatformId: '',
      gopayAutoSignupSmscodePlatformQuery: 'gojek',
      gopayAutoSignupSmscodeProductId: '',
      gopayAutoSignupSmscodeMinPrice: String(saved.gopayAutoSignupSmscodeMinPrice || '').trim(),
      gopayAutoSignupSmscodeMaxPrice: String(saved.gopayAutoSignupSmscodeMaxPrice || '').trim(),
      gopayAutoSignupSmscodeTimeout: 120,
      gopayBalanceWaitFallbackTransfer: Boolean(saved.gopayBalanceWaitFallbackTransfer),
      autoRegisterMailProvider: String(saved.autoRegisterMailProvider || gopayForm.value.autoRegisterMailProvider || ''),
      autoRegisterLuckmailEmailType: String(saved.autoRegisterLuckmailEmailType || gopayForm.value.autoRegisterLuckmailEmailType || 'ms_imap'),
      autoRegisterLuckmailPreferredDomain: String(saved.autoRegisterLuckmailPreferredDomain || gopayForm.value.autoRegisterLuckmailPreferredDomain || ''),
      autoRegisterLuckmailPreferredDomains: Array.isArray(saved.autoRegisterLuckmailPreferredDomains)
        ? saved.autoRegisterLuckmailPreferredDomains.map(domain => String(domain || '').trim().replace(/^@/, '')).filter(Boolean)
        : (saved.autoRegisterLuckmailPreferredDomain ? [String(saved.autoRegisterLuckmailPreferredDomain).trim().replace(/^@/, '')].filter(Boolean) : gopayForm.value.autoRegisterLuckmailPreferredDomains),
      autoRegisterDomains: Array.isArray(saved.autoRegisterDomains)
        ? saved.autoRegisterDomains.map(domain => String(domain || '').trim().replace(/^@/, '')).filter(Boolean)
        : [],
      autoRegisterPrefix: String(saved.autoRegisterPrefix || ''),
      autoRegisterPassword: '',
      batchMode: Boolean(saved.batchMode),
      accountEmails: normalizeEmailList(saved.accountEmails),
      checkoutUrl: String(saved.checkoutUrl || '').trim(),
      gopayPin: String(saved.gopayPin || '').trim(),
      countryCode: digitsOnly(saved.countryCode) || '62',
      phoneNumber: String(saved.phoneNumber || '').trim(),
      usePhonePool: Boolean(saved.usePhonePool),
      phonePoolText: String(saved.phonePoolText || '').trim(),
      otpChannel: saved.otpChannel === 'whatsapp' ? 'whatsapp' : 'sms',
      whatsappAdbPort: String(saved.whatsappAdbPort || '').replace(/\D/g, '').slice(0, 5),
      smsUrl: String(saved.smsUrl || '').trim(),
      proxyLabel: String(saved.proxyLabel || '').trim(),
      proxyUrl: String(saved.proxyUrl || '').trim(),
      proxyPoolEnabled: Boolean(saved.proxyPoolEnabled),
      proxyPoolText: String(saved.proxyPoolText || '').trim(),
      proxyApiEnabled: Boolean(saved.proxyApiEnabled),
      proxyApiProvider: ['1024proxy', 'cliproxy'].includes(String(saved.proxyApiProvider || '')) ? saved.proxyApiProvider : 'cliproxy',
      checkoutUiMode: saved.checkoutUiMode === 'custom' ? 'custom' : 'hosted',
      deleteRejectedAccounts: Boolean(saved.deleteRejectedAccounts),
      autoOauthAfterSuccess: Boolean(saved.autoOauthAfterSuccess),
      pendingRetryAttempts: normalizeGoPayPendingRetryAttempts(saved.pendingRetryAttempts),
      gopayConcurrency: normalizeGoPayConcurrency(saved.gopayConcurrency),
    }
    return true
  } catch (e) {
    console.error('loadGoPayFormState', e)
    return false
  }
}

function saveGoPayFormState() {
  try {
    localStorage.setItem(GOPAY_FORM_STATE_KEY, JSON.stringify(getRememberedGoPayForm()))
  } catch (e) {
    console.error('saveGoPayFormState', e)
  }
}

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const accounts = await api.getAccounts({ includeSessionStubs: true })
    accountOptions.value = (accounts || [])
      .filter(isBindableFreeAccount)
      .sort((a, b) => Number(b?.created_at || 0) - Number(a?.created_at || 0))
    const selectableEmails = new Set(accountOptions.value.map(account => String(account.email || '').toLowerCase()))
    if (selectedAccountEmail.value && !selectableEmails.has(selectedAccountEmail.value.toLowerCase())) {
      selectedAccountEmail.value = ''
    }
    if (gopayForm.value.email && !selectableEmails.has(gopayForm.value.email.toLowerCase())) {
      gopayForm.value.email = ''
    }
    gopayForm.value.accountEmails = normalizeEmailList(gopayForm.value.accountEmails)
      .filter(email => selectableEmails.has(email))
    gopayRuntimeAppendEmails.value = normalizeEmailList(gopayRuntimeAppendEmails.value)
      .filter(email => selectableEmails.has(email))
  } catch (e) {
    setMessage(`加载号池账号失败: ${e.message}`, false)
  } finally {
    loadingAccounts.value = false
  }
}

function isBindableFreeAccount(account) {
  if (!account?.email || account?.is_main_account) return false
  if (String(account?.account_type || '').toLowerCase() !== 'free') return false
  if (!hasBindableAccountAuth(account)) return false
  const status = String(account?.status || '').toLowerCase()
  // Quota-exhausted free accounts can still be upgraded through GoPay. Keep
  // standby excluded unless it is a CPA/Codex-auth import with a usable auth file.
  if (['fail', 'auth_invalid', 'orphan', 'pending'].includes(status)) return false
  if (status === 'standby' && !hasBindableCodexAuth(account)) return false
  return true
}

function hasBindableAccountAuth(account) {
  if (account?.auth_session_file) return true
  return hasBindableCodexAuth(account)
}

function hasBindableCodexAuth(account) {
  if (account?.has_codex_auth_file !== undefined) return Boolean(account.has_codex_auth_file)
  return Boolean(account?.codex_auth_file || account?.auth_file)
}

async function loadCards() {
  loadingCards.value = true
  try {
    const result = await api.getCardPool('card')
    cardOptions.value = result.items || []
    if (!availableCards.value.some(card => card.id === bindTaskForm.value.cardItemId)) {
      bindTaskForm.value.cardItemId = ''
    }
  } catch (e) {
    setMessage(`加载卡池失败: ${e.message}`, false)
  } finally {
    loadingCards.value = false
  }
}

function saveHistory() {
  try {
    localStorage.setItem(BIND_HISTORY_KEY, JSON.stringify(history.value.slice(0, 50)))
  } catch (e) {
    console.error('saveHistory', e)
  }
}

function formatDate() {
  const d = new Date()
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function pushBindLog(message, level = 'info') {
  const levelMap = {
    info: { label: 'INFO', levelClass: 'text-blue-400' },
    success: { label: 'SUCCESS', levelClass: 'text-emerald-400' },
    warn: { label: 'WARN', levelClass: 'text-amber-400' },
    error: { label: 'ERROR', levelClass: 'text-red-400' },
  }
  const meta = levelMap[level] || levelMap.info
  bindLogEntries.value.push({
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    time: formatDate(),
    message,
    label: meta.label,
    levelClass: meta.levelClass,
  })
  if (bindLogEntries.value.length > 200) {
    bindLogEntries.value.splice(0, bindLogEntries.value.length - 200)
  }
}

function scrollGoPayLogToBottom() {
  nextTick(() => {
    const el = gopayLogScrollRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function pushGoPayLog(message, level = 'info') {
  const normalizedMessage = String(message || '').replace(/\s+/g, ' ').trim()
  if (!normalizedMessage) return
  if (gopayLoggedMessages.value.has(normalizedMessage)) return
  gopayLoggedMessages.value.add(normalizedMessage)
  const levelMap = {
    info: { label: 'INFO', levelClass: 'text-blue-400' },
    success: { label: 'SUCCESS', levelClass: 'text-emerald-400' },
    warn: { label: 'WARN', levelClass: 'text-amber-400' },
    error: { label: 'ERROR', levelClass: 'text-red-400' },
  }
  const meta = levelMap[level] || levelMap.info
  gopayLogEntries.value.push({
    id: `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`,
    time: formatDate(),
    message: normalizedMessage,
    label: meta.label,
    levelClass: meta.levelClass,
  })
  if (gopayLogEntries.value.length > 200) {
    gopayLogEntries.value.splice(0, gopayLogEntries.value.length - 200)
  }
  scrollGoPayLogToBottom()
}

function rememberGoPayTaskId(taskId) {
  const id = String(taskId || '').trim()
  if (!id) return
  try {
    localStorage.setItem(GOPAY_RECENT_TASK_KEY, id)
  } catch (e) {
    console.error('rememberGoPayTaskId', e)
  }
}

function goPayProgressLogLevel(event) {
  const level = String(event?.level || '').trim()
  if (['info', 'success', 'warn', 'error'].includes(level)) return level
  const stage = String(event?.stage || '')
  if (stage === 'completed' || stage === 'payment_completed' || stage === 'otp_received' || stage === 'gopay_oauth_login_done' || stage === 'gopay_session_cpa_convert_done' || stage === 'gopay_wallet_balance_ready') return 'success'
  if (stage === 'gopay_oauth_login_failed') return 'error'
  if (stage === 'gopay_session_cpa_convert_failed') return 'warn'
  if (stage === 'gopay_wallet_balance_wait' || stage === 'gopay_wallet_balance_not_ready' || stage === 'gopay_wallet_balance_fallback_transfer' || stage === 'gopay_wallet_balance_abandoned' || stage === 'gopay_wallet_balance_check_failed') return 'warn'
  if (stage === 'gopay_wallet_auto_signup_probe_failed') return 'error'
  if (stage === 'gopay_oauth_phone_required_removed' || stage === 'gopay_oauth_phone_required') return 'warn'
  if (stage.includes('network_error')) return 'warn'
  if (stage.includes('not_approved') || stage.includes('blocked') || stage.includes('cooldown') || stage.includes('retry')) return 'warn'
  if (stage === 'failed' || stage.includes('all_accounts')) return 'error'
  return 'info'
}

function goPayProgressWorkerPrefix(event) {
  const rawLabel = String(event?.worker_label || event?.worker || '').trim()
  if (rawLabel) return `[${rawLabel}] `
  const workerIndex = Number(event?.worker_index || 0)
  if (Number.isFinite(workerIndex) && workerIndex > 0) {
    return `[worker-${workerIndex}] `
  }
  return ''
}

function formatGoPayProgressMessage(event) {
  const message = String(event?.message || '').trim()
  if (!message) return ''
  if (/^\[worker-\d+\]\s/.test(message)) return message
  return `${goPayProgressWorkerPrefix(event)}${message}`
}

const goPayWalletSignupFailureStages = new Set([
  'gopay_wallet_no_numbers',
  'gopay_wallet_provider_unavailable',
  'gopay_wallet_network_error',
  'gopay_wallet_rate_limited',
])

function shouldHideGoPayProgressEvent(event) {
  const stage = String(event?.stage || '')
  if (stage === 'gopay_wallet_signup_failed_no_account_retry') return true
  return stage === 'gopay_auto_signup_account_failed'
    && goPayWalletSignupFailureStages.has(String(event?.failure_stage || ''))
}

function processGoPayProgressEvents(task) {
  const events = Array.isArray(task?.progress_events) ? task.progress_events : []
  let printed = 0
  for (const event of events) {
    const eventId = String(event?.event_id || `${event?.updated_at || ''}-${event?.stage || ''}-${event?.message || ''}`)
    if (!eventId || gopayLoggedProgressEventIds.value.has(eventId)) continue
    gopayLoggedProgressEventIds.value.add(eventId)
    if (event?.stage === 'gopay_account_skipped_by_user') {
      gopaySkipping.value = false
    }
    if (event?.stage === 'gopay_account_bound') {
      showGoPaySuccessNotice(event?.email || '')
    }
    if (shouldHideGoPayProgressEvent(event)) continue
    const message = formatGoPayProgressMessage(event)
    if (!message) continue
    pushGoPayLog(message, goPayProgressLogLevel(event))
    printed += 1
  }
  return printed
}

function hydrateGoPayTaskLog(task, restoreMessage = '') {
  if (!task) return
  activeTab.value = 'gopay'
  gopayTask.value = task
  if (isTaskActive(task)) {
    gopayRuntimeConcurrency.value = normalizeGoPayConcurrency(task.params?.gopay_concurrency || task.result?.concurrency || gopayForm.value.gopayConcurrency)
    gopayRuntimeSmsProvider.value = String(task.params?.gopay_auto_signup_sms_provider || task.result?.gopay_auto_signup_sms_provider || gopayForm.value.gopayAutoSignupSmsProvider || 'smscloud')
    gopayRuntimeBalancePollIntervalSeconds.value = normalizeGoPayRuntimeSeconds(task.params?.gopay_balance_poll_interval_seconds, 20, 300)
    gopayRuntimeTransferBalanceWaitSeconds.value = normalizeGoPayRuntimeSeconds(task.params?.gopay_transfer_balance_wait_seconds, 120, 1800)
  }
  rememberGoPayTaskId(task.task_id)
  if (restoreMessage) {
    pushGoPayLog(restoreMessage, 'info')
  }
  if (task.progress?.stage) {
    pushGoPayLog(`执行阶段：${gopayStageLabelMap[task.progress.stage] || task.progress.stage}`, 'info')
  }
  const printed = processGoPayProgressEvents(task)
  if (!printed && task.progress?.message) {
    pushGoPayLog(formatGoPayProgressMessage(task.progress), goPayProgressLogLevel(task.progress))
  }
  if (!isTaskActive(task)) {
    const statusLabel = bindStatusText(task)
    pushGoPayLog(`任务状态：${statusLabel}`, task.status === 'failed' ? 'error' : task.status === 'completed' ? 'success' : task.status === 'cancelled' ? 'warn' : 'info')
    const resultMessage = String(task.result?.message || '').trim()
    if (resultMessage) {
      pushGoPayLog(resultMessage, task.result?.status === 'success' ? 'success' : task.status === 'cancelled' ? 'warn' : 'error')
    }
  }
}

function formatCardOption(card) {
  const content = card?.meta?.content || {}
  const rawNumber = String(content.card_number || card?.value || '')
  const last4 = rawNumber.slice(-4)
  const expiry = String(content.expiry_date || card?.expires_at || '').trim()
  const provider = String(card?.provider || '').trim()
  const parts = [`**** ${last4 || '----'}`]
  if (expiry) parts.push(expiry)
  if (provider) parts.push(provider)
  return parts.join(' / ')
}

function buildBindLinkPayload(accessToken) {
  return buildCheckoutPayload({
    accessToken,
    planType: bindForm.value.planType,
    country: bindForm.value.country,
    teamWorkspaceName: bindForm.value.teamWorkspaceName,
    teamPriceInterval: bindForm.value.teamPriceInterval,
    teamSeatQuantity: bindForm.value.teamSeatQuantity,
  })
}

function resolveGeneratedLink(result) {
  return resolveCheckoutLink(result)
}

function stopBindTaskPolling() {
  if (bindTaskPollTimer) {
    window.clearTimeout(bindTaskPollTimer)
    bindTaskPollTimer = 0
  }
}

function stopGoPayTaskPolling() {
  if (gopayTaskPollTimer) {
    window.clearTimeout(gopayTaskPollTimer)
    gopayTaskPollTimer = 0
  }
}

function stopGoPaySuccessNoticeTimer() {
  if (gopaySuccessNoticeTimer) {
    window.clearTimeout(gopaySuccessNoticeTimer)
    gopaySuccessNoticeTimer = 0
  }
}

async function pollBindTask(taskId) {
  stopBindTaskPolling()
  try {
    const previous = bindTask.value
    const task = await api.getTask(taskId)
    bindTask.value = task
    if (!previous || previous.status !== task.status) {
      pushBindLog(`任务状态更新：${bindTaskStatusLabel.value}`, task.status === 'failed' ? 'error' : task.status === 'completed' ? 'success' : task.status === 'cancelled' ? 'warn' : 'info')
    }
    const previousStage = previous?.progress?.stage || ''
    const nextStage = task?.progress?.stage || ''
    if (nextStage && previousStage !== nextStage && !shouldHideGoPayProgressEvent(task.progress)) {
      pushBindLog(`执行阶段：${nextStage}`, 'info')
    }
    if (['pending', 'running'].includes(task.status)) {
      bindTaskPollTimer = window.setTimeout(() => {
        pollBindTask(taskId)
      }, 3000)
      return
    }
    bindCancelling.value = false
    if (task.result?.message) {
      pushBindLog(task.result.message, task.result?.status === 'success' ? 'success' : task.status === 'cancelled' ? 'warn' : 'error')
    }
    await loadCards()
  } catch (e) {
    pushBindLog(`查询绑卡任务失败: ${e.message}`, 'error')
    setMessage(`查询绑卡任务失败: ${e.message}`, false)
  }
}

async function pollGoPayTask(taskId) {
  stopGoPayTaskPolling()
  try {
    const previous = gopayTask.value
    const task = await api.getTask(taskId)
    gopayTask.value = task
    rememberGoPayTaskId(task.task_id || taskId)
    const statusLabel = task.status === 'pending'
      ? '排队中'
      : task.status === 'running'
        ? '运行中'
        : task.status === 'completed'
          ? '已完成'
          : task.status === 'failed'
            ? '失败'
            : task.status === 'cancelled'
              ? '已取消'
              : task.status
    if (!previous || previous.status !== task.status) {
      pushGoPayLog(`任务状态更新：${statusLabel}`, task.status === 'failed' ? 'error' : task.status === 'completed' ? 'success' : task.status === 'cancelled' ? 'warn' : 'info')
    }
    const previousStage = previous?.progress?.stage || ''
    const nextStage = task?.progress?.stage || ''
    if (nextStage && previousStage !== nextStage && !shouldHideGoPayProgressEvent(task.progress)) {
      pushGoPayLog(`执行阶段：${gopayStageLabelMap[nextStage] || nextStage}`, 'info')
    }
    const printedProgressEvents = processGoPayProgressEvents(task)
    if (['pending', 'running'].includes(task.status)) {
      const previousProgressMessage = formatGoPayProgressMessage(previous?.progress || {})
      const nextProgressMessage = formatGoPayProgressMessage(task?.progress || {})
      if (!shouldHideGoPayProgressEvent(task.progress) && !printedProgressEvents && nextProgressMessage && nextProgressMessage !== previousProgressMessage) {
        pushGoPayLog(nextProgressMessage, nextStage === 'checkout_not_approved_rotate' ? 'warn' : 'info')
      }
      gopayTaskPollTimer = window.setTimeout(() => {
        pollGoPayTask(taskId)
      }, 3000)
      return
    }
    gopayCancelling.value = false
    gopaySkipping.value = false
    const removedPoolEmails = task.result?.removed_pool_emails || []
    const resultMessage = String(task.result?.message || '')
    const paymentNotApproved = /付款.*未获批准|未获批准|payment\s+(?:was\s+)?not\s+approved|payment\s+(?:was\s+)?declined|not\s+approved/i.test(resultMessage)
    if (removedPoolEmails.length) {
      const reason = paymentNotApproved ? '付款未获批准' : (resultMessage || '账号不可用')
      pushGoPayLog(`${reason}，已从号池删除账号: ${removedPoolEmails.join(', ')}`, 'warn')
    }
    if (resultMessage && !(removedPoolEmails.length && paymentNotApproved)) {
      pushGoPayLog(resultMessage, task.result?.status === 'success' ? 'success' : task.status === 'cancelled' ? 'warn' : 'error')
    }
    await loadAccounts()
  } catch (e) {
    pushGoPayLog(`查询 GoPay 任务失败: ${e.message}`, 'error')
    setMessage(`查询 GoPay 任务失败: ${e.message}`, false)
  }
}

function isTaskActive(task) {
  return ['pending', 'running'].includes(task?.status)
}

function bindStatusText(task) {
  if (task?.status === 'pending') return '排队中'
  if (task?.status === 'running') return '运行中'
  if (task?.status === 'completed') return '已完成'
  if (task?.status === 'failed') return '失败'
  if (task?.status === 'cancelled') return '已取消'
  return task?.status || '-'
}

async function restoreActiveBindTasks() {
  try {
    const tasks = await api.getTasks()
    const running = (tasks || []).find(task => isTaskActive(task) && ['bind-card', 'gopay-bind'].includes(task.command))
    const recentGoPay = (tasks || []).find(task => task.command === 'gopay-bind' && isTaskActive(task))
    if (!running) {
      let restored = recentGoPay
      if (!restored) {
        try {
          const savedGoPayTaskId = localStorage.getItem(GOPAY_RECENT_TASK_KEY)
          if (savedGoPayTaskId) {
            const saved = await api.getTask(savedGoPayTaskId)
            if (saved?.command === 'gopay-bind' && isTaskActive(saved)) restored = saved
          }
        } catch {
          restored = null
        }
      }
      if (restored?.command === 'gopay-bind') {
        hydrateGoPayTaskLog(restored, `已恢复最近 GoPay 任务日志：${restored.task_id}`)
      }
      return
    }

    if (running.command === 'gopay-bind') {
      hydrateGoPayTaskLog(running, `已恢复 GoPay 任务轮询：${running.task_id}`)
      await pollGoPayTask(running.task_id)
      return
    }

    activeTab.value = 'bind'
    bindTask.value = running
    pushBindLog(`已恢复绑卡任务轮询：${running.task_id}`, 'info')
    if (running.progress?.stage) {
      pushBindLog(`执行阶段：${running.progress.stage}`, 'info')
    }
    if (running.progress?.message) {
      pushBindLog(running.progress.message, 'info')
    }
    await pollBindTask(running.task_id)
  } catch (e) {
    console.error('restoreActiveBindTasks', e)
  }
}

watch(
  () => bindForm.value.country,
  (country) => {
    bindForm.value.currency = countryCurrencyMap[country] || 'USD'
  },
  { immediate: true }
)

watch(
  () => [
    bindForm.value.planType,
    bindForm.value.country,
    bindForm.value.teamWorkspaceName,
    bindForm.value.teamSeatQuantity,
    bindForm.value.teamPriceInterval,
  ],
  () => {
    if (bindTaskForm.value.checkoutMode !== 'auto') return
    currentLink.value = ''
    checkoutSessionId.value = ''
    rawGeneratedUrl.value = ''
    bindTaskForm.value.checkoutUrl = ''
  }
)

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
  } catch (e) {
    setMessage(`提取 access_token 失败: ${e.message}`, false)
  } finally {
    loadingAccountToken.value = false
  }
}

async function generateLink() {
  if (generating.value) return
  if (!bindForm.value.accessToken) {
    setMessage('请输入 access_token', false)
    return
  }
  generating.value = true
  currentLink.value = ''
  checkoutSessionId.value = ''
  rawGeneratedUrl.value = ''

  try {
    const result = await api.generateBindLink(buildBindLinkPayload(bindForm.value.accessToken))
    const resolved = resolveGeneratedLink(result)

    if (!resolved) {
      const errorMsg = result.detail || JSON.stringify(result)
      setMessage(`生成失败: ${errorMsg}`, false)
      history.value.unshift({
        time: formatDate(),
        plan: bindForm.value.planType.toUpperCase(),
        country: bindForm.value.country,
        currency: bindForm.value.currency,
        link: '',
        error: errorMsg,
        success: false,
      })
      saveHistory()
    } else {
      currentLink.value = resolved.link
      checkoutSessionId.value = resolved.sessionId
      rawGeneratedUrl.value = resolved.rawGeneratedUrl
      bindTaskForm.value.checkoutUrl = resolved.link
      history.value.unshift({
        time: formatDate(),
        plan: bindForm.value.planType.toUpperCase(),
        country: bindForm.value.country,
        currency: bindForm.value.currency,
        link: resolved.link,
        error: '',
        success: true,
      })
      saveHistory()
      setMessage('生成成功！请点击链接或复制到浏览器打开')
    }
  } catch (e) {
    setMessage(`生成失败: ${e.message}`, false)
    history.value.unshift({
      time: formatDate(),
      plan: bindForm.value.planType.toUpperCase(),
      country: bindForm.value.country,
      currency: bindForm.value.currency,
      link: '',
      error: e.message,
      success: false,
    })
    saveHistory()
  } finally {
    generating.value = false
  }
}

async function generateAndOpenWithAuthSession() {
  if (generating.value) return
  if (!selectedAccountEmail.value) {
    setMessage('请先选择号池账号', false)
    return
  }
  generating.value = true
  currentLink.value = ''
  checkoutSessionId.value = ''
  rawGeneratedUrl.value = ''

  try {
    const payload = {
      ...buildBindLinkPayload(bindForm.value.accessToken),
      email: selectedAccountEmail.value,
    }
    const result = await api.openBindLinkWithAuthSession(payload)
    const resolved = resolveGeneratedLink(result)
    if (!resolved) {
      const errorMsg = result.detail || JSON.stringify(result)
      throw new Error(errorMsg)
    }

    currentLink.value = resolved.link
    checkoutSessionId.value = resolved.sessionId
    rawGeneratedUrl.value = resolved.rawGeneratedUrl
    bindTaskForm.value.checkoutUrl = resolved.link
    history.value.unshift({
      time: formatDate(),
      plan: bindForm.value.planType.toUpperCase(),
      country: bindForm.value.country,
      currency: bindForm.value.currency,
      link: resolved.link,
      error: '',
      success: true,
    })
    saveHistory()
    setMessage(`已用 ${selectedAccountEmail.value} 的 auth_session 打开支付页`)
  } catch (e) {
    setMessage(`生成并打开失败: ${e.message}`, false)
    history.value.unshift({
      time: formatDate(),
      plan: bindForm.value.planType.toUpperCase(),
      country: bindForm.value.country,
      currency: bindForm.value.currency,
      link: '',
      error: e.message,
      success: false,
    })
    saveHistory()
  } finally {
    generating.value = false
  }
}

async function ensureBindCheckoutUrl() {
  if (bindTaskForm.value.checkoutMode === 'manual') {
    const manualLink = String(bindTaskForm.value.checkoutUrl || '').trim()
    if (!manualLink) {
      throw new Error('请手动输入 checkout 链接')
    }
    pushBindLog('检测到手动输入支付链接，直接使用该链接', 'info')
    return manualLink
  }

  pushBindLog(`开始为账号 ${selectedAccountEmail.value} 提取 access_token`, 'info')
  const authResult = await api.getCodexAuth(selectedAccountEmail.value)
  const token = authResult?.codex_auth?.tokens?.access_token || ''
  if (!token) {
    throw new Error('对应 auth_session 文件中没有 accessToken')
  }

  bindForm.value.accessToken = token
  pushBindLog(`access_token 提取成功，开始生成 ${bindPlanLabel(bindForm.value.planType)} 支付链接`, 'info')
  const linkResult = await api.generateBindLink(buildBindLinkPayload(token))
  const resolved = resolveGeneratedLink(linkResult)
  if (!resolved?.link) {
    throw new Error(linkResult?.detail || '自动生成支付链接失败')
  }

  currentLink.value = resolved.link
  checkoutSessionId.value = resolved.sessionId
  rawGeneratedUrl.value = resolved.rawGeneratedUrl
  bindTaskForm.value.checkoutUrl = resolved.link
  pushBindLog('支付链接生成成功', 'success')
  return resolved.link
}

async function startBindCard() {
  if (bindSubmitting.value || bindTaskRunning.value) return
  if (!selectedAccountEmail.value) {
    setMessage('请先选择号池账号', false)
    return
  }
  if (!bindTaskForm.value.cardItemId) {
    setMessage('请选择一张未使用卡', false)
    return
  }

  bindSubmitting.value = true
  bindLogEntries.value = []
  pushBindLog('准备提交绑卡任务', 'info')
  try {
    const checkoutUrl = await ensureBindCheckoutUrl()
    const task = await api.startBindCard({
      email: selectedAccountEmail.value,
      card_item_id: bindTaskForm.value.cardItemId,
      checkout_url: checkoutUrl,
      proxy_api_provider: bindTaskForm.value.proxyApiEnabled ? 'cliproxy' : '',
      proxy_api_country: bindTaskForm.value.proxyApiEnabled
        ? (String(bindTaskForm.value.proxyApiCountry || 'US').trim().toUpperCase() || 'US')
        : '',
      proxy_api_url: bindTaskForm.value.proxyApiEnabled ? String(bindTaskForm.value.proxyApiUrl || '').trim() : '',
      manual_confirm: false,
    })
    bindTask.value = task
    pushBindLog(`绑卡任务已提交，任务 ID: ${task.task_id}`, 'success')
    setMessage(`绑卡任务已提交: ${task.task_id}`)
    await loadCards()
    await pollBindTask(task.task_id)
  } catch (e) {
    pushBindLog(`提交绑卡任务失败: ${e.message}`, 'error')
    setMessage(`提交绑卡任务失败: ${e.message}`, false)
  } finally {
    bindSubmitting.value = false
  }
}

async function cancelBindTask() {
  if (!bindTaskRunning.value || bindCancelling.value) return
  bindCancelling.value = true
  pushBindLog('已发起取消请求，正在停止提交新步骤并打断可中断等待', 'warn')
  try {
    const result = await api.cancelTask()
    if (result?.message) {
      pushBindLog(result.message, 'warn')
    }
    setMessage(result?.message || '已请求取消当前任务')
  } catch (e) {
    pushBindLog(`取消任务失败: ${e.message}`, 'error')
    setMessage(`取消任务失败: ${e.message}`, false)
  } finally {
    bindCancelling.value = false
  }
}

async function startGoPayBind() {
  if (gopaySubmitting.value || gopayTaskRunning.value) return
  normalizeGoPayPhoneFields({ forceLocal: true })
  saveGoPayFormState()
  if (!gopayCanSubmit.value) {
    setMessage('请填写完整的 GoPay 参数', false)
    return
  }

  gopaySubmitting.value = true
  gopayLogEntries.value = []
  gopayLoggedProgressEventIds.value = new Set()
  gopayLoggedMessages.value = new Set()
  pushGoPayLog(
    gopayForm.value.autoRegister
      ? `准备提交自动注册并 GoPay 绑定任务，共 ${normalizedGoPayAutoRegisterCount.value} 个账号`
      : gopayBatchActive.value
        ? `准备提交批量 GoPay 任务，共 ${gopaySelectedBatchEmails.value.length} 个账号，并发 ${normalizedGoPayConcurrency.value}`
        : '准备提交 GoPay 任务',
    'info'
  )
  try {
    const useAutoSignup = gopayAutoSignupEnabled.value
    const effectiveOtpChannel = useAutoSignup ? 'sms' : gopayOtpChannel.value
    const effectiveSmsUrl = useAutoSignup || effectiveOtpChannel === 'whatsapp' ? '' : gopayForm.value.smsUrl
    const effectivePhoneAccounts = useAutoSignup
      ? []
      : gopayActivePhoneAccounts.value.map(account => ({
        ...account,
        otp_channel: effectiveOtpChannel,
        sms_url: effectiveOtpChannel === 'whatsapp' ? '' : account.sms_url,
      }))
    if (!useAutoSignup && gopayUsingWhatsAppOtp.value) {
      await startWhatsAppOtpListener()
      pushGoPayLog('OTP 来源已切换为 WhatsApp，本次任务不会触发 GoPay SMS OTP', 'info')
    }
    if (useAutoSignup && !gopayAutoSignupProviderConfigured.value) {
      throw new Error(gopayAutoSignupMissingMessage.value)
    }
    if (gopayForm.value.proxyPoolEnabled && !gopayProxyPoolEntries.value.length) {
      throw new Error('启用动态代理池后需要先配置代理')
    }
    if (gopayForm.value.proxyApiEnabled && !['1024proxy', 'cliproxy'].includes(String(gopayForm.value.proxyApiProvider || ''))) {
      throw new Error('代理 API 供应商暂只支持 1024proxy 或 Cliproxy')
    }
    const autoSignupCfg = gopayAutoSignupConfig.value || {}
    const autoSignupMode = useAutoSignup
      ? (String(gopayForm.value.gopayAutoSignupMode || 'http').trim().toLowerCase() === 'appium' ? 'appium' : 'http')
      : 'http'
    const appiumUrl = useAutoSignup ? String(autoSignupCfg.appium_url || '').trim() : ''
    const appiumAdbSerial = useAutoSignup ? String(autoSignupCfg.appium_adb_serial || '').trim() : ''
    const task = await api.startGoPayBind({
      email: gopayEffectiveEmail.value,
      account_emails: gopayBatchActive.value ? gopaySelectedBatchEmails.value : [],
      auto_register: Boolean(gopayForm.value.autoRegister),
      auto_register_count: normalizedGoPayAutoRegisterCount.value,
      auto_register_protocol: Boolean(gopayForm.value.autoRegisterProtocol),
      gopay_auto_signup: useAutoSignup,
      gopay_auto_signup_sms_provider: useAutoSignup ? gopayAutoSignupProvider.value : 'smscloud',
      gopay_auto_signup_mode: autoSignupMode,
      gopay_appium_url: appiumUrl,
      gopay_appium_adb_serial: appiumAdbSerial,
      gopay_auto_signup_hero_sms_api_key: '',
      gopay_auto_signup_hero_sms_base_url: useAutoSignup && gopayAutoSignupProvider.value === 'hero_sms'
        ? String(gopayForm.value.gopayAutoSignupHeroSmsBaseUrl || autoSignupCfg.hero_sms_base_url || '').trim()
        : '',
      gopay_auto_signup_hero_sms_country: useAutoSignup && gopayAutoSignupProvider.value === 'hero_sms'
        ? String(gopayForm.value.gopayAutoSignupHeroSmsCountry || autoSignupCfg.hero_sms_country || '').trim()
        : '',
      gopay_auto_signup_hero_sms_service: useAutoSignup && gopayAutoSignupProvider.value === 'hero_sms'
        ? String(gopayForm.value.gopayAutoSignupHeroSmsService || autoSignupCfg.hero_sms_service || '').trim()
        : '',
      gopay_auto_signup_hero_sms_timeout: '',
      gopay_auto_signup_hero_sms_min_price: useAutoSignup && gopayAutoSignupProvider.value === 'hero_sms'
        ? String(gopayForm.value.gopayAutoSignupHeroSmsMinPrice || '').trim()
        : '',
      gopay_auto_signup_hero_sms_max_price: useAutoSignup && gopayAutoSignupProvider.value === 'hero_sms'
        ? String(gopayForm.value.gopayAutoSignupHeroSmsMaxPrice || '').trim()
        : '',
      gopay_auto_signup_hero_sms_preferred_price: useAutoSignup && gopayAutoSignupProvider.value === 'hero_sms'
        ? String(gopayForm.value.gopayAutoSignupHeroSmsPreferredPrice || '').trim()
        : '',
      gopay_auto_signup_smsbower_api_key: '',
      gopay_auto_signup_smsbower_base_url: useAutoSignup && gopayAutoSignupProvider.value === 'smsbower'
        ? String(gopayForm.value.gopayAutoSignupSmsbowerBaseUrl || autoSignupCfg.smsbower_base_url || '').trim()
        : '',
      gopay_auto_signup_smsbower_country: useAutoSignup && gopayAutoSignupProvider.value === 'smsbower'
        ? String(gopayForm.value.gopayAutoSignupSmsbowerCountry || autoSignupCfg.smsbower_country || '').trim()
        : '',
      gopay_auto_signup_smsbower_service: useAutoSignup && gopayAutoSignupProvider.value === 'smsbower'
        ? String(gopayForm.value.gopayAutoSignupSmsbowerService || autoSignupCfg.smsbower_service || '').trim()
        : '',
      gopay_auto_signup_smsbower_min_price: useAutoSignup && gopayAutoSignupProvider.value === 'smsbower'
        ? String(gopayForm.value.gopayAutoSignupSmsbowerMinPrice || autoSignupCfg.smsbower_min_price || '').trim()
        : '',
      gopay_auto_signup_smsbower_max_price: useAutoSignup && gopayAutoSignupProvider.value === 'smsbower'
        ? String(gopayForm.value.gopayAutoSignupSmsbowerMaxPrice || autoSignupCfg.smsbower_max_price || '').trim()
        : '',
      gopay_auto_signup_smsbower_preferred_price: useAutoSignup && gopayAutoSignupProvider.value === 'smsbower'
        ? String(gopayForm.value.gopayAutoSignupSmsbowerPreferredPrice || autoSignupCfg.smsbower_preferred_price || '').trim()
        : '',
      gopay_auto_signup_smsbower_timeout: '',
      gopay_auto_signup_smscloud_base_url: '',
      gopay_auto_signup_smscloud_country: '',
      gopay_auto_signup_smscloud_service: '',
      gopay_auto_signup_smscloud_max_price: '',
      gopay_auto_signup_smscloud_timeout: '',
      gopay_auto_signup_smscode_api_token: '',
      gopay_auto_signup_smscode_base_url: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodeBaseUrl || autoSignupCfg.smscode_base_url || '').trim()
        : '',
      gopay_auto_signup_smscode_country_id: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodeCountryId || autoSignupCfg.smscode_country_id || '').trim()
        : '',
      gopay_auto_signup_smscode_platform_id: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodePlatformId || autoSignupCfg.smscode_platform_id || '').trim()
        : '',
      gopay_auto_signup_smscode_platform_query: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodePlatformQuery || autoSignupCfg.smscode_platform_query || '').trim()
        : '',
      gopay_auto_signup_smscode_product_id: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodeProductId || autoSignupCfg.smscode_product_id || '').trim()
        : '',
      gopay_auto_signup_smscode_min_price: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodeMinPrice || autoSignupCfg.smscode_min_price || '').trim()
        : '',
      gopay_auto_signup_smscode_max_price: useAutoSignup && gopayAutoSignupProvider.value === 'smscode'
        ? String(gopayForm.value.gopayAutoSignupSmscodeMaxPrice || autoSignupCfg.smscode_max_price || '').trim()
        : '',
      gopay_auto_signup_smscode_timeout: '',
      gopay_balance_wait_fallback_transfer: useAutoSignup
        && !rekberinajaTransferEnabled.value
        && Boolean(gopayForm.value.gopayBalanceWaitFallbackTransfer),
      auto_register_mail_provider: gopayForm.value.autoRegisterMailProvider || null,
      auto_register_luckmail_email_type: gopayAutoRegisterUsesLuckMail.value ? (gopayForm.value.autoRegisterLuckmailEmailType || 'ms_imap') : null,
      auto_register_luckmail_preferred_domain: gopayAutoRegisterUsesLuckMail.value ? gopayForm.value.autoRegisterLuckmailPreferredDomain : null,
      auto_register_luckmail_preferred_domains: gopayAutoRegisterUsesLuckMail.value ? gopayForm.value.autoRegisterLuckmailPreferredDomains : [],
      auto_register_domain: gopayAutoRegisterUsesDomains.value ? (gopaySelectedAutoRegisterDomains.value[0] || '') : '',
      auto_register_domains: gopayAutoRegisterUsesDomains.value ? gopaySelectedAutoRegisterDomains.value : [],
      auto_register_prefix: String(gopayForm.value.autoRegisterPrefix || '').trim(),
      auto_register_password: String(gopayForm.value.autoRegisterPassword || '').trim(),
      checkout_url: gopayForm.value.checkoutUrl || '',
      checkout_ui_mode: gopayForm.value.checkoutUiMode === 'hosted' ? 'hosted' : 'custom',
      country_code: useAutoSignup ? '62' : (gopayForm.value.countryCode || ''),
      phone_number: useAutoSignup ? '' : gopayForm.value.phoneNumber,
      phone_accounts: effectivePhoneAccounts,
      otp_channel: effectiveOtpChannel,
      sms_url: effectiveSmsUrl,
      gopay_pin: gopayForm.value.gopayPin,
      proxy_url: (!gopayForm.value.proxyPoolEnabled && !gopayForm.value.proxyApiEnabled) ? (gopayForm.value.proxyUrl || null) : null,
      proxy_pool_text: gopayForm.value.proxyPoolEnabled && !gopayForm.value.proxyApiEnabled ? gopayForm.value.proxyPoolText : '',
      proxy_api_provider: gopayForm.value.proxyApiEnabled ? gopayForm.value.proxyApiProvider : '',
      proxy_api_url: gopayForm.value.proxyApiEnabled && gopayForm.value.proxyApiProvider === 'cliproxy'
        ? 'https://api.cliproxy.io/white/api?region=ID&num=1&time=30&format=n&type=txt'
        : '',
      proxy_label: gopayForm.value.proxyLabel,
      delete_rejected_accounts: Boolean(gopayForm.value.deleteRejectedAccounts),
      auto_oauth_after_success: Boolean(gopayForm.value.autoOauthAfterSuccess),
      pending_retry_attempts: normalizedGoPayPendingRetryAttempts.value,
      gopay_concurrency: normalizedGoPayConcurrency.value,
    })
    gopayTask.value = task
    gopayRuntimeConcurrency.value = normalizedGoPayConcurrency.value
    gopayRuntimeSmsProvider.value = gopayAutoSignupProvider.value
    gopayRuntimeBalancePollIntervalSeconds.value = normalizeGoPayRuntimeSeconds(task.params?.gopay_balance_poll_interval_seconds, 20, 300)
    gopayRuntimeTransferBalanceWaitSeconds.value = normalizeGoPayRuntimeSeconds(task.params?.gopay_transfer_balance_wait_seconds, 120, 1800)
    gopayRuntimeAppendEmails.value = []
    rememberGoPayTaskId(task.task_id)
    pushGoPayLog(`GoPay 任务已提交，任务 ID: ${task.task_id}`, 'success')
    setMessage(`GoPay 任务已提交: ${task.task_id}`)
    await pollGoPayTask(task.task_id)
    emit('refresh')
  } catch (e) {
    pushGoPayLog(`提交 GoPay 任务失败: ${e.message}`, 'error')
    setMessage(`提交 GoPay 任务失败: ${e.message}`, false)
    emit('refresh')
  } finally {
    gopaySubmitting.value = false
  }
}

async function cancelGoPayTask() {
  if (!gopayTaskRunning.value || gopayCancelling.value) return
  gopayCancelling.value = true
  pushGoPayLog('已发起取消请求，正在停止提交新账号并打断可中断等待', 'warn')
  try {
    const result = await api.cancelTask()
    if (result?.message) {
      pushGoPayLog(result.message, 'warn')
    }
    setMessage(result?.message || '已请求取消当前任务')
  } catch (e) {
    pushGoPayLog(`取消 GoPay 任务失败: ${e.message}`, 'error')
    setMessage(`取消 GoPay 任务失败: ${e.message}`, false)
  } finally {
    gopayCancelling.value = false
  }
}

async function skipGoPayCurrentAccount() {
  if (!gopayTaskRunning.value || gopaySkipping.value || !gopaySkipAvailable.value) return
  gopaySkipping.value = true
  pushGoPayLog('已请求跳过当前账号，等待当前步骤退出后切换下一个账号', 'warn')
  try {
    const result = await api.skipCurrentTask()
    if (result?.message) {
      pushGoPayLog(result.message, 'warn')
    }
    setMessage(result?.message || '已请求跳过当前账号')
  } catch (e) {
    pushGoPayLog(`跳过当前账号失败: ${e.message}`, 'error')
    setMessage(`跳过当前账号失败: ${e.message}`, false)
    gopaySkipping.value = false
  }
}

async function applyGoPayRuntimeControl() {
  if (!gopayTaskRunning.value || gopayRuntimeUpdating.value) return
  const accountEmails = normalizeEmailList(gopayRuntimeAppendEmails.value)
  gopayRuntimeUpdating.value = true
  try {
    const result = await api.updateGoPayRuntimeControl({
      task_id: gopayTask.value?.task_id || '',
      gopay_concurrency: normalizeGoPayConcurrency(gopayRuntimeConcurrency.value),
      gopay_auto_signup_sms_provider: gopayRuntimeSmsProvider.value,
      gopay_balance_poll_interval_seconds: normalizeGoPayRuntimeSeconds(gopayRuntimeBalancePollIntervalSeconds.value, 20, 300),
      gopay_transfer_balance_wait_seconds: normalizeGoPayRuntimeSeconds(gopayRuntimeTransferBalanceWaitSeconds.value, 120, 1800),
      account_emails: accountEmails,
    })
    const updates = result?.updates || {}
    if (updates.added_account_emails?.length) {
      gopayRuntimeAppendEmails.value = []
    }
    pushGoPayLog(result?.message || 'GoPay 热切换已应用', 'success')
    setMessage(result?.message || 'GoPay 热切换已应用')
  } catch (e) {
    pushGoPayLog(`GoPay 热切换失败: ${e.message}`, 'error')
    setMessage(`GoPay 热切换失败: ${e.message}`, false)
  } finally {
    gopayRuntimeUpdating.value = false
  }
}

function copyCurrentLink() {
  if (currentLink.value) {
    navigator.clipboard.writeText(currentLink.value)
    setMessage('链接已复制到剪贴板')
  }
}

function openLink() {
  if (currentLink.value) {
    window.open(currentLink.value, '_blank')
  }
}

function openBackupLink() {
  if (checkoutSessionId.value) {
    const link = bindForm.value.planType === 'team'
      ? `https://chatgpt.com/checkout/openai_ie/${checkoutSessionId.value}`
      : `https://chatgpt.com/checkout/openai_llc/${checkoutSessionId.value}`
    window.open(link, '_blank')
  }
}

function openHistoryLink(link) {
  if (link) {
    window.open(link, '_blank')
  }
}

onMounted(() => {
  loadHistory()
  loadChatGPTBindFormState()
  const restoredGoPayForm = loadGoPayFormState()
  loadGoPayAutoSignupConfig({ applyDefaults: !restoredGoPayForm })
  loadGoPayRekberinajaConfig()
  if (gopayUsingWhatsAppOtp.value) {
    refreshWhatsAppOtpStatus()
  }
  if (gopayForm.value.autoRegister) {
    loadGoPayAutoRegisterMailProviders()
    loadGoPayAutoRegisterDomains()
  }
  loadAccounts()
  loadCards()
  restoreActiveBindTasks()
})

onUnmounted(() => {
  stopBindTaskPolling()
  stopGoPayTaskPolling()
  stopGoPaySuccessNoticeTimer()
})

watch(activeTab, (tab) => {
  if (tab !== 'gopay') {
    gopayAutoRegisterConfigOpen.value = false
    gopayPhonePoolConfigOpen.value = false
  }
  if (tab === 'generate' || tab === 'bind' || tab === 'gopay') {
    loadAccounts()
    loadCards()
  }
})

watch(
  () => gopayForm.value.otpChannel,
  (channel) => {
    gopayForm.value.otpChannel = channel === 'whatsapp' ? 'whatsapp' : 'sms'
    if (gopayForm.value.otpChannel === 'whatsapp') {
      refreshWhatsAppOtpStatus()
    }
    saveGoPayFormState()
  }
)
</script>

<style scoped>
.link-panel::-webkit-scrollbar {
  display: none;
}

.link-panel [style*="overflow-x-auto"]::-webkit-scrollbar {
  display: none;
}
</style>
