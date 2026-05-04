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

    <h2 class="text-xl font-bold text-white mb-2">自助绑卡服务</h2>
    <p class="text-sm text-gray-400 mb-6">
      支持生成官方优惠链接，visa卡池管理，以及一键绑卡服务。
    </p>

    <div class="relative mb-6">
      <div class="flex flex-wrap gap-2">
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
      <div
        v-if="activeTab === 'gopay'"
        class="mt-4 grid grid-cols-2 gap-3 xl:absolute xl:right-0 xl:-top-14 xl:mt-0 xl:w-[960px] xl:grid-cols-4">
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
              <option value="ID">印度尼西亚 (ID)</option>
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
            <label class="block text-sm text-gray-400 mb-1">链接类型</label>
            <select
              v-model="bindForm.checkoutMode"
              :disabled="generating"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-if="bindForm.planType !== 'team'" value="custom">短链（chatgpt.com/checkout）</option>
              <option value="hosted">长链（pay.openai.com/c/pay）</option>
            </select>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>套餐：<span class="text-gray-200">{{ bindForm.planType === 'plus' ? 'ChatGPT Plus' : 'ChatGPT Team' }}</span></div>
            <div>优惠：<span class="text-gray-200">{{ selectedPromoName }}</span></div>
            <div>国家：<span class="text-gray-200">{{ bindForm.country }}</span> / 货币：<span class="text-gray-200">{{ bindForm.currency }}</span></div>
            <div>链接类型：<span class="text-gray-200">{{ bindForm.checkoutMode === 'custom' ? '短链（chatgpt.com/checkout）' : '长链（pay.openai.com/c/pay）' }}</span></div>
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
                <option value="ID">印度尼西亚 (ID)</option>
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
              <label class="block text-sm text-gray-400 mb-1">链接类型</label>
              <select
                v-model="bindForm.checkoutMode"
                :disabled="bindSubmitting || bindTaskRunning"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-if="bindForm.planType !== 'team'" value="custom">短链（chatgpt.com/checkout）</option>
                <option value="hosted">长链（pay.openai.com/c/pay）</option>
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
        <div>
          <h3 class="text-lg font-semibold text-white">GoPay</h3>
          <p class="text-sm text-gray-400 mt-1">
            走印尼区 GoPay 支付链路，自动处理 OTP、短信验证码和 PIN 提交。
          </p>
        </div>
      </div>

      <div class="grid grid-cols-1 xl:grid-cols-[420px_minmax(0,1fr)] gap-4">
        <div class="space-y-3">
          <div>
            <div class="flex items-center justify-between gap-3 mb-1">
              <label class="block text-sm text-gray-400">号池账号</label>
              <div class="flex items-center gap-3">
                <label class="inline-flex items-center gap-2 text-xs text-gray-300">
                  <input
                    v-model="gopayForm.autoRegister"
                    type="checkbox"
                    :disabled="gopaySubmitting || gopayTaskRunning || Boolean(gopayForm.checkoutUrl)"
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
                  @click="openGoPayAccountPicker"
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

          <div class="grid grid-cols-1 md:grid-cols-[120px_minmax(0,1fr)_minmax(0,1fr)] gap-3">
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
            <div>
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

        <div class="border border-gray-800 rounded-xl bg-gray-950/60 p-4 min-w-0 flex flex-col h-[calc(100vh-220px)] min-h-[520px] max-h-[760px]">
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

    <div
      v-if="gopayAutoRegisterConfigOpen"
      class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4"
      @click.self="closeGoPayAutoRegisterConfig"
    >
      <div class="w-full max-w-2xl max-h-[82vh] rounded-xl border border-gray-800 bg-gray-900 shadow-2xl flex flex-col">
        <div class="flex items-center justify-between gap-4 px-5 py-4 border-b border-gray-800">
          <div>
            <h4 class="text-lg font-semibold text-white">自动注册配置</h4>
            <div class="text-xs text-gray-500 mt-1">选择 GoPay 自动注册使用的域名、邮箱前缀和密码。</div>
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
                +5位随机字母数字 @随机域名
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
            <div>域名轮换：<span class="text-gray-200">{{ gopaySelectedAutoRegisterDomainsLabel }}</span></div>
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
            :disabled="!gopaySelectedAutoRegisterDomains.length"
            class="px-5 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50">
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
            <h4 class="text-lg font-semibold text-white">批量选择账号</h4>
            <div class="text-xs text-gray-500 mt-1">已选择 {{ gopaySelectedBatchEmails.length }} / {{ accountOptions.length }} 个账号</div>
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
                :disabled="loadingAccounts || !accountOptions.length || gopayAllAccountsSelected"
                class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                全选
              </button>
              <button
                type="button"
                @click="clearGoPayBatchAccounts"
                :disabled="!gopaySelectedBatchEmails.length"
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
              v-model="gopayForm.accountEmails"
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
import BindCardPool from './BindCardPool.vue'

