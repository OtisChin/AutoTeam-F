<template>
  <div class="space-y-6">
    <UiPageHeader title="卡池" eyebrow="资源工作台" description="统一管理兑换码与虚拟卡，支持筛选、批量操作和安全导入。" />

    <div class="rounded-2xl border border-gray-800 bg-gray-900/80 p-2">
      <UiSegmentedControl v-model="poolType" :options="poolTabs" aria-label="卡池类型" />
    </div>

    <div v-if="message" class="px-4 py-3 rounded-xl text-sm border" :class="messageClass">
      {{ message }}
    </div>

    <div :class="poolType === 'redeem' ? 'grid grid-cols-1 md:grid-cols-3 gap-4' : 'grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-4'">
      <div class="rounded-2xl border border-gray-800 bg-gray-900 p-5">
        <div class="text-4xl font-bold text-white">{{ stats.total }}</div>
        <div class="mt-3 text-sm text-gray-400">{{ poolType === 'redeem' ? '兑换码总数' : '虚拟卡总数' }}</div>
      </div>
      <div class="rounded-2xl border border-violet-500/30 bg-gray-900 p-5">
        <div class="text-4xl font-bold text-violet-400">{{ stats.unused }}</div>
        <div class="mt-3 text-sm text-gray-400">未使用</div>
      </div>
      <div class="rounded-2xl border border-sky-500/30 bg-gray-900 p-5">
        <div class="text-4xl font-bold text-sky-400">{{ stats.used }}</div>
        <div class="mt-3 text-sm text-gray-400">已使用</div>
      </div>
      <div v-if="poolType === 'card'" class="rounded-2xl border border-amber-500/30 bg-gray-900 p-5">
        <div class="text-4xl font-bold text-amber-300">{{ stats.binding }}</div>
        <div class="mt-3 text-sm text-gray-400">绑定中</div>
      </div>
      <div v-if="poolType === 'card'" class="rounded-2xl border border-orange-500/30 bg-gray-900 p-5">
        <div class="text-4xl font-bold text-orange-300">{{ stats.failed }}</div>
        <div class="mt-3 text-sm text-gray-400">失败待核对</div>
      </div>
      <div v-if="poolType === 'card'" class="rounded-2xl border border-rose-500/30 bg-gray-900 p-5">
        <div class="text-4xl font-bold text-rose-400">{{ stats.expired }}</div>
        <div class="mt-3 text-sm text-gray-400">已过期</div>
      </div>
    </div>

    <div class="rounded-2xl border border-gray-800 bg-gray-900 p-4 space-y-4">
      <div class="flex flex-col xl:flex-row xl:items-center xl:justify-between gap-4">
        <div class="flex flex-col md:flex-row gap-3">
          <div class="flex flex-wrap gap-2">
            <button
              v-for="status in activeStatuses"
              :key="status.value"
              @click="selectedStatus = status.value"
              class="px-4 py-2 rounded-xl text-sm font-medium border transition"
              :class="selectedStatus === status.value
                ? 'bg-blue-600/20 text-blue-400 border-blue-500/30'
                : 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700'">
              {{ status.label }}
            </button>
          </div>

          <select
            v-model="selectedProvider"
            class="px-4 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="">全部供应商</option>
            <option v-for="provider in providerOptions" :key="provider" :value="provider">
              {{ provider }}
            </option>
          </select>

          <select
            v-model="selectedSort"
            class="px-4 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option value="created_desc">时间降序</option>
            <option value="created_asc">时间升序</option>
            <option value="expires_desc">过期时间降序</option>
            <option value="expires_asc">过期时间升序</option>
          </select>

          <div class="flex gap-3">
            <input
              v-model.trim="keyword"
              type="text"
              placeholder="搜索兑换码 / 卡券 / 邮箱"
              class="w-full md:w-72 px-4 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:outline-none focus:border-blue-500"
            />
            <button
              @click="page = 1"
              class="px-5 py-2 rounded-xl text-sm font-medium border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition">
              搜索
            </button>
          </div>
        </div>
      </div>

      <div class="flex flex-wrap gap-3">
        <button
          @click="openImport"
          class="px-5 py-2 rounded-xl text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white transition">
          导入
        </button>
          <button
            @click="exportCurrent"
            :disabled="!filteredItems.length"
            class="px-5 py-2 rounded-xl text-sm font-medium border transition disabled:opacity-50"
            :class="filteredItems.length
              ? 'bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700'
              : 'bg-gray-900 text-gray-500 border-gray-800'">
            导出
        </button>
        <button
          v-if="poolType === 'redeem'"
          @click="redeemSelected"
          :disabled="!selectedIds.length"
          class="px-5 py-2 rounded-xl text-sm font-medium border transition disabled:opacity-50"
          :class="selectedIds.length
            ? 'bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border-emerald-500/30'
            : 'bg-gray-900 text-gray-500 border-gray-800'">
          批量兑换
        </button>
        <button
          @click="confirmDeleteSelected"
          :disabled="!selectedIds.length"
          class="px-5 py-2 rounded-xl text-sm font-medium border transition disabled:opacity-50"
          :class="selectedIds.length
            ? 'bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border-rose-500/30'
            : 'bg-gray-900 text-gray-500 border-gray-800'">
          批量删除
        </button>
      </div>
    </div>

    <div class="rounded-2xl border border-gray-800 bg-gray-900 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead class="bg-gray-800/70 text-gray-300">
            <tr>
              <th class="px-4 py-4 text-left w-12">
                <input
                  type="checkbox"
                  class="accent-blue-500"
                  :checked="allPageSelected"
                  @change="toggleSelectPage($event)"
                />
              </th>
              <th class="px-4 py-4 text-left">{{ poolType === 'redeem' ? '兑换码' : '卡号' }}</th>
              <th class="px-4 py-4 text-left">供应商</th>
              <th class="px-4 py-4 text-left">状态</th>
              <th class="px-4 py-4 text-left">{{ poolType === 'redeem' ? '导入时间' : '创建时间' }}</th>
              <th v-if="poolType === 'card'" class="px-4 py-4 text-left">过期时间</th>
              <th v-if="poolType === 'card'" class="px-4 py-4 text-left">使用者邮箱</th>
              <th class="px-4 py-4 text-left">使用时间</th>
              <th class="px-4 py-4 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td :colspan="poolType === 'card' ? 9 : 7" class="px-4 py-10 text-gray-500">加载中...</td>
            </tr>
            <tr v-else-if="!pagedItems.length">
              <td :colspan="poolType === 'card' ? 9 : 7" class="px-4 py-10 text-gray-500">暂无匹配数据。</td>
            </tr>
            <tr
              v-for="item in pagedItems"
              :key="item.id"
              class="border-t border-gray-800/70 hover:bg-gray-800/30"
            >
              <td class="px-4 py-4">
                <input
                  type="checkbox"
                  class="accent-blue-500"
                  :checked="selectedIds.includes(item.id)"
                  @change="toggleSelected(item.id, $event.target.checked)"
                />
              </td>
              <td class="px-4 py-4 font-mono text-xs text-gray-200 break-all max-w-[280px]">
                {{ item.value }}
              </td>
              <td class="px-4 py-4 text-gray-300">{{ item.provider || '-' }}</td>
              <td class="px-4 py-4">
                <UiStatusBadge
                  :tone="statusTone(isExpired(item) ? 'expired' : item.status)"
                  :label="statusLabel(isExpired(item) ? 'expired' : item.status)"
                />
              </td>
              <td class="px-4 py-4 text-gray-400">{{ formatDateTime(item.created_at) }}</td>
              <td v-if="poolType === 'card'" class="px-4 py-4 text-gray-400">{{ formatDateTime(item.expires_at) }}</td>
              <td v-if="poolType === 'card'" class="px-4 py-4 text-gray-300">{{ item.used_by || '-' }}</td>
              <td class="px-4 py-4 text-gray-400">{{ formatDateTime(item.used_at) }}</td>
              <td class="px-4 py-4 text-right">
                <div class="flex justify-end gap-2">
                  <button
                    v-if="poolType === 'redeem'"
                    @click="redeemItem(item)"
                    :disabled="item.status === 'used'"
                    class="px-3 py-1.5 rounded-lg text-xs border bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border-emerald-500/30 transition">
                    兑换
                  </button>
                  <button
                    @click="toggleStatus(item)"
                    class="px-3 py-1.5 rounded-lg text-xs border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition">
                    {{ item.status === 'unused' ? '标记使用' : item.status === 'used' ? '恢复未使用' : '恢复' }}
                  </button>
                  <button
                    v-if="poolType === 'card' && item.meta && Object.keys(item.meta).length"
                    @click="detailItem = item"
                    class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition">
                    详情
                  </button>
                  <button
                    @click="confirmRemoveItem(item)"
                    class="px-3 py-1.5 rounded-lg text-xs border bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border-rose-500/30 transition">
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4 px-4 py-4 border-t border-gray-800">
        <div class="flex items-center gap-3 text-sm text-gray-400">
          <span>每页</span>
          <select
            v-model.number="pageSize"
            class="px-3 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:outline-none focus:border-blue-500"
          >
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
        </div>

        <div class="flex items-center gap-3">
          <button
            @click="page = Math.max(1, page - 1)"
            :disabled="page <= 1"
            class="px-4 py-2 rounded-xl text-sm border transition disabled:opacity-50"
            :class="page > 1
              ? 'bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700'
              : 'bg-gray-900 text-gray-500 border-gray-800'">
            上一页
          </button>
          <div class="text-sm text-gray-300">第 {{ page }} 页 / 共 {{ totalPages }} 页</div>
          <button
            @click="page = Math.min(totalPages, page + 1)"
            :disabled="page >= totalPages"
            class="px-4 py-2 rounded-xl text-sm border transition disabled:opacity-50"
            :class="page < totalPages
              ? 'bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700'
              : 'bg-gray-900 text-gray-500 border-gray-800'">
            下一页
          </button>
        </div>
      </div>
    </div>
  </div>

  <div v-if="importing" class="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" @click.self="closeImport">
    <div class="w-full max-w-3xl rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl">
      <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800">
        <div>
          <h4 class="text-lg font-semibold text-white">{{ poolType === 'redeem' ? '导入兑换码' : '导入卡券' }}</h4>
          <div class="text-xs text-gray-500 mt-1">
            {{ poolType === 'redeem'
              ? '支持文本粘贴或从文件导入，每行一个兑换码'
              : '仅支持文本导入，多组卡券之间用空行分隔' }}
          </div>
        </div>
        <button
          @click="closeImport"
          :disabled="importLoading"
          class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition disabled:opacity-50">
          关闭
        </button>
      </div>

      <div class="p-5 space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-4">
          <div v-if="poolType === 'redeem'">
            <label class="block text-sm text-gray-400 mb-2">供应商</label>
            <select
              v-model="importProvider"
              class="w-full px-4 py-2 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:outline-none focus:border-blue-500"
            >
              <option value="">请选择供应商</option>
              <option value="988">988</option>
              <option value="EFUN">EFUN</option>
            </select>
          </div>

          <div v-if="poolType === 'redeem'" class="flex items-end gap-3">
            <label
              for="redeem-import-file"
              class="inline-flex px-5 py-2 rounded-xl text-sm font-medium border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition cursor-pointer">
              从文件导入
            </label>
            <input
              id="redeem-import-file"
              type="file"
              accept=".txt"
              class="hidden"
              @change="handleFileImport"
            />
            <div class="text-xs text-gray-500">仅支持 `.txt`，每行一个兑换码</div>
          </div>
        </div>

        <div>
          <label class="block text-sm text-gray-400 mb-2">{{ poolType === 'redeem' ? '兑换码文本' : '卡券文本' }}</label>
          <textarea
            v-model="importText"
            rows="10"
            :placeholder="importPlaceholder"
            class="w-full px-4 py-3 bg-gray-800 border border-gray-700 rounded-xl text-sm text-white focus:outline-none focus:border-blue-500 resize-y"
          />
        </div>
      </div>

      <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
        <button
          @click="closeImport"
          :disabled="importLoading"
          class="px-5 py-2 rounded-xl text-sm font-medium border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition disabled:opacity-50">
          取消
        </button>
        <button
          @click="submitImport"
          :disabled="!importText.trim() || (poolType === 'redeem' && !importProvider) || importLoading"
          class="px-5 py-2 rounded-xl text-sm font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition disabled:opacity-50">
          {{ importLoading ? '导入中...' : '确认导入' }}
        </button>
      </div>
    </div>
  </div>

  <AccessibleModal v-if="detailItem" label="卡券详情" @close="detailItem = null">
    <div class="w-full max-w-4xl rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl">
      <div class="flex items-center justify-between px-5 py-4 border-b border-gray-800">
        <div>
          <h4 class="text-lg font-semibold text-white">卡券详情</h4>
          <div class="text-xs text-gray-500 mt-1">{{ detailItem.value }}</div>
        </div>
        <button
          @click="detailItem = null"
          class="px-3 py-1.5 rounded-lg text-sm border bg-gray-800 hover:bg-gray-700 text-gray-300 border-gray-700 transition">
          关闭
        </button>
      </div>

      <div class="p-5">
        <div class="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-5">
          <div class="flex flex-col gap-4">
            <div class="flex items-center justify-between gap-4 border-b border-gray-800 pb-4">
              <span class="inline-flex items-center rounded-full bg-blue-600/15 px-4 py-2 text-sm font-medium text-blue-300">
                类别: {{ detailMeta.card.category || '-' }}
              </span>
              <span class="inline-flex items-center rounded-full bg-emerald-500/15 px-4 py-2 text-sm font-medium text-emerald-300">
                {{ cardStatusLabel }}
              </span>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">卡号 Card Number</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-2xl font-mono text-gray-100 break-all">{{ detailMeta.content.card_number || '-' }}</div>
                  <button
                    @click="copyText('card_number', detailMeta.content.card_number)"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition"
                    :class="copyButtonClass('card_number')">
                    {{ copyButtonLabel('card_number', '复制卡号') }}
                  </button>
                </div>
              </div>

              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">有效期 Expiry</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-2xl font-mono text-gray-100">{{ formattedExpiryDate }}</div>
                  <button
                    @click="copyText('expiry', formattedExpiryDate)"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition"
                    :class="copyButtonClass('expiry')">
                    {{ copyButtonLabel('expiry', '复制有效期') }}
                  </button>
                </div>
              </div>

              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">CVV</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-2xl font-mono text-gray-100">{{ detailMeta.content.cvv || '-' }}</div>
                  <button
                    @click="copyText('cvv', detailMeta.content.cvv)"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition"
                    :class="copyButtonClass('cvv')">
                    {{ copyButtonLabel('cvv', '复制 CVV') }}
                  </button>
                </div>
              </div>

              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">电话 Phone</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-xl font-mono text-gray-100 break-all">{{ detailMeta.content.phone || '-' }}</div>
                  <button
                    @click="copyText('phone', detailMeta.content.phone)"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition"
                    :class="copyButtonClass('phone')">
                    {{ copyButtonLabel('phone', '复制电话') }}
                  </button>
                </div>
              </div>

              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4 md:col-span-2">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">姓名 Name</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-xl text-gray-100 break-all">{{ detailMeta.content.name || '-' }}</div>
                  <button
                    @click="copyText('name', detailMeta.content.name)"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition"
                    :class="copyButtonClass('name')">
                    {{ copyButtonLabel('name', '复制姓名') }}
                  </button>
                </div>
              </div>

              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4 md:col-span-2">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">地址 Address</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-lg text-gray-100 break-all">{{ detailMeta.content.address || '-' }}</div>
                  <button
                    @click="copyText('address', detailMeta.content.address)"
                    class="shrink-0 px-3 py-1.5 rounded-lg text-xs border transition"
                    :class="copyButtonClass('address')">
                    {{ copyButtonLabel('address', '复制地址') }}
                  </button>
                </div>
              </div>

              <div class="rounded-xl border border-gray-800 bg-gray-950/80 p-4 md:col-span-2">
                <div class="text-xs text-gray-500 mb-2 uppercase tracking-wide">接码 API</div>
                <div class="flex items-center justify-between gap-3">
                  <div class="text-sm font-mono text-gray-100 break-all">{{ detailMeta.content.sms_api || '-' }}</div>
                  <div class="shrink-0 flex items-center gap-2">
                    <button
                      @click="openSmsApi"
                      class="px-3 py-1.5 rounded-lg text-xs border bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border-blue-500/30 transition">
                      跳转
                    </button>
                    <button
                      @click="copyText('sms_api', detailMeta.content.sms_api)"
                      class="px-3 py-1.5 rounded-lg text-xs border transition"
                      :class="copyButtonClass('sms_api')">
                      {{ copyButtonLabel('sms_api', '复制 API') }}
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div class="rounded-xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-4">
              <div class="flex flex-col md:flex-row md:items-center gap-3">
                <div class="flex-1 text-lg font-mono text-emerald-300">
                  {{ smsCode || '等待获取验证码...' }}
                </div>
                <button
                  @click="fetchSmsCode"
                  :disabled="smsLoading || !detailMeta.content.sms_api"
                  class="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 transition disabled:opacity-50">
                  {{ smsLoading ? '获取中...' : '获取验证码' }}
                </button>
              </div>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div class="rounded-xl border border-gray-800 bg-gray-950/80 px-4 py-3 text-sm text-gray-300">
                激活时间: <span class="text-gray-100">{{ formatDateTime(detailMeta.card.activated_at) }}</span>
              </div>
              <div class="rounded-xl border border-gray-800 bg-gray-950/80 px-4 py-3 text-sm text-gray-300">
                到期时间: <span class="text-gray-100">{{ formatDateTime(detailMeta.card.expires_at || detailMeta.content.expiry_date) }}</span>
              </div>
              <div class="rounded-xl border border-gray-800 bg-gray-950/80 px-4 py-3 text-sm text-gray-300">
                剩余时间: <span class="text-gray-100">{{ remainingTimeLabel }}</span>
              </div>
            </div>

            <div class="flex justify-end">
              <button
                @click="copyAllCardInfo"
                class="px-5 py-2.5 rounded-xl text-sm font-medium transition"
                :class="copyAllButtonClass">
                {{ copyAllButtonLabel }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AccessibleModal>

  <AccessibleModal v-if="confirmRedeemItem" label="确认兑换" @close="closeRedeemConfirm">
    <div class="w-full max-w-md rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl">
      <div class="px-5 py-4 border-b border-gray-800">
        <h4 class="text-lg font-semibold text-white">确认兑换</h4>
        <div class="text-sm text-gray-400 mt-2 break-all">确定要兑换这个兑换码吗？</div>
        <div class="text-xs text-gray-500 mt-2 font-mono break-all">{{ confirmRedeemItem.value }}</div>
      </div>

      <div class="px-5 py-4">
        <label class="inline-flex items-center gap-2 text-sm text-gray-300">
          <input v-model="skipRedeemConfirm" type="checkbox" class="accent-blue-500" />
          不再提醒
        </label>
      </div>

      <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
        <button
          @click="closeRedeemConfirm"
          class="px-5 py-2 rounded-xl text-sm font-medium border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition">
          取消
        </button>
        <button
          @click="confirmRedeem"
          class="px-5 py-2 rounded-xl text-sm font-medium bg-emerald-600 hover:bg-emerald-500 text-white transition">
          确认兑换
        </button>
      </div>
    </div>
  </AccessibleModal>

  <AccessibleModal v-if="deleteConfirm.visible" label="确认删除" @close="closeDeleteConfirm">
    <div class="w-full max-w-md rounded-2xl border border-gray-800 bg-gray-900 shadow-2xl">
      <div class="px-5 py-4 border-b border-gray-800">
        <h4 class="text-lg font-semibold text-white">{{ deleteConfirm.mode === 'batch' ? '确认批量删除' : '确认删除' }}</h4>
        <div class="text-sm text-gray-400 mt-2">
          {{ deleteConfirm.mode === 'batch'
            ? `确定要删除选中的 ${deleteConfirm.ids.length} 条记录吗？`
            : '确定要删除这条记录吗？' }}
        </div>
        <div v-if="deleteConfirm.mode === 'single'" class="text-xs text-gray-500 mt-2 font-mono break-all">
          {{ deleteConfirm.label }}
        </div>
      </div>

      <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-gray-800">
        <button
          @click="closeDeleteConfirm"
          class="px-5 py-2 rounded-xl text-sm font-medium border bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700 transition">
          取消
        </button>
        <button
          @click="executeDelete"
          class="px-5 py-2 rounded-xl text-sm font-medium bg-rose-600 hover:bg-rose-500 text-white transition">
          确认删除
        </button>
      </div>
    </div>
  </AccessibleModal>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { api } from '../api.js'
import AccessibleModal from './AccessibleModal.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiSegmentedControl from './ui/UiSegmentedControl.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'

const poolTabs = [
  { value: 'redeem', label: '兑换码' },
  { value: 'card', label: '虚拟卡' },
]

const statuses = [
  { value: 'all', label: '全部' },
  { value: 'unused', label: '未使用' },
  { value: 'binding', label: '绑定中' },
  { value: 'used', label: '已使用' },
  { value: 'failed', label: '失败待核对' },
  { value: 'expired', label: '已过期' },
]

const poolType = ref('redeem')
const selectedStatus = ref('all')
const selectedProvider = ref('')
const selectedSort = ref('created_desc')
const keyword = ref('')
const page = ref(1)
const pageSize = ref(50)
const selectedIds = ref([])
const loading = ref(false)
const importLoading = ref(false)
const importing = ref(false)
const importText = ref('')
const importProvider = ref('')
const items = ref([])
const stats = ref({ total: 0, unused: 0, binding: 0, used: 0, failed: 0, expired: 0 })
const message = ref('')
const messageClass = ref('')
const detailItem = ref(null)
const smsCode = ref('')
const smsLoading = ref(false)
const confirmRedeemItem = ref(null)
const skipRedeemConfirm = ref(false)
const copiedStates = ref({})
const copyTimers = new Map()
const deleteConfirm = ref({
  visible: false,
  mode: 'single',
  ids: [],
  label: '',
})

const activeStatuses = computed(() => {
  return poolType.value === 'redeem'
    ? statuses.filter(status => !['binding', 'failed', 'expired'].includes(status.value))
    : statuses
})

const providerOptions = computed(() => {
  return [...new Set(items.value.map(item => item.provider).filter(Boolean))].sort()
})

const detailMeta = computed(() => {
  const meta = detailItem.value?.meta || {}
  return {
    card: meta.card || {},
    content: meta.content || meta,
  }
})

const cardStatusLabel = computed(() => {
  const status = String(detailMeta.value.card.status || '').toLowerCase()
  if (status === 'used' || status === 'active') return '已激活'
  if (status === 'expired') return '已过期'
  return status || '未知状态'
})

const remainingTimeLabel = computed(() => {
  const expiresAt = detailMeta.value.card.expires_at
  if (!expiresAt) return '-'
  const now = Date.now()
  const end = new Date(expiresAt).getTime()
  if (Number.isNaN(end)) return '-'
  const diff = Math.floor((end - now) / 1000)
  if (diff <= 0) return '已过期'
  const minutes = Math.floor(diff / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)
  if (days > 0) return `${days}天${hours % 24}小时`
  if (hours > 0) return `${hours}小时${minutes % 60}分钟`
  return `${minutes}分钟`
})

const formattedExpiryDate = computed(() => {
  return formatExpiryDate(detailMeta.value.content.expiry_date)
})
const copyAllButtonLabel = computed(() => copiedStates.value.all ? '已复制' : '复制全部信息')
const copyAllButtonClass = computed(() => copiedStates.value.all
  ? 'bg-emerald-600 text-white'
  : 'bg-blue-600 hover:bg-blue-500 text-white')

const importPlaceholder = computed(() => {
  if (poolType.value === 'redeem') {
    return '每行一条兑换码，例如：\nCODE-001\nCODE-002'
  }
  return [
    '卡号 Card Number: 4859540177266250',
    '有效期 Expiry: 2030/5',
    'CVV: 150',
    '电话 Phone: +15139372522',
    '姓名 Name: KRYSTLE RULE',
    '地址 Address: 570 MARGARET ST. APT. C,MUSKEGON 49442,US',
    '接码 API: http://a.62-us.com/api/get_sms?key=...',
  ].join('\n')
})

const filteredItems = computed(() => {
  const query = keyword.value.toLowerCase()
  const filtered = items.value.filter(item => {
    if (selectedStatus.value !== 'all' && effectiveStatus(item) !== selectedStatus.value) return false
    if (selectedProvider.value && item.provider !== selectedProvider.value) return false
    if (!query) return true
    return [
      item.value,
      item.provider,
      item.used_by,
    ].some(field => String(field || '').toLowerCase().includes(query))
  })

  return [...filtered].sort((a, b) => {
    if (selectedSort.value === 'created_asc') return sortTime(a.created_at, b.created_at)
    if (selectedSort.value === 'expires_desc') return sortTime(b.expires_at, a.expires_at)
    if (selectedSort.value === 'expires_asc') return sortTime(a.expires_at, b.expires_at)
    return sortTime(b.created_at, a.created_at)
  })
})

const isExpired = (item) => {
  if (item.status === 'used') return false
  if (item.status === 'expired') return true
  if (poolType.value !== 'card') return false
  const time = toTime(item.expires_at)
  return time > 0 && time <= Date.now()
}

const effectiveStatus = (item) => {
  return isExpired(item) ? 'expired' : item.status
}

const totalPages = computed(() => Math.max(1, Math.ceil(filteredItems.value.length / pageSize.value)))

const pagedItems = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredItems.value.slice(start, start + pageSize.value)
})

