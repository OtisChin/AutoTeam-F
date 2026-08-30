<template>
  <div class="mt-6 space-y-6 settings-page">
    <SettingsWorkspace v-model="activeSettingsSection" :sections="settingsSections" aria-label="设置工作区">
    <SettingsGroup id="appearance" title="外观" description="跟随设备，或为当前浏览器固定明亮/深色模式。" :open="true" v-show="activeSettingsSection === 'appearance'">
      <div class="settings-appearance" aria-labelledby="settings-appearance-title">
        <div>
          <span class="workspace-eyebrow">个性化</span>
          <h2 id="settings-appearance-title">外观</h2>
          <p>跟随设备，或为当前浏览器固定明亮/深色模式。</p>
        </div>
        <ThemeSwitcher mode="group" />
      </div>
    </SettingsGroup>
    <div v-if="message" class="rounded-lg border px-4 py-3 text-sm" :class="messageClass">
      {{ message }}
    </div>

    <SettingsGroup id="phone" title="OAuth 手机号接码" description="OAuth 手机号接码相关配置" tone="neutral" :disclosure="false" :open="settingsDisclosure.phone" v-show="activeSettingsSection === 'phone'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">OAuth 手机号接码</h2>
          <p class="text-sm text-gray-400 mt-1">
            OAuth 登录遇到 add-phone 时使用；国家 ID 在注册任务页按所选供应商单独选择。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="oauthPhoneSmsConfigured
            ? 'bg-green-500/10 text-green-400 border-green-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'">
          {{ oauthPhoneSmsConfigured ? '已配置' : '未配置' }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">手机号来源</label>
          <select
            v-model="oauthPhoneSmsForm.provider"
            :disabled="oauthPhoneSmsLoading || oauthPhoneSmsSaving"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="phone_pool">OAuth 手机号池</option>
            <option value="hero_sms">hero-sms</option>
            <option value="smsbower">smsbower</option>
            <option value="smscloud">SMSCloud</option>
            <option value="oasis">Oasis CDK</option>
            <option value="tujie">TuJie CDK</option>
          </select>
          <p class="mt-1 text-xs text-gray-500">手机号池适合固定号码；hero-sms / smsbower / SMSCloud 按国家买号；Oasis / TuJie 使用 CDK 池兑换号码。</p>
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">固定参数</label>
          <div class="rounded-lg border border-gray-800 bg-gray-950 px-3 py-2 text-sm text-gray-300">
            服务：OpenAI（service: dr）/ 国家：注册任务页选择
          </div>
        </div>
        <template v-if="oauthPhoneSmsForm.provider === 'hero_sms'">
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              hero-sms API Key
              <span v-if="oauthPhoneSmsStatus.hero_sms_api_key_present" class="text-xs text-green-400 ml-1">已保存</span>
            </label>
            <input
              v-model="oauthPhoneSmsForm.hero_sms_api_key"
              type="password"
              autocomplete="off"
              :placeholder="oauthPhoneSmsStatus.hero_sms_api_key_masked || '留空则保留现有配置'"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">hero-sms 最低价格</label>
            <input
              v-model.trim="oauthPhoneSmsForm.hero_sms_min_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.1，留空不限下限"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">填 0.1 时，0.1 以下的号码不会取。</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">hero-sms 最高价格</label>
            <input
              v-model.trim="oauthPhoneSmsForm.hero_sms_max_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.045，留空不限价"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">作为价格上限；留空则不限上限。</p>
          </div>
        </template>
        <template v-if="oauthPhoneSmsForm.provider === 'smsbower'">
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              smsbower API Key
              <span v-if="oauthPhoneSmsStatus.smsbower_api_key_present" class="text-xs text-green-400 ml-1">已保存</span>
            </label>
            <input
              v-model="oauthPhoneSmsForm.smsbower_api_key"
              type="password"
              autocomplete="off"
              :placeholder="oauthPhoneSmsStatus.smsbower_api_key_masked || '留空则保留现有配置'"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">smsbower 最低价格</label>
            <input
              v-model.trim="oauthPhoneSmsForm.smsbower_min_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.1，留空不限下限"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">填 0.1 时，0.1 以下的 provider 不会取。</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">smsbower 最高价格</label>
            <input
              v-model.trim="oauthPhoneSmsForm.smsbower_max_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.045，留空不限价"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">作为价格上限；留空则不限上限。</p>
          </div>
        </template>
        <template v-if="oauthPhoneSmsForm.provider === 'smscloud'">
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              SMSCloud API Key
              <span v-if="oauthPhoneSmsStatus.smscloud_api_key_present" class="text-xs text-green-400 ml-1">已保存</span>
            </label>
            <input
              v-model="oauthPhoneSmsForm.smscloud_api_key"
              type="password"
              autocomplete="off"
              :placeholder="oauthPhoneSmsStatus.smscloud_api_key_masked || '留空则保留现有配置'"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">SMSCloud 最低价格</label>
            <input
              v-model.trim="oauthPhoneSmsForm.smscloud_min_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.05，留空不限下限"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">填 0.05 时，实际扣费低于 0.05 的号码会取消并换号。</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">SMSCloud 最高价格</label>
            <input
              v-model.trim="oauthPhoneSmsForm.smscloud_max_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.08，留空不限价"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">作为 maxPrice 传给 SMSCloud flexible 取号接口。</p>
          </div>
        </template>
        <template v-if="oauthPhoneSmsForm.provider === 'oasis'">
          <div class="md:col-span-2">
            <label class="block text-sm text-gray-400 mb-1">
              Oasis CDK 池
              <span v-if="oauthPhoneSmsStatus.oasis_sms_cdk_count" class="text-xs text-green-400 ml-1">
                已保存 {{ oauthPhoneSmsStatus.oasis_sms_cdk_count }} 个
              </span>
            </label>
            <textarea
              v-model.trim="oauthPhoneSmsForm.oasis_sms_cdks"
              rows="5"
              spellcheck="false"
              autocomplete="off"
              placeholder="一行一个或粘贴多个 CDK，例如 SMS-6L2A-6TAH-Q7BA"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white font-mono focus:outline-none focus:border-blue-500"
            ></textarea>
            <p class="mt-1 text-xs text-gray-500">每个 CDK 只对应一个号码和验证码，注册成功后会保存 CDK 与账号的映射。</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              CDK 文件
              <span v-if="oauthPhoneSmsStatus.oasis_sms_cdk_file_present" class="text-xs text-green-400 ml-1">已配置</span>
            </label>
            <input
              v-model.trim="oauthPhoneSmsForm.oasis_sms_cdk_file"
              type="text"
              autocomplete="off"
              placeholder="例如 data/oasis_cdks.txt"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">Oasis API 地址</label>
            <input
              v-model.trim="oauthPhoneSmsForm.oasis_sms_base_url"
              type="text"
              autocomplete="off"
              placeholder="https://sms.oapi.vip"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">账号映射文件</label>
            <input
              v-model.trim="oauthPhoneSmsForm.oasis_sms_account_map_file"
              type="text"
              autocomplete="off"
              placeholder="oasis-cdk-accounts.jsonl"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">轮询次数</label>
              <input
                v-model.trim="oauthPhoneSmsForm.oasis_sms_poll_attempts"
                type="number"
                min="1"
                autocomplete="off"
                placeholder="24"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">轮询间隔 ms</label>
              <input
                v-model.trim="oauthPhoneSmsForm.oasis_sms_poll_interval_ms"
                type="number"
                min="500"
                autocomplete="off"
                placeholder="5000"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        </template>
        <template v-if="oauthPhoneSmsForm.provider === 'tujie'">
          <div class="md:col-span-2">
            <label class="block text-sm text-gray-400 mb-1">
              TuJie CDK 池
              <span v-if="oauthPhoneSmsStatus.tujie_sms_cdk_count" class="text-xs text-green-400 ml-1">
                已保存 {{ oauthPhoneSmsStatus.tujie_sms_cdk_count }} 个
              </span>
            </label>
            <textarea
              v-model.trim="oauthPhoneSmsForm.tujie_sms_cdks"
              rows="5"
              spellcheck="false"
              autocomplete="off"
              placeholder="一行一个或粘贴多个 CDK，例如 SMS-AE4H6TLEZV5H69SJGQ"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white font-mono focus:outline-none focus:border-blue-500"
            ></textarea>
            <p class="mt-1 text-xs text-gray-500">每个 CDK 只对应一个号码和验证码，OAuth 成功后会保存 CDK 与账号的映射。</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              CDK 文件
              <span v-if="oauthPhoneSmsStatus.tujie_sms_cdk_file_present" class="text-xs text-green-400 ml-1">已配置</span>
            </label>
            <input
              v-model.trim="oauthPhoneSmsForm.tujie_sms_cdk_file"
              type="text"
              autocomplete="off"
              placeholder="例如 data/tujie_cdks.txt"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">TuJie 取码页面地址</label>
            <input
              v-model.trim="oauthPhoneSmsForm.tujie_sms_base_url"
              type="text"
              autocomplete="off"
              placeholder="填写 TuJie 页面地址；支持 {cdk} 占位符"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">账号映射文件</label>
            <input
              v-model.trim="oauthPhoneSmsForm.tujie_sms_account_map_file"
              type="text"
              autocomplete="off"
              placeholder="tujie-cdk-accounts.jsonl"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-sm text-gray-400 mb-1">轮询次数</label>
              <input
                v-model.trim="oauthPhoneSmsForm.tujie_sms_poll_attempts"
                type="number"
                min="1"
                autocomplete="off"
                placeholder="24"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label class="block text-sm text-gray-400 mb-1">轮询间隔 ms</label>
              <input
                v-model.trim="oauthPhoneSmsForm.tujie_sms_poll_interval_ms"
                type="number"
                min="500"
                autocomplete="off"
                placeholder="5000"
                class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>
        </template>
      </div>

      <div class="mt-3 flex justify-end gap-3">
        <button
          @click="loadOAuthPhoneSmsConfig"
          :disabled="oauthPhoneSmsLoading || oauthPhoneSmsSaving"
          class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
        >
          {{ oauthPhoneSmsLoading ? '刷新中...' : '刷新配置' }}
        </button>
        <button
          @click="saveOAuthPhoneSmsConfig"
          :disabled="oauthPhoneSmsSaving"
          class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ oauthPhoneSmsSaving ? '保存中...' : '保存 OAuth 接码配置' }}
        </button>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="maintenance" title="配置导入 / 导出" description="配置导入 / 导出相关配置" tone="danger" :disclosure="true" :open="settingsDisclosure.maintenance" @update:open="settingsDisclosure.maintenance = $event" v-show="activeSettingsSection === 'maintenance'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-start justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">配置导入 / 导出</h2>
          <button type="button" class="ui-button ui-button-quiet" @click="emit('navigate', 'logs')">查看运行日志</button>
          <p class="text-sm text-gray-400 mt-1">
            导出设置页相关配置为 JSON，包含 API Key、短信服务商、代理、Rekberinaja 等敏感密钥，只在可信设备间传递。
          </p>
        </div>
        <span
          v-if="configImportExportBusy"
          class="px-3 py-1.5 rounded-full text-xs text-blue-200 border border-blue-500/30 bg-blue-500/10 whitespace-nowrap"
        >
          处理中
        </span>
      </div>

      <textarea
        v-model="configImportText"
        rows="5"
        spellcheck="false"
        placeholder="可粘贴导出的配置 JSON，或点击“选择 JSON 文件”导入"
        class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white font-mono focus:outline-none focus:border-blue-500"
      ></textarea>
      <input
        ref="configImportFileInput"
        type="file"
        accept="application/json,.json"
        class="hidden"
        @change="onConfigImportFileSelected"
      />

      <div class="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-xs text-gray-500">
          导入会写回 `.env`，并同步账号 Hub、注册域名、巡检和自动刷新配置。
        </p>
        <div class="flex flex-wrap gap-3">
          <button
            @click="exportConfig"
            :disabled="configExporting || configImporting"
            class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
          >
            {{ configExporting ? '导出中...' : '导出配置' }}
          </button>
          <button
            @click="configImportFileInput?.click()"
            :disabled="configExporting || configImporting"
            class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
          >
            选择 JSON 文件
          </button>
          <button
            @click="importConfig"
            :disabled="configImporting || !configImportText.trim()"
            class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
          >
            {{ configImporting ? '导入中...' : '导入配置' }}
          </button>
        </div>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="integrations" title="RoxyBrowser" description="RoxyBrowser相关配置" tone="neutral" :disclosure="false" :open="settingsDisclosure.integrations" v-show="activeSettingsSection === 'integrations'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">RoxyBrowser</h2>
          <p class="text-sm text-gray-400 mt-1">
            配置浏览器自动化使用 RoxyBrowser 模式时连接本机客户端所需的 API 参数。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="roxyBrowserConfigured
            ? 'bg-green-500/10 text-green-400 border-green-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'">
          {{ roxyBrowserConfigured ? '已配置' : '未配置' }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">API 地址</label>
          <input
            v-model.trim="roxyBrowserForm.api_host"
            type="text"
            autocomplete="off"
            placeholder="http://127.0.0.1:50000"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">
            API Token
            <span v-if="roxyBrowserStatus.api_token_present" class="text-xs text-green-400 ml-1">已保存</span>
          </label>
          <input
            v-model="roxyBrowserForm.api_token"
            type="password"
            autocomplete="off"
            :placeholder="roxyBrowserStatus.api_token_masked || '请输入 RoxyBrowser API Token'"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <p class="mt-1 text-xs text-gray-500">已有 Token 时留空会保留原配置。</p>
        </div>
      </div>

      <div v-if="!roxyBrowserConfigured" class="mt-4 rounded-lg border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        选择 RoxyBrowser 模式前，需要先保存 API Token。
      </div>

      <div class="mt-3 flex justify-end gap-3">
        <button
          @click="loadRoxyBrowserConfig"
          :disabled="roxyBrowserLoading || roxyBrowserSaving"
          class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
        >
          {{ roxyBrowserLoading ? '刷新中...' : '刷新配置' }}
        </button>
        <button
          @click="saveRoxyBrowserConfig"
          :disabled="roxyBrowserSaving"
          class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ roxyBrowserSaving ? '保存中...' : '保存 RoxyBrowser 配置' }}
        </button>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="payments" title="GoPay 自动注册" description="GoPay 自动注册相关配置" tone="warning" :disclosure="true" :open="settingsDisclosure.payments" @update:open="settingsDisclosure.payments = $event" v-show="activeSettingsSection === 'payments'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">GoPay 自动注册</h2>
          <p class="text-sm text-gray-400 mt-1">
            配置自动注册 GoPay 钱包时使用的短信服务商凭证。GoPay 任务页面只选择服务商，不直接输入密钥。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="gopayAutoSignupConfigured
            ? 'bg-green-500/10 text-green-400 border-green-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'">
          {{ gopayAutoSignupConfigured ? '已配置' : '未配置' }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">短信服务商</label>
          <select
            v-model="gopayAutoSignupForm.provider"
            :disabled="gopayAutoSignupLoading || gopayAutoSignupSaving"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="smscloud">smscloud</option>
            <option value="hero_sms">hero-sms</option>
            <option value="smsbower">smsbower</option>
            <option value="smscode">smscode.gg</option>
          </select>
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">注册模式</label>
          <select
            v-model="gopayAutoSignupForm.signup_mode"
            :disabled="gopayAutoSignupLoading || gopayAutoSignupSaving"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="http">协议绑定</option>
            <option value="appium">Appium</option>
          </select>
          <p class="mt-1 text-xs text-gray-500">Appium 模式会走真实 GoPay APP 注册、主页补设 PIN，并复用同一短信会话收第二个 OTP。</p>
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">GoPay 注册/PIN 印尼代理
            <span v-if="gopayAutoSignupStatus.proxy_url_present" class="text-xs text-green-400 ml-1">已保存</span>
          </label>
          <input
            v-model.trim="gopayAutoSignupForm.proxy_url"
            type="password"
            autocomplete="off"
            placeholder="socks5://user:pass@host:port，留空直连"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <p class="mt-1 text-xs text-gray-500">只用于 GoPay 注册和设置 PIN 阶段；绑定 checkout/支付阶段仍按任务逻辑直连。</p>
        </div>
        <div v-if="gopayAutoSignupForm.signup_mode === 'appium'">
          <label class="block text-sm text-gray-400 mb-1">Appium URL</label>
          <input
            v-model.trim="gopayAutoSignupForm.appium_url"
            type="text"
            autocomplete="off"
            placeholder="http://127.0.0.1:4723"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div v-if="gopayAutoSignupForm.signup_mode === 'appium'">
          <label class="block text-sm text-gray-400 mb-1">ADB Serial</label>
          <input
            v-model.trim="gopayAutoSignupForm.appium_adb_serial"
            type="text"
            autocomplete="off"
            placeholder="emulator-5556"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <p class="mt-1 text-xs text-gray-500">例如 emulator-5556。留空时由后端按默认设备选择逻辑处理。</p>
        </div>
        <div v-if="gopayAutoSignupForm.provider === 'smscloud'">
          <label class="block text-sm text-gray-400 mb-1">
            smscloud XI_TOKEN
            <span v-if="gopayAutoSignupStatus.smscloud_xi_token_present" class="text-xs text-green-400 ml-1">已保存</span>
          </label>
          <input
            v-model="gopayAutoSignupForm.smscloud_xi_token"
            type="password"
            autocomplete="off"
            :placeholder="gopayAutoSignupStatus.smscloud_xi_token_masked || '留空则保留现有配置'"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          <p class="mt-1 text-xs text-gray-500">填写 smscloud 登录后浏览器 localStorage 里的 XI_TOKEN，不是资料页 API密钥。</p>
        </div>
        <div v-else-if="gopayAutoSignupForm.provider === 'hero_sms'" class="grid grid-cols-1 gap-4 md:grid-cols-2 md:col-span-2">
          <div>
          <label class="block text-sm text-gray-400 mb-1">
            hero-sms API Key
            <span v-if="gopayAutoSignupStatus.hero_sms_api_key_present" class="text-xs text-green-400 ml-1">已保存</span>
          </label>
          <input
            v-model="gopayAutoSignupForm.hero_sms_api_key"
            type="password"
            autocomplete="off"
            :placeholder="gopayAutoSignupStatus.hero_sms_api_key_masked || '留空则保留现有配置'"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">hero-sms API 地址</label>
            <input
              v-model.trim="gopayAutoSignupForm.hero_sms_base_url"
              type="text"
              autocomplete="off"
              placeholder="https://hero-sms.com/stubs/handler_api.php"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">国家 ID</label>
            <input
              v-model.trim="gopayAutoSignupForm.hero_sms_country"
              type="text"
              autocomplete="off"
              placeholder="6"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">服务代码</label>
            <input
              v-model.trim="gopayAutoSignupForm.hero_sms_service"
              type="text"
              autocomplete="off"
              placeholder="ni"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">hero-sms 最低购买价</label>
            <input
              v-model.trim="gopayAutoSignupForm.hero_sms_min_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.06，留空不限下限"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">hero-sms 最高价格</label>
            <input
              v-model.trim="gopayAutoSignupForm.hero_sms_max_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.045，留空不限价"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">会作为 maxPrice 传给取号接口，超过该价格的号码不会购买。</p>
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">hero-sms 指定档位</label>
            <input
              v-model.trim="gopayAutoSignupForm.hero_sms_preferred_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="例如 0.09，留空按价格从低到高"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <p class="mt-1 text-xs text-gray-500">指定档位必须在最低价/最高价区间内，否则会被忽略。</p>
          </div>
        </div>
        <div v-else-if="gopayAutoSignupForm.provider === 'smsbower'" class="grid grid-cols-1 gap-4 md:grid-cols-2 md:col-span-2">
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              smsbower API Key
              <span v-if="gopayAutoSignupStatus.smsbower_api_key_present" class="text-xs text-green-400 ml-1">已保存</span>
            </label>
            <input
              v-model="gopayAutoSignupForm.smsbower_api_key"
              type="password"
              autocomplete="off"
              :placeholder="gopayAutoSignupStatus.smsbower_api_key_masked || '留空则保留现有配置'"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">smsbower API 地址</label>
            <input
              v-model.trim="gopayAutoSignupForm.smsbower_base_url"
              type="text"
              autocomplete="off"
              placeholder="https://smsbower.page/stubs/handler_api.php"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">国家 ID</label>
            <input
              v-model.trim="gopayAutoSignupForm.smsbower_country"
              type="text"
              autocomplete="off"
              placeholder="6"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">服务代码</label>
            <input
              v-model.trim="gopayAutoSignupForm.smsbower_service"
              type="text"
              autocomplete="off"
              placeholder="ni"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">smsbower 最低购买价</label>
            <input
              v-model.trim="gopayAutoSignupForm.smsbower_min_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="留空不限下限"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">smsbower 最高价格</label>
            <input
              v-model.trim="gopayAutoSignupForm.smsbower_max_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="留空不限价"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">smsbower 指定档位</label>
            <input
              v-model.trim="gopayAutoSignupForm.smsbower_preferred_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="留空按价格从低到高"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
        <div v-else-if="gopayAutoSignupForm.provider === 'smscode'" class="grid grid-cols-1 gap-4 md:grid-cols-2 md:col-span-2">
          <div>
            <label class="block text-sm text-gray-400 mb-1">
              SMSCode API Token
              <span v-if="gopayAutoSignupStatus.smscode_api_token_present" class="text-xs text-green-400 ml-1">已保存</span>
            </label>
            <input
              v-model="gopayAutoSignupForm.smscode_api_token"
              type="password"
              autocomplete="off"
              :placeholder="gopayAutoSignupStatus.smscode_api_token_masked || '留空则保留现有配置'"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">SMSCode API 地址</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_base_url"
              type="text"
              autocomplete="off"
              placeholder="https://api.smscode.gg/v1"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">国家 ID</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_country_id"
              type="text"
              autocomplete="off"
              placeholder="7"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">平台关键词</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_platform_query"
              type="text"
              autocomplete="off"
              placeholder="gopay"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">平台 ID（可选）</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_platform_id"
              type="text"
              autocomplete="off"
              placeholder="留空则按关键词查询"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">产品 ID（可选）</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_product_id"
              type="text"
              autocomplete="off"
              placeholder="留空则按价格筛选最低可用产品"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">最低购买价</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_min_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="留空不限下限"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label class="block text-sm text-gray-400 mb-1">最高价格</label>
            <input
              v-model.trim="gopayAutoSignupForm.smscode_max_price"
              type="text"
              inputmode="decimal"
              autocomplete="off"
              placeholder="留空不限价"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <div class="mt-3 flex justify-end gap-3">
        <button
          @click="loadGoPayAutoSignupConfig"
          :disabled="gopayAutoSignupLoading || gopayAutoSignupSaving"
          class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
        >
          {{ gopayAutoSignupLoading ? '刷新中...' : '刷新配置' }}
        </button>
        <button
          @click="saveGoPayAutoSignupConfig"
          :disabled="gopayAutoSignupSaving"
          class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ gopayAutoSignupSaving ? '保存中...' : '保存 GoPay 配置' }}
        </button>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="payments-rekberinaja" title="Rekberinaja GoPay 充值" description="Rekberinaja GoPay 充值相关配置" tone="warning" :disclosure="true" :open="settingsDisclosure.payments" @update:open="settingsDisclosure.payments = $event" v-show="activeSettingsSection === 'payments'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">Rekberinaja GoPay 充值</h2>
          <p class="text-sm text-gray-400 mt-1">
            转账开关默认关闭。开启后，自动注册 GoPay 钱包完成 PIN 设置后，使用 Rekberinaja 站内余额充值最低 GoPay 面额；关闭时不转账，先等待 60 秒后首次绑定，若疑似 1rp 未到账会复用同一钱包延长等待重试。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="rekberinajaConfigured
            ? 'bg-green-500/10 text-green-400 border-green-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'">
          {{ rekberinajaConfigured ? '已启用' : '未启用' }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <label class="inline-flex items-center gap-2 text-sm text-gray-300 md:col-span-2">
          <input v-model="rekberinajaForm.enabled" type="checkbox" class="accent-blue-500" />
          启用 Rekberinaja 站内余额充值/转账
        </label>
        <div>
          <label class="block text-sm text-gray-400 mb-1">登录邮箱</label>
          <input
            v-model.trim="rekberinajaForm.email"
            type="email"
            autocomplete="off"
            placeholder="Rekberinaja 账号邮箱"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">
            登录密码
            <span v-if="rekberinajaStatus.password_present" class="text-xs text-green-400 ml-1">已保存</span>
          </label>
          <input
            v-model="rekberinajaForm.password"
            type="password"
            autocomplete="off"
            :placeholder="rekberinajaStatus.password_masked || '留空则保留现有配置'"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">最低余额要求</label>
          <input
            v-model.number="rekberinajaForm.min_balance"
            type="number"
            min="0"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">到账等待超时（秒）</label>
          <input
            v-model.number="rekberinajaForm.poll_timeout"
            type="number"
            min="10"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
        <div class="md:col-span-2">
          <label class="block text-sm text-gray-400 mb-1">Invoice Email（可选）</label>
          <input
            v-model.trim="rekberinajaForm.invoice_email"
            type="email"
            autocomplete="off"
            placeholder="留空即可"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          />
        </div>
      </div>

      <div class="mt-3 flex justify-end gap-3">
        <button
          @click="loadRekberinajaConfig"
          :disabled="rekberinajaLoading || rekberinajaSaving"
          class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
        >
          {{ rekberinajaLoading ? '刷新中...' : '刷新配置' }}
        </button>
        <button
          @click="saveRekberinajaConfig"
          :disabled="rekberinajaSaving"
          class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ rekberinajaSaving ? '保存中...' : '保存 Rekberinaja 配置' }}
        </button>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="accounts" title="邮件 Provider" description="邮件 Provider相关配置" tone="neutral" :disclosure="false" :open="settingsDisclosure.accounts" v-show="activeSettingsSection === 'accounts'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">邮件 Provider</h2>
          <p class="text-sm text-gray-400 mt-1">
            配置注册账号时使用的接码服务。LuckMail 支持已购邮箱 token，格式为 email----tok_xxx。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="mailProvider
            ? 'bg-green-500/10 text-green-400 border-green-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'">
          {{ mailProvider || '未配置' }}
        </span>
      </div>

      <div class="space-y-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">Mail Provider</label>
          <select
            v-model="mailProvider"
            :disabled="mailSetupLoading || mailSetupSaving"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option v-for="option in mailProviderOptions" :key="option.value" :value="option.value">
              {{ option.label }} ({{ option.description }})
            </option>
          </select>
        </div>

        <div v-if="mailProviderFieldTitle" class="text-xs font-semibold uppercase tracking-wide text-gray-500">
          {{ mailProviderFieldTitle }}
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div
            v-for="field in mailProviderFields"
            :key="field.key"
            :class="isLongTextField(field.key) ? 'md:col-span-2' : ''"
          >
            <label class="block text-sm text-gray-400 mb-1">
              {{ field.prompt }}
              <span v-if="!field.optional" class="text-red-400">*</span>
              <span v-if="field.configured" class="text-xs text-green-400 ml-1">已保存</span>
            </label>
            <textarea
              v-if="isLongTextField(field.key)"
              v-model="mailProviderForm[field.key]"
              rows="4"
              spellcheck="false"
              :placeholder="field.default || ''"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white font-mono focus:outline-none focus:border-blue-500"
            ></textarea>
            <input
              v-else
              v-model="mailProviderForm[field.key]"
              :type="isSecretField(field.key) ? 'password' : 'text'"
              :placeholder="field.default || ''"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>

        <div class="flex justify-end gap-3">
          <button
            @click="loadMailProviderConfig"
            :disabled="mailSetupLoading || mailSetupSaving"
            class="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-sm text-gray-200 rounded-lg border border-gray-700 transition disabled:opacity-50"
          >
            {{ mailSetupLoading ? '刷新中...' : '刷新配置' }}
          </button>
          <button
            @click="saveMailProvider"
            :disabled="mailSetupSaving || !mailProvider"
            class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
          >
            {{ mailSetupSaving ? '验证并保存中...' : '保存邮件配置' }}
          </button>
        </div>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="accounts-hub" title="远程账号 Hub" description="远程账号 Hub相关配置" tone="neutral" :disclosure="true" :open="settingsDisclosure.accounts" @update:open="settingsDisclosure.accounts = $event" v-show="activeSettingsSection === 'accounts'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">远程账号 Hub</h2>
          <p class="text-sm text-gray-400 mt-1">
            将本机账号池和 data/auths 里的 CPA 凭证上传到一个中心节点，便于统一筛选和导出。
          </p>
        </div>
        <span
          class="min-w-[72px] px-3 py-1.5 rounded-full text-xs text-center whitespace-nowrap border"
          :class="accountHubConfigured
            ? 'bg-green-500/10 text-green-400 border-green-500/20'
            : 'bg-gray-800 text-gray-400 border-gray-700'">
          {{ accountHubConfigured ? '已配置' : '未配置' }}
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">远程 URL</label>
          <input
            v-model.trim="accountHubForm.url"
            type="text"
            placeholder="例如 http://192.168.1.10:8787 或 https://hub.example.com"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500" />
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">节点名称</label>
          <input
            v-model.trim="accountHubForm.name"
            type="text"
            placeholder="例如 pc-01 / vps-01"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500" />
        </div>
        <div class="md:col-span-2">
          <label class="block text-sm text-gray-400 mb-1">Token</label>
          <input
            v-model="accountHubForm.token"
            type="password"
            autocomplete="off"
            placeholder="所有节点和 Hub 端保持一致"
            class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500" />
          <div class="text-xs text-gray-500 mt-2">
            作为中心 Hub 的机器也需要配置同一个 Token；作为上传节点时再填写远程 URL。
          </div>
        </div>
      </div>

      <div class="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label class="inline-flex items-center gap-2 text-sm text-gray-300">
          <input v-model="accountHubForm.auto_upload" type="checkbox" class="accent-blue-500" />
          每 5 分钟自动同步可用且已有凭证的 Plus / Team / Pro 账号到账号 Hub
        </label>
        <div class="flex flex-wrap gap-3">
          <button
            @click="testAccountHub"
            :disabled="accountHubBusy || !accountHubForm.url || !accountHubForm.token"
            class="px-4 py-2 rounded-lg text-sm border transition"
            :class="accountHubBusy || !accountHubForm.url || !accountHubForm.token
              ? 'bg-gray-800 text-gray-500 border-gray-700 cursor-not-allowed'
              : 'bg-emerald-600/15 hover:bg-emerald-600/25 text-emerald-200 border-emerald-500/30'">
            {{ accountHubTesting ? '测试中...' : '连接测试' }}
          </button>
          <button
            @click="saveAccountHub"
            :disabled="accountHubBusy"
            class="px-4 py-2 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50">
            {{ accountHubSaving ? '保存中...' : '保存 Hub 配置' }}
          </button>
        </div>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="accounts-domains" title="注册域名设置" description="注册域名设置相关配置" tone="neutral" :disclosure="false" :open="settingsDisclosure.accounts" v-show="activeSettingsSection === 'accounts'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">注册域名设置</h2>
          <p class="text-sm text-gray-400 mt-1">
            维护“注册账号”页面可选的域名列表。一个域名一行，或使用逗号分隔。
          </p>
        </div>
        <button
          @click="loadRegisterDomains"
          :disabled="registerDomainLoading"
          class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50"
        >
          {{ registerDomainLoading ? '刷新中...' : '刷新域名' }}
        </button>
      </div>

      <div class="space-y-3">
        <textarea
          v-model="registerDomainsText"
          rows="4"
          spellcheck="false"
          placeholder="openaibus.com&#10;mail2.example.com"
          class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500"
        ></textarea>
        <div class="flex items-center justify-between gap-3">
          <div class="text-xs text-gray-500">当前共 {{ parsedRegisterDomains.length }} 个域名</div>
          <button
            @click="saveRegisterDomains"
            :disabled="registerDomainSaving || !parsedRegisterDomains.length"
            class="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white text-sm rounded-lg transition disabled:opacity-50"
          >
            {{ registerDomainSaving ? '保存中...' : '保存域名列表' }}
          </button>
        </div>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="automation" title="自动刷新额度" description="自动刷新额度相关配置" tone="neutral" :disclosure="false" :open="settingsDisclosure.automation" v-show="activeSettingsSection === 'automation'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between gap-4 mb-4">
        <div>
          <h2 class="text-lg font-semibold text-white">自动刷新额度</h2>
          <p class="text-sm text-gray-400 mt-1">
            按固定间隔后台刷新账号额度快照，使用“刷新额度”的并发逻辑；已有刷新任务运行时会自动跳过本轮。
          </p>
        </div>
        <span v-if="quotaRefreshSaved" class="text-xs text-green-400 transition">已保存</span>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <label class="inline-flex items-center gap-2 text-sm text-gray-300">
          <input v-model="quotaRefreshForm.enabled" type="checkbox" class="accent-blue-500" />
          启用自动刷新额度
        </label>
        <div>
          <label class="block text-sm text-gray-400 mb-1">刷新间隔</label>
          <div class="flex items-center gap-2">
            <input
              v-model.number="quotaRefreshForm.interval"
              type="number"
              min="1"
              :disabled="!quotaRefreshForm.enabled"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500 disabled:opacity-50"
            />
            <span class="text-sm text-gray-500 shrink-0">分钟</span>
          </div>
        </div>
      </div>

      <div class="mt-3 flex items-center justify-between gap-3">
        <p class="text-xs text-gray-500">
          {{ quotaRefreshForm.enabled ? `每 ${quotaRefreshForm.interval || 1} 分钟自动执行一次刷新额度任务` : '当前关闭，不会自动刷新额度' }}
        </p>
        <button
          @click="saveAutoRefreshQuota"
          :disabled="quotaRefreshSaving"
          class="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {{ quotaRefreshSaving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>

    </SettingsGroup>

    <SettingsGroup id="automation-inspection" title="巡检设置" description="巡检设置相关配置" tone="neutral" :disclosure="true" :open="settingsDisclosure.automation" @update:open="settingsDisclosure.automation = $event" v-show="activeSettingsSection === 'automation'">
    <div class="bg-gray-900 border border-gray-800 rounded-xl p-4 settings-legacy-panel">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-lg font-semibold text-white">巡检设置</h2>
        <span v-if="saved" class="text-xs text-green-400 transition">已保存</span>
      </div>

      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div>
          <label class="block text-sm text-gray-400 mb-1">巡检间隔</label>
          <div class="flex items-center gap-2">
            <input v-model.number="form.interval" type="number" min="1"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500" />
            <span class="text-sm text-gray-500 shrink-0">分钟</span>
          </div>
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">额度阈值</label>
          <div class="flex items-center gap-2">
            <input v-model.number="form.threshold" type="number" min="1" max="100"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500" />
            <span class="text-sm text-gray-500 shrink-0">%</span>
          </div>
        </div>
        <div>
          <label class="block text-sm text-gray-400 mb-1">触发账号数</label>
          <div class="flex items-center gap-2">
            <input v-model.number="form.min_low" type="number" min="1"
              class="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-white focus:outline-none focus:border-blue-500" />
            <span class="text-sm text-gray-500 shrink-0">个</span>
          </div>
        </div>
      </div>

      <div class="mt-3 flex items-center justify-between gap-3">
        <p class="text-xs text-gray-500">
          每 {{ form.interval }} 分钟检查一次，{{ form.min_low }} 个以上账号剩余低于 {{ form.threshold }}% 时自动轮转
        </p>
        <button @click="save" :disabled="saving"
          class="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded-lg transition disabled:opacity-50">
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
    </SettingsGroup>

    </SettingsWorkspace>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { api } from '../api.js'
