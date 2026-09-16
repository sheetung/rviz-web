import { decodePointCloudBinaryFrame } from '../utils/pointCloudBinary.js'
import { createWebSocketUrl } from '../utils/websocketUrl.js'

// Production uses native v2; legacy codecs remain for archived v1 code.
export const selectedBackend = () => 'v2'

export const backendSocketUrl = (location, mode, v1Url = '', v2Url = '') =>
  createWebSocketUrl(location, mode === 'v2' ? (v2Url || '/ws/v2/ros') : v1Url)

const methods = {
  ping: 'ping',
  get_topics: 'topics.list',
  get_topic_types: 'topics.list',
  subscribe: 'topics.subscribe',
  unsubscribe: 'topics.unsubscribe',
  advertise: 'topics.advertise',
  unadvertise: 'topics.unadvertise',
  publish: 'topics.publish',
}

// Keep protocol differences at the transport boundary, outside visualization code.
export const createRosTransport = (mode = 'v1') => {
  const pending = new Map()
  return {
    supports(operation) { return mode === 'v1' || Object.hasOwn(methods, operation) },
    reset() { pending.clear() },
    forget(id) { pending.delete(id) },
    encode(message) {
      if (mode === 'v1') return JSON.stringify(message)
      if (!methods[message.op]) throw new Error(`v2 服务不支持 ${message.op}`)
      const { op, id, ...params } = message
      pending.set(id, op)
      return JSON.stringify({ version: 2, id, method: methods[op], params })
    },
    decode(data) {
      const message = typeof data === 'string' ? JSON.parse(data) : decodePointCloudBinaryFrame(data)
      if (mode === 'v1') return message
      if (message.version !== 2) throw new Error('后端协议版本不兼容')
      if (message.event === 'hello') return {
        op: 'connection_info', protocol_version: message.capabilities?.protocol_version,
        capabilities: message.capabilities,
      }
      if (message.event === 'topic.message' || message.op === 'publish') {
        return { op: 'publish', topic: message.topic, msg: message.display_snapshot ? { ...message.msg, _displaySnapshot: message.display_snapshot } : message.msg }
      }
      const operation = pending.get(message.id)
      pending.delete(message.id)
      if (!operation) return null
      if (!message.ok) return {
        op: 'error', id: message.id, code: message.error?.code,
        error: `${message.error?.code || 'request_failed'}: ${message.error?.message || '请求失败'}`,
      }
      const result = message.result || {}
      if (operation === 'get_topic_types') return {
        op: 'get_topic_types_result', id: message.id,
        topic_types: Object.fromEntries((result.topics || []).map(topic => [topic.name, topic.message_type])),
      }
      return { ...result, op: operation === 'ping' ? 'pong' : `${operation}_result`, id: message.id, success: true }
    },
  }
}
