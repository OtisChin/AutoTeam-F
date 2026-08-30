let generationSequence = 0
const startAckListeners = new Map()

function objectValue(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function readRoot(storage, storageKey) {
  try {
    return objectValue(JSON.parse(storage.getItem(storageKey) || '{}'))
  } catch {
    return {}
  }
}

function currentScope(root, scopeKey) {
  return scopeKey ? objectValue(root[scopeKey]) : objectValue(root)
}

function withoutGeneration(value) {
  const snapshot = { ...objectValue(value) }
  delete snapshot.startGeneration
  return snapshot
}

function writeRoot(storage, storageKey, root) {
  try {
    return storage.setItem(storageKey, JSON.stringify(root)) !== false
  } catch {
    return false
  }
}

function removeValue(storage, key) {
  try {
    return storage.removeItem(key) !== false
  } catch {
    return false
  }
}

function timestamp(value = Date.now()) {
  const resolved = typeof value === 'function' ? value() : value
  const numeric = Number(resolved)
  return Number.isFinite(numeric) && numeric > 0 ? numeric : Date.now()
}

function listenerKey(storageKey, scopeKey = '') {
  return `${storageKey}\u0000${scopeKey || '$root'}`
}

function notifyStartAck(storageKey, scopeKey, event) {
  const listeners = startAckListeners.get(listenerKey(storageKey, scopeKey))
  if (!listeners?.size) return
  for (const listener of [...listeners]) {
    try { listener(event) } catch {}
  }
}

export function startAckGenerationStorageKey(storageKey, scopeKey = '') {
  const scope = encodeURIComponent(scopeKey || '$root')
  return `${storageKey}:start-ack-generation:${scope}`
}

export function startAckCheckpointStorageKey(storageKey, scopeKey = '') {
  const scope = encodeURIComponent(scopeKey || '$root')
  return `${storageKey}:start-ack-checkpoint:${scope}`
}

function readGeneration(storage, generationStorageKey) {
  try {
    return String(storage.getItem(generationStorageKey) || '')
  } catch {
    return ''
  }
}

export function readStartAckCheckpoint({
  storage = globalThis.localStorage,
  storageKey,
  scopeKey = '',
} = {}) {
  if (!storageKey) return null
  const generation = readGeneration(storage, startAckGenerationStorageKey(storageKey, scopeKey))
  if (!generation) return null
  try {
    const raw = objectValue(JSON.parse(storage.getItem(startAckCheckpointStorageKey(storageKey, scopeKey)) || '{}'))
    if (raw.generation && String(raw.generation) !== generation) return null
    return {
      ...raw,
      version: Number(raw.version || 1),
      status: String(raw.status || 'starting'),
      generation,
      clientRequestId: String(raw.clientRequestId || generation),
      startedAt: Number(raw.startedAt || 0),
    }
  } catch {
    return {
      version: 1,
      status: 'starting',
      generation,
      clientRequestId: generation,
      startedAt: 0,
    }
  }
}

export function watchStartAckGeneration({
  storage = globalThis.localStorage,
  storageKey,
  scopeKey = '',
  onChange = () => {},
} = {}) {
  if (!storageKey || typeof onChange !== 'function') return { checkpoint: null, unsubscribe() {} }
  const key = listenerKey(storageKey, scopeKey)
  let listeners = startAckListeners.get(key)
  if (!listeners) {
    listeners = new Set()
    startAckListeners.set(key, listeners)
  }
  listeners.add(onChange)
  let active = true
  return {
    checkpoint: readStartAckCheckpoint({ storage, storageKey, scopeKey }),
    unsubscribe() {
      if (!active) return
      active = false
      listeners.delete(onChange)
      if (!listeners.size) startAckListeners.delete(key)
    },
  }
}

function nextGeneration() {
  generationSequence += 1
  try {
    if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  } catch {}
  return `${Date.now().toString(36)}-${generationSequence.toString(36)}-${Math.random().toString(36).slice(2)}`
}

export function reserveStartAckGeneration({
  storage = globalThis.localStorage,
  storageKey,
  scopeKey = '',
  generation = nextGeneration(),
  clientRequestId = `start-${generation}`,
  checkpoint = {},
  now = Date.now,
  supersede = false,
} = {}) {
  if (!storageKey) return null
  const existing = readStartAckCheckpoint({ storage, storageKey, scopeKey })
  if (existing && !supersede) {
    return {
      status: 'occupied',
      shouldContinue: false,
      checkpoint: existing,
      storage,
      storageKey,
      scopeKey,
    }
  }
  const generationStorageKey = startAckGenerationStorageKey(storageKey, scopeKey)
  const checkpointStorageKey = startAckCheckpointStorageKey(storageKey, scopeKey)
  const cleanGeneration = String(generation)
  const cleanClientRequestId = String(clientRequestId || cleanGeneration)
  const startingCheckpoint = {
    ...objectValue(checkpoint),
    version: 1,
    status: 'starting',
    generation: cleanGeneration,
    clientRequestId: cleanClientRequestId,
    startedAt: timestamp(now),
  }
  try {
    if (storage.setItem(generationStorageKey, cleanGeneration) === false) return null
    if (storage.setItem(checkpointStorageKey, JSON.stringify(startingCheckpoint)) === false) {
      removeValue(storage, generationStorageKey)
      return null
    }
  } catch {
    removeValue(storage, generationStorageKey)
    return null
  }
  return {
    status: 'reserved',
    storage,
    storageKey,
    scopeKey,
    generation: cleanGeneration,
    clientRequestId: cleanClientRequestId,
    checkpoint: startingCheckpoint,
    generationStorageKey,
    checkpointStorageKey,
  }
}

export function commitStartAckSnapshot(reservation, {
  componentUnmounted = false,
  createSnapshot = current => current,
} = {}) {
  if (!reservation) return { status: 'unavailable', shouldContinue: false, snapshot: null, root: null }
  if (reservation.status !== 'reserved') {
    return { status: reservation.status || 'unavailable', shouldContinue: false, snapshot: null, root: readRoot(reservation.storage, reservation.storageKey) }
  }
  const { storage, storageKey, scopeKey, generation, clientRequestId, generationStorageKey, checkpointStorageKey } = reservation
  const root = readRoot(storage, storageKey)
  const current = currentScope(root, scopeKey)
  if (readGeneration(storage, generationStorageKey) !== generation) {
    return { status: 'superseded', shouldContinue: false, snapshot: null, root }
  }
  const snapshot = objectValue(createSnapshot(withoutGeneration(current)))
  const nextRoot = scopeKey ? { ...root, [scopeKey]: snapshot } : snapshot
  if (!writeRoot(storage, storageKey, nextRoot)) {
    return { status: 'unavailable', shouldContinue: false, snapshot: null, root }
  }
  removeValue(storage, generationStorageKey)
  removeValue(storage, checkpointStorageKey)
  const result = {
    status: componentUnmounted ? 'persisted' : 'active',
    shouldContinue: !componentUnmounted,
    snapshot,
    root: nextRoot,
  }
  if (componentUnmounted) {
    notifyStartAck(storageKey, scopeKey, {
      type: 'acknowledged',
      generation,
      clientRequestId,
      snapshot,
      root: nextRoot,
    })
  }
  return result
}

export function markStartAckGenerationUnknown(reservation, {
  componentUnmounted = false,
  error = '',
  now = Date.now,
} = {}) {
  if (!reservation || reservation.status !== 'reserved') return { status: 'unavailable', root: null, checkpoint: null }
  const { storage, storageKey, scopeKey, generation, clientRequestId, generationStorageKey, checkpointStorageKey } = reservation
  const root = readRoot(storage, storageKey)
  if (readGeneration(storage, generationStorageKey) !== generation) return { status: 'superseded', root, checkpoint: null }
  const current = readStartAckCheckpoint({ storage, storageKey, scopeKey }) || reservation.checkpoint || {}
  const checkpoint = {
    ...current,
    version: 1,
    status: 'unknown',
    generation,
    clientRequestId,
    error: String(error || ''),
    updatedAt: timestamp(now),
  }
  try {
    if (storage.setItem(checkpointStorageKey, JSON.stringify(checkpoint)) === false) {
      return { status: 'unavailable', root, checkpoint: null }
    }
  } catch {
    return { status: 'unavailable', root, checkpoint: null }
  }
  if (componentUnmounted) {
    notifyStartAck(storageKey, scopeKey, { type: 'unknown', generation, clientRequestId, checkpoint, root })
  }
  return { status: 'unknown', root, checkpoint }
}

export function cancelStartAckGeneration(reservation, {
  componentUnmounted = false,
  error = '',
} = {}) {
  if (!reservation) return { status: 'unavailable', root: null }
  if (reservation.status !== 'reserved') return { status: reservation.status || 'unavailable', root: readRoot(reservation.storage, reservation.storageKey) }
  const { storage, storageKey, scopeKey, generation, clientRequestId, generationStorageKey, checkpointStorageKey } = reservation
  const root = readRoot(storage, storageKey)
  if (readGeneration(storage, generationStorageKey) !== generation) return { status: 'superseded', root }
  const removedGeneration = removeValue(storage, generationStorageKey)
  removeValue(storage, checkpointStorageKey)
  const status = removedGeneration ? 'cancelled' : 'unavailable'
  if (status === 'cancelled' && componentUnmounted) {
    notifyStartAck(storageKey, scopeKey, {
      type: 'cancelled',
      generation,
      clientRequestId,
      error: String(error || ''),
      root,
    })
  }
  return { status, root }
}