import ThemeSwitcher from './ThemeSwitcher.vue'
import SettingsWorkspace from './settings/SettingsWorkspace.vue'
import SettingsGroup from './settings/SettingsGroup.vue'

const emit = defineEmits(['refresh', 'admin-progress', 'navigate'])

const settingsSections = Object.freeze([
  { id: 'appearance', label: '外观', description: '主题与显示' },
  { id: 'accounts', label: '账号与邮件', description: 'Hub、域名、邮件 Provider' },
  { id: 'phone', label: 'OAuth 手机号', description: '接码来源与国家' },
  { id: 'payments', label: '支付与钱包', description: 'GoPay、Rekberinaja' },
  { id: 'integrations', label: '集成', description: 'RoxyBrowser 与外部服务' },
  { id: 'automation', label: '自动化', description: '额度刷新与巡检' },
  { id: 'maintenance', label: '维护', description: '配置导入导出与日志' },
])
const activeSettingsSection = ref('appearance')
const settingsDisclosure = ref({ maintenance: false, payments: false, accounts: true, integrations: true, phone: true, automation: true, appearance: true })

const form = ref({ interval: 5, threshold: 10, min_low: 2 })
const saving = ref(false)
const saved = ref(false)
const quotaRefreshForm = ref({ enabled: false, interval: 30 })
const quotaRefreshSaving = ref(false)
const quotaRefreshSaved = ref(false)

