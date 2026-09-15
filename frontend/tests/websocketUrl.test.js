import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createApiBaseUrl,
  createWebSocketUrl
} from '../src/utils/websocketUrl.js'

test('versioned ROS websocket selects the matching HTTP API including prefix', () => {
  const location = { protocol: 'https:', host: 'ui.example' }
  assert.equal(createApiBaseUrl(location, '', 'wss://robot.example/proxy/ws/ros1'),
    'https://robot.example/proxy/ros1/api/v1')
  assert.equal(createApiBaseUrl(location, '', 'wss://robot.example/ws/ros2'),
    'https://robot.example/ros2/api/v1')
  assert.equal(createApiBaseUrl(location, '', 'wss://robot.example/ws'),
    'https://robot.example/api/v1')
  assert.throws(() => createApiBaseUrl(location, 'https://other.example', 'wss://robot.example/ws/ros1'))
  assert.throws(() => createWebSocketUrl(location, 'ws://robot.example/ws'))
  assert.throws(() => createApiBaseUrl(location, '', 'wss://robot.example/ws/ros3'))
})

test('websocket URL uses same-origin proxy by default', () => {
  assert.equal(
    createWebSocketUrl(
      {
        protocol: 'http:',
        hostname: '192.168.1.66',
        host: '192.168.1.66:3000'
      }
    ),
    'ws://192.168.1.66:3000/ws'
  )
})

test('websocket URL uses the full configured ROS endpoint without appending a path', () => {
  assert.equal(
    createWebSocketUrl(
      {
        protocol: 'http:',
        hostname: 'localhost',
        host: 'localhost:3000'
      },
      'ws://192.168.1.66:8090/ws'
    ),
    'ws://192.168.1.66:8090/ws'
  )
})

test('websocket URL falls back to the page port when no backend port is injected', () => {
  assert.equal(
    createWebSocketUrl(
      {
        protocol: 'http:',
        hostname: 'localhost',
        host: 'localhost:3000'
      },
      ''
    ),
    'ws://localhost:3000/ws'
  )
})

test('API URL uses the same-origin proxy by default', () => {
  assert.equal(
    createApiBaseUrl({
      protocol: 'http:',
      host: 'robot.local:3000',
      origin: 'http://robot.local:3000'
    }),
    '/api/v1'
  )
})

test('API URL uses an explicitly configured backend URL', () => {
  assert.equal(
    createApiBaseUrl(
      {
        protocol: 'https:',
        host: 'ui.example',
        origin: 'https://ui.example'
      },
      'https://api.example/backend/'
    ),
    'https://api.example/backend/api/v1'
  )
})
