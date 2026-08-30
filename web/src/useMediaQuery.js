import { onMounted, onUnmounted, readonly, ref } from 'vue'

export function useMediaQuery(query) {
  const matches = ref(false)
  let mediaQuery = null
  const update = event => { matches.value = Boolean(event?.matches ?? mediaQuery?.matches) }
  onMounted(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    try { mediaQuery = window.matchMedia(query) } catch { mediaQuery = null; return }
    update(mediaQuery)
    if (typeof mediaQuery.addEventListener === 'function') mediaQuery.addEventListener('change', update)
    else if (typeof mediaQuery.addListener === 'function') mediaQuery.addListener(update)
  })
  onUnmounted(() => {
    if (!mediaQuery) return
    if (typeof mediaQuery.removeEventListener === 'function') mediaQuery.removeEventListener('change', update)
    else if (typeof mediaQuery.removeListener === 'function') mediaQuery.removeListener(update)
    mediaQuery = null
  })
  return readonly(matches)
}
