<template>
  <div class="team-workspace">
    <UiPageHeader title="Team 成员" eyebrow="账号 / Team" description="成员、邀请和本地账号状态" :status="error && data ? '显示上次成功数据' : ''">
      <template #actions><UiButton variant="secondary" :loading="loading" @click="fetchMembers">刷新</UiButton></template>
    </UiPageHeader>
    <UiMetricSummary label="Team 指标" :items="metricItems" />
    <UiStatePanel v-if="!data && loading" state="loading" title="正在加载 Team 成员" message="读取成员和邀请状态…" />
    <UiStatePanel v-else-if="!data && error" state="error" title="Team 成员加载失败" :message="error" action-label="重试" @action="fetchMembers" />
    <UiStatePanel v-else-if="data && error" state="partial" title="显示上次成功数据" :message="error" />
    <UiStatePanel v-else-if="data && !members.length" state="empty" title="暂无 Team 成员" message="邀请成员后，他们会显示在这里。" />
    <UiTableFrame label="Team 成员" :busy="loading" :empty="!members.length" min-width="900px">
      <template #header><span class="ui-table-frame-meta">{{ members.length }} 位成员 · {{ inviteCount }} 个待接受邀请</span></template>
      <table class="ui-data-table"><thead><tr><th>#</th><th>邮箱</th><th>角色</th><th>状态</th><th>来源</th><th>操作</th></tr></thead>
        <tbody><tr v-for="(member, index) in members" :key="memberKey(member)"><td class="ui-table-index">{{ index + 1 }}</td><td><strong>{{ member.email || '-' }}</strong><small class="ui-table-subtext">{{ member.user_id || '邀请中' }}</small></td><td><UiStatusBadge :label="roleLabel(member)" :tone="member.role === 'account-owner' ? 'info' : 'neutral'" /></td><td><UiStatusBadge :label="member.type === 'invite' ? '待接受' : '已加入'" :tone="member.type === 'invite' ? 'warning' : 'success'" /></td><td><UiStatusBadge :label="member.is_local ? '本地管理' : '外部'" :tone="member.is_local ? 'info' : 'neutral'" /></td><td><UiButton v-if="member.role !== 'account-owner'" variant="danger" size="sm" :loading="removingId === memberKey(member)" @click="requestRemove(member)">移出</UiButton><span v-else class="ui-muted">所有者</span></td></tr></tbody>
      </table>
    </UiTableFrame>
    <AccessibleModal v-if="pendingMember" label="确认移出 Team 成员" @close="closeRemoveDialog"><section class="ui-modal-card"><header class="ui-modal-header"><h2>确认移出成员</h2><UiButton variant="quiet" size="sm" aria-label="关闭" @click="closeRemoveDialog">关闭</UiButton></header><div class="ui-modal-body"><p>确认{{ pendingMember.type === 'invite' ? '取消邀请' : '移出 Team' }} <strong>{{ pendingMember.email }}</strong>？</p></div><footer class="ui-modal-footer"><UiButton variant="quiet" @click="closeRemoveDialog">取消</UiButton><UiButton variant="danger" :loading="Boolean(removingId)" @click="confirmRemove">确认</UiButton></footer></section></AccessibleModal>
  </div>
</template>
<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api.js'
import { createSessionStorageFacade } from '../sessionStorageScope.js'
import AccessibleModal from './AccessibleModal.vue'
import UiButton from './ui/UiButton.vue'
import UiMetricSummary from './ui/UiMetricSummary.vue'
import UiPageHeader from './ui/UiPageHeader.vue'
import UiStatePanel from './ui/UiStatePanel.vue'
import UiStatusBadge from './ui/UiStatusBadge.vue'
import UiTableFrame from './ui/UiTableFrame.vue'
const sessionStorage = createSessionStorageFacade(); const CACHE_KEY = 'autotoken_team_members'; const CACHE_TTL = 600000
const data = ref(null); const loading = ref(false); const error = ref(''); const removingId = ref(''); const pendingMember = ref(null)
const members = computed(() => Array.isArray(data.value?.members) ? data.value.members : [])
const inviteCount = computed(() => Number(data.value?.invites || members.value.filter(member => member.type === 'invite').length))
const metricItems = computed(() => [{ key: 'total', label: '成员总数', value: Number(data.value?.total ?? members.value.length), tone: 'neutral' }, { key: 'active', label: '已加入', value: members.value.filter(member => member.type !== 'invite').length, tone: 'success' }, { key: 'invites', label: '待接受邀请', value: inviteCount.value, tone: 'warning' }])
function memberKey(member) { return `${member.type || 'member'}:${member.user_id || ''}:${member.email || ''}` }
function roleLabel(member) { return member.role === 'account-owner' ? '所有者' : member.role === 'account-admin' ? '管理员' : '成员' }
function loadCache() { try { const cached = JSON.parse(sessionStorage.getItem(CACHE_KEY) || 'null'); return cached?.time && Date.now() - cached.time < CACHE_TTL ? cached.data : null } catch { return null } }
function saveCache(value) { try { sessionStorage.setItem(CACHE_KEY, JSON.stringify({ data: value, time: Date.now() })) } catch {} }
async function fetchMembers() { loading.value = true; error.value = ''; try { const next = await api.getTeamMembers(); data.value = next; saveCache(next) } catch (e) { error.value = e?.message || '加载失败' } finally { loading.value = false } }
function requestRemove(member) { if (member.role !== 'account-owner') pendingMember.value = member }
function closeRemoveDialog() { if (!removingId.value) pendingMember.value = null }
async function confirmRemove() { const member = pendingMember.value; if (!member) return; removingId.value = memberKey(member); error.value = ''; try { await api.removeTeamMember({ email: member.email, user_id: member.user_id, type: member.type }); sessionStorage.removeItem(CACHE_KEY); pendingMember.value = null; await fetchMembers() } catch (e) { error.value = e?.message || '移出失败' } finally { removingId.value = '' } }
onMounted(() => { const cached = loadCache(); if (cached) data.value = cached; else void fetchMembers() })
</script>
