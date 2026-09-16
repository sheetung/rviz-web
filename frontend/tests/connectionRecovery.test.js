import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useConnectionStore } from '../src/composables/useConnectionStore.js'

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }

const harness = async run => {
  const names = ['WebSocket', 'setTimeout', 'clearTimeout', 'setInterval', 'clearInterval']
  const originals = Object.fromEntries(names.map(name => [name, globalThis[name]]))
  const sockets = [], timers = new Map()
  let next = 0
  class Socket {
    static OPEN = 1
    constructor() { this.readyState = 0; this.sent = []; this.closed = false; sockets.push(this) }
    send(text) { this.sent.push(JSON.parse(text)) }
    close() { this.closed = true; this.readyState = 3 }
    receive(value) { this.onmessage?.({ data: JSON.stringify(value) }) }
    ready() {
      this.readyState = 1
      this.receive({ version: 2, event: 'hello', capabilities: { protocol_version: 2, read_only: false,
        publish_types: ['geometry_msgs/msg/PoseStamped'] } })
      this.reply(this.last('ping'), { pong: true })
    }
    last(method) { return this.sent.filter(item => item.method === method).at(-1) }
    reply(request, result = {}) { this.receive({ version: 2, id: request.id, ok: true, result }) }
  }
  globalThis.WebSocket = Socket
  globalThis.setTimeout = (callback, delay) => { const id = ++next; timers.set(id, { callback, delay }); return id }
  globalThis.clearTimeout = id => timers.delete(id)
  globalThis.setInterval = () => ++next
  globalThis.clearInterval = () => {}
  const timer = delay => {
    const found = [...timers].find(([, value]) => value.delay === delay)
    assert.ok(found, `Missing ${delay}ms timer`)
    timers.delete(found[0]); found[1].callback()
  }
  setActivePinia(createPinia())
  const store = useConnectionStore()
  store.reconnectInterval = 25
  try { await run({ store, sockets, timers, timer }) }
  finally { store.disconnect(); await flush(); for (const name of names) globalThis[name] = originals[name] }
}

test('recovers desired subscriptions but never republishes a command after lost acknowledgement', () => harness(async ({ store, sockets, timer }) => {
  await store.connect(); const first = sockets[0]; first.ready(); await flush()
  const seen = []
  store.subscribeTopic('/points', 'sensor_msgs/msg/PointCloud2', message => seen.push(message), { reliability: 'reliable' })
  first.reply(first.last('topics.subscribe')); await flush()
  const pending = store.publishMessage('/goal_pose', 'geometry_msgs/msg/PoseStamped', { pose: {} }).catch(error => error)
  const command = first.last('topics.publish')
  const lateMessage = first.onmessage
  first.onclose({ code: 1006 }); await flush()
  assert.equal((await pending).code, 'submission_unknown')
  timer(25); const second = sockets[1]; second.ready(); await flush()
  assert.equal(second.last('topics.subscribe').params.reliability, 'reliable')
  assert.equal(second.sent.filter(m => ['topics.publish', 'topics.advertise'].includes(m.method)).length, 0)
  lateMessage({ data: JSON.stringify({ version: 2, id: command.id, ok: true, result: { status: 'submitted' } }) })
  second.reply(second.last('topics.subscribe')); await flush()
  second.receive({ version: 2, event: 'topic.message', topic: '/points', msg: { frame: 2 } })
  assert.deepEqual(seen, [{ frame: 2 }])
  assert.deepEqual(store.subscribedTopics, ['/points'])
}))

test('unsubscribe during subscribe and resubscribe during unsubscribe converge without leaking a topic', () => harness(async ({ store, sockets }) => {
  await store.connect(); const socket = sockets[0]; socket.ready(); await flush()
  const handler = () => {}
  store.subscribeTopic('/a', 'std_msgs/msg/Float64', handler)
  store.unsubscribeTopic('/a', handler)
  socket.reply(socket.last('topics.subscribe')); await flush()
  const unsubscribe = socket.last('topics.unsubscribe'); assert.ok(unsubscribe)
  store.subscribeTopic('/a', 'std_msgs/msg/Float64', handler)
  socket.reply(unsubscribe); await flush()
  assert.equal(socket.sent.filter(m => m.method === 'topics.subscribe').length, 2)
  socket.reply(socket.last('topics.subscribe')); await flush()
  assert.deepEqual(store.subscribedTopics, ['/a'])
  store.unsubscribeTopic('/a', handler)
  socket.reply(socket.last('topics.unsubscribe')); await flush()
  assert.deepEqual(store.subscribedTopics, [])
}))

test('old subscribe cleanup cannot delete the new generation request; manual reconnect retains callbacks', () => harness(async ({ store, sockets }) => {
  const handler = () => {}
  await store.connect(); sockets[0].ready(); await flush()
  store.subscribeTopic('/a', 'std_msgs/msg/Float64', handler)
  await store.reconnect(); sockets[1].ready(); await flush()
  store.subscribeTopic('/a', 'std_msgs/msg/Float64', handler)
  assert.equal(sockets[1].sent.filter(m => m.method === 'topics.subscribe').length, 1)
  sockets[1].reply(sockets[1].last('topics.subscribe')); await flush()
  assert.deepEqual(store.subscribedTopics, ['/a'])
}))

test('handshake and heartbeat timeouts close the old socket and schedule recovery', () => harness(async ({ store, sockets, timer }) => {
  await store.connect(); timer(10000)
  assert.ok(sockets[0].closed)
  timer(25)
  const socket = sockets[1]; socket.readyState = 1
  socket.receive({ version: 2, event: 'hello', capabilities: { protocol_version: 2 } })
  timer(10000); await flush()
  assert.ok(socket.closed)
  assert.equal(store.isConnected, false)
  timer(25); assert.equal(sockets.length, 3)
}))

test('publish waits for submitted acknowledgement and blocks a concurrent duplicate click', () => harness(async ({ store, sockets }) => {
  await store.connect(); const socket = sockets[0]; socket.ready(); await flush()
  const command = store.publishMessage('/goal_pose', 'geometry_msgs/msg/PoseStamped', {})
  await assert.rejects(store.publishMessage('/goal_pose', 'geometry_msgs/msg/PoseStamped', {}), /正在提交/)
  assert.equal(socket.sent.filter(m => m.method === 'topics.publish').length, 1)
  socket.reply(socket.last('topics.publish'), { status: 'submitted', execution: 'unknown' })
  assert.equal(await command, true)
  assert.deepEqual(store.publishingTopics, [])
}))