const message = ref('')
const messageClass = ref('')
const configImportText = ref('')
const configImporting = ref(false)
const configExporting = ref(false)
const configImportFileInput = ref(null)
const registerDomainsText = ref('')
const registerDomainLoading = ref(false)
const registerDomainSaving = ref(false)
const accountHubForm = ref({ url: '', token: '', name: '', auto_upload: false })
const accountHubSaving = ref(false)
const accountHubTesting = ref(false)
const mailSetupLoading = ref(false)
const mailSetupSaving = ref(false)
const mailProvider = ref('cloudflare_temp_email')
const mailProviderOptions = ref([])
const mailProviderFieldGroups = ref({})
const mailProviderForm = ref({})
const gopayAutoSignupLoading = ref(false)
const gopayAutoSignupSaving = ref(false)
const gopayAutoSignupStatus = ref({})
const gopayAutoSignupForm = ref({
  provider: 'smscloud',
  country_code: '+62',
  smscloud_xi_token: '',
  hero_sms_api_key: '',
  hero_sms_base_url: 'https://hero-sms.com/stubs/handler_api.php',
  hero_sms_country: '6',
  hero_sms_service: 'ni',
  hero_sms_min_price: '',
  hero_sms_max_price: '',
  hero_sms_preferred_price: '',
  smsbower_api_key: '',
  smsbower_base_url: 'https://smsbower.page/stubs/handler_api.php',
  smsbower_country: '6',
  smsbower_service: 'ni',
  smsbower_min_price: '',
  smsbower_max_price: '',
  smsbower_preferred_price: '',
  smscode_api_token: '',
  smscode_base_url: 'https://api.smscode.gg/v1',
  smscode_country_id: '7',
  smscode_platform_id: '',
  smscode_platform_query: 'gojek',
  smscode_product_id: '',
  smscode_min_price: '',
  smscode_max_price: '',
  proxy_url: '',
  signup_mode: 'http',
  appium_url: 'http://127.0.0.1:4723',
  appium_adb_serial: '',
})
const oauthPhoneSmsLoading = ref(false)
const oauthPhoneSmsSaving = ref(false)
const oauthPhoneSmsStatus = ref({})
const oauthPhoneSmsForm = ref({
  provider: 'phone_pool',
  hero_sms_api_key: '',
  hero_sms_min_price: '',
  hero_sms_max_price: '',
  smsbower_api_key: '',
  smsbower_min_price: '',
  smsbower_max_price: '',
  smscloud_api_key: '',
  smscloud_min_price: '',
  smscloud_max_price: '',
  oasis_sms_cdks: '',
  oasis_sms_cdk_file: '',
  oasis_sms_base_url: 'https://sms.oapi.vip',
  oasis_sms_poll_attempts: '24',
  oasis_sms_poll_interval_ms: '5000',
  oasis_sms_account_map_file: 'oasis-cdk-accounts.jsonl',
  tujie_sms_cdks: '',
  tujie_sms_cdk_file: '',
  tujie_sms_base_url: 'https://tujie.xyz/api',
  tujie_sms_poll_attempts: '24',
  tujie_sms_poll_interval_ms: '5000',
  tujie_sms_account_map_file: 'tujie-cdk-accounts.jsonl',
})
const rekberinajaLoading = ref(false)
const rekberinajaSaving = ref(false)
const rekberinajaStatus = ref({})
const rekberinajaForm = ref({
  enabled: false,
  email: '',
  password: '',
  min_balance: 5000,
  poll_timeout: 180,
  invoice_email: '',
})
const roxyBrowserLoading = ref(false)
const roxyBrowserSaving = ref(false)
const roxyBrowserStatus = ref({})
const roxyBrowserForm = ref({
  api_host: 'http://127.0.0.1:50000',
  api_token: '',
})

