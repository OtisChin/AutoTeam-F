<template>
  <div>
    <h2 class="text-xl font-bold text-white mb-2">自助绑卡服务</h2>
    <p class="text-sm text-gray-400 mb-6">
      支持生成官方优惠链接，visa卡池管理，以及一键绑卡服务。
    </p>

    <div class="flex flex-wrap gap-2 mb-6">
      <button
        @click="activeTab = 'bind'"
        class="px-4 py-2 rounded-lg text-sm border transition"
        :class="activeTab === 'bind'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
        自动绑卡
      </button>
      <button
        @click="activeTab = 'generate'"
        class="px-4 py-2 rounded-lg text-sm border transition"
        :class="activeTab === 'generate'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
        生成支付链接
      </button>
      <button
        @click="activeTab = 'pool'"
        class="px-4 py-2 rounded-lg text-sm border transition"
        :class="activeTab === 'pool'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
        卡池
      </button>
      <button
        @click="activeTab = 'gopay'"
        class="px-4 py-2 rounded-lg text-sm border transition"
        :class="activeTab === 'gopay'
          ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
          : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
        GoPay
      </button>
    </div>

    <div v-if="activeTab === 'generate'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
      <div class="flex items-start justify-between gap-4 flex-wrap mb-4">
        <div>
          <h3 class="text-lg font-semibold text-white">生成支付链接</h3>
          <p class="text-sm text-gray-400 mt-1">
            选择套餐类型和优惠活动，系统将生成官方绑卡链接。
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
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="bindForm.planType = 'plus'"
                :disabled="generating"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="bindForm.planType === 'plus'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                Plus
              </button>
              <button
                @click="bindForm.planType = 'team'"
                :disabled="generating"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="bindForm.planType === 'team'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                Team
              </button>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">{{ bindForm.planType === 'team' ? '优惠码' : '优惠活动' }}</label>
            <template v-if="bindForm.planType === 'team'">
              <input
                v-model.trim="bindForm.teamPromoCode"
                :disabled="generating"
                type="text"
                placeholder="例如 STRIPEPERKSGPT4BIZ"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </template>
            <select
              v-else
              v-model="bindForm.promoId"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="promo in filteredPromoOptions" :key="promo.id" :value="promo.id">
                {{ promo.name }}
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
              <option value="US">美国 (US)</option>
              <option value="GB">英国 (GB)</option>
              <option value="DE">德国 (DE)</option>
              <option value="FR">法国 (FR)</option>
              <option value="CA">加拿大 (CA)</option>
              <option value="AU">澳大利亚 (AU)</option>
              <option value="JP">日本 (JP)</option>
              <option value="SG">新加坡 (SG)</option>
              <option value="HK">香港 (HK)</option>
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
              <div>
                <label class="block text-sm text-gray-400 mb-1">取消回跳地址</label>
                <input
                  v-model.trim="bindForm.teamCancelUrl"
                  :disabled="generating"
                  type="text"
                  placeholder="https://chatgpt.com/?promoCode=..."
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </div>
            </div>
          </template>

          <div>
            <label class="block text-sm text-gray-400 mb-1">支付模式</label>
            <select
              v-model="bindForm.checkoutMode"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-if="bindForm.planType !== 'team'" value="custom">代付短链接（站内支付，推荐）</option>
              <option value="hosted">托管模式（Stripe 外部页面）</option>
            </select>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>套餐：<span class="text-gray-200">{{ bindForm.planType === 'plus' ? 'ChatGPT Plus' : 'ChatGPT Team' }}</span></div>
            <div>优惠：<span class="text-gray-200">{{ selectedPromoName }}</span></div>
            <div>国家：<span class="text-gray-200">{{ bindForm.country }}</span> / 货币：<span class="text-gray-200">{{ bindForm.currency }}</span></div>
            <div>支付模式：<span class="text-gray-200">{{ bindForm.checkoutMode === 'custom' ? '代付短链接（站内支付，推荐）' : '托管模式（Stripe 外部页面）' }}</span></div>
            <template v-if="bindForm.planType === 'team'">
              <div>工作区：<span class="text-gray-200">{{ bindForm.teamWorkspaceName || '-' }}</span></div>
              <div>席位 / 周期：<span class="text-gray-200">{{ bindForm.teamSeatQuantity || 2 }} / {{ bindForm.teamPriceInterval }}</span></div>
            </template>
          </div>

        </div>

        <div class="min-w-0 min-h-0 space-y-4">
          <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 h-[270px] flex flex-col">
            <div class="mb-3 flex items-start justify-between gap-3">
              <div>
                <h3 class="text-white font-semibold">Access Token</h3>
                <div class="text-xs text-gray-500 mt-0.5">输入 ChatGPT access_token</div>
              </div>
              <button
                @click="generateLink"
                :disabled="generating || !bindForm.accessToken"
                class="shrink-0 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm rounded-lg transition disabled:opacity-50">
                {{ generating ? '生成中...' : '生成绑卡链接' }}
              </button>
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
        <h3 class="text-lg font-semibold text-white">自动绑卡</h3>
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
              <div class="grid grid-cols-2 gap-2">
                <button
                  @click="bindForm.planType = 'plus'"
                  :disabled="bindSubmitting || bindTaskRunning"
                  class="px-4 py-2 rounded-lg text-sm border transition"
                  :class="bindForm.planType === 'plus'
                    ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                    : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                  Plus
                </button>
                <button
                  @click="bindForm.planType = 'team'"
                  :disabled="bindSubmitting || bindTaskRunning"
                  class="px-4 py-2 rounded-lg text-sm border transition"
                  :class="bindForm.planType === 'team'
                    ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                    : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                  Team
                </button>
              </div>
            </div>

            <div>
              <label class="block text-sm text-gray-400 mb-1">{{ bindForm.planType === 'team' ? '优惠码' : '优惠活动' }}</label>
              <template v-if="bindForm.planType === 'team'">
                <input
                  v-model.trim="bindForm.teamPromoCode"
                  :disabled="bindSubmitting || bindTaskRunning"
                  type="text"
                  placeholder="例如 STRIPEPERKSGPT4BIZ"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                />
              </template>
              <select
                v-else
                v-model="bindForm.promoId"
                :disabled="bindSubmitting || bindTaskRunning"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-for="promo in filteredPromoOptions" :key="promo.id" :value="promo.id">
                  {{ promo.name }}
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
                <option value="US">美国 (US)</option>
                <option value="GB">英国 (GB)</option>
                <option value="DE">德国 (DE)</option>
                <option value="FR">法国 (FR)</option>
                <option value="CA">加拿大 (CA)</option>
                <option value="AU">澳大利亚 (AU)</option>
                <option value="JP">日本 (JP)</option>
                <option value="SG">新加坡 (SG)</option>
                <option value="HK">香港 (HK)</option>
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
                <div>
                  <label class="block text-sm text-gray-400 mb-1">取消回跳地址</label>
                  <input
                    v-model.trim="bindForm.teamCancelUrl"
                    :disabled="bindSubmitting || bindTaskRunning"
                    type="text"
                    placeholder="https://chatgpt.com/?promoCode=..."
                    class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                  />
                </div>
              </div>
            </template>

            <div>
              <label class="block text-sm text-gray-400 mb-1">支付模式</label>
              <select
                v-model="bindForm.checkoutMode"
                :disabled="bindSubmitting || bindTaskRunning"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-if="bindForm.planType !== 'team'" value="custom">代付短链接（站内支付，推荐）</option>
                <option value="hosted">托管模式（Stripe 外部页面）</option>
              </select>
            </div>
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

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">代理标签</label>
              <input
                v-model.trim="bindTaskForm.proxyLabel"
                type="text"
                :disabled="bindSubmitting || bindTaskRunning"
                placeholder="例如 res-us-01"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">代理 URL</label>
              <input
                v-model.trim="bindTaskForm.proxyUrl"
                type="text"
                :disabled="bindSubmitting || bindTaskRunning"
                placeholder="socks5://user:pass@host:port"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <label class="flex items-center gap-2 text-sm text-gray-300">
            <input v-model="bindTaskForm.manualConfirm" type="checkbox" class="accent-blue-500" />
            打开页面后由人工确认最终支付状态
          </label>
          <div class="text-xs text-amber-300/90">
            远程服务器或 Docker 部署通常无法直接操作 Playwright 浏览器，默认建议关闭该选项走自动提交。
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>账号：<span class="text-gray-200">{{ selectedAccountEmail || '-' }}</span></div>
            <div>卡片：<span class="text-gray-200">{{ selectedCardLabel || '-' }}</span></div>
            <div>链接模式：<span class="text-gray-200">{{ bindTaskForm.checkoutMode === 'auto' ? '自动生成' : '手动添加' }}</span></div>
            <div>链接：<span class="text-gray-200 break-all">{{ effectiveCheckoutUrl || '-' }}</span></div>
            <div>代理：<span class="text-gray-200">{{ bindTaskForm.proxyLabel || '-' }}</span></div>
            <div>模式：<span class="text-gray-200">{{ bindTaskForm.manualConfirm ? '人工确认' : '自动提交' }}</span></div>
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

    <BindCardPool v-else-if="activeTab === 'pool'" />

    <div v-else-if="activeTab === 'gopay'" class="bg-gray-900 border border-gray-800 rounded-xl p-4 mb-6">
      <div class="mb-4">
        <h3 class="text-lg font-semibold text-white">GoPay</h3>
        <p class="text-sm text-gray-400 mt-1">
          走印尼区 GoPay 支付链路，自动处理 OTP、短信验证码和 PIN 提交。
        </p>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[420px_minmax(0,1fr)] gap-4">
        <div class="space-y-3">
          <div>
            <div class="flex items-center justify-between gap-3 mb-1">
              <label class="block text-sm text-gray-400">号池账号</label>
              <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                <input
                  v-model="gopayForm.batchMode"
                  type="checkbox"
                  :disabled="gopaySubmitting || gopayTaskRunning || Boolean(gopayForm.checkoutUrl)"
                  class="accent-blue-500"
                />
                批量绑定
              </label>
            </div>
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
            <select
              v-if="gopayForm.batchMode && !gopayForm.checkoutUrl"
              v-model="gopayForm.accountEmails"
              multiple
              size="6"
              :disabled="gopaySubmitting || gopayTaskRunning || loadingAccounts"
              class="mt-2 w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="account in filteredGoPayAccountOptions" :key="`batch-${account.email}`" :value="account.email">
                {{ account.email }}
              </option>
            </select>
            <div v-if="gopayForm.batchMode && !gopayForm.checkoutUrl" class="mt-1 text-xs text-gray-500">
              已选择 {{ gopaySelectedBatchEmails.length }} 个账号；仅在 ChatGPT approve 返回 blocked 时切换下一个。
            </div>
            <div v-if="gopayForm.checkoutUrl" class="mt-1 text-xs text-gray-500">
              已输入 checkout 链接，任务会固定使用当前账号。
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">Checkout 链接</label>
            <input
              v-model.trim="gopayForm.checkoutUrl"
              type="text"
              :disabled="gopaySubmitting || gopayTaskRunning"
              placeholder="可留空；也可粘贴 ChatGPT checkout、pm-redirects 或 Midtrans snap 链接"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="grid grid-cols-1 md:grid-cols-[120px_minmax(0,1fr)_minmax(0,1fr)] gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">国家区号</label>
              <input
                v-model.trim="gopayForm.countryCode"
                type="text"
                :disabled="gopaySubmitting || gopayTaskRunning"
                placeholder="62"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">GoPay 手机号</label>
              <input
                v-model.trim="gopayForm.phoneNumber"
                type="text"
                :disabled="gopaySubmitting || gopayTaskRunning"
                placeholder="+6287761973970"
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

          <div>
            <label class="block text-sm text-gray-400 mb-1">短信接口 Token / URL</label>
            <input
              v-model.trim="gopayForm.smsUrl"
              type="text"
              :disabled="gopaySubmitting || gopayTaskRunning"
              placeholder="https://it.tgflare.com/api/record?token=..."
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

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

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>账号：<span class="text-gray-200">{{ gopayEffectiveEmail || '-' }}</span></div>
            <div>批量：<span class="text-gray-200">{{ gopayBatchActive ? `${gopaySelectedBatchEmails.length} 个账号` : '关闭' }}</span></div>
            <div>国家区号：<span class="text-gray-200">{{ gopayForm.countryCode || '62' }}</span></div>
            <div>手机号：<span class="text-gray-200">{{ gopayForm.phoneNumber || '-' }}</span></div>
            <div>OTP 接口：<span class="text-gray-200 break-all">{{ gopayForm.smsUrl || '-' }}</span></div>
            <div>链接：<span class="text-gray-200 break-all">{{ gopayForm.checkoutUrl || '留空自动生成' }}</span></div>
            <div>代理：<span class="text-gray-200">{{ gopayForm.proxyLabel || '-' }}</span></div>
            <div>账单地址：<span class="text-gray-200">运行任务时自动生成并填写</span></div>
          </div>

          <button
            @click="startGoPayBind"
            :disabled="gopaySubmitting || gopayTaskRunning || !gopayCanSubmit"
            class="w-full px-4 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50">
            {{ gopaySubmitting ? '提交中...' : gopayTaskRunning ? '任务运行中...' : (gopayBatchActive ? '开始批量 GoPay 绑卡' : '开始 GoPay 绑卡') }}
          </button>
          <button
            v-if="gopayTaskRunning"
            @click="cancelGoPayTask"
            :disabled="gopayCancelling"
            class="w-full px-4 py-2 rounded-lg text-sm border bg-red-600/15 hover:bg-red-600/25 text-red-300 border-red-500/30 transition disabled:opacity-50">
            {{ gopayCancelling ? '取消中...' : '取消任务' }}
          </button>
        </div>

        <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 min-w-0 flex flex-col">
          <div class="flex items-center justify-between gap-3 mb-3">
            <div class="text-sm text-gray-400">实时 GoPay 日志</div>
            <div v-if="gopayTask" class="text-xs text-gray-500 font-mono">
              {{ gopayTask.task_id }}
            </div>
          </div>
          <div class="rounded-lg border border-gray-800 bg-gray-900 p-3 flex-1 min-h-[420px] overflow-y-auto space-y-2">
            <div v-if="!gopayLogEntries.length" class="text-sm text-gray-500">
              尚未提交 GoPay 任务。
            </div>
            <div
              v-for="entry in gopayLogEntries"
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
          <div class="mt-2 text-sm text-gray-200">{{ item.plan }} / {{ item.promo }}</div>
          <div v-if="item.link" class="mt-2 text-xs text-blue-400 truncate cursor-pointer hover:text-blue-300" @click="openHistoryLink(item.link)">
            {{ item.link }}
          </div>
          <div v-if="item.error" class="mt-2 text-xs text-red-400">
            {{ item.error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'
import BindCardPool from './BindCardPool.vue'

const BIND_HISTORY_KEY = 'autoteam_bind_history_v1'

const activeTab = ref('bind')
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
const gopayForm = ref({
  email: '',
  batchMode: false,
  accountEmails: [],
  checkoutUrl: '',
  countryCode: '62',
  phoneNumber: '+6287761973970',
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
})
const gopayAccountSearchKeyword = ref('')
const gopaySubmitting = ref(false)
const gopayCancelling = ref(false)
const gopayTask = ref(null)
const gopayLogEntries = ref([])
let bindTaskPollTimer = 0
let gopayTaskPollTimer = 0

const bindForm = ref({
  accessToken: '',
  planType: 'plus',
  promoId: 'plus-1-month-free',
  country: 'SG',
  currency: 'SGD',
  checkoutMode: 'custom',
  teamWorkspaceName: '我的团队',
  teamSeatQuantity: 2,
  teamPriceInterval: 'month',
  teamPromoCode: 'STRIPEPERKSGPT4BIZ',
  teamCancelUrl: 'https://chatgpt.com/?promoCode=STRIPEPERKSGPT4BIZ',
})

const bindTaskForm = ref({
  checkoutMode: 'auto',
  cardItemId: '',
  checkoutUrl: '',
  proxyLabel: '',
  proxyUrl: '',
  manualConfirm: false,
})

const countryCurrencyMap = {
  US: 'USD',
  GB: 'GBP',
  DE: 'EUR',
  FR: 'EUR',
  CA: 'CAD',
  AU: 'AUD',
  JP: 'JPY',
  SG: 'SGD',
  HK: 'HKD',
}

const promoOptions = [
  { id: 'plus-1-month-free', name: 'Plus 1个月免费试用', plan: 'plus' },
]

const filteredPromoOptions = computed(() => {
  return promoOptions.filter(p => p.plan === bindForm.value.planType)
})

const selectedPromoName = computed(() => {
  if (bindForm.value.planType === 'team') {
    return bindForm.value.teamPromoCode || '-'
  }
  const promo = promoOptions.find(p => p.id === bindForm.value.promoId)
  return promo?.name || bindForm.value.promoId
})

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

const gopayBatchActive = computed(() => {
  return Boolean(gopayForm.value.batchMode && !gopayForm.value.checkoutUrl && gopaySelectedBatchEmails.value.length > 0)
})

const gopayEffectiveEmail = computed(() => {
  if (gopayBatchActive.value) {
    return gopaySelectedBatchEmails.value[0] || ''
  }
  return String(gopayForm.value.email || '').trim().toLowerCase()
})

const gopayCanSubmit = computed(() => {
  return Boolean(
    gopayEffectiveEmail.value
    && gopayForm.value.phoneNumber
    && gopayForm.value.smsUrl
    && gopayForm.value.gopayPin
  )
})

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

const bindResult = computed(() => bindTask.value?.result || null)

const bindTaskRunning = computed(() => {
  return ['pending', 'running'].includes(bindTask.value?.status)
})

const gopayTaskRunning = computed(() => {
  return ['pending', 'running'].includes(gopayTask.value?.status)
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
  gopay_try_account: '尝试当前 auth_session',
  gopay_rotate_account: '切换 auth_session 重试',
  gopay_account_skipped_cooldown: '跳过冷却中的 auth_session',
  generate_checkout: '生成支付链接',
  checkout_ready: '支付链接已生成',
  open_checkout: '打开支付页',
  checkout_opened: '已进入支付页',
  checkout_context_warmup: '预热 ChatGPT checkout 上下文',
  gopay_http_flow: '进入 GoPay HTTP 支付流程',
  stripe_create_payment_method: '创建 Stripe GoPay 支付方式',
  stripe_init: '初始化 Stripe 支付页',
  stripe_confirm: '确认 Stripe GoPay 支付方式',
  chatgpt_approve: '确认 ChatGPT checkout',
  chatgpt_approve_blocked_rotate: 'ChatGPT approve 被拦截，切换账号',
  gopay_all_accounts_blocked: '所有账号 approve 均被拦截',
  resolve_midtrans_redirect: '解析 Midtrans 跳转',
  pm_redirect: '跟随 Stripe 跳转',
  midtrans_load_transaction: '读取 Midtrans 交易',
  midtrans_linking: '发起 GoPay 账户绑定',
  midtrans_already_linked: '手机号已绑定其他账号，等待解绑后重试',
  midtrans_already_linked_failed: '手机号仍绑定其他账号，已停止',
  gopay_validate_reference: '校验 GoPay 绑定引用',
  gopay_user_consent: '确认 GoPay 授权',
  gopay_rate_limited: 'GoPay 尝试过多，请稍后再试',
  wait_sms_otp_window: '等待 SMS OTP 通道',
  trigger_sms_otp: '点击 SMS OTP 按钮',
  sms_otp_triggered: '已切换到 SMS OTP',
  sms_otp_trigger_failed: '切换 SMS OTP 失败',
  wait_otp: '等待 GoPay OTP',
  fetch_otp: '拉取 GoPay OTP',
  gopay_validate_otp: '校验 GoPay OTP',
  gopay_tokenize_pin: '生成 GoPay PIN token',
  gopay_validate_pin: '校验 GoPay 绑定 PIN',
  midtrans_create_charge: '创建 Midtrans GoPay 扣款',
  gopay_payment_validate: '校验 GoPay 扣款引用',
  gopay_payment_confirm: '确认 GoPay 扣款',
  gopay_payment_process: '提交 GoPay 扣款 PIN',
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

async function loadAccounts() {
  loadingAccounts.value = true
  try {
    const accounts = await api.getAccounts()
    accountOptions.value = (accounts || [])
      .filter(account => account?.email && account?.auth_session_file)
      .sort((a, b) => Number(b?.created_at || 0) - Number(a?.created_at || 0))
  } catch (e) {
    setMessage(`加载号池账号失败: ${e.message}`, false)
  } finally {
    loadingAccounts.value = false
  }
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

function pushGoPayLog(message, level = 'info') {
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
    message,
    label: meta.label,
    levelClass: meta.levelClass,
  })
  if (gopayLogEntries.value.length > 200) {
    gopayLogEntries.value.splice(0, gopayLogEntries.value.length - 200)
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
    checkout_ui_mode: bindForm.value.checkoutMode,
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
    return {
      link: bindForm.value.planType === 'team'
        ? `https://chatgpt.com/checkout/openai_ie/${sessionId}`
        : `https://chatgpt.com/checkout/openai_llc/${sessionId}`,
      sessionId,
      rawGeneratedUrl: '',
    }
  }
  return null
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
    if (nextStage && previousStage !== nextStage) {
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
    if (nextStage && previousStage !== nextStage) {
      pushGoPayLog(`执行阶段：${gopayStageLabelMap[nextStage] || nextStage}`, 'info')
    }
    if (['pending', 'running'].includes(task.status)) {
      gopayTaskPollTimer = window.setTimeout(() => {
        pollGoPayTask(taskId)
      }, 3000)
      return
    }
    gopayCancelling.value = false
    if (task.result?.message) {
      pushGoPayLog(task.result.message, task.result?.status === 'success' ? 'success' : task.status === 'cancelled' ? 'warn' : 'error')
    }
  } catch (e) {
    pushGoPayLog(`查询 GoPay 任务失败: ${e.message}`, 'error')
    setMessage(`查询 GoPay 任务失败: ${e.message}`, false)
  }
}

watch(
  () => bindForm.value.planType,
  (planType) => {
    if (planType === 'team') {
      bindForm.value.country = 'US'
      bindForm.value.currency = 'USD'
      bindForm.value.checkoutMode = 'hosted'
    } else {
      const nextPromo = promoOptions.find(p => p.plan === planType)
      if (nextPromo && nextPromo.id !== bindForm.value.promoId) {
        bindForm.value.promoId = nextPromo.id
      }
      bindForm.value.country = 'SG'
      bindForm.value.currency = 'SGD'
      bindForm.value.checkoutMode = 'custom'
    }
  }
)

watch(
  () => bindForm.value.country,
  (country) => {
    bindForm.value.currency = countryCurrencyMap[country] || 'USD'
  },
  { immediate: true }
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
        promo: selectedPromoName.value,
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
        promo: selectedPromoName.value,
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
      promo: selectedPromoName.value,
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

  const manualLink = String(bindTaskForm.value.checkoutUrl || '').trim()
  if (manualLink) {
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
  pushBindLog('access_token 提取成功，开始生成支付链接', 'info')
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
      proxy_url: bindTaskForm.value.proxyUrl || null,
      proxy_label: bindTaskForm.value.proxyLabel,
      manual_confirm: bindTaskForm.value.manualConfirm,
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
  pushBindLog('已发起取消请求，等待任务在安全点退出', 'warn')
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
  if (!gopayCanSubmit.value) {
    setMessage('请填写完整的 GoPay 参数', false)
    return
  }

  gopaySubmitting.value = true
  gopayLogEntries.value = []
  pushGoPayLog(gopayBatchActive.value ? `准备提交批量 GoPay 任务，共 ${gopaySelectedBatchEmails.value.length} 个账号` : '准备提交 GoPay 任务', 'info')
  try {
    const task = await api.startGoPayBind({
      email: gopayEffectiveEmail.value,
      account_emails: gopayBatchActive.value ? gopaySelectedBatchEmails.value : [],
      checkout_url: gopayForm.value.checkoutUrl || '',
      country_code: gopayForm.value.countryCode || '',
      phone_number: gopayForm.value.phoneNumber,
      sms_url: gopayForm.value.smsUrl,
      gopay_pin: gopayForm.value.gopayPin,
      proxy_url: gopayForm.value.proxyUrl || null,
      proxy_label: gopayForm.value.proxyLabel,
    })
    gopayTask.value = task
    pushGoPayLog(`GoPay 任务已提交，任务 ID: ${task.task_id}`, 'success')
    setMessage(`GoPay 任务已提交: ${task.task_id}`)
    await pollGoPayTask(task.task_id)
  } catch (e) {
    pushGoPayLog(`提交 GoPay 任务失败: ${e.message}`, 'error')
    setMessage(`提交 GoPay 任务失败: ${e.message}`, false)
  } finally {
    gopaySubmitting.value = false
  }
}

async function cancelGoPayTask() {
  if (!gopayTaskRunning.value || gopayCancelling.value) return
  gopayCancelling.value = true
  pushGoPayLog('已发起取消请求，等待任务在安全点退出', 'warn')
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
  loadAccounts()
  loadCards()
})

onUnmounted(() => {
  stopBindTaskPolling()
  stopGoPayTaskPolling()
})

watch(activeTab, (tab) => {
  if (tab === 'generate' || tab === 'bind' || tab === 'gopay') {
    loadAccounts()
    loadCards()
  }
})
</script>

<style scoped>
.link-panel::-webkit-scrollbar {
  display: none;
}

.link-panel [style*="overflow-x-auto"]::-webkit-scrollbar {
  display: none;
}
</style>
