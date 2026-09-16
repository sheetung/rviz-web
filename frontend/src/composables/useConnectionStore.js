/**
 * ROS2 连接状态管理 Composable
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { debugLog } from '../utils/debug.js'
import { selectedBackend, backendSocketUrl, createRosTransport } from '../services/rosTransport.js'
import { appApi } from '../services/api.js'
import { systemMessage } from './useSystemMessage.js'

export const useConnectionStore = defineStore('connection', () => {
  // 连接状态
  const isConnected = ref(false)
  const isConnecting = ref(false)
  const connectionError = ref(null)
  const connectionLatency = ref(null)
  const websocket = ref(null)
  let latencyTimer = null
  let latencyMeasurementInFlight = null
  let reconnectTimer = null
  let handshakeTimer = null
  let intentionalDisconnect = false
  let socketGeneration = 0
  
  // 默认经当前页面同源代理连接；仅在独立部署后端时设置公开 URL。
  const browserLocation = typeof window === 'undefined' ? null : window.location
  const backendMode = selectedBackend()
  const capabilities = ref(null)
  const transport = createRosTransport(backendMode)
  const wsUrl = ref(backendSocketUrl(
    browserLocation, backendMode, import.meta.env?.ROS_WS_URL, import.meta.env?.VITE_ROS_V2_WS_URL
  ))
  const reconnectAttempts = ref(0)
  const reconnectInterval = ref(3000)
  
  // 订阅的主题
  const subscribedTopics = ref(new Set())
  const desiredSubscriptions = ref(new Map())
  const messageHandlers = ref(new Map())
  const subscriptionRequests = new Map()
  const confirmedSubscriptions = new Map()
  const publishingTopics = ref(new Map())
  
  // API调用的Promise管理
  const pendingRequests = ref(new Map())
  let requestIdCounter = 0
  
  // 计算属性
  const connectionStatus = computed(() => {
    if (isConnecting.value) return 'connecting'
    if (isConnected.value) return 'connected'
    if (connectionError.value) return 'error'
    return 'disconnected'
  })
  
  const connectionStatusText = computed(() => {
    switch (connectionStatus.value) {
      case 'connecting':
        return '连接中...'
      case 'connected':
        return '已连接'
      case 'error':
        return `连接错误: ${connectionError.value}`
      default:
        return '未连接'
    }
  })
  
  // 初始化连接
  const initializeConnection = async () => {
    if (isConnected.value || isConnecting.value) {
      return
    }
    
    await connect()
  }
  
  const clearHandshakeTimer = () => {
    if (handshakeTimer) clearTimeout(handshakeTimer)
    handshakeTimer = null
  }

  const endSocket = (socket, generation, reason) => {
    if (generation !== socketGeneration) return
    socketGeneration++
    clearHandshakeTimer()
    socket.onopen = socket.onmessage = socket.onclose = socket.onerror = null
    try { socket.close(1000, 'Connection ended') } catch { /* already closed */ }
    isConnected.value = false
    isConnecting.value = false
    websocket.value = null
    capabilities.value = null
    subscribedTopics.value.clear()
    confirmedSubscriptions.clear()
    subscriptionRequests.clear()
    advertisedTopics.value.clear()
    publishingTopics.value.clear()
    stopLatencyTracking()
    clearPendingRequests()
    if (!intentionalDisconnect) {
      connectionError.value = reason
      attemptReconnect()
    }
  }

  // A socket generation owns its requests and acknowledgements. Late events from
  // a replaced socket must never change the new connection's subscription state.
  const connect = async () => {
    if (isConnected.value || isConnecting.value) return
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = null
    const generation = ++socketGeneration
    intentionalDisconnect = false
    isConnecting.value = true
    connectionError.value = null
    try {
      const socket = new WebSocket(wsUrl.value)
      socket.binaryType = 'arraybuffer'
      websocket.value = socket
      handshakeTimer = setTimeout(() => endSocket(socket, generation, '连接握手超时'), 10000)
      const onReady = () => {
        if (generation !== socketGeneration) return
        clearHandshakeTimer()
        isConnected.value = true
        isConnecting.value = false
        reconnectAttempts.value = 0
        subscribedTopics.value.clear()
        confirmedSubscriptions.clear()
        subscriptionRequests.clear()
        advertisedTopics.value.clear()
        startLatencyTracking()
        desiredSubscriptions.value.forEach((_, topic) => requestSubscription(topic))
        systemMessage.success('已连接到 ROS 服务')
      }
      socket.onopen = () => { if (backendMode === 'v1') onReady() }
      socket.onmessage = event => {
        if (generation !== socketGeneration) return
        try {
          const message = transport.decode(event.data)
          if (!message) return
          if (isConnecting.value && backendMode === 'v2' &&
            (message.op !== 'connection_info' || message.protocol_version !== 2)) throw new Error('Invalid hello')
          handleMessage(message)
          if (backendMode === 'v2' && message.op === 'connection_info' && isConnecting.value) onReady()
        } catch (error) {
          console.error('[ConnectionStore] 协议消息无效:', error)
          if (isConnecting.value) {
            intentionalDisconnect = true
            connectionError.value = '后端 v2 协议握手失败'
            endSocket(socket, generation, connectionError.value)
          }
        }
      }
      socket.onclose = event => {
        if (event.code === 1008 && event.reason === 'middleware_mismatch') {
          if (generation !== socketGeneration) return
          intentionalDisconnect = true
          connectionError.value = '所选 ROS 版本与后端不匹配，请检查 ROS_WS_URL'
        }
        endSocket(socket, generation, `连接关闭 (${event.code})`)
      }
      socket.onerror = () => endSocket(socket, generation, '连接失败')
    } catch (error) {
      clearHandshakeTimer()
      isConnecting.value = false
      connectionError.value = error.message
      attemptReconnect()
    }
  }

  // 断开连接
  const disconnect = (preserveSubscriptions = false) => {
    clearHandshakeTimer()
    intentionalDisconnect = true
    socketGeneration++
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    stopLatencyTracking()
    if (websocket.value) {
      websocket.value.close(1000, 'Normal closure')
      websocket.value = null
    }
    isConnected.value = false
    isConnecting.value = false
    reconnectAttempts.value = 0
    connectionError.value = null
    subscribedTopics.value.clear()
    subscriptionRequests.clear()
    confirmedSubscriptions.clear()
    capabilities.value = null
    if (!preserveSubscriptions) {
      desiredSubscriptions.value.clear()
      messageHandlers.value.clear()
    }
    advertisedTopics.value.clear()  // 清理发布者声明
    clearPendingRequests()
    publishingTopics.value.clear()
  }
  
  const reconnect = () => {
    disconnect(true)
    return connect()
  }

  // 重连逻辑
  const attemptReconnect = () => {
    if (intentionalDisconnect || reconnectTimer) return

    reconnectAttempts.value++
    if (reconnectAttempts.value === 1) {
      systemMessage.warning('连接已断开，正在自动重连')
    }
    debugLog(`Attempting to reconnect (${reconnectAttempts.value})`)
    
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, reconnectInterval.value)
  }
  
  // 发送消息
  const sendMessage = (message) => {
    if (
      !isConnected.value ||
      !websocket.value ||
      websocket.value.readyState !== WebSocket.OPEN
    ) {
      console.warn('WebSocket not connected')
      return false
    }
    
    try {
      websocket.value.send(transport.encode(message))
      return true
    } catch (error) {
      console.error('Failed to send message:', error)
      return false
    }
  }
  
  // 处理接收到的消息
  const handleMessage = (message) => {
    const { op, topic, id } = message
    
    debugLog(`[ConnectionStore] 🔀 处理消息 - 操作: ${op}, 主题: ${topic || 'N/A'}`)

    // 根据操作类型处理消息
    switch (op) {
      case 'connection_info':
        capabilities.value = message.capabilities || null
        if (message.protocol_version !== (backendMode === 'v2' ? 2 : 1)) {
          connectionError.value = '后端协议版本不兼容'
          intentionalDisconnect = true
          websocket.value?.close(1008, 'protocol_mismatch')
        }
        break
      case 'publish':
        debugLog(`[ConnectionStore] 📢 发布消息到主题: ${topic}`)
        handleTopicMessage(topic, message.msg)
        break
      case 'get_topics_result':
        debugLog(`[ConnectionStore] 📋 收到主题列表，数量: ${(message.topics || []).length}`)
        resolveRequest(id, message.topics || [])
        break
      case 'get_nodes_result':
        debugLog(`[ConnectionStore] 🏢 收到节点列表，数量: ${(message.nodes || []).length}`)
        resolveRequest(id, message.nodes || [])
        break
      case 'get_topic_types_result':
        debugLog(`[ConnectionStore] 🏷️ 收到主题类型映射`)
        resolveRequest(id, message.topic_types || {})
        break
      case 'get_topic_frequencies_result':
        debugLog(`[ConnectionStore] 📊 收到主题频率信息`)
        resolveRequest(id, message.frequencies || {})
        break
      case 'get_system_status_result':
        resolveRequest(id, message.status || null)
        break
      case 'get_services_result':
        debugLog(`[ConnectionStore] 🔧 收到服务列表，数量: ${(message.services || []).length}`)
        resolveRequest(id, message.services || [])
        break
      case 'get_service_types_result':
        debugLog(`[ConnectionStore] 🔧 收到服务类型映射`)
        resolveRequest(id, message.service_types || {})
        break
      case 'get_params_result':
        debugLog(`[ConnectionStore] ⚙️ 收到参数列表，数量: ${(message.params || []).length}`)
        resolveRequest(id, message.params || [])
        break
      case 'pong':
        resolveRequest(id, true)
        break
      case 'subscribe_result':
      case 'unsubscribe_result':
      case 'advertise_result':
      case 'unadvertise_result':
      case 'publish_result':
        resolveRequest(id, message)
        break
      case 'error':
        console.error(`[ConnectionStore] ❌ 收到错误消息:`, message.error)
        rejectRequest(id, message.error || 'Unknown error', message.code)
        break
      default:
        console.warn(`[ConnectionStore] ⚠️ 未知的消息操作: ${op}`, message)
    }
  }
  
  // 生成请求ID
  const generateRequestId = () => {
    return `req_${++requestIdCounter}_${Date.now()}`
  }
  
  // 解决请求Promise
  const resolveRequest = (requestId, data) => {
    if (requestId && pendingRequests.value.has(requestId)) {
      const { resolve, timeoutId } = pendingRequests.value.get(requestId)
      clearTimeout(timeoutId)
      resolve(data)
      pendingRequests.value.delete(requestId)
    }
  }
  
  // 拒绝请求Promise
  const rejectRequest = (requestId, error, code) => {
    if (requestId && pendingRequests.value.has(requestId)) {
      const { reject, timeoutId } = pendingRequests.value.get(requestId)
      clearTimeout(timeoutId)
      reject(Object.assign(new Error(error), { code }))
      pendingRequests.value.delete(requestId)
    }
  }
  
  // 发送API请求并返回Promise
  const sendApiRequest = (operation, params = {}) => {
    return new Promise((resolve, reject) => {
      if (!isConnected.value) {
        reject(new Error('Not connected to ROS'))
        return
      }
      
      const requestId = generateRequestId()
      const message = {
        op: operation,
        id: requestId,
        ...params
      }
      
      if (!transport.supports(operation)) {
        reject(new Error(`v2 服务不支持 ${operation}`))
        return
      }

      // 设置超时
      const timeoutId = setTimeout(() => {
        if (pendingRequests.value.has(requestId)) {
          pendingRequests.value.delete(requestId)
          transport.forget(requestId)
          reject(Object.assign(new Error(operation === 'publish' ? '发布确认超时，结果未知；不会自动重发' : `Request timeout: ${operation}`), { code: operation === 'publish' ? 'submission_unknown' : 'timeout' }))
        }
      }, 10000) // 10秒超时

      // 存储 Promise 及其超时句柄
      pendingRequests.value.set(requestId, { resolve, reject, timeoutId, operation })
      
      if (!sendMessage(message)) {
        clearTimeout(timeoutId)
        pendingRequests.value.delete(requestId)
        transport.forget(requestId)
        reject(new Error(`Failed to send message: ${operation}`))
      }
    })
  }

  const measureLatency = async () => {
    if (!isConnected.value || latencyMeasurementInFlight) return

    const measurement = {}
    const generation = socketGeneration
    latencyMeasurementInFlight = measurement
    const startedAt = performance.now()
    try {
      await sendApiRequest('ping')
      if (generation !== socketGeneration) return
      connectionLatency.value = Math.max(0, Math.round(performance.now() - startedAt))
    } catch {
      if (generation === socketGeneration && websocket.value) endSocket(websocket.value, generation, '心跳超时')
    } finally {
      if (latencyMeasurementInFlight === measurement) latencyMeasurementInFlight = null
    }
  }

  const stopLatencyTracking = () => {
    if (latencyTimer) {
      clearInterval(latencyTimer)
      latencyTimer = null
    }
    latencyMeasurementInFlight = null
    connectionLatency.value = null
  }

  const startLatencyTracking = () => {
    stopLatencyTracking()
    measureLatency()
    latencyTimer = setInterval(measureLatency, 5000)
  }
  
  // 处理主题消息
  const handleTopicMessage = (topic, message) => {
    const handlers = messageHandlers.value.get(topic)

    // 减少详细日志输出，只保留关键信息
    debugLog(`[ConnectionStore] 🎯 处理主题消息: ${topic}`)

    if (handlers && handlers.size > 0) {
      let handlerIndex = 0
      handlers.forEach(handler => {
        try {
          handlerIndex++
          handler(message)
          // 只在出错时输出详细信息
        } catch (error) {
          console.error(`[ConnectionStore] - ❌ 处理器 #${handlerIndex} 执行失败:`, error)
          console.error(`[ConnectionStore] - 消息内容:`, message)
        }
      })
    } else {
      console.warn(`[ConnectionStore] ⚠️ 主题 ${topic} 没有注册处理器`)
      console.warn(`[ConnectionStore] - 所有已注册的处理器:`)
      messageHandlers.value.forEach((handlerSet, handlerTopic) => {
        console.warn(`  - ${handlerTopic}: ${handlerSet.size} handlers`)
      })
    }
  }
  
  // 清理待处理请求（连接关闭时）
  const clearPendingRequests = () => {
    pendingRequests.value.forEach(({ reject, timeoutId, operation }) => {
      clearTimeout(timeoutId)
      reject(Object.assign(new Error(operation === 'publish' ? '连接中断，发布结果未知；不会自动重发' : 'Connection closed'), { code: operation === 'publish' ? 'submission_unknown' : 'connection_closed' }))
    })
    pendingRequests.value.clear()
    transport.reset()
  }
  
  // Serialize reconciliation per topic, including unsubscribe/resubscribe races.
  const requestSubscription = async topic => {
    if (!isConnected.value || subscriptionRequests.has(topic)) return
    const token = {}
    const generation = socketGeneration
    subscriptionRequests.set(topic, token)
    try {
      while (generation === socketGeneration && isConnected.value) {
        const desired = desiredSubscriptions.value.get(topic)
        const confirmed = confirmedSubscriptions.get(topic)
        if (desired === confirmed) break
        if (confirmed) {
          await sendApiRequest('unsubscribe', { topic })
          if (generation !== socketGeneration) return
          confirmedSubscriptions.delete(topic)
          subscribedTopics.value.delete(topic)
        } else if (desired) {
          const result = await sendApiRequest('subscribe', { topic, type: desired.messageType, ...desired.options })
          if (generation !== socketGeneration) return
          if (!result?.success) throw new Error(`订阅 ${topic} 未被后端确认`)
          confirmedSubscriptions.set(topic, desired)
          subscribedTopics.value.add(topic)
        }
      }
    } catch (error) {
      if (generation === socketGeneration && isConnected.value) {
        systemMessage.error(`订阅 ${topic} 失败: ${error.message}`)
      }
    } finally {
      if (subscriptionRequests.get(topic) === token) subscriptionRequests.delete(topic)
    }
  }

  const subscribeTopic = (topic, messageType, handler, options = {}) => {
    const qos = { reliability: options.reliability || 'auto', durability: options.durability || 'auto' }
    const existing = desiredSubscriptions.value.get(topic)
    if (existing && (existing.messageType !== messageType || JSON.stringify(existing.options) !== JSON.stringify(qos))) {
      systemMessage.error(`话题 ${topic} 已使用不同类型或 QoS 订阅`)
      return false
    }
    if (!messageHandlers.value.has(topic)) messageHandlers.value.set(topic, new Set())
    messageHandlers.value.get(topic).add(handler)
    if (!existing) desiredSubscriptions.value.set(topic, { messageType, options: qos })
    requestSubscription(topic)
    return true
  }

  const unsubscribeTopic = (topic, handler) => {
    const handlers = messageHandlers.value.get(topic)
    if (!handlers) return
    handlers.delete(handler)
    if (!handlers.size) {
      messageHandlers.value.delete(topic)
      desiredSubscriptions.value.delete(topic)
      requestSubscription(topic)
    }
  }

  // 已声明的发布者
  const advertisedTopics = ref(new Set())

  // 声明发布者
  const advertise = async (topic, messageType) => {
    if (!isConnected.value) {
      console.warn('Not connected to ROS')
      throw new Error('Not connected to ROS')
    }

    if (advertisedTopics.value.has(topic)) {
      debugLog(`[ConnectionStore] 话题 ${topic} 已经声明过发布者`)
      return true
    }

    const result = await sendApiRequest('advertise', {
      topic: topic,
      type: messageType
    })

    if (result?.success) {
      advertisedTopics.value.add(topic)
      debugLog(`[ConnectionStore] ✅ 成功声明发布者: ${topic}`)
      return true
    }
    throw new Error(`后端未确认发布者声明: ${topic}`)
  }

  // 取消声明发布者
  const unadvertise = async (topic) => {
    if (!isConnected.value) {
      return false
    }

    debugLog(`[ConnectionStore] 取消声明发布者: ${topic}`)
    const result = await sendApiRequest('unadvertise', { topic })
    if (result?.success) {
      advertisedTopics.value.delete(topic)
      debugLog(`[ConnectionStore] ✅ 成功取消声明发布者: ${topic}`)
    }
    return result
  }

  // 发布消息到主题
  const publishMessage = async (topic, messageType, message) => {
    if (!isConnected.value) {
      console.warn('[ConnectionStore] Not connected to ROS')
      throw new Error('Not connected to ROS')
    }

    if (backendMode === 'v2' && !capabilities.value?.publish_types?.includes(messageType)) {
      throw new Error('当前后端不支持此类型的发布')
    }
    if (publishingTopics.value.has(topic)) throw new Error('此话题正在提交，请等待确认')
    const token = {}
    const generation = socketGeneration
    publishingTopics.value.set(topic, token)
    try {
      const result = await sendApiRequest('publish', { topic, type: messageType, msg: message })
      if (!result?.success || (backendMode === 'v2' && result.status !== 'submitted')) throw new Error(`后端未确认消息发布: ${topic}`)
      if (generation === socketGeneration) advertisedTopics.value.add(topic)
      return true
    } finally {
      // A late rejection from the old socket cannot clear a new submission.
      if (generation === socketGeneration) publishingTopics.value.delete(topic)
    }
  }
  
  // ROS API 方法 - 返回Promise
  
  // 获取主题列表
  const getTopics = async () => {
    try {
      const topics = await sendApiRequest('get_topics')
      debugLog('获取到主题列表:', topics)
      return backendMode === 'v2' ? topics.filter(topic => topic.supported !== false) : topics
    } catch (error) {
      console.error('获取主题列表失败:', error)
      return []
    }
  }
  
  // 获取节点列表
  const getNodes = async () => {
    if (!transport.supports('get_nodes')) return []
    try {
      const nodes = await sendApiRequest('get_nodes')
      debugLog('获取到节点列表:', nodes)
      return nodes
    } catch (error) {
      console.error('获取节点列表失败:', error)
      return []
    }
  }
  
  // 获取主题类型映射
  const getTopicTypes = async () => {
    try {
      const topicTypes = await sendApiRequest('get_topic_types')
      debugLog('获取到主题类型:', topicTypes)
      return topicTypes
    } catch (error) {
      console.error('获取主题类型失败:', error)
      return {}
    }
  }
  
  // 获取主题频率信息
  const getTopicFrequencies = async () => {
    if (!transport.supports('get_topic_frequencies')) return {}
    try {
      const frequencies = await sendApiRequest('get_topic_frequencies')
      debugLog('获取到主题频率:', frequencies)
      return frequencies
    } catch (error) {
      console.error('获取主题频率失败:', error)
      return {}
    }
  }
  
  // 获取系统状态
  const getSystemStatus = async () => {
    try {
      if (backendMode === 'v2') return await appApi.getSystemStatus()
      return await sendApiRequest('get_system_status')
    } catch (error) {
      console.error('获取系统状态失败:', error)
      return null
    }
  }

  // 获取服务列表
  const getServices = async () => {
    if (!transport.supports('get_services')) return []
    try {
      const services = await sendApiRequest('get_services')
      debugLog('获取到服务列表:', services)
      return services
    } catch (error) {
      console.error('获取服务列表失败:', error)
      return []
    }
  }
  
  // 获取服务类型映射
  const getServiceTypes = async () => {
    if (!transport.supports('get_service_types')) return {}
    try {
      const serviceTypes = await sendApiRequest('get_service_types')
      debugLog('获取到服务类型:', serviceTypes)
      return serviceTypes
    } catch (error) {
      console.error('获取服务类型失败:', error)
      return {}
    }
  }
  
  // 获取参数列表
  const getParams = async () => {
    if (!transport.supports('get_params')) return []
    try {
      const params = await sendApiRequest('get_params')
      debugLog('获取到参数列表:', params)
      return params
    } catch (error) {
      console.error('获取参数列表失败:', error)
      return []
    }
  }
  
  return {
    // 状态
    backendMode,
    capabilities,
    publishingTopics: computed(() => Array.from(publishingTopics.value.keys())),
    isConnected,
    isConnecting,
    connectionError,
    connectionLatency,
    connectionStatus,
    connectionStatusText,
    websocket,
    reconnectAttempts,
    subscribedTopics: computed(() => Array.from(subscribedTopics.value)),
    
    // 配置
    wsUrl,
    reconnectInterval,
    
    // 方法
    initializeConnection,
    connect,
    reconnect,
    disconnect,
    sendMessage,
    subscribeTopic,
    unsubscribeTopic,
    advertise,
    unadvertise,
    publishMessage,
    
    // ROS API方法
    getTopics,
    getNodes,
    getTopicTypes,
    getTopicFrequencies,
    getSystemStatus,
    getServices,
    getServiceTypes,
    getParams
  }
})