const allPageSelected = computed(() => {
  return pagedItems.value.length > 0 && pagedItems.value.every(item => selectedIds.value.includes(item.id))
})

watch([poolType, selectedStatus, selectedProvider, selectedSort, keyword, pageSize], () => {
  page.value = 1
})

watch(poolType, () => {
  selectedIds.value = []
  loadPool()
})

watch(totalPages, (value) => {
  if (page.value > value) page.value = value
})

function sortTime(a, b) {
  return toTime(a) - toTime(b)
}

function toTime(value) {
  if (!value) return 0
  if (typeof value === 'number') return value
  const parsed = new Date(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}

function setMessage(text, ok = true) {
  message.value = text
  messageClass.value = ok
    ? 'bg-green-500/10 text-green-400 border-green-500/20'
    : 'bg-red-500/10 text-red-400 border-red-500/20'
  window.clearTimeout(setMessage._timer)
  setMessage._timer = window.setTimeout(() => {
    message.value = ''
  }, 5000)
}

async function loadPool() {
  loading.value = true
  try {
    const result = await api.getCardPool(poolType.value)
    items.value = result.items || []
    stats.value = result.stats || { total: 0, unused: 0, binding: 0, used: 0, failed: 0, expired: 0 }
  } catch (e) {
    setMessage(`加载卡池失败: ${e.message}`, false)
  } finally {
    loading.value = false
  }
}

function openImport() {
  importing.value = true
  if (poolType.value === 'redeem' && !importProvider.value) {
    importProvider.value = '988'
  }
}

function closeImport() {
  importing.value = false
  importText.value = ''
  importProvider.value = ''
}

async function submitImport() {
  if (!importText.value.trim()) return
  importLoading.value = true
  try {
    const result = await api.importCardPool({
      pool_type: poolType.value,
      text: importText.value,
      provider: importProvider.value,
    })
    setMessage(result.message || '导入成功')
    closeImport()
    await loadPool()
  } catch (e) {
    setMessage(`导入失败: ${e.message}`, false)
  } finally {
    importLoading.value = false
  }
}

function handleFileImport(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    importText.value = String(reader.result || '')
    event.target.value = ''
  }
  reader.readAsText(file)
}