const accountHubBusy = computed(() => accountHubSaving.value || accountHubTesting.value)
const configImportExportBusy = computed(() => configImporting.value || configExporting.value)
const accountHubConfigured = computed(() => Boolean(accountHubForm.value.token || accountHubForm.value.url))
const gopayAutoSignupConfigured = computed(() => {
  if (gopayAutoSignupForm.value.provider === 'hero_sms') return Boolean(gopayAutoSignupStatus.value.hero_sms_api_key_present)
  if (gopayAutoSignupForm.value.provider === 'smsbower') return Boolean(gopayAutoSignupStatus.value.smsbower_api_key_present)
  if (gopayAutoSignupForm.value.provider === 'smscode') return Boolean(gopayAutoSignupStatus.value.smscode_api_token_present)
  return Boolean(gopayAutoSignupStatus.value.smscloud_xi_token_present)
})
const oauthPhoneSmsConfigured = computed(() => {
  if (oauthPhoneSmsForm.value.provider === 'phone_pool') return true
  if (oauthPhoneSmsForm.value.provider === 'smsbower') return Boolean(oauthPhoneSmsStatus.value.smsbower_api_key_present)
  if (oauthPhoneSmsForm.value.provider === 'smscloud') return Boolean(oauthPhoneSmsStatus.value.smscloud_api_key_present)
  if (oauthPhoneSmsForm.value.provider === 'oasis') return Number(oauthPhoneSmsStatus.value.oasis_sms_cdk_count || 0) > 0
  if (oauthPhoneSmsForm.value.provider === 'tujie') {
    return Number(oauthPhoneSmsStatus.value.tujie_sms_cdk_count || 0) > 0 && Boolean(oauthPhoneSmsStatus.value.tujie_sms_base_url)
  }
  return Boolean(oauthPhoneSmsStatus.value.hero_sms_api_key_present)
})
const rekberinajaConfigured = computed(() => Boolean(rekberinajaStatus.value.configured || rekberinajaForm.value.enabled))
const roxyBrowserConfigured = computed(() => Boolean(roxyBrowserStatus.value.configured))
const mailProviderFields = computed(() => mailProviderFieldGroups.value[mailProvider.value] || [])
const mailProviderFieldTitle = computed(() =>
  mailProvider.value === 'cloud-mail'
    ? 'cloud-mail 配置'
    : mailProvider.value === 'outlook'
      ? 'Outlook 配置'
      : mailProvider.value === 'icloud'
        ? 'iCloud 配置'
        : mailProvider.value === 'luckmail'
          ? 'LuckMail 配置'
          : mailProvider.value === 'mailu'
            ? 'Mailu (自建) 配置'
            : 'cloudflare_temp_email 配置'
)

