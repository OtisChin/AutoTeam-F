const tone = (label, value) => ({ label, tone: value })
const normalize = value => String(value ?? '').toLowerCase()
const mapPresentation = (value, mappings, fallback = ['未知', 'neutral']) => {
  const key = normalize(value)
  const entry = mappings[key]
  return entry ? tone(entry[0], entry[1]) : tone(fallback[0], fallback[1])
}

export const taskStatusPresentation = value => mapPresentation(value, {
  pending: ['待执行', 'neutral'], running: ['执行中', 'warning'], completed: ['已完成', 'success'], failed: ['失败', 'danger'], cancelled: ['已取消', 'neutral'],
})
export const accountStatusPresentation = value => mapPresentation(value, {
  active: ['活跃', 'success'], session_only: ['仅会话', 'success'], standby: ['待机', 'warning'], orphan: ['孤立', 'warning'], exhausted: ['耗尽', 'danger'], auth_invalid: ['认证失效', 'danger'], auth_revoked: ['认证撤销', 'danger'], fail: ['失败', 'danger'], pending: ['待处理', 'neutral'], stashed: ['已暂存', 'neutral'],
})
export const accountTypePresentation = value => mapPresentation(value, { oauth: ['OAuth', 'info'], password: ['密码', 'neutral'], email: ['邮箱', 'neutral'], api: ['API', 'info'] })
export const bindProviderPresentation = value => mapPresentation(value, { google: ['Google', 'info'], github: ['GitHub', 'neutral'], microsoft: ['Microsoft', 'info'], apple: ['Apple', 'neutral'] })
export const mailAccountStatusPresentation = value => mapPresentation(value, { enabled: ['启用', 'success'], disabled: ['停用', 'neutral'] })
export const mailCheckStatusPresentation = value => mapPresentation(value, { valid: ['有效', 'success'], invalid: ['失效', 'danger'], error: ['错误', 'danger'], unchecked: ['未检查', 'neutral'] })
export const taskStatus = taskStatusPresentation
export const teamRolePresentation = value => mapPresentation(value, { owner: ['所有者', 'info'], admin: ['管理员', 'warning'], member: ['成员', 'neutral'], viewer: ['只读', 'neutral'] })
export const teamMemberTypePresentation = value => mapPresentation(value, { member: ['成员', 'success'], invite: ['待接受', 'warning'] })
export const oauthPhoneStatusPresentation = value => mapPresentation(value, { available: ['可用', 'success'], full: ['已满', 'info'], cooldown: ['冷却中', 'warning'], invalid: ['无效', 'danger'], disabled: ['停用', 'neutral'] })
export const oauthPhoneRecordStatusPresentation = value => {
  const key = normalize(value)
  if (key.startsWith('success')) return tone('成功', 'success')
  return mapPresentation(key, { acquired: ['已获取', 'info'], cancelled: ['已取消', 'warning'], released: ['已释放', 'warning'], failed: ['失败', 'danger'], invalid: ['无效', 'danger'], cooldown: ['冷却中', 'danger'] })
}

export const credentialExportPresentation = value => mapPresentation(Boolean(value) ? 'exported' : 'pending', { exported: ['已导出', 'success'], pending: ['未导出', 'neutral'] })
export const accountHubSyncPresentation = value => mapPresentation(Boolean(value) ? 'synced' : 'pending', { synced: ['已同步', 'success'], pending: ['未同步', 'neutral'] })

// Payment/workflow statuses intentionally return semantic tones rather than utility class names.
export const paypalStatusPresentation = value => mapPresentation(value, {
  pending: ['待处理', 'neutral'], queued: ['排队中', 'neutral'], running: ['进行中', 'info'], processing: ['处理中', 'info'],
  success: ['成功', 'success'], paid: ['已支付', 'success'], completed: ['已完成', 'success'],
  failed: ['失败', 'danger'], error: ['错误', 'danger'], cancelled: ['已取消', 'warning'],
  unknown: ['结果待核对', 'warning'], unknown_outcome: ['结果待核对', 'warning'], needs_action: ['需要操作', 'warning'],
})
export const workflowStatusPresentation = paypalStatusPresentation
