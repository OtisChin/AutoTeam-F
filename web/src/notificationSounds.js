export const PAYPAL_LINK_SUCCESS_SOUND_URL = '/notification-sounds/universfield-game-bonus-02-294436.mp3'
export const LINK_SUCCESS_SOUND_URL = '/notification-sounds/freesound_community-bell-chord1-83260.mp3'

const activeAudios = new Set()

export function playNotificationSound(url, enabled = true) {
  if (!enabled || !url || typeof window === 'undefined' || typeof Audio === 'undefined') return
  try {
    const audio = new Audio(url)
    audio.preload = 'auto'
    audio.volume = 0.9
    activeAudios.add(audio)
    const cleanup = () => activeAudios.delete(audio)
    audio.addEventListener('ended', cleanup, { once: true })
    audio.addEventListener('error', cleanup, { once: true })
    const played = audio.play()
    if (played && typeof played.catch === 'function') played.catch(cleanup)
  } catch {
    // 提示音不可用时不影响任务流程。
  }
}
