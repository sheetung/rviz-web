import test from 'node:test'
import assert from 'node:assert/strict'

import {
  createApiBaseUrl,
  createWebSocketUrl
} from '../src/utils/websocketUrl.js'

test('websocket URL uses same-origin proxy by default', () => {
  assert.equal(
    createWebSocketUrl(
      {
        protocol: 'http:',
        hostname: '192.168.1.66',
        host: '192.168.1.66:3000'
      }
    ),
    'ws://192.168.1.66:3000/ws/v2/ros'
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
    'ws://localhost:3000/ws/v2/ros'
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
      'https://api.example/backend/management/'
    ),
    'https://api.example/backend/management/api/v1'
  )
})
