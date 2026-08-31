/**
 * Small, dependency-free appearance controller shared by the shell and pages.
 * It only mutates the document root, so switching themes remains O(1) even for
 * large account tables.
 */
export const THEME_STORAGE_KEY = 'autotoken_theme'
export const THEME_PREFERENCES = Object.freeze(['system', 'light', 'dark'])
export const THEME_CONTROLLER_KEY = Symbol('autotoken-theme-controller')

const DARK_MEDIA_QUERY = '(prefers-color-scheme: dark)'
const THEME_COLORS = Object.freeze({ light: '#f5f5f7', dark: '#151517' })

export function normalizeThemePreference(value) {
  return THEME_PREFERENCES.includes(value) ? value : 'system'
}

export function resolveThemePreference(preference, systemDark = false) {
  const normalized = normalizeThemePreference(preference)
  return normalized === 'system' ? (systemDark ? 'dark' : 'light') : normalized
}

function globalValue(name) {
  try { return globalThis[name] || null } catch { return null }
}

function safeRead(storage) {
  try { return storage?.getItem?.(THEME_STORAGE_KEY) ?? null } catch { return null }
}

function safeWrite(storage, value) {
  try { storage?.setItem?.(THEME_STORAGE_KEY, value) } catch {}
}

function defaultMediaQueryList() {
  try { return globalValue('window')?.matchMedia?.(DARK_MEDIA_QUERY) || null } catch { return null }
}

function defaultThemeColorMeta() {
  try { return globalValue('document')?.querySelector?.('meta[name="theme-color"]') || null } catch { return null }
}

function subscribeMedia(media, listener) {
  if (typeof media?.addEventListener === 'function') {
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }
  if (typeof media?.addListener === 'function') {
    media.addListener(listener)
    return () => media.removeListener(listener)
  }
  return () => {}
}

function applyThemeState(root, themeColorMeta, preference, resolvedTheme) {
  if (root) {
    root.dataset.themePreference = preference
    root.dataset.theme = resolvedTheme
    if (root.style) root.style.colorScheme = resolvedTheme
  }
  if (themeColorMeta) {
    const color = THEME_COLORS[resolvedTheme]
    if ('content' in themeColorMeta) themeColorMeta.content = color
    else themeColorMeta.setAttribute?.('content', color)
  }
}

export function createThemeController(options = {}) {
  const browserDocument = globalValue('document')
  const browserWindow = globalValue('window')
  const root = options.root ?? browserDocument?.documentElement ?? null
  const storage = Object.prototype.hasOwnProperty.call(options, 'storage')
    ? options.storage
    : globalValue('localStorage')
  const mediaQueryList = Object.prototype.hasOwnProperty.call(options, 'mediaQueryList')
    ? options.mediaQueryList
    : defaultMediaQueryList()
  const eventTarget = Object.prototype.hasOwnProperty.call(options, 'eventTarget')
    ? options.eventTarget
    : browserWindow
  const themeColorMeta = Object.prototype.hasOwnProperty.call(options, 'themeColorMeta')
    ? options.themeColorMeta
    : defaultThemeColorMeta()
  const seed = options.initialPreference ?? root?.dataset?.themePreference ?? safeRead(storage)

  let preference = normalizeThemePreference(seed)
  let resolvedTheme = resolveThemePreference(preference, Boolean(mediaQueryList?.matches))
  let disposed = false
  const subscribers = new Set()
  const getSnapshot = () => ({ preference, resolvedTheme })

  function notify() {
    const snapshot = getSnapshot()
    for (const subscriber of subscribers) subscriber(snapshot)
  }

  function commit(nextPreference, persist) {
    if (disposed) return getSnapshot()
    const normalized = normalizeThemePreference(nextPreference)
    const nextResolved = resolveThemePreference(normalized, Boolean(mediaQueryList?.matches))
    const changed = normalized !== preference || nextResolved !== resolvedTheme
    preference = normalized
    resolvedTheme = nextResolved
    if (persist) safeWrite(storage, preference)
    applyThemeState(root, themeColorMeta, preference, resolvedTheme)
    if (changed) notify()
    return getSnapshot()
  }

  const handleSystemChange = () => {
    if (preference === 'system') commit(preference, false)
  }
  const handleStorageChange = event => {
    if (event?.key === THEME_STORAGE_KEY) commit(event.newValue, false)
  }

  const removeMediaListener = subscribeMedia(mediaQueryList, handleSystemChange)
  eventTarget?.addEventListener?.('storage', handleStorageChange)
  applyThemeState(root, themeColorMeta, preference, resolvedTheme)

  return {
    getSnapshot,
    setPreference(next) { return commit(next, true) },
    subscribe(listener) {
      if (typeof listener !== 'function' || disposed) return () => {}
      subscribers.add(listener)
      return () => subscribers.delete(listener)
    },
    dispose() {
      if (disposed) return
      disposed = true
      removeMediaListener()
      eventTarget?.removeEventListener?.('storage', handleStorageChange)
      subscribers.clear()
    },
  }
}