const parsedRegisterDomains = computed(() =>
  Array.from(new Set(
    registerDomainsText.value
      .split(/[\s,;|]+/)
      .map(v => v.trim().replace(/^@/, ''))
      .filter(Boolean)
  ))
)

onMounted(async () => {
  try {
    const cfg = await api.getAutoCheckConfig()
    form.value = {
      interval: Math.round(cfg.interval / 60),
      threshold: cfg.threshold,
      min_low: cfg.min_low,
    }
  } catch (e) {
    console.error('加载巡检配置失败:', e)
  }
  try {
    const cfg = await api.getAutoRefreshQuotaConfig()
    quotaRefreshForm.value = {
      enabled: !!cfg.enabled,
      interval: Math.max(1, Math.round((cfg.interval || 1800) / 60)),
    }
  } catch (e) {
    console.error('加载自动刷新额度配置失败:', e)
  }
  loadRegisterDomains()
  loadAccountHubConfig()
  loadGoPayAutoSignupConfig()
  loadOAuthPhoneSmsConfig()
  loadRekberinajaConfig()
  loadRoxyBrowserConfig()
  loadMailProviderConfig()
})

function setMessage(text, type = 'success') {
  message.value = text
  messageClass.value = type === 'success'
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 8000)
}

function downloadTextFile(filename, content, mime = 'application/json') {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

async function exportConfig() {
  configExporting.value = true
  try {
    const result = await api.exportConfig()
    const content = JSON.stringify(result, null, 2)
    configImportText.value = content
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    downloadTextFile(`autotoken-config-${stamp}.json`, content)
    setMessage('配置已导出')
  } catch (e) {
    setMessage(e.message || '导出配置失败', 'error')
  } finally {
    configExporting.value = false
  }
}

async function importConfig() {
  configImporting.value = true
  try {
    const text = configImportText.value.trim()
    JSON.parse(text)
    const result = await api.importConfig({ content: text, overwrite_empty: true })
    setMessage(result.message || '配置导入完成')
    await Promise.allSettled([
      loadGoPayAutoSignupConfig(),
      loadOAuthPhoneSmsConfig(),
          loadRekberinajaConfig(),
      loadRoxyBrowserConfig(),
      loadMailProviderConfig(),
      loadRegisterDomains(),
      loadAccountHubConfig(),
      api.getAutoCheckConfig().then(cfg => {
        form.value = {
          interval: Math.round(cfg.interval / 60),
          threshold: cfg.threshold,
          min_low: cfg.min_low,
        }
      }),
      api.getAutoRefreshQuotaConfig().then(cfg => {
        quotaRefreshForm.value = {
          enabled: !!cfg.enabled,
          interval: Math.max(1, Math.round((cfg.interval || 1800) / 60)),
        }
      }),
    ])
  } catch (e) {
    setMessage(e.message || '导入配置失败', 'error')
  } finally {
    configImporting.value = false
  }
}

async function onConfigImportFileSelected(event) {
  const file = event?.target?.files?.[0]
  if (!file) return
  try {
    configImportText.value = await file.text()
    setMessage(`已读取配置文件：${file.name}`)
  } catch (e) {
    setMessage(e.message || '读取配置文件失败', 'error')
  } finally {
    if (event?.target) {
      event.target.value = ''
    }
  }
}

async function save() {
  saving.value = true
  saved.value = false
  try {
    const cfg = await api.setAutoCheckConfig({
      interval: form.value.interval * 60,
      threshold: form.value.threshold,
      min_low: form.value.min_low,
    })
    form.value = {
      interval: Math.round(cfg.interval / 60),
      threshold: cfg.threshold,
      min_low: cfg.min_low,
    }
    saved.value = true
    setTimeout(() => { saved.value = false }, 3000)
  } catch (e) {
    console.error('保存失败:', e)
  } finally {
    saving.value = false
  }
}

async function saveAutoRefreshQuota() {
  quotaRefreshSaving.value = true
  quotaRefreshSaved.value = false
  try {
    const minutes = Math.max(1, Number(quotaRefreshForm.value.interval || 1))
    const cfg = await api.setAutoRefreshQuotaConfig({
      enabled: !!quotaRefreshForm.value.enabled,
      interval: quotaRefreshForm.value.enabled ? minutes * 60 : 0,
    })
    quotaRefreshForm.value = {
      enabled: !!cfg.enabled,
      interval: Math.max(1, Math.round((cfg.interval || minutes * 60) / 60)),
    }
    quotaRefreshSaved.value = true
    setTimeout(() => { quotaRefreshSaved.value = false }, 3000)
  } catch (e) {
    setMessage(e.message || '保存自动刷新额度配置失败', 'error')
  } finally {
    quotaRefreshSaving.value = false
  }
}

async function loadRegisterDomains() {
  registerDomainLoading.value = true
  try {
    const result = await api.getRegisterDomain()
    const domains = result.domains?.length ? result.domains : (result.domain ? [result.domain] : [])
    registerDomainsText.value = domains.join('\n')
  } catch (e) {
    console.error('加载注册域名失败:', e)
  } finally {
    registerDomainLoading.value = false
  }
}

async function saveRegisterDomains() {
  registerDomainSaving.value = true
  try {
    const domains = parsedRegisterDomains.value
    const result = await api.setRegisterDomains(domains, domains[0] || null)
    registerDomainsText.value = (result.domains || domains).join('\n')
    setMessage(result.message || '注册域名已保存')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    registerDomainSaving.value = false
  }
}

async function loadAccountHubConfig() {
  try {
    const cfg = await api.getAccountHubConfig()
    accountHubForm.value = {
      url: cfg.url || '',
      token: cfg.token || '',
      name: cfg.name || '',
      auto_upload: Boolean(cfg.auto_upload),
    }
  } catch (e) {
    console.error('加载账号 Hub 配置失败:', e)
  }
}

async function saveAccountHub() {
  accountHubSaving.value = true
  try {
    const result = await api.saveAccountHubConfig(accountHubForm.value)
    const cfg = result.config || accountHubForm.value
    accountHubForm.value = {
      url: cfg.url || '',
      token: cfg.token || '',
      name: cfg.name || '',
      auto_upload: Boolean(cfg.auto_upload),
    }
    setMessage(result.message || '账号 Hub 配置已保存')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    accountHubSaving.value = false
  }
}

async function testAccountHub() {
  accountHubTesting.value = true
  try {
    const result = await api.testAccountHub(accountHubForm.value)
    setMessage(result.message || '账号 Hub 连接成功')
  } catch (e) {
    setMessage(e.message, 'error')
  } finally {
    accountHubTesting.value = false
  }
}

async function loadGoPayAutoSignupConfig() {
  gopayAutoSignupLoading.value = true
  try {
    const cfg = await api.getGoPayAutoSignupConfig()
    gopayAutoSignupStatus.value = cfg || {}
    gopayAutoSignupForm.value = {
      provider: ['hero_sms', 'smsbower', 'smscode'].includes(cfg?.provider) ? cfg.provider : 'smscloud',
      country_code: '+62',
      smscloud_xi_token: '',
      hero_sms_api_key: '',
      hero_sms_base_url: cfg?.hero_sms_base_url || 'https://hero-sms.com/stubs/handler_api.php',
      hero_sms_country: cfg?.hero_sms_country || '6',
      hero_sms_service: cfg?.hero_sms_service || 'ni',
      hero_sms_min_price: cfg?.hero_sms_min_price || '',
      hero_sms_max_price: cfg?.hero_sms_max_price || '',
      hero_sms_preferred_price: cfg?.hero_sms_preferred_price || '',
      smsbower_api_key: '',
      smsbower_base_url: cfg?.smsbower_base_url || 'https://smsbower.page/stubs/handler_api.php',
      smsbower_country: cfg?.smsbower_country || '6',
      smsbower_service: cfg?.smsbower_service || 'ni',
      smsbower_min_price: cfg?.smsbower_min_price || '',
      smsbower_max_price: cfg?.smsbower_max_price || '',
      smsbower_preferred_price: cfg?.smsbower_preferred_price || '',
      smscode_api_token: '',
      smscode_base_url: cfg?.smscode_base_url || 'https://api.smscode.gg/v1',
      smscode_country_id: cfg?.smscode_country_id || '7',
      smscode_platform_id: cfg?.smscode_platform_id || '',
      smscode_platform_query: cfg?.smscode_platform_query || 'gojek',
      smscode_product_id: cfg?.smscode_product_id || '',
      smscode_min_price: cfg?.smscode_min_price || '',
      smscode_max_price: cfg?.smscode_max_price || '',
      proxy_url: cfg?.proxy_url || '',
      signup_mode: cfg?.signup_mode === 'appium' ? 'appium' : 'http',
      appium_url: cfg?.appium_url || 'http://127.0.0.1:4723',
      appium_adb_serial: cfg?.appium_adb_serial || '',
    }
  } catch (e) {
    setMessage(e.message || '加载 GoPay 自动注册配置失败', 'error')
  } finally {
    gopayAutoSignupLoading.value = false
  }
}

async function saveGoPayAutoSignupConfig() {
  gopayAutoSignupSaving.value = true
  try {
    const result = await api.saveGoPayAutoSignupConfig(gopayAutoSignupForm.value)
    gopayAutoSignupStatus.value = result || {}
    gopayAutoSignupForm.value.smscloud_xi_token = ''
    gopayAutoSignupForm.value.hero_sms_api_key = ''
    gopayAutoSignupForm.value.smsbower_api_key = ''
    gopayAutoSignupForm.value.smscode_api_token = ''
    setMessage(result.message || 'GoPay 自动注册配置已保存')
    await loadGoPayAutoSignupConfig()
  } catch (e) {
    setMessage(e.message || '保存 GoPay 自动注册配置失败', 'error')
  } finally {
    gopayAutoSignupSaving.value = false
  }
}

async function loadOAuthPhoneSmsConfig() {
  oauthPhoneSmsLoading.value = true
  try {
    const cfg = await api.getOAuthPhoneSmsConfig()
    oauthPhoneSmsStatus.value = cfg || {}
    oauthPhoneSmsForm.value = {
      provider: ['hero_sms', 'smsbower', 'smscloud', 'oasis', 'tujie'].includes(cfg?.provider) ? cfg.provider : 'phone_pool',
      hero_sms_api_key: '',
      hero_sms_min_price: cfg?.hero_sms_min_price || '',
      hero_sms_max_price: cfg?.hero_sms_max_price || '',
      smsbower_api_key: '',
      smsbower_min_price: cfg?.smsbower_min_price || '',
      smsbower_max_price: cfg?.smsbower_max_price || '',
      smscloud_api_key: '',
      smscloud_min_price: cfg?.smscloud_min_price || '',
      smscloud_max_price: cfg?.smscloud_max_price || '',
      oasis_sms_cdks: '',
      oasis_sms_cdk_file: cfg?.oasis_sms_cdk_file || '',
      oasis_sms_base_url: cfg?.oasis_sms_base_url || 'https://sms.oapi.vip',
      oasis_sms_poll_attempts: cfg?.oasis_sms_poll_attempts || '24',
      oasis_sms_poll_interval_ms: cfg?.oasis_sms_poll_interval_ms || '5000',
      oasis_sms_account_map_file: cfg?.oasis_sms_account_map_file || 'oasis-cdk-accounts.jsonl',
      tujie_sms_cdks: '',
      tujie_sms_cdk_file: cfg?.tujie_sms_cdk_file || '',
      tujie_sms_base_url: cfg?.tujie_sms_base_url || 'https://tujie.xyz/api',
      tujie_sms_poll_attempts: cfg?.tujie_sms_poll_attempts || '24',
      tujie_sms_poll_interval_ms: cfg?.tujie_sms_poll_interval_ms || '5000',
      tujie_sms_account_map_file: cfg?.tujie_sms_account_map_file || 'tujie-cdk-accounts.jsonl',
    }
  } catch (e) {
    setMessage(e.message || '加载 OAuth 接码配置失败', 'error')
  } finally {
    oauthPhoneSmsLoading.value = false
  }
}

async function saveOAuthPhoneSmsConfig() {
  oauthPhoneSmsSaving.value = true
  try {
    const result = await api.saveOAuthPhoneSmsConfig(oauthPhoneSmsForm.value)
    oauthPhoneSmsStatus.value = result || {}
    oauthPhoneSmsForm.value.hero_sms_api_key = ''
    oauthPhoneSmsForm.value.smsbower_api_key = ''
    oauthPhoneSmsForm.value.smscloud_api_key = ''
    oauthPhoneSmsForm.value.oasis_sms_cdks = ''
    oauthPhoneSmsForm.value.tujie_sms_cdks = ''
    setMessage(result.message || 'OAuth 接码配置已保存')
    await loadOAuthPhoneSmsConfig()
  } catch (e) {
    setMessage(e.message || '保存 OAuth 接码配置失败', 'error')
  } finally {
    oauthPhoneSmsSaving.value = false
  }
}

async function loadRekberinajaConfig() {
  rekberinajaLoading.value = true
  try {
    const cfg = await api.getRekberinajaConfig()
    rekberinajaStatus.value = cfg || {}
    rekberinajaForm.value = {
      enabled: Boolean(cfg?.transfer_enabled ?? cfg?.enabled),
      email: cfg?.email || '',
      password: '',
      min_balance: Number(cfg?.min_balance || 5000),
      poll_timeout: Number(cfg?.poll_timeout || 180),
      invoice_email: cfg?.invoice_email || '',
    }
  } catch (e) {
    setMessage(e.message || '加载 Rekberinaja 配置失败', 'error')
  } finally {
    rekberinajaLoading.value = false
  }
}

async function saveRekberinajaConfig() {
  rekberinajaSaving.value = true
  try {
    const result = await api.saveRekberinajaConfig({
      enabled: Boolean(rekberinajaForm.value.enabled),
      transfer_enabled: Boolean(rekberinajaForm.value.enabled),
      email: rekberinajaForm.value.email,
      password: rekberinajaForm.value.password,
      min_balance: rekberinajaForm.value.min_balance,
      poll_timeout: rekberinajaForm.value.poll_timeout,
      invoice_email: rekberinajaForm.value.invoice_email,
    })
    rekberinajaStatus.value = result || {}
    rekberinajaForm.value.password = ''
    setMessage(result.message || 'Rekberinaja 配置已保存')
    await loadRekberinajaConfig()
  } catch (e) {
    setMessage(e.message || '保存 Rekberinaja 配置失败', 'error')
  } finally {
    rekberinajaSaving.value = false
  }
}

async function loadRoxyBrowserConfig() {
  roxyBrowserLoading.value = true
  try {
    const cfg = await api.getRoxyBrowserConfig()
    roxyBrowserStatus.value = cfg || {}
    roxyBrowserForm.value = {
      api_host: cfg?.api_host || 'http://127.0.0.1:50000',
      api_token: '',
    }
  } catch (e) {
    setMessage(e.message || '加载 RoxyBrowser 配置失败', 'error')
  } finally {
    roxyBrowserLoading.value = false
  }
}

async function saveRoxyBrowserConfig() {
  roxyBrowserSaving.value = true
  try {
    const result = await api.saveRoxyBrowserConfig({
      api_host: roxyBrowserForm.value.api_host,
      api_token: roxyBrowserForm.value.api_token,
    })
    roxyBrowserStatus.value = result || {}
    roxyBrowserForm.value.api_token = ''
    setMessage(result.message || 'RoxyBrowser 配置已保存')
    await loadRoxyBrowserConfig()
  } catch (e) {
    setMessage(e.message || '保存 RoxyBrowser 配置失败', 'error')
  } finally {
    roxyBrowserSaving.value = false
  }
}

function isSecretField(key) {
  return key.includes('PASSWORD') || key.includes('KEY') || key.includes('TOKEN')
}

function isLongTextField(key) {
  return key.endsWith('_ACCOUNTS')
}

async function loadMailProviderConfig() {
  mailSetupLoading.value = true
  try {
    const result = await api.getMailProviderConfig()
    mailProvider.value = result.provider || 'cloudflare_temp_email'
    mailProviderOptions.value = result.provider_options || []
    mailProviderFieldGroups.value = result.provider_fields || {}
    const nextForm = {}
    for (const fields of Object.values(mailProviderFieldGroups.value)) {
      for (const field of fields) {
        nextForm[field.key] = field.value || ''
      }
    }
    mailProviderForm.value = nextForm
  } catch (e) {
    setMessage(e.message || '加载邮件 Provider 配置失败', 'error')
  } finally {
    mailSetupLoading.value = false
  }
}

async function saveMailProvider() {
  mailSetupSaving.value = true
  try {
    const payload = { MAIL_PROVIDER: mailProvider.value }
    for (const field of mailProviderFields.value) {
      payload[field.key] = mailProviderForm.value[field.key] || ''
    }
    const result = await api.saveMailProviderConfig(payload)
    setMessage(result.message || '邮件 Provider 配置已保存')
    await loadMailProviderConfig()
  } catch (e) {
    setMessage(e.message || '保存邮件 Provider 配置失败', 'error')
  } finally {
    mailSetupSaving.value = false
  }
}
</script>