function exportCurrent() {
  const content = poolType.value === 'redeem'
    ? filteredItems.value.map(item => item.value).join('\n')
    : filteredItems.value.map(formatCardExportBlock).join('\n\n')
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = poolType.value === 'redeem' ? 'redeem-codes.txt' : 'card-coupons.txt'
  link.click()
  URL.revokeObjectURL(url)
}

function toggleSelected(id, checked) {
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id)
    return
  }
  selectedIds.value = selectedIds.value.filter(value => value !== id)
}

function toggleSelectPage(event) {
  const checked = event.target.checked
  const ids = pagedItems.value.map(item => item.id)
  if (checked) {
    selectedIds.value = [...new Set([...selectedIds.value, ...ids])]
    return
  }
  selectedIds.value = selectedIds.value.filter(id => !ids.includes(id))
}

function confirmDeleteSelected() {
  if (!selectedIds.value.length) return
  deleteConfirm.value = {
    visible: true,
    mode: 'batch',
    ids: [...selectedIds.value],
    label: '',
  }
}

async function deleteSelected(ids) {
  try {
    const result = await api.deleteCardPoolItems({
      pool_type: poolType.value,
      ids,
    })
    selectedIds.value = []
    setMessage(result.message || '删除成功')
    await loadPool()
  } catch (e) {
    setMessage(`删除失败: ${e.message}`, false)
  }
}