const emit = defineEmits(['refresh'])

const BIND_HISTORY_KEY = 'autoteam_bind_history_v1'
const GOPAY_FORM_STATE_KEY = 'autoteam_gopay_form_state_v1'

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
  autoRegister: false,
  autoRegisterCount: 1,
  autoRegisterDomains: [],
  autoRegisterPrefix: '',
  autoRegisterPassword: '',
  batchMode: false,
  accountEmails: [],
  checkoutUrl: '',
  checkoutUiMode: 'hosted',
  countryCode: '62',
  phoneNumber: '81997420107',
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
  deleteRejectedAccounts: false,
  autoOauthAfterSuccess: false,
})
const gopayAccountSearchKeyword = ref('')
const gopayAccountPickerOpen = ref(false)
const gopayAutoRegisterConfigOpen = ref(false)
const gopayRegisterDomainOptions = ref([])
const gopayRegisterDomainLoading = ref(false)
const gopaySubmitting = ref(false)
const gopayCancelling = ref(false)
const gopaySkipping = ref(false)
const gopayTask = ref(null)
const gopayLogEntries = ref([])
const gopayLogScrollRef = ref(null)
const gopayLoggedProgressEventIds = ref(new Set())
const gopaySuccessNoticeVisible = ref(false)
const gopaySuccessNoticeEmail = ref('')
let bindTaskPollTimer = 0
let gopayTaskPollTimer = 0
let gopaySuccessNoticeTimer = 0

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
  ID: 'IDR',
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

const normalizedGoPayAutoRegisterCount = computed(() => {
  return normalizeGoPayAutoRegisterCount(gopayForm.value.autoRegisterCount)
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
  return `${gopaySelectedAutoRegisterDomainsLabel.value}，前缀 ${prefix || '随机'}，密码 ${password ? '自定义' : '随机'}`
})

const gopayAutoRegisterPreviewEmail = computed(() => {
  const prefix = String(gopayForm.value.autoRegisterPrefix || '').trim()
  const domain = gopaySelectedAutoRegisterDomains.value[0] || gopayRegisterDomainOptions.value[0] || 'domain.com'
  return `${prefix ? `${prefix}a8k3p` : '__random__'}@${domain}`
})

const gopayAllAutoRegisterDomainsSelected = computed(() => {
  if (!gopayRegisterDomainOptions.value.length) return false
  const selected = new Set(gopaySelectedAutoRegisterDomains.value.map(domain => domain.toLowerCase()))
  return gopayRegisterDomainOptions.value.every(domain => selected.has(String(domain || '').toLowerCase()))
})

