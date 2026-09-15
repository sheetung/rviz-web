import assert from 'node:assert/strict'
import test from 'node:test'
import * as THREE from 'three'

import { FollowFrameTracker, TfBuffer, frameIdFromMessage, messageTimestampMs } from '../src/utils/tfBuffer.js'


const stampedTransform = ({ parent = 'map', child = 'base', seconds, x = 0, yaw = 0 }) => ({
  header: { frame_id: parent, stamp: { sec: seconds, nanosec: 0 } },
  child_frame_id: child,
  transform: {
    translation: { x, y: 0, z: 0 },
    rotation: { x: 0, y: 0, z: Math.sin(yaw / 2), w: Math.cos(yaw / 2) }
  }
})


const translation = matrix => new THREE.Vector3().setFromMatrixPosition(matrix)


test('extracts normalized frame IDs and ROS timestamps', () => {
  const message = { header: { frame_id: '/laser', stamp: { sec: 12, nanosec: 500_000_000 } } }
  assert.equal(frameIdFromMessage(message), 'laser')
  assert.equal(messageTimestampMs(message), 12_500)
})


test('interpolates translation at the message timestamp', () => {
  const buffer = new TfBuffer()
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 10, x: 0 })] })
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 12, x: 10 })] })

  const matrix = buffer.lookupTransform('map', 'base', 11_000)
  assert.ok(matrix)
  assert.ok(Math.abs(translation(matrix).x - 5) < 1e-9)
})


test('uses quaternion slerp for rotations', () => {
  const buffer = new TfBuffer()
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 10, yaw: 0 })] })
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 12, yaw: Math.PI })] })

  const matrix = buffer.lookupTransform('map', 'base', 11_000)
  const direction = new THREE.Vector3(1, 0, 0).transformDirection(matrix)
  assert.ok(Math.abs(direction.x) < 1e-9)
  assert.ok(Math.abs(Math.abs(direction.y) - 1) < 1e-9)
})


test('composes a transform chain using the same timestamp', () => {
  const buffer = new TfBuffer()
  buffer.updateMessage({ transforms: [stampedTransform({ parent: 'map', child: 'odom', seconds: 10, x: 2 })] })
  buffer.updateMessage({ transforms: [stampedTransform({ parent: 'odom', child: 'base', seconds: 10, x: 3 })] })

  const matrix = buffer.lookupTransform('map', 'base', 10_000)
  assert.ok(matrix)
  assert.ok(Math.abs(translation(matrix).x - 5) < 1e-9)
})


test('static transforms are valid for every message timestamp', () => {
  const buffer = new TfBuffer()
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 1, x: 4 })] }, true)

  assert.equal(translation(buffer.lookupTransform('map', 'base', 50_000)).x, 4)
})


test('prunes samples outside the configured history window', () => {
  const buffer = new TfBuffer({ historyDurationMs: 1_000, maxSamplesPerFrame: 10 })
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 1, x: 1 })] })
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 3, x: 3 })] })

  assert.equal(buffer.transforms.get('base').samples.length, 1)
  assert.equal(translation(buffer.lookupTransform('map', 'base', 1_000)).x, 3)
})


test('lists normalized parent and child frame IDs', () => {
  const buffer = new TfBuffer()
  buffer.updateMessage({ transforms: [
    stampedTransform({ parent: '/map', child: '/odom', seconds: 1 }),
    stampedTransform({ parent: 'odom', child: 'base', seconds: 1 })
  ] })

  assert.deepEqual(buffer.frameIds(), ['base', 'map', 'odom'])
})


test('clearing Follow Frame stops updates immediately and resets the baseline', () => {
  const buffer = new TfBuffer()
  const tracker = new FollowFrameTracker()
  tracker.setFrame('base')
  assert.equal(tracker.status, 'waiting')
  assert.equal(tracker.update(buffer, 'map'), null)
  assert.equal(tracker.status, 'waiting')
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 1, x: 1 })] })
  assert.equal(tracker.update(buffer, 'map'), null)
  assert.equal(tracker.status, 'tracking')
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 2, x: 2 })] })
  assert.equal(tracker.update(buffer, 'map').x, 1)
  tracker.setFrame('')
  assert.equal(tracker.status, 'disabled')
  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 3, x: 20 })] })
  assert.equal(tracker.update(buffer, 'map'), null)
  assert.equal(tracker.position, null)
  tracker.setFrame('base')
  assert.equal(tracker.update(buffer, 'map'), null)
})

test('follow frame tracker returns translation only and ignores rotation', () => {
  const buffer = new TfBuffer()
  const tracker = new FollowFrameTracker()
  tracker.setFrame('base')

  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 1, x: 2, yaw: 0 })] })
  assert.equal(tracker.update(buffer, 'map'), null)

  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 2, x: 2, yaw: Math.PI / 2 })] })
  assert.deepEqual(tracker.update(buffer, 'map').toArray(), [0, 0, 0])

  buffer.updateMessage({ transforms: [stampedTransform({ seconds: 3, x: 5, yaw: Math.PI })] })
  assert.deepEqual(tracker.update(buffer, 'map').toArray(), [3, 0, 0])
})