function confirmRemoveItem(item) {
  deleteConfirm.value = {
    visible: true,
    mode: 'single',
    ids: [item.id],
    label: item.value,
  }
}

async function removeItem(id) {
  try {
    const result = await api.deleteCardPoolItems({
      pool_type: poolType.value,
      ids: [id],
    })
    selectedIds.value = selectedIds.value.filter(value => value !== id)
    setMessage(result.message || '删除成功')
    await loadPool()
  } catch (e) {
    setMessage(`删除失败: ${e.message}`, false)
  }
}

function closeDeleteConfirm() {
  deleteConfirm.value = {
    visible: false,
    mode: 'single',
    ids: [],
    label: '',
  }
}

async function executeDelete() {
  const { mode, ids } = deleteConfirm.value
  closeDeleteConfirm()
  if (!ids.length) return
  if (mode === 'batch') {
    await deleteSelected(ids)
    return
  }
  await removeItem(ids[0])
}

async function toggleStatus(item) {
  const nextStatus = item.status === 'unused' ? 'used' : 'unused'
  try {
    await api.updateCardPoolItem({
      pool_type: poolType.value,
      item_id: item.id,
      status: nextStatus,
    })
    setMessage(nextStatus === 'used' ? '已标记为已使用' : '已恢复为未使用')
    await loadPool()
  } catch (e) {
    setMessage(`更新失败: ${e.message}`, false)
  }
}

