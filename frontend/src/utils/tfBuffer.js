import * as THREE from 'three'

const normalizeFrame = (frame = '') => String(frame).replace(/^\/+/, '')

const stampToMilliseconds = stamp => {
  if (!stamp) return null
  const seconds = Number(stamp.sec ?? 0)
  const nanoseconds = Number(stamp.nanosec ?? 0)
  if (!Number.isFinite(seconds) || !Number.isFinite(nanoseconds)) return null
  const milliseconds = seconds * 1000 + nanoseconds / 1e6
  return milliseconds > 0 ? milliseconds : null
}

const transformToMatrix = (transform = {}) => {
  const translation = transform.translation || {}
  const rotation = transform.rotation || {}
  const position = new THREE.Vector3(
    Number(translation.x ?? 0),
    Number(translation.y ?? 0),
    Number(translation.z ?? 0)
  )
  const quaternion = new THREE.Quaternion(
    Number(rotation.x ?? 0),
    Number(rotation.y ?? 0),
    Number(rotation.z ?? 0),
    Number(rotation.w ?? 1)
  ).normalize()
  return new THREE.Matrix4().compose(position, quaternion, new THREE.Vector3(1, 1, 1))
}

const interpolateMatrices = (from, to, ratio) => {
  const fromPosition = new THREE.Vector3()
  const fromRotation = new THREE.Quaternion()
  const toPosition = new THREE.Vector3()
  const toRotation = new THREE.Quaternion()
  from.decompose(fromPosition, fromRotation, new THREE.Vector3())
  to.decompose(toPosition, toRotation, new THREE.Vector3())
  return new THREE.Matrix4().compose(
    fromPosition.lerp(toPosition, ratio),
    fromRotation.slerp(toRotation, ratio),
    new THREE.Vector3(1, 1, 1)
  )
}

export class TfBuffer {
  constructor({ historyDurationMs = 10_000, maxSamplesPerFrame = 200 } = {}) {
    this.transforms = new Map()
    this.historyDurationMs = historyDurationMs
    this.maxSamplesPerFrame = maxSamplesPerFrame
  }

  updateMessage(message, isStatic = false) {
    const transforms = message?.transforms || []
    transforms.forEach(stamped => {
      const header = stamped.header || {}
      const parent = normalizeFrame(header.frame_id)
      const child = normalizeFrame(stamped.child_frame_id)
      const transform = stamped.transform
      if (!parent || !child || !transform || parent === child) return

      const timestamp = stampToMilliseconds(header.stamp) ?? Date.now()
      const existing = this.transforms.get(child)
      const entry = existing?.parent === parent && existing?.isStatic === isStatic
        ? existing
        : { parent, isStatic, samples: [] }
      const sample = { timestamp, matrix: transformToMatrix(transform) }

      if (isStatic) {
        entry.samples = [sample]
      } else {
        const duplicateIndex = entry.samples.findIndex(item => item.timestamp === timestamp)
        if (duplicateIndex >= 0) entry.samples[duplicateIndex] = sample
        else entry.samples.push(sample)
        entry.samples.sort((left, right) => left.timestamp - right.timestamp)

        const newestTimestamp = entry.samples.at(-1).timestamp
        const oldestAllowed = newestTimestamp - this.historyDurationMs
        entry.samples = entry.samples
          .filter(item => item.timestamp >= oldestAllowed)
          .slice(-this.maxSamplesPerFrame)
      }
      this.transforms.set(child, entry)
    })
  }

  matrixAt(entry, timestamp = null) {
    const samples = entry.samples
    if (!samples?.length) return null
    if (entry.isStatic || timestamp === null || !Number.isFinite(timestamp)) {
      return samples.at(-1).matrix.clone()
    }
    if (timestamp <= samples[0].timestamp) return samples[0].matrix.clone()
    if (timestamp >= samples.at(-1).timestamp) return samples.at(-1).matrix.clone()

    for (let index = 1; index < samples.length; index += 1) {
      const after = samples[index]
      if (after.timestamp < timestamp) continue
      const before = samples[index - 1]
      const duration = after.timestamp - before.timestamp
      if (duration <= 0) return after.matrix.clone()
      return interpolateMatrices(before.matrix, after.matrix, (timestamp - before.timestamp) / duration)
    }
    return samples.at(-1).matrix.clone()
  }

  lookupTransform(targetFrame, sourceFrame, timestamp = null) {
    const target = normalizeFrame(targetFrame)
    const source = normalizeFrame(sourceFrame)
    if (!target || !source) return null
    if (target === source) return new THREE.Matrix4()

    const adjacency = new Map()
    const addEdge = (from, to, matrix) => {
      if (!adjacency.has(from)) adjacency.set(from, [])
      adjacency.get(from).push({ frame: to, matrix })
    }
    this.transforms.forEach((entry, child) => {
      const matrix = this.matrixAt(entry, timestamp)
      if (!matrix) return
      addEdge(child, entry.parent, matrix)
      addEdge(entry.parent, child, matrix.clone().invert())
    })

    const queue = [{ frame: source, matrix: new THREE.Matrix4() }]
    const visited = new Set([source])
    while (queue.length > 0) {
      const current = queue.shift()
      for (const edge of adjacency.get(current.frame) || []) {
        if (visited.has(edge.frame)) continue
        const matrix = edge.matrix.clone().multiply(current.matrix)
        if (edge.frame === target) return matrix
        visited.add(edge.frame)
        queue.push({ frame: edge.frame, matrix })
      }
    }
    return null
  }

  frameIds() {
    const frames = new Set()
    this.transforms.forEach((entry, child) => {
      frames.add(child)
      frames.add(entry.parent)
    })
    return [...frames].sort((left, right) => left.localeCompare(right))
  }
}

export class FollowFrameTracker {
  constructor() {
    this.frameId = ''
    this.position = null
    this.status = 'disabled'
  }

  setFrame(frameId) {
    this.frameId = normalizeFrame(frameId)
    this.position = null
    this.status = this.frameId ? 'waiting' : 'disabled'
  }

  reset() {
    this.position = null
    this.status = this.frameId ? 'waiting' : 'disabled'
  }

  update(tfBuffer, fixedFrame) {
    if (!this.frameId) return null
    const transform = tfBuffer.lookupTransform(fixedFrame, this.frameId)
    if (!transform) {
      this.position = null
      this.status = 'waiting'
      return null
    }

    this.status = 'tracking'
    const nextPosition = new THREE.Vector3().setFromMatrixPosition(transform)
    if (!this.position) {
      this.position = nextPosition
      return null
    }

    const translation = nextPosition.clone().sub(this.position)
    this.position.copy(nextPosition)
    return translation
  }
}

export const frameIdFromMessage = message => {
  const header = message?.header || {}
  return normalizeFrame(header.frame_id)
}

export const messageTimestampMs = message => {
  const header = message?.header || {}
  return stampToMilliseconds(header.stamp)
}
