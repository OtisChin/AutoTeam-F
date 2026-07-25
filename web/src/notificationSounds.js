export const PAYPAL_LINK_SUCCESS_SOUND_URL = '/notification-sounds/universfield-game-bonus-02-294436.mp3'
export const LINK_SUCCESS_SOUND_URL = '/notification-sounds/freesound_community-bell-chord1-83260.mp3'

const activeAudios = new Set()
const audioBuffers = new Map()
const audioBufferPromises = new Map()

let audioContext = null
let notificationSoundUnlocked = false

function getAudioContext() {
  if (typeof window === 'undefined') return null
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext
  if (!AudioContextCtor) return null
  if (!audioContext) audioContext = new AudioContextCtor()
  return audioContext
}

async function resumeAudioContext(context) {
  if (context?.state === 'suspended' && typeof context.resume === 'function') {
    await context.resume()
  }
}

function playBuffer(context, buffer, volume = 0.9) {
  const source = context.createBufferSource()
  const gain = context.createGain()
  gain.gain.value = volume
  source.buffer = buffer
  source.connect(gain).connect(context.destination)
  source.start(0)
}

async function loadAudioBuffer(url) {
  if (audioBuffers.has(url)) return audioBuffers.get(url)
  if (audioBufferPromises.has(url)) return audioBufferPromises.get(url)

  const promise = (async () => {
    const context = getAudioContext()
    if (!context) throw new Error('当前浏览器不支持 Web Audio')
    const response = await fetch(url, { cache: 'force-cache' })
    if (!response.ok) throw new Error(`提示音加载失败: HTTP ${response.status}`)
    const arrayBuffer = await response.arrayBuffer()
    const buffer = await context.decodeAudioData(arrayBuffer)
    audioBuffers.set(url, buffer)
    audioBufferPromises.delete(url)
    return buffer
  })().catch((error) => {
    audioBufferPromises.delete(url)
    throw error
  })

  audioBufferPromises.set(url, promise)
  return promise
}

function playHtmlAudioFallback(url) {
  if (!url || typeof window === 'undefined' || typeof Audio === 'undefined') return
  const audio = new Audio(url)
  audio.preload = 'auto'
  audio.volume = 0.9
  activeAudios.add(audio)
  const cleanup = () => activeAudios.delete(audio)
  audio.addEventListener('ended', cleanup, { once: true })
  audio.addEventListener('error', cleanup, { once: true })
  const played = audio.play()
  if (played && typeof played.catch === 'function') played.catch(cleanup)
}

export function isNotificationSoundUnlocked() {
  return notificationSoundUnlocked
}

export async function preloadNotificationSounds() {
  await Promise.allSettled([
    loadAudioBuffer(PAYPAL_LINK_SUCCESS_SOUND_URL),
    loadAudioBuffer(LINK_SUCCESS_SOUND_URL),
  ])
}

export async function unlockNotificationSounds() {
  const context = getAudioContext()
  if (!context) throw new Error('当前浏览器不支持 Web Audio')

  await resumeAudioContext(context)
  const silentBuffer = context.createBuffer(1, 1, context.sampleRate)
  playBuffer(context, silentBuffer, 0.0001)
  notificationSoundUnlocked = true
  await preloadNotificationSounds()
  return true
}

export async function playNotificationSound(url, enabled = true) {
  if (!enabled || !url || typeof window === 'undefined') return
  try {
    const context = getAudioContext()
    if (context && notificationSoundUnlocked) {
      await resumeAudioContext(context)
      const buffer = await loadAudioBuffer(url)
      playBuffer(context, buffer, 0.9)
      return
    }
    playHtmlAudioFallback(url)
  } catch {
    // 提示音不可用时不影响任务流程。
    try {
      playHtmlAudioFallback(url)
    } catch {
      // ignore
    }
  }
}