async function redeemItem(item) {
  if (!skipRedeemConfirm.value) {
    confirmRedeemItem.value = item
    return
  }
  await doRedeemItem(item)
}

async function doRedeemItem(item) {
  try {
    const result = await api.redeemCardPoolItem({ item_id: item.id })
    setMessage(result.message || '兑换成功')
    await loadPool()
  } catch (e) {
    setMessage(`兑换失败: ${e.message}`, false)
  }
}

function closeRedeemConfirm() {
  confirmRedeemItem.value = null
}

async function confirmRedeem() {
  if (!confirmRedeemItem.value) return
  const item = confirmRedeemItem.value
  confirmRedeemItem.value = null
  await doRedeemItem(item)
}

async function redeemSelected() {
  if (!selectedIds.value.length) return
  try {
    const result = await api.redeemCardPoolItems({ item_ids: selectedIds.value })
    const failed = (result.results || []).filter(item => !item.ok)
    selectedIds.value = []
    if (!failed.length) {
      setMessage(result.message || '批量兑换成功')
    } else {
      const preview = failed
        .slice(0, 3)
        .map(item => item.error || `记录 ${item.item_id} 兑换失败`)
        .join('；')
      setMessage(`${result.message || '批量兑换完成'}，失败 ${failed.length} 条：${preview}`, false)
    }
    await loadPool()
  } catch (e) {
    setMessage(`批量兑换失败: ${e.message}`, false)
  }
}

