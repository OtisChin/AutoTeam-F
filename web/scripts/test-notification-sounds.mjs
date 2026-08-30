import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const startedSources = []

class FakeGain {
  constructor() {
    this.gain = { value: 1 }
  }

  connect(target) {
    return target
  }
}

class FakeBufferSource {
  constructor() {
    this.buffer = null
  }

  connect(target) {
    return target
  }

  start() {
    startedSources.push(this.buffer)
  }
}

class FakeAudioContext {
  constructor() {
    this.destination = {}
    this.sampleRate = 48000
    this.state = 'suspended'
  }

  async resume() {
    this.state = 'running'
  }

  createBuffer(numberOfChannels, length, sampleRate) {
    return { numberOfChannels, length, sampleRate, silent: true }
  }

  createBufferSource() {
    return new FakeBufferSource()
  }

  createGain() {
    return new FakeGain()
  }

  async decodeAudioData(arrayBuffer) {
    return { decoded: true, bytes: arrayBuffer.byteLength }
  }
}

globalThis.window = { AudioContext: FakeAudioContext }
globalThis.document = { hidden: true }
globalThis.fetch = async (url, options) => ({
  ok: true,
  status: 200,
  url,
  options,
  async arrayBuffer() {
    return new Uint8Array([1, 2, 3, 4]).buffer
  },
})

const {
  LINK_SUCCESS_SOUND_URL,
  PAYPAL_LINK_SUCCESS_SOUND_URL,
  isNotificationSoundUnlocked,
  playNotificationSound,
  unlockNotificationSounds,
} = await import('../src/notificationSounds.js')

assert.equal(isNotificationSoundUnlocked(), false)
await unlockNotificationSounds()
assert.equal(isNotificationSoundUnlocked(), true)
assert.ok(startedSources.length >= 1, 'unlock should start a silent buffer from a user gesture')

const beforePlayCount = startedSources.length
await playNotificationSound(PAYPAL_LINK_SUCCESS_SOUND_URL, true)
assert.equal(startedSources.length, beforePlayCount + 1, 'unlocked WebAudio should play even when document.hidden=true')

await playNotificationSound(LINK_SUCCESS_SOUND_URL, false)
assert.equal(startedSources.length, beforePlayCount + 1, 'disabled sound should not play')

const controlSource = await readFile(new URL('../src/components/NotificationSoundControl.vue', import.meta.url), 'utf8')
assert.match(controlSource, /role="switch"/, 'notification control should render as one switch')
assert.doesNotMatch(controlSource, /type="checkbox"/, 'notification control should not render a separate checkbox')
assert.match(controlSource, />\s*启用提示音\s*</, 'the merged switch should be labeled 启用提示音')
assert.doesNotMatch(controlSource, /需点击启用/, 'notification control should not show the old click-to-enable hint')
assert.doesNotMatch(controlSource, /已启用后台播放/, 'notification control should not show enabled background-play hint')

for (const pageName of ['MomoPage.vue', 'GCashPhPage.vue', 'KakaoPayPage.vue']) {
  const pageSource = await readFile(new URL(`../src/components/${pageName}`, import.meta.url), 'utf8')
  assert.match(pageSource, /const successNotificationTimers = new Set\(\)/, `${pageName} should own delayed success-sound timers`)
  assert.match(pageSource, /successNotificationTimers\.add\(timer\)/, `${pageName} should retain every delayed timer handle`)
  assert.match(pageSource, /successNotificationTimers\.delete\(timer\)/, `${pageName} should release fired timer handles`)
  assert.match(pageSource, /function clearSuccessNotificationTimers\(\)[\s\S]*?window\.clearTimeout\(timer\)/, `${pageName} should expose timer cleanup`)
  assert.match(pageSource, /onUnmounted\(\(\) => \{[\s\S]*?clearSuccessNotificationTimers\(\)/, `${pageName} should cancel delayed sounds during unmount`)
}

console.log('notification sound behavior passed')
