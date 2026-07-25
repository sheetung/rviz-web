import test from 'node:test'
import assert from 'node:assert/strict'

import { createConfigFingerprint } from '../src/utils/configSnapshot.js'

test('config fingerprints ignore object key order', () => {
  const first = { fixedFrame: 'map', scene: { showGrid: true, showAxes: false } }
  const second = { scene: { showAxes: false, showGrid: true }, fixedFrame: 'map' }

  assert.equal(createConfigFingerprint(first), createConfigFingerprint(second))
})

test('config fingerprints detect nested setting changes', () => {
  const saved = { displays: [{ name: '/points', visible: true }] }
  const changed = { displays: [{ name: '/points', visible: false }] }

  assert.notEqual(createConfigFingerprint(saved), createConfigFingerprint(changed))
})

test('config fingerprints detect point cloud render style changes', () => {
  const points = {
    displays: [{ name: '/map', config: { renderStyle: 'points', pointSize: 0.03 } }]
  }
  const boxes = {
    displays: [{ name: '/map', config: { renderStyle: 'boxes', boxSize: 0.1 } }]
  }

  assert.notEqual(createConfigFingerprint(points), createConfigFingerprint(boxes))
})

test('config fingerprints detect point cloud sparse display changes', () => {
  const full = {
    displays: [{ name: '/points', config: { sparse: false, sampleStep: 4 } }]
  }
  const sparse = {
    displays: [{ name: '/points', config: { sparse: true, sampleStep: 8 } }]
  }

  assert.notEqual(createConfigFingerprint(full), createConfigFingerprint(sparse))
})

test('config fingerprints detect RTSP source and overlay layout changes', () => {
  const first = {
    video: {
      sourceUrl: 'rtsp://192.168.1.66:8554/1',
      visible: true,
      layout: { x: 20, y: 30, width: 360, height: 240 }
    }
  }
  const moved = {
    video: {
      sourceUrl: 'rtsp://192.168.1.66:8554/1',
      visible: true,
      layout: { x: 80, y: 30, width: 480, height: 300 }
    }
  }

  assert.notEqual(createConfigFingerprint(first), createConfigFingerprint(moved))
})

test('config fingerprints detect robot model visibility changes', () => {
  const hidden = { position: { odomTopic: '/odom', showRobotModel: false } }
  const visible = { position: { odomTopic: '/odom', showRobotModel: true } }

  assert.notEqual(createConfigFingerprint(hidden), createConfigFingerprint(visible))
})