function statusLabel(status) {
  if (status === 'binding') return '绑定中'
  if (status === 'failed') return '失败待核对'
  if (status === 'expired') return '已过期'
  if (status === 'used') return '已使用'
  return '未使用'
}

function statusClass(status) {
  if (status === 'binding') return 'bg-amber-500/10 text-amber-300 border-amber-500/20'
  if (status === 'failed') return 'bg-orange-500/10 text-orange-300 border-orange-500/20'
  if (status === 'used') return 'bg-sky-500/10 text-sky-300 border-sky-500/20'
  if (status === 'expired') return 'bg-rose-500/10 text-rose-300 border-rose-500/20'
  return 'bg-violet-500/10 text-violet-300 border-violet-500/20'
}

function statusTone(status) {
  if (status === 'binding') return 'info'
  if (status === 'failed') return 'warning'
  if (status === 'used') return 'success'
  if (status === 'expired') return 'danger'
  return 'neutral'
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function formatExpiryDate(value) {
  const raw = String(value || '').trim()
  if (!raw) return '-'
  const match = raw.match(/^(\d{4})\/(\d{1,2})$/)
  if (!match) return raw
  const year = match[1].slice(-2)
  const month = match[2].padStart(2, '0')
  return `${month}/${year}`
}

function formatCardExportBlock(item) {
  const meta = item.meta || {}
  const content = meta.content || meta
  return [
    `卡号 Card Number: ${content.card_number || item.value || '-'}`,
    `有效期 Expiry: ${content.expiry_date || item.expires_at || '-'}`,
    `CVV: ${content.cvv || '-'}`,
    `电话 Phone: ${content.phone || '-'}`,
    `姓名 Name: ${content.name || '-'}`,
    `地址 Address: ${content.address || '-'}`,
    `接码 API: ${content.sms_api || '-'}`,
  ].join('\n')
}

function copyButtonLabel(key, defaultLabel) {
  return copiedStates.value[key] ? '已复制' : defaultLabel
}

function copyButtonClass(key) {
  return copiedStates.value[key]
    ? 'bg-emerald-600 text-white border-emerald-500'
    : 'bg-gray-800 hover:bg-gray-700 text-gray-200 border-gray-700'
}

function markCopied(key) {
  copiedStates.value = { ...copiedStates.value, [key]: true }
  if (copyTimers.has(key)) {
    window.clearTimeout(copyTimers.get(key))
  }
  const timer = window.setTimeout(() => {
    copiedStates.value = { ...copiedStates.value, [key]: false }
    copyTimers.delete(key)
  }, 3000)
  copyTimers.set(key, timer)
}

async function copyText(key, value) {
  const text = String(value || '').trim()
  if (!text) {
    setMessage('没有可复制的内容', false)
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    markCopied(key)
  } catch (e) {
    setMessage(`复制失败: ${e.message}`, false)
  }
}

function copyAllCardInfo() {
  if (!detailItem.value) return
  const content = detailMeta.value.content || {}
  const lines = [
    `卡号: ${content.card_number || '-'}`,
    `有效期: ${formatExpiryDate(content.expiry_date)}`,
    `CVV: ${content.cvv || '-'}`,
    `电话: ${content.phone || '-'}`,
    `姓名: ${content.name || '-'}`,
    `地址: ${content.address || '-'}`,
    `SMS API: ${content.sms_api || '-'}`,
  ]
  copyText('all', lines.join('\n'))
}

async function fetchSmsCode() {
  const smsApi = String(detailMeta.value.content.sms_api || '').trim()
  if (!smsApi) {
    setMessage('缺少 SMS API', false)
    return
  }
  smsLoading.value = true
  try {
    const resp = await api.fetchCardPoolSms(smsApi)
    const text = String(resp.text || '')
    const parts = text.split('|')
    if (parts[0] === 'yes' && parts[1]) {
      const rawCode = parts[1].trim()
      const matchedCode = rawCode.match(/\b(\d{4,8})\b/)
      smsCode.value = matchedCode ? matchedCode[1] : rawCode
      setMessage('验证码获取成功')
      return
    }
    smsCode.value = parts[1] ? parts[1].trim() : text.trim() || '暂无验证码'
    setMessage('暂未获取到验证码', false)
  } catch (e) {
    smsCode.value = '获取失败'
    setMessage(`获取验证码失败: ${e.message}`, false)
  } finally {
    smsLoading.value = false
  }
}

function openSmsApi() {
  const smsApi = String(detailMeta.value.content.sms_api || '').trim()
  if (!smsApi) {
    setMessage('缺少 SMS API', false)
    return
  }
  window.open(smsApi, '_blank', 'noopener,noreferrer')
}

onMounted(loadPool)

watch(detailItem, () => {
  smsCode.value = ''
  smsLoading.value = false
  copiedStates.value = {}
  for (const timer of copyTimers.values()) {
    window.clearTimeout(timer)
  }
  copyTimers.clear()
})
</script>
