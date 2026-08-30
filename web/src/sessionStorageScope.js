export const SESSION_OWNER_KEY = 'autotoken_storage_session_owner_v1'
export const LOGGED_OUT_SESSION_OWNER = 'logged-out'

const SESSION_KEY_PREFIX = 'autotoken'
const PRESERVED_STORAGE_KEYS = new Set([
  'autotoken_api_key',
  'autotoken_current_page',
  'autotoken_task_panel_position',
])

function fallbackFingerprint(value) {
  const input = `autotoken-session-v1\u0000${value}`
  let left = 0xcbf29ce484222325n
  let right = 0x84222325cbf29ce4n
  const prime = 0x100000001b3n
  const mask = 0xffffffffffffffffn
  for (let index = 0; index < input.length; index += 1) {
    const code = BigInt(input.charCodeAt(index))
    left = ((left ^ code) * prime) & mask
    right = ((right ^ (code + BigInt(index + 1))) * prime) & mask
  }
  return `fallback:${left.toString(16).padStart(16, '0')}${right.toString(16).padStart(16, '0')}`
}

export async function storageSessionFingerprint(apiKey, { cryptoImpl = globalThis.crypto } = {}) {
  const identity = String(apiKey || '__anonymous__')
  if (cryptoImpl?.subtle && typeof TextEncoder === 'function') {
    try {
      const bytes = new TextEncoder().encode(`autotoken-session-v1\u0000${identity}`)
      const digest = await cryptoImpl.subtle.digest('SHA-256', bytes)
      const hex = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')
      return `sha256:${hex}`
    } catch {}
  }
  return fallbackFingerprint(identity)
}

function storageKeys(storage) {
  const keys = []
  for (let index = 0; index < Number(storage?.length || 0); index += 1) {
    const key = storage.key(index)
    if (typeof key === 'string') keys.push(key)
  }
  return keys
}

function clearSessionValues(storage) {
  for (const key of storageKeys(storage)) {
    if (!key.startsWith(SESSION_KEY_PREFIX)) continue
    if (key === SESSION_OWNER_KEY || PRESERVED_STORAGE_KEYS.has(key)) continue
    storage.removeItem(key)
  }
}

function storageOwnerFingerprint(owner) {
  const value = String(owner || '')
  const separator = value.indexOf('#')
  return separator === -1 ? value : value.slice(0, separator)
}

function createSessionNonce(cryptoImpl = globalThis.crypto) {
  try {
    if (typeof cryptoImpl?.randomUUID === 'function') return cryptoImpl.randomUUID()
    if (typeof cryptoImpl?.getRandomValues === 'function') {
      const values = new Uint32Array(4)
      cryptoImpl.getRandomValues(values)
      return [...values].map(value => value.toString(16).padStart(8, '0')).join('')
    }
  } catch {}
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`
}

export function createSessionStorageFacade({ storage = globalThis.localStorage } = {}) {
  let owner = null
  try {
    owner = storage.getItem(SESSION_OWNER_KEY)
  } catch {}

  function isCurrent() {
    try {
      return storage.getItem(SESSION_OWNER_KEY) === owner
    } catch {
      return false
    }
  }

  return {
    getItem(key) {
      if (!isCurrent()) return null
      try { return storage.getItem(key) } catch { return null }
    },
    setItem(key, value) {
      if (!isCurrent()) return false
      try {
        storage.setItem(key, value)
        return true
      } catch {
        return false
      }
    },
    removeItem(key) {
      if (!isCurrent()) return false
      try {
        storage.removeItem(key)
        return true
      } catch {
        return false
      }
    },
  }
}

export async function prepareStorageSession(apiKey, {
  storage = globalThis.localStorage,
  cryptoImpl = globalThis.crypto,
  rotate = false,
} = {}) {
  const fingerprint = await storageSessionFingerprint(apiKey, { cryptoImpl })
  try {
    const previous = storage.getItem(SESSION_OWNER_KEY)
    const reusable = Boolean(
      !rotate
      && previous
      && previous !== LOGGED_OUT_SESSION_OWNER
      && storageOwnerFingerprint(previous) === fingerprint
    )
    const changed = Boolean(previous && !reusable)
    if (changed) clearSessionValues(storage)
    const owner = reusable ? previous : `${fingerprint}#${createSessionNonce(cryptoImpl)}`
    storage.setItem(SESSION_OWNER_KEY, owner)
    return { changed, fingerprint, owner }
  } catch {
    return { changed: false, fingerprint, owner: '' }
  }
}

export function clearStorageSession({ storage = globalThis.localStorage } = {}) {
  try {
    clearSessionValues(storage)
    storage.setItem(SESSION_OWNER_KEY, LOGGED_OUT_SESSION_OWNER)
  } catch {}
}
