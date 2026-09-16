import assert from 'node:assert/strict'
import test from 'node:test'
import { selectedBackend, backendSocketUrl, createRosTransport } from '../src/services/rosTransport.js'

test('production always selects v2 and ignores legacy switching parameters', () => {
  const location = { protocol: 'https:', host: 'robot.local', search: '?backend=v2' }
  assert.equal(selectedBackend(location), 'v2')
  assert.equal(selectedBackend({ search: '' }), 'v2')
  assert.equal(backendSocketUrl(location, 'v2', '/ws/ros1'), 'wss://robot.local/ws/v2/ros')
  assert.equal(selectedBackend({ search: '?backend=v1' }, 'v1'), 'v2')
})

test('v2 maps requests and confirmations without changing component contracts', () => {
  const transport = createRosTransport('v2')
  assert.equal(JSON.parse(transport.encode({ op: 'subscribe', id: '1', topic: '/a', type: 'nav_msgs/msg/Odometry' })).method, 'topics.subscribe')
  assert.deepEqual(transport.decode(JSON.stringify({ version: 2, id: '1', ok: true, result: { topic: '/a' } })), { op: 'subscribe_result', id: '1', topic: '/a', success: true })
  transport.encode({ op: 'get_topic_types', id: '2' })
  assert.deepEqual(transport.decode(JSON.stringify({ version: 2, id: '2', ok: true, result: { topics: [{ name: '/a', message_type: 'nav_msgs/msg/Odometry' }] } })).topic_types, { '/a': 'nav_msgs/msg/Odometry' })
  assert.equal(JSON.parse(transport.encode({ op: 'publish', id: '3' })).method, 'topics.publish')
  assert.equal(transport.decode(JSON.stringify({ version: 2, id: '3', ok: true, result: { status: 'submitted', execution: 'unknown' } })).status, 'submitted')
})

test('v2 preserves explicit errors, rejects wrong versions and discards old responses', () => {
  const transport = createRosTransport('v2')
  transport.encode({ op: 'subscribe', id: '1' })
  const error = transport.decode(JSON.stringify({ version: 2, id: '1', ok: false, error: { code: 'unsupported_type', message: 'stage 1' } }))
  assert.equal(error.op, 'error')
  assert.match(error.error, /unsupported_type/)
  assert.throws(() => transport.decode('{"version":1}'), /协议版本/)
  transport.encode({ op: 'subscribe', id: '2' })
  transport.reset()
  assert.equal(transport.decode('{"version":2,"id":"2","ok":true}'), null)
})

test('v1 transport remains transparent', () => {
  const transport = createRosTransport('v1')
  const message = { op: 'publish', topic: '/a', msg: { data: 1 } }
  assert.deepEqual(transport.decode(transport.encode(message)), message)
})


test('marker snapshots preserve original fields for charts and full state for displays', () => {
  const transport = createRosTransport('v2')
  const snapshot = [{ action: 3 }, { id: 1, action: 0 }, { id: 2, action: 0 }]
  const event = transport.decode(JSON.stringify({ version: 2, event: 'topic.message', topic: '/markers',
    msg: { id: 2, pose: { position: { x: 4 } } }, display_snapshot: snapshot }))
  assert.equal(event.msg.pose.position.x, 4)
  assert.deepEqual(event.msg._displaySnapshot, snapshot)
})
