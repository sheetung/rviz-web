import assert from 'node:assert/strict'
import { createPinia, setActivePinia } from 'pinia'
import { appApi } from '../src/services/api.js'
import { useConnectionStore } from '../src/composables/useConnectionStore.js'

setActivePinia(createPinia())
const store = useConnectionStore()
const original = appApi.getSystemStatus
try {
  let calls = 0
  const metrics = { cpu_usage: 17.5, memory_usage: 42.1, cpu_temperature: null }
  appApi.getSystemStatus = async () => { calls++; return metrics }
  assert.deepEqual(await store.getSystemStatus(), metrics)
  assert.equal(calls, 1)
  assert.equal(store.websocket, null, 'Host metrics should not need a ROS WebSocket')
} finally {
  appApi.getSystemStatus = original
}