const gopayAllAccountsSelected = computed(() => {
  if (!accountOptions.value.length) return false
  const selected = new Set(gopaySelectedBatchEmails.value)
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

const gopayEffectiveEmail = computed(() => {
  if (gopayForm.value.autoRegister) return ''
  if (gopayBatchActive.value) {
    return gopaySelectedBatchEmails.value[0] || ''
  }
  return String(gopayForm.value.email || '').trim().toLowerCase()
})

const gopayCanSubmit = computed(() => {
  return Boolean(
    (gopayForm.value.autoRegister || gopayEffectiveEmail.value)
    && (!gopayForm.value.autoRegister || gopaySelectedAutoRegisterDomains.value.length)
    && gopayForm.value.phoneNumber
    && gopayForm.value.smsUrl
    && gopayForm.value.gopayPin
  )
})

let normalizingGoPayPhone = false

function digitsOnly(value) {
  return String(value || '').replace(/\D/g, '')
}

function normalizeGoPayAutoRegisterCount(value) {
  const count = Number(value || 1)
  if (!Number.isFinite(count)) return 1
  return Math.max(1, Math.min(100, Math.floor(count)))
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
    openGoPayAutoRegisterConfig()
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
  () => getRememberedGoPayForm(),
  () => saveGoPayFormState(),
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
  gopay_batch_completed: '批量绑定完成',
  gopay_account_skipped_cooldown: '跳过冷却中的 auth_session',
  gopay_skip_current_requested: '已请求跳过当前账号',
  gopay_account_skipped_by_user: '已跳过当前账号',
  gopay_all_accounts_skipped: '所有账号都已跳过',
  generate_checkout: '生成支付链接',
  checkout_ready: '支付链接已生成',
  open_checkout: '打开支付页',
  checkout_opened: '已进入支付页',
  checkout_context_warmup: '预热 ChatGPT checkout 上下文',
  chatgpt_http_session_ready: 'ChatGPT HTTP 会话已准备',
  gopay_http_flow: '进入 GoPay HTTP 支付流程',
  stripe_create_payment_method: '创建 Stripe GoPay 支付方式',
  stripe_init: '初始化 Stripe 支付页',
  stripe_confirm: '确认 Stripe GoPay 支付方式',
  chatgpt_approve: '确认 ChatGPT checkout',
  chatgpt_approve_blocked_rotate: 'ChatGPT approve 被拦截，切换账号',
  chatgpt_approve_blocked_cooldown: 'ChatGPT approve 被拦截，账号进入冷却',
  gopay_all_accounts_blocked: '所有账号 approve 均被拦截',
  checkout_not_approved_rotate: '付款未获批准，切换账号',
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
  gopay_validate_reference: '校验 GoPay 绑定引用',
  gopay_user_consent: '确认 GoPay 授权',
  gopay_rate_limited: 'GoPay 尝试过多，请稍后再试',
  wait_sms_otp_window: '等待 GoPay SMS 可重发',
  trigger_sms_otp: '协议触发 GoPay SMS OTP',
  sms_otp_triggered: '已触发 GoPay SMS OTP',
  sms_otp_resend_due: '2 分钟未收到 OTP，重新发送',
  sms_otp_resend_failed: '重新发送 OTP 失败',
  sms_otp_trigger_failed: '触发 GoPay SMS OTP 失败',
  wait_otp: '等待 GoPay OTP',
  fetch_otp: '拉取 GoPay OTP',
  otp_received: '收到 SMS OTP',
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

const gopayTopCards = computed(() => [
  {
    label: '当前账号',
    value: gopayBoardEmail.value,
    color: 'text-cyan-300 font-mono text-base',
    meta: '',
  },
  {
    label: '任务进度',
    value: gopayBoardProgress.value,
    color: 'text-blue-400',
    meta: '',
  },
  {
    label: '绑卡成功',
    value: String(gopayBoardProgressStats.value.successful || 0),
    color: 'text-emerald-400',
    meta: gopayBoardRegistrationMeta.value,
  },
  {
    label: '绑卡失败',
    value: String(gopayBoardFailureCount.value),
    color: 'text-red-400',
    meta: '',
  },
])

const gopayBoardFailureCount = computed(() => {
  const failedEmails = new Set()
  const result = gopayTask.value?.result || {}
  const lists = [
    result.rejected_emails,
    result.payment_failed_emails,
    result.nonzero_blocked_emails,
    result.blocked_emails,
    result.skipped_emails,
    result.bind_failed_emails,
    result.failed_emails,
  ]
  for (const list of lists) {
    if (!Array.isArray(list)) continue
    for (const item of list) {
      const normalized = String((item && typeof item === 'object') ? item.email : item || '').trim().toLowerCase()
      if (normalized) failedEmails.add(normalized)
    }
  }

  const failureStages = new Set([
    'chatgpt_approve_blocked_rotate',
    'checkout_not_approved_rotate',
    'gopay_payment_process_failed_rotate',
    'gopay_nonzero_amount_blocked_rotate',
    'gopay_account_skipped_by_user',
  ])
  const events = Array.isArray(gopayTask.value?.progress_events) ? gopayTask.value.progress_events : []
  for (const event of events) {
    if (!failureStages.has(String(event?.stage || ''))) continue
    const normalized = String(event?.email || '').trim().toLowerCase()
    if (normalized) failedEmails.add(normalized)
  }

  return failedEmails.size
})

const gopayBoardRegistrationMeta = computed(() => {
  const result = gopayTask.value?.result || {}
  const params = gopayTask.value?.params || {}
  if (!params.auto_register) return ''
  const registered = Array.isArray(result.registered_emails) ? result.registered_emails.length : 0
  return `注册成功 ${registered}`
})

const gopayBoardEmail = computed(() => {
  const progress = gopayTask.value?.progress || {}
  const result = gopayTask.value?.result || {}
  const params = gopayTask.value?.params || {}
  return progress.email || result.email || result.email_used || params.email || gopayForm.value.email || '-'
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
  const task = gopayTask.value || {}
  const progress = task.progress || {}
  const result = task.result || {}
  const params = task.params || {}
  const accounts = Array.isArray(params.account_emails) ? params.account_emails : []
  const isAutoRegister = Boolean(params.auto_register)
  const autoRegisterEventTotal = (Array.isArray(task.progress_events) ? task.progress_events : []).reduce((maxTotal, event) => {
    const stage = String(event?.stage || '')
    if (!(stage.startsWith('gopay_auto_register') || stage.startsWith('register_'))) return maxTotal
    const total = Number(event?.total || 0)
    return Number.isFinite(total) ? Math.max(maxTotal, total) : maxTotal
  }, 0)
  const autoRegisterCount = params.auto_register
    ? normalizeGoPayAutoRegisterCount(params.auto_register_count || result.auto_register_count || progress.auto_register_count || autoRegisterEventTotal || 1)
    : 0
  const attempted = Array.isArray(result.attempted_emails)
    ? result.attempted_emails.length
    : Number(result.auto_register_attempted || progress.attempted || progress.attempt || 0)
  const successful = Array.isArray(result.successful_emails)
    ? result.successful_emails.length
    : Number(progress.successful || 0)
  const done = Math.max(attempted, successful)
  const total = isAutoRegister
    ? autoRegisterCount
    : Number(progress.total || accounts.length || (task.task_id ? 1 : 0))
  const remaining = Number.isFinite(Number(progress.remaining_candidates))
    ? Number(progress.remaining_candidates)
    : Math.max(0, Math.max(total, done) - done)
  return {
    total: Math.max(total, done),
    attempted: done,
    successful,
    remaining,
  }
})

const gopayBoardProgress = computed(() => {
  const stats = gopayBoardProgressStats.value
  if (!stats.total) return '0/0'
  const done = Math.max(stats.attempted, stats.successful)
  return `${done}/${stats.total}`
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

function mergeGoPayBatchEmails(emails) {
  gopayForm.value.accountEmails = normalizeEmailList([
    ...gopaySelectedBatchEmails.value,
    ...emails,
  ])
}

function selectAllGoPayAccounts() {
  mergeGoPayBatchEmails(accountOptions.value.map(account => account.email))
}

function clearGoPayBatchAccounts() {
  gopayForm.value.accountEmails = []
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

async function openGoPayAutoRegisterConfig() {
  await loadGoPayAutoRegisterDomains()
  gopayAutoRegisterConfigOpen.value = true
}

function closeGoPayAutoRegisterConfig() {
  gopayAutoRegisterConfigOpen.value = false
}

function confirmGoPayAutoRegisterConfig() {
  if (!gopaySelectedAutoRegisterDomains.value.length) {
    setMessage('请选择至少一个自动注册域名', false)
    return
  }
  gopayForm.value.autoRegisterDomains = gopaySelectedAutoRegisterDomains.value
  closeGoPayAutoRegisterConfig()
}

function selectAllGoPayAutoRegisterDomains() {
  gopayForm.value.autoRegisterDomains = [...gopayRegisterDomainOptions.value]
}

function clearGoPayAutoRegisterDomains() {
  gopayForm.value.autoRegisterDomains = []
}

function openGoPayAccountPicker() {
  gopayAccountPickerOpen.value = true
}

function closeGoPayAccountPicker() {
  gopayAccountPickerOpen.value = false
}

function getRememberedGoPayForm() {
  return {
    email: String(gopayForm.value.email || '').trim().toLowerCase(),
    autoRegister: Boolean(gopayForm.value.autoRegister),
    autoRegisterCount: normalizedGoPayAutoRegisterCount.value,
    autoRegisterDomains: gopaySelectedAutoRegisterDomains.value,
    autoRegisterPrefix: String(gopayForm.value.autoRegisterPrefix || '').trim(),
    batchMode: Boolean(gopayForm.value.batchMode),
    accountEmails: normalizeEmailList(gopayForm.value.accountEmails),
    countryCode: digitsOnly(gopayForm.value.countryCode) || '62',
    phoneNumber: String(gopayForm.value.phoneNumber || '').trim(),
    smsUrl: String(gopayForm.value.smsUrl || '').trim(),
    proxyLabel: String(gopayForm.value.proxyLabel || '').trim(),
    proxyUrl: String(gopayForm.value.proxyUrl || '').trim(),
    checkoutUiMode: gopayForm.value.checkoutUiMode === 'hosted' ? 'hosted' : 'custom',
    deleteRejectedAccounts: Boolean(gopayForm.value.deleteRejectedAccounts),
    autoOauthAfterSuccess: Boolean(gopayForm.value.autoOauthAfterSuccess),
  }
}

function loadGoPayFormState() {
  try {
    const raw = localStorage.getItem(GOPAY_FORM_STATE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return
    gopayForm.value = {
      ...gopayForm.value,
      email: String(saved.email || '').trim().toLowerCase(),
      autoRegister: Boolean(saved.autoRegister),
      autoRegisterCount: normalizeGoPayAutoRegisterCount(saved.autoRegisterCount),
      autoRegisterDomains: Array.isArray(saved.autoRegisterDomains)
        ? saved.autoRegisterDomains.map(domain => String(domain || '').trim().replace(/^@/, '')).filter(Boolean)
        : [],
      autoRegisterPrefix: String(saved.autoRegisterPrefix || ''),
      autoRegisterPassword: '',
      batchMode: Boolean(saved.batchMode),
      accountEmails: normalizeEmailList(saved.accountEmails),
      countryCode: digitsOnly(saved.countryCode) || '62',
      phoneNumber: String(saved.phoneNumber || '').trim(),
      smsUrl: String(saved.smsUrl || '').trim(),
      proxyLabel: String(saved.proxyLabel || '').trim(),
      proxyUrl: String(saved.proxyUrl || '').trim(),
      checkoutUiMode: saved.checkoutUiMode === 'custom' ? 'custom' : 'hosted',
      deleteRejectedAccounts: Boolean(saved.deleteRejectedAccounts),
      autoOauthAfterSuccess: Boolean(saved.autoOauthAfterSuccess),
    }
  } catch (e) {
    console.error('loadGoPayFormState', e)
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
    const accounts = await api.getAccounts()
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
  } catch (e) {
    setMessage(`加载号池账号失败: ${e.message}`, false)
  } finally {
    loadingAccounts.value = false
  }
}

function isBindableFreeAccount(account) {
  if (!account?.email || account?.is_main_account) return false
  if (String(account?.account_type || '').toLowerCase() !== 'free') return false
  if (!account?.auth_session_file) return false
  const status = String(account?.status || '').toLowerCase()
  if (['fail', 'auth_invalid', 'orphan', 'exhausted', 'standby', 'pending'].includes(status)) return false
  return true
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
  scrollGoPayLogToBottom()
}

function goPayProgressLogLevel(event) {
  const level = String(event?.level || '').trim()
  if (['info', 'success', 'warn', 'error'].includes(level)) return level
  const stage = String(event?.stage || '')
  if (stage === 'completed' || stage === 'payment_completed' || stage === 'otp_received' || stage === 'gopay_oauth_login_done') return 'success'
  if (stage === 'gopay_oauth_login_failed') return 'error'
  if (stage === 'gopay_oauth_phone_required_removed') return 'warn'
  if (stage.includes('not_approved') || stage.includes('blocked') || stage.includes('cooldown') || stage.includes('retry')) return 'warn'
  if (stage === 'failed' || stage.includes('all_accounts')) return 'error'
  return 'info'
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
    const message = String(event?.message || '').trim()
    if (!message) continue
    pushGoPayLog(message, goPayProgressLogLevel(event))
    printed += 1
  }
  return printed
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
    const printedProgressEvents = processGoPayProgressEvents(task)
    if (['pending', 'running'].includes(task.status)) {
      const previousProgressMessage = previous?.progress?.message || ''
      const nextProgressMessage = task?.progress?.message || ''
      if (!printedProgressEvents && nextProgressMessage && nextProgressMessage !== previousProgressMessage) {
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
    if (!running) return

    if (running.command === 'gopay-bind') {
      activeTab.value = 'gopay'
      gopayTask.value = running
      pushGoPayLog(`已恢复 GoPay 任务轮询：${running.task_id}`, 'info')
      const printed = processGoPayProgressEvents(running)
      if (!printed && running.progress?.message) {
        pushGoPayLog(running.progress.message, 'info')
      }
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
  normalizeGoPayPhoneFields({ forceLocal: true })
  saveGoPayFormState()
  if (!gopayCanSubmit.value) {
    setMessage('请填写完整的 GoPay 参数', false)
    return
  }

  gopaySubmitting.value = true
  gopayLogEntries.value = []
  gopayLoggedProgressEventIds.value = new Set()
  pushGoPayLog(
    gopayForm.value.autoRegister
      ? `准备提交自动注册并 GoPay 绑定任务，共 ${normalizedGoPayAutoRegisterCount.value} 个账号`
      : gopayBatchActive.value
        ? `准备提交批量 GoPay 任务，共 ${gopaySelectedBatchEmails.value.length} 个账号`
        : '准备提交 GoPay 任务',
    'info'
  )
  try {
    const task = await api.startGoPayBind({
      email: gopayEffectiveEmail.value,
      account_emails: gopayBatchActive.value ? gopaySelectedBatchEmails.value : [],
      auto_register: Boolean(gopayForm.value.autoRegister),
      auto_register_count: normalizedGoPayAutoRegisterCount.value,
      auto_register_domain: gopaySelectedAutoRegisterDomains.value[0] || '',
      auto_register_domains: gopaySelectedAutoRegisterDomains.value,
      auto_register_prefix: String(gopayForm.value.autoRegisterPrefix || '').trim(),
      auto_register_password: String(gopayForm.value.autoRegisterPassword || '').trim(),
      checkout_url: gopayForm.value.checkoutUrl || '',
      checkout_ui_mode: gopayForm.value.checkoutUiMode === 'hosted' ? 'hosted' : 'custom',
      country_code: gopayForm.value.countryCode || '',
      phone_number: gopayForm.value.phoneNumber,
      sms_url: gopayForm.value.smsUrl,
      gopay_pin: gopayForm.value.gopayPin,
      proxy_url: gopayForm.value.proxyUrl || null,
      proxy_label: gopayForm.value.proxyLabel,
      delete_rejected_accounts: Boolean(gopayForm.value.deleteRejectedAccounts),
      auto_oauth_after_success: Boolean(gopayForm.value.autoOauthAfterSuccess),
    })
    gopayTask.value = task
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
  loadGoPayFormState()
  if (gopayForm.value.autoRegister) {
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
