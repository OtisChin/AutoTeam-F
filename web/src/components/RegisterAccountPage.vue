<template>
  <div class="space-y-6 xl:h-[calc(100vh-3rem)] xl:min-h-0">
    <div class="grid shrink-0 grid-cols-1 gap-4 xl:grid-cols-[380px_minmax(0,1fr)] xl:items-stretch">
      <div class="flex flex-col justify-center">
        <h2 class="text-xl font-bold text-white">注册账号</h2>
        <p class="mt-1 text-sm text-gray-400">
          使用当前已配置的邮箱服务执行注册任务；也可以走手机号注册后绑定邮箱流程。
        </p>
        <div class="mt-4 flex items-center gap-2">
          <button
            @click="statsMode = 'task'"
            class="px-3 py-1.5 rounded-lg text-xs border transition"
            :class="statsMode === 'task'
              ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
              : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
            本次任务
          </button>
          <button
            @click="statsMode = 'today'"
            class="px-3 py-1.5 rounded-lg text-xs border transition"
            :class="statsMode === 'today'
              ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
              : 'bg-gray-900 text-gray-300 border-gray-700 hover:bg-gray-800'">
            今日统计
          </button>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <div v-for="card in statCards" :key="card.label" class="min-w-0 rounded-xl border border-gray-800 bg-gray-900 px-4 py-3">
          <div class="text-xs text-gray-400">{{ card.label }}</div>
          <div class="mt-2 truncate text-xl font-bold" :class="card.color">{{ card.value }}</div>
        </div>
      </div>
    </div>

    <div v-if="statsMode === 'task'" class="shrink-0 rounded-lg border border-gray-800 bg-gray-900 px-4 py-3 text-sm text-gray-300">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div class="min-w-0">
          <span class="text-gray-500">任务 ID：</span>
          <span class="font-mono text-white">{{ currentTaskMeta.taskId || '-' }}</span>
          <span class="mx-3 text-gray-700">|</span>
          <span class="text-gray-500">开始时间：</span>
          <span class="font-mono text-white">{{ currentTaskMeta.startedAt || '-' }}</span>
          <template v-if="activeRegisterTaskStatus">
            <span class="mx-3 text-gray-700">|</span>
            <span class="text-gray-500">状态：</span>
            <span class="font-mono text-amber-300">{{ activeRegisterTaskStatus }}</span>
          </template>
        </div>
        <button
          v-if="props.runningTask"
          type="button"
          @click="cancelRegisterTask"
          :disabled="registerCancelBusy || registerCancelRequested"
          class="shrink-0 rounded-lg border px-3 py-1.5 text-xs font-medium transition"
          :class="registerCancelBusy || registerCancelRequested
            ? 'cursor-not-allowed border-gray-700 bg-gray-800 text-gray-500'
            : 'border-rose-500/30 bg-rose-600/10 text-rose-300 hover:bg-rose-600/20'">
          {{ registerCancelRequested ? '取消中...' : (registerCancelBusy ? '提交中...' : '取消任务') }}
        </button>
      </div>
    </div>

    <div v-if="message" class="shrink-0 rounded-lg border px-4 py-3 text-sm" :class="messageClass">
      {{ message }}
    </div>

    <section class="rounded-xl border border-gray-800 bg-gray-900 p-4 xl:h-[calc(100vh-170px)] xl:min-h-0 xl:flex xl:flex-col xl:overflow-hidden">
      <div class="grid grid-cols-1 gap-4 xl:min-h-0 xl:flex-1 xl:grid-cols-[430px_minmax(0,1fr)] xl:overflow-hidden">
        <div class="space-y-3 xl:min-h-0 xl:overflow-y-auto xl:pr-2 xl:pb-2">
          <div class="rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <button
              @click="submitManualRegister"
              :disabled="registeringBusy || registeringAccount || !canSubmitRegister"
              class="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition hover:bg-blue-500 disabled:opacity-50">
              {{ registeringAccount ? '提交中...' : (isPhoneCpaFlow ? '开始手机注册' : (registerForm.mode === 'batch' ? '开始批量注册' : '开始注册')) }}
            </button>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">注册模式</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="registerForm.mode = 'single'"
                :disabled="registeringBusy"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="registerForm.mode === 'single'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                单次注册
              </button>
              <button
                @click="registerForm.mode = 'batch'"
                :disabled="registeringBusy"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="registerForm.mode === 'batch'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                批量注册
              </button>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">注册链路</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="registerForm.registrationFlow = 'standard'"
                :disabled="registeringBusy"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="registerForm.registrationFlow === 'standard'
                  ? 'bg-blue-600/20 text-blue-400 border-blue-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                邮箱注册
              </button>
              <button
                @click="registerForm.registrationFlow = 'phone_cpa'"
                :disabled="registeringBusy"
                class="px-4 py-2 rounded-lg text-sm border transition"
                :class="registerForm.registrationFlow === 'phone_cpa'
                  ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/40'
                  : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
                手机→邮箱→OAuth
              </button>
            </div>
          </div>

          <div v-if="isPhoneCpaFlow && !registerForm.phoneOnly" class="rounded-lg border border-emerald-500/20 bg-emerald-500/10 px-3 py-3 text-sm text-emerald-100 space-y-1">
            <div class="font-medium">手机→邮箱→OAuth 注册</div>
            <div class="text-xs text-emerald-200/80">
              先使用下方手机号供应商注册 ChatGPT，再绑定当前邮件供应商邮箱，最后生成 OAuth 凭证并写入当前账号池。
            </div>
          </div>
          <div v-if="isPhoneCpaFlow && registerForm.phoneOnly" class="rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-3 text-sm text-amber-100 space-y-1">
            <div class="font-medium">仅手机注册（不绑定邮箱、不 OAuth）</div>
            <div class="text-xs text-amber-200/80">
              仅使用手机号注册 ChatGPT，不绑定邮箱、不执行 Codex OAuth，注册后仅保存 auth_session。
            </div>
          </div>

          <label v-if="isPhoneCpaFlow" class="flex items-start gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2 text-sm text-gray-300 cursor-pointer hover:bg-gray-800/50">
            <input
              v-model="registerForm.phoneOnly"
              type="checkbox"
              :disabled="registeringBusy"
              class="mt-1 rounded border-gray-600 bg-gray-800"
            />
            <span>
              <span class="text-gray-100">仅手机注册</span>
              <span class="block text-xs text-gray-500">勾选后仅通过手机号注册账号，不绑定邮箱和 OAuth 登录。</span>
            </span>
          </label>

          <label v-if="!isPhoneCpaFlow" class="flex items-start gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2 text-sm text-gray-300">
            <input
              v-model="registerForm.protocolRegister"
              @change="registerForm.protocolRegister && (registerForm.useRoxyBrowser = false)"
              type="checkbox"
              :disabled="registeringBusy"
              class="mt-1 rounded border-gray-600 bg-gray-800"
            />
            <span>
              <span class="text-gray-100">协议注册</span>
              <span class="block text-xs text-gray-500">默认使用浏览器注册；勾选后使用协议注册流程。</span>
            </span>
          </label>

          <label v-if="!isPhoneCpaFlow" class="flex items-start gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2 text-sm text-gray-300">
            <input
              v-model="registerForm.useRoxyBrowser"
              @change="registerForm.useRoxyBrowser && (registerForm.protocolRegister = false)"
              type="checkbox"
              :disabled="registeringBusy"
              class="mt-1 rounded border-gray-600 bg-gray-800"
            />
            <span>
              <span class="text-gray-100">使用Roxy Browser</span>
              <span class="block text-xs text-gray-500">勾选后浏览器注册使用 RoxyBrowser 窗口，不启动本地 Playwright Chromium。</span>
            </span>
          </label>

          <label v-if="!isPhoneCpaFlow" class="flex items-start gap-2 rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-2 text-sm text-gray-300">
            <input
              v-model="registerForm.postRegisterOauth"
              type="checkbox"
              :disabled="registeringBusy"
              class="mt-1 rounded border-gray-600 bg-gray-800"
            />
            <span>
              <span class="text-gray-100">注册完成后 OAuth 登录</span>
              <span class="block text-xs text-gray-500">勾选后会生成并保留 OAuth 凭证；遇到 add-phone 时使用“设置 → OAuth 手机号”配置。</span>
            </span>
          </label>

          <label
            class="flex items-start gap-2 rounded-lg border px-3 py-2 text-sm"
            :class="isPhoneCpaFlow
              ? 'border-gray-800 bg-gray-900/50 text-gray-500'
              : 'border-cyan-500/20 bg-cyan-500/10 text-gray-300'"
          >
            <input
              v-model="registerForm.enableTotpMfa"
              type="checkbox"
              :disabled="registeringBusy || isPhoneCpaFlow"
              class="mt-1 rounded border-gray-600 bg-gray-800"
            />
            <span>
              <span :class="isPhoneCpaFlow ? 'text-gray-400' : 'text-cyan-100'">注册后启用官方 2FA / TOTP</span>
              <span class="block text-xs" :class="isPhoneCpaFlow ? 'text-gray-500' : 'text-cyan-200/80'">
                {{ isPhoneCpaFlow
                  ? '当前手机号注册链路暂不支持自动启用 2FA；切回“邮箱注册”后可勾选。'
                  : '通过 ChatGPT 官方安全设置启用 Authenticator app，并只在本地保存 masked 状态；raw secret 默认不导出。' }}
              </span>
            </span>
          </label>

          <div v-if="isPhoneCpaFlow || registerForm.postRegisterOauth" class="rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-3 text-sm text-gray-300 space-y-3">
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs text-gray-500 mb-1">{{ isPhoneCpaFlow ? '手机号供应商' : 'OAuth 手机号供应商' }}</label>
                <select
                  v-model="registerForm.oauthPhoneSmsProvider"
                  :disabled="registeringBusy || oauthPhoneSmsLoading"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option v-for="option in oauthPhoneSmsProviderOptions" :key="option.value" :value="option.value">
                    {{ option.label }}{{ option.configured ? '' : '（未配置）' }}
                  </option>
                </select>
              </div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">手机号国家</label>
                <div class="relative">
                  <input
                    v-model="oauthPhoneSmsCountrySearch"
                    :disabled="registeringBusy || oauthPhoneSmsLoading || oauthPhoneSmsCountriesLoading || oauthPhoneSmsCountryDisabled(registerForm.oauthPhoneSmsProvider)"
                    type="search"
                    autocomplete="off"
                    :placeholder="isCdkOAuthPhoneProvider(registerForm.oauthPhoneSmsProvider) ? '由 CDK 兑换结果决定' : (oauthPhoneSmsCountriesLoading ? '国家列表加载中...' : '搜索或选择国家')"
                    class="w-full px-3 py-2 pr-9 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-60"
                    @focus="openOAuthPhoneSmsCountryDropdown"
                    @input="handleOAuthPhoneSmsCountryInput"
                    @blur="closeOAuthPhoneSmsCountryDropdownSoon"
                  />
                  <button
                    type="button"
                    :disabled="registeringBusy || oauthPhoneSmsLoading || oauthPhoneSmsCountriesLoading || oauthPhoneSmsCountryDisabled(registerForm.oauthPhoneSmsProvider)"
                    class="absolute right-1.5 top-1/2 -translate-y-1/2 rounded px-1.5 py-1 text-xs text-gray-400 transition hover:bg-gray-700 hover:text-white disabled:pointer-events-none disabled:opacity-40"
                    @mousedown.prevent
                    @click="toggleOAuthPhoneSmsCountryDropdown"
                  >
                    ▾
                  </button>
                  <div
                    v-if="oauthPhoneSmsCountryDropdownOpen && !oauthPhoneSmsCountryDisabled(registerForm.oauthPhoneSmsProvider)"
                    class="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-gray-700 bg-gray-900 shadow-xl shadow-black/40"
                  >
                    <button
                      v-for="option in oauthPhoneSmsCountryOptionsForSelect"
                      :key="option.value"
                      type="button"
                      class="block w-full px-3 py-2 text-left text-sm transition hover:bg-gray-800"
                      :class="option.value === registerForm.oauthPhoneSmsCountry ? 'bg-blue-600/15 text-blue-200' : 'text-gray-200'"
                      @mousedown.prevent="selectOAuthPhoneSmsCountry(option)"
                    >
                      <span class="block truncate">{{ option.label }}</span>
                    </button>
                    <div v-if="!oauthPhoneSmsCountryOptionsForSelect.length" class="px-3 py-2 text-sm text-gray-500">
                      没有匹配的国家
                    </div>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="OAUTH_PHONE_DYNAMIC_PRICE_PROVIDERS.includes(registerForm.oauthPhoneSmsProvider)">
              <label class="block text-xs text-gray-500 mb-1">价格上限</label>
              <input
                v-model.trim="registerForm.oauthPhoneSmsMaxPrice"
                :disabled="registeringBusy || oauthPhoneSmsLoading"
                type="text"
                inputmode="decimal"
                autocomplete="off"
                placeholder="留空使用设置页配置；例如 0.045"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-60"
              />
            </div>
            <div v-if="isCdkOAuthPhoneProvider(registerForm.oauthPhoneSmsProvider)">
              <label class="block text-xs text-gray-500 mb-1">本次任务 CDK 池</label>
              <textarea
                v-model.trim="registerForm.oauthOasisSmsCdks"
                :disabled="registeringBusy || oauthPhoneSmsLoading"
                rows="4"
                spellcheck="false"
                autocomplete="off"
                :placeholder="oauthCdkTextareaPlaceholder"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white font-mono placeholder:text-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-60"
              ></textarea>
            </div>
            <div class="text-xs text-gray-500">
              手机号池使用池内号码；hero-sms / smsbower / SMSCloud 按国家 ID 和价格上限取号；Oasis / TuJie 优先使用本次任务 CDK 池。
            </div>
            <div v-if="oauthPhoneSmsCountryError" class="text-xs text-amber-300">
              {{ oauthPhoneSmsCountryError }}
            </div>
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-900/50 px-3 py-3 text-sm text-gray-300 space-y-3">
            <div v-if="!registerForm.proxyApiEnabled">
              <label class="block text-xs text-gray-500 mb-1">代理 URL</label>
              <input
                v-model.trim="registerForm.proxyUrl"
                :disabled="registeringBusy"
                type="text"
                autocomplete="off"
                placeholder="例如 http://user:pass@host:port 或 socks5://host:port"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white placeholder:text-gray-500 focus:outline-none focus:border-blue-500 disabled:opacity-60"
              />
              <div class="mt-1 text-xs text-gray-500">
                本次注册流程共用该代理；启用动态代理 API 时，动态代理优先。
              </div>
            </div>
            <label class="flex items-start gap-2">
              <input
                v-model="registerForm.proxyApiEnabled"
                type="checkbox"
                :disabled="registeringBusy"
                class="mt-1 rounded border-gray-600 bg-gray-800"
              />
              <span>
                <span class="text-gray-100">启用动态代理 API</span>
                <span class="block text-xs text-gray-500">每个账号注册前按所选国家提取一条代理；浏览器注册、协议注册和注册后 OAuth 共用本次代理。</span>
              </span>
            </label>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label class="block text-xs text-gray-500 mb-1">动态代理供应商</label>
                <select
                  v-model="registerForm.proxyApiProvider"
                  :disabled="registeringBusy"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="1024proxy">1024proxy</option>
                  <option value="cliproxy">Cliproxy</option>
                </select>
              </div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">代理国家</label>
                <select
                  v-model="registerForm.proxyApiCountry"
                  :disabled="registeringBusy"
                  class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
                >
                  <option v-for="option in registerProxyCountryOptions" :key="`register-proxy-${option.country}`" :value="option.country">
                    {{ option.label }}
                  </option>
                </select>
              </div>
            </div>
            <div class="mt-1 text-xs text-gray-500">
              {{ registerForm.proxyApiEnabled ? registerProxyApiHelp : '启用动态代理 API 后会使用这里选择的供应商和国家。' }}
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">邮件供应商</label>
            <select
              v-model="registerForm.mailProvider"
              :disabled="registeringBusy || mailProviderLoading"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="option in mailProviderOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </option>
            </select>
            <div class="mt-1 text-xs text-gray-500">
              这里只选择本次注册使用哪个 Provider；具体 API Key / token 池仍在“设置 → 邮件 Provider”里配置。
            </div>
          </div>

          <div v-if="registerProviderUsesPool">
            <label class="block text-sm text-gray-400 mb-1">注册域名</label>
            <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-2 text-sm text-gray-300">
              {{ registerProviderPoolMessage }}
            </div>
          </div>

          <div v-if="isOutlookLikePoolProvider" class="rounded-xl border border-gray-800 bg-gray-950/60 p-3 space-y-3">
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="text-sm font-medium text-white">{{ accountPoolProviderLabel }} 邮箱池</div>
                <div class="mt-1 text-xs text-gray-500">
                  {{ accountPoolProviderDescription }}
                </div>
              </div>
              <div class="flex shrink-0 items-center gap-2">
                <button
                  type="button"
                  @click="loadOutlookPoolStatus"
                  :disabled="outlookPoolLoading"
                  class="px-3 py-1.5 rounded-lg text-xs border bg-gray-900 hover:bg-gray-800 text-gray-300 border-gray-700 transition disabled:opacity-50">
                  {{ outlookPoolLoading ? '刷新中...' : '刷新状态' }}
                </button>
                <button
                  type="button"
                  @click="openOutlookPoolDialog"
                  class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition">
                  管理邮箱池
                </button>
                <button
                  type="button"
                  @click="openOutlookImportDialog"
                  class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition">
                  导入邮箱
                </button>
              </div>
            </div>
            <div v-if="outlookPoolStatus" class="border-y border-gray-800 py-3">
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div>
                  <div class="text-[11px] text-gray-500">邮箱池</div>
                  <div class="mt-0.5 text-sm font-medium text-white">{{ outlookPoolStatus.total }}</div>
                </div>
                <div>
                  <div class="text-[11px] text-gray-500">可用</div>
                  <div class="mt-0.5 text-sm font-medium text-emerald-300">{{ outlookPoolStatus.available }}</div>
                </div>
                <div>
                  <div class="text-[11px] text-gray-500">已注册</div>
                  <div class="mt-0.5 text-sm font-medium text-gray-300">{{ outlookPoolStatus.registered }}</div>
                </div>
                <div>
                  <div class="text-[11px] text-gray-500">暂不可用</div>
                  <div class="mt-0.5 text-sm font-medium text-amber-300">{{ outlookPoolStatus.unavailable }}</div>
                </div>
              </div>
              <div class="mt-2 text-xs text-gray-500">
                下一个可用邮箱：
                <span class="font-mono text-gray-300">{{ outlookPoolStatus.next_available_email || '无' }}</span>
              </div>
            </div>
            <div v-else-if="outlookPoolError" class="text-xs text-red-300">
              {{ outlookPoolError }}
            </div>
          </div>

          <div v-if="isMailComProvider" class="rounded-xl border border-gray-800 bg-gray-950/60 p-3 space-y-3">
            <div class="flex items-start justify-between gap-3">
              <div>
                <div class="text-sm font-medium text-white">mail.com 邮箱池</div>
                <div class="mt-1 text-xs text-gray-500">只管理注册可用邮箱池，并显示是否已注册。</div>
              </div>
              <div class="flex flex-wrap justify-end gap-2">
                <button
                  type="button"
                  @click="loadMailComPoolStatus"
                  :disabled="mailComPoolLoading"
                  class="px-3 py-1.5 rounded-lg text-xs border bg-gray-900 hover:bg-gray-800 text-gray-300 border-gray-700 transition disabled:opacity-50">
                  {{ mailComPoolLoading ? '刷新中...' : '刷新状态' }}
                </button>
                <button
                  type="button"
                  @click="openMailComImportDialog"
                  class="px-3 py-1.5 rounded-lg text-xs border bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border-emerald-500/30 transition">
                  导入邮箱
                </button>
                <button
                  type="button"
                  @click="openMailComPoolDialog"
                  class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition">
                  管理邮箱池
                </button>
              </div>
            </div>
            <div v-if="mailComPoolStatus" class="border-y border-gray-800 py-3">
              <div class="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <div><div class="text-[11px] text-gray-500">邮箱池</div><div class="mt-0.5 text-sm font-medium text-white">{{ mailComPoolStatus.total }}</div></div>
                <div><div class="text-[11px] text-gray-500">可用</div><div class="mt-0.5 text-sm font-medium text-emerald-300">{{ mailComPoolStatus.available }}</div></div>
                <div><div class="text-[11px] text-gray-500">已注册</div><div class="mt-0.5 text-sm font-medium text-blue-300">{{ mailComPoolStatus.registered || 0 }}</div></div>
                <div><div class="text-[11px] text-gray-500">未使用</div><div class="mt-0.5 text-sm font-medium text-amber-300">{{ Math.max(0, (mailComPoolStatus.total || 0) - (mailComPoolStatus.registered || 0)) }}</div></div>
              </div>
              <div class="mt-2 text-xs text-gray-500">
                下一个可用邮箱：
                <span class="font-mono text-gray-300">{{ mailComPoolStatus.next_available_email || '无' }}</span>
              </div>
            </div>
            <div v-else-if="mailComPoolError" class="text-xs text-red-300">{{ mailComPoolError }}</div>
          </div>

          <div v-if="registerProviderUsesDomains">
            <label class="block text-sm text-gray-400 mb-1">注册域名</label>
            <select
              v-if="registerForm.mode === 'single'"
              v-model="registerForm.domain"
              :disabled="registeringBusy || !registerDomainOptions.length"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option v-for="domain in registerDomainOptions" :key="domain" :value="domain">
                @{{ domain }}
              </option>
            </select>
            <div v-else class="relative">
              <button
                type="button"
                @click="toggleRegisterDomainDropdown"
                :disabled="registeringBusy || !registerDomainOptions.length"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50 flex items-center justify-between gap-3 text-left"
              >
                <span class="truncate">{{ selectedRegisterDomainsLabel }}</span>
                <span class="text-gray-500 text-xs">{{ registerDomainDropdownOpen ? '收起' : '展开' }}</span>
              </button>
              <div
                v-if="registerDomainDropdownOpen"
                class="absolute z-30 mt-2 w-full rounded-lg border border-gray-700 bg-gray-900 shadow-2xl"
              >
                <div class="flex items-center justify-between gap-3 px-3 py-2 border-b border-gray-800">
                  <div class="text-xs text-gray-400">
                    已选择 {{ selectedRegisterDomains.length }} / {{ registerDomainOptions.length }}
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      type="button"
                      @click="selectAllRegisterDomains"
                      :disabled="registerAllDomainsSelected"
                      class="px-2 py-1 rounded-md text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                      全选
                    </button>
                    <button
                      type="button"
                      @click="clearRegisterDomains"
                      :disabled="!selectedRegisterDomains.length"
                      class="px-2 py-1 rounded-md text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
                      清空
                    </button>
                  </div>
                </div>
                <div class="max-h-52 overflow-y-auto px-2 py-2 space-y-1">
                  <label
                    v-for="domain in registerDomainOptions"
                    :key="`batch-domain-${domain}`"
                    class="flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-gray-200 hover:bg-gray-800 cursor-pointer"
                  >
                    <input
                      v-model="registerForm.selectedDomains"
                      type="checkbox"
                      :value="domain"
                      class="accent-blue-500"
                    />
                    <span class="font-mono text-xs">@{{ domain }}</span>
                  </label>
                </div>
              </div>
            </div>
            <div class="mt-1 text-xs text-gray-500">
              <span v-if="registerForm.mode === 'batch'">
                已选择 {{ selectedRegisterDomains.length }} / {{ registerDomainOptions.length }} 个域名，批量注册时每个账号随机使用一个。
              </span>
              <span v-else>
                可选域名列表在“设置”页面维护。当前共 {{ registerDomainOptions.length }} 个域名。
              </span>
            </div>
          </div>

          <div v-if="isLuckMailProvider" class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">LuckMail 邮箱类型</label>
              <select
                v-model="registerForm.luckmailEmailType"
                :disabled="registeringBusy"
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
                v-model="registerForm.luckmailPreferredDomain"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              >
                <option v-for="option in luckmailDomainOptions" :key="option.value || 'auto'" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </div>
            <div class="col-span-2 text-xs text-gray-500">
              账号池为空时按这里的类型和域名自动购买；选择自动分配时由 LuckMail 按库存自动分配。
            </div>
          </div>

          <div v-if="registerForm.mode === 'batch'">
            <label class="block text-sm text-gray-400 mb-1">批量数量（1-1000）</label>
            <input
              v-model.number="registerForm.count"
              type="number"
              min="1"
              max="1000"
              :disabled="registeringBusy"
              class="w-full px-3 py-2 bg-gray-800 border rounded-lg text-sm text-white focus:outline-none"
              :class="validBatchCount ? 'border-gray-700 focus:border-blue-500' : 'border-red-500 focus:border-red-400'"
            />
            <div v-if="!validBatchCount" class="mt-1 text-xs text-red-400">批量数量不能超过 1000</div>
          </div>

          <div v-if="registerForm.mode === 'batch'" class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">并发数</label>
              <input
                v-model.number="registerForm.concurrency"
                type="number"
                min="1"
                max="20"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">间隔秒数</label>
              <input
                v-model.number="registerForm.intervalSeconds"
                type="number"
                min="0"
                step="0.5"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div v-if="registerForm.mode === 'batch'" class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">随机抖动最小值</label>
              <input
                v-model.number="registerForm.jitterMinSeconds"
                type="number"
                min="0"
                step="0.5"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">随机抖动最大值</label>
              <input
                v-model.number="registerForm.jitterMaxSeconds"
                type="number"
                min="0"
                step="0.5"
                :disabled="registeringBusy"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">邮箱前缀</label>
            <div class="flex items-center rounded-lg border border-gray-700 bg-gray-800">
              <input
                v-model.trim="registerForm.prefix"
                type="text"
                placeholder="例如 prefix"
                :disabled="registeringBusy"
                class="flex-1 px-3 py-2 bg-transparent text-sm text-white focus:outline-none"
              />
              <div class="px-3 text-xs text-gray-500 border-l border-gray-700">
                +5位随机字母数字 {{ registerDomainSuffixLabel }}
              </div>
            </div>
          </div>

          <div>
            <label class="block text-sm text-gray-400 mb-1">密码</label>
            <input
              v-model.trim="registerForm.password"
              type="text"
              placeholder="留空自动生成"
              :disabled="registeringBusy"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>

          <div class="rounded-lg border border-gray-800 bg-gray-800/40 px-3 py-3 text-xs text-gray-400 space-y-1">
            <div>预览邮箱：<span class="font-mono text-gray-200">{{ registerPreviewEmail }}</span></div>
            <div v-if="isLuckMailProvider">LuckMail 购买：<span class="text-gray-200">{{ luckmailPurchaseLabel }}</span></div>
            <div>密码：<span class="text-gray-200">{{ registerForm.password || '自动随机生成' }}</span></div>
            <div>行为：<span class="text-gray-200">{{ registerBehaviorLabel }}</span></div>
            <div v-if="isPhoneCpaFlow || registerForm.postRegisterOauth">
              {{ isPhoneCpaFlow ? '手机号配置' : 'OAuth 手机号' }}：
              <span class="text-gray-200">{{ oauthPhoneSmsProviderLabel }} / {{ oauthPhoneSmsCountryLabel }} / 价格上限 {{ oauthPhoneSmsMaxPriceLabel }}</span>
            </div>
            <div>代理：<span class="text-gray-200">{{ registerProxyLabel }}</span></div>
            <div v-if="registerForm.mode === 'batch' && registerProviderUsesDomains">域名轮换：<span class="text-gray-200">{{ selectedRegisterDomainsLabel }}</span></div>
            <div v-if="registerForm.mode === 'batch'">批量策略：<span class="text-gray-200">并发 {{ validConcurrency }}，固定间隔 {{ validIntervalSeconds }}s，随机抖动 {{ validJitterMinSeconds }}-{{ validJitterMaxSeconds }}s</span></div>
          </div>

        </div>

        <div class="min-h-[520px] xl:min-h-0">
          <section class="flex h-full min-h-0 flex-col rounded-xl border border-gray-800 bg-gray-950/60 p-4">
            <div class="shrink-0 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <h3 class="text-white font-semibold">注册日志</h3>
                <div class="text-xs text-gray-500 mt-0.5">显示最近的注册相关日志</div>
              </div>
              <button
                @click="loadRegisterLogs"
                :disabled="logsLoading"
                class="shrink-0 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-sm text-gray-200 transition hover:bg-gray-700 disabled:opacity-50">
                {{ logsLoading ? '加载中...' : '刷新日志' }}
              </button>
            </div>
            <div ref="logsContainer" class="mt-4 min-h-0 flex-1 overflow-y-auto rounded-lg border border-gray-800 bg-gray-950 p-3 space-y-2">
              <div v-if="!registerLogs.length" class="text-sm text-gray-500">暂无注册日志</div>
              <div
                v-for="(log, idx) in registerLogs"
                :key="idx"
                class="rounded-lg border border-gray-800 bg-gray-900/70 px-3 py-2">
                <div class="flex items-center justify-between gap-3">
                  <span class="text-xs font-mono text-gray-500">{{ fmtLogTime(log.time) }}</span>
                  <span class="text-[11px] uppercase tracking-wide" :class="logLevelClass(log.level)">{{ log.level }}</span>
                </div>
                <div class="mt-1 text-sm text-gray-200 whitespace-pre-wrap break-words">{{ log.message }}</div>
              </div>
            </div>
          </section>
        </div>
      </div>
    </section>
  </div>

  <Teleport to="body">
    <div
      v-if="outlookPoolDialogOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      @click.self="closeOutlookPoolDialog"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="outlook-pool-title"
        class="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-2xl"
      >
        <header class="flex shrink-0 items-start justify-between gap-4 border-b border-gray-800 px-5 py-4">
          <div>
            <h3 id="outlook-pool-title" class="text-base font-semibold text-white">管理 {{ accountPoolProviderLabel }} 邮箱池</h3>
            <p class="mt-1 text-xs text-gray-500">查看邮箱可用状态，批量删除不再使用的邮箱池记录。</p>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              :disabled="outlookPoolLoading || outlookPoolDeleting"
              class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50"
              @click="loadOutlookPoolStatus"
            >
              {{ outlookPoolLoading ? '刷新中...' : '刷新' }}
            </button>
            <button
              type="button"
              :disabled="outlookPoolDeleting"
              class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50"
              @click="closeOutlookPoolDialog"
            >
              关闭
            </button>
          </div>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <div v-if="outlookPoolStatus" class="grid grid-cols-2 border-b border-gray-800 sm:grid-cols-4">
            <div class="border-r border-gray-800 px-4 py-3 last:border-r-0">
              <div class="text-xs text-gray-500">邮箱池</div>
              <div class="mt-1 text-xl font-semibold text-white">{{ outlookPoolStatus.total }}</div>
            </div>
            <div class="border-r border-gray-800 px-4 py-3 last:border-r-0">
              <div class="text-xs text-gray-500">可用</div>
              <div class="mt-1 text-xl font-semibold text-emerald-300">{{ outlookPoolStatus.available }}</div>
            </div>
            <div class="border-r border-gray-800 px-4 py-3 last:border-r-0">
              <div class="text-xs text-gray-500">已注册</div>
              <div class="mt-1 text-xl font-semibold text-gray-300">{{ outlookPoolStatus.registered }}</div>
            </div>
            <div class="px-4 py-3">
              <div class="text-xs text-gray-500">暂不可用</div>
              <div class="mt-1 text-xl font-semibold text-amber-300">{{ outlookPoolStatus.unavailable }}</div>
            </div>
          </div>

          <div class="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-3">
            <div class="min-w-0 text-xs text-gray-500">
              下一个可用邮箱：
              <span class="font-mono text-gray-300">{{ outlookPoolStatus?.next_available_email || '无' }}</span>
            </div>
          </div>

          <div class="flex flex-wrap items-center gap-2 border-b border-gray-800 px-5 py-3">
            <span class="text-xs text-gray-500">筛选：</span>
            <button
              v-for="option in outlookPoolStatusFilterOptions"
              :key="option.value"
              type="button"
              :aria-pressed="outlookPoolStatusFilter === option.value"
              :disabled="outlookPoolDeleting"
              class="rounded-full border px-3 py-1.5 text-xs transition disabled:opacity-50"
              :class="outlookPoolStatusFilter === option.value
                ? 'border-blue-500/40 bg-blue-600/20 text-blue-300'
                : 'border-gray-700 bg-gray-950 text-gray-400 hover:bg-gray-800 hover:text-gray-200'"
              @click="outlookPoolStatusFilter = option.value"
            >
              <span>{{ option.label }}</span>
              <span class="ml-1 font-mono text-[11px] opacity-75">{{ option.count }}</span>
            </button>
          </div>

          <div class="flex items-center justify-between gap-3 border-b border-gray-800 px-5 py-3">
            <div class="min-w-0 text-xs text-gray-500">
              当前显示：
              <span class="font-mono text-gray-300">{{ outlookPoolVisibleEmails.length }}</span>
              <span class="text-gray-600"> / </span>
              <span class="font-mono text-gray-400">{{ outlookPoolStatus?.total || 0 }}</span>
            </div>
            <div class="flex shrink-0 items-center gap-3">
              <label class="inline-flex items-center gap-2 text-xs text-gray-400">
                <input
                  type="checkbox"
                  :checked="outlookPoolAllVisibleSelected"
                  :disabled="outlookPoolDeleting || !outlookPoolVisibleEmails.length"
                  class="h-3.5 w-3.5 rounded border-gray-700 bg-gray-900 text-blue-500 focus:ring-blue-500"
                  @change="toggleOutlookPoolVisible($event.target.checked)"
                />
                当前列表全选
              </label>
              <button
                type="button"
                :disabled="outlookPoolDeleting || outlookPoolSelectedCount === 0"
                class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
                @click="deleteSelectedOutlookPoolEmails"
              >
                {{ outlookPoolDeleting ? '删除中...' : `删除所选 (${outlookPoolSelectedCount})` }}
              </button>
            </div>
          </div>

          <div v-if="outlookPoolError" class="mx-5 mt-4 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {{ outlookPoolError }}
          </div>

          <div v-if="outlookPoolVisibleAccounts.length" class="divide-y divide-gray-800">
            <div
              v-for="account in outlookPoolVisibleAccounts"
              :key="account.email"
              class="flex items-center justify-between gap-3 px-5 py-2.5 text-xs"
            >
              <label class="flex min-w-0 flex-1 items-center gap-2">
                <input
                  type="checkbox"
                  :checked="outlookPoolSelectedSet.has(account.email)"
                  :disabled="outlookPoolDeleting"
                  class="h-3.5 w-3.5 shrink-0 rounded border-gray-700 bg-gray-900 text-blue-500 focus:ring-blue-500"
                  @change="toggleOutlookPoolEmail(account.email, $event.target.checked)"
                />
                <span class="min-w-0 truncate font-mono text-gray-300">{{ account.email }}</span>
              </label>
              <span class="shrink-0" :class="outlookPoolAccountStatusClass(account.status)">
                {{ outlookPoolAccountStatusLabel(account.status) }}
              </span>
            </div>
          </div>
          <div v-else-if="outlookPoolStatus?.accounts?.length && !outlookPoolLoading" class="px-5 py-8 text-center text-sm text-gray-500">
            当前筛选暂无记录
          </div>
          <div v-else-if="!outlookPoolLoading" class="px-5 py-8 text-center text-sm text-gray-500">
            邮箱池暂无记录
          </div>
        </div>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="mailComPoolDialogOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" @click.self="closeMailComPoolDialog">
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="mailcom-pool-title"
        class="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-2xl"
      >
        <header class="flex shrink-0 items-start justify-between gap-4 border-b border-gray-800 px-5 py-4">
          <div>
            <h3 id="mailcom-pool-title" class="text-base font-semibold text-white">管理 mail.com 邮箱池</h3>
            <p class="mt-1 text-xs text-gray-500">查看邮箱状态和是否已注册，可删除不需要的邮箱。</p>
          </div>
          <div class="flex items-center gap-2">
            <button
              type="button"
              :disabled="mailComPoolLoading || mailComPoolDeleting"
              class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50"
              @click="loadMailComPoolStatus"
            >
              {{ mailComPoolLoading ? '刷新中...' : '刷新' }}
            </button>
            <button
              type="button"
              :disabled="mailComPoolDeleting"
              class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50"
              @click="closeMailComPoolDialog"
            >
              关闭
            </button>
          </div>
        </header>

        <div class="min-h-0 flex-1 overflow-y-auto">
          <div v-if="mailComPoolStatus" class="grid grid-cols-2 border-b border-gray-800 sm:grid-cols-4">
            <div class="border-r border-gray-800 px-4 py-3 last:border-r-0">
              <div class="text-xs text-gray-500">邮箱池</div>
              <div class="mt-1 text-xl font-semibold text-white">{{ mailComPoolStatus.total }}</div>
            </div>
            <div class="border-r border-gray-800 px-4 py-3 last:border-r-0">
              <div class="text-xs text-gray-500">可用</div>
              <div class="mt-1 text-xl font-semibold text-emerald-300">{{ mailComPoolStatus.available }}</div>
            </div>
            <div class="px-4 py-3">
              <div class="text-xs text-gray-500">已注册</div>
              <div class="mt-1 text-xl font-semibold text-blue-300">{{ mailComPoolStatus.registered || 0 }}</div>
            </div>
            <div class="px-4 py-3">
              <div class="text-xs text-gray-500">未使用</div>
              <div class="mt-1 text-xl font-semibold text-amber-300">{{ Math.max(0, (mailComPoolStatus.total || 0) - (mailComPoolStatus.registered || 0)) }}</div>
            </div>
          </div>

          <div class="flex flex-wrap items-center justify-between gap-3 border-b border-gray-800 px-5 py-3">
            <div class="min-w-0 text-xs text-gray-500">
              下一个可用邮箱：
              <span class="font-mono text-gray-300">{{ mailComPoolStatus?.next_available_email || '无' }}</span>
            </div>
            <div class="flex shrink-0 flex-wrap items-center gap-3">
              <label class="inline-flex items-center gap-2 text-xs text-gray-400">
                <input
                  type="checkbox"
                  :checked="mailComPoolAllVisibleSelected"
                  :disabled="mailComPoolDeleting || !mailComPoolVisibleEmails.length"
                  class="h-3.5 w-3.5 rounded border-gray-700 bg-gray-900 text-blue-500 focus:ring-blue-500"
                  @change="toggleMailComPoolVisible($event.target.checked)"
                />
                当前列表全选
              </label>
              <button
                type="button"
                :disabled="mailComPoolDeleting || mailComPoolSelectedCount === 0"
                class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
                @click="deleteSelectedMailComPoolEmails"
              >
                {{ mailComPoolDeleting ? '删除中...' : `删除所选 (${mailComPoolSelectedCount})` }}
              </button>
            </div>
          </div>

          <div v-if="mailComPoolError" class="mx-5 mt-4 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {{ mailComPoolError }}
          </div>

          <div v-if="mailComPoolItems.length" class="overflow-x-auto">
            <table class="min-w-full divide-y divide-gray-800 text-xs">
              <thead class="bg-gray-950/40 text-left text-gray-500">
                <tr>
                  <th class="px-5 py-3">
                    <input
                      type="checkbox"
                      :checked="mailComPoolAllVisibleSelected"
                      :disabled="mailComPoolDeleting || !mailComPoolVisibleEmails.length"
                      class="h-3.5 w-3.5 rounded border-gray-700 bg-gray-900 text-blue-500 focus:ring-blue-500"
                      @change="toggleMailComPoolVisible($event.target.checked)"
                    />
                  </th>
                  <th class="px-5 py-3 font-medium">邮箱</th>
                  <th class="px-5 py-3 font-medium">邮箱状态</th>
                  <th class="px-5 py-3 font-medium">是否已注册</th>
                  <th class="px-5 py-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-800">
                <tr v-for="item in mailComPoolItems" :key="item.email" class="text-gray-300">
                  <td class="px-5 py-3 align-middle">
                    <input
                      type="checkbox"
                      :checked="mailComPoolSelectedEmails.includes(normalizeMailComEmail(item.email))"
                      :disabled="mailComPoolDeleting"
                      class="h-3.5 w-3.5 rounded border-gray-700 bg-gray-900 text-blue-500 focus:ring-blue-500"
                      @change="toggleMailComPoolEmail(item.email, $event.target.checked)"
                    />
                  </td>
                  <td class="px-5 py-3 align-middle font-mono">{{ item.email || '-' }}</td>
                  <td class="px-5 py-3 align-middle">
                    <div class="space-y-1">
                      <span :class="item.status === 'enabled' ? 'text-emerald-300' : 'text-gray-400'">
                        {{ item.status === 'enabled' ? '启用' : '禁用' }}
                      </span>
                    </div>
                  </td>
                  <td class="px-5 py-3 align-middle">
                    <span :class="item.registered ? 'text-blue-300' : 'text-gray-400'">
                      {{ item.registered ? '已注册' : '未注册' }}
                    </span>
                  </td>
                  <td class="px-5 py-3 align-middle">
                    <button
                      type="button"
                      :disabled="mailComPoolDeleting"
                      class="rounded-lg border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-xs text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-50"
                      @click="mailComPoolSelectedEmails = item.email ? [normalizeMailComEmail(item.email)] : []; deleteSelectedMailComPoolEmails()"
                    >
                      删除
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else-if="!mailComPoolLoading" class="px-5 py-8 text-center text-sm text-gray-500">
            邮箱池暂无记录
          </div>
        </div>
      </section>
    </div>
  </Teleport>

  <Teleport to="body">
    <div v-if="mailComImportDialogOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div class="w-full max-w-3xl rounded-2xl border border-gray-800 bg-gray-950 p-5 shadow-2xl">
        <div class="flex items-center justify-between">
          <h3 class="text-lg font-semibold text-white">导入 mail.com 邮箱</h3>
          <button type="button" class="text-gray-400 hover:text-white" @click="closeMailComImportDialog">×</button>
        </div>
        <p class="mt-2 text-xs text-gray-500">格式：邮箱----邮箱密码，每行一个。这里导入的是未注册 ChatGPT 的 mail.com 邮箱。</p>
        <textarea v-model="mailComImportContent" rows="10" spellcheck="false" class="mt-3 w-full rounded-lg border border-gray-700 bg-gray-900 p-3 font-mono text-xs text-gray-100 focus:border-blue-500 focus:outline-none" placeholder="user@mail.com----mail-password"></textarea>
        <div v-if="mailComImportResult" class="mt-3 rounded-lg px-3 py-2 text-xs" :class="mailComImportResultOk ? 'border border-emerald-500/20 bg-emerald-500/10 text-emerald-300' : 'border border-red-500/20 bg-red-500/10 text-red-300'">
          {{ mailComImportResult }}
        </div>
        <div class="mt-4 flex justify-end gap-2">
          <button type="button" @click="closeMailComImportDialog" class="rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-300 hover:bg-gray-800">取消</button>
          <button type="button" @click="importMailComAccounts" :disabled="mailComPoolLoading" class="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white hover:bg-emerald-500 disabled:opacity-50">
            {{ mailComPoolLoading ? '导入中...' : '导入邮箱池' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>

  <Teleport to="body">
    <div
      v-if="outlookImportDialogOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      @click.self="closeOutlookImportDialog"
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="outlook-import-title"
        class="w-full max-w-2xl overflow-hidden rounded-xl border border-gray-800 bg-gray-900 shadow-2xl"
      >
        <header class="flex items-start justify-between gap-4 border-b border-gray-800 px-5 py-4">
          <div>
            <h3 id="outlook-import-title" class="text-base font-semibold text-white">导入 {{ accountPoolProviderLabel }} 邮箱</h3>
            <p class="mt-1 text-xs text-gray-500">{{ accountPoolImportHelp }}</p>
          </div>
          <button
            type="button"
            :disabled="outlookImporting"
            class="rounded-lg border border-gray-700 bg-gray-800 px-3 py-1.5 text-xs text-gray-300 hover:bg-gray-700 disabled:opacity-50"
            @click="closeOutlookImportDialog"
          >
            关闭
          </button>
        </header>

        <div class="space-y-4 p-5">
          <div class="flex flex-wrap items-center gap-3">
            <label class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-gray-700 bg-gray-800 px-3 py-2 text-xs text-gray-300 transition hover:bg-gray-700">
              <input
                type="file"
                accept=".txt,text/plain"
                class="hidden"
                :disabled="outlookImporting"
                @change="handleOutlookImportFile"
              />
              选择 txt 文件
            </label>
            <span class="min-w-0 truncate text-xs text-gray-500">{{ outlookImportFilename || '未选择文件' }}</span>
          </div>

          <textarea
            v-model="outlookImportContent"
            :disabled="outlookImporting"
            rows="10"
            spellcheck="false"
            :placeholder="accountPoolImportPlaceholder"
            class="w-full resize-y rounded-lg border border-gray-700 bg-gray-950 px-3 py-2 font-mono text-xs text-gray-100 outline-none placeholder:text-gray-600 focus:border-blue-500 disabled:opacity-60"
          ></textarea>

          <div v-if="outlookImportResult" class="rounded-lg border px-3 py-2 text-xs" :class="outlookImportResultClass">
            {{ outlookImportResult }}
          </div>
        </div>

        <footer class="flex justify-end gap-2 border-t border-gray-800 px-5 py-4">
          <button
            type="button"
            :disabled="outlookImporting"
            class="rounded-lg border border-gray-700 bg-gray-800 px-4 py-2 text-sm text-gray-300 hover:bg-gray-700 disabled:opacity-50"
            @click="closeOutlookImportDialog"
          >
            取消
          </button>
          <button
            type="button"
            :disabled="outlookImporting || !outlookImportContent.trim()"
            class="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500 disabled:opacity-50"
            @click="importOutlookAccounts"
          >
            {{ outlookImporting ? '导入中...' : '确认导入' }}
          </button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { api } from '../api.js'
import { accountPoolAllAccounts, accountPoolVisibleAccounts as resolveAccountPoolVisibleAccounts } from '../accountPoolStatus.js'
import { bindCountryOptions } from '../bindLinkPayload.js'

const REGISTER_FORM_STORAGE_KEY = 'autotoken_register_form_v1'
const OAUTH_PHONE_SMS_COUNTRIES_CACHE_KEY = 'autotoken_oauth_phone_sms_countries_v2'
const OAUTH_PHONE_SMS_COUNTRIES_CACHE_TTL_MS = 30 * 60 * 1000

const props = defineProps({
  runningTask: Object,
  adminStatus: {
    type: Object,
    default: null,
  },
})

const emit = defineEmits(['task-started', 'refresh'])

const message = ref('')
const messageClass = ref('')
const registerConfigLoading = ref(false)
const registeringAccount = ref(false)
const registerDomainOptions = ref([])
const registerDomainDropdownOpen = ref(false)
const outlookImportContent = ref('')
const outlookImportFilename = ref('')
const outlookImporting = ref(false)
const outlookImportResult = ref('')
const outlookImportResultOk = ref(true)
const outlookImportDialogOpen = ref(false)
const outlookPoolDialogOpen = ref(false)
const outlookPoolLoading = ref(false)
const outlookPoolDeleting = ref(false)
const outlookPoolError = ref('')
const outlookPoolStatus = ref(null)
const outlookPoolSelectedEmails = ref([])
const outlookPoolStatusFilter = ref('all')
const mailComPoolStatus = ref(null)
const mailComPoolLoading = ref(false)
const mailComPoolError = ref('')
const mailComImportDialogOpen = ref(false)
const mailComImportContent = ref('')
const mailComImportResult = ref('')
const mailComImportResultOk = ref(true)
const mailComPoolDialogOpen = ref(false)
const mailComPoolSelectedEmails = ref([])
const mailComPoolDeleting = ref(false)
const registerLogs = ref([])
const logsLoading = ref(false)
const logsContainer = ref(null)
const registerCancelBusy = ref(false)
const registerCancelRequested = ref(false)
const oauthPhoneSmsLoading = ref(false)
const oauthPhoneSmsCountriesLoading = ref(false)
const oauthPhoneSmsCountryError = ref('')
const oauthPhoneSmsCountrySearch = ref('')
const oauthPhoneSmsCountryDropdownOpen = ref(false)
const oauthPhoneSmsCountryRequests = new Map()
const oauthPhoneSmsProviderOptions = ref([
  { value: 'phone_pool', label: '手机号池', configured: true },
  { value: 'hero_sms', label: 'hero-sms', configured: false },
  { value: 'smsbower', label: 'smsbower', configured: false },
  { value: 'smscloud', label: 'SMSCloud', configured: false },
  { value: 'oasis', label: 'Oasis CDK', configured: false },
  { value: 'tujie', label: 'TuJie CDK', configured: false },
])
const oauthPhoneSmsConfig = ref({})
const oauthPhoneSmsConfigLoaded = ref(false)
const registerStats = ref({
  task: { total: 0, ok: 0, failed: 0, successRate: 0 },
  today: { total: 0, ok: 0, failed: 0, successRate: 0 },
})
const statsMode = ref('task')
const registerForm = ref({
  mode: 'single',
  registrationFlow: 'standard',
  count: 1,
  concurrency: 3,
  intervalSeconds: 12,
  jitterMinSeconds: 8,
  jitterMaxSeconds: 20,
  domain: '',
  selectedDomains: [],
  mailProvider: '',
  luckmailEmailType: '',
  luckmailPreferredDomain: '',
  luckmailPreferredDomains: [],
  prefix: '',
  password: '',
  protocolRegister: false,
  useRoxyBrowser: false,
  postRegisterOauth: false,
  enableTotpMfa: false,
  phoneOnly: false,
  oauthPhoneSmsProvider: 'phone_pool',
  oauthPhoneSmsCountry: '187',
  oauthPhoneSmsMaxPrice: '',
  oauthOasisSmsCdks: '',
  proxyUrl: '',
  proxyApiEnabled: false,
  proxyApiProvider: '1024proxy',
  proxyApiCountry: 'JP',
})
const mailProviderLoading = ref(false)
const mailProviderOptions = ref([])
let savedLuckmailEmailType = false
let savedLuckmailPreferredDomain = false
let savedOauthPhoneSmsCountries = {}
let savedOauthPhoneSmsMaxPrices = {}
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
const oauthPhoneSmsCountryFallbackOptions = {
  phone_pool: [],
  hero_sms: [
    { value: 'all', label: '全部国家 / 不限制' },
    { value: '187', label: '美国 / 187' },
    { value: '6', label: '印度尼西亚 / 6' },
    { value: '33', label: '哥伦比亚 / 33' },
  ],
  smsbower: [
    { value: 'all', label: '全部国家 / 不限制' },
    { value: '187', label: '美国 / 187' },
    { value: '44', label: '英国 / 44' },
    { value: '6', label: '印度尼西亚 / 6' },
    { value: '33', label: '哥伦比亚 / 33' },
  ],
  smscloud: [
    { value: 'all', label: '全部国家 / 不限制' },
    { value: '187', label: '美国 / 187' },
    { value: '44', label: '英国 / 44' },
    { value: '6', label: '印度尼西亚 / 6' },
    { value: '33', label: '哥伦比亚 / 33' },
  ],
  oasis: [],
  tujie: [],
}
const oauthPhoneSmsCountryOptions = ref([
  { value: 'all', label: '全部国家 / 不限制' },
  { value: '187', label: '美国 (+1) / 187' },
  { value: '6', label: '印度尼西亚 (+62) / 6' },
  { value: '33', label: '哥伦比亚 (+57) / 33' },
])
const OAUTH_PHONE_PROVIDER_VALUES = ['phone_pool', 'hero_sms', 'smsbower', 'smscloud', 'oasis', 'tujie']
const OAUTH_PHONE_DYNAMIC_PRICE_PROVIDERS = ['hero_sms', 'smsbower', 'smscloud']
const OAUTH_PHONE_CDK_PROVIDERS = ['oasis', 'tujie']

function isCdkOAuthPhoneProvider(provider) {
  return OAUTH_PHONE_CDK_PROVIDERS.includes(String(provider || ''))
}

function oauthPhoneSmsCountryDisabled(provider) {
  const normalized = String(provider || 'phone_pool')
  return normalized === 'phone_pool' || isCdkOAuthPhoneProvider(normalized)
}

const registeringBusy = computed(() => !!props.runningTask)
const validBatchCount = computed(() => {
  const count = Number(registerForm.value.count || 0)
  return registerForm.value.mode === 'single' ? true : count >= 1 && count <= 1000
})
const validConcurrency = computed(() => {
  const value = Number(registerForm.value.concurrency || 0)
  return Math.max(1, Math.min(20, value || 3))
})
const validIntervalSeconds = computed(() => {
  const value = Number(registerForm.value.intervalSeconds ?? 12)
  return Math.max(0, value)
})
const validJitterMinSeconds = computed(() => {
  const value = Number(registerForm.value.jitterMinSeconds ?? 8)
  return Math.max(0, value)
})
const validJitterMaxSeconds = computed(() => {
  const value = Number(registerForm.value.jitterMaxSeconds ?? 20)
  return Math.max(validJitterMinSeconds.value, value)
})
const selectedRegisterDomains = computed(() => {
  const source = registerForm.value.mode === 'batch'
    ? registerForm.value.selectedDomains
    : [registerForm.value.domain]
  const seen = new Set()
  return (Array.isArray(source) ? source : [])
    .map(domain => String(domain || '').trim().replace(/^@/, ''))
    .filter(domain => {
      if (!domain || seen.has(domain)) return false
      if (registerDomainOptions.value.length && !registerDomainOptions.value.includes(domain)) return false
      seen.add(domain)
      return true
    })
})
const selectedRegisterDomainsLabel = computed(() => {
  const domains = selectedRegisterDomains.value
  if (!domains.length) return '未选择'
  if (domains.length <= 3) return domains.map(domain => `@${domain}`).join(' / ')
  return `${domains.slice(0, 3).map(domain => `@${domain}`).join(' / ')} 等 ${domains.length} 个`
})
const registerAllDomainsSelected = computed(() => {
  if (!registerDomainOptions.value.length) return false
  const selected = new Set(selectedRegisterDomains.value)
  return registerDomainOptions.value.every(domain => selected.has(domain))
})
const isLuckMailProvider = computed(() => registerForm.value.mailProvider === 'luckmail')
const isOutlookProvider = computed(() => registerForm.value.mailProvider === 'outlook')
const isICloudProvider = computed(() => registerForm.value.mailProvider === 'icloud')
const isGenericApiProvider = computed(() => registerForm.value.mailProvider === 'generic-api')
const isOutlookLikePoolProvider = computed(() => isOutlookProvider.value || isICloudProvider.value || isGenericApiProvider.value)
const isMailComProvider = computed(() => String(registerForm.value.mailProvider || '').trim().toLowerCase() === 'mail.com')
const isPhoneCpaFlow = computed(() => registerForm.value.registrationFlow === 'phone_cpa')
const registerProviderUsesPool = computed(() => isLuckMailProvider.value || isOutlookLikePoolProvider.value || isMailComProvider.value)
const registerProviderUsesDomains = computed(() => !registerProviderUsesPool.value && !isPhoneCpaFlow.value)
function normalizeRegisterProxyCountry(value) {
  return String(value || 'JP').trim().toUpperCase().replace(/[^A-Z]/g, '').slice(0, 2) || 'JP'
}
const registerProxyExtraCountryOptions = [
  { country: 'BR', currency: 'BRL', label: '巴西（BRL）' },
  { country: 'GB', currency: 'GBP', label: '英国（GBP）' },
  { country: 'IS', currency: 'ISK', label: '冰岛（ISK）' },
  { country: 'TH', currency: 'THB', label: '泰国（THB）' },
  { country: 'TR', currency: 'TRY', label: '土耳其（TRY）' },
  { country: 'KR', currency: 'KRW', label: '韩国（KRW）' },
]
const registerProxyCountryOptions = computed(() => {
  const options = []
  const seen = new Set()
  for (const option of [...bindCountryOptions, ...registerProxyExtraCountryOptions]) {
    const country = normalizeRegisterProxyCountry(option.country)
    if (!country || seen.has(country)) continue
    seen.add(country)
    options.push({ ...option, country })
  }
  const selected = normalizeRegisterProxyCountry(registerForm.value.proxyApiCountry)
  if (!options.some(option => option.country === selected)) {
    options.push({ country: selected, currency: '', label: `${selected}` })
  }
  return options
})
const registerProviderPoolMessage = computed(() => {
  if (isLuckMailProvider.value) return 'LuckMail 使用已购邮箱池或 API 购买邮箱，注册域名选择不参与本次任务。'
  if (isOutlookProvider.value) return 'Outlook 使用已配置的微软邮箱账号池，注册域名选择不参与本次任务。'
  if (isICloudProvider.value) return 'iCloud 使用已配置的 iCloud 邮箱池和收码链接，注册域名选择不参与本次任务。'
  if (isGenericApiProvider.value) return '通用API 使用已配置的邮箱池和收码链接，注册域名选择不参与本次任务。'
  if (isMailComProvider.value) return 'mail.com 邮箱池中选择'
  return ''
})
const accountPoolProviderLabel = computed(() => {
  if (isICloudProvider.value) return 'iCloud'
  if (isGenericApiProvider.value) return '通用API'
  return 'Outlook'
})
const accountPoolProviderDescription = computed(() =>
  isICloudProvider.value
    ? '导入 iCloud 邮箱和收码链接；再次打开页面时将从首个可用邮箱继续注册。'
    : isGenericApiProvider.value
      ? '导入任意邮箱和收码链接；再次打开页面时将从首个可用邮箱继续注册。'
      : '邮箱池会持久化保存；再次打开页面时将从首个可用邮箱继续注册。'
)
const accountPoolImportHelp = computed(() =>
  isICloudProvider.value
    ? '支持 txt 文件或直接粘贴，一行一个 iCloud 邮箱和收码链接。'
    : isGenericApiProvider.value
      ? '支持 txt 文件或直接粘贴，一行一个“邮箱----收码链接”。'
      : '支持 txt 文件或直接粘贴，一行一个邮箱账号。'
)
const accountPoolImportPlaceholder = computed(() =>
  isICloudProvider.value
    ? '例如：\nuser@icloud.com----https://icloud-api.top/show/xxx/user@icloud.com'
    : isGenericApiProvider.value
      ? '例如：\nnanette_hayspjq@birdlover.com----https://milwaukee-testimony-jackets-indication.trycloudflare.com/code/Kq6WBn3fb7JmfA5OubuzljzZbekYeSPJQKI0JEhf-nA'
      : '例如：\nuser@hotmail.com----https://mailapi.icu/key?type=html&orderNo=xxxx\nuser@outlook.com----password----client_id----refresh_token'
)
const registerDomainSuffixLabel = computed(() => {
  if (isLuckMailProvider.value) return '@LuckMail'
  if (isOutlookProvider.value) return '@Outlook账号池'
  if (isICloudProvider.value) return '@iCloud账号池'
  if (isGenericApiProvider.value) return '@通用API账号池'
  if (registerForm.value.mode === 'batch') {
    return selectedRegisterDomains.value.length
      ? `@随机域名(${selectedRegisterDomains.value.length})`
      : '@domain.com'
  }
  return `@${registerForm.value.domain || 'domain.com'}`
})
const registerPreviewEmail = computed(() => {
  const prefix = registerForm.value.prefix ? `${registerForm.value.prefix}a8k3p` : '__random__'
  const domain = registerForm.value.mode === 'batch'
    ? (selectedRegisterDomains.value[0] || 'domain.com')
    : (registerForm.value.domain || 'domain.com')
  if (isLuckMailProvider.value) return 'LuckMail邮箱池中选择'
  if (isOutlookProvider.value) return 'Outlook邮箱池中选择'
  if (isICloudProvider.value) return 'iCloud邮箱池中选择'
  if (isGenericApiProvider.value) return '通用API邮箱池中选择'
  if (isMailComProvider.value) return 'mail.com邮箱池中选择'
  return `${prefix}@${domain}`
})
const luckmailPurchaseLabel = computed(() => {
  const emailType = registerForm.value.luckmailEmailType || 'ms_imap'
  const preferredDomain = String(registerForm.value.luckmailPreferredDomain || '').trim().replace(/^@/, '')
  const domain = preferredDomain ? `@${preferredDomain}` : '自动分配'
  return `${emailType} / ${domain}`
})
const registerBehaviorLabel = computed(() => {
  if (isPhoneCpaFlow.value) return '先用手机号注册 ChatGPT，再绑定当前邮件供应商邮箱并生成 OAuth 凭证'
  const registerMode = registerForm.value.useRoxyBrowser
    ? 'Roxy Browser注册'
    : registerForm.value.protocolRegister ? '协议注册' : '浏览器注册'
  const flowDesc = registerForm.value.phoneOnly && isPhoneCpaFlow.value
    ? '仅手机注册，不绑定邮箱、不 OAuth'
    : registerForm.value.postRegisterOauth
      ? '免费账号，随后执行 OAuth 并保留凭证'
      : '免费账号并保存 auth_session'
  return `${registerMode}${flowDesc}`
})
const registerProxyApiHelp = computed(() => {
  const country = normalizeRegisterProxyCountry(registerForm.value.proxyApiCountry)
  const countryLabel = registerProxyCountryOptions.value.find(option => option.country === country)?.label || country
  if (registerForm.value.proxyApiProvider === 'cliproxy') {
    return `运行时使用 Cliproxy ${countryLabel} 白名单 API，每个账号注册前提取一条。`
  }
  return `运行时使用 1024proxy ${countryLabel} 白名单 API，每个账号注册前提取一条。`
})
const registerProxyLabel = computed(() => {
  const fixedProxy = String(registerForm.value.proxyUrl || '').trim()
  if (registerForm.value.proxyApiEnabled) {
    const country = normalizeRegisterProxyCountry(registerForm.value.proxyApiCountry)
    return `动态 API / ${registerForm.value.proxyApiProvider || '1024proxy'} / ${country}`
  }
  return fixedProxy ? '指定代理' : '未启用'
})
const oauthPhoneSmsCountryOptionsForSelect = computed(() => {
  const selected = String(registerForm.value.oauthPhoneSmsCountry || '').trim()
  const query = String(oauthPhoneSmsCountrySearch.value || '').trim().toLowerCase()
  const sourceOptions = oauthPhoneSmsCountryOptions.value || []
  const selectedOption = sourceOptions.find(option => option.value === selected)
  const selectedLabel = String(selectedOption?.label || '').trim().toLowerCase()
  let options = sourceOptions
  if (query && query !== selectedLabel) {
    options = sourceOptions.filter(option => {
      const text = `${option.value} ${option.label}`.toLowerCase()
      return text.includes(query)
    })
  }
  if (selected && !options.some(option => option.value === selected)) {
    const known = sourceOptions.find(option => option.value === selected)
    options = [{ value: selected, label: known?.label || `当前配置 / ${selected}` }, ...options]
  }
  return options
})
const selectedOAuthPhoneSmsCountryOption = computed(() => {
  const selected = String(registerForm.value.oauthPhoneSmsCountry || '').trim()
  return (oauthPhoneSmsCountryOptions.value || []).find(item => item.value === selected) || null
})
const oauthPhoneSmsProviderLabel = computed(() => {
  const provider = String(registerForm.value.oauthPhoneSmsProvider || 'phone_pool')
  const option = oauthPhoneSmsProviderOptions.value.find(item => item.value === provider)
  return option?.label || provider
})
const oauthPhoneSmsCountryLabel = computed(() => {
  if (registerForm.value.oauthPhoneSmsProvider === 'phone_pool') return '按手机号池'
  if (isCdkOAuthPhoneProvider(registerForm.value.oauthPhoneSmsProvider)) return '由 CDK 分配'
  const option = selectedOAuthPhoneSmsCountryOption.value
  return option?.label || registerForm.value.oauthPhoneSmsCountry || '美国 (+1) / 187'
})
const oauthPhoneSmsMaxPriceLabel = computed(() => {
  if (oauthPhoneSmsCountryDisabled(registerForm.value.oauthPhoneSmsProvider)) return '不适用'
  return String(registerForm.value.oauthPhoneSmsMaxPrice || '').trim() || '使用设置页配置'
})
const oauthCdkTextareaPlaceholder = computed(() => {
  const provider = String(registerForm.value.oauthPhoneSmsProvider || '')
  const label = provider === 'tujie' ? 'TuJie' : 'Oasis'
  const sample = provider === 'tujie' ? 'SMS-AE4H6TLEZV5H69SJGQ' : 'SMS-6L2A-6TAH-Q7BA'
  return `可输入单个或多个 CDK，一行一个；例如 ${sample}；留空则使用设置页保存的 ${label} CDK 池`
})
const outlookImportResultClass = computed(() => outlookImportResultOk.value
  ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20'
  : 'bg-red-500/10 text-red-300 border-red-500/20')
const outlookPoolStatusFilterOptions = computed(() => [
  { value: 'all', label: '全部', count: Number(outlookPoolStatus.value?.total || 0) },
  { value: 'available', label: '可用', count: Number(outlookPoolStatus.value?.available || 0) },
  { value: 'registered', label: '已注册', count: Number(outlookPoolStatus.value?.registered || 0) },
  { value: 'unavailable', label: '暂不可用', count: Number(outlookPoolStatus.value?.unavailable || 0) },
])
const outlookPoolAllAccounts = computed(() => accountPoolAllAccounts(outlookPoolStatus.value))
const outlookPoolVisibleAccounts = computed(() => {
  return resolveAccountPoolVisibleAccounts(outlookPoolStatus.value, outlookPoolStatusFilter.value, {
    isICloudProvider: isICloudProvider.value,
  })
})
const outlookPoolVisibleEmails = computed(() => outlookPoolVisibleAccounts.value.map(account => account.email))
const outlookPoolSelectedSet = computed(() => new Set(outlookPoolSelectedEmails.value))
const outlookPoolSelectedCount = computed(() => outlookPoolSelectedEmails.value.length)
const outlookPoolAllVisibleSelected = computed(() => {
  const emails = outlookPoolVisibleEmails.value
  if (!emails.length) return false
  const selected = outlookPoolSelectedSet.value
  return emails.every(email => selected.has(email))
})
const mailComPoolItems = computed(() => (
  Array.isArray(mailComPoolStatus.value?.items)
    ? mailComPoolStatus.value.items.filter(item => isMailComEmail(item?.email))
    : []
))
const mailComPoolVisibleEmails = computed(() => mailComPoolItems.value.map(item => normalizeMailComEmail(item.email)).filter(Boolean))
const mailComPoolSelectedCount = computed(() => mailComPoolSelectedEmails.value.length)
const mailComPoolAllVisibleSelected = computed(() => {
  const visible = mailComPoolVisibleEmails.value
  return visible.length > 0 && visible.every(email => mailComPoolSelectedEmails.value.includes(email))
})
const canSubmitRegister = computed(() => {
  if (!validBatchCount.value) return false
  if (registerProviderUsesPool.value) return true
  return registerForm.value.mode === 'batch'
    ? selectedRegisterDomains.value.length > 0
    : Boolean(registerForm.value.domain)
})
let logsTimer = null
let statsTimer = null
let statsLoading = false
let mailProviderWatchReady = false
let registerPageMounted = false
let registerInitTimers = []
const REGISTER_LOG_FETCH_LIMIT = 300
const REGISTER_POLL_INTERVAL_MS = 5000
const statCards = computed(() => {
  const scope = statsMode.value === 'today' ? registerStats.value.today : currentTaskStats.value
  const prefix = statsMode.value === 'today' ? '今日' : '本次'
  return [
    { label: `${prefix}注册`, value: scope.total, color: 'text-blue-400' },
    { label: `${prefix}成功`, value: scope.ok, color: 'text-emerald-400' },
    { label: `${prefix}失败`, value: scope.failed, color: 'text-rose-400' },
    { label: `${prefix}成功率`, value: `${scope.successRate.toFixed(1)}%`, color: 'text-amber-300' },
  ]
})
const currentTaskStats = computed(() => {
  const task = props.runningTask
  if (!task) return registerStats.value.task
  const progress = task.progress || {}
  const result = task.result || {}
  const total = Number(progress.total ?? result.count ?? task.params?.count ?? registerStats.value.task.total ?? 0)
  const ok = Number(progress.ok ?? result.ok ?? registerStats.value.task.ok ?? 0)
  const failed = Number(progress.failed ?? result.failed ?? registerStats.value.task.failed ?? 0)
  return {
    total,
    ok,
    failed,
    successRate: total > 0 ? (ok / total) * 100 : 0,
  }
})
const currentTaskMeta = computed(() => ({
  taskId: props.runningTask?.task_id || registerStats.value.taskMeta?.taskId || '',
  startedAt: props.runningTask
    ? fmtTaskTime(props.runningTask.started_at || props.runningTask.created_at || 0)
    : (registerStats.value.taskMeta?.startedAt || ''),
}))
const activeRegisterTaskStatus = computed(() => {
  if (!props.runningTask) return ''
  return props.runningTask.cancel_requested ? 'cancel_requested' : String(props.runningTask.status || '')
})

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

function toggleRegisterDomainDropdown() {
  if (registeringBusy.value || !registerDomainOptions.value.length) return
  registerDomainDropdownOpen.value = !registerDomainDropdownOpen.value
}

function syncOAuthPhoneSmsCountrySearch() {
  if (oauthPhoneSmsCountryDisabled(registerForm.value.oauthPhoneSmsProvider)) {
    oauthPhoneSmsCountrySearch.value = ''
    oauthPhoneSmsCountryDropdownOpen.value = false
    return
  }
  oauthPhoneSmsCountrySearch.value = oauthPhoneSmsCountryLabel.value
}

function openOAuthPhoneSmsCountryDropdown(event) {
  if (registeringBusy.value || oauthPhoneSmsLoading.value || oauthPhoneSmsCountriesLoading.value) return
  if (oauthPhoneSmsCountryDisabled(registerForm.value.oauthPhoneSmsProvider)) return
  oauthPhoneSmsCountryDropdownOpen.value = true
  event?.target?.select?.()
}

function handleOAuthPhoneSmsCountryInput() {
  if (registeringBusy.value || oauthPhoneSmsLoading.value || oauthPhoneSmsCountriesLoading.value) return
  if (oauthPhoneSmsCountryDisabled(registerForm.value.oauthPhoneSmsProvider)) return
  oauthPhoneSmsCountryDropdownOpen.value = true
}

function toggleOAuthPhoneSmsCountryDropdown() {
  if (registeringBusy.value || oauthPhoneSmsLoading.value || oauthPhoneSmsCountriesLoading.value) return
  if (oauthPhoneSmsCountryDisabled(registerForm.value.oauthPhoneSmsProvider)) return
  oauthPhoneSmsCountryDropdownOpen.value = !oauthPhoneSmsCountryDropdownOpen.value
}

function closeOAuthPhoneSmsCountryDropdownSoon() {
  window.setTimeout(() => {
    oauthPhoneSmsCountryDropdownOpen.value = false
    syncOAuthPhoneSmsCountrySearch()
  }, 120)
}

function selectOAuthPhoneSmsCountry(option) {
  registerForm.value.oauthPhoneSmsCountry = String(option?.value || '').trim()
  oauthPhoneSmsCountrySearch.value = String(option?.label || option?.value || '').trim()
  oauthPhoneSmsCountryDropdownOpen.value = false
}

function selectAllRegisterDomains() {
  registerForm.value.selectedDomains = [...registerDomainOptions.value]
}

function clearRegisterDomains() {
  registerForm.value.selectedDomains = []
}

async function handleOutlookImportFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  outlookImportFilename.value = file.name
  try {
    outlookImportContent.value = await file.text()
    outlookImportResult.value = `已读取 ${file.name}，请确认内容后点击导入。`
    outlookImportResultOk.value = true
  } catch (e) {
    outlookImportResult.value = `读取文件失败: ${e.message}`
    outlookImportResultOk.value = false
  } finally {
    event.target.value = ''
  }
}

function openOutlookImportDialog() {
  outlookImportResult.value = ''
  outlookImportDialogOpen.value = true
}

function closeOutlookImportDialog() {
  if (outlookImporting.value) return
  outlookImportDialogOpen.value = false
}

async function openOutlookPoolDialog() {
  if (isICloudProvider.value || isGenericApiProvider.value) {
    outlookPoolStatusFilter.value = 'available'
  }
  outlookPoolDialogOpen.value = true
  await loadOutlookPoolStatus({ includeAll: true })
}

function closeOutlookPoolDialog() {
  if (outlookPoolDeleting.value) return
  outlookPoolDialogOpen.value = false
}

function openMailComImportDialog() {
  mailComImportDialogOpen.value = true
  mailComImportResult.value = ''
}

function closeMailComImportDialog() {
  if (mailComPoolLoading.value) return
  mailComImportDialogOpen.value = false
}

function normalizeMailComEmail(email) {
  return String(email || '').trim().toLowerCase()
}

function isMailComEmail(email) {
  const normalized = normalizeMailComEmail(email)
  return normalized.endsWith('@mail.com')
}

function parseMailComImportContent(content) {
  const lines = String(content || '').split(/\r?\n/)
  const emails = []
  const invalidLines = []
  const seen = new Set()
  for (let index = 0; index < lines.length; index += 1) {
    const line = String(lines[index] || '').trim()
    if (!line) continue
    const parts = line.split('----').map(part => String(part || '').trim())
    const firstField = parts[0] || ''
    if (parts.length !== 2) {
      invalidLines.push({
        lineNumber: index + 1,
        email: firstField,
        reason: '必须是 2 段：邮箱----邮箱密码',
      })
      continue
    }
    if (parts.some(part => !part)) {
      invalidLines.push({
        lineNumber: index + 1,
        email: firstField,
        reason: '2 个字段都不能为空',
      })
      continue
    }
    if (!isMailComEmail(firstField)) {
      invalidLines.push({
        lineNumber: index + 1,
        email: firstField,
        reason: '第一段必须是 @mail.com 邮箱',
      })
      continue
    }
    const normalizedEmail = normalizeMailComEmail(firstField)
    if (seen.has(normalizedEmail)) continue
    seen.add(normalizedEmail)
    emails.push(normalizedEmail)
  }
  return {
    emails,
    invalidLines,
  }
}

async function loadMailComPoolStatus() {
  if (!isMailComProvider.value || mailComPoolLoading.value) return
  mailComPoolLoading.value = true
  mailComPoolError.value = ''
  try {
    mailComPoolStatus.value = await api.getMailAccountsPoolStatus()
    const visible = new Set(mailComPoolVisibleEmails.value)
    mailComPoolSelectedEmails.value = mailComPoolSelectedEmails.value.filter(email => visible.has(email))
  } catch (e) {
    mailComPoolStatus.value = null
    mailComPoolError.value = `读取 mail.com 邮箱池失败: ${e.message}`
  } finally {
    mailComPoolLoading.value = false
  }
}

async function importMailComAccounts() {
  if (mailComPoolLoading.value) return
  const content = mailComImportContent.value.trim()
  if (!content) {
    mailComImportResult.value = '请先粘贴 mail.com 账号'
    mailComImportResultOk.value = false
    return
  }
  const { emails: parsedMailComEmails, invalidLines } = parseMailComImportContent(content)
  if (invalidLines.length) {
    const preview = invalidLines
      .slice(0, 3)
      .map(item => `第 ${item.lineNumber} 行: ${item.reason}${item.email ? `（${item.email}）` : ''}`)
      .join('；')
    const suffix = invalidLines.length > 3 ? `；另有 ${invalidLines.length - 3} 行` : ''
    mailComImportResult.value = `导入格式错误：${preview}${suffix}`
    mailComImportResultOk.value = false
    return
  }
  if (!parsedMailComEmails.length) {
    mailComImportResult.value = '未解析到可导入的 @mail.com 邮箱'
    mailComImportResultOk.value = false
    return
  }
  mailComPoolLoading.value = true
  mailComPoolError.value = ''
  try {
    const result = await api.importMailAccounts(content, { sync_account_pool: false })
    const importedEmails = Array.isArray(result.emails)
      ? result.emails.map(normalizeMailComEmail).filter(isMailComEmail)
      : []
    mailComPoolStatus.value = result.pool_status || await api.getMailAccountsPoolStatus()
    mailComImportResult.value = `导入完成：成功 ${result.imported || 0}，跳过 ${result.skipped || 0}，加入邮箱池 ${importedEmails.length} 个`
    mailComImportResultOk.value = true
    const visible = new Set(mailComPoolVisibleEmails.value)
    mailComPoolSelectedEmails.value = mailComPoolSelectedEmails.value.filter(email => visible.has(email))
  } catch (e) {
    mailComImportResult.value = `导入失败: ${e.message}`
    mailComImportResultOk.value = false
  } finally {
    mailComPoolLoading.value = false
  }
  await loadMailComPoolStatus()
}

function openMailComPoolDialog() {
  mailComPoolDialogOpen.value = true
  loadMailComPoolStatus()
}

function closeMailComPoolDialog() {
  if (mailComPoolDeleting.value) return
  mailComPoolDialogOpen.value = false
}

function toggleMailComPoolEmail(email, checked) {
  const value = normalizeMailComEmail(email)
  if (!value) return
  const selected = new Set(mailComPoolSelectedEmails.value)
  checked ? selected.add(value) : selected.delete(value)
  mailComPoolSelectedEmails.value = Array.from(selected)
}

function toggleMailComPoolVisible(checked) {
  const selected = new Set(mailComPoolSelectedEmails.value)
  for (const email of mailComPoolVisibleEmails.value) {
    checked ? selected.add(email) : selected.delete(email)
  }
  mailComPoolSelectedEmails.value = Array.from(selected)
}

async function deleteSelectedMailComPoolEmails() {
  if (mailComPoolDeleting.value || mailComPoolSelectedCount.value === 0) return
  const emails = [...mailComPoolSelectedEmails.value]
  const ok = window.confirm(`确认从 mail.com 邮箱池删除 ${emails.length} 个邮箱?\n\n只会删除 mail邮箱管理中的记录，不会删除本地账号池记录。`)
  if (!ok) return
  mailComPoolDeleting.value = true
  try {
    const result = await api.deleteMailAccounts(emails)
    mailComPoolSelectedEmails.value = []
    await loadMailComPoolStatus()
    setMessage(`已从 mail.com 邮箱池删除 ${result.deleted || 0} 个邮箱`, true)
  } catch (e) {
    setMessage(`删除 mail.com 邮箱失败: ${e.message}`, false)
  } finally {
    mailComPoolDeleting.value = false
  }
}

function handleGlobalKeydown(event) {
  if (event.key !== 'Escape') return
  if (outlookImportDialogOpen.value) {
    closeOutlookImportDialog()
  } else if (outlookPoolDialogOpen.value) {
    closeOutlookPoolDialog()
  } else if (mailComImportDialogOpen.value) {
    closeMailComImportDialog()
  } else if (mailComPoolDialogOpen.value) {
    closeMailComPoolDialog()
  }
}

async function importOutlookAccounts() {
  const content = outlookImportContent.value.trim()
  if (!content || outlookImporting.value) return
  outlookImporting.value = true
  outlookImportResult.value = ''
  try {
    const result = isICloudProvider.value
      ? await api.importICloudAccounts(content, outlookImportFilename.value || 'pasted.txt')
      : isGenericApiProvider.value
        ? await api.importGenericApiAccounts(content, outlookImportFilename.value || 'pasted.txt')
        : await api.importOutlookAccounts(content, outlookImportFilename.value || 'pasted.txt')
    const firstHint = result.first_imported_email
      ? `，单次注册将优先使用 ${result.first_imported_email}`
      : ''
    outlookImportResult.value = `导入完成：新增 ${result.imported}，重复 ${result.duplicates}，无效 ${result.invalid}${firstHint}，写入 ${result.file}`
    outlookImportResultOk.value = result.invalid === 0
    if (result.imported > 0) {
      if (registerForm.value.mode === 'batch') {
        registerForm.value.count = result.imported
      }
      outlookImportContent.value = ''
      outlookImportFilename.value = ''
    }
    await loadOutlookPoolStatus({ includeAll: outlookPoolDialogOpen.value })
  } catch (e) {
    outlookImportResult.value = `导入失败: ${e.message}`
    outlookImportResultOk.value = false
  } finally {
    outlookImporting.value = false
  }
}

async function loadOutlookPoolStatus(options = {}) {
  if (!isOutlookLikePoolProvider.value || outlookPoolLoading.value) return
  const includeAll = Boolean(options.includeAll || outlookPoolDialogOpen.value)
  outlookPoolLoading.value = true
  outlookPoolError.value = ''
  try {
    outlookPoolStatus.value = isICloudProvider.value
      ? await api.getICloudAccountsStatus(includeAll)
      : isGenericApiProvider.value
        ? await api.getGenericApiAccountsStatus(includeAll)
        : await api.getOutlookAccountsStatus()
    pruneOutlookPoolSelectionToVisible()
  } catch (e) {
    outlookPoolStatus.value = null
    outlookPoolError.value = `读取 ${accountPoolProviderLabel.value} 邮箱池失败: ${e.message}`
  } finally {
    outlookPoolLoading.value = false
  }
}

function pruneOutlookPoolSelectionToVisible() {
  const visible = new Set(outlookPoolVisibleEmails.value)
  outlookPoolSelectedEmails.value = outlookPoolSelectedEmails.value.filter(email => visible.has(email))
}

function toggleOutlookPoolEmail(email, checked) {
  const value = String(email || '').trim()
  if (!value) return
  const selected = new Set(outlookPoolSelectedEmails.value)
  if (checked) {
    selected.add(value)
  } else {
    selected.delete(value)
  }
  outlookPoolSelectedEmails.value = Array.from(selected)
}

function toggleOutlookPoolVisible(checked) {
  const selected = new Set(outlookPoolSelectedEmails.value)
  for (const email of outlookPoolVisibleEmails.value) {
    if (checked) {
      selected.add(email)
    } else {
      selected.delete(email)
    }
  }
  outlookPoolSelectedEmails.value = Array.from(selected)
}

async function deleteSelectedOutlookPoolEmails() {
  if (outlookPoolDeleting.value || outlookPoolSelectedCount.value === 0) return
  const emails = [...outlookPoolSelectedEmails.value]
  const ok = window.confirm(`确认从 ${accountPoolProviderLabel.value} 邮箱池删除 ${emails.length} 个邮箱?\n\n只会删除邮箱池中的记录，不会删除本地已注册账号。`)
  if (!ok) return
  outlookPoolDeleting.value = true
  try {
    const result = isICloudProvider.value
      ? await api.deleteICloudAccounts(emails)
      : isGenericApiProvider.value
        ? await api.deleteGenericApiAccounts(emails)
        : await api.deleteOutlookAccounts(emails)
    outlookPoolSelectedEmails.value = []
    await loadOutlookPoolStatus()
    setMessage(`已从 ${accountPoolProviderLabel.value} 邮箱池删除 ${result.deleted || 0} 个邮箱`, true)
  } catch (e) {
    setMessage(`删除 ${accountPoolProviderLabel.value} 邮箱失败: ${e.message}`, false)
  } finally {
    outlookPoolDeleting.value = false
  }
}

function outlookPoolAccountStatusLabel(status) {
  if (status === 'registered') return '已注册'
  if (status === 'unavailable') return '暂不可用'
  return '可用'
}

function outlookPoolAccountStatusClass(status) {
  if (status === 'registered') return 'text-gray-500'
  if (status === 'unavailable') return 'text-amber-300'
  return 'text-emerald-300'
}

function loadSavedRegisterForm() {
  try {
    const raw = localStorage.getItem(REGISTER_FORM_STORAGE_KEY)
    if (!raw) return
    const saved = JSON.parse(raw)
    if (!saved || typeof saved !== 'object') return
    savedLuckmailEmailType = Object.prototype.hasOwnProperty.call(saved, 'luckmailEmailType')
    savedLuckmailPreferredDomain = Object.prototype.hasOwnProperty.call(saved, 'luckmailPreferredDomain')
    savedOauthPhoneSmsCountries = saved.oauthPhoneSmsCountryByProvider && typeof saved.oauthPhoneSmsCountryByProvider === 'object'
      ? Object.fromEntries(
        Object.entries(saved.oauthPhoneSmsCountryByProvider)
          .map(([provider, country]) => [String(provider), String(country || '').trim()])
          .filter(([, country]) => country)
      )
      : {}
    savedOauthPhoneSmsMaxPrices = saved.oauthPhoneSmsMaxPriceByProvider && typeof saved.oauthPhoneSmsMaxPriceByProvider === 'object'
      ? Object.fromEntries(
        Object.entries(saved.oauthPhoneSmsMaxPriceByProvider)
          .map(([provider, maxPrice]) => [String(provider), String(maxPrice || '').trim()])
      )
      : {}
    const savedOauthPhoneSmsProvider = OAUTH_PHONE_PROVIDER_VALUES.includes(String(saved.oauthPhoneSmsProvider || ''))
      ? String(saved.oauthPhoneSmsProvider)
      : 'phone_pool'
    const savedOauthPhoneSmsCountry = String(saved.oauthPhoneSmsCountry || savedOauthPhoneSmsCountries[savedOauthPhoneSmsProvider] || registerForm.value.oauthPhoneSmsCountry || '187')
    if (!oauthPhoneSmsCountryDisabled(savedOauthPhoneSmsProvider) && savedOauthPhoneSmsCountry) {
      savedOauthPhoneSmsCountries[savedOauthPhoneSmsProvider] = savedOauthPhoneSmsCountry
    }
    const savedOauthPhoneSmsMaxPrice = String(saved.oauthPhoneSmsMaxPrice || savedOauthPhoneSmsMaxPrices[savedOauthPhoneSmsProvider] || '').trim()
    if (!oauthPhoneSmsCountryDisabled(savedOauthPhoneSmsProvider)) {
      savedOauthPhoneSmsMaxPrices[savedOauthPhoneSmsProvider] = savedOauthPhoneSmsMaxPrice
    }
    registerForm.value = {
      ...registerForm.value,
      mode: saved.mode === 'batch' ? 'batch' : 'single',
      registrationFlow: saved.registrationFlow === 'phone_cpa' ? 'phone_cpa' : 'standard',
      count: Number(saved.count || registerForm.value.count),
      concurrency: Number(saved.concurrency || registerForm.value.concurrency),
      intervalSeconds: Number(saved.intervalSeconds ?? registerForm.value.intervalSeconds),
      jitterMinSeconds: Number(saved.jitterMinSeconds ?? registerForm.value.jitterMinSeconds),
      jitterMaxSeconds: Number(saved.jitterMaxSeconds ?? registerForm.value.jitterMaxSeconds),
      domain: String(saved.domain || ''),
      selectedDomains: Array.isArray(saved.selectedDomains)
        ? saved.selectedDomains.map(domain => String(domain || '').trim()).filter(Boolean)
        : [],
      mailProvider: String(saved.mailProvider || registerForm.value.mailProvider || ''),
      luckmailEmailType: savedLuckmailEmailType
        ? String(saved.luckmailEmailType || 'ms_imap')
        : String(registerForm.value.luckmailEmailType || ''),
      luckmailPreferredDomain: savedLuckmailPreferredDomain
        ? String(saved.luckmailPreferredDomain || '')
        : (Array.isArray(saved.luckmailPreferredDomains) && saved.luckmailPreferredDomains.length
          ? String(saved.luckmailPreferredDomains[0] || '').trim().replace(/^@/, '')
          : String(registerForm.value.luckmailPreferredDomain || '')),
      luckmailPreferredDomains: Array.isArray(saved.luckmailPreferredDomains)
        ? saved.luckmailPreferredDomains.map(domain => String(domain || '').trim().replace(/^@/, '')).filter(Boolean)
        : (saved.luckmailPreferredDomain ? [String(saved.luckmailPreferredDomain).trim().replace(/^@/, '')].filter(Boolean) : registerForm.value.luckmailPreferredDomains),
      prefix: String(saved.prefix || ''),
      // 密码不持久化，避免明文留在本地存储
      password: '',
      useRoxyBrowser: Boolean(saved.useRoxyBrowser),
      protocolRegister: Boolean(saved.protocolRegister) && !Boolean(saved.useRoxyBrowser),
      postRegisterOauth: Boolean(saved.postRegisterOauth),
      enableTotpMfa: Boolean(saved.enableTotpMfa),
      phoneOnly: Boolean(saved.phoneOnly),
      oauthPhoneSmsProvider: savedOauthPhoneSmsProvider,
      oauthPhoneSmsCountry: savedOauthPhoneSmsCountry,
      oauthPhoneSmsMaxPrice: savedOauthPhoneSmsMaxPrice,
      oauthOasisSmsCdks: '',
      proxyUrl: String(saved.proxyUrl || ''),
      proxyApiEnabled: Boolean(saved.proxyApiEnabled),
      proxyApiProvider: ['1024proxy', 'cliproxy'].includes(String(saved.proxyApiProvider || ''))
        ? String(saved.proxyApiProvider)
        : '1024proxy',
      proxyApiCountry: normalizeRegisterProxyCountry(saved.proxyApiCountry),
    }
  } catch (e) {
    console.error('loadSavedRegisterForm', e)
  }
}

function saveRegisterForm() {
  try {
    const oauthProvider = OAUTH_PHONE_PROVIDER_VALUES.includes(String(registerForm.value.oauthPhoneSmsProvider || ''))
      ? registerForm.value.oauthPhoneSmsProvider
      : 'phone_pool'
    const oauthCountry = isCdkOAuthPhoneProvider(oauthProvider) ? '' : String(registerForm.value.oauthPhoneSmsCountry || '').trim()
    if (!oauthPhoneSmsCountryDisabled(oauthProvider) && oauthCountry) {
      savedOauthPhoneSmsCountries[oauthProvider] = oauthCountry
    }
    const oauthMaxPrice = OAUTH_PHONE_DYNAMIC_PRICE_PROVIDERS.includes(oauthProvider)
      ? String(registerForm.value.oauthPhoneSmsMaxPrice || '').trim()
      : ''
    if (!oauthPhoneSmsCountryDisabled(oauthProvider)) {
      savedOauthPhoneSmsMaxPrices[oauthProvider] = oauthMaxPrice
    }
    localStorage.setItem(
      REGISTER_FORM_STORAGE_KEY,
      JSON.stringify({
        mode: registerForm.value.mode,
        registrationFlow: registerForm.value.registrationFlow,
        count: registerForm.value.count,
        concurrency: registerForm.value.concurrency,
        intervalSeconds: registerForm.value.intervalSeconds,
        jitterMinSeconds: registerForm.value.jitterMinSeconds,
        jitterMaxSeconds: registerForm.value.jitterMaxSeconds,
        domain: registerForm.value.domain,
        selectedDomains: selectedRegisterDomains.value,
        mailProvider: registerForm.value.mailProvider,
        luckmailEmailType: registerForm.value.luckmailEmailType,
      luckmailPreferredDomain: registerForm.value.luckmailPreferredDomain,
      luckmailPreferredDomains: registerForm.value.luckmailPreferredDomain ? [registerForm.value.luckmailPreferredDomain] : [],
      prefix: registerForm.value.prefix,
      protocolRegister: Boolean(registerForm.value.protocolRegister),
      useRoxyBrowser: Boolean(registerForm.value.useRoxyBrowser),
      postRegisterOauth: Boolean(registerForm.value.postRegisterOauth),
      enableTotpMfa: Boolean(registerForm.value.enableTotpMfa),
      phoneOnly: Boolean(registerForm.value.phoneOnly),
      oauthPhoneSmsProvider: oauthProvider,
      oauthPhoneSmsCountry: isCdkOAuthPhoneProvider(oauthProvider) ? '' : (oauthCountry || '187'),
      oauthPhoneSmsCountryByProvider: savedOauthPhoneSmsCountries,
      oauthPhoneSmsMaxPrice: oauthMaxPrice,
      oauthPhoneSmsMaxPriceByProvider: savedOauthPhoneSmsMaxPrices,
      proxyUrl: String(registerForm.value.proxyUrl || '').trim(),
      proxyApiEnabled: Boolean(registerForm.value.proxyApiEnabled),
      proxyApiProvider: ['1024proxy', 'cliproxy'].includes(String(registerForm.value.proxyApiProvider || ''))
        ? registerForm.value.proxyApiProvider
        : '1024proxy',
      proxyApiCountry: normalizeRegisterProxyCountry(registerForm.value.proxyApiCountry),
    })
    )
  } catch (e) {
    console.error('saveRegisterForm', e)
  }
}

async function reloadRegisterDomains() {
  registerConfigLoading.value = true
  try {
    const result = await api.getRegisterDomain()
    const domains = result.domains?.length ? result.domains : (result.domain ? [result.domain] : [])
    registerDomainOptions.value = domains
    if (!registerForm.value.domain || !domains.includes(registerForm.value.domain)) {
      registerForm.value.domain = result.domain || domains[0] || ''
    }
    const selected = selectedRegisterDomains.value.filter(domain => domains.includes(domain))
    registerForm.value.selectedDomains = selected.length
      ? selected
      : (registerForm.value.domain ? [registerForm.value.domain] : [])
  } catch (e) {
    setMessage(`读取注册域名失败: ${e.message}`, false)
  } finally {
    registerConfigLoading.value = false
  }
}

async function loadMailProviderOptions() {
  mailProviderLoading.value = true
  try {
    const result = await api.getMailProviderConfig()
    mailProviderOptions.value = result.provider_options || []
    if (!registerForm.value.mailProvider) {
      registerForm.value.mailProvider = result.provider || 'cloudflare_temp_email'
    }
    const luckmailFields = result.provider_fields?.luckmail || []
    const emailTypeField = luckmailFields.find(field => field.key === 'LUCKMAIL_EMAIL_TYPE')
    const domainField = luckmailFields.find(field => field.key === 'LUCKMAIL_PREFERRED_DOMAIN')
    const configuredLuckmailEmailType = String(emailTypeField?.value || '').trim()
    if (!savedLuckmailEmailType && !registerForm.value.luckmailEmailType) {
      registerForm.value.luckmailEmailType = configuredLuckmailEmailType || registerForm.value.luckmailEmailType || 'ms_imap'
    }
    if (!savedLuckmailPreferredDomain && !registerForm.value.luckmailPreferredDomain && domainField?.value) {
      registerForm.value.luckmailPreferredDomain = domainField.value
      registerForm.value.luckmailPreferredDomains = [String(domainField.value).trim().replace(/^@/, '')].filter(Boolean)
    }
  } catch (e) {
    setMessage(`读取邮件 Provider 失败: ${e.message}`, false)
  } finally {
    mailProviderLoading.value = false
  }
}

async function loadOAuthPhoneSmsConfig() {
  oauthPhoneSmsLoading.value = true
  try {
    const result = await api.getOAuthPhoneSmsConfig()
    oauthPhoneSmsConfig.value = result || {}
    oauthPhoneSmsConfigLoaded.value = true
    const providers = Array.isArray(result.providers) && result.providers.length
      ? result.providers
      : oauthPhoneSmsProviderOptions.value
    oauthPhoneSmsProviderOptions.value = providers.map(option => ({
      value: option.value,
      label: option.label || option.value,
      configured: Boolean(option.configured),
    }))
    if (!registerForm.value.oauthPhoneSmsProvider) {
      registerForm.value.oauthPhoneSmsProvider = result.provider || 'phone_pool'
    }
    const provider = registerForm.value.oauthPhoneSmsProvider
    if (!registerForm.value.oauthPhoneSmsCountry) {
      registerForm.value.oauthPhoneSmsCountry = isCdkOAuthPhoneProvider(provider)
        ? ''
        : provider === 'smsbower'
        ? (result.smsbower_country || '187')
        : provider === 'smscloud'
        ? (result.smscloud_country || '187')
        : (result.hero_sms_country || '187')
    }
    if (!registerForm.value.oauthPhoneSmsMaxPrice) {
      const hasRememberedMaxPrice = Object.prototype.hasOwnProperty.call(savedOauthPhoneSmsMaxPrices, provider)
      const rememberedMaxPrice = String(savedOauthPhoneSmsMaxPrices[provider] || '').trim()
      registerForm.value.oauthPhoneSmsMaxPrice = isCdkOAuthPhoneProvider(provider)
        ? ''
        : hasRememberedMaxPrice ? rememberedMaxPrice : (provider === 'smsbower'
        ? (result.smsbower_max_price || '')
        : provider === 'smscloud'
        ? (result.smscloud_max_price || '')
        : (result.hero_sms_max_price || ''))
    }
    await loadOAuthPhoneSmsCountries(provider)
  } catch (e) {
    setMessage(`读取 OAuth 接码配置失败: ${e.message}`, false)
  } finally {
    oauthPhoneSmsLoading.value = false
  }
}

function configuredOAuthPhoneCountry(provider) {
  if (!oauthPhoneSmsConfigLoaded.value) return ''
  const cfg = oauthPhoneSmsConfig.value || {}
  if (isCdkOAuthPhoneProvider(provider)) return ''
  if (provider === 'smsbower') return String(cfg.smsbower_country || '187')
  if (provider === 'smscloud') return String(cfg.smscloud_country || '187')
  if (provider === 'hero_sms') return String(cfg.hero_sms_country || '187')
  return ''
}

function configuredOAuthPhoneMaxPrice(provider) {
  if (!oauthPhoneSmsConfigLoaded.value) return ''
  const cfg = oauthPhoneSmsConfig.value || {}
  if (isCdkOAuthPhoneProvider(provider)) return ''
  if (provider === 'smsbower') return String(cfg.smsbower_max_price || '')
  if (provider === 'smscloud') return String(cfg.smscloud_max_price || '')
  if (provider === 'hero_sms') return String(cfg.hero_sms_max_price || '')
  return ''
}

function normalizeOAuthPhoneSmsCountryOptions(options) {
  return (Array.isArray(options) ? options : []).map(option => ({
    value: String(option.value || ''),
    label: String(option.label || option.value || ''),
  })).filter(option => option.value)
}

function readOAuthPhoneSmsCountriesCache(provider) {
  try {
    const raw = localStorage.getItem(OAUTH_PHONE_SMS_COUNTRIES_CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    const entry = parsed?.[provider]
    if (!entry || !Array.isArray(entry.options)) return null
    if (Date.now() - Number(entry.cachedAt || 0) > OAUTH_PHONE_SMS_COUNTRIES_CACHE_TTL_MS) return null
    const options = normalizeOAuthPhoneSmsCountryOptions(entry.options)
    return options.length ? options : null
  } catch {
    return null
  }
}

function writeOAuthPhoneSmsCountriesCache(provider, options) {
  try {
    const raw = localStorage.getItem(OAUTH_PHONE_SMS_COUNTRIES_CACHE_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    parsed[provider] = {
      cachedAt: Date.now(),
      options: normalizeOAuthPhoneSmsCountryOptions(options),
    }
    localStorage.setItem(OAUTH_PHONE_SMS_COUNTRIES_CACHE_KEY, JSON.stringify(parsed))
  } catch (e) {
    console.error('writeOAuthPhoneSmsCountriesCache', e)
  }
}

async function loadOAuthPhoneSmsCountries(provider = registerForm.value.oauthPhoneSmsProvider) {
  const normalizedProvider = String(provider || 'phone_pool')
  oauthPhoneSmsCountryError.value = ''
  oauthPhoneSmsCountryDropdownOpen.value = false
  if (oauthPhoneSmsCountryDisabled(normalizedProvider)) {
    oauthPhoneSmsCountryOptions.value = []
    syncOAuthPhoneSmsCountrySearch()
    return
  }
  const cachedOptions = readOAuthPhoneSmsCountriesCache(normalizedProvider)
  if (cachedOptions) {
    oauthPhoneSmsCountryOptions.value = cachedOptions
    syncOAuthPhoneSmsCountrySearch()
    return
  }
  oauthPhoneSmsCountriesLoading.value = true
  let request = oauthPhoneSmsCountryRequests.get(normalizedProvider)
  try {
    if (!request) {
      request = api.getOAuthPhoneSmsCountries(normalizedProvider)
      oauthPhoneSmsCountryRequests.set(normalizedProvider, request)
    }
    const result = await request
    const options = Array.isArray(result.options) && result.options.length
      ? result.options
      : (oauthPhoneSmsCountryFallbackOptions[normalizedProvider] || [])
    oauthPhoneSmsCountryOptions.value = normalizeOAuthPhoneSmsCountryOptions(options)
    if (!result.fallback && oauthPhoneSmsCountryOptions.value.length) {
      writeOAuthPhoneSmsCountriesCache(normalizedProvider, oauthPhoneSmsCountryOptions.value)
    }
    oauthPhoneSmsCountryError.value = result.fallback && result.error ? result.error : ''
    syncOAuthPhoneSmsCountrySearch()
  } catch (e) {
    oauthPhoneSmsCountryOptions.value = oauthPhoneSmsCountryFallbackOptions[normalizedProvider] || []
    oauthPhoneSmsCountryError.value = e.message || '国家列表加载失败，已使用兜底列表'
    syncOAuthPhoneSmsCountrySearch()
  } finally {
    if (oauthPhoneSmsCountryRequests.get(normalizedProvider) === request) {
      oauthPhoneSmsCountryRequests.delete(normalizedProvider)
    }
    oauthPhoneSmsCountriesLoading.value = false
  }
}

async function loadRegisterLogs() {
  if (logsLoading.value) return
  logsLoading.value = true
  try {
    const result = await api.getLogs(REGISTER_LOG_FETCH_LIMIT)
    registerLogs.value = (result.logs || []).filter(entry => {
      const msg = String(entry.message || '')
      return msg.includes('[注册账号]') || msg.includes('[直接注册]') || msg.includes('[注册]') || msg.includes('[协议注册]') || msg.includes('[phone-first]') || msg.includes('[Codex]')
    })
    await nextTick()
    if (logsContainer.value) {
      logsContainer.value.scrollTop = logsContainer.value.scrollHeight
    }
  } catch (e) {
    setMessage(`读取注册日志失败: ${e.message}`, false)
  } finally {
    logsLoading.value = false
  }
}

async function loadRegisterStats() {
  if (statsLoading) return
  statsLoading = true
  try {
    const tasks = await api.getTasks()
    const registerTasks = (tasks || []).filter(task => task.command === 'register')
    const todayStart = new Date()
    todayStart.setHours(0, 0, 0, 0)
    const todayStartTs = todayStart.getTime() / 1000

    const activeTask = registerTasks.find(task => task.status === 'running' || task.status === 'pending') || null
    const latestTask = activeTask || registerTasks[0] || null
    const taskScope = { total: 0, ok: 0, failed: 0 }
    const today = { total: 0, ok: 0, failed: 0 }

    for (const task of registerTasks) {
      const createdAt = Number(task.created_at || 0)
      const result = task.result || {}
      const count = typeof result.count === 'number' ? Number(result.count || 0) : Number(task.params?.count || 1)
      const okCount = typeof result.ok === 'number' ? Number(result.ok || 0) : 0
      const failedCount = typeof result.failed === 'number' ? Number(result.failed || 0) : 0

      if (createdAt >= todayStartTs) {
        today.total += count
        today.ok += okCount
        today.failed += failedCount
      }
      if (latestTask && task.task_id === latestTask.task_id) {
        const progress = task.progress || null
        if (progress && (task.status === 'running' || task.status === 'pending')) {
          taskScope.total += Number(progress.total || count || 0)
          taskScope.ok += Number(progress.ok || 0)
          taskScope.failed += Number(progress.failed || 0)
        } else {
          taskScope.total += count
          taskScope.ok += okCount
          taskScope.failed += failedCount
        }
      }
    }

    registerStats.value = {
      task: {
        ...taskScope,
        successRate: taskScope.total > 0 ? (taskScope.ok / taskScope.total) * 100 : 0,
      },
      today: {
        ...today,
        successRate: today.total > 0 ? (today.ok / today.total) * 100 : 0,
      },
      taskMeta: latestTask
        ? {
            taskId: latestTask.task_id || '',
            startedAt: fmtTaskTime(latestTask.started_at || latestTask.created_at || 0),
          }
        : {
            taskId: '',
            startedAt: '',
          },
    }
  } catch (e) {
    console.error('loadRegisterStats', e)
  } finally {
    statsLoading = false
  }
}

async function submitManualRegister() {
  if (registeringBusy.value || registeringAccount.value) return
  registeringAccount.value = true
  try {
    if (!isPhoneCpaFlow.value && Boolean(registerForm.value.useRoxyBrowser)) {
      try {
        const roxy = await api.getRoxyBrowserWorkspaces()
        const workspaceCount = Number(roxy?.count ?? (Array.isArray(roxy?.workspaces) ? roxy.workspaces.length : 0))
        if (!workspaceCount) {
          throw new Error('未找到可用工作空间')
        }
      } catch (e) {
        setMessage(`RoxyBrowser 未连接或不可用，请启动 RoxyBrowser 客户端并确认设置页 API Host/Token 正确，或取消“使用Roxy Browser”：${e.message}`, false)
        return
      }
    }
    const oauthProvider = String(registerForm.value.oauthPhoneSmsProvider || 'phone_pool')
    const oauthUsesProvider = isPhoneCpaFlow.value || registerForm.value.postRegisterOauth
    const payload = {
      mode: registerForm.value.mode,
      registration_flow: registerForm.value.registrationFlow,
      count: registerForm.value.mode === 'batch' ? Number(registerForm.value.count || 1) : 1,
      concurrency: registerForm.value.mode === 'batch' ? validConcurrency.value : 1,
      interval_seconds: registerForm.value.mode === 'batch' ? validIntervalSeconds.value : 0,
      jitter_min_seconds: registerForm.value.mode === 'batch' ? validJitterMinSeconds.value : 0,
      jitter_max_seconds: registerForm.value.mode === 'batch' ? validJitterMaxSeconds.value : 0,
      domain: registerProviderUsesDomains.value ? registerForm.value.domain : '',
      domains: registerProviderUsesDomains.value && registerForm.value.mode === 'batch' ? selectedRegisterDomains.value : [],
      mail_provider: registerForm.value.mailProvider || null,
      luckmail_email_type: isLuckMailProvider.value ? (registerForm.value.luckmailEmailType || 'ms_imap') : null,
      luckmail_preferred_domain: isLuckMailProvider.value ? registerForm.value.luckmailPreferredDomain : null,
      luckmail_preferred_domains: isLuckMailProvider.value && registerForm.value.luckmailPreferredDomain ? [registerForm.value.luckmailPreferredDomain] : [],
      prefix: registerForm.value.prefix || null,
      password: registerForm.value.password || null,
      protocol_register: isPhoneCpaFlow.value || (!Boolean(registerForm.value.useRoxyBrowser) && Boolean(registerForm.value.protocolRegister)),
      use_roxybrowser: !isPhoneCpaFlow.value && Boolean(registerForm.value.useRoxyBrowser),
      enable2fa: !isPhoneCpaFlow.value && Boolean(registerForm.value.enableTotpMfa),
      phone_only: isPhoneCpaFlow.value && Boolean(registerForm.value.phoneOnly),
      post_register_oauth: (isPhoneCpaFlow.value && !Boolean(registerForm.value.phoneOnly)) || Boolean(registerForm.value.postRegisterOauth),
      oauth_phone_sms_provider: oauthUsesProvider ? oauthProvider : '',
      oauth_phone_sms_country: oauthUsesProvider && !isCdkOAuthPhoneProvider(oauthProvider) ? registerForm.value.oauthPhoneSmsCountry : '',
      oauth_phone_sms_max_price: oauthUsesProvider && OAUTH_PHONE_DYNAMIC_PRICE_PROVIDERS.includes(oauthProvider) ? registerForm.value.oauthPhoneSmsMaxPrice : '',
      oauth_oasis_sms_cdks: oauthUsesProvider && isCdkOAuthPhoneProvider(oauthProvider) ? registerForm.value.oauthOasisSmsCdks : '',
      proxy_url: registerForm.value.proxyApiEnabled ? '' : (registerForm.value.proxyUrl || ''),
      proxy_api_provider: registerForm.value.proxyApiEnabled ? registerForm.value.proxyApiProvider : '',
      proxy_api_country: registerForm.value.proxyApiEnabled
        ? normalizeRegisterProxyCountry(registerForm.value.proxyApiCountry)
        : '',
    }
    await api.startAdd(payload)
    emit('task-started')
    emit('refresh')
  } catch (e) {
    setMessage(e.message, false)
  } finally {
    registeringAccount.value = false
  }
}

async function cancelRegisterTask() {
  if (registerCancelBusy.value || registerCancelRequested.value) return
  const task = props.runningTask
  if (!task?.task_id) return
  const ok = window.confirm(`确认取消当前账号注册任务?\n\nID: ${task.task_id}\n\n已开始的单个账号步骤会在可中断点停止，后续账号不会继续提交。`)
  if (!ok) return
  registerCancelBusy.value = true
  try {
    const result = await api.cancelTask({
      task_id: task.task_id,
      task_group: 'register',
    })
    registerCancelRequested.value = true
    message.value = result.message || '已请求取消注册任务'
    messageClass.value = 'bg-amber-500/10 text-amber-300 border-amber-500/20'
    emit('refresh')
  } catch (e) {
    setMessage(`取消注册任务失败: ${e.message}`, false)
  } finally {
    registerCancelBusy.value = false
  }
}

watch(
  registerForm,
  () => {
    saveRegisterForm()
  },
  { deep: true }
)

watch(
  () => registerForm.value.mode,
  mode => {
    registerDomainDropdownOpen.value = false
    if (mode === 'batch' && !selectedRegisterDomains.value.length && registerForm.value.domain) {
      registerForm.value.selectedDomains = [registerForm.value.domain]
    }
    if (mode === 'single' && !registerForm.value.domain && selectedRegisterDomains.value.length) {
      registerForm.value.domain = selectedRegisterDomains.value[0]
    }
  }
)

watch(
  () => registerForm.value.mailProvider,
  () => {
    outlookPoolStatus.value = null
    outlookPoolError.value = ''
    outlookPoolSelectedEmails.value = []
    outlookPoolStatusFilter.value = isICloudProvider.value ? 'available' : 'all'
    if (!mailProviderWatchReady) return
    if (isOutlookLikePoolProvider.value) loadOutlookPoolStatus()
    if (isMailComProvider.value) loadMailComPoolStatus()
  }
)

watch(
  outlookPoolStatusFilter,
  () => {
    pruneOutlookPoolSelectionToVisible()
  }
)

watch(
  isMailComProvider,
  enabled => {
    if (!mailProviderWatchReady) return
    if (enabled) loadMailComPoolStatus()
  }
)

watch(
  () => registerForm.value.oauthPhoneSmsProvider,
  async (provider, previousProvider) => {
    const normalizedProvider = String(provider || 'phone_pool')
    const normalizedPreviousProvider = String(previousProvider || '')
    const currentCountry = String(registerForm.value.oauthPhoneSmsCountry || '').trim()
    const currentMaxPrice = String(registerForm.value.oauthPhoneSmsMaxPrice || '').trim()
    if (normalizedPreviousProvider && !oauthPhoneSmsCountryDisabled(normalizedPreviousProvider) && currentCountry) {
      savedOauthPhoneSmsCountries[normalizedPreviousProvider] = currentCountry
    }
    if (normalizedPreviousProvider && !oauthPhoneSmsCountryDisabled(normalizedPreviousProvider)) {
      savedOauthPhoneSmsMaxPrices[normalizedPreviousProvider] = currentMaxPrice
    }
    if (oauthPhoneSmsCountryDisabled(normalizedProvider)) {
      registerForm.value.oauthPhoneSmsCountry = ''
      registerForm.value.oauthPhoneSmsMaxPrice = ''
      oauthPhoneSmsCountryOptions.value = []
      syncOAuthPhoneSmsCountrySearch()
      return
    }
    const rememberedCountry = String(savedOauthPhoneSmsCountries[normalizedProvider] || '').trim()
    const configuredCountry = configuredOAuthPhoneCountry(normalizedProvider)
    const nextCountry = rememberedCountry || configuredCountry
    if (nextCountry) {
      registerForm.value.oauthPhoneSmsCountry = nextCountry
    }
    const hasRememberedMaxPrice = Object.prototype.hasOwnProperty.call(savedOauthPhoneSmsMaxPrices, normalizedProvider)
    const rememberedMaxPrice = String(savedOauthPhoneSmsMaxPrices[normalizedProvider] || '').trim()
    const configuredMaxPrice = configuredOAuthPhoneMaxPrice(normalizedProvider)
    registerForm.value.oauthPhoneSmsMaxPrice = hasRememberedMaxPrice ? rememberedMaxPrice : configuredMaxPrice
    await loadOAuthPhoneSmsCountries(normalizedProvider)
    syncOAuthPhoneSmsCountrySearch()
  },
  { flush: 'sync' }
)

function scheduleRegisterInit(fn, delayMs) {
  const timer = window.setTimeout(() => {
    registerInitTimers = registerInitTimers.filter(item => item !== timer)
    if (!registerPageMounted) return
    fn()
  }, delayMs)
  registerInitTimers.push(timer)
}

function startRegisterPolling() {
  if (!statsTimer) {
    statsTimer = window.setInterval(loadRegisterStats, REGISTER_POLL_INTERVAL_MS)
  }
  if (!logsTimer) {
    logsTimer = window.setInterval(loadRegisterLogs, REGISTER_POLL_INTERVAL_MS)
  }
}

function stopRegisterPolling() {
  if (logsTimer) {
    window.clearInterval(logsTimer)
    logsTimer = null
  }
  if (statsTimer) {
    window.clearInterval(statsTimer)
    statsTimer = null
  }
}

onMounted(() => {
  registerPageMounted = true
  window.addEventListener('keydown', handleGlobalKeydown)
  loadSavedRegisterForm()
  scheduleRegisterInit(() => {
    reloadRegisterDomains()
  }, 50)
  scheduleRegisterInit(async () => {
    await loadMailProviderOptions()
    if (!registerPageMounted) return
    mailProviderWatchReady = true
  }, 100)
  scheduleRegisterInit(() => {
    loadOAuthPhoneSmsConfig()
  }, 150)
  scheduleRegisterInit(() => {
    loadRegisterStats()
  }, 300)
  scheduleRegisterInit(() => {
    loadRegisterLogs()
    if (props.runningTask) startRegisterPolling()
  }, 600)
})
onUnmounted(() => {
  registerPageMounted = false
  window.removeEventListener('keydown', handleGlobalKeydown)
  mailProviderWatchReady = false
  for (const timer of registerInitTimers) {
    window.clearTimeout(timer)
  }
  registerInitTimers = []
  stopRegisterPolling()
})
watch(() => props.runningTask?.task_id, (newId, oldId) => {
  if (newId !== oldId) {
    registerCancelBusy.value = false
    registerCancelRequested.value = false
  }
  if (newId) {
    loadRegisterLogs()
    loadRegisterStats()
    startRegisterPolling()
  }
  if (oldId && !newId) {
    stopRegisterPolling()
    reloadRegisterDomains()
    if (isOutlookLikePoolProvider.value) loadOutlookPoolStatus()
    if (isMailComProvider.value) loadMailComPoolStatus()
    loadRegisterLogs()
    loadRegisterStats()
  }
})
watch(() => props.runningTask?.cancel_requested, value => {
  if (value) registerCancelRequested.value = true
}, { immediate: true })

function fmtLogTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function fmtTaskTime(ts) {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function logLevelClass(level) {
  const value = String(level || '').toUpperCase()
  if (value === 'ERROR') return 'text-red-400'
  if (value === 'WARNING') return 'text-amber-300'
  if (value === 'INFO') return 'text-sky-400'
  return 'text-gray-400'
}
</script>
