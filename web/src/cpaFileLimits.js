export const MAX_CPA_TO_SUB2API_FILES = 200
export const MAX_CPA_TO_SUB2API_BYTES = 10 * 1024 * 1024

function fileIdentity(file) {
  return String(file?.webkitRelativePath || file?.filename || file?.name || '').trim()
}

function measuredBytes(file) {
  const explicitSize = Number(file?.byteSize ?? file?.size)
  if (Number.isFinite(explicitSize) && explicitSize >= 0) return explicitSize
  return new TextEncoder().encode(String(file?.content || '')).byteLength
}

export function validateCpaFileSelection(existingFiles, incomingFiles) {
  const incomingByName = new Map()
  for (const file of incomingFiles || []) {
    const identity = fileIdentity(file)
    if (identity) incomingByName.set(identity, file)
  }
  const retained = (existingFiles || []).filter(file => !incomingByName.has(fileIdentity(file)))
  const uniqueIncoming = [...incomingByName.values()]
  const totalCount = retained.length + uniqueIncoming.length
  if (totalCount > MAX_CPA_TO_SUB2API_FILES) {
    return {
      ok: false,
      code: 'too_many_files',
      message: `CPA JSON 文件最多支持 ${MAX_CPA_TO_SUB2API_FILES} 个，当前选择后将达到 ${totalCount} 个。`,
      totalCount,
      totalBytes: 0,
      incomingFiles: uniqueIncoming,
    }
  }

  const totalBytes = [...retained, ...uniqueIncoming].reduce((sum, file) => sum + measuredBytes(file), 0)
  if (totalBytes > MAX_CPA_TO_SUB2API_BYTES) {
    return {
      ok: false,
      code: 'content_too_large',
      message: `CPA JSON 总内容最多支持 10MB，当前选择后约 ${(totalBytes / 1024 / 1024).toFixed(2)}MB。`,
      totalCount,
      totalBytes,
      incomingFiles: uniqueIncoming,
    }
  }

  return { ok: true, code: '', message: '', totalCount, totalBytes, incomingFiles: uniqueIncoming }
}
